"""Public login-method routes: method discovery, CAS login / callback / logout, HTTP Basic login."""

from __future__ import annotations

import base64
import binascii
import math
from typing import Annotated
from urllib.parse import urlencode, urlsplit

import httpx2
import structlog
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from heracles.api.deps import StateDep, client_ip, session_from_cookie
from heracles.api.errors import ApiError, not_found, unauthenticated, validation
from heracles.api.hosts import request_base
from heracles.api.state import AppState
from heracles.auth.cas import CasClient, CasError
from heracles.auth.login import InvalidLoginError, authenticate_bind, find_user_dn
from heracles.auth.sessions import CLIENT_KEY, client_info
from heracles.auth.sso import SsoConfig, effective_sso
from heracles.ldap.client import DirectoryClient

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

#: Cookie telling the SPA that the session was opened through CAS (so it can end the CAS session).
SSO_COOKIE = "heracles_sso"
BASIC_REALM = 'Basic realm="Heracles", charset="UTF-8"'


class MethodInfo(BaseModel):
    """One way of signing in."""

    id: str
    #: Where the browser goes to start this method (``null`` for the form).
    url: str | None = None


class MethodsResponse(BaseModel):
    """Public description of the login methods."""

    #: The configured primary method (``form`` unless another one is configured and usable).
    login_method: str
    methods: list[MethodInfo]


def _directory(state: AppState, directory_id: str | None) -> tuple[str, DirectoryClient]:
    if directory_id is None:
        directory_id = next(iter(state.directories), "")
    directory = state.directories.get(directory_id)
    if directory is None:
        raise validation("Unknown directory", {"directory": "Unknown directory"})
    return directory_id, directory


def _config(state: AppState, directory: DirectoryClient) -> SsoConfig:
    return effective_sso(state.settings.sso, directory)


def safe_next(value: str | None) -> str:
    """Only same-origin absolute paths are accepted as post-login targets."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


def _public_base(request: Request, state: AppState, config: SsoConfig) -> str:
    name = config.cas_service_name.strip()
    if name:
        return (name if "://" in name else f"https://{name}").rstrip("/")
    return request_base(request, state.settings.allowed_hosts, setting="cas_service_name")


def _service_url(
    request: Request, state: AppState, config: SsoConfig, directory_id: str, next_path: str
) -> str:
    query = urlencode({"directory": directory_id, "next": next_path})
    return f"{_public_base(request, state, config)}/api/v2/auth/cas/callback?{query}"


def _cas_client(request: Request, config: SsoConfig) -> CasClient:
    transport: httpx2.BaseTransport | None = getattr(request.app.state, "cas_transport", None)
    return CasClient(config, transport=transport)


def available_methods(state: AppState, config: SsoConfig) -> MethodsResponse:
    methods = [MethodInfo(id="form")]
    if config.basic_available:
        methods.append(MethodInfo(id="http-basic", url="/api/v2/auth/login/basic"))
    if state.settings.login.header_enabled:
        methods.append(MethodInfo(id="http-header", url="/api/v2/auth/login/header"))
    if config.cas_available:
        methods.append(MethodInfo(id="cas", url="/api/v2/auth/cas/login"))
    primary = config.login_method if any(m.id == config.login_method for m in methods) else "form"
    return MethodsResponse(login_method=primary, methods=methods)


@router.get("/methods")
def login_methods(
    state: StateDep, directory: Annotated[str | None, Query()] = None
) -> MethodsResponse:
    """Which sign-in methods are enabled (public: the login page needs it)."""
    _, client = _directory(state, directory)
    return available_methods(state, _config(state, client))


def _open_session(
    request: Request,
    response: Response,
    state: AppState,
    user_dn: str,
    directory_id: str,
    *,
    sso: str | None = None,
) -> list[str]:
    """Rotate the session and open a new one; returns the pending second-factor methods."""
    old = session_from_cookie(request, state)
    if old is not None:
        state.sessions.delete(old.id)
    methods = state.second_factor.methods_for(user_dn)
    session = state.sessions.create(
        user_dn,
        directory_id,
        second_factor_pending=bool(methods),
        second_factor_methods=methods,
    )
    session.cache[CLIENT_KEY] = client_info(
        client_ip(request, state), request.headers.get("user-agent")
    )
    if sso:
        session.cache["sso"] = sso
    state.sessions.save(session)
    cfg = state.settings.session
    response.set_cookie(
        cfg.cookie_name,
        session.id,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite="lax",
        path="/",
    )
    if sso:
        response.set_cookie(
            SSO_COOKIE, sso, httponly=False, secure=cfg.cookie_secure, samesite="lax", path="/"
        )
    return methods


def _landing(next_path: str, methods: list[str]) -> str:
    if not methods:
        return next_path
    query = urlencode({"methods": ",".join(methods), "redirect": next_path})
    return f"/login/second-factor?{query}"


def _rate_limited(state: AppState, request: Request, login: str) -> str:
    key = state.limiter.key(client_ip(request, state), login)
    wait = state.limiter.retry_after(key)
    if wait > 0:
        raise ApiError(
            429,
            "rate_limited",
            "Too many attempts, try again later",
            headers={"Retry-After": str(math.ceil(wait))},
        )
    return key


# -- CAS ----------------------------------------------------------------------------------------
def _cas_config(state: AppState, directory: DirectoryClient) -> SsoConfig:
    config = _config(state, directory)
    if not config.cas_available:
        raise not_found("CAS login is not enabled")
    return config


@router.get("/cas/login")
def cas_login(
    request: Request,
    state: StateDep,
    directory: Annotated[str | None, Query()] = None,
    next: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Send the browser to the CAS server."""
    directory_id, client = _directory(state, directory)
    config = _cas_config(state, client)
    service = _service_url(request, state, config, directory_id, safe_next(next))
    return RedirectResponse(_cas_client(request, config).login_url(service), status_code=302)


@router.get("/cas/callback")
def cas_callback(
    request: Request,
    state: StateDep,
    directory: Annotated[str | None, Query()] = None,
    ticket: Annotated[str | None, Query()] = None,
    next: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Validate the ticket, map the CAS user to an account and open a session."""
    directory_id, client = _directory(state, directory)
    config = _cas_config(state, client)
    target = safe_next(next)
    failure = RedirectResponse("/login?sso_error=1", status_code=302)
    if not ticket:
        return failure
    service = _service_url(request, state, config, directory_id, target)
    try:
        principal = _cas_client(request, config).validate(ticket, service)
    except CasError as exc:
        log.info("cas_validation_failed", reason=str(exc))
        return failure
    key = _rate_limited(state, request, "cas:" + principal.name)
    user_dn = find_user_dn(client, state.login_config, principal.name)
    if user_dn is None:
        state.limiter.record_failure(key)
        log.info("cas_unknown_account", directory=directory_id)
        return failure
    state.limiter.record_success(key)
    response = RedirectResponse("/", status_code=302)
    methods = _open_session(request, response, state, user_dn, directory_id, sso="cas")
    response.headers["location"] = _landing(target, methods)
    log.info("login_ok", directory=directory_id, user=user_dn, method="cas")
    return response


@router.get("/cas/logout")
def cas_logout(
    request: Request,
    state: StateDep,
    directory: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """End the Heracles session (if any) and the CAS session, then come back to the login page."""
    session = session_from_cookie(request, state)
    if session is not None:
        state.sessions.delete(session.id)
        for hook in state.logout_hooks:
            try:
                hook(session)
            except Exception:
                log.exception("logout_hook_failed")
    destination = "/login"
    try:
        _, client = _directory(state, directory)
        config = _config(state, client)
        if config.cas_available:
            back = f"{_public_base(request, state, config)}/login"
            destination = _cas_client(request, config).logout_url(back)
    except ApiError:
        pass
    response = RedirectResponse(destination, status_code=302)
    response.delete_cookie(state.settings.session.cookie_name, path="/")
    response.delete_cookie(SSO_COOKIE, path="/")
    return response


# -- HTTP Basic ---------------------------------------------------------------------------------
def _challenge(message: str) -> ApiError:
    error = unauthenticated(message)
    error.headers = {"WWW-Authenticate": BASIC_REALM}
    return error


def parse_basic(header: str | None) -> tuple[str, str] | None:
    """``(login, password)`` of an ``Authorization: Basic`` header."""
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic" or not value.strip():
        return None
    try:
        decoded = base64.b64decode(value.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    login, sep, password = decoded.partition(":")
    return (login, password) if sep and login else None


def _require_same_origin(request: Request) -> None:
    """Refuse a navigation started by another site.

    The Basic login is a GET (the browser challenge needs a navigation), so any page could
    send the visitor to ``https://attacker:secret@console/...`` and sign them in as the
    attacker (login CSRF). Browsers state who started the request: ``Sec-Fetch-Site`` must
    be ``same-origin`` (a link in the console) or ``none`` (typed address, bookmark). Without
    it (command-line clients, old browsers) a present ``Origin`` must name this host.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        allowed = site in ("same-origin", "none")
    else:
        origin = request.headers.get("origin")
        allowed = origin is None or urlsplit(origin).netloc == request.headers.get("host")
    if not allowed:
        log.warning("login_basic_cross_site", site=site, origin=request.headers.get("origin"))
        raise ApiError(403, "cross_site", "Sign-in must be started from this site")


@router.get("/login/basic")
def login_basic(
    request: Request,
    state: StateDep,
    directory: Annotated[str | None, Query()] = None,
    next: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """HTTP Basic login: challenge the browser, check the credentials by LDAP bind."""
    directory_id, client = _directory(state, directory)
    if not _config(state, client).basic_available:
        raise not_found("HTTP Basic login is not enabled")
    _require_same_origin(request)
    credentials = parse_basic(request.headers.get("authorization"))
    if credentials is None:
        raise _challenge("Authentication required")
    login, password = credentials
    key = _rate_limited(state, request, login)
    try:
        user_dn = authenticate_bind(client, state.login_config, login, password)
    except InvalidLoginError:
        state.limiter.record_failure(key)
        raise _challenge("Invalid username or password") from None
    state.limiter.record_success(key)
    response = RedirectResponse("/", status_code=302)
    methods = _open_session(request, response, state, user_dn, directory_id)
    response.headers["location"] = _landing(safe_next(next), methods)
    log.info("login_ok", directory=directory_id, user=user_dn, method="http-basic")
    return response


__all__ = ["SSO_COOKIE", "available_methods", "parse_basic", "router", "safe_next"]
