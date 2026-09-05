# Skill Primitives: What Goes Where, and Why

> **Non-normative guide to SDS 1.0-draft**
> (docs/superpowers/specs/2026-09-05-skill-design-specification.xml).
> Where this conflicts with the spec, the spec wins (SDS-F-052). Rule
> IDs in parentheses point at the normative text.

`kit/HOW-TO-BUILD-A-SKILL.md` gives you the procedure. This gives you the
decision rule for every physical primitive the Base Spec makes
available, so a step in that procedure never leaves you guessing where
something belongs. Read the relevant section when the procedure points
here; don't read this front-to-back before starting.

Worked examples throughout: `skills/dependency-audit/` (a Query
Skill) and `skills/pr-description-writer/` (a Command Skill),
both built end-to-end through the procedure and referenced by path
below.

---

## 1. SKILL.md — always required, always the entry point (SDS-S-001, SDS-S-030, SDS-S-035)

Budget, per the Base Spec: under 500 lines, under ~5,000 tokens.
`dependency-audit/SKILL.md` is 162 lines / ~1,000 tokens — well inside
budget, which is the normal case. If you're pushing the limit, that is
the signal to move content to `references/`, not to write tighter
prose. Never trim a required H2 section (SDS-S-030) to
make room; move optional depth out instead.

Contains, in fixed order (from the templates): frontmatter, When to
use / When not to use, `@requires`, Instructions (stage-grammar
subheadings), `@returns`, `@throws`, `@example`.

---

## 2. `scripts/` — deterministic, mechanical, no-judgment work (SDS-S-060 … SDS-S-068)

### Decision rule: the toil test

Ask: is this sub-step manual, repetitive, deterministic, and requiring
no interpretation of ambiguous input? If yes, script it. If it
requires applying a rubric, weighing options, or interpreting
ambiguous natural language, it stays prose — a script cannot exercise
judgment, and forcing it to try produces silently wrong results
instead of a legible reasoning step.

### Concrete triggers to write a script

- **Parsing a real grammar** — a manifest format, a structured log,
  SARIF/OSV JSON. `dependency-audit/scripts/parse_manifest.py` exists
  because "does this JSON have a `dependencies` key" is not a judgment
  call.
- **Calling an external system and normalizing its response** —
  `osv_batch_query.py` handles the actual HTTP calls, retries-worth
  timeouts, and response-shape checking. The model should never be
  asked to "carefully read" a raw API response byte-by-byte when a
  script can parse it correctly every time.
- **Format translation (Adapters, SDS-C-062)** — anything
  converting one standard's shape into the family's canonical shape
  belongs in a script, kept separate from judgment. `osv_to_finding.py`
  is a pure adapter: given the same OSV record, it always produces the
  same finding-list entry. If you find yourself writing prose
  instructions like "then convert the OSV severity field to a SARIF
  level, mapping CRITICAL and HIGH to error, MODERATE to warning..." —
  that is a deterministic table, not a judgment call. Script it.

### What never belongs in a script

Analyze, Classify, and Decide stages. A script can flag "this
dependency has 6 known CVEs"; only the model's Analyze stage should
say "given this is a dev-only dependency behind a build step, the
practical risk is lower than the CVE count alone suggests" — and only
if the skill's design actually calls for that kind of judgment.

### Requirements (Base Spec + this family)

- Self-contained, or clearly document what's missing.
  `parse_manifest.py` needs `tomli` only for Cargo files on Python
  < 3.11, and says so both in its own docstring and in
  `references/ecosystem-notes.md` — a dependency is fine as long as
  it's named, not silently assumed.
- Helpful, specific error messages on stderr, prefixed consistently
  (this family uses `"ERROR: ..."`) so the calling skill's Gather
  stage can surface the exact cause under `@throws`, not a generic
  failure.
- Handle the edge cases named in the skill's `@throws` list
  gracefully — an empty result is a normal exit path with valid
  output, never a crash (see `parse_manifest.py` exiting 0 with `[]`
  when no manifest exists).
- Naming: verb-noun, descriptive of the single thing the script does
  (`parse_manifest.py`, not `utils.py`). An adapter script names both
  sides of the translation where practical
  (`osv_to_finding.py`).

---

## 3. `references/` — large, occasionally-needed detail (SDS-S-070 … SDS-S-073)

### Decision rule

If every invocation needs it, it belongs in SKILL.md's body. If it's
needed sometimes — to explain an edge case, cover a less-common
variant, or provide depth a specific situation calls for — it belongs
in `references/`, loaded only when that situation actually arises.

`dependency-audit/references/ecosystem-notes.md` is the worked
example: SKILL.md's Gather step tells the model to consult it only
"if unsure why a dependency shows `resolved: false`" — not on every
run. Most invocations never open it, which is the point.

### Naming (per Base Spec convention)

`REFERENCE.md` for one large technical reference, `FORMS.md` for
templates/structured formats, or a descriptive domain-specific name
(`ecosystem-notes.md`, as here) when the content is one bounded topic
rather than the skill's whole technical backing.

### The one-level-deep rule

SKILL.md may link to `references/X.md`. `X.md` should not itself link
deeply into a further nested reference chain — keep the graph shallow
enough that a model following one link from SKILL.md has everything it
needs, rather than needing to chase three files to answer one
question.

### Write the pointer as a condition, not a blanket instruction

Bad: "See references/ecosystem-notes.md for details." (implies always
read it — defeats progressive disclosure.)
Good, as used in `dependency-audit/SKILL.md`: "If unsure why X,
consult references/Y.md — but only then." The condition is what makes
it genuinely on-demand rather than a second mandatory file.

---

## 4. `assets/` — static resources the output conforms to, or injected config (SDS-S-080 … SDS-S-082)

### Decision rule

Use `assets/` for: templates the output should follow, images/
diagrams referenced by the skill, lookup/data tables, or — per the
Dependency Injection reuse pattern (SDS-C-061) — an
injected, per-installation dependency such as one org's specific
style guide or severity rubric that specializes an otherwise-generic
skill.

`dependency-audit` has no `assets/` directory, correctly — it has
nothing static to ship; its "template" is the family-wide
`finding-list` shape, which lives one level up (see next section), not
per-skill.

### Relationship to the family-level `kit/shapes/`

`kit/shapes/*.schema.json` are **family-wide** canonical structural
types — one definition, shared and versioned across every skill in
the family (SDS-C-030, the Shape Registry). A skill's own
`assets/` is for **per-skill or per-installation** resources: a
specific org's style guide injected into `style-guide-enforcer`, a
severity-weighting table specific to one skill's domain. Never
duplicate a family shape's schema into a skill's `assets/` — reference
`kit/shapes/` directly (as `dependency-audit/SKILL.md`'s `@returns`
does) so there is exactly one place that definition can drift from.

### Hermeticity note

If a skill's Gather stage reads its own `assets/` file, that file
counts as a declared input for hermeticity purposes (SDS-C-003, SDS-S-081)
— it must be named in `@requires`, not treated as invisible ambient
configuration.

---

## 5. Frontmatter fields the procedure doesn't already cover (SDS-S-014, SDS-S-015, SDS-S-020 … SDS-S-023)

### `license`

Default to this family's standard license (Apache-2.0, per SDS's
governance layer) unless there's a specific reason to diverge.
`dependency-audit/SKILL.md` sets it explicitly rather than omitting
it, so the choice is visible rather than assumed.

### `compatibility`

Only set this when there's a genuine environment requirement beyond
"any host that supports Agent Skills." Most Query Skills reading only
local files need no `compatibility` field at all — omitting it is
correct, not incomplete. `dependency-audit` sets it because it
genuinely requires network access to a specific host and, on older
Python, an extra package — both real constraints worth surfacing
before someone tries to run it somewhere that can't.

### `allowed-tools` — two different sources, not one

This is a distinction this build surfaced that the original kit
under-specified:

- **Shared, cross-cutting profiles** (`shared/tool-profiles/*.yaml`)
  exist for patterns reused across *many* skills — git and gh
  operations that recur throughout the family. Copy these verbatim
  when a skill's Act stage genuinely matches one.
- **Skill-own bundled-script invocation** is inherently per-skill,
  because the script paths are specific to that skill's directory —
  there is no meaningful shared profile for "may run my own
  scripts/parse_manifest.py." Declare these inline in the skill's own
  `allowed-tools`, scoped to the exact scripts it ships, as
  `dependency-audit/SKILL.md` does
  (`Bash(python3 scripts/parse_manifest.py:*)` etc. — never a bare
  `Bash(python3:*)`, which would pre-approve running arbitrary Python,
  not just this skill's own vetted scripts).

Both sources can appear in the same skill's `allowed-tools` line: the
skill's own scripts, plus a shared profile for the git/gh operations
its Act stage performs.

---

## 6. Evals against an open-world (`external-read-only` or above) stage (SDS-S-092 … SDS-S-095)

A rule this build surfaced that the original `evals/TEMPLATE.eval.yaml`
didn't yet capture precisely enough:

**Never assert exact content from a live call to an open-world system
in a required, blocking eval row.** The content of an external system
(a vulnerability database, a CI status, a live API) changes over time
for reasons that have nothing to do with whether your skill is
correct — an eval that fails when OSV publishes a new CVE is a flaky
eval, not a caught regression.

Instead, split it exactly as `dependency-audit/evals/dependency-audit.eval.yaml`
does:

1. **Deterministic rows** test everything before and after the live
   call against local fixtures — `parse_manifest.py`'s Gather logic
   against fixture repos, and the adapter's Synthesize logic against a
   **frozen recording** of one real external response (captured once,
   committed, never re-fetched by the eval itself).
2. **A separate, non-blocking smoke test** exercises the actual live
   call, asserting only response *shape* (exit code, schema validity,
   non-empty where expected) — never specific content — and is not
   part of the pass/fail table that gates the skill.

### Correction to the fixed-point row condition

The original template gated the fixed-point eval row on
`metadata.idempotent == "true"` alone. Building `dependency-audit`
showed this is wrong: `idempotent: "true"` there means the weaker,
correct MCP-style claim ("safe to call again with the same
arguments"), not the stronger composition-law claim that requires
feeding a skill's own output back in as its own input. **The
fixed-point row only applies when a skill's `shape-out` equals its
`shape-in`** — i.e., the skill is actually self-composable, typically
an editing/refinement skill. For any skill where they differ (as with
`dependency-audit`: `shape-out: finding-list`, `shape-in: freeform`),
mark the row `not-applicable` with the reason stated explicitly, as
shown in the worked example — never silently omit the row.

One more precision, found while classifying `pr-description-writer`
(`shape-out: freeform`, `shape-in: freeform`): **`shape-out ==
shape-in` only triggers the fixed-point row when both are the same
*registered* shape.** `freeform` matching `freeform` is not a
self-composability signal — `freeform` is the declared absence of
structure, not a structure a skill's own output could meaningfully be
fed back into itself as. Treat a `freeform`/`freeform` pair as
not-applicable by default, same as a genuine shape mismatch, unless
the skill's Instructions explicitly describe feeding its own prior
freeform output back in as input (in which case say so, and write the
row for real).

---

## 7. Checkpoint and compensating-action state — where it actually lives (SDS-S-053, SDS-S-054, SDS-S-100)

SDS-S-053 requires a Command Skill to persist a **two-phase**
checkpoint around each mutating Act step: a `pending` record before
the call, updated to `completed` after it succeeds. This is runtime
data, not part of the skill
package (it's not checked into `scripts/`, `references/`, or
`assets/` — it doesn't exist until the skill runs).

**Convention: `<family-root>/.skills-state/<skill-name>/<key>.json`** (SDS-S-100),
where `<key>` is whatever uniquely identifies the invocation (a PR
number, a branch name, a migration id). `pr-description-writer` uses
`.skills-state/pr-description-writer/<pr-number>.json`, holding the
pre-Act body so its compensating action has something concrete to
revert to.

- Add `.skills-state/` to the repository's `.gitignore` — it's
  machine state for resuming/reverting a specific skill run, not
  project content, and committing it would let it silently go stale.
- Write the `pending` record **before** the mutating call it protects
  (`{key, step, status: "pending", startedAt, preState,
  compensatingAction}`) and update it to `completed` (adding
  `postState`) **immediately after** the call succeeds. A record written
  only after Act protects nothing if Act itself fails partway through;
  a record never marked completed leaves a resumed session guessing —
  it must treat `pending` as possibly-applied and run check-before-act
  (SDS-C-046) before retrying, and skip a `completed` step outright.
- For a skill with only one mutating step (like
  `pr-description-writer`), writing this file is simple enough to do
  directly via the model's own file-write tool in the Act section of
  SKILL.md — it does not need a bundled script (SDS-S-055). Reserve a dedicated
  `scripts/checkpoint.py` for orchestrators with multiple mutating
  steps across a longer sequence, where the read/write logic is
  reused enough times to be worth centralizing (see, when built, an
  orchestrator like `pr-lifecycle-manager`).

## 8. Never wrap a rung-5/6 Act inside an `allowed-tools`-scoped script (SDS-S-051)

Found while building `pr-description-writer`: it's tempting to write
`scripts/apply_description.py` to do the actual `gh pr edit` call,
the same way `dependency-audit` wraps its OSV query in a script. Don't.

If a script performs the mutating operation, and that script's path is
what appears in `allowed-tools` (per Section 5 above, SDS-S-021, "skill-own
bundled-script invocation"), then approving the script *is* approving
the mutation — the host's confirmation gate never actually engages,
because from the host's perspective the pre-approved action was
"run this script," and the script, not the model's next tool call, is
what performs the edit. This silently defeats the entire Confirm-gate
mechanism (SDS-C-044, SDS-S-050) while looking, on paper, like a
correctly-scoped `allowed-tools` line.

The rule: anything at rung 5 or 6 must be issued as a direct tool call
by the model, in the open, after Confirm — never delegated to a
bundled script that is itself pre-approved. Scripts stay confined to
Gather-stage work (read-only) and to genuinely low-risk local writes
(like the checkpoint file in Section 7, SDS-S-053) that don't need a gate at all.
`pr-description-writer/SKILL.md`'s Act section says this explicitly:
run `gh pr edit` directly, not through a script.

---

## Summary table

| Primitive | Use when | Don't use when |
|---|---|---|
| SKILL.md body | always | — |
| `scripts/` | deterministic, mechanical, passes the toil test | the step requires judgment |
| `references/` | large, occasionally-needed depth | needed on every single invocation |
| `assets/` | per-skill/per-install static resource or injected config | the resource is a family-wide shape (use `kit/shapes/` instead) |
| `license` | always set explicitly | never omit |
| `compatibility` | a genuine environment/network/package requirement exists | the skill only reads local files with the standard library |
| `allowed-tools` (shared profile) | the operation matches a cross-cutting git/gh pattern | the operation is this skill's own bundled script |
| `allowed-tools` (inline) | scoping this skill's own `scripts/` | scoping anything wider than the exact script path |
| Frozen eval fixture | the stage under test hits an open-world system | the stage is local/deterministic (use a live fixture directly) |
| `.skills-state/` checkpoint | a Command Skill's Act step needs to be resumable/revertible | the skill is Query-kind (nothing to resume) |
| Bundled script for Act itself | never, if the Act is rung 5 or 6 | — issue it as a direct, unwrapped tool call after Confirm instead |
