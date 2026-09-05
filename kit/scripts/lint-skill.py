#!/usr/bin/env python3
"""SDS conformance linter — checks a skill directory (or every skill in a
family) against the MACHINE-tagged rules of the Skill Design
Specification (SDS) 1.0-draft.

Usage:
    lint-skill.py <skill-dir> [--kit <kit>] [--registry <file>] [--json]
                  [--strict] [--no-review]
    lint-skill.py --all <skills-dir> [same options]
    lint-skill.py --rules

Exit codes: 0 conformant; 1 at least one ERROR (or WARN with --strict);
2 usage/IO error. Text output: one finding per line
`<RULE-ID> <LEVEL> <root-relative path>[:line] <message>`, sorted by
path, line, ID; a summary on stderr; then the REVIEW checklist.
`--json` emits a `finding-list` document conforming to
kit/shapes/finding-list.schema.json (REVIEW items become level "hint").
`--rules` prints the embedded rule table (`ID|slug|level|tag|section`),
one rule per line in ID order, for diffing against the spec's Appendix B.

Family root = parent of --kit (default: two levels above this file).
Never the git toplevel.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

try:
    import yaml
except ModuleNotFoundError:
    sys.stderr.write("ERROR: pyyaml is required (pip install pyyaml)\n")
    sys.exit(2)
try:
    import jsonschema
except ModuleNotFoundError:
    jsonschema = None

LINTER_VERSION = "1.0.0"
SDS_TARGET = "1.0-draft"

# --------------------------------------------------------------------------
# Rule table (must equal the spec's Appendix B)
# --------------------------------------------------------------------------
RULES: dict[str, tuple[str, str, str, str, str]] = {}
_RULE_TEXT = """
SDS-C-001 | five-parts | MUST | REVIEW | 2.1 | A skill declares Trigger, Inputs, Procedure, Permissions, Output.
SDS-C-002 | cqs | MUST | REVIEW | 2.2 | Command-Query Separation: a skill is a Query Skill or a Command Skill, never both.
SDS-C-003 | hermetic-gather | MUST | REVIEW | 2.3 | A Query Skill's Gather reads only declared Inputs (purity / referential transparency).
SDS-C-004 | idempotent-semantics | MAY | ADVISORY | 2.3 | metadata.idempotent means "safe to re-call with identical arguments" (MCP idempotentHint), NOT the fixed-point law.
SDS-C-005 | totality | MUST | REVIEW | 2.4 | Defined, non-crashing Output for every precondition-satisfying input incl. boundary cases.
SDS-C-010 | stage-vocabulary | MUST | REVIEW | 3.1 | Procedure stages drawn only from the 13-stage vocabulary (machine check: SDS-S-031).
SDS-C-011 | query-pipeline | MUST | REVIEW | 3.2 | Query pipeline Gather -> [Filter] -> Analyze -> [Classify] -> Synthesize.
SDS-C-012 | command-pipeline | MUST | REVIEW | 3.2 | Command pipeline Gather -> Analyze -> Decide -> (Confirm -> Act) -> [Communicate] -> [Persist]; parenthesized pair conditional per 10.4.
SDS-C-013 | nothing-after-synthesize | MUST | REVIEW | 3.2 | Nothing after Synthesize in a Query pipeline touches external state.
SDS-C-014 | railway | MUST | REVIEW | 3.3 | Railway-oriented composition; failure short-circuits to the declared failure Output.
SDS-C-015 | law-identity | MUST | REVIEW | 3.4 | Identity law; empty result is the identity element, handled by the ordinary path.
SDS-C-016 | law-associativity | MUST | REVIEW | 3.4 | Associativity; lossy reduction only at final Synthesize.
SDS-C-017 | law-fixed-point | MUST | REVIEW | 3.4 | Fixed-point law applies iff shape-out == shape-in and both are registered shapes (freeform/freeform does not qualify). Machine check: SDS-S-094.
SDS-C-018 | law-map-fusion | MUST | REVIEW | 3.4 | map(f)->map(g) == map(f->g); otherwise never fuse.
SDS-C-019 | fail-fast | MUST | REVIEW | 3.5 | Validate every precondition first; failure names the unmet precondition.
SDS-C-020 | termination | MUST | REVIEW | 3.6 | Any iterating stage declares a termination condition.
SDS-C-030 | shape-registered | MUST | REVIEW | 4.1 | @returns/@requires name a registered Shape or `freeform`. Machine check: SDS-S-026, SDS-S-038.
SDS-C-031 | standards-first | MUST | REVIEW | 4.2 | Adopt an existing interchange standard before registering a new Shape.
SDS-C-033 | null-object | MUST | REVIEW | 4.3 | Zero-result output is a well-formed, schema-valid instance of the Shape.
SDS-C-034 | immutability | SHOULD | REVIEW | 4.4 | Persisted artifacts are immutable; changes are new instances with supersession links.
SDS-C-040 | highest-rung | MUST | REVIEW | 5.1 | Declare the single highest Effect Ladder rung the Procedure reaches.
SDS-C-041 | rung-kind | MUST | REVIEW | 5.1 | Rungs 1-3 are Query Skills; 4-6 are Command Skills. Machine check: SDS-S-025.
SDS-C-042 | mcp-mapping | SHOULD | ADVISORY | 5.2 | Reflect the rung in MCP tool annotations where a skill is exposed as a tool.
SDS-C-043 | permission-scoping | MUST | REVIEW | 5.3 | allowed-tools scoped by rung; rung-5/6 ops never pre-approved. Machine checks: SDS-S-020..S-023.
SDS-C-044 | confirm-every-time | MUST | REVIEW | 5.4 | Confirm runs on every invocation reaching Act at rung>=5 and states the concrete effect.
SDS-C-045 | compensating-actions | MUST | REVIEW | 5.5 | Every mutating step declares a compensating action (saga).
SDS-C-046 | check-before-act | MUST | REVIEW | 5.6 | Every mutating step verifies current state first and skips as a no-op when already applied.
SDS-C-047 | checkpoint | MUST | REVIEW | 5.6 | Command Skills persist a two-phase checkpoint. Machine check: SDS-S-053.
SDS-C-048 | trust-model | MUST | ADVISORY | 5.7 | Declared hints are untrusted; declared risk, scoping, and host approval are independent layers.
SDS-C-050 | contracts-present | MUST | REVIEW | 6.1 | @requires, @returns, @throws stated as testable assertions. Machine check: SDS-S-030.
SDS-C-051 | required-optional | MUST | REVIEW | 6.1 | Each precondition marked REQUIRED or OPTIONAL with default. Machine check: SDS-S-036.
SDS-C-052 | long-parameter-list | MUST | REVIEW | 6.1 | More than five REQUIRED inputs => split the skill. Machine check: SDS-S-037.
SDS-C-053 | causal-chain | MUST | REVIEW | 6.2 | Failure values preserve the causal chain (wrapped errors).
SDS-C-054 | substitutability | MUST | REVIEW | 6.3 | A superseding skill satisfies Liskov substitution against declared consumers.
SDS-C-060 | functional-core | SHOULD | REVIEW | 7.1 | Orchestrators contain no Analyze/Classify/Decide logic of their own.
SDS-C-061 | injection-not-fork | MUST | REVIEW | 7.2 | Specialize via assets/ or compatibility; never fork a skill.
SDS-C-062 | strangler-fig | MUST | REVIEW | 7.3 | Adopt new shapes/conventions incrementally with adapters.
SDS-C-063 | contract-tests | SHOULD | REVIEW | 7.4 | Chained skills have a consumer-driven contract test.
SDS-F-001 | family-layout | MUST | MACHINE | 8.1 | Family root contains kit/, skills/, docs/.
SDS-F-002 | skills-dir-only-skills | MUST | MACHINE | 8.1 | skills/ contains only skill package directories (each with SKILL.md).
SDS-F-003 | spec-source-of-truth | MUST | REVIEW | 8.1 | The XML spec is authoritative; .txt/.html renderings regenerated with xml2rfc in the same change.
SDS-F-010 | registry-file | MUST | MACHINE | 8.2 | Canonical registry is kit/registry/marketplace.json.
SDS-F-011 | registry-schema | MUST | MACHINE | 8.2 | Registry validates against kit/registry/marketplace.schema.json.
SDS-F-012 | registry-fields | MUST | MACHINE | 8.2 | Each entry has name, description, version, effect-tier, tier, shape-out, shape-in.
SDS-F-013 | registry-skill-match | MUST | MACHINE | 8.2 | Every skills/<name> has exactly one entry; version/effect-tier/tier/shape-out/shape-in equal frontmatter.
SDS-F-014 | index-generated | MUST | REVIEW | 8.2 | Human-facing skill indexes are generated from the registry, never hand-maintained.
SDS-F-015 | registry-status | MUST | MACHINE | 8.2 | status is planned or built; built requires the skill dir to exist; a dir without an entry is an error.
SDS-F-016 | registry-description | SHOULD | MACHINE | 8.2 | Entry description equals the frontmatter description (whitespace-collapsed).
SDS-F-020 | root-gitignore | MUST | MACHINE | 8.3 | Family-root .gitignore contains `.skills-state/`.
SDS-F-021 | state-not-tracked | MUST | MACHINE | 8.3 | No tracked file under .skills-state/.
SDS-F-030 | root-relative-paths | MUST | MACHINE | 8.4 | Cross-references to kit/, skills/, docs/ files are family-root-relative; no `../`; no bare shapes/, shared/, templates/, registry/; referenced kit/ paths exist.
SDS-F-031 | skill-relative-commands | MUST | MACHINE | 8.4 | Commands run from the skill dir; scripts/, references/, assets/, evals/ references exist (generated fixtures exempt).
SDS-F-032 | root-resolution | MAY | ADVISORY | 8.4 | Tooling resolves root-relative paths by locating the family root (parent of kit/), never the git toplevel.
SDS-F-040 | skill-semver | MUST | MACHINE | 8.5 | metadata.version is semver.
SDS-F-041 | shape-semver | MUST | REVIEW | 8.5 | Shape changes: remove/narrow = MAJOR, add optional = MINOR, else PATCH.
SDS-F-042 | registry-sds-version | MUST | MACHINE | 8.5 | Registry top-level `sds` names the conformance target (e.g. "1.0-draft").
SDS-F-043 | major-shape-review | MUST | REVIEW | 8.5 | MAJOR shape change triggers review of every skill declaring that shape.
SDS-F-044 | spec-changelog | MUST | REVIEW | 8.5 | Every spec revision adds an Appendix C entry.
SDS-F-050 | spec-change-process | MUST | REVIEW | 8.6 | A spec change = XML edit + regenerated renderings + linter update when a MACHINE rule changes.
SDS-F-051 | ids-permanent | MUST | REVIEW | 8.6 | Rule IDs are never reused; withdrawn rules stay listed as withdrawn.
SDS-F-052 | guides-non-normative | MUST | ADVISORY | 8.6 | Kit guides are non-normative; conflicts resolve to the spec.
SDS-F-053 | promotion-threshold | SHOULD | REVIEW | 8.6 | Promotion situational -> pillar requires a recorded numeric threshold.
SDS-F-060 | glossary-single | MUST | MACHINE | 8.7 | Exactly one glossary at kit/shared/glossary.md.
SDS-F-061 | glossary-no-synonyms | SHOULD | MACHINE | 8.7 | Headings, @requires, @returns, and description avoid the glossary's do-not-use terms (heuristic; reserved words tier/rung/gate/checkpoint are REVIEW).
SDS-K-001 | kit-layout | MUST | MACHINE | 9.1 | kit/ contains templates/, evals/TEMPLATE.eval.yaml, shapes/, shared/{glossary.md,gates/,tool-profiles/}, registry/, scripts/lint-skill.py.
SDS-K-002 | guides-banner | MUST | MACHINE | 9.1 | HOW-TO-BUILD-A-SKILL.md and PRIMITIVES.md open with a non-normative banner citing the spec.
SDS-K-010 | template-order | MUST | MACHINE | 9.2 | Template H2/H3 order equals the normative order in 10.3.
SDS-K-020 | shape-file | MUST | MACHINE | 9.3 | kit/shapes/<name>.schema.json is JSON Schema 2020-12 with title == name and $id https://skills.local/shapes/<name>.schema.json.
SDS-K-021 | shape-registration | MUST | REVIEW | 9.3 | New shape carries a standards-first justification and a validating null-object instance.
SDS-K-022 | shape-glossary | SHOULD | REVIEW | 9.3 | A shape introducing a term adds a glossary row.
SDS-K-030 | gate-file | MUST | MACHINE | 9.4 | kit/shared/gates/<level>.md contains What, Why, and Reversible or Compensating action fields.
SDS-K-031 | gate-rung | MUST | REVIEW | 9.4 | Each gate maps to exactly one rung.
SDS-K-040 | profile-file | MUST | MACHINE | 9.5 | Tool profile YAML has name, effect-tier (enum), allowed-tools (list), notes.
SDS-K-041 | profile-denylist | MUST | MACHINE | 9.5 | No profile entry is a rung-5/6 operation (gh pr merge/edit/create at rung<5, git push, git merge, git rebase, git reset, branch -D, gh release create, gh api -X POST|PATCH|PUT|DELETE, rm -rf, git clean).
SDS-K-042 | profile-no-bare | MUST | MACHINE | 9.5 | No bare Bash(*)/Bash(python3:*)/interpreter entries in profiles.
SDS-K-043 | profile-verbatim | SHOULD | MACHINE | 9.5 | Skills copy profile entries verbatim; narrowing allowed, widening not (git/gh tokens outside every profile are INFO).
SDS-K-050 | glossary-row | MUST | MACHINE | 9.6 | Glossary rows are term | definition | do-not-use.
SDS-K-051 | glossary-cites | SHOULD | REVIEW | 9.6 | Each glossary row cites the spec section fixing the concept.
SDS-K-060 | eval-row-schema | MUST | MACHINE | 9.7 | Eval rows are {name, input?, expected{kind, shape?, failureCode?, reason?, assertions[]}} (checked per skill by SDS-S-090).
SDS-K-070 | linter-contract | MUST | MACHINE | 9.8 | kit/scripts/lint-skill.py <skill-dir>|--all exits 0 only when all MUST+MACHINE rules pass; output `<ID> <LEVEL> <path>[:line] <message>`; --json emits finding-list.
SDS-K-071 | linter-rules-match-spec | MUST | REVIEW | 9.8 | The linter's MACHINE rule table equals Appendix B's MACHINE set.
SDS-S-001 | skillmd-present | MUST | MACHINE | 10.1 | SKILL.md exists at the skill root.
SDS-S-002 | eval-file-present | MUST | MACHINE | 10.1 | Exactly one evals/<name>.eval.yaml exists.
SDS-S-003 | dir-name | MUST | MACHINE | 10.1 | Directory name equals frontmatter name.
SDS-S-004 | allowed-subdirs | SHOULD | MACHINE | 10.1 | Only scripts/, references/, assets/, evals/ (and SKILL.md) at the skill root.
SDS-S-005 | empty-subdir | MAY | MACHINE | 10.1 | Empty scripts/, references/, assets/ directories are reported.
SDS-S-010 | base-spec-keys | MUST | MACHINE | 10.2 | Only name, description, license, compatibility, metadata, allowed-tools at frontmatter top level.
SDS-S-011 | name-format | MUST | MACHINE | 10.2 | name matches ^[a-z0-9]+(-[a-z0-9]+)*$ and is <= 64 chars.
SDS-S-012 | description-length | MUST | MACHINE | 10.2 | description is 1-1024 characters.
SDS-S-013 | description-trigger | SHOULD | MACHINE | 10.2 | description contains a trigger phrase ("Use when" or equivalent); write it last.
SDS-S-014 | license-explicit | SHOULD | MACHINE | 10.2 | license is set explicitly; family default Apache-2.0 (difference is INFO).
SDS-S-015 | compatibility | MUST | MACHINE | 10.2 | compatibility <= 500 chars, names concrete requirements, and is present when effect-tier >= external-read-only.
SDS-S-016 | metadata-seven-keys | MUST | MACHINE | 10.2 | metadata is a map of strings containing exactly family, effect-tier, idempotent, tier, shape-out, shape-in, version.
SDS-S-017 | effect-tier-enum | MUST | MACHINE | 10.2 | effect-tier is one of the six rungs.
SDS-S-018 | idempotent-string | MUST | MACHINE | 10.2 | idempotent is the string "true" or "false".
SDS-S-019 | tier-enum | MUST | MACHINE | 10.2 | tier is pillar or situational.
SDS-S-020 | allowed-tools-required | MUST | MACHINE | 10.2 | Any skill at rung >= 2 that invokes tools or bundled scripts declares allowed-tools (string).
SDS-S-021 | allowed-tools-sources | MUST | MACHINE | 10.2 | allowed-tools = shared profile entries verbatim + inline Bash(python3 scripts/<file>:*) per shipped script; script tokens reference existing files under scripts/ only.
SDS-S-022 | allowed-tools-no-bare | MUST | MACHINE | 10.2 | No bare Bash(*), Bash(python3:*), Bash(sh:*), Bash(bash:*), Bash(node:*) or bare Bash.
SDS-S-023 | allowed-tools-denylist | MUST | MACHINE | 10.2 | No rung-5/6 operation at any rung (FORBIDDEN-ALWAYS); no FORBIDDEN-BELOW-5 op below rung 5; no FORBIDDEN-BELOW-4 op (Write, Edit, MultiEdit, NotebookEdit, git checkout -b, git stash) below rung 4.
SDS-S-024 | write-scope | MUST | REVIEW | 10.2 | Write/Edit tools only for Command Skills and only for .skills-state/ or the declared output location.
SDS-S-025 | rung-kind-sections | MUST | MACHINE | 10.2 | Rung <= 3 => no Confirm/Act/Communicate headings; rung >= 4 => Act heading; rung >= 5 => Confirm heading before Act.
SDS-S-026 | shapes-registered | MUST | MACHINE | 10.2 | shape-out and each shape-in value is a registered shape (kit/shapes/*.schema.json) or freeform.
SDS-S-027 | version-semver | MUST | MACHINE | 10.2 | metadata.version is semver (also SDS-F-040).
SDS-S-028 | family-matches | MUST | MACHINE | 10.2 | metadata.family equals the registry's family.
SDS-S-030 | h2-order | MUST | MACHINE | 10.3 | H2 sections exactly: When to use, When not to use, @requires, Instructions, @returns, @throws, @example (extras only @see/@deprecated; none empty).
SDS-S-031 | stage-headings | MUST | MACHINE | 10.3 | H3 under Instructions are stage-vocabulary names; Query requires Gather, Analyze, Synthesize (Filter/Classify optional); Command requires Gather, Analyze, Decide, [Confirm at rung 4 optional, required at 5-6], Act, Communicate, Persist; canonical order as a subsequence.
SDS-S-032 | na-form | MUST | MACHINE | 10.3 | An inapplicable required heading's body begins `N/A — <reason>`.
SDS-S-033 | no-fill-residue | MUST | MACHINE | 10.3 | No `[FILL`, `skill-name-here`, or `[Write this LAST` residue.
SDS-S-034 | voice | SHOULD | MACHINE | 10.3 | Second-person imperative; no marketing words (powerful, seamless, comprehensive, robust, cutting-edge).
SDS-S-035 | budget | MUST | MACHINE | 10.3 | SKILL.md under 500 lines (warning at 400).
SDS-S-036 | requires-form | MUST | MACHINE | 10.3 | @requires bullets start REQUIRED: or OPTIONAL:; OPTIONAL bullets carry (default: ...) unless exactly `OPTIONAL: none`.
SDS-S-037 | requires-count | MUST | MACHINE | 10.3 | At least one REQUIRED input; more than five is a warning to split (SDS-C-052).
SDS-S-038 | returns-shape | MUST | MACHINE | 10.3 | @returns contains Shape: `<shape-out>` and, for a registered shape, the literal kit/shapes/<shape-out>.schema.json.
SDS-S-039 | throws-form | MUST | MACHINE | 10.3 | @throws has >= 1 bullet of form - `kebab-code`: ...; codes unique; every eval failureCode is a declared code; rung >= 5 declares a declined/refused code (warning).
SDS-S-040 | example | MUST | MACHINE | 10.3 | @example contains **Input:** and an Output/Result block.
SDS-S-041 | conditional-act | MUST | MACHINE | 10.4 | If Decide contains a bold `**If <condition>: stop here.**` branch, Confirm and Act sections begin `Only reached when <condition>.` and @returns describes both paths.
SDS-S-042 | act-less-no-mutation | MUST | REVIEW | 10.4 | The Act-less path mutates nothing.
SDS-S-043 | h1-title | SHOULD | MACHINE | 10.3 | First heading is `# <name>`.
SDS-S-050 | confirm-gate | MUST | MACHINE | 10.5 | Rung-5 Confirm cites kit/shared/gates/medium.md; rung-6 cites kit/shared/gates/high.md; Confirm precedes Act.
SDS-S-051 | act-unwrapped | MUST | MACHINE | 10.5 | Rung-5/6 Act is a direct tool call; no bundled script performs the mutation (scripts at rung >= 5 must not subprocess mutating commands).
SDS-S-052 | check-before-act-stated | MUST | REVIEW | 10.5 | Act states the check-before-act no-op skip explicitly.
SDS-S-053 | two-phase-checkpoint | MUST | MACHINE | 10.5 | Rung >= 4 Act contains **Checkpoint** describing the pending-then-completed record at .skills-state/<name>/<key>.json.
SDS-S-054 | compensating-label | MUST | MACHINE | 10.5 | Rung >= 4 Act contains **Compensating action** for each mutating step.
SDS-S-055 | checkpoint-ownership | SHOULD | REVIEW | 10.5 | Inline checkpoint write for one mutating step; scripts/checkpoint.py for two or more.
SDS-S-060 | toil-test | MUST | REVIEW | 10.6 | Scripts hold deterministic, mechanical work only.
SDS-S-061 | no-judgment-in-scripts | MUST | REVIEW | 10.6 | Analyze, Classify, Decide never live in a script.
SDS-S-062 | script-naming | SHOULD | MACHINE | 10.6 | scripts/ files are snake_case verb_noun .py/.sh; adapters name both sides.
SDS-S-063 | script-conventions | MUST | MACHINE | 10.6 | Scripts start with a shebang, have a module docstring (or leading comment block for .sh), print JSON to stdout, exit 0 with an empty instance on empty input, exit 1 with `ERROR: ` on stderr on failure (presence of ERROR:/exit handling is a warning check).
SDS-S-064 | script-deps | MUST | REVIEW | 10.6 | Non-stdlib dependencies are named in the docstring and in compatibility.
SDS-S-065 | injectable-fixture | SHOULD | MACHINE | 10.6 | A script that calls an external system exposes a --<thing>-file flag substituting a fixture for the live call.
SDS-S-066 | script-executable | SHOULD | MACHINE | 10.6 | Scripts carry the owner execute bit.
SDS-S-067 | script-referenced | SHOULD | MACHINE | 10.6 | Every scripts/ file is referenced from SKILL.md.
SDS-S-070 | references-placement | MUST | REVIEW | 10.7 | Content needed every invocation lives in SKILL.md; occasional depth lives in references/.
SDS-S-071 | references-one-level | SHOULD | MACHINE | 10.7 | references/ files do not link to other references/ files.
SDS-S-072 | references-conditional | SHOULD | MACHINE | 10.7 | Each SKILL.md pointer to references/ is phrased as a condition (if/when/only/unless).
SDS-S-073 | references-linked | SHOULD | MACHINE | 10.7 | Every references/ file is linked from SKILL.md.
SDS-S-080 | assets-no-shape-copy | MUST | MACHINE | 10.8 | assets/ never contains a copy of a family shape schema.
SDS-S-081 | assets-declared | MUST | MACHINE | 10.8 | Every assets/ file read by the Procedure is named in @requires or Instructions.
SDS-S-082 | assets-injection | MUST | REVIEW | 10.8 | Per-installation configuration is injected via assets/, never by forking.
SDS-S-090 | eval-structure | MUST | MACHINE | 10.9 | Eval file parses; skill == name; rows non-empty with unique names; expected.kind in {success, failure, not-applicable}; not-applicable has reason; failure has failureCode; extra YAML documents are empty.
SDS-S-091 | eval-assertions | SHOULD | MACHINE | 10.9 | Success rows have >= 1 assertion and, for registered shapes, a shape field ("runs without erroring" is not a pass).
SDS-S-092 | eval-open-world | MUST | MACHINE | 10.9 | Rung >= 3: no required row invokes a live external system (curl, wget, http(s)://, gh api, pip/npm install); live checks live after the `---` separator asserting shape only.
SDS-S-093 | frozen-fixture-naming | SHOULD | MACHINE | 10.9 | Frozen recordings are evals/fixtures/frozen-<source>-<what>.json.
SDS-S-094 | eval-fixed-point | MUST | MACHINE | 10.9 | fixed-point row is success iff shape-out == shape-in and registered; otherwise not-applicable with reason.
SDS-S-095 | eval-mutation-fixture | MUST | MACHINE | 10.9 | mutation-fixture row is success with an evals/fixtures/ path iff shape-out == finding-list; otherwise not-applicable with reason.
SDS-S-096 | fixtures-layout | MUST | MACHINE | 10.9 | Static fixtures in evals/fixtures/<case>/ (.gitkeep when empty); generated fixtures listed in evals/fixtures/.gitignore with an executable evals/fixtures/build-<name>.sh; nested .git directories are gitignored; every referenced fixture exists or is generated.
SDS-S-097 | fixtures-referenced | SHOULD | MACHINE | 10.9 | Every fixture file is referenced by a row or the smoke section.
SDS-S-098 | eval-paths-inside | MUST | MACHINE | 10.9 | Rows reference only paths inside the skill dir or kit/ (absolute or ~ paths are warnings).
SDS-S-099 | eval-required-rows | MUST | MACHINE | 10.9 | Rows named happy-path* (success), >= 2 boundary-* (one empty/zero/none/minimal success, one malformed/invalid/missing/not-a/bad failure), and contract-with-* exist.
SDS-S-100 | state-path | MUST | MACHINE | 10.10 | Command Skills reference .skills-state/<name>/ for runtime state (a different skill name is an error).
SDS-S-101 | state-record | MUST | REVIEW | 10.10 | Checkpoint record is {key, step, status: pending|completed, startedAt, preState, compensatingAction, postState?}.
SDS-S-110 | validation-gate | MUST | REVIEW | 10.11 | Done = linter passes, metadata matches procedure, example artifact validates, eval table passes, glossary check.
"""
for _line in _RULE_TEXT.strip().splitlines():
    _parts = [p.strip() for p in _line.split("|", 5)]
    RULES[_parts[0]] = (_parts[1], _parts[2], _parts[3], _parts[4], _parts[5])

REVIEW_ORDER = [
    "SDS-C-002", "SDS-C-003", "SDS-C-005", "SDS-C-019", "SDS-C-020",
    "SDS-C-033", "SDS-C-031", "SDS-C-044", "SDS-C-045", "SDS-C-046",
    "SDS-C-047", "SDS-S-024", "SDS-S-042", "SDS-S-052", "SDS-S-055",
    "SDS-S-060", "SDS-S-061", "SDS-S-064", "SDS-S-070", "SDS-S-082",
    "SDS-S-101", "SDS-S-110",
]

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
LADDER = [
    "local-read-only", "domain-read-only", "external-read-only",
    "local-write", "shared-write", "irreversible",
]
TIERS = {"pillar", "situational"}
META_KEYS = ["family", "effect-tier", "idempotent", "tier", "shape-out", "shape-in", "version"]
BASE_SPEC_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
REQUIRED_H2 = ["When to use", "When not to use", "@requires", "Instructions", "@returns", "@throws", "@example"]
OPTIONAL_H2 = {"@see", "@deprecated"}
STAGE_ALIASES = {
    "Gather": "Gather", "Filter": "Filter", "Select": "Filter",
    "Analyze": "Analyze", "Diagnose": "Analyze", "Classify": "Classify",
    "Score": "Classify", "Decide": "Decide", "Recommend": "Decide",
    "Synthesize": "Synthesize", "Compose": "Synthesize", "Validate": "Validate",
    "Verify": "Validate", "Transform": "Transform", "Generate": "Transform",
    "Confirm": "Confirm", "Act": "Act", "Mutate": "Act",
    "Communicate": "Communicate", "Notify": "Communicate",
    "Persist": "Persist", "Record": "Persist", "Delegate": "Delegate", "Dispatch": "Delegate",
}
CANON_ORDER = ["Gather", "Filter", "Analyze", "Classify", "Decide", "Synthesize",
               "Validate", "Transform", "Confirm", "Act", "Communicate", "Persist", "Delegate"]
QUERY_REQUIRED = ["Gather", "Analyze", "Synthesize"]
COMMAND_REQUIRED = ["Gather", "Analyze", "Decide", "Act", "Communicate", "Persist"]
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TRIGGER_RE = re.compile(r"use (this |it )?when|when the user|when (asked|reviewing|opening)", re.I)
MARKETING_RE = re.compile(r"\b(powerful|seamless|comprehensive|robust|cutting-edge)\b", re.I)
FORBIDDEN_ALWAYS = [
    r"gh pr merge", r"git push", r"git merge", r"git rebase", r"git reset",
    r"git branch -D", r"git branch -d", r"gh release create", r"gh repo delete",
    r"gh issue close", r"gh pr close", r"gh api -X (POST|PATCH|PUT|DELETE)",
    r"rm -rf", r"git clean",
]
FORBIDDEN_BELOW_5 = [r"gh pr create", r"gh pr edit", r"gh pr comment", r"gh issue create",
                     r"git commit", r"git add"]
FORBIDDEN_BELOW_4_EXACT = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
FORBIDDEN_BELOW_4 = [r"git checkout -b", r"git stash"]
BARE_TOOLS_RE = re.compile(r"^(Bash|Bash\(\*\)|Bash\((python3?|sh|bash|node)(:\*)?\))$")
LIVE_CALL_RE = re.compile(r"\bcurl\b|\bwget\b|https?://|\bgh api\b|pip install|npm install")
MUTATING_SCRIPT_RE = re.compile("|".join(FORBIDDEN_ALWAYS + [r"gh pr edit", r"gh pr create", r"git commit"]))
EXTERNAL_CALL_RE = re.compile(r"urllib\.request|import requests|http\.client|socket\.|\bcurl\b|\"gh\"|'gh'")
FIXTURE_RESERVED = {".gitignore", ".gitkeep"}
LEVEL_FOR = {"MUST": "ERROR", "SHOULD": "WARN", "MAY": "INFO"}
JSON_LEVEL = {"ERROR": "error", "WARN": "warning", "INFO": "info", "REVIEW": "hint"}


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Finding:
    rule_id: str
    level: str
    path: str
    line: int | None
    message: str


@dataclass
class Check:
    id: str
    scope: str  # "skill" | "family"
    fn: Callable


CHECKS: list[Check] = []


def check(rule_id: str, scope: str = "skill"):
    def deco(fn):
        CHECKS.append(Check(rule_id, scope, fn))
        return fn
    return deco


@dataclass
class Heading:
    level: int
    text: str
    line: int  # 1-based


@dataclass
class FamilyCtx:
    root: Path
    kit: Path
    registry_path: Path | None
    registry: dict | None
    registry_error: str | None
    shapes: set[str]
    profile_tokens: set[str]
    glossary_terms: list[str]
    all_mode: bool = False


@dataclass
class SkillCtx:
    dir: Path
    fam: FamilyCtx
    name: str
    raw: list[str] = field(default_factory=list)
    fm: dict = field(default_factory=dict)
    fm_ok: bool = False
    fm_end: int = 0
    key_lines: dict = field(default_factory=dict)
    headings: list[Heading] = field(default_factory=list)
    eval_path: Path | None = None
    eval_doc: dict | None = None
    eval_extra: list = field(default_factory=list)
    eval_raw: list[str] = field(default_factory=list)
    eval_error: str | None = None
    eval_row_lines: dict = field(default_factory=dict)

    # ---- helpers -------------------------------------------------------
    @property
    def rung(self) -> int:
        et = self.meta.get("effect-tier")
        return LADDER.index(et) + 1 if et in LADDER else 0

    @property
    def meta(self) -> dict:
        m = self.fm.get("metadata")
        return m if isinstance(m, dict) else {}

    @property
    def rel(self) -> str:
        return relpath(self.fam.root, self.dir)

    def p(self, sub: str = "") -> str:
        return f"{self.rel}/{sub}" if sub else self.rel

    def h2s(self) -> list[Heading]:
        return [h for h in self.headings if h.level == 2]

    def h2(self, text: str) -> Heading | None:
        for h in self.headings:
            if h.level == 2 and h.text == text:
                return h
        return None

    def section_lines(self, h: Heading) -> tuple[int, int]:
        """Return (start, end) 1-based inclusive/exclusive line span of a section body."""
        end = len(self.raw) + 1
        for other in self.headings:
            if other.line > h.line and other.level <= h.level:
                end = other.line
                break
        return h.line + 1, end

    def section_text(self, h: Heading | None) -> str:
        if h is None:
            return ""
        s, e = self.section_lines(h)
        return "\n".join(self.raw[s - 1:e - 1])

    def stage_headings(self) -> list[Heading]:
        ins = self.h2("Instructions")
        if ins is None:
            return []
        s, e = self.section_lines(ins)
        return [h for h in self.headings if h.level == 3 and s <= h.line < e]

    def stage(self, name: str) -> Heading | None:
        for h in self.stage_headings():
            if norm_stage(h.text) == name:
                return h
        return None

    def body_text(self) -> str:
        return "\n".join(self.raw[self.fm_end:])

    def prose_lines(self) -> list[tuple[int, str]]:
        return strip_fences(self.raw, self.fm_end)


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def relpath(root: Path, p: Path) -> str:
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(p)


def norm_stage(text: str) -> str:
    base = text.split("/")[0].strip()
    base = re.sub(r"[^A-Za-z].*$", "", base)
    return STAGE_ALIASES.get(base, base)


def split_frontmatter(lines: list[str]) -> tuple[str | None, int]:
    if not lines or lines[0].strip() != "---":
        return None, 0
    for i in range(1, len(lines)):
        if re.match(r"^---\s*$", lines[i]):
            return "\n".join(lines[1:i]), i + 1
    return None, 0


def parse_headings(lines: list[str], offset: int) -> list[Heading]:
    out, in_fence = [], False
    for i in range(offset, len(lines)):
        line = lines[i]
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            out.append(Heading(len(m.group(1)), m.group(2).strip(), i + 1))
    return out


def strip_fences(lines: list[str], offset: int) -> list[tuple[int, str]]:
    out, in_fence = [], False
    for i in range(offset, len(lines)):
        line = lines[i]
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((i + 1, line))
    return out


def tokenize_allowed_tools(s: str) -> list[str]:
    tokens, buf, depth = [], "", 0
    for frag in s.split():
        buf = f"{buf} {frag}" if buf else frag
        depth += frag.count("(") - frag.count(")")
        if depth <= 0:
            tokens.append(buf)
            buf, depth = "", 0
    if buf:
        tokens.append(buf)
    return tokens


PATH_RE = re.compile(r"(?<![\w.\-/])((?:\.\./)+[\w./-]*|kit/[\w./-]+|skills/[\w./-]+|docs/[\w./-]+|scripts/[\w./-]+|references/[\w./-]+|assets/[\w./-]+|evals/[\w./-]+)")
STRIP_TRAIL = "`.,):;'\"*]>"


def iter_path_refs(text: str):
    for m in PATH_RE.finditer(text):
        tok = m.group(1).rstrip(STRIP_TRAIL)
        # trim trailing "/" artifacts like "kit/" alone
        yield tok


def bullets(section: str) -> list[str]:
    """Top-level '- ' bullets with continuation lines joined."""
    out: list[str] = []
    for line in section.splitlines():
        if re.match(r"^- ", line):
            out.append(line[2:].strip())
        elif out and re.match(r"^\s{2,}\S", line):
            out[-1] += " " + line.strip()
    return out


def load_yaml_file(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def gitignored(fixtures_dir: Path, rel: str) -> bool:
    gi = fixtures_dir / ".gitignore"
    if not gi.exists():
        return False
    for pat in gi.read_text().splitlines():
        pat = pat.strip()
        if not pat or pat.startswith("#"):
            continue
        p = pat.rstrip("/")
        if fnmatch.fnmatch(rel, p) or rel == p or rel.startswith(p + "/"):
            return True
    return False


# --------------------------------------------------------------------------
# Context loading
# --------------------------------------------------------------------------
def load_family(root: Path, kit: Path, registry_arg: str | None, all_mode: bool) -> FamilyCtx:
    reg_path, reg, reg_err = None, None, None
    candidates = [Path(registry_arg)] if registry_arg else [kit / "registry" / "marketplace.json",
                                                            kit / "registry" / "marketplace.example.json"]
    for c in candidates:
        if c.exists():
            reg_path = c
            break
    if reg_path is None:
        reg_err = "no registry file found"
    else:
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            reg_err = f"registry unreadable: {e}"
    shapes = {p.name[: -len(".schema.json")] for p in (kit / "shapes").glob("*.schema.json")}
    profile_tokens: set[str] = set()
    for prof in (kit / "shared" / "tool-profiles").glob("*.yaml"):
        try:
            data = load_yaml_file(prof)
            for t in (data or {}).get("allowed-tools", []) or []:
                profile_tokens.add(str(t))
        except yaml.YAMLError:
            pass
    terms: list[str] = []
    gl = kit / "shared" / "glossary.md"
    if gl.exists():
        for line in gl.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 3 and cells[0] not in ("Term", "---"):
                for tok in cells[2].split(","):
                    tok = re.sub(r"\(.*?\)", "", tok).strip().strip("`")
                    if tok and " " not in tok and tok.lower() not in {"tier", "rung", "gate", "checkpoint"}:
                        terms.append(tok.lower())
    return FamilyCtx(root, kit, reg_path, reg, reg_err, shapes, profile_tokens, terms, all_mode)


def load_skill(d: Path, fam: FamilyCtx) -> SkillCtx:
    ctx = SkillCtx(d, fam, d.name)
    sk = d / "SKILL.md"
    if not sk.exists():
        return ctx
    ctx.raw = sk.read_text(encoding="utf-8").splitlines()
    fm_text, end = split_frontmatter(ctx.raw)
    ctx.fm_end = end
    if fm_text is not None:
        try:
            data = yaml.safe_load(fm_text)
            if isinstance(data, dict):
                ctx.fm, ctx.fm_ok = data, True
        except yaml.YAMLError:
            pass
    for i in range(0, end):
        m = re.match(r"^([A-Za-z-]+):", ctx.raw[i])
        if m:
            ctx.key_lines.setdefault(m.group(1), i + 1)
    ctx.headings = parse_headings(ctx.raw, end)
    evals = sorted((d / "evals").glob("*.eval.yaml")) if (d / "evals").is_dir() else []
    ctx.eval_path = evals[0] if len(evals) == 1 else None
    if ctx.eval_path:
        ctx.eval_raw = ctx.eval_path.read_text(encoding="utf-8").splitlines()
        try:
            docs = list(yaml.safe_load_all("\n".join(ctx.eval_raw)))
            ctx.eval_doc = docs[0] if docs and isinstance(docs[0], dict) else None
            ctx.eval_extra = docs[1:]
            if ctx.eval_doc is None:
                ctx.eval_error = "first YAML document is not a mapping"
        except yaml.YAMLError as e:
            ctx.eval_error = str(e).splitlines()[0]
        for i, line in enumerate(ctx.eval_raw):
            m = re.match(r"^\s*-\s+name:\s*(\S+)", line)
            if m:
                ctx.eval_row_lines.setdefault(m.group(1), i + 1)
    return ctx


# --------------------------------------------------------------------------
# Skill-scope checks
# --------------------------------------------------------------------------
def F(ctx: SkillCtx, rid: str, msg: str, sub: str = "SKILL.md", line: int | None = None, level: str | None = None) -> Finding:
    lvl = level or LEVEL_FOR[RULES[rid][1]]
    return Finding(rid, lvl, ctx.p(sub), line, msg)


@check("SDS-S-001")
def c_s001(ctx):
    if not (ctx.dir / "SKILL.md").exists():
        return [F(ctx, "SDS-S-001", "SKILL.md is missing", "")]
    return []


@check("SDS-S-002")
def c_s002(ctx):
    evals = sorted((ctx.dir / "evals").glob("*.eval.yaml")) if (ctx.dir / "evals").is_dir() else []
    expected = ctx.dir / "evals" / f"{ctx.name}.eval.yaml"
    if len(evals) != 1 or evals[0] != expected:
        return [F(ctx, "SDS-S-002", f"expected exactly one eval file named evals/{ctx.name}.eval.yaml; found {[e.name for e in evals]}", "evals")]
    return []


@check("SDS-S-003")
def c_s003(ctx):
    if ctx.fm_ok and ctx.fm.get("name") != ctx.name:
        return [F(ctx, "SDS-S-003", f"frontmatter name {ctx.fm.get('name')!r} != directory name {ctx.name!r}", line=ctx.key_lines.get("name"))]
    return []


@check("SDS-S-004")
def c_s004(ctx):
    out = []
    for entry in sorted(ctx.dir.iterdir()):
        if entry.name not in {"SKILL.md", "scripts", "references", "assets", "evals"}:
            out.append(F(ctx, "SDS-S-004", f"unexpected entry at skill root: {entry.name}", entry.name))
    return out


@check("SDS-S-005")
def c_s005(ctx):
    out = []
    for sub in ("scripts", "references", "assets"):
        p = ctx.dir / sub
        if p.is_dir() and not any(p.iterdir()):
            out.append(F(ctx, "SDS-S-005", f"{sub}/ exists but is empty", sub))
    return out


@check("SDS-S-010")
def c_s010(ctx):
    if not ctx.fm_ok:
        return [F(ctx, "SDS-S-010", "frontmatter missing or not valid YAML mapping", line=1)]
    return [F(ctx, "SDS-S-010", f"unknown top-level frontmatter key {k!r}", line=ctx.key_lines.get(k))
            for k in ctx.fm if k not in BASE_SPEC_KEYS]


@check("SDS-S-011")
def c_s011(ctx):
    n = ctx.fm.get("name")
    if not ctx.fm_ok:
        return []
    if not isinstance(n, str) or not n:
        return [F(ctx, "SDS-S-011", "name missing", line=ctx.key_lines.get("name"))]
    if not NAME_RE.match(n) or len(n) > 64:
        return [F(ctx, "SDS-S-011", f"name {n!r} is not kebab-case <= 64 chars", line=ctx.key_lines.get("name"))]
    return []


@check("SDS-S-012")
def c_s012(ctx):
    if not ctx.fm_ok:
        return []
    d = ctx.fm.get("description")
    if not isinstance(d, str) or not (1 <= len(d) <= 1024):
        return [F(ctx, "SDS-S-012", f"description missing or length {len(d) if isinstance(d, str) else 0} not in 1..1024", line=ctx.key_lines.get("description"))]
    return []


@check("SDS-S-013")
def c_s013(ctx):
    d = ctx.fm.get("description")
    if isinstance(d, str) and not TRIGGER_RE.search(d):
        return [F(ctx, "SDS-S-013", "description lacks a trigger phrase such as 'Use when ...'", line=ctx.key_lines.get("description"))]
    return []


@check("SDS-S-014")
def c_s014(ctx):
    if not ctx.fm_ok:
        return []
    lic = ctx.fm.get("license")
    if not lic:
        return [F(ctx, "SDS-S-014", "license not set explicitly (family default Apache-2.0)", line=1)]
    if str(lic).strip() != "Apache-2.0":
        return [F(ctx, "SDS-S-014", f"license {lic!r} differs from family default Apache-2.0", line=ctx.key_lines.get("license"), level="INFO")]
    return []


@check("SDS-S-015")
def c_s015(ctx):
    if not ctx.fm_ok:
        return []
    out = []
    comp = ctx.fm.get("compatibility")
    if comp is not None and len(str(comp)) > 500:
        out.append(F(ctx, "SDS-S-015", f"compatibility is {len(str(comp))} chars (> 500)", line=ctx.key_lines.get("compatibility")))
    if ctx.rung >= 3 and not comp:
        out.append(F(ctx, "SDS-S-015", "effect-tier >= external-read-only requires a compatibility field naming the external requirement", line=1))
    return out


@check("SDS-S-016")
def c_s016(ctx):
    if not ctx.fm_ok:
        return []
    m = ctx.fm.get("metadata")
    ln = ctx.key_lines.get("metadata")
    if not isinstance(m, dict):
        return [F(ctx, "SDS-S-016", "metadata missing or not a mapping", line=ln)]
    out = []
    for k in META_KEYS:
        if k not in m:
            out.append(F(ctx, "SDS-S-016", f"metadata.{k} missing", line=ln))
    for k, v in m.items():
        if k not in META_KEYS:
            out.append(F(ctx, "SDS-S-016", f"metadata.{k} is not one of the seven family keys", line=ln))
        elif not isinstance(v, str):
            out.append(F(ctx, "SDS-S-016", f"metadata.{k} must be a string (got {type(v).__name__}; quote it)", line=ln))
    return out


@check("SDS-S-017")
def c_s017(ctx):
    et = ctx.meta.get("effect-tier")
    if ctx.fm_ok and et not in LADDER:
        return [F(ctx, "SDS-S-017", f"effect-tier {et!r} not in {LADDER}", line=ctx.key_lines.get("metadata"))]
    return []


@check("SDS-S-018")
def c_s018(ctx):
    v = ctx.meta.get("idempotent")
    if ctx.fm_ok and v not in ("true", "false"):
        return [F(ctx, "SDS-S-018", f"idempotent must be the string \"true\" or \"false\" (got {v!r})", line=ctx.key_lines.get("metadata"))]
    return []


@check("SDS-S-019")
def c_s019(ctx):
    v = ctx.meta.get("tier")
    if ctx.fm_ok and v not in TIERS:
        return [F(ctx, "SDS-S-019", f"tier must be pillar or situational (got {v!r})", line=ctx.key_lines.get("metadata"))]
    return []


def script_files(ctx: SkillCtx) -> list[Path]:
    d = ctx.dir / "scripts"
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix in (".py", ".sh")) if d.is_dir() else []


def tools(ctx: SkillCtx) -> list[str]:
    at = ctx.fm.get("allowed-tools")
    return tokenize_allowed_tools(at) if isinstance(at, str) else []


@check("SDS-S-020")
def c_s020(ctx):
    if not ctx.fm_ok:
        return []
    at = ctx.fm.get("allowed-tools")
    needs = ctx.rung >= 2 or bool(script_files(ctx))
    if needs and at is None:
        return [F(ctx, "SDS-S-020", "allowed-tools required (rung >= 2 or bundled scripts present)", line=1)]
    if at is not None and not isinstance(at, str):
        return [F(ctx, "SDS-S-020", "allowed-tools must be a space-separated string, not a list", line=ctx.key_lines.get("allowed-tools"))]
    return []


SCRIPT_TOKEN_RE = re.compile(r"^Bash\((?:python3?\s+|bash\s+|sh\s+)?([^\s:)]+\.(?:py|sh))(?::\*)?\)$")


@check("SDS-S-021")
def c_s021(ctx):
    out, ln = [], ctx.key_lines.get("allowed-tools")
    referenced = set()
    for tok in tools(ctx):
        m = SCRIPT_TOKEN_RE.match(tok)
        if not m:
            continue
        path = m.group(1)
        if not path.startswith("scripts/"):
            out.append(F(ctx, "SDS-S-021", f"script token {tok!r} points outside scripts/", line=ln))
        elif not (ctx.dir / path).exists():
            out.append(F(ctx, "SDS-S-021", f"script token {tok!r} references a file that does not exist", line=ln))
        referenced.add(path)
    if ctx.fm.get("allowed-tools") is not None:
        for sf in script_files(ctx):
            rel = f"scripts/{sf.name}"
            if rel not in referenced:
                out.append(F(ctx, "SDS-S-021", f"{rel} is shipped but has no inline allowed-tools entry (Bash(python3 {rel}:*))", line=ln))
    return out


@check("SDS-S-022")
def c_s022(ctx):
    ln = ctx.key_lines.get("allowed-tools")
    return [F(ctx, "SDS-S-022", f"bare interpreter/tool scope {tok!r} pre-approves arbitrary commands", line=ln)
            for tok in tools(ctx) if BARE_TOOLS_RE.match(tok)]


@check("SDS-S-023")
def c_s023(ctx):
    out, ln, r = [], ctx.key_lines.get("allowed-tools"), ctx.rung
    for tok in tools(ctx):
        for pat in FORBIDDEN_ALWAYS:
            if re.search(pat, tok):
                out.append(F(ctx, "SDS-S-023", f"{tok!r} is a rung-5/6 operation and must never be pre-approved", line=ln))
        if r < 5:
            for pat in FORBIDDEN_BELOW_5:
                if re.search(pat, tok):
                    out.append(F(ctx, "SDS-S-023", f"{tok!r} is a shared-write operation not permitted below rung 5", line=ln))
        if r < 4:
            if tok in FORBIDDEN_BELOW_4_EXACT or any(re.search(p, tok) for p in FORBIDDEN_BELOW_4):
                out.append(F(ctx, "SDS-S-023", f"{tok!r} is a write operation not permitted below rung 4", line=ln))
    return out


@check("SDS-S-025")
def c_s025(ctx):
    if not ctx.fm_ok or ctx.rung == 0 or not ctx.h2("Instructions"):
        return []
    out, r = [], ctx.rung
    names = {norm_stage(h.text): h for h in ctx.stage_headings()}
    if r <= 3:
        for bad in ("Confirm", "Act", "Communicate"):
            if bad in names:
                out.append(F(ctx, "SDS-S-025", f"Query Skill (rung {r}) must not have a '### {bad}' stage", line=names[bad].line))
    else:
        if "Act" not in names:
            out.append(F(ctx, "SDS-S-025", f"Command Skill (rung {r}) requires a '### Act' stage", line=ctx.h2("Instructions").line))
        if r >= 5 and "Confirm" not in names:
            out.append(F(ctx, "SDS-S-025", f"rung {r} requires a '### Confirm' stage before Act", line=ctx.h2("Instructions").line))
        if "Confirm" in names and "Act" in names and names["Confirm"].line > names["Act"].line:
            out.append(F(ctx, "SDS-S-025", "'### Confirm' must precede '### Act'", line=names["Confirm"].line))
    return out


@check("SDS-S-026")
def c_s026(ctx):
    if not ctx.fm_ok:
        return []
    out, ln = [], ctx.key_lines.get("metadata")
    reg = ctx.fam.shapes | {"freeform"}
    so = ctx.meta.get("shape-out")
    if isinstance(so, str) and so not in reg:
        out.append(F(ctx, "SDS-S-026", f"shape-out {so!r} is not a registered shape or freeform", line=ln))
    si = ctx.meta.get("shape-in")
    if isinstance(si, str):
        for s in [x.strip() for x in si.split(",")]:
            if s not in reg:
                out.append(F(ctx, "SDS-S-026", f"shape-in {s!r} is not a registered shape or freeform", line=ln))
    return out


@check("SDS-S-027")
def c_s027(ctx):
    v = ctx.meta.get("version")
    if ctx.fm_ok and isinstance(v, str) and not SEMVER_RE.match(v):
        return [F(ctx, "SDS-S-027", f"version {v!r} is not semver", line=ctx.key_lines.get("metadata"))]
    return []


@check("SDS-S-028")
def c_s028(ctx):
    reg = ctx.fam.registry
    fam = ctx.meta.get("family")
    if ctx.fm_ok and reg and isinstance(fam, str) and fam != reg.get("family"):
        return [F(ctx, "SDS-S-028", f"metadata.family {fam!r} != registry family {reg.get('family')!r}", line=ctx.key_lines.get("metadata"))]
    return []


@check("SDS-S-030")
def c_s030(ctx):
    if not ctx.raw:
        return []
    out = []
    h2 = [h.text for h in ctx.h2s()]
    for req in REQUIRED_H2:
        if req not in h2:
            out.append(F(ctx, "SDS-S-030", f"missing required section '## {req}'", line=len(ctx.raw)))
    present = [h for h in h2 if h in REQUIRED_H2]
    if present != [r for r in REQUIRED_H2 if r in present]:
        out.append(F(ctx, "SDS-S-030", f"H2 order is {present}; required order is {REQUIRED_H2}", line=ctx.h2s()[0].line if ctx.h2s() else None))
    for h in ctx.h2s():
        if h.text not in REQUIRED_H2 and h.text not in OPTIONAL_H2:
            out.append(F(ctx, "SDS-S-030", f"unexpected section '## {h.text}'", line=h.line, level="WARN"))
        if h.text in REQUIRED_H2 and not ctx.section_text(h).strip():
            out.append(F(ctx, "SDS-S-030", f"section '## {h.text}' is empty", line=h.line))
    return out


@check("SDS-S-031")
def c_s031(ctx):
    ins = ctx.h2("Instructions")
    if ins is None or ctx.rung == 0:
        return []
    out, stages = [], ctx.stage_headings()
    names = []
    for h in stages:
        n = norm_stage(h.text)
        if n not in CANON_ORDER:
            out.append(F(ctx, "SDS-S-031", f"'### {h.text}' is not a stage-vocabulary name", line=h.line))
        else:
            names.append(n)
    required = list(QUERY_REQUIRED) if ctx.rung <= 3 else list(COMMAND_REQUIRED)
    if ctx.rung >= 5:
        required.insert(3, "Confirm")
    for req in required:
        if req not in names:
            out.append(F(ctx, "SDS-S-031", f"missing required stage '### {req}' for a {'Query' if ctx.rung <= 3 else 'Command'} Skill at rung {ctx.rung}", line=ins.line))
    order_idx = [CANON_ORDER.index(n) for n in names if n in CANON_ORDER]
    if order_idx != sorted(order_idx):
        out.append(F(ctx, "SDS-S-031", f"stage order {names} is not the canonical order", line=stages[0].line))
    return out


@check("SDS-S-032")
def c_s032(ctx):
    out = []
    for h in ctx.stage_headings() + ctx.h2s():
        body = ctx.section_text(h).strip()
        if body.startswith("N/A"):
            if not re.match(r"^N/A\s*[—\-:]\s*\S", body):
                out.append(F(ctx, "SDS-S-032", f"'{h.text}' is marked N/A without a reason ('N/A — <reason>')", line=h.line))
    return out


@check("SDS-S-033")
def c_s033(ctx):
    out = []
    for i, line in enumerate(ctx.raw):
        if "[FILL" in line or "skill-name-here" in line or "[Write this LAST" in line:
            out.append(F(ctx, "SDS-S-033", "template residue left in SKILL.md", line=i + 1))
    return out


@check("SDS-S-034")
def c_s034(ctx):
    out = []
    d = ctx.fm.get("description")
    if isinstance(d, str) and MARKETING_RE.search(d):
        out.append(F(ctx, "SDS-S-034", f"marketing language in description: {MARKETING_RE.search(d).group(0)!r}", line=ctx.key_lines.get("description")))
    for ln, line in ctx.prose_lines():
        m = MARKETING_RE.search(line)
        if m:
            out.append(F(ctx, "SDS-S-034", f"marketing language: {m.group(0)!r}", line=ln))
    return out


@check("SDS-S-035")
def c_s035(ctx):
    n = len(ctx.raw)
    if n >= 500:
        return [F(ctx, "SDS-S-035", f"SKILL.md is {n} lines (limit 500)", line=n)]
    if n >= 400:
        return [F(ctx, "SDS-S-035", f"SKILL.md is {n} lines (approaching the 500-line limit)", line=n, level="WARN")]
    return []


@check("SDS-S-036")
def c_s036(ctx):
    h = ctx.h2("@requires")
    if h is None:
        return []
    out = []
    for b in bullets(ctx.section_text(h)):
        if not (b.startswith("REQUIRED:") or b.startswith("OPTIONAL:")):
            out.append(F(ctx, "SDS-S-036", f"@requires bullet must start with REQUIRED: or OPTIONAL: — {b[:60]!r}", line=h.line))
        elif b.startswith("OPTIONAL:") and "(default:" not in b and not re.match(r"^OPTIONAL:\s*none\b", b):
            out.append(F(ctx, "SDS-S-036", f"OPTIONAL input lacks '(default: ...)': {b[:60]!r}", line=h.line))
    return out


@check("SDS-S-037")
def c_s037(ctx):
    h = ctx.h2("@requires")
    if h is None:
        return []
    n = sum(1 for b in bullets(ctx.section_text(h)) if b.startswith("REQUIRED:"))
    if n == 0:
        return [F(ctx, "SDS-S-037", "no REQUIRED input declared", line=h.line)]
    if n > 5:
        return [F(ctx, "SDS-S-037", f"{n} REQUIRED inputs — split the skill (SDS-C-052)", line=h.line, level="WARN")]
    return []


@check("SDS-S-038")
def c_s038(ctx):
    h = ctx.h2("@returns")
    so = ctx.meta.get("shape-out")
    if h is None or not isinstance(so, str):
        return []
    out, text = [], ctx.section_text(h)
    if f"Shape: `{so}`" not in text:
        out.append(F(ctx, "SDS-S-038", f"@returns must contain \"Shape: `{so}`\" (the declared shape-out)", line=h.line))
    if so in ctx.fam.shapes and not re.search(rf"(?<![\w./-])kit/shapes/{re.escape(so)}\.schema\.json", text):
        out.append(F(ctx, "SDS-S-038", f"@returns must reference the literal kit/shapes/{so}.schema.json (family-root-relative)", line=h.line))
    if so == "freeform" and "kit/shapes/" in text:
        out.append(F(ctx, "SDS-S-038", "shape-out is freeform but @returns references a kit/shapes/ schema", line=h.line, level="WARN"))
    return out


def throws_codes(ctx: SkillCtx) -> list[str]:
    h = ctx.h2("@throws")
    if h is None:
        return []
    codes = []
    for b in bullets(ctx.section_text(h)):
        m = re.match(r"^`([a-z0-9]+(?:-[a-z0-9]+)*)`:", b)
        if m:
            codes.append(m.group(1))
    return codes


def eval_rows(ctx: SkillCtx) -> list[dict]:
    rows = (ctx.eval_doc or {}).get("rows")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


@check("SDS-S-039")
def c_s039(ctx):
    h = ctx.h2("@throws")
    if h is None:
        return []
    out, bl = [], bullets(ctx.section_text(h))
    if not bl:
        out.append(F(ctx, "SDS-S-039", "@throws has no entries", line=h.line))
    codes = []
    for b in bl:
        m = re.match(r"^`([a-z0-9]+(?:-[a-z0-9]+)*)`:", b)
        if not m:
            out.append(F(ctx, "SDS-S-039", f"@throws bullet must be \"- `kebab-code`: ...\" — {b[:50]!r}", line=h.line))
        else:
            if m.group(1) in codes:
                out.append(F(ctx, "SDS-S-039", f"duplicate @throws code {m.group(1)!r}", line=h.line))
            codes.append(m.group(1))
    tested = set()
    for r in eval_rows(ctx):
        exp = r.get("expected") or {}
        fc = exp.get("failureCode")
        if fc:
            tested.add(fc)
            if fc not in codes:
                out.append(F(ctx, "SDS-S-039", f"eval row {r.get('name')!r} uses failureCode {fc!r} not declared in @throws {codes}", "evals/" + (ctx.eval_path.name if ctx.eval_path else ""), ctx.eval_row_lines.get(r.get("name"))))
    for c in codes:
        if c not in tested:
            out.append(F(ctx, "SDS-S-039", f"@throws code {c!r} is exercised by no eval row", line=h.line, level="INFO"))
    if ctx.rung >= 5 and not any(re.search(r"-declined$|-refused$|^confirm-", c) for c in codes):
        out.append(F(ctx, "SDS-S-039", "rung >= 5 skill should declare a declined/refused confirmation code", line=h.line, level="WARN"))
    return out


@check("SDS-S-040")
def c_s040(ctx):
    h = ctx.h2("@example")
    if h is None:
        return []
    out, text = [], ctx.section_text(h)
    if "**Input:**" not in text:
        out.append(F(ctx, "SDS-S-040", "@example lacks a '**Input:**' block", line=h.line))
    if not re.search(r"\*\*(Output|Result)", text):
        out.append(F(ctx, "SDS-S-040", "@example lacks an '**Output**'/'**Result**' block", line=h.line))
    return out


@check("SDS-S-041")
def c_s041(ctx):
    dec = ctx.stage("Decide")
    if dec is None:
        return []
    dtext = ctx.section_text(dec)
    if not (re.search(r"\*\*If .*", dtext) and "stop here" in dtext):
        return []
    out = []
    for name in ("Confirm", "Act"):
        h = ctx.stage(name)
        if h is None:
            continue
        first = next((l.strip() for l in ctx.section_text(h).splitlines() if l.strip()), "")
        if not first.startswith("Only reached when"):
            out.append(F(ctx, "SDS-S-041", f"conditional Act path: '### {name}' must begin 'Only reached when <condition>.'", line=h.line))
    ret = ctx.h2("@returns")
    if ret and "path" not in ctx.section_text(ret).lower():
        out.append(F(ctx, "SDS-S-041", "conditional Act path: @returns must describe both paths", line=ret.line))
    return out


@check("SDS-S-043")
def c_s043(ctx):
    if ctx.headings and not (ctx.headings[0].level == 1 and ctx.headings[0].text == ctx.name):
        return [F(ctx, "SDS-S-043", f"first heading should be '# {ctx.name}'", line=ctx.headings[0].line)]
    return []


@check("SDS-S-050")
def c_s050(ctx):
    if ctx.rung < 5:
        return []
    conf, act = ctx.stage("Confirm"), ctx.stage("Act")
    if conf is None:
        return []
    out, gate = [], "kit/shared/gates/medium.md" if ctx.rung == 5 else "kit/shared/gates/high.md"
    if gate not in ctx.section_text(conf):
        out.append(F(ctx, "SDS-S-050", f"rung-{ctx.rung} Confirm must cite {gate}", line=conf.line))
    if act and act.line < conf.line:
        out.append(F(ctx, "SDS-S-050", "Confirm must precede Act", line=conf.line))
    return out


@check("SDS-S-051")
def c_s051(ctx):
    if ctx.rung < 5:
        return []
    out = []
    for tok in tools(ctx):
        m = SCRIPT_TOKEN_RE.match(tok)
        if m and re.search(r"apply|edit|push|merge|delete|publish|mutate", Path(m.group(1)).stem):
            out.append(F(ctx, "SDS-S-051", f"allowed-tools pre-approves {m.group(1)}, whose name suggests it performs the mutation", line=ctx.key_lines.get("allowed-tools")))
    for sf in script_files(ctx):
        text = sf.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines()):
            if ("subprocess" in line or "os.system" in line or sf.suffix == ".sh") and MUTATING_SCRIPT_RE.search(line):
                out.append(F(ctx, "SDS-S-051", f"bundled script performs a mutating command: {line.strip()[:60]!r}", f"scripts/{sf.name}", i + 1))
    return out


@check("SDS-S-053")
def c_s053(ctx):
    if ctx.rung < 4:
        return []
    act = ctx.stage("Act")
    if act is None:
        return []
    out, text = [], ctx.section_text(act)
    if "**Checkpoint**" not in text:
        out.append(F(ctx, "SDS-S-053", "Act lacks a '**Checkpoint**' label", line=act.line))
    elif not ("pending" in text and "completed" in text):
        out.append(F(ctx, "SDS-S-053", "Checkpoint must describe the two-phase pending -> completed record", line=act.line))
    if f".skills-state/{ctx.name}/" not in text:
        out.append(F(ctx, "SDS-S-053", f"Checkpoint must name .skills-state/{ctx.name}/<key>.json", line=act.line))
    return out


@check("SDS-S-054")
def c_s054(ctx):
    if ctx.rung < 4:
        return []
    act = ctx.stage("Act")
    if act is not None and "**Compensating action**" not in ctx.section_text(act):
        return [F(ctx, "SDS-S-054", "Act lacks a '**Compensating action**' label", line=act.line)]
    return []


@check("SDS-S-062")
def c_s062(ctx):
    out = []
    for sf in script_files(ctx):
        if not re.match(r"^[a-z]+_[a-z0-9_]+\.(py|sh)$", sf.name) or sf.stem in {"utils", "helpers", "common"}:
            out.append(F(ctx, "SDS-S-062", f"script name {sf.name!r} is not snake_case verb_noun", f"scripts/{sf.name}", level="INFO"))
    return out


@check("SDS-S-063")
def c_s063(ctx):
    out = []
    for sf in script_files(ctx):
        rel = f"scripts/{sf.name}"
        text = sf.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if not lines or not lines[0].startswith("#!"):
            out.append(F(ctx, "SDS-S-063", "script lacks a shebang line", rel, 1))
        if sf.suffix == ".py":
            try:
                if not ast.get_docstring(ast.parse(text)):
                    out.append(F(ctx, "SDS-S-063", "script lacks a module docstring", rel, 1))
            except SyntaxError as e:
                out.append(F(ctx, "SDS-S-063", f"script has a syntax error: {e.msg}", rel, e.lineno))
        else:
            if not any(l.startswith("#") and not l.startswith("#!") for l in lines[:5]):
                out.append(F(ctx, "SDS-S-063", "shell script lacks a leading comment block", rel, 1))
        if "ERROR:" not in text and "sys.exit" not in text and "exit " not in text:
            out.append(F(ctx, "SDS-S-063", "script has no visible ERROR:/exit-code handling", rel, 1, level="WARN"))
    return out


@check("SDS-S-065")
def c_s065(ctx):
    if ctx.rung < 3:
        return []
    out = []
    for sf in script_files(ctx):
        text = sf.read_text(encoding="utf-8", errors="replace")
        if EXTERNAL_CALL_RE.search(text) and not re.search(r"--[a-z0-9-]+-file\b", text):
            out.append(F(ctx, "SDS-S-065", "script calls an external system but exposes no --<thing>-file fixture flag", f"scripts/{sf.name}", 1))
    return out


@check("SDS-S-066")
def c_s066(ctx):
    return [F(ctx, "SDS-S-066", "script is not executable (chmod +x)", f"scripts/{sf.name}")
            for sf in script_files(ctx) if not os.access(sf, os.X_OK)]


@check("SDS-S-067")
def c_s067(ctx):
    body = ctx.body_text() + str(ctx.fm.get("allowed-tools", ""))
    return [F(ctx, "SDS-S-067", f"scripts/{sf.name} is never referenced from SKILL.md", f"scripts/{sf.name}")
            for sf in script_files(ctx) if sf.name not in body]


def reference_files(ctx: SkillCtx) -> list[Path]:
    d = ctx.dir / "references"
    return sorted(p for p in d.iterdir() if p.is_file()) if d.is_dir() else []


@check("SDS-S-071")
def c_s071(ctx):
    out = []
    for rf in reference_files(ctx):
        for i, line in enumerate(rf.read_text(encoding="utf-8", errors="replace").splitlines()):
            if re.search(r"references/[\w./-]+", line):
                out.append(F(ctx, "SDS-S-071", "reference file links to another references/ file (keep one level deep)", f"references/{rf.name}", i + 1))
    return out


@check("SDS-S-072")
def c_s072(ctx):
    out, prose = [], ctx.prose_lines()
    text = " ".join(l for _, l in prose)
    for sent in re.split(r"(?<=[.;])\s+", text):
        if "references/" in sent and not re.search(r"\b(if|only|when|unless)\b", sent, re.I):
            ln = next((n for n, l in prose if "references/" in l), None)
            out.append(F(ctx, "SDS-S-072", f"references/ pointer is unconditional: {sent.strip()[:70]!r}", line=ln))
    return out


@check("SDS-S-073")
def c_s073(ctx):
    body = ctx.body_text()
    return [F(ctx, "SDS-S-073", f"references/{rf.name} is never linked from SKILL.md", f"references/{rf.name}")
            for rf in reference_files(ctx) if f"references/{rf.name}" not in body]


@check("SDS-S-080")
def c_s080(ctx):
    out, d = [], ctx.dir / "assets"
    if not d.is_dir():
        return out
    for p in d.glob("*.schema.json"):
        try:
            title = json.loads(p.read_text()).get("title")
        except (OSError, json.JSONDecodeError):
            continue
        if title in ctx.fam.shapes:
            out.append(F(ctx, "SDS-S-080", f"assets/{p.name} duplicates family shape {title!r}; reference kit/shapes/ instead", f"assets/{p.name}"))
    return out


@check("SDS-S-081")
def c_s081(ctx):
    d = ctx.dir / "assets"
    if not d.is_dir():
        return []
    body = ctx.body_text()
    return [F(ctx, "SDS-S-081", f"assets/{p.name} is not named in @requires or Instructions", f"assets/{p.name}")
            for p in sorted(d.iterdir()) if p.is_file() and p.name not in body]


# ---- evals ---------------------------------------------------------------
def ev(ctx: SkillCtx, rid: str, msg: str, row: str | None = None, level: str | None = None) -> Finding:
    sub = "evals/" + (ctx.eval_path.name if ctx.eval_path else f"{ctx.name}.eval.yaml")
    return F(ctx, rid, msg, sub, ctx.eval_row_lines.get(row) if row else None, level)


@check("SDS-S-090")
def c_s090(ctx):
    if ctx.eval_path is None:
        return []
    if ctx.eval_error:
        return [ev(ctx, "SDS-S-090", f"eval file does not parse: {ctx.eval_error}")]
    out, doc = [], ctx.eval_doc
    if doc.get("skill") != ctx.name:
        out.append(ev(ctx, "SDS-S-090", f"skill field {doc.get('skill')!r} != {ctx.name!r}"))
    rows = doc.get("rows")
    if not isinstance(rows, list) or not rows:
        out.append(ev(ctx, "SDS-S-090", "rows missing or empty"))
        return out
    seen = set()
    for r in rows:
        if not isinstance(r, dict) or "name" not in r:
            out.append(ev(ctx, "SDS-S-090", "row without a name"))
            continue
        n = r["name"]
        if n in seen:
            out.append(ev(ctx, "SDS-S-090", f"duplicate row name {n!r}", n))
        seen.add(n)
        exp = r.get("expected")
        if not isinstance(exp, dict):
            out.append(ev(ctx, "SDS-S-090", f"row {n!r} lacks an expected block", n))
            continue
        kind = exp.get("kind")
        if kind not in ("success", "failure", "not-applicable"):
            out.append(ev(ctx, "SDS-S-090", f"row {n!r} expected.kind {kind!r} invalid", n))
        if kind == "not-applicable" and not str(exp.get("reason", "")).strip():
            out.append(ev(ctx, "SDS-S-090", f"row {n!r} is not-applicable without a reason", n))
        if kind == "failure" and not exp.get("failureCode"):
            out.append(ev(ctx, "SDS-S-090", f"row {n!r} is a failure row without failureCode", n))
    for extra in ctx.eval_extra:
        if extra not in (None, {}, []):
            out.append(ev(ctx, "SDS-S-090", "extra YAML document after '---' is not empty (smoke section must be comments only)", level="WARN"))
    return out


@check("SDS-S-091")
def c_s091(ctx):
    out = []
    so = ctx.meta.get("shape-out")
    for r in eval_rows(ctx):
        exp = r.get("expected") or {}
        if exp.get("kind") != "success":
            continue
        a = exp.get("assertions")
        if not a:
            out.append(ev(ctx, "SDS-S-091", f"success row {r.get('name')!r} has no assertions", r.get("name")))
        if so in ctx.fam.shapes and "shape" not in exp:
            out.append(ev(ctx, "SDS-S-091", f"success row {r.get('name')!r} lacks a shape field ({so})", r.get("name"), level="INFO"))
    return out


def row_command(r: dict) -> str:
    inp = r.get("input")
    if isinstance(inp, dict):
        return " ".join(str(v) for v in inp.values())
    return str(inp) if inp is not None else ""


@check("SDS-S-092")
def c_s092(ctx):
    if ctx.rung < 3:
        return []
    return [ev(ctx, "SDS-S-092", f"required row {r.get('name')!r} invokes a live external system", r.get("name"))
            for r in eval_rows(ctx) if (r.get("expected") or {}).get("kind") != "not-applicable" and LIVE_CALL_RE.search(row_command(r))]


@check("SDS-S-093")
def c_s093(ctx):
    d = ctx.dir / "evals" / "fixtures"
    if not d.is_dir():
        return []
    return [F(ctx, "SDS-S-093", f"frozen fixture {p.name!r} should be named frozen-<source>-<what>.json", f"evals/fixtures/{p.name}")
            for p in d.glob("frozen*") if not re.match(r"^frozen-[a-z0-9]+-[a-z0-9-]+\.json$", p.name)]


@check("SDS-S-094")
def c_s094(ctx):
    if ctx.eval_doc is None or not ctx.fm_ok:
        return []
    so, si = ctx.meta.get("shape-out"), ctx.meta.get("shape-in")
    required = so == si and so in ctx.fam.shapes
    rows = {r.get("name"): r for r in eval_rows(ctx)}
    row = rows.get("fixed-point")
    if row is None:
        return [ev(ctx, "SDS-S-094", "no 'fixed-point' row (required as success, or not-applicable with reason)")]
    kind = (row.get("expected") or {}).get("kind")
    if required and kind != "success":
        return [ev(ctx, "SDS-S-094", f"shape-out == shape-in == {so}: fixed-point row must be a success test", "fixed-point")]
    if not required and kind == "success":
        return [ev(ctx, "SDS-S-094", "fixed-point row is a success test but the skill is not self-composable — verify", "fixed-point", level="WARN")]
    return []


@check("SDS-S-095")
def c_s095(ctx):
    if ctx.eval_doc is None or not ctx.fm_ok:
        return []
    so = ctx.meta.get("shape-out")
    rows = [r for r in eval_rows(ctx) if str(r.get("name", "")).startswith("mutation-fixture")]
    if so == "finding-list":
        ok = [r for r in rows if (r.get("expected") or {}).get("kind") == "success" and "evals/fixtures/" in row_command(r)]
        if not ok:
            return [ev(ctx, "SDS-S-095", "finding-list skill needs a success 'mutation-fixture*' row whose command references evals/fixtures/")]
        return []
    if not rows:
        return [ev(ctx, "SDS-S-095", "no 'mutation-fixture' row (must exist as not-applicable with reason)")]
    return [ev(ctx, "SDS-S-095", f"row {r.get('name')!r} should be not-applicable for a non-finding-list skill", r.get("name"))
            for r in rows if (r.get("expected") or {}).get("kind") == "success"]


def fixture_refs(ctx: SkillCtx) -> list[tuple[str, str | None]]:
    refs = []
    for r in eval_rows(ctx):
        for m in re.finditer(r"evals/fixtures/[\w./-]+", row_command(r)):
            refs.append((m.group(0).rstrip(STRIP_TRAIL), r.get("name")))
    return refs


@check("SDS-S-096")
def c_s096(ctx):
    d = ctx.dir / "evals" / "fixtures"
    out = []
    for ref, row in fixture_refs(ctx):
        rel = ref[len("evals/fixtures/"):]
        if (ctx.dir / ref).exists():
            continue
        if gitignored(d, rel):
            builders = list(d.glob("build-*.sh"))
            if not builders:
                out.append(ev(ctx, "SDS-S-096", f"generated fixture {ref} has no evals/fixtures/build-*.sh generator", row))
            for b in builders:
                if not os.access(b, os.X_OK):
                    out.append(F(ctx, "SDS-S-096", f"generator {b.name} is not executable", f"evals/fixtures/{b.name}", level="WARN"))
        else:
            out.append(ev(ctx, "SDS-S-096", f"fixture {ref} does not exist and is not a gitignored generated fixture", row))
    if d.is_dir():
        for git_dir in d.rglob(".git"):
            rel = str(git_dir.parent.relative_to(d))
            if not gitignored(d, rel):
                out.append(F(ctx, "SDS-S-096", f"nested git repository {rel}/ is not gitignored (would become a gitlink)", f"evals/fixtures/{rel}"))
        for sub in d.iterdir():
            if sub.is_dir() and not any(sub.iterdir()):
                out.append(F(ctx, "SDS-S-096", f"empty fixture directory {sub.name}/ needs a .gitkeep", f"evals/fixtures/{sub.name}"))
    return out


@check("SDS-S-097")
def c_s097(ctx):
    d = ctx.dir / "evals" / "fixtures"
    if not d.is_dir() or not ctx.eval_raw:
        return []
    text, out = "\n".join(ctx.eval_raw), []
    for p in sorted(d.iterdir()):
        if p.name in FIXTURE_RESERVED or p.name.startswith("build-"):
            continue
        if gitignored(d, p.name):
            continue
        if f"evals/fixtures/{p.name}" not in text:
            out.append(F(ctx, "SDS-S-097", f"fixture {p.name} is referenced by no row or smoke test", f"evals/fixtures/{p.name}"))
    return out


@check("SDS-S-098")
def c_s098(ctx):
    out = []
    for r in eval_rows(ctx):
        cmd = row_command(r)
        for tok in cmd.split():
            t = tok.strip(STRIP_TRAIL + "\"'")
            if t.startswith("/") or t.startswith("~"):
                out.append(ev(ctx, "SDS-S-098", f"row {r.get('name')!r} uses an absolute path {t!r}; use a fixture inside the skill", r.get("name"), level="WARN"))
            elif t.startswith("../") or (t.startswith("skills/") and not t.startswith(f"skills/{ctx.name}/")):
                out.append(ev(ctx, "SDS-S-098", f"row {r.get('name')!r} references a path outside the skill: {t!r}", r.get("name")))
    return out


@check("SDS-S-099")
def c_s099(ctx):
    if ctx.eval_doc is None:
        return []
    rows, out = eval_rows(ctx), []
    kind = lambda r: (r.get("expected") or {}).get("kind")
    if not any(str(r.get("name", "")).startswith("happy-path") and kind(r) == "success" for r in rows):
        out.append(ev(ctx, "SDS-S-099", "no success 'happy-path*' row"))
    b = [r for r in rows if str(r.get("name", "")).startswith("boundary-")]
    if len(b) < 2:
        out.append(ev(ctx, "SDS-S-099", "fewer than two 'boundary-*' rows"))
    if not any(re.search(r"empty|zero|none|no-|minimal", r["name"]) and kind(r) == "success" for r in b):
        out.append(ev(ctx, "SDS-S-099", "no empty/zero/minimal boundary row with kind success"))
    if not any(re.search(r"malformed|invalid|missing|not-a|bad", r["name"]) and kind(r) == "failure" for r in b):
        out.append(ev(ctx, "SDS-S-099", "no malformed/invalid boundary row with kind failure"))
    if not any(str(r.get("name", "")).startswith("contract-with-") for r in rows):
        out.append(ev(ctx, "SDS-S-099", "no 'contract-with-*' row (may be not-applicable with reason)"))
    return out


@check("SDS-S-100")
def c_s100(ctx):
    if not ctx.fm_ok:
        return []
    out, body = [], ctx.body_text()
    for m in re.finditer(r"\.skills-state/([\w-]+)/", body):
        if m.group(1) != ctx.name:
            out.append(F(ctx, "SDS-S-100", f".skills-state path names another skill: {m.group(1)!r}", line=body[:m.start()].count("\n") + ctx.fm_end + 1))
    if ctx.rung >= 4 and f".skills-state/{ctx.name}/" not in body:
        out.append(F(ctx, "SDS-S-100", f"Command Skill must reference .skills-state/{ctx.name}/", line=1))
    return out


# ---- path convention (F-030/F-031 per skill) --------------------------------
def scan_paths(ctx: SkillCtx, sub: str, lines: list[str], yaml_mode: bool) -> list[Finding]:
    out, in_fence = [], False
    for i, line in enumerate(lines):
        if not yaml_mode and re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
        is_comment = yaml_mode and line.lstrip().startswith("#")
        for tok in iter_path_refs(line):
            if tok.startswith("../"):
                out.append(F(ctx, "SDS-F-030", f"parent-relative path {tok!r}; use a family-root-relative path", sub, i + 1, "INFO" if is_comment else None))
            elif tok.startswith("kit/"):
                if "<" in tok or ">" in tok:
                    continue
                if not (ctx.fam.root / tok).exists():
                    out.append(F(ctx, "SDS-F-030", f"referenced {tok} does not exist under the family root", sub, i + 1, "INFO" if is_comment else None))
            elif tok.startswith(("scripts/", "references/", "assets/")):
                if "<" in tok or ">" in tok or in_fence and yaml_mode:
                    continue
                if not (ctx.dir / tok).exists() and not (ctx.dir / tok).is_dir():
                    out.append(F(ctx, "SDS-F-031", f"referenced {tok} does not exist in the skill", sub, i + 1, "INFO" if is_comment else None))
        for m in re.finditer(r"(?<![\w/.-])(shapes|shared|templates|registry)/[\w.-]", line):
            out.append(F(ctx, "SDS-F-030", f"bare '{m.group(1)}/' reference; write kit/{m.group(1)}/...", sub, i + 1, "INFO" if is_comment else None))
    return out


@check("SDS-F-030")
def c_f030(ctx):
    out = scan_paths(ctx, "SKILL.md", ctx.raw, False)
    if ctx.eval_path:
        out += scan_paths(ctx, "evals/" + ctx.eval_path.name, ctx.eval_raw, True)
    for rf in reference_files(ctx):
        out += scan_paths(ctx, f"references/{rf.name}", rf.read_text(encoding="utf-8", errors="replace").splitlines(), False)
    return [f for f in out if f.rule_id == "SDS-F-030"]


@check("SDS-F-031")
def c_f031(ctx):
    out = scan_paths(ctx, "SKILL.md", ctx.raw, False)
    if ctx.eval_path:
        out += scan_paths(ctx, "evals/" + ctx.eval_path.name, ctx.eval_raw, True)
        for r in eval_rows(ctx):
            for m in re.finditer(r"scripts/[\w./-]+", row_command(r)):
                if not (ctx.dir / m.group(0)).exists():
                    out.append(ev(ctx, "SDS-F-031", f"row {r.get('name')!r} runs {m.group(0)} which does not exist", r.get("name")))
    return [f for f in out if f.rule_id == "SDS-F-031"]


# ---- registry per skill ----------------------------------------------------
def registry_entry(ctx: SkillCtx) -> dict | None:
    reg = ctx.fam.registry or {}
    for e in reg.get("skills", []) or []:
        if isinstance(e, dict) and e.get("name") == ctx.name:
            return e
    return None


@check("SDS-F-013")
def c_f013(ctx):
    if ctx.fam.registry is None or not ctx.fm_ok:
        return []
    regp = relpath(ctx.fam.root, ctx.fam.registry_path)
    entries = [e for e in ctx.fam.registry.get("skills", []) if isinstance(e, dict) and e.get("name") == ctx.name]
    if len(entries) != 1:
        return [Finding("SDS-F-013", "ERROR", regp, None, f"{ctx.name}: expected exactly one registry entry, found {len(entries)}")]
    e, out = entries[0], []
    for k in ("version", "effect-tier", "tier", "shape-out", "shape-in"):
        if e.get(k) != ctx.meta.get(k):
            out.append(Finding("SDS-F-013", "ERROR", regp, None, f"{ctx.name}: registry {k}={e.get(k)!r} != frontmatter {ctx.meta.get(k)!r}"))
    return out


@check("SDS-F-016")
def c_f016(ctx):
    e = registry_entry(ctx)
    if e is None or not ctx.fm_ok:
        return []
    a = " ".join(str(e.get("description", "")).split())
    b = " ".join(str(ctx.fm.get("description", "")).split())
    if a != b:
        return [Finding("SDS-F-016", "WARN", relpath(ctx.fam.root, ctx.fam.registry_path), None, f"{ctx.name}: registry description differs from frontmatter description")]
    return []


@check("SDS-K-043")
def c_k043(ctx):
    ln = ctx.key_lines.get("allowed-tools")
    return [F(ctx, "SDS-K-043", f"{tok!r} matches no shared tool profile; consider adding it to kit/shared/tool-profiles/", line=ln, level="INFO")
            for tok in tools(ctx) if re.match(r"^Bash\((git|gh) ", tok) and tok not in ctx.fam.profile_tokens]


@check("SDS-F-061")
def c_f061(ctx):
    if not ctx.fam.glossary_terms:
        return []
    out, targets = [], []
    d = ctx.fm.get("description")
    if isinstance(d, str):
        targets.append((ctx.key_lines.get("description"), d))
    for h in ctx.headings:
        targets.append((h.line, h.text))
    req = ctx.h2("@requires")
    if req:
        for b in bullets(ctx.section_text(req)):
            targets.append((req.line, b))
    ret = ctx.h2("@returns")
    if ret:
        for l in ctx.section_text(ret).splitlines():
            if l.startswith("Shape:"):
                targets.append((ret.line, l))
    for ln, text in targets:
        for term in ctx.fam.glossary_terms:
            if re.search(rf"\b{re.escape(term)}\b(?!\.json|\sfile)", text, re.I):
                out.append(F(ctx, "SDS-F-061", f"glossary do-not-use term {term!r} in: {text.strip()[:60]!r}", line=ln))
    return out


# --------------------------------------------------------------------------
# Family-scope checks
# --------------------------------------------------------------------------
def FF(fam: FamilyCtx, rid: str, msg: str, sub: str, level: str | None = None) -> Finding:
    return Finding(rid, level or LEVEL_FOR[RULES[rid][1]], sub, None, msg)


@check("SDS-F-001", "family")
def f_001(fam):
    return [FF(fam, "SDS-F-001", f"family root lacks {d}/", d) for d in ("kit", "skills", "docs") if not (fam.root / d).is_dir()]


@check("SDS-F-002", "family")
def f_002(fam):
    out, sd = [], fam.root / "skills"
    if not sd.is_dir():
        return out
    for e in sorted(sd.iterdir()):
        if not e.is_dir() or not (e / "SKILL.md").exists():
            out.append(FF(fam, "SDS-F-002", f"skills/{e.name} is not a skill package (no SKILL.md)", f"skills/{e.name}"))
    return out


@check("SDS-F-010", "family")
def f_010(fam):
    canon = fam.kit / "registry" / "marketplace.json"
    if fam.registry_path is None or fam.registry_path.resolve() != canon.resolve():
        return [FF(fam, "SDS-F-010", f"canonical registry kit/registry/marketplace.json not found (using {relpath(fam.root, fam.registry_path) if fam.registry_path else 'nothing'})", relpath(fam.root, canon))]
    return []


@check("SDS-F-011", "family")
def f_011(fam):
    if fam.registry_error:
        return [FF(fam, "SDS-F-011", fam.registry_error, "kit/registry")]
    schema_p = fam.kit / "registry" / "marketplace.schema.json"
    if not schema_p.exists() or jsonschema is None:
        return [FF(fam, "SDS-F-011", "marketplace.schema.json missing or jsonschema unavailable", "kit/registry/marketplace.schema.json")]
    try:
        v = jsonschema.Draft202012Validator(json.loads(schema_p.read_text()))
        return [FF(fam, "SDS-F-011", f"registry violates schema at /{'/'.join(map(str, e.path))}: {e.message[:80]}", relpath(fam.root, fam.registry_path))
                for e in sorted(v.iter_errors(fam.registry), key=lambda e: list(e.path))]
    except (json.JSONDecodeError, jsonschema.SchemaError) as e:
        return [FF(fam, "SDS-F-011", f"schema unusable: {e}", "kit/registry/marketplace.schema.json")]


@check("SDS-F-012", "family")
def f_012(fam):
    out = []
    for e in (fam.registry or {}).get("skills", []) or []:
        for k in ("name", "description", "version", "effect-tier", "tier", "shape-out", "shape-in"):
            if not isinstance(e, dict) or k not in e:
                out.append(FF(fam, "SDS-F-012", f"entry {e.get('name') if isinstance(e, dict) else e!r} lacks {k}", relpath(fam.root, fam.registry_path)))
    return out


@check("SDS-F-015", "family")
def f_015(fam):
    if fam.registry is None:
        return []
    out, regp, sd = [], relpath(fam.root, fam.registry_path), fam.root / "skills"
    names = set()
    for e in fam.registry.get("skills", []) or []:
        if not isinstance(e, dict):
            continue
        names.add(e.get("name"))
        st = e.get("status", "planned")
        exists = (sd / str(e.get("name")) / "SKILL.md").exists()
        if st not in ("planned", "built"):
            out.append(FF(fam, "SDS-F-015", f"{e.get('name')}: status {st!r} must be planned or built", regp))
        elif st == "built" and not exists:
            out.append(FF(fam, "SDS-F-015", f"{e.get('name')}: status built but skills/{e.get('name')}/ does not exist", regp))
        elif st == "planned" and not exists and fam.all_mode:
            out.append(FF(fam, "SDS-F-015", f"{e.get('name')}: planned, not yet built", regp, "INFO"))
    if fam.all_mode and sd.is_dir():
        for d in sorted(sd.iterdir()):
            if (d / "SKILL.md").exists() and d.name not in names:
                out.append(FF(fam, "SDS-F-015", f"skills/{d.name} has no registry entry", regp))
    return out


@check("SDS-F-020", "family")
def f_020(fam):
    gi = fam.root / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if not any(l.strip().rstrip("/") == ".skills-state" for l in lines):
        return [FF(fam, "SDS-F-020", "family-root .gitignore must contain `.skills-state/`", ".gitignore")]
    return []


@check("SDS-F-021", "family")
def f_021(fam):
    try:
        res = subprocess.run(["git", "ls-files", ".skills-state"], cwd=fam.root, capture_output=True, text=True, timeout=10)
        tracked = [l for l in res.stdout.splitlines() if l.strip()] if res.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        tracked = []
    return [FF(fam, "SDS-F-021", f"runtime state file is tracked: {t}", t) for t in tracked]


@check("SDS-F-040", "family")
def f_040(fam):
    return [FF(fam, "SDS-F-040", f"{e.get('name')}: version {e.get('version')!r} is not semver", relpath(fam.root, fam.registry_path))
            for e in (fam.registry or {}).get("skills", []) or [] if isinstance(e, dict) and not SEMVER_RE.match(str(e.get("version", "")))]


@check("SDS-F-042", "family")
def f_042(fam):
    if fam.registry is not None and not isinstance(fam.registry.get("sds"), str):
        return [FF(fam, "SDS-F-042", f"registry lacks top-level \"sds\" conformance target (e.g. \"{SDS_TARGET}\")", relpath(fam.root, fam.registry_path))]
    return []


@check("SDS-F-060", "family")
def f_060(fam):
    if not (fam.kit / "shared" / "glossary.md").exists():
        return [FF(fam, "SDS-F-060", "kit/shared/glossary.md is missing", "kit/shared/glossary.md")]
    return []


@check("SDS-K-001", "family")
def k_001(fam):
    req = ["templates", "evals/TEMPLATE.eval.yaml", "shapes", "shared/glossary.md", "shared/gates",
           "shared/tool-profiles", "registry", "scripts/lint-skill.py"]
    return [FF(fam, "SDS-K-001", f"kit/ lacks {r}", f"kit/{r}") for r in req if not (fam.kit / r).exists()]


@check("SDS-K-002", "family")
def k_002(fam):
    out = []
    for g in ("HOW-TO-BUILD-A-SKILL.md", "PRIMITIVES.md"):
        p = fam.kit / g
        if p.exists():
            head = "\n".join(p.read_text(encoding="utf-8").splitlines()[:12]).lower()
            if "non-normative" not in head:
                out.append(FF(fam, "SDS-K-002", f"{g} does not open with a non-normative banner", f"kit/{g}"))
    return out


@check("SDS-K-010", "family")
def k_010(fam):
    out = []
    for t in sorted((fam.kit / "templates").glob("SKILL.md.*.template")):
        lines = t.read_text(encoding="utf-8").splitlines()
        _, end = split_frontmatter(lines)
        hs = parse_headings(lines, end)
        h2 = [h.text for h in hs if h.level == 2 and h.text in REQUIRED_H2]
        if h2 != REQUIRED_H2:
            out.append(FF(fam, "SDS-K-010", f"H2 order {h2} != normative {REQUIRED_H2}", f"kit/templates/{t.name}"))
        idx = [CANON_ORDER.index(norm_stage(h.text)) for h in hs if h.level == 3 and norm_stage(h.text) in CANON_ORDER]
        if idx != sorted(idx):
            out.append(FF(fam, "SDS-K-010", "H3 stage order is not canonical", f"kit/templates/{t.name}"))
    return out


@check("SDS-K-020", "family")
def k_020(fam):
    out = []
    for p in sorted((fam.kit / "shapes").glob("*.schema.json")):
        rel, name = f"kit/shapes/{p.name}", p.name[: -len(".schema.json")]
        try:
            s = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            out.append(FF(fam, "SDS-K-020", f"invalid JSON: {e}", rel))
            continue
        if s.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            out.append(FF(fam, "SDS-K-020", "$schema must be JSON Schema 2020-12", rel))
        if s.get("title") != name:
            out.append(FF(fam, "SDS-K-020", f"title {s.get('title')!r} != {name!r}", rel))
        if s.get("$id") != f"https://skills.local/shapes/{name}.schema.json":
            out.append(FF(fam, "SDS-K-020", "$id must be https://skills.local/shapes/<name>.schema.json", rel))
        if jsonschema is not None:
            try:
                jsonschema.Draft202012Validator.check_schema(s)
            except jsonschema.SchemaError as e:
                out.append(FF(fam, "SDS-K-020", f"schema invalid: {e.message[:80]}", rel))
    return out


@check("SDS-K-030", "family")
def k_030(fam):
    out = []
    for p in sorted((fam.kit / "shared" / "gates").glob("*.md")):
        text, rel = p.read_text(encoding="utf-8"), f"kit/shared/gates/{p.name}"
        for fld in ("**What:**", "**Why:**"):
            if fld not in text:
                out.append(FF(fam, "SDS-K-030", f"gate lacks {fld} field", rel))
        if "**Reversible" not in text and "**Compensating action" not in text:
            out.append(FF(fam, "SDS-K-030", "gate lacks a Reversible or Compensating action field", rel))
    return out


@check("SDS-K-040", "family")
def k_040(fam):
    out = []
    for p in sorted((fam.kit / "shared" / "tool-profiles").glob("*.yaml")):
        rel = f"kit/shared/tool-profiles/{p.name}"
        try:
            d = load_yaml_file(p) or {}
        except yaml.YAMLError as e:
            out.append(FF(fam, "SDS-K-040", f"invalid YAML: {e}", rel))
            continue
        for k in ("name", "effect-tier", "allowed-tools", "notes"):
            if k not in d:
                out.append(FF(fam, "SDS-K-040", f"profile lacks {k}", rel))
        if d.get("effect-tier") not in LADDER:
            out.append(FF(fam, "SDS-K-040", f"effect-tier {d.get('effect-tier')!r} invalid", rel))
        if not isinstance(d.get("allowed-tools"), list):
            out.append(FF(fam, "SDS-K-040", "allowed-tools must be a list", rel))
    return out


@check("SDS-K-041", "family")
def k_041(fam):
    out = []
    for p in sorted((fam.kit / "shared" / "tool-profiles").glob("*.yaml")):
        try:
            d = load_yaml_file(p) or {}
        except yaml.YAMLError:
            continue
        rung = LADDER.index(d["effect-tier"]) + 1 if d.get("effect-tier") in LADDER else 0
        for tok in d.get("allowed-tools", []) or []:
            tok = str(tok)
            if any(re.search(pat, tok) for pat in FORBIDDEN_ALWAYS) or (rung < 5 and any(re.search(pat, tok) for pat in FORBIDDEN_BELOW_5)):
                out.append(FF(fam, "SDS-K-041", f"profile pre-approves {tok!r}", f"kit/shared/tool-profiles/{p.name}"))
    return out


@check("SDS-K-042", "family")
def k_042(fam):
    out = []
    for p in sorted((fam.kit / "shared" / "tool-profiles").glob("*.yaml")):
        try:
            d = load_yaml_file(p) or {}
        except yaml.YAMLError:
            continue
        for tok in d.get("allowed-tools", []) or []:
            if BARE_TOOLS_RE.match(str(tok)):
                out.append(FF(fam, "SDS-K-042", f"bare entry {tok!r}", f"kit/shared/tool-profiles/{p.name}"))
    return out


@check("SDS-K-050", "family")
def k_050(fam):
    gl = fam.kit / "shared" / "glossary.md"
    if not gl.exists():
        return []
    out = []
    for i, line in enumerate(gl.read_text(encoding="utf-8").splitlines()):
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            cells = [c for c in line.strip().strip("|").split("|")]
            if len(cells) != 3:
                out.append(Finding("SDS-K-050", "ERROR", "kit/shared/glossary.md", i + 1, f"glossary row has {len(cells)} columns, expected 3"))
    return out


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------
def run_checks(scope: str, target) -> list[Finding]:
    findings: list[Finding] = []
    for c in CHECKS:
        if c.scope != scope:
            continue
        try:
            findings.extend(c.fn(target))
        except Exception as e:  # noqa: BLE001 — a crashing check must not hide other findings
            path = target.rel if scope == "skill" else "."
            findings.append(Finding("SDS-X-INTERNAL", "ERROR", path, None, f"check {c.id} crashed: {type(e).__name__}: {e}"))
    return findings


def lint_skill(d: Path, fam: FamilyCtx) -> list[Finding]:
    ctx = load_skill(d, fam)
    if not (d / "SKILL.md").exists():
        return [Finding("SDS-S-001", "ERROR", relpath(fam.root, d), None, "SKILL.md is missing")]
    return run_checks("skill", ctx)


def lint_family(fam: FamilyCtx) -> list[Finding]:
    return run_checks("family", fam)


def sort_key(f: Finding):
    return (f.path, f.line if f.line is not None else 0, f.rule_id)


def report_text(findings: list[Finding], review: bool, label: str) -> None:
    for f in sorted(findings, key=sort_key):
        loc = f"{f.path}:{f.line}" if f.line else f.path
        print(f"{f.rule_id} {f.level} {loc} {f.message}")
    n = {lvl: sum(1 for f in findings if f.level == lvl) for lvl in ("ERROR", "WARN", "INFO")}
    sys.stderr.write(f"{n['ERROR']} error(s), {n['WARN']} warning(s), {n['INFO']} info(s) — {label}\n")
    if review:
        print("REVIEW (human checklist, not failures):")
        for rid in REVIEW_ORDER:
            slug, level, _, section, text = RULES[rid]
            print(f"  REVIEW {rid} [{level}, §{section}] {text}")


def report_json(findings: list[Finding], review: bool, kit: Path) -> int:
    results = []
    for f in sorted(findings, key=sort_key):
        r = {"ruleId": f.rule_id, "level": JSON_LEVEL[f.level], "message": {"text": f.message},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": f.path}}}]}
        if f.line:
            r["locations"][0]["physicalLocation"]["region"] = {"startLine": f.line}
        results.append(r)
    if review:
        for rid in REVIEW_ORDER:
            results.append({"ruleId": rid, "level": "hint", "message": {"text": RULES[rid][4]}, "locations": []})
    doc = {"version": "sds-finding-list-1.0",
           "runs": [{"tool": {"driver": {"name": "lint-skill", "version": LINTER_VERSION}}, "results": results}]}
    schema_p = kit / "shapes" / "finding-list.schema.json"
    if jsonschema is not None and schema_p.exists():
        try:
            jsonschema.validate(doc, json.loads(schema_p.read_text()))
        except (jsonschema.ValidationError, json.JSONDecodeError) as e:
            sys.stderr.write(f"ERROR: linter output failed finding-list schema validation: {str(e)[:120]}\n")
            return 2
    print(json.dumps(doc, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SDS conformance linter")
    ap.add_argument("skill_dir", nargs="?", help="skill directory to lint")
    ap.add_argument("--all", metavar="SKILLS_DIR", help="lint every skill under this directory (plus family checks)")
    ap.add_argument("--kit", help="kit directory (default: two levels above this script)")
    ap.add_argument("--registry", help="registry file (default: <kit>/registry/marketplace.json)")
    ap.add_argument("--json", action="store_true", help="emit a finding-list document")
    ap.add_argument("--rules", action="store_true", help="print the embedded rule table and exit")
    ap.add_argument("--strict", action="store_true", help="treat WARN as failing")
    ap.add_argument("--no-review", action="store_true", help="suppress the REVIEW checklist")
    a = ap.parse_args(argv)

    if a.rules:
        for rid in sorted(RULES):
            slug, level, tag, section, _ = RULES[rid]
            print(f"{rid}|{slug}|{level}|{tag}|{section}")
        return 0
    if not a.skill_dir and not a.all:
        ap.print_usage(sys.stderr)
        return 2

    kit = Path(a.kit).resolve() if a.kit else Path(__file__).resolve().parent.parent
    if not kit.is_dir():
        sys.stderr.write(f"ERROR: kit directory not found: {kit}\n")
        return 2
    root = kit.parent
    fam = load_family(root, kit, a.registry, bool(a.all))
    if fam.registry_error and a.registry:
        sys.stderr.write(f"ERROR: {fam.registry_error}\n")
        return 2

    findings: list[Finding] = []
    if a.all:
        sd = Path(a.all).resolve()
        if not sd.is_dir():
            sys.stderr.write(f"ERROR: not a directory: {sd}\n")
            return 2
        findings += lint_family(fam)
        for d in sorted(p for p in sd.iterdir() if p.is_dir() and (p / "SKILL.md").exists()):
            findings += lint_skill(d, fam)
        label = relpath(root, sd)
    else:
        d = Path(a.skill_dir).resolve()
        if not d.is_dir():
            sys.stderr.write(f"ERROR: not a directory: {d}\n")
            return 2
        findings += lint_skill(d, fam)
        label = relpath(root, d)

    review = not a.no_review
    if a.json:
        rc = report_json(findings, review, kit)
        if rc:
            return rc
    else:
        report_text(findings, review, label)
    failing = any(f.level == "ERROR" or (a.strict and f.level == "WARN") for f in findings)
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
