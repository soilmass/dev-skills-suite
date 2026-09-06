---
name: i18n-string-inventory
description: >-
  Compares the translation keys a repository's Python and JavaScript
  code references — through t(), _(), gettext, i18n.t and the team's
  own names — with its message catalogs: keys used but missing from the
  base message catalog, keys nothing references, locales missing keys
  the base has, placeholders that differ between a translation and
  its source, and translate calls whose key the inventory cannot see
  — as a finding-list with per-locale coverage attached. Use before a
  release in a new locale, when users see raw keys, or when asked how
  complete the translations are.
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
  Bash(python3 scripts/inventory_i18n.py:*) Read
---

# i18n-string-inventory

## When to use

- A release is going out in a new or updated locale.
- Users report raw keys (`nav.home`) or the wrong language on a
  page.
- Asked how complete the translations are, or which keys are dead.

## When not to use

- Finding hard-coded user-facing strings that were never wrapped in
  a translate call — a lint for that exists per framework; this
  skill sees keys, not prose.
- Translating — a translator; this skill reports gaps and never
  writes a catalog.
- Catalog formats other than JSON (gettext `.po`, YAML) — convert
  first, or extend the script; the comparison is the same.

## @requires

- REQUIRED: the repository directory.
- REQUIRED: `catalogs` — the directory of `<locale>.json` catalogs
  (flat or nested).
- OPTIONAL: `base` — the source locale (default: `en`).
- OPTIONAL: `patterns` — the translate function names to recognise
  (default: `assets/translate-patterns.json`).
- OPTIONAL: `exclude` — directories to skip (default: none).

## Instructions

### Gather

Validate the preconditions first (SDS-C-019): the path is a
directory and the base catalog exists. Then inventory — the
mechanical part (SDS-S-060):

```
python3 scripts/inventory_i18n.py <repo> --catalogs <dir> [--base en] [--patterns <file>]
```

It finds every translate call by shape (rung 1; nothing is run),
flattens nested catalogs to dotted keys, and reports
`i18n/missing-key`, `i18n/unused-key`, `i18n/untranslated` (one per
locale, listing the keys), `i18n/placeholder-mismatch`, and
`i18n/dynamic-key`. `tool.properties` carries the locales, key
counts, per-locale coverage, and the dynamic-call count.

### Analyze

The inventory is exact for literal keys; this stage handles what it
cannot see (SDS-S-061). An unused key beside a `dynamic-key` call
in the same area is probably built at runtime (`t(\`status.${s}\`)`)
— read the call and say which keys it can produce before calling
any of them dead. A missing key is a user-visible defect whatever
the locale — first in the list. Untranslated keys block a locale's
release only if that locale is being released; report coverage per
locale and let the release decide. A placeholder mismatch is a
runtime error in most libraries — a defect, not a style issue.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[add to <base>.json]`, `[delete: unreferenced]`,
`[keep: built dynamically by <call>]`, `[translate before <locale>
release: N keys]`, `[fix placeholders in <locale>]`.

### Synthesize

Return the finding-list, errors first, followed by the coverage
table per locale and the list of keys to add or delete. A tree and
catalogs in agreement yield a well-formed finding-list with an empty
`results` array (SDS-C-033) and coverage 1.0 everywhere.

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per gap, located at the first referencing file or the
catalog, with the key, locale, and placeholders in `properties`;
`runs[0].tool.properties` carries locales, counts, and coverage.
Nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `catalog-missing`: the catalogs directory is missing or has no
  base-locale file.
- `catalog-unparseable`: a catalog is not a JSON object.
- `source-unparseable`: a Python file does not parse.
- `patterns-invalid`: the patterns file is not the expected shape.

## @example

**Input:** code calling `t("checkout.pay")`, an `en.json` without
it, and a `de.json` whose `cart.items` says `{{count}} Artikel` where
the base says `{count} items`.

**Output (excerpt):**

```json
{
  "ruleId": "i18n/missing-key",
  "level": "error",
  "message": { "text": "[add to en.json] 'checkout.pay' is referenced in 2 place(s) but absent from en.json; users see the key" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "app/checkout.py" }, "region": { "startLine": 6 } } }],
  "properties": { "key": "checkout.pay", "references": 2 }
}
```
