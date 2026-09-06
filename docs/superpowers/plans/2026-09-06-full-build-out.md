# dev-skills-suite Full Build-Out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the family from "60 conformant skills with a linter, a runner, and CI" to a complete, self-verifying, fully exercised product: every shape has producers *and* consumers, every thin cluster is filled, every Command Skill has been run live, the kit can prove its own linter and hermeticity, the family ships its own releases with its own skills, and a reader can find the right skill in one page.

**Architecture:** Nothing here changes the core model (TRIGGER → PROCEDURE(INPUTS) → OUTPUT under PERMISSIONS, SDS 1.0-draft rev 04). Work is grouped into five workstreams that can run in order or, after W0, in parallel: **W0** kit hardening (the tools that check everything else get their own tests), **W1** closing the shape graph (finding-list and status-report gain Command consumers), **W2** the fourth bench (thin clusters and a security seam), **W3** utilization (a sweep runner, dogfooding on real repositories, live runs, the family's own release through its own skills), **W4** docs, spec revision 05, and the v1.3.0-draft tag. Every new skill follows the one standing recipe (Task 6 is written out in full as the reference; later skill tasks give their normative rule tables, fixtures, and rows and reuse that recipe's mechanics).

**Tech Stack:** Python 3.10+ stdlib + `pyyaml` + `jsonschema`; bash; `gh` CLI (read-only in scripts, direct gated calls for mutations); GitHub Actions; xml2rfc for the SDS renderings.

## Global Constraints

Copied from the SDS and the family's standing practice; every task inherits them.

- Family root is `/home/edox1/Public/claude`; it is its own git repo (`origin` = `https://github.com/soilmass/dev-skills-suite`, branch `main`). Run every git and kit command from the family root.
- Skill = `skills/<name>/{SKILL.md, scripts/, assets/, references/, evals/<name>.eval.yaml, evals/fixtures/}`; dir name == `name` == `^[a-z0-9]+(-[a-z0-9]+)*$`.
- `metadata` has exactly seven string keys: `family, effect-tier, idempotent, tier, shape-out, shape-in, version`. Rung ≥ 3 requires a `compatibility` line. Never bare `Bash(python3:*)`; script tokens are `Bash(python3 scripts/<file>:*)`.
- Section order in SKILL.md is exact: `# <name>`, `## When to use`, `## When not to use`, `## @requires`, `## Instructions`, `## @returns`, `## @throws`, `## @example`. Query stages `Gather, [Filter], Analyze, [Classify], Synthesize`; Command stages all seven `Gather, Analyze, Decide, Confirm, Act, Communicate, Persist` (inapplicable ones start `N/A — <reason>`).
- Required eval rows: `happy-path*`; `boundary-empty-*` (success) and `boundary-malformed-*` (failure); `mutation-fixture*` (success iff `shape-out == finding-list`, else N/A); `fixed-point` (success iff registered `shape-out == shape-in`, else N/A); `contract-with-*`. Blocking rows never touch a live system; frozen recordings are `evals/fixtures/frozen-<source>-<what>.<ext>`.
- Scripts: JSON on stdout, exit 0 + empty instance on empty input, exit 1 + `ERROR: … (<failure-code>) …` on stderr on failure; every `@throws` code appears literally in the script's message. Every external call has an injectable-fixture flag (`--<thing>-json-file`) and clocks are injected (`--as-of`).
- Glossary do-not-use words never appear bare in description, headings, `@requires`, or the `@returns` Shape line: `codebase, project, document, deliverable, schema (as a noun for a Shape), format, problem, level, suite, catalog, collection, card, ticket, snapshot, mock, stub`. Use `repository, artifact, shape, finding, severity, family, message catalog, board item, GitHub issue, frozen fixture`.
- Standing pre-commit sequence (run under exit guards; never pipe the linter into `head`):
  ```bash
  cd /home/edox1/Public/claude
  python3 kit/scripts/lint-skill.py skills/<name> --no-review > /tmp/lint.txt; L1=$?
  python3 kit/scripts/lint-skill.py --all skills --strict --no-review > /tmp/lint-all.txt; L2=$?
  python3 kit/scripts/run-evals.py skills/<name>; E=$?
  test $L1 -eq 0 -a $L2 -eq 0 -a $E -eq 0 && grep -q "0 warning" /tmp/lint.txt
  python3 -c "import json,jsonschema; jsonschema.validate(json.load(open('kit/registry/marketplace.json')), json.load(open('kit/registry/marketplace.schema.json')))"
  python3 kit/scripts/render_index.py && python3 kit/scripts/render_plugin.py
  python3 kit/scripts/render_index.py --check && python3 kit/scripts/render_plugin.py --check
  ```
- Commit messages are Conventional Commits with scopes `docs(sds)`, `feat(kit)`, `fix(kit)`, `feat(skills)`, `fix(skills)`, `docs(catalog)`, `ci`, `chore(release)`, and end with the two trailers `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01Cyf7ARTjtMpjw8LEMGzwqw`. One commit per skill or per kit change; push after each.
- The snap `gh` cannot read the session scratch directory; anything `gh` must see is cloned under `~`.
- A spec change = XML edit + `xml2rfc … --text --html` regenerated renderings + linter rule-table update in the same commit when a MACHINE rule changes (SDS-F-050). After any spec edit, the cross-check must print `body^appB []`, `appB^linter []`.
- Rung-5/6 Act steps are direct, unwrapped `gh` calls with `-R owner/repo`, never `cd`, never inside a bundled script; each is preceded by a `pending` checkpoint and followed by `completed`.
- Mutating live runs (W3) target only `soilmass/sds-skill-testbed` (kept on purpose) or the family repository itself, and only after their gate is answered by the user.

---

## Workstream map

| Workstream | Tasks | Produces |
|---|---|---|
| W0 Kit hardening | 1–5 | linter negative tests in CI, hermetic eval job, shape-compat job, scaffolder, runner `--json` + SARIF upload |
| W1 Close the shape graph | 6–8 | `findings-to-issues` (rung 5), `findings-to-code-scanning` (rung 5), `report-poster` (rung 5) |
| W2 Fourth bench | 9–15 | `import-cycle-finder`, `layer-boundary-check`, `workspace-consistency-check`, `flag-retirement-plan-writer`, `eval-dataset-audit`, `dockerfile-review`, `license-header-check` |
| W3 Utilization | 16–21 | `sweep.py`, dogfood sweep on three real repositories, live runs of every Command Skill, the family's own release via its skills |
| W4 Docs, spec, tag | 22–26 | `CHOOSING-A-SKILL.md` (generated), SDS revision 05, promotion review, `v1.3.0-draft` |

---

## W0 — Kit hardening

### Task 1: Linter negative tests, run in CI

The linter is 2,014 lines and has never had a permanent test. Verification item 6 of the original plan (break one rule per category, confirm the ERROR) was done once by hand; make it permanent.

**Files:**
- Create: `kit/tests/test_lint_negative.py`
- Create: `kit/tests/README.md`
- Modify: `.github/workflows/conformance.yml` (add a step after "Lint every skill")
- Modify: `kit/HOW-TO-BUILD-A-SKILL.md` Step 11 item 0 (one sentence: the linter's own tests live in `kit/tests/`)

**Interfaces:**
- Consumes: `python3 kit/scripts/lint-skill.py <dir> --json --no-review` (exit 1 on ERROR; stdout is a `finding-list` whose `results[].ruleId` are SDS IDs).
- Produces: `kit/tests/test_lint_negative.py` runnable by `python3 -m pytest kit/tests -q` and by `python3 kit/tests/test_lint_negative.py` (stdlib `unittest` fallback so CI needs no pytest).

- [ ] **Step 1: Write the failing test file**

```python
#!/usr/bin/env python3
"""Negative tests for kit/scripts/lint-skill.py: copy a conformant skill,
break exactly one rule, and assert the linter reports that rule's ID.
Runs under unittest (no pytest needed): python3 kit/tests/test_lint_negative.py
"""
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LINT = ROOT / "kit" / "scripts" / "lint-skill.py"
BASE = ROOT / "skills" / "codeowners-check"   # small, rung 1, finding-list


def lint_ids(skill_dir: Path) -> set[str]:
    r = subprocess.run([sys.executable, str(LINT), str(skill_dir), "--json", "--no-review"],
                       capture_output=True, text=True, cwd=ROOT)
    doc = json.loads(r.stdout)
    return {res["ruleId"] for res in doc["runs"][0]["results"] if res["level"] == "error"}


class Broken(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lint-neg-"))
        self.skill = self.tmp / "codeowners-check"
        shutil.copytree(BASE, self.skill)
        # the linter resolves kit/ from the skill's family root; point it at ours
        self.env_root = ROOT

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, rel, old, new):
        p = self.skill / rel
        text = p.read_text(encoding="utf-8")
        assert old in text, f"{old!r} not in {rel}"
        p.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_missing_section_order(self):          # SDS-S-030 section order
        self.edit("SKILL.md", "## When not to use", "## Not when")
        self.assertIn("SDS-S-030", lint_ids(self.skill))

    def test_parent_path_reference(self):          # SDS-F-030 no ../
        self.edit("SKILL.md", "kit/shapes/finding-list.schema.json", "../kit/shapes/finding-list.schema.json")
        self.assertIn("SDS-F-030", lint_ids(self.skill))

    def test_forbidden_tool_always(self):          # SDS-S-023 denylist
        self.edit("SKILL.md", "allowed-tools: >-\n", "allowed-tools: >-\n  Bash(gh pr merge:*)\n")
        self.assertIn("SDS-S-023", lint_ids(self.skill))

    def test_missing_contract_row(self):           # SDS-S-098 contract row required
        ev = self.skill / "evals" / "codeowners-check.eval.yaml"
        text = ev.read_text(encoding="utf-8")
        head, _, _ = text.partition("  - name: contract-with-")
        ev.write_text(head, encoding="utf-8")
        self.assertIn("SDS-S-098", lint_ids(self.skill))

    def test_throws_code_not_declared(self):       # SDS-S-038 failureCode ⊆ @throws
        self.edit("evals/codeowners-check.eval.yaml", "failureCode: repo-invalid", "failureCode: made-up-code")
        self.assertIn("SDS-S-038", lint_ids(self.skill))

    def test_clean_copy_passes(self):
        self.assertEqual(lint_ids(self.skill), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

Before writing: confirm the five rule IDs by running `python3 kit/scripts/lint-skill.py --rules | grep -E 'section-order|no-parent|forbidden-always|contract-row|throws-codes'` and use the IDs printed (the slugs above are the family's; the numbers must come from `--rules`, not from memory). Also confirm `codeowners-check`'s failure code `repo-invalid` exists with `grep -n repo-invalid skills/codeowners-check/evals/codeowners-check.eval.yaml`.

- [ ] **Step 2: Run it to verify the copy-outside-family behaviour**

Run: `python3 kit/tests/test_lint_negative.py`
Expected: the `test_clean_copy_passes` case may FAIL with registry errors (`SDS-F-012` no registry entry for a skill outside `skills/`). If so, the linter needs a `--no-registry` flag: add it in `kit/scripts/lint-skill.py` `main()` argparse (`ap.add_argument("--no-registry", action="store_true")`) and skip the `SDS-F-01x` registry checks when set; document the flag in the module docstring and in SDS-K-070's rule-table line. Re-run until only the intended IDs differ.

- [ ] **Step 3: Make every case pass**

Adjust the `old` strings in `edit()` calls to the exact text in `skills/codeowners-check/SKILL.md` and its eval file (open both; do not guess). Run: `python3 kit/tests/test_lint_negative.py` → `OK`.

- [ ] **Step 4: Wire into CI**

In `.github/workflows/conformance.yml`, after the "Lint every skill (warnings fail)" step:
```yaml
      - name: Linter negative tests
        run: python kit/tests/test_lint_negative.py
```

- [ ] **Step 5: Write `kit/tests/README.md`** (five lines: what lives here, how to run, that every MACHINE rule added to the linter gets a case here).

- [ ] **Step 6: Commit and push; watch CI**

```bash
git add kit/tests .github/workflows/conformance.yml kit/scripts/lint-skill.py kit/HOW-TO-BUILD-A-SKILL.md
git commit -q -m "test(kit): negative tests for the linter, run in CI"
git push -q origin main
gh run watch $(gh run list -R soilmass/dev-skills-suite --limit 1 --json databaseId --jq '.[0].databaseId') -R soilmass/dev-skills-suite --exit-status
```

### Task 2: Hermetic eval job (no network) in CI

Prove SDS-S-092 mechanically: blocking rows pass with the network removed.

**Files:**
- Modify: `.github/workflows/conformance.yml` (add a second job)

- [ ] **Step 1: Add the job**

```yaml
  hermetic:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    needs: conformance
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: "3.12"
      - run: python -m pip install --quiet pyyaml jsonschema
      - name: Run every eval row with the network removed
        run: sudo unshare -n sudo -u runner env PATH="$PATH" python kit/scripts/run-evals.py --all skills
```

- [ ] **Step 2: Verify locally first**

Run: `unshare -rn python3 kit/scripts/run-evals.py --all skills | tail -1`
Expected: `TOTAL 61 skill(s): … 0 failed …` (count grows as skills are added). If any row fails only under `unshare`, that row reaches the network and is a real SDS-S-092 violation: fix the skill (inject a fixture), never the job.

- [ ] **Step 3: Commit, push, watch CI** (`ci: hermetic eval job under unshare -n`).

### Task 3: Shape compatibility job (SDS-K-023 as CI)

**Files:**
- Create: `kit/scripts/check-shapes.sh`
- Modify: `.github/workflows/conformance.yml` (step in the `conformance` job after "Validate the registry")

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Checks every kit/shapes/<name>.schema.json is backward compatible with
# its copy at the last tag, using json-schema-compat-check's own script
# (SDS-K-023). Exit 1 on any breaking change.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
tag=$(git describe --tags --abbrev=0)
status=0
for f in kit/shapes/*.schema.json; do
  old=$(mktemp); git show "$tag:$f" > "$old" 2>/dev/null || { echo "new shape $f (no copy at $tag)"; continue; }
  out=$(cd skills/json-schema-compat-check && python3 scripts/compare_schemas.py "$old" "../../$f")
  errors=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(1 for r in d['runs'][0]['results'] if r['level']=='error'))")
  echo "$f vs $tag: $errors breaking change(s)"
  [ "$errors" -eq 0 ] || status=1
  rm -f "$old"
done
exit $status
```
Confirm the compare script's real name and argument order with `ls skills/json-schema-compat-check/scripts` and its docstring; adjust the one line that calls it. Note the `../../$f` path: that script runs from its skill dir and the family forbids `../` only inside skill files, not in a kit script.

- [ ] **Step 2: Run** `bash kit/scripts/check-shapes.sh` → every shape `0 breaking change(s)`.
- [ ] **Step 3: Add the CI step** `- name: Shapes compatible with the last tag` / `run: bash kit/scripts/check-shapes.sh` (checkout needs `fetch-depth: 0` for tags: add `with: {fetch-depth: 0}` to the checkout step).
- [ ] **Step 4: Commit, push, watch CI** (`ci: shape compatibility against the last tag (SDS-K-023)`).

### Task 4: Skill scaffolder

**Files:**
- Create: `kit/scripts/new-skill.py`
- Modify: `kit/HOW-TO-BUILD-A-SKILL.md` Step 0 (use the scaffolder)

**Interfaces:**
- Produces: `python3 kit/scripts/new-skill.py <name> --kind query|command --rung 1..6 --shape-out <shape|freeform> [--shape-in <shape|freeform>] [--script <snake_name>.py]` → creates `skills/<name>/SKILL.md` from the matching `kit/templates/SKILL.md.<kind>.template`, `scripts/<script>` stub with docstring and the `ERROR: … (<code>)` convention, `evals/<name>.eval.yaml` from `kit/evals/TEMPLATE.eval.yaml` with the required row names pre-filled as N/A-or-todo, `evals/fixtures/.gitkeep`, and appends a `status: planned` registry entry. Exit 2 if the directory exists.

- [ ] **Step 1: Write the script** (stdlib only; read the two templates and substitute `skill-name-here` and `[FILL …]` markers with the CLI values; leave every other `[FILL` marker in place — the linter's residue rule SDS-S-035 is the reminder to finish).
- [ ] **Step 2: Test by scaffolding a throwaway** `python3 kit/scripts/new-skill.py zz-scaffold-test --kind query --rung 1 --shape-out finding-list`, then `python3 kit/scripts/lint-skill.py skills/zz-scaffold-test --no-review` → expect ERRORs only for `[FILL` residue and empty sections, nothing structural. Remove the throwaway and its registry entry.
- [ ] **Step 3: Commit, push** (`feat(kit): new-skill.py scaffolder`).

### Task 5: Runner `--json` and SARIF upload of lint results (dogfood code scanning)

**Files:**
- Modify: `kit/scripts/run-evals.py` (add `--json`: one `finding-list`, driver `run-evals`, one result per failed row, `ruleId` = `eval/<row-name>`, location = the eval file path with the row's line)
- Modify: `.github/workflows/conformance.yml` (upload the linter's `--json` as SARIF)

- [ ] **Step 1: Add `--json` to the runner** mirroring the linter's reporter; self-validate against `kit/shapes/finding-list.schema.json` before printing.
- [ ] **Step 2: Add the upload step** (permissions `security-events: write` on the job):
```yaml
      - name: Lint as SARIF
        if: always()
        run: python kit/scripts/lint-skill.py --all skills --json --no-review > lint.sarif || true
      - name: Upload to code scanning
        if: always()
        uses: github/codeql-action/upload-sarif@<pinned-sha> # v3
        with:
          sarif_file: lint.sarif
```
Resolve `<pinned-sha>` with `gh api repos/github/codeql-action/git/ref/tags/v3 --jq .object.sha` (dereference if it is an annotated tag). The family's `finding-list` is SARIF-compatible by design (SDS-C-031); if the upload rejects it, the missing fields are `$schema` and `version: "2.1.0"` — add them in the linter's `--json` reporter as a `--sarif` variant rather than changing the shape.
- [ ] **Step 3: Push, watch CI, open the Security → Code scanning tab** and confirm alerts appear (they will be the family's INFO rows, e.g. `SDS-S-039`).
- [ ] **Step 4: Commit** (`feat(kit): run-evals --json; ci: upload lint findings to code scanning`).

---

## W1 — Close the shape graph

### Task 6: `findings-to-issues` (rung 5, `finding-list` → `status-report`) — reference implementation

The first Command consumer of `finding-list`. Written out in full; Tasks 7–15 reuse its mechanics.

**Files:**
- Create: `skills/findings-to-issues/SKILL.md`
- Create: `skills/findings-to-issues/scripts/plan_issues.py`
- Create: `skills/findings-to-issues/scripts/checkpoint.py` (byte-identical copy of `skills/issue-triage/scripts/checkpoint.py`)
- Create: `skills/findings-to-issues/evals/findings-to-issues.eval.yaml`
- Create: `skills/findings-to-issues/evals/fixtures/{frozen-dependency-audit-findings.json, frozen-gh-issues-open.json, issues-none.json, findings-malformed.json, build-state-scratch.sh, .gitignore}`
- Modify: `kit/registry/marketplace.json` (append entry), `README.md`, `.claude-plugin/*` (generated)

**Interfaces:**
- Consumes: any `finding-list`; `gh issue list --state open --limit 200 --json number,title,body,labels` (live) or `--issues-json-file` (frozen, same array shape).
- Produces: a `plan-doc` (one `create` step per (tool, ruleId) group not already open; a `nothing to do` phase when all are open); Act creates issues by direct `gh issue create -R <owner/repo> --title … --body … --label …`; Persist returns a `status-report`.
- Fingerprint: every created issue body ends with `<!-- sds-finding-group: <tool>/<ruleId> -->`; check-before-act searches that marker in open issue bodies. That marker is the dedupe key across runs, so `idempotent: "true"` holds.

- [ ] **Step 1: Freeze the producer fixture**

```bash
mkdir -p skills/findings-to-issues/evals/fixtures skills/findings-to-issues/scripts
cp skills/findings-digest/evals/fixtures/frozen-dependency-audit-findings.json skills/findings-to-issues/evals/fixtures/
cp skills/issue-triage/scripts/checkpoint.py skills/findings-to-issues/scripts/
cp skills/issue-triage/evals/fixtures/build-state-scratch.sh skills/findings-to-issues/evals/fixtures/
cp skills/issue-triage/evals/fixtures/.gitignore skills/findings-to-issues/evals/fixtures/
```
Then write `frozen-gh-issues-open.json` (array in `gh issue list --json number,title,body,labels` shape) with two issues: #40 whose body ends `<!-- sds-finding-group: dependency-audit/GHSA-p6mc-m468-83gw -->` (already filed) and #41 unrelated; and `issues-none.json` = `[]`; and `findings-malformed.json` = `{"runs": "nope"}`.

- [ ] **Step 2: Write the planner**

```python
#!/usr/bin/env python3
"""Plan GitHub issues for the findings an audit produced, as a plan-doc
(kit/shapes/plan-doc.schema.json).

Usage:
    plan_issues.py <repo-path> <finding-list.json>... [--min-level warning|error] [--label L] [--limit N]
    plan_issues.py <repo-path> <finding-list.json>... --issues-json-file <path> [--min-level …] [--label L]

This is the deterministic part of findings-to-issues' Decide stage
(SDS-C-060). Findings at or above --min-level (default warning) are
grouped by (tool, ruleId); each group becomes one proposed issue whose
body lists every location. A group already open — an open issue whose
body carries the marker `<!-- sds-finding-group: <tool>/<ruleId> -->` —
is skipped, which is what makes a re-run a no-op (SDS-C-004). Live
mode reads (rung 3):
    gh issue list --state open --limit 200 --json number,title,body,labels
`--issues-json-file` (SDS-S-065) replaces it with a file in the same
array shape. The creations are direct, gated tool calls outside this
script (SDS-S-051); it never writes to GitHub.

Prints one plan-doc; nothing to file yields a single 'nothing to do'
phase (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that
is not a directory (repo-invalid), an input that is not a finding-list
(findings-invalid), an issues file that is not a JSON array
(issues-unparseable), a bad level (level-invalid), or a failed live
call (gh-unreachable).
"""
import json, re, subprocess, sys
from collections import OrderedDict
from pathlib import Path

MARK = "<!-- sds-finding-group: {} -->"
LEVELS = {"note": 0, "info": 0, "warning": 1, "error": 2}


def load_findings(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        runs = doc["runs"]
        assert isinstance(runs, list)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: {path} is not a finding-list (findings-invalid): {e}")
    for run in runs:
        tool = run.get("tool", {}).get("driver", {}).get("name", "unknown")
        for r in run.get("results", []):
            loc = (r.get("locations") or [{}])[0].get("physicalLocation", {})
            uri = loc.get("artifactLocation", {}).get("uri", "(no location)")
            line = loc.get("region", {}).get("startLine")
            yield tool, r["ruleId"], str(r.get("level", "warning")).lower(), r.get("message", {}).get("text", ""), uri, line


def load_issues(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert isinstance(data, list)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: issues file {path} is not a JSON array (issues-unparseable): {e}")
    return data


def live_issues(repo):
    r = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", "200", "--json", "number,title,body,labels"],
                       cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: gh issue list failed (gh-unreachable): {r.stderr.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: gh returned unparseable JSON (issues-unparseable): {e}")


def main():
    args = sys.argv[1:]
    opts = {"--issues-json-file": None, "--min-level": "warning", "--label": "audit", "--limit": "20"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) < 2:
        sys.exit("ERROR: usage: plan_issues.py <repo-path> <finding-list.json>... [--issues-json-file F] [--min-level warning|error] [--label L] [--limit N]")
    repo, inputs = Path(args[0]), args[1:]
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")
    if opts["--min-level"] not in ("warning", "error"):
        sys.exit(f"ERROR: --min-level must be warning or error (level-invalid): {opts['--min-level']!r}")
    floor = LEVELS[opts["--min-level"]]
    limit = int(opts["--limit"])
    groups = OrderedDict()
    for path in inputs:
        for tool, rule, level, text, uri, line in load_findings(path):
            if LEVELS.get(level, 0) < floor:
                continue
            g = groups.setdefault((tool, rule), {"level": level, "locations": [], "text": text})
            g["locations"].append(f"{uri}:{line}" if line else uri)
            if LEVELS[level] > LEVELS[g["level"]]:
                g["level"] = level
    issues = load_issues(opts["--issues-json-file"]) if opts["--issues-json-file"] else live_issues(repo)
    open_marks = {m for i in issues for m in re.findall(r"<!-- sds-finding-group: (\S+) -->", i.get("body") or "")}
    steps, skipped = [], []
    for (tool, rule), g in list(groups.items())[:limit]:
        key = f"{tool}/{rule}"
        if key in open_marks:
            skipped.append(key)
            continue
        title = f"[{tool}] {rule}: {len(g['locations'])} location(s)"
        body = (f"{g['text']}\n\nLocations:\n" + "\n".join(f"- `{l}`" for l in sorted(set(g["locations"]))[:50])
                + f"\n\nSeverity: {g['level']}. Filed by findings-to-issues.\n{MARK.format(key)}")
        steps.append({"description": f"create issue {title!r} with label {opts['--label']}; body:\n{body}",
                      "riskIfFails": "low",
                      "rollback": "gh issue close <number> --reason 'not planned' — a rung-6 close, so a human runs it",
                      "checkpointAfter": True})
    goal = f"File {len(steps)} issue(s) for {len(groups)} finding group(s) at or above {opts['--min-level']} ({len(skipped)} already open, skipped)"
    phases = [{"name": "create", "steps": steps}] if steps else [{"name": "nothing to do", "steps": [
        {"description": f"every finding group is already open ({len(skipped)}) or nothing reached the floor", "riskIfFails": "low",
         "rollback": "none needed — nothing is written", "checkpointAfter": False}]}]
    print(json.dumps({"goal": goal, "phases": phases}, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the rows by hand from the skill dir and record the true numbers**

```bash
cd skills/findings-to-issues
python3 scripts/plan_issues.py . evals/fixtures/frozen-dependency-audit-findings.json --issues-json-file evals/fixtures/frozen-gh-issues-open.json
```
Expected: dependency-audit's six findings group into six rules; three errors and three warnings all reach the `warning` floor; the GHSA-p6mc group is skipped (open in #40) → `File 5 issue(s) for 6 finding group(s) … (1 already open, skipped)`. With `--min-level error` → 2 filed (3 errors, one skipped). With `issues-none.json` → 6 filed. Record what the script actually prints; the eval assertions state those numbers.

- [ ] **Step 4: Write SKILL.md** — copy the structure of `skills/issue-triage/SKILL.md` verbatim and change the substance: description (trigger: "after an audit, when findings should become tracked work, when asked to file the findings"), `compatibility` (gh with issue read and create), `metadata` (`effect-tier: shared-write`, `idempotent: "true"`, `shape-out: status-report`, `shape-in: finding-list`), `allowed-tools: Bash(python3 scripts/plan_issues.py:*) Bash(python3 scripts/checkpoint.py:*) Bash(gh issue list:*) Bash(gh issue view:*) Read Write` with the HTML comment stating that `gh issue create` is deliberately absent and issued as a direct gated call (SDS-S-023, SDS-S-051). Decide writes the plan to `.skills-state/findings-to-issues/<date>.json`; stop branch `**If the plan's only phase is "nothing to do": stop here.**`; Confirm quotes `kit/shared/gates/medium.md` with What/Why/Reversible (reversible only by a rung-6 close); Act: pending checkpoint → check-before-act (`gh issue list --search "sds-finding-group: <key>" --state open`) → `gh issue create -R <owner/repo> --title … --body … --label …` → completed; `**Compensating action**` and `**Checkpoint**` labels present; Communicate `N/A — the issue is the communication.`; Persist = status-report. `@throws`: `repo-invalid, findings-invalid, issues-unparseable, level-invalid, gh-unreachable, filing-declined, label-missing`.

- [ ] **Step 5: Write the eval file** with rows: `happy-path-planted-findings` (plan-doc; numbers from Step 3), `boundary-min-level-error`, `boundary-empty-all-open` (issues file where every group's marker is open → `nothing to do`; build that file `frozen-gh-issues-all-open.json` from the six keys), `boundary-empty-no-findings` (`skills/findings-digest/evals/fixtures/findings-empty.json` copied in as `findings-empty.json` → nothing to do), `boundary-malformed-findings` (`findings-invalid`), `boundary-malformed-issues` (`issues-unparseable`, a file `{"x":1}`), `boundary-invalid-level`, `boundary-invalid-repo-path`, `happy-path-checkpoint-round-trip` (copy issue-triage's row with skill name and step `dependency-audit-GHSA-35jh-create`), `mutation-fixture` N/A, `fixed-point` N/A, `contract-with-upstream-producer` (the frozen finding-list validates against `finding-list` and the plan against `plan-doc`), and the smoke section after `---` naming the live `gh issue list` read.

- [ ] **Step 6: Run the standing pre-commit sequence** (Global Constraints). Fix every WARN by rewording, every FAIL in the script — never in the expectation.

- [ ] **Step 7: Commit and push** `feat(skills): add findings-to-issues (rung 5; first Command consumer of finding-list)`; watch CI.

### Task 7: `findings-to-code-scanning` (rung 5, `finding-list` → `status-report`)

Uploads a family `finding-list` to GitHub Code Scanning as SARIF — the standards-first destination for findings (SDS-C-031 chose SARIF for exactly this).

**Files:** `skills/findings-to-code-scanning/{SKILL.md, scripts/prepare_sarif.py, scripts/checkpoint.py, evals/…}`

**Interfaces:**
- `prepare_sarif.py <repo-path> <finding-list.json>... [--ref refs/heads/main] [--sha <40hex>]` → prints the upload payload `{"commit_sha", "ref", "sarif": "<base64 gzip>", "tool_name"}` after adding `$schema` and `version: "2.1.0"` to the merged document and validating it against `kit/shapes/finding-list.schema.json`; `--sha`/`--ref` default to `git rev-parse HEAD` / `git symbolic-ref HEAD` in the repository. Throws `repo-invalid, findings-invalid, ref-invalid, sha-invalid`.
- Act: `gh api -X POST repos/<owner>/<repo>/code-scanning/sarifs --input payload.json` — a direct gated call; check-before-act: `gh api repos/<o>/<r>/code-scanning/sarifs/<id>` after upload for the pending checkpoint's `postState`; compensating action: none exists (an upload cannot be deleted) — state it and sequence the single step last (plan-doc rule).
- Fixtures: the three frozen producer files from `findings-digest`; a `frozen-git-head.txt`-free design (the script takes `--sha`/`--ref` explicitly in every eval row so no git repo fixture is needed).
- Rows: `happy-path-three-audits` (payload has `commit_sha` = given, `sarif` decodes to 20 results, `tool_name` `dev-skills-suite`), `boundary-empty-findings` (payload with 0 results; still a valid upload), `boundary-malformed-findings`, `boundary-invalid-sha` (`sha-invalid`, 39 hex chars), `boundary-invalid-ref`, `happy-path-checkpoint-round-trip`, N/A mutation and fixed-point, `contract-with-upstream-producers` (decode the payload, validate against the shape).
- SKILL.md: rung 5 → medium gate; Communicate `N/A — the alerts appear in the repository's Security tab.`; `@throws` adds `upload-declined`, `gh-unreachable`.
- Live run belongs to Task 19 (upload the family's own lint SARIF once by hand, then let Task 5's CI step do it).

- [ ] Steps: scaffold with `new-skill.py` (Task 4) → write script → run rows → SKILL.md → eval file → pre-commit sequence → commit `feat(skills): add findings-to-code-scanning` → push, watch CI.

### Task 8: `report-poster` (rung 5, `status-report` → `status-report`)

Posts any family `status-report` where people read it: as a comment on a pull request or issue, or as a discussion-free release-notes body is out of scope (that is `release-publisher`).

**Interfaces:**
- `render_report_comment.py <status-report.json> --target pr:<n>|issue:<n> [--marker <id>]` → prints `{"target": …, "marker": "<!-- sds-report: <id> -->", "body": "<markdown>"}`; markdown = `## <summary>` then each section as `### heading` + body, `generatedFrom` in a footer, and the marker last. `--marker` defaults to a hash of `generatedFrom`. Throws `report-invalid` (not a status-report), `target-invalid`.
- Check-before-act: `gh pr view <n> --json comments` / `gh issue view <n> --json comments`; a comment already carrying the marker is a skip (idempotent). Act: `gh pr comment <n> -R <o/r> --body-file …` / `gh issue comment`. Compensating action: rung-6 API delete named in the plan. Fixed-point row: **required** (`status-report` → `status-report`): the script's output is not the same document — so `shape-out` here must be the *posted* report? No: keep `shape-out: status-report` for the Persist report ("posted comment N on PR M"), and the fixed-point row asserts `render_report_comment.py` on its own Persist report produces a valid comment payload again (idempotence of rendering), as `release-notes-writer` does. Frozen inputs: `frozen-findings-digest-report.json` (freeze from `findings-digest`'s happy-path row), `frozen-changelog-writer-report.json` (copy from `release-notes-writer`).
- Rows: happy-path (digest report → markdown with six `###` headings and the marker), boundary-empty (a status-report with `sections: []` → summary-only body), boundary-malformed (`report-invalid`), boundary-invalid-target, fixed-point (success), checkpoint round trip, contract-with-upstream-producers (both frozen reports validate; both render).
- Steps as Task 7. Commit `feat(skills): add report-poster`.

After Task 8 the generated README Compositions table shows every registered shape with at least one consumer. Verify: `grep -A6 '^| Shape' README.md` has no `—` cell.

---

## W2 — Fourth bench (thin clusters and a security seam)

Each task: rung 1 unless stated, `shape-in: freeform`, `shape-out: finding-list` unless stated, `tier: situational`, one script, planted fixtures, the required rows, glossary-safe wording. The rule tables below are normative; the script skeleton (option parsing, `finding()`, sort by level then rule then uri, `tool.properties`, `ERROR: … (<code>)`) is the one in `skills/i18n-string-inventory/scripts/inventory_i18n.py`.

### Task 9: `import-cycle-finder` (Architecture & Decisions)

- CLI: `find_import_cycles.py <repo> [--lang python|js|auto] [--exclude dir,dir] [--max-cycles N]`.
- Gather: Python via `ast` (`import x`, `from x import y`, relative imports resolved against package `__init__.py`); JS/TS via regex on `import … from '…'` / `require('…')` resolving relative paths with extensions `.js .ts .tsx .jsx .mjs .cjs` and `index.*`. Build a module graph; Tarjan SCCs; every SCC with size > 1 (or a self-import) is a cycle.
- Rules: `arch/import-cycle` (error when the cycle spans ≥ 3 modules, warning for 2), `arch/self-import` (warning), `arch/unresolved-import` (info, relative import that resolves to no file). `properties`: `modules` (the cycle in order), `size`, `edges`.
- `tool.properties`: modules, edges, cycles, largestCycle.
- Throws: `repo-invalid, source-unparseable, lang-invalid, exclude-invalid`.
- Fixtures: `planted-py/` with `a.py → b.py → c.py → a.py` (3-cycle), `d.py ↔ e.py` (2-cycle), `f.py` importing `.missing`; `planted-js/` with a 2-cycle through `index.ts`; `clean-py/`; `broken-py/` with a syntax error.
- Rows: happy-path-python (one error cycle a→b→c, one warning d↔e, one info unresolved), happy-path-javascript, boundary-empty-clean, boundary-max-cycles (`--max-cycles 1` → one result + `tool.properties.truncated true`), boundary-malformed-source, boundary-invalid-lang, boundary-invalid-path, mutation-fixture (the 3-cycle is found with `modules [a, b, c]`), fixed-point N/A, contract-with-downstream-consumer.

### Task 10: `layer-boundary-check` (Architecture & Decisions)

- CLI: `check_layers.py <repo> --layers <layers.json> [--exclude …]`; `assets/layers.example.json`: `{"layers": ["domain", "application", "adapters", "infrastructure"], "paths": {"domain": ["src/domain"], …}, "allowed": {"application": ["domain"], "adapters": ["application", "domain"], "infrastructure": ["adapters", "application", "domain"]}}`. Declared input in `@requires` (SDS-S-080 assets read by Gather are declared).
- Gather: same import resolution as Task 9 (share nothing across skills — copy the resolver; skills do not import each other).
- Rules: `arch/layer-violation` (error: import from a layer not in `allowed[from]`), `arch/unassigned-module` (info: file in no layer path), `arch/inward-only-ok` none. `properties`: fromLayer, toLayer, importer, imported.
- Throws: `repo-invalid, layers-invalid` (missing keys, unknown layer named in `allowed`), `source-unparseable`.
- Fixtures: planted repo where `src/domain/order.py` imports `src/infrastructure/db.py` (violation) and `src/adapters/api.py` imports `src/application/service.py` (allowed); a `layers-bad.json` naming an unknown layer.
- Rows: happy-path (one error, one info for `src/scripts/tool.py`), boundary-empty-clean (layers.json with no violations), boundary-malformed-layers, boundary-invalid-path, mutation-fixture, fixed-point N/A, contract-with-downstream-consumer.

### Task 11: `workspace-consistency-check` (Monorepo Coordination)

- CLI: `check_workspaces.py <repo>`; detects npm/pnpm/yarn workspaces (`package.json#workspaces`, `pnpm-workspace.yaml`), Cargo workspaces, Go `go.work`, Python `uv`/`hatch` workspaces (`pyproject.toml [tool.uv.workspace]`).
- Rules: `mono/member-missing` (error: a declared workspace member path has no manifest), `mono/orphan-package` (warning: a manifest under `packages/*`/`apps/*` not declared), `mono/duplicate-name` (error: two members share a package name), `mono/internal-version-mismatch` (warning: a member depends on a sibling at a version the sibling is not — this is `cross-package-version-drift`'s territory for *external* deps; here only sibling ranges), `mono/mixed-lockfiles` (warning: more than one lockfile kind at the root), `mono/nested-lockfile` (info: a member has its own lockfile).
- Throws: `repo-invalid, manifest-unparseable, workspace-unrecognized` (no workspace definition found → **not** a failure: empty result with `tool.properties.kind null`; the throw is for a definition that exists but does not parse).
- Fixtures: `planted-npm/` (a missing member, an orphan, a duplicate name, two lockfiles), `planted-cargo/`, `clean-pnpm/`, `broken-npm/` (bad JSON).
- Rows as the pattern; mutation-fixture on `mono/member-missing`.

### Task 12: `flag-retirement-plan-writer` (Feature Flags; `shape-in: finding-list`, `shape-out: plan-doc`)

Consumes `feature-flag-inventory`'s finding-list (freeze `skills/feature-flag-inventory`'s happy-path output as `frozen-feature-flag-inventory-findings.json`) and writes the retirement plan.

- CLI: `plan_flag_retirement.py <finding-list.json> [--as-of ISO] [--older-than-days N]`.
- Rule table: for each flag finding with `properties.state` in `{fully-on, fully-off, stale}` (use the real property names from `feature-flag-inventory`'s script — read it): phase "remove dead branches" (per flag: description names the flag, the files, and which branch survives; `rollback: git revert <commit>`; risk low), phase "delete flag definition" (risk medium; rollback re-add), phase "clean config/provider" last. Flags with `state: active` produce no step. Empty input → `nothing to do`.
- Throws: `findings-invalid, as-of-invalid`.
- Rows: happy-path (N steps from the frozen inventory: state the real count after running), boundary-empty (a finding-list with only active flags → nothing to do), boundary-malformed, boundary-missing-as-of (if `--as-of` is required with the frozen file — make it required), mutation-fixture N/A, fixed-point N/A (finding-list ≠ plan-doc), contract-with-upstream-producer (the frozen inventory validates as `finding-list`; the plan validates as `plan-doc`) and contract-with-downstream-consumer (`issue-triage` and `project-board-sync` consume `plan-doc`; validate only).

### Task 13: `eval-dataset-audit` (AI Feature Engineering)

- CLI: `audit_eval_dataset.py <file.jsonl|.csv|.json> [--input-field input] [--expected-field expected] [--near-duplicate-threshold 0.9]`.
- Rules: `evals/duplicate-row` (warning: identical input), `evals/near-duplicate` (info: Jaccard over word 3-grams ≥ threshold), `evals/empty-expected` (error), `evals/label-imbalance` (warning: when `expected` is categorical with ≤ 20 classes and the largest class > 70 %), `evals/leak-suspect` (warning: `expected` text appears verbatim inside `input`), `evals/missing-field` (error per row lacking a field; stop after 20).
- `tool.properties`: rows, fields, classes, largestClassShare.
- Throws: `dataset-unreadable, dataset-invalid` (not JSONL/CSV/JSON array), `field-invalid`.
- Fixtures: `planted.jsonl` (2 duplicates, 1 near-duplicate, 1 empty expected, 1 leak, 8 of 10 rows one class), `clean.jsonl`, `planted.csv`, `broken.jsonl`.
- Rows as the pattern; mutation-fixture on `evals/leak-suspect`.

### Task 14: `dockerfile-review` (Local Dev & Environment / security seam)

- CLI: `review_dockerfile.py <repo|Dockerfile> [--allow-latest]`; finds every `Dockerfile*` and `*.dockerfile`.
- Rules (each cites the Dockerfile best-practices doc in `references/dockerfile-rules.md`, linked from SKILL.md with a condition sentence): `docker/latest-tag` (warning), `docker/unpinned-base` (info: no digest), `docker/root-user` (warning: no `USER` after the last `FROM`), `docker/apt-no-cleanup` (info), `docker/secret-in-arg-env` (error: `ARG|ENV` name matches `(?i)(secret|token|password|api_key)`), `docker/add-instead-of-copy` (info), `docker/no-healthcheck` (info, only for images that `EXPOSE`), `docker/multi-stage-missing` (info: `RUN … build` and no second `FROM`), `docker/copy-dot-before-deps` (warning: `COPY . .` before the dependency install layer — cache bust).
- Throws: `repo-invalid, dockerfile-missing` (a path given explicitly does not exist), `dockerfile-unparseable` (an instruction line without a keyword).
- Fixtures: `planted/Dockerfile` (every rule once), `clean/Dockerfile`, `broken/Dockerfile`.
- Rows as the pattern; mutation-fixture on `docker/secret-in-arg-env`. Note in "When not to use": `docker-compose-review` reads compose files; this reads the image build.

### Task 15: `license-header-check` (Dependencies & Supply Chain)

- CLI: `check_license_headers.py <repo> --header <header.txt> [--ext py,js,ts,go,rs] [--exclude …]`; `assets/header.example.txt` (Apache-2.0 short header with `{year}` and `{owner}` placeholders — a declared input).
- Rules: `license/header-missing` (warning), `license/header-stale-year` (info: header present, year older than the file's last git year — **only** with `--git-years-json-file`, a frozen `{path: year}`; without it the rule is off), `license/header-mismatch` (warning: a header present but text differs after whitespace collapse — e.g. a different license), `license/spdx-missing` (info: no `SPDX-License-Identifier:` line).
- Throws: `repo-invalid, header-unreadable, years-unparseable`.
- Fixtures: planted tree with one file per rule; `frozen-git-years.json`; clean tree.
- Rows as the pattern; mutation-fixture on `license/header-mismatch`.

After Tasks 9–15: update the catalog table in `docs/superpowers/specs/2026-09-05-dev-skills-suite-design.md` with a "Fourth bench (2026-09-xx, built)" block listing these seven under their clusters, and commit `docs(catalog): fourth bench`.

---

## W3 — Utilization

### Task 16: `kit/scripts/sweep.py` — run every applicable Query Skill on one repository

**Files:** Create `kit/scripts/sweep.py`; Create `kit/registry/sweep.json`; Modify `kit/HOW-TO-BUILD-A-SKILL.md` (Step 12: register the sweep line for a new Query Skill whose Gather has repository-only defaults).

**Interfaces:**
- `kit/registry/sweep.json`: `{"<skill>": {"command": "python3 scripts/<file>.py {repo}", "needs": []}}` — only skills whose script runs with the repository path and defaults (no other required input). Initial entries (verify each script's usage line before adding): `dependency-audit` (needs network → `"needs": ["osv"]`, excluded by default), `ci-pipeline-audit`, `codeowners-check`, `commit-message-lint` (`needs: ["git"]`), `dead-code-finder`, `code-comment-audit`, `naming-consistency-check`, `large-file-splitter-advisor`, `tech-debt-inventory`, `test-coverage-gap-finder` (needs a coverage file → excluded), `test-smell-review`, `env-var-inventory`, `devcontainer-audit`, `docker-compose-review`, `feature-flag-inventory`, `retry-timeout-audit`, `prompt-template-audit`, `test-data-pii-scan`, `import-cycle-finder`, `workspace-consistency-check`, `dockerfile-review`, `repository-orientation` (freeform out → excluded from the digest, still run), `branch-hygiene` (`needs: ["git"]`).
- `sweep.py <repo> [--only a,b] [--skip a,b] [--out <dir>] [--needs git,osv]` runs each registered script from its skill directory with `{repo}` absolute, writes `<out>/<skill>.json`, then runs `skills/findings-digest/scripts/digest_findings.py <out>/*.json` (only finding-list outputs) and prints the digest. Exit 0 even when audits find things; exit 1 only when a script crashed (its stderr is shown). A script's non-zero exit with `ERROR:` is recorded as `<out>/<skill>.error.txt` and reported.

- [ ] Steps: write registry → write script → `python3 kit/scripts/sweep.py . --out /tmp/sweep-self` on the family repo → confirm the digest prints → commit `feat(kit): sweep.py runs every applicable Query Skill on a repository and digests the result`.

### Task 17: Dogfood sweep on the family repository — and fix what it finds

- [ ] Run `python3 kit/scripts/sweep.py /home/edox1/Public/claude --out ~/sweep-family` and read the digest.
- [ ] For every **error**: fix the family repository (not the skill) unless the finding is wrong, in which case fix the skill's rule and add a row proving the false positive is gone. Expected candidates: `test-data-pii-scan` on `skills/test-data-pii-scan/evals/fixtures` (its own planted card — add an `ignoreValues`-style skip for `evals/fixtures/planted-*` paths? No: that hides the planted proof. Instead the sweep passes `--exclude evals` for that skill; record it in `sweep.json` as `"args": "--exclude evals"`), `retry-timeout-audit` on `subprocess.run` calls without timeout in kit scripts (real: add `timeout=` to `gh` calls in `ci-status-gate`, `github-actions-cost-audit`, `findings-to-issues`, `run-evals.py`), `dead-code-finder` on any unused helper.
- [ ] Record the digest in `docs/live-runs/2026-09-xx-dogfood-sweep.md` (before/after totals) and commit each fix separately with `fix(skills): …` or `fix(kit): …`.

### Task 18: Dogfood sweep on two external repositories

- [ ] Clone under `~` (the snap `gh` constraint): `git clone --depth 50 https://github.com/actions/checkout ~/sweep-checkout` and one Python repository with tests and workflows, e.g. `https://github.com/psf/requests ~/sweep-requests`.
- [ ] Run the sweep on each; read the digests; for every finding that is a **false positive**, fix the rule and add a `boundary-*` row reproducing the case (a regression row from a real repository is worth more than a planted one). Do not open issues on those repositories.
- [ ] Append both digests' totals and the list of rule fixes to the dogfood doc; remove the clones; commit.

### Task 19: Live runs of every Command Skill not yet exercised

| Skill | Target | Gate | What proves it |
|---|---|---|---|
| `findings-to-issues` | testbed | medium | file the testbed's own `ci-pipeline-audit` findings (there are none → run `test-data-pii-scan` on a planted file pushed to the testbed first); re-run → `nothing to do` |
| `findings-to-code-scanning` | family repo | medium | upload `lint-skill.py --all --json` once by hand; alert count matches INFO rows |
| `report-poster` | testbed PR | medium | post the digest on a PR opened for the planted file; re-run → skip |
| `project-board-sync` | testbed | medium | **blocked on scope**: the user runs `! gh auth refresh -s project` in the session (interactive); then a board with two columns and issues #2–#5 |
| plugin install | user's Claude Code | user decision | `/plugin marketplace add soilmass/dev-skills-suite` + `/plugin install dev-skills-suite@dev-skills-suite`; invoke `/dev-skills-suite:repository-orientation` on the testbed; the `${CLAUDE_SKILL_DIR}` working-directory assumption is the thing to check |

- [ ] For each: run Gather → Analyze → Decide, show the gate text, **stop and ask** (the user answers the gate), Act with pending/completed checkpoints, Persist the status-report to `.skills-state/<skill>/`, and append a table row to `docs/live-runs/2026-09-xx-command-skills.md` in the format of `docs/live-runs/2026-09-06-testbed-bench.md`. Every text defect found in a SKILL.md during a live run is fixed in the same commit as the live-run note (`fix(skills): …`).

### Task 20: The family releases itself through its own skills

- [ ] `changelog-writer` on the family repository from `v1.2.0-draft..HEAD` → status-report (offline, git only).
- [ ] `release-notes-writer` on that report with `--product dev-skills-suite --version 1.3.0-draft`.
- [ ] `ci-status-gate` on `HEAD` → must be `pass` (the conformance run).
- [ ] `release-publisher` with the notes and the decision → high gate (`kit/shared/gates/high.md`) → **ask the user** → `gh release create v1.3.0-draft -R soilmass/dev-skills-suite --notes-file …` with pending/completed checkpoints. This is Task 26's tag; do not tag by hand.
- [ ] Record in `docs/live-runs/…`; commit `chore(release): v1.3.0-draft published by release-publisher`.

### Task 21: Promotion review (SDS-F-053)

- [ ] Write `docs/promotion-criteria.md`: a skill is promoted `situational → pillar` when it has ≥ 3 recorded live or dogfood runs with zero false positives after fixes, a pinned contract on both sides where a shape allows it, and 0 lint infos. Record the numeric count per skill from `docs/live-runs/*.md` in a table.
- [ ] Promote the skills that meet it (candidates after W3: `ci-status-gate`, `findings-digest`, `ci-pipeline-audit`, `commit-message-lint`) by changing `tier` in SKILL.md and the registry, one commit each (`chore(promotion): <skill> → pillar (criteria met: …)`).

---

## W4 — Docs, spec revision 05, tag

### Task 22: `docs/CHOOSING-A-SKILL.md`, generated

**Files:** Create `kit/registry/clusters.json` (`{"<cluster>": ["<skill>", …]}` — the catalog's tables transcribed once, including the benches and cross-cutting); Modify `kit/scripts/render_index.py` (a second output: `--choosing docs/CHOOSING-A-SKILL.md`, and `--check` covers it); Modify `.github/workflows/conformance.yml` (`render_index.py --check` already runs; nothing to add).

- The page: one section per cluster; per skill a one-line "Use when …" cut from the description's trigger sentence (the text after "Use when", "Use before", "Use after", or "Use " — the same heuristic SDS-S-011 recognises); Query/Command and rung in a column; a final "By situation" table mapping twelve situations ("before a release", "after an outage", "a PR is open", "the audits ran", "open-sourcing", "a new locale", "the bill surprised someone", "onboarding", "a migration", "a dependency upgrade", "a design is proposed", "the tracker grew") to the skills in order of use, written by hand once in `kit/registry/situations.json` so the renderer stays a renderer.
- [ ] Steps: write the two JSON files → extend the renderer → generate → link the page from the README header (in the `HEADER` template) → commit `docs: CHOOSING-A-SKILL.md generated from the registry and clusters`.

### Task 23: SDS 1.0-draft revision 05

New and changed rules from W0–W2, each with body text, Appendix B row, linter rule-table line, and a linter negative test where MACHINE:
- SDS-K-001 (MACHINE, changed): kit layout adds `scripts/new-skill.py`, `scripts/sweep.py`, `scripts/check-shapes.sh`, `tests/`.
- SDS-K-073 (MUST, MACHINE): `kit/tests/` holds at least one negative case per MACHINE rule category (directory, frontmatter, sections, contracts, paths, scripts, evals, registry) — the linter checks the file exists and names ≥ 8 rule IDs.
- SDS-F-055 (SHOULD, ADVISORY): the CI gate runs the eval table with the network removed.
- SDS-F-056 (SHOULD, REVIEW): a family keeps a sweep registry naming every Query Skill runnable with repository-only inputs.
- SDS-S-057 (MUST, REVIEW): a Command Skill that writes to a shared system embeds an idempotency marker in what it writes (`<!-- sds-… -->`) and check-before-acts on it — the rule Tasks 6–8 all follow.
- Changelog entry; `docName="draft-skill-design-spec-05"`; renderings; cross-check prints empty diffs; `--rules` count updated in memory.
- [ ] Commit `docs(sds): revision 05 — kit tests, hermetic gate, sweep registry, idempotency marker`.

### Task 24: Kit guides caught up

- [ ] `kit/HOW-TO-BUILD-A-SKILL.md`: Step 0 scaffolder, Step 11 runner + `kit/tests`, Step 12 sweep registry, a "Command Skill idempotency marker" paragraph citing SDS-S-057.
- [ ] `kit/PRIMITIVES.md`: primitive "Idempotency marker" with the three skills as examples.
- [ ] Commit `docs(kit): guides cover scaffolder, runner, tests, sweep, idempotency marker`.

### Task 25: Memory and catalog closure

- [ ] Update `~/.claude/projects/-home-edox1-Public/memory/skills-family-repo.md` (state line: skill count, revision 05, rule count, tag, the sweep command) and `MEMORY.md`'s hook line.
- [ ] Catalog: mark the fourth bench built, add the cross-cutting trio (Tasks 6–8), and a "Utilization" paragraph pointing at `docs/live-runs/` and `docs/promotion-criteria.md`.

### Task 26: Tag `v1.3.0-draft`

- [ ] Registry `version` → `1.3.0-draft`; `render_plugin.py`; `claude plugin validate .` passes; CI green on the commit; the tag is the one `release-publisher` created in Task 20 (verify `git tag` shows it and `gh release view v1.3.0-draft -R soilmass/dev-skills-suite` resolves). If Task 20 was deferred, `git tag -a v1.3.0-draft -m "dev-skills-suite v1.3.0-draft: shape graph closed, fourth bench, kit tests, sweep" && git push origin main --tags`.

---

## Self-review

**Spec coverage.** "Build everything out fully": W1 closes every shape's consumer gap (Task 8's check), W2 fills the clusters the catalog called thin plus a security seam. "Utilize everything fully": W3 runs every Query Skill on three real repositories (Tasks 16–18), every Command Skill live (Task 19), and the family's own release through four of its skills (Task 20). "And more": W0 makes the tooling self-verifying (Tasks 1–3, 5), Task 4 lowers the cost of every later skill, W4 gives readers a way in and keeps spec, kit, and linter equal (Task 23's cross-check).

**Placeholder scan.** Skill tasks 7–15 name their rule tables, throws, fixtures, and rows; the shared mechanics are pointed at one fully written reference (Task 6) rather than repeated. Three values are deliberately left to be read at execution time because guessing them would be wrong: the five rule IDs in Task 1 (from `--rules`), the compare script's name in Task 3, and the pinned SHA in Task 5.

**Type consistency.** `finding-list`, `plan-doc`, `status-report`, `decision-doc` are the only shapes named; `sweep.json`'s keys are skill names; the idempotency marker text `<!-- sds-finding-group: <tool>/<ruleId> -->` (Task 6) and `<!-- sds-report: <id> -->` (Task 8) are the strings SDS-S-057 (Task 23) refers to.

**Order.** W0 first (Tasks 1–5), then W1–W2 in any order, then W3 (needs W1's three skills and W2's two sweep entries), then W4. Tasks 19 (four gates), 20 (one high gate), and the plugin install need the user; everything else runs autonomously.
