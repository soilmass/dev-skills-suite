#!/usr/bin/env python3
"""Map every call site a migration touches.

Usage:
    map_migration_scope.py <repo-path> --pattern <regex>
                           [--ext .py,.ts,...] [--exclude tests,vendor]

Walks the working tree (Effect Ladder rung 1) and reports every line
matching --pattern (the thing being migrated away from: a function
name, an import path, a table, a config key), grouped per file, with
the tests that reference it listed separately — because tests are
migrated last and are the safety net for the migrate phase.

Prints {"pattern", "totalSites", "files": [{"path", "sites": [{"line",
"text"}]}], "testFiles": [...same...], "hints": [...]} — facts only;
slicing the migration into shippable phases is the skill's Decide
stage (SDS-S-061). Zero matches -> totalSites 0 and empty arrays with
a "nothing to migrate" hint (SDS-C-033). Exit 1 with "ERROR: ..." on
stderr for a path that is not a directory (repo-invalid) or an invalid
regular expression (bad-argument).
"""
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state"}
DEFAULT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".sql", ".yaml", ".yml", ".toml"}
TEST_MARKERS = ("test", "tests", "spec", "__tests__")


def is_test(path):
    parts = [p.lower() for p in path.parts]
    return any(p in TEST_MARKERS for p in parts[:-1]) or path.name.lower().startswith(("test_", "spec_")) or path.stem.lower().endswith(("_test", ".test", ".spec", "_spec"))


def main():
    args = sys.argv[1:]
    def take(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value (bad-argument)")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    pattern = take("--pattern")
    ext = take("--ext")
    exclude = {e.strip() for e in (take("--exclude") or "").split(",") if e.strip()}
    if len(args) != 1 or not pattern:
        sys.exit("ERROR: usage: map_migration_scope.py <repo-path> --pattern <regex> [--ext .py,.ts] [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    try:
        rx = re.compile(pattern)
    except re.error as e:
        sys.exit(f"ERROR: invalid regular expression {pattern!r} (bad-argument): {e}")
    exts = {e if e.startswith(".") else f".{e}" for e in ext.split(",")} if ext else DEFAULT_EXT

    files, tests, total = [], [], 0
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        if not p.is_file() or p.suffix not in exts:
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        sites = [{"line": i, "text": l.strip()[:160]} for i, l in enumerate(lines, start=1) if rx.search(l)]
        if sites:
            total += len(sites)
            (tests if is_test(rel) else files).append({"path": str(rel), "sites": sites})

    hints = []
    if total == 0:
        hints.append("nothing to migrate: no call sites match; confirm the pattern before planning")
    else:
        hints.append(f"{len(files)} production file(s) and {len(tests)} test file(s) reference the old path")
        if not tests:
            hints.append("no tests reference the old path: the migrate phase has no safety net; add characterization tests in the expand phase")
        big = [f["path"] for f in files if len(f["sites"]) >= 10]
        if big:
            hints.append("high-density files (10+ sites) deserve their own migrate slice: " + ", ".join(big))
    print(json.dumps({"pattern": pattern, "totalSites": total, "files": files, "testFiles": tests, "hints": hints}, indent=2))


if __name__ == "__main__":
    main()
