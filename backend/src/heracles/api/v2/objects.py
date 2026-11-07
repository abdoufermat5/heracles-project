"""Object API v2: types metadata, listing, CRUD, locks, snapshots."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager  # pyright: ignore[reportDeprecated]
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query, Response, status
from pydantic import BaseModel, Field

from heracles.acl import Rights
from heracles.api.deps import CurrentUserDep
from heracles.api.domain import DomainDep, TypeAclPolicy
from heracles.api.errors import ApiError, forbidden, not_found, validation
from heracles.attributes import JSON
from heracles.core.locks import Lock, LockedError
from heracles.core.snapshots import Snapshot, SnapshotError
from heracles.ldap import dn as dnlib
from heracles.ldap.client import NoSuchObjectError, Scope
from heracles.objects import (
    ObjectConflictError,
    ObjectNotFoundError,
    ObjectService,
    ObjectState,
    ObjectValidationError,
    PermissionDeniedError,
    UnknownTypeError,
)

router = APIRouter(tags=["objects"])


# ----------------------------------------------------------------- helpers


@contextmanager  # pyright: ignore[reportDeprecated]
def object_errors() -> Iterator[None]:
    """Translate object-layer errors into API errors."""
    try:
        yield
    except UnknownTypeError as exc:
        raise not_found(f"Unknown object type: {exc}") from exc
    except ObjectNotFoundError as exc:
        raise not_found(f"Object not found: {exc}") from exc
    except NoSuchObjectError as exc:
        raise not_found(f"Object not found: {exc}") from exc
    except ObjectValidationError as exc:
        raise validation("Some fields are invalid", exc.fields) from exc
    except PermissionDeniedError as exc:
        raise forbidden(str(exc)) from exc
    except ObjectConflictError as exc:
        raise ApiError(409, "conflict", str(exc)) from exc
    except LockedError as exc:
        raise locked_error(exc.lock) from exc


def lock_json(lock: Lock) -> dict[str, JSON]:
    return {"user": lock.user_dn, "since": lock.acquired_at.isoformat()}


def locked_error(lock: Lock) -> ApiError:
    return ApiError(
        409,
        "locked",
        "This object is being edited by another user",
        extra={"lock": lock_json(lock)},
    )


def rights_str(rights: Rights) -> str:
    return rights.without_self().canonical()


def object_json(
    service: ObjectService, policy: TypeAclPolicy, state: ObjectState
) -> dict[str, JSON]:
    """``GET /objects/{type}/{dn}`` body: values plus the per-tab ``acl`` block."""
    body = service.state_json(state)
    info = service.registry.get(state.type_name)
    acl: dict[str, JSON] = {}
    for tab in info.tabs:
        object_rights, attributes = policy.tab_rights(state.dn, tab)
        acl[tab.name] = {
            "object": rights_str(object_rights),
            "attributes": {name: rights_str(r) for name, r in attributes.items()},
        }
    body["acl"] = acl
    return body


def _check_not_locked_by_other(domain: DomainDep, user: CurrentUserDep, dn: str) -> None:
    lock = domain.locks(user.directory_id, user.directory).get(dn)
    if lock is not None and dnlib.normalize(lock.user_dn) != dnlib.normalize(user.dn):
        raise locked_error(lock)


# --------------------------------------------------------------- metadata


@router.get("/types")
def list_types(user: CurrentUserDep, domain: DomainDep) -> list[JSON]:
    base = user.directory.base_dn
    evaluator = domain.evaluator(user)

    def can_create(name: str) -> bool:
        info = domain.registry.get(name)
        return evaluator.permissions(base, info.acl_object(info.main_tab)).create

    return list(domain.registry.summaries(can_create=can_create))


@router.get("/types/{type_name}")
def describe_type(type_name: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, JSON]:
    del user
    with object_errors():
        return domain.registry.describe(type_name)


# ------------------------------------------------------------------ listing


@router.get("/objects/{type_name}")
def list_objects(
    type_name: str,
    user: CurrentUserDep,
    domain: DomainDep,
    base: str | None = None,
    scope: Literal["one", "sub"] = "one",
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    cursor: str | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
) -> dict[str, JSON]:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        page = service.list(
            type_name,
            base or user.directory.base_dn,
            Scope.SUBTREE if scope == "sub" else Scope.ONE,
            q,
            limit,
            cursor,
            sort=sort,
            descending=order == "desc",
        )
    body = page.to_json()
    if type_name == "user":
        _mark_locked_accounts(user, body)
    return body


def _mark_locked_accounts(user: CurrentUserDep, body: dict[str, JSON]) -> None:
    """Fill ``locked`` (account lock) on user rows."""
    from heracles.auth.passwords import is_locked

    items = body.get("items")
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        dn = item.get("dn")
        if not isinstance(dn, str):
            continue
        entry = user.directory.get(dn, ["userPassword"])
        stored = entry.text("userPassword") if entry is not None else None
        item["locked"] = bool(stored) and is_locked(stored or "")


# --------------------------------------------------------------------- CRUD


class TabPayload(BaseModel):
    active: bool = True
    values: dict[str, Any] = Field(default_factory=lambda: {})


class CreateBody(BaseModel):
    base: str
    template: str | None = None
    tabs: dict[str, TabPayload]


class PatchBody(BaseModel):
    tabs: dict[str, TabPayload]


class MoveBody(BaseModel):
    base: str


def _tabs_json(tabs: dict[str, TabPayload]) -> dict[str, Any]:
    return {name: tab.model_dump() for name, tab in tabs.items()}


@router.post("/objects/{type_name}", status_code=status.HTTP_201_CREATED)
def create_object(
    type_name: str, body: CreateBody, user: CurrentUserDep, domain: DomainDep
) -> dict[str, str]:
    if body.template is not None:
        raise ApiError(501, "not_implemented", "Templates are not supported yet")
    with object_errors():
        service, _policy = domain.service(user, type_name)
        new_dn = service.create(type_name, body.base, _tabs_json(body.tabs))
    return {"dn": new_dn}


@router.post("/objects/{type_name}/{dn:path}/lock")
def acquire_lock(
    type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep
) -> dict[str, JSON]:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        service.load(type_name, dn)
        lock = domain.locks(user.directory_id, user.directory).acquire(dn, user.dn)
    return {"lock": lock_json(lock)}


@router.delete("/objects/{type_name}/{dn:path}/lock", status_code=status.HTTP_204_NO_CONTENT)
def release_lock(type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep) -> Response:
    del type_name
    domain.locks(user.directory_id, user.directory).release(dn, user.dn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/objects/{type_name}/{dn:path}/move")
def move_object(
    type_name: str, dn: str, body: MoveBody, user: CurrentUserDep, domain: DomainDep
) -> dict[str, str]:
    _check_not_locked_by_other(domain, user, dn)
    with object_errors():
        service, policy = domain.service(user, type_name)
        service.load(type_name, dn)
        if not policy.can_move(dn) or not policy.can_create(type_name, body.base):
            raise PermissionDeniedError(f"cannot move {dn} to {body.base}")
        info = domain.registry.get(type_name)
        superior = dnlib.join(info.type.rdn, body.base)
        new_dn = user.directory.rename(dn, dnlib.rdn(dn), superior)
    return {"dn": new_dn}


@router.get("/objects/{type_name}/{dn:path}/snapshots")
def list_snapshots(
    type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep
) -> list[dict[str, JSON]]:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        service.load(type_name, dn)
    snaps = domain.snapshots(user.directory_id, user.directory).list_for_dn(dn)
    return [snapshot_json(s) for s in snaps]


class SnapshotBody(BaseModel):
    description: str = ""


@router.post("/objects/{type_name}/{dn:path}/snapshots", status_code=status.HTTP_201_CREATED)
def create_snapshot(
    type_name: str,
    dn: str,
    user: CurrentUserDep,
    domain: DomainDep,
    body: Annotated[SnapshotBody | None, Body()] = None,
) -> dict[str, JSON]:
    with object_errors():
        info = domain.registry.get(type_name)
        service, _policy = domain.service(user, type_name)
        service.load(type_name, dn)
        if not domain.evaluator(user).can_snapshot_create(dn, info.acl_object(info.main_tab)):
            raise PermissionDeniedError(f"cannot snapshot {dn}")
    snap = domain.snapshots(user.directory_id, user.directory).create(
        dn, object_type=type_name, description=(body.description if body else "") or None
    )
    return snapshot_json(snap)


def snapshot_json(snap: Snapshot) -> dict[str, JSON]:
    created = snap.created_at
    return {
        "id": snap.dn,
        "object_dn": snap.object_dn,
        "type": snap.object_type,
        "description": snap.description,
        "created_at": created.isoformat() if created else None,
        "source": snap.source,
    }


def _snapshot_type_and_key(domain: DomainDep, snap: Snapshot) -> str:
    if snap.object_type is None:
        raise forbidden("Snapshot has no object type")
    with object_errors():
        info = domain.registry.get(snap.object_type)
    return info.acl_object(info.main_tab)


@router.post("/snapshots/{snapshot_id:path}/restore")
def restore_snapshot(snapshot_id: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, JSON]:
    snapshots = domain.snapshots(user.directory_id, user.directory)
    snap = snapshots.get(snapshot_id)
    if snap is None:
        raise not_found("Snapshot not found")
    key = _snapshot_type_and_key(domain, snap)
    if not domain.evaluator(user).can_snapshot_restore(snap.object_dn, key):
        raise forbidden("Cannot restore this snapshot")
    _check_not_locked_by_other(domain, user, snap.object_dn)
    try:
        restored = snapshots.restore(snapshot_id)
    except SnapshotError as exc:
        raise ApiError(409, "conflict", str(exc)) from exc
    return {"dn": snap.object_dn, "restored": list(restored)}


@router.delete("/snapshots/{snapshot_id:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_snapshot(snapshot_id: str, user: CurrentUserDep, domain: DomainDep) -> Response:
    snapshots = domain.snapshots(user.directory_id, user.directory)
    snap = snapshots.get(snapshot_id)
    if snap is None:
        raise not_found("Snapshot not found")
    key = _snapshot_type_and_key(domain, snap)
    if not domain.evaluator(user).can_snapshot_delete(snap.object_dn, key):
        raise forbidden("Cannot delete this snapshot")
    snapshots.delete(snapshot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/objects/{type_name}/{dn:path}")
def get_object(type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, JSON]:
    with object_errors():
        service, policy = domain.service(user, type_name)
        state = service.load(type_name, dn)
        if not policy.can_read(dn, domain.registry.get(type_name).main_tab.name, ""):
            raise PermissionDeniedError(f"cannot read {dn}")
        return object_json(service, policy, state)


@router.patch("/objects/{type_name}/{dn:path}")
def patch_object(
    type_name: str, dn: str, body: PatchBody, user: CurrentUserDep, domain: DomainDep
) -> dict[str, JSON]:
    _check_not_locked_by_other(domain, user, dn)
    with object_errors():
        service, policy = domain.service(user, type_name)
        state = service.update(type_name, dn, _tabs_json(body.tabs))
        if dnlib.normalize(state.dn) != dnlib.normalize(dn):
            locks = domain.locks(user.directory_id, user.directory)
            locks.release(dn, user.dn)
        return object_json(service, policy, state)


@router.delete("/objects/{type_name}/{dn:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_object(type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep) -> Response:
    _check_not_locked_by_other(domain, user, dn)
    with object_errors():
        service, _policy = domain.service(user, type_name)
        service.delete(type_name, dn)
    domain.locks(user.directory_id, user.directory).release(dn, user.dn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
