"""Planted fixture: no debt signals at all — must produce zero findings."""


def clamp(value, low, high):
    return max(low, min(high, value))
