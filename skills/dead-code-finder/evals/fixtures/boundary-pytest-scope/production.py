"""Planted fixture (not from a source repository): a bare (no base
classes) class named Test* with no __init__, living outside any
pytest collection scope — not a test_*.py/*_test.py file, not under a
tests/test/testing directory. Pytest would never collect this class
by name pattern here, so unlike its counterpart in tests/test_helpers.py
this is ordinary (perhaps forgotten) production code, and must still
be reported if nothing references it."""


class TestConnection:
    def test_ping(self):
        return True
