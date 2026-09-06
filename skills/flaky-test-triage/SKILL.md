---
name: flaky-test-triage
description: >-
  Reads a history of JUnit XML test reports, finds tests that both pass
  and fail on the same commit, and produces a finding-list with the
  evidence needed to classify each as a real bug, a test bug, or an
  environment fault — the classification itself is the model's
  judgment. Use when a CI job is intermittently red, when asked which
  tests are flaky, or when a failure cannot be reproduced locally.
license: Apache-2.0
metadata:
  family: dev-skills-suite
  effect-tier: domain-read-only
  idempotent: "true"
  tier: pillar
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/analyze_test_history.py:*) Bash(git log:*)
  Bash(git rev-parse:*) Read
---

# flaky-test-triage

## When to use

- A CI job goes red intermittently on the same commit.
- Asked which tests in a suite are flaky, and why.
- A failure seen in CI cannot be reproduced locally.

## When not to use

- Fixing the flaky test — this skill classifies and gathers evidence;
  the fix is ordinary development work, and the decision to quarantine
  a test is the team's, not this skill's.
- Judging test *quality* in the abstract (over-mocking, unclear
  intent) — that is `test-smell-review` (situational).
- A test that fails every run is not flaky; this skill still reports
  it (`flaky/consistent-failure`) so it is not mistaken for one, but
  the work belongs to normal debugging.

## @requires

- REQUIRED: a directory of JUnit XML reports from two or more runs
  (JUnit XML is the interchange standard every runner and CI system
  can emit; SDS-C-031).
- OPTIONAL: `manifest` — a JSON file mapping each report to its commit
  and timestamp (default: none; all reports are then assumed to be the
  same commit, which can only over-report intermittency).
- OPTIONAL: `git-root` — the repository, so the test's source file can
  be checked for recent changes (default: none).
- OPTIONAL: `recent-days` — window for "changed recently" (default: 14).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the reports path is a
directory. Then run the analysis — the mechanical part (SDS-S-060):

```
python3 scripts/analyze_test_history.py <reports-dir> [--manifest <runs.json>] [--git-root <repo>] [--recent-days N]
```

It reads the reports and, with `--git-root`, `git log` for the test
file (rung 2, domain-read-only; no network) and prints a
`finding-list` with `flaky/intermittent` (warning) and
`flaky/consistent-failure` (error) results. Each carries `properties`:
runs, failures, passRate, the distinct failure messages, and `hints`
— mechanical observations such as a timing-like message or a recently
changed test file. A nonzero exit maps to `@throws`.

### Analyze

Classification is the judgment the script does not make (SDS-S-061).
For each `flaky/intermittent` finding decide, from the evidence, one
of three causes and say which evidence carries it:

- **environment** — failure messages are timing/connection-shaped, or
  differ from run to run, and the test's own code has not changed:
  the test is at the mercy of something outside it (a port, a
  service, a clock).
- **test bug** — the test file changed recently, or the failure is a
  fixed assertion that only sometimes trips (order-dependence, shared
  state, an unseeded random): the test is wrong, not the code.
- **real bug** — the same failure recurs with a stable message and
  the code under test (not the test) changed, or the passRate is
  falling across commits: the intermittency is the bug's, not the
  test's.

If the evidence supports two of these equally, say so rather than
picking; a wrong confident classification costs more than an honest
"needs a repro."

### Classify

Record the classification and its carrying evidence in each finding's
`message.text` (prefix: `[environment]`, `[test bug]`, `[real bug]`,
or `[undetermined]`). Leave `level` as produced unless a `[real bug]`
classification is on a release-critical path, in which case promote
it to `error` and say why.

### Synthesize

Return the finding-list, `error` first. Zero intermittent tests is a
complete, schema-valid finding-list with an empty `results` array
(SDS-C-033) — "nothing is flaky" is a finding worth stating.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per test that failed in two or more runs of one commit,
with `ruleId` `flaky/intermittent` or `flaky/consistent-failure`, a
classification in `message.text`, and `properties` holding the
run/failure counts, pass rate, distinct failure messages, and hints.
Nothing in the repository or the reports has changed.

## @throws

- `reports-missing`: the reports path is not a directory.
- `report-unparseable`: a report is not well-formed JUnit XML.
- `manifest-unparseable`: the runs manifest is unreadable or lacks the
  `runs` list.

## @example

**Input:** four reports of one commit in which
`tests.test_checkout::test_checkout_completes` passed twice and failed
twice with a timeout and then a connection refusal; the test file is
untouched.

**Output (excerpt, after Analyze/Classify):**

```json
{
  "ruleId": "flaky/intermittent",
  "level": "warning",
  "message": { "text": "[environment] tests.test_checkout::test_checkout_completes passed and failed on commit abc1234: 2/4 runs failed; hints: timing-like failure message, distinct failure messages — two different network errors against an unchanged test point at the payment-gateway stub, not the test" },
  "properties": { "passRate": 0.5, "failureMessages": ["ConnectionError: ECONNREFUSED 127.0.0.1:8402", "TimeoutError: payment gateway did not respond within 30s"], "hints": ["timing-like failure message", "distinct failure messages"] }
}
```
