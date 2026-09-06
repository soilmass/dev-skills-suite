#!/usr/bin/env python3
"""Check a runbook specification for completeness and render it.

Usage:
    render_runbook.py <runbook.json> --out-dir <dir> [--dry-run]

The input conforms to assets/runbook.schema.json, this skill's own
intermediate shape (SDS-S-080): title, purpose, trigger,
preconditions[], steps[{do, verify, ifFails}], rollback,
escalation{who, when}, optional lastVerified. The model composes it in
the Decide stage; this script does only what is mechanical
(SDS-S-060):

  1. validates the JSON against the asset schema;
  2. refuses (runbook-incomplete) any step whose `verify` or `ifFails`
     is blank — a step that cannot be checked is not an instruction,
     it is a hope — and an escalation with no `who`;
  3. warns (never fails) when a step's `do` contains no fenced or
     backticked command (it may be prose that hides a command), and
     when `lastVerified` is absent (the runbook has never been walked
     through end to end);
  4. renders <out-dir>/<slug>.md with numbered steps in Do / Verify /
     If it fails form (rung 4, local-write).

`--dry-run` prints everything and writes nothing. Output:
{"path", "warnings", "steps", "rendered"?}. Exit 1 with "ERROR: ..."
on stderr for an unreadable/malformed input (runbook-unparseable), a
spec failing the shape (runbook-invalid), an unverifiable step or
missing escalation (runbook-incomplete), or a missing output
directory (out-dir-missing). Requires the `jsonschema` package.
"""
import json
import re
import sys
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    sys.exit("ERROR: the jsonschema package is required (pip install jsonschema)")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "runbook"


def render(rb):
    lines = [f"# Runbook: {rb['title']}", "", f"**Purpose.** {rb['purpose']}", "", f"**Trigger.** {rb['trigger']}", ""]
    if rb.get("lastVerified"):
        lines += [f"_Last walked through end to end: {rb['lastVerified']}._", ""]
    else:
        lines += ["_Never verified end to end — treat every step as untested._", ""]
    lines += ["## Preconditions", ""]
    lines += [f"- {p}" for p in rb["preconditions"]] or ["- (none)"]
    lines += ["", "## Steps", ""]
    for i, s in enumerate(rb["steps"], start=1):
        lines += [f"### {i}. {s['do'].splitlines()[0][:80]}", "", f"**Do.** {s['do']}", "",
                  f"**Verify.** {s['verify']}", "", f"**If it fails.** {s['ifFails']}", ""]
    lines += ["## Rollback", "", rb["rollback"], "", "## Escalation", "",
              f"- **Who:** {rb['escalation']['who']}", f"- **When:** {rb['escalation']['when']}", ""]
    return "\n".join(lines)


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
        sys.exit("ERROR: usage: render_runbook.py <runbook.json> --out-dir <dir> [--dry-run]")
    try:
        rb = json.loads(Path(args[0]).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load runbook {args[0]} (runbook-unparseable): {e}")
    schema = json.loads((Path(__file__).resolve().parent.parent / "assets" / "runbook.schema.json").read_text())
    try:
        jsonschema.validate(rb, schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: runbook fails assets/runbook.schema.json (runbook-invalid): {e.message}")
    if not out_dir.is_dir():
        sys.exit(f"ERROR: output directory does not exist (out-dir-missing): {out_dir}")

    for i, s in enumerate(rb["steps"], start=1):
        if not s["verify"].strip() or not s["ifFails"].strip():
            sys.exit(f"ERROR: step {i} ({s['do'][:50]!r}) lacks a verify or ifFails; an unverifiable step is not an instruction (runbook-incomplete)")
    if not rb["escalation"]["who"].strip():
        sys.exit("ERROR: escalation.who is empty (runbook-incomplete)")

    warnings = []
    for i, s in enumerate(rb["steps"], start=1):
        if "`" not in s["do"]:
            warnings.append(f"step {i}: 'do' contains no backticked command; if there is a command, show it exactly")
    if not rb.get("lastVerified"):
        warnings.append("lastVerified is absent: this runbook has never been walked through end to end")

    path = out_dir / f"{slugify(rb['title'])}.md"
    rendered = render(rb)
    if not dry_run:
        path.write_text(rendered)
    out = {"path": str(path), "warnings": warnings, "steps": len(rb["steps"])}
    if dry_run:
        out["rendered"] = rendered
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
