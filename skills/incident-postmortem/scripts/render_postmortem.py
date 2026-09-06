#!/usr/bin/env python3
"""Check a postmortem status-report for completeness and blaming
language, then render it as a markdown record.

Usage:
    render_postmortem.py <postmortem.json> --out-dir <dir> [--dry-run]

The input is a status-report (kit/shapes/status-report.schema.json)
the model composed in the Decide stage. This script does only what is
mechanical (SDS-S-060):

  1. validates the JSON against the family shape;
  2. checks the five required sections are present, by heading:
         Timeline, Impact, Contributing Factors, What Went Well,
         Action Items
     and that every Action Items line either carries an owner and a
     due date ("... — owner: <name>, due: YYYY-MM-DD") or the section
     body begins "No action items:" with a stated reason (an explicit
     empty case, SDS-C-033);
  3. scans every section for blaming phrases (see
     references/blameless-language.md) and reports them as warnings —
     never as a failure: whether a sentence is blame is the model's
     judgment; this only points at the sentences worth re-reading;
  4. renders <out-dir>/<YYYY-MM-DD>-<slug>.md (rung 4, local-write),
     the date taken from generatedFrom's first YYYY-MM-DD if present,
     else today.

`--dry-run` prints everything and writes nothing.

Prints a JSON object: {"path", "warnings": [...], "report": <input>}
(+ "rendered" with --dry-run). Exit 1 with "ERROR: ..." on stderr for:
an unreadable/malformed input (postmortem-unparseable); a document
failing the shape (postmortem-invalid); a missing required section or
an action item without owner/due (postmortem-incomplete); a missing
output directory (out-dir-missing). Requires the `jsonschema` package.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    sys.exit("ERROR: the jsonschema package is required (pip install jsonschema)")

REQUIRED = ["Timeline", "Impact", "Contributing Factors", "What Went Well", "Action Items"]
ACTION_RE = re.compile(r"owner:\s*\S+.*due:\s*\d{4}-\d{2}-\d{2}", re.I)
BLAME_PATTERNS = [
    (r"\b(failed|neglected|forgot) to\b", "assigns failure to a person; describe what the system allowed instead"),
    (r"\bshould have\b", "hindsight judgment; state what information was available at the time"),
    (r"\b(careless|negligent|incompetent|lazy|sloppy)\b", "character judgment; remove"),
    (r"\bhuman error\b", "names a person as the cause; ask what made the error easy to make"),
    (r"\b(his|her|their) (fault|mistake)\b", "attributes fault; describe the contributing condition"),
]


def family_root(start):
    for c in [start, *start.parents]:
        if (c / "kit").is_dir():
            return c
    return None


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "incident"


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")
    out_dir = None
    if "--out-dir" in args:
        i = args.index("--out-dir")
        if i + 1 >= len(args):
            sys.exit("ERROR: --out-dir requires a value")
        out_dir = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1 or out_dir is None:
        sys.exit("ERROR: usage: render_postmortem.py <postmortem.json> --out-dir <dir> [--dry-run]")

    try:
        report = json.loads(Path(args[0]).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load postmortem file {args[0]} (postmortem-unparseable): {e}")
    root = family_root(Path(__file__).resolve())
    if root is None:
        sys.exit("ERROR: could not locate the family root (a directory containing kit/) above this script")
    try:
        jsonschema.validate(report, json.loads((root / "kit/shapes/status-report.schema.json").read_text()))
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: status-report fails kit/shapes/status-report.schema.json (postmortem-invalid): {e.message}")
    if not out_dir.is_dir():
        sys.exit(f"ERROR: output directory does not exist (out-dir-missing): {out_dir}")

    sections = {s["heading"].strip().lower(): s["body"] for s in report["sections"]}
    missing = [h for h in REQUIRED if h.lower() not in sections]
    if missing:
        sys.exit(f"ERROR: postmortem lacks required section(s) (postmortem-incomplete): {', '.join(missing)}")
    actions = sections["action items"].strip()
    if actions.lower().startswith("no action items:"):
        if len(actions) <= len("no action items:") + 3:
            sys.exit("ERROR: 'No action items:' must state a reason (postmortem-incomplete)")
    else:
        lines = [l.strip() for l in actions.splitlines() if l.strip()]
        bad = [l for l in lines if not ACTION_RE.search(l)]
        if not lines or bad:
            sys.exit("ERROR: every action item needs '— owner: <name>, due: YYYY-MM-DD' (postmortem-incomplete): "
                     + (bad[0] if bad else "no items"))

    warnings = []
    for s in report["sections"]:
        for pat, why in BLAME_PATTERNS:
            for m in re.finditer(pat, s["body"], re.I):
                start = max(0, m.start() - 40)
                warnings.append({"section": s["heading"], "phrase": m.group(0),
                                 "context": s["body"][start:m.end() + 40].replace("\n", " "), "why": why})

    m = re.search(r"\d{4}-\d{2}-\d{2}", report.get("generatedFrom", ""))
    day = m.group(0) if m else date.today().isoformat()
    path = out_dir / f"{day}-{slugify(report['summary'])}.md"
    lines = [f"# Postmortem: {report['summary']}", "", f"- date: {day}", "- blameless: yes",
             f"- source: {report.get('generatedFrom', '(not stated)')}", ""]
    for s in report["sections"]:
        lines += [f"## {s['heading']}", "", s["body"].rstrip(), ""]
    rendered = "\n".join(lines)
    if not dry_run:
        path.write_text(rendered)
    out = {"path": str(path), "warnings": warnings, "report": report}
    if dry_run:
        out["rendered"] = rendered
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
