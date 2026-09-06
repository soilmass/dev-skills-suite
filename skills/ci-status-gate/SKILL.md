---
name: ci-status-gate
description: >-
  Answers one question about a commit — do its CI checks pass the
  gate? — by reading GitHub's check runs for the ref, applying a
  fixed rule table (a required check missing, failed, or stuck beyond
  a staleness limit fails; one still running waits; all green passes)
  and returning a decision-doc that says which check decided it and
  why. Use before merging, deploying, or tagging, when a pipeline
  looks green but something is missing, or when asked "is CI green?"
license: Apache-2.0
compatibility: Requires the gh CLI authenticated with read access to
  the target repository's check runs (live mode only; evals run
  offline from fixtures).
metadata:
  family: dev-skills-suite
  effect-tier: external-read-only
  idempotent: "true"
  tier: situational
  shape-out: decision-doc
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/evaluate_checks.py:*) Bash(git rev-parse:*)
  Bash(gh api -X GET:*) Read
---

# ci-status-gate

## When to use

- Before merging, deploying, or tagging a commit.
- A pipeline looks green but a check seems to be missing, or one has
  been "in progress" for an hour.
- Asked whether CI is green for a branch, commit, or pull request.

## When not to use

- Merging the pull request — that is `pr-lifecycle-manager`, which
  can consume this decision; this skill decides and stops.
- Why a check failed — read its log; this skill reports *which*
  check blocks and links to it.
- Auditing the workflow definitions — that is `ci-pipeline-audit`,
  which reads the YAML and never the run state.

## @requires

- REQUIRED: the repository directory.
- OPTIONAL: `ref` — the commit, branch, or tag to evaluate (default:
  `HEAD`).
- OPTIONAL: `required` — the check names that gate; without it every
  check that reported is treated as required (default: all reported
  checks).
- OPTIONAL: `stale-minutes` — how long a check may stay queued or in
  progress before the gate treats it as failed (default: 60).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the repository is a
directory and `git rev-parse <ref>` resolves. Then read the check
runs — the mechanical part (SDS-S-060):

```
python3 scripts/evaluate_checks.py <repo> [--ref <ref>] [--required a,b] [--stale-minutes N]
```

Live mode issues one read-only call, `gh api -X GET
repos/{owner}/{repo}/commits/<ref>/check-runs` (rung 3). Offline,
`--checks-json-file <path> --as-of <ISO>` replaces the call and the
clock (SDS-S-064, SDS-S-065). Reruns of the same check name keep the
latest run.

### Analyze

The rule table is in the script; this stage reads the decision-doc
and adds what the table cannot know (SDS-S-061). A `fail` on a
missing required check is often a renamed job — compare the required
name against the names that did report and say so. A `fail` on
staleness is usually a runner shortage or a hung step; the fix is a
cancel-and-rerun, not a longer limit. A `wait` with a check that has
been running twice as long as its usual duration deserves a note
even before it goes stale. A `pass` with a failing non-required check
(listed under `consequences.negative`) should say who owns that
check.

### Synthesize

Return the decision-doc, leading with `chosenOption` and the check
that decided it, then the driver list (one line per required check),
then the notes from Analyze. Say when the evaluation was made and
that it must be re-run before acting; check runs can be re-triggered.

## @returns

Shape: `decision-doc` — see `kit/shapes/decision-doc.schema.json`.

`chosenOption` is `pass`, `wait`, or `fail`; `justification` names
the deciding check; `decisionDrivers` lists every required check
with its state; `consequences.negative` lists failing non-required
checks. Nothing was modified and no mutating call was made.

## @throws

- `repo-invalid`: the path is not a directory.
- `checks-unparseable`: the checks file (or the live response) is
  not JSON or lacks a `check_runs` array.
- `as-of-invalid`: `--as-of` is missing with a fixture, or a
  timestamp or `stale-minutes` does not parse.
- `gh-unreachable`: the live `gh api` call failed.

## @example

**Input:** ref `abc123` with `build` succeeded, `test` failed, and
`lint` in progress; required `build,test,lint`.

**Output (excerpt):**

```json
{
  "status": "accepted",
  "decisionOutcome": { "chosenOption": "fail", "justification": "required check 'test' concluded failure" },
  "decisionDrivers": ["build: success", "test: failure — https://github.com/o/r/actions/runs/7/job/2"],
  "consideredOptions": ["pass", "wait", "fail"]
}
```
