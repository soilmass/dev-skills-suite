#!/usr/bin/env bash
# Resets the gitignored output directories the write-mode eval rows
# render into (SDS-S-096: generated fixtures are produced by an
# idempotent build-<name>.sh and listed in evals/fixtures/.gitignore).
#
#   evals/fixtures/build-adr-out.sh
#
# Produces:
#   adr-out/          a copy of adr-dir-existing/ (one accepted ADR,
#                     0001) for the numbering and supersession rows
#   adr-out-empty/    an empty ADR directory for the first-ADR row
# Safe to re-run: previous outputs are removed first.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf adr-out adr-out-empty
mkdir -p adr-out adr-out-empty
cp adr-dir-existing/*.md adr-out/
echo "ADR output directories reset at $(pwd)"
