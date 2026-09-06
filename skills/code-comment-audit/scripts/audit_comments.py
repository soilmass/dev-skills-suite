#!/usr/bin/env python3
"""Find comments and docstrings that have drifted from the Python code
beside them, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    audit_comments.py <repo-path> [--exclude dir,dir]

Three deterministic detectors (Effect Ladder rung 1; `ast` and
`tokenize` only, nothing is imported or run — SDS-S-060):

    comment/stale-param        a function docstring documents a
                               parameter (":param x:", "x (type):",
                               "x:" under an Args:/Arguments: heading)
                               that the signature does not have
                               -> warning
    comment/dangling-reference a `#` comment names an identifier
                               (backticked, or a bare snake_case/
                               CamelCase token of 4+ chars with an
                               underscore or a call parenthesis) that
                               is defined nowhere in the tree
                               -> warning (a small denylist,
                               COMMON_PROPER_NOUNS, exempts
                               CamelCase-shaped product/protocol names
                               like GitHub and PyYAML that are prose,
                               never a symbol in this tree)
    comment/commented-out-code a run of 2+ consecutive `#` lines that
                               parse as Python statements once the
                               `#` is stripped
                               -> info

Whether a stale comment actually misleads a reader is the skill's
Analyze stage (SDS-S-061); this script only reports the mismatch and
its evidence in properties.

Prints one finding-list; a tree with no drift yields an empty
`results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a
path that is not a directory (repo-invalid) or a file that does not
parse (source-unparseable).
"""
import ast
import io
import json
import re
import sys
import textwrap
import tokenize
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
PARAM_RE = re.compile(r"^\s*(?::param\s+(\w+)\s*:|(\w+)\s*\([^)]*\)\s*:|(\w+)\s*:\s)", re.M)
IDENT_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`|\b([a-z]+_[a-z0-9_]+|[A-Z][a-z]+[A-Z][A-Za-z0-9]*)\b|\b([A-Za-z_][A-Za-z0-9_]{3,})\(")
COMMON_WORDS = {"e_g", "i_e", "to_do", "note_that", "as_is"}
# Proper nouns that are CamelCase-shaped (matched by IDENT_RE's identifier
# heuristic) but name a product, protocol, or library rather than a symbol
# in this tree — found dogfooding this skill on the family repository's
# own comments (GitHub, PyYAML, OpenAPI all mentioned in prose, none ever
# claimed to be defined here).
COMMON_PROPER_NOUNS = {"github", "pyyaml", "openapi"}


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def documented_params(doc):
    names = set()
    in_args = False
    for line in doc.splitlines():
        if re.match(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", line):
            in_args = True
            continue
        if re.match(r"^\s*(Returns|Raises|Yields|Examples?|Notes?|Attributes)\s*:\s*$", line):
            in_args = False
            continue
        m = re.match(r"^\s*:param\s+(\w+)\s*:", line)
        if m:
            names.add(m.group(1))
            continue
        if in_args:
            m = re.match(r"^\s{2,}(\w+)\s*(\([^)]*\))?\s*:", line)
            if m:
                names.add(m.group(1))
    return names


def scan_file(p, rel, defined_names):
    results = []
    src = p.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(p))
    except SyntaxError as e:
        sys.exit(f"ERROR: {rel} does not parse (source-unparseable): {e}")
    # stale documented params
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if not doc:
                continue
            actual = {a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}
            if node.args.vararg:
                actual.add(node.args.vararg.arg)
            if node.args.kwarg:
                actual.add(node.args.kwarg.arg)
            for name in sorted(documented_params(doc) - actual):
                results.append(finding("comment/stale-param", "warning",
                                       f"{node.name}() documents parameter {name!r} but does not take it (actual: {', '.join(sorted(actual)) or 'none'})",
                                       rel, node.lineno, {"function": node.name, "documented": name, "actual": sorted(actual)}))
    # comment analysis via tokenize
    comments = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            # keep the text's own indentation (strip only "#" and one space)
            # so a commented-out block still parses as a suite
            comments.append((tok.start[0], re.sub(r"^ ?", "", tok.string[1:], count=1).rstrip()))
    for line, text in comments:
        for m in IDENT_RE.finditer(text):
            name = (m.group(1) or m.group(2) or m.group(3) or "").split(".")[-1]
            if not name or name.lower() in COMMON_WORDS or name.lower() in COMMON_PROPER_NOUNS or name.upper() == name:
                continue
            if name not in defined_names and name not in dir(__builtins__):
                results.append(finding("comment/dangling-reference", "warning",
                                       f"comment refers to {name!r}, which is defined nowhere in the tree: '# {text[:80]}'",
                                       rel, line, {"reference": name, "comment": text[:160]}))
                break
    # commented-out code: runs of 2+ comment lines that parse as statements
    run = []
    def flush():
        if len(run) >= 2:
            body = textwrap.dedent("\n".join(t for _, t in run))
            parsed = None
            for candidate in (body, "def _wrapped():\n" + textwrap.indent(body, "    ")):
                # a block lifted from inside a function may contain return/yield,
                # which only parse inside a def
                try:
                    parsed = ast.parse(candidate)
                    break
                except SyntaxError:
                    continue
            if parsed is None:
                return
            if len(parsed.body) == 1 and isinstance(parsed.body[0], ast.FunctionDef) and parsed.body[0].name == "_wrapped":
                parsed.body = parsed.body[0].body
            if parsed.body and all(not isinstance(n, ast.Expr) or not isinstance(getattr(n, "value", None), ast.Constant) for n in parsed.body):
                results.append(finding("comment/commented-out-code", "info",
                                       f"{len(run)} consecutive comment lines parse as Python code; delete or restore, version control remembers it",
                                       rel, run[0][0], {"lines": len(run), "first": run[0][1][:80]}))
    prev = None
    for line, text in comments:
        if prev is not None and line == prev + 1:
            run.append((line, text))
        else:
            flush()
            run = [(line, text)]
        prev = line
    flush()
    return results


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
        sys.exit("ERROR: usage: audit_comments.py <repo-path> [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")

    files = [p for p in sorted(root.rglob("*.py")) if not any(part in SKIP_DIRS or part in exclude for part in p.relative_to(root).parts)]
    defined = set()
    for p in files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            sys.exit(f"ERROR: {p.relative_to(root)} does not parse (source-unparseable): {e}")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name):
                defined.add(node.id)
            elif isinstance(node, ast.Attribute):
                defined.add(node.attr)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    defined.add((a.asname or a.name).split(".")[-1])
    results = []
    for p in files:
        results += scan_file(p, str(p.relative_to(root)), defined)
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"]["region"]["startLine"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "code-comment-audit", "version": "0.1.0"}}, "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
