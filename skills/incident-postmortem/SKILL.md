---
name: incident-postmortem
description: >-
  Facilitates and writes a blameless incident postmortem — timeline,
  impact, contributing factors, what went well, owned and dated action
  items — as a status-report and a markdown record in the repository,
  with a mechanical check for completeness and blaming language. Use
  after an incident or outage is resolved, when asked to run a retro
  or postmortem, or when a review keeps turning into who-did-what.
license: Apache-2.0
compatibility: Requires the Python `jsonschema` package (the render
  script validates the status-report against the family shape).
metadata:
  family: dev-skills-suite
  effect-tier: local-write
  idempotent: "false"
  tier: pillar
  shape-out: status-report
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/render_postmortem.py:*) Bash(git log:*) Read
  Write
---
<!-- Write is used only for the two-phase checkpoint under
     .skills-state/incident-postmortem/ and for the status-report JSON
     handed to the render script (SDS-S-024). The record itself is
     written by scripts/render_postmortem.py, a rung-4 local write. -->

# incident-postmortem

## When to use

- An incident or outage has been resolved and needs a written record.
- The user asks to run a retro or postmortem on something that broke.
- A review of an incident keeps turning into who-did-what and needs
  redirecting to what-the-system-allowed.

## When not to use

- Writing the *runbook* the incident showed was missing — that is
  `runbook-writer` (situational); this skill produces an action item
  pointing at it, not the runbook.
- Recording a design decision the incident prompted — that is
  `adr-writer`; a postmortem can reference the ADR it led to.
- During the incident. This skill starts once the incident is closed;
  running it mid-incident turns responders into narrators.

## @requires

- REQUIRED: the current directory is the root of a git repository.
- REQUIRED: a postmortems directory exists (default
  `docs/postmortems/`; created by the user — a missing directory is
  `out-dir-missing`).
- REQUIRED: the incident's artifacts — at minimum an incident-channel
  export or responder notes, plus the alert and deploy timestamps for
  the window.
- OPTIONAL: `incident-id` and the incident window (default: taken from
  the artifacts).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): repository root,
postmortems directory present. Collect the artifacts for the window:
the channel export or notes, alert timestamps, and the deploys in the
window (`git log --since <start> --until <end> --format='%h %ad %s'
--date=iso`, rung 2). Read them before forming any explanation.

### Analyze

Reconstruct the timeline from the artifacts first — what was seen and
done, minute by minute — before any cause is discussed. Then derive
contributing factors, plural: for every "X did Y", ask what made Y the
reasonable action with the information available, and what would have
made the safer action easier; stop when the answer names a condition of
the system rather than a person. Record what went well (detection,
communication, rollback). If the session is being facilitated live with
responders rather than written from notes, consult
`references/facilitation-guide.md` — only then.

### Decide

Compose the `status-report` (`kit/shapes/status-report.schema.json`):
`summary` = one sentence of what happened and for how long; exactly
five sections headed `Timeline`, `Impact`, `Contributing Factors`,
`What Went Well`, `Action Items`; `generatedFrom` = the incident id,
window, and sources. Every action item carries `— owner: <name>, due:
YYYY-MM-DD`; if there genuinely are none, the section body begins
`No action items:` followed by the reason. Write the JSON under
`.skills-state/incident-postmortem/`.

Preview:

```
python3 scripts/render_postmortem.py <postmortem.json> --out-dir <postmortems-dir> --dry-run
```

The script validates the shape, refuses an incomplete record
(`postmortem-incomplete`), and lists every blaming phrase it noticed as
a warning. Rewrite each flagged sentence to describe the condition
rather than the person; if unsure how, consult
`references/blameless-language.md` — only then. A warning is a prompt
to re-read, not a verdict; the judgment stays with the writer.

### Confirm

Rung 4 needs no gate (SDS-S-031); show the dry-run render and the
remaining warnings anyway, because the record becomes part of the
repository's history and will be read by the people it describes. Do
not proceed while a flagged phrase has not been consciously kept or
rewritten.

### Act

Write the `pending` checkpoint (single mutating step — inline via the
Write tool, SDS-S-055) to
`.skills-state/incident-postmortem/<incident-id>.json`, then:

```
python3 scripts/render_postmortem.py <postmortem.json> --out-dir <postmortems-dir>
```

Check-before-act (SDS-C-046): if a record for the same date and slug
already exists, stop and ask rather than overwrite. On success update
the checkpoint to `completed` with `postState` = the written path.

**Compensating action** (SDS-S-054): delete the newly written record
(it is untracked until committed).

**Checkpoint** (SDS-S-053): the pending-then-completed record at
`.skills-state/incident-postmortem/<incident-id>.json`.

### Communicate

N/A — the record is committed and shared through the team's normal
review path; this skill sends no message of its own.

### Persist

The rendered record at `<postmortems-dir>/<YYYY-MM-DD>-<slug>.md` is
the durable artifact. Return the status-report as this skill's output.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

The five-section status-report, plus the path of the written record.
Exactly one new file exists in the postmortems directory; nothing else
in the repository changed.

## @throws

- `postmortem-unparseable`: the status-report file is unreadable or not
  valid JSON.
- `postmortem-invalid`: the document fails the family shape.
- `postmortem-incomplete`: a required section is missing, or an action
  item lacks an owner or due date.
- `out-dir-missing`: the postmortems directory does not exist.

## @example

**Input:** incident INC-2041 — 38 minutes of checkout 502s after a
config deploy pointed the payment client at the staging gateway;
channel export and deploy log available.

**Result:** `docs/postmortems/2026-09-04-checkout-api-returned-502-….md`
with the five sections, three action items each owned and dated, and
the status-report returned; the dry run flagged no blaming phrases.
