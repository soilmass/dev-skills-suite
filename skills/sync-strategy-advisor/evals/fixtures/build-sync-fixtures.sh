#!/usr/bin/env bash
# Rebuilds the git fixtures for sync-strategy-advisor's evals (SDS-S-096:
# a git repository cannot be checked in as a static fixture, so it is
# generated; the output directories are listed in evals/fixtures/.gitignore).
#
#   evals/fixtures/build-sync-fixtures.sh
#
# Idempotent. Produces:
#   sync-remote.git   a bare "origin" whose main has commits A, B, C
#   sync-work/        a clone with one branch per scenario, all fetched:
#     feature/up-to-date        on C, pushed                 -> up-to-date
#     feature/behind            on B, pushed, nothing local  -> merge-base
#     feature/behind-unpushed   on B + 1 local commit        -> rebase-onto-base
#     feature/conflict          on B, edits C's line, local  -> resolve-conflicts
#     feature/unpushed          on C + 1 local commit, pushed base -> push
#     feature/local-only        on C + 1 commit, no upstream -> publish-branch
set -euo pipefail
cd "$(dirname "$0")"
rm -rf sync-remote.git sync-work
export GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=test@example.com \
       GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=test@example.com

git init -q --bare -b main sync-remote.git
git init -q -b main sync-work
cd sync-work
git remote add origin ../sync-remote.git

# A, B on main
printf 'line1\nline2\n' > file.txt; git add file.txt; git commit -qm "A: initial"
printf 'line1\nline2\nline3\n' > file.txt; git add file.txt; git commit -qm "B: add line3"
B=$(git rev-parse HEAD)

# branches rooted at B
git branch feature/behind
git branch feature/behind-unpushed
git branch feature/conflict

# C on main: changes line2
printf 'line1\nline2-changed-by-C\nline3\n' > file.txt; git add file.txt; git commit -qm "C: change line2"

# branches rooted at C
git branch feature/up-to-date
git branch feature/unpushed
git branch feature/local-only

# local-only commits
git checkout -q feature/behind-unpushed; echo "extra" > extra.txt; git add extra.txt; git commit -qm "D: unpushed work"
git checkout -q feature/conflict; printf 'line1\nline2-changed-by-conflict\nline3\n' > file.txt; git add file.txt; git commit -qm "E: conflicting change to line2"
git checkout -q feature/unpushed; echo "more" > more.txt; git add more.txt; git commit -qm "F: unpushed on top of C"
git checkout -q feature/local-only; echo "solo" > solo.txt; git add solo.txt; git commit -qm "G: never published"

# publish main and the "shared" branches; feature/unpushed's upstream is set at C (before F)
git checkout -q main
git push -q -u origin main
git push -q -u origin feature/up-to-date feature/behind
git push -q origin "$B:refs/heads/feature/behind-unpushed" "$B:refs/heads/feature/conflict"
git branch -q --set-upstream-to=origin/feature/behind-unpushed feature/behind-unpushed
git branch -q --set-upstream-to=origin/feature/conflict feature/conflict
git push -q origin "$(git rev-parse feature/unpushed~1):refs/heads/feature/unpushed"
git branch -q --set-upstream-to=origin/feature/unpushed feature/unpushed
git remote set-head origin main
git checkout -q feature/up-to-date
echo "Sync fixtures rebuilt at $(pwd)"
