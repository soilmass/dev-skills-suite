---
name: sla-error-budget-check
description: >-
  Answers one question before a release — do the error budgets allow
  it? — by reading the service's OpenSLO definitions and the measured
  good/total counts per window, computing each SLO's remaining budget
  and its 1h and 6h burn rates, and applying a fixed rule table
  (exhausted or fast-burning freezes; low or unmeasured cautions;
  all healthy proceeds) into a decision-doc that says which SLO
  decided it. Use before a deploy under an error-budget policy, when
  an SLO alert fired and someone asks whether to ship anyway, or when
  asked how much budget is left.
license: Apache-2.0
compatibility: Requires pyyaml (OpenSLO definitions are YAML). The
  measurements are supplied as a file; obtaining them from Prometheus
  or a vendor is outside this skill.
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: decision-doc
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/check_error_budget.py:*) Read
---

# sla-error-budget-check

## When to use

- A release is going out under an error-budget policy.
- A burn-rate alert fired and someone asks whether to ship anyway.
- Asked how much of the budget is left, or which SLO is in trouble.

## When not to use

- Writing or tuning the SLOs and their alerts — `alert-fatigue-audit`
  judges the alert rules; this skill takes the SLOs as given.
- Getting the numbers — the good/total counts come from the metrics
  system by a query this skill does not run; supply them as the
  measurements file.
- Merging or publishing — `pr-lifecycle-manager` and
  `release-publisher` can consume this decision; this skill decides
  and stops.

## @requires

- REQUIRED: the OpenSLO file — one or more `kind: SLO` documents
  with a name, an objective target, and a time window.
- REQUIRED: `measurements` — the good and total event counts per
  SLO for its window and, optionally, the 1h and 6h windows.
- REQUIRED: `as-of` — the timestamp the counts were taken.
- OPTIONAL: `caution-below` — the remaining-budget ratio under which
  a healthy SLO becomes `low` (default: 0.25).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the OpenSLO file
parses and every SLO has a target in (0, 1) and a window; the
measurements file has an `slos` object. Then decide — the
mechanical part (SDS-S-060):

```
python3 scripts/check_error_budget.py <openslo.yaml> --measurements-json-file <path> --as-of <ISO> [--caution-below 0.25]
```

It computes, per SLO, the SLI, the budget remaining, and the burn
rates, assigns a state (`no-data`, `exhausted`, `burning`, `low`,
`healthy`), and chooses `freeze`, `caution`, `proceed`, or
`no-slos` by the rule table in the script's docstring (rung 1;
nothing is queried).

### Analyze

The rule table is in the script; this stage reads the decision-doc
and adds what the table cannot know (SDS-S-061). A `freeze` on an
exhausted budget with low burn rates means the damage is old — say
when the budget resets (the window is rolling) and whether the
release is a fix for the cause, which the policy usually exempts. A
`freeze` on `burning` with most of the budget left is an incident in
progress: the question is not the release but the page. A `caution`
on `no-data` for one SLO is a measurement gap, not a reliability
signal — name the missing window. A `proceed` with one SLO just
above the caution line deserves the number in the summary.

### Synthesize

Return the decision-doc, leading with `chosenOption` and the SLO
that decided it, then one line per SLO (state, SLI, remaining, burn
rates), then the notes from Analyze. Say when the counts were taken
and that the check must be re-run before releasing.

## @returns

Shape: `decision-doc` — see `kit/shapes/decision-doc.schema.json`.

`chosenOption` is `proceed`, `caution`, `freeze`, or `no-slos` (the
file defines no SLO, so there is no budget to check — not the same
as healthy); `justification` names the deciding SLOs and their
states; `decisionDrivers` carries one line per SLO with its state,
SLI, remaining budget, and burn rates; `consequences.negative` lists
the SLOs not healthy. Nothing was modified.

## @throws

- `slo-unparseable`: the OpenSLO file is missing or not valid YAML.
- `slo-invalid`: an SLO document lacks a name, a target in (0, 1),
  or a time window.
- `measurements-unparseable`: the measurements file is not JSON or
  lacks an `slos` object.
- `as-of-invalid`: `as-of` is missing or does not parse, or
  `caution-below` is not a ratio.

## @example

**Input:** three SLOs; `checkout-success` at 99.5% over 28d with
80% of its budget left but 100 failures in the last 1,000 checkouts.

**Output (excerpt):**

```json
{
  "status": "accepted",
  "decisionOutcome": { "chosenOption": "freeze", "justification": "checkout-success is burning; the budget policy stops feature releases until the burn is under the threshold" },
  "decisionDrivers": ["checkout-success (99.500% over 28d): burning — SLI 99.9000%, budget remaining 80.0%, burn rate 1h 20.0x / 6h 3.3x"]
}
```
