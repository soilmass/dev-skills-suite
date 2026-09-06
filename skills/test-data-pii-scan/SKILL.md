---
name: test-data-pii-scan
description: >-
  Scans a repository's test data — fixtures, seeds, factories,
  recorded responses, snapshots — for values that look like a real
  person's: credit-card numbers that pass Luhn and are not the known
  test numbers,
  valid US Social Security Numbers, checksum-valid IBANs, e-mail
  addresses at real domains, phone numbers outside the fictional
  555-01xx range, public IP addresses, and dates of birth — as a
  finding-list with every value masked; then judges which hits are
  copied from production and must go. Use before open-sourcing or
  sharing a repository, after a "copy prod to staging" incident, when
  a privacy review asks what personal data the tests hold, or when
  asked whether the fixtures are safe to commit.
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
  Bash(python3 scripts/scan_test_data.py:*) Read
---

# test-data-pii-scan

## When to use

- A repository is about to be open-sourced or shared with a vendor.
- Someone copied production rows into a fixture, a seed, or a
  recorded cassette, or a privacy review asks what the tests hold.
- Asked whether the test data is safe to commit.

## When not to use

- Secrets and credentials (API keys, tokens, private keys) — a
  secret scanner (gitleaks, trufflehog) covers those; this skill sees
  personal data, not credentials.
- Production databases or logs — this skill reads files in the
  repository; scanning live data is a different tool and a different
  authorisation.
- Names — a name is not detectable by shape; the Analyze stage flags
  names only beside another hit in the same record.

## @requires

- REQUIRED: the repository directory.
- OPTIONAL: `paths` — the test-data directories to scan, replacing
  the conventional set (default: test, tests, spec, fixtures,
  testdata, seeds, factories, mocks, cassettes, snapshots, e2e, and
  files named `*.fixture.*`, `*.seed.*`, `*.cassette.*`).
- OPTIONAL: `allowlist` — safe e-mail domains, known test
  credit-card numbers, and literal values to ignore (default:
  `assets/allowlist.json`).
- OPTIONAL: `exclude` — directories to skip (default: none).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a
directory and every explicit `paths` entry exists. Then scan — the
mechanical part (SDS-S-060):

```
python3 scripts/scan_test_data.py <repo> [--paths dir,dir] [--allowlist <file>]
```

It reads the test-data files (rung 1; nothing is run, nothing leaves
the machine), validates every candidate — Luhn for cards, area and
group rules for SSNs, mod-97 for IBANs, reserved and allowlisted
domains for e-mail, the fictional range for phones, private and
documentation ranges for IPs — and reports `pii/credit-card`,
`pii/ssn`, `pii/iban` (errors), `pii/email`, `pii/phone`
(warnings), `pii/ip-address`, `pii/date-of-birth` (infos), with
every value masked to its last four characters. `tool.properties`
carries the directories, file counts, and hits per rule.

### Analyze

The scan says what validates; this stage decides what is real
(SDS-S-061). A record with two or more hits — an address at a real
domain beside a phone number and a date of birth — is almost
certainly a copied person: treat the whole record as personal data,
name included, and say so. A lone Luhn-valid card number in a
payments test may be a generated one — check whether the test
generates it or asserts on it; an asserted literal was typed by
someone, from somewhere. A recorded cassette with real e-mail
addresses means the recording was made against a real account —
the fix is re-recording against a test account, not editing the
cassette. Public IPs in seeds are usually infrastructure, not
people, unless paired with a user record. State what you could not
check: names, addresses, and free text are invisible to the scan.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[remove: copied record]`, `[replace with test
card 4242…]`, `[re-record against a test account]`, `[replace domain
with example.com]`, `[keep: infrastructure, not personal]`,
`[keep: generated in test]`.

### Synthesize

Return the finding-list, errors first, grouped by file, with one line
on whether the repository is safe to share and which files to purge
from history if a copied record is found (a fixture deleted today is
still in every clone's history). Clean test data yields a
well-formed finding-list with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per hit, located at the file and line, with the masked
value and the detector's details (domain, country, key) in
`properties`; `runs[0].tool.properties` carries the directories
scanned, the file counts, and hits per rule. No unmasked value
appears in the output, and nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `paths-missing`: an explicit `paths` entry is not a directory under
  the repository.
- `allowlist-invalid`: the allowlist is not a JSON object with the
  expected lists.

## @example

**Input:** `tests/fixtures/users.json` with a record whose card
number passes Luhn and is not a known test card.

**Output (excerpt):**

```json
{
  "ruleId": "pii/credit-card",
  "level": "error",
  "message": { "text": "[remove: copied record] Luhn-valid card number ************6467 in test data" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "tests/fixtures/users.json" }, "region": { "startLine": 4 } } }],
  "properties": { "value": "************6467", "length": 16 }
}
```
