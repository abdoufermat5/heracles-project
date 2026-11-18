"""Authorisation of a snapshot restore, attribute by attribute.

A restore writes the stored entries back as they are: passwords, ACL assignments, group
memberships. The ``restore`` right on the snapshot only says the caller may start one; what
the restore changes must still be something the caller could change by hand. So every
attribute that differs between the live subtree and the snapshot needs the write right on
that attribute (as the object routes require), an ACL assignment or role template that
differs must not grant more than the caller may grant, and entries the restore drops need
the delete right. Bootstrap administrators ignore the ACLs, here as elsewhere.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from heracles.acl import admin as acl_admin
from heracles.api.deps import CurrentUser
from heracles.api.domain import Domain
from heracles.api.errors import forbidden
from heracles.core.snapshots import RestorePlan
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Entry
from heracles.objects import TypeInfo
from heracles.schema import names as schema


def _classes(entry: Entry) -> set[str]:
    return {v.decode("utf-8", "replace").lower() for v in entry.get("objectClass")}


def _type_of(domain: Domain, entry: Entry, fallback: TypeInfo) -> TypeInfo:
    """The most specific registered type whose main object classes the entry carries."""
    held = _classes(entry)
    best = fallback
    size = -1
    for info in domain.registry.list():
        wanted = {c.lower() for c in info.main_tab.object_classes}
        if wanted and wanted <= held and len(wanted) > size:
            best, size = info, len(wanted)
    return best


def _values(entry: Entry | None, name: str) -> set[bytes]:
    return set(entry.get(name)) if entry is not None else set()


def _names(entry: Entry | None) -> dict[str, str]:
    return {k.lower(): k for k in entry.attrs} if entry is not None else {}


def _text(entry: Entry | None, name: str) -> list[str]:
    return [v.decode("utf-8", "replace") for v in entry.get(name)] if entry is not None else []


def restore_authorizer(
    domain: Domain, user: CurrentUser, root_type: TypeInfo
) -> Callable[[RestorePlan], None]:
    """Check for :meth:`SnapshotService.restore`: refuses (403) what the caller could not write."""
    evaluator = domain.evaluator(user)

    def check(plan: RestorePlan) -> None:
        if evaluator.ignore_acl:
            return
        kept: set[str] = set()
        for record in plan.records:
            ndn = dnlib.normalize(record.dn)
            kept.add(ndn)
            current = plan.live.get(ndn)
            info = _type_of(domain, record, root_type)
            names = {**_names(current), **_names(record)}
            for lowered, name in names.items():
                if lowered == "objectclass":
                    continue
                if _values(current, name) == _values(record, name):
                    continue
                _check_attribute(domain, user, info, record.dn, name)
            _check_grants(domain, user, record, current)
        for ndn, gone in plan.live.items():
            if ndn in kept:
                continue
            info = _type_of(domain, gone, root_type)
            key = info.acl_object(info.main_tab)
            if not evaluator.permissions(gone.dn, key).delete:
                raise forbidden(f"Restoring would delete {gone.dn}, which you cannot delete")

    return check


def _check_attribute(domain: Domain, user: CurrentUser, info: TypeInfo, dn: str, name: str) -> None:
    keys = {info.acl_object(t) for t in info.tabs if t.attribute(name) is not None}
    if not keys:  # an attribute no tab manages needs the right on the object itself
        keys = {info.acl_object(info.main_tab)}
    evaluator = domain.evaluator(user)
    for key in sorted(keys):
        if not evaluator.can_write_attr(dn, key, name):
            raise forbidden(f"Restoring would change {name} of {dn}, which you cannot write")


def _check_grants(domain: Domain, user: CurrentUser, record: Entry, current: Entry | None) -> None:
    evaluator = domain.evaluator(user)
    entry_attr = schema.ATTR.ACL_ENTRY
    template_attr = schema.ATTR.ACL_TEMPLATE
    missing: Collection[str] = []
    saved = _text(record, entry_attr)
    stored = _text(current, entry_attr)
    if saved != stored:
        missing = acl_admin.unheld_grants(
            user.directory, stored, saved, at=record.dn, delegable=evaluator.delegable
        )
    if not missing:
        saved = _text(record, template_attr)
        stored = _text(current, template_attr)
        if saved != stored:
            missing = acl_admin.unheld_template_grants(
                user.directory, record.dn, stored, saved, delegable=evaluator.delegable
            )
    if missing:
        raise forbidden(
            "Restoring would grant rights you do not hold: " + ", ".join(sorted(missing))
        )
