#!/usr/bin/env python3
"""Find top-level Python functions and classes nothing references, as a
finding-list (kit/shapes/finding-list.schema.json).

Usage:
    find_dead_code.py <repo-path> [--exclude dir,dir]

Method (deterministic, Effect Ladder rung 1, `ast` only — nothing is
imported or executed): collect every top-level `def`/`class` in every
.py file; collect every Name and Attribute reference and every string
literal across the tree; a definition is reported as
dead/unreferenced-definition (warning) when its name occurs nowhere
except its own definition line.

What is deliberately NOT reported, because static counting cannot see
the reference (SDS-C-048 — say what you cannot know):
    - names listed in a module's __all__ (public API for importers
      outside this tree);
    - names that appear inside any string literal (getattr, plugin
      registries, CLI dispatch tables);
    - dunder names, `main`, and names starting with `test_`;
    - a top-level def/class carrying at least one decorator (a
      decorator hands the function/class object itself to code that
      may register it elsewhere — a route table, a check registry, a
      pytest fixture — with no name reference for this scan to find,
      exactly like the string-registry case above);
    - a top-level class whose base list names anything ending in
      `TestCase` (unittest-style test classes are found by the test
      runner's discovery, not by a name reference anywhere in source);
    - anything under directories named in --exclude or the usual
      vendored/build directories.
Every finding carries properties.confidence "static" and the reminder
that dynamic dispatch, reflection, and out-of-tree importers are
invisible to this scan; the skill's Analyze stage decides whether a
candidate is really dead.

Prints one finding-list. A tree where every definition is referenced
yields an empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..."
on stderr for a path that is not a directory (repo-invalid) or a file
that does not parse (source-unparseable).
"""
import ast
import json
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
IGNORE_NAMES = {"main"}


def _base_name(base):
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def _framework_registered(node):
    """A top-level def/class a static name-count cannot see used: a
    decorator hands the function/class object to code elsewhere (a
    route table, a check registry, a pytest fixture) with no name
    reference to find; a TestCase subclass is found by the test
    runner's own discovery, never referenced by name in source."""
    if node.decorator_list:
        return True
    if isinstance(node, ast.ClassDef):
        return any(_base_name(b).endswith("TestCase") for b in node.bases)
    return False


def collect(root, exclude):
    defs, refs, strings, exported = [], set(), set(), set()
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except (SyntaxError, UnicodeDecodeError) as e:
            sys.exit(f"ERROR: {rel} does not parse (source-unparseable): {e}")
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if _framework_registered(node):
                    continue
                defs.append((node.name, str(rel), node.lineno, type(node).__name__))
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    exported |= {e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                refs.add(node.id)
            elif isinstance(node, ast.Attribute):
                refs.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.add(node.value)
        # a definition's own name node is not a Name reference, but an import of it elsewhere is
        for node in ast.walk(tree):
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                for alias in node.names:
                    refs.add(alias.name.split(".")[-1])
                    if alias.asname:
                        refs.add(alias.asname)
    return defs, refs, strings, exported


def main():
    args = sys.argv[1:]
    exclude = set()
    if "--exclude" in args:
        i = args.index("--exclude")
        if i + 1 >= len(args):
            sys.exit("ERROR: --exclude requires a value")
        exclude = {x.strip() for x in args[i + 1].split(",") if x.strip()}
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: find_dead_code.py <repo-path> [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")

    defs, refs, strings, exported = collect(root, exclude)
    in_strings = set()
    for name, *_ in defs:
        if any(name in s for s in strings):
            in_strings.add(name)
    results = []
    for name, rel, line, kind in defs:
        if name.startswith("__") and name.endswith("__"):
            continue
        if name in IGNORE_NAMES or name.startswith("test_") or name in exported or name in in_strings:
            continue
        if name in refs:
            continue
        results.append({
            "ruleId": "dead/unreferenced-definition",
            "level": "warning",
            "message": {"text": f"{kind.replace('Def', '').lower()} {name} in {rel} is referenced nowhere in the tree (static scan; dynamic dispatch, reflection, and out-of-tree importers are not visible)"},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": rel}, "region": {"startLine": line}}}],
            "properties": {"name": name, "kind": kind.replace("Def", "").lower(), "confidence": "static"},
        })
    results.sort(key=lambda r: (r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["properties"]["name"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "dead-code-finder", "version": "0.1.0"}}, "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
