#!/usr/bin/env python3
"""Inventory every environment variable the code reads and compare it
with what the repository documents, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    inventory_env_vars.py <repo-path> [--example <.env.example>] [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): files are read; nothing is run and
no environment is inspected. Reads are found by shape:

    Python      os.environ["X"], os.environ.get("X"[, default]),
                os.getenv("X"[, default]), environ["X"], environ.get(...)
                — via `ast`
    JS / TS     process.env.X, process.env["X"], process.env.X ?? d,
                process.env.X || d — via a regular expression over
                .js/.mjs/.cjs/.ts/.tsx/.jsx files

The documented set comes from --example (default: the first of
.env.example, .env.sample, .env.template, .env.dist at the
repository root) as KEY=value lines; a KEY with no value or an empty
value is documented-but-unset.

Rules emitted:

    env/undocumented        read in code, absent from the example file
                            -> warning (a newcomer cannot know it exists)
    env/unused              documented but read nowhere -> info (stale,
                            or read by a tool outside this tree)
    env/secret-with-default a name that looks like a secret (KEY, TOKEN,
                            SECRET, PASSWORD, PASSWD, PRIVATE) read with
                            a non-empty literal default -> warning (a
                            fallback credential ships in the code)
    env/required-no-example a variable read without a default (a crash
                            if absent) whose example line is empty ->
                            info (the example should show a sample value
                            or say where it comes from)

The run's `tool.properties` carries the inventory: every variable with
its read count, files, whether any read has a default, whether it is
documented, and the example's value presence. Deciding which
undocumented variable is a real requirement versus a local override,
and what the example should say, is the skill's Analyze stage
(SDS-S-061).

Prints one finding-list; a tree whose reads and example agree yields
an empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on
stderr for a path that is not a directory (repo-invalid), a Python
file that does not parse (source-unparseable), or an --example path
that cannot be read (example-unreadable). No example file at all is
not an error: every read is then undocumented.
"""
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv", "coverage"}
EXAMPLE_NAMES = (".env.example", ".env.sample", ".env.template", ".env.dist")
SECRET_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE|CREDENTIAL)", re.I)
JS_RE = re.compile(r"process\.env(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\])(\s*(?:\?\?|\|\|)\s*(['\"][^'\"]*['\"]|[\w.]+))?")
JS_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def env_name(node):
    if isinstance(node, ast.Name):
        return node.id == "environ"
    return isinstance(node, ast.Attribute) and node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os"


def python_reads(tree, rel):
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and env_name(node.value) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            yield node.slice.value, rel, node.lineno, None, True
        elif isinstance(node, ast.Call):
            f = node.func
            is_get = isinstance(f, ast.Attribute) and f.attr == "get" and env_name(f.value)
            is_getenv = (isinstance(f, ast.Attribute) and f.attr == "getenv" and isinstance(f.value, ast.Name) and f.value.id == "os") or (isinstance(f, ast.Name) and f.id == "getenv")
            if (is_get or is_getenv) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                default = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "default"), None)
                dval = default.value if isinstance(default, ast.Constant) else ("<expr>" if default is not None else None)
                yield node.args[0].value, rel, node.lineno, dval, default is None


def js_reads(text, rel):
    for m in JS_RE.finditer(text):
        name = m.group(1) or m.group(2)
        line = text.count("\n", 0, m.start()) + 1
        default = m.group(4)
        dval = default.strip("'\"") if default and default[0] in "'\"" else ("<expr>" if default else None)
        yield name, rel, line, dval, default is None


def load_example(path):
    documented = {}
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        documented[k.strip()] = {"line": i, "value": v.strip().strip("'\"")}
    return documented


def main():
    args = sys.argv[1:]
    example, exclude = None, set()
    for flag in ("--example", "--exclude"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            if flag == "--example":
                example = Path(args[i + 1])
            else:
                exclude = {x.strip() for x in args[i + 1].split(",") if x.strip()}
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: inventory_env_vars.py <repo-path> [--example <.env.example>] [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    if example is None:
        example = next((root / n for n in EXAMPLE_NAMES if (root / n).is_file()), None)
    documented = {}
    if example is not None:
        try:
            documented = load_example(example)
        except (OSError, UnicodeDecodeError) as e:
            sys.exit(f"ERROR: could not read example file {example} (example-unreadable): {e}")

    reads = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        if p.suffix == ".py":
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            except SyntaxError as e:
                sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
            reads += list(python_reads(tree, rel.as_posix()))
        elif p.suffix in JS_EXT:
            reads += list(js_reads(p.read_text(encoding="utf-8", errors="replace"), rel.as_posix()))

    by_var = defaultdict(list)
    for name, rel, line, dval, required in reads:
        by_var[name].append({"file": rel, "line": line, "default": dval, "required": required})
    results = []
    for name in sorted(by_var):
        rs = by_var[name]
        first = min(rs, key=lambda r: (r["file"], r["line"]))
        doc = documented.get(name)
        if doc is None:
            results.append(finding("env/undocumented", "warning",
                                   f"{name} is read in {len(rs)} place(s) but not documented in {example.name if example else 'any example file'}",
                                   first["file"], first["line"], {"variable": name, "reads": len(rs), "files": sorted({r['file'] for r in rs})}))
        elif doc["value"] == "" and all(r["required"] for r in rs):
            results.append(finding("env/required-no-example", "info",
                                   f"{name} is required by every read and its example line is empty; show a sample value or say where it comes from",
                                   example.name, doc["line"], {"variable": name}))
        for r in rs:
            if SECRET_RE.search(name) and isinstance(r["default"], str) and r["default"] not in ("", "<expr>"):
                results.append(finding("env/secret-with-default", "warning",
                                       f"{name} looks like a secret and is read with a literal default {r['default']!r}; a fallback credential ships in the code",
                                       r["file"], r["line"], {"variable": name, "default": r["default"]}))
    for name, doc in sorted(documented.items()):
        if name not in by_var:
            results.append(finding("env/unused", "info", f"{name} is documented but read nowhere in the tree; stale, or read by a tool outside it",
                                   example.name, doc["line"], {"variable": name}))
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["ruleId"], r["properties"]["variable"]))
    inventory = [{"variable": n, "reads": len(rs), "files": sorted({r["file"] for r in rs}),
                  "hasDefault": any(r["default"] is not None for r in rs), "required": all(r["required"] for r in rs),
                  "documented": n in documented, "exampleValueSet": bool(documented.get(n, {}).get("value"))} for n, rs in sorted(by_var.items())]
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "env-var-inventory", "version": "0.1.0"},
                                         "properties": {"exampleFile": example.name if example else None, "variables": inventory, "documented": sorted(documented)}},
                                "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
