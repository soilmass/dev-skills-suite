# A Portable Skills Suite for Software Development — High-Level Design

Status: brainstorm output, not yet approved as an implementation plan.

## Vision

A small, portable library of Claude Agent Skills (`SKILL.md` format — same as
Anthropic's own official skills) covering the software development lifecycle:
code health, testing, architecture, dependencies, performance, release, docs,
and full GitHub operation. Project-agnostic and company-agnostic — drops into
any repo, any org, with zero setup.

What makes it a *suite* rather than a folder of unrelated skills: every skill
is cut from the same small kit of parts (see **Core Model** below), and every
skill's output is legible as another's input, Unix-pipe style, without hard
dependencies between them.

Near-term goal: a tight set of flagship ("pillar") skills, one or two per
cluster, built and proven in real use — not total coverage on day one. A
longer bench of situational ("long-tail") skills fills in once the standard
holds up under actual use, not just on paper.

**Gap this fills:** Anthropic's own catalog leans creative/document/enterprise;
loud community skill sets are either narrow (one methodology) or heavy and
bespoke (a whole project methodology). Nobody's shipped a small, sharp,
standalone dev-lifecycle set that assumes nothing about the project it lands in.

## The Catalog

8 clusters, ⭐ = pillar (build/polish first). 38 skills total (10 pillars, 28 long-tail).

| Cluster | Pillars | Long-tail |
|---|---|---|
| Code Quality & Health | ⭐tech-debt-inventory | dead-code-finder, code-comment-audit, naming-consistency-check, large-file-splitter-advisor |
| Testing & CI | ⭐flaky-test-triage | test-coverage-gap-finder, ci-pipeline-audit, test-smell-review |
| Architecture & Decisions | ⭐adr-writer | migration-plan-writer, design-doc-review, rfc-writer |
| Dependencies & Supply Chain | ⭐dependency-audit | upgrade-risk-assessor, sbom-generator, license-compliance-check |
| Performance & Observability | ⭐performance-budget-check | query-plan-review, log-taxonomy-designer, alert-fatigue-audit |
| Release & Operations | ⭐incident-postmortem | changelog-writer, release-notes-writer, rollback-plan-writer, runbook-writer |
| Collaboration & Docs | ⭐pr-description-writer, ⭐api-doc-writer | readme-writer, onboarding-doc-generator, repository-orientation |
| GitHub Operations | ⭐sync-strategy-advisor, ⭐pr-lifecycle-manager | issue-triage, project-board-sync, release-publisher, branch-hygiene, ci-status-gate |

**Bench (exploratory, not committed):** Refactoring & Modernization, Local Dev
& Environment, Data & Schema, AI Feature Engineering, Feature Flags &
Experimentation, Monorepo Coordination — ~19 more candidate skills, pull from
here once a cluster above proves thin.

**Second bench (2026-09-06, built — tag v1.1.0-draft):** with all 38
catalog skills built, the exploratory clusters got concrete names — one to
three each, standards-first and repository-agnostic; all eleven are built,
with cross-bench contract rows pinned by frozen producer output:

| Cluster | Skills |
|---|---|
| Data & Schema | openapi-breaking-change-check, json-schema-compat-check, schema-migration-review |
| Local Dev & Environment | env-var-inventory, devcontainer-audit |
| Feature Flags & Experimentation | feature-flag-inventory |
| Refactoring & Modernization | deprecation-sweep, public-api-change-check |
| AI Feature Engineering | prompt-template-audit |
| Monorepo Coordination | affected-packages-finder, cross-package-version-drift |

**Third bench (2026-09-06, being built):** ten more, same rhythm —
commit-message-lint, codeowners-check, retry-timeout-audit,
docker-compose-review, terraform-plan-review, accessibility-audit,
i18n-string-inventory, test-data-pii-scan, github-actions-cost-audit,
sla-error-budget-check.

## Core Model: a skill is a function

```
SKILL = TRIGGER → PROCEDURE(INPUTS) → OUTPUT, under PERMISSIONS
```

- **Trigger** — when it activates (`description` + when/when-not to use).
- **Inputs** — what it needs, required vs. optional-with-defaults.
- **Procedure** — an ordered sequence of function-stages: Gather → Filter →
  Analyze → Decide → [Confirm] → [Act] → Synthesize/Persist.
- **Permissions** — an effect ladder, not a binary: local-read → repo-read →
  network-read → local-write → shared-write → irreversible. Confirmation is
  required above "local-write," expressed as `allowed-tools` scoping plus an
  explicit gate — the skill's job is to classify effects correctly, not to
  reimplement the approval mechanism the host already provides.
- **Output** — a typed artifact (`finding-list`, `decision-doc`, `plan-doc`,
  `status-report`) or a live-state change, always a `Result` (success shape or
  a defined failure shape) — never just the happy path.

Artifact-kind skills are pure functions (safe anytime, cacheable, composable
by simple piping). Action-kind skills are impure functions with a declared
effect contract, a compensating action for every mutating step, and a
checkpoint after each step so an interrupted session can resume correctly.

## The Six Meta Layers

1. **Schema** — fixed `SKILL.md` sections (mirroring docstring conventions:
   `@requires`/`@returns`/`@throws`/`@example`), custom fields under `metadata:`
   per the real Agent Skills spec.
2. **Composability** — a closed vocabulary of artifact shapes; skills agree on
   shape, never call each other directly.
3. **Safety** — the effect ladder, `allowed-tools` scoping, confirm gates as
   "auth middleware" in front of Act.
4. **Voice** — plain, second-person imperative, one shared glossary, no
   marketing language.
5. **Infra** — `marketplace.json` as source of truth, per-skill semver +
   changelog, an `evals/` folder (example-based, property-based, and
   mutation-style fixtures) run in CI.
6. **Distribution/governance** — Apache-2.0, closed contribution for now with
   room to open later, suite-level version tags bundling known-good skill sets.

## External Standards to Build On (not reinvent)

- **MCP tool annotations** (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`) — the risk/kind vocabulary, aligned with the wider agent ecosystem.
- **SARIF** — the `finding-list` shape; uploadable straight into GitHub Code Scanning.
- **OSV** (OpenSSF) — vulnerability data for `dependency-audit`.
- **SPDX / CycloneDX** — the SBOM and license shapes.
- **Conventional Commits + Keep a Changelog** — input/output contract for the release cluster.
- **JSON Schema** — machine-checkable definitions of the canonical artifact shapes.
- **MADR** — the `decision-doc` shape, with built-in `superseded-by` versioning.
- **Diátaxis** — which of tutorial/how-to/reference/explanation each doc-skill produces.
- **C4 model** — the declared zoom level for anything architecture-shaped.
- **OpenTelemetry semantic conventions** — field naming for the observability cluster.
- **Twelve-Factor App** — the rubric behind the local-dev/environment bench cluster.

## Function-Design Principles Borrowed From Software Engineering

Named disciplines mapped directly onto skill design — cite by name in the spec
rather than re-justifying from scratch:

- **Command-Query Separation** — the formal name for the artifact/action split.
- **Design by Contract** — `@requires`/`@ensures` as testable assertions, not prose.
- **Railway-oriented programming** — how a `Result`-returning pipeline short-circuits on failure.
- **Functional core, imperative shell** — orchestrators must stay mechanically simple; judgment lives in pure sub-skills.
- **Fail-fast validation** — preconditions are checked first, before Gather proceeds.
- **Null Object pattern** — an empty finding-list is a valid, fully-formed instance, not an exception.
- **Dependency Injection** — `assets/`/`compatibility` are the injection points; never fork a skill to specialize it.
- **Liskov Substitution** — a skill that supersedes another must accept everything the original did and guarantee everything it guaranteed.
- **Strangler Fig** — how the standards above get adopted into the 38-skill catalog: one skill at a time, adapters bridging old to new, never a big-bang rewrite.

## Open Questions

- Naming for the suite itself (working candidates only, not settled).
- Exact promotion threshold from long-tail to pillar (an eval pass-rate number, per the SRE error-budget principle).
- Whether/when the bench clusters get promoted into the committed catalog.
