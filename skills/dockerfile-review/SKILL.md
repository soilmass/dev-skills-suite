---
name: dockerfile-review
description: >-
  Reviews a Dockerfile, stage by stage, for the build-time and runtime
  choices that make an image bigger, slower to rebuild, or less safe
  than it needs to be — an unpinned or `:latest` base image, no digest
  pin, the final stage running as root, an `apt-get install` with no
  cache cleanup, a secret in a build argument or environment variable,
  `ADD` used where `COPY` would do, no `HEALTHCHECK` for an exposed
  port, a build command with no multi-stage split, and the whole build
  context copied before the dependency-install layer — as a
  finding-list. Use before an image build goes to a shared registry,
  when a rebuild is slower than it should be, or when asked to review
  a Dockerfile.
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
  Bash(python3 scripts/review_dockerfile.py:*) Read
---

# dockerfile-review

## When to use

- A Dockerfile is about to be built and pushed to a shared registry.
- A rebuild is slower than it should be, or an unrelated source edit
  reinstalls every dependency.
- Asked to review a `Dockerfile`, `Dockerfile.*`, or `*.dockerfile`.

## When not to use

- The Compose file that runs the built image — that is
  `docker-compose-review`; this skill reads the image build, not the
  service definitions around it.
- A dev container's `devcontainer.json` and the choices specific to a
  development environment — that is `devcontainer-audit`, which reads
  the same kind of Dockerfile but under a development lens (a
  post-create step, newcomer-friendly file ownership) rather than a
  production one.
- Building or running the image — never; this skill reads text files
  and contacts no engine.

## @requires

- REQUIRED: a path to a Dockerfile, or a directory containing at least
  zero Dockerfiles.
- OPTIONAL: `--allow-latest` — silence `docker/latest-tag` for a base
  image intentionally tracking a moving tag (default: not silenced).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the given path exists as
a directory or a file, or names a plain missing Dockerfile. Then
review — the mechanical part (SDS-S-060):

```
python3 scripts/review_dockerfile.py <repo|Dockerfile> [--allow-latest]
```

A directory argument is scanned for every `Dockerfile`, `Dockerfile.*`,
and `*.dockerfile` file; a file argument is parsed directly. It
reports, per stage, `docker/latest-tag`, `docker/unpinned-base`,
`docker/root-user`, `docker/apt-no-cleanup`, `docker/secret-in-arg-env`,
`docker/add-instead-of-copy`, `docker/no-healthcheck`,
`docker/multi-stage-missing`, and `docker/copy-dot-before-deps`.
`tool.properties` carries the number of files, stages, and
instructions, and a count per rule.

### Analyze

The review flags patterns; this stage weighs them for this build
(SDS-S-061). `docker/root-user` and `docker/secret-in-arg-env` are
wrong regardless of context — keep them as stated. `docker/latest-tag`
and `docker/unpinned-base` matter more for a base image everyone
builds from than for a throwaway CI image rebuilt every run; say so
if the image is disposable. `docker/multi-stage-missing` is a
suggestion, not a defect — a five-line script with no real build
toolchain does not need a second stage. If a finding's fix is not
obvious, read `references/dockerfile-rules.md` — one section per rule
with the rationale and the fix, citing Docker's own Dockerfile best
practices guide.

### Classify

Keep the script's severities and prefix each finding's `message.text`
with the action — `[pin: <tag>]`, `[digest: <image>@sha256:...]`,
`[add: USER app]`, `[cleanup: rm -rf /var/lib/apt/lists/*]`,
`[secret mount or runtime injection]`, `[use COPY]`,
`[add: HEALTHCHECK]`, `[split: build + runtime stage]`,
`[reorder: install before COPY .]`.

### Synthesize

Return the finding-list, errors first, with the file and stage each
finding belongs to. A Dockerfile with none of these patterns yields a
well-formed finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per stage-and-rule outcome that is not a clean pass,
located at the Dockerfile and the instruction's first line;
`runs[0].tool.properties` carries the file, stage, and instruction
counts and a count per rule. Nothing was built and nothing was
modified.

## @throws

- `repo-invalid`: the given path is neither an existing directory, an
  existing file, nor a plausible Dockerfile path.
- `dockerfile-missing`: an explicit path whose name matches the
  Dockerfile naming convention does not exist.
- `dockerfile-unparseable`: a non-empty instruction line's first token
  is not a recognized Dockerfile instruction.

## @example

**Input:** a single-stage `FROM node:latest` build that runs as root,
carries `ARG NPM_TOKEN`, and copies the whole build context before
`RUN npm ci`.

**Output (excerpt):**

```json
{
  "ruleId": "docker/secret-in-arg-env",
  "level": "error",
  "message": { "text": "ARG NPM_TOKEN looks like a secret; pass it as a build secret or inject it at runtime instead" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "Dockerfile" }, "region": { "startLine": 2 } } }],
  "properties": { "instruction": "ARG", "name": "NPM_TOKEN" }
}
```
