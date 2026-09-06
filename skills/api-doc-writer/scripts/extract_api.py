#!/usr/bin/env python3
"""Extract a Python package's public API — signatures, docstrings,
raised exceptions — and detect drift against an existing reference.

Usage:
    extract_api.py <package-dir-or-file.py> [--include-private]
                   [--existing <reference.md>]

Uses only the standard library's `ast` (no import of the target code,
so nothing runs; Effect Ladder rung 1). Emits exactly what the code
states and nothing else (the skill's "never invent behavior" rule):

    {"modules": [{"module": "pkg.client", "path": "...", "symbols": [
        {"kind": "class"|"function"|"method", "name": "Client.get",
         "signature": "get(self, path: str, *, timeout: float = 5.0) -> dict",
         "summary": "<first docstring paragraph or null>",
         "doc": "<full docstring or null>", "documented": bool,
         "raises": ["ValueError", ...], "decorators": ["property", ...],
         "lineno": 12}]}],
     "drift": [{"symbol": "...", "issue": "removed"|"signature-changed",
                "documented": "<line from the existing reference>"}]}

`--existing` reads a markdown reference containing lines of the form
`### <symbol>` followed by a fenced signature; symbols that no longer
exist, or whose signature no longer matches, are listed under `drift`.
Private names (leading underscore) and private modules are skipped
unless --include-private.

The output conforms to assets/api-extract.schema.json (this skill's
own intermediate shape, not a family shape).

Exit 1 with "ERROR: ..." on stderr for: a path that is neither a .py
file nor a directory containing one (source-missing); a file that does
not parse (source-unparseable); an unreadable existing reference
(reference-unreadable).
"""
import ast
import json
import re
import sys
from pathlib import Path


def fmt_arg(a, default=None):
    s = a.arg
    if a.annotation is not None:
        s += f": {ast.unparse(a.annotation)}"
    if default is not None:
        s += f" = {ast.unparse(default)}"
    return s


def signature(fn):
    a = fn.args
    parts = []
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    for arg, d in zip(pos, defaults):
        parts.append(fmt_arg(arg, d))
    if a.posonlyargs:
        parts.insert(len(a.posonlyargs), "/")
    if a.vararg:
        parts.append("*" + fmt_arg(a.vararg))
    elif a.kwonlyargs:
        parts.append("*")
    for arg, d in zip(a.kwonlyargs, a.kw_defaults):
        parts.append(fmt_arg(arg, d))
    if a.kwarg:
        parts.append("**" + fmt_arg(a.kwarg))
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns is not None else ""
    return f"{fn.name}({', '.join(parts)}){ret}"


def raises(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Raise) and n.exc is not None:
            e = n.exc
            if isinstance(e, ast.Call):
                e = e.func
            out.add(ast.unparse(e))
    return sorted(out)


def symbol(kind, name, node):
    doc = ast.get_docstring(node)
    return {
        "kind": kind, "name": name, "signature": signature(node) if kind != "class" else f"class {node.name}",
        "summary": (doc.strip().split("\n\n")[0].strip() if doc else None),
        "doc": doc, "documented": bool(doc),
        "raises": raises(node) if kind != "class" else [],
        "decorators": [ast.unparse(d) for d in node.decorator_list],
        "lineno": node.lineno,
    }


def extract_module(path, modname, include_private):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as e:
        sys.exit(f"ERROR: {path} does not parse (source-unparseable): {e}")
    syms = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if include_private or not node.name.startswith("_"):
                syms.append(symbol("function", node.name, node))
        elif isinstance(node, ast.ClassDef):
            if not include_private and node.name.startswith("_"):
                continue
            syms.append(symbol("class", node.name, node))
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if include_private or not m.name.startswith("_") or m.name == "__init__":
                        syms.append(symbol("method", f"{node.name}.{m.name}", m))
    return {"module": modname, "path": str(path), "symbols": syms}


def drift_against(existing_path, modules):
    try:
        text = Path(existing_path).read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"ERROR: could not read existing reference {existing_path} (reference-unreadable): {e}")
    current = {s["name"]: s["signature"] for m in modules for s in m["symbols"]}
    drift = []
    for m in re.finditer(r"^### `?([\w.]+)`?\s*\n(?:```\w*\n(.*?)\n```)?", text, re.M | re.S):
        name, sig = m.group(1), (m.group(2) or "").strip()
        if name not in current:
            drift.append({"symbol": name, "issue": "removed", "documented": sig or name})
        elif sig and sig != current[name] and sig != f"class {name}":
            drift.append({"symbol": name, "issue": "signature-changed", "documented": sig, "actual": current[name]})
    return drift


def main():
    args = sys.argv[1:]
    include_private = "--include-private" in args
    if include_private:
        args.remove("--include-private")
    existing = None
    if "--existing" in args:
        i = args.index("--existing")
        if i + 1 >= len(args):
            sys.exit("ERROR: --existing requires a path")
        existing = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: extract_api.py <package-dir-or-file.py> [--include-private] [--existing <reference.md>]")
    target = Path(args[0])
    if target.is_file() and target.suffix == ".py":
        files = [target]
        base = target.parent
    elif target.is_dir():
        files = sorted(p for p in target.rglob("*.py") if "__pycache__" not in p.parts)
        base = target.parent
        if not files:
            sys.exit(f"ERROR: no .py files under {target} (source-missing)")
    else:
        sys.exit(f"ERROR: not a .py file or a package directory (source-missing): {target}")

    modules = []
    for f in files:
        rel = f.relative_to(base).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        if not include_private and any(p.startswith("_") and p != "__init__" for p in parts):
            continue
        modules.append(extract_module(f, ".".join(parts) or target.stem, include_private))

    print(json.dumps({"modules": modules, "drift": drift_against(existing, modules) if existing else []}, indent=2))


if __name__ == "__main__":
    main()
