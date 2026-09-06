---
name: tech-debt-inventory
description: >-
  Scans a repository's source files for technical-debt signals —
  TODO/FIXME/HACK markers, oversized files, duplicated code blocks —
  and produces a prioritized SARIF-compatible finding-list, with the
  model ranking what a mechanical scan cannot. Use when asked to
  inventory, audit, or prioritize technical debt, before planning a
  refactor, or when the user mentions TODOs, code smells, or god files.
license: Apache-2.0
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: pillar
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/scan_debt.py:*) Read
---

# tech-debt-inventory

## When to use

- Planning a refactor or a "cleanup sprint" and needing a ranked list
  of what to touch first.
- Asked to audit or inventory technical debt in a repository.
- The user mentions TODOs, FIXMEs, code smells, god files, or
  copy-pasted logic.

## When not to use

- Finding dead code — that is `dead-code-finder` (situational); a
  marker inventory says nothing about reachability.
- Auditing third-party dependencies — that is `dependency-audit`;
  this skill never reads manifests or the network.
- Judging whether a *specific* design is sound — that is
  `design-doc-review`; this skill surfaces signals, it does not
  evaluate architecture.

## @requires

- REQUIRED: a repository directory to scan (the working tree; git is
  not consulted).
- OPTIONAL: `long-file-lines` — line count above which a file is
  reported (default: 500).
- OPTIONAL: `dup-window` — consecutive normalized lines that must
  match to count as a duplicate block (default: 8).
- OPTIONAL: `ext` — comma-separated source extensions to scan
  (default: common source extensions; docs and data files are ignored).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a directory.
Then run the scanner — the whole mechanical part of this skill
(SDS-S-060):

```
python3 scripts/scan_debt.py <repo-path> [--long-file-lines N] [--dup-window N] [--ext .py,.ts]
```

It reads only the working tree (rung 1) and prints a `finding-list`
with three rule ids: `debt/marker`, `debt/long-file`,
`debt/duplicate-block`. Non-UTF-8 files are skipped with a note, not a
failure. A nonzero exit maps to `@throws`.

### Analyze

The scanner reports every occurrence; it does not read intent. This
is the judgment step (SDS-S-061): re-rank the raw findings by likely
cost of leaving them. Drop false positives (a `TODO` inside a string
literal, duplicated *test setup*). Promote a `FIXME` on a request
path or in a security boundary to `error`; demote a `TODO` that is
just a ticket reference. Treat a long file by how many
responsibilities it mixes, not by its line count. If unsure what a
marker category conventionally means, consult
`references/marker-taxonomy.md` — only then.

### Classify

Assign the final `level` per finding (`error`, `warning`, `info`) and
attach a one-line reason to any finding whose level you changed, in
its `message.text`. Never remove a finding the scanner produced
without saying so in the summary; the inventory must stay auditable
against the raw scan.

### Synthesize

Return the finding-list ordered by level (`error` first), then by
file. Zero signals in the repository yields a well-formed finding-list
with an empty `results` array (SDS-C-033), not a "nothing found"
message. The artifact is SARIF-compatible so it can be uploaded to
code scanning as-is.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

Every debt signal the scanner found is present as one result with
`ruleId`, a `level` the Analyze/Classify stages stand behind, a
`message.text` that quotes the evidence, and a file-plus-line
location. Findings sharing a duplicate `fingerprint` are the same
block.

## @throws

- `repo-invalid`: the path is not a directory.
- `bad-argument`: `long-file-lines` or `dup-window` is not an integer.

## @example

**Input:** a repository whose `markers.py` carries a `FIXME` at line
11, whose `long_module.py` exceeds the threshold, and whose `dup_a.py`
and `dup_b.py` share an 8-line normalization block.

**Output (excerpt):**

```json
{
  "ruleId": "debt/marker",
  "level": "warning",
  "message": { "text": "FIXME marker: # FIXME: silently drops the last record when the file has no trailing newline" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "markers.py" }, "region": { "startLine": 11 } } }],
  "properties": { "marker": "FIXME" }
}
```
