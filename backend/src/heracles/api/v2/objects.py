"""Object API v2: types metadata, listing, CRUD, locks, snapshots."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager  # pyright: ignore[reportDeprecated]
from typing import Annotated, Any, Literal, cast

import structlog
from fastapi import APIRouter, Body, Query, Response, status
from pydantic import BaseModel, Field

from heracles.acl import Rights
from heracles.api.deps import CurrentUserDep
from heracles.api.domain import DomainDep, TypeAclPolicy
from heracles.api.errors import ApiError, forbidden, not_found, validation
from heracles.attributes import JSON
from heracles.core import references
from heracles.core.config_store import effective_settings
from heracles.core.locks import Lock, LockedError
from heracles.core.snapshots import Snapshot, SnapshotError, SnapshotService
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Entry, NoSuchObjectError, Scope
from heracles.ldap.filter import escape_filter_value
from heracles.objects import (
    ObjectConflictError,
    ObjectNotFoundError,
    ObjectService,
    ObjectState,
    ObjectValidationError,
    PermissionDeniedError,
    UnknownTypeError,
    bulk,
    templates,
    transfer,
)
from heracles.objects.service import encode_cursor
from heracles.schema import names as schema

log = structlog.get_logger(__name__)

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


def _capabilities(info: Any) -> dict[str, JSON]:
    """Capability flags of a type (``creatable`` / ``editable`` / ``deletable``)."""
    return {
        "creatable": info.type.creatable,
        "editable": info.type.editable,
        "deletable": info.type.deletable,
    }


@router.get("/types")
def list_types(user: CurrentUserDep, domain: DomainDep) -> list[JSON]:
    base = user.directory.base_dn
    evaluator = domain.evaluator(user)

    def can_create(name: str) -> bool:
        info = domain.registry.get(name)
        if not info.type.creatable:
            return False
        return evaluator.permissions(base, info.acl_object(info.main_tab)).create

    return [
        {**t.summary(can_create=can_create(t.name)), **_capabilities(t)}
        for t in domain.registry.list()
    ]


@router.get("/types/{type_name}")
def describe_type(type_name: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, JSON]:
    del user
    with object_errors():
        body = domain.registry.describe(type_name)
        info = domain.registry.get(type_name)
    body.update(_capabilities(info))
    body["supports_templates"] = bool(body["supports_templates"]) and info.type.creatable
    return body


# ---------------------------------------------------------------- templates


class TemplateCreateBody(BaseModel):
    name: str
    base: str
    tabs: dict[str, TabPayload] = Field(default_factory=lambda: {})


class TemplatePatchBody(BaseModel):
    name: str | None = None
    tabs: dict[str, TabPayload] = Field(default_factory=lambda: {})


class TemplatePreviewBody(BaseModel):
    values: dict[str, dict[str, Any]] = Field(default_factory=lambda: {})


def _template_tabs(tabs: dict[str, TabPayload]) -> dict[str, Any]:
    """Template payloads only carry ``active`` when the client sent it for a tab."""
    return {
        name: {
            **({"active": tab.active} if "active" in tab.model_fields_set else {}),
            "values": tab.values,
        }
        for name, tab in tabs.items()
    }


@router.get("/types/{type_name}/templates")
def list_type_templates(
    type_name: str, user: CurrentUserDep, domain: DomainDep, base: str | None = None
) -> list[JSON]:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        found = templates.list_templates(service, type_name, base)
    return [t.to_json() for t in found]


@router.post("/types/{type_name}/templates", status_code=status.HTTP_201_CREATED)
def create_type_template(
    type_name: str, body: TemplateCreateBody, user: CurrentUserDep, domain: DomainDep
) -> dict[str, JSON]:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        tpl = templates.create_template(
            service, type_name, body.base, body.name, _template_tabs(body.tabs)
        )
        return templates.template_json(service, tpl)


@router.get("/types/{type_name}/templates/{dn:path}/fields")
def template_fields(
    type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep
) -> dict[str, JSON]:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        templates.get_template(service, type_name, dn)
        fields = templates.template_fields(service, type_name, dn)
    return {"fields": {tab: list(names) for tab, names in fields.items()}}


@router.post("/types/{type_name}/templates/{dn:path}/preview")
def preview_template(
    type_name: str,
    dn: str,
    body: TemplatePreviewBody,
    user: CurrentUserDep,
    domain: DomainDep,
) -> dict[str, JSON]:
    """Resolved values for the given field values, without storing anything."""
    with object_errors():
        service, _policy = domain.service(user, type_name)
        templates.get_template(service, type_name, dn)
        resolved = templates.apply_template(service, type_name, dn, body.values, preview=True)
    return {"tabs": {tab: dict(values) for tab, values in resolved.items()}}  # pyright: ignore[reportReturnType]


@router.get("/types/{type_name}/templates/{dn:path}")
def get_type_template(
    type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep
) -> dict[str, JSON]:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        return templates.template_json(service, templates.get_template(service, type_name, dn))


@router.patch("/types/{type_name}/templates/{dn:path}")
def patch_type_template(
    type_name: str, dn: str, body: TemplatePatchBody, user: CurrentUserDep, domain: DomainDep
) -> dict[str, JSON]:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        tpl = templates.update_template(
            service, type_name, dn, _template_tabs(body.tabs), body.name
        )
        return templates.template_json(service, tpl)


@router.delete("/types/{type_name}/templates/{dn:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_type_template(
    type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep
) -> Response:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        templates.delete_template(service, type_name, dn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
) -> dict[str, JSON]:
    with object_errors():
        if offset > 0 and cursor is None:
            cursor = encode_cursor(offset)
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
            extra_attrs=["userPassword"] if type_name == "user" else (),
            locked=_account_locked if type_name == "user" else None,
        )
    body = page.to_json()
    if type_name == "user":
        _count_groups(user, domain, body)
    return body


def _account_locked(entry: Entry) -> bool:
    """Account lock of a user row, from the password fetched with the listing."""
    from heracles.auth.passwords import is_locked

    stored = entry.text("userPassword")
    return bool(stored) and is_locked(stored or "")


def _count_groups(user: CurrentUserDep, domain: DomainDep, body: dict[str, JSON]) -> None:
    """Fill ``groups_count`` on user rows: groups of the page's users the caller may read.

    One search bounded by the page (``member`` equal to one of its DNs); groups the
    caller has no read right on are not counted, so the number reveals nothing more
    than the group list itself would.
    """
    raw = body.get("items")
    if not isinstance(raw, list):
        return
    items = [cast(dict[str, JSON], i) for i in raw if isinstance(i, dict)]
    dns = [dn for i in items if isinstance(dn := i.get("dn"), str)]
    if not dns:
        return
    info = domain.registry.get("group")
    acl_object = info.acl_object(info.main_tab)
    evaluator = domain.evaluator(user)
    members = "".join(f"(member={escape_filter_value(dn)})" for dn in dns)
    wanted = {dnlib.normalize(dn) for dn in dns}
    counts: dict[str, int] = {}
    for group in user.directory.search(
        user.directory.base_dn,
        f"(&(objectClass=groupOfNames)(|{members}))",
        Scope.SUBTREE,
        ["member"],
    ):
        if not evaluator.permissions(group.dn, acl_object).read:
            continue
        for member in group.texts("member"):
            key = dnlib.normalize(member)
            if key in wanted:
                counts[key] = counts.get(key, 0) + 1
    for item in items:
        dn = item.get("dn")
        if isinstance(dn, str):
            item["groups_count"] = counts.get(dnlib.normalize(dn), 0)


# --------------------------------------------------------------------- CRUD


class TabPayload(BaseModel):
    active: bool = True
    values: dict[str, Any] = Field(default_factory=lambda: {})


class CreateBody(BaseModel):
    base: str
    template: str | None = None
    tabs: dict[str, TabPayload] = Field(default_factory=lambda: {})


class PatchBody(BaseModel):
    tabs: dict[str, TabPayload]


class MoveBody(BaseModel):
    base: str


def _tabs_json(tabs: dict[str, TabPayload]) -> dict[str, Any]:
    return {name: tab.model_dump() for name, tab in tabs.items()}


@router.post("/objects/{type_name}", status_code=status.HTTP_201_CREATED)
def create_object(
    type_name: str, body: CreateBody, user: CurrentUserDep, domain: DomainDep
) -> dict[str, JSON]:
    with object_errors():
        service, _policy = domain.service(user, type_name)
        tabs = _tabs_json(body.tabs)
        if body.template is not None:
            tabs = _tabs_from_template(service, type_name, body.template, body.tabs)
        new_dn = service.create(type_name, body.base, tabs)
    return _with_event_output(user, domain, {"dn": new_dn})


def _snapshot_service(user: CurrentUserDep, domain: DomainDep) -> SnapshotService:
    """Snapshot service honouring the directory-stored snapshot settings."""
    config = effective_settings(user.directory)
    service = domain.snapshots(user.directory_id, user.directory)
    service.snapshot_base = config.snapshot_base or dnlib.join(
        schema.RDN.SNAPSHOTS, user.directory.base_dn
    )
    return service


def _prune_snapshots(user: CurrentUserDep, service: SnapshotService) -> None:
    """Apply the configured retention after a new snapshot was taken."""
    config = effective_settings(user.directory)
    try:
        service.prune(config.snapshot_retention_days or 0, config.snapshot_min_retention or 0)
    except (NoSuchObjectError, SnapshotError):
        log.warning("snapshot_prune_failed", exc_info=True)


def _with_event_output(
    user: CurrentUserDep, domain: DomainDep, payload: dict[str, JSON]
) -> dict[str, JSON]:
    """Add the trigger output the events of this request collected ("show hook output")."""
    warnings, messages = domain.collected(user)
    if warnings:
        payload["warnings"] = cast(JSON, warnings)
    if messages:
        payload["messages"] = cast(JSON, messages)
    return payload


class BulkBody(BaseModel):
    dns: list[str]
    changes: dict[str, dict[str, dict[str, Any]]]


class BulkSelection(BaseModel):
    dns: list[str]


@router.post("/objects/{type_name}/_bulk/attributes")
def bulk_attributes(
    type_name: str, body: BulkSelection, user: CurrentUserDep, domain: DomainDep
) -> dict[str, JSON]:
    """Attributes editable on every selected object, by tab."""
    with object_errors():
        service, _policy = domain.service(user, type_name)
        found = bulk.editable_attributes(service, type_name, body.dns)
    return {"attributes": {tab: list(names) for tab, names in found.items()}}


@router.patch("/objects/{type_name}/_bulk")
def bulk_edit(
    type_name: str, body: BulkBody, user: CurrentUserDep, domain: DomainDep
) -> dict[str, JSON]:
    """Apply the same change to several objects; failures do not abort the others."""
    locks = domain.locks(user.directory_id, user.directory)

    def is_locked(dn: str) -> bool:
        lock = locks.get(dn)
        return lock is not None and dnlib.normalize(lock.user_dn) != dnlib.normalize(user.dn)

    with object_errors():
        service, _policy = domain.service(user, type_name)
        results = bulk.bulk_update(service, type_name, body.dns, body.changes, is_locked=is_locked)
    return {"results": [r.to_json() for r in results]}


def _tabs_from_template(
    service: ObjectService, type_name: str, template: str, given: dict[str, TabPayload]
) -> dict[str, Any]:
    """Resolve ``template`` with the values of the request (they win over the template)."""
    supplied = {name: payload.values for name, payload in given.items() if payload.active}
    resolved = templates.apply_template(service, type_name, template, supplied)
    tabs: dict[str, Any] = {
        name: {"active": True, "values": values} for name, values in resolved.items()
    }
    for name, payload in given.items():
        if not payload.active:
            tabs[name] = {"active": False, "values": {}}
    return tabs


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


class CopyBody(BaseModel):
    base: str
    values: dict[str, dict[str, Any]] = Field(default_factory=lambda: {})


@router.post("/objects/{type_name}/{dn:path}/copy", status_code=status.HTTP_201_CREATED)
def copy_object(
    type_name: str, dn: str, body: CopyBody, user: CurrentUserDep, domain: DomainDep
) -> dict[str, str]:
    """Copy an object to another department (read on the source, create on the target)."""
    with object_errors():
        service, policy = domain.service(user, type_name)
        service.load(type_name, dn)
        if not policy.can_read(dn, domain.registry.get(type_name).main_tab.name, ""):
            raise PermissionDeniedError(f"cannot read {dn}")
        new_dn = transfer.copy_object(service, type_name, dn, body.base, body.values)
    return {"dn": new_dn}


@router.get("/objects/{type_name}/{dn:path}/references")
def object_references(
    type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep
) -> list[JSON]:
    """Objects that refer to this one (membership, manager, ACL assignments, ...)."""
    with object_errors():
        service, policy = domain.service(user, type_name)
        service.load(type_name, dn)
        if not policy.can_read(dn, domain.registry.get(type_name).main_tab.name, ""):
            raise PermissionDeniedError(f"cannot read {dn}")
        hits = references.find_references(user.directory, domain.registry, dn)
        out: list[JSON] = []
        policies: dict[str, TypeAclPolicy] = {}
        for hit in hits:
            hit_policy = policies.get(hit.type_name)
            if hit_policy is None:
                hit_policy = policies[hit.type_name] = domain.service(user, hit.type_name)[1]
            main = domain.registry.get(hit.type_name)
            if not hit_policy.can_read(hit.dn, main.main_tab.name, main.type.main_attr):
                continue
            out.append(
                {
                    "dn": hit.dn,
                    "type": hit.type_name,
                    "label": hit.label,
                    "attribute": hit.attribute,
                }
            )
    return out


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
    config = effective_settings(user.directory)
    if not config.snapshots_enabled:
        raise forbidden("Snapshots are disabled in the configuration")
    snapshots = _snapshot_service(user, domain)
    snap = snapshots.create(
        dn, object_type=type_name, description=(body.description if body else "") or None
    )
    _prune_snapshots(user, snapshots)
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


@router.get("/snapshots/deleted")
def list_deleted_snapshots(
    user: CurrentUserDep,
    domain: DomainDep,
    type: str | None = None,
    base: str | None = None,
) -> list[dict[str, JSON]]:
    """Latest snapshot of each object that no longer exists (restorable ones only)."""
    evaluator = domain.evaluator(user)
    found: list[dict[str, JSON]] = []
    for snap in domain.snapshots(user.directory_id, user.directory).list_deleted(base):
        if snap.object_type is None or (type is not None and snap.object_type != type):
            continue
        try:
            info = domain.registry.get(snap.object_type)
        except UnknownTypeError:
            continue
        if evaluator.can_snapshot_restore(snap.object_dn, info.acl_object(info.main_tab)):
            found.append(snapshot_json(snap))
    return found


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
        return _with_event_output(user, domain, object_json(service, policy, state))


@router.delete("/objects/{type_name}/{dn:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_object(type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep) -> Response:
    _check_not_locked_by_other(domain, user, dn)
    with object_errors():
        service, _policy = domain.service(user, type_name)
        service.delete(type_name, dn)
    domain.locks(user.directory_id, user.directory).release(dn, user.dn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
