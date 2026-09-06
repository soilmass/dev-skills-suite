---
name: deprecation-sweep
description: >-
  Finds every use of a deprecated symbol in a Python repository — from
  a maintained deprecation list, resolved through imports, aliases,
  and one hop of assignment — and every DeprecationWarning a captured
  test log attributed to the tree, rating each by whether a target
  version removes it, as a finding-list that becomes the pre-upgrade
  work list. Use before a major dependency or interpreter upgrade,
  when a test run is noisy with warnings, or when asked what will
  break next release.
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
  Bash(python3 scripts/sweep_deprecations.py:*) Read
---

# deprecation-sweep

## When to use

- Before upgrading a dependency or the interpreter past a version
  that removes things.
- The test run prints a wall of DeprecationWarnings nobody reads.
- Asked what will break at the next major release.

## When not to use

- Rating one upgrade's overall risk — that is `upgrade-risk-assessor`;
  its `facts.breakingLines` can seed this skill's deprecation list.
- Third-party warnings alone — this skill files them as informational;
  the fix is the dependency's upgrade, not this tree.
- Running the tests to capture warnings — do that first
  (`python -W always -m pytest 2>warnings.log`); this skill reads the
  log and runs nothing.

## @requires

- REQUIRED: the repository directory.
- REQUIRED: at least one of `deprecations` — a JSON list
  `{deprecations: [{symbol, replacement?, removedIn?, since?}]}` —
  or `warnings-log` — a captured run whose lines carry Python's
  `path:line: DeprecationWarning: text` form.
- OPTIONAL: `target-version` — the version being upgraded to; uses
  whose removal is at or below it become errors (default: none, all
  warnings).
- OPTIONAL: `exclude` — directories to skip (default: none).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a
directory and at least one source is given. Then sweep — the
mechanical part (SDS-S-060):

```
python3 scripts/sweep_deprecations.py <repo> [--deprecations <list.json>] [--warnings-log <log>] [--target-version <v>]
```

It resolves each listed symbol through `import … as`, `from … import`,
and one assignment hop with `ast` (rung 1; nothing is run), reports
`deprecation/usage` at every use site, parses the log for
`deprecation/warning-emitted` (inside the tree) and
`deprecation/warning-external` (a dependency's own use), and marks a
finding an error when its removal version is at or below the target.
`tool.properties` carries the target, the listed symbols, and the
blocking count.

### Analyze

The sweep is exhaustive; this stage orders the work (SDS-S-061).
Errors block the upgrade and go first, grouped by replacement so one
mechanical change closes many sites. A warning whose replacement
exists today is cheap — do it in the same pull request as the
upgrade. A warning whose replacement does not exist yet in the
current version (the note says "in 3.0 use …") waits for the
upgrade itself. An external warning that names a dependency the
tree pins is that dependency's upgrade; add it to the same plan.
A deprecated use inside a test that asserts the old behaviour is a
test to rewrite, not a shim to add.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[replace now: <replacement>]`, `[replace during
upgrade]`, `[upgrade <dependency>]`, `[rewrite test]`, `[suppress:
<reason>]` (only for an external warning with no upgrade
available).

### Synthesize

Return the finding-list, errors first, grouped by replacement, with
the work list in the order to do it and the count of sites per
change. A tree with no deprecated use yields a well-formed
finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per use site or warning line, located at the file and
line, with the symbol, replacement, removal version, and whether
the target removes it in `properties`; `runs[0].tool.properties`
carries the target, the listed symbols, and the blocking count.
Nothing was run and nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `no-source`: neither a deprecation list nor a warnings log was
  given.
- `deprecations-unparseable`: the list is not the expected shape.
- `log-unreadable`: the warnings log cannot be read.
- `source-unparseable`: a Python file does not parse.

## @example

**Input:** a list marking `requests.Session.mount` removed in 3.0.0,
a tree calling `s.mount(...)` on a `requests.Session()`, target
3.0.0.

**Output (excerpt):**

```json
{
  "ruleId": "deprecation/usage",
  "level": "error",
  "message": { "text": "[replace now: Session.adapters] requests.Session.mount is deprecated since 2.32.0, removed in 3.0.0; use Session.adapters; the target version removes it" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "app/http.py" }, "region": { "startLine": 7 } } }],
  "properties": { "symbol": "requests.Session.mount", "replacement": "Session.adapters", "removedIn": "3.0.0", "imminent": true }
}
```
