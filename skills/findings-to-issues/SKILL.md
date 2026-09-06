---
name: findings-to-issues
description: >-
  Turns the findings an audit skill produced into a plan of GitHub
  issues — one per (tool, rule) group, skipping any group an open
  issue already tracks by its fingerprint marker — then files each
  issue only after a medium-risk confirmation, one issue at a time,
  with every filing checkpointed and reversible only by a human's
  rung-6 close. Use after an audit, when findings should become
  tracked work, or when asked to file the findings.
license: Apache-2.0
compatibility: Requires the gh CLI authenticated against the target
  repository with permission to read issues and, for Act, to create
  issues.
metadata:
  family: dev-skills-suite
  effect-tier: shared-write
  idempotent: "true"
  tier: situational
  shape-out: status-report
  shape-in: finding-list
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/plan_issues.py:*)
  Bash(python3 scripts/checkpoint.py:*) Bash(gh issue list:*)
  Bash(gh issue view:*) Read Write
---
<!-- Write is scoped to .skills-state/findings-to-issues/ and the
     revised plan-doc only (SDS-S-024). The mutation — gh issue
     create — is deliberately absent from allowed-tools (SDS-S-023)
     and is issued as a direct, unwrapped tool call after the gate
     (SDS-S-051). Closing issues is out of scope: gh issue close is
     rung 6 and belongs to a human. -->

# findings-to-issues

## When to use

- An audit skill just produced findings and someone needs them as
  tracked work, not just a report.
- Asked to file the findings, or to turn an audit into issues.
- A recurring audit keeps surfacing the same findings with nothing
  opened against them.

## When not to use

- Digesting or ranking findings across several audits — that is
  `findings-digest`, and it runs first.
- Labeling, prioritizing, or nudging issues that already exist —
  that is `issue-triage`.
- Closing an issue once its finding is fixed — never; that is a
  rung-6 action for a human.
- A repository without `gh` authenticated with permission to read
  and create issues — filing fails at Act.

## @requires

- REQUIRED: the repository directory, with `gh` authenticated.
- REQUIRED: one or more `finding-list` files, as any family audit
  skill emits.
- OPTIONAL: `min-level` — the lowest severity to file: `warning` or
  `error` (default: `warning`).
- OPTIONAL: `label` — the label attached to each filed issue
  (default: `audit`).
- OPTIONAL: `limit` — the most issues proposed in one run (default: 20).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then read the findings and the open issues and produce
the plan — the mechanical part (SDS-S-060):

```
python3 scripts/plan_issues.py <repo> <finding-list.json>... [--min-level warning|error] [--label L] [--limit N]
```

Live mode issues one read (`gh issue list --json …`, rung 3);
offline, `--issues-json-file <path>` replaces the call (SDS-S-065).
A group is already tracked when an open issue's body carries its
`<!-- sds-finding-group: <tool>/<ruleId> -->` marker; the script
skips it, which is what makes a re-run a no-op (SDS-C-004). If a
resumed run's checkpoint (`checkpoint.py findings-to-issues <date>
--show`) exists, read it first: `completed` steps are skipped;
`pending` ones are check-before-act'ed in Act below, since a step's
own record cannot yet name an issue number for a create that may or
may not have gone through.

### Analyze

The grouping is mechanical; this stage reads each proposed step and
corrects it with domain knowledge (SDS-S-061). A rule that only ever
fires on generated or vendored files is noise for a tracker — drop
the step. A proposed issue whose title names the same package and
advisory as one already filed by hand, without the marker, is a
duplicate a human filed before this skill ran — drop the step and
name the existing issue number in Persist. A `--label` that is not
one used elsewhere in the repository's open issues is worth flagging
here rather than discovering it at Act. Drop, change, or add steps;
every changed step keeps the same rollback form.

### Decide

Write the revised plan-doc (`kit/shapes/plan-doc.schema.json`) to
`.skills-state/findings-to-issues/<date>.json`.

**If the plan's only phase is "nothing to do": stop here** — report
that every finding group is already tracked, or that nothing reached
the floor.

### Confirm

Only reached when the plan has at least one create step. Use the
medium-risk gate (`kit/shared/gates/medium.md`), once for the whole
plan, listing every proposed issue:

> I'm about to file N GitHub issue(s) in `<owner/repo>` from findings
> at or above `<min-level>`. This is visible to every subscriber of
> the repository's issue tracker.
> - **What:** [the step list — one title per finding group]
> - **Why:** the plan at `.skills-state/findings-to-issues/<date>.json`
> - **Reversible?:** not without also taking a rung-6 action —
>   `gh issue close <number> --reason 'not planned'`, which this
>   skill does not run.
>
> Proceed?

A declined gate ends the run with `filing-declined` and nothing
created.

### Act

Only reached when the plan has at least one create step. For each
step, in plan order: write the `pending` checkpoint (`checkpoint.py
findings-to-issues <date> --step <tool>-<ruleId>-create --status
pending --compensating-action "<rollback>"`), check-before-act
(SDS-C-046: `gh issue list --search "sds-finding-group: <key>"
--state open` — a marker already present is a skip, because another
run or a human filed it since Decide ran), issue the mutation as a
direct tool call — `gh issue create -R <owner/repo> --title <title>
--body <body> --label <label>`, from the skill directory, never by
changing into the repository — then confirm the new issue's body
carries the marker (`gh issue view <number> --json body`) and mark
the step `completed`.

If `gh issue create` reports the label does not exist, stop with
`label-missing`: create the label first (`gh label create`) and
resume from the checkpoint.

**Compensating action** (SDS-S-054): per step, the plan's `rollback`
— `gh issue close <number> --reason 'not planned'`, a rung-6 action
this skill does not run.

**Checkpoint** (SDS-S-053): the two-phase record at
`.skills-state/findings-to-issues/<date>.json`, one step per created
issue.

### Communicate

N/A — the issue is the communication.

### Persist

Return the status-report: what was filed, skipped as already
tracked, or dropped in Analyze, per finding group, naming each
issue's number and its rollback, with the checkpoint path.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

`summary` counts issues filed and finding groups skipped;
`generatedFrom` names the finding-list inputs and the plan; one
section per finding group acted on, naming the issue number and its
rollback. On the stop-early path the report says every finding group
was already tracked (or none reached the floor) and nothing was
written.

## @throws

- `repo-invalid`: the path is not a directory.
- `findings-invalid`: an input is not a `finding-list` (no `runs`
  array, or `runs` is not an array).
- `issues-unparseable`: the issues file or live response is not a
  JSON array of issues.
- `level-invalid`: `--min-level` is not `warning` or `error`.
- `gh-unreachable`: the live `gh issue list` call failed.
- `filing-declined`: the confirmation gate was declined; nothing was
  created.
- `label-missing`: `gh issue create` reported the label does not
  exist in the repository; create it and resume from the checkpoint.

## @example

**Input:** `dependency-audit`'s finding-list — six findings across
six rules, three errors and three warnings — and one open issue,
#40, whose body already carries
`dependency-audit/GHSA-p6mc-m468-83gw`'s marker.

**Output (excerpt of the plan the gate shows):**

```json
{
  "goal": "File 5 issue(s) for 6 finding group(s) at or above warning (1 already open, skipped)",
  "phases": [
    { "name": "create", "steps": [
      { "description": "create issue '[dependency-audit] GHSA-29mw-wpgm-hmr9: 1 location(s)' with label audit; body:\n...", "riskIfFails": "low", "rollback": "gh issue close <number> --reason 'not planned' — a rung-6 close, so a human runs it", "checkpointAfter": true }
    ] }
  ]
}
```
