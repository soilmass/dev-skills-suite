---
name: design-doc-review
description: >-
  Reviews a design doc in two passes — a mechanical one that
  finds missing or empty sections against a checklist, leftover
  placeholders, an alternatives section with fewer than two options,
  and open questions nobody owns; then a judgment pass on whether the
  motivation is stated before the solution, the alternatives were weighed
  honestly, and the risks and rollout are real — returning a
  finding-list the author can act on. Use before a design review
  meeting, when asked to review or critique a design, or when a
  design doc is about to be marked accepted.
license: Apache-2.0
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/check_design_doc.py:*) Read
---

# design-doc-review

## When to use

- A design review meeting is scheduled and the document should
  arrive without structural gaps.
- Asked to review, critique, or pressure-test a design.
- A document is about to move from draft to accepted.

## When not to use

- Recording the decision once made — that is `adr-writer`; a design
  document argues, an ADR records.
- Writing the document — that is `rfc-writer`, which produces the
  structure this skill checks.
- Reviewing code — the pull request tools; this skill reads prose.

## @requires

- REQUIRED: the design doc, a markdown file with headings.
- OPTIONAL: `checklist` — the sections required and the heading
  aliases that count (default: `assets/checklist.json`).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the file exists and
has markdown headings. Then run the structural pass — the
mechanical part (SDS-S-060):

```
python3 scripts/check_design_doc.py <design.md> [--checklist <checklist.json>]
```

It reports `design/missing-section` and `design/empty-section`
against the checklist, `design/placeholder` (TBD, TODO, `???`,
bracketed fill-in markers), `design/too-few-alternatives`, `design/unowned-question`,
and `design/missing-metadata`. Then read the document itself, in
full — the structural pass only tells you where not to look twice.

### Analyze

This is the review (SDS-S-061). Ask, in order: Is the problem stated
before the solution, and would a reader who disagrees with the
solution still agree with the problem? Do the goals exclude
something (a goals list with no non-goals is a wish list)? Is each
alternative described well enough that someone could argue for it,
or is it a straw man? Does the proposed design answer the goals
one by one? Are the risks the ones a skeptic would raise, with a
mitigation or an honest "accepted"? Is the rollout reversible, and
does it say how? Do the open questions block acceptance or not, and
does the document say which? Every answer of "no" is a finding; cite
the section and quote the sentence that made you say no.

### Classify

Keep the script's findings and add the judgment findings with
`ruleId` `design/review` and a level: `error` when acceptance should
wait (problem unstated, no real alternatives, rollout not
reversible with no justification), `warning` when the author should
fix before the meeting, `info` when it is a suggestion. Prefix every
`message.text` with the action — `[state the problem first]`,
`[add a real alternative]`, `[name the mitigation]`, `[assign
owner]`, `[fill or delete]`.

### Synthesize

Return the finding-list, errors first, then warnings, then infos,
each located at the section's heading line, followed by one
paragraph: whether the document is ready for review and what would
change that. A complete, sound document yields a well-formed
finding-list with an empty `results` array (SDS-C-033) and that
paragraph.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

Structural findings from the script plus `design/review` findings
from the judgment pass, each located at a heading line with the
quoted evidence in `properties`. Nothing was modified.

## @throws

- `doc-missing`: the file does not exist or cannot be read.
- `doc-unstructured`: the file has no markdown headings.
- `checklist-invalid`: the checklist file is not the expected shape.

## @example

**Input:** a design document whose "Alternatives considered" section
says only "We also considered doing nothing."

**Output (excerpt):**

```json
{
  "ruleId": "design/too-few-alternatives",
  "level": "warning",
  "message": { "text": "[add a real alternative] the alternatives section lists 1 option(s); a design compared against fewer than two alternatives was not compared" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "checkout-retries.md" }, "region": { "startLine": 41 } } }],
  "properties": { "options": 1 }
}
```
