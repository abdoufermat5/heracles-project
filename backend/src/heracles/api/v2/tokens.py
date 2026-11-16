"""Managing API tokens: one's own (``/auth/tokens``), a service account's
(``/service-accounts/{dn}/tokens``), everyone's for administrators (``/tokens``).

None of these routes accepts an API token (:mod:`heracles.api.tokens` lists no rule for
them): a token can neither mint nor revoke tokens. Creating one needs a recent proof of
identity (step-up); revoking does not. A person's token is created by that person only:
nobody mints a credential that acts as someone else. A service account (a ``dsa`` object,
which never signs in) gets its tokens from whoever may set its password, an equivalent
power: that person could already bind to the directory as the account.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from heracles.api.deps import CurrentUser, CurrentUserDep, StateDep
from heracles.api.errors import forbidden, not_found, validation
from heracles.api.state import AppState
from heracles.api.stepup import require_recent_auth
from heracles.auth import api_tokens
from heracles.auth.api_tokens import ADMIN, SCOPES, ApiToken
from heracles.ldap import dn as dnlib

log = structlog.get_logger(__name__)

DAY = 86_400.0

router = APIRouter(tags=["tokens"])


class TokenOut(BaseModel):
    id: str
    name: str
    owner_dn: str
    scope: str
    types: list[str]
    created_at: float
    expires_at: float
    last_used_at: float | None
    last_used_ip: str
    #: Networks (CIDR) the token may be used from; empty: any address.
    allowed_ips: list[str]
    #: Who created it (the owner, or for a service account the person who minted it).
    created_by: str


class TokenCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    scope: str
    #: Object types the token is limited to (empty: every type).
    types: list[str] = Field(default_factory=lambda: [])
    expires_in_days: Annotated[int, Field(ge=1)]
    #: Addresses or networks (CIDR) the token may be used from (empty: any address).
    allowed_ips: list[str] = Field(default_factory=lambda: [])


class TokenCreated(TokenOut):
    #: The token itself: shown once, never stored.
    secret: str


class TokenLimits(BaseModel):
    enabled: bool
    max_lifetime_days: int
    scopes: list[str]


def _out(token: ApiToken) -> TokenOut:
    return TokenOut(
        id=token.id,
        name=token.name,
        owner_dn=token.owner_dn,
        scope=token.scope,
        types=list(token.types),
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        last_used_ip=token.last_used_ip,
        allowed_ips=list(token.allowed_ips),
        created_by=token.created_by,
    )


def _audit(
    state: AppState, user: CurrentUser, owner_dn: str, line: str, object_type: str = "user"
) -> None:
    state.audit.record_by(
        user, "api_token", object_type=object_type, object_dn=owner_dn, attributes=[line]
    )


def _known_types(request: Request) -> set[str] | None:
    domain = getattr(request.app.state, "domain", None)
    if domain is None:
        return None
    return {info.name for info in domain.registry.list()}


def _require_console(request: Request, user: CurrentUser) -> None:
    """Tokens are for console users: the self-service portal has no use for the API."""
    domain = getattr(request.app.state, "domain", None)
    if domain is None:
        return
    from heracles.api.v2.admin import is_console_user

    if not is_console_user(user, domain):
        raise forbidden("API tokens are for people who use the administration console")


def _require_enabled(state: AppState) -> None:
    if not state.settings.api_tokens.enabled:
        raise not_found("API tokens are disabled")


# -- one's own tokens ---------------------------------------------------------------------------
@router.get("/auth/tokens/limits")
def token_limits(user: CurrentUserDep, state: StateDep) -> TokenLimits:
    del user
    cfg = state.settings.api_tokens
    return TokenLimits(
        enabled=cfg.enabled, max_lifetime_days=cfg.max_lifetime_days, scopes=list(SCOPES)
    )


@router.get("/auth/tokens")
def my_tokens(user: CurrentUserDep, state: StateDep) -> list[TokenOut]:
    """The signed-in person's API tokens (never their secrets)."""
    now = state.clock()
    return [_out(t) for t in state.api_tokens.list_for_owner(user.dn) if t.expires_at > now]


@router.post("/auth/tokens", status_code=201)
def create_token(
    body: TokenCreate, request: Request, user: CurrentUserDep, state: StateDep
) -> TokenCreated:
    """Create a token acting as the signed-in person. The secret is in this answer only."""
    _require_enabled(state)
    _require_console(request, user)
    return _mint(state, request, user, body, owner_dn=user.dn, object_type="user")


def _mint(
    state: AppState,
    request: Request,
    user: CurrentUser,
    body: TokenCreate,
    *,
    owner_dn: str,
    object_type: str,
) -> TokenCreated:
    """Check ``body``, then create a token acting as ``owner_dn`` (made by ``user``)."""
    cfg = state.settings.api_tokens
    fields: dict[str, str] = {}
    name = body.name.strip()
    if not name:
        fields["name"] = "Give the token a name"
    if body.scope not in SCOPES:
        fields["scope"] = f"One of: {', '.join(SCOPES)}"
    types = sorted({t.strip() for t in body.types if t.strip()})
    if types and body.scope == ADMIN:
        fields["types"] = "An admin token cannot be limited to some types"
    known = _known_types(request)
    unknown = [t for t in types if known is not None and t not in known]
    if unknown:
        fields["types"] = f"Unknown object types: {', '.join(unknown)}"
    if body.expires_in_days > cfg.max_lifetime_days:
        fields["expires_in_days"] = f"At most {cfg.max_lifetime_days} days"
    networks: tuple[str, ...] = ()
    if len([n for n in body.allowed_ips if n.strip()]) > api_tokens.MAX_ALLOWED_IPS:
        fields["allowed_ips"] = f"At most {api_tokens.MAX_ALLOWED_IPS} addresses or networks"
    else:
        try:
            networks = api_tokens.normalize_networks(body.allowed_ips)
        except ValueError as exc:
            fields["allowed_ips"] = f"Not an address or a network: {exc}"
    if fields:
        raise validation("Invalid token", fields)
    require_recent_auth(state, user.session)
    owner = user.directory.get(owner_dn, list(api_tokens.OWNER_STAMP_ATTRS))
    if owner is None:
        raise not_found("The owner of the token does not exist")
    now = state.clock()
    state.api_tokens.purge_expired(now)
    if len(state.api_tokens.list_for_owner(owner_dn)) >= cfg.max_per_owner:
        raise validation(
            "Too many tokens",
            {"name": f"At most {cfg.max_per_owner} tokens: revoke one first"},
        )
    created = api_tokens.generate(
        owner_dn=owner.dn,
        directory_id=user.directory_id,
        name=name,
        scope=body.scope,
        types=types,
        expires_at=now + body.expires_in_days * DAY,
        created_by=user.dn,
        now=now,
        allowed_ips=networks,
        owner_stamp=api_tokens.owner_stamp(owner.text),
    )
    state.api_tokens.add(created.token)
    token = created.token
    log.info("api_token_created", owner=owner.dn, actor=user.dn, token=token.id, scope=token.scope)
    _audit(
        state,
        user,
        owner.dn,
        f"created: {token.id} '{token.name}' scope={token.scope}"
        + (f" types={','.join(token.types)}" if token.types else "")
        + (f" from={','.join(token.allowed_ips)}" if token.allowed_ips else "")
        + f" days={body.expires_in_days}",
        object_type,
    )
    return TokenCreated(**_out(token).model_dump(), secret=created.secret)


@router.delete("/auth/tokens/{token_id}", status_code=204)
def revoke_my_token(token_id: str, user: CurrentUserDep, state: StateDep) -> None:
    token = state.api_tokens.get(token_id)
    if token is None or dnlib.normalize(token.owner_dn) != dnlib.normalize(user.dn):
        raise not_found("Token not found")
    state.api_tokens.delete(token_id)
    log.info("api_token_revoked", owner=user.dn, token=token_id)
    _audit(state, user, user.dn, f"revoked: {token.id} '{token.name}'")


# -- administrators: everyone's tokens ----------------------------------------------------------
def _domain(request: Request) -> Any:
    return getattr(request.app.state, "domain", None)


def _is_admin(request: Request, user: CurrentUser, state: AppState) -> bool:
    domain = _domain(request)
    return state.is_admin(user.directory, user.dn) or (
        domain is not None and domain.is_admin(user.dn)
    )


def _can_manage(request: Request, user: CurrentUser, state: AppState, owner_dn: str) -> bool:
    """May see and revoke this person's tokens: the right to lock their account."""
    if _is_admin(request, user, state):
        return True
    domain = _domain(request)
    if domain is None:
        return False
    from heracles.api.v2.directory import USER_LOCK_ACL

    info = domain.registry.get("user")
    evaluator = domain.evaluator(user)
    return bool(evaluator.can_write_attr(owner_dn, info.acl_object(info.main_tab), USER_LOCK_ACL))


def _can_list_all(request: Request, user: CurrentUser, state: AppState) -> bool:
    """May see every token: an administrator, or whoever may read the configuration."""
    if _is_admin(request, user, state):
        return True
    domain = _domain(request)
    if domain is None:
        return False
    from heracles.api.v2.admin import CONFIG_KEY, rights_of

    return bool(rights_of(user, domain, CONFIG_KEY).read)


@router.get("/tokens")
def all_tokens(
    request: Request, user: CurrentUserDep, state: StateDep, owner: str | None = None
) -> list[TokenOut]:
    """Live API tokens of everyone, or of one ``owner`` (for whoever may lock that account)."""
    if owner is not None:
        if not _can_manage(request, user, state, owner):
            raise forbidden("You cannot see the API tokens of this person")
        found = state.api_tokens.list_for_owner(owner)
    else:
        if not _can_list_all(request, user, state):
            raise forbidden("You cannot see every API token")
        found = state.api_tokens.list_all()
    now = state.clock()
    return [_out(t) for t in found if t.expires_at > now]


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_any_token(
    token_id: str, request: Request, user: CurrentUserDep, state: StateDep
) -> None:
    """Revoke someone's token (whoever may lock their account, after a recent confirmation)."""
    token = state.api_tokens.get(token_id)
    if token is None or not _can_manage(request, user, state, token.owner_dn):
        raise not_found("Token not found")
    require_recent_auth(state, user.session)
    state.api_tokens.delete(token_id)
    log.warning("api_token_revoked", actor=user.dn, owner=token.owner_dn, token=token_id)
    _audit(state, user, token.owner_dn, f"revoked by {user.dn}: {token.id} '{token.name}'")


# -- service accounts: tokens of a ``dsa`` object ----------------------------------------------
SERVICE_ACCOUNT_TYPE = "dsa"


def _service_account(request: Request, user: CurrentUser, dn: str) -> str:
    """The DN of the service account ``dn``, if the caller may manage its tokens.

    The entry must be a ``dsa`` object (never a person), and the caller must be a console
    user allowed to set its password.
    """
    from heracles.objects import ObjectNotFoundError, UnknownTypeError

    domain = _domain(request)
    if domain is None:
        raise not_found("Service accounts are not available")
    _require_console(request, user)
    try:
        service, policy = domain.service(user, SERVICE_ACCOUNT_TYPE)
        account = service.load(SERVICE_ACCOUNT_TYPE, dn)
    except (UnknownTypeError, ObjectNotFoundError):
        raise not_found("Service account not found") from None
    info = domain.registry.get(SERVICE_ACCOUNT_TYPE)
    if not policy.can_write(account.dn, info.main_tab.name, "userPassword"):
        raise forbidden("You cannot manage the API tokens of this service account")
    return account.dn


@router.get("/service-accounts/{dn:path}/tokens")
def service_account_tokens(
    dn: str, request: Request, user: CurrentUserDep, state: StateDep
) -> list[TokenOut]:
    """The live API tokens of a service account (never their secrets)."""
    _require_enabled(state)
    owner = _service_account(request, user, dn)
    now = state.clock()
    return [_out(t) for t in state.api_tokens.list_for_owner(owner) if t.expires_at > now]


@router.post("/service-accounts/{dn:path}/tokens", status_code=201)
def create_service_account_token(
    dn: str, body: TokenCreate, request: Request, user: CurrentUserDep, state: StateDep
) -> TokenCreated:
    """Create a token acting as a service account. The secret is in this answer only."""
    _require_enabled(state)
    owner = _service_account(request, user, dn)
    return _mint(state, request, user, body, owner_dn=owner, object_type=SERVICE_ACCOUNT_TYPE)


@router.delete("/service-accounts/{dn:path}/tokens/{token_id}", status_code=204)
def revoke_service_account_token(
    dn: str, token_id: str, request: Request, user: CurrentUserDep, state: StateDep
) -> None:
    owner = _service_account(request, user, dn)
    token = state.api_tokens.get(token_id)
    if token is None or dnlib.normalize(token.owner_dn) != dnlib.normalize(owner):
        raise not_found("Token not found")
    state.api_tokens.delete(token_id)
    log.warning("api_token_revoked", actor=user.dn, owner=owner, token=token_id)
    _audit(
        state,
        user,
        owner,
        f"revoked by {user.dn}: {token.id} '{token.name}'",
        SERVICE_ACCOUNT_TYPE,
    )
