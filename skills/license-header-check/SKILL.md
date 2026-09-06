---
name: license-header-check
description: >-
  Compares every source file's leading comment block against a license
  header template and reports a block that is not a header at all as a
  missing-header finding, one that names a license but does not match
  the template as a mismatch, a header whose year is older than the
  file's recorded year as stale, and a header with no
  SPDX-License-Identifier line as a separate finding — as a
  finding-list. Use before a release, when onboarding a new file
  extension into a repository's header policy, or when asked whether
  every source file carries the required license header.
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
  Bash(python3 scripts/check_license_headers.py:*) Read
---

# license-header-check

## When to use

- Before a release, to confirm every source file carries the required
  first-party license header.
- Onboarding a new file extension or directory into a repository's
  header policy and needing to know what is missing or wrong today.
- Asked whether a source file's header is current, or whether an
  SPDX identifier line is present.

## When not to use

- Checking third-party dependency licenses in a bill of materials —
  that is `license-compliance-check`, which judges compatibility
  between a dependency's license and the repository's own; this skill
  never looks at a dependency, only at a repository's own source
  files.
- Producing the bill of materials those dependency licenses come from
  — that is `sbom-generator`.
- A repository with no agreed header template — this skill has
  nothing to compare a comment block against until one exists.

## @requires

- REQUIRED: a repository directory.
- REQUIRED: `header` — the header template text, with `{year}` and
  `{owner}` placeholders (see `assets/header.example.txt`).
- OPTIONAL: `ext` — the file extensions to scan (default:
  `py,js,ts,go,rs`).
- OPTIONAL: `exclude` — directory or file names to skip beyond the
  usual vendored and build directories (default: none).
- OPTIONAL: `git-years-json-file` — a JSON object mapping each file's
  repository-relative path to the integer year it was last changed;
  turns on the stale-year check (default: off).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a directory,
and the header template file is readable. Then check — the mechanical
part (SDS-S-060):

```
python3 scripts/check_license_headers.py <repo> --header <header.txt> \
  [--ext py,js,ts,go,rs] [--exclude a,b] [--git-years-json-file <file>]
```

For each scanned file it reads the leading comment block — the run of
comment lines at the top, after an optional shebang and, for a Python
file, an optional encoding declaration — and compares it, whitespace
collapsed, against the header template. It reports a block that names
neither "Copyright" nor "Licensed under" as `license/header-missing`
(warning), a block that names one of those but does not match the
template as `license/header-mismatch` (warning), a matching header
whose year is older than the file's recorded year in
`git-years-json-file` as `license/header-stale-year` (info, only
emitted when that input is given), and a non-missing header with no
`SPDX-License-Identifier:` line as `license/spdx-missing` (info).
`tool.properties` carries the scanned file count, the count with a
matching header, the missing and mismatched counts, the count with an
SPDX line, and whether the stale-year input was given. A nonzero exit
maps to `@throws`.

### Analyze

The comparison is exact for what it resolves; this stage supplies
context (SDS-S-061). A mismatch is often a header copied from a
different, formerly-used license, or a vendored file that should have
been excluded rather than fixed — check its origin before proposing a
rewrite. A stale year on a file with real recent history is worth
flagging even if the header text is otherwise correct; a stale year on
a file that has not changed in years is lower priority.

### Classify

Keep the script's severities; prefix each finding's `message.text`
with `[add header]` for a missing header, `[replace header]` for a
mismatch, `[bump year]` for a stale year, and `[add SPDX line]` for a
missing SPDX identifier.

### Synthesize

Return the finding-list, warnings first, with a one-line summary of
how many files are missing a header outright versus carrying the wrong
one. A repository where every scanned file's header matches the
template, carries an SPDX line, and (when checked) has a current year
yields a well-formed finding-list with an empty `results` array
(SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per header outcome that is not a clean pass, located at the
source file (`region.startLine` 1 for a missing, mismatched, or
SPDX-missing header, or the line carrying the year for a stale-year
finding); `properties` names the file, and a stale-year finding also
carries the header's year and the recorded year.
`runs[0].tool.properties` carries the scanned, matching, missing,
mismatched, and SPDX counts and whether the stale-year input was
given. Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `header-unreadable`: `--header` is missing, or its file is missing
  or unreadable.
- `years-unparseable`: `--git-years-json-file` is given but is not a
  JSON object mapping paths to integer years.

## @example

**Input:** `src/legacy.js` opens with an MIT-style comment block
("Copyright 2019 Acme Corp... Permission is hereby granted..."), and
the repository's header template is the Apache-2.0 short header.

**Output (excerpt):**

```json
{
  "ruleId": "license/header-mismatch",
  "level": "warning",
  "message": { "text": "[replace header] src/legacy.js's leading comment block does not match the header template" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "src/legacy.js" }, "region": { "startLine": 1 } } }],
  "properties": { "file": "src/legacy.js" }
}
```
