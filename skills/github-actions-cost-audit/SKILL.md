---
name: github-actions-cost-audit
description: >-
  Attributes a repository's GitHub Actions minutes to its workflows
  over a window and finds the usual waste — macOS and Windows runners
  billed at 10x and 2x, the same commit run on both push and
  pull_request, pull-request workflows without concurrency
  cancellation that keep running after a newer push, long median
  runs, minutes spent on failed runs and re-runs — as a finding-list
  with per-workflow minutes attached; then judges which fixes pay
  back. Use when the Actions bill or the minutes quota surprises
  someone, before adding a runner or a workflow, or when asked where
  the CI minutes go.
license: Apache-2.0
compatibility: Requires pyyaml, and the gh CLI authenticated with
  read access to the target repository's workflow runs (live mode
  only; evals run offline from a frozen recording).
metadata:
  family: dev-skills-suite
  effect-tier: external-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/audit_actions_cost.py:*) Bash(gh api -X GET:*)
  Read
---

# github-actions-cost-audit

## When to use

- The Actions bill or the included-minutes quota surprised someone.
- Before adding a macOS or Windows job, a matrix, or a scheduled
  workflow.
- Asked where the CI minutes go, or what to cut first.

## When not to use

- Whether the pipeline is correct or safe — that is
  `ci-pipeline-audit`, which reads the same workflow files for
  pinning, permissions, and secrets; this skill reads the runs for
  cost.
- Whether CI is green for a commit — `ci-status-gate`.
- Self-hosted runner infrastructure cost — those minutes are free on
  GitHub's meter; the cost is in the cloud bill, which this skill
  cannot see.

## @requires

- REQUIRED: the repository directory, with `.github/workflows/`.
- OPTIONAL: `since` — the start of the window (default: 30 days
  before `as-of`).
- OPTIONAL: `as-of` — the end of the window and the clock (default:
  now; required with a fixture).
- OPTIONAL: `long-minutes` — the median run length that counts as
  long (default: 30).
- OPTIONAL: `runs-json-file` — a recording of the runs API response
  replacing the live call (default: none, live).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the repository is a
directory and the workflow files parse. Then attribute — the
mechanical part (SDS-S-060):

```
python3 scripts/audit_actions_cost.py <repo> [--since <ISO>] [--as-of <ISO>] [--long-minutes N]
```

Live mode issues one read-only call, `gh api -X GET
repos/{owner}/{repo}/actions/runs` for the window (rung 3). Offline,
`--runs-json-file <path> --as-of <ISO>` replaces the call and the
clock (SDS-S-064, SDS-S-065). Minutes are wall-clock per run times
the runner multiplier of the workflow's most expensive `runs-on` —
an approximation of the bill, which is per job; the script says so
in `tool.properties.approximation`.

### Analyze

The attribution says where the minutes go; this stage decides which
to cut (SDS-S-061). Weighted minutes rank the fixes: a macOS
workflow at 10x usually dwarfs everything else, and the question is
whether every job on it needs macOS — a lint or a unit-test job on a
macOS runner is the first cut. `duplicate-trigger` on a workflow
whose push trigger is unfiltered is one line to fix (`branches:
[main]`); `no-concurrency-cancel` is three lines. A long median run
with no cache step is a caching problem; with one, a splitting
problem. Failed minutes concentrated in one workflow point at a
flaky suite — hand that to `flaky-test-triage` rather than buying
minutes. Say what the approximation hides: queue time, per-job
billing, and self-hosted runners.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[move <job> to ubuntu: saves ~N weighted
min/month]`, `[add branches filter to push]`, `[add concurrency
cancel-in-progress]`, `[cache <thing>]`, `[fix flakiness first]`,
`[keep: needs macOS]`.

### Synthesize

Return the finding-list, warnings first, then the per-workflow table
(runs, minutes, weighted minutes, share) and the ranked fixes with
their estimated savings. A lean repository yields a well-formed
finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per waste pattern per workflow, located at the workflow
file, with the minutes, multiplier, commit examples, or superseded
counts in `properties`; `runs[0].tool.properties` carries the
window, run count, total and weighted minutes, the per-workflow
table, and the approximation note. Nothing was modified and no
mutating call was made.

## @throws

- `repo-invalid`: the path is not a directory.
- `runs-unparseable`: the runs file (or the live response) is not
  JSON or lacks a `workflow_runs` array.
- `workflows-unparseable`: a workflow file is not valid YAML.
- `as-of-invalid`: `as-of` is missing with a fixture, or a timestamp
  or `long-minutes` does not parse.
- `gh-unreachable`: the live `gh api` call failed.

## @example

**Input:** a release workflow on `macos-14` that ran twice for 35
minutes each in a window where everything else totalled 172
minutes.

**Output (excerpt):**

```json
{
  "ruleId": "actions-cost/expensive-runner",
  "level": "warning",
  "message": { "text": "[keep: needs macOS — but move lint off it] .github/workflows/release.yml runs on macos (10x): 70 minute(s) bill as 700" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": ".github/workflows/release.yml" } } }],
  "properties": { "runner": "macos", "multiplier": 10, "minutes": 70, "weightedMinutes": 700 }
}
```
