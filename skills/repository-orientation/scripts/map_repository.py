#!/usr/bin/env python3
"""Collect the mechanical facts a newcomer needs to orient in a repository,
as one JSON object on stdout.

Usage:
    map_repository.py <repo-path> [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): files are read, nothing is run. The
output is this skill's own facts shape (assets/orientation.schema.json,
SDS-S-080), consumed by the skill's Analyze stage and by downstream
writers (readme-writer, onboarding-doc-generator) via --facts-file:

    languages     file counts by language, inferred from extension
                  (the same signal GitHub Linguist starts from)
    manifests     which build/dependency manifests exist and the
                  commands they declare — package.json "scripts",
                  pyproject [project.scripts] and tool sections,
                  Makefile targets, Cargo.toml / go.mod presence
    layout        top-level entries with file counts, and which of
                  the conventional directories exist (src, tests,
                  docs, scripts, .github/workflows)
    entryPoints   files conventionally treated as entry points
                  (main.py, __main__.py, app.py, manage.py, index.*,
                  server.*, cmd/*/main.go, main.rs)
    signals       presence of README, LICENSE, CONTRIBUTING, CHANGELOG,
                  CI workflows, a lockfile, tests

Prints the facts object; an empty directory yields zero counts and
empty lists, still schema-valid (SDS-C-033). Exit 1 with "ERROR: ..."
on stderr for a path that is not a directory (repo-invalid) or a
manifest that does not parse (manifest-malformed).
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache"}
LANG = {".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
        ".jsx": "JavaScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP",
        ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++", ".cs": "C#", ".swift": "Swift", ".sh": "Shell",
        ".bash": "Shell", ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".md": "Markdown", ".yml": "YAML",
        ".yaml": "YAML", ".json": "JSON", ".toml": "TOML", ".xml": "XML", ".tf": "HCL", ".proto": "Protocol Buffers"}
ENTRY_NAMES = {"main.py", "__main__.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "index.js", "index.ts", "index.mjs",
               "server.js", "server.ts", "main.go", "main.rs", "Program.cs", "Main.java"}
MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_./-]+)\s*:(?!=)", re.M)


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
        sys.exit("ERROR: usage: map_repository.py <repo-path> [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")

    files = []
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        if p.is_file():
            files.append(rel)
    files.sort()

    languages = Counter(LANG[f.suffix] for f in files if f.suffix in LANG)
    top = Counter(f.parts[0] for f in files)
    layout = {"topLevel": [{"name": n, "files": c, "kind": "directory" if (root / n).is_dir() else "file"} for n, c in sorted(top.items())],
              "conventional": {d: (root / d).is_dir() for d in ("src", "lib", "tests", "test", "docs", "scripts", ".github/workflows")}}

    manifests = []
    def read_json(rel):
        try:
            return json.loads((root / rel).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            sys.exit(f"ERROR: {rel} does not parse (manifest-malformed): {e}")
    def read_toml(rel):
        try:
            return tomllib.loads((root / rel).read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            sys.exit(f"ERROR: {rel} does not parse (manifest-malformed): {e}")

    if (root / "package.json").is_file():
        pkg = read_json("package.json")
        manifests.append({"file": "package.json", "ecosystem": "npm", "name": pkg.get("name"),
                          "commands": [{"name": k, "command": v} for k, v in (pkg.get("scripts") or {}).items()]})
    if (root / "pyproject.toml").is_file():
        py = read_toml("pyproject.toml")
        proj = py.get("project") or {}
        tools = sorted((py.get("tool") or {}).keys())
        manifests.append({"file": "pyproject.toml", "ecosystem": "python", "name": proj.get("name"),
                          "commands": [{"name": k, "command": v} for k, v in (proj.get("scripts") or {}).items()],
                          "tools": tools})
    if (root / "Cargo.toml").is_file():
        cargo = read_toml("Cargo.toml")
        manifests.append({"file": "Cargo.toml", "ecosystem": "cargo", "name": (cargo.get("package") or {}).get("name"), "commands": []})
    if (root / "go.mod").is_file():
        first = (root / "go.mod").read_text(encoding="utf-8").splitlines()[:1]
        manifests.append({"file": "go.mod", "ecosystem": "go", "name": first[0].split()[-1] if first and first[0].startswith("module") else None, "commands": []})
    if (root / "Makefile").is_file():
        text = (root / "Makefile").read_text(encoding="utf-8")
        targets = [t for t in MAKE_TARGET_RE.findall(text) if not t.startswith(".")]
        manifests.append({"file": "Makefile", "ecosystem": "make", "name": None,
                          "commands": [{"name": t, "command": f"make {t}"} for t in dict.fromkeys(targets)]})

    entry_points = [f.as_posix() for f in files if f.name in ENTRY_NAMES or (len(f.parts) >= 3 and f.parts[0] == "cmd" and f.name == "main.go")]

    names = {f.as_posix() for f in files}
    lower = {n.lower(): n for n in names}
    def has(prefix):
        return any(n.split("/")[0].lower().startswith(prefix) for n in names if "/" not in n)
    signals = {
        "readme": has("readme"), "license": has("license") or has("copying"), "contributing": has("contributing"),
        "changelog": has("changelog"),
        "ci": any(n.startswith(".github/workflows/") for n in names),
        "lockfile": any(n in lower for n in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "cargo.lock", "go.sum", "pipfile.lock")),
        "tests": any(part in ("tests", "test", "__tests__", "spec") for f in files for part in f.parts[:-1]) or any(f.name.startswith("test_") or f.name.endswith("_test.py") or ".test." in f.name or ".spec." in f.name for f in files),
    }

    print(json.dumps({"version": "repository-orientation-1.0", "repository": root.name, "fileCount": len(files),
                      "languages": [{"language": l, "files": c} for l, c in languages.most_common()],
                      "manifests": manifests, "layout": layout, "entryPoints": entry_points, "signals": signals}, indent=2))


if __name__ == "__main__":
    main()
