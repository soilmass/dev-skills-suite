"""Planted fixture: a decorator-registered function and a test-runner-
discovered class — both live only through their decoration/inheritance,
never through a name reference this scanner's static count can see.
Neither must be reported (a real repository case: kit/scripts/lint-skill.py
registers ~90 check functions this way; kit/tests/test_lint_negative.py
has a unittest.TestCase subclass discovered the same way)."""
import unittest

REGISTRY = []


def register(rule_id):
    def deco(fn):
        REGISTRY.append((rule_id, fn))
        return fn
    return deco


@register("PLANTED-001")
def decorator_registered_check(ctx):
    return []


class DiscoveredByRunner(unittest.TestCase):
    def test_nothing(self):
        self.assertTrue(True)


# Minimal reproduction of a false positive found dogfooding this skill on
# psf/requests (tests/test_utils.py, e.g. `class TestSuperLen:`): pytest
# collects a bare class named Test* by name pattern alone, no TestCase
# base required.
class TestBareClass:
    def test_something(self):
        assert True
