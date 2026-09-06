---
name: pr-lifecycle-manager
description: >-
  Orchestrates a pull request end to end: opens it from the current
  branch if none exists, requests reviewers, verifies CI and review
  state, and merges only after an explicit high-risk confirmation. Use
  when finishing a feature branch, when asked to open, ship, land, or
  merge a PR, or when a PR is green and waiting to be merged.
license: Apache-2.0
compatibility: Requires git and the gh CLI, authenticated against the
  target repository with permission to open, review-request, and merge
  pull requests.
metadata:
  family: dev-skills-suite
  effect-tier: irreversible
  idempotent: "true"
  tier: pillar
  shape-out: status-report
  shape-in: decision-doc
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/assess_pr_readiness.py:*)
  Bash(python3 scripts/checkpoint.py:*) Bash(git status:*)
  Bash(git rev-parse:*) Bash(git log:*) Bash(gh pr view:*)
  Bash(gh pr checks:*) Bash(gh repo view:*) Read Write
---
<!-- Write is scoped to .skills-state/pr-lifecycle-manager/ and the
     drafted PR body file only (SDS-S-024). Every mutation — gh pr
     create, gh pr edit --add-reviewer, gh pr merge — is deliberately
     absent from allowed-tools (SDS-S-023) and is issued as a direct,
     unwrapped tool call after its gate (SDS-S-051). -->

# pr-lifecycle-manager

## When to use

- A feature branch is finished and should become a merged pull request.
- The user asks to open, ship, land, or merge a PR.
- A PR is reported green and approved and is waiting to be merged.

## When not to use

- Writing or refreshing the PR *description text* — that is
  `pr-description-writer`'s job; this skill delegates to it on the
  no-PR path and never drafts prose itself.
- Deciding whether a branch should be rebased or merged against its
  base before the PR — that is `sync-strategy-advisor` (situational,
  not yet built); this skill assumes the branch is already pushed and
  up to date.
- Reviewing the code. This skill checks review *state*, never review
  *content*.

## @requires

- REQUIRED: the current directory is the root of a git repository with
  a GitHub remote, on a pushed branch other than the base branch.
- OPTIONAL: `pr` — the pull request number (default: the PR for the
  current branch, or none).
- OPTIONAL: `description` — PR body text, typically
  `pr-description-writer`'s drafted output (default: delegate to
  `pr-description-writer` on the no-PR path).
- OPTIONAL: `reviewers` — GitHub logins to request (default: none
  requested automatically; the user is asked at Confirm).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): `git rev-parse
--show-toplevel` must equal the current directory, and `git status`
must show a pushed branch. Then run the readiness assessment:

```
python3 scripts/assess_pr_readiness.py . [--pr <number>]
```

It reads `gh pr view` and `gh repo view` (external-read-only) and
emits a `decision-doc` (`kit/shapes/decision-doc.schema.json`) — the
`shape-in` this skill consumes. A nonzero exit maps to `@throws`
(`repo-invalid`, `pr-state-unparseable`, `gh-unreachable`); surface
its stderr verbatim. "No pull request exists" is not a failure: the
decision-doc's `chosenOption` is `open-pr`.

If `chosenOption` is `open-pr` and no `description` input was given,
delegate to `pr-description-writer` for the drafted body text
(Delegate stage; SDS-C-060). Do not write the description here.

### Analyze

N/A — per SDS-C-060 (functional core, imperative shell) this
orchestrator performs no analysis of its own. Readiness is the fixed
rule table in `scripts/assess_pr_readiness.py`; description drafting
is delegated to `pr-description-writer`.

### Decide

The decision *is* the delegated `decision-doc` from Gather. Read
`decisionOutcome.chosenOption` and `facts` (`prNumber`,
`mergeStrategy`, `deleteBranchOnMerge`). Do not re-derive or override
it here.

**If `chosenOption` is not `open-pr` and not `merge`: stop here.** The
assessment says the PR is waiting on something outside this skill's
authority — checks still running, a failing check, changes requested,
no approving review, a draft, a conflict, or a PR that is already
merged or closed. Return a `status-report` naming that state and the
decision-doc's justification (conditional Act path, SDS-S-041).
Nothing is mutated on this path.

If `chosenOption` is `open-pr` or `merge`: continue to Confirm.

### Confirm

Only reached when `chosenOption` is `open-pr` or `merge`.

Present the whole sequence that will run, then gate each mutating
step individually when it is reached (a gate is middleware, SDS-C-044;
it runs every time, never carried over from an earlier step or
session):

- Steps 1 and 2 (open the PR; request reviewers) are rung 5,
  shared-write: use the base text from `kit/shared/gates/medium.md`.
- Step 4 (merge) is rung 6, irreversible: use the base text from
  `kit/shared/gates/high.md` (SDS-S-050), filled with the exact merge
  command, the strategy from `facts.mergeStrategy`, and the explicit
  statement that there is no compensating action for a merge.

Ask for reviewers here if `reviewers` was not supplied.

### Act

Only reached when `chosenOption` is `open-pr` or `merge`, and only for
the steps the user confirmed. This is a multi-step sequence, so the
checkpoint record is kept by `scripts/checkpoint.py` (SDS-S-055),
keyed by the PR number (or the branch name until a PR exists), at
`.skills-state/pr-lifecycle-manager/<key>.json`. Before every step,
`checkpoint.py <skill> <key> --show`: a `completed` step is skipped; a
`pending` step is treated as possibly-applied and re-checked before
retrying (SDS-C-046).

**Step 1 — open the PR** (only when `chosenOption` is `open-pr`).
Check-before-act: `gh pr view` must still report no PR for the branch.
Write the pending record, then issue the mutation directly (never via
a script referenced by `allowed-tools`, SDS-S-051):

```
python3 scripts/checkpoint.py pr-lifecycle-manager <branch> --step open-pr --status pending \
  --compensating-action "gh pr close <number> --delete-branch=false"
gh pr create --base <base> --title "<title>" --body-file <drafted-body>
python3 scripts/checkpoint.py pr-lifecycle-manager <branch> --step open-pr --status completed \
  --post-state-file <json with the new PR number and url>
```

**Compensating action** (SDS-S-054): `gh pr close <number>` — closing
is reversible (the PR can be reopened), so opening is safe to undo.

**Step 2 — request reviewers** (when `reviewers` is non-empty).
Check-before-act: skip any login already in `reviewRequests`. Pending
record, then `gh pr edit <number> --add-reviewer <logins>`, then
completed.

**Compensating action**: `gh pr edit <number> --remove-reviewer <logins>`.

**Step 3 — verify readiness again.** Re-run
`scripts/assess_pr_readiness.py . --pr <number>`. Continue to Step 4
only if `chosenOption` is still `merge`; otherwise stop and report
(the decision-doc's `confirmation` field requires exactly this).

**Step 4 — merge** (only when the re-assessment says `merge`, and only
after the high-risk gate from Confirm has been shown and answered
*again* at this point). Check-before-act: `gh pr view --json state`
must be `OPEN`. Pending record, then the direct call:

```
python3 scripts/checkpoint.py pr-lifecycle-manager <number> --step merge --status pending \
  --compensating-action "none — this step must be last"
gh pr merge <number> --<facts.mergeStrategy>
python3 scripts/checkpoint.py pr-lifecycle-manager <number> --step merge --status completed
```

**Compensating action**: none — a merge is irreversible (rung 6), so
it is sequenced last and nothing runs after it.

**Checkpoint** (SDS-S-053): the two-phase record above — each step
written `pending` before its mutating call and updated to `completed`
immediately after — at `.skills-state/pr-lifecycle-manager/<key>.json`;
a resumed session reads it with `--show` to skip completed steps and
re-check pending ones instead of re-deciding from zero.

### Communicate

N/A — GitHub itself notifies requested reviewers and watchers of the
open and merge events; this skill sends no separate message.

### Persist

Return the `status-report` (below). The checkpoint record is the
durable trace of what actually ran; no other file is written into the
repository.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

On the Act-less path (any `chosenOption` other than `open-pr`/`merge`):
a `status-report` whose `summary` names the blocking state and whose
single section carries the decision-doc's justification; nothing was
mutated. On the Act path: one section per step (`open-pr`,
`request-reviewers`, `verify-readiness`, `merge`) stating whether it
ran, was skipped by check-before-act, or was declined, with
`generatedFrom` naming the PR and the checkpoint file.

## @throws

- `repo-invalid`: the current directory is not the root of a git
  repository.
- `pr-state-unparseable`: GitHub's response (or the injected PR state
  file) could not be parsed.
- `gh-unreachable`: `gh` failed for a reason other than "no pull
  request exists".
- `merge-declined`: the user did not confirm a gated step — the
  sequence stops there; the status-report records which steps ran.
- `step-failed-compensated`: a mutating step failed after an earlier
  step succeeded; the earlier step's compensating action was offered
  and the status-report names it.

## @example

**Input:** branch `feature/add-retry-logic`, PR #42 open, two checks
`SUCCESS`, `reviewDecision` `APPROVED`, repository allows squash.

**Confirmed action:** the high-risk gate for
`gh pr merge 42 --squash`, answered yes.

**Result:** a `status-report` as in
`evals/fixtures/example-status-report.json` — `open-pr` and
`request-reviewers` skipped by check-before-act, `verify-readiness`
unchanged at `merge`, `merge` ran, checkpoint step `merge`
`pending -> completed`.
