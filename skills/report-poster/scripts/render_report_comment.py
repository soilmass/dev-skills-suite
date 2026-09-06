#!/usr/bin/env python3
"""Render a family status-report as a pull-request or GitHub-issue comment.

Usage:
    render_report_comment.py <status-report.json> --target pr:<n>|issue:<n> [--marker <id>]

This is the deterministic part of report-poster's Gather stage
(SDS-S-060). The input is validated against
kit/shapes/status-report.schema.json, then rendered as markdown:

    ## <summary>

    ### <heading>

    <body>

    ...

    _Generated from: <generatedFrom>_
    <!-- sds-report: <id> -->

One `###` section per entry in `sections`, in order; the footer line
naming `generatedFrom` is included only when the report carries one;
the hidden marker comment is always the last line, so a later run of
this skill (or a human) can recognize a comment this skill already
posted. `--marker` defaults to the first 12 hex characters of
sha256(`generatedFrom` if present, else `summary`).

Prints one JSON object:
    {"target": {"kind": "pr"|"issue", "number": <n>},
     "marker": "<!-- sds-report: <id> -->",
     "body": "<markdown>"}

This script never calls `gh`; posting the comment is a direct, gated
tool call issued by the skill after Confirm (SDS-S-051).

Exit 1 with "ERROR: ..." on stderr for an input that is unreadable,
not JSON, or fails the shape (report-invalid), or a `--target` that
does not match `pr:<n>` or `issue:<n>` with `n >= 1`
(target-invalid). Requires the `jsonschema` package.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    sys.exit("ERROR: the jsonschema package is required (pip install jsonschema)")

TARGET_RE = re.compile(r"^(pr|issue):([1-9][0-9]*)$")


def load_report(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"ERROR: could not read {path} (report-invalid): {e}")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: {path} is not JSON (report-invalid): {e}")
    schema_path = Path(__file__).resolve().parents[3] / "kit" / "shapes" / "status-report.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: {path} fails kit/shapes/status-report.schema.json (report-invalid): {e.message}")
    return doc


def parse_target(spec):
    m = TARGET_RE.match(spec or "")
    if not m:
        sys.exit(f"ERROR: --target must match pr:<n> or issue:<n> with n >= 1 (target-invalid): {spec!r}")
    return {"kind": m.group(1), "number": int(m.group(2))}


def render_body(report, marker_line):
    lines = [f"## {report['summary']}"]
    for s in report.get("sections", []):
        lines.append("")
        lines.append(f"### {s['heading']}")
        lines.append("")
        lines.append(s["body"])
    if report.get("generatedFrom"):
        lines.append("")
        lines.append(f"_Generated from: {report['generatedFrom']}_")
    lines.append("")
    lines.append(marker_line)
    return "\n".join(lines)


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

    target_spec = take("--target")
    marker_id = take("--marker")
    if len(args) != 1:
        sys.exit("ERROR: usage: render_report_comment.py <status-report.json> --target pr:<n>|issue:<n> [--marker <id>]")

    report = load_report(args[0])
    target = parse_target(target_spec)

    if marker_id is None:
        basis = report.get("generatedFrom") or report["summary"]
        marker_id = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    marker_line = f"<!-- sds-report: {marker_id} -->"

    print(json.dumps({
        "target": target,
        "marker": marker_line,
        "body": render_body(report, marker_line),
    }, indent=2))


if __name__ == "__main__":
    main()
