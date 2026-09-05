# How to Build a Skill

> **Non-normative guide to SDS 1.0-draft**
> (docs/superpowers/specs/2026-09-05-skill-design-specification.xml).
> Where this conflicts with the spec, the spec wins (SDS-F-052). Rule
> IDs in parentheses point at the normative text.

This is the one procedure. Follow it in order. It is not a menu — every
step is required, and the branch points are the only decisions you get
to make. Everything referenced below (`kit/...`) is a real file in this
kit, not a description of one; open it and fill it in.

For a decision rule on `scripts/`, `references/`, `assets/`, and the
frontmatter fields this procedure doesn't cover (`license`,
`compatibility`, and the two different sources of `allowed-tools`),
see `kit/PRIMITIVES.md` — read the relevant section of it when a step
below points you there, not all at once up front.

Two complete, linter-clean worked examples built through every step of
this procedure live at `skills/dependency-audit/` (a Query Skill) and
`skills/pr-description-writer/` (a Command Skill) — refer to them
whenever a step below is unclear in the abstract.

All paths in this kit are family-root-relative (SDS-F-030): the family
root is the directory containing `kit/`, `skills/`, and `docs/`.

---

## Step 0 — Classify the skill: Query or Command (SDS-C-002, SDS-C-041)

Ask one question: **does this skill change anything outside the
artifact it produces?**

- No → it's a **Query Skill**. Use `kit/templates/SKILL.md.query.template`.
- Yes → it's a **Command Skill**. Use `kit/templates/SKILL.md.command.template`.

If you're not sure, it's a Query Skill — push the mutating part into a
separate Command Skill that the Query Skill's output feeds (SDS-C-002).
Do not write one skill that does both.

## Step 1 — Assign the Effect Ladder rung (SDS-C-040, SDS-S-017, SDS-S-025)

Pick the single highest rung the skill's Procedure reaches:

| Rung | Meaning | Example |
|---|---|---|
| 1 local-read-only | reads only local files | `tech-debt-inventory` |
| 2 domain-read-only | reads repo/version-control history | `flaky-test-triage` |
| 3 external-read-only | hits a network API | `dependency-audit` (queries OSV) |
| 4 local-write | writes only its own output file | `adr-writer` |
| 5 shared-write | writes/notifies something others depend on | `pr-description-writer` |
| 6 irreversible | can't be undone, or its undo is itself irreversible | `pr-lifecycle-manager` (merge) |

Rungs 1-3 → Query Skill. Rungs 4-6 → Command Skill. If this
contradicts Step 0's answer, Step 0 was answered wrong — redo it.

Rungs 5 and 6 require a Confirm gate (Step 6). Any rung ≥ 2 that
invokes tools or scripts requires `allowed-tools` (Step 5). There is
no rung at which you skip these.

## Step 2 — Pick the artifact shape, or register a new one (SDS-C-030, SDS-C-031, SDS-S-026)

Check `kit/shapes/` first:

- Producing a list of problems found → `kit/shapes/finding-list.schema.json`
- Producing a decision with alternatives considered → `kit/shapes/decision-doc.schema.json`
- Producing a multi-step plan → `kit/shapes/plan-doc.schema.json`
- Producing a narrative summary → `kit/shapes/status-report.schema.json`
- None of these fit → before inventing a new shape, apply the
  Standards-First Rule (SDS-C-031): is there an established external
  format for this kind of artifact? If yes, wrap it — don't invent
  (registering a new shape: SDS-K-020, SDS-K-021). If genuinely no
  shape fits and no external standard exists, declare `freeform` in
  `metadata.shape-out` and say so explicitly; this is the exception,
  not the default.

## Step 3 — Copy the template, don't start from a blank file (SDS-S-030, SDS-S-031, SDS-S-032, SDS-S-033)

```
cp kit/templates/SKILL.md.<query|command>.template  skills/<new-skill>/SKILL.md
```

Every bracketed `[FILL: ...]` must be replaced (SDS-S-033). Every H2
section heading in the template stays, in the order given (SDS-S-030)
— do not reorder, merge, or drop one. For stage headings under
Instructions (SDS-S-031): a Query Skill MAY omit `### Filter` and
`### Classify` entirely; a Command Skill keeps all seven
(`Gather, Analyze, Decide, Confirm, Act, Communicate, Persist`). If a
required heading genuinely doesn't apply, its body starts
`N/A — <reason>` (SDS-S-032) rather than being deleted; a missing
section is indistinguishable from a forgotten one.

While filling in Instructions, decide per sub-step whether it's prose,
a bundled script, or a reference file — see `kit/PRIMITIVES.md`
Sections 2-4 for the exact decision rule (the toil test for
`scripts/`, SDS-S-060; the "needed every time vs. sometimes" test for
`references/`, SDS-S-070). Don't default to prose for everything; a
mechanical parsing or format-translation step written as prose is
instructions a model has to re-derive correctly every single run
instead of code that's correct once.

## Step 4 — Write `description` last, not first (SDS-S-012, SDS-S-013)

Draft everything else first. Then write `description` to contain the
specific keywords a real task description would use — not a summary of
what you just wrote. Bad: "Helps with dependencies." Good: "Scans
package manifests for stale or vulnerable dependencies. Use when
reviewing a dependency bump, auditing supply-chain risk, or when the
user mentions outdated packages, CVEs, or `npm audit`/`pip-audit`."

## Step 5 — Attach `allowed-tools`: shared profile plus own scripts (SDS-S-020 … SDS-S-023)

This applies to any skill with an Effect Ladder rung above
local-read-only that invokes tools or scripts, not Command Skills
alone — an `external-read-only` Query Skill invoking its own bundled
scripts still needs a scoped `allowed-tools` line (SDS-S-020; see
`skills/dependency-audit/SKILL.md`).

Two different sources, per `kit/PRIMITIVES.md` Section 5 — use both
where they apply, never hand-write either from scratch (SDS-S-021):

1. For cross-cutting git/gh operations, pick the closest match from
   `kit/shared/tool-profiles/` and paste its `allowed-tools` list
   verbatim (SDS-K-043). If none fits, copy the closest one and narrow
   it further — never widen a profile for convenience.
2. For this skill's own bundled `scripts/`, add an inline entry scoped
   to the exact script path (`Bash(python3 scripts/your_script.py:*)`)
   — never a bare `Bash(python3:*)` (SDS-S-022), which pre-approves
   running arbitrary Python, not just this skill's vetted scripts.

The rung-5/6 operation itself (push, merge, edit, delete, publish)
must never appear in `allowed-tools`, from either source, ever
(SDS-S-023, SDS-K-041).

## Step 6 — Command Skills only: write the Confirm gate (SDS-S-050, SDS-C-044)

Copy the base text from `kit/shared/gates/medium.md` (rung 5) or
`kit/shared/gates/high.md` (rung 6) into the skill's Confirm section
and fill in the brackets. Do not paraphrase the structure away — the
What/Why/Reversible fields are load-bearing, not decoration.

If the skill has a conditional Act path (SDS-S-041) — a Decide-stage
branch on which nothing needs to be mutated — write that branch as a
bold `**If <condition>: stop here.**` line in Decide, and begin both
the Confirm and Act sections with `Only reached when <condition>.`

## Step 7 — Command Skills only: compensating action and two-phase checkpoint (SDS-S-053, SDS-S-054, SDS-C-046)

For every mutating step in Act, fill in three things in the template,
non-optionally:

1. **Compensating action** (SDS-S-054) — what undoes this step if a
   later step in the same sequence fails, or if the result turns out
   wrong. If truly nothing can undo it, write "no compensating action —
   this step must be last" and put it last.
2. **Checkpoint** (SDS-S-053) — a two-phase record at
   `.skills-state/<skill-name>/<key>.json`: **before** the mutating
   call, write `{key, step, status: "pending", startedAt, preState,
   compensatingAction}`; **immediately after** it succeeds, set
   `status: "completed"` and add `postState`. A resumed invocation that
   reads `pending` treats the step as possibly-applied and runs
   check-before-act before retrying; `completed` means skip it. Single
   mutating step → write it inline with the Write tool; two or more →
   a `scripts/checkpoint.py` (SDS-S-055).
3. **Check-before-act** (SDS-C-046) — the sentence stating how Act
   verifies current state first and skips as a no-op when the effect
   is already applied.

The mutation itself is issued as a direct, unwrapped tool call after
Confirm — never through a bundled script (SDS-S-051).

A Command Skill with any of these left blank is not done.

## Step 8 — Fill `@requires` / `@returns` / `@throws` (SDS-S-036 … SDS-S-039)

- `@requires`: every precondition as a testable assertion, each marked
  `REQUIRED:` or `OPTIONAL:` with `(default: …)` (SDS-S-036). More than
  five REQUIRED inputs means split the skill (SDS-C-052, SDS-S-037).
- `@returns`: `Shape: \`<shape-out>\`` naming the shape from Step 2, and
  for a registered shape the literal `kit/shapes/<shape>.schema.json`
  path (SDS-S-038).
- `@throws`: enumerate failure modes as `` - `kebab-code`: … `` until
  you've covered the boundary cases you'll write evals for in Step 9 —
  empty input, malformed input, precondition violated (SDS-S-039). If
  you can't yet name a failure mode a boundary eval would hit, go find
  that boundary case now, not after.

## Step 9 — Write the eval table (SDS-S-090 … SDS-S-099)

Copy `kit/evals/TEMPLATE.eval.yaml`. Required rows, no exceptions
(SDS-S-099):

- the primary happy-path scenario,
- one row per boundary case named in `@throws` (at least one
  empty-input success and one malformed-input failure),
- if this skill searches for known problems (`shape-out: finding-list`):
  one **mutation fixture** — a fixture with a deliberately planted,
  known instance of what it claims to detect, asserting it's actually
  found (SDS-S-095),
- a `fixed-point` row — success only if `shape-out` equals `shape-in`
  **and both are registered shapes**; otherwise `not-applicable` with
  the reason stated (SDS-S-094). This is NOT the same test as
  `metadata.idempotent` (SDS-C-004).
- a `contract-with-*` row (SDS-C-063), `not-applicable` with a reason
  if no chained skill exists yet.

If this skill's Gather or Analyze stage hits an `external-read-only`
(or above) system: no blocking row may invoke the live system
(SDS-S-092). Test deterministically against local fixtures and one
frozen recording (`evals/fixtures/frozen-<source>-<what>.json`,
SDS-S-093), give the script an injectable-fixture flag (SDS-S-065) so
the full pipeline runs offline, and put any live-call check after the
`---` separator as a non-blocking smoke test asserting shape only.

Fixture layout (SDS-S-096): static fixtures in
`evals/fixtures/<case>/` (`.gitkeep` when empty); anything that cannot
be checked in as static content (a git repository) is regenerated by
an idempotent `evals/fixtures/build-<name>.sh` whose output dir is
listed in `evals/fixtures/.gitignore`. Rows reference only paths
inside the skill or `kit/` (SDS-S-098) — never `/tmp`.

"Runs without erroring" is not a passing eval suite (SDS-S-091).

## Step 10 — Register in the family registry (SDS-F-010 … SDS-F-016)

Add one entry to `kit/registry/marketplace.json` with `name`,
`description` (identical to the frontmatter description, SDS-F-016),
`version`, `status: built`, `effect-tier`, `tier`, `shape-out`,
`shape-in` (SDS-F-012, SDS-F-013). This file is the only place a
human-facing skill index may be generated from — never hand-maintain a
separate list (SDS-F-014).

## Step 11 — Validate before calling it done (SDS-S-110)

0. Run `python3 kit/scripts/lint-skill.py skills/<skill>`; zero
   ERRORs (SDS-K-070). Read the trailing REVIEW checklist and answer
   each item honestly.
1. Validate the SKILL.md frontmatter's `metadata` block by hand
   against Step 1/Step 2's choices — rung and shape must match what
   the Procedure actually does, not what's convenient to declare.
2. Validate any produced example artifact against its shape's
   `.schema.json` in `kit/shapes/` using a JSON Schema validator.
3. Run the eval table. All rows pass, including the mutation fixture
   and fixed-point row where required.
4. Re-read the glossary (`kit/shared/glossary.md`) and confirm you
   didn't introduce a synonym for a term it already defines
   (SDS-F-061).

If all five pass, the skill is done. If any fail, fix the skill —
not the eval, and not the glossary.
