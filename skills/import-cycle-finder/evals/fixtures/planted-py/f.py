"""Planted unresolved relative import and a planted self-import."""
from . import missing
import f


def noop():
    return None
