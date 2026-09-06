---
name: findings-digest
description: >-
  Merges the finding-lists that any number of audit skills produced
  into one status-report — totals, counts by tool, severity, and rule,
  the files with the most findings, and every error listed, with
  duplicates across overlapping audits counted once — then judges
  what to fix first and which findings are noise. Use after running
  several audits on one repository, when a review or a release needs
  one page instead of ten JSON files, or when asked what the audits
  found overall.
license: Apache-2.0
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: status-report
  shape-in: finding-list
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/digest_findings.py:*) Read
---

# findings-digest

## When to use

- Several audit skills ran on one repository and someone needs one
  page.
- A review, a release, or a weekly report wants the audits' totals
  and their errors in a form people read.
- Asked what the audits found overall, or whether anything is an
  error.

## When not to use

- Ranking one audit's findings — the producing skill's own Analyze
  stage does that with domain knowledge; this skill counts across
  tools and knows nothing about any one of them.
- Filing the findings as GitHub issues — a Command Skill's job; this
  skill writes nothing and calls nothing.
- Trend over time — this skill digests one set of inputs; keep the
  reports and diff them.

## @requires

- REQUIRED: one or more `finding-list` files as any family audit
  skill emits (`-` for stdin).
- OPTIONAL: `min-level` — the lowest severity to count and list: `info`,
  `warning`, `error` (default: `info`).
- OPTIONAL: `top` — the length of each listing (default: 10).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): every input reads and
has a `runs` array of results. Then merge — the mechanical part
(SDS-S-060):

```
python3 scripts/digest_findings.py <finding-list.json>... [--min-level info|warning|error] [--top N]
```

It merges results across inputs and runs, counts a result once when
two inputs carry the same rule, location, and message, and writes
the six sections in order: Totals, By tool, By level, Top rules,
Files with most findings, Errors. `generatedFrom` names the inputs.
Nothing is run (rung 1).

### Analyze

The digest counts; this stage decides what the counts mean
(SDS-S-061). Errors from a security or correctness tool
(`dependency-audit`, `schema-migration-review`,
`test-data-pii-scan`) come before errors from a hygiene tool
whatever the numbers. A file at the top of "Files with most
findings" across several tools is a hotspot — name it and say
whether the findings share a cause. A rule that fires many times is
either systemic (one fix, many findings — say which fix) or noise
(the tool's threshold is wrong for this repository — say so, and
which threshold). Duplicates merged above zero means two audits
overlap; note which, so the team runs one. Say what the digest
cannot see: findings below the floor, and tools that were not run.

### Classify

Prefix each listed error with the action in the report's Errors
section when you rewrite it — `[fix first: security]`, `[fix once:
<shared cause>]`, `[noise: raise threshold]`, `[accept: documented]`
— and leave the counts as the script wrote them.

### Synthesize

Return the status-report with the summary line first, the Totals and
By tool sections next, then the ranked errors from Analyze, then the
hotspots and systemic rules. Inputs with no results yield a
well-formed status-report whose totals are zero (SDS-C-033).

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

`summary` gives the count across tools and whether errors exist;
`generatedFrom` names the inputs; `sections` are Totals, By tool, By
level, Top rules, Files with most findings, and Errors, in that
order. Nothing was modified.

## @throws

- `input-missing`: an input file cannot be read.
- `input-invalid`: an input is not JSON, or is not a finding-list (no
  `runs` array, a run without `results`, a result without `ruleId`).
- `level-invalid`: `min-level` is not one of the three, or `top` is
  not a positive integer.

## @example

**Input:** the finding-lists of `dependency-audit`,
`ci-pipeline-audit`, and `retry-timeout-audit` on one repository.

**Output (excerpt):**

```json
{
  "summary": "20 finding(s) across 3 tool(s): 3 error(s) to fix first",
  "generatedFrom": "dependency-audit.json, ci-pipeline-audit.json, retry-timeout-audit.json",
  "sections": [
    { "heading": "Totals", "body": "20 finding(s) at or above info from 3 input(s) and 3 tool(s); 3 error(s), 10 warning(s), 7 info(s); 0 duplicate(s) merged." },
    { "heading": "By tool", "body": "- ci-pipeline-audit: 7\n- retry-timeout-audit: 7\n- dependency-audit: 6" }
  ]
}
```
