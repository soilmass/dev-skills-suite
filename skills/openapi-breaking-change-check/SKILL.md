---
name: openapi-breaking-change-check
description: >-
  Compares two versions of an OpenAPI 3 description and reports every
  change that breaks an existing client — removed paths and
  operations, parameters made required or retyped, request properties
  newly required, response properties removed or retyped, enum values
  dropped — as a finding-list located by JSON pointer, with purely
  additive changes listed as information. Use before merging an API
  change, when deciding whether a release is a major version, or when
  asked whether an API change is backwards compatible.
license: Apache-2.0
compatibility: Requires PyYAML only when the documents are YAML; JSON
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
  Bash(python3 scripts/diff_openapi.py:*) Read
---

# openapi-breaking-change-check

## When to use

- A pull request changes the API description and the reviewer needs
  to know whether clients will break.
- Deciding whether a release is a major or a minor version.
- Asked whether an API change is backwards compatible.

## When not to use

- Reference documentation from the code — that is `api-doc-writer`;
  this skill compares two descriptions, it does not write one.
- Two versions of a JSON Schema on its own (an event, a config file)
  — the same idea, but a schema is not an API; a sibling skill can
  cover it.
- Detecting drift between the description and the running server —
  a contract-test job; this skill reads two files and calls nothing.

## @requires

- REQUIRED: the old OpenAPI 3 description (JSON or YAML) — the
  version clients were built against.
- REQUIRED: the new OpenAPI 3 description — the proposed version.

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): both files parse and
carry `openapi` and `paths`. Then diff — the mechanical part
(SDS-S-060):

```
python3 scripts/diff_openapi.py <old> <new>
```

It resolves local `$ref`s, walks every path, operation, parameter,
request body, and response schema, and reports `api/path-removed`,
`api/operation-removed`, `api/param-removed`,
`api/param-required-added`, `api/param-type-changed`,
`api/request-required-added`, `api/response-removed`,
`api/response-property-removed`, `api/response-type-changed`,
`api/enum-value-removed`, and `api/operation-added` (info). Each
finding carries the JSON pointer of the changed element.
`tool.properties` counts the breaking changes.

### Analyze

The diff says what changed; this stage says whether it matters
(SDS-S-061). A removed operation nobody calls (check access logs or
the client repositories) is a cleanup, not a break — say how you
know. A parameter made required that every known client already
sends is technically breaking and practically safe; say which. A
response property removed is breaking for any client that reads it,
and there is no way to know from the server side — treat it as a
break unless the property was never populated. An enum value removed
from a response breaks exhaustive switches in typed clients; an enum
value *added* does too, which this diff does not flag — mention it
when new values appear. If the document's `info.version` did not
bump its major part while breaking changes exist, say so plainly.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the verdict — `[breaking: bump major]`, `[breaking but unused:
verify with logs]`, `[compatible in practice: all clients send it]`,
`[deprecate first: keep for one release]` — and, for a removal,
propose the deprecation path (keep the field, mark `deprecated:
true`, remove next major).

### Synthesize

Return the finding-list, errors first, grouped by path, with the
version verdict in one line: compatible / needs a minor bump / needs
a major bump, and why. Identical or purely additive documents yield
a well-formed finding-list with only `api/operation-added` infos or
an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per change, located at the new document with
`properties.pointer` naming the element; errors are breaking,
warnings are likely breaking, infos are additive;
`runs[0].tool.properties` carries both `info.version` values and the
breaking count. Nothing was modified and nothing was called.

## @throws

- `spec-unparseable`: a file cannot be read or is not valid JSON or
  YAML.
- `spec-invalid`: a file is not an OpenAPI 3 document with `openapi`
  and `paths`.

## @example

**Input:** v1 documents `GET /orders/{id}` returning `total` and
`status` (enum open, paid, shipped); v2 drops `total` and the
`shipped` value, and makes the `expand` query parameter required.

**Output (excerpt):**

```json
{
  "ruleId": "api/response-property-removed",
  "level": "error",
  "message": { "text": "[breaking: bump major] paths./orders/{id}.get.responses.200.total: response property removed" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "openapi-v2.json" } } }],
  "properties": { "pointer": "paths./orders/{id}.get.responses.200.total" }
}
```
