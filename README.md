# dev-skills-suite

A family of portable [Agent Skills](https://agentskills.io/specification)
for the software-development lifecycle, built to the Skill Design
Specification (SDS 1.0-draft) in `docs/superpowers/specs/`.

Every skill is either a **Query Skill** (Effect Ladder rungs 1–3: reads,
never mutates; safe to run unattended) or a **Command Skill** (rungs 4–6:
performs an effect behind a confirmation gate, with a compensating action
and a two-phase checkpoint). Skills compose by agreeing on artifact
shapes (`kit/shapes/`), never by calling each other.

## Skills

_This table is generated from `kit/registry/marketplace.json` by
`kit/scripts/render_index.py` (SDS-F-014). Do not edit it by hand._

| Skill | Kind | Rung | Tier | Status | In → Out | What it does |
|---|---|---|---|---|---|---|
| `performance-budget-check` | Query | 1 (local-read-only) | pillar | built | freeform → finding-list | Compares measured page metrics against a Lighthouse CI budget.json and, optionally, a baseline run, and produces a finding-list of over-budget, near-budget, and regressed metrics per path. Use before a release, when a bundle or page got slower, when asked whether performance is within budget, or when the user mentions Lighthouse, Core Web Vitals, or bundle size. |
| `tech-debt-inventory` | Query | 1 (local-read-only) | pillar | built | freeform → finding-list | Scans a repository's source files for technical-debt signals — TODO/FIXME/HACK markers, oversized files, duplicated code blocks — and produces a prioritized SARIF-compatible finding-list, with the model ranking what a mechanical scan cannot. Use when asked to inventory, audit, or prioritize technical debt, before planning a refactor, or when the user mentions TODOs, code smells, or god files. |
| `flaky-test-triage` | Query | 2 (domain-read-only) | pillar | built | freeform → finding-list | Reads a history of JUnit XML test reports, finds tests that both pass and fail on the same commit, and produces a finding-list with the evidence needed to classify each as a real bug, a test bug, or an environment fault — the classification itself is the model's judgment. Use when a CI job is intermittently red, when asked which tests are flaky, or when a failure cannot be reproduced locally. |
| `sync-strategy-advisor` | Query | 2 (domain-read-only) | pillar | built | freeform → decision-doc | Assesses a branch against its base and upstream — ahead/behind counts, predicted conflicts, whether the branch is already shared — and recommends exactly one sync action (rebase, merge, pull, push, resolve conflicts, fetch first, or nothing) as a decision-doc without performing any of them. Use when a branch is behind main, before opening a PR, when asked whether to rebase or merge, or when git reports divergence. |
| `dependency-audit` | Query | 3 (external-read-only) | pillar | built | freeform → finding-list | Scans a repository's dependency manifests (npm, PyPI, crates.io) for known vulnerabilities via the OSV database, and flags unresolved version ranges as best-effort. Use when reviewing a dependency bump, auditing supply-chain risk, checking a PR for outdated or vulnerable packages, or when the user mentions CVEs, npm audit, pip-audit, cargo audit, or "are our dependencies safe." |
| `adr-writer` | Command | 4 (local-write) | pillar | built | freeform → decision-doc | Captures an architecture decision as a numbered MADR record in the repository's ADR directory and as a machine-readable decision-doc, treating accepted records as immutable and superseding rather than editing them. Use when a significant technical choice has just been settled, when asked to write or record an ADR, or when an earlier decision is being replaced. |
| `api-doc-writer` | Command | 4 (local-write) | pillar | built | freeform → freeform | Extracts a Python package's public signatures and docstrings, detects drift between an existing reference page and the code, and writes a Diataxis-style reference page in which anything the code does not state is marked undocumented rather than invented. Use when API docs are missing or stale, before publishing a library, or when asked to write reference docs for a module's public interface. |
| `changelog-writer` | Command | 4 (local-write) | situational | built | freeform → status-report | Collects the Conventional Commits since the last tag, groups them into Keep a Changelog categories as a status-report, and inserts the entry at the top of CHANGELOG.md, refusing to write a version that already exists. Use when cutting a release, when asked to update or generate the changelog, or when a PR needs a changelog entry from its commits. |
| `incident-postmortem` | Command | 4 (local-write) | pillar | built | freeform → status-report | Facilitates and writes a blameless incident postmortem — timeline, impact, contributing factors, what went well, owned and dated action items — as a status-report and a markdown record in the repository, with a mechanical check for completeness and blaming language. Use after an incident or outage is resolved, when asked to run a retro or postmortem, or when a review keeps turning into who-did-what. |
| `pr-description-writer` | Command | 5 (shared-write) | pillar | built | freeform → freeform | Drafts a pull request description (summary, risk, test plan) from a branch's diff and commit history, and applies it to the open PR once confirmed. Use when opening or refreshing a PR description, when a diff has drifted from its original description, or when the user asks to write, update, or clean up a PR description. |
| `pr-lifecycle-manager` | Command | 6 (irreversible) | pillar | built | decision-doc → status-report | Orchestrates a pull request end to end: opens it from the current branch if none exists, requests reviewers, verifies CI and review state, and merges only after an explicit high-risk confirmation. Use when finishing a feature branch, when asked to open, ship, land, or merge a PR, or when a PR is green and waiting to be merged. |

## Using a skill

Each skill is a directory under `skills/` with a `SKILL.md` (the
instructions a model follows), `scripts/` for the mechanical parts,
optional `references/` and `assets/`, and `evals/` with a table-driven
eval file whose rows are real, runnable commands.

## Building a skill

Follow `kit/HOW-TO-BUILD-A-SKILL.md`, then run the conformance linter:

    python3 kit/scripts/lint-skill.py skills/<name>
    python3 kit/scripts/lint-skill.py --all skills

A skill is done when the linter reports zero errors and every eval row
passes (SDS-S-110).
