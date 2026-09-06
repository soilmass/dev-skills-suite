#!/usr/bin/env bash
# Resets the gitignored scratch directory the contract row derives its list into (SDS-S-096).
#   evals/fixtures/build-state-scratch.sh
set -euo pipefail
cd "$(dirname "$0")"
rm -rf state-scratch && mkdir -p state-scratch
echo "Scratch reset at $(pwd)/state-scratch"
