---
name: changelog-writer
description: >-
  Collects the Conventional Commits since the last tag, groups them
  into Keep a Changelog categories as a status-report, and inserts the
  entry at the top of CHANGELOG.md, refusing to write a version that
  already exists. Use when cutting a release, when asked to update or
  generate the changelog, or when a PR needs a changelog entry from
  its commits.
license: Apache-2.0
compatibility: Requires git and the Python `jsonschema` package (the
  render script validates the report against the family shape).
  Assumes commit messages follow Conventional Commits; others are
  listed as Uncategorized, never dropped.
metadata:
  family: dev-skills-suite
  effect-tier: local-write
  idempotent: "false"
  tier: situational
  shape-out: status-report
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/collect_commits.py:*)
  Bash(python3 scripts/render_changelog.py:*) Bash(git log:*)
  Bash(git rev-parse:*) Bash(git describe:*) Bash(git tag -l:*) Read
  Write
---
<!-- Write is used only for the two-phase checkpoint under
     .skills-state/changelog-writer/ and for the report JSON handed to
     the render script (SDS-S-024). CHANGELOG.md itself is written by
     scripts/render_changelog.py, a rung-4 local write. Not idempotent:
     a second run for the same version is refused (version-exists). -->

# changelog-writer

## When to use

- Cutting a release and the changelog needs its entry.
- Asked to update or generate CHANGELOG.md.
- A PR needs a changelog entry derived from its commits.

## When not to use

- Writing user-facing release notes — that is `release-notes-writer`
  (situational), which takes this skill's status-report as input and
  rewrites it for an external audience; this skill stays close to the
  commits.
- Publishing the release on GitHub — that is `release-publisher`
  (situational, rung 6); this skill only edits a file in the working
  tree.
- Amending an already-released entry: refused by design
  (`version-exists`); that is a deliberate manual edit.

## @requires

- REQUIRED: the current directory is the root of a git repository with
  at least one commit.
- REQUIRED: a `CHANGELOG.md` exists (created by the user in Keep a
  Changelog form; a missing file is `changelog-missing`).
- OPTIONAL: `version` — the entry heading (default: `Unreleased`).
- OPTIONAL: `since` — the ref to collect from (default: the most
  recent tag, or the root commit if none).
- OPTIONAL: `include-all` — also list chore/docs/test/ci/build/style
  commits under Changed (default: omitted as not user-facing).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): repository root,
`CHANGELOG.md` present. Then collect — the mechanical part
(SDS-S-060):

```
python3 scripts/collect_commits.py . [--since <ref>] [--include-all]
```

It reads `git log` (rung 2, domain-read-only) and prints a
`status-report` with one section per non-empty Keep a Changelog
category (Added, Changed, Deprecated, Removed, Fixed, Security) plus
Uncategorized for commits that do not follow Conventional Commits;
breaking changes are prefixed `**BREAKING:**`. Write it to the report
file. A nonzero exit maps to `@throws`.

### Analyze

The script sorts by commit *type*; this stage judges *relevance*
(SDS-S-061). Drop lines a user of the project would not care about
even though they are typed `feat`/`fix` (a fix to a test-only helper;
a feature behind a flag nobody can turn on yet) and say so in the
summary. Every Uncategorized line is a decision: file it under the
category its content earns, or leave it and flag the commit message
for the author — never let a change disappear because its message was
sloppy. If the same change spans several commits, merge them into one
line citing all hashes.

### Decide

Settle the entry heading: a concrete `version` (must not already
exist in the file) or `Unreleased`. Preview:

```
python3 scripts/render_changelog.py <report.json> --changelog CHANGELOG.md --version <version> --dry-run
```

### Confirm

Rung 4 needs no gate (SDS-S-031); show the rendered entry anyway, since
it becomes permanent release history once tagged, and confirm the
version string with the user if it was not given.

### Act

Write the `pending` checkpoint (single mutating step — inline via the
Write tool, SDS-S-055) to `.skills-state/changelog-writer/<version>.json`
with `preState` = the current `CHANGELOG.md` content hash, then:

```
python3 scripts/render_changelog.py <report.json> --changelog CHANGELOG.md --version <version>
```

Check-before-act (SDS-C-046): the render script itself refuses if the
version's entry already exists; treat that refusal as "already
applied", not as an error to retry. On success update the checkpoint
to `completed` with `postState` = the entry heading written.

**Compensating action** (SDS-S-054): `git checkout -- CHANGELOG.md`
restores the pre-entry file (the change is uncommitted until the user
commits it).

**Checkpoint** (SDS-S-053): the pending-then-completed record at
`.skills-state/changelog-writer/<version>.json`.

### Communicate

N/A — the entry reaches readers with the release; this skill sends no
message.

### Persist

`CHANGELOG.md` with the new entry at the top is the durable artifact.
Return the status-report as this skill's output so
`release-notes-writer` can consume it.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

The categorized report (summary of counts, one section per category,
`generatedFrom` naming the ref range), and a `CHANGELOG.md` whose
first `## ` entry is the new version. Existing entries are unchanged
byte for byte.

## @throws

- `repo-invalid`: the current directory is not a git repository root.
- `log-unreadable`: an injected log file could not be read.
- `report-unparseable`: the report handed to the renderer is not JSON.
- `report-invalid`: the report fails the family shape.
- `changelog-missing`: `CHANGELOG.md` does not exist.
- `version-exists`: the file already has an entry for that version.

## @example

**Input:** eight commits since `v1.1.0` — two features (one breaking),
two fixes (one in scope `security`), a perf change, a deprecation, a
docs commit, and a CI chore — and `version` `1.2.0`.

**Result:** a `## [1.2.0] - 2026-09-06` entry inserted above
`## [1.1.0]` with sections Added (2, one `**BREAKING:**`), Changed (1),
Deprecated (1), Fixed (1), Security (1); the docs and CI commits are
omitted as not user-facing; the report returned with those counts.
