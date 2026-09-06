---
name: devcontainer-audit
description: >-
  Audits a repository's dev container — the Dev Container definition
  and the Dockerfile it builds — for the choices that make it slow,
  irreproducible, or unsafe: unpinned base images and features,
  everything running as root, the whole tree copied before the
  dependency install so every edit rebuilds it, secrets in build
  arguments, apt caches left in layers, and no post-create step — as
  a finding-list, leaving the call on what this team can live with to
  a human. Use when the container is slow to rebuild, when newcomers
  hit root-owned files, or when asked to review a Dockerfile or dev
  container.
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
  Bash(python3 scripts/audit_devcontainer.py:*) Read
---

# devcontainer-audit

## When to use

- Rebuilding the dev container takes minutes after every edit.
- Newcomers hit files owned by root, or an environment that differs
  from a colleague's.
- Asked to review a Dockerfile or a `.devcontainer` definition.

## When not to use

- The variables the container needs — that is `env-var-inventory`.
- Production images — the same Dockerfile rules apply, but the
  container/root-user and no-post-create judgments are about a
  *development* container; say so if pointed at a production
  Dockerfile.
- Building or running the container — never; this skill reads two
  files and pulls nothing.

## @requires

- REQUIRED: the repository directory; the definition is found per
  the Dev Container spec (`.devcontainer/devcontainer.json`,
  `.devcontainer.json`, or `.devcontainer/<name>/devcontainer.json`)
  and the Dockerfile via its `build.dockerfile`.

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then audit — the mechanical part (SDS-S-060):

```
python3 scripts/audit_devcontainer.py <repo>
```

It parses the definition as JSONC, follows `build.dockerfile`, and
reports `container/unpinned-image`, `container/root-user`,
`container/copy-before-install`, `container/secret-in-build`,
`container/apt-no-cleanup`, `container/no-post-create`, and, with no
definition at all, `container/no-definition`. A definition that is
not valid JSONC stops the audit (`definition-unparseable`).

### Analyze

The audit flags patterns; this stage weighs them for this team
(SDS-S-061). An unpinned *internal* base image whose own Dockerfile
pins upstream is a policy choice — say where the pin lives. Root in
a container nobody mounts a workspace into is harmless; root with a
bind-mounted workspace produces the root-owned files newcomers
complain about — check `workspaceMount`. Copy-before-install is the
usual cause of slow rebuilds: name the manifest files (`package.json`
and lockfile, `pyproject.toml` and lockfile) that should be copied
first. A secret in a build argument is a defect regardless of value.
A missing post-create step is fine when the image already contains
the dependencies — check whether the Dockerfile installs them.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[pin: <image>@sha256:…]`, `[keep: pinned in
<internal image>]`, `[add remoteUser: vscode]`, `[copy manifests
first: <files>]`, `[use --mount=type=secret]`, `[add && rm -rf
/var/lib/apt/lists/*]`, `[add postCreateCommand: <install>]`, `[keep:
deps baked into the image]`.

### Synthesize

Return the finding-list, warnings first, with one paragraph on the
rebuild-time and reproducibility consequences and the single change
most worth making first. A well-formed definition yields a
well-formed finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per pattern, located at the definition or the Dockerfile
line, with the image, feature, instruction, or line involved in
`properties`; `runs[0].tool.properties.definition` names the
definition audited. Nothing was built, pulled, or modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `definition-unparseable`: the definition is not valid JSONC.

## @example

**Input:** a definition building `.devcontainer/Dockerfile` that
starts `FROM python` and runs `COPY . .` before `pip install -e .`.

**Output (excerpt):**

```json
{
  "ruleId": "container/copy-before-install",
  "level": "warning",
  "message": { "text": "[copy manifests first: pyproject.toml, uv.lock] the whole tree was copied at line 4 before this dependency install; every source edit rebuilds the dependency layer — copy the manifest first, install, then copy the rest" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": ".devcontainer/Dockerfile" }, "region": { "startLine": 5 } } }],
  "properties": { "copyLine": 4 }
}
```
