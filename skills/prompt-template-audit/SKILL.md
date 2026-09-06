---
name: prompt-template-audit
description: >-
  Audits the LLM calls in a Python repository — found by call shape,
  not vendor — for the prompt-engineering mistakes that cost the most
  in production: model ids that are aliases or carry no version, no
  token ceiling, user-supplied text interpolated into a prompt with
  no delimiter around it, no system prompt, and long prompts written
  inline at the call site instead of in a versioned template — as a
  finding-list with the call inventory attached. Use before shipping
  an LLM feature, when evals started drifting, or when asked to
  review how a service prompts a model.
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
  Bash(python3 scripts/audit_prompts.py:*) Read
---

# prompt-template-audit

## When to use

- An LLM-backed feature is about to ship, or its evals have started
  drifting without a code change.
- A security review asks where user text enters a prompt.
- Asked to review how a service prompts a model, or what models it
  pins.

## When not to use

- Judging prompt *quality* — this skill finds structural defects; a
  prompt that is safe and pinned can still be bad, and that review
  is a human's.
- Vendor SDK usage in other languages — Python only, for now; the
  call shapes are in `assets/llm-call-patterns.json` and a team's own
  wrapper names go there.
- Secrets in the tree (API keys) — a secret scanner, or
  `env-var-inventory` for keys read with a fallback.

## @requires

- REQUIRED: the repository directory.
- OPTIONAL: `patterns` — the call methods, model/prompt keyword
  names, and the pinned-model pattern (default:
  `assets/llm-call-patterns.json`).
- OPTIONAL: `inline-limit` — the prompt length above which an inline
  literal is reported (default: 300).
- OPTIONAL: `exclude` — directories to skip (default: none).

## Instructions

### Gather

Validate the precondition first (SDS-C-019): the path is a
directory. Then audit — the mechanical part (SDS-S-060):

```
python3 scripts/audit_prompts.py <repo> [--patterns <file>] [--inline-limit N] [--exclude dir,dir]
```

It finds every call whose method name and keywords match the
patterns (rung 1; no model is called) and reports
`prompt/unpinned-model`, `prompt/no-max-tokens`,
`prompt/user-input-interpolated`, `prompt/no-system-prompt`, and
`prompt/inline-template`. `tool.properties` carries the call count,
the model literals seen, and how many calls have a system prompt. A
Python file that does not parse stops the scan
(`source-unparseable`).

### Analyze

The audit finds shapes; this stage decides which are defects here
(SDS-S-061). An alias model id is acceptable only when the team
refreshes it deliberately and re-runs evals on each refresh — ask
whether that happens; otherwise pin. A missing `max_tokens` on a
classification call is a cost bug waiting for a long input; on a
generation call it may be intended — check the use. An
interpolation of user text without a delimiter is an injection
surface whatever the source claims to be, unless the source is a
constant or an enum. No system prompt is a defect for a
user-facing feature and fine for a one-off script. An inline
template over the limit blocks eval pinning; the fix is a template
file with a version the evals reference.

### Classify

Keep the script's levels and prefix each finding's `message.text`
with the action — `[pin: <model-id>]`, `[keep alias: refreshed with
evals on <cadence>]`, `[add max_tokens: N]`, `[wrap in <user_input>
tags]`, `[trusted source: <why>]`, `[add system prompt]`, `[move to
templates/<name>.md v1]`.

### Synthesize

Return the finding-list, warnings first, grouped by file, with the
inventory: calls, models, and the count with a system prompt. A tree
with well-formed calls, or none, yields a well-formed finding-list
with an empty `results` array (SDS-C-033).

## @returns

Shape: `finding-list` — see `kit/shapes/finding-list.schema.json`.

One result per defect, located at the call or the prompt expression,
with the model id, interpolated expression, or literal length in
`properties`; `runs[0].tool.properties` carries the inventory. No
model was called and nothing was modified.

## @throws

- `repo-invalid`: the path is not a directory.
- `source-unparseable`: a Python file does not parse.
- `patterns-invalid`: the patterns file is not the expected shape,
  or `inline-limit` is not an integer.

## @example

**Input:** a service calling
`client.messages.create(model="claude-latest", messages=[{"role":
"user", "content": f"Summarise: {user_text}"}])`.

**Output (excerpt):**

```json
{
  "ruleId": "prompt/user-input-interpolated",
  "level": "warning",
  "message": { "text": "[wrap in <user_input> tags] prompt interpolates 'user_text' with no delimiter before it; wrap user-supplied text in a tag or fence so instructions and data are separable" },
  "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "app/summarise.py" }, "region": { "startLine": 9 } } }],
  "properties": { "expression": "user_text" }
}
```
