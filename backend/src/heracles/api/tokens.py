"""Requests authenticated with an API token (``Authorization: Bearer hrc_…``).

One authentication mode per request: when the header carries a Bearer token, the session
cookie and the ``Session-Token`` header are ignored everywhere (an invalid token is a 401,
never a fall-back to the cookie). That is what makes such requests safe without the CSRF
token: a browser does not attach an ``Authorization`` header to a cross-site request.

The token acts as its owner: :func:`authenticate` builds a :class:`CurrentUser` around a
throw-away :class:`Session` (never stored, marked with :data:`TOKEN_KEY`), so the owner's
ACL applies unchanged. Step-up (:mod:`heracles.api.stepup`) always refuses such a session.

Routes are **denied unless listed** in :data:`RULES`: each rule names the scope level a
route needs. A token limited to some object types reaches only the routes about one of
those types (the ``type_name`` / ``type`` path parameter, or the type a rule implies) and
the few type-free routes marked ``any_type``. Account security (sign-in, second factors,
sessions, the tokens themselves) is never reachable with a token.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

import structlog
from fastapi import Request

from heracles.acl.rights import FULL_RIGHTS, NO_RIGHTS, Rights
from heracles.api.deps import CurrentUser, StateDep, client_ip
from heracles.api.errors import ApiError
from heracles.api.middleware import bearer_value
from heracles.api.state import AppState
from heracles.auth import api_tokens
from heracles.auth.api_tokens import (
    ADMIN,
    READ,
    SESSION_KEY,
    TOUCH_INTERVAL_SECONDS,
    WRITE,
    ApiToken,
    token_session_id,
)
from heracles.auth.passwords.lock import is_locked
from heracles.auth.sessions import Session
from heracles.core.audit import AUDIT_VIA
from heracles.objects import UnknownTypeError
from heracles.schema.names import STD_ATTR

if TYPE_CHECKING:
    from heracles.objects.registry import TypeRegistry

log = structlog.get_logger(__name__)

#: Session cache key marking a token request (its value is the token id).
TOKEN_KEY: Final = SESSION_KEY
_SCOPE_CACHE: Final = "api_token.scope"
_TYPES_CACHE: Final = "api_token.types"

#: ACL categories whose objects are administration, not directory content: a ``write`` token
#: reads them but changes them only with the ``admin`` scope (whatever the route).
ADMIN_CATEGORIES: Final = frozenset(
    {
        "acl",
        "config",
        "configuration",
        "tasks",
        "dsa",
        "ppolicy",
        "publicForm",
        "invitation",
        "registration",
        "mailTemplate",
        "auditEvent",
        "archivedObject",
    }
)
#: Tabs that are administration on any type (the ACL assignments of a department).
ADMIN_TABS: Final = frozenset({"acl"})

#: ASGI scope key of the authenticated ``(user, token)`` of a request.
_SCOPE_KEY: Final = "heracles.api_token"

_SAFE: Final = frozenset({"GET", "HEAD"})
_MUTATING: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_ANY: Final = _SAFE | _MUTATING


@dataclass(frozen=True, slots=True)
class Rule:
    methods: frozenset[str]
    pattern: re.Pattern[str]
    scope: str
    #: Allowed for a token limited to some types although the route names no type.
    any_type: bool = False
    #: The object type a route without a type parameter is about.
    implied_type: str | None = None


def _rule(
    methods: frozenset[str],
    path: str,
    scope: str,
    *,
    any_type: bool = False,
    implied_type: str | None = None,
) -> Rule:
    return Rule(methods, re.compile(f"^{path}$"), scope, any_type, implied_type)


_V2 = "/api/v2"
_V1 = "/api/v1"
_SCIM = "/scim/v2"
_OBJ = r"/objects/\{type_name\}(/.*)?"
_TYPE = r"/types/\{type_name\}"

#: First match wins. A route matching none is refused to every token.
RULES: Final[tuple[Rule, ...]] = (
    # -- API v2: objects and types
    _rule(_SAFE, _V2 + _OBJ, READ),
    _rule(_MUTATING, _V2 + _OBJ, WRITE),
    _rule(frozenset({"POST"}), _V2 + r"/archive/\{type_name\}/\{dn\}", WRITE),
    _rule(_SAFE, _V2 + "/types", READ, any_type=True),
    _rule(frozenset({"POST"}), _V2 + _TYPE + r"/templates/\{dn\}/preview", READ),
    _rule(_SAFE, _V2 + _TYPE + "(/.*)?", READ),
    _rule(_MUTATING, _V2 + _TYPE + "/templates(/.*)?", ADMIN),
    _rule(frozenset({"POST"}), _V2 + r"/users/\{dn\}/(lock|unlock)", WRITE, implied_type="user"),
    _rule(_SAFE, _V2 + "/tree", READ),
    _rule(_SAFE, _V2 + "/snapshots/deleted", READ),
    _rule(frozenset({"POST"}), _V2 + r"/snapshots/\{snapshot_id\}/restore", WRITE),
    _rule(frozenset({"DELETE"}), _V2 + r"/snapshots/\{snapshot_id\}", WRITE),
    # -- API v2: about the owner, read-only
    _rule(_SAFE, _V2 + "/auth/me(/groups)?", READ, any_type=True),
    _rule(_SAFE, _V2 + "/me/applications", READ, any_type=True),
    _rule(_SAFE, _V2 + "/status", READ, any_type=True),
    _rule(_SAFE, _V2 + "/dashboard", READ),
    _rule(_SAFE, _V2 + "/audit", READ),
    # -- API v2: administration
    _rule(_ANY, _V2 + "/admin/.*", ADMIN),
    _rule(_ANY, _V2 + "/(ldif|csv)/.*", ADMIN),
    _rule(frozenset({"POST"}), _V2 + "/invitations/send", ADMIN),
    # -- API v1
    _rule(_SAFE, _V1 + r"/objects/\{type\}(/.*)?", READ),
    _rule(_MUTATING, _V1 + r"/objects/\{type\}(/.*)?", WRITE),
    _rule(_SAFE, _V1 + "/types", READ, any_type=True),
    _rule(_SAFE, _V1 + r"/types/\{type\}(/.*)?", READ),
    _rule(_SAFE, _V1 + r"/userlock/\{dn\}", READ, implied_type="user"),
    _rule(frozenset({"PUT"}), _V1 + r"/userlock/\{dn\}", WRITE, implied_type="user"),
    _rule(frozenset({"POST"}), _V1 + r"/archive/\{type\}/\{dn\}", WRITE),
    # -- SCIM: users and groups (the type is implied by the collection)
    _rule(_SAFE, _SCIM + "/Users(/.*)?", READ, implied_type="user"),
    _rule(frozenset({"POST"}), _SCIM + r"/Users/\.search", READ, implied_type="user"),
    _rule(_MUTATING, _SCIM + "/Users(/.*)?", WRITE, implied_type="user"),
    _rule(_SAFE, _SCIM + "/Groups(/.*)?", READ, implied_type="group"),
    _rule(frozenset({"POST"}), _SCIM + r"/Groups/\.search", READ, implied_type="group"),
    _rule(_MUTATING, _SCIM + "/Groups(/.*)?", WRITE, implied_type="group"),
    _rule(
        _SAFE, _SCIM + "/(ServiceProviderConfig|ResourceTypes|Schemas)(/.*)?", READ, any_type=True
    ),
)

_INVALID = {"WWW-Authenticate": 'Bearer error="invalid_token"'}


def _invalid(message: str) -> ApiError:
    return ApiError(401, "unauthenticated", message, headers=_INVALID)


def _refused(message: str) -> ApiError:
    return ApiError(
        403,
        "token_scope",
        message,
        headers={"WWW-Authenticate": 'Bearer error="insufficient_scope"'},
    )


def is_token_session(session: Session) -> bool:
    return TOKEN_KEY in session.cache


def rights_cap(session: Session, registry: TypeRegistry) -> Callable[[str], Rights] | None:
    """Upper bound of the rights of a token request per ACL object key (``None``: no token).

    Applied by the ACL evaluator after the owner's own rights (administrators included), so
    whatever route reaches the object layer, a token never exceeds its scope:

    * ``read``: read only, everywhere;
    * ``write``: read only on administration objects (:data:`ADMIN_CATEGORIES`,
      :data:`ADMIN_TABS`);
    * limited to some types: nothing at all on the ACL categories of other types.
    """
    if TOKEN_KEY not in session.cache:
        return None
    scope = str(session.cache.get(_SCOPE_CACHE, READ))
    raw_types: Any = session.cache.get(_TYPES_CACHE) or []
    types = {str(t) for t in cast("list[object]", raw_types)}
    allowed: set[str] | None = None
    if types:
        allowed = set()
        for name in types:
            try:
                allowed.add(registry.get(name).acl_category)
            except UnknownTypeError:
                continue
    admin_keys = {
        info.acl_object(tab)
        for info in registry.list()
        for tab in info.tabs
        if tab.name in ADMIN_TABS
    }
    read_only = FULL_RIGHTS.read_only()

    def cap(obj: str) -> Rights:
        category = obj.split("/", 1)[0]
        if allowed is not None and category not in allowed:
            return NO_RIGHTS
        if scope == READ:
            return read_only
        if scope == WRITE and (category in ADMIN_CATEGORIES or obj in admin_keys):
            return read_only
        return FULL_RIGHTS

    return cap


def _route_template(request: Request) -> str:
    """The full template of the matched route (``/api/v2/objects/{type_name}/{dn}``).

    The route object may carry its path relative to the router it was declared on (the
    prefixes of the routers it was included through are not on it), so the prefix is taken
    back from the request path: render the template with the path parameters and strip it
    from the end of the path. When that fails the relative template is returned, which no
    rule matches (they are anchored at ``/api/v1`` or ``/api/v2``): refused.
    """
    route = request.scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not isinstance(template, str):
        return ""
    rendered = template
    for name, value in request.path_params.items():
        rendered = rendered.replace("{" + name + "}", str(value))
    path = str(request.scope.get("path", ""))
    if path.endswith(rendered):
        return path[: len(path) - len(rendered)] + template
    return template


def check_scope(request: Request, token: ApiToken) -> None:
    """Refuse (403 ``token_scope``) unless the route accepts this token."""
    template = _route_template(request)
    method = request.method.upper()
    rule = next(
        (r for r in RULES if method in r.methods and r.pattern.match(template)),
        None,
    )
    if rule is None:
        raise _refused("This endpoint does not accept API tokens")
    if not token.allows(rule.scope):
        raise _refused(f"This API token does not have the {rule.scope} scope")
    if token.types:
        params = request.path_params
        about = params.get("type_name") or params.get("type") or rule.implied_type
        if about is None:
            if not rule.any_type:
                raise _refused("This API token is limited to some object types")
        elif str(about) not in token.types:
            raise _refused(f"This API token cannot reach objects of type {about}")


def authenticate(request: Request, state: AppState) -> CurrentUser:
    """The owner of the request's token, after checking it may reach this route."""
    cached = request.scope.get(_SCOPE_KEY)
    if cached is not None:
        user, token = cached
        check_scope(request, token)
        return user
    if not state.settings.api_tokens.enabled:
        raise _invalid("API tokens are disabled")
    parsed = api_tokens.parse(bearer_value(request) or "")
    if parsed is None:
        raise _invalid("Malformed API token")
    token_id, secret = parsed
    token = state.api_tokens.get(token_id)
    if token is None or not api_tokens.verify(token, secret):
        raise _invalid("Invalid or revoked API token")
    now = state.clock()
    if token.expires_at <= now:
        raise _invalid("This API token has expired")
    directory = state.directories.get(token.directory_id)
    if directory is None:
        raise _invalid("Unknown directory")
    owner = directory.get(token.owner_dn, [STD_ATTR.USER_PASSWORD])
    if owner is None:
        raise _invalid("The owner of this API token no longer exists")
    stored = owner.text(STD_ATTR.USER_PASSWORD) or ""
    if stored and is_locked(stored):
        raise _invalid("The owner of this API token is locked")
    ip = client_ip(request, state)
    if token.last_used_at is None or now - token.last_used_at >= TOUCH_INTERVAL_SECONDS:
        try:
            state.api_tokens.touch(token.id, now, ip)
        except Exception:
            log.exception("api_token_touch_failed", token=token.id)
    session = Session(
        id=token_session_id(token.id),
        user_dn=token.owner_dn,
        directory_id=token.directory_id,
        created_at=token.created_at,
        last_seen=now,
        cache={TOKEN_KEY: token.id, _SCOPE_CACHE: token.scope, _TYPES_CACHE: list(token.types)},
    )
    user = CurrentUser(session, token.directory_id, directory, ip)
    request.scope[_SCOPE_KEY] = (user, token)
    via = AUDIT_VIA.get()
    if via is not None:  # the request's holder, set by the middleware: only a verified token
        via[0] = f"api token {token.id}"
    check_scope(request, token)
    return user


def token_guard(request: Request, state: StateDep) -> None:
    """Router dependency: a Bearer request is authenticated and scope-checked up front.

    Routes that never look at the user (sign-in, CSRF, …) are refused to tokens too.
    """
    if bearer_value(request) is not None:
        authenticate(request, state)


__all__ = [
    "RULES",
    "TOKEN_KEY",
    "authenticate",
    "check_scope",
    "is_token_session",
    "rights_cap",
    "token_guard",
]
