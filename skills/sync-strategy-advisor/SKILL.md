---
name: sync-strategy-advisor
description: >-
  Assesses a branch against its base and upstream — ahead/behind
  counts, predicted conflicts, whether the branch is already shared —
  and recommends exactly one sync action (rebase, merge, pull, push,
  resolve conflicts, fetch first, or nothing) as a decision-doc without
  performing any of them. Use when a branch is behind main, before
  opening a PR, when asked whether to rebase or merge, or when git
  reports divergence.
license: Apache-2.0
compatibility: Requires git 2.34 or later. Run `git fetch` first; this
  skill never touches the network.
metadata:
  family: dev-skills-suite
  effect-tier: domain-read-only
  idempotent: "true"
  tier: pillar
  shape-out: decision-doc
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/assess_sync_state.py:*) Bash(git status:*)
  Bash(git rev-parse:*) Bash(git log:*) Bash(git diff:*)
  Bash(git show:*) Bash(git fetch:*) Read
---

# sync-strategy-advisor

## When to use

- A branch is behind its base and the question is rebase or merge.
- Before opening a pull request, to confirm the branch is current.
- `git status` reports the branch has diverged from its upstream.
- `pr-lifecycle-manager` needs to know whether a branch is ready to
  open a PR from.

## When not to use

- Performing the sync — this skill never runs `git pull`, `rebase`,
  `merge`, or `push`. It hands back a `decision-doc`; a Command Skill
  (or the user) acts on it. A rebase followed by a force-push is a
  rung-6 operation and is deliberately out of this skill's reach.
- Deciding whether the *content* of a branch is ready to merge (checks,
  reviews) — that is `pr-lifecycle-manager`'s readiness assessment.

## @requires

- REQUIRED: the current directory is the root of a git repository with
  a remote named `origin`.
- REQUIRED: the remote-tracking refs to compare against exist locally —
  run `git fetch` first. A missing base ref is a `refs-missing`
  failure, never a silent "up to date".
- OPTIONAL: `branch` (default: the current branch).
- OPTIONAL: `base` (default: the remote's HEAD branch, else
  `origin/main`).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): `git rev-parse
--show-toplevel` equals the current directory. Then:

```
python3 scripts/assess_sync_state.py . [--branch <name>] [--base <ref>]
```

The script reads only local git plumbing — rev-list counts against the
upstream and the base, an old-style `git merge-tree` conflict
prediction, and `git status --porcelain` — and applies the fixed rule
table in its docstring. This is hermetic (SDS-C-003): the same
fetched refs always yield the same decision-doc. A nonzero exit maps
to `@throws`; surface stderr verbatim.

### Analyze

The one judgment the script cannot make: whether the branch is
*shared*. It uses "fully pushed" as a heuristic (a fully pushed branch
is treated as shared, so it recommends `merge-base` over
`rebase-onto-base`). If the user states the branch is private (theirs
alone, even though pushed) or shared (others have pulled it, even
though it has unpushed commits), override that one choice in the
decision-doc's `decisionOutcome` and record the override and its
reason as an added `decisionDriver`. Change nothing else.

### Synthesize

Return the decision-doc, validated against
`kit/shapes/decision-doc.schema.json`. `chosenOption` is exactly one of
the ten options in `consideredOptions`; `facts` carries the measured
counts so a consumer can show them. `up-to-date` is a complete,
schema-valid decision-doc, not an empty result (SDS-C-033).

## @returns

Shape: `decision-doc` — see `kit/shapes/decision-doc.schema.json`.

A decision-doc whose `chosenOption` names the single recommended sync
action and whose `facts` object records `branch`, `base`, `upstream`,
`aheadUpstream`/`behindUpstream`, `aheadBase`/`behindBase`,
`conflictsPredicted`, and `dirtyWorkTree`. Nothing in the repository
has changed.

## @throws

- `repo-invalid`: the path is not the root of a git repository.
- `branch-missing`: the requested branch does not exist.
- `refs-missing`: the base's remote-tracking ref is not present
  locally (fetch first).
- `facts-unparseable`: an injected facts file is unreadable or lacks
  required keys.

## @example

**Input:** branch `feature/behind-unpushed`, one local commit on top
of a base that has since gained one commit, no predicted conflict.

**Output (excerpt):**

```json
{
  "decisionOutcome": {
    "chosenOption": "rebase-onto-base",
    "justification": "The branch is behind its base and has unpublished commits only; rebasing keeps history linear without rewriting anything shared."
  },
  "facts": { "aheadBase": 1, "behindBase": 1, "aheadUpstream": 1, "behindUpstream": 0, "conflictsPredicted": false, "dirtyWorkTree": false }
}
```
