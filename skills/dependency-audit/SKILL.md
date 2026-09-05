---
name: dependency-audit
description: >-
  Scans a repository's dependency manifests (npm, PyPI, crates.io) for
  known vulnerabilities via the OSV database, and flags unresolved
  version ranges as best-effort. Use when reviewing a dependency bump,
  auditing supply-chain risk, checking a PR for outdated or vulnerable
  packages, or when the user mentions CVEs, npm audit, pip-audit,
  cargo audit, or "are our dependencies safe."
license: Apache-2.0
compatibility: Requires network access to https://api.osv.dev, and the
  `tomli` package if parsing Cargo files on Python < 3.11.
metadata:
  family: dev-skills-suite
  effect-tier: external-read-only
  idempotent: "true"
  tier: pillar
  shape-out: finding-list
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/parse_manifest.py:*) Bash(python3
  scripts/osv_batch_query.py:*) Bash(python3 scripts/osv_to_finding.py:*)
  Read
---

# dependency-audit

## When to use

- Reviewing a dependency version bump before merging.
- A general supply-chain/security sweep of a repository.
- The user asks whether current dependencies have known CVEs.

## When not to use

- Auditing first-party code for vulnerabilities — that's the
  installed `security-review` skill's job, not this one's. This skill
  only ever looks at third-party dependency *identity and version*,
  never application logic.
- Checking whether a dependency's *license* is compatible with the
  project's — that's `license-compliance-check` (a separate, situational
  skill in this family), even though both skills read the same manifests.

## @requires

- REQUIRED: the repository contains at least one recognized manifest
  file (`package.json`, `package-lock.json`, `requirements.txt`,
  `Cargo.toml`, or `Cargo.lock`).
- OPTIONAL: none — this skill takes no other configuration.

## Instructions

### Gather

Run, in order, from the repository root:

```
python3 scripts/parse_manifest.py <repo-path>
```

This is the skill's hermetic boundary (SDS-C-003): it reads
*only* the manifest/lockfiles listed above, nothing else. Validate its
exit code before proceeding — a nonzero exit means a manifest was
found but could not be parsed (malformed JSON/TOML, or a missing
`tomli` dependency for Cargo files); surface the script's stderr
message verbatim as the failure, per `@throws` below, rather than
guessing at the cause.

A zero exit with `[]` printed means no manifest was found, or a
manifest was found with zero dependencies. This is not a failure —
proceed to Synthesize directly and produce an empty finding-list
(see `@returns`).

If unsure why a dependency shows `"resolved": false`, consult
`references/ecosystem-notes.md` — but only then; it is not needed to
run this skill successfully in the common case.

### Analyze

Pipe the Gather output into the OSV query:

```
python3 scripts/parse_manifest.py <repo-path> | python3 scripts/osv_batch_query.py -
```

This step is `external-read-only` (Effect Ladder rung 3): it queries
`https://api.osv.dev`, an open-world system outside this repository's
control. A nonzero exit means OSV itself was unreachable or returned
an unexpected shape — this is a distinct failure mode from "queried
successfully, found nothing" (`@throws: osv-unreachable`), and should
never be silently treated as "no vulnerabilities found."

Dependencies with an unresolved version are skipped by the script
with a stderr note, since OSV cannot be queried without a concrete
version — this is a known, documented scope limit, not a bug.

### Synthesize

Convert the OSV matches into the family's canonical `finding-list`
shape:

```
... | python3 scripts/osv_to_finding.py -
```

This adapter script (SDS-C-062) is the only place OSV's raw
record format is translated — if OSV's schema changes, this is the
one file to update, not this skill's reasoning. Zero matches produce
a fully well-formed `finding-list` with an empty `results` array
(SDS-C-033), never `null` or an omitted file.

Do not re-summarize or re-word the findings before presenting them —
the adapter's `message.text` field is already the final, presentable
text.

## @returns

Shape: `finding-list` — see kit/shapes/finding-list.schema.json.

On success, every dependency with a resolvable version has been
checked against OSV, and every known vulnerability found is present in
`results` as one entry, with `level` derived from OSV's own severity
classification (`CRITICAL`/`HIGH` &rarr; `error`, `MODERATE` &rarr;
`warning`, `LOW` or unrecognized &rarr; `warning`, never silently
downgraded to `info`).

## @throws

- `manifest-unparseable`: a recognized manifest file exists but is not
  valid JSON/TOML. The failure message names the exact file and parse
  error (from `parse_manifest.py`'s stderr).
- `missing-toml-dependency`: a Cargo manifest was found but `tomli` is
  not installed and the Python version is below 3.11.
- `osv-unreachable`: the OSV API could not be reached, timed out, or
  returned a response this skill could not parse.

## @example

**Input:** a repository whose `package.json` declares
`"lodash": "4.17.15"`.

**Output (excerpt):**

```json
{
  "version": "sds-finding-list-1.0",
  "runs": [{
    "tool": { "driver": { "name": "dependency-audit", "version": "0.1.0" } },
    "results": [{
      "ruleId": "GHSA-29mw-wpgm-hmr9",
      "level": "warning",
      "message": { "text": "lodash@4.17.15 (npm) is affected by GHSA-29mw-wpgm-hmr9 (aka CVE-2020-28500): Regular Expression Denial of Service (ReDoS) in lodash [NOTE: version is an unresolved range from the manifest, not a lockfile-pinned version — treat as best-effort.]" },
      "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "package.json" } } }]
    }]
  }]
}
```

Verified live against the real OSV API on 2026-09-05; see
`evals/dependency-audit.eval.yaml` for the frozen fixtures used in
regression testing.
