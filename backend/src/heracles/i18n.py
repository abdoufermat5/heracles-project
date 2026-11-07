"""Translation marker.

``_()`` is a no-op that flags a literal as translatable so that extraction
tools (and later a real catalogue lookup) can find it. Labels and messages are
plain strings at definition time.
"""

from __future__ import annotations


def _(message: str) -> str:
    """Mark ``message`` as translatable and return it unchanged."""
    return message
