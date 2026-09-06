"""Planted fixture: no call sites of the old path — must not appear in the scope."""


def format_total(cents):
    return f"{cents / 100:.2f}"
