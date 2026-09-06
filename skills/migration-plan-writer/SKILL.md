---
name: migration-plan-writer
description: >-
  Maps every call site a migration from X to Y touches and produces a
  plan-doc in expand, migrate, contract order — the new path added
  beside the old, usage moved in shippable slices, the old path
  removed last and only after a verification step — refusing a plan
  that skips the coexistence phase or contracts before migrating. Use
  when replacing a library, API, database table, or service, when asked
  how to migrate off something, or before a large refactor.
license: Apache-2.0
compatibility: Requires the Python `jsonschema` package (the check
  script validates the plan against the family shape).
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: plan-doc
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/map_migration_scope.py:*)
  Bash(python3 scripts/check_migration_plan.py:*) Read
---

# migration-plan-writer

## When to use

- Replacing a library, an internal API, a schema, or a service with
  another one, across more than one release.
- Asked how to migrate off something.
- Before a refactor large enough that "do it all in one PR" is the
  tempting and wrong answer.

## When not to use

- Planning the undo of a single deploy — that is
  `rollback-plan-writer`; this skill plans a change that spans
  releases and needs both paths alive in the middle.
- Performing the migration — the plan's steps are ordinary
  development work; this skill produces the plan.
- Deciding *whether* to migrate at all — that is a decision record
  (`adr-writer`); this skill assumes the decision and plans the route.

## @requires

- REQUIRED: a repository directory to scan.
- REQUIRED: `pattern` — a regular expression matching the old path
  (a function name, an import, a table, a config key).
- REQUIRED: what the new path is (the "to Y"), so the plan names it.
- OPTIONAL: `ext` — source extensions to scan (default: common source
  and config extensions).
- OPTIONAL: `exclude` — directories to skip beyond the defaults
  (default: none).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a directory,
the pattern compiles. Then map the scope — the mechanical part
(SDS-S-060):

```
python3 scripts/map_migration_scope.py <repo> --pattern <regex> [--ext ...] [--exclude ...]
```

It walks the tree (rung 1) and lists every matching line per file,
with test files separated out and hints about density and missing
safety nets. Facts only; a nonzero exit maps to `@throws`.

### Analyze

The slicing is judgment (SDS-S-061). Group the production files into
migrate slices that can each ship alone: by ownership, by traffic, by
density (a file with many sites is its own slice), and by risk. Decide
what "coexistence" looks like for this migration — a feature flag, a
dual write, an adapter, a shim — because that is what every Migrate
step's rollback will be. Decide the verification the Contract phase
opens with: usually this skill's own scope map reporting zero sites,
plus whatever runtime evidence (flag at 100% for N days, no traffic
on the old endpoint) proves the old path is dead.

### Decide

Compose the `plan-doc` (`kit/shapes/plan-doc.schema.json`): a `goal`
of the form "from X to Y"; one **Expand** phase (new path added beside
the old; characterization tests); one or more **Migrate** phases (one
slice each; every step reversible by the coexistence mechanism); one
**Contract** phase that begins with a verification step and ends with
the removal, the only step allowed to have `rollback: none —`. Then
check it:

```
python3 scripts/check_migration_plan.py <plan.json> --render
```

The script validates the shape, refuses a plan without an Expand
phase, with Contract anywhere but last, with an irreversible step
before Contract, or without a verification step opening Contract
(`plan-not-parallel-change`), applies the last-in-phase rule to the
removal (`plan-unsafe-order`), warns on single-step slices and a goal
that does not say "from X to Y", and renders the checklist.

### Synthesize

Return the checked plan-doc, the rendered checklist, and the scope
map's totals so a reader sees how much is moving. Every warning is
fixed or explained, never silently accepted. A scope of zero sites
yields a one-phase plan stating there is nothing to migrate, not an
error (SDS-C-033).

## @returns

Shape: `plan-doc` — see `kit/shapes/plan-doc.schema.json`.

An Expand → Migrate… → Contract plan whose every pre-contract step is
reversible through the chosen coexistence mechanism, whose Contract
phase opens with verification and ends with the sole irreversible
step, plus the checklist and the scope totals. Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `bad-argument`: the pattern is not a valid regular expression.
- `plan-unparseable`: the plan handed to the checker is not JSON.
- `plan-invalid`: the plan fails the family shape.
- `plan-not-parallel-change`: the plan lacks the Expand/Migrate/
  Contract structure, has an irreversible step before Contract, or
  contracts without verifying.
- `plan-unsafe-order`: the irreversible removal is not the last step
  of Contract.

## @example

**Input:** pattern `legacy_fetch` over a tree with four sites in
`app/orders.py` and `app/reports.py` and one test referencing it;
new path `OrdersClient`.

**Output (excerpt):** a four-phase plan — Expand (add `OrdersClient`,
add characterization tests), Migrate slice 1 (`app/orders.py` behind a
flag at 10%), Migrate slice 2 (`app/reports.py` and the test, flag to
100%), Contract (verify zero sites and two weeks at 100%, then remove
the flag and the legacy module with `rollback: none —`) — with the
rendered checklist marking that final step irreversible.
