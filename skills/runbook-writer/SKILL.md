---
name: runbook-writer
description: >-
  Turns tribal operational knowledge into a runbook a tired engineer
  can follow at 3 a.m.: a purpose, a trigger, preconditions, numbered
  steps that each pair a command with how to verify it worked and what
  to do if it did not, a rollback, and an escalation path — refusing
  to write a step that cannot be verified. Use when an incident
  revealed a missing runbook, when asked to write or update one, or
  when a procedure lives only in someone's head.
license: Apache-2.0
compatibility: Requires the Python `jsonschema` package (the render
  script validates the specification against this skill's asset
  schema).
metadata:
  family: dev-skills-suite
  effect-tier: local-write
  idempotent: "true"
  tier: situational
  shape-out: freeform
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/render_runbook.py:*) Bash(git log:*) Read Write
---
<!-- Write is used only for the two-phase checkpoint under
     .skills-state/runbook-writer/ and for the specification JSON
     handed to the render script (SDS-S-024). The runbook itself is
     written by scripts/render_runbook.py, a rung-4 local write.
     Re-rendering an unchanged specification rewrites an identical
     page, so idempotent is "true". -->

# runbook-writer

## When to use

- An incident's postmortem produced the action item "write the
  runbook for X".
- Asked to write or update an operational procedure.
- A procedure exists only as one person's memory or a chat thread.

## When not to use

- Planning the undo of a specific deploy — that is
  `rollback-plan-writer`; a runbook's Rollback section may point at
  one.
- Writing the postmortem that found the gap — that is
  `incident-postmortem`.
- Executing the procedure. A runbook is followed by a human; nothing
  here runs the commands it describes.

## @requires

- REQUIRED: the current directory is the root of a git repository.
- REQUIRED: a runbooks directory exists (default `docs/runbooks/`;
  created by the user — a missing directory is `out-dir-missing`).
- REQUIRED: the source knowledge — the person who does this today,
  a chat thread, shell history, or an existing informal note.
- OPTIONAL: `last-verified` — the date the procedure was last walked
  through end to end (default: none, which the runbook states
  plainly).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): repository root,
runbooks directory present. Collect the procedure as it is actually
performed, not as it is supposed to be: the exact commands (from
shell history where possible), what the operator looks at to know a
step worked, and what they did the last time it did not. Check
`git log` for the last change to any script the procedure calls.

### Analyze

Every step must answer three questions or it is not a step: what
exactly do I run, how do I know it worked, and what do I do if it did
not (SDS-S-061). Turn "check that it's fine" into an observable
("the dashboard's error rate stays below 0.5% for five minutes").
Turn "if it breaks, fix it" into an action or an escalation. Separate
preconditions (things that must already be true — a role, a VPN, a
quiet system) from steps. Decide the rollback for the whole
procedure and the point past which it no longer applies. Name who to
escalate to and the concrete condition that triggers it.

### Decide

Compose the specification (`assets/runbook.schema.json`, this skill's
own shape, SDS-S-080): `title`, `purpose`, `trigger`,
`preconditions`, `steps` each with `do`/`verify`/`ifFails`, `rollback`,
`escalation` with `who` and `when`, and `lastVerified` if the
procedure has been walked through. Write it under
`.skills-state/runbook-writer/`. Preview:

```
python3 scripts/render_runbook.py <runbook.json> --out-dir <runbooks-dir> --dry-run
```

The script validates the shape, refuses a step with an empty `verify`
or `ifFails` or an escalation with no `who` (`runbook-incomplete`),
warns on a `do` with no backticked command and on a missing
`lastVerified`, and renders the page.

### Confirm

Rung 4 needs no gate (SDS-S-031); show the dry run and its warnings
anyway — a warning about a step with no shown command is usually a
step where the command lives in someone's head, which is the problem
this skill exists to fix.

### Act

Write the `pending` checkpoint (single mutating step — inline via the
Write tool, SDS-S-055) to `.skills-state/runbook-writer/<slug>.json`,
with `preState` = the existing page's path if one is being replaced,
then:

```
python3 scripts/render_runbook.py <runbook.json> --out-dir <runbooks-dir>
```

Check-before-act (SDS-C-046): if the target page already equals the
dry-run output, skip the write. On success update the checkpoint to
`completed` with `postState` = the written path and step count.

**Compensating action** (SDS-S-054): restore the previous page from
version control if one was replaced, or delete the new file if none
was.

**Checkpoint** (SDS-S-053): the pending-then-completed record at
`.skills-state/runbook-writer/<slug>.json`.

### Communicate

N/A — the runbook reaches its readers through the repository and the
on-call rotation's index; this skill sends no message.

### Persist

The rendered page at `<runbooks-dir>/<slug>.md` is the durable
artifact. Return its path and the remaining warnings.

## @returns

Shape: `freeform` (a markdown runbook).

Purpose, trigger, preconditions, numbered steps each in Do / Verify /
If it fails form, rollback, and escalation; the page states plainly
whether it has ever been verified end to end. Exactly one file was
written.

## @throws

- `runbook-unparseable`: the specification is unreadable or not JSON.
- `runbook-invalid`: the specification fails `assets/runbook.schema.json`.
- `runbook-incomplete`: a step has no `verify` or `ifFails`, or the
  escalation names nobody.
- `out-dir-missing`: the runbooks directory does not exist.

## @example

**Input:** the payments engineer's description of rotating the
gateway API key, plus the four `opsctl` commands from their shell
history and the date they last did it.

**Result:** `docs/runbooks/rotate-the-payment-gateway-api-key.md` with
three preconditions, four steps each showing its command, what the
console or dashboard must show afterwards, and the recovery if it
does not; a rollback that names the secret-version command; an
escalation to `#payments-oncall` at a stated error-rate threshold; and
no warnings.
