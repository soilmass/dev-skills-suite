---
name: repository-orientation
description: >-
  Builds a newcomer's map of an unfamiliar repository — what languages
  it is written in, which manifests declare which build, test, and
  run commands, how the tree is laid out, where the entry points are,
  and which conventional signals (README, LICENSE, CI, lockfile,
  tests) are present or missing — then writes the orientation a
  reader needs in the first hour: where to start, how to run it, what
  is unusual. Use on the first day in a repository, before reviewing
  a repository you have never opened, or when asked "how is this
  organised".
license: Apache-2.0
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: freeform
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/map_repository.py:*) Read
---

# repository-orientation

## When to use

- The first day in a repository, before touching anything.
- Before reviewing a repository you have never opened.
- Asked how a repository is organised, how to run it, or where to
  start reading.

## When not to use

- Writing the README — that is `readme-writer`, which consumes this
  skill's facts and produces the page.
- Writing the onboarding guide — that is `onboarding-doc-generator`,
  which adds the human procedure (access, first task, who to ask)
  the tree cannot show.
- Judging quality — `tech-debt-inventory`, `dead-code-finder`, and
  `ci-pipeline-audit` do that; this skill describes, it does not
  grade.

## @requires

- REQUIRED: a repository directory.
- OPTIONAL: `exclude` — directories to skip beyond the usual vendored
  and build directories (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a directory.
Then collect the facts — the mechanical part (SDS-S-060):

```
python3 scripts/map_repository.py <repo> [--exclude dir,dir]
```

It walks the tree (rung 1; nothing is run) and prints one JSON
object in this skill's own facts shape
(`assets/orientation.schema.json`, SDS-S-080): languages by file
count, manifests with the commands they declare (`package.json`
scripts, `pyproject` project scripts and tool sections, Makefile
targets, Cargo and Go module names), top-level layout with the
conventional directories flagged, entry points, and presence
signals. A manifest that does not parse stops the scan
(`manifest-malformed`). Then read the README if one exists, and the
top of each entry point — those are the parts a map cannot
summarise.

### Analyze

Facts are not orientation; this stage turns them into one
(SDS-S-061). Decide the *primary* language and ecosystem (the
manifest, not the file count, when they disagree — a Python service
with a large `docs/` is still Python). Pick the three commands a
newcomer runs first — install, test, run — from the declared ones,
preferring the manifest's own names (`npm test`, `make test`,
`pytest` via `[tool.pytest]`) over guesses, and say plainly when
none is declared. Identify the reading order: entry point first,
then the directory the entry point imports most from. Name what is
unusual — no tests, no CI, a lockfile missing where the ecosystem
expects one, a `src/` beside a top-level package — because the
unusual is what a newcomer trips on.

### Synthesize

Write the orientation, in this order and no longer than a screen:
one line on what the repository is (from the README or the manifest
name); primary language and ecosystem; the install / test / run
commands as they are declared, or "none declared"; the layout as a
short annotated list of top-level directories; where to start
reading; and what is unusual or missing. An empty repository yields
a valid orientation that says so (SDS-C-033).

## @returns

Shape: `freeform` (a markdown orientation page, one screen).

Every command shown is one the tree declares; every directory named
exists; the facts object it was built from validates against
`assets/orientation.schema.json` and is available to downstream
writers. Nothing was run and nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `manifest-malformed`: `package.json`, `pyproject.toml`, or
  `Cargo.toml` does not parse.

## @example

**Input:** a repository with `pyproject.toml` declaring a
`shop` console script and `[tool.pytest]`, a `Makefile` with
`test` and `lint` targets, `src/shop/main.py`, `tests/`, CI, but no
lockfile.

**Output (excerpt):**

```markdown
# Orientation: shop

**What:** the order-pricing service (pyproject name `shop`).
**Language:** Python (pyproject; 14 files), with a small JavaScript admin page.

**Run first**
- install: `pip install -e .` (pyproject; no lockfile committed)
- test: `make test` (Makefile target; pytest is configured in pyproject)
- run: `shop` (console script → `src/shop/main.py`)

**Start reading** at `src/shop/main.py`, then `src/shop/pricing/`.
**Unusual:** no lockfile, so installs are not reproducible; `docs/` is empty.
```
