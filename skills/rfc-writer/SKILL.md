---
name: rfc-writer
description: >-
  Writes a request-for-comments design doc that will survive review:
  a three-sentence summary, motivation stated before the proposal,
  goals with explicit non-goals, at least two alternatives each with
  why it lost, risks each with a mitigation or an honest acceptance,
  a rollout with its rollback, and open questions each with an owner
  — refusing to render a placeholder, an anonymous owner, or a risk
  with no answer, so the page passes design-doc-review's structural
  pass by construction. Use when a change is big enough to need
  agreement before code, when asked to write an RFC or design doc,
  or when a decision keeps being re-litigated in chat.
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
  Bash(python3 scripts/render_rfc.py:*) Bash(git log:*) Read Write
---
<!-- Write is used only for the two-phase checkpoint under
     .skills-state/rfc-writer/ and for the specification JSON handed
     to the render script (SDS-S-024). The RFC itself is written by
     scripts/render_rfc.py, a rung-4 local write. Re-rendering an
     unchanged specification rewrites an identical file, hence
     idempotent: "true" (SDS-C-004). -->

# rfc-writer

## When to use

- A change is large, cross-team, or hard to reverse, and needs
  agreement before code is written.
- Asked to write an RFC, a design doc, or a proposal.
- The same decision keeps being re-argued in chat because nothing
  was written down.

## When not to use

- Recording a decision already made — that is `adr-writer`; an RFC
  argues for a change, an ADR records the outcome.
- Reviewing someone else's RFC — that is `design-doc-review`.
- A change small enough that the pull request description is the
  proposal — `pr-description-writer`.

## @requires

- REQUIRED: the change being proposed and why, from the driver, an
  issue, or a conversation.
- REQUIRED: the RFC directory in the repository (`docs/rfcs/` or the
  team's equivalent).
- OPTIONAL: `authors` (default: the driver).
- OPTIONAL: `status` (default: `draft`).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the RFC directory
exists. Read the existing RFCs' titles (`git log` on the directory
shows the latest) so the numbering and tone match, the issue or
thread that prompted this, and any ADR the change would supersede.

### Analyze

Decide the argument before the prose (SDS-S-061). What is the
situation that makes the change worth its cost — stated so that
someone who rejects the proposal still agrees with the situation?
What are the goals, and what is deliberately out of scope? Which
two or more alternatives would a skeptic raise, and why does each
lose — honestly, not as straw men? What could go wrong, and for each
risk, what is the mitigation or why is it accepted? How does this
roll out, and how does it roll back? What remains unknown, and who
will find out?

### Decide

Compose the specification (`assets/rfc.schema.json`, this skill's
own shape, SDS-S-080): `title`, `status`, `authors`, `date`,
`summary` (three sentences), `motivation`, `goals`, `nonGoals`,
`proposal`, `alternatives` (at least two, each with `whyNot`),
`risks` (each with `mitigation`), `rollout` with `plan` and
`rollback`, and `openQuestions` each with an `owner`. Write it under
`.skills-state/rfc-writer/`. Preview:

```
python3 scripts/render_rfc.py <rfc.json> --out-dir <rfc-dir> --dry-run
```

The script refuses a placeholder anywhere, an anonymous owner, or a
risk with no mitigation (`rfc-incomplete`), warns on a summary over
three sentences or a proposal shorter than the motivation, and
renders the page.

**If the target file already equals the dry-run output: stop here**
— there is nothing to write, say so.

### Confirm

Only reached when the rendered RFC differs from the existing file.
Rung 4 needs no gate (SDS-S-031); show the dry run and its warnings
— the alternatives section in particular, because a reviewer will
read it first.

### Act

Only reached when the rendered RFC differs from the existing file.
Write the `pending` checkpoint (single mutating step — inline via the
Write tool, SDS-S-055) to `.skills-state/rfc-writer/<slug>.json`,
with `preState` = whether the file existed and its byte length, then:

```
python3 scripts/render_rfc.py <rfc.json> --out-dir <rfc-dir>
```

Check-before-act (SDS-C-046): if the target already equals the
dry-run output (a resumed run), skip the write. On success update the
checkpoint to `completed` with `postState` = the written path and
section list.

**Compensating action** (SDS-S-054): restore the previous file from
version control if one was replaced, or delete the new file if none
existed.

**Checkpoint** (SDS-S-053): the pending-then-completed record at
`.skills-state/rfc-writer/<slug>.json`.

### Communicate

N/A — the RFC reaches its reviewers through the repository and the
team's review channel; this skill sends no message.

### Persist

The rendered `<rfc-dir>/<slug>.md` is the durable artifact. Return
its path, the section list, and the remaining warnings — and suggest
running `design-doc-review` on it before circulating.

## @returns

Shape: `freeform` (a markdown RFC).

Status line, summary, motivation, goals, non-goals, proposed design,
alternatives each with why not, risks each with a mitigation,
rollout with rollback, and owned open questions — the sections
`design-doc-review`'s checklist requires, in its order. Exactly one
file was written; on the stop-early path, when the existing file
already matched, nothing was written and the result says so.

## @throws

- `rfc-unparseable`: the specification is unreadable or not JSON.
- `rfc-invalid`: the specification fails `assets/rfc.schema.json`
  (including fewer than two alternatives).
- `rfc-incomplete`: a placeholder, an anonymous owner, or a risk
  without a mitigation.
- `out-dir-missing`: the RFC directory does not exist.

## @example

**Input:** a proposal to retry transient payment-gateway failures
with an idempotency key, prompted by a 2% failure rate.

**Output (excerpt):**

```markdown
# RFC: Checkout retries

**Status:** draft · **Authors:** @priya · **Date:** 2026-09-05

## Summary

Retry transient gateway failures with an idempotency key. …

## Alternatives considered

### Client-side retry in the web app

**Why not:** duplicates charges when the first call succeeded but the response was lost.
```
