# Dogfood sweep on the family repository — before/after (2026-09-06)

Task 17: run `kit/scripts/sweep.py` (Task 16) against `dev-skills-suite`
itself — every applicable Query Skill's Gather, against the same
repository they live in — then fix what it finds.

## Command (before and after, identical)

```
python3 kit/scripts/sweep.py /home/edox1/Public/claude --out <dir> \
  --extra codeowners-check="--exclude evals" \
  --extra dead-code-finder="--exclude evals" \
  --extra code-comment-audit="--exclude evals" \
  --extra naming-consistency-check="--exclude evals" \
  --extra large-file-splitter-advisor="--exclude evals" \
  --extra test-smell-review="--exclude evals" \
  --extra env-var-inventory="--exclude evals" \
  --extra retry-timeout-audit="--exclude evals" \
  --extra prompt-template-audit="--exclude evals" \
  --extra test-data-pii-scan="--exclude evals" \
  --extra import-cycle-finder="--exclude evals" \
  --extra deprecation-sweep="--exclude evals" \
  --extra repository-orientation="--exclude evals"
```

`--exclude evals` was passed to every registered skill whose script
accepts it (checked each script's own usage line first) so the planted
eval fixtures — which exist to trip these exact audits — are out of
scope; a path component named `evals` matches `skills/*/evals` for
every skill in one flag. `ci-pipeline-audit`, `tech-debt-inventory`,
`devcontainer-audit`, `workspace-consistency-check`, `dockerfile-review`,
`commit-message-lint`, and `branch-hygiene` have no `--exclude` and ran
as-is; `commit-message-lint` and `branch-hygiene` need the `git` gate
(not passed) and were `SKIP`ped both times, as designed.
`dependency-audit` needs `osv` (not passed) and was skipped both times.

## Before / after

| | Before | After |
|---|---:|---:|
| Findings (digest total) | 1425 | 1327 |
| Errors | 0 | 0 |
| Warnings | 1327 | 1232 |
| Infos | 98 | 95 |
| Tools contributing findings | 8 | 7 |
| `ERROR:` exits | 2 (`deprecation-sweep`, `dockerfile-review`) | 1 (`dockerfile-review`) |

By tool:

| Tool | Before | After |
|---|---:|---:|
| tech-debt-inventory | 1220 | 1220 |
| dead-code-finder | 89 | 0 |
| naming-consistency-check | 75 | 75 |
| retry-timeout-audit | 26 | 23 |
| code-comment-audit | 12 | 6 |
| codeowners-check | 1 | 1 |
| devcontainer-audit | 1 | 1 |
| large-file-splitter-advisor | 1 | 1 |

`kit/scripts/lint-skill.py`'s own finding count (the family's largest
file, 2037 lines) dropped from 111 to 18 in "Files with most findings"
— almost entirely the `dead-code-finder` false positives below.

## ERROR exits, classified

- **`dockerfile-review`** — `evals/fixtures/broken/Dockerfile` has an
  intentionally invalid `INSTALL` instruction; the script has no
  `--exclude` flag and this family repository ships no real
  Dockerfile outside eval fixtures (it is a Python-skills repo, not a
  container image build). **Category C**: expected noise from a
  planted fixture on a tool this repository isn't a real target for.
  Left as is, per the brief's own rule for this exact shape.
- **`deprecation-sweep`** — always exits `ERROR: give --deprecations
  and/or --warnings-log; there is nothing to sweep for (no-source)`
  when given only a repository path; it has no repository-only mode
  at all, unlike the other tools' `--exclude`-shaped ERRORs. This
  matches the reasoning already recorded for the 8 skills under
  `sweep.json`'s `"excluded"` map (e.g. `license-compliance-check`).
  **Fixed**: moved to `excluded` (commit `cb6c7aa`) rather than left
  erroring on every run.

## Fixes (8 commits, at the cap)

1. **Category A** — `ci-status-gate`: `subprocess.run(["gh","api",...])`
   in `load_live()` had no timeout; added `timeout=60` with a
   `TimeoutExpired` → `ERROR: ... (gh-unreachable)` handler (an
   existing `@throws` code, no new failure code needed). Commit
   `540945e`.
2. **Category A** — `github-actions-cost-audit`: same shape, same fix,
   in `load_live()`'s `gh api actions/runs` call. Commit `1e62355`.
3. **Category A** — `findings-to-issues`: same shape, `live_issues()`'s
   `gh issue list` call. Commit `eb3ab21`.
4. **Category A** — `kit/scripts/lint-skill.py`: removed `throws_codes()`,
   verified dead by grep across `kit/` and `skills/` — `c_s039`
   reimplements the same regex inline and never calls it.
   `kit/tests/test_lint_negative.py` still 6/6 after removal. Commit
   `36747e5`.
5. **Category B** — `dead-code-finder`: 88 of its 89 findings on this
   repository were decorator-registered functions
   (`kit/scripts/lint-skill.py` registers ~90 `SDS-S-NNN` checks via
   `@check("SDS-S-NNN")`) and one `unittest.TestCase` subclass
   (`kit/tests/test_lint_negative.py`'s `Broken`) — neither leaves a
   name reference a static scan can see, the same blind spot the
   tool's existing string-registry exclusion already names. Extended
   the exclusion to any top-level def/class carrying a decorator and
   any class subclassing `*TestCase`; added
   `evals/fixtures/planted-src/framework_registered.py` and eval row
   `boundary-framework-registered-definitions`. Commit `baa7256`.
6. **Category B** — `code-comment-audit`: `GitHub` (×4), `PyYAML`, and
   `OpenAPI` in prose comments matched the CamelCase-identifier
   heuristic and were reported as dangling references to symbols that
   were never claimed to exist. Added a `COMMON_PROPER_NOUNS` denylist
   next to the existing `COMMON_WORDS` one, plus
   `evals/fixtures/planted-src/proper_nouns.py` and eval row
   `boundary-proper-noun-comments`. Commit `e4cd1ac`, tightened by
   `78bb753` (the fix's own explanatory comment used the literal word
   "CamelCase" and briefly re-triggered the rule it had just fixed —
   caught by the after-sweep, reworded, no behavior change).
7. **Kit config** — `kit/registry/sweep.json`: moved `deprecation-sweep`
   into `"excluded"` (see above). Commit `cb6c7aa`.

## Deferred (not fixed — listed with counts and reasons)

- **`tech-debt-inventory` — `debt/duplicate-block`: 1207 findings**
  (dominant single rule in the sweep). `scan_debt.py` has no
  `--exclude`, so this includes the tool's own planted duplicate
  fixtures. The largest real component is `checkpoint.py`, byte-identical
  across 7 skills (`findings-to-code-scanning`, `findings-to-issues`,
  `issue-triage`, `pr-lifecycle-manager`, `project-board-sync`,
  `release-publisher`, `report-poster`; confirmed with `diff`) —
  intentional, not neglect: the README calls the family "portable
  Agent Skills", and a shared library would break a skill copied out
  of the family on its own. Deduplicating would change the family's
  portability guarantee, which is out of this task's scope (`fix a
  finding`, not `redesign the architecture`). Left as is.
- **`tech-debt-inventory` — `debt/marker`: 12 findings** — TODO/FIXME/
  HACK/WORKAROUND comments (some in the tool's own docstring and
  planted eval fixtures describing the rule, not real debt). Fixing
  a marker means resolving the underlying TODO, which is out of scope
  for a sweep-driven fix; left as backlog markers.
- **`tech-debt-inventory` — `debt/long-file`: 1 finding** —
  `kit/scripts/lint-skill.py` at 2037 lines (threshold 500). It is the
  family's linter, implementing ~90 `SDS-S-NNN` checks; splitting it
  is a real refactor with its own review, not a sweep-sized fix.
- **`naming-consistency-check`: 75 findings** (61
  `naming/ambiguous-short-name`, 14 `naming/mixed-convention`). Spot
  checked: several `mixed-convention` hits are framework-mandated
  names the tool can't know are exempt (`setUp`/`tearDown` on a
  `unittest.TestCase`, `visit_Import`/`visit_Assign`/etc. on an
  `ast.NodeVisitor` subclass) alongside genuine style flags and the
  `text_`-trailing-underscore idiom (avoids shadowing a builtin). A
  correct fix needs a framework-name allowlist across two categories
  of finding, which is a larger rule change than a sweep-sized fix
  budget covers here; deferred with this note for the next sweep.
- **`retry-timeout-audit`: 23 of 26 findings remain** (all
  `net/subprocess-no-timeout`, `info` level). The 3 fixed above were
  the brief's named `gh api`/`gh issue` candidates. The remaining 23
  are local `git`/`python3` subprocess calls across ~18 more skill
  scripts plus `kit/scripts/sweep.py` and
  `kit/tests/test_lint_negative.py` — lower risk (no network, fast,
  local-only) than the network-facing `gh` calls fixed here, and 21
  separate files exceeds this task's 8-fix-commit cap on its own.
  Deferred; a follow-up sweep-fix task should batch these by skill.
- **`code-comment-audit`: 6 of 12 findings remain** (`Session` ×2,
  `downgrade`, `input_str`, `database_specific`, `verb_noun`) — prose
  describing external-library or target-repository identifiers
  (`requests.Session`, an Alembic `downgrade()` in a repo being
  reviewed, a tuple-shape comment, a JSON field name), not proper
  nouns; a correct fix would need real semantic understanding of
  "is this comment about this tree or a tree it inspects", which
  risks changing the rule's precision in ways this task's scope guard
  says not to attempt casually. Deferred.
- **`codeowners-check`: 1 info** — "no CODEOWNERS found". The family
  has one maintainer and no path-based review routing need; the
  finding is informational (`level: info`), not a defect. **Category
  C.**
- **`devcontainer-audit`: 1 info** — "no dev container definition
  found". The skills are plain Python scripts with no runtime beyond
  `python3`/`pyyaml`/`jsonschema`; a devcontainer isn't part of this
  repository's real workflow. **Category C.**

## Guard outputs (before push)

```
$ python3 kit/scripts/lint-skill.py --all skills --strict --no-review; echo $?
0 error(s), 0 warning(s), 55 info(s) — skills
0

$ python3 kit/scripts/run-evals.py --all skills | tail -1
TOTAL 70 skill(s): 609 passed, 0 failed, 97 skipped

$ python3 kit/tests/test_lint_negative.py
Ran 6 tests in 2.0s — OK

$ find skills -name __pycache__ -type d -exec rm -rf {} +
$ git status --short
(clean)
```

## Scope guard

No changes to `kit/scripts/lint-skill.py`'s rules (only removed a
verified-dead helper function, `throws_codes`), no new skills, no
fixture deletions. `kit/registry/sweep.json`'s `deprecation-sweep`
move is a registry-accuracy fix (mirrors 8 already-excluded entries),
not a rule-meaning change. 8 fix commits, the task's cap; the
remaining findings above are listed as deferred rather than fixed to
stay under it.
