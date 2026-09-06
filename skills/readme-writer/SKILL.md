---
name: readme-writer
description: >-
  Writes or rewrites a repository's README in Standard Readme order —
  name, one-sentence tagline, install, usage, development, license —
  where every command shown is one the repository's manifests
  actually declare, checked against the facts repository-orientation
  collected, and refusing to render a command the tree lacks. Use
  when a repository has no README, when the README's commands have
  drifted from the Makefile or package.json, or when asked to write
  or refresh one.
license: Apache-2.0
compatibility: Requires the Python `jsonschema` package (the render
  script validates the specification against this skill's asset
  schema).
metadata:
  family: dev-skills-suite
  effect-tier: local-write
  idempotent: "true"
  tier: situational
  shape-out: freeform
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/render_readme.py:*) Read Write
---
<!-- Write is used only for the two-phase checkpoint under
     .skills-state/readme-writer/ and for the specification JSON handed
     to the render script (SDS-S-024). The README itself is written by
     scripts/render_readme.py, a rung-4 local write. Re-rendering an
     unchanged specification rewrites an identical file, hence
     idempotent: "true" (SDS-C-004). -->

# readme-writer

## When to use

- A repository has no README, or one that says only its name.
- The README's commands no longer match the Makefile, `package.json`,
  or `pyproject.toml`.
- Asked to write or refresh a README.

## When not to use

- Collecting what the repository declares — that is
  `repository-orientation`; run it first and hand its facts here.
- Reference documentation for an API — that is `api-doc-writer`.
- The onboarding guide (access, first task, who to ask) — that is
  `onboarding-doc-generator`; a README is for every reader, an
  onboarding guide for a new colleague.
- A changelog — that is `changelog-writer`.

## @requires

- REQUIRED: the repository directory the README is for.
- REQUIRED: the repository-orientation facts object for it
  (`python3 skills/repository-orientation/scripts/map_repository.py <repo>`
  saved to a file), so every command is checked against what the
  tree declares.
- OPTIONAL: `existing` — the current README, when one exists
  (default: read from `<repo>/README.md` if present).
- OPTIONAL: `audience` — who reads it first: users, contributors, or
  both (default: both).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the repository is a
directory and the facts file parses. Read the facts, the existing
README if any, and the top of each entry point the facts name. Do not
re-walk the tree: the facts are the record (SDS-S-065).

### Analyze

Decide what a reader needs, from the facts (SDS-S-061): the
manifest's own name and the one sentence the existing README or the
entry point's docstring says; the install command the ecosystem
implies (`pip install -e .`, `npm ci` when a lockfile exists, `npm
install` when not); the usage example the entry point's interface
suggests; the development commands the tree declares (`make test`,
`npm test`, `pytest` via `[tool.pytest]`). Keep what the existing
README says that the tree cannot (why it exists, who maintains it,
how to contribute) — that is the part worth preserving.

### Decide

Compose the specification (`assets/readme.schema.json`, this skill's
own shape, SDS-S-080): `name`, `tagline`, optional `background`,
`install`, `usage`, optional `develop`, `maintainers`, `contributing`,
`license` (an SPDX identifier where one applies). Every command is a
structured entry — the script checks each `make` target and npm
script against the facts. Write it under
`.skills-state/readme-writer/`. Preview:

```
python3 scripts/render_readme.py <readme.json> --out-dir <repo> --facts-file <facts.json> --dry-run
```

The script refuses a command the tree does not declare
(`command-undeclared`) and warns when the facts show tests, CI, or a
missing LICENSE file that the specification ignores.

**If the existing README already equals the dry-run output: stop
here** — there is nothing to write, say so.

### Confirm

Only reached when the rendered README differs from the existing one.
Rung 4 needs no gate (SDS-S-031); show the dry run, its warnings, and
— when replacing — a summary of what the old README said that the
new one drops. A dropped paragraph is the usual mistake.

### Act

Only reached when the rendered README differs from the existing one.
Write the `pending` checkpoint (single mutating step — inline via the
Write tool, SDS-S-055) to `.skills-state/readme-writer/<repo-name>.json`,
with `preState` = whether a README existed and its byte length, then:

```
python3 scripts/render_readme.py <readme.json> --out-dir <repo> --facts-file <facts.json>
```

Check-before-act (SDS-C-046): if `<repo>/README.md` now equals the
dry-run output (a resumed run), skip the write. On success update the
checkpoint to `completed` with `postState` = the written path and
section list.

**Compensating action** (SDS-S-054): restore the previous README from
version control (`git checkout -- README.md`) if one was replaced, or
delete the new file if none existed.

**Checkpoint** (SDS-S-053): the pending-then-completed record at
`.skills-state/readme-writer/<repo-name>.json`.

### Communicate

N/A — the README reaches its readers through the repository; this
skill sends no message.

### Persist

The rendered `<repo>/README.md` is the durable artifact. Return its
path, its section list, and the remaining warnings.

## @returns

Shape: `freeform` (a markdown README).

Name, tagline, install, usage, development, and license in Standard
Readme order, plus whatever background, maintainers, and contributing
text the previous README supplied; every command shown is declared
by the tree. Exactly one file was written — or none, when the
existing README already matched, which the result says.

## @throws

- `readme-unparseable`: the specification is unreadable or not JSON.
- `readme-invalid`: the specification fails `assets/readme.schema.json`.
- `command-undeclared`: a `make` target or npm script in the
  specification is not declared by the repository's manifests.
- `facts-unparseable`: the facts file is unreadable or not JSON.
- `out-dir-missing`: the repository directory does not exist.

## @example

**Input:** facts for a Python service with a `Makefile` declaring
`test` and `lint`, `[tool.pytest]`, no lockfile, an existing README
of one line.

**Output (excerpt):**

```markdown
# shop

The order-pricing service behind the checkout API.

## Install

Editable install into the current environment (no lockfile is committed, so pin your own):

```sh
pip install -e .
```

## Development

Run the tests:

```sh
make test
```
```
