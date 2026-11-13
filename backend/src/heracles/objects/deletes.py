"""Drop references to deleted entries (spec 05, lifecycle).

Deleting an object (or a department and its subtree) leaves the DN in every attribute
that pointed at it — group members, role occupants, managers, ACL assignment members and
roles — and those references would dangle (worse, a new object created at the same DN
would silently inherit them). :func:`propagate` removes them after the delete: the
:func:`subtree_dns` list of the removed entries is read before, the references are
rewritten after.

An attribute the entry's type declares mandatory (``member`` of a group) is never
emptied: the value is kept and a warning is logged, so the entry is not left invalid.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import structlog

from heracles.acl.model import AclAssignment
from heracles.acl.parser import parse_assignment, serialise_assignment
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry, Modification, Scope
from heracles.objects import filters
from heracles.objects.registry import TypeInfo, TypeRegistry
from heracles.schema import names as schema

log = structlog.get_logger(__name__)

#: DNs matched by one search (keeps the filter small after deleting a whole department).
_CHUNK = 20


def _rewrite_assignment(value: str, gone: set[str]) -> str | None:
    """The assignment without the deleted role or members, or ``None`` to drop it."""
    parsed = parse_assignment(value)
    if not isinstance(parsed, AclAssignment):
        return None  # unparseable values are kept untouched
    if dnlib.normalize(parsed.role_dn) in gone:
        return ""  # the role no longer exists
    members = tuple(m for m in parsed.members if m == "*" or dnlib.normalize(m) not in gone)
    if members == parsed.members:
        return None
    if not members:
        return ""
    return serialise_assignment(
        AclAssignment(
            parsed.index,
            parsed.scope,
            parsed.role_dn,
            members,
            parsed.user_filter,
            parsed.target_filter,
        )
    )


def _required(info: TypeInfo | None, attribute: str) -> bool:
    """True when the entry's type declares ``attribute`` mandatory."""
    if info is None:
        return False
    found = info.find_attribute(attribute)
    return found is not None and found.required


def _dn_modifications(
    entry: Entry, attrs: Sequence[str], gone: set[str], info: TypeInfo | None
) -> list[Modification]:
    mods: list[Modification] = []
    for attr in attrs:
        values = entry.texts(attr)
        removed = [v for v in values if dnlib.normalize(v) in gone]
        if not removed:
            continue
        kept = [v for v in values if dnlib.normalize(v) not in gone]
        if not kept and _required(info, attr):
            log.warning(
                "reference_to_deleted_object_kept",
                dn=entry.dn,
                attribute=attr,
                value=removed[0],
                detail="the attribute is mandatory for this entry",
            )
            continue
        mods.append(Modification("replace", attr, [v.encode("utf-8") for v in kept]))
    return mods


def _acl_modifications(entry: Entry, gone: set[str]) -> list[Modification]:
    values = entry.texts(schema.ATTR.ACL_ENTRY)
    if not values:
        return []
    rewritten: list[str] = []
    for value in values:
        new = _rewrite_assignment(value, gone)
        if new is None:
            rewritten.append(value)
        elif new:
            rewritten.append(new)
    if rewritten == values:
        return []
    mods: list[Modification] = []
    if rewritten:
        mods.append(
            Modification("replace", schema.ATTR.ACL_ENTRY, [v.encode("utf-8") for v in rewritten])
        )
    else:
        # an entry with no assignment left must not keep the auxiliary class that demands one
        mods.append(Modification("delete", schema.ATTR.ACL_ENTRY))
        mods.append(Modification("delete", "objectClass", [schema.OC.ACL_ASSIGNMENT.encode()]))
    return mods


def _apply(
    directory: DirectoryClient,
    registry: TypeRegistry,
    holders: Mapping[str, Entry],
    attrs: Sequence[str],
    gone: set[str],
) -> None:
    from heracles.core.references import type_of

    for holder in holders.values():
        mods = [
            *_dn_modifications(holder, attrs, gone, type_of(registry, holder)),
            *_acl_modifications(holder, gone),
        ]
        if not mods:
            continue
        try:
            directory.modify(holder.dn, mods)
        except DirectoryError as exc:
            log.warning("reference_cleanup_failed", dn=holder.dn, error=type(exc).__name__)


def propagate(
    directory: DirectoryClient,
    registry: TypeRegistry,
    deleted_dns: Sequence[str],
) -> None:
    """Remove references to ``deleted_dns`` (call :func:`subtree_dns` before the delete)."""
    from heracles.core.references import dn_attributes

    if not deleted_dns:
        return
    gone = {dnlib.normalize(d) for d in deleted_dns}
    attrs = dn_attributes(registry)
    base = directory.base_dn
    wanted = ["objectClass", *attrs, schema.ATTR.ACL_ENTRY]
    holders: dict[str, Entry] = {}
    for start in range(0, len(deleted_dns), _CHUNK):
        chunk = list(deleted_dns[start : start + _CHUNK])
        clauses = [filters.equals(a, d) for d in chunk for a in attrs]
        try:
            found = list(directory.search(base, filters.or_(clauses), Scope.SUBTREE, wanted))
        except DirectoryError:
            continue
        holders.update({dnlib.normalize(e.dn): e for e in found})
    # ACL assignments hold the DNs base64 encoded: one pass over the entries carrying them.
    try:
        carriers = list(
            directory.search(base, f"({schema.ATTR.ACL_ENTRY}=*)", Scope.SUBTREE, wanted)
        )
    except DirectoryError:
        carriers = []
    holders.update({dnlib.normalize(e.dn): e for e in carriers})
    holders = {k: e for k, e in holders.items() if k not in gone}
    _apply(directory, registry, holders, attrs, gone)


__all__ = ["propagate"]
