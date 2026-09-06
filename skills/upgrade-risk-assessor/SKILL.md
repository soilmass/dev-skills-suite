---
name: upgrade-risk-assessor
description: >-
  Assesses how risky one dependency upgrade is for this repository —
  from the semver jump, every module that imports the package and
  every symbol it uses (found in the syntax tree, not guessed), and
  the changelog's breaking entries matched against those symbols —
  as a decision-doc rating the upgrade low, medium, or high, or
  flagging a downgrade or an unused dependency. Use before merging a
  dependency bump, when a bot opened a major-version pull request, or
  when asked whether an upgrade is safe.
license: Apache-2.0
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: decision-doc
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/assess_upgrade.py:*) Read
---

# upgrade-risk-assessor

## When to use

- Before merging a dependency bump, especially one a bot opened.
- A major-version upgrade is proposed and nobody has read the
  changelog.
- Asked whether an upgrade is safe, or what it would touch.

## When not to use

- Finding vulnerable versions — that is `dependency-audit`; this
  skill assesses one chosen upgrade, not the whole tree.
- Planning the migration a high-risk upgrade needs — that is
  `migration-plan-writer`, which consumes this assessment.
- Fetching the changelog — do that first (the package's repository
  release page or CHANGELOG) and pass the file; this skill reads no
  network.
- Non-Python packages, for now.

## @requires

- REQUIRED: the repository directory.
- REQUIRED: `package`, `from`, and `to` — the dependency and the two
  versions.
- OPTIONAL: `changelog` — the package's changelog or release notes
  covering the range, as a file (default: none, and the assessment
  says the breaking changes are unknown).
- OPTIONAL: `exclude` — directories to skip (default: none).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a
directory and both versions parse. Then assess — the mechanical part
(SDS-S-060):

```
python3 scripts/assess_upgrade.py <repo> --package <name> --from <v> --to <v> [--changelog-file <path>]
```

It classifies the jump, finds every importing module and used
symbol with `ast` (rung 1; nothing is installed or run), extracts
the changelog's breaking lines for the version range, matches them
against the used symbols, and applies the rule table. `facts`
carries the modules, symbols, and matched lines.

### Analyze

The rule table rates the jump; this stage rates it *for this
repository* (SDS-S-061). Read the importing modules: are they on a
request path or in a one-off script? Do they have tests
(`test-coverage-gap-finder` can say)? A `high` on a symbol used once
in a maintenance script is a small, mechanical fix; a `low` patch
bump of a package that pins a transitive dependency the tree also
uses may not be low at all — check the lockfile diff. A missing
changelog is itself a finding: say what was not read. For anything
above `low`, name the first test to run against the new version.

### Synthesize

Return the decision-doc, leading with the rating and the one
sentence that justifies it, then the importing modules and used
symbols, the matched breaking lines with what to change, and the
recommended first test. A package the tree never imports yields a
valid decision-doc rated `unused` (SDS-C-033).

## @returns

Shape: `decision-doc` — see `kit/shapes/decision-doc.schema.json`.

`chosenOption` is `low`, `medium`, `high`, `downgrade`, or `unused`;
`decisionDrivers` state the jump, the usage counts, and the changelog
match; `consequences.negative` lists each used symbol a breaking
line names; `facts` carries the modules, symbols, and breaking lines.
Nothing was installed and nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `version-invalid`: `from` or `to` is not a version.
- `changelog-unreadable`: the changelog file cannot be read.
- `source-unparseable`: a Python file does not parse.

## @example

**Input:** `requests` 2.31.0 → 3.0.0 with a changelog whose 3.0.0
section says "BREAKING: `Session.mount` removed", in a tree that
calls `requests.Session().mount`.

**Output (excerpt):**

```json
{
  "decisionOutcome": { "chosenOption": "high", "justification": "1 breaking change(s) name symbols this tree uses: requests.Session.mount" },
  "decisionDrivers": ["jump: 2.31.0 -> 3.0.0 (major)", "usage: imported by 2 module(s); 4 symbol(s) used", "changelog: 2 breaking line(s), 1 naming a used symbol"],
  "facts": { "importingModules": ["app/http.py", "app/upload.py"], "usedSymbols": ["requests.Session", "requests.Session.mount", "requests.get", "requests.post"] }
}
```
