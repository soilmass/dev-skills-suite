---
name: onboarding-doc-generator
description: >-
  Writes the guide a new colleague follows in their first days on a
  repository — the access they must be granted and by whom, setup
  steps each paired with what they should see when it worked, a first
  task small enough to finish in a day, and who to ask about what —
  refusing a step nobody can verify or an access grant from "someone",
  and checking every setup command against the facts
  repository-orientation collected. Use when a new person is joining,
  when the last newcomer got stuck, or when asked to write or refresh
  an onboarding guide.
license: Apache-2.0
compatibility: Requires the Python `jsonschema` package (the render
  script validates the specification against this skill's asset
  schema).
metadata:
  family: dev-skills-suite
  effect-tier: local-write
  idempotent: "true"
  tier: situational
  shape-out: freeform
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/render_onboarding.py:*) Read Write
---
<!-- Write is used only for the two-phase checkpoint under
     .skills-state/onboarding-doc-generator/ and for the specification
     JSON handed to the render script (SDS-S-024). The guide itself is
     written by scripts/render_onboarding.py, a rung-4 local write.
     Re-rendering an unchanged specification rewrites an identical
     file, hence idempotent: "true" (SDS-C-004). -->

# onboarding-doc-generator

## When to use

- A new person is joining the team next week.
- The last newcomer got stuck, and where they got stuck is known.
- Asked to write or refresh an onboarding guide.

## When not to use

- The README — that is `readme-writer`; a README is for every
  reader, this guide is for one new colleague and includes what a
  README must not (who grants access, who to ask).
- Collecting what the repository declares — that is
  `repository-orientation`; run it first and hand its facts here.
- An operational procedure — that is `runbook-writer`.

## @requires

- REQUIRED: the repository directory the guide is for.
- REQUIRED: the repository-orientation facts object for it
  (`python3 skills/repository-orientation/scripts/map_repository.py <repo>`
  saved to a file), so every setup command is checked against what
  the tree declares.
- REQUIRED: the human facts the tree cannot show — who grants which
  access, who owns which area, what the first task is — from the
  driver, a team page, or the existing guide.
- OPTIONAL: the env-var-inventory finding-list for the repository,
  so every variable the code requires is checked against the guide's
  access and setup steps (default: none).
- OPTIONAL: `existing` — the current guide, when one exists
  (default: read from `<repo>/ONBOARDING.md` if present).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the repository is a
directory and the facts file parses. Read the facts, the README, the
existing guide if any, and `CODEOWNERS` if present — it is the best
evidence of who to ask. Do not re-walk the tree: the facts are the
record (SDS-S-065).

### Analyze

Decide what a newcomer's first day needs, in order (SDS-S-061):
access first, because every wait for a grant is a day lost; then
setup in the order the tree implies (install, then the test command
the manifest declares, because a green test run is the first proof
that setup worked); then a first task that touches the entry point
but not the hard part; then who to ask, one name or channel per
area, from `CODEOWNERS` and the driver — never "the team". Where the
tree and the driver disagree about a command, the tree wins and the
guide says so.

### Decide

Compose the specification (`assets/onboarding.schema.json`, this
skill's own shape, SDS-S-080): `repository`, `audience`, `access`
each with `what`/`grantedBy`, `setup` steps each with `do`/`verify`
and the `command` when there is one, `firstTask` with `done`,
`whoToAsk`, optional `reading` and `lastVerified`. Write it under
`.skills-state/onboarding-doc-generator/`. Preview:

```
python3 scripts/render_onboarding.py <onboarding.json> --out-dir <repo> --facts-file <facts.json> [--env-file <env-vars.json>] --dry-run
```

The script refuses a step with no `verify` or an access grant from
nobody in particular (`onboarding-incomplete`) and a command the
tree does not declare (`command-undeclared`); it warns when the
facts show tests no step runs, CI the guide never mentions, a
required variable from env-var-inventory that no step hands over, or
no `lastVerified`.

**If the existing guide already equals the dry-run output: stop
here** — there is nothing to write, say so.

### Confirm

Only reached when the rendered guide differs from the existing one.
Rung 4 needs no gate (SDS-S-031); show the dry run and its warnings
— a missing `lastVerified` is the honest state of most guides, and
the page says so to its reader.

### Act

Only reached when the rendered guide differs from the existing one.
Write the `pending` checkpoint (single mutating step — inline via the
Write tool, SDS-S-055) to
`.skills-state/onboarding-doc-generator/<repo-name>.json`, with
`preState` = whether a guide existed and its byte length, then:

```
python3 scripts/render_onboarding.py <onboarding.json> --out-dir <repo> --facts-file <facts.json>
```

Check-before-act (SDS-C-046): if `<repo>/ONBOARDING.md` now equals
the dry-run output (a resumed run), skip the write. On success update
the checkpoint to `completed` with `postState` = the written path and
step count.

**Compensating action** (SDS-S-054): restore the previous guide from
version control (`git checkout -- ONBOARDING.md`) if one was
replaced, or delete the new file if none existed.

**Checkpoint** (SDS-S-053): the pending-then-completed record at
`.skills-state/onboarding-doc-generator/<repo-name>.json`.

### Communicate

N/A — the guide reaches the newcomer through the repository and
whoever welcomes them; this skill sends no message.

### Persist

The rendered `<repo>/ONBOARDING.md` is the durable artifact. Return
its path, the step count, and the remaining warnings — and ask that
the next newcomer's date go into `lastVerified`.

## @returns

Shape: `freeform` (a markdown onboarding guide).

Access with grantors, numbered setup steps each with a "you should
see", a first task with its done condition, who to ask per area, and
the guide's own verification status; every command shown is declared
by the tree. Exactly one file was written — or none, when the
existing guide already matched, which the result says.

## @throws

- `onboarding-unparseable`: the specification is unreadable or not
  JSON.
- `onboarding-invalid`: the specification fails
  `assets/onboarding.schema.json`.
- `onboarding-incomplete`: a setup step has no `verify`, or an access
  entry is granted by nobody in particular.
- `command-undeclared`: a setup command names a `make` target or npm
  script the repository's manifests do not declare.
- `facts-unparseable`: the facts file is unreadable or not JSON.
- `env-unparseable`: the env file is not env-var-inventory output.
- `out-dir-missing`: the repository directory does not exist.

## @example

**Input:** facts for a Python service with `make test`, a driver who
says "Priya grants AWS, ask #checkout-dev about pricing", and a first
task of adding one pricing rule.

**Output (excerpt):**

```markdown
# Onboarding: shop

_For a backend engineer joining the checkout team._

## Access you need first

- **AWS staging account** — granted by Priya (checkout lead); ask in #checkout-dev

## Setup

### 2. Run the tests

```sh
make test
```

**You should see:** `42 passed` in under a minute.
```
