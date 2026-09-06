#!/usr/bin/env python3
"""Compare the translation keys the code references with the message
catalogs, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    inventory_i18n.py <repo-path> --catalogs <dir> [--base en] [--patterns <patterns.json>] [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): files are read; nothing is run.
References are found by call shape — a function or method named in
the patterns' `translateFunctions` (t, _, gettext, i18n.t, translate,
formatMessage, …) whose first argument is a string literal — in Python
via `ast` and in JavaScript/TypeScript via a pattern. Catalogs are
`<dir>/<locale>.json` files: flat `{"key": "text"}` or nested objects
whose paths are joined with dots (`nav.home`), as i18next, vue-i18n,
and react-intl exports look. `--base` (default `en`) names the source
locale.

Rules emitted:

    i18n/missing-key         a key the code references is absent from
                             the base catalog -> error (the user sees
                             the key)
    i18n/unused-key          a base-catalog key no code references ->
                             info (stale, or built dynamically —
                             Analyze decides)
    i18n/untranslated        a base key absent from another locale's
                             catalog -> warning, one finding per locale
                             listing the keys (the user sees the base
                             language or the key)
    i18n/placeholder-mismatch a translation whose placeholders
                             ({name}, {{name}}, %(name)s, %s) differ
                             from the base text's -> warning (a runtime
                             error or a garbled sentence)
    i18n/dynamic-key         a translate call whose first argument is
                             not a literal -> info (the inventory
                             cannot see which keys it needs)

`tool.properties` carries the locales, key counts, coverage per
locale, and the referencing files. Deciding whether an unused key is
built dynamically, and which locale's gaps block a release, is the
skill's Analyze stage (SDS-S-061).

Prints one finding-list; a tree and catalogs in agreement yield an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a path that is not a directory (repo-invalid), a catalogs
directory without the base locale (catalog-missing), a catalog that
does not parse (catalog-unparseable), a Python file that does not
parse (source-unparseable), or a patterns file that is not the
expected shape (patterns-invalid).
"""
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv", "coverage"}
JS_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte"}
PLACEHOLDER_RE = re.compile(r"\{\{\s*[\w.]+\s*\}\}|\{[\w.]+\}|%\(\w+\)[sd]|%[sd]")


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def flat(obj):
    def rec(o, pre):
        out = {}
        for k, v in o.items():
            key = f"{pre}.{k}" if pre else str(k)
            if isinstance(v, dict):
                out.update(rec(v, key))
            else:
                out[key] = "" if v is None else str(v)
        return out
    return rec(obj, "")


def placeholders(text):
    return sorted(set(m.group(0).replace(" ", "") for m in PLACEHOLDER_RE.finditer(text)))


def py_refs(tree, rel, names):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            fname = None
            if isinstance(f, ast.Name):
                fname = f.id
            elif isinstance(f, ast.Attribute):
                fname = f.attr
                base = f.value.id if isinstance(f.value, ast.Name) else None
                if base and f"{base}.{f.attr}" in names:
                    fname = f"{base}.{f.attr}"
            if fname in names and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    yield a.value, rel, node.lineno, True
                else:
                    yield None, rel, node.lineno, False


def js_refs(text, rel, names):
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    rx = re.compile(r"(?<![\w.$])(" + alts + r")\(\s*(?:(['\"`])([^'\"`]+)\2|([^'\"`)\s][^,)]*))")
    for m in rx.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        if m.group(3) is not None and not (m.group(2) == "`" and "${" in m.group(3)):
            yield m.group(3), rel, line, True
        else:
            yield None, rel, line, False


def main():
    args = sys.argv[1:]
    opts = {"--catalogs": None, "--base": "en", "--patterns": None, "--exclude": ""}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or not opts["--catalogs"]:
        sys.exit("ERROR: usage: inventory_i18n.py <repo-path> --catalogs <dir> [--base en] [--patterns F] [--exclude dir,dir]")
    root, cat_dir = Path(args[0]), Path(opts["--catalogs"])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    if not cat_dir.is_dir():
        sys.exit(f"ERROR: catalogs path is not a directory (catalog-missing): {cat_dir}")
    pp = opts["--patterns"] or str(Path(__file__).resolve().parent.parent / "assets" / "translate-patterns.json")
    try:
        names = set(json.loads(Path(pp).read_text(encoding="utf-8"))["translateFunctions"])
        assert names
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: patterns {pp} must be {{translateFunctions: [names]}} (patterns-invalid): {e}")
    catalogs = {}
    for f in sorted(cat_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            assert isinstance(data, dict)
        except Exception as e:  # noqa: BLE001
            sys.exit(f"ERROR: catalog {f.name} does not parse as a JSON object (catalog-unparseable): {e}")
        catalogs[f.stem] = flat(data)
    base = opts["--base"]
    if base not in catalogs:
        sys.exit(f"ERROR: no {base}.json in {cat_dir} (catalog-missing); locales found: {', '.join(sorted(catalogs)) or 'none'}")
    exclude = {x.strip() for x in opts["--exclude"].split(",") if x.strip()}
    cat_abs = cat_dir.resolve()
    refs, dynamic = defaultdict(list), []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts) or cat_abs in p.resolve().parents:
            continue
        if p.suffix == ".py":
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            except SyntaxError as e:
                sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
            items = py_refs(tree, rel.as_posix(), names)
        elif p.suffix in JS_EXT:
            items = js_refs(p.read_text(encoding="utf-8", errors="replace"), rel.as_posix(), names)
        else:
            continue
        for key, r, line, literal in items:
            if literal:
                refs[key].append((r, line))
            else:
                dynamic.append((r, line))
    base_keys = set(catalogs[base])
    out = []
    for key in sorted(refs):
        if key not in base_keys:
            r, line = sorted(refs[key])[0]
            out.append(finding("i18n/missing-key", "error", f"{key!r} is referenced in {len(refs[key])} place(s) but absent from {base}.json; users see the key", r, line, {"key": key, "references": len(refs[key])}))
    for key in sorted(base_keys - set(refs)):
        out.append(finding("i18n/unused-key", "info", f"{key!r} is in {base}.json but referenced nowhere; stale, or built dynamically", f"{base}.json", None, {"key": key}))
    coverage = {}
    for loc, cat in sorted(catalogs.items()):
        if loc == base:
            continue
        missing = sorted(base_keys - set(cat))
        coverage[loc] = round(1 - len(missing) / len(base_keys), 3) if base_keys else 1.0
        if missing:
            out.append(finding("i18n/untranslated", "warning", f"{loc}.json lacks {len(missing)} of {len(base_keys)} base key(s): {', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}", f"{loc}.json", None, {"locale": loc, "missing": missing}))
        for key in sorted(base_keys & set(cat)):
            pb, pl = placeholders(catalogs[base][key]), placeholders(cat[key])
            if pb != pl:
                out.append(finding("i18n/placeholder-mismatch", "warning", f"{loc}.json {key!r}: placeholders {pl} differ from the base's {pb}", f"{loc}.json", None, {"locale": loc, "key": key, "base": pb, "translation": pl}))
    for r, line in dynamic:
        out.append(finding("i18n/dynamic-key", "info", "translate call with a non-literal key; the inventory cannot see which keys it needs", r, line, {}))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda x: (order[x["level"]], x["ruleId"], x["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], x["properties"].get("key", x["properties"].get("locale", ""))))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "i18n-string-inventory", "version": "0.1.0"},
                                         "properties": {"base": base, "locales": sorted(catalogs), "baseKeys": len(base_keys), "referencedKeys": len(refs), "dynamicCalls": len(dynamic), "coverage": coverage}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
