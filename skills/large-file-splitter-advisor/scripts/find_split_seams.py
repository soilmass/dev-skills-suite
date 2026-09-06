#!/usr/bin/env python3
"""Find Python modules that exceed a line budget and propose where each
could be split, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    find_split_seams.py <repo-path> [--max-lines N] [--exclude dir,dir]

For every `.py` file over --max-lines (default 500; `ast` only, nothing
is imported or run — Effect Ladder rung 1, SDS-S-060) the script builds
a reference graph between the module's top-level definitions (a
function or class refers to another when its body names it), then
takes the connected components of that graph as candidate seams: a
component is a set of definitions that lean on each other and on
nothing else at top level, so it could move together. Components are
listed largest-first with their names and line span. Module-level
constants and imports are not nodes; every component may need some.

Rules emitted:

    size/oversized-module   a module over the budget -> warning;
                            properties carry lines, definitions,
                            and the seams
    size/single-cluster     an oversized module whose definitions form
                            one connected component -> info (no seam;
                            the split, if any, is by responsibility,
                            which is a human's call)

Whether a seam is a sensible module boundary — a cohesive concept with
a name, not an accident of the reference graph — is the skill's
Analyze stage (SDS-S-061); this script reports the graph.

Prints one finding-list; a tree with no oversized module yields an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a path that is not a directory (repo-invalid), a non-positive or non-integer --max-lines
(budget-invalid), or a file that does not parse (source-unparseable).
"""
import ast
import json
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def seams(tree):
    """Connected components over top-level definitions, by name reference."""
    defs = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs[node.name] = node
    names = set(defs)
    adj = {n: set() for n in names}
    for name, node in defs.items():
        for sub in ast.walk(node):
            ref = None
            if isinstance(sub, ast.Name):
                ref = sub.id
            elif isinstance(sub, ast.Attribute):
                ref = sub.attr
            if ref in names and ref != name:
                adj[name].add(ref)
                adj[ref].add(name)
    seen = set()
    comps = []
    for n in defs:  # source order, so components are stable
        if n in seen:
            continue
        stack, comp = [n], []
        seen.add(n)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in adj[cur]:
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        comp.sort(key=lambda x: defs[x].lineno)
        first, last = defs[comp[0]], defs[comp[-1]]
        comps.append({"definitions": comp,
                      "startLine": first.lineno,
                      "endLine": max(getattr(defs[c], "end_lineno", defs[c].lineno) for c in comp),
                      "lines": sum(getattr(defs[c], "end_lineno", defs[c].lineno) - defs[c].lineno + 1 for c in comp)})
    comps.sort(key=lambda c: (-c["lines"], c["startLine"]))
    return len(defs), comps


def main():
    args = sys.argv[1:]
    exclude = set()
    max_lines = 500
    for flag in ("--exclude", "--max-lines"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            if flag == "--exclude":
                exclude = {x.strip() for x in args[i + 1].split(",") if x.strip()}
            else:
                try:
                    max_lines = int(args[i + 1])
                except ValueError:
                    sys.exit("ERROR: --max-lines must be an integer (budget-invalid)")
                if max_lines < 1:
                    sys.exit("ERROR: --max-lines must be positive (budget-invalid)")
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: find_split_seams.py <repo-path> [--max-lines N] [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")

    files = [p for p in sorted(root.rglob("*.py")) if not any(part in SKIP_DIRS or part in exclude for part in p.relative_to(root).parts)]
    results = []
    for p in files:
        rel = str(p.relative_to(root))
        src = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, filename=str(p))
        except SyntaxError as e:
            sys.exit(f"ERROR: {rel} does not parse (source-unparseable): {e}")
        n_lines = src.count("\n") + (0 if src.endswith("\n") or not src else 1)
        if n_lines <= max_lines:
            continue
        n_defs, comps = seams(tree)
        props = {"lines": n_lines, "maxLines": max_lines, "definitions": n_defs, "seams": comps}
        if len(comps) >= 2:
            results.append(finding("size/oversized-module", "warning",
                                   f"{rel} is {n_lines} lines (budget {max_lines}); its {n_defs} definitions fall into {len(comps)} independent clusters — "
                                   + "; ".join(f"[{', '.join(c['definitions'][:4])}{'…' if len(c['definitions']) > 4 else ''}] ({c['lines']} lines)" for c in comps[:3]),
                                   rel, 1, props))
        else:
            results.append(finding("size/single-cluster", "info",
                                   f"{rel} is {n_lines} lines (budget {max_lines}) but its {n_defs} definitions all reference one another; no mechanical seam — a split, if any, is by responsibility",
                                   rel, 1, props))
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], -r["properties"]["lines"], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "large-file-splitter-advisor", "version": "0.1.0"}}, "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
