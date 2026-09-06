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

## External repositories (added later the same day)

Task 18: point `sweep.py` at two real public repositories — a planted
fixture cannot manufacture the false positives a real, unrelated
codebase's actual style produces. Read-only throughout: both
repositories were only cloned and swept, never pushed to.

### actions/checkout

```
git clone -q --depth 50 https://github.com/actions/checkout ~/sweep-checkout
git -C ~/sweep-checkout rev-parse --short HEAD   # f548e57
python3 kit/scripts/sweep.py ~/sweep-checkout --out ~/sweep-checkout-out --needs git
```

| | Before | After |
|---|---:|---:|
| Findings (digest total) | 209 | 172 |
| Errors | 0 | 0 |
| Warnings | 138 | 139 |
| Infos | 71 | 33 |
| `ERROR:` exits | 0 | 0 |

By tool:

| Tool | Before | After |
|---|---:|---:|
| tech-debt-inventory | 129 | 129 |
| import-cycle-finder | 38 | 1 |
| ci-pipeline-audit | 31 | 31 |
| env-var-inventory | 10 | 10 |
| devcontainer-audit | 1 | 1 |

- **Fix (B)** — `import-cycle-finder`: all 38 findings were
  `arch/unresolved-import` (info); every relative specifier ended
  `.js` (TypeScript's own ESM/NodeNext convention of writing the
  compiled extension in source, e.g.
  `src/git-auth-helper.ts` importing `./git-command-manager.js`) while
  only the `.ts` source existed on disk. `resolve_js()` now falls back
  to a same-stem `.ts`/`.tsx` (or `.mts`/`.cts`) file. Eval row
  `boundary-ts-js-extension`, fixture
  `evals/fixtures/boundary-ts-js-extension/{a,b}.ts`. Commit `74408d1`.
- **True positive (A), surfaced by the fix above** — with the `.js`
  specifiers now resolving, a real warning-level 2-module cycle
  appeared: `src/git-command-manager.ts <-> src/ref-helper.ts`. The
  resolution bug had been hiding it; left as-is (real finding, not a
  defect in the rule).
- **True positives (A), not fixed** — `ci-pipeline-audit`'s 31
  findings (`ci/unpinned-action` on tag refs like `v7`/`v6`/`v4` rather
  than a commit SHA, `ci/no-timeout` on jobs with no
  `timeout-minutes`, `ci/no-concurrency` on workflows with no
  concurrency group) were spot-checked across every workflow file in
  `.github/workflows/`; every one names a real job and a real,
  unpinned tag or missing setting. No false positive found in this
  tool's output on this repository.
- **Category C** — `devcontainer-audit`'s 1 info ("no dev container
  definition found") — `actions/checkout` is a plain TypeScript action
  with no devcontainer; informational, not a defect, same shape as the
  family's own dogfood record.
- **Deferred** — `tech-debt-inventory`'s 129 findings (`debt/duplicate-block`
  dominant, concentrated in `__test__/*.test.ts`) and `env-var-inventory`'s
  10 `env/undocumented` findings: not sampled for false positives here
  (budget spent on the two fixes above plus the two on psf/requests,
  the four-fix subtotal well under the 6-fix cap but the effort budget
  for this task); a follow-up sweep-fix task should sample these.

### psf/requests

```
git clone -q --depth 50 https://github.com/psf/requests ~/sweep-requests
git -C ~/sweep-requests rev-parse --short HEAD   # dae7ef6
python3 kit/scripts/sweep.py ~/sweep-requests --out ~/sweep-requests-out --needs git
```

| | Before | After |
|---|---:|---:|
| Findings (digest total) | 548 | 519 |
| Errors | 1 | 0 |
| Warnings | 468 | 440 |
| Infos | 79 | 79 |
| `ERROR:` exits | 0 | 0 |

By tool:

| Tool | Before | After |
|---|---:|---:|
| retry-timeout-audit | 172 | 172 |
| code-comment-audit | 95 | 95 |
| naming-consistency-check | 89 | 82 |
| tech-debt-inventory | 64 | 64 |
| test-smell-review | 32 | 32 |
| dead-code-finder | 24 | 3 |
| test-data-pii-scan | 23 | 23 |
| codeowners-check | 20 | 20 |
| ci-pipeline-audit | 16 | 16 |
| large-file-splitter-advisor | 7 | 7 |
| env-var-inventory | 3 | 3 |
| import-cycle-finder | 2 | 1 |
| devcontainer-audit | 1 | 1 |

The one **error-severity finding** (the whole reason to classify
before fixing): `import-cycle-finder`'s `arch/import-cycle` on an
8-module component through `src/requests/_types.py`.

- **Fix (B)** — `import-cycle-finder`: the reported cycle only closes
  through `_types.py`'s `if TYPE_CHECKING: from .cookies import ...`
  (and similar) imports — never executed at runtime — while every
  other edge in the chain (`cookies.py -> _types.py`,
  `auth.py -> cookies.py`, `adapters.py -> exceptions.py`, etc.) is
  real; traced by hand against the real source, no real cycle exists.
  `ast.walk()` was walking into the `body` of `if TYPE_CHECKING:`
  blocks; it now skips that body (the `else` branch, if any, is still
  walked). Eval row `boundary-type-checking-only-import`, fixture
  `evals/fixtures/boundary-type-checking-py/{mod_a,mod_b}.py`. Commit
  `98963b0`. Verified: `import-cycle-finder` on the live clone reports
  `cycles: 0` after the fix.
- **Fix (B)** — `dead-code-finder`: 21 of 24 findings were classes like
  `TestSuperLen`, `TestRequests`, `TestCaseInsensitiveDict` — bare
  (no base class) pytest-style test classes, collected by pytest's own
  name-pattern convention (`Test*`, no `__init__`), not a
  `unittest.TestCase` subclass, so the existing `*TestCase` exclusion
  (added in Task 17) missed them. Extended `_framework_registered` to
  also exclude a bare top-level class named `Test*` with no
  `__init__`. Eval row `boundary-pytest-bare-class`, fixture addition
  to `evals/fixtures/planted-src/framework_registered.py`
  (`TestBareClass`). Commit `df41e9b`.
- **Fix (B)** — `naming-consistency-check`: 7 of 89 findings were
  `TypeVar` declarations (`_T_co = TypeVar("_T_co", covariant=True)`
  in `_types.py`, `cookies.py`, `structures.py`, `utils.py`) flagged
  against the tree's snake_case variable convention; PEP 484's own
  TypeVar naming convention is not this tree's variable convention.
  `X = TypeVar(...)` / `X = typing.TypeVar(...)` assignments are now
  excluded entirely — neither a vote nor a violation. Eval row
  `boundary-typevar-assignment`, fixture
  `evals/fixtures/boundary-typevar-src/module.py`. Commit `cf2e813`.
- **Category C** — `dead-code-finder`'s remaining 3 findings
  (`HTTPProxyAuth` in `auth.py`, `dict_from_cookiejar` and
  `dict_to_sequence` in `utils.py`): documented public-library API
  reached only by out-of-tree importers (`requests.auth.HTTPProxyAuth`,
  `requests.utils.dict_from_cookiejar`), not listed in `__init__.py`'s
  `__all__` or imported internally. The tool's own message already
  names this limitation ("out-of-tree importers are not visible");
  left as is.
- **True positives (A), not fixed** — `ci-pipeline-audit`'s 16
  findings and `codeowners-check`'s 20 `owners/unowned-path` findings
  (`psf/requests` ships no `CODEOWNERS`) were spot-checked; real.
- **Deferred (sampled, not fixed)**:
  - `naming-consistency-check`'s remaining 82 findings: several
    `mixed-convention` hits are deliberate, checked by hand against
    the source rather than guessed — `SOCKSProxyManager` (adapters.py)
    is a fallback stub function named to match the real
    `urllib3.contrib.socks.SOCKSProxyManager` class it substitutes for
    on `ImportError`, for drop-in API compatibility; `KD` (auth.py) is
    named per RFC 2617 Digest Access Authentication's own "KD" (Key
    Digest) notation for the hash-combining step, not an arbitrary
    short name. Both are real, deliberate exceptions to the tree's
    snake_case convention that a naming rule can't distinguish from a
    careless one without source-level context a static scan doesn't
    have; a correct general fix needs a broader allowlist than a
    single sweep-fix task's cap allows. `naming/ambiguous-short-name`
    was not sampled.
  - `code-comment-audit`'s 95 findings: the top offender is
    `docs/conf.py`, Sphinx's own generated config template — dozens of
    `comment/dangling-reference` hits on Sphinx config-variable names
    (`html_theme_path`, `epub_tocdepth`, etc.) inside commented-out
    example lines. A `docs/conf.py`-shaped exclusion risks widening
    the rule past "this specific file happens to be noisy" into
    guessing at doc-generator boilerplate in general; deferred rather
    than risk the rule's precision on a task-sized budget.
  - `test-data-pii-scan`'s 23 findings: `172.16.1.1` (an RFC1918
    private address) is flagged as an "e-mail address at a real
    domain", and `kennethreitz.com` (the project's original author's
    own domain, used in test fixtures for URL-parsing, not real PII)
    reads as ambiguous rather than a clear false positive; not fixed
    without risking the rule's precision on real leaked-PII detection.
  - `retry-timeout-audit` (172), `test-smell-review` (32),
    `large-file-splitter-advisor` (7), `tech-debt-inventory` (64),
    `env-var-inventory` (3): not sampled — outside the four fixes'
    scope and this task's effort budget; a follow-up sweep-fix task
    should sample these next.

### Fixes (4 commits, under the 6-fix cap)

1. **Category B** — `import-cycle-finder`: skip `if TYPE_CHECKING:`
   imports when building edges (found on `psf/requests`). Commit
   `98963b0`.
2. **Category B** — `import-cycle-finder`: resolve `.js`-suffixed
   TS/ESM specifiers against `.ts` sources (found on
   `actions/checkout`). Commit `74408d1`.
3. **Category B** — `dead-code-finder`: exclude bare pytest-style
   `Test*` classes (found on `psf/requests`). Commit `df41e9b`.
4. **Category B** — `naming-consistency-check`: exclude `TypeVar`
   assignments from convention votes (found on `psf/requests`).
   Commit `cf2e813`.

2 of the 4 fixes land in the same skill (`import-cycle-finder`) but
address two independent bugs found on two different repositories, so
each is its own commit per the task's rule.

### Guard outputs (before push)

```
$ python3 kit/scripts/lint-skill.py --all skills --strict --no-review > /tmp/lint-all.txt; echo $?
0 error(s), 0 warning(s), 55 info(s) — skills
0

$ python3 kit/scripts/run-evals.py --all skills | tail -1
TOTAL 70 skill(s): 613 passed, 0 failed, 97 skipped

$ python3 kit/tests/test_lint_negative.py
Ran 6 tests in 1.933s — OK

$ find skills -name __pycache__ -type d -exec rm -rf {} +
$ git status --short
(clean)
```

### Scope guard

No linter rule changes beyond the three false-positive guards listed
above (each a guard/exclusion, not a change to what its rule means);
no new skills; no fixture deletions; no changes to
`kit/registry/sweep.json` (no script crashed on either repository —
both sweeps exited 0 on every registered skill, `--needs git`
included). 4 fix commits, under the task's 6-fix cap; the remaining
findings above are recorded as true positives, documented limitations,
or deferred with reasons rather than fixed to stay well under it.
