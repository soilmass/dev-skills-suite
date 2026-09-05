#!/usr/bin/env bash
# Rebuilds the local git fixture used by pr-description-writer's evals.
#
# A git repository cannot be checked into this repository as static
# fixture files: a nested .git directory becomes a gitlink (submodule
# reference), not tracked content, so the fixture would silently break
# for anyone who fresh-clones the parent repo. Regenerate it instead:
#
#   evals/fixtures/build-sample-repo.sh
#
# Idempotent: safe to re-run, it recreates the fixture from scratch
# each time. The resulting directory is gitignored (see
# evals/fixtures/.gitignore) — it is generated, not checked in.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf sample-repo
mkdir sample-repo
cd sample-repo

git init -q
git config user.email "test@example.com"
git config user.name "Test"

echo "hello" > README.md
git add README.md
git commit -qm "chore: initial commit"
git branch -m main

git checkout -qb feature/add-retry-logic
cat > retry.py <<'EOF'
def with_retry(fn, attempts=3):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
EOF
git add retry.py
git commit -qm "feat: add retry helper with exponential backoff"

cat >> README.md <<'EOF'

## Retry helper
See retry.py for the with_retry() utility.
EOF
git add README.md
git commit -qm "docs: document the retry helper"

echo "Fixture rebuilt at $(pwd)"
