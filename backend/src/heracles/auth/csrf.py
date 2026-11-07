"""Double-submit CSRF protection.

The token is handed out by ``GET /api/v2/auth/csrf`` and mirrored in the
``heracles_csrf`` cookie. Mutating requests must repeat it in ``X-CSRF-Token``.
The framework glue (a FastAPI dependency) lives in ``heracles.api.deps``.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Final

CSRF_COOKIE: Final = "heracles_csrf"
CSRF_HEADER: Final = "X-CSRF-Token"
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
#: Path prefixes that never need a CSRF token (API v1 uses a session token header).
EXEMPT_PREFIXES: Final = ("/api/v1",)


class CsrfError(Exception):
    """CSRF validation failed."""


def new_token() -> str:
    return secrets.token_urlsafe(32)


def is_exempt(method: str, path: str) -> bool:
    if method.upper() in SAFE_METHODS:
        return True
    return any(path == p or path.startswith(p + "/") for p in EXEMPT_PREFIXES)


def check(method: str, path: str, cookie: str | None, header: str | None) -> None:
    """Raise :class:`CsrfError` unless the request is exempt or the tokens match."""
    if is_exempt(method, path):
        return
    if not cookie or not header:
        raise CsrfError("Missing CSRF token")
    if not hmac.compare_digest(cookie.encode(), header.encode()):
        raise CsrfError("Invalid CSRF token")
