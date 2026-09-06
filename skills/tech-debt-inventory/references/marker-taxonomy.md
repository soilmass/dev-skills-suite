# Debt Marker Taxonomy

Loaded on demand from SKILL.md's Analyze stage — only when the user
asks why a finding got the level it did, or when re-ranking a marker
category wholesale. Not needed for an ordinary scan.

## Markers (`debt/marker`)

| Marker | Default level | Conventional meaning | Typical re-rank |
|---|---|---|---|
| `FIXME` | warning | known-wrong behavior the author chose to ship | promote to `error` if on a request path or in a security boundary |
| `HACK` | warning | deliberate shortcut with a known better shape | keep `warning`; promote if it touches shared state |
| `XXX` | warning | author's own alarm: "this is dangerous / unclear" | promote if unexplained after `git blame` |
| `TODO` | info | planned, not yet done; not necessarily wrong today | demote to nothing if it is a tracked ticket reference; promote if it guards an unimplemented branch |
| `WORKAROUND` | info | compensates for a bug elsewhere (a dependency, a platform) | demote if the upstream bug is fixed and the workaround is now dead |

The scanner reports every occurrence; it does not read intent. A
`TODO` inside a string literal or a docstring example is a false
positive the Analyze stage should drop.

## Long files (`debt/long-file`)

Default threshold 500 lines. The signal is not length itself but the
number of responsibilities: a 700-line file with one clear purpose
(a generated table, a single large state machine) is often fine; a
300-line file mixing I/O, parsing, and business rules is the real
target. Re-rank on responsibilities, not on the line count.

## Duplicate blocks (`debt/duplicate-block`)

Default window 8 whitespace-normalized non-blank lines. Findings
sharing a `fingerprint` are the same block. Duplicated *test setup*
is usually acceptable and should be demoted; duplicated *business
logic* across modules is the case worth promoting, since a fix in one
copy silently misses the others.
