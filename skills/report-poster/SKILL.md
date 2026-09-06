---
name: report-poster
description: >-
  Posts any family status-report as a comment on a pull request or
  GitHub issue — one section per heading, a footer naming what the
  report covers, and a hidden marker so a repeat run recognizes its
  own comment instead of posting a duplicate. Use after a
  status-report is produced, when asked to post it as a comment, or
  when a pull request or GitHub issue needs the report where its
  readers already are.
license: Apache-2.0
compatibility: Requires the gh CLI authenticated with write access to
  comment on the target repository — live mode only.
metadata:
  family: dev-skills-suite
  effect-tier: shared-write
  idempotent: "true"
  tier: situational
  shape-out: status-report
  shape-in: status-report
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/render_report_comment.py:*)
  Bash(python3 scripts/checkpoint.py:*) Bash(gh pr view:*)
  Bash(gh issue view:*) Read Write
---
<!-- Write is scoped to .skills-state/report-poster/ only (SDS-S-024).
     The mutation — gh pr comment / gh issue comment — is deliberately
     absent from allowed-tools (SDS-S-023) and is issued as a direct,
     unwrapped tool call after the gate (SDS-S-051). The compensating
     action — gh api -X DELETE
     repos/<owner>/<repo>/issues/comments/<id> — is a rung-6 action
     this skill does not run. -->

# report-poster

## When to use

- A status-report exists and needs to reach people where they already
  read — a pull request or a GitHub issue.
- Asked to post a status-report as a comment, or to put a report
  where reviewers will see it.
- A recurring status-report keeps regenerating and the same comment
  would otherwise be duplicated on every run.

## When not to use

- Preparing or publishing release notes — that is `release-publisher`.
- Turning findings into tracked work — that is `findings-to-issues`;
  findings become issues there, not comments.
- A repository without `gh` authenticated with write access to
  comment on the target pull request or GitHub issue — posting fails
  at Act.

## @requires

- REQUIRED: a `status-report` file, as any family skill emits.
- REQUIRED: `--target` — `pr:<n>` or `issue:<n>` naming the pull
  request or GitHub issue to comment on.
- OPTIONAL: `--marker` — the identifier embedded in the hidden marker
  that makes a repeat run a no-op (default: the first 12 hex
  characters of a hash of the report's `generatedFrom`, or its
  `summary` when `generatedFrom` is absent).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the input parses and
conforms to the shape, and `--target` matches `pr:<n>` or `issue:<n>`.
Then render — the mechanical part (SDS-S-060):

```
python3 scripts/render_report_comment.py <status-report.json> --target pr:<n>|issue:<n> [--marker <id>]
```

It validates against `kit/shapes/status-report.schema.json`, then
renders one comment body: `## <summary>`, one `### <heading>` section
per entry with its body, a footer line naming `generatedFrom` when the
report carries one, and the hidden marker `<!-- sds-report: <id> -->`
as the last line — so a later run recognizes its own comment. A
nonzero exit maps to `@throws`.

### Analyze

The render is mechanical; this stage reads the rendered body before
deciding to post it (SDS-S-061). A summary or section body that reads
fine inside a report can read as noise, or as exposing something not
meant for the target's audience, once it is a public comment — check
every section for that before Confirm. A `--target` that names the
wrong pull request or GitHub issue for what the report actually
covers is worth catching here, not after posting.

### Decide

The plan has exactly one step: post the rendered comment to
`<pr|issue> #<n>`.

**If a comment carrying the marker already exists: stop here.**
Report that the target already carries this report as a comment and
nothing new needs to be posted; this is the idempotency rule
(SDS-C-004).

### Confirm

Only reached when no comment on the target carries the marker yet.
Use the medium-risk gate (`kit/shared/gates/medium.md`):

> I'm about to post a comment on `<pr|issue> #<n>` in `<owner/repo>`
> carrying the status-report's summary and N section(s). This is
> visible to every subscriber of the pull request or GitHub issue.
> - **What:** post the rendered comment body to `<pr|issue> #<n>`.
> - **Why:** the status-report named at Gather.
> - **Reversible?:** not without a rung-6 API delete —
>   `gh api -X DELETE repos/<owner>/<repo>/issues/comments/<id>`,
>   which this skill does not run.
>
> Proceed?

A declined gate ends the run with `post-declined` and nothing posted.

### Act

Only reached when the Confirm gate is accepted. Check-before-act
(SDS-C-046): `gh pr view <n> -R <owner/repo> --json comments` or
`gh issue view <n> -R <owner/repo> --json comments` — a comment whose
body already contains the marker is a skip. If the view call reports
the pull request or GitHub issue does not exist, stop with
`target-missing`; any other failure to reach GitHub is
`gh-unreachable`. Write the `pending` checkpoint (`checkpoint.py
report-poster <pr|issue>-<n> --step <pr|issue>-<n>-comment --status
pending --compensating-action "gh api -X DELETE
repos/<owner>/<repo>/issues/comments/<id> — a rung-6 delete, so a
human runs it"`). Write the rendered body to
`.skills-state/report-poster/<pr|issue>-<n>-body.md` (Write tool).
Issue the mutation as a direct tool call, never through a bundled
script: `gh pr comment <n> -R <owner/repo> --body-file
.skills-state/report-poster/<pr|issue>-<n>-body.md` or `gh issue
comment <n> -R <owner/repo> --body-file …`. After success, mark the
step `completed`.

**Compensating action** (SDS-S-054): the rung-6 API delete named in
the plan — `gh api -X DELETE
repos/<owner>/<repo>/issues/comments/<id>` — which this skill does
not run.

**Checkpoint** (SDS-S-053): the two-phase record at
`.skills-state/report-poster/<pr|issue>-<n>.json`, one step for the
comment.

### Communicate

N/A — the comment is the communication.

### Persist

Return the status-report: which pull request or GitHub issue received
the comment, the marker used, and the checkpoint path — or, on the
stop-early path, that a comment carrying the marker already exists
and nothing new was posted.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

Once this skill succeeds, the named pull request or GitHub issue has
one comment carrying the status-report's content and its marker, and
`.skills-state/report-poster/` holds a `completed` checkpoint record
for it. On the stop-early path the report says a comment with that
marker already exists and nothing new was posted.

## @throws

- `report-invalid`: the input is unreadable, not JSON, or fails
  `kit/shapes/status-report.schema.json`.
- `target-invalid`: `--target` does not match `pr:<n>` or `issue:<n>`
  with `n >= 1`.
- `post-declined`: the confirmation gate was declined; nothing was
  posted.
- `target-missing`: the pull request or GitHub issue named by
  `--target` does not exist, from the `gh … view` check.
- `gh-unreachable`: the live `gh … view` or comment call failed to
  reach GitHub.

For a failure after the `pending` checkpoint was written but before
the comment call completes, resume by re-reading the checkpoint and
re-running the check-before-act read: a `pending` step with no
matching marker on the target means the comment never landed and may
be retried; a `pending` step whose marker is now present means it
landed and the step should be marked `completed` without posting
again.

## @example

**Input:** `findings-digest`'s status-report for three audits — six
sections — targeted at pull request #7.

**Confirmed action:** the Confirm gate above, showing the summary and
six sections for `pr #7`.

**Result:** `gh pr comment 7 -R soilmass/dev-skills-suite --body-file
.skills-state/report-poster/pr-7-body.md` succeeds; the checkpoint at
`.skills-state/report-poster/pr-7.json` records the `pr-7-comment`
step as `completed`; the status-report names pull request #7 and the
marker used.
