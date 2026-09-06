---
name: public-api-change-check
description: >-
  Compares two versions of a Python package's public surface — the
  names `__all__` exports or that carry no leading underscore, their
  signatures, class methods and attributes — and reports what breaks
  importers: symbols removed, parameters removed, renamed, or made
  required, defaults and return annotations changed, with additions
  as information and a semver verdict (major, minor, patch). Use
  before releasing a library, when reviewing a refactor of a shared
  package, or when asked whether a change is backwards compatible for
  callers.
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
  Bash(python3 scripts/diff_public_api.py:*) Bash(git worktree list:*) Read
---

# public-api-change-check

## When to use

- A library release is being cut and the version bump must match
  the change.
- A refactor touches a package other repositories import.
- Asked whether a change is backwards compatible for callers.

## When not to use

- An HTTP API — that is `openapi-breaking-change-check`; this skill
  reads Python signatures.
- A dependency's upgrade risk *to* this repository — that is
  `upgrade-risk-assessor`; this skill is the other side, what this
  package does to its own importers.
- Behavioural compatibility — the same signature can change what it
  does; this skill sees surface only, and says so.

## @requires

- REQUIRED: the released version's package directory (a checkout, a
  `git worktree`, or an extracted sdist).
- REQUIRED: the proposed version's package directory.

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): both paths are
directories. Then diff — the mechanical part (SDS-S-060):

```
python3 scripts/diff_public_api.py <old-package-dir> <new-package-dir>
```

It parses both trees with `ast` (rung 1; nothing is imported),
builds each public surface (honouring `__all__`, skipping
underscore-prefixed names and modules), and reports
`api/symbol-removed`, `api/param-removed`, `api/param-required-added`
as errors; `api/param-renamed`, `api/param-kind-changed` as warnings;
`api/default-changed`, `api/return-annotation-changed`,
`api/symbol-added` as info. A removed or added module is reported
once, not per member. `tool.properties.verdict` is the semver
verdict.

### Analyze

The diff is exact about surface; this stage judges the release
(SDS-S-061). A removed symbol that was public by accident (no
underscore, never documented, no importer anywhere) can be treated as
private — say how you established it (a search of dependent
repositories, the documentation). A renamed parameter breaks only
keyword callers — check how the documentation shows the call. A
default change is a behaviour change every caller inherits silently;
weigh it as if it were breaking when the old default was
load-bearing. A pre-1.0 package may break by convention, but its
importers are no less broken — say which policy applies. The verdict
is the script's unless a finding is downgraded with a stated reason.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the verdict — `[breaking: bump major]`, `[keep compatible: alias
the old name for one release]`, `[was private in practice: <how
known>]`, `[behaviour change: call out in the changelog]`, `[minor:
document]`.

### Synthesize

Return the finding-list, errors first, with the release verdict in
one line — the version to bump to and why — and the deprecation
shims that would make a major a minor. Identical surfaces yield a
well-formed finding-list with an empty `results` array (SDS-C-033)
and a `patch` verdict.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per surface change, located at the symbol's definition
in the new snapshot (or the old, for removals), with
`properties.symbol` as the dotted path; `runs[0].tool.properties`
carries the symbol counts, the breaking count, and the verdict.
Nothing was imported and nothing was modified.

## @throws

- `package-invalid`: a path is not a directory.
- `source-unparseable`: a Python file does not parse.

## @example

**Input:** old `pricing.price(order, *, currency="USD",
discount=0.0)`; new `price(order, *, currency="EUR", discount)`.

**Output (excerpt):**

```json
{
  "ruleId": "api/param-required-added",
  "level": "error",
  "message": { "text": "[breaking: bump major] pkg.pricing.price: parameter 'discount' lost its default and is now required" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "pricing.py" }, "region": { "startLine": 4 } } }],
  "properties": { "symbol": "pkg.pricing.price", "param": "discount" }
}
```
