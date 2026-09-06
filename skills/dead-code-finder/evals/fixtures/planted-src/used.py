"""Planted fixture: a definition that IS referenced (by main.py)."""


def helper(x):
    return x * 2


class UsedByHelper:
    """Referenced only from within this module, which still counts."""

    def run(self):
        return helper(1)


_instance = UsedByHelper()
