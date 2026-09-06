---
name: release-notes-writer
description: >-
  Turns a changelog status-report into release notes for people who
  use the software rather than build it: breaking changes first,
  security fixes next, commit hashes stripped, categories ordered by
  impact, and commits the changelog could not classify set aside for
  review instead of published. Use when publishing a release, when
  asked for user-facing release notes, or when a changelog entry needs
  rewriting for customers.
license: Apache-2.0
compatibility: Requires the Python `jsonschema` package (the prepare
  script validates input and output against the family shape).
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: status-report
  shape-in: status-report
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/prepare_notes.py:*) Read
---

# release-notes-writer

## When to use

- A release is being published and needs notes its users can read.
- Asked for user-facing or customer-facing release notes.
- A changelog entry exists but reads like a commit log.

## When not to use

- Producing the changelog itself from commits — that is
  `changelog-writer`, whose status-report is this skill's input.
- Publishing the release on GitHub — that is `release-publisher`
  (rung 6); this skill only prepares text.
- Internal engineering notes — the changelog already serves that
  audience; this skill deliberately removes what only engineers need
  (hashes, scopes, unclassified work-in-progress).

## @requires

- REQUIRED: a `status-report` in the form `changelog-writer` produces
  (Keep a Changelog category headings; optional Uncategorized).
- OPTIONAL: `product` — the product name for the summary line
  (default: none).
- OPTIONAL: `version` — the version for the summary line (default:
  none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the input file parses and
conforms to the shape. Then prepare — the mechanical part (SDS-S-060):

```
python3 scripts/prepare_notes.py <report.json> [--product <name>] [--version <x.y.z>]
```

It reads one local file (rung 1) and prints the same shape back with
hashes and scope labels stripped, breaking changes lifted into a
leading "Breaking changes" section, sections ordered by user impact,
and every Uncategorized line moved out of the notes into
`needsReview`. A nonzero exit maps to `@throws`.

### Analyze

The script decides *placement*; this stage decides *meaning*
(SDS-S-061). For every line ask what a user notices and what, if
anything, they must do. A breaking change needs its migration step in
the same sentence. A security fix needs the affected versions and
whether action is required — and nothing that helps an attacker. A
"changed" line that a user cannot observe is not release-note
material; drop it and say so. Work through `needsReview`: each is
either a change the author described badly (rewrite it from what it
actually did and file it under the right heading) or genuinely not
user-facing (leave it out and tell the author).

### Synthesize

Rewrite each surviving line in plain language, second person where a
user must act ("Upgrade to…", "Set … before…"), no hashes, no
internal names. Keep the section order the script set. Return the
notes as a `status-report` with the same headings; an input with no
user-facing changes yields a well-formed report whose summary says so
(SDS-C-033) — a release with nothing to announce is still a release.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

The prepared notes: `summary` = "<product> <version>: <counts>",
sections in impact order (Breaking changes, Security, Added, Changed,
Fixed, Deprecated, Removed) with hash-free lines, `generatedFrom`
carried over from the input, and `needsReview` listing every
unclassified commit that was withheld. Nothing was modified.

## @throws

- `report-unparseable`: the input is unreadable or not JSON.
- `report-invalid`: the input fails the family shape.

## @example

**Input:** `changelog-writer`'s report for 1.2.0 — two Added lines
(one `**BREAKING:**`), one Security fix, one Changed, one Fixed, one
Deprecated, two Uncategorized.

**Output (excerpt, before the Synthesize rewrite):**

```json
{
  "summary": "acme-cli 1.2.0: 1 breaking changes, 1 security, 1 added, 1 changed, 1 fixed, 1 deprecated",
  "sections": [
    { "heading": "Breaking changes", "body": "- drop Python 3.8 support" },
    { "heading": "Security", "body": "- reject path traversal in artifact names" }
  ],
  "needsReview": ["- Update stuff", "- WIP"]
}
```
