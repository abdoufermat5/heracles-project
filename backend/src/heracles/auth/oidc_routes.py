"""OpenID Connect sign-in routes: ``/api/v2/auth/oidc/login``, ``/callback``, ``/logout``.

See :mod:`heracles.auth.oidc`. Every failure sends the browser back to ``/login?sso_error=1``
(the reason goes to the log and, for a known person, to the audit log): the page does not
tell an outsider which check failed.
"""

from __future__ import annotations

import secrets
from typing import Annotated

import httpx2
import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from heracles.acl._names import OC_ROLE
from heracles.api.auth_audit import audit_login, audit_login_failed
from heracles.api.deps import StateDep, session_from_cookie
from heracles.api.errors import ApiError, not_found
from heracles.api.hosts import request_base
from heracles.api.state import AppState
from heracles.auth.login import account_locked
from heracles.auth.oidc import (
    MemoryPendingStore,
    OidcClient,
    OidcError,
    Pending,
    PendingStore,
    SqlPendingStore,
    claim_values,
    mapped_roles,
    new_secret,
)
from heracles.auth.routes import (
    SSO_COOKIE,
    _directory,  # pyright: ignore[reportPrivateUsage]
    _landing,  # pyright: ignore[reportPrivateUsage]
    _open_session,  # pyright: ignore[reportPrivateUsage]
    _rate_limited,  # pyright: ignore[reportPrivateUsage]
    safe_next,
)
from heracles.auth.sessions import SESSION_ROLES_KEY
from heracles.ldap import filter as ldap_filter
from heracles.ldap.client import DirectoryClient, DirectoryError, Scope

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth/oidc", tags=["auth"])

#: Cookie binding a pending sign-in to the browser that started it (holds the ``state``).
STATE_COOKIE = "heracles_oidc"
_COOKIE_PATH = "/api/v2/auth/oidc"
#: Session cache key of the ID token (the logout hint).
ID_TOKEN_KEY = "oidc_id_token"  # noqa: S105 (a cache key, not a secret)
_FAILURE = "/login?sso_error=1"


def _enabled(state: AppState) -> None:
    if not state.settings.oidc.enabled:
        raise not_found("OpenID Connect sign-in is not enabled")


def _client(request: Request, state: AppState) -> OidcClient:
    """One client per application (it caches the provider's documents)."""
    app_state = request.app.state
    client: OidcClient | None = getattr(app_state, "oidc_client", None)
    if client is None or client.settings is not state.settings.oidc:
        transport: httpx2.BaseTransport | None = getattr(app_state, "oidc_transport", None)
        client = OidcClient(state.settings.oidc, transport=transport, clock=state.clock)
        app_state.oidc_client = client
    return client


def _pending(request: Request, state: AppState) -> PendingStore:
    app_state = request.app.state
    store: PendingStore | None = getattr(app_state, "oidc_pending", None)
    if store is None:
        store = (
            SqlPendingStore(state.database) if state.database is not None else MemoryPendingStore()
        )
        app_state.oidc_pending = store
    return store


def _public_base(request: Request, state: AppState) -> str:
    url = state.settings.oidc.public_url.strip()
    if url:
        return (url if "://" in url else f"https://{url}").rstrip("/")
    return request_base(
        request,
        state.settings.allowed_hosts,
        setting="oidc.public_url",
        trusted_proxies=state.trusted_proxies,
    )


def _redirect_uri(request: Request, state: AppState) -> str:
    """Fixed: the provider compares it with the registered one, so nothing varies in it."""
    return f"{_public_base(request, state)}/api/v2/auth/oidc/callback"


def _same(a: str, b: str) -> bool:
    """Constant-time comparison of two strings of any characters (compare_digest refuses
    non-ASCII ``str``)."""
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _failed(response: RedirectResponse | None = None) -> RedirectResponse:
    out = response or RedirectResponse(_FAILURE, status_code=302)
    out.headers["location"] = _FAILURE
    out.delete_cookie(STATE_COOKIE, path=_COOKIE_PATH)
    return out


@router.get("/login")
def oidc_login(
    request: Request,
    state: StateDep,
    directory: Annotated[str | None, Query()] = None,
    next: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Send the browser to the identity provider."""
    _enabled(state)
    directory_id, _ = _directory(state, directory)
    client = _client(request, state)
    pending = Pending(
        state=new_secret(),
        nonce=new_secret(),
        verifier=new_secret(),
        directory_id=directory_id,
        next_path=safe_next(next),
        created_at=state.clock(),
    )
    try:
        target = client.authorization_url(
            _redirect_uri(request, state), pending.state, pending.nonce, pending.verifier
        )
    except OidcError as exc:
        log.warning("oidc_provider_unavailable", reason=str(exc))
        return _failed()
    _pending(request, state).add(pending)
    response = RedirectResponse(target, status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        pending.state,
        max_age=600,
        httponly=True,
        secure=state.settings.session.cookie_secure,
        samesite="lax",
        path=_COOKIE_PATH,
    )
    return response


def _find_account(
    state: AppState, client: DirectoryClient, attribute: str, value: str
) -> str | None:
    """The DN of the single person whose ``attribute`` equals ``value`` (else ``None``)."""
    flt = (
        f"(&(objectClass={ldap_filter.escape_filter_value(state.login_config.user_object_class)})"
        f"({attribute}={ldap_filter.escape_filter_value(value)}))"
    )
    found: list[str] = []
    for entry in client.search(client.base_dn, flt, Scope.SUBTREE, ["1.1"]):
        found.append(entry.dn)
        if len(found) > 1:
            return None
    return found[0] if found else None


_ACCOUNT = "simplesecurityobject"


def _existing_roles(client: DirectoryClient, dns: list[str]) -> list[str]:
    """The DNs of ``dns`` that name a role entry; others are logged and dropped.

    Only role entries: a user, group or service account DN here would hand the session
    someone else's assignments.
    """
    kept: list[str] = []
    for dn in dns:
        try:
            entry = client.get(dn, ["objectClass"])
        except DirectoryError:
            entry = None
        classes: set[str] = (
            {c.lower() for c in entry.texts("objectClass")} if entry is not None else set()
        )
        # a service account is an organizationalRole too, but an account: never a role here
        if entry is not None and OC_ROLE.lower() in classes and _ACCOUNT not in classes:
            kept.append(entry.dn)
        else:
            log.warning("oidc_role_mapping_ignored", dn=dn)
    return kept


@router.get("/callback")
def oidc_callback(
    request: Request,
    state: StateDep,
    code: Annotated[str | None, Query()] = None,
    state_param: Annotated[str | None, Query(alias="state")] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Check what the provider sent back, map the person to an account, open a session."""
    _enabled(state)
    settings = state.settings.oidc
    cookie = request.cookies.get(STATE_COOKIE, "")
    if error:
        log.info("oidc_provider_error", error=error[:64])
        return _failed()
    if not code or not state_param or not cookie or not _same(cookie, state_param):
        log.info("oidc_state_mismatch")
        return _failed()
    pending = _pending(request, state).take(state_param, state.clock())
    if pending is None:
        log.info("oidc_state_unknown")
        return _failed()
    try:
        directory_id, directory = _directory(state, pending.directory_id)
    except ApiError:
        return _failed()
    client = _client(request, state)
    try:
        id_token = client.exchange(code, pending.verifier, _redirect_uri(request, state))
        claims = client.verify(id_token, pending.nonce)
    except OidcError as exc:
        log.warning("oidc_token_refused", reason=str(exc))
        return _failed()

    values = claim_values(claims, settings.claim)
    login = values[0].strip() if len(values) == 1 else ""
    if not login:
        log.info("oidc_claim_missing", claim=settings.claim)
        return _failed()
    key = _rate_limited(state, request, "oidc:" + login)
    if settings.claim == "email" and claims.get("email_verified") is not True:
        audit_login_failed(state, request, directory, login, "oidc: email not verified")
        return _failed()
    if settings.allowed_groups:
        groups = set(claim_values(claims, settings.groups_claim))
        if not groups & set(settings.allowed_groups):
            audit_login_failed(state, request, directory, login, "oidc: group not allowed")
            return _failed()
    attribute = settings.attribute or state.login_config.login_attribute
    user_dn = _find_account(state, directory, attribute, login)
    if user_dn is None:
        log.info("oidc_no_single_account", directory=directory_id)
        audit_login_failed(state, request, directory, login, "oidc: no single matching account")
        return _failed()
    if account_locked(directory, user_dn):
        audit_login_failed(state, request, directory, login, "oidc: account locked")
        return _failed()
    roles = _existing_roles(directory, mapped_roles(settings, claims))
    state.limiter.record_success(key)
    response = RedirectResponse("/", status_code=302)
    audit_login(state, request, directory, user_dn, "oidc", session_roles=roles)
    cache: dict[str, object] = {ID_TOKEN_KEY: id_token}
    if roles:
        cache[SESSION_ROLES_KEY] = roles
    methods = _open_session(
        request, response, state, user_dn, directory_id, sso="oidc", cache=cache
    )
    response.headers["location"] = _landing(pending.next_path, methods)
    response.delete_cookie(STATE_COOKIE, path=_COOKIE_PATH)
    log.info("login_ok", directory=directory_id, user=user_dn, method="oidc")
    return response


@router.get("/logout")
def oidc_logout(request: Request, state: StateDep) -> RedirectResponse:
    """End the Heracles session, then the provider's (when it says how).

    Answers even when the sign-in is switched off: a browser holding a session opened through
    it must still be able to sign out.
    """
    session = session_from_cookie(request, state)
    id_token = ""
    if session is not None:
        id_token = str(session.cache.get(ID_TOKEN_KEY) or "")
        state.sessions.delete(session.id)
        for hook in state.logout_hooks:
            try:
                hook(session)
            except Exception:
                log.exception("logout_hook_failed")
    destination = "/login"
    if state.settings.oidc.enabled:
        back = f"{_public_base(request, state)}/login"
        destination = _client(request, state).logout_url(id_token, back) or "/login"
    response = RedirectResponse(destination, status_code=302)
    response.delete_cookie(state.settings.session.cookie_name, path="/")
    response.delete_cookie(SSO_COOKIE, path="/")
    return response


__all__ = ["ID_TOKEN_KEY", "STATE_COOKIE", "router"]
