---
name: test-smell-review
description: >-
  Reviews Python test files for structural smells — tests that assert
  nothing, tests that sleep, tests that swallow exceptions, tests that
  branch in their outermost block — as a finding-list, leaving the
  call on which smell is a real weakness to a human. Use before
  trusting a green test run, when reviewing a test-heavy pull request,
  or when asked why tests pass but bugs ship.
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
  Bash(python3 scripts/find_test_smells.py:*) Read
---

# test-smell-review

## When to use

- Before trusting a green suite that has never been questioned.
- Reviewing a pull request that adds or rewrites many tests.
- Asked why tests pass but bugs ship, or whether a suite is any good.

## When not to use

- Tests that pass and fail on the same commit — that is
  `flaky-test-triage`, which works from run history; this skill
  works from the source and finds the *causes* flakiness usually has.
- What is untested — that is `test-coverage-gap-finder`; a smell is
  a test that exists but proves little.
- Non-Python suites, for now.

## @requires

- REQUIRED: a repository directory containing Python test files
  (`test_*.py`, `*_test.py`, or anything under `tests/`).
- OPTIONAL: `exclude` — directories to skip beyond the usual vendored
  and build directories (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a directory.
Then scan — the mechanical part (SDS-S-060):

```
python3 scripts/find_test_smells.py <repo> [--exclude dir,dir]
```

It parses each test file with `ast` (rung 1; nothing is imported or
run), finds every `test*` function at module scope or inside a
class, and reports `test/no-assertion` (no `assert`, `pytest.raises`,
`self.assert*`, or `assert*`/`check*` helper call), `test/sleep-in-test`,
`test/swallowed-exception` (a broad handler whose body is only
`pass`/`return`), and `test/conditional-logic` (an `if`/`for`/`while`
at the test's top level). Fixtures and helpers draw nothing. A file
that does not parse stops the scan (`source-unparseable`).

### Analyze

The scan finds shapes; this stage decides which are faults
(SDS-S-061). A test without an assertion is sometimes a smoke test
("it does not raise") — legitimate if named so, a hole if it was
meant to check a value. A sleep that waits for a background worker
is a race waiting to be lost; a sleep that honours a documented rate
limit in an integration test is a design choice — the fix for the
first is a condition to wait on, not a longer sleep. A swallowed
exception in a test almost always hides the failure the test was
written to catch. A loop over cases is fine when each iteration
asserts; a loop whose `if` can skip every assertion tests nothing on
some inputs, and `pytest.mark.parametrize` says the same thing
honestly.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[add assertion: <what>]`, `[rename as smoke
test]`, `[wait on condition]`, `[keep: rate limit]`, `[let it
raise]`, `[parametrize]` — and, for a missing assertion, say what
the test's name promises it checks.

### Synthesize

Return the finding-list, warnings first, grouped by file, with the
count per action. A suite with no smell yields a well-formed
finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per smell, located at the test's `def` line (no
assertion) or the offending statement (sleep, handler, branch), with
`properties.test` naming the test. Nothing was run and nothing was
modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a test file does not parse.

## @example

**Input:** a suite where `TestCart.test_prints_only` only prints.

**Output (excerpt):**

```json
{
  "ruleId": "test/no-assertion",
  "level": "warning",
  "message": { "text": "[add assertion: printed text equals the cart summary] TestCart.test_prints_only() asserts nothing; it can only fail by raising" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "tests/test_orders.py" }, "region": { "startLine": 30 } } }],
  "properties": { "test": "TestCart.test_prints_only" }
}
```
