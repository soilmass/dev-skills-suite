---
name: rollback-plan-writer
description: >-
  Inventories what a change touches — migrations, config,
  infrastructure, code — and produces a plan-doc in which every step
  names its rollback, irreversible steps are sequenced last, and the
  plan is refused if a step with no rollback is followed by one that
  depends on it. Use before a risky deploy or migration, when asked how
  a change would be undone, or when a release checklist needs its
  rollback section.
license: Apache-2.0
compatibility: Requires git and the Python `jsonschema` package (the
  check script validates the plan against the family shape).
metadata:
  family: dev-skills-suite
  effect-tier: domain-read-only
  idempotent: "true"
  tier: situational
  shape-out: plan-doc
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/inventory_change.py:*)
  Bash(python3 scripts/check_plan.py:*) Bash(git diff:*)
  Bash(git log:*) Bash(git rev-parse:*) Read
---

# rollback-plan-writer

## When to use

- A deploy or migration is risky enough that "how do we undo this"
  needs an answer before it ships, not during the incident.
- Asked how a change would be rolled back.
- A release checklist needs its rollback section.

## When not to use

- Performing the deploy or the rollback — this skill produces the
  plan; a Command Skill or a human executes it.
- Planning a large refactor or migration between systems — that is
  `migration-plan-writer` (situational), whose plan spans releases;
  this skill plans the undo of one change.
- Writing the runbook a rollback would follow — that is
  `runbook-writer`; a rollback plan can point at one.

## @requires

- REQUIRED: the current directory is the root of a git repository.
- REQUIRED: `range` — the change as `<base>..<head>` (a diff range).
- OPTIONAL: the deploy mechanism (how builds, config, and migrations
  reach production), so rollbacks name real commands (default: asked
  for at Analyze if not stated).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): repository root, range
resolves. Then inventory — the mechanical part (SDS-S-060):

```
python3 scripts/inventory_change.py . --range <base>..<head>
```

It reads `git diff --name-status` (rung 2) and buckets every changed
file as migration, config, infrastructure, dependency, data, or code,
with a hint per category about what its rollback takes. Facts only; a
nonzero exit maps to `@throws`.

### Analyze

The plan is judgment (SDS-S-061): from the inventory decide the
*order* things must be applied so each can be undone by redoing the
previous state — snapshots and value captures first, reversible
infrastructure and code next, migrations after the code that
tolerates both schemas, and anything irreversible (a data load, a
destructive migration) last and only after everything before it is
verified. Ask, when unstated, how builds, config, and migrations are
actually deployed; a rollback that says "redeploy" without naming
the command is a wish. Read each hint from the inventory and decide
whether it applies.

### Decide

Compose the `plan-doc` (`kit/shapes/plan-doc.schema.json`): a `goal`,
phases, and for every step a `description`, a `riskIfFails`, a
`rollback` that a tired engineer could execute from the text alone,
and `checkpointAfter`. A step that genuinely cannot be undone gets
`rollback` starting with `none —` followed by why, and goes last in
its phase. Then check it:

```
python3 scripts/check_plan.py <plan.json> --render
```

The script validates the shape, refuses an irreversible step that is
not last in its phase (`plan-unsafe-order`), warns on high-risk steps
with no rollback, terse rollbacks, and uncheckpointed phases, and
renders the checklist.

### Synthesize

Return the checked plan-doc and the rendered checklist. Every warning
the check raised is either fixed in the plan or explained in the
summary; none is silently accepted. An empty range (no files changed)
yields a plan-doc with one phase and one step — "nothing to deploy,
nothing to roll back" — not an error (SDS-C-033).

## @returns

Shape: `plan-doc` — see `kit/shapes/plan-doc.schema.json`.

A plan whose every step names its rollback, whose irreversible steps
are last in their phases, with the check script's warnings resolved or
explained, plus the markdown checklist. Nothing was modified.

## @throws

- `repo-invalid`: the current directory is not a git repository root,
  or the range does not resolve.
- `diff-unreadable`: an injected diff file could not be read.
- `plan-unparseable`: the plan handed to the checker is not JSON.
- `plan-invalid`: the plan fails the family shape (for example a step
  without a rollback field).
- `plan-unsafe-order`: an irreversible step is followed by another
  step in the same phase.

## @example

**Input:** a range touching a checkout service, one migration adding
an index, `config/prod.yaml`, `terraform/rds.tf`, the lockfile, and a
seed CSV.

**Output (excerpt):** a two-phase plan — Prepare (snapshot and value
capture; terraform apply with the previous definition saved) and
Deploy (build, config, migration with its down-migration, and the seed
load last with `rollback: none — seed rows cannot be told apart from
later inserts`) — plus the rendered checklist marking that last step
irreversible.
