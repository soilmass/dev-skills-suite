---
name: flag-retirement-plan-writer
description: >-
  Turns feature-flag-inventory's finding-list into a plan-doc for
  retiring dead flags — one phase to remove the dead code branch a
  fully-rolled-out or permanently-off flag guards, one to delete each
  retired flag's definition, and one to clean the flag provider and
  configuration last — with every step's rollback named. Use after a
  flag-cleanup pass has found stale flags and someone needs the
  removal steps in order, or when asked how a dead flag would actually
  be retired.
license: Apache-2.0
compatibility: Requires the Python `jsonschema` package only for
  contract validation in the eval table; the script itself has no
  dependency beyond the standard library.
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: plan-doc
  shape-in: finding-list
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/plan_flag_retirement.py:*) Read
---

# flag-retirement-plan-writer

## When to use

- `feature-flag-inventory` has already found stale flags and the
  removal steps — in what order, with what rollback — are needed
  next.
- Asked how a specific dead flag would actually be retired.
- A flag-cleanup rota's findings need turning into an executable plan
  before anyone touches code.

## When not to use

- Finding which flags are stale — that is `feature-flag-inventory`;
  this skill only plans what its findings already identified.
- Executing the plan — `issue-triage` and `project-board-sync` are
  the consumers that turn a plan-doc into tracked work; a human or a
  Command Skill performs the actual edits.
- Deciding whether a permanently-off flag is a kill switch worth
  keeping — that judgment belongs to `feature-flag-inventory`'s
  Analyze stage, upstream of this one; a flag it did not report as
  stale never reaches this skill.

## @requires

- REQUIRED: `findings` — a finding-list in the form
  `feature-flag-inventory` produces: each result's `ruleId` one of
  `flag/fully-rolled-out`, `flag/permanently-off`, `flag/unreferenced`,
  `flag/unowned`, or `flag/unregistered`, with `properties.flag`, and
  `runs[*].tool.properties.flags` carrying each flag's `files` and
  `ageDays`.
- REQUIRED: `as-of` — the moment the plan is written, recorded in the
  goal so the retired count is reproducible.
- OPTIONAL: `older-than-days` — drop a candidate flag whose inventory
  `ageDays` is below it (default: 0, nothing dropped).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the input parses as a
finding-list (a `runs` array whose results carry `ruleId`), and
`as-of` parses as a timestamp. Then compute — the mechanical part
(SDS-S-060):

```
python3 scripts/plan_flag_retirement.py <findings.json> --as-of <ISO> [--older-than-days N]
```

It reads each result's `ruleId` and `properties.flag`, joins it with
the matching record in `runs[*].tool.properties.flags` for that
flag's `files` and `ageDays`, and emits the plan directly — a rung-1
Query Skill with no separate judgment stage, because the rule table
below is total over `feature-flag-inventory`'s five rule IDs.

### Analyze

Only three rule IDs are retirement candidates. `flag/fully-rolled-out`
and `flag/permanently-off` each guard a code branch that is now dead
— the enabled branch survives the first, the disabled branch survives
the second, and the check itself goes with whichever branch does not
survive. `flag/unreferenced` is configured but checked nowhere, so
there is no code branch to remove, only the definition. `flag/unowned`
and `flag/unregistered` are ownership and registration findings, not
retirement candidates — a flag nobody owns, or a check nobody
registered, is not thereby dead code — and produce no step at all.

### Classify

Order every candidate into the three-phase structure: dead-branch
removal first (for the two rule IDs that guard one), definition
deletion next (for all three retirement rule IDs, including
unreferenced ones with no branch step), and the flag
provider/configuration cleanup last, because it must not run before
the code and the definitions it is cleaning up for are already gone.
Every phase in the plan-doc shape requires at least one step
(`kit/shapes/plan-doc.schema.json`), so the dead-branch phase is
omitted entirely — not emitted with zero steps — when every candidate
is `flag/unreferenced` and none guards a code branch.

### Synthesize

Compose the `plan-doc` (`kit/shapes/plan-doc.schema.json`): a `goal`
stating the retired-flag count and the `as-of`, then the phases above.
Every step names a `rollback` a tired engineer could run from the
text alone (`git revert <commit>` for the code and configuration
phases; re-adding the definition from the reverted commit for the
deletion phase), a `riskIfFails`, and `checkpointAfter`. No candidate
flags yields a single `nothing to do` phase with one step whose
rollback says none is needed and whose `checkpointAfter` is `false` —
not an error (SDS-C-033).

## @returns

Shape: `plan-doc` — see `kit/shapes/plan-doc.schema.json`.

A plan whose dead-branch and definition-deletion steps cover every
`flag/fully-rolled-out`, `flag/permanently-off`, and
`flag/unreferenced` result at or above `--older-than-days`, whose
cleanup step is last, and whose every step names a rollback. Nothing
was modified.

## @throws

- `findings-invalid`: the input is not JSON, is not an object with a
  non-empty `runs` array, or a result is missing `ruleId`.
- `as-of-invalid`: `--as-of` is missing or not a timestamp, or
  `--older-than-days` is not an integer.

## @example

**Input:** the frozen `feature-flag-inventory` finding-list in
`evals/fixtures/frozen-feature-flag-inventory-findings.json` — five
flags, three of which qualify: `new-checkout` (fully-rolled-out, 97
days, checked in three files), `dark-mode` (permanently-off, 60 days,
checked in one file), and `legacy-export` (unreferenced).

**Output (excerpt):**

```json
{
  "goal": "Retire 3 dead flag(s) (new-checkout, dark-mode, legacy-export) as of 2026-09-06T12:00:00+00:00: 2 dead-branch removal(s), 3 definition deletion(s), 1 provider/config cleanup",
  "phases": [
    { "name": "remove dead branches", "steps": [ "...new-checkout...", "...dark-mode..." ] },
    { "name": "delete flag definitions", "steps": [ "...new-checkout...", "...dark-mode...", "...legacy-export..." ] },
    { "name": "clean the flag provider/config", "steps": [ "...all three, last..." ] }
  ]
}
```
