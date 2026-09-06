---
name: json-schema-compat-check
description: >-
  Compares two versions of a JSON Schema and answers the question a
  registry asks — can every instance the old version accepted
  still pass the new one? — reporting each backward-incompatible
  change as a finding-list located by pointer: properties made
  required, properties removed under closed objects, types narrowed,
  enum values dropped, constraints tightened; with widenings and
  relaxations listed as information and enum additions as a warning
  for exhaustive readers. Use before publishing a JSON Schema change
  for an event, a config file, or a stored record, or when asked
  whether a JSON Schema change is compatible.
license: Apache-2.0
compatibility: Requires PyYAML only when the schemas are YAML; JSON
  needs nothing beyond the standard library.
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/diff_json_schema.py:*) Read
---

# json-schema-compat-check

## When to use

- A schema for an event, a message, a config file, or a stored
  record is about to change and old data or old producers still
  exist.
- Registering a new schema version where the registry enforces a
  compatibility mode.
- Asked whether a schema change is backward compatible.

## When not to use

- An HTTP API description — that is `openapi-breaking-change-check`,
  which understands paths, parameters, and responses; this skill
  sees one schema.
- Validating data against a schema — any JSON Schema validator; this
  skill compares two schemas and validates nothing.
- Forward compatibility (can *old* readers accept *new* data?) — run
  the diff in the other direction and read `type-widened`,
  `required-removed`, and `enum-value-added` as the breaks; say so
  when reporting.

## @requires

- REQUIRED: the old JSON Schema (JSON or YAML) — the version existing
  data and producers conform to.
- REQUIRED: the new JSON Schema — the proposed version.

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): both files parse and
look like JSON Schema objects. Then diff — the mechanical part
(SDS-S-060):

```
python3 scripts/diff_json_schema.py <old> <new>
```

It resolves local `$ref`s, walks properties and array items, and
reports `schema/required-added`, `schema/property-removed`,
`schema/type-narrowed`, `schema/enum-value-removed`,
`schema/constraint-tightened`, and
`schema/additional-properties-closed` as errors (old instances can be
rejected); `schema/enum-value-added` as a warning; and
`schema/type-widened`, `schema/constraint-loosened`,
`schema/required-removed` as info. `tool.properties.backwardCompatible`
is true when nothing was reported at error level.

### Analyze

The diff is exact about validity; this stage is about consequences
(SDS-S-061). A property made required breaks every producer that
does not send it and every stored record that lacks it — ask whether
a default can be applied on read instead. A property removed under
an open object is validation-safe but silently drops meaning for
readers; under a closed object it rejects old data outright — the
fix is usually to keep the property as `deprecated` for one version.
A narrowed type or tightened constraint is only safe if no stored
data violates it — say what would have to be checked (a query over
the store) before calling it safe. An enum value added is harmless
to validation and hazardous to exhaustive `switch` statements in
typed readers; name the readers if known. If the schema's `$id` or
version did not change while breaks exist, say so.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the verdict — `[breaking: new major schema version]`,
`[breaking unless store verified: <query>]`, `[safe: open object,
document the removal]`, `[readers: handle new value]` — and, for a
required addition, propose the default-on-read alternative.

### Synthesize

Return the finding-list, errors first, with the compatibility verdict
in one line: backward compatible / compatible after the named
verification / incompatible, needs a new major version and a
migration. Identical schemas yield a well-formed finding-list with an
empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per change, located at the new schema file with
`properties.pointer` naming the element; errors can reject
previously valid instances, warnings affect readers, infos are
relaxations; `runs[0].tool.properties` carries both `$id`s, the
breaking count, and `backwardCompatible`. Nothing was modified and
nothing was called.

## @throws

- `schema-unparseable`: a file cannot be read or is not valid JSON or
  YAML.
- `schema-invalid`: a file is not a JSON Schema object.

## @example

**Input:** an `order-placed` event schema where v2 makes `currency`
required, narrows `total` from number to integer, and drops
`shipped` from the `status` enum.

**Output (excerpt):**

```json
{
  "ruleId": "schema/required-added",
  "level": "error",
  "message": { "text": "[breaking: new major schema version, or default on read] #.currency: property is now required" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "order-placed-v2.json" } } }],
  "properties": { "pointer": "#.currency", "new": false }
}
```
