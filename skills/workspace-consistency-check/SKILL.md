---
name: workspace-consistency-check
description: >-
  Checks a monorepo's declared workspace members against its directory
  tree across npm/yarn, pnpm, Cargo, Go, and uv workspaces — a
  declared member with no manifest, a manifest under packages/, apps/,
  libs/, crates/, or services/ that no declaration covers, two
  members sharing one package name, a member depending on a sibling
  at a range the sibling's own version does not satisfy, more than
  one lockfile kind at the root, and a member with its own nested
  lockfile — as a finding-list with the member and declaration counts
  attached. Use when a monorepo grows a member nobody declared, a
  workspace dependency fails to resolve, or when asked whether the
  workspace layout still matches its manifests.
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
  Bash(python3 scripts/check_workspaces.py:*) Read
---

# workspace-consistency-check

## When to use

- A workspace member exists on disk that nothing declares, or a
  declared member has no manifest to back it.
- Two members share a package name, or one depends on a sibling at a
  range the sibling's own version isn't at.
- Asked whether a monorepo's workspace layout still matches its
  manifests, or before adding a new member.

## When not to use

- External dependency ranges disagreeing across members — that is
  `cross-package-version-drift`; this skill compares a member against
  its own siblings' versions, not third-party ranges against each
  other.
- Which packages a set of changed files affects — that is
  `affected-packages-finder`.
- Workspace kinds beyond npm/yarn, pnpm, Cargo, Go, and uv, for now.

## @requires

- REQUIRED: a repository directory.

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a directory.
Then scan — the mechanical part (SDS-S-060):

```
python3 scripts/check_workspaces.py <repo>
```

It detects the workspace kind in order — npm/yarn (`package.json`
`workspaces`), pnpm (`pnpm-workspace.yaml`), Cargo (`Cargo.toml`
`[workspace]`), Go (`go.work`), or uv (`pyproject.toml`
`[tool.uv.workspace]`) — resolves each declared entry against the
directory tree, and reports `mono/member-missing` (declared, no
manifest), `mono/orphan-package` (a manifest one level under
packages/, apps/, libs/, crates/, or services/ that nothing declares),
`mono/duplicate-name` (two members, one package name),
`mono/internal-version-mismatch` (a sibling range the sibling's own
version does not satisfy), `mono/mixed-lockfiles` (more than one
lockfile kind at the root), and `mono/nested-lockfile` (a member with
its own lockfile). No recognised workspace declaration is not a
failure: `tool.properties.kind` comes back `null` with an empty result
list (SDS-C-033). `tool.properties` also carries the resolved member
count, the declared-entry count, and the orphan count.

### Analyze

The scan is exact about what exists and what is declared; this stage
supplies the judgment call (SDS-S-061). A missing member is usually a
rename or a deletion the declaration never caught up with — check
history before assuming the directory should be restored. An orphan
is often a package mid-migration into the workspace; it only becomes
a defect once it is meant to build alongside the others. A duplicate
name is a hazard regardless of intent — whichever tool resolves the
workspace will pick one of the two arbitrarily. An internal version
mismatch means the dependent tests against a published copy while its
sibling has moved on; the fix is usually the workspace protocol, not
a version bump. Mixed lockfiles mean two package managers are both
trusted for the same tree — one has to go. A nested lockfile is often
harmless (a member published on its own) but worth confirming it
isn't shadowing the root's resolution.

### Classify

Keep the script's severities; prefix each finding's `message.text`
with what it implies for the reader — `[declare it]` or `[remove the
entry]` for an orphan or a missing member depending on which way the
drift went, `[rename one]` for a duplicate, `[use the workspace
protocol]` for an internal mismatch, `[standardise on one lockfile]`
for mixed lockfiles, `[confirm: intentional]` for a nested lockfile.

### Synthesize

Return the finding-list, errors first, with a one-line summary of the
workspace kind and member count. A workspace with nothing wrong
yields a well-formed finding-list with an empty `results` array
(SDS-C-033); a directory with no recognised workspace declaration
yields the same, with `kind` `null`.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per inconsistency, located at the root manifest for a
missing member and at the relevant member manifest or lockfile for
the rest, with the pattern, path, name, or range details in
`properties`; `runs[0].tool.properties` carries the workspace kind,
the member and declared-entry counts, the orphan count, and the root
lockfiles found. Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `manifest-unparseable`: a root or member manifest does not parse for
  its kind.

## @example

**Input:** an npm workspace declaring `["packages/*", "tools/cli"]`
where `tools/cli` has no `package.json`, `packages/a` and
`packages/c` are both named `@acme/shared`, and `packages/a` requires
the sibling `@acme/b` at `^2.0.0` while `@acme/b` is `1.4.0`.

**Output (excerpt):**

```json
{
  "ruleId": "mono/internal-version-mismatch",
  "level": "warning",
  "message": { "text": "@acme/shared depends on sibling @acme/b at '^2.0.0' but @acme/b is 1.4.0" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "packages/a/package.json" } } }],
  "properties": { "from": "@acme/shared", "to": "@acme/b", "required": "^2.0.0", "actual": "1.4.0" }
}
```
