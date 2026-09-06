# kit/tests

Permanent tests for `kit/scripts/lint-skill.py`. `test_lint_negative.py`
copies `skills/codeowners-check`, breaks exactly one MACHINE rule per
case, and asserts the linter reports that rule's ID as an error; one
case asserts the unmodified copy lints clean.

Run: `python3 kit/tests/test_lint_negative.py` (stdlib `unittest`, no
pytest needed) or `python3 -m pytest kit/tests -q`.

Every MACHINE rule added to the linter gets a negative-test case here.
