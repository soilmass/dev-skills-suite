"""Planted fixture: two definitions nothing references (SDS-S-095)."""


def orphan(a, b):
    return a + b


class Abandoned:
    def __init__(self):
        self.x = 1


def test_helper_shape():
    """Named like a test: must NOT be reported even though nothing calls it."""
    assert True
