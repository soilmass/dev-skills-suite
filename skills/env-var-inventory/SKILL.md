---
name: env-var-inventory
description: >-
  Inventories every environment variable a repository's code reads —
  Python `os.environ`/`os.getenv`, JavaScript and TypeScript
  `process.env` — and compares it with what `.env.example` documents,
  reporting variables read but undocumented, documented but never
  read, secrets read with a literal fallback, and required variables
  whose example line is blank, as a finding-list with the full
  inventory attached. Use when onboarding fails on a missing variable,
  before adding a deploy environment, or when asked what
  configuration a service needs.
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
  Bash(python3 scripts/inventory_env_vars.py:*) Read
---

# env-var-inventory

## When to use

- A newcomer's first run failed on a variable nobody had written
  down.
- A new deploy environment, container, or CI job needs the complete
  variable list.
- Asked what configuration a service needs, or whether
  `.env.example` is current.

## When not to use

- Secrets committed in the tree — a secret scanner; this skill
  reports a *fallback* credential in code, not leaked values.
- Auditing the dev container itself — that is `devcontainer-audit`.
- Writing the onboarding guide — `onboarding-doc-generator`, which
  can take this inventory as the "access and configuration" facts.
- Other languages, for now.

## @requires

- REQUIRED: the repository directory.
- OPTIONAL: `example` — the documented-variables file (default: the
  first of `.env.example`, `.env.sample`, `.env.template`,
  `.env.dist` at the root; none means every read is undocumented).
- OPTIONAL: `exclude` — directories to skip beyond the usual vendored
  and build directories (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then inventory — the mechanical part (SDS-S-060):

```
python3 scripts/inventory_env_vars.py <repo> [--example <file>] [--exclude dir,dir]
```

It finds every read by shape (rung 1; nothing is run, no environment
is inspected), parses the example file, and reports
`env/undocumented`, `env/unused`, `env/secret-with-default`, and
`env/required-no-example`. The run's `tool.properties.variables`
carries the inventory — each variable's read count, files, whether it
has a default, whether every read requires it, and whether it is
documented. A Python file that does not parse stops the scan
(`source-unparseable`).

### Analyze

The inventory is complete; this stage decides what each variable
*is* (SDS-S-061). An undocumented variable read without a default is
a hard requirement — the example must gain it, with a sample value
or "from the vault". One read with a default is a local override —
document it with its default. A documented-but-unused variable is
either stale (remove it) or read by something outside the tree (a
Docker entrypoint, a CI step) — say which if the tree shows it. A
secret with a literal default is a defect whatever the value; the
fix is to require it and let the process fail loudly. Group the
result into the sets a deploy environment needs: required, optional
with default, secret.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[document: required, from <source>]`, `[document:
optional, default <value>]`, `[remove from example]`, `[keep: read by
<tool>]`, `[require it; drop the literal default]`, `[add sample
value]`.

### Synthesize

Return the finding-list, warnings first, followed by the inventory as
three lists — required, optional with defaults, secrets — ready to
paste into the example file or an onboarding guide. A tree whose
reads and example agree yields a well-formed finding-list with an
empty `results` array (SDS-C-033) and the inventory.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per discrepancy, located at the first read (or the
example line), with `properties.variable`;
`runs[0].tool.properties.variables` is the full inventory and
`documented` the example's keys. Nothing was run and no environment
value was read.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a Python file does not parse.
- `example-unreadable`: the example file given cannot be read.

## @example

**Input:** a service reading `DATABASE_URL` (required), `LOG_LEVEL`
(default `info`), and `STRIPE_API_KEY` with a literal fallback, whose
`.env.example` lists `DATABASE_URL=` and a stale `REDIS_URL`.

**Output (excerpt):**

```json
{
  "ruleId": "env/secret-with-default",
  "level": "warning",
  "message": { "text": "[require it; drop the literal default] STRIPE_API_KEY looks like a secret and is read with a literal default 'sk_test_123'; a fallback credential ships in the code" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "app/payments.py" }, "region": { "startLine": 9 } } }],
  "properties": { "variable": "STRIPE_API_KEY", "default": "sk_test_123" }
}
```
