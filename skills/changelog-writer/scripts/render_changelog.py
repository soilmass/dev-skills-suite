#!/usr/bin/env python3
"""Insert a categorized status-report as a new Keep a Changelog entry
at the top of CHANGELOG.md.

Usage:
    render_changelog.py <report.json> --changelog <CHANGELOG.md>
                        --version <x.y.z | Unreleased> [--date YYYY-MM-DD]
                        [--dry-run]

Validates the report against kit/shapes/status-report.schema.json,
renders

    ## [x.y.z] - YYYY-MM-DD        (or ## [Unreleased])
    ### Added
    - ...
    ### Fixed
    - ...

and inserts it directly after the file's `# Changelog` heading and
intro (before the first existing `## ` entry), preserving everything
else byte for byte. Refuses to write if an entry for that version
already exists (version-exists) — a changelog is append-only history
(SDS-C-034); amending a released entry is a deliberate manual act.

`--dry-run` prints the new file content and writes nothing. Output is
a JSON object {"path", "version", "entry", "content"?}. Exit 1 with
"ERROR: ..." on stderr for an unreadable/malformed report
(report-unparseable), a report failing the shape (report-invalid), a
missing changelog file (changelog-missing), or an existing entry
(version-exists). Requires the `jsonschema` package.
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


def render_entry(report, version, day):
    head = "## [Unreleased]" if version.lower() == "unreleased" else f"## [{version}] - {day}"
    lines = [head, ""]
    for s in report["sections"]:
        lines += [f"### {s['heading']}", "", s["body"].rstrip(), ""]
    if not report["sections"]:
        lines += ["_No changes._", ""]
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")
    def take(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return None
    changelog = take("--changelog")
    version = take("--version")
    day = take("--date") or date.today().isoformat()
    if len(args) != 1 or not changelog or not version:
        sys.exit("ERROR: usage: render_changelog.py <report.json> --changelog <file> --version <x.y.z|Unreleased> [--date YYYY-MM-DD] [--dry-run]")

    try:
        report = json.loads(Path(args[0]).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load report {args[0]} (report-unparseable): {e}")
    root = family_root(Path(__file__).resolve())
    if root is None:
        sys.exit("ERROR: could not locate the family root (a directory containing kit/) above this script")
    try:
        jsonschema.validate(report, json.loads((root / "kit/shapes/status-report.schema.json").read_text()))
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: report fails kit/shapes/status-report.schema.json (report-invalid): {e.message}")

    path = Path(changelog)
    if not path.is_file():
        sys.exit(f"ERROR: changelog file does not exist (changelog-missing): {path}")
    text = path.read_text()
    tag = "[Unreleased]" if version.lower() == "unreleased" else f"[{version}]"
    if re.search(r"^## " + re.escape(tag), text, re.M):
        sys.exit(f"ERROR: an entry for {tag} already exists in {path} (version-exists)")

    entry = render_entry(report, version, day)
    m = re.search(r"^## ", text, re.M)
    if m:
        content = text[:m.start()] + entry + "\n" + text[m.start():]
    else:
        content = text.rstrip("\n") + "\n\n" + entry
    if not dry_run:
        path.write_text(content)
    out = {"path": str(path), "version": version, "entry": entry}
    if dry_run:
        out["content"] = content
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
