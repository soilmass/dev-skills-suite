"""Consistent fixture."""
from flags import is_enabled


def f():
    return is_enabled("beta-search")
