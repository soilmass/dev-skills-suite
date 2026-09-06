---
name: layer-boundary-check
description: >-
  Builds a repository's import graph against a declared layer map and
  reports an import that crosses from one layer into a layer not on
  its allowed list as an error, and a source file assigned to no
  layer as an info, as a finding-list with the layer names and
  per-layer counts attached. Use when reviewing whether a change
  respects declared layer boundaries, placing a new module and asking
  which layer it belongs to, or asked whether one layer depends on
  another it should not.
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
  Bash(python3 scripts/check_layers.py:*) Read
---

# layer-boundary-check

## When to use

- Reviewing whether a change respects the layer boundaries a
  repository has declared, before merging it.
- Placing a new module and needing to know which layer it falls into,
  or whether it would be allowed to import what it needs.
- Asked whether one layer depends on another it should not, or which
  import is the one crossing a boundary.

## When not to use

- Finding modules that import each other in a cycle — that is
  `import-cycle-finder`, which asks about cycles, not boundaries; a
  cycle can exist entirely within one layer with no boundary crossed.
- Checking whether a name follows the repository's naming
  conventions — that is `naming-consistency-check`.
- A repository with no declared layer map — this skill has nothing to
  check imports against until one exists.

## @requires

- REQUIRED: a repository directory.
- REQUIRED: `layers` — the layer map (see `assets/layers.example.json`
  for the shape: layers, paths, allowed).
- OPTIONAL: `exclude` — directory names to skip beyond the usual
  vendored and build directories (default: none).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a directory,
and the layer map names a non-empty, unique `layers` list, a `paths`
entry covering every layer with a non-empty list of directory
prefixes, and an `allowed` map whose keys and listed values are all
layer names — a layer missing from `allowed` may import nothing but
itself. Then build the graph — the mechanical part (SDS-S-060):

```
python3 scripts/check_layers.py <repo> --layers <layers.json> [--exclude dir,dir]
```

It resolves the same import edges as the family's import-graph
resolver — every Python `import`/`from ... import` via `ast`, and
every relative JavaScript/TypeScript `import`/`export ... from`/
`require()` by pattern — assigns each source file to the layer whose
`paths` prefix matches it, or to no layer if none matches, and reports
each resolved edge that crosses from one layer into a layer not on the
source layer's `allowed` list as `arch/layer-violation` (error, at the
importing file with the import's line), and each source file matched
by no `paths` prefix as `arch/unassigned-module` (info, at most one
per file). A same-layer import and an import that resolves to no
module in the repository never fire. `tool.properties` carries the
layer names, the count of modules assigned to a layer, the count left
unassigned, and the violation count.

### Analyze

The graph is exact for what it resolves; this stage supplies what it
cannot (SDS-S-061). An unassigned module may be a genuine gap in the
layer map — a directory nobody added to `paths` yet — or a file that
legitimately sits outside the layered part of the repository, such as
a one-off script; check its directory before proposing a fix. A
violation between two adjacent layers is often one call that should go
through an existing seam; a violation that skips several layers at
once usually signals a missing abstraction.

### Classify

Keep the script's severities; prefix each finding's `message.text`
with what the violation implies for the reader — `[route through the
seam]` for an adjacent-layer violation, `[missing abstraction]` for
one that skips more than one layer, `[confirm: intentionally outside
the layer map]` for an unassigned module that may not be a defect.

### Synthesize

Return the finding-list, errors first, with a one-line summary of the
layer with the most violations. A repository where every import
respects its layer's allowed list, and every source file is assigned
to a layer, yields a well-formed finding-list with an empty `results`
array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per layer violation or unassigned module, located at the
importing file (a violation carries the import's line in
`region.startLine`) or at the file itself (an unassigned module); a
violation carries `fromLayer`, `toLayer`, `importer`, and `imported`
in `properties`, an unassigned module carries `module`;
`runs[0].tool.properties` carries the layer names and the assigned,
unassigned, and violation counts. Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `layers-invalid`: `--layers` is missing, its file is missing or is
  not valid JSON, or its content fails validation — a missing
  `layers`, `paths`, or `allowed` key; `layers` not a non-empty list
  of unique strings; `paths` not covering every layer with a
  non-empty list of directory prefixes; or `allowed` naming a layer
  not in `layers`.
- `source-unparseable`: a Python file does not parse.

## @example

**Input:** `src/domain/order.py` does `import src.infrastructure.db`,
and the layer map's `allowed` has no entry for `domain` — domain may
import nothing but itself.

**Output (excerpt):**

```json
{
  "ruleId": "arch/layer-violation",
  "level": "error",
  "message": { "text": "src/domain/order.py (layer 'domain') imports src/infrastructure/db.py (layer 'infrastructure'), which is not in allowed['domain']" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "src/domain/order.py" }, "region": { "startLine": 2 } } }],
  "properties": { "fromLayer": "domain", "toLayer": "infrastructure", "importer": "src/domain/order.py", "imported": "src/infrastructure/db.py" }
}
```
