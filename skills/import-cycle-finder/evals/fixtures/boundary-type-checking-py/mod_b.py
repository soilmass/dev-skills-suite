"""Real, unconditional counterpart to mod_a.py's TYPE_CHECKING-only
import — see mod_a.py for provenance."""
from __future__ import annotations

from .mod_a import helper


class Thing:
    pass


helper()
