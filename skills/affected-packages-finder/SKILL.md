---
name: affected-packages-finder
description: >-
  Maps a set of changed files in a monorepo — npm, yarn, pnpm, or
  Cargo workspaces — to the packages they affect: the ones changed
  directly, the ones that depend on those through the internal
  dependency graph (with the chain), every package when a root
  manifest or lockfile changed, and the changed files no package
  owns — as a finding-list carrying the affected set in build order
  for CI to consume. Use when deciding what to build, test, or
  release for a change, when a monorepo CI runs everything, or when
  asked what a change touches.
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
  Bash(python3 scripts/find_affected.py:*) Bash(git diff:*) Read
---

# affected-packages-finder

## When to use

- Deciding what to build, test, or release for a pull request in a
  monorepo.
- CI runs every package on every change and takes too long.
- Asked what a change touches, or whether package B needs a release
  because package A changed.

## When not to use

- Version drift across packages — that is
  `cross-package-version-drift`.
- Single-package repositories — everything is affected; nothing to
  map.
- Computing the diff — run `git diff --name-only <base>...<head>`
  first and pass the list; this skill reads manifests and a file
  list, and runs no git command inside its script.

## @requires

- REQUIRED: the monorepo root directory (with `package.json`
  workspaces, `pnpm-workspace.yaml`, or a Cargo `[workspace]`).
- REQUIRED: `changed-files` — a file listing the changed paths, one
  per line, repository-relative, as `git diff --name-only` prints
  them.

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a
directory and the change list is readable. Then map — the
mechanical part (SDS-S-060):

```
git diff --name-only <base>...<head> > <changes.txt>
python3 scripts/find_affected.py <repo> --changed-files <changes.txt>
```

It discovers the workspace members and their internal dependency
edges from the manifests (rung 1; nothing is built), assigns each
changed file to its package, walks the dependents, and reports
`affected/direct`, `affected/dependent` (with the chain),
`affected/root-change`, and `affected/unowned-file`.
`tool.properties.buildOrder` lists the affected packages after
their dependencies — what a CI filter needs.

### Analyze

The map is exact for manifest-declared dependencies; this stage
covers what manifests do not say (SDS-S-061). An unowned change to
a shared config (`tsconfig.base.json`, an ESLint config, a CI
workflow) affects whoever consumes it — say which packages, or
"all" for CI. A change to a package's tests affects only that
package, not its dependents — downgrade the dependents if every
changed file in the direct package is a test. A change to a
package's public surface (`public-api-change-check` can say)
affects dependents at build *and* runtime; a private change affects
them at build only, which matters for what to release. A root
lockfile change with no manifest change is usually a dependency
bump — everything rebuilds, nothing necessarily releases.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[build and test]`, `[build, test, release]`,
`[tests only: skip dependents]`, `[shared config: affects <pkgs>]`,
`[no effect: docs]`.

### Synthesize

Return the finding-list with the build order first, then one line
per affected package saying build / test / release, then the
unowned files with their verdicts. An empty change list yields a
well-formed finding-list with an empty `results` array and an empty
build order (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per affected package or unowned file, located at the
package directory or the file, with the package, the changed files,
or the dependency chain in `properties`; `runs[0].tool.properties`
carries the members, their internal edges, and `buildOrder`.
Nothing was built and nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `workspace-not-found`: no recognised workspace manifest.
- `changes-unreadable`: the change list cannot be read.
- `manifest-malformed`: a member manifest does not parse.

## @example

**Input:** changes in `packages/core/src/index.ts`, where `ui`
depends on `core` and `app` on `ui`.

**Output (excerpt):**

```json
{
  "ruleId": "affected/dependent",
  "level": "warning",
  "message": { "text": "[build, test, release] @shop/app depends on changed package(s) via @shop/core -> @shop/ui -> @shop/app" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "apps/app" } } }],
  "properties": { "package": "@shop/app", "via": ["@shop/core", "@shop/ui", "@shop/app"] }
}
```
