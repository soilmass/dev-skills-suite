---
name: query-plan-review
description: >-
  Reviews a PostgreSQL `EXPLAIN` plan, in its `FORMAT JSON` output, for the shapes that
  make queries slow — a sequential scan with a filter over a large
  table, a nested loop re-scanning its inner side, row estimates ten
  times off the actuals, sorts and hashes spilling to disk, index-only
  scans fetching from the heap, lossy bitmaps — as a finding-list
  located at the plan node, leaving the call on which shape matters
  and what to change (an index, statistics, work_mem, the query) to a
  human. Use when a query is slow, before adding an index, or when
  asked to read an explain plan.
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
  Bash(python3 scripts/review_plan.py:*) Read
---

# query-plan-review

## When to use

- A query is slow and its plan has been captured.
- Before adding an index, to confirm the plan actually lacks one.
- Asked to read or explain an EXPLAIN plan.

## When not to use

- Capturing the plan — run `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`
  against a database with production-like data first; this skill
  reads the file and contacts no database.
- Non-PostgreSQL plans, for now — the JSON shape is PostgreSQL's.
- Writing the migration that adds the index — that is
  `migration-plan-writer`.

## @requires

- REQUIRED: the plan as a JSON file — `EXPLAIN` run with `FORMAT JSON`;
  with `ANALYZE` as well, the estimate and spill rules become
  available.
- OPTIONAL: `large-rows` — the row count above which a scan or loop
  counts as large (default: 10000).
- OPTIONAL: the SQL itself, for the review's reasoning about what
  the query is trying to do (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the file is EXPLAIN
JSON with a `Plan`. Then run the structural pass — the mechanical
part (SDS-S-060):

```
python3 scripts/review_plan.py <plan.json> [--large-rows N]
```

It walks every node and reports `plan/seq-scan-large`,
`plan/nested-loop-large`, and — when the plan carries actuals —
`plan/estimate-off`, `plan/sort-on-disk`, `plan/hash-batches`,
`plan/heap-fetches`, and `plan/lossy-bitmap`, each located at its
node path. `tool.properties` says whether the plan was analyzed,
the node count, total cost, and execution time.

### Analyze

The shapes say where time goes; this stage decides what to do about
each (SDS-S-061). A large sequential scan with a filter wants an
index only if the filter is selective — check `Rows Removed by
Filter` against rows kept; a scan that keeps most rows is correct
and an index would be slower. A nested loop over a large outer side
usually means the planner *expected* the outer side to be small —
look for an `estimate-off` on that child first; fixing statistics
fixes the join choice. A sort on disk is a `work_mem` setting for
this query, or an index that provides the order. Estimate-off on a
filtered column with correlated predicates wants `CREATE STATISTICS`.
Heap fetches want `VACUUM`, not an index. Say for each finding
whether the fix is an index, statistics, a memory setting, or the
query itself, and for an index give the columns in filter order.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[index: orders(customer_id, created_at)]`,
`[ANALYZE orders]`, `[CREATE STATISTICS on (a, b)]`, `[work_mem for
this query: 64MB]`, `[VACUUM orders]`, `[rewrite: …]`, `[keep: scan
is correct]`.

### Synthesize

Return the finding-list, warnings first, in plan order, followed by
one paragraph: where the time goes, the single change most likely
to help, and how to verify it (re-run the EXPLAIN and compare the
node). A plan with none of the shapes yields a well-formed
finding-list with an empty `results` array (SDS-C-033) and a
sentence saying the plan is already reasonable.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per slow shape, located at the plan file with
`properties.nodePath` pointing at the node, the node type and
relation, and the numbers (rows, ratio, batches, blocks);
`runs[0].tool.properties` carries whether the plan was analyzed and
its totals. Nothing was modified and no database was contacted.

## @throws

- `plan-unparseable`: the file is not JSON or not EXPLAIN (FORMAT
  JSON) output with a `Plan`.
- `threshold-invalid`: `large-rows` is not a positive integer.

## @example

**Input:** an analyzed plan where `orders` is scanned sequentially
over 1.2 million rows with `Filter: (customer_id = 42)` and 1,199,950
rows removed by the filter.

**Output (excerpt):**

```json
{
  "ruleId": "plan/seq-scan-large",
  "level": "warning",
  "message": { "text": "[index: orders(customer_id)] Seq Scan on orders over 1200000 rows with filter (customer_id = 42); no index serves this predicate" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "slow-orders.json" } } }],
  "properties": { "nodePath": "Plan/Plans[0]", "nodeType": "Seq Scan", "relation": "orders", "rows": 1200000, "filter": "(customer_id = 42)", "removedByFilter": 1199950 }
}
```
