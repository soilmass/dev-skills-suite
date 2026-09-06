---
name: release-publisher
description: >-
  Publishes a GitHub release for a version: takes the notes
  release-notes-writer prepared and the CI verdict ci-status-gate
  gave, checks that no release or draft for the tag already exists,
  that the notes are complete, reviewed, and name this version, and
  that CI passed — then creates the release, tag included, only after
  an explicit high-risk confirmation, since a published release
  notifies every watcher and cannot be un-sent. Use when cutting a
  release, when asked to publish, tag, or ship a version, or when
  finalizing a draft release.
license: Apache-2.0
compatibility: Requires git and the gh CLI, authenticated against the
  target repository with permission to create releases and push
  tags.
metadata:
  family: dev-skills-suite
  effect-tier: irreversible
  idempotent: "true"
  tier: situational
  shape-out: status-report
  shape-in: status-report, decision-doc
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/assess_release_readiness.py:*)
  Bash(python3 scripts/checkpoint.py:*) Bash(git rev-parse:*)
  Bash(git tag -l:*) Bash(git describe:*) Bash(git log:*)
  Bash(gh release view:*) Bash(gh release list:*) Read Write
---
<!-- Write is scoped to .skills-state/release-publisher/ and the notes
     body file handed to gh release create (SDS-S-024). The mutation —
     gh release create — is deliberately absent from allowed-tools
     (SDS-S-023) and is issued as a direct, unwrapped tool call after
     the high-risk gate (SDS-S-051). Re-running after a successful
     publish resolves to already-published and changes nothing, hence
     idempotent: "true" (SDS-C-004). -->

# release-publisher

## When to use

- Cutting a release: the changelog is written, the notes are
  prepared, CI is green on the commit to tag.
- Asked to publish, tag, or ship a version.
- A draft release exists and should be finalized.

## When not to use

- Writing the notes — that is `changelog-writer` then
  `release-notes-writer`; this skill publishes what they produced
  and refuses notes with withheld commits.
- Deciding whether CI is green — that is `ci-status-gate`; hand its
  decision-doc here.
- Publishing a package to a registry (npm, PyPI, crates.io) — a
  separate irreversible action with its own skill; this one stops at
  the GitHub release.
- Deleting or rewriting a published release — never; a mistaken
  release gets a follow-up release, not a rewrite.

## @requires

- REQUIRED: the repository directory, on the commit to release, with
  `gh` authenticated.
- REQUIRED: `version` — the tag to publish (`vMAJOR.MINOR.PATCH`,
  optionally with a prerelease suffix).
- REQUIRED: the release notes as the status-report
  `release-notes-writer` produced for this version.
- OPTIONAL: the decision-doc `ci-status-gate` produced for the
  commit (default: not consulted, and the gate says so).
- OPTIONAL: `prerelease` — mark the release as a prerelease
  (default: true when the tag carries a prerelease suffix, else
  false).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a
directory, the version is semver, the notes file is a status-report.
Then assess — the mechanical part (SDS-S-060):

```
python3 scripts/assess_release_readiness.py <repo> --version <tag> --notes-file <notes.json> [--ci-decision-file <ci.json>]
```

Live mode reads `gh release view <tag>`, the tag ref, and `HEAD`
(rung 3); offline, `--release-json-file <path> --as-of <ISO>`
replaces them (SDS-S-064, SDS-S-065). If a resumed run's checkpoint
exists (`checkpoint.py release-publisher <tag> --show`), read it
first: a `pending` publish step means the release may already exist
— the assessment's `already-published` is the check-before-act.

### Analyze

The rule table decides; this stage adds what it cannot see
(SDS-S-061). `already-published` on a tag whose SHA is not `HEAD`
means someone released a different commit under this version — say
so loudly. `hold-for-review` lists commits the notes withheld; read
them and decide with the driver whether each is user-facing. A tag
that already exists but has no release is normal (tagged in CI);
the release will attach to it, and the assessment's `facts.tagSha`
must equal the commit the driver means. Decide `prerelease` from the
suffix unless told otherwise.

### Decide

Write the assessment to `.skills-state/release-publisher/<tag>.json`
and the notes body (`facts.body`) to
`.skills-state/release-publisher/<tag>-notes.md`.

**If `chosenOption` is anything other than `publish` or
`finalize-draft`: stop here** — report the option and its
justification; no gate, no mutation.

### Confirm

Only reached when the assessment says `publish` or `finalize-draft`.
Use the high-risk gate (`kit/shared/gates/high.md`):

> I'm about to publish GitHub release `<tag>` for `<repo>` at commit
> `<head>`[, creating the tag]. This cannot be undone: every watcher
> is notified and the tag is public; deleting the release afterwards
> leaves both.
> - **What:** `gh release create <tag> --title <tag> --notes-file <body> [--prerelease]`
> - **Why:** the assessment at `.skills-state/release-publisher/<tag>.json`
>   (notes complete and reviewed; CI: <passed | no check runs on this commit | not consulted>)
> - **Compensating action if this turns out wrong:** none that
>   un-sends it — a follow-up release `<tag>+1` with corrected notes,
>   and `gh release delete` only for a release nobody could have seen.
>
> This needs your explicit go-ahead. Proceed?

A declined gate ends the run with `publish-declined` and nothing
created.

### Act

Only reached when the assessment says `publish` or `finalize-draft`.
Re-run the assessment immediately before acting (its `confirmation`
field requires it); continue only if the option is unchanged.
Pending record, then the direct call — all three from the skill
directory, addressing the repository with `-R` rather than by
changing directory (the live run of 2026-09-06 lost its `completed`
record to a `cd` between the calls):

```
python3 scripts/checkpoint.py release-publisher <tag> --step publish --status pending \
  --compensating-action "none — this step must be last"
gh release create <tag> -R <owner/repo> --title <tag> --notes-file <family-root>/.skills-state/release-publisher/<tag>-notes.md [--prerelease] [--target <head>]
gh release view <tag> -R <owner/repo> --json url,tagName,targetCommitish,isPrerelease > <family-root>/.skills-state/release-publisher/<tag>-post.json
python3 scripts/checkpoint.py release-publisher <tag> --step publish --status completed --post-state-file <family-root>/.skills-state/release-publisher/<tag>-post.json
```

Save the `gh release view` response to a file and pass it with
`--post-state-file <path>` on the `--status completed` call — the
`completed` record needs the release's actual URL and commit, not
just the fact that the call returned zero, and re-typing that JSON
inline invites the same drift a `cd` once caused here (SDS-S-053).

For `finalize-draft` the call is `gh release edit <tag> -R <owner/repo>
--draft=false` under the same record. A `gh release create` failure after the
`pending` record leaves the release possibly created: re-run the
assessment; `already-published` means it succeeded.

**Compensating action** (SDS-S-054): none — a publish is irreversible
(rung 6), so it is sequenced last and nothing runs after it.

**Checkpoint** (SDS-S-053): the two-phase record at
`.skills-state/release-publisher/<tag>.json`, written `pending` before
the call and `completed` immediately after.

### Communicate

N/A — the release itself notifies watchers; this skill sends no
separate message.

### Persist

Return the status-report: what was published (tag, commit, URL,
prerelease flag) or why it stopped, with the checkpoint path.

## @returns

Shape: `status-report` — see `kit/shapes/status-report.schema.json`.

`summary` names the tag, commit, and URL when published, or the
stopping option; sections `assess`, `confirm`, `publish` each say
what happened or was skipped; `generatedFrom` names the notes file,
the CI decision if any, and the checkpoint. On the stop-early path
nothing was created and the report says so.

## @throws

- `repo-invalid`: the path is not a directory.
- `version-invalid`: the version is not semver.
- `notes-unparseable`: the notes file is not a status-report.
- `ci-decision-unparseable`: the CI decision file is not a
  decision-doc.
- `release-state-unparseable`: the release facts file does not parse.
- `as-of-invalid`: `--as-of` is missing with a fixture or does not
  parse.
- `gh-unreachable`: a live `gh` or `git` call failed.
- `publish-declined`: the high-risk gate was declined; nothing was
  created.

## @example

**Input:** `v1.4.0`, notes with six sections and nothing withheld,
CI decision `pass`, no release or tag yet.

**Output (excerpt of the assessment the gate shows):**

```json
{
  "decisionOutcome": { "chosenOption": "publish", "justification": "no release for v1.4.0 exists, the notes are complete and name 1.4.0, and CI passed" },
  "decisionDrivers": ["tag v1.4.0: will be created at HEAD 3f9c2a1", "release: none", "notes: 6 section(s), 0 withheld commit(s), summary 'shop 1.4.0: 1 breaking changes, 1 security, 1 added, 1 changed, 1 fixed, 1 deprecated'", "ci-status-gate: pass — all 3 required check(s) concluded successfully"],
  "facts": { "tag": "v1.4.0", "tagExists": false, "head": "3f9c2a1", "ciConsulted": true, "body": "## Breaking changes\n\n- drop Python 3.8 support\n..." }
}
```
