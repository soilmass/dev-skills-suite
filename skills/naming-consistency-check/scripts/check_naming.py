#!/usr/bin/env python3
"""Find Python identifiers that break the naming convention the rest of
the repository already follows, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    check_naming.py <repo-path> [--exclude dir,dir] [--min-votes N]

The script does not impose PEP 8. For each identifier kind it counts
the styles actually used across the tree (`ast` only; nothing is
imported or run — Effect Ladder rung 1, SDS-S-060), takes the majority
as the dominant convention, and reports the minority. A tree that
consistently uses camelCase functions gets no function findings.

Kinds and the styles recognised for them:

    function     snake_case | camelCase
    class        CapWords   | snake_case | camelCase
    constant     UPPER_CASE | snake_case | camelCase   (module-level
                 names bound to a literal, never rebound)
    variable     snake_case | camelCase                (module-level
                 names bound to a non-literal)
    argument     snake_case | camelCase

Rules emitted:

    naming/mixed-convention    an identifier of a kind uses a style
                               other than the kind's dominant style
                               -> warning; properties carry the kind,
                               the identifier's style, the dominant
                               style, and the vote counts
    naming/ambiguous-short-name a function or argument name of 1-2
                               characters outside a comprehension,
                               lambda, or loop target -> info

A kind needs at least --min-votes (default 3) identifiers before a
dominant style is declared; below that nothing is reported for it.
Dunder names, `_`-prefixed private names' leading underscores, and
`self`/`cls` are ignored when classifying. A module-level name bound
to a `TypeVar(...)` / `typing.TypeVar(...)` call is ignored entirely
(neither a vote nor a violation): PEP 484's own TypeVar naming
convention is not this tree's general variable-naming convention.

Prints one finding-list; a consistent tree yields an empty `results`
array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that
is not a directory (repo-invalid) or a file that does not parse
(source-unparseable).
"""
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
STYLES = {
    "snake_case": re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$"),
    "camelCase": re.compile(r"^[a-z][a-z0-9]*([A-Z][a-z0-9]*)+$"),
    "CapWords": re.compile(r"^[A-Z][a-z0-9]*([A-Z][a-z0-9]*)*$"),
    "UPPER_CASE": re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$"),
}
ALLOWED = {
    "function": ("snake_case", "camelCase"),
    "class": ("CapWords", "snake_case", "camelCase"),
    "constant": ("UPPER_CASE", "snake_case", "camelCase"),
    "variable": ("snake_case", "camelCase"),
    "argument": ("snake_case", "camelCase"),
}
IGNORE = {"self", "cls", "_"}


def _is_typevar_call(value):
    """True for `X = TypeVar(...)` / `X = typing.TypeVar(...)`: PEP
    484's own naming convention for TypeVars (CapWords, optionally
    `_`-prefixed and `_co`/`_contra`-suffixed for variance) is not
    this tree's general variable-naming convention, so a TypeVar
    assignment is not a naming-convention vote or violation."""
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id == "TypeVar"
    if isinstance(func, ast.Attribute):
        return func.attr == "TypeVar"
    return False


def style_of(name, kind):
    bare = name.lstrip("_")
    if not bare:
        return None
    for s in ALLOWED[kind]:
        if STYLES[s].match(bare):
            return s
    if len(bare) == 1:
        return None
    return "other"


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def collect(tree, rel):
    """Yield (kind, name, uri, line, in_short_scope) for every declared identifier."""
    out = []
    short_scope_args = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Lambda):
            short_scope_args.update(id(a) for a in node.args.args)
    bound = Counter()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
            targets = [node.target]
            value = node.value
        for t in targets:
            bound[t.id] += 1
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if _is_typevar_call(node.value):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name) and bound[t.id] == 1:
                    kind = "constant" if isinstance(node.value, ast.Constant) or (isinstance(node.value, (ast.Tuple, ast.List, ast.Set)) and all(isinstance(e, ast.Constant) for e in node.value.elts)) else "variable"
                    out.append((kind, t.id, rel, node.lineno, False))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(("function", node.name, rel, node.lineno, False))
            for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                out.append(("argument", a.arg, rel, a.lineno, False))
        elif isinstance(node, ast.ClassDef):
            out.append(("class", node.name, rel, node.lineno, False))
        elif isinstance(node, ast.Lambda):
            for a in node.args.args:
                out.append(("argument", a.arg, rel, node.lineno, True))
    return out


def main():
    args = sys.argv[1:]
    exclude = set()
    min_votes = 3
    for flag in ("--exclude", "--min-votes"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            if flag == "--exclude":
                exclude = {x.strip() for x in args[i + 1].split(",") if x.strip()}
            else:
                try:
                    min_votes = int(args[i + 1])
                except ValueError:
                    sys.exit("ERROR: --min-votes must be an integer")
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: check_naming.py <repo-path> [--exclude dir,dir] [--min-votes N]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")

    files = [p for p in sorted(root.rglob("*.py")) if not any(part in SKIP_DIRS or part in exclude for part in p.relative_to(root).parts)]
    declared = []
    for p in files:
        rel = str(p.relative_to(root))
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            sys.exit(f"ERROR: {rel} does not parse (source-unparseable): {e}")
        declared += collect(tree, rel)

    votes = defaultdict(Counter)
    styled = []
    for kind, name, uri, line, short_scope in declared:
        if name in IGNORE or (name.startswith("__") and name.endswith("__")):
            continue
        s = style_of(name, kind)
        if s is None:
            continue
        votes[kind][s] += 1
        styled.append((kind, name, uri, line, s))

    results = []
    dominant = {}
    for kind, c in votes.items():
        if sum(c.values()) >= min_votes:
            dominant[kind] = c.most_common(1)[0][0]
    for kind, name, uri, line, s in styled:
        if kind in dominant and s != dominant[kind]:
            results.append(finding("naming/mixed-convention", "warning",
                                   f"{kind} {name!r} is {s}; this tree's {kind}s are {dominant[kind]} ({votes[kind][dominant[kind]]} of {sum(votes[kind].values())})",
                                   uri, line, {"kind": kind, "name": name, "style": s, "dominant": dominant[kind],
                                               "votes": dict(votes[kind])}))
    for kind, name, uri, line, short_scope in declared:
        if kind in ("function", "argument") and not short_scope and name not in IGNORE and len(name.lstrip("_")) <= 2 and name.lstrip("_"):
            results.append(finding("naming/ambiguous-short-name", "info",
                                   f"{kind} {name!r} is {len(name)} character(s) long; a reader cannot tell what it holds",
                                   uri, line, {"kind": kind, "name": name}))

    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"]["region"]["startLine"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "naming-consistency-check", "version": "0.1.0"},
                                         "properties": {"dominant": dominant, "votes": {k: dict(v) for k, v in votes.items()}}},
                                "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
