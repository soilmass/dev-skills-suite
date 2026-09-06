#!/usr/bin/env python3
"""Find import cycles in a repository, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    find_import_cycles.py <repo> [--lang python|js|auto]
                           [--exclude dir,dir] [--max-cycles N]

Effect Ladder rung 1 (SDS-S-060): files are read; nothing is run.

Builds a directed module graph: Python imports via `ast` (`import a.b`,
`from a.b import c`, and relative imports resolved against the
importing file's package directory), and JavaScript/TypeScript
imports via a pattern over `import ... from '...'`, bare `import
'...'`, `export ... from '...'`, and `require('...')` — only relative
specifiers (`./`, `../`) are resolved; a bare specifier is external
and ignored. `--lang` (default `auto`) scans Python only, JavaScript
only, or both.

Tarjan's algorithm finds the graph's strongly connected components.
Every component of two or more modules is one `arch/import-cycle`
finding (severity error for three or more modules, warning for two);
a module that imports itself is one `arch/self-import` finding
(warning); a relative import that resolves to no module inside the
repository is one `arch/unresolved-import` finding (info) — an
unresolved absolute import is external and is not reported.
`tool.properties` carries the module and edge counts, the total
number of cycles found (import-cycles and self-imports together)
before `--max-cycles` truncates the list, the largest cycle's size,
and whether the list was truncated.

Prints one finding-list; a repository with no cycles yields an empty
`results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a
path that is not a directory (repo-invalid), a Python file that does
not parse (source-unparseable), a `--lang` value other than python,
js, or auto (lang-invalid), or an `--exclude` list with an empty
entry such as `,,` (exclude-invalid).
"""
import ast
import json
import os
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".venv", "venv"}
JS_EXTS = [".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"]
LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2, "hint": 3}

JS_IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:[^'";]*?\sfrom\s+)?['"]([^'"]+)['"]"""
    r"""|require\(\s*['"]([^'"]+)['"]\s*\)"""
)


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def gather_files(root, want_py, want_js, exclude):
    py_files, js_files = [], []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        if want_py and p.suffix == ".py":
            py_files.append(rel)
        elif want_js and p.suffix in JS_EXTS:
            js_files.append(rel)
    return py_files, js_files


def resolve_absolute_py(dotted, root, extra_name=None):
    parts = dotted.split(".")
    base = root.joinpath(*parts)
    candidates = [base.with_suffix(".py"), base / "__init__.py"]
    if extra_name:
        candidates.append(root.joinpath(*parts, extra_name).with_suffix(".py"))
    for c in candidates:
        if c.is_file():
            return c.relative_to(root).as_posix()
    return None


def resolve_relative_py(level, module, name, importing_rel, root):
    target_dir = importing_rel.parent
    for _ in range(level - 1):
        target_dir = target_dir.parent
    if module:
        parts = module.split(".")
        base = root / target_dir
        base = base.joinpath(*parts)
        candidates = [base.with_suffix(".py"), base / "__init__.py", base.joinpath(name).with_suffix(".py")]
    else:
        base = (root / target_dir / name)
        candidates = [base.with_suffix(".py"), base / "__init__.py"]
    for c in candidates:
        if c.is_file():
            return c.relative_to(root).as_posix()
    return None


def py_edges(rel, root):
    """Yield (target_or_None, lineno, unresolved_name_or_None) for each
    import in the file at rel."""
    text = (root / rel).read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(rel))
    except SyntaxError as e:
        sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = resolve_absolute_py(alias.name, root)
                if target:
                    yield target, node.lineno, None
                # an unresolved plain "import x" is external -> ignored
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names if a.name != "*"]
            if node.level == 0:
                if not node.module or not names:
                    continue
                for name in names:
                    target = resolve_absolute_py(node.module, root, extra_name=name)
                    if target:
                        yield target, node.lineno, None
                    # an unresolved absolute "from x import y" is external -> ignored
            else:
                if not names:
                    continue
                for name in names:
                    target = resolve_relative_py(node.level, node.module, name, rel, root)
                    if target:
                        yield target, node.lineno, None
                    else:
                        label = "." * node.level + (node.module + "." if node.module else "") + name
                        yield None, node.lineno, label


def resolve_js(importing_rel, spec, root):
    importing_dir = (root / importing_rel).parent
    norm = Path(os.path.normpath(str(importing_dir / spec)))
    if norm.suffix in JS_EXTS and norm.is_file():
        return norm.relative_to(root).as_posix()
    for ext in JS_EXTS:
        c = Path(str(norm) + ext)
        if c.is_file():
            return c.relative_to(root).as_posix()
    for ext in JS_EXTS:
        c = norm / f"index{ext}"
        if c.is_file():
            return c.relative_to(root).as_posix()
    return None


def js_edges(rel, root):
    """Yield (target_or_None, lineno, unresolved_spec_or_None) for each
    relative import/require in the file at rel. Bare specifiers are
    external and are not yielded at all."""
    text = (root / rel).read_text(encoding="utf-8", errors="replace")
    for m in JS_IMPORT_RE.finditer(text):
        spec = m.group(1) or m.group(2)
        if not (spec.startswith("./") or spec.startswith("../")):
            continue
        line = text.count("\n", 0, m.start()) + 1
        target = resolve_js(rel, spec, root)
        if target:
            yield target, line, None
        else:
            yield None, line, spec


def strongly_connected_components(graph, nodes):
    """Tarjan's algorithm, iterative to avoid recursion-depth limits."""
    index_of, lowlink, on_stack, indexer = {}, {}, {}, [0]
    stack, call_stack, sccs = [], [], []

    for start in sorted(nodes):
        if start in index_of:
            continue
        call_stack.append((start, iter(sorted(graph.get(start, ())))))
        index_of[start] = lowlink[start] = indexer[0]
        indexer[0] += 1
        stack.append(start)
        on_stack[start] = True
        while call_stack:
            v, it = call_stack[-1]
            advanced = False
            for w in it:
                if w not in index_of:
                    index_of[w] = lowlink[w] = indexer[0]
                    indexer[0] += 1
                    stack.append(w)
                    on_stack[w] = True
                    call_stack.append((w, iter(sorted(graph.get(w, ())))))
                    advanced = True
                    break
                elif on_stack.get(w):
                    lowlink[v] = min(lowlink[v], index_of[w])
            if advanced:
                continue
            call_stack.pop()
            if call_stack:
                parent = call_stack[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[v])
            if lowlink[v] == index_of[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    comp.append(w)
                    if w == v:
                        break
                sccs.append(comp)
    return sccs


def order_cycle(comp, graph):
    comp_set = set(comp)
    start = min(comp)
    order, current, seen = [start], start, {start}
    while len(order) < len(comp):
        nxts = sorted(n for n in graph.get(current, ()) if n in comp_set and n not in seen)
        if not nxts:
            break
        order.append(nxts[0])
        seen.add(nxts[0])
        current = nxts[0]
    return order


def main():
    args = sys.argv[1:]
    opts = {"--lang": None, "--exclude": None, "--max-cycles": None}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: find_import_cycles.py <repo> [--lang python|js|auto] [--exclude dir,dir] [--max-cycles N]")

    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")

    lang = opts["--lang"] or "auto"
    if lang not in ("python", "js", "auto"):
        sys.exit(f"ERROR: --lang must be python, js, or auto (lang-invalid): {lang!r}")

    exclude = set()
    if opts["--exclude"] is not None:
        parts = opts["--exclude"].split(",")
        if any(p.strip() == "" for p in parts):
            sys.exit(f"ERROR: --exclude entries must be non-empty, comma-separated directory names (exclude-invalid): {opts['--exclude']!r}")
        exclude = {p.strip() for p in parts}

    max_cycles = None
    if opts["--max-cycles"] is not None:
        try:
            max_cycles = int(opts["--max-cycles"])
        except ValueError:
            sys.exit(f"ERROR: --max-cycles must be an integer: {opts['--max-cycles']!r}")

    want_py, want_js = lang in ("python", "auto"), lang in ("js", "auto")
    py_files, js_files = gather_files(root, want_py, want_js, exclude)
    modules = sorted(p.as_posix() for p in py_files + js_files)

    graph = {}
    unresolved = []
    for rel in py_files:
        src = rel.as_posix()
        for target, line, label in py_edges(rel, root):
            if target:
                graph.setdefault(src, set()).add(target)
            else:
                unresolved.append((src, line, label))
    for rel in js_files:
        src = rel.as_posix()
        for target, line, label in js_edges(rel, root):
            if target:
                graph.setdefault(src, set()).add(target)
            else:
                unresolved.append((src, line, label))

    edges_total = sum(len(v) for v in graph.values())
    sccs = strongly_connected_components(graph, modules)

    cycle_records = []
    for comp in sccs:
        size = len(comp)
        self_loop = size == 1 and comp[0] in graph.get(comp[0], ())
        if size < 2 and not self_loop:
            continue
        comp_set = set(comp)
        edges_in = sum(1 for u in comp for v in graph.get(u, ()) if v in comp_set)
        order = order_cycle(comp, graph) if size > 1 else list(comp)
        cycle_records.append({"order": order, "size": size, "edges": edges_in, "self": self_loop})

    cycle_records.sort(key=lambda r: (-r["size"], r["order"][0]))
    total_cycles = len(cycle_records)
    largest_cycle = max((r["size"] for r in cycle_records), default=0)
    truncated = max_cycles is not None and total_cycles > max_cycles
    kept = cycle_records[:max_cycles] if max_cycles is not None else cycle_records

    out = []
    for rec in kept:
        order, size, edges_in = rec["order"], rec["size"], rec["edges"]
        if rec["self"]:
            out.append(finding(
                "arch/self-import", "warning",
                f"{order[0]} imports itself",
                order[0], None, {"modules": order, "size": size, "edges": edges_in},
            ))
        else:
            severity = "error" if size >= 3 else "warning"
            chain = " -> ".join(order + [order[0]])
            out.append(finding(
                "arch/import-cycle", severity,
                f"import cycle of {size} modules: {chain}",
                order[0], None, {"modules": order, "size": size, "edges": edges_in},
            ))

    for src, line, label in unresolved:
        out.append(finding(
            "arch/unresolved-import", "info",
            f"relative import {label!r} in {src} resolves to no module in the repository",
            src, line, {"name": label},
        ))

    out.sort(key=lambda x: (LEVEL_ORDER[x["level"]], x["ruleId"], x["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], json.dumps(x["properties"], sort_keys=True)))

    print(json.dumps({
        "version": "sds-finding-list-1.0",
        "runs": [{
            "tool": {
                "driver": {"name": "import-cycle-finder", "version": "0.1.0"},
                "properties": {
                    "modules": len(modules),
                    "edges": edges_total,
                    "cycles": total_cycles,
                    "largestCycle": largest_cycle,
                    "truncated": truncated,
                },
            },
            "results": out,
        }],
    }, indent=2))


if __name__ == "__main__":
    main()
