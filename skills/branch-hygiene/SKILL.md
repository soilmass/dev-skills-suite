---
name: branch-hygiene
description: >-
  Lists a repository's branches that are merged into the base, stale
  beyond a threshold, or tracking an upstream that no longer exists,
  as a finding-list for a human to act on — it proposes deletions and
  never performs one. Use when a repository has accumulated branches,
  before a release freeze, or when asked which branches can be cleaned
  up.
license: Apache-2.0
compatibility: Requires git 2.34 or later. Run `git fetch --prune`
  first so upstream state is current; this skill never touches the
  network.
metadata:
  family: dev-skills-suite
  effect-tier: domain-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/scan_branches.py:*) Bash(git rev-parse:*)
  Bash(git for-each-ref:*) Bash(git branch --merged:*) Bash(git log:*)
  Read
---

# branch-hygiene

## When to use

- A repository has accumulated branches and someone asks what can go.
- Before a release freeze or a repository migration.
- A `git fetch --prune` left local branches whose upstream is gone.

## When not to use

- Deleting the branches. `git branch -D` and `git push --delete` are
  rung-6 acts; this skill hands a human the list and stops
  (SDS-S-023). Nothing here is pre-approved to delete anything.
- Deciding whether a branch should be rebased or merged — that is
  `sync-strategy-advisor`.
- Judging whether the *work* on a stale branch is still wanted — that
  is a conversation with its author; this skill only says the branch
  is old and unmerged.

## @requires

- REQUIRED: the current directory is the root of a git repository
  with the base branch present.
- OPTIONAL: `base` (default: `main`).
- OPTIONAL: `stale-days` — age after which an unmerged branch is
  reported (default: 30).
- OPTIONAL: `as-of` — the reference date for staleness (default: the
  current date, which every stale finding then names as ambient).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): repository root, base
branch exists. Then scan — the mechanical part (SDS-S-060):

```
python3 scripts/scan_branches.py . [--base main] [--stale-days 30] [--as-of YYYY-MM-DD]
```

It reads local refs only (rung 2): which branches are merged into the
base, each branch's last commit date, and whether its upstream is
gone. Staleness depends on "today", which is ambient state a hermetic
Gather must not read silently (SDS-C-003): pass `--as-of` when the
result must be reproducible, and note that without it the findings
carry the date they used. A nonzero exit maps to `@throws`.

### Analyze

The scanner reports the mechanical state; this stage decides what to
propose (SDS-S-061). A merged branch is deletable on the evidence
alone. A stale branch is not — check `git log -1 <branch>` for its
author and last message, and treat a branch named like a release,
hotfix, or long-running integration line as out of scope unless the
user says otherwise. A gone-upstream branch whose work is merged is
just clutter; one whose work is unmerged may be the only copy left,
and is the finding to raise first.

### Classify

Keep the scanner's levels and prefix each finding's `message.text`
with the proposed action — `[delete]`, `[ask author]`, `[keep]` — and
the one-line reason. Never propose `[delete]` for an unmerged branch
with unique commits.

### Synthesize

Return the finding-list ordered `warning` first, then by branch name,
with a summary line of how many branches fall under each proposed
action. A repository with nothing merged, stale, or gone yields a
well-formed finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per branch condition (`branch/merged`, `branch/stale`,
`branch/gone-upstream`; a branch may carry more than one), each
located at `refs/heads/<name>` with `properties` holding the last
commit date, age in days, merged flag, and upstream. Nothing was
modified; no branch was deleted.

## @throws

- `repo-invalid`: the current directory is not a git repository root.
- `facts-unparseable`: an injected facts file is unreadable or lacks
  required fields.
- `bad-argument`: `stale-days` is not an integer or `as-of` is not a
  date.

## @example

**Input:** a repository with `feature/merged` (merged), `feature/stale`
(unmerged, last commit 2026-01-15), `feature/active` (unmerged, last
commit 2026-09-01), and `feature/gone` (upstream deleted), scanned
`--as-of 2026-09-06`.

**Output (excerpt):**

```json
{
  "ruleId": "branch/stale",
  "level": "warning",
  "message": { "text": "[ask author] feature/stale has no commits for 234 days (as of 2026-09-06) and is not merged into main" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "refs/heads/feature/stale" } } }],
  "properties": { "branch": "feature/stale", "lastCommit": "2026-01-15", "ageDays": 234, "merged": false, "upstream": "origin/feature/stale" }
}
```
