#!/usr/bin/env python3
"""Find structural smells in Python test functions, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    find_test_smells.py <repo-path> [--exclude dir,dir]

Scans files named `test_*.py` or `*_test.py` (and anything under a
`tests/` directory) with `ast` only — nothing is imported or run
(Effect Ladder rung 1, SDS-S-060). A test function is a `def test_*`
at module scope or inside a class. Rules emitted:

    test/no-assertion         the body contains no `assert`, no
                              `pytest.raises`/`pytest.warns` context,
                              no `self.assert*`/`self.fail` call, and no
                              call to a helper whose name starts with
                              `assert` or `check` -> warning
    test/sleep-in-test        a call to `time.sleep`/`sleep`/
                              `asyncio.sleep` -> warning (a timing
                              dependency; the usual root of flakiness)
    test/swallowed-exception  a `try` whose handler is bare `except:`
                              or `except Exception:` with a body of
                              only `pass`/`return` -> warning
    test/conditional-logic    an `if`, `for`, or `while` at the test's
                              top level -> info (a test that branches
                              tests more than one thing, or nothing)

Fixtures (`@pytest.fixture`) and helpers are not tests and draw
nothing. Whether a smell is a fault — a sleep that waits on a real
clock versus a documented rate limit — is the skill's Analyze stage
(SDS-S-061).

Prints one finding-list; a tree with clean tests yields an empty
`results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a
path that is not a directory (repo-invalid) or a test file that does
not parse (source-unparseable).
"""
import ast
import json
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
SLEEPS = {"sleep"}


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def is_test_file(rel):
    return rel.name.startswith("test_") or rel.name.endswith("_test.py") or "tests" in rel.parts


def call_name(node):
    f = node.func
    if isinstance(f, ast.Name):
        return f.id, None
    if isinstance(f, ast.Attribute):
        base = f.value.id if isinstance(f.value, ast.Name) else None
        return f.attr, base
    return None, None


def test_functions(tree):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test"):
                    yield f"{node.name}.{sub.name}", sub


def scan(tree, rel):
    results = []
    for name, fn in test_functions(tree):
        asserts = 0
        sleeps = []
        swallowed = []
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Assert):
                asserts += 1
            elif isinstance(sub, ast.Call):
                n, base = call_name(sub)
                if n and (n.startswith("assert") or n.startswith("check") or n == "fail" or n in ("raises", "warns")):
                    asserts += 1
                if n in SLEEPS:
                    sleeps.append(sub.lineno)
            elif isinstance(sub, ast.With):
                for item in sub.items:
                    if isinstance(item.context_expr, ast.Call):
                        n, _ = call_name(item.context_expr)
                        if n in ("raises", "warns", "assertRaises"):
                            asserts += 1
            elif isinstance(sub, ast.Try):
                for h in sub.handlers:
                    broad = h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ("Exception", "BaseException"))
                    trivial = all(isinstance(s, (ast.Pass, ast.Return)) for s in h.body)
                    if broad and trivial:
                        swallowed.append(h.lineno)
        if asserts == 0:
            results.append(finding("test/no-assertion", "warning",
                                   f"{name}() asserts nothing; it can only fail by raising",
                                   rel, fn.lineno, {"test": name}))
        for ln in sleeps:
            results.append(finding("test/sleep-in-test", "warning",
                                   f"{name}() sleeps at line {ln}; it depends on wall-clock timing",
                                   rel, ln, {"test": name}))
        for ln in swallowed:
            results.append(finding("test/swallowed-exception", "warning",
                                   f"{name}() catches a broad exception at line {ln} and discards it; a failure there is invisible",
                                   rel, ln, {"test": name}))
        branches = [s for s in fn.body if isinstance(s, (ast.If, ast.For, ast.While, ast.AsyncFor))]
        if branches:
            results.append(finding("test/conditional-logic", "info",
                                   f"{name}() branches at its top level ({', '.join(type(b).__name__.lower() for b in branches)}); which case does it test?",
                                   rel, branches[0].lineno, {"test": name, "branches": len(branches)}))
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
        sys.exit("ERROR: usage: find_test_smells.py <repo-path> [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    results = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts) or not is_test_file(rel):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
        results += scan(tree, rel.as_posix())
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"]["region"]["startLine"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "test-smell-review", "version": "0.1.0"}}, "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
