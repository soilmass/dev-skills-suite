---
name: license-compliance-check
description: >-
  Checks every component license in a CycloneDX BOM against the
  repository's own SPDX license using a stated compatibility policy —
  strong copyleft into permissively licensed or proprietary code is
  incompatible, weak copyleft needs review, unknown is unknown,
  deprecated SPDX identifiers are flagged — and reports the result as a
  finding-list. Use before a release or a dependency addition, when
  asked whether the dependencies' licenses are acceptable, or with
  sbom-generator's output in hand.
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
  Bash(python3 scripts/check_licenses.py:*) Read
---

# license-compliance-check

## When to use

- Before a release, to confirm nothing in the BOM conflicts with how
  the repository is licensed and distributed.
- Before adding a dependency whose license is unfamiliar.
- Asked whether the dependencies' licenses are acceptable.

## When not to use

- Producing the BOM — that is `sbom-generator`; this skill consumes
  its CycloneDX output (or any CycloneDX BOM).
- Finding vulnerabilities — that is `dependency-audit`.
- Legal advice. The policy here is a stated engineering default; an
  actual distribution decision for a contested case belongs to whoever
  owns licensing. If a case is contested, the category table and its
  rationale are in `references/license-categories.md` — consult it only
  then.

## @requires

- REQUIRED: `bom` — a CycloneDX BOM (JSON) with a `components` array.
- REQUIRED: `own-license` — the repository's own license as an SPDX
  identifier, or `proprietary`.
- OPTIONAL: `allow` — SPDX identifiers that pass regardless of
  category (default: none; each use is reported as allowlisted).
- OPTIONAL: `deny` — SPDX identifiers that fail regardless of category
  (default: none).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the BOM parses and is
CycloneDX; the project license is a recognized identifier. Then check
— the mechanical part (SDS-S-060):

```
python3 scripts/check_licenses.py --bom <bom.json> --own-license <SPDX-id> [--allow ids] [--deny ids]
```

It reads one local file (rung 1) and prints a `finding-list` with
`license/incompatible` (error), `license/review` and
`license/unknown` (warning), and `license/nonstandard-id` and
`license/allowlisted` (info). SPDX expressions with `OR` pass if any
alternative passes; with `AND`, every part must. A nonzero exit maps
to `@throws`.

### Analyze

The policy is a default; this stage applies context (SDS-S-061). An
`incompatible` finding is a fact about the licenses, not necessarily
about this repository: if the code is never distributed (an internal
service, a build tool), say so and why the obligation is not
triggered — but keep the finding. A `review` finding needs the
linking mode (dynamic vs static, separate process vs same binary)
to resolve; ask if unknown. An `unknown` finding is the one to chase
first: check the package's repository for a LICENSE file and record
what you found and where. If a category assignment seems wrong for
the case, consult `references/license-categories.md` — only then.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the resolution — `[blocking]`, `[acceptable: <reason>]`,
`[needs owner decision]`, `[resolved: <license found at …>]` — never
delete a finding; a resolved one stays in the list as the record of
why it was fine.

### Synthesize

Return the finding-list, `error` first, with a summary line counting
blocking, acceptable, and undecided items. A BOM whose every component
passes yields a well-formed finding-list with an empty `results` array
(SDS-C-033) — "all licenses compatible" is the finding.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per component-license outcome that is not a clean pass,
located by purl, with `properties` holding the component, version,
the license expression, and the project license and category it was
judged against. Nothing was modified.

## @throws

- `bom-unparseable`: the BOM file is unreadable or not JSON.
- `bom-invalid`: the file is not a CycloneDX BOM with a `components`
  array.
- `bad-argument`: the project license is not a recognized identifier.

## @example

**Input:** an MIT repository whose BOM lists `lodash` (MIT),
`readline-gpl` (GPL-3.0-only), `libfoo` (LGPL-2.1-or-later),
`mystery-lib` (no license), and `old-id-lib` (deprecated `GPL-2.0`).

**Output (excerpt):**

```json
{
  "ruleId": "license/incompatible",
  "level": "error",
  "message": { "text": "[blocking] readline-gpl@8.2.0: GPL-3.0-only (strong-copyleft) cannot be combined with a permissive codebase" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "pkg:generic/readline-gpl@8.2.0" } } }],
  "properties": { "component": "readline-gpl", "version": "8.2.0", "license": "GPL-3.0-only", "projectLicense": "MIT", "projectCategory": "permissive" }
}
```
