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

    def test_missing_section_order(self):          # SDS-S-030 h2-order
        self.edit("SKILL.md", "## When not to use", "## Not when")
        self.assertIn("SDS-S-030", lint_ids(self.skill))

    def test_parent_path_reference(self):          # SDS-F-030 root-relative-paths (no ../)
        self.edit("SKILL.md", "kit/shapes/finding-list.schema.json", "../kit/shapes/finding-list.schema.json")
        self.assertIn("SDS-F-030", lint_ids(self.skill))

    def test_forbidden_tool_always(self):          # SDS-S-023 allowed-tools-denylist
        self.edit("SKILL.md", "allowed-tools: >-\n", "allowed-tools: >-\n  Bash(gh pr merge:*)\n")
        self.assertIn("SDS-S-023", lint_ids(self.skill))

    def test_missing_contract_row(self):           # SDS-S-099 eval-required-rows (contract-with-* required)
        ev = self.skill / "evals" / "codeowners-check.eval.yaml"
        text = ev.read_text(encoding="utf-8")
        head, _, _ = text.partition("  - name: contract-with-")
        ev.write_text(head, encoding="utf-8")
        self.assertIn("SDS-S-099", lint_ids(self.skill))

    def test_throws_code_not_declared(self):       # SDS-S-039 throws-form (failureCode must be a declared @throws code)
        self.edit("evals/codeowners-check.eval.yaml", "failureCode: repo-invalid", "failureCode: made-up-code")
        self.assertIn("SDS-S-039", lint_ids(self.skill))

    def test_clean_copy_passes(self):
        self.assertEqual(lint_ids(self.skill), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
