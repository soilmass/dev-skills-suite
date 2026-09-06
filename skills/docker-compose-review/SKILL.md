---
name: docker-compose-review
description: >-
  Reviews a Docker Compose file, service by service, for the
  definitions that bite in production or leak in development —
  unpinned images, no healthcheck, depends_on without a readiness
  condition, privileged or host-namespace services, secret literals
  in environment, root or Docker-socket bind mounts, ports published
  on every interface, no resource limits, no restart policy — as a
  finding-list judged under a dev or prod profile, leaving the call on
  what this file is for to a human. Use before a compose file goes to
  a shared host, when a container escaped or starved the box, or when
  asked to review docker-compose.
license: Apache-2.0
compatibility: Requires PyYAML.
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/review_compose.py:*) Read
---

# docker-compose-review

## When to use

- A compose file is about to run on a shared or internet-facing
  host.
- A container escaped, exhausted the host, or came up before its
  database and failed.
- Asked to review a `docker-compose.yml` or `compose.yaml`.

## When not to use

- The Dockerfiles the services build — that is `devcontainer-audit`
  for the dev container, or the same rules applied by hand to a
  production Dockerfile.
- Kubernetes manifests — a different spec with different rules.
- Running the stack — never; this skill reads one file and contacts
  no engine.

## @requires

- REQUIRED: the compose file.
- OPTIONAL: `profile` — `dev` or `prod`; prod raises host-port
  exposure to a warning and adds the restart-policy check (default:
  `dev`).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the file parses and
has a `services` mapping. Then review — the mechanical part
(SDS-S-060):

```
python3 scripts/review_compose.py <compose.yml> [--profile dev|prod]
```

It reports, per service, `compose/unpinned-image`,
`compose/no-healthcheck`, `compose/depends-on-no-condition`,
`compose/privileged`, `compose/host-network`,
`compose/secret-literal`, `compose/root-bind-mount`,
`compose/port-all-interfaces`, `compose/no-resource-limits`, and,
under prod, `compose/no-restart-policy`. `tool.properties` carries
the profile and the service names.

### Analyze

The review flags patterns; this stage weighs them for this file
(SDS-S-061). A dev compose exists to publish ports and mount source
— its host ports are the point, and a `latest` image of a local
database may be fine; say so and keep the secret and privilege
findings, which are wrong in any profile. A prod compose with no
healthchecks will race its own dependencies on every restart — the
healthcheck plus `condition: service_healthy` pair is the first
change. A Docker-socket mount is root on the host whatever the
profile; if the service is a CI runner that needs it, say so and
name the isolation that replaces it. Resource limits matter when
more than one service shares the host — check the file, not the
rule.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[pin: <image>:<tag>]`, `[add healthcheck: <cmd>]`,
`[condition: service_healthy]`, `[drop privileged; cap_add only
<caps>]`, `[use ${VAR} / secrets:]`, `[bind 127.0.0.1]`, `[keep: dev
profile]`, `[limits: memory 512m, cpus 1]`, `[restart:
unless-stopped]`.

### Synthesize

Return the finding-list, warnings first, grouped by service, with the
profile stated and the single change that most reduces risk first. A
well-formed file yields a well-formed finding-list with an empty
`results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per service per pattern, located at the compose file,
with the service and the image, key, port, or mount source in
`properties`; `runs[0].tool.properties` carries the profile and
services. Nothing was run and nothing was modified.

## @throws

- `compose-unparseable`: the file cannot be read or is not valid
  YAML.
- `compose-invalid`: the file has no `services` mapping.
- `profile-invalid`: `profile` is neither `dev` nor `prod`.

## @example

**Input:** a `web` service with `image: nginx`, `privileged: true`,
and `DB_PASSWORD: hunter2` in `environment`.

**Output (excerpt):**

```json
{
  "ruleId": "compose/secret-literal",
  "level": "warning",
  "message": { "text": "[use ${DB_PASSWORD} / secrets:] web: environment DB_PASSWORD carries a literal value; use ${DB_PASSWORD} from the environment or a Compose secret" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "docker-compose.yml" } } }],
  "properties": { "service": "web", "key": "DB_PASSWORD" }
}
```
