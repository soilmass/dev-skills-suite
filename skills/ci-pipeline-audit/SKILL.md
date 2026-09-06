---
name: ci-pipeline-audit
description: >-
  Audits GitHub Actions workflow files for the mistakes that cost the
  most in practice — actions pinned to a branch or a movable tag,
  write permissions granted to every job, pull_request_target checking
  out untrusted code, secrets printed into logs, jobs without a
  timeout, workflows without a concurrency group — as a finding-list,
  leaving the call on which one matters in this repository to a
  human. Use when inheriting a pipeline, before granting a workflow
  new permissions, or when asked whether CI is safe and sane.
license: Apache-2.0
compatibility: Requires Python 3.10+ with PyYAML.
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/audit_workflows.py:*) Read
---

# ci-pipeline-audit

## When to use

- Inheriting a pipeline nobody currently understands.
- Before granting a workflow new permissions or secrets.
- Asked whether CI is safe, why runs pile up, or why a job took six
  hours.

## When not to use

- A run that is failing right now — read its log; this skill reads
  the workflow definitions, not run history.
- Tests that pass and fail on the same commit — that is
  `flaky-test-triage`.
- Deciding whether a pull request may merge — that is
  `pr-lifecycle-manager`, which reads check status; this skill has no
  network and never queries the API.
- Pipelines outside GitHub Actions, for now.

## @requires

- REQUIRED: a repository directory; workflows are read from
  `.github/workflows/`.

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a directory.
Then scan — the mechanical part (SDS-S-060):

```
python3 scripts/audit_workflows.py <repo>
```

It parses every workflow file with PyYAML (rung 1; files only, no
API) and reports `ci/unpinned-action` (branch pin: warning; tag pin:
info), `ci/broad-permissions` (`write-all`, or workflow-wide
`contents: write`), `ci/pull-request-target-checkout` (the
untrusted-head hole), `ci/secret-in-run-echo`, `ci/no-timeout`, and
`ci/no-concurrency`. A repository with no `.github/workflows/`
yields an empty list; a workflow that is not valid YAML stops the
scan (`workflow-malformed`).

### Analyze

The scan finds patterns; this stage decides which are risks here
(SDS-S-061). A branch pin on an action this organisation owns is a
choice; on a third-party action it is a supply-chain exposure — the
2025 tj-actions incident was exactly a moved tag. Workflow-wide
`contents: write` is wrong when only the release job pushes; move it
to that job. `pull_request_target` with the head checked out is
almost always a hole, unless the checked-out code is never executed
(labelling from file paths is fine; running its tests is not).
Echoing a secret is a leak even though GitHub masks known values —
transformed values are not masked. A missing timeout on a
two-minute job is cheap to fix and cheaper still to ignore; rank it
last.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[pin to SHA]`, `[keep: first-party action]`,
`[scope to job <name>]`, `[split trigger: pull_request for tests]`,
`[remove echo]`, `[add timeout-minutes: N]`, `[add concurrency
group]` — with the concrete value where one exists (the current SHA
of the tag, the job that needs the permission).

### Synthesize

Return the finding-list, warnings first, grouped by workflow, with
the security findings before the hygiene ones. A repository whose
workflows draw nothing yields a well-formed finding-list with an
empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per pattern, located at the workflow line where it
appears, with `properties` carrying the job, action, ref, pin kind,
or permissions involved. Nothing was run, nothing was modified, and
no network call was made.

## @throws

- `repo-invalid`: the path is not a directory.
- `workflow-malformed`: a workflow file is not valid YAML or is not a
  mapping.

## @example

**Input:** a CI workflow whose checkout step reads
`uses: actions/checkout@main`.

**Output (excerpt):**

```json
{
  "ruleId": "ci/unpinned-action",
  "level": "warning",
  "message": { "text": "[pin to SHA] actions/checkout is pinned to branch 'main'; every run picks up whatever is there now" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": ".github/workflows/ci.yml" }, "region": { "startLine": 14 } } }],
  "properties": { "job": "test", "action": "actions/checkout", "ref": "main", "pin": "branch" }
}
```
