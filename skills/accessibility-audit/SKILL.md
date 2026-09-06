---
name: accessibility-audit
description: >-
  Turns axe-core accessibility results — from the browser extension,
  the CLI, Playwright, or Lighthouse — into a finding-list a team can
  triage: one finding per violated rule per page, graded by impact,
  with the WCAG success criteria and conformance (A, AA, AAA) carried
  through, the affected elements listed, and axe's "needs review"
  items kept apart for a human; then judges which findings block a
  release and how to fix them in this repository's components. Use
  before a release with a conformance target, when an accessibility
  report arrives as raw JSON, or when asked what WCAG conformance a
  page meets.
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
  Bash(python3 scripts/audit_axe_results.py:*) Read
---

# accessibility-audit

## When to use

- A release has a WCAG 2.1 AA (or other) conformance target.
- An accessibility scan produced raw JSON nobody has read.
- Asked what level a page meets, or what blocks the audit.

## When not to use

- Running the scan — do that first (`axe <url> --save results.json`,
  or `@axe-core/playwright` in a test); this skill reads the results
  and loads no page.
- Manual accessibility testing (keyboard traversal, screen-reader
  flow) — axe finds roughly a third of issues; say so in every
  report.
- Performance results — that is `performance-budget-check`, the
  Lighthouse sibling.

## @requires

- REQUIRED: axe-core results as JSON — one file, an array, or a
  directory of files (one per page).
- OPTIONAL: `min-impact` — the lowest impact to report: `minor`,
  `moderate`, `serious`, `critical` (default: `minor`).
- OPTIONAL: the conformance target (e.g. WCAG 2.1 AA), for the
  verdict (default: none, and the report counts by A / AA / AAA).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the input is axe
results with a `violations` array. Then convert — the mechanical
part (SDS-S-060):

```
python3 scripts/audit_axe_results.py <results.json | dir> [--min-impact <impact>]
```

It emits `a11y/<rule>` per violated rule per page (critical and
serious → error, moderate → warning, minor → info) with the WCAG
criteria, conformance level, node count, and up to five elements,
and `a11y/needs-review` for each incomplete check. `tool.properties`
carries the pages, totals, and counts by impact and by WCAG level.

### Analyze

The results say what failed; this stage decides what it means for
the release (SDS-S-061). Against a target level, every violation
tagged at or below that level blocks; best-practice rules do not,
and say so. Group findings by the component that renders the
elements — three pages failing `color-contrast` on the same button
class is one fix, not three — and name the component from the
selectors. `needs-review` items on contrast are usually real (a
gradient or image background); on `alt` usually a decorative image
that wants `alt=""` — say which and why. State the limit: axe
finds roughly a third of WCAG issues, so a clean result is
necessary, not sufficient.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[blocks AA: fix <component>]`, `[best practice:
not blocking]`, `[fix once: <shared component>]`, `[review: likely
real]`, `[review: likely decorative, alt=""]`.

### Synthesize

Return the finding-list, errors first, grouped by component then
page, with the conformance verdict in one line (meets / does not
meet <level>, N blocking findings in M components) and the reminder
that manual testing remains. Results with no violations and nothing
incomplete yield a well-formed finding-list with an empty `results`
array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per rule per page, located at the page URL, with impact,
WCAG criteria, conformance (A / AA / AAA), node count, help URL, and
elements in `properties`; `runs[0].tool.properties` carries pages,
totals, and counts by impact and by conformance. Nothing was loaded and
nothing was modified.

## @throws

- `results-unparseable`: a file cannot be read or is not JSON.
- `results-invalid`: a file is not axe results (no `violations`
  array), or a directory holds no `.json` files.
- `impact-invalid`: `min-impact` is not one of the four impacts.

## @example

**Input:** results for `/checkout` with `color-contrast` (serious,
wcag2aa 1.4.3) on four elements.

**Output (excerpt):**

```json
{
  "ruleId": "a11y/color-contrast",
  "level": "error",
  "message": { "text": "[blocks AA: fix PrimaryButton] Elements must meet minimum color contrast ratio thresholds — 4 element(s) on https://shop.example/checkout; WCAG 1.4.3 (AA)" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "https://shop.example/checkout" } } }],
  "properties": { "impact": "serious", "wcag": ["1.4.3"], "level": "AA", "nodes": 4, "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/color-contrast" }
}
```
