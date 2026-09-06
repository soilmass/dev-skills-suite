#!/usr/bin/env python3
"""Render a decision-doc as a numbered MADR file and write it into an ADR
directory; optionally mark an earlier ADR as superseded.

Usage:
    render_adr.py <decision.json> --adr-dir <dir> [--title "<text>"]
                  [--supersedes <NNNN>] [--dry-run]

The input is a decision-doc (kit/shapes/decision-doc.schema.json) the
model composed in the Decide stage; this script validates it against
that schema, then does only the mechanical part (SDS-S-060): pick the
next four-digit number by scanning <adr-dir> for NNNN-*.md, derive a
slug from the title, render the MADR sections, and write the file.
Content judgment never happens here.

Writes (Effect Ladder rung 4, local-write):
    <adr-dir>/NNNN-<slug>.md               always (unless --dry-run)
    <adr-dir>/<supersedes>-*.md            only with --supersedes: the
        single sanctioned mutation of an accepted record — its
        `status:` line becomes `superseded by ADR-NNNN`. Body content
        is never edited (SDS-C-034; MADR's status convention).

`--dry-run` prints the target path and the rendered file without
touching the directory, so the Confirm preview and the evals exercise
the exact same rendering code.

Prints a JSON object to stdout: {"number", "path", "supersededPath",
"decision"} where "decision" is the input decision-doc with `status`
set to "accepted" and, when superseding, no other field changed. With
--dry-run, "path" is the path that WOULD be written and the rendered
markdown is included under "rendered".

Exit 1 with "ERROR: ..." on stderr for: an unreadable/malformed input
file (decision-unparseable); a decision-doc that fails the schema
(decision-invalid); a missing ADR directory (adr-dir-missing); a
--supersedes number with no matching file (supersede-target-missing).
Requires the `jsonschema` package (named in SKILL.md compatibility).
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


def family_root(start):
    for c in [start, *start.parents]:
        if (c / "kit").is_dir():
            return c
    return None


def load_schema():
    root = family_root(Path(__file__).resolve())
    if root is None:
        sys.exit("ERROR: could not locate the family root (a directory containing kit/) above this script")
    return json.loads((root / "kit" / "shapes" / "decision-doc.schema.json").read_text())


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "decision"


def next_number(adr_dir):
    nums = [int(m.group(1)) for p in adr_dir.glob("*.md")
            if (m := re.match(r"^(\d{4})-", p.name))]
    return max(nums, default=0) + 1


def bullets(items):
    return "\n".join(f"- {i}" for i in items) if items else "- (none recorded)"


def render(number, title, doc, supersedes):
    out = doc["decisionOutcome"]
    cons = doc.get("consequences", {})
    lines = [
        f"# ADR-{number:04d}: {title}",
        "",
        f"- status: {doc['status']}",
        f"- date: {date.today().isoformat()}",
    ]
    if supersedes:
        lines.append(f"- supersedes: ADR-{supersedes:04d}")
    lines += [
        "",
        "## Context and Problem Statement",
        "",
        doc["contextAndProblemStatement"],
        "",
        "## Decision Drivers",
        "",
        bullets(doc.get("decisionDrivers", [])),
        "",
        "## Considered Options",
        "",
        bullets(doc["consideredOptions"]),
        "",
        "## Decision Outcome",
        "",
        f"Chosen option: \"{out['chosenOption']}\", because {out['justification']}",
        "",
        "### Consequences",
        "",
        "Good:",
        "",
        bullets(cons.get("positive", [])),
        "",
        "Bad:",
        "",
        bullets(cons.get("negative", [])),
        "",
        "## Confirmation",
        "",
        doc.get("confirmation", "(not stated)"),
        "",
    ]
    return "\n".join(lines)


def mark_superseded(adr_dir, old_number, new_number, dry_run):
    matches = sorted(adr_dir.glob(f"{old_number:04d}-*.md"))
    if not matches:
        sys.exit(f"ERROR: no ADR numbered {old_number:04d} in {adr_dir} (supersede-target-missing)")
    target = matches[0]
    text = target.read_text()
    new_text, n = re.subn(r"^- status: .*$", f"- status: superseded by ADR-{new_number:04d}", text, count=1, flags=re.M)
    if n == 0:
        sys.exit(f"ERROR: {target.name} has no '- status:' line to update (supersede-target-missing)")
    if not dry_run:
        target.write_text(new_text)
    return target


def main():
    args = sys.argv[1:]
    def take(flag, default=None, has_value=True):
        if flag not in args:
            return default
        i = args.index(flag)
        if not has_value:
            del args[i]
            return True
        if i + 1 >= len(args):
            sys.exit(f"ERROR: {flag} requires a value")
        v = args[i + 1]
        del args[i:i + 2]
        return v
    adr_dir = take("--adr-dir")
    title = take("--title")
    supersedes = take("--supersedes")
    dry_run = take("--dry-run", False, has_value=False)
    if len(args) != 1 or not adr_dir:
        sys.exit("ERROR: usage: render_adr.py <decision.json> --adr-dir <dir> [--title <text>] [--supersedes <NNNN>] [--dry-run]")

    try:
        doc = json.loads(Path(args[0]).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load decision file {args[0]} (decision-unparseable): {e}")
    try:
        jsonschema.validate(doc, load_schema())
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: decision-doc fails kit/shapes/decision-doc.schema.json (decision-invalid): {e.message}")

    adr_dir = Path(adr_dir)
    if not adr_dir.is_dir():
        sys.exit(f"ERROR: ADR directory does not exist (adr-dir-missing): {adr_dir}")
    old_number = None
    if supersedes:
        if not re.fullmatch(r"\d{1,4}", supersedes):
            sys.exit(f"ERROR: --supersedes expects a number like 0001 (supersede-target-missing): {supersedes}")
        old_number = int(supersedes)

    doc = dict(doc, status="accepted")
    number = next_number(adr_dir)
    title = title or doc["decisionOutcome"]["chosenOption"]
    path = adr_dir / f"{number:04d}-{slugify(title)}.md"
    rendered = render(number, title, doc, old_number)

    superseded_path = None
    if old_number is not None:
        superseded_path = mark_superseded(adr_dir, old_number, number, dry_run)
    if not dry_run:
        path.write_text(rendered)

    result = {
        "number": f"{number:04d}",
        "path": str(path),
        "supersededPath": str(superseded_path) if superseded_path else None,
        "decision": doc,
    }
    if dry_run:
        result["rendered"] = rendered
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
