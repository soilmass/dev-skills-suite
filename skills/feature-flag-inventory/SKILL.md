---
name: feature-flag-inventory
description: >-
  Inventories every feature-flag check in a repository's Python and
  JavaScript code and compares it with the flag configuration —
  flags checked but never configured, configured but never checked,
  enabled at 100% for weeks yet still guarded, off for weeks yet
  still shipped, and flags nobody owns — as a finding-list with the
  full inventory attached, so stale flags get removed instead of
  accumulating. Use on a flag-cleanup rota, when a flag service bill
  or a config file has grown, or when asked which flags can go.
license: Apache-2.0
compatibility: Requires PyYAML only when the flags file is YAML.
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/inventory_flags.py:*) Read
---

# feature-flag-inventory

## When to use

- A periodic flag-cleanup pass, or a flag count that keeps growing.
- A flag check with no matching configuration was found the hard
  way — in production.
- Asked which flags can be removed, or who owns a flag.

## When not to use

- Removing the flags — a refactor with its own review; this skill
  produces the removal list, not the diff.
- Experiment analysis (did the variant win?) — the experimentation
  platform; this skill sees checks and configuration, not outcomes.
- Environment variables used as flags — that is `env-var-inventory`,
  unless the check goes through a flag function named in
  `assets/flag-patterns.json`.

## @requires

- REQUIRED: the repository directory.
- REQUIRED: `flags-file` — the flag configuration as
  `{"flags": [{name, enabled, rollout?, createdAt?, owner?}]}` (JSON
  or YAML), exported from the flag service or maintained in the
  repository.
- REQUIRED: `as-of` — the moment of the audit, so flag ages are
  reproducible.
- OPTIONAL: `stale-days` — how long a flag may stay fully on or fully
  off before it is reported (default: 30).
- OPTIONAL: `patterns` — the check-function names to look for
  (default: `assets/flag-patterns.json`).
- OPTIONAL: `exclude` — directories to skip beyond the usual vendored
  and build directories (default: none).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a
directory, the flags file parses, `as-of` is a timestamp. Then
inventory — the mechanical part (SDS-S-060):

```
python3 scripts/inventory_flags.py <repo> --flags-file <flags.json> --as-of <ISO> [--stale-days N] [--patterns <file>]
```

It finds every check by call shape (rung 1; no flag service is
called), joins it with the configuration, and reports
`flag/unregistered`, `flag/unreferenced`, `flag/fully-rolled-out`,
`flag/permanently-off`, and `flag/unowned`. The run's
`tool.properties.flags` carries the inventory: checks, files, state,
rollout, age, owner. A Python file that does not parse stops the scan
(`source-unparseable`).

### Analyze

The inventory says what is stale; this stage decides what to do
(SDS-S-061). A fully-rolled-out flag is removed by keeping the
enabled branch and deleting the other — list the files, and flag any
check whose two branches differ in more than a few lines as a larger
change. A permanently-off flag guards either an abandoned feature
(delete the guarded code) or a kill switch (keep, and say so in the
configuration's owner or description) — the name usually tells. An
unregistered flag is a check that reads the default: find what the
default is in the check function and say what the code does today.
An unreferenced flag may live in another repository — say so if the
name suggests it. Order the removal list by risk: unregistered first
(behaviour nobody controls), then fully-rolled-out, then off.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[register or remove]`, `[remove flag: keep the
enabled branch in <files>]`, `[delete guarded code]`, `[keep: kill
switch]`, `[remove from config]`, `[keep: read by <repository>]`,
`[assign owner]`.

### Synthesize

Return the finding-list, warnings first, followed by the removal
list in risk order with the files each removal touches. A tree
whose checks and configuration agree and whose flags are young
yields a well-formed finding-list with an empty `results` array
(SDS-C-033) and the inventory.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per stale or inconsistent flag, located at its first
check (or the flags file), with `properties.flag` and the counts;
`runs[0].tool.properties.flags` is the full inventory. Nothing was
called and nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a Python file does not parse.
- `flags-unparseable`: the flags file cannot be read or lacks a
  `flags` array with named entries.
- `patterns-invalid`: the patterns file is not `{checkFunctions:
  [names]}`.
- `as-of-invalid`: `as-of` is missing or not a timestamp, or
  `stale-days` is not an integer.

## @example

**Input:** `new-checkout` enabled at 100% since 2026-06-01, checked in
three modules, audited on 2026-09-06.

**Output (excerpt):**

```json
{
  "ruleId": "flag/fully-rolled-out",
  "level": "warning",
  "message": { "text": "[remove flag: keep the enabled branch in app/checkout.py, app/cart.py, web/checkout.js] new-checkout has been enabled at 100% for 97 days and is still checked in 3 place(s); the flag is dead code — remove the checks and the flag" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "app/cart.py" }, "region": { "startLine": 12 } } }],
  "properties": { "flag": "new-checkout", "ageDays": 97, "checks": 3 }
}
```
