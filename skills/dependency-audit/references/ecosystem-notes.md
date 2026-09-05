# Ecosystem Parsing Notes

Loaded on demand from SKILL.md's Gather step — only open this file once
`parse_manifest.py` has told you which ecosystem(s) were found, and
only if you need to explain a result's provenance to the user (e.g.
"why is this version marked unresolved?"). Not needed for the common
case where the script's output speaks for itself.

## npm

- `package-lock.json` (v2/v3, the `packages` object) is authoritative
  when present: it holds the actually-installed, resolved version,
  not a declared range.
- Falling back to `package.json` alone means every version is a
  *range* (`^4.17.15`, `~1.2.0`), not a pin. `parse_manifest.py`
  strips the range operator and queries OSV against the resulting
  string as a best-effort concrete version — this can both miss real
  vulnerabilities (if the actually-installed version differs) and
  over-report (if it doesn't). Findings from an unresolved dependency
  carry an explicit note to this effect; don't strip that note when
  presenting results.

## PyPI

- Only exact pins (`name==1.2.3`) in `requirements.txt` are treated as
  resolved. Range specifiers (`>=`, `~=`), unpinned bare names, and
  `-r other-file.txt` / VCS / URL requirements are currently out of
  scope for this skill and are skipped rather than guessed at.
- `pyproject.toml` / `poetry.lock` / `Pipfile.lock` are not yet parsed.
  If asked to audit a project using one of these instead of
  `requirements.txt`, say so explicitly rather than silently reporting
  zero dependencies — an empty result here means "nothing parseable
  found," not "nothing to worry about."

## crates.io (Rust)

- `Cargo.lock` (`[[package]]` entries) is authoritative when present,
  same reasoning as npm's lockfile.
- `Cargo.toml` alone gives declared ranges, same caveat as npm.
- Parsing requires the `tomli` package on Python < 3.11 (the standard
  library's `tomllib` on 3.11+ is used automatically if available).
  This is the one real external dependency in this skill's scripts;
  it is not vendored, per the Base Spec's "clearly document
  dependencies" allowance for scripts that aren't fully self-contained.

## OSV ecosystem strings

`parse_manifest.py` emits OSV's own ecosystem identifiers directly
(`npm`, `PyPI`, `crates.io`) so no translation layer is needed between
Gather and the OSV query step — this was a deliberate Standards-First
choice (SDS-C-031): normalize to the external standard's
vocabulary at the earliest point, not at the adapter boundary.
