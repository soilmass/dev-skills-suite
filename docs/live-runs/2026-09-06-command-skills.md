# Live run — findings-to-issues, findings-to-code-scanning, report-poster on `soilmass/sds-skill-testbed` and the family repo (2026-09-06)

Third live exercise of the family: the three ready Command Skills
from Task 19's list, up to and through their Confirm gates and Act.
`project-board-sync` and the plugin install were prepared but not
run (see Left as is).

## Setup (not a skill's Act)

- Pulled `~/sds-skill-testbed`, branched `planted/pii-fixture`, added
  `tests/fixtures/users.json` (copied from
  `skills/test-data-pii-scan/evals/fixtures/planted-repo/...`, all
  values invented by construction), pushed, opened
  **PR #6** (`soilmass/sds-skill-testbed`) against `main`. Not merged.
- The `audit` label did not exist on the testbed; created it.

## findings-to-issues (rung 5)

| Stage | What happened |
|---|---|
| Gather | `test-data-pii-scan` on the branch checkout → `~/live-pii-findings.json` (5 results: 2 error, 2 warning, 1 info). `plan_issues.py` live `gh issue list` read → 4 create steps at or above `warning` (the info-level `pii/date-of-birth` excluded by default). |
| Analyze | Nothing to revise; all 4 groups distinct, no pre-existing marker. |
| Decide | Plan persisted to `.skills-state/findings-to-issues/2026-09-06-plan.json`, validated against `plan-doc`. |
| Confirm | Medium gate shown once for the plan; user answered *proceed: file all 4 issues*. |
| Act | 4 steps, each: pending checkpoint → `gh issue list --search "sds-finding-group: ..."` check-before-act (no hits) → `gh issue create -R soilmass/sds-skill-testbed` → `gh issue view --json body` marker confirmed → completed. Filed **#7** (pii/credit-card), **#8** (pii/ssn), **#9** (pii/email), **#10** (pii/phone), all labeled `audit`. |
| Persist | Status-report at `.skills-state/findings-to-issues/2026-09-06-report.json`, validated against `status-report`. |
| Idempotency | Second `plan_issues.py` run: **"File 0 issue(s) ... (4 already open, skipped)"** — `idempotent: "true"` holds. |

## findings-to-code-scanning (rung 5)

| Stage | What happened |
|---|---|
| Gather | `kit/scripts/lint-skill.py --all skills --json --no-review` → `~/live-lint-findings.json` (55 results, all `info`). `prepare_sarif.py /home/edox1/Public/claude ~/live-lint-findings.json` → merged SARIF at commit `4e8201c21fc578aec8a638b7221086107528d28d`, `refs/heads/main`, 55 results. |
| Analyze | Result count (55) matches the family's own lint INFO rows exactly — expected, not a surprise; `--ref` matches `main`. |
| Decide | No completed checkpoint existed yet for this commit_sha + ref + tool_name. |
| Confirm | Medium gate shown; user answered *proceed: upload the analysis*. |
| Act | Pending checkpoint → payload (results stripped) written to `.skills-state/findings-to-code-scanning/4e8201c-payload.json` → `gh api -X POST repos/soilmass/dev-skills-suite/code-scanning/sarifs` → **sarif_id `1c0fb1d6-a9e1-11f1-957e-0474ebf55efe`** → `gh api -X GET .../sarifs/<id>` on the first poll already returned `processing_status: complete` (no retry needed) → step marked `completed` via `checkpoint.py`, then `postState` was added by hand-editing `.skills-state/findings-to-code-scanning/4e8201c.json` with the GET response after the fact, `completedAt` unchanged, because the script refuses `--post-state-file` on an already-completed step (see "What the skills' text got wrong"). |
| Persist | Status-report at `.skills-state/findings-to-code-scanning/4e8201c-report.json`, validated against `status-report`. |
| Idempotency | `checkpoint.py findings-to-code-scanning 4e8201c --show` reports the step `completed` — a second run stops at Decide per SDS-C-004, without a second upload. |

## report-poster (rung 5)

| Stage | What happened |
|---|---|
| Gather | `findings-digest` over `~/live-pii-findings.json` → `~/live-digest-report.json` (6 sections). `render_report_comment.py ... --target pr:6` → payload at `.skills-state/report-poster/pr-6-payload.json`, marker `<!-- sds-report: 4a9bb7b9d8d3 -->`. |
| Analyze | Comment body reads fine for PR readers; target PR #6 matches what the report covers (the planted-fixture branch). |
| Decide | `gh pr view 6 --json comments` (Gather-adjacent read) found no comment carrying the marker. |
| Confirm | Medium gate shown; user answered *proceed: post the comment*. |
| Act | Check-before-act repeated → pending checkpoint → body extracted to `.skills-state/report-poster/pr-6-body.md` → `gh pr comment 6 -R soilmass/sds-skill-testbed --body-file ...` → **https://github.com/soilmass/sds-skill-testbed/pull/6#issuecomment-5558740885** → marker confirmed present → completed. |
| Persist | Status-report at `.skills-state/report-poster/pr-6-report.json`, validated against `status-report`. |
| Idempotency | `gh pr view 6 --json comments` now returns the marker on the posted comment — a second run's check-before-act would skip. |

## What the skills' text got wrong

- `checkpoint.py`'s own usage-error message (printed on any malformed
  invocation, including `--help`) named only `--step`, `--status`,
  and `--state-dir` — omitting `--pre-state-file`,
  `--compensating-action`, and, critically, `--post-state-file`, all
  three of which the script's own docstring documents and fully
  supports. Nothing in the short usage string suggested `postState`
  could be attached at completion time, which is exactly what
  findings-to-code-scanning's Act needed and did not get in the live
  run above (see that row). Fixed in this commit across all seven
  identical copies of the script
  (`skills/{findings-to-code-scanning,findings-to-issues,issue-triage,
  pr-lifecycle-manager,project-board-sync,release-publisher,
  report-poster}/scripts/checkpoint.py`, previously byte-identical at
  md5 `2ac94d48c2492e683a9f0ae0f9485aa8`) — the usage string now lists
  all three optional flags per mode.
- `findings-to-code-scanning/SKILL.md`'s Act paragraph said to
  "confirm the upload landed with `gh api -X GET ...`" and then "mark
  the step `completed` with that response as `postState`" without
  saying how — it read as if `postState` attached itself, or could be
  added on a later, separate call. The correct sequence is: save the
  GET response to a file, then pass that file with
  `--post-state-file <path>` on the very `--status completed` call
  that marks the step done — `checkpoint.py` has no way to attach
  `postState` to a step once it is already `completed`. That gap is
  why the live run's `postState` above had to be added by a hand
  edit of the checkpoint record instead. Fixed in this commit.

## Left as is

- `project-board-sync`: still blocked on the `project` scope; user
  declined to run `gh auth refresh -s project` this session ("skip
  both for now"). Prepared plan target unchanged from Task 19 Phase 1.
- Plugin install (`/plugin marketplace add soilmass/dev-skills-suite`
  + `/plugin install dev-skills-suite@dev-skills-suite`): user
  decision, deferred.
- The testbed now carries issues #2–#10, PR #6 (open, unmerged), one
  code scanning analysis on the family repository, and one PR comment
  on #6.

## The family's own release (v1.3.0-draft)

Task 20: the family released itself, on itself — `changelog-writer` →
`release-notes-writer` → `ci-status-gate` → `release-publisher`
against `soilmass/dev-skills-suite` at `HEAD` (`3522623`). Dispatched
in two phases: Phase 1 ran every non-mutating stage and handed back
the high gate; the user answered "Proceed, marked pre-release";
Phase 2 ran Act.

| Skill / stage | What happened |
|---|---|
| changelog-writer — Gather | `collect_commits.py . --since v1.2.0-draft` (from `skills/changelog-writer`) → 48 commits since `v1.2.0-draft`: 15 Added, 18 Fixed, no Uncategorized, 15 chore/docs/test/ci/build/style omitted by default. No `CHANGELOG.md` exists in this repo, so only Gather ran (`render_changelog.py`, the Act stage, is out of scope for a release-notes pipeline that never touches the working tree). |
| release-notes-writer — Gather/Analyze/Synthesize | `prepare_notes.py --product dev-skills-suite --version 1.3.0-draft` → same two sections, hashes stripped, `needsReview: []` — nothing withheld. |
| ci-status-gate — Gather/Analyze/Synthesize | `evaluate_checks.py /home/edox1/Public/claude --ref HEAD` (live) → `chosenOption: pass` — "all 2 required check(s) concluded successfully"; drivers `conformance: success`, `hermetic: success`. Passed on the first read; no polling needed. |
| release-publisher — Gather/Analyze/Decide | `assess_release_readiness.py … --version v1.3.0-draft --notes-file … --ci-decision-file …` → `chosenOption: publish` — "no release for v1.3.0-draft exists, the notes are complete and name 1.3.0, and CI passed". Run twice more before Act (check-before-act each time): both returned `publish` unchanged. |
| release-publisher — Confirm | High-risk gate (`kit/shared/gates/high.md`) shown, filled with the tag, repo, commit, notes summary, and CI line. User answered "Proceed, marked pre-release". |
| release-publisher — Act | `checkpoint.py release-publisher v1.3.0-draft --step publish --status pending` → `gh release create v1.3.0-draft -R soilmass/dev-skills-suite --target 3522623d99e1ac67fa29d669378c91bab447e1a8 --title "dev-skills-suite v1.3.0-draft" --prerelease --notes-file …/v1.3.0-draft-notes.md` → succeeded → `gh release view … --json url,tagName,targetCommitish,isPrerelease` captured to `v1.3.0-draft-post.json` → `checkpoint.py … --step publish --status completed --post-state-file …-post.json`. Release: **https://github.com/soilmass/dev-skills-suite/releases/tag/v1.3.0-draft** (`isPrerelease: true`, `targetCommitish: 3522623d99e1ac67fa29d669378c91bab447e1a8`). |
| release-publisher — Persist | Status-report at `.skills-state/release-publisher/v1.3.0-draft-report.json`, validated against `status-report`. |
| release-publisher — Idempotency | A third `assess_release_readiness.py` run → `chosenOption: already-published` — "v1.3.0-draft was published at 2026-09-06T19:20:42Z; nothing to do" — `idempotent: "true"` holds. |

`git fetch --tags origin` afterward confirmed `v1.3.0-draft` locally
(the release call creates the tag server-side; nothing was tagged by
hand). The registry `version` field is left at `1.2.0-draft` — bumping
it is Task 26's job, deliberately not done here.

### What the skills' text got wrong

- `release-publisher/SKILL.md`'s Act paragraph gave the completion
  call as a bare `--status completed`, with no way to attach the
  release's actual URL and commit as `postState` — the same gap Task
  19 found and fixed in `findings-to-code-scanning/SKILL.md` (see
  above), present here too because the two Act paragraphs were
  written independently. Fixed in this commit: save the `gh release
  view` response to a file and pass it with `--post-state-file <path>`
  on the same `--status completed` call.
