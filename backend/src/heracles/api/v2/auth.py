"""Authentication endpoints of API v2."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Request, Response
from pydantic import BaseModel, Field
from webauthn import base64url_to_bytes
from webauthn.helpers import bytes_to_base64url

from heracles.api.auth_audit import audit_login, audit_login_failed
from heracles.api.deps import (
    CurrentUserDep,
    PendingSessionDep,
    StateDep,
    client_ip,
    session_from_cookie,
)
from heracles.api.errors import ApiError, not_found, unauthenticated, validation
from heracles.api.state import AppState
from heracles.api.stepup import mark_reauthenticated, require_recent_auth
from heracles.auth import csrf
from heracles.auth.login import (
    InvalidLoginError,
    authenticate_bind,
    authenticate_header,
)
from heracles.auth.passwords import PasswordPolicyError
from heracles.auth.recovery import RecoveryError
from heracles.auth.second_factor import WebAuthnCredential
from heracles.auth.sessions import CLIENT_KEY, Session, client_info, session_ref
from heracles.auth.webauthn import ASSERTION_KEY, REGISTRATION_KEY, WebAuthnError
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Scope
from heracles.ldap.filter import escape_filter_value

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
directories_router = APIRouter(tags=["auth"])

_GENERIC_LOGIN_ERROR = "Invalid username or password"


# -- models --------------------------------------------------------------------------------------
class CsrfResponse(BaseModel):
    token: str


class DirectoryInfo(BaseModel):
    id: str
    label: str


class LoginBody(BaseModel):
    directory: str = "main"
    username: Annotated[str, Field(min_length=1, max_length=256)]
    password: Annotated[str, Field(max_length=1024)]


class HeaderLoginBody(BaseModel):
    directory: str = "main"


class LoginResponse(BaseModel):
    status: Literal["ok", "second_factor"]
    methods: list[str] = Field(default_factory=lambda: [])


class SecondFactorBody(BaseModel):
    method: Literal["totp", "webauthn", "recovery"]
    code: Annotated[str, Field(max_length=2048)] = ""
    #: The browser's assertion (``PublicKeyCredential`` as JSON) for method ``webauthn``.
    credential: dict[str, Any] | None = None


class StatusResponse(BaseModel):
    status: Literal["ok"] = "ok"


class Me(BaseModel):
    dn: str
    uid: str
    display_name: str
    avatar_url: str | None
    is_admin: bool
    directory: str
    base: str


class ReauthBody(BaseModel):
    """The current password, or a code of an existing second factor."""

    password: Annotated[str, Field(max_length=1024)] = ""
    method: Literal["totp", "recovery"] | None = None
    code: Annotated[str, Field(max_length=64)] = ""


class SessionOut(BaseModel):
    id: str
    user_agent: str
    ip: str
    created_at: float
    last_seen: float
    current: bool


class RevokedOut(BaseModel):
    revoked: int


class WebAuthnOptions(BaseModel):
    options: dict[str, Any]


class WebAuthnRegisterBody(BaseModel):
    label: Annotated[str, Field(max_length=64)] = ""
    credential: dict[str, Any]


class WebAuthnCredentialInfo(BaseModel):
    id: str
    label: str
    sign_count: int


class TotpStatus(BaseModel):
    enabled: bool
    recovery_codes_remaining: int
    security_keys: int


class TotpEnrolment(BaseModel):
    secret: str
    uri: str
    expires_in: int


class TotpConfirmBody(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=16)]


class RecoveryCodes(BaseModel):
    codes: list[str]


class RecoveryBody(BaseModel):
    email: Annotated[str, Field(max_length=320)]
    directory: str | None = None


class RecoveryConfirmBody(BaseModel):
    login: Annotated[str, Field(min_length=1, max_length=256)]
    token: Annotated[str, Field(min_length=1, max_length=512)]
    password: Annotated[str, Field(max_length=1024)]
    directory: str | None = None


# -- helpers -------------------------------------------------------------------------------------
def _set_session_cookie(response: Response, state: AppState, session: Session) -> None:
    cfg = state.settings.session
    response.set_cookie(
        cfg.cookie_name,
        session.id,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite="lax",
        path="/",
    )


def _set_csrf_cookie(response: Response, state: AppState, token: str) -> None:
    response.set_cookie(
        csrf.CSRF_COOKIE,
        token,
        httponly=False,
        secure=state.settings.session.cookie_secure,
        samesite="lax",
        path="/",
    )


def _directory(state: AppState, directory_id: str | None) -> tuple[str, DirectoryClient]:
    if directory_id is None:
        directory_id = next(iter(state.directories), "")
    directory = state.directories.get(directory_id)
    if directory is None:
        raise validation("Unknown directory", {"directory": "Unknown directory"})
    return directory_id, directory


def _start_session(
    request: Request,
    response: Response,
    state: AppState,
    user_dn: str,
    directory_id: str,
) -> LoginResponse:
    """Drop any previous session (rotation) and open a new one for ``user_dn``."""
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
    state.sessions.save(session)
    _set_session_cookie(response, state, session)
    if methods:
        return LoginResponse(status="second_factor", methods=methods)
    return LoginResponse(status="ok")


# -- endpoints -----------------------------------------------------------------------------------
@router.get("/csrf")
def get_csrf(request: Request, response: Response, state: StateDep) -> CsrfResponse:
    token = request.cookies.get(csrf.CSRF_COOKIE) or csrf.new_token()
    _set_csrf_cookie(response, state, token)
    return CsrfResponse(token=token)


class Branding(BaseModel):
    organization: str
    logo_url: str | None
    tagline: str


@directories_router.get("/branding")
def branding(state: StateDep) -> Branding:
    """Public: how the sign-in page presents the organisation."""
    b = state.settings.branding
    return Branding(organization=b.organization, logo_url=b.logo_url or None, tagline=b.tagline)


@directories_router.get("/directories")
def list_directories(state: StateDep) -> list[DirectoryInfo]:
    labels = state.settings.directory_labels
    return [DirectoryInfo(id=i, label=labels.get(i, i)) for i in state.directories]


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, state: StateDep) -> LoginResponse:
    directory_id, directory = _directory(state, body.directory)
    key = state.limiter.key(client_ip(request, state), body.username)
    wait = state.limiter.retry_after(key)
    if wait > 0:
        raise ApiError(
            429,
            "rate_limited",
            "Too many attempts, try again later",
            extra={"retry_after": math.ceil(wait)},
            headers={"Retry-After": str(math.ceil(wait))},
        )
    try:
        user_dn = authenticate_bind(directory, state.login_config, body.username, body.password)
    except InvalidLoginError:
        state.limiter.record_failure(key)
        log.info("login_failed", directory=directory_id)
        audit_login_failed(state, request, directory, body.username, "invalid credentials")
        raise unauthenticated(_GENERIC_LOGIN_ERROR) from None
    state.limiter.record_success(key)
    log.info("login_ok", directory=directory_id, user=user_dn)
    audit_login(state, request, directory, user_dn, "password")
    return _start_session(request, response, state, user_dn, directory_id)


@router.post("/login/header")
def login_header(
    body: HeaderLoginBody, request: Request, response: Response, state: StateDep
) -> LoginResponse:
    """Login by trusted reverse-proxy header (disabled unless configured)."""
    cfg = state.settings.login
    if not cfg.header_enabled:
        raise ApiError(404, "not_found", "Not found")
    directory_id, directory = _directory(state, body.directory)
    peer = request.client.host if request.client else None
    try:
        user_dn = authenticate_header(
            directory,
            state.login_config,
            peer_ip=peer,
            trusted=state.trusted_proxies,
            header_value=request.headers.get(cfg.header_name),
        )
    except InvalidLoginError:
        raise unauthenticated() from None
    audit_login(state, request, directory, user_dn, "header")
    return _start_session(request, response, state, user_dn, directory_id)


@router.post("/second-factor")
def second_factor(
    body: SecondFactorBody,
    request: Request,
    response: Response,
    state: StateDep,
    session: PendingSessionDep,
) -> StatusResponse:
    if not session.second_factor_pending:
        return StatusResponse()
    if body.method not in session.second_factor_methods:
        raise validation("Method not available", {"method": "Method not available"})
    # Cap across logins: the per-session failure budget is renewed by every new login (the
    # password is right), so the code would be open to unlimited guessing. Each *exhausted*
    # session counts as one failure of the account (key below), which then backs off
    # exponentially; the per-session budget itself is unaffected.
    key = state.limiter.key("second-factor", dnlib.normalize(session.user_dn))
    wait = state.limiter.retry_after(key)
    if wait > 0:
        raise ApiError(
            429,
            "rate_limited",
            "Too many attempts, try again later",
            extra={"retry_after": math.ceil(wait)},
            headers={"Retry-After": str(math.ceil(wait))},
        )
    if body.method == "webauthn":
        verified = _verify_webauthn(state, session, body.credential)
    else:
        verified = state.second_factor.verify(session.user_dn, body.method, body.code)
    if not verified:
        _audit_second_factor_failed(state, request, session, body.method)
        session.second_factor_failures += 1
        if session.second_factor_failures >= state.settings.login.max_second_factor_failures:
            state.limiter.record_failure(key)
            state.sessions.delete(session.id)
        raise unauthenticated("Invalid code")
    state.limiter.record_success(key)
    # Persist what this request already changed (a consumed WebAuthn challenge) before the
    # row is renamed: the old id stops working right below.
    state.sessions.save(session)
    rotated = state.sessions.rotate(session.id)
    if rotated is None:
        raise unauthenticated()
    rotated.second_factor_pending = False
    rotated.second_factor_failures = 0
    state.sessions.save(rotated)
    _set_session_cookie(response, state, rotated)
    return StatusResponse()


def _audit_second_factor_failed(
    state: AppState, request: Request, session: Session, method: str
) -> None:
    directory = state.directories.get(session.directory_id)
    if directory is None:
        return
    state.audit.record(
        directory,
        "login_failed",
        object_type="user",
        object_dn=session.user_dn,
        author_dn=session.user_dn,
        author_ip=client_ip(request, state),
        attributes=[f"second factor: {method}"],
        result="failure",
    )


@router.post("/reauth")
def reauth(
    body: ReauthBody, request: Request, user: CurrentUserDep, state: StateDep
) -> StatusResponse:
    """Confirm the password (or a second-factor code), allowing sensitive changes a while."""
    if not body.password and not (body.method and body.code):
        raise validation("Enter your password", {"password": "Required"})
    key = state.limiter.key(client_ip(request, state), user.dn)
    wait = state.limiter.retry_after(key)
    if wait > 0:
        raise ApiError(
            429,
            "rate_limited",
            "Too many attempts, try again later",
            extra={"retry_after": math.ceil(wait)},
            headers={"Retry-After": str(math.ceil(wait))},
        )
    if body.method and body.code and not body.password:
        ok = body.method in state.second_factor.methods_for(user.dn) and state.second_factor.verify(
            user.dn, body.method, body.code
        )
        field_name = "code"
    else:
        try:
            ok = user.directory.check_password(user.dn, body.password)
        except DirectoryError:
            ok = False
        field_name = "password"
    if not ok:
        state.limiter.record_failure(key)
        log.info("reauth_failed", user=user.dn)
        # 422, not 401: a wrong confirmation must not end the session.
        raise validation("Wrong password or code", {field_name: "Wrong value"})
    state.limiter.record_success(key)
    mark_reauthenticated(state, user.session)
    return StatusResponse()


def _verify_webauthn(state: AppState, session: Session, credential: dict[str, Any] | None) -> bool:
    """Check an assertion against the (single-use) challenge held by the session."""
    try:
        challenge = state.webauthn.take(session.cache, ASSERTION_KEY)
        if credential is None:
            return False
        return state.webauthn.finish_assertion(session.user_dn, credential, challenge)
    except WebAuthnError:
        return False


@router.post("/webauthn/options")
def webauthn_options(state: StateDep, session: PendingSessionDep) -> WebAuthnOptions:
    """Assertion options for the pending second factor; the challenge lives in the session."""
    if not session.second_factor_pending or "webauthn" not in session.second_factor_methods:
        raise validation("Method not available", {"method": "Method not available"})
    challenge = state.webauthn.begin_assertion(session.user_dn)
    state.webauthn.remember(session.cache, ASSERTION_KEY, challenge.challenge)
    return WebAuthnOptions(options=challenge.options)


def _credential_info(c: WebAuthnCredential) -> WebAuthnCredentialInfo:
    return WebAuthnCredentialInfo(
        id=bytes_to_base64url(c.credential_id),
        label=c.label,
        sign_count=c.sign_count,
    )


@router.get("/webauthn/credentials")
def webauthn_list(user: CurrentUserDep, state: StateDep) -> list[WebAuthnCredentialInfo]:
    return [_credential_info(c) for c in state.webauthn.credentials(user.dn)]


@router.post("/webauthn/credentials/options")
def webauthn_register_options(user: CurrentUserDep, state: StateDep) -> WebAuthnOptions:
    require_recent_auth(state, user.session)
    entry = user.directory.get(user.dn, ["uid", "displayName", "cn"])
    if entry is None:
        raise unauthenticated("Account no longer exists")
    uid = entry.text("uid") or user.dn
    display = entry.text("displayName") or entry.text("cn") or uid
    challenge = state.webauthn.begin_registration(user.dn, uid, display)
    state.webauthn.remember(user.session.cache, REGISTRATION_KEY, challenge.challenge)
    return WebAuthnOptions(options=challenge.options)


@router.post("/webauthn/credentials", status_code=201)
def webauthn_register(
    body: WebAuthnRegisterBody, user: CurrentUserDep, state: StateDep
) -> WebAuthnCredentialInfo:
    label = body.label.strip()
    try:
        challenge = state.webauthn.take(user.session.cache, REGISTRATION_KEY)
        stored = state.webauthn.finish_registration(user.dn, body.credential, challenge, label)
    except WebAuthnError as exc:
        log.info("webauthn_registration_failed", user=user.dn, reason=str(exc))
        raise validation(
            "Security key registration failed", {"credential": "Registration failed"}
        ) from None
    log.info("webauthn_registered", user=user.dn)
    state.audit.record_by(
        user,
        "second_factor",
        object_type="user",
        object_dn=user.dn,
        attributes=["security key: added"],
    )
    return _credential_info(stored)


@router.delete("/webauthn/credentials/{credential_id}", status_code=204)
def webauthn_delete(
    credential_id: str,
    request: Request,
    user: CurrentUserDep,
    state: StateDep,
    confirm_disable: bool = False,
) -> None:
    require_recent_auth(state, user.session)
    try:
        raw = base64url_to_bytes(credential_id)
    except ValueError:
        raise not_found() from None
    remaining = [c for c in state.webauthn.credentials(user.dn) if c.credential_id != raw]
    owned = len(remaining) < len(state.webauthn.credentials(user.dn))
    if owned and not confirm_disable:
        left = [m for m in state.second_factor.methods_for(user.dn) if m != "recovery"]
        if left == ["webauthn"] and not remaining:
            raise ApiError(
                409,
                "last_second_factor",
                "Removing this key turns off the second factor for your account",
            )
    if not state.webauthn.remove_credential(user.dn, raw):
        raise not_found()
    log.info("webauthn_removed", user=user.dn)
    state.audit.record_by(
        user,
        "second_factor",
        object_type="user",
        object_dn=user.dn,
        attributes=["security key: removed"],
    )
    if not _real_factors(state, user.dn):
        _second_factor_turned_off(state, user, request)


# -- TOTP and recovery codes (self-service) ------------------------------------------------------
#: Seconds a freshly generated TOTP secret waits for its confirmation code.
TOTP_PENDING_TTL_SECONDS = 5 * 60
_TOTP_PENDING_KEY = "totp_pending"


def _real_factors(state: AppState, user_dn: str) -> list[str]:
    return [m for m in state.second_factor.methods_for(user_dn) if m != "recovery"]


def _second_factor_turned_off(state: AppState, user: CurrentUserDep, request: Request) -> None:
    """The last second factor is gone: audit it and tell the user by mail (when it is set up)."""
    log.warning("second_factor_turned_off", user=user.dn)
    state.audit.record_by(
        user,
        "second_factor",
        object_type="user",
        object_dn=user.dn,
        attributes=["2FA turned off: last second factor removed"],
    )
    try:
        entry = user.directory.get(user.dn, ["mail"])
        address = entry.text("mail") if entry is not None else None
        if address:
            state.mailer.send(
                address,
                "Two-factor authentication turned off",
                "Two-factor authentication was turned off on your account "
                f"(request from {client_ip(request, state)}).\n"
                "If this was not you, change your password and contact an administrator.",
            )
    except Exception:
        log.exception("second_factor_mail_failed")


@router.get("/totp")
def totp_status(user: CurrentUserDep, state: StateDep) -> TotpStatus:
    store = state.second_factor.store
    return TotpStatus(
        enabled=bool(store.totp_secret(user.dn)),
        recovery_codes_remaining=len(store.recovery_hashes(user.dn)),
        security_keys=len(state.webauthn.credentials(user.dn)),
    )


@router.post("/totp/begin")
def totp_begin(user: CurrentUserDep, state: StateDep) -> TotpEnrolment:
    """Issue a secret for the authenticator app; it only counts once confirmed."""
    require_recent_auth(state, user.session)
    entry = user.directory.get(user.dn, ["uid", "cn"])
    if entry is None:
        raise unauthenticated("Account no longer exists")
    account = entry.text("uid") or entry.text("cn") or user.dn
    secret, uri = state.second_factor.begin_totp(account)
    user.session.cache[_TOTP_PENDING_KEY] = (secret, state.clock() + TOTP_PENDING_TTL_SECONDS)
    return TotpEnrolment(secret=secret, uri=uri, expires_in=TOTP_PENDING_TTL_SECONDS)


@router.post("/totp/confirm")
def totp_confirm(body: TotpConfirmBody, user: CurrentUserDep, state: StateDep) -> StatusResponse:
    """Activate TOTP if the code matches the pending secret (kept for retries on a typo)."""
    require_recent_auth(state, user.session)
    cache = user.session.cache
    pending = cache.get(_TOTP_PENDING_KEY)
    if pending is None or state.clock() > pending[1]:
        cache.pop(_TOTP_PENDING_KEY, None)
        raise validation("Start the setup again", {"code": "Setup expired, start again"})
    if not state.second_factor.activate_totp(user.dn, str(pending[0]), body.code):
        log.info("totp_confirmation_failed", user=user.dn)
        raise validation("Wrong code", {"code": "Wrong code"})
    cache.pop(_TOTP_PENDING_KEY, None)
    log.info("totp_enabled", user=user.dn)
    state.audit.record_by(
        user,
        "second_factor",
        object_type="user",
        object_dn=user.dn,
        attributes=["authenticator app: enabled"],
    )
    return StatusResponse()


@router.delete("/totp", status_code=204)
def totp_disable(
    request: Request, user: CurrentUserDep, state: StateDep, confirm_disable: bool = False
) -> None:
    require_recent_auth(state, user.session)
    store = state.second_factor.store
    if not store.totp_secret(user.dn):
        raise not_found()
    if _real_factors(state, user.dn) == ["totp"] and not confirm_disable:
        raise ApiError(
            409,
            "last_second_factor",
            "Disabling this turns off the second factor for your account",
        )
    store.set_totp_secret(user.dn, None)
    if not _real_factors(state, user.dn):
        store.set_recovery_hashes(user.dn, [])  # unusable now; do not revive them later
    user.session.cache.pop(_TOTP_PENDING_KEY, None)
    log.info("totp_disabled", user=user.dn)
    state.audit.record_by(
        user,
        "second_factor",
        object_type="user",
        object_dn=user.dn,
        attributes=["authenticator app: disabled"],
    )
    if not _real_factors(state, user.dn):
        _second_factor_turned_off(state, user, request)


@router.post("/recovery-codes")
def recovery_codes_generate(user: CurrentUserDep, state: StateDep) -> RecoveryCodes:
    """(Re)generate the single-use codes; the clear values are returned only here."""
    require_recent_auth(state, user.session)
    if not _real_factors(state, user.dn):
        raise ApiError(
            409,
            "second_factor_required",
            "Set up an authenticator app or a security key first",
        )
    codes = state.second_factor.regenerate_recovery_codes(user.dn)
    log.info("recovery_codes_generated", user=user.dn)
    state.audit.record_by(
        user,
        "second_factor",
        object_type="user",
        object_dn=user.dn,
        attributes=["recovery codes: regenerated"],
    )
    return RecoveryCodes(codes=codes)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, state: StateDep) -> None:
    session = session_from_cookie(request, state)
    if session is not None:
        state.sessions.delete(session.id)
        directory = state.directories.get(session.directory_id)
        if directory is not None and not session.second_factor_pending:
            state.audit.record(
                directory,
                "logout",
                object_type="user",
                object_dn=session.user_dn,
                author_dn=session.user_dn,
                author_ip=client_ip(request, state),
            )
        for hook in state.logout_hooks:
            try:
                hook(session)
            except Exception:
                log.exception("logout_hook_failed")
    response.delete_cookie(state.settings.session.cookie_name, path="/")


# -- active sessions (self-service) --------------------------------------------------------------
@router.get("/sessions")
def my_sessions(user: CurrentUserDep, state: StateDep) -> list[SessionOut]:
    """The signed-in person's active sessions (devices), the current one marked."""
    mine = session_ref(user.session.id)
    return [
        SessionOut(
            id=i.ref,
            user_agent=i.user_agent,
            ip=i.ip,
            created_at=i.created_at,
            last_seen=i.last_seen,
            current=i.ref == mine,
        )
        for i in state.sessions.list_for_user(user.dn)
    ]


def _audit_revoke(state: AppState, user: CurrentUserDep, target_dn: str, what: str) -> None:
    log.info("sessions_revoked", actor=user.dn, target=target_dn, what=what)
    state.audit.record_by(
        user,
        "logout",
        object_type="user",
        object_dn=target_dn,
        attributes=[what],
    )


@router.delete("/sessions/{ref}", status_code=204)
def revoke_session(ref: str, user: CurrentUserDep, state: StateDep) -> None:
    """Sign one of the person's other sessions out."""
    if ref == session_ref(user.session.id):
        raise validation("Use sign out for this session", {"id": "This is the current session"})
    if not state.sessions.delete_for_user(user.dn, ref=ref):
        raise not_found("Session not found")
    _audit_revoke(state, user, user.dn, "session revoked")


@router.post("/sessions/revoke-others")
def revoke_other_sessions(user: CurrentUserDep, state: StateDep) -> RevokedOut:
    """Sign out everywhere but here."""
    count = state.sessions.delete_for_user(user.dn, keep=session_ref(user.session.id))
    if count:
        _audit_revoke(state, user, user.dn, f"other sessions revoked: {count}")
    return RevokedOut(revoked=count)


class MyGroup(BaseModel):
    dn: str
    name: str
    description: str


@router.get("/me/groups")
def my_groups(user: CurrentUserDep) -> list[MyGroup]:
    """Groups the signed-in person belongs to (self-service portal).

    A person may always see their own memberships, even without read rights on
    the group entries; only the name and description are returned.
    """
    member = escape_filter_value(user.dn)
    found = user.directory.search(
        user.directory.base_dn,
        f"(&(objectClass=groupOfNames)(member={member}))",
        Scope.SUBTREE,
        ["cn", "description"],
    )
    groups = [
        MyGroup(
            dn=g.dn,
            name=g.text("cn") or g.dn,
            description=g.text("description") or "",
        )
        for g in found
    ]
    return sorted(groups, key=lambda g: g.name.lower())


@router.get("/me")
def me(user: CurrentUserDep, request: Request, state: StateDep) -> Me:
    entry = user.directory.get(user.dn, ["uid", "displayName", "cn"])
    if entry is None:
        state.sessions.delete(user.session.id)
        raise unauthenticated("Account no longer exists")
    uid = entry.text("uid") or ""
    display = entry.text("displayName") or entry.text("cn") or uid
    return Me(
        dn=user.dn,
        uid=uid,
        display_name=display,
        avatar_url=None,
        is_admin=state.is_admin(user.directory, user.dn),
        directory=user.directory_id,
        base=user.directory.base_dn,
    )


# -- password recovery ---------------------------------------------------------------------------
def _recover(state: AppState, directory: DirectoryClient, email: str, ip: str) -> None:
    """Send the recovery link and record it (runs after the response)."""
    user_dn = state.recovery.request(directory, email)
    if user_dn is not None:
        state.audit.record(
            directory,
            "password",
            object_type="user",
            object_dn=user_dn,
            author_ip=ip,
            attributes=["recovery link: requested"],
        )


@router.post("/recovery", status_code=202)
def recovery_request(
    body: RecoveryBody, request: Request, tasks: BackgroundTasks, state: StateDep
) -> StatusResponse:
    """Always 202, whatever happens: the work is done after the response is sent."""
    if state.settings.recovery.enabled:
        directory = state.directories.get(body.directory or next(iter(state.directories), ""))
        key = state.limiter.key(client_ip(request, state), "recovery:" + body.email)
        if directory is not None and state.limiter.retry_after(key) <= 0:
            state.limiter.record_failure(key)
            tasks.add_task(_recover, state, directory, body.email, client_ip(request, state))
    return StatusResponse()


@router.post("/recovery/confirm")
def recovery_confirm(
    body: RecoveryConfirmBody, request: Request, state: StateDep
) -> StatusResponse:
    if not state.settings.recovery.enabled:
        raise ApiError(404, "not_found", "Not found")
    _, directory = _directory(state, body.directory)
    key = state.limiter.key(client_ip(request, state), "recovery-confirm:" + body.login)
    wait = state.limiter.retry_after(key)
    if wait > 0:
        raise ApiError(
            429,
            "rate_limited",
            "Too many attempts, try again later",
            headers={"Retry-After": str(math.ceil(wait))},
        )
    ip = client_ip(request, state)
    try:
        user_dn = state.recovery.confirm(directory, body.login, body.token, body.password)
    except PasswordPolicyError as exc:
        raise validation("Password rejected", {"password": "; ".join(exc.problems)}) from None
    except RecoveryError:
        state.limiter.record_failure(key)
        state.audit.record(
            directory,
            "password",
            object_type="user",
            object_dn=body.login,
            author_ip=ip,
            attributes=["recovery: invalid or expired link"],
            result="failure",
        )
        raise validation(
            "Invalid or expired recovery link", {"token": "Invalid or expired token"}
        ) from None
    state.limiter.record_success(key)
    # A reset is what people do when the account may be compromised: whoever holds a session
    # of it must not keep it.
    state.sessions.delete_for_user(user_dn)
    state.audit.record(
        directory,
        "password",
        object_type="user",
        object_dn=user_dn,
        author_dn=user_dn,
        author_ip=ip,
        attributes=["password: reset with a recovery link"],
    )
    return StatusResponse()
