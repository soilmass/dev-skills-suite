"""Planted fixture: Python flag checks."""
from flags import is_enabled


def checkout(cart):
    if is_enabled("new-checkout"):
        return "new"
    if is_enabled("dark-mode"):
        return "dark"
    return "old"
