"""Minimal reproduction of a false positive found dogfooding this
skill on psf/requests (tests/test_utils.py, e.g. `class TestSuperLen:`):
a bare (no base classes) class named Test* with no __init__, inside
pytest's own collection scope (this file's name starts with test_,
and it also lives under a tests/ directory) — pytest collects it by
name pattern alone, no TestCase base required."""


class TestHelper:
    def test_something(self):
        assert True
