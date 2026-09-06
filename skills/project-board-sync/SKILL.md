---
name: project-board-sync
description: >-
  Brings a GitHub Projects board in line with the repository it
  tracks: adds open issues and pull requests the board is missing and
  moves each item to the column its real state implies — merged or
  closed to Done, draft PRs and assigned issues to In progress, ready
  PRs to In review, unassigned issues to Todo — as a plan-doc a human
  revises, applied only after a medium-risk confirmation with every
  edit reversible and checkpointed. Use when the board has drifted
  from reality, before a planning meeting, or when asked to update,
  sync, or tidy the project board.
license: Apache-2.0
compatibility: Requires the gh CLI authenticated with the `project`
  scope (gh auth refresh -s project), with read access to the board
  and, for Act, write access to it.
metadata:
  family: dev-skills-suite
  effect-tier: shared-write
  idempotent: "true"
  tier: situational
  shape-out: status-report
  shape-in: plan-doc
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/propose_board_sync.py:*)
  Bash(python3 scripts/checkpoint.py:*) Bash(gh project view:*)
  Bash(gh project field-list:*) Bash(gh project item-list:*)
  Bash(gh issue list:*) Bash(gh pr list:*) Read Write
---
<!-- Write is scoped to .skills-state/project-board-sync/ and the
     revised plan-doc only (SDS-S-024). The mutations — gh project
     item-add and gh project item-edit — are deliberately absent from
     allowed-tools (SDS-S-023) and are issued as direct, unwrapped tool
     calls after the gate (SDS-S-051). Removing items from the board is
     out of scope: the plan never deletes. -->

# project-board-sync

## When to use

- The board no longer matches what is open, merged, or assigned.
- Before a planning or stand-up meeting that reads the board.
- Asked to update, sync, or tidy the project board.

## When not to use

- Labelling or commenting on issues — that is `issue-triage`; this
  skill touches only board membership and the Status column.
- Removing items or archiving a board — never proposed; a human
  decides what leaves the board.
- Custom fields beyond Status (priority, iteration, estimate) — out
  of scope; the plan changes one field.

## @requires

- REQUIRED: the repository directory, with `gh` authenticated with
  the `project` scope.
- REQUIRED: `project` — the board number, and `owner` — the user or
  organisation that owns it.

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then read the board and the repository and produce the
proposal — the mechanical part (SDS-S-060):

```
python3 scripts/propose_board_sync.py <repo> --project <number> --owner <login>
```

Live mode issues five reads (`gh project view/field-list/item-list`,
`gh issue list`, `gh pr list`; rung 3); offline,
`--board-json-file <path>` replaces them (SDS-S-065). Items already
at their target column produce no step. If a resumed run's
checkpoint (`checkpoint.py project-board-sync <board> --show`) exists,
read it first: `completed` steps are skipped, `pending` ones are
check-before-act'ed against a fresh `gh project item-list`.

### Analyze

The rule table maps state to column; this stage catches what state
cannot say (SDS-S-061). An issue assigned as a placeholder ("owner:
triage") is not in progress. A PR marked ready but with changes
requested is still being worked on. A closed issue the team wants
visible for one more week can stay where it is — drop the step. A
board with columns the map in `assets/status-map.json` does not name
(Blocked, QA) needs the map edited, not the plan forced. Remove or
change steps; a changed step keeps the same rollback form.

### Decide

Write the revised plan-doc (`kit/shapes/plan-doc.schema.json`) to
`.skills-state/project-board-sync/<owner>-<number>.json`. Add steps
come first (an added item needs its status set next); status steps
follow.

**If the plan's only phase is "nothing to do": stop here** — report
that the board is in sync.

### Confirm

Only reached when the plan has at least one add or status step. Use
the medium-risk gate (`kit/shared/gates/medium.md`), once for the
whole plan:

> I'm about to add N item(s) to board `<title>` and change the
> Status of M item(s). This is visible to everyone who reads the
> board.
> - **What:** [the step list, each with from → to]
> - **Why:** the revised sync plan at `.skills-state/project-board-sync/<owner>-<number>.json`
> - **Reversible?:** yes — an added item by `gh project item-delete`,
>   a status change by setting the previous status back.
>
> Proceed?

A declined gate ends the run with `sync-declined` and nothing
applied.

### Act

Only reached when the plan has at least one add or status step. For
each step, in plan order: write the `pending` checkpoint
(`checkpoint.py project-board-sync <owner>-<number> --step
<kind>-<n>-<action> --status pending --compensating-action
"<rollback>"`), check-before-act (SDS-C-046: `gh project item-list`
shows the item already present, or already at the target status —
skip), issue the mutation as a direct tool call — `gh project
item-add <number> --owner <owner> --url <url>` then `gh project
item-edit --project-id <facts.projectId> --id <item-id> --field-id
<facts.statusFieldId> --single-select-option-id <optionId>` — then
mark the step `completed` with the new item id in `postState`.

**Compensating action** (SDS-S-054): per step, the plan's `rollback`
— `gh project item-delete` for an add (the new id is in the
checkpoint's `postState`), or `gh project item-edit` back to the
previous option for a status change.

**Checkpoint** (SDS-S-053): the two-phase record at
`.skills-state/project-board-sync/<owner>-<number>.json`, one step
per add or status change.

### Communicate

N/A — the board is the communication; this skill sends no message.

### Persist

Return the status-report: what was added, moved, skipped, or
declined, with the checkpoint path.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

`summary` counts items added and statuses changed; one section per
item touched with from → to and its rollback; `generatedFrom` names
the board, the plan, and the checkpoint. On the stop-early path the
report says the board was already in sync and nothing was written.

## @throws

- `repo-invalid`: the path is not a directory.
- `board-unparseable`: the board file or a live response is not the
  expected JSON.
- `status-field-missing`: the board has no single-select Status
  field, or it lacks a column named in `assets/status-map.json`.
- `gh-unreachable`: a live `gh` call failed (often a missing
  `project` scope).
- `sync-declined`: the confirmation gate was declined; nothing was
  applied.

## @example

**Input:** board "Checkout" with issue #12 in Todo (now assigned) and
PR #40 in In review (now merged); issue #15 open and not on the
board.

**Output (excerpt of the plan the gate shows):**

```json
{
  "goal": "Sync board 'Checkout' (#3) with the repository: 1 to add, 2 status change(s), 1 already in sync",
  "phases": [
    { "name": "add missing items", "steps": [
      { "description": "add issue #15 (Proxy support) to the board, then set Status to Todo", "riskIfFails": "low", "rollback": "gh project item-delete <project-number> --owner <owner> --id <new-item-id>" } ] },
    { "name": "set statuses", "steps": [
      { "description": "set Status of issue #12 (App crashes on startup) from Todo to In progress", "riskIfFails": "low", "rollback": "gh project item-edit --project-id PVT_1 --id PVTI_12 --field-id PVTSSF_1 --single-select-option-id opt-todo" },
      { "description": "set Status of PR #40 (Retry logic) from In review to Done", "riskIfFails": "low", "rollback": "gh project item-edit --project-id PVT_1 --id PVTI_40 --field-id PVTSSF_1 --single-select-option-id opt-review" } ] }
  ]
}
```
