---
name: retry-timeout-audit
description: >-
  Audits a Python repository's network calls for the three shapes
  behind most cascading failures — calls with no timeout (including
  through a client object constructed without one), retry loops that
  sleep a constant instead of backing off, and `while True` retries
  with no bound — plus subprocess calls without a timeout and retry
  handlers that catch everything, as a finding-list with the call
  inventory attached. Use after an outage that spread, before a
  service goes on a request path, or when asked whether the code is
  resilient to a slow dependency.
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
  Bash(python3 scripts/audit_network_calls.py:*) Read
---

# retry-timeout-audit

## When to use

- An outage in one dependency took the service down with it.
- A service is about to sit on a request path for the first time.
- Asked whether the code copes with a slow or failing dependency.

## When not to use

- Deciding timeout *values* — that is a latency budget from the
  dependency's p99; this skill finds the absence, and Analyze
  proposes from the budget if one is known.
- Non-Python sources, for now; the call shapes are in
  `assets/network-calls.json` and a team's own client wrappers go
  there.
- Runtime behaviour under load — a load test; this skill reads
  source and calls nothing.

## @requires

- REQUIRED: the repository directory.
- OPTIONAL: `patterns` — the network call names, client
  constructors, and client methods to recognise (default:
  `assets/network-calls.json`).
- OPTIONAL: `exclude` — directories to skip (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then audit — the mechanical part (SDS-S-060):

```
python3 scripts/audit_network_calls.py <repo> [--patterns <file>] [--exclude dir,dir]
```

It resolves callees through imports and aliases with `ast` (rung 1;
nothing is called), tracks client variables back to their
constructor, and reports `net/no-timeout`,
`net/subprocess-no-timeout`, `net/constant-backoff`,
`net/unbounded-retry`, and `net/broad-retry`. `tool.properties`
carries the call count, how many carry a timeout, and the calls per
file. A file that does not parse stops the scan
(`source-unparseable`).

### Analyze

The audit finds shapes; this stage decides which are faults here
(SDS-S-061). A missing timeout on a request path is a defect; in a
one-off migration script it is a choice — say which. A timeout set
in a wrapper the audit cannot see (a session factory in another
module) is a false positive to name, and a candidate for the
patterns file's `clientConstructors`. A constant sleep in a loop
that runs at most three times is tolerable; in a loop that can run
for minutes it synchronises every retrying caller — the fix is
exponential backoff with jitter and a cap, and a total deadline.
An unbounded retry is never right on a request path; in a daemon it
needs a circuit breaker or a bounded attempt count with an alert.
A broad handler that retries `KeyError` is retrying a bug.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[add timeout=(connect, read)]`, `[set on client:
<constructor>]`, `[backoff: exponential, jitter, cap Ns, deadline
Ms]`, `[bound: N attempts then raise]`, `[narrow: catch <errors>]`,
`[keep: batch script]`.

### Synthesize

Return the finding-list, warnings first, grouped by file, with the
inventory line (calls, with timeout) and the single change that
most reduces blast radius first. A tree with safe calls, or none,
yields a well-formed finding-list with an empty `results` array
(SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per shape, located at the call or the loop, with the
call name or loop details in `properties`;
`runs[0].tool.properties` carries the inventory. Nothing was called
and nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a Python file does not parse.
- `patterns-invalid`: the patterns file is not the expected shape.

## @example

**Input:** a worker with `while True: try: requests.get(url) except
Exception: time.sleep(5); continue`.

**Output (excerpt):**

```json
{
  "ruleId": "net/unbounded-retry",
  "level": "warning",
  "message": { "text": "[bound: 5 attempts then raise; backoff with jitter] while True retries a network call on every exception with no break; a peer that is down is retried forever" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "worker/poll.py" }, "region": { "startLine": 8 } } }],
  "properties": { "handlers": [{ "line": 11, "broad": true }] }
}
```
