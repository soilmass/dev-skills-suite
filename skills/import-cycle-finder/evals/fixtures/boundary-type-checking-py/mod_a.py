"""Minimal reproduction of a false positive found dogfooding this skill
on psf/requests (src/requests/_types.py imports .cookies only inside
`if TYPE_CHECKING:`, while src/requests/cookies.py imports ._types for
real — the TYPE_CHECKING-only edge closed a phantom cycle)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mod_b import Thing


def helper():
    return None
