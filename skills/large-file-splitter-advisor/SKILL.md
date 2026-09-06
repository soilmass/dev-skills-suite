---
name: large-file-splitter-advisor
description: >-
  Finds Python modules over a line budget and proposes where each
  could be split — by building the reference graph between the
  module's module-scope definitions and reporting its independent
  clusters as candidate seams, largest first — as a finding-list for
  human review; it advises, it never moves code. Use when a module
  has grown past what one reader holds in mind, when reviewers keep
  asking "where does this live", or when asked how to break a file
  up.
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
  Bash(python3 scripts/find_split_seams.py:*) Read
---

# large-file-splitter-advisor

## When to use

- A module has grown past what one reader can hold in mind and
  nobody agrees where to cut it.
- Reviews keep asking "where does this live" for the same file.
- Asked how to break a file up, or whether a file is too big.

## When not to use

- Doing the split — this skill is rung 1 and returns advice; the
  move is an ordinary refactor with its own review, and the seams
  here are its input, not its plan.
- A module that is long because of data (tables, fixtures,
  generated code); size is not the concern there and the reference
  graph is empty.
- Dead or unreferenced definitions — that is `dead-code-finder`; an
  isolated cluster of one is often dead code, and this skill will
  only tell you it is isolated.

## @requires

- REQUIRED: a repository directory containing Python sources.
- OPTIONAL: `max-lines` — the line budget a module must exceed to be
  reported (default: 500).
- OPTIONAL: `exclude` — directories to skip beyond the usual vendored
  and build directories (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a directory.
Then scan — the mechanical part (SDS-S-060):

```
python3 scripts/find_split_seams.py <repo> [--max-lines N] [--exclude dir,dir]
```

For every `.py` file over the budget it parses the module with `ast`
(rung 1; nothing is imported or run), links each top-level function
or class to every other one its body names, and takes the connected
components of that graph as candidate seams. `size/oversized-module`
(warning) carries the seams — each with its definitions, line span,
and line count, largest first; `size/single-cluster` (info) means
every definition reaches every other and there is no mechanical
seam. Module-level constants and imports are not nodes: any cluster
that moves may need some of them. A file that does not parse stops
the scan (`source-unparseable`).

### Analyze

The graph says what *could* move together; this stage decides what
*should* (SDS-S-061). A seam is a good module boundary when it has a
name — "reporting", "order pricing" — and a reader would look for it
there; a cluster that is merely the set of things nothing else calls
is not a module, it is a candidate for `dead-code-finder`. A
single-cluster module usually has a responsibility split that the
reference graph cannot see (two concepts that share one utility);
the advice is to name the concepts and extract the shared utility
first. Check what each cluster needs from module scope (constants,
imports) and what outside the module imports from it — a public name
that moves needs a re-export or a deprecation.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[split: <name-a> / <name-b>]`, `[extract shared
utility first]`, `[leave: data module]`, `[leave: cohesive]` — and,
for a split, propose a module name per seam and list the module-scope
names it takes along.

### Synthesize

Return the finding-list, warnings first, largest module first, each
oversized module followed by its proposed target modules and what
moves where. A tree with no oversized module yields a well-formed
finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per module over the budget, located at line 1, with
`properties` carrying `lines`, `maxLines`, `definitions`, and `seams`
(each a `definitions` list with `startLine`, `endLine`, `lines`).
Nothing was modified; the split, if adopted, is a separate change.

## @throws

- `repo-invalid`: the path is not a directory.
- `budget-invalid`: `max-lines` is not a positive integer.
- `source-unparseable`: a Python file does not parse.

## @example

**Input:** a 54-line `shop.py` scanned with a 40-line budget; its
order-pricing definitions and its reporting definitions never name
each other.

**Output (excerpt):**

```json
{
  "ruleId": "size/oversized-module",
  "level": "warning",
  "message": { "text": "[split: reporting / order pricing] shop.py is 54 lines (budget 40); its 7 definitions fall into 2 independent clusters — [Report, format_row, render_report, _pad] (18 lines); [OrderLine, load_order, total_for] (13 lines)" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "shop.py" }, "region": { "startLine": 1 } } }],
  "properties": {
    "lines": 54, "maxLines": 40, "definitions": 7,
    "seams": [
      { "definitions": ["Report", "format_row", "render_report", "_pad"], "startLine": 31, "endLine": 54, "lines": 18 },
      { "definitions": ["OrderLine", "load_order", "total_for"], "startLine": 12, "endLine": 28, "lines": 13 }
    ]
  }
}
```
