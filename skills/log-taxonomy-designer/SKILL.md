---
name: log-taxonomy-designer
description: >-
  Inventories every logging call in a Python repository — levels,
  message templates, field names — maps the field names onto
  OpenTelemetry semantic conventions, reports the drift as a
  finding-list (one attribute logged under three spellings, failures
  logged at info, secrets in fields, messages built by interpolation,
  exceptions logged without their traceback), and then designs the
  taxonomy: the canonical attribute names, what every event must
  carry, and the rename map. Use when logs are hard to query, before
  adopting structured logging or a log pipeline, or when asked to
  standardise logging.
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
  Bash(python3 scripts/inventory_logs.py:*) Read
---

# log-taxonomy-designer

## When to use

- Queries against the logs need three spellings of one field to
  find everything.
- Before adopting structured logging, a log pipeline, or an
  observability vendor whose value depends on consistent
  attributes.
- Asked to standardise, clean up, or design logging.

## When not to use

- Alert noise — that is `alert-fatigue-audit`; this skill reads
  source, not alert history.
- Applying the renames — a refactor with its own review; this skill
  produces the rename map, not the diff.
- Non-Python sources, for now.

## @requires

- REQUIRED: a repository directory containing Python sources.
- OPTIONAL: `conventions` — the canonical attribute names and their
  known variants (default: `assets/semantic-conventions.json`,
  OpenTelemetry names).
- OPTIONAL: `exclude` — directories to skip beyond the usual vendored
  and build directories (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then inventory — the mechanical part (SDS-S-060):

```
python3 scripts/inventory_logs.py <repo> [--exclude dir,dir] [--conventions <file>]
```

It parses every `.py` file with `ast` (rung 1; nothing is run),
finds each `logger.<level>(...)` call, and reports
`log/inconsistent-field-name`, `log/level-mismatch`,
`log/sensitive-field`, `log/interpolated-message`, and
`log/exception-without-traceback`. The run's `tool.properties`
carries the inventory: calls per level, every field with its count
and canonical mapping, and the constant message templates. A file
that does not parse stops the scan (`source-unparseable`).

### Analyze

The inventory shows what is logged; this stage decides what should
be (SDS-S-061). For each canonical attribute with variants, pick the
OpenTelemetry name unless the repository already uses one spelling
overwhelmingly and it is not misleading. Decide the *required
set* — the fields every event must carry so any line can be joined
to a request (`trace_id`, `user.id` where there is a user,
`service.name`) — from what the busiest templates already carry.
Decide the level policy in one line per level (debug: developer
detail; info: a state change worth counting; warning: degraded but
handled; error: a request failed; critical: the service cannot
serve). A field in the sensitive list is a defect regardless of
level. A message built by interpolation becomes a constant template
plus fields — write the template.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[rename → user.id]`, `[demote to info]`,
`[promote to error]`, `[remove field]`, `[template: "order priced"
+ fields order.id, duration_ms]`, `[use .exception()]`.

### Synthesize

Return the finding-list, warnings first, grouped by file, followed
by the taxonomy in three short tables: canonical attributes with the
rename map (variant → canonical, occurrences), the required set per
event, and the level policy. A tree with consistent logging yields a
well-formed finding-list with an empty `results` array (SDS-C-033)
and the taxonomy as it already stands.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per drift instance, located at the logging call (or, for
an inconsistent name, at the first call in the tree), with
`properties` carrying the variants and canonical name, the level and
template, or the field; `runs[0].tool.properties` carries the full
inventory. Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a Python file does not parse.
- `conventions-invalid`: the conventions file is not the expected
  shape.

## @example

**Input:** a service logging `user_id=` in one module, `userId=` in
another, and `uid=` in a third.

**Output (excerpt):**

```json
{
  "ruleId": "log/inconsistent-field-name",
  "level": "warning",
  "message": { "text": "[rename → user.id] user.id is logged as user_id (7), userId (3), uid (1); one attribute, one name" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "app/orders.py" }, "region": { "startLine": 12 } } }],
  "properties": { "canonical": "user.id", "variants": { "user_id": 7, "userId": 3, "uid": 1 } }
}
```
