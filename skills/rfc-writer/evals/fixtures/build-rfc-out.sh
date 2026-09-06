#!/usr/bin/env bash
# Resets the gitignored output directory the write-mode eval rows render
# into (SDS-S-096: generated fixtures are produced by an idempotent
# build-<name>.sh and listed in evals/fixtures/.gitignore).
#
#   evals/fixtures/build-rfc-out.sh
#
# Safe to re-run: previous output is removed first.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf rfc-out
mkdir -p rfc-out
echo "RFC output directory reset at $(pwd)/rfc-out"
