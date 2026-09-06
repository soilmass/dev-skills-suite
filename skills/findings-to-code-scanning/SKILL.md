---
name: findings-to-code-scanning
description: >-
  Uploads a family finding-list to GitHub Code Scanning as SARIF —
  merging every input into one analysis scoped to a commit and ref —
  after a medium-risk confirmation, with the single upload step
  checkpointed and, once accepted, not reversible through this
  skill. Use after an audit, when findings should surface as code
  scanning alerts, or when asked to upload findings to code
  scanning.
license: Apache-2.0
compatibility: Requires the gh CLI authenticated against the target
  repository with security_events write permission — live mode only.
metadata:
  family: dev-skills-suite
  effect-tier: shared-write
  idempotent: "true"
  tier: situational
  shape-out: status-report
  shape-in: finding-list
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/prepare_sarif.py:*)
  Bash(python3 scripts/checkpoint.py:*) Bash(gh api -X GET:*) Read Write
---
<!-- Write is scoped to .skills-state/findings-to-code-scanning/ only
     (SDS-S-024). The mutation — gh api -X POST
     repos/<owner>/<repo>/code-scanning/sarifs — is deliberately
     absent from allowed-tools (SDS-S-023) and is issued as a direct,
     unwrapped tool call after the gate (SDS-S-051). There is no
     compensating action: an uploaded analysis cannot be deleted
     through this skill, so this is always the last mutating step of
     a run. -->

# findings-to-code-scanning

## When to use

- An audit skill just produced findings and they should surface as
  code scanning alerts, not just a report.
- Asked to upload findings to code scanning, or to publish an
  analysis for a repository's Security tab.
- CI produced the family's own lint output as SARIF and it needs to
  reach GitHub once, by hand or from a pipeline step.

## When not to use

- Digesting or ranking findings across several audits — that is
  `findings-digest`, and it runs first.
- Turning findings into tracked work items — that is
  `findings-to-issues`; run it separately, since neither substitutes
  for the other's surface.
- A repository without `gh` authenticated with `security_events`
  write permission — the upload fails at Act.
- Deleting or superseding a prior analysis — no skill in this family
  does that; an analysis ages out on GitHub's own schedule.

## @requires

- REQUIRED: the repository directory, with `gh` authenticated.
- REQUIRED: one or more `finding-list` files, as any family audit
  skill emits.
- OPTIONAL: `--sha` — the 40-character commit hash the analysis is
  scoped to (default: `git rev-parse HEAD` in the repository).
- OPTIONAL: `--ref` — the ref the analysis is scoped to, e.g.
  `refs/heads/main` (default: `git symbolic-ref HEAD` in the
  repository).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then merge and validate the findings, the mechanical part
(SDS-S-060):

```
python3 scripts/prepare_sarif.py <repo> <finding-list.json>... [--sha <40hex>] [--ref refs/heads/main]
```

Each input is checked against `kit/shapes/finding-list.schema.json`
and every run is merged into one analysis, with the same SARIF-2.1.0
variant `kit/scripts/lint-skill.py`'s `--sarif` branch emits: a
top-level `$schema`, `version: "2.1.0"`, and each result's severity
narrowed from the family's `error`/`warning`/`info`/`hint` to
SARIF's `none`/`note`/`warning`/`error` (`info` and `hint` fold to
`note`). The result is gzip-compressed and base64-encoded and printed
with the commit, ref, and a result count. If a resumed run's
checkpoint (`checkpoint.py findings-to-code-scanning <sha7> --show`)
exists, read it first.

### Analyze

The merge is mechanical; this stage reads the merged analysis with
domain knowledge before deciding to proceed (SDS-S-061). A result
count far outside what the source audits normally report is worth
naming before Confirm rather than discovering after upload. A `--ref`
that does not match the branch someone actually asked about is a sign
the wrong commit was scoped, not a reason to proceed and hope.

### Decide

The plan has exactly one step: upload the merged analysis for
`<commit_sha>` at `<ref>` to code scanning.

**If a `completed` checkpoint record already exists for this
commit_sha + ref + tool_name: stop here** — report that GitHub
already has this analysis and nothing new needs to be sent; this is
the idempotency rule (SDS-C-004), since GitHub has no read endpoint
for an analysis before it is uploaded, so the checkpoint record is
the only check available.

### Confirm

Only reached when no completed checkpoint record exists yet for this
commit_sha + ref + tool_name. Use the medium-risk gate
(`kit/shared/gates/medium.md`):

> I'm about to upload a SARIF analysis with `<results>` result(s) to
> GitHub Code Scanning for `<owner/repo>` at commit `<commit_sha>` on
> `<ref>`. This is visible to every subscriber of the repository's
> Security tab.
> - **What:** upload the merged analysis produced by
>   `prepare_sarif.py` for the given findings.
> - **Why:** the finding-list inputs named at Gather.
> - **Reversible?:** not reversible: an analysis cannot be deleted by
>   this skill; it ages out.
>
> Proceed?

A declined gate ends the run with `upload-declined` and nothing
uploaded.

### Act

Only reached when the Confirm gate is accepted. Write the `pending`
checkpoint (`checkpoint.py findings-to-code-scanning <sha7> --step
upload-<sha7> --status pending --compensating-action "none — this
step must be last"`). Write the upload payload — the
`prepare_sarif.py` output with `results` stripped — to
`.skills-state/findings-to-code-scanning/<sha7>-payload.json` (Write
tool). Issue the mutation as a direct tool call, never through a
bundled script: `gh api -X POST
repos/<owner>/<repo>/code-scanning/sarifs --input
.skills-state/findings-to-code-scanning/<sha7>-payload.json`.
Check-before-act is the checkpoint record read in Decide, since
GitHub offers no way to check an analysis's presence before it
exists (SDS-C-046). After success, confirm the upload landed with
`gh api -X GET repos/<owner>/<repo>/code-scanning/sarifs/<id>` (the
`id` the POST response returned), save that response to a file, and
mark the step `completed` with `checkpoint.py findings-to-code-scanning
<sha7> --step upload-<sha7> --status completed --post-state-file
<path>` so the response is recorded as `postState`.

**Compensating action** (SDS-S-054): no compensating action — this
step must be last; an uploaded analysis cannot be deleted through
this skill.

**Checkpoint** (SDS-S-053): the two-phase record at
`.skills-state/findings-to-code-scanning/<sha7>.json`, one step for
the upload.

### Communicate

N/A — the alerts appear in the repository's Security tab.

### Persist

Return the status-report: the commit and ref the analysis was
scoped to, the result count uploaded, the checkpoint path, and the
`sarif_id` from the post-upload check — or, on the stop-early path,
that a completed analysis already existed for this commit_sha, ref,
and tool_name, and nothing was uploaded.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

Once this skill succeeds, GitHub Code Scanning has one analysis for
the given commit and ref, and `.skills-state/findings-to-code-scanning/`
holds a `completed` checkpoint record for it. On the stop-early path
the report says a completed analysis already existed for this
commit_sha, ref, and tool_name, and nothing new was uploaded.

## @throws

- `repo-invalid`: the path is not a directory.
- `findings-invalid`: an input is not a `finding-list` (fails
  validation against `kit/shapes/finding-list.schema.json`).
- `sha-invalid`: `--sha` is not 40 hexadecimal characters.
- `ref-invalid`: `--ref` does not start with `refs/`.
- `upload-declined`: the confirmation gate was declined; nothing was
  uploaded.
- `gh-unreachable`: the live `gh api` call — the upload or the
  post-success check — failed to reach GitHub.

For a failure after the `pending` checkpoint was written but before
`gh api -X POST` completes, resume by re-reading the checkpoint: a
`pending` step with no confirmed analysis on GitHub means the upload
never landed and may be retried; there is no compensating action to
run.

## @example

**Input:** `dependency-audit`, `ci-pipeline-audit`, and
`retry-timeout-audit`'s finding-lists — 20 results total, three
errors, ten warnings, seven infos — at commit
`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` on `refs/heads/main`.

**Confirmed action:** the Confirm gate above, showing 20 results
for that commit and ref.

**Result:** `gh api -X POST
repos/soilmass/dev-skills-suite/code-scanning/sarifs --input
.skills-state/findings-to-code-scanning/aaaaaaa-payload.json`
succeeds; the checkpoint at
`.skills-state/findings-to-code-scanning/aaaaaaa.json` records the
`upload-aaaaaaa` step as `completed` with the response's `sarif_id`
in `postState`; the status-report names the commit, ref, and result
count uploaded.
