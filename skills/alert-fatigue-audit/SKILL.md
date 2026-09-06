---
name: alert-fatigue-audit
description: >-
  Finds the alerts that page people without telling them anything —
  from an Alertmanager-shaped alert history and, optionally, the
  Prometheus rules behind it: alerts fired many times and never
  acknowledged, alerts that flap for minutes at a time, conditions
  that have been "firing" for a week, alerts with no runbook, pairs
  that always fire together, and rules that never fire — as a
  finding-list, leaving the call on delete, re-threshold, or reroute
  to a human. Use after an on-call retrospective, when pages are
  being ignored, or when asked which alerts are noise.
license: Apache-2.0
compatibility: Requires PyYAML when a Prometheus rules file is
  supplied with --rules.
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/audit_alerts.py:*) Read
---

# alert-fatigue-audit

## When to use

- After an on-call retrospective where "we ignore that one" was
  said out loud.
- Pages are being acknowledged late or not at all.
- Asked which alerts are noise, or why on-call is exhausting.

## When not to use

- Investigating one incident — that is `incident-postmortem`; this
  skill reads a month of alerts, not one night.
- Designing the alerts for a new service — write the SLOs first;
  this skill needs history to judge.
- Exporting the history — do that first (`amtool alert --output
  json`, or the Alertmanager `/api/v2/alerts` endpoint over time, or
  the paging vendor's export mapped to the same shape); this skill
  reads a file and calls nothing.

## @requires

- REQUIRED: the alert history as a JSON array in the Alertmanager
  API v2 alert shape (`labels.alertname`, `startsAt`, `endsAt`,
  `status.state`, `annotations.runbook_url`), with an
  `acknowledged` boolean per firing where the paging tool records
  it.
- REQUIRED: `as-of` — the moment the audit is made, so open alerts
  and the window are reproducible.
- OPTIONAL: `rules` — the Prometheus alerting-rules file, to report
  rules without a runbook and rules that never fired (default:
  none).
- OPTIONAL: `window-days` — how far back to look (default: 30).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the history parses
as an array of alerts and `as-of` is a timestamp. Then run the
audit — the mechanical part (SDS-S-060):

```
python3 scripts/audit_alerts.py <alerts.json> --as-of <ISO> [--rules <rules.yml>] [--window-days N]
```

It groups firings by `alertname` within the window and reports
`alert/never-acknowledged`, `alert/flapping`, `alert/always-firing`,
`alert/no-runbook`, `alert/co-firing`, and, with rules,
`alert/silent-rule`. The run's `tool.properties` carries the window
and the totals.

### Analyze

The counts say which alerts are noise; this stage decides what each
should become (SDS-S-061). A never-acknowledged alert is either
deleted, or demoted from a page to a ticket or a dashboard — ask
what a responder would *do* on seeing it; if the answer is "nothing
until it happens again", it is not a page. A flapping alert needs
its `for:` duration raised or its threshold moved off the signal's
noise floor — look at the median duration and set `for:` above it.
An always-firing alert is a standing condition: fix the condition or
turn the alert into an SLO burn-rate alert with a real budget. A
co-firing pair is one alert too many: keep the one that names the
cause. A rule with no runbook gets one before its next page
(`runbook-writer`). A silent rule may be dead or may guard something
rare — the rule's `for:` and threshold say which.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[delete]`, `[demote to ticket]`, `[raise for: to
Nm]`, `[move threshold to X]`, `[replace with burn-rate alert]`,
`[keep: names the cause]`, `[write runbook]`, `[keep: rare but
real]` — with the concrete value where the data gives one.

### Synthesize

Return the finding-list, warnings first, grouped by alertname, with
a one-paragraph summary: how many alertnames, how many firings, and
how many pages the proposed changes would have saved in the window.
A quiet, well-run alert set yields a well-formed finding-list with
an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per noisy alertname per pattern, located at the history
file, with `properties` carrying the alertname, counts, medians, and
severity; `runs[0].tool.properties` carries the window and totals.
Nothing was modified and nothing was called.

## @throws

- `alerts-unparseable`: the history is not a JSON array of alerts
  with `labels.alertname` and `startsAt`.
- `rules-unparseable`: the rules file is not Prometheus rule YAML.
- `as-of-invalid`: `as-of` is missing or not a timestamp, or
  `window-days` is not an integer.

## @example

**Input:** thirty days of history where `DiskAlmostFull` fired 14
times for a median of 2 minutes and was never acknowledged.

**Output (excerpt):**

```json
{
  "ruleId": "alert/flapping",
  "level": "warning",
  "message": { "text": "[raise for: to 10m] DiskAlmostFull fired 14 times with a median duration of 2.0 minutes; the threshold sits on the signal's noise" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "alerts-30d.json" } } }],
  "properties": { "alertname": "DiskAlmostFull", "firings": 14, "medianMinutes": 2.0, "severity": "warning" }
}
```
