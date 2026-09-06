---
name: code-comment-audit
description: >-
  Finds comments and docstrings that no longer match the Python code
  beside them — documented parameters the function does not take,
  comments naming identifiers that no longer exist in the repository,
  and commented-out code — as a finding-list, leaving the call on
  whether a comment misleads to a human. Use during a cleanup, when a
  module's comments feel unreliable, or when asked to audit
  documentation drift inside the code.
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
  Bash(python3 scripts/audit_comments.py:*) Read
---

# code-comment-audit

## When to use

- A cleanup pass, where stale comments cost readers more than no
  comments.
- A module whose comments have stopped being trusted.
- Asked to audit documentation drift inside the code itself.

## When not to use

- Reference documentation outside the code — that is
  `api-doc-writer`, which detects drift between a reference page and
  the signatures.
- Debt markers (`TODO`, `FIXME`) — that is `tech-debt-inventory`; a
  marker is a comment that is *meant* to be there.
- Non-Python sources, for now.

## @requires

- REQUIRED: a repository directory containing Python sources.
- OPTIONAL: `exclude` — directories to skip beyond the usual vendored
  and build directories (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a directory.
Then scan — the mechanical part (SDS-S-060):

```
python3 scripts/audit_comments.py <repo> [--exclude dir,dir]
```

It parses every `.py` file with `ast` and `tokenize` (rung 1; nothing
is imported or run) and reports `comment/stale-param` (a docstring
documents a parameter the signature lacks), `comment/dangling-reference`
(a comment names an identifier defined nowhere in the tree), and
`comment/commented-out-code` (consecutive comment lines that parse as
statements). A file that does not parse stops the scan
(`source-unparseable`).

### Analyze

The scan finds mismatches; this stage decides which mislead
(SDS-S-061). A stale parameter in a docstring is nearly always wrong
and cheap to fix. A dangling reference may be a renamed function (fix
the comment), a deleted one (the comment describes behavior that is
gone — check whether the code still does it), or an external name
the scan cannot see (leave it, say so). Commented-out code is either
dead (delete it; version control remembers) or a note someone needs
(turn it into a sentence saying why).

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[fix comment]`, `[delete]`, `[rewrite as prose]`,
`[keep: external name]` — and, where the comment described behavior
the code no longer has, say what the code does now.

### Synthesize

Return the finding-list, warnings first, grouped by file, with a
summary count per action. A tree with no drift yields a well-formed
finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per mismatch, located at the function or comment line,
with `properties` carrying the evidence (the documented vs actual
parameters, the dangling name and the comment text, the length and
first line of a commented-out run). Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a Python file does not parse.

## @example

**Input:** a module whose `load_order()` docstring still lists a
removed `timeout` parameter, whose `total()` comment cites a deleted
`normalize_rows()`, and which keeps four lines of an old
implementation commented out.

**Output (excerpt):**

```json
{
  "ruleId": "comment/stale-param",
  "level": "warning",
  "message": { "text": "[fix comment] load_order() documents parameter 'timeout' but does not take it (actual: fresh, order_id)" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "drifted.py" }, "region": { "startLine": 4 } } }],
  "properties": { "function": "load_order", "documented": "timeout", "actual": ["fresh", "order_id"] }
}
```
