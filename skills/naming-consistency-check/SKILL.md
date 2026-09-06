---
name: naming-consistency-check
description: >-
  Finds Python identifiers that break the naming convention the rest
  of the repository already follows — a camelCase function among
  snake_case ones, a lowercase class, a constant that is not
  UPPER_CASE where the others are — by counting the styles actually
  in use per kind and reporting the minority, never by imposing PEP 8;
  plus one- and two-letter names a reader cannot decode. Returns a
  finding-list for human review. Use before a cleanup, when reviewing
  code from a new contributor, or when asked whether naming is
  consistent.
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
  Bash(python3 scripts/check_naming.py:*) Read
---

# naming-consistency-check

## When to use

- Before a cleanup, to see where the repository disagrees with
  itself.
- Reviewing a contribution from someone new to the repository's
  conventions.
- Asked whether naming is consistent, or which convention a tree
  actually uses.

## When not to use

- Enforcing a house style the tree does not yet follow — this check
  reports the *majority* convention; a tree that is consistently
  camelCase gets no function findings. Adopting PEP 8 is a decision,
  not a finding.
- Debt markers, dead code, or stale comments — `tech-debt-inventory`,
  `dead-code-finder`, and `code-comment-audit` respectively.
- Non-Python sources, for now.

## @requires

- REQUIRED: a repository directory containing Python sources.
- OPTIONAL: `exclude` — directories to skip beyond the usual vendored
  and build directories (default: none).
- OPTIONAL: `min-votes` — how many identifiers of a kind must exist
  before a dominant style is declared for it (default: 3).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a directory.
Then scan — the mechanical part (SDS-S-060):

```
python3 scripts/check_naming.py <repo> [--exclude dir,dir] [--min-votes N]
```

It parses every `.py` file with `ast` (rung 1; nothing is imported or
run), classifies each declared function, class, module-level
constant, module-level variable, and argument by style
(`snake_case`, `camelCase`, `CapWords`, `UPPER_CASE`), takes the
majority per kind as that kind's dominant convention, and reports
`naming/mixed-convention` for every identifier in the minority and
`naming/ambiguous-short-name` for function and argument names of one
or two characters outside lambdas and comprehensions. The run's
`tool.properties` carries the dominant style and vote counts per
kind, so the reader sees what the tree decided. A file that does not
parse stops the scan (`source-unparseable`).

### Analyze

The scan reports disagreement; this stage decides what to do about
each (SDS-S-061). A deviant name that is *public* — exported,
imported by other repositories, part of a wire contract — cannot be
renamed without a deprecation, so the finding becomes a note, not a
task. A deviant that mirrors an external API (a camelCase argument
that matches a JSON field) may be deliberate; say so. A kind whose
votes are close to even (say 5 vs 4) has no real convention yet, and
the useful output is "pick one", not a list of renames. Short names
come in conventional pairs — `lo`/`hi`, `x`/`y` in geometry, `i`/`j`
in index arithmetic — that a human dismisses at a glance.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[rename]`, `[keep: public API]`, `[keep: mirrors
external name]`, `[keep: conventional pair]`, `[decide convention]` —
and, for a rename, propose the conforming name.

### Synthesize

Return the finding-list, warnings first, grouped by file, opening
with the dominant convention per kind and the vote counts. A
consistent tree yields a well-formed finding-list with an empty
`results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per deviant identifier, located at its declaration, with
`properties` carrying the kind, the identifier's style, the dominant
style, and the vote counts; `runs[0].tool.properties` carries the
dominant style per kind. Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a Python file does not parse.

## @example

**Input:** a snake_case module where `fetchOrders(customerId)` was
pasted in from a JavaScript-flavoured branch.

**Output (excerpt):**

```json
{
  "ruleId": "naming/mixed-convention",
  "level": "warning",
  "message": { "text": "[rename -> fetch_orders] function 'fetchOrders' is camelCase; this tree's functions are snake_case (6 of 7)" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "orders.py" }, "region": { "startLine": 35 } } }],
  "properties": { "kind": "function", "name": "fetchOrders", "style": "camelCase", "dominant": "snake_case", "votes": { "snake_case": 6, "camelCase": 1 } }
}
```
