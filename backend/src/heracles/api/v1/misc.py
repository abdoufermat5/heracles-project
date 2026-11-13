"""v1 user lock, archive and password recovery endpoints."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Response, status
from pydantic import BaseModel, Field

from heracles.api.deps import StateDep
from heracles.api.domain import DomainDep
from heracles.api.errors import ApiError, forbidden, not_found
from heracles.api.v1.common import V1Route, V1UserDep
from heracles.api.v1.convert import bad_request
from heracles.api.v1.names import resolve_type
from heracles.api.v2 import directory as v2_directory
from heracles.api.v2.objects import object_errors
from heracles.auth.passwords import PasswordPolicyError, is_locked
from heracles.auth.recovery import RecoveryError
from heracles.ldap.client import NoSuchObjectError
from heracles.objects import PermissionDeniedError

router = APIRouter(route_class=V1Route)


# -- user lock --------------------------------------------------------------------------------
@router.get(
    "/userlock/{dn}",
    tags=["objects"],
    summary="Get lock state of a user",
    operation_id="getLockState",
)
def get_lock_state(dn: str, user: V1UserDep, domain: DomainDep) -> bool:
    info = domain.registry.get("user")
    evaluator = domain.evaluator(user)
    if not evaluator.can_read_attr(dn, info.acl_object(info.main_tab), v2_directory.USER_LOCK_ACL):
        raise forbidden("You cannot read the lock state of this account")
    entry = user.directory.get(dn, ["userPassword", "objectClass"])
    if entry is None or not entry.has_object_class("inetOrgPerson"):
        raise not_found("User not found")
    return is_locked(entry.text("userPassword") or "")


@router.put(
    "/userlock/{dn}",
    tags=["objects"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set lock state of a user",
    operation_id="setLockState",
)
def set_lock_state(
    dn: str, body: Annotated[bool, Body()], user: V1UserDep, domain: DomainDep
) -> Response:
    if body:
        v2_directory.lock_account(dn, user, domain)
    else:
        v2_directory.unlock_account(dn, user, domain)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- archive ----------------------------------------------------------------------------------
@router.post(
    "/archive/{type}/{dn}",
    tags=["objects"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive an object (delete it)",
    operation_id="archiveObject",
)
def archive_object(type: str, dn: str, user: V1UserDep, domain: DomainDep) -> Response:
    if "archive" not in domain.registry.settings:
        raise ApiError(501, "not_implemented", "The archive plugin is not available")
    service_module = importlib.import_module("heracles_plugins.archive")
    settings: Any = domain.registry.settings["archive"]
    with object_errors():
        info = resolve_type(domain.registry, type)
        service, policy = domain.service(user, info.name)
        service.load(info.name, dn)
        if not policy.can_delete(dn, info.name):
            raise PermissionDeniedError(f"cannot archive {dn}")
    if not settings.archive_on_delete:
        # With ``archive_on_delete`` the delete hook archives the object by itself.

        def can_read(attr: str) -> bool:
            tab = next((t for t in info.tabs if t.attribute(attr) is not None), info.main_tab)
            return policy.can_read(dn, tab.name, attr)

        try:
            service_module.archive(
                user.directory,
                dn,
                info.name,
                settings=settings,
                now=datetime.now(UTC),
                can_read=can_read,
            )
        except NoSuchObjectError:
            raise not_found(f"Object not found: {dn}") from None
        except service_module.ArchiveError as exc:
            raise bad_request(str(exc)) from exc
    with object_errors():
        service.delete(info.name, dn)
    domain.locks(user.directory_id, user.directory).release(dn, user.dn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- recovery ---------------------------------------------------------------------------------
class RecoveryRequest(BaseModel):
    """Body of ``PUT /recovery``."""

    token: Annotated[str, Field(description="Recovery token")]
    login: Annotated[str, Field(description="The login of the user")]
    password1: Annotated[str, Field(description="First password entered by the user")]
    password2: Annotated[str, Field(description="Second password entered by the user")]


class RecoveryResponse(BaseModel):
    token: Annotated[str, Field(description="Recovery token")]
    login: Annotated[str, Field(description="The login of the user")]


@router.get(
    "/recovery",
    tags=["recovery"],
    summary="Generate recovery token for a user",
    operation_id="getRecoveryToken",
)
def get_recovery_token(
    email: Annotated[str, Query(description="The email address of the user")],
    user: V1UserDep,
    state: StateDep,
    domain: DomainDep,
) -> RecoveryResponse:
    if not state.settings.recovery.enabled:
        raise not_found("Password recovery is disabled")
    match = state.recovery.find(user.directory, email)
    if match is None:
        raise not_found("No account matches this email address")
    # A token lets its bearer choose the account password: only callers who may set the
    # password of this very account are allowed to mint one.
    info = domain.registry.get("user")
    _service, policy = domain.service(user, info.name)
    tab = next((t for t in info.tabs if t.attribute("userPassword") is not None), info.main_tab)
    if not policy.can_write(match[0], tab.name, "userPassword"):
        raise forbidden("You cannot reset the password of this account")
    issued = state.recovery.issue(user.directory, email)
    if issued is None:
        raise not_found("No account matches this email address")
    return RecoveryResponse(token=issued[0], login=issued[1])


@router.put(
    "/recovery",
    tags=["recovery"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change a user password using a recovery token",
    operation_id="confirmRecoveryPasswordChange",
)
def confirm_recovery(body: RecoveryRequest, user: V1UserDep, state: StateDep) -> Response:
    if not state.settings.recovery.enabled:
        raise not_found("Password recovery is disabled")
    if body.password1 != body.password2:
        raise bad_request("The two passwords do not match")
    try:
        target = state.recovery.confirm(user.directory, body.login, body.token, body.password1)
    except PasswordPolicyError as exc:
        raise bad_request("Password rejected: " + "; ".join(exc.problems)) from None
    except RecoveryError:
        raise bad_request("Invalid or expired recovery token") from None
    # A reset is what people do when the account may be compromised: whoever holds a
    # session of it must not keep it (same as API v2).
    state.sessions.delete_for_user(target)
    state.audit.record_by(
        user,
        "password",
        object_type="user",
        object_dn=target,
        attributes=["password: reset with a recovery token"],
        source="api v1",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
