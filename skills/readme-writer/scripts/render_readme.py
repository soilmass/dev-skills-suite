#!/usr/bin/env python3
"""Check a README specification against what the repository declares and
render it.

Usage:
    render_readme.py <readme.json> --out-dir <dir> [--facts-file <orientation.json>] [--dry-run]

The input conforms to assets/readme.schema.json, this skill's own
intermediate shape (SDS-S-080). The model composes it in the Decide
stage; this script does only what is mechanical (SDS-S-060):

  1. validates the JSON against the asset schema;
  2. with --facts-file (the repository-orientation facts object,
     SDS-S-065: the upstream producer's output is injected, never
     re-collected here), refuses (command-undeclared) any `make <target>`
     or `npm run <script>` / `npm <script>` / `yarn <script>` / `pnpm
     <script>` command that the repository's manifests do not declare
     — a README that names a command the tree lacks is worse than no
     README — and warns when the facts show a lockfile, tests, or CI
     that the specification never mentions;
  3. renders <out-dir>/README.md in Standard Readme section order
     (rung 4, local-write).

`--dry-run` prints everything and writes nothing. Output:
{"path", "warnings", "sections", "rendered"?}. Exit 1 with "ERROR: ..."
on stderr for an unreadable/malformed input (readme-unparseable), a
spec failing the shape (readme-invalid), a command the facts do not
declare (command-undeclared), an unreadable facts file
(facts-unparseable), or a missing output directory (out-dir-missing).
Requires the `jsonschema` package.
"""
import json
import re
import sys
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    sys.exit("ERROR: the jsonschema package is required (pip install jsonschema)")

MAKE_RE = re.compile(r"(?:^|&&|;|\|\|)\s*make\s+([A-Za-z0-9_./-]+)")
NPM_RE = re.compile(r"(?:^|&&|;|\|\|)\s*(?:npm\s+run|npm|yarn|pnpm)\s+([A-Za-z0-9:_-]+)")
NPM_BUILTINS = {"install", "ci", "test", "start", "init", "publish", "audit", "i", "add", "run"}


def load_json(path, code):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: {path}: {e} ({code})")


def declared(facts):
    make, npm = set(), set()
    for m in facts.get("manifests", []):
        names = {c["name"] for c in m.get("commands", [])}
        if m.get("ecosystem") == "make":
            make |= names
        elif m.get("ecosystem") == "npm":
            npm |= names
    return make, npm


def check_commands(spec, facts):
    make, npm = declared(facts)
    for section in ("install", "usage", "develop"):
        for c in spec.get(section, []):
            for target in MAKE_RE.findall(c["command"]):
                if target not in make:
                    sys.exit(f"ERROR: {section}: 'make {target}' is not a declared Makefile target (declared: {', '.join(sorted(make)) or 'none'}) (command-undeclared)")
            for script in NPM_RE.findall(c["command"]):
                if script not in npm and script not in NPM_BUILTINS:
                    sys.exit(f"ERROR: {section}: '{script}' is not a declared package.json script (declared: {', '.join(sorted(npm)) or 'none'}) (command-undeclared)")


def facts_warnings(spec, facts):
    text = json.dumps(spec).lower()
    sig = facts.get("signals", {})
    w = []
    if sig.get("tests") and not spec.get("develop"):
        w.append("the repository has tests but the specification has no develop section saying how to run them")
    if sig.get("ci") and "ci" not in text and "workflow" not in text:
        w.append("the repository has CI workflows the README never mentions")
    if not sig.get("license"):
        w.append("the README names a license but the repository has no LICENSE file")
    return w


def render(spec):
    lines = [f"# {spec['name']}", "", spec["tagline"], ""]
    if spec.get("background"):
        lines += ["## Background", "", spec["background"], ""]
    for title, key in (("Install", "install"), ("Usage", "usage"), ("Development", "develop")):
        items = spec.get(key)
        if not items:
            continue
        lines += [f"## {title}", ""]
        for c in items:
            lines += [c["description"], "", "```sh", c["command"], "```", ""]
            if c.get("output"):
                lines += ["Expected output:", "", "```", c["output"], "```", ""]
    if spec.get("maintainers"):
        lines += ["## Maintainers", ""] + [f"- {m}" for m in spec["maintainers"]] + [""]
    if spec.get("contributing"):
        lines += ["## Contributing", "", spec["contributing"], ""]
    lines += ["## License", "", spec["license"], ""]
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    if dry:
        args.remove("--dry-run")
    out_dir = facts_path = None
    for flag in ("--out-dir", "--facts-file"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            if flag == "--out-dir":
                out_dir = Path(args[i + 1])
            else:
                facts_path = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or out_dir is None:
        sys.exit("ERROR: usage: render_readme.py <readme.json> --out-dir <dir> [--facts-file <orientation.json>] [--dry-run]")
    spec = load_json(args[0], "readme-unparseable")
    schema = json.loads((Path(__file__).resolve().parent.parent / "assets" / "readme.schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.validate(spec, schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: specification fails assets/readme.schema.json at {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message} (readme-invalid)")
    if not out_dir.is_dir():
        sys.exit(f"ERROR: output directory does not exist (out-dir-missing): {out_dir}")
    warnings = []
    if facts_path:
        facts = load_json(facts_path, "facts-unparseable")
        check_commands(spec, facts)
        warnings += facts_warnings(spec, facts)
    else:
        warnings.append("no --facts-file given: commands were not checked against the repository's declared ones")
    rendered = render(spec)
    sections = [l[3:] for l in rendered.splitlines() if l.startswith("## ")]
    path = out_dir / "README.md"
    result = {"path": str(path), "warnings": warnings, "sections": sections}
    if dry:
        result["rendered"] = rendered
    else:
        path.write_text(rendered, encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
