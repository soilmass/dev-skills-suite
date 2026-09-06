#!/usr/bin/env python3
"""Render an API extract (the output of extract_api.py) as a
Diataxis-style reference page and write it.

Usage:
    render_api_docs.py <extract.json> --out <reference.md> [--dry-run]

Validates the extract against assets/api-extract.schema.json, then
renders one `## <module>` section per module and one `### <symbol>`
entry per public symbol: a fenced signature, the docstring summary if
the code has one, `Raises:` from the raise statements found, and — for
any symbol without a docstring — the literal line

    _Undocumented — behavior not stated in the code; do not infer._

That marker is the point of this skill: the reference never claims
behavior the code does not state. The model's Decide stage may replace
a marker only with prose it can source (a docstring, a test, a call
site) and must cite the source inline. Drift entries, if any, render
under a leading `## Drift` section so stale documentation is visible
before it is silently overwritten.

`--dry-run` prints the rendered page and writes nothing. Output is a
JSON object {"path", "symbols", "undocumented", "drift", "rendered"?}.
Exit 1 with "ERROR: ..." on stderr for an unreadable/malformed extract
(extract-unparseable), an extract failing the asset schema
(extract-invalid), or a missing output directory (out-dir-missing).
Requires the `jsonschema` package.
"""
import json
import sys
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    sys.exit("ERROR: the jsonschema package is required (pip install jsonschema)")

UNDOC = "_Undocumented — behavior not stated in the code; do not infer._"


def render(extract):
    lines = ["# API Reference", "", "_Reference (Diataxis): what each public symbol accepts, returns, and raises, as stated by the code._", ""]
    if extract.get("drift"):
        lines += ["## Drift", "", "Entries in the previous reference that no longer match the code:", ""]
        for d in extract["drift"]:
            detail = f" (documented `{d['documented']}`, actual `{d.get('actual')}`)" if d["issue"] == "signature-changed" else ""
            lines.append(f"- `{d['symbol']}`: {d['issue']}{detail}")
        lines.append("")
    undocumented = 0
    count = 0
    for m in extract["modules"]:
        lines += [f"## `{m['module']}`", ""]
        if not m["symbols"]:
            lines += ["_No public symbols._", ""]
        for s in m["symbols"]:
            count += 1
            lines += [f"### `{s['name']}`", "", "```python", s["signature"], "```", ""]
            if s["documented"]:
                lines += [s["summary"], ""]
            else:
                undocumented += 1
                lines += [UNDOC, ""]
            if s["raises"]:
                lines += ["Raises: " + ", ".join(f"`{r}`" for r in s["raises"]), ""]
    return "\n".join(lines), count, undocumented


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")
    out = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            sys.exit("ERROR: --out requires a path")
        out = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1 or out is None:
        sys.exit("ERROR: usage: render_api_docs.py <extract.json> --out <reference.md> [--dry-run]")
    try:
        extract = json.loads(Path(args[0]).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load extract {args[0]} (extract-unparseable): {e}")
    schema = json.loads((Path(__file__).resolve().parent.parent / "assets" / "api-extract.schema.json").read_text())
    try:
        jsonschema.validate(extract, schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: extract fails assets/api-extract.schema.json (extract-invalid): {e.message}")
    if not out.parent.is_dir():
        sys.exit(f"ERROR: output directory does not exist (out-dir-missing): {out.parent}")

    rendered, count, undocumented = render(extract)
    if not dry_run:
        out.write_text(rendered)
    result = {"path": str(out), "symbols": count, "undocumented": undocumented, "drift": len(extract.get("drift", []))}
    if dry_run:
        result["rendered"] = rendered
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
