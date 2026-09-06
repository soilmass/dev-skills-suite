---
name: adr-writer
description: >-
  Captures an architecture decision as a numbered MADR record in the
  repository's ADR directory and as a machine-readable decision-doc,
  treating accepted records as immutable and superseding rather than
  editing them. Use when a significant technical choice has just been
  settled, when asked to write or record an ADR, or when an earlier
  decision is being replaced.
license: Apache-2.0
compatibility: Requires the Python `jsonschema` package (the render
  script validates the decision-doc against the family shape).
metadata:
  family: dev-skills-suite
  effect-tier: local-write
  idempotent: "false"
  tier: pillar
  shape-out: decision-doc
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/render_adr.py:*) Bash(git status:*)
  Bash(git log:*) Read Write
---
<!-- Write is used only for the two-phase checkpoint under
     .skills-state/adr-writer/ and for the decision-doc JSON handed to
     the render script (SDS-S-024). The ADR file itself is written by
     scripts/render_adr.py, a rung-4 local write (SDS-S-051 governs
     rung 5/6 only). -->

# adr-writer

## When to use

- A significant technical choice was just settled and should be
  recorded before the reasoning is lost.
- The user asks to write, draft, or record an ADR.
- An earlier decision is being replaced and the old record must be
  marked superseded rather than rewritten.

## When not to use

- Reviewing whether a *proposed* design is sound — that is
  `design-doc-review` (situational). This skill records a decision
  already made; it does not evaluate it.
- Recording an operational choice (a runbook step, an incident
  action) — those are `runbook-writer` / `incident-postmortem`, whose
  outputs are status-reports, not decision records.

## @requires

- REQUIRED: the current directory is the root of a git repository.
- REQUIRED: an ADR directory exists (default `docs/adr/`; created by
  the user, never by this skill — a missing directory is
  `adr-dir-missing`).
- OPTIONAL: `title` (default: the chosen option's name).
- OPTIONAL: `supersedes` — the four-digit number of the ADR this
  decision replaces (default: none).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): repository root, ADR
directory present. Read the existing ADRs' titles and status lines
(`grep -h '^# \|^- status' <adr-dir>/*.md`) so the new record can
reference prior ones and so a decision that is really a supersession
is recognized as one.

### Analyze

Elicit, from the conversation and the user, the four things a MADR
record needs and that no script can supply: the context and problem
statement, the decision drivers, every option actually considered
(including the ones rejected), and the consequences — good and bad —
of the chosen one. Push back on a record with one option and no
negative consequences; that is an announcement, not a decision. If an
existing accepted ADR covers the same question, this decision
supersedes it: ask, and set `supersedes`.

### Decide

Compose the `decision-doc` (`kit/shapes/decision-doc.schema.json`)
with `status: proposed`, exactly one `chosenOption` drawn from
`consideredOptions`, and a `confirmation` stating how compliance will
be checked. Write it to a file under `.skills-state/adr-writer/`
(a scratch input, not the record).

Preview the render without writing anything:

```
python3 scripts/render_adr.py <decision.json> --adr-dir <adr-dir> [--title "<title>"] [--supersedes <NNNN>] --dry-run
```

The script validates the decision-doc against the shape
(`decision-invalid` on failure) and prints the target path, the next
number, and the rendered markdown.

### Confirm

Rung 4 needs no gate (SDS-S-031); show the dry-run render and the
target path anyway, because the record is about to become part of the
repository's history. If `supersedes` is set, say explicitly that
ADR-<NNNN>'s status line will change to `superseded by ADR-<new>` and
that nothing else in it will.

### Act

Write the `pending` checkpoint (single mutating step — inline via the
Write tool, SDS-S-055) to `.skills-state/adr-writer/<NNNN>.json`
before the call, with `preState` holding the superseded ADR's current
status line when `supersedes` is set:

```
python3 scripts/render_adr.py <decision.json> --adr-dir <adr-dir> [--title "<title>"] [--supersedes <NNNN>]
```

Check-before-act (SDS-C-046): the dry-run number must still be the
next free number; if another ADR landed meanwhile, re-run the dry run
rather than overwrite. On success update the checkpoint to
`completed` with `postState` = the written path.

**Compensating action** (SDS-S-054): delete the newly written
`<adr-dir>/<NNNN>-<slug>.md` (it is untracked until committed), and,
if `supersedes` was set, restore the superseded ADR's original status
line from `preState`.

**Checkpoint** (SDS-S-053): the pending-then-completed record at
`.skills-state/adr-writer/<NNNN>.json`.

Never edit an accepted ADR's body (SDS-C-034). The status line of a
superseded record is the single field MADR designates as mutable; a
changed decision is always a new numbered record.

### Communicate

N/A — the ADR file in the repository is the communication; it reaches
readers when committed and reviewed like any other change.

### Persist

The rendered ADR at `<adr-dir>/<NNNN>-<slug>.md` is the durable
artifact. Return the decision-doc (now `status: accepted`) as this
skill's output; leave committing to the user or a Command Skill.

## @returns

Shape: `decision-doc` — see `kit/shapes/decision-doc.schema.json`.

The accepted decision-doc, plus the path of the written ADR and (when
superseding) the path of the record whose status line was updated.
Exactly one new file exists in the ADR directory; if `supersedes` was
set, exactly one status line changed in one existing file.

## @throws

- `decision-unparseable`: the decision-doc file is unreadable or not
  valid JSON.
- `decision-invalid`: the decision-doc fails the family shape (for
  example, no `decisionOutcome`).
- `adr-dir-missing`: the ADR directory does not exist.
- `supersede-target-missing`: no ADR with the given number exists, or
  it has no status line to update.

## @example

**Input:** the settled choice of managed PostgreSQL, ADR directory
`docs/adr/` containing no records yet.

**Result:** `docs/adr/0001-postgresql-managed.md` rendered from the
decision-doc — title, `status: accepted`, date, Context, Drivers,
Considered Options, Decision Outcome with justification, Consequences
(good and bad), Confirmation — and the decision-doc returned with
`status: accepted`.
