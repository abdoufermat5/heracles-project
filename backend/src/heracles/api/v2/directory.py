"""Directory-wide API v2 routes: department tree, account lock, dashboard."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from fastapi import APIRouter

from heracles.api.deps import CurrentUserDep
from heracles.api.domain import DomainDep
from heracles.api.errors import forbidden, not_found, validation
from heracles.attributes import JSON
from heracles.auth.passwords import is_locked, lock, unlock
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Modification, NoSuchObjectError, Scope
from heracles.objects import ObjectValidationError, UnknownTypeError
from heracles.objects.policy import EventContext
from heracles.schema.legacy import OC

router = APIRouter(tags=["directory"])

#: ACL attribute protecting the account lock action (compatibility key).
USER_LOCK_ACL = "userLock"

_KIND_BY_ATTR = {"ou": "ou", "o": "o", "l": "l", "c": "c", "dc": "dc"}


# ------------------------------------------------------------------- tree


@router.get("/tree")
def department_tree(user: CurrentUserDep, domain: DomainDep) -> list[dict[str, JSON]]:
    """Departments readable by the user, as a tree rooted at the base."""
    directory = user.directory
    base = directory.base_dn
    try:
        entries = list(directory.search(base, f"(objectClass={OC.DEPARTMENT})", Scope.SUBTREE))
    except NoSuchObjectError:
        entries = []
    evaluator = domain.evaluator(user)
    categories = list(domain.category_tabs())
    dns = [e.dn for e in entries]
    visible = {
        dnlib.normalize(d)
        for category in categories
        for d in evaluator.departments_for(category, dns)
    }
    # keep ancestors of visible departments so the tree stays connected
    for d in list(visible):
        parent = dnlib.parent(d)
        while parent is not None and dnlib.is_descendant(parent, base, include_self=False):
            visible.add(dnlib.normalize(parent))
            parent = dnlib.parent(parent)

    nodes: dict[str, dict[str, JSON]] = {}
    root: dict[str, JSON] = {
        "dn": base,
        "label": _label(dnlib.rdn(base)),
        "kind": _kind(dnlib.rdn(base)),
        "children": [],
    }
    nodes[dnlib.normalize(base)] = root
    for entry in sorted(entries, key=lambda e: dnlib.depth(e.dn)):
        key = dnlib.normalize(entry.dn)
        if key == dnlib.normalize(base) or key not in visible:
            continue
        node: dict[str, JSON] = {
            "dn": entry.dn,
            "label": _label(dnlib.rdn(entry.dn)),
            "kind": _kind(dnlib.rdn(entry.dn)),
            "children": [],
        }
        nodes[key] = node
        parent_dn = dnlib.parent(entry.dn)
        parent = None
        while parent_dn is not None:
            parent = nodes.get(dnlib.normalize(parent_dn))
            if parent is not None:
                break
            parent_dn = dnlib.parent(parent_dn)
        children = (parent or root)["children"]
        assert isinstance(children, list)
        children.append(node)
    for node in nodes.values():
        children = node["children"]
        assert isinstance(children, list)
        children.sort(key=lambda n: str(n["label"]).lower() if isinstance(n, dict) else "")
    return [root]


def _label(rdn: str) -> str:
    return rdn.partition("=")[2].replace("\\", "")


def _kind(rdn: str) -> str:
    return _KIND_BY_ATTR.get(rdn.partition("=")[0].strip().lower(), "ou")


# ----------------------------------------------------------- account lock


@contextmanager  # pyright: ignore[reportDeprecated]
def _trigger_errors() -> Iterator[None]:
    """A failing ``pre*`` trigger aborts the operation with its output."""
    try:
        yield
    except ObjectValidationError as exc:
        raise validation("The change was refused", exc.fields) from exc


def _set_account_lock(
    user: CurrentUserDep, domain: DomainDep, dn: str, locked: bool
) -> dict[str, JSON]:
    info = domain.registry.get("user")
    evaluator = domain.evaluator(user)
    if not evaluator.can_write_attr(dn, info.acl_object(info.main_tab), USER_LOCK_ACL):
        raise forbidden("You cannot lock or unlock this account")
    entry = user.directory.get(dn)
    if entry is None or not entry.has_object_class("inetOrgPerson"):
        raise not_found("User not found")
    stored = entry.text("userPassword") or ""
    new = lock(stored) if locked else unlock(stored)
    changes: list[Modification] = []
    if new != stored:
        if new:
            changes.append(Modification("replace", "userPassword", [new.encode()]))
        else:
            changes.append(Modification("delete", "userPassword"))
    for hook in domain.registry.account_lock_hooks:
        changes.extend(hook(entry, locked))
    service, _policy = domain.service(user, "user")
    events = domain.events(user)
    before = service.load("user", dn)
    pre = EventContext(type_name="user", dn=dn, before=before, after=before, changes=changes)
    with _trigger_errors():
        (events.pre_lock if locked else events.pre_unlock)(pre)
    if changes:
        user.directory.modify(dn, changes)
    after = service.load("user", dn)
    post = EventContext(type_name="user", dn=dn, before=before, after=after, changes=changes)
    (events.post_lock if locked else events.post_unlock)(post)
    warnings, messages = domain.collected(user)
    result: dict[str, JSON] = {"dn": dn, "locked": is_locked(new)}
    if warnings:
        result["warnings"] = cast(JSON, warnings)
    if messages:
        result["messages"] = cast(JSON, messages)
    return result


@router.post("/users/{dn:path}/lock")
def lock_account(dn: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, JSON]:
    return _set_account_lock(user, domain, dn, True)


@router.post("/users/{dn:path}/unlock")
def unlock_account(dn: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, JSON]:
    return _set_account_lock(user, domain, dn, False)


# -------------------------------------------------------------- dashboard


_DASHBOARD_TYPES = ("user", "group", "role", "department")


@router.get("/dashboard")
def dashboard(user: CurrentUserDep, domain: DomainDep) -> dict[str, JSON]:
    directory = user.directory
    base = directory.base_dn
    cards: list[JSON] = []
    locked_users = 0
    for name in _DASHBOARD_TYPES:
        try:
            info = domain.registry.get(name)
        except UnknownTypeError:
            continue
        service, _policy = domain.service(user, name)
        page = service.list(name, base, Scope.SUBTREE, limit=1)
        cards.append(
            {
                "key": name,
                "label": info.type.label_plural or info.type.label,
                "value": page.total,
                "trend": None,
            }
        )
        if name == "user":
            try:
                for entry in directory.search(
                    base, info.type.filter, Scope.SUBTREE, ["userPassword"]
                ):
                    stored = entry.text("userPassword")
                    if stored and is_locked(stored):
                        locked_users += 1
            except NoSuchObjectError:
                pass
    return {
        "cards": cards,
        "locked_users": locked_users,
        "expiring_passwords": 0,
        "tasks": {"pending": 0, "failed": 0},
    }
