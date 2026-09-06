---
name: commit-message-lint
description: >-
  Checks every commit message in a range against Conventional Commits
  — subjects that do not parse as `type(scope)!: description`, types
  outside the allowed set, a breaking bang with no BREAKING CHANGE
  footer, over-long or capitalised subjects, empty descriptions, and
  fixup! commits that were never squashed — as a finding-list, so the
  changelog and the version bump that read those messages stay
  correct. Use before merging a branch, when a changelog came out
  wrong, or when asked whether commits follow the convention.
license: Apache-2.0
compatibility: Requires git for live mode; evals run from a recorded
  log file.
metadata:
  family: dev-skills-suite
  effect-tier: domain-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/lint_commits.py:*) Bash(git log:*)
  Bash(git symbolic-ref:*) Read
---

# commit-message-lint

## When to use

- Before merging a branch whose commits will be kept (rebase or
  merge, not squash).
- `changelog-writer` produced an entry with commits it could not
  classify.
- Asked whether commits follow the convention, or why the version
  bump was wrong.

## When not to use

- Writing the changelog — that is `changelog-writer`; this skill
  reads the same log and reports what would go wrong first.
- A branch about to be squash-merged with a rewritten title — only
  the final message matters; lint that one.
- Rewriting history — a `git rebase -i` the author runs; this skill
  only reports.

## @requires

- REQUIRED: the repository directory.
- OPTIONAL: `range` — the commits to check as `<base>..<head>`
  (default: the default branch to `HEAD`).
- OPTIONAL: `types` — the allowed types (default: the Conventional
  Commits set plus build, ci, chore, revert).
- OPTIONAL: `max-subject` — the subject length limit (default: 72).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then lint — the mechanical part (SDS-S-060):

```
python3 scripts/lint_commits.py <repo> [--range <base>..<head>] [--types a,b] [--max-subject N]
```

Live mode runs one `git log` over the range (rung 2); offline,
`--log-file <path>` takes the `%h<TAB>%s<TAB>%b<<END>>` recording
`changelog-writer` also uses (SDS-S-065). It reports
`commit/not-conventional`, `commit/unknown-type`,
`commit/breaking-no-footer`, `commit/subject-too-long`,
`commit/subject-style`, `commit/empty-description`, and
`commit/fixup-left`; merge commits are skipped.
`tool.properties` carries the commit and conformance counts.

### Analyze

The lint is exact; this stage decides what to do (SDS-S-061). A
`not-conventional` subject on a branch that will be rebased is a
rewrite request to the author, with the corrected subject proposed
from the diff's intent. An unknown type that the team uses on
purpose (`deps`, `wip`) is a `types` setting, not a finding — ask
before proposing a rename. A breaking bang without a footer is the
finding that matters most: the footer is what `release-notes-writer`
and the version bump read. A leftover `fixup!` means the branch is
not ready. Style infos are worth fixing only when the branch is
being rewritten anyway.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[rewrite: <proposed subject>]`, `[add footer:
BREAKING CHANGE: <what>]`, `[autosquash]`, `[team type: add to
types]`, `[leave: squash-merge]`.

### Synthesize

Return the finding-list, warnings first in commit order, with one
line: how many commits, how many conventional, and whether the
range is ready for a changelog. A clean range yields a well-formed
finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per defect, located at the commit hash, with the
subject and parsed type, scope, and breaking flag in `properties`;
`runs[0].tool.properties` carries the source, commit count, merges
skipped, and conformant count. Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `log-unreadable`: the log file cannot be read.
- `git-failed`: the live `git log` failed (bad range), or
  `max-subject` is not an integer.

## @example

**Input:** a branch with `feat(api)!: drop v1 endpoints` and no
footer.

**Output (excerpt):**

```json
{
  "ruleId": "commit/breaking-no-footer",
  "level": "warning",
  "message": { "text": "[add footer: BREAKING CHANGE: the v1 endpoints are removed; use /v2] 3f9c2a1: marked breaking with `!` but no BREAKING CHANGE: footer explains what breaks" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "3f9c2a1" } } }],
  "properties": { "hash": "3f9c2a1", "subject": "feat(api)!: drop v1 endpoints", "type": "feat", "scope": "api", "breaking": true }
}
```
