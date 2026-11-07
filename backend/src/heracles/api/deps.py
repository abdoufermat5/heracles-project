"""FastAPI dependencies shared by all routers.

Routers use :data:`CurrentUserDep` to require an authenticated session::

    @router.get("/something")
    def something(user: CurrentUserDep) -> ...:
        user.directory.search(...)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from heracles.api.errors import ApiError, forbidden, unauthenticated
from heracles.api.state import AppState
from heracles.auth import csrf
from heracles.auth.login import is_trusted_proxy
from heracles.auth.sessions import Session
from heracles.ldap.client import DirectoryClient


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.heracles
    return state


StateDep = Annotated[AppState, Depends(get_state)]


def client_ip(request: Request, state: AppState) -> str:
    """Peer address, or the right-most untrusted ``X-Forwarded-For`` hop behind a trusted proxy."""
    peer = request.client.host if request.client else "unknown"
    if not is_trusted_proxy(peer, state.trusted_proxies):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):
        if not is_trusted_proxy(hop, state.trusted_proxies):
            return hop
    return peer


def csrf_protect(request: Request) -> None:
    """Double-submit check for mutating requests (exempts safe methods and API v1)."""
    try:
        csrf.check(
            request.method,
            request.url.path,
            request.cookies.get(csrf.CSRF_COOKIE),
            request.headers.get(csrf.CSRF_HEADER),
        )
    except csrf.CsrfError as exc:
        raise forbidden(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The authenticated principal of a request."""

    session: Session
    directory_id: str
    directory: DirectoryClient
    client_ip: str = ""

    @property
    def dn(self) -> str:
        return self.session.user_dn


def session_from_cookie(request: Request, state: AppState) -> Session | None:
    sid = request.cookies.get(state.settings.session.cookie_name)
    return state.sessions.get(sid) if sid else None


def current_session(request: Request, state: StateDep) -> Session:
    """A live session, including one still waiting for its second factor."""
    session = session_from_cookie(request, state)
    if session is None:
        raise unauthenticated()
    return session


def current_user(request: Request, state: StateDep) -> CurrentUser:
    """Require a fully authenticated session (second factor done)."""
    session = session_from_cookie(request, state)
    if session is None:
        raise unauthenticated()
    if session.second_factor_pending:
        raise unauthenticated("Second factor required")
    directory = state.directories.get(session.directory_id)
    if directory is None:
        raise ApiError(401, "unauthenticated", "Unknown directory")
    return CurrentUser(session, session.directory_id, directory, client_ip(request, state))


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
PendingSessionDep = Annotated[Session, Depends(current_session)]
