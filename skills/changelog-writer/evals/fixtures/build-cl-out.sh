#!/usr/bin/env bash
# Resets the gitignored output directory the write-mode eval rows use
# (SDS-S-096): a fresh copy of changelog-existing.md to insert into, so
# each run starts from the same file.
#
#   evals/fixtures/build-cl-out.sh
#
# Safe to re-run: previous output is removed first.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf cl-out
mkdir -p cl-out
cp changelog-existing.md cl-out/CHANGELOG.md
echo "Changelog output directory reset at $(pwd)/cl-out"
