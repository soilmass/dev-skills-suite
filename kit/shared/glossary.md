# Shared Glossary

One canonical term per concept. Every skill in this family MUST use
these terms; introducing a synonym in a SKILL.md is nonconformant
(SDS-F-061, SDS-S-034). Add to this table before inventing a new term — check here
first.

| Term | Definition | Do not use instead |
|---|---|---|
| repository | The version-controlled project a skill operates on | codebase, project, repo (fine in casual prose, never as a defined term) |
| artifact | The structured output a skill produces | document, deliverable, output file |
| shape | The registered, machine-checkable type an artifact conforms to | schema (reserve for the JSON Schema file itself), format |
| finding | One entry inside a finding-list | problem, item |
| GitHub issue | An item in a repository's issue tracker, the object the GitHub cluster (issue-triage, project-board-sync) operates on; never a synonym for finding, which is an entry a skill produced (SDS-C-031) | ticket |
| gate | A Confirm stage | checkpoint (reserved, see below), approval step |
| checkpoint | The two-phase persisted record for a mutating Act step — `pending` before the call, `completed` after (SDS-S-053) | gate, save point |
| rung | One level of the Effect Ladder (SDS-C-040) | risk level, danger level, tier (reserved, see below) |
| tier | `pillar` or `situational` — a skill's priority within the family (SDS-S-019) | rung (reserved, see above), level |
| family | The set of skills governed by one instance of SDS | suite, catalog, collection |
| family root | The directory containing `kit/`, `skills/`, and `docs/`; all cross-references are relative to it, and it is not necessarily the git toplevel (SDS-F-030) | repo root, project root |
| conditional Act path | A Command Skill's declared Decide-stage branch (`**If <condition>: stop here.**`) on which Confirm and Act are not reached (SDS-S-041) | optional action, dry run |
| checkpoint record | The two-phase `.skills-state/<skill>/<key>.json` record: `pending` before the mutating call, `completed` after (SDS-S-053) | save file, state file |
| frozen fixture | A committed recording of one real open-world response (`evals/fixtures/frozen-<source>-<what>.json`) used in place of a live call by blocking eval rows (SDS-S-093) | mock, stub, snapshot |
| generator | An idempotent `evals/fixtures/build-<name>.sh` that recreates a fixture which cannot be checked in as static content, e.g. a git repository (SDS-S-096) | builder script, setup script |
