---
name: issue-triage
description: >-
  Triages a repository's untriaged open issues: reads them, proposes a
  kind label, a priority for bugs, a request for reproduction steps
  where a bug has none, and a nudge on stale issues — as a plan-doc a
  human revises — then applies each label and comment only after a
  medium-risk confirmation, one issue at a time, with every label
  reversible and every step checkpointed. Use when the untriaged
  count has grown, on a triage rota, or when asked to label, sort, or
  clean up the issue tracker.
license: Apache-2.0
compatibility: Requires the gh CLI authenticated against the target
  repository with permission to read issues and, for Act, to edit
  labels and comment.
metadata:
  family: dev-skills-suite
  effect-tier: shared-write
  idempotent: "true"
  tier: situational
  shape-out: status-report
  shape-in: plan-doc
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/propose_triage.py:*)
  Bash(python3 scripts/checkpoint.py:*) Bash(gh issue list:*)
  Bash(gh issue view:*) Read Write
---
<!-- Write is scoped to .skills-state/issue-triage/ and the revised
     plan-doc only (SDS-S-024). The mutations — gh issue edit
     --add-label and gh issue comment — are deliberately absent from
     allowed-tools (SDS-S-023) and are issued as direct, unwrapped tool
     calls after the gate (SDS-S-051). Closing issues is out of scope:
     gh issue close is rung 6 and belongs to a human. -->

# issue-triage

## When to use

- The untriaged issue count has grown past what a glance covers.
- A triage rota shift, or the weekly issue review.
- Asked to label, sort, or tidy the issue tracker.

## When not to use

- Closing issues — never; the plan proposes a stale nudge, and a
  human closes after the reply window.
- Project board placement — that is `project-board-sync`.
- Pull requests — that is `pr-lifecycle-manager`.
- A repository without the label taxonomy in `assets/taxonomy.json`
  — create the labels first (`gh label create`), or the edits fail.

## @requires

- REQUIRED: the repository directory, with `gh` authenticated.
- OPTIONAL: `limit` — how many open issues to read (default: 100).
- OPTIONAL: `stale-days` — days without activity before a stale
  nudge is proposed (default: 90).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then read the open issues and produce the proposal — the
mechanical part (SDS-S-060):

```
python3 scripts/propose_triage.py <repo> [--limit N] [--stale-days N]
```

Live mode issues one read (`gh issue list --json …`, rung 3);
offline, `--issues-json-file <path> --as-of <ISO>` replaces the call
and the clock (SDS-S-064, SDS-S-065). Issues already carrying a
`kind/*` label or `triaged` are skipped. If a resumed run's
checkpoint (`checkpoint.py issue-triage <date> --show`) exists, read
it first: `completed` steps are skipped, `pending` ones are
check-before-act'ed by viewing the issue's current labels.

### Analyze

The rule table guesses from keywords; this stage reads each issue
and corrects it (SDS-S-061). "Fails to mention X in the docs" is
`kind/docs`, not `kind/bug`. A feature request phrased as a question
is a feature. A bug from a maintainer rarely needs the reproduction
comment. A stale issue with a recent linked pull request is not
stale. Drop, change, or add steps; every changed step keeps the same
rollback form.

### Decide

Write the revised plan-doc (`kit/shapes/plan-doc.schema.json`) to
`.skills-state/issue-triage/<date>.json`. Label steps come first;
comment steps last, because a comment's rollback is a rung-6 delete.

**If the plan's only phase is "nothing to do": stop here** — report
that every open issue is triaged.

### Confirm

Only reached when the plan has at least one label or comment step.
Use the medium-risk gate (`kit/shared/gates/medium.md`), once for the
whole plan, listing every step by issue number:

> I'm about to apply N labels and M comments to K open issues in
> `<repo>`. This is visible to every subscriber of those issues.
> - **What:** [the step list]
> - **Why:** the revised triage plan at `.skills-state/issue-triage/<date>.json`
> - **Reversible?:** labels yes, by `gh issue edit N --remove-label`;
>   comments only through a rung-6 API delete.
>
> Proceed?

A declined gate ends the run with `triage-declined` and nothing
applied.

### Act

Only reached when the plan has at least one label or comment step.
For each step, in plan order: write the `pending` checkpoint
(`checkpoint.py issue-triage <date> --step <issue>-<action> --status
pending --compensating-action "<rollback>"`), check-before-act
(SDS-C-046: `gh issue view N --json labels,comments` — a label
already present or an identical comment already posted is a skip),
issue the mutation as a direct tool call — `gh issue edit N -R
<owner/repo> --add-label <label>` or `gh issue comment N -R
<owner/repo> --body <text>`, from the skill directory, never by
changing into the repository — then mark the step `completed`.

**Compensating action** (SDS-S-054): per step, the plan's `rollback`
— `gh issue edit N --remove-label <label>` for a label; for a
comment, the rung-6 API delete named in the step, which this skill
does not run.

**Checkpoint** (SDS-S-053): the two-phase record at
`.skills-state/issue-triage/<date>.json`, one step per label or
comment.

### Communicate

N/A — the labels and comments are the communication; subscribers are
notified by GitHub.

### Persist

Return the status-report: what was applied, skipped, or declined,
per issue, with the checkpoint path.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

`summary` counts labels and comments applied and issues skipped;
one section per issue touched, naming each label or comment and its
rollback; `generatedFrom` names the plan and checkpoint. On the
stop-early path the report says every issue was already triaged and
nothing was written.

## @throws

- `repo-invalid`: the path is not a directory.
- `issues-unparseable`: the issues file or live response is not a
  JSON array of issues.
- `as-of-invalid`: `--as-of` is missing with a fixture or does not
  parse.
- `gh-unreachable`: the live `gh issue list` call failed.
- `triage-declined`: the confirmation gate was declined; nothing was
  applied.
- `label-missing`: `gh issue edit` reported the label does not exist
  in the repository; create it and resume from the checkpoint.

## @example

**Input:** three open issues — #12 "App crashes on startup" with a
two-line body, #13 "Add dark mode", #14 already labelled `kind/docs`.

**Output (excerpt of the plan the gate shows):**

```json
{
  "goal": "Triage 2 untriaged open issue(s) as of 2026-09-05 (1 already triaged, skipped)",
  "phases": [
    { "name": "label", "steps": [
      { "description": "add label kind/bug to #12: title/body match the bug rule", "riskIfFails": "low", "rollback": "gh issue edit 12 --remove-label kind/bug" },
      { "description": "add label priority/high to #12: bug mentions a high-severity term", "riskIfFails": "low", "rollback": "gh issue edit 12 --remove-label priority/high" },
      { "description": "add label kind/feature to #13: title/body match the feature rule", "riskIfFails": "low", "rollback": "gh issue edit 13 --remove-label kind/feature" } ] },
    { "name": "comment", "steps": [
      { "description": "comment on #12 (bug without reproduction): Thanks for the report. Could you add the steps to reproduce…", "riskIfFails": "low", "rollback": "delete the comment with gh api -X DELETE … — a rung-6 call, so this step is sequenced last" } ] }
  ]
}
```
