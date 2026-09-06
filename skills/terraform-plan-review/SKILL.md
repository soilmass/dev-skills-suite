---
name: terraform-plan-review
description: >-
  Reviews a Terraform or OpenTofu plan — the JSON from `terraform show
  -json` — for the changes that lose data, expose resources, or
  weaken protection: destroys, replacements of stateful resources
  (databases, buckets, volumes, queues), rules opening 0.0.0.0/0,
  public access on storage or databases, encryption switched off,
  deletion protection off, and plans too large to apply in one go —
  as a finding-list, leaving the call on whether a destroy is a
  decommission or a mistake to a human. Use before `terraform apply`,
  in a plan-review step of CI, or when asked whether a plan is safe.
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
  Bash(python3 scripts/review_plan.py:*) Read
---

# terraform-plan-review

## When to use

- Before applying a plan, especially one produced by an automated
  pipeline.
- A CI job posts the plan and a human has to decide.
- Asked whether a plan is safe, or what it destroys.

## When not to use

- Producing the plan — run `terraform plan -out=plan.tfplan &&
  terraform show -json plan.tfplan > plan.json` first; this skill
  reads the JSON and contacts no provider.
- Applying it — never; a plan review that could apply is the wrong
  tool.
- Linting the HCL itself (naming, modules) — a linter; this skill
  judges the *change*, not the source.

## @requires

- REQUIRED: the plan as JSON (`terraform show -json <planfile>`).
- OPTIONAL: `stateful` — the resource types that hold data (default:
  `assets/stateful-types.json`, the common AWS, GCP, and Azure
  types).
- OPTIONAL: `large` — the change count above which the plan is
  flagged for slicing (default: 25).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the file is plan JSON
with `resource_changes`. Then review — the mechanical part
(SDS-S-060):

```
python3 scripts/review_plan.py <plan.json> [--stateful <types.json>] [--large N]
```

It classifies every resource change and reports `tf/destroy`,
`tf/replace-stateful`, `tf/replace`, `tf/public-exposure`,
`tf/encryption-off`, `tf/deletion-protection-off`, and
`tf/large-update`. `tool.properties.counts` carries the create /
update / delete / replace / no-op tally.

### Analyze

The review says what the plan does; this stage says whether it
should (SDS-S-061). A destroy of a stateful resource is either a
decommission with a verified backup or an accident — ask which, and
name the backup. A replacement of a database is a data loss unless
the provider snapshots on delete (`skip_final_snapshot` false,
`deletion_protection`) — check `before` for those flags and say what
would be kept. A replacement of a stateless resource is downtime;
say for whom. An ingress from the world on port 22 or 3306 is a
defect; on 443 of a load balancer it is the point — read the type.
Encryption switched off is a defect in any environment. A large
plan is safer in slices ordered by dependency; propose the slices.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the verdict — `[block: verify backup first]`, `[block: data
loss, use create_before_destroy + snapshot]`, `[accept: decommission
<ticket>]`, `[downtime for <users>: schedule]`, `[intended: public
endpoint]`, `[block: restrict to <cidr>]`, `[apply in slices: …]`.

### Synthesize

Return the finding-list, errors first, with the tally and one line:
safe to apply / apply after the named checks / do not apply. A plan
of creates and safe updates yields a well-formed finding-list with
an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per risky change, located at the plan file, with the
resource address, type, actions, and the exposure or encryption
detail in `properties`; `runs[0].tool.properties` carries the
versions, the tally, and the destructive count. Nothing was applied
and no provider was contacted.

## @throws

- `plan-unparseable`: the file cannot be read or is not JSON.
- `plan-invalid`: the JSON has no `resource_changes` array.
- `stateful-invalid`: the stateful list is not `{statefulTypes:
  [...]}`, or `large` is not an integer.

## @example

**Input:** a plan that replaces `aws_db_instance.orders` because its
`engine_version` changed.

**Output (excerpt):**

```json
{
  "ruleId": "tf/replace-stateful",
  "level": "error",
  "message": { "text": "[block: data loss, snapshot then create_before_destroy] aws_db_instance.orders (aws_db_instance) will be replaced; a replace destroys the data it holds" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "plan.json" } } }],
  "properties": { "address": "aws_db_instance.orders", "type": "aws_db_instance", "actions": ["delete", "create"], "stateful": true }
}
```
