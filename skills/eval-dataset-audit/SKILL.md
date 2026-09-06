---
name: eval-dataset-audit
description: >-
  Audits an eval set — a `.jsonl`, `.json`, or `.csv` dataset of
  input/expected row pairs — for the data-quality defects that break
  an eval quietly, before any model is ever called: rows whose input
  is an exact or near-duplicate of another row's, an empty expected
  value, an expected label so imbalanced that a model can look good by
  guessing the majority class, and an expected value that leaks
  verbatim into its own row's input — as a finding-list with the row
  and field counts attached. Use before running an eval for the first
  time, when eval scores look too good to be true, or when asked
  whether an eval set is safe to trust.
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
  Bash(python3 scripts/audit_eval_dataset.py:*) Read
---

# eval-dataset-audit

## When to use

- An eval set is about to be run for the first time, or was hand-
  edited and needs a sanity check before the next run.
- Eval scores jumped or look too good to be true — a leaked expected
  value or a lopsided label split can produce exactly that.
- Asked whether an eval set is safe to trust, or why two rows keep
  scoring the same.

## When not to use

- Judging whether the *prompt* that will be evaluated is well formed —
  that is `prompt-template-audit`, which reads the calling code, not
  the eval set's rows.
- Checking an eval set for personal data — that is
  `test-data-pii-scan`, which asks whether a row is safe to keep, not
  whether it is safe to score on.
- A dataset in a form this skill does not read (anything other than
  `.jsonl`, `.json`, or `.csv`) — convert it first.

## @requires

- REQUIRED: a `.jsonl`, `.json`, or `.csv` file, readable, whose rows
  carry an input value and an expected value.
- OPTIONAL: `input-field` — the row key holding the input text
  (default: `input`).
- OPTIONAL: `expected-field` — the row key holding the expected text
  (default: `expected`).
- OPTIONAL: `near-duplicate-threshold` — the word-3-gram Jaccard score
  at or above which two distinct inputs count as near-duplicates
  (default: `0.9`).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the two field names are
non-empty, and the path is a readable file whose extension names a
supported form. Then read the rows — the mechanical part
(SDS-S-060):

```
python3 scripts/audit_eval_dataset.py <file> [--input-field F] [--expected-field F] [--near-duplicate-threshold N]
```

A `.jsonl` file is one JSON object per line; a `.json` file is one
array of row objects (a row's location is its 1-based position in the
array, since an array has no native line number); a `.csv` file is a
header row plus one data row per line (the header is line 1, so data
row *k* is at line *k*+1). A row missing either field draws one
`evals/missing-field` error at that row (capped at the first 20, with
`tool.properties.missingFieldTruncated` set once more exist) and is
excluded from every rule below, since there is nothing left to
compare.

Over the remaining rows it reports `evals/duplicate-row` (two or more
rows share an identical input after whitespace collapse),
`evals/near-duplicate` (two inputs are not identical but score at or
above the threshold on word-3-gram Jaccard similarity),
`evals/empty-expected` (an expected value that is empty or
whitespace-only), `evals/label-imbalance` (only when expected is
categorical — at most 20 distinct values, each at most 40 characters
— and the largest class exceeds 70% of rows), and `evals/leak-suspect`
(an expected value, four characters or more after stripping, that
appears verbatim inside that row's own input). `tool.properties`
carries the row and field counts, the categorical stats when expected
qualifies as categorical, and the duplicate and near-duplicate finding
counts.

### Analyze

The audit finds shapes; this stage decides what to do about them
(SDS-S-061). An exact duplicate is sometimes intentional — a
repeated regression case — and sometimes a copy-paste accident that
silently doubles one row's weight in the score; check which before
deleting one. A near-duplicate pair below the exact-match line still
inflates a metric that averages per-row scores. `evals/empty-expected`
is close to always a defect: a row with nothing to compare against
cannot be scored. A `evals/label-imbalance` finding does not mean the
real-world distribution is wrong — it means a model that always
answers the majority class will score high on this eval without
having learned anything, so the score needs a per-class breakdown
alongside the aggregate. `evals/leak-suspect` deserves the most
suspicion of all: a row this skill flags should be read in full before
it is trusted, since some leaks are legitimate (the input is itself
about the expected term) and some are the exact reason a model
"passes" an eval it should fail.

### Classify

Keep the script's levels and prefix each finding's `message.text` with
the action — `[merge or justify]` for a duplicate or near-duplicate,
`[fill in or drop]` for an empty expected value, `[report per class]`
for a label imbalance, `[read row N in full]` for a leak suspect.

### Synthesize

Return the finding-list, errors first, with the row and field counts
from `tool.properties` stated up front. An eval set with none of the
above yields a well-formed finding-list with an empty `results` array
(SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per row-level or eval-set-level defect, located at the row
(or the file, for `evals/label-imbalance`), with the row numbers,
similarity score, or class stats in `properties`; `runs[0].tool.properties`
carries the row, field, and rule-count inventory. No model was called
and nothing was modified.

## @throws

- `dataset-unreadable`: the path is not a readable file (missing, a
  directory, or its bytes do not decode as UTF-8 text).
- `dataset-invalid`: the file's extension names an unsupported form,
  or its content does not parse as that form (not JSON, not a JSON
  object per `.jsonl` line, not a JSON array of objects for `.json`).
- `field-invalid`: `input-field` or `expected-field` is empty.

## @example

**Input:** a `.jsonl` eval set where two rows have the identical
input text and one row's expected value is `"negative"`, which also
appears, verbatim, inside that same row's input.

**Output (excerpt):**

```json
{
  "ruleId": "evals/leak-suspect",
  "level": "warning",
  "message": { "text": "[read row 6 in full] row 6's expected value appears verbatim inside its own input" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "evals/dataset.jsonl" }, "region": { "startLine": 6 } } }],
  "properties": { "row": 6 }
}
```
