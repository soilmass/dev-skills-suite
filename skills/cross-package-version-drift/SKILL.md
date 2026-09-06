---
name: cross-package-version-drift
description: >-
  Finds the dependencies a monorepo's packages disagree about — one
  external library required at two or more different ranges across
  workspace members, a sibling package depended on at a range its
  current version does not satisfy so the build resolves a published
  copy instead, and siblings referenced by workspace protocol in some
  members but pinned by range in others — as a finding-list with the
  full range inventory attached. Use when a monorepo ships two copies
  of one library, when a sibling change does not show up in a
  dependent, or when asked to align versions across packages.
license: Apache-2.0
compatibility: Requires Python 3.11+ or the `tomli` package for
  Cargo workspaces (npm and pnpm need nothing).
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/find_version_drift.py:*) Read
---

# cross-package-version-drift

## When to use

- The bundle or lockfile carries two copies of one library.
- A change in a sibling package does not appear in the package that
  depends on it (it resolved a published copy).
- Asked to align, dedupe, or standardise dependency versions across
  a monorepo.

## When not to use

- Which packages a change affects — that is
  `affected-packages-finder`.
- Vulnerable versions — that is `dependency-audit`; this skill
  compares ranges to each other, not to advisories.
- Applying the alignment — a dependency bump with its own review;
  this skill produces the target ranges, not the diff.

## @requires

- REQUIRED: the monorepo root directory (with `package.json`
  workspaces, `pnpm-workspace.yaml`, or a Cargo `[workspace]`).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then scan — the mechanical part (SDS-S-060):

```
python3 scripts/find_version_drift.py <repo>
```

It discovers the members and their manifests (rung 1; no registry is
contacted), collects every dependency range per member, and reports
`drift/version-mismatch` (one external library, several ranges),
`drift/internal-mismatch` (a sibling required at a range its version
does not satisfy), and `drift/internal-unpinned` (mixed workspace
reference and range for one sibling). `tool.properties.external`
carries every external dependency's ranges and users.

### Analyze

The scan says who disagrees; this stage picks the winner
(SDS-S-061). For an external mismatch the target is usually the
newest range that every user's code supports — check the changelog
between the ranges (`upgrade-risk-assessor` rates it) before choosing
the newest blindly; when the root manifest or a catalog (pnpm
`catalog:`, Cargo `[workspace.dependencies]`) already pins one, that
is the target and the finding is "use the catalog". An internal
mismatch is a build defect: the dependent tests against a published
copy while the sibling changes — the fix is the workspace protocol
or a range that admits the sibling's version. Mixed strategies for
one sibling become one strategy; workspace references win inside a
monorepo.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[align to <range>: <why>]`, `[use catalog entry]`,
`[use workspace:* ]`, `[bump range to admit <version>]`, `[keep:
intentional split, <why>]`.

### Synthesize

Return the finding-list, errors first, followed by the alignment
table: dependency, target range, the members that change. A
consistent workspace yields a well-formed finding-list with an empty
`results` array (SDS-C-033) and the inventory.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per disagreement, located at the manifest that carries
it, with the dependency, the ranges and their users, or the
sibling's version in `properties`; `runs[0].tool.properties`
carries the member versions and the external inventory. No registry
was contacted and nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `workspace-not-found`: no recognised workspace manifest.
- `manifest-malformed`: a member manifest does not parse.

## @example

**Input:** a pnpm workspace where `ui` and `app` require `react` at
`^18.2.0` and `tools` at `^17.0.2`, and `app` requires the sibling
`@shop/ui` at `^0.9.0` while `ui` is at `1.0.0`.

**Output (excerpt):**

```json
{
  "ruleId": "drift/internal-mismatch",
  "level": "error",
  "message": { "text": "[use workspace:*] @shop/app requires sibling @shop/ui at '^0.9.0' but the workspace copy is 1.0.0; the build resolves a published copy, not the sibling" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "apps/app/package.json" } } }],
  "properties": { "package": "@shop/app", "dependency": "@shop/ui", "range": "^0.9.0", "siblingVersion": "1.0.0" }
}
```
