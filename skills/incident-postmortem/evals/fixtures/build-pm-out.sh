#!/usr/bin/env bash
# Resets the gitignored output directory the write-mode eval row renders
# into (SDS-S-096: generated fixtures are produced by an idempotent
# build-<name>.sh and listed in evals/fixtures/.gitignore).
#
#   evals/fixtures/build-pm-out.sh
#
# Safe to re-run: previous output is removed first.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf pm-out
mkdir -p pm-out
echo "Postmortem output directory reset at $(pwd)/pm-out"
