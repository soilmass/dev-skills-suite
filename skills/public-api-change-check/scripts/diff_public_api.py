#!/usr/bin/env python3
"""Compare the public surface of two snapshots of a Python package and
report the changes that break importers, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    diff_public_api.py <old-package-dir> <new-package-dir>

Effect Ladder rung 1 (SDS-S-060): both trees are parsed with `ast`;
nothing is imported or run. The public surface of a module is: the
names in `__all__` when it is defined, else every module-level
function, class, and assignment whose name does not start with an
underscore; for a class, its methods and class attributes not
starting with an underscore. Modules whose file or any parent
directory starts with an underscore are private.

Rules emitted (a client that worked against the old snapshot):

    api/symbol-removed          a public module, function, class,
                                method, or attribute is gone -> error
    api/param-removed           a positional or keyword parameter is
                                gone (callers passing it by name fail)
                                -> error
    api/param-required-added    a new parameter without a default, or
                                an existing one whose default was
                                removed -> error
    api/param-renamed           a parameter at the same position has a
                                new name (positional callers work,
                                keyword callers fail) -> warning
    api/param-kind-changed      a parameter moved across the `/` or `*`
                                markers (positional-only vs keyword-only)
                                -> warning
    api/default-changed         a default value changed -> info
                                (behaviour, not signature)
    api/return-annotation-changed the return annotation changed -> info
    api/symbol-added            a new public symbol -> info (never
                                breaking; may mean a minor bump)

Each finding carries the dotted symbol (`pkg.module.Class.method`)
in `properties.symbol`; `tool.properties.verdict` is `major` when
any error exists, `minor` when only additions or renames exist, else
`patch`. Whether a removal is acceptable — the symbol was documented
as private, the package is pre-1.0 — is the skill's Analyze stage
(SDS-S-061).

Prints one finding-list; identical surfaces yield an empty `results`
array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that
is not a directory (package-invalid) or a file that does not parse
(source-unparseable).
"""
import ast
import json
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", "tests", "test"}


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def dump(node):
    return ast.unparse(node) if node is not None else None


def signature(fn):
    a = fn.args
    params = []
    pos_defaults = [None] * (len(a.posonlyargs) + len(a.args) - len(a.defaults)) + list(a.defaults)
    for i, p in enumerate(a.posonlyargs):
        params.append({"name": p.arg, "kind": "positional-only", "default": dump(pos_defaults[i])})
    for i, p in enumerate(a.args):
        params.append({"name": p.arg, "kind": "positional", "default": dump(pos_defaults[len(a.posonlyargs) + i])})
    if a.vararg:
        params.append({"name": "*" + a.vararg.arg, "kind": "var-positional", "default": None})
    for p, d in zip(a.kwonlyargs, a.kw_defaults):
        params.append({"name": p.arg, "kind": "keyword-only", "default": dump(d)})
    if a.kwarg:
        params.append({"name": "**" + a.kwarg.arg, "kind": "var-keyword", "default": None})
    return {"params": params, "returns": dump(fn.returns), "line": fn.lineno}


def surface(root):
    """Map dotted symbol -> {"kind", "line", "uri", "sig"?}."""
    out = {}
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (package-invalid): {root}")
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or (part.startswith("_") and part != "__init__.py") for part in rel.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
        mod = ".".join([root.name] + [x for x in rel.with_suffix("").parts if x != "__init__"])
        uri = rel.as_posix()
        exported = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets) and isinstance(node.value, (ast.List, ast.Tuple)):
                exported = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
        out[mod] = {"kind": "module", "line": 1, "uri": uri}

        def public(name):
            return name in exported if exported is not None else not name.startswith("_")

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and public(node.name):
                out[f"{mod}.{node.name}"] = {"kind": "function", "line": node.lineno, "uri": uri, "sig": signature(node)}
            elif isinstance(node, ast.ClassDef) and public(node.name):
                out[f"{mod}.{node.name}"] = {"kind": "class", "line": node.lineno, "uri": uri}
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not sub.name.startswith("_") or sub.name == "__init__"):
                        out[f"{mod}.{node.name}.{sub.name}"] = {"kind": "method", "line": sub.lineno, "uri": uri, "sig": signature(sub)}
                    elif isinstance(sub, (ast.Assign, ast.AnnAssign)):
                        targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                        for t in targets:
                            if isinstance(t, ast.Name) and not t.id.startswith("_"):
                                out[f"{mod}.{node.name}.{t.id}"] = {"kind": "attribute", "line": sub.lineno, "uri": uri}
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id != "__all__" and public(t.id):
                        out[f"{mod}.{t.id}"] = {"kind": "constant", "line": node.lineno, "uri": uri}
    return out


def compare_sig(sym, o, n, uri, line, out):
    op, np_ = o["params"], n["params"]
    o_names = {p["name"]: p for p in op if not p["name"].startswith("*")}
    n_names = {p["name"]: p for p in np_ if not p["name"].startswith("*")}
    o_pos = [p for p in op if p["kind"] in ("positional-only", "positional")]
    n_pos = [p for p in np_ if p["kind"] in ("positional-only", "positional")]
    renamed = set()
    for i, (a, b) in enumerate(zip(o_pos, n_pos)):
        if a["name"] != b["name"] and a["name"] not in n_names and b["name"] not in o_names:
            renamed.add(a["name"]); renamed.add(b["name"])
            out.append(finding("api/param-renamed", "warning", f"{sym}: parameter {a['name']!r} renamed to {b['name']!r} at position {i}; keyword callers break", uri, line, {"symbol": sym, "from": a["name"], "to": b["name"], "position": i}))
    for name, p in o_names.items():
        if name in renamed:
            continue
        q = n_names.get(name)
        if q is None:
            out.append(finding("api/param-removed", "error", f"{sym}: parameter {name!r} removed", uri, line, {"symbol": sym, "param": name}))
            continue
        if p["default"] is not None and q["default"] is None:
            out.append(finding("api/param-required-added", "error", f"{sym}: parameter {name!r} lost its default and is now required", uri, line, {"symbol": sym, "param": name}))
        elif p["default"] != q["default"] and q["default"] is not None:
            out.append(finding("api/default-changed", "info", f"{sym}: default of {name!r} changed from {p['default']} to {q['default']}", uri, line, {"symbol": sym, "param": name, "from": p["default"], "to": q["default"]}))
        if p["kind"] != q["kind"]:
            out.append(finding("api/param-kind-changed", "warning", f"{sym}: parameter {name!r} changed from {p['kind']} to {q['kind']}", uri, line, {"symbol": sym, "param": name, "from": p["kind"], "to": q["kind"]}))
    for name, q in n_names.items():
        if name not in o_names and name not in renamed and q["default"] is None and q["kind"] != "var-positional":
            out.append(finding("api/param-required-added", "error", f"{sym}: new required parameter {name!r}", uri, line, {"symbol": sym, "param": name}))
    if o["returns"] != n["returns"]:
        out.append(finding("api/return-annotation-changed", "info", f"{sym}: return annotation changed from {o['returns']} to {n['returns']}", uri, line, {"symbol": sym, "from": o["returns"], "to": n["returns"]}))


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        sys.exit("ERROR: usage: diff_public_api.py <old-package-dir> <new-package-dir>")
    old, new = surface(Path(args[0])), surface(Path(args[1]))
    # align package names: the two directories may be named differently
    o_root, n_root = Path(args[0]).name, Path(args[1]).name
    old = {k.replace(o_root, "pkg", 1): v for k, v in old.items()}
    new = {k.replace(n_root, "pkg", 1): v for k, v in new.items()}
    out = []
    for sym, o in old.items():
        n = new.get(sym)
        if n is None:
            # a removed module removes its symbols; report the module once, not every member
            if any(sym.startswith(parent + ".") and parent not in new for parent in old if old[parent]["kind"] == "module" and parent != sym):
                continue
            out.append(finding("api/symbol-removed", "error", f"{o['kind']} {sym} removed", o["uri"], o["line"], {"symbol": sym, "kind": o["kind"]}))
            continue
        if "sig" in o and "sig" in n:
            compare_sig(sym, o["sig"], n["sig"], n["uri"], n["line"], out)
    for sym, n in new.items():
        if sym not in old:
            if any(sym.startswith(parent + ".") and parent not in old for parent in new if new[parent]["kind"] == "module" and parent != sym):
                continue
            out.append(finding("api/symbol-added", "info", f"{n['kind']} {sym} added", n["uri"], n["line"], {"symbol": sym, "kind": n["kind"]}))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order[r["level"]], r["properties"]["symbol"], r["ruleId"]))
    levels = {r["level"] for r in out}
    verdict = "major" if "error" in levels else "minor" if levels & {"warning", "info"} else "patch"
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "public-api-change-check", "version": "0.1.0"},
                                         "properties": {"oldSymbols": len(old), "newSymbols": len(new), "breaking": sum(1 for r in out if r["level"] == "error"), "verdict": verdict}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
