"""Password method protocol and shared helpers."""

from __future__ import annotations

import base64
import re
from typing import Protocol, runtime_checkable

_SCHEME_RE = re.compile(r"^\{([^}]*)\}")


class PasswordError(Exception):
    """Base error for password handling."""


class UnsupportedOperationError(PasswordError):
    """The method cannot perform the requested operation (e.g. verify-only)."""


@runtime_checkable
class PasswordMethod(Protocol):
    """One ``userPassword`` storage scheme."""

    @property
    def id(self) -> str:
        """Stable method identifier."""
        ...

    @property
    def can_hash(self) -> bool:
        """False for verify-only legacy methods."""
        ...

    def hash(self, password: str) -> str:
        """Return the stored form (including ``{SCHEME}`` prefix when applicable)."""
        ...

    def verify(self, password: str, stored: str) -> bool:
        """Constant-time check of ``password`` against ``stored``."""
        ...

    def matches(self, stored: str) -> bool:
        """True if ``stored`` is written in this scheme."""
        ...


def scheme_of(stored: str) -> str | None:
    """Upper-cased ``{SCHEME}`` tag of ``stored`` or ``None``."""
    m = _SCHEME_RE.match(stored)
    return m.group(1).upper() if m else None


def strip_scheme(stored: str) -> str:
    """Remove the leading ``{SCHEME}`` tag if any."""
    m = _SCHEME_RE.match(stored)
    return stored[m.end() :] if m else stored


def b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64decode(text: str) -> bytes | None:
    """Strict base64 decode; ``None`` on malformed input."""
    try:
        return base64.b64decode(text, validate=True)
    except ValueError:
        return None
