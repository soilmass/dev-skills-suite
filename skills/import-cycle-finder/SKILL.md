---
name: import-cycle-finder
description: >-
  Builds a repository's Python and JavaScript/TypeScript import graph
  and reports strongly connected components as import cycles — an
  error for three or more mutually importing modules, a warning for
  two, a warning for a module that imports itself, and an info for a
  relative import that resolves to no module in the repository — as a
  finding-list with the module and edge counts attached. Use before
  splitting a module, when an import fails only in some entry points,
  or when asked whether two modules depend on each other both ways.
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
  Bash(python3 scripts/find_import_cycles.py:*) Read
---

# import-cycle-finder

## When to use

- Before splitting a large module, to see what would have to move
  together.
- An import fails only when the entry point changes, or only under a
  particular import order — the classic symptom of a cycle.
- Asked whether two modules depend on each other both ways, or which
  modules form the tightest import cluster.

## When not to use

- Checking whether one layer imports another it should not — that is
  `layer-boundary-check`, which asks about boundaries between layers,
  not cycles; a cycle can exist entirely within one layer.
- Finding code nothing calls — that is `dead-code-finder`; this skill
  follows import edges, not reference counts.
- Languages other than Python and JavaScript/TypeScript, for now.

## @requires

- REQUIRED: a repository directory.
- OPTIONAL: `lang` — `python`, `js`, or `auto` to scan both (default:
  `auto`).
- OPTIONAL: `exclude` — directory names to skip beyond the usual
  vendored and build directories (default: none).
- OPTIONAL: `max-cycles` — cap on the number of cycle findings
  returned (default: unlimited).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a
directory, `lang` is one of the accepted values, and `exclude` has no
empty entry. Then build the graph — the mechanical part (SDS-S-060):

```
python3 scripts/find_import_cycles.py <repo> [--lang python|js|auto] [--exclude dir,dir] [--max-cycles N]
```

It resolves every `import`/`from ... import` (Python, via `ast`) and
every relative `import`/`export ... from`/`require()` (JavaScript and
TypeScript, by pattern) to a module inside the repository, runs
Tarjan's algorithm over the resulting directed graph, and reports each
strongly connected component of two or more modules as
`arch/import-cycle` (error at three or more modules, warning at two),
each module that imports itself as `arch/self-import` (warning), and
each relative import that resolves to no module in the repository as
`arch/unresolved-import` (info). A bare, non-relative import that
resolves to nothing is external to the repository and is not
reported. `tool.properties` carries the module and edge counts, the
total cycle count before `max-cycles` truncates the list, the largest
cycle's size, and whether truncation happened.

### Analyze

The graph is exact for what it resolves; this stage supplies what it
cannot (SDS-S-061). A cycle inside one module's own package is often
an artifact of how a package was split and is cheap to fix by moving
the shared piece down; a cycle that crosses top-level packages is
usually a real layering problem. An `arch/unresolved-import` may be a
typo, a file deleted without updating its importer, or a module
generated at build time that does not exist in the tree being
scanned — check before treating it as a defect.

### Classify

Keep the script's severities; prefix each finding's `message.text`
with what the cycle implies for the reader — `[extract the shared
piece]` for a same-package cycle, `[layering problem]` for a
cross-package one, `[confirm: generated at build time]` for an
unresolved import that may not be a defect.

### Synthesize

Return the finding-list, errors first, with a one-line summary of the
largest cycle found. A repository with no cycles and no unresolved
relative imports yields a well-formed finding-list with an empty
`results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per cycle, self-import, or unresolved relative import,
located at the cycle's lexicographically first module (or the
importing file, for a self-import or an unresolved import), with the
cycle's modules, size, and internal edge count in `properties`;
`runs[0].tool.properties` carries the module and edge totals, the
cycle count, the largest cycle's size, and whether the list was
truncated. Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a Python file does not parse.
- `lang-invalid`: `lang` is not `python`, `js`, or `auto`.
- `exclude-invalid`: `exclude` contains an empty entry.

## @example

**Input:** `orders/api.py` does `import orders.db`, and
`orders/db.py` does `import orders.api` to reuse a formatting helper —
a two-module cycle.

**Output (excerpt):**

```json
{
  "ruleId": "arch/import-cycle",
  "level": "warning",
  "message": { "text": "[extract the shared piece] import cycle of 2 modules: orders/api.py -> orders/db.py -> orders/api.py" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "orders/api.py" } } }],
  "properties": { "modules": ["orders/api.py", "orders/db.py"], "size": 2, "edges": 2 }
}
```
