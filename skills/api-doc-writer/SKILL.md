---
name: api-doc-writer
description: >-
  Extracts a Python package's public signatures and docstrings, detects
  drift between an existing reference page and the code, and
  writes a Diataxis-style reference page in which anything the code
  does not state is marked undocumented rather than invented. Use when
  API docs are missing or stale, before publishing a library, or when
  asked to write reference docs for a module's public interface.
license: Apache-2.0
compatibility: Requires the Python `jsonschema` package (the render
  script validates the extract against this skill's asset schema).
  Extraction covers Python source only.
metadata:
  family: dev-skills-suite
  effect-tier: local-write
  idempotent: "true"
  tier: pillar
  shape-out: freeform
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/extract_api.py:*)
  Bash(python3 scripts/render_api_docs.py:*) Bash(git log:*) Read
  Write
---
<!-- Write is used only for the two-phase checkpoint under
     .skills-state/api-doc-writer/ and for the extract JSON handed to
     the render script (SDS-S-024). The reference page itself is
     written by scripts/render_api_docs.py, a rung-4 local write.
     Re-running against unchanged code rewrites an identical page, so
     idempotent is "true". -->

# api-doc-writer

## When to use

- A package has no API reference, or the one it has is stale.
- Before publishing or tagging a library release.
- Asked to document a module's public interface.

## When not to use

- Writing a tutorial or how-to — those are other Diataxis quadrants;
  this skill produces *reference* only (what each symbol accepts,
  returns, and raises). `onboarding-doc-generator` and
  `readme-writer` (situational) cover the others.
- Describing behavior the code does not state. This skill marks such
  symbols undocumented; filling them in is a code change (add the
  docstring), not a documentation change.
- Non-Python sources, for now.

## @requires

- REQUIRED: a Python package directory or a single `.py` file.
- REQUIRED: the output file's directory exists (created by the user —
  a missing directory is `out-dir-missing`).
- OPTIONAL: `existing` — the current reference page, so drift can be
  reported before it is overwritten (default: none).
- OPTIONAL: `include-private` — also include leading-underscore names
  in the page (default: no).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the source path exists,
the output directory exists. Then extract — the mechanical part
(SDS-S-060), via `ast`, without importing or running the code:

```
python3 scripts/extract_api.py <package-or-file> [--existing <reference.md>] [--include-private]
```

Write its output to the extract file. It conforms to
`assets/api-extract.schema.json`, this skill's own intermediate shape
(a per-skill asset, SDS-S-080; the family shape-out stays freeform).
With `--existing`, the `drift` list names documented symbols that no
longer exist or whose signature changed. A nonzero exit maps to
`@throws`.

### Analyze

Read the extract, not the code. For every symbol with `documented:
false`, look for a *sourceable* description: a docstring on a wrapper,
a test that names the behavior, a call site that shows the contract.
If one exists, note it with its location; if none does, the symbol
stays undocumented. Read each `drift` entry and decide whether the
old text was wrong or the code moved — both are reported, neither is
silently dropped.

### Decide

Preview the page:

```
python3 scripts/render_api_docs.py <extract.json> --out <reference.md> --dry-run
```

Where Analyze found a sourceable description, add it to the extract's
`summary` for that symbol *with its source cited inline* (for example,
"per tests/test_client.py::test_post_echoes_payload"). Never replace
the undocumented marker with unsourced prose; a reader who sees the
marker knows to read the code, a reader who sees confident prose does
not.

### Confirm

Rung 4 needs no gate (SDS-S-031); show the dry run, the count of
undocumented symbols, and every drift entry anyway — the drift list
is exactly what a maintainer wants to see before an old page is
overwritten.

### Act

Write the `pending` checkpoint (single mutating step — inline via the
Write tool, SDS-S-055) to `.skills-state/api-doc-writer/<package>.json`
with `preState` = the existing page's path if one is being replaced,
then:

```
python3 scripts/render_api_docs.py <extract.json> --out <reference.md>
```

Check-before-act (SDS-C-046): if the target page already equals the
dry-run output, this is a no-op; skip the write. On success update the
checkpoint to `completed` with `postState` = symbol and undocumented
counts.

**Compensating action** (SDS-S-054): restore the previous page from
version control (`git checkout -- <reference.md>`) if one was
replaced, or delete the new file if none was.

**Checkpoint** (SDS-S-053): the pending-then-completed record at
`.skills-state/api-doc-writer/<package>.json`.

### Communicate

N/A — the reference page reaches readers through the repository's
normal review and publishing path; this skill sends no message.

### Persist

The rendered page at `<reference.md>` is the durable artifact. Return
its path, the symbol count, the undocumented count, and the drift list.

## @returns

Shape: `freeform` (a markdown reference page).

The page contains one `## <module>` per public module and one
`### <symbol>` per public symbol with a fenced signature; every symbol
lacking a docstring carries the literal undocumented marker; drift, if
any, is listed at the top. Exactly one file was written.

## @throws

- `source-missing`: the path is neither a `.py` file nor a directory
  containing one.
- `source-unparseable`: a source file does not parse.
- `reference-unreadable`: the `existing` reference could not be read.
- `extract-unparseable`: the extract handed to the renderer is not JSON.
- `extract-invalid`: the extract fails `assets/api-extract.schema.json`.
- `out-dir-missing`: the output file's directory does not exist.

## @example

**Input:** `sample_pkg/`, whose `Client.post` has no docstring, with
an existing reference that still lists a removed `Client.old_fetch`
and an older `Client.get` signature.

**Output (excerpt):**

```markdown
## Drift
- `Client.get`: signature-changed (documented `get(self, path: str) -> dict`, actual `get(self, path: str, *, timeout: float | None = None) -> dict`)
- `Client.old_fetch`: removed

### `Client.post`

```python
post(self, path: str, payload: dict) -> dict
```

_Undocumented — behavior not stated in the code; do not infer._
```
