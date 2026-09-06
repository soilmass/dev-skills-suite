#!/usr/bin/env bash
# Resets the gitignored scratch state directory used by the checkpoint
# round-trip eval rows (SDS-S-096: generated fixtures are built by an
# idempotent build-<name>.sh and listed in evals/fixtures/.gitignore).
#
#   evals/fixtures/build-state-scratch.sh
#
# Safe to re-run: it removes any previous scratch state so each eval
# run starts from an empty checkpoint store.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf state-scratch
mkdir -p state-scratch
echo "Scratch state directory reset at $(pwd)/state-scratch"
