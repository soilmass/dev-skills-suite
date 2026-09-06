"""Planted fixture: a public API export nothing in this tree calls.

The exported name is listed in __all__, so it exists for importers
outside this repository and must NOT be reported. The second function
is neither exported nor referenced: it must be reported. (Neither name
may appear in this docstring — a string mention would count as a
possible dynamic reference and mask the finding.)
"""

__all__ = ["public_api"]


def public_api():
    return "for callers outside this tree"


def private_leftover():
    return "nobody calls this"
