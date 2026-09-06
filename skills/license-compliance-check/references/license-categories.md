# License Categories and Policy

Loaded on demand from SKILL.md's Analyze stage — only when the user
asks why a license landed in a category, or when a finding's category
needs to be argued with in context. Not needed for an ordinary check.

## Categories (SPDX identifiers)

| Category | Identifiers | Obligation that drives the policy |
|---|---|---|
| permissive | MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, 0BSD, Unlicense, WTFPL, CC0-1.0, Zlib, PSF-2.0, BlueOak-1.0.0, MIT-0, BSL-1.0 | attribution at most; no effect on the combined work's license |
| weak-copyleft | LGPL-2.1/-3.0 (-only, -or-later), MPL-2.0, EPL-1.0/2.0, CDDL-1.0 | modifications to the component itself must be shared; combining is allowed under linking/file-boundary terms |
| strong-copyleft | GPL-2.0/-3.0 (-only, -or-later) | the combined work distributed must carry the GPL |
| network-copyleft | AGPL-3.0 (-only, -or-later), SSPL-1.0 | as strong copyleft, plus "distribution" includes serving over a network |
| unknown | anything else, or nothing declared | cannot be assessed; the risk is the not-knowing |

## Policy matrix (component category down, project category across)

| component \ project | permissive / proprietary | weak-copyleft | strong-copyleft (GPL) |
|---|---|---|---|
| permissive | pass | pass | pass |
| weak-copyleft | **review** (linking terms) | pass | pass |
| strong-copyleft | **incompatible** | **incompatible** | pass |
| network-copyleft | **incompatible** | **incompatible** | **review** (network clause) |
| unknown | **unknown** | **unknown** | **unknown** |

## What the script deliberately does not decide

- Whether the component is *distributed* at all. An internal tool that
  never ships may combine anything; the finding still stands as a
  fact, and the Analyze stage says why it is acceptable here.
- Dynamic vs static linking for weak copyleft. The script reports
  `review`; the answer depends on how the build actually links.
- Dual-license intent. `MIT OR Apache-2.0` passes if either does; the
  chosen alternative should be recorded in the notice file, which is
  outside this skill.

## Deprecated identifiers

SPDX retired the bare `GPL-2.0`, `GPL-3.0`, `LGPL-2.1`, `LGPL-3.0`, and
`AGPL-3.0` in favor of explicit `-only` / `-or-later` forms. The script
evaluates a bare id as `-only` (the conservative reading) and reports
`license/nonstandard-id` so the upstream metadata can be corrected.
