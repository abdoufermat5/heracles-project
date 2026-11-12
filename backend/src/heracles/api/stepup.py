"""Step-up authentication: sensitive account changes need a recent proof of identity.

A fresh login counts; otherwise the client confirms the password (or a code of an existing
second factor) through ``POST /auth/reauth`` and retries. The time of the last proof is kept
on the session (``reauth_at``). A stolen session cookie alone is not enough.
"""

from __future__ import annotations

from heracles.api.errors import ApiError
from heracles.api.state import AppState
from heracles.auth.sessions import Session

#: How long a login or a confirmation allows sensitive account changes.
REAUTH_WINDOW_SECONDS = 5 * 60
REAUTH_KEY = "reauth_at"


def require_recent_auth(state: AppState, session: Session) -> None:
    """Refuse (403 ``reauth_required``) unless the user proved who they are recently."""
    last = float(session.cache.get(REAUTH_KEY, session.created_at))
    if state.clock() - last > REAUTH_WINDOW_SECONDS:
        raise ApiError(403, "reauth_required", "Confirm your password to continue")


def mark_reauthenticated(state: AppState, session: Session) -> None:
    session.cache[REAUTH_KEY] = state.clock()
