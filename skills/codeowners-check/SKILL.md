---
name: codeowners-check
description: >-
  Checks a repository's CODEOWNERS file against its tree the way
  GitHub reads it — last matching rule wins, gitignore-style patterns
  — and reports top-level paths no rule owns, rules that match
  nothing any more, lines with no owner, owners that are not a valid
  handle or are absent from a members list, and rules a later broader
  rule shadows completely — as a finding-list, leaving the call on who
  should own what to a human. Use when reviews are not being
  requested, after a directory moves, or when asked whether ownership
  is complete.
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
  Bash(python3 scripts/check_codeowners.py:*) Read
---

# codeowners-check

## When to use

- Pull requests in some directory get no automatic reviewer.
- A directory was moved or renamed and the rules were not.
- Asked whether ownership is complete, or who owns a path.

## When not to use

- Deciding who *should* own a path — the team; this skill reports
  what is unowned and what is stale, and Analyze proposes from the
  history.
- Enforcing review approval — branch protection settings; this
  skill reads a file.
- Team membership from GitHub — pass a members list captured with
  `gh api` (rung 3) if you want unknown handles flagged; this skill
  itself contacts nothing.

## @requires

- REQUIRED: the repository directory.
- OPTIONAL: `members` — a file with one valid handle per line
  (`@user`, `@org/team`), so owners outside the organisation are
  flagged (default: none; handles are checked for form only).
- OPTIONAL: `exclude` — directories to skip beyond the usual vendored
  and build directories (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then check — the mechanical part (SDS-S-060):

```
python3 scripts/check_codeowners.py <repo> [--members <file>] [--exclude dir,dir]
```

It locates the file as GitHub does, parses the rules, matches every
file in the tree with last-match-wins, and reports
`owners/unowned-path` (per top-level entry), `owners/rule-matches-nothing`,
`owners/no-owner`, `owners/invalid-owner`, `owners/unknown-owner`,
`owners/shadowed-rule`, and `owners/missing-file`. `tool.properties`
carries the rule, file, and owned-file counts and the owner set.

### Analyze

The check says what is unowned and stale; this stage says who
(SDS-S-061). For an unowned path, propose the owner from evidence —
the people who touch it (`git log --format=%an -- <path>`, which
this skill's script does not run; say what to run), the owner of
the nearest sibling, or "deliberately shared" when the path is
config every team edits. A rule matching nothing is deleted or
re-pointed at where the path went. A shadowed rule is either
deleted or moved *after* the broader rule so it wins again — say
which, based on whether its owners still differ. A catch-all `*`
rule at the top is a common pattern: everything below it must be
more specific and later.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[assign: @team, from history]`, `[shared: leave
unowned, say so in the file]`, `[delete stale rule]`, `[re-point to
<path>]`, `[move after line N]`, `[fix handle]`.

### Synthesize

Return the finding-list, warnings first, followed by the proposed
CODEOWNERS additions as lines ready to paste. A complete, current
file yields a well-formed finding-list with an empty `results` array
(SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per defect, located at the CODEOWNERS line (or the
file, for unowned paths), with the pattern, owners, or path in
`properties`; `runs[0].tool.properties` carries the counts and
owner set. Nothing was modified and nothing was contacted.

## @throws

- `repo-invalid`: the path is not a directory.
- `members-unreadable`: the members file cannot be read.

## @example

**Input:** a tree whose `infra/` directory matches no rule and whose
`/services/legacy/` rule points at a deleted directory.

**Output (excerpt):**

```json
{
  "ruleId": "owners/unowned-path",
  "level": "warning",
  "message": { "text": "[assign: @shop/platform, from history] infra/: 4 of 4 file(s) match no rule; nobody is requested for review there" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": ".github/CODEOWNERS" } } }],
  "properties": { "path": "infra", "unownedFiles": 4, "files": 4, "examples": ["infra/main.tf", "infra/vars.tf", "infra/modules/db/main.tf"] }
}
```
