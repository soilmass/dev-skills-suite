#!/usr/bin/env python3
"""Inventory what a change touches, categorized for rollback planning.

Usage:
    inventory_change.py <repo-path> --range <base>..<head>
    inventory_change.py <repo-path> --diff-file <name-status.txt>

Reads `git diff --name-status <range>` (rung 2, domain-read-only) or,
with --diff-file (SDS-S-065), a file in that exact format (one
"<M|A|D|R...>\\t<path>[\\t<new path>]" line per file) and buckets each
path by what rolling it back would take:

    migration        migrations/**, db/**, *.sql, alembic/**, prisma/**
                     -> hint: "needs a down-migration or a verified
                        backup before the step that applies it"
    config           *.yaml/*.yml/*.toml/*.ini/*.env, config/**, .github/**
                     -> hint: "previous values must be captured before
                        the change, not reconstructed after"
    infrastructure   terraform/**, *.tf, k8s/**, helm/**, Dockerfile*,
                     docker-compose*
                     -> hint: "rollback is a re-apply of the previous
                        definition; confirm state is not drifted"
    dependency       package.json, package-lock.json, requirements*.txt,
                     pyproject.toml, Cargo.*, go.mod, go.sum
                     -> hint: "pin the previous versions; a lockfile
                        revert is the rollback"
    data             *.csv/*.json under data/**, fixtures/**, seeds/**
                     -> hint: "data changes are rarely reversible by
                        redeploy; plan an explicit restore"
    code             everything else
                     -> hint: "rollback is redeploying the previous
                        build; verify nothing above depends on it"
    deleted          any D entry, in addition to its category
                     -> hint: "deleted files come back only from
                        version control; note the commit"

Prints {"range", "files": [{"path", "status", "category"}],
"categories": {name: count}, "hints": [...]} — facts only; the plan's
steps and their order are the skill's Decide stage. No changed files
yields empty files/categories and no hints (SDS-C-033). Exit 1 with
"ERROR: ..." on stderr for a path that is not a git repository root
(repo-invalid) or an unreadable diff file (diff-unreadable).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

RULES = [
    ("migration", r"(^|/)(migrations?|db|alembic|prisma)/|\.sql$"),
    ("infrastructure", r"(^|/)(terraform|k8s|kubernetes|helm)/|\.tf$|(^|/)Dockerfile|(^|/)docker-compose"),
    ("dependency", r"(^|/)(package(-lock)?\.json|requirements[^/]*\.txt|pyproject\.toml|Cargo\.(toml|lock)|go\.(mod|sum))$"),
    ("data", r"(^|/)(data|fixtures|seeds)/.*\.(csv|json|ya?ml)$"),
    ("config", r"\.(ya?ml|toml|ini|env)$|(^|/)config/|(^|/)\.github/"),
]
HINTS = {
    "migration": "needs a down-migration or a verified backup before the step that applies it",
    "config": "previous values must be captured before the change, not reconstructed after",
    "infrastructure": "rollback is a re-apply of the previous definition; confirm state is not drifted",
    "dependency": "pin the previous versions; a lockfile revert is the rollback",
    "data": "data changes are rarely reversible by redeploy; plan an explicit restore",
    "code": "rollback is redeploying the previous build; verify nothing above depends on it",
    "deleted": "deleted files come back only from version control; note the commit",
}


def categorize(path):
    for name, pattern in RULES:
        if re.search(pattern, path):
            return name
    return "code"


def read_git(repo, rng):
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        sys.exit(f"ERROR: not a git repository (repo-invalid): {repo}: {e}")
    if Path(top).resolve() != Path(repo).resolve():
        sys.exit(f"ERROR: not a git repository root (repo-invalid): {repo} (root is {top})")
    r = subprocess.run(["git", "diff", "--name-status", rng], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: git diff failed for range {rng} (repo-invalid): {r.stderr.strip()}")
    return r.stdout


def main():
    args = sys.argv[1:]
    def take(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return None
    rng = take("--range")
    diff_file = take("--diff-file")
    if len(args) != 1 or not (rng or diff_file):
        sys.exit("ERROR: usage: inventory_change.py <repo-path> (--range <base>..<head> | --diff-file <path>)")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")
    if diff_file:
        try:
            raw = Path(diff_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            sys.exit(f"ERROR: could not read diff file {diff_file} (diff-unreadable): {e}")
        rng = f"diff-file:{diff_file}"
    else:
        raw = read_git(repo, rng)

    files, counts, hints = [], {}, []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip():
            continue
        status, path = parts[0].strip(), parts[-1].strip()
        cat = categorize(path)
        files.append({"path": path, "status": status, "category": cat})
        counts[cat] = counts.get(cat, 0) + 1
        if status.startswith("D"):
            counts["deleted"] = counts.get("deleted", 0) + 1
    for cat in counts:
        h = f"{cat}: {HINTS[cat]}"
        if h not in hints:
            hints.append(h)
    print(json.dumps({"range": rng, "files": files, "categories": counts, "hints": hints}, indent=2))


if __name__ == "__main__":
    main()
