"""Account lock helpers.

A locked account has ``!`` right after the ``{SCHEME}`` prefix. An account
without any password is locked with the sentinel :data:`EMPTY_LOCK`.
"""

from __future__ import annotations

import re
from typing import Final

EMPTY_LOCK: Final = "{CRYPT}!"
_LOCKED_RE = re.compile(r"^[^}]*}!")


def is_locked(stored: str) -> bool:
    """True if ``stored`` carries the lock marker."""
    return _LOCKED_RE.match(stored) is not None


def lock(stored: str) -> str:
    """Return the locked form of ``stored`` (idempotent)."""
    if is_locked(stored):
        return stored
    if stored == "":
        return EMPTY_LOCK
    end = stored.find("}")
    if stored.startswith("{") and end != -1:
        return stored[: end + 1] + "!" + stored[end + 1 :]
    # Plain-text value without a scheme tag: make the tag explicit.
    return "{CLEAR}!" + stored


def unlock(stored: str) -> str:
    """Return the unlocked form of ``stored`` (idempotent)."""
    if stored == EMPTY_LOCK:
        return ""
    m = _LOCKED_RE.match(stored)
    if m is None:
        return stored
    return stored[: m.end() - 1] + stored[m.end() :]
