"""Directory-wide API v2 routes: department tree, account lock, second factors, dashboard."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import structlog
from fastapi import APIRouter
from webauthn import base64url_to_bytes
from webauthn.helpers import bytes_to_base64url

from heracles.api.deps import CurrentUserDep, StateDep
from heracles.api.domain import DomainDep
from heracles.api.errors import forbidden, not_found, validation
from heracles.attributes import JSON
from heracles.auth.passwords import is_locked, lock, unlock
from heracles.auth.second_factor import SecondFactorSummary
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Modification, NoSuchObjectError, Scope
from heracles.objects import ObjectValidationError, UnknownTypeError
from heracles.objects.policy import EventContext
from heracles.schema.legacy import OC

router = APIRouter(tags=["directory"])
log = structlog.get_logger(__name__)

#: ACL attribute protecting the account lock action (compatibility key).
USER_LOCK_ACL = "userLock"
#: ACL attribute protecting the administrators' view and reset of second factors.
SECOND_FACTOR_ACL = "secondFactor"


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
        try:
            user.directory.modify(dn, changes)
        finally:
            domain.invalidate_listings(user)
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


# ---------------------------------------------------------- second factors


def _second_factor_target(user: CurrentUserDep, domain: DomainDep, dn: str, *, write: bool) -> bool:
    """Check the right on a user's second factors; return whether the caller may reset them.

    Reading needs the read right on the ``secondFactor`` pseudo-attribute, resetting the write
    right. Nobody resets their own factors here: that skips the step-up of the self-service
    endpoints.
    """
    info = domain.registry.get("user")
    evaluator = domain.evaluator(user)
    key = info.acl_object(info.main_tab)
    can_write = evaluator.can_write_attr(dn, key, SECOND_FACTOR_ACL)
    if write and not can_write:
        raise forbidden("You cannot reset the second factors of this account")
    if not write and not (can_write or evaluator.can_read_attr(dn, key, SECOND_FACTOR_ACL)):
        raise forbidden("You cannot view the second factors of this account")
    if write and dnlib.normalize(dn) == dnlib.normalize(user.dn):
        raise forbidden("Manage your own second factors from your account page")
    entry = user.directory.get(dn, ["objectClass"])
    if entry is None or not entry.has_object_class("inetOrgPerson"):
        raise not_found("User not found")
    return can_write and dnlib.normalize(dn) != dnlib.normalize(user.dn)


def _describe(summary: SecondFactorSummary) -> list[bytes]:
    items: list[str] = []
    if summary.totp:
        items.append("authenticator app")
    items.extend(f"security key: {c.label or 'unnamed'}" for c in summary.security_keys)
    if summary.recovery_codes:
        items.append(f"recovery codes: {summary.recovery_codes}")
    return [i.encode() for i in items]


def _record_reset(
    user: CurrentUserDep, domain: DomainDep, dn: str, removed: SecondFactorSummary
) -> None:
    """Log the reset and hand it to the audit events (when the audit plugin is enabled)."""
    what = [v.decode() for v in _describe(removed)]
    log.warning("second_factor_reset", actor=user.dn, target=dn, removed=what)
    change = Modification("delete", SECOND_FACTOR_ACL, _describe(removed))
    domain.events(user).post_second_factor_reset(
        EventContext(type_name="user", dn=dn, changes=[change])
    )


@router.get("/users/{dn:path}/second-factors")
def second_factors(dn: str, user: CurrentUserDep, domain: DomainDep, state: StateDep) -> JSON:
    """What a user has registered, never the secrets themselves."""
    can_reset = _second_factor_target(user, domain, dn, write=False)
    summary = state.second_factor.summary(dn)
    return {
        "totp": summary.totp,
        "security_keys": [
            {"id": bytes_to_base64url(c.credential_id), "label": c.label}
            for c in summary.security_keys
        ],
        "recovery_codes": summary.recovery_codes,
        "can_reset": can_reset,
    }


@router.delete("/users/{dn:path}/second-factors/webauthn/{credential_id}", status_code=204)
def remove_security_key(
    dn: str, credential_id: str, user: CurrentUserDep, domain: DomainDep, state: StateDep
) -> None:
    _second_factor_target(user, domain, dn, write=True)
    try:
        raw = base64url_to_bytes(credential_id)
    except ValueError:
        raise not_found() from None
    found = [c for c in state.webauthn.credentials(dn) if c.credential_id == raw]
    if not found or not state.webauthn.remove_credential(dn, raw):
        raise not_found("Security key not found")
    _record_reset(user, domain, dn, SecondFactorSummary(False, (found[0],), 0))


@router.delete("/users/{dn:path}/second-factors", status_code=204)
def reset_second_factors(dn: str, user: CurrentUserDep, domain: DomainDep, state: StateDep) -> None:
    """Remove the authenticator, security keys and recovery codes of a user."""
    _second_factor_target(user, domain, dn, write=True)
    removed = state.second_factor.reset(dn)
    _record_reset(user, domain, dn, removed)


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
        service, policy = domain.service(user, name)
        if name == "user":
            # one search gives both the readable users and the locked accounts
            total = 0
            main_tab, main_attr = info.main_tab.name, info.type.main_attr
            try:
                for entry in directory.search(
                    base, info.type.filter, Scope.SUBTREE, ["userPassword"]
                ):
                    if policy.can_read(entry.dn, main_tab, main_attr):
                        total += 1
                    stored = entry.text("userPassword")
                    if stored and is_locked(stored):
                        locked_users += 1
            except NoSuchObjectError:
                pass
        else:
            total = service.count(name, base, Scope.SUBTREE)
        cards.append(
            {
                "key": name,
                "label": info.type.label_plural or info.type.label,
                "value": total,
                "trend": None,
            }
        )
    return {
        "cards": cards,
        "locked_users": locked_users,
        "expiring_passwords": 0,
        "tasks": {"pending": 0, "failed": 0},
    }
