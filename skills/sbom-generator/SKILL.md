---
name: sbom-generator
description: >-
  Produces a CycloneDX software bill of materials from a repository's
  manifests and lockfiles (npm, PyPI, crates.io), with package URLs and
  every license the manifests actually declare — unknown where they do
  not — and no timestamp or serial number unless supplied, so the same
  tree always yields the same BOM. Use when a release needs an SBOM,
  when asked what a repository depends on, or as the input to
  license-compliance-check.
license: Apache-2.0
compatibility: Parsing Cargo files on Python < 3.11 requires the
  `tomli` package.
metadata:
  family: dev-skills-suite
  effect-tier: local-read-only
  idempotent: "true"
  tier: situational
  shape-out: freeform
  shape-in: freeform
  version: "0.1.0"
allowed-tools: >-
  Bash(python3 scripts/generate_sbom.py:*) Read
---

# sbom-generator

## When to use

- A release, customer, or compliance process needs a bill of
  materials.
- Asked what a project depends on, with versions.
- `license-compliance-check` needs its input.

## When not to use

- Finding vulnerabilities in those dependencies — that is
  `dependency-audit`, which queries OSV; this skill never leaves the
  working tree.
- Deciding whether the licenses are acceptable — that is
  `license-compliance-check`, which consumes this skill's output.
- Anything the manifests do not state. This skill does not resolve
  version ranges against a registry, infer licenses from package
  names, or invent a timestamp.

## @requires

- REQUIRED: a repository directory containing at least one of
  `package-lock.json`/`package.json`, `requirements.txt`, or
  `Cargo.lock`/`Cargo.toml` (a directory with none yields an empty
  BOM, not an error).
- OPTIONAL: `name` and `version` for the BOM's own component
  (default: omitted).
- OPTIONAL: `timestamp` (ISO-8601) and `serial` (`urn:uuid:…`)
  (default: both omitted — they are ambient state and would make the
  BOM non-reproducible, SDS-C-003).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a directory.
Then generate — the whole mechanical part (SDS-S-060):

```
python3 scripts/generate_sbom.py <project-dir> [--name N --version V] [--timestamp T --serial URN]
```

It reads the manifests and, for npm, `node_modules/<name>/package.json`
for declared licenses (rung 1) and prints a CycloneDX 1.5 document
(ECMA-424; SDS-C-031). Lockfiles win over manifests; a component read
from a declared range carries `sds:version-source: declared-range` so
a consumer knows the version is not resolved. A nonzero exit maps to
`@throws`. The document's minimum structure is described by
`assets/cyclonedx-minimal.schema.json`, a per-skill subset of the
official schema (SDS-S-080) — the official schema is authoritative.

### Analyze

The BOM states facts; this stage states their limits (SDS-S-061).
Report how many components have no `licenses` key (the manifests did
not say), how many carry `declared-range` (no lockfile), and which
ecosystems were found — so a reader knows what the document does not
cover before relying on it. If the user needs a signed or timestamped
BOM, that is the moment to supply `--timestamp` and `--serial`
deliberately.

### Synthesize

Return the CycloneDX document unchanged, with the coverage notes from
Analyze. An empty project yields a valid BOM with an empty
`components` array (SDS-C-033).

## @returns

Shape: `freeform` (a CycloneDX 1.5 JSON BOM).

`bomFormat` CycloneDX, one `library` component per dependency with a
purl, licenses only where declared, sorted by purl; byte-identical on
every run against the same tree when no timestamp or serial is given.
Nothing was modified.

## @throws

- `project-invalid`: the path is not a directory.
- `manifest-unparseable`: a manifest exists but is not valid JSON/TOML.
- `dependency-missing`: Cargo files present but `tomli` is unavailable
  on Python < 3.11.

## @example

**Input:** a project with a lockfile pinning `left-pad 1.3.0` (license
WTFPL in `node_modules`) and `lodash 4.17.21` (MIT), `requests==2.32.3`,
and `serde 1.0.200` in `Cargo.lock`.

**Output (excerpt):**

```json
{
  "type": "library", "name": "left-pad", "version": "1.3.0",
  "purl": "pkg:npm/left-pad@1.3.0",
  "licenses": [{ "expression": "WTFPL" }],
  "properties": [{ "name": "sds:ecosystem", "value": "npm" }]
}
```
