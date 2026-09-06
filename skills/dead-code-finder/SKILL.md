---
name: dead-code-finder
description: >-
  Finds Python functions and classes that nothing in the repository
  references — by static name counting over the syntax tree, so it
  deliberately does not report names exported in __all__, referenced
  from strings, or shaped like tests or dunders — and lists them as a
  finding-list for human review, never for automatic deletion. Use
  before a cleanup, when a module has grown suspiciously, or when asked
  what code is unused.
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
  Bash(python3 scripts/find_dead_code.py:*) Read
---

# dead-code-finder

## When to use

- Before a cleanup or a refactor, to find candidates for removal.
- A module has grown and nobody is sure what in it is still called.
- Asked what code is unused.

## When not to use

- Deleting anything. Every finding is a *candidate*; deletion is a
  code change with a review, and the scan's blind spots (below) are
  exactly where deleting on its say-so breaks production.
- Inventorying debt markers or duplicated blocks — that is
  `tech-debt-inventory`; this skill answers a narrower question.
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
python3 scripts/find_dead_code.py <repo> [--exclude dir,dir]
```

It parses every `.py` file with `ast` (rung 1; nothing is imported or
run), collects every top-level definition and every name, attribute,
import, and string literal, and reports each definition whose name
occurs nowhere but its own line as `dead/unreferenced-definition`
(warning). A file that does not parse stops the scan
(`source-unparseable`) rather than being skipped silently.

### Analyze

The scan reports what static counting can see and says so on every
finding; this stage supplies what it cannot (SDS-S-061, SDS-C-048).
For each candidate ask: is it reached by reflection, a plugin
registry, a framework decorator, a CLI entry point in packaging
metadata, or an importer outside this repository? Check the packaging
files (`pyproject.toml` entry points, `setup.cfg`) and any
registration mechanism the codebase uses before believing a name is
dead. A candidate that survives that check is a real removal
candidate; one that does not is a false positive to record, not
delete.

### Classify

Keep the level; prefix each finding's `message.text` with the verdict
— `[remove]`, `[keep: <how it is reached>]`, or `[unsure: ask <owner>]`
— so the list reads as decisions, not just as candidates.

### Synthesize

Return the finding-list sorted by file, with a summary of how many
candidates fall under each verdict. A tree where everything is
referenced yields a well-formed finding-list with an empty `results`
array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per unreferenced top-level function or class, located at
its definition line, with `properties.confidence` `static` and the
Analyze verdict in the message. Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a Python file does not parse.

## @example

**Input:** a tree where `main.py` calls `helper()` and dispatches
`REGISTRY["plugin_hook"]()`, `exported.py` lists `public_api` in
`__all__`, and `unused.py` defines `orphan()` and class `Abandoned`
that nothing mentions.

**Output (excerpt):**

```json
{
  "ruleId": "dead/unreferenced-definition",
  "level": "warning",
  "message": { "text": "[remove] function orphan in unused.py is referenced nowhere in the tree (static scan; dynamic dispatch, reflection, and out-of-tree importers are not visible)" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "unused.py" }, "region": { "startLine": 4 } } }],
  "properties": { "name": "orphan", "kind": "function", "confidence": "static" }
}
```
