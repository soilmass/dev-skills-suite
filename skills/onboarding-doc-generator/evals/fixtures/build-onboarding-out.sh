#!/usr/bin/env bash
# Resets the gitignored output directory the write-mode eval row renders
# into (SDS-S-096: generated fixtures are produced by an idempotent
# build-<name>.sh and listed in evals/fixtures/.gitignore).
#
#   evals/fixtures/build-onboarding-out.sh
#
# Safe to re-run: previous output is removed first.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf onboarding-out
mkdir -p onboarding-out
echo "Onboarding output directory reset at $(pwd)/onboarding-out"
