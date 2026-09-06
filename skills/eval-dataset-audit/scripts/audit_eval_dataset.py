#!/usr/bin/env python3
"""Audit an eval set (a rows-of-input/expected-pairs dataset) for the
data-quality defects that quietly break an eval before any model is
called, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    audit_eval_dataset.py <file.jsonl|.json|.csv>
                           [--input-field input] [--expected-field expected]
                           [--near-duplicate-threshold 0.9]

Effect Ladder rung 1 (SDS-S-060): the one file named is read; nothing
is run and no model is called.

The dataset is read row by row: one JSON object per line for
`.jsonl`, one JSON array of objects for `.json` (row k's location is
line k+1, 1-based — an array has no native per-element line), and a
header-plus-data table for `.csv` (the header is line 1, so data row
k is line k+1). Anything else, or content that does not parse per its
suffix, is `dataset-invalid`; a path that is not a readable file
(missing, a directory, undecodable bytes) is `dataset-unreadable`.
`--input-field` and `--expected-field` (default `input`, `expected`)
name the two columns compared; either given empty is `field-invalid`.

A row missing either field (the key absent, or its value JSON `null`)
draws one `evals/missing-field` error, located at the row, up to the
first 20 such rows (`tool.properties.missingFieldTruncated` is `true`
past that point); such a row is excluded from every other rule below,
since there is nothing to compare.

Rules over the remaining rows:

    evals/duplicate-row    two or more rows share an identical input
                            after whitespace collapse -> warning, one
                            finding per group, located at the first
                            row, `rows` (all row numbers in the
                            group) and `count`
    evals/near-duplicate    two rows' inputs are not identical but
                            score >= --near-duplicate-threshold
                            (default 0.9) on Jaccard similarity of
                            their word 3-grams -> info, one finding
                            per pair, located at the earlier row,
                            `rows` (the pair) and `similarity`
                            (0-1, 3 decimals)
    evals/empty-expected    the expected value is empty or
                            whitespace-only -> error, located at the
                            row, `row`
    evals/label-imbalance   only when expected is categorical (at
                            most 20 distinct values after whitespace
                            collapse, each at most 40 characters) and
                            the largest class is more than 70% of
                            rows -> warning, one finding located at
                            the file, `classes`, `largestClass`,
                            `largestClassShare`
    evals/leak-suspect      the expected value, 4 or more characters
                            after strip, appears verbatim inside that
                            row's own input -> warning, located at
                            the row, `row`

`tool.properties` carries `rows` (total rows read, including any
excluded for a missing field), `fields` (`[input-field,
expected-field]`), `classes` and `largestClassShare` (the categorical
stats when expected is categorical, else both `null` — independent of
whether label-imbalance actually fired), `duplicates` and
`nearDuplicates` (finding counts for those two rules), and
`missingFieldTruncated`.

Prints one finding-list; a dataset with none of the above yields a
well-formed, zero-entry `results` array (SDS-C-033). Exit 1 with
"ERROR: ..." on stderr for a field name that is empty
(field-invalid), a path that is not a readable file
(dataset-unreadable), or a form that is unsupported or does not parse
(dataset-invalid).
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2, "hint": 3}
MISSING_FIELD_CAP = 20


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line is not None:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def collapse_ws(text):
    return " ".join(text.split())


def word_ngrams(text, n=3):
    words = text.split()
    if not words:
        return set()
    if len(words) < n:
        return {tuple(words)}
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a, b):
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def load_jsonl(path):
    rows = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: {path} line {lineno} is not valid JSON (dataset-invalid): {e}")
        if not isinstance(obj, dict):
            sys.exit(f"ERROR: {path} line {lineno} is not a JSON object (dataset-invalid)")
        rows.append((lineno, obj))
    return rows


def load_json(path):
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: {path} is not valid JSON (dataset-invalid): {e}")
    if not isinstance(data, list):
        sys.exit(f"ERROR: {path} is not a JSON array of row objects (dataset-invalid)")
    rows = []
    for idx, obj in enumerate(data, start=1):
        if not isinstance(obj, dict):
            sys.exit(f"ERROR: {path} row {idx} is not a JSON object (dataset-invalid)")
        rows.append((idx, obj))
    return rows


def load_csv(path):
    text = path.read_text(encoding="utf-8")
    try:
        reader = csv.DictReader(text.splitlines())
        fieldnames = reader.fieldnames
        if not fieldnames:
            sys.exit(f"ERROR: {path} has no header row (dataset-invalid)")
        rows = []
        for i, obj in enumerate(reader, start=1):
            rows.append((i + 1, dict(obj)))
    except csv.Error as e:
        sys.exit(f"ERROR: {path} is not valid CSV (dataset-invalid): {e}")
    return rows


LOADERS = {".jsonl": load_jsonl, ".json": load_json, ".csv": load_csv}


def main():
    args = sys.argv[1:]
    opts = {"--input-field": "input", "--expected-field": "expected", "--near-duplicate-threshold": "0.9"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: audit_eval_dataset.py <file.jsonl|.json|.csv> [--input-field F] [--expected-field F] [--near-duplicate-threshold N]")

    input_field, expected_field = opts["--input-field"], opts["--expected-field"]
    if not input_field.strip() or not expected_field.strip():
        sys.exit(f"ERROR: --input-field and --expected-field must be non-empty (field-invalid): {input_field!r}, {expected_field!r}")

    try:
        threshold = float(opts["--near-duplicate-threshold"])
    except ValueError:
        sys.exit(f"ERROR: --near-duplicate-threshold must be a number: {opts['--near-duplicate-threshold']!r}")

    path = Path(args[0])
    if not path.is_file():
        sys.exit(f"ERROR: not a readable file (dataset-unreadable): {path}")

    suffix = path.suffix.lower()
    loader = LOADERS.get(suffix)
    if loader is None:
        sys.exit(f"ERROR: {path} has an unsupported suffix {suffix!r}; expected .jsonl, .json, or .csv (dataset-invalid)")

    try:
        rows = loader(path)
    except UnicodeDecodeError as e:
        sys.exit(f"ERROR: {path} is not readable as UTF-8 text (dataset-unreadable): {e}")
    except OSError as e:
        sys.exit(f"ERROR: cannot read {path} (dataset-unreadable): {e}")

    uri = path.as_posix()
    total_rows = len(rows)

    missing_findings = []
    missing_count = 0
    valid_rows = []  # (line, input_str, expected_str)
    for line, obj in rows:
        has_input = input_field in obj and obj[input_field] is not None
        has_expected = expected_field in obj and obj[expected_field] is not None
        if not (has_input and has_expected):
            missing_count += 1
            if missing_count <= MISSING_FIELD_CAP:
                missing = [f for f, present in ((input_field, has_input), (expected_field, has_expected)) if not present]
                missing_findings.append(finding(
                    "evals/missing-field", "error",
                    f"row {line} is missing {', '.join(repr(m) for m in missing)}",
                    uri, line, {"row": line, "fields": missing},
                ))
            continue
        valid_rows.append((line, str(obj[input_field]), str(obj[expected_field])))
    missing_field_truncated = missing_count > MISSING_FIELD_CAP

    # evals/duplicate-row
    groups = defaultdict(list)
    for line, inp, _ in valid_rows:
        groups[collapse_ws(inp)].append(line)
    duplicate_findings = []
    for key, lines in groups.items():
        if len(lines) >= 2:
            lines_sorted = sorted(lines)
            duplicate_findings.append(finding(
                "evals/duplicate-row", "warning",
                f"{len(lines_sorted)} rows share identical input after whitespace collapse: rows {lines_sorted}",
                uri, lines_sorted[0], {"rows": lines_sorted, "count": len(lines_sorted)},
            ))

    # evals/near-duplicate (pairs whose collapsed input differs but scores high)
    near_duplicate_findings = []
    grams = [word_ngrams(collapse_ws(inp).lower()) for _, inp, _ in valid_rows]
    collapsed = [collapse_ws(inp) for _, inp, _ in valid_rows]
    for i in range(len(valid_rows)):
        for j in range(i + 1, len(valid_rows)):
            if collapsed[i] == collapsed[j]:
                continue  # exact duplicate, already covered above
            sim = jaccard(grams[i], grams[j])
            if sim >= threshold:
                li, lj = valid_rows[i][0], valid_rows[j][0]
                pair = sorted([li, lj])
                near_duplicate_findings.append(finding(
                    "evals/near-duplicate", "info",
                    f"rows {pair} are near-duplicates (jaccard {round(sim, 3)} >= {threshold})",
                    uri, pair[0], {"rows": pair, "similarity": round(sim, 3)},
                ))

    # evals/empty-expected
    empty_expected_findings = []
    for line, _, exp in valid_rows:
        if exp.strip() == "":
            empty_expected_findings.append(finding(
                "evals/empty-expected", "error",
                f"row {line} has an empty (or whitespace-only) expected value",
                uri, line, {"row": line},
            ))

    # evals/leak-suspect
    leak_findings = []
    for line, inp, exp in valid_rows:
        stripped = exp.strip()
        if len(stripped) >= 4 and stripped in inp:
            leak_findings.append(finding(
                "evals/leak-suspect", "warning",
                f"row {line}'s expected value appears verbatim inside its own input",
                uri, line, {"row": line},
            ))

    # evals/label-imbalance
    label_imbalance_findings = []
    classes, largest_class_share = None, None
    n_valid = len(valid_rows)
    if n_valid:
        class_counts = Counter(collapse_ws(exp) for _, _, exp in valid_rows)
        categorical = len(class_counts) <= 20 and all(len(c) <= 40 for c in class_counts)
        if categorical:
            largest_class, largest_count = class_counts.most_common(1)[0]
            classes = len(class_counts)
            largest_class_share = round(largest_count / n_valid, 3)
            if largest_class_share > 0.7:
                label_imbalance_findings.append(finding(
                    "evals/label-imbalance", "warning",
                    f"expected is categorical ({classes} classes) and {largest_class!r} is {largest_class_share:.1%} of rows",
                    uri, None, {"classes": classes, "largestClass": largest_class, "largestClassShare": largest_class_share},
                ))

    out = missing_findings + duplicate_findings + near_duplicate_findings + empty_expected_findings + label_imbalance_findings + leak_findings
    out.sort(key=lambda r: (
        LEVEL_ORDER[r["level"]],
        r["ruleId"],
        r["locations"][0]["physicalLocation"].get("region", {}).get("startLine", 0),
        json.dumps(r["properties"], sort_keys=True),
    ))

    print(json.dumps({
        "version": "sds-finding-list-1.0",
        "runs": [{
            "tool": {
                "driver": {"name": "eval-dataset-audit", "version": "0.1.0"},
                "properties": {
                    "rows": total_rows,
                    "fields": [input_field, expected_field],
                    "classes": classes,
                    "largestClassShare": largest_class_share,
                    "duplicates": len(duplicate_findings),
                    "nearDuplicates": len(near_duplicate_findings),
                    "missingFieldTruncated": missing_field_truncated,
                },
            },
            "results": out,
        }],
    }, indent=2))


if __name__ == "__main__":
    main()
