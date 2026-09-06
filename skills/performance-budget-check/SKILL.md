---
name: performance-budget-check
description: >-
  Compares measured page metrics against a Lighthouse CI budget.json
  and, optionally, a baseline run, and produces a finding-list of
  over-budget, near-budget, and regressed metrics per path. Use before
  a release, when a bundle or page got slower, when asked whether
  performance is within budget, or when the user mentions Lighthouse,
  Core Web Vitals, or bundle size.
license: Apache-2.0
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: pillar
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/check_budget.py:*) Read
---

# performance-budget-check

## When to use

- Before a release, to confirm every budgeted path is still within
  budget.
- A page or bundle got slower and the question is by how much and
  against what.
- Asked whether performance is "within budget", or the user mentions
  Lighthouse, Core Web Vitals, or bundle size.

## When not to use

- Measuring performance — this skill compares numbers; producing them
  (a Lighthouse run, a bundle analysis) happens before it.
- Explaining *why* a page is slow — that is profiling work; this skill
  tells you which budget line moved, not which function did it.
- Reviewing a SQL query plan — that is `query-plan-review`
  (situational).

## @requires

- REQUIRED: `budget` — a Lighthouse CI `budget.json` (the standard
  budget declaration; SDS-C-031), with per-path timings, resource
  sizes, and resource counts.
- REQUIRED: `metrics` — one measured run as a JSON object keyed by
  path (`timings` in ms, `resourceSizes` in KB, `resourceCounts`).
- OPTIONAL: `baseline` — a previous run in the same metrics shape
  (default: none; regressions are then not reported).
- OPTIONAL: `tolerance` — percent worse than baseline that counts as a
  regression (default: 5).
- OPTIONAL: `near` — percent of headroom below which a metric is
  reported as near its budget (default: 10).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): both files exist and
parse. Then run the comparison — the mechanical part (SDS-S-060):

```
python3 scripts/check_budget.py --budget <budget.json> --metrics <metrics.json> [--baseline <metrics.json>] [--tolerance 5] [--near 10]
```

It reads only the two (or three) local files (rung 1) and prints a
`finding-list` with `perf/over-budget` (error), `perf/regression`
(warning), `perf/near-budget` (info), and `perf/no-data` (info). A
nonzero exit maps to `@throws`.

### Analyze

The script says which lines moved; this stage says which of them
matter (SDS-S-061). Weigh each `over-budget` and `regression` by
whether the metric is user-facing on that path (an interactive-time
breach on `/checkout` outranks a script-size breach on a rarely
visited page), whether the budget itself is stale (a budget set before
a deliberate feature addition is a budget to renegotiate, not a
regression to fix), and whether a `no-data` line hides a measurement
gap rather than a healthy page. Never soften an `over-budget` level
without stating why in the finding.

### Classify

Keep the script's levels unless Analyze gave a reason to change one;
append that reason to the finding's `message.text`. Group findings
for the same path so a reader sees the page's whole picture.

### Synthesize

Return the finding-list, `error` first. A budget every measurement
satisfies with room to spare yields a well-formed finding-list with an
empty `results` array (SDS-C-033) — "within budget" is the finding.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per budgeted metric that is over, near, regressed, or
unmeasured, located by path, with `properties` holding the budget,
the measured value, and (for regressions) the baseline and percent
change. Nothing was modified.

## @throws

- `budget-unparseable`: the budget file is unreadable, not JSON, or
  not an array of entries.
- `metrics-unparseable`: the metrics or baseline file is unreadable
  or not an object keyed by path.
- `bad-argument`: `tolerance` or `near` is not a number.

## @example

**Input:** a budget capping `/checkout` script size at 200 KB; a run
measuring it at 240 KB.

**Output (excerpt):**

```json
{
  "ruleId": "perf/over-budget",
  "level": "error",
  "message": { "text": "/checkout script is 240KB, over its 200KB budget by 20.0%" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "/checkout" } } }],
  "properties": { "path": "/checkout", "category": "resourceSizes", "metric": "script", "budget": 200, "measured": 240, "overBy": 20.0 }
}
```
