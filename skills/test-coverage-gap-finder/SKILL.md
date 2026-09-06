---
name: test-coverage-gap-finder
description: >-
  Reads a Cobertura coverage report beside the sources it measured and
  turns the percentage into names — functions and methods whose body
  no test executed, files below a coverage floor, and files the
  report never saw — as a finding-list, ranked by the human judgment
  of which gap is risky rather than by size. Use when a coverage
  number dropped and nobody knows where, when deciding which tests to
  write next, or when asked what is untested.
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
  Bash(python3 scripts/find_coverage_gaps.py:*) Read
---

# test-coverage-gap-finder

## When to use

- A coverage number dropped and nobody knows which change did it.
- Deciding which tests to write next with limited time.
- Asked what is untested, or whether a file is really covered.

## When not to use

- Producing the coverage report — run the test suite with coverage
  enabled (`coverage xml`, `pytest --cov --cov-report=xml`) first;
  this skill reads the result and executes nothing.
- Tests that pass and fail on the same commit — that is
  `flaky-test-triage`.
- Enforcing a coverage threshold in CI — a one-line gate in the
  pipeline does that; this skill explains a gap, it does not block on
  one.

## @requires

- REQUIRED: a Cobertura XML coverage report (`coverage.xml` from
  coverage.py, pytest-cov, JaCoCo, Istanbul, or gcovr).
- REQUIRED: the repository directory the report's `filename`
  attributes are relative to.
- OPTIONAL: `min-file-rate` — the line-rate below which a file is
  reported (default: 0.5).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the report exists and
is well-formed Cobertura, the repository is a directory. Then scan —
the mechanical part (SDS-S-060):

```
python3 scripts/find_coverage_gaps.py <coverage.xml> --repo <repo> [--min-file-rate F]
```

For each measured file it maps line numbers to hit counts, parses
the source with `ast` (rung 1; nothing is run), and intersects every
function's *body* with the map — the `def` line is executed at
import time, so it is never evidence. It reports
`coverage/uncovered-function` (no body line hit), `coverage/low-file-rate`
(a file below the floor), and `coverage/unmeasured-file` (a `.py`
file under the repository with no entry in the report). Tests and
dunders are skipped.

### Analyze

The scan lists gaps; this stage decides which matter (SDS-S-061). An
uncovered public function on a request path — an endpoint, a
command, a data migration — is a risk; an uncovered `_helper` that
its callers cover indirectly may be fine, and the report's per-line
hits will show whether it is really unreached. An unmeasured file is
either configured out (check `.coveragerc` / `pyproject.toml`
`[tool.coverage]` omit lists) or never imported by any test, and
those are different findings: the first is a decision, the second is
a gap. A low-rate file whose misses are all in one function is that
function's gap, not the file's.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[write test: <what to assert>]`, `[covered
indirectly]`, `[omitted by config]`, `[never imported]` — and, for a
gap worth closing, say in one line what the first test should
exercise.

### Synthesize

Return the finding-list, warnings first, grouped by file, with the
gaps worth closing listed before the ones to leave. A report where
every function body was reached yields a well-formed finding-list
with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per gap, located at the function's `def` line or the
file's line 1, with `properties` carrying the function name and body
span, or the file's rate and tracked/hit line counts. Nothing was
run and nothing was modified.

## @throws

- `report-missing`: the coverage report path does not exist.
- `report-malformed`: the report is not well-formed XML, or its root
  is not `<coverage>`, or a `<line>` lacks numeric attributes.
- `repo-invalid`: the repository path is not a directory.
- `rate-invalid`: `min-file-rate` is not a number between 0 and 1.
- `source-unparseable`: a measured source file does not parse.

## @example

**Input:** a `coverage.xml` where `cancel_order()`'s `def` line was
hit at import but none of its body was.

**Output (excerpt):**

```json
{
  "ruleId": "coverage/uncovered-function",
  "level": "warning",
  "message": { "text": "[write test: cancelling sets cancelled=True] src/orders.py:cancel_order() has no covered lines (3 tracked lines, lines 9-12)" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "src/orders.py" }, "region": { "startLine": 9 } } }],
  "properties": { "function": "cancel_order", "startLine": 9, "endLine": 12, "trackedLines": 3, "public": true }
}
```
