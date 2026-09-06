"""Planted fixture: comments and docstrings that match the code — must produce nothing."""


def clamp(value, low, high):
    """Clamp a value into [low, high].

    Args:
        value: the number to clamp
        low: lower bound, inclusive
        high: upper bound, inclusive
    """
    # clamp() is used by total() in drifted.py; the bounds are inclusive on purpose
    return max(low, min(high, value))
