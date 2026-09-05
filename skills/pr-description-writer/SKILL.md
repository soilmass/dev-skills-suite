---
name: pr-description-writer
description: >-
  Drafts a pull request description (summary, risk, test plan) from a
  branch's diff and commit history, and applies it to the open PR once
  confirmed. Use when opening or refreshing a PR description, when a
  diff has drifted from its original description, or when the user
  asks to write, update, or clean up a PR description.
license: Apache-2.0
compatibility: Requires git and the gh CLI, authenticated against the
  target repository.
metadata:
  family: dev-skills-suite
  effect-tier: shared-write
  idempotent: "true"
  tier: pillar
  shape-out: freeform
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/gather_pr_context.py:*) Bash(git diff:*)
  Bash(git log:*) Bash(git rev-parse:*) Bash(gh pr view:*) Read Write
---
<!-- Write is scoped to .skills-state/pr-description-writer/ and the
     drafted body file only (SDS-S-024); the mutation itself is
     `gh pr edit`, deliberately absent from allowed-tools (SDS-S-023). -->


# pr-description-writer

## When to use

- Opening a PR and it needs a description written from the diff.
- An existing PR's description is stale relative to its current diff.
- The user directly asks for a PR description to be written or refreshed.

## When not to use

- Opening the PR itself, requesting reviewers, or merging — that's
  `pr-lifecycle-manager`'s job. This skill only ever produces and
  applies description *text*; it never creates, closes, or merges a PR.
- Writing release notes or a changelog entry — those summarize what
  shipped across many PRs for an external audience; this summarizes
  one branch's changes for a reviewer.

## @requires

- REQUIRED: the current directory is a git repository, on a branch
  with at least one commit ahead of a stated base branch.
- REQUIRED: `base` — the branch to diff against (e.g. `main`).
- OPTIONAL: a PR already exists for the current branch (default:
  none — see the no-PR-yet path in Decide below).

## Instructions

### Gather

Run:

```
python3 scripts/gather_pr_context.py <repo-path> --base <base>
```

This is read-only: it inspects `git diff`/`git log` (domain-read-only)
and, if reachable, an existing PR's current body via `gh pr view`
(external-read-only — the highest read rung this stage reaches). A
nonzero exit means the repo path or base ref is invalid — surface the
script's stderr verbatim under `@throws`. A PR not existing yet is
NOT a failure: `currentBody` is simply `null`, and that's the normal
"drafting a brand-new description" case.

### Analyze

Read the gathered file list and commit subjects. Identify: what
changed (by area, not just filename), whether the change is additive,
a fix, a refactor, or a mix, and anything that looks like it carries
risk (a changed public interface, a dependency bump, a migration).
This is judgment — do not mechanically concatenate commit subjects
into the description; synthesize what a reviewer actually needs to
know.

### Decide

Draft the new description: a short summary, a risk/impact note where
relevant, and a test plan (what was verified, or what a reviewer
should verify). This is the artifact this skill exists to produce.

**If `currentBody` is null: stop here.** No PR exists yet — return the
drafted text as this invocation's output (see `@returns`). There is
nothing to Confirm or Act on, since nothing outside this artifact
would be mutated (conditional Act path, SDS-S-041). Do not attempt to
create a PR; that's out of scope (see When not to use).

If `currentBody` is non-null (an existing PR will be updated):
continue to Confirm.

### Confirm

Only reached when `currentBody` is non-null. Use the base text from
`kit/shared/gates/medium.md` (rung 5, shared-write; SDS-S-050).
Show the user the current body and the proposed new body side by side
— not just the new text alone; the reviewer-facing change is a diff of
descriptions, not just a new artifact appearing from nowhere.

### Act

Only reached when `currentBody` is non-null, and only after explicit
confirmation.

First, write the `pending` checkpoint — a plain local file write via
the Write tool, not a bundled script (single mutating step; SDS-S-055)
— to `.skills-state/pr-description-writer/<pr-number>.json`,
**before** the edit:

```json
{
  "key": "<pr-number>",
  "step": "edit-body",
  "status": "pending",
  "startedAt": "<ISO-8601>",
  "preState": { "previousBody": "<verbatim currentBody>" },
  "compensatingAction": "gh pr edit <pr-number> --body-file <previousBody>"
}
```

Before mutating, check whether the PR's body already equals the
proposed text (re-fetch via `gh pr view`) — if so, this is a no-op;
skip the edit rather than re-applying an identical body
(check-before-act, SDS-C-046). A resumed invocation that finds this
file with `status: pending` treats the edit as possibly-applied and
performs the same check before retrying; `status: completed` means
skip it entirely.

Then run, directly, as an unwrapped tool call — **do not** wrap this
in a script referenced by `allowed-tools`; doing so would silently
pre-approve the very mutation this Confirm gate exists to guard
(SDS-S-051):

```
gh pr edit <pr-number> --body-file <path-to-new-body>
```

Immediately after it succeeds, update the same file: set `status` to
`completed` and add `"postState": { "appliedBody": "<new body>" }`.

**Compensating action** (SDS-S-054) if the result turns out wrong
after the fact — there is only this one mutating step, so this is also
the recovery path: re-run
`gh pr edit <pr-number> --body-file <path-to-checkpoint's previousBody>`.

**Checkpoint** (SDS-S-053): the two-phase record above — `pending`
written before the edit, `completed` after — at
`.skills-state/pr-description-writer/<pr-number>.json`; a resumed
session reads it to recover the pre-edit body without re-deriving it.

### Communicate

N/A — the applied PR body is the communication; no separate
notification is sent.

### Persist

The checkpoint file from Act is the durable record. No separate
status-report artifact is produced beyond the applied PR body itself.

## @returns

Shape: `freeform` (drafted or applied PR description text).

On the no-PR-yet path: the drafted text, ready to be used when the PR
is opened (by the user or by `pr-lifecycle-manager`).
On the update-existing-PR path, after confirmation: the PR's body now
equals the drafted text, and `.skills-state/pr-description-writer/<pr-number>.json`
holds the previous body for reversion.

## @throws

- `repo-invalid`: the given path is not a git repository.
- `base-ref-missing`: the stated base branch does not exist.
- `edit-declined`: the user did not confirm the update — no mutation
  occurred; the drafted text is still returned as `freeform` output.

## @example

**Input:** a branch `feature/add-retry-logic` two commits ahead of
`main` (a retry helper added, then documented), no PR open yet.

**Output:**

> **Summary:** Adds a `with_retry()` helper with exponential backoff
> and documents it in the README.
> **Risk:** Low — new utility function, no existing call sites changed.
> **Test plan:** Exercise `with_retry()` against a function that fails
> N times then succeeds; confirm it raises only after the final attempt.

No Confirm/Act occurred (no PR existed yet) — this text is returned
directly, per the Decide-stage branch above.
