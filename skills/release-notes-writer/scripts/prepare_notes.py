#!/usr/bin/env python3
"""Prepare a changelog status-report for a user-facing audience.

Usage:
    prepare_notes.py <report.json> [--product <name>] [--version <x.y.z>]

The input is the status-report changelog-writer produces (Keep a
Changelog categories, commit hashes in parentheses, `**BREAKING:**`
prefixes, an optional Uncategorized section). This script does only
what is mechanical (SDS-S-060) and leaves the rewriting — plain
language, why a change matters, what a user must do — to the skill's
Synthesize stage:

    1. validates the input against kit/shapes/status-report.schema.json;
    2. strips trailing commit hashes "(abc1234)" and scope labels
       "scope: " from every line;
    3. moves every `**BREAKING:**` line, prefix removed, into a leading
       "Breaking changes" section;
    4. orders sections by user impact: Breaking changes, Security,
       Added, Changed, Fixed, Deprecated, Removed;
    5. removes the Uncategorized section from the notes and reports its
       lines in `needsReview` — unclassified commits are never
       published as-is;
    6. rewrites the summary as "<product> <version>: <counts>".

The transformation is idempotent by construction (SDS-C-017, checked
by the fixed-point eval row): applying it to its own output changes
nothing, because stripped hashes, moved breaking lines, and the fixed
order are all fixed points.

Prints a status-report (same shape in and out) with an extra
`needsReview` array. An input with no sections yields a well-formed
report with no sections (SDS-C-033). Exit 1 with "ERROR: ..." on
stderr for an unreadable/malformed input (report-unparseable) or one
failing the shape (report-invalid). Requires the `jsonschema` package.
"""
import json
import re
import sys
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    sys.exit("ERROR: the jsonschema package is required (pip install jsonschema)")

ORDER = ["Breaking changes", "Security", "Added", "Changed", "Fixed", "Deprecated", "Removed"]
HASH_RE = re.compile(r"\s*\([0-9a-f]{7,40}(?:,\s*[0-9a-f]{7,40})*\)\s*$")
SCOPE_RE = re.compile(r"^- ([a-z0-9_./-]+): ")
BREAK_RE = re.compile(r"^- \*\*BREAKING:\*\*\s*")


def family_root(start):
    for c in [start, *start.parents]:
        if (c / "kit").is_dir():
            return c
    return None


def clean(line):
    line = HASH_RE.sub("", line.rstrip())
    line = SCOPE_RE.sub("- ", line)
    return line


def prepare(report, product, version):
    buckets = {k: [] for k in ORDER}
    # An input that is already prepared carries its withheld lines in
    # needsReview rather than an Uncategorized section; keep them, or the
    # transformation would not be a fixed point (the eval row for
    # SDS-S-094 caught exactly this).
    needs_review = list(report.get("needsReview", []))
    for s in report["sections"]:
        heading = s["heading"].strip()
        for raw in s["body"].splitlines():
            if not raw.strip():
                continue
            line = clean(raw)
            if heading == "Uncategorized":
                needs_review.append(line)
                continue
            if BREAK_RE.match(line):
                buckets["Breaking changes"].append(BREAK_RE.sub("- ", line))
                continue
            if heading == "Breaking changes":
                buckets["Breaking changes"].append(line)
                continue
            buckets.setdefault(heading, []).append(line)
    sections = [{"heading": k, "body": "\n".join(buckets[k])} for k in ORDER if buckets.get(k)]
    for k in buckets:
        if k not in ORDER and buckets[k]:
            sections.append({"heading": k, "body": "\n".join(buckets[k])})
    counts = ", ".join(f"{len(buckets[k])} {k.lower()}" for k in ORDER if buckets.get(k))
    label = " ".join(x for x in (product, version) if x)
    summary = f"{label}: {counts}" if label else (counts or "no user-facing changes")
    if not counts:
        summary = f"{label}: no user-facing changes" if label else "no user-facing changes"
    return {
        "summary": summary,
        "sections": sections,
        "generatedFrom": report.get("generatedFrom", "changelog status-report"),
        "needsReview": needs_review,
    }


def main():
    args = sys.argv[1:]
    def take(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return None
    product = take("--product")
    version = take("--version")
    if len(args) != 1:
        sys.exit("ERROR: usage: prepare_notes.py <report.json> [--product <name>] [--version <x.y.z>]")
    try:
        report = json.loads(Path(args[0]).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load report {args[0]} (report-unparseable): {e}")
    root = family_root(Path(__file__).resolve())
    if root is None:
        sys.exit("ERROR: could not locate the family root (a directory containing kit/) above this script")
    schema = json.loads((root / "kit/shapes/status-report.schema.json").read_text())
    try:
        jsonschema.validate(report, schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: report fails kit/shapes/status-report.schema.json (report-invalid): {e.message}")

    out = prepare(report, product, version)
    jsonschema.validate(out, schema)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
