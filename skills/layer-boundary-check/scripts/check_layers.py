#!/usr/bin/env python3
"""Find architectural layer violations in a repository, as a
finding-list (kit/shapes/finding-list.schema.json).

Usage:
    check_layers.py <repo> --layers <layers.json> [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): files are read; nothing is run.

The layer map (see assets/layers.example.json for the shape) names the
`layers`, maps each to the repository-relative directory prefixes
under `paths`, and lists under `allowed` which other layers each layer
may import from. A layer missing from `allowed` may import nothing but
itself.

Builds the same directed module graph as the family's import-graph
resolver: Python imports via `ast` (absolute and relative, resolved
against the importing file's package directory), and
JavaScript/TypeScript imports via a pattern over `import ... from
'...'`, bare `import '...'`, `export ... from '...'`, and
`require('...')` — only relative specifiers (`./`, `../`) are
resolved; a bare specifier is external and ignored, as is an
unresolved absolute Python import.

Every source file (`.py` or a JavaScript/TypeScript extension) under
no `paths` prefix draws one `arch/unassigned-module` finding (info,
at most one per file). Every resolved import edge whose source and
target both fall under a `paths` prefix, in different layers, where
the target's layer is not in the source layer's `allowed` list, draws
one `arch/layer-violation` finding (error), located at the importing
file with `region.startLine` set to the import's line. A same-layer
import and an import that resolves to no in-repo module never fire.
`tool.properties` carries the layer names, the count of modules
assigned to a layer, the count left unassigned, and the violation
count.

Prints one finding-list; a repository with no violations and no
unassigned modules yields an empty `results` array (SDS-C-033). Exit 1
with "ERROR: ..." on stderr on failure: the repository path is not a
directory (repo-invalid); `--layers` is missing, its file is missing
or is not valid JSON, or its content fails the layer-map validation —
missing `layers`/`paths`/`allowed` keys, `layers` not a non-empty list
of unique strings, `paths` not covering every layer with a non-empty
list of directory prefixes, or `allowed` naming a layer not in
`layers` (layers-invalid); or a Python file does not parse
(source-unparseable).
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


def gather_files(root, exclude):
    py_files, js_files = [], []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        if p.suffix == ".py":
            py_files.append(rel)
        elif p.suffix in JS_EXTS:
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
    """Yield (target_or_None, lineno) for each import in the file at rel
    that resolves to a module inside the repository. An unresolved
    absolute import is external and is not yielded; an unresolved
    relative import is yielded with target None (also not fired on by
    the caller, since its layer cannot be determined)."""
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
                    yield target, node.lineno
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names if a.name != "*"]
            if node.level == 0:
                if not node.module or not names:
                    continue
                for name in names:
                    target = resolve_absolute_py(node.module, root, extra_name=name)
                    if target:
                        yield target, node.lineno
            else:
                if not names:
                    continue
                for name in names:
                    target = resolve_relative_py(node.level, node.module, name, rel, root)
                    if target:
                        yield target, node.lineno


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
    """Yield (target, lineno) for each relative import/require in the
    file at rel that resolves to a module inside the repository. A
    bare specifier is external and is not yielded at all; an
    unresolved relative specifier is skipped too."""
    text = (root / rel).read_text(encoding="utf-8", errors="replace")
    for m in JS_IMPORT_RE.finditer(text):
        spec = m.group(1) or m.group(2)
        if not (spec.startswith("./") or spec.startswith("../")):
            continue
        line = text.count("\n", 0, m.start()) + 1
        target = resolve_js(rel, spec, root)
        if target:
            yield target, line


def validate_layers(data):
    """Return an error string, or None if data is a well-formed layer
    map (see assets/layers.example.json)."""
    if not isinstance(data, dict):
        return "layer map must be a JSON object"
    missing = [k for k in ("layers", "paths", "allowed") if k not in data]
    if missing:
        return f"layer map is missing key(s): {', '.join(missing)}"

    layers = data["layers"]
    if not isinstance(layers, list) or not layers or not all(isinstance(x, str) and x for x in layers):
        return "'layers' must be a non-empty list of strings"
    if len(set(layers)) != len(layers):
        return "'layers' must not contain duplicate names"
    layer_set = set(layers)

    paths = data["paths"]
    if not isinstance(paths, dict):
        return "'paths' must be an object mapping each layer to a list of directory prefixes"
    for layer in layers:
        if layer not in paths:
            return f"'paths' has no entry for layer {layer!r}"
    for key, prefixes in paths.items():
        if key not in layer_set:
            return f"'paths' names layer {key!r}, which is not in 'layers'"
        if not isinstance(prefixes, list) or not prefixes or not all(isinstance(p, str) and p for p in prefixes):
            return f"'paths' entry for {key!r} must be a non-empty list of directory prefixes"

    allowed = data["allowed"]
    if not isinstance(allowed, dict):
        return "'allowed' must be an object mapping a layer to the layers it may import"
    for key, targets in allowed.items():
        if key not in layer_set:
            return f"'allowed' names layer {key!r}, which is not in 'layers'"
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            return f"'allowed' entry for {key!r} must be a list of layer names"
        for target in targets:
            if target not in layer_set:
                return f"'allowed' entry for {key!r} names layer {target!r}, which is not in 'layers'"
    return None


def layer_of(rel_posix, paths):
    """The layer whose paths entry has the longest matching prefix for
    rel_posix, or None if no prefix matches."""
    best, best_len = None, -1
    for layer, prefixes in paths.items():
        for prefix in prefixes:
            norm = prefix.rstrip("/")
            if rel_posix == norm or rel_posix.startswith(norm + "/"):
                if len(norm) > best_len:
                    best, best_len = layer, len(norm)
    return best


def main():
    args = sys.argv[1:]

    layers_path = None
    if "--layers" in args:
        i = args.index("--layers")
        if i + 1 >= len(args):
            sys.exit("ERROR: --layers requires a value (layers-invalid)")
        layers_path = args[i + 1]
        del args[i:i + 2]
    if layers_path is None:
        sys.exit("ERROR: --layers <file> is required (layers-invalid)")

    exclude = set()
    if "--exclude" in args:
        i = args.index("--exclude")
        if i + 1 >= len(args):
            sys.exit("ERROR: --exclude requires a value")
        parts = args[i + 1].split(",")
        del args[i:i + 2]
        exclude = {p.strip() for p in parts if p.strip()}

    if len(args) != 1:
        sys.exit("ERROR: usage: check_layers.py <repo> --layers <layers.json> [--exclude dir,dir]")

    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")

    try:
        layers_text = Path(layers_path).read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"ERROR: cannot read --layers file (layers-invalid): {layers_path}: {e}")
    try:
        layers_data = json.loads(layers_text)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: --layers file is not valid JSON (layers-invalid): {layers_path}: {e}")

    err = validate_layers(layers_data)
    if err:
        sys.exit(f"ERROR: {err} (layers-invalid)")

    layer_names = layers_data["layers"]
    paths = layers_data["paths"]
    allowed = layers_data["allowed"]

    py_files, js_files = gather_files(root, exclude)
    modules = sorted(p.as_posix() for p in py_files + js_files)

    edges = set()
    for rel in py_files:
        src = rel.as_posix()
        for target, line in py_edges(rel, root):
            edges.add((src, target, line))
    for rel in js_files:
        src = rel.as_posix()
        for target, line in js_edges(rel, root):
            edges.add((src, target, line))

    module_layer = {m: layer_of(m, paths) for m in modules}
    unassigned = sorted(m for m, layer in module_layer.items() if layer is None)

    violations = []
    for src, target, line in edges:
        from_layer = module_layer.get(src)
        to_layer = module_layer.get(target)
        if from_layer is None or to_layer is None:
            continue
        if from_layer == to_layer:
            continue
        if to_layer in allowed.get(from_layer, []):
            continue
        violations.append((src, target, line, from_layer, to_layer))

    out = []
    for src, target, line, from_layer, to_layer in violations:
        out.append(finding(
            "arch/layer-violation", "error",
            f"{src} (layer '{from_layer}') imports {target} (layer '{to_layer}'), which is not in allowed['{from_layer}']",
            src, line,
            {"fromLayer": from_layer, "toLayer": to_layer, "importer": src, "imported": target},
        ))
    for m in unassigned:
        out.append(finding(
            "arch/unassigned-module", "info",
            f"{m} is under no layer's path prefix",
            m, None,
            {"module": m},
        ))

    out.sort(key=lambda x: (LEVEL_ORDER[x["level"]], x["ruleId"], x["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], json.dumps(x["properties"], sort_keys=True)))

    print(json.dumps({
        "version": "sds-finding-list-1.0",
        "runs": [{
            "tool": {
                "driver": {"name": "layer-boundary-check", "version": "0.1.0"},
                "properties": {
                    "layers": layer_names,
                    "modules": len(modules) - len(unassigned),
                    "unassigned": len(unassigned),
                    "violations": len(violations),
                },
            },
            "results": out,
        }],
    }, indent=2))


if __name__ == "__main__":
    main()
