#!/usr/bin/env bash
# Rebuilds the git fixture for branch-hygiene's evals (SDS-S-096: a git
# repository cannot be checked in as a static fixture, so it is generated
# and its directory is listed in evals/fixtures/.gitignore).
#
#   evals/fixtures/build-branch-fixtures.sh
#
# Produces hygiene-remote.git (bare origin) and hygiene-work/ with:
#   main                       the base
#   feature/merged             merged into main            -> branch/merged
#   feature/stale              unmerged, committed 2026-01-15 -> branch/stale (as-of 2026-09-06)
#   feature/active             unmerged, committed 2026-09-01 -> nothing
#   feature/gone               upstream deleted on the remote  -> branch/gone-upstream
# Commit dates are pinned with GIT_COMMITTER_DATE so staleness is
# deterministic under --as-of.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf hygiene-remote.git hygiene-work
export GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=test@example.com \
       GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=test@example.com

git init -q --bare -b main hygiene-remote.git
git init -q -b main hygiene-work
cd hygiene-work
git remote add origin ../hygiene-remote.git

commit() { # <date> <message>
  export GIT_AUTHOR_DATE="$1T12:00:00Z" GIT_COMMITTER_DATE="$1T12:00:00Z"
  echo "$2" >> log.txt; git add log.txt; git commit -qm "$2"
}

commit 2026-01-01 "root"
git checkout -qb feature/merged; commit 2026-01-10 "merged work"
git checkout -q main; git merge -q --no-ff -m "merge feature/merged" feature/merged
git checkout -qb feature/stale main; commit 2026-01-15 "old unmerged work"
git checkout -qb feature/active main; commit 2026-09-01 "recent unmerged work"
git checkout -qb feature/gone main; commit 2026-08-20 "pushed then deleted upstream"
git checkout -q main
git push -q -u origin main feature/merged feature/stale feature/active feature/gone
git push -q origin --delete feature/gone
git fetch -q --prune origin
echo "Branch fixtures rebuilt at $(pwd)"
