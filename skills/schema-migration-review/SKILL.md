---
name: schema-migration-review
description: >-
  Reviews database migration files — Alembic, Django, or raw SQL — for
  the operations that lock tables, lose data, or cannot be undone:
  drops, NOT NULL columns without a default, in-place type changes,
  indexes built without CONCURRENTLY, migrations with no downgrade,
  and DDL and data changes mixed in one file — as a finding-list
  judged against the expand, migrate, contract order, leaving the call
  on which finding is acceptable for this table to a human. Use before
  merging a migration, when a deploy will run one against a large
  table, or when asked whether a migration is safe.
license: Apache-2.0
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/review_migrations.py:*) Read
---

# schema-migration-review

## When to use

- A pull request adds or changes a migration.
- A deploy will run migrations against a table large enough that a
  lock is an outage.
- Asked whether a migration is safe, reversible, or zero-downtime.

## When not to use

- Planning the migration — that is `migration-plan-writer`, which
  produces the expand/migrate/contract plan this skill reviews the
  files against.
- Reviewing the query performance that results — that is
  `query-plan-review`.
- Running or applying migrations — never; this skill reads files and
  contacts no database.

## @requires

- REQUIRED: the migrations directory (Alembic `versions/`, a Django
  app's `migrations/`, or a directory of `.sql` files).
- OPTIONAL: `exclude` — subdirectories to skip (default: none).
- OPTIONAL: the migration plan (`migration-plan-writer` output) for
  the change, to check that destructive steps sit in its contract
  phase (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then scan — the mechanical part (SDS-S-060):

```
python3 scripts/review_migrations.py <migrations-dir> [--exclude dir,dir]
```

It recognises Alembic (`op.*`), Django (`migrations.*`), and SQL by
shape, and reports `migration/destructive`,
`migration/not-null-no-default`, `migration/type-change`,
`migration/index-not-concurrent`, `migration/irreversible`, and
`migration/ddl-with-dml`, each at the file and line. A Python
migration that does not parse stops the scan
(`migration-unparseable`).

### Analyze

The scan flags shapes; this stage judges them for these tables
(SDS-S-061). A drop is correct in a contract-phase migration whose
migrate phase has been verified — ask for the evidence (the plan, a
query showing the old column unread) and otherwise call it
premature. A NOT NULL without default is fine on an empty or new
table and an outage on a populated one — say which, and propose add
nullable → backfill → set NOT NULL. A type change on a small table
is a second of lock; on a large one it is a rewrite — the fix is a
new column, dual writes, and a later drop. A non-concurrent index on
a table with writes is a write outage for the build's duration.
An irreversible migration is acceptable only if the rollback plan
(`rollback-plan-writer`) says the deploy rolls forward. Mixed DDL and
DML is a split into two migrations.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[move to contract phase: after <verification>]`,
`[add nullable, backfill, then set NOT NULL]`, `[new column + dual
write]`, `[CONCURRENTLY, outside the transaction]`, `[write
downgrade]`, `[split into two migrations]`, `[keep: empty table]`,
`[keep: contract phase, verified]`.

### Synthesize

Return the finding-list, errors first, grouped by file in migration
order, with one line per file: safe to run / safe with the named
change / blocks the deploy. A directory of safe migrations yields a
well-formed finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per risky operation, located at the migration file and
line, with `properties.dialect` and the operation;
`runs[0].tool.properties` counts files and blocking findings.
Nothing was run and no database was contacted.

## @throws

- `migrations-dir-invalid`: the path is not a directory.
- `migration-unparseable`: a Python migration does not parse.

## @example

**Input:** an Alembic revision that adds `orders.currency` as
`nullable=False` with no `server_default` and drops `orders.notes`
in the same file.

**Output (excerpt):**

```json
{
  "ruleId": "migration/not-null-no-default",
  "level": "error",
  "message": { "text": "[add nullable, backfill, then set NOT NULL] op.add_column with nullable=False and no server_default fails on existing rows" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "versions/0007_currency.py" }, "region": { "startLine": 14 } } }],
  "properties": { "dialect": "alembic" }
}
```
