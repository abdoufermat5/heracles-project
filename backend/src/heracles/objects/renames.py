"""Keep DN references in step when an entry is renamed or moved (spec 05, lifecycle step 3).

Renaming an object or moving it to another department changes its DN, and the DN of every
entry below it. Groups, roles, managers, ACL assignments and the other DN-valued attributes
that pointed at the old DNs would dangle (and a later object created at an old DN would
silently inherit them). :func:`subtree_dns` is read before the rename, :func:`propagate`
rewrites the references after it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

import structlog

from heracles.acl.model import AclAssignment
from heracles.acl.parser import parse_assignment, serialise_assignment
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry, Modification, Scope
from heracles.objects import filters
from heracles.objects.registry import TypeRegistry
from heracles.schema import names as schema

log = structlog.get_logger(__name__)

#: DNs matched by one search (keeps the filter small when a whole department moves).
_CHUNK = 20


def subtree_dns(directory: DirectoryClient, dn: str) -> list[str]:
    """``dn`` and the DNs of its descendants (read before a rename)."""
    try:
        found = [e.dn for e in directory.search(dn, "(objectClass=*)", Scope.SUBTREE, ["1.1"])]
    except DirectoryError:
        found = []
    if not any(dnlib.normalize(d) == dnlib.normalize(dn) for d in found):
        found.insert(0, dn)
    return found


def _moved(old_dns: Sequence[str], old_root: str, new_root: str) -> dict[str, str]:
    """Normalised old DN -> new DN for the renamed entry and everything below it."""
    depth = dnlib.depth(old_root)
    out: dict[str, str] = {}
    for old in old_dns:
        relative = dnlib.split(old)[: dnlib.depth(old) - depth]
        out[dnlib.normalize(old)] = (
            dnlib.join(",".join(relative), new_root) if relative else new_root
        )
    return out


def _rewrite_values(values: Sequence[str], mapping: Mapping[str, str]) -> list[str] | None:
    """``values`` with the moved DNs replaced, or ``None`` when none of them is moved."""
    changed = False
    out: list[str] = []
    for value in values:
        target = mapping.get(dnlib.normalize(value))
        if target is not None:
            changed = True
            out.append(target)
        else:
            out.append(value)
    return out if changed else None


def _rewrite_assignment(value: str, mapping: Mapping[str, str]) -> str | None:
    parsed = parse_assignment(value)
    if not isinstance(parsed, AclAssignment):
        return None  # unparseable values are kept untouched
    role = mapping.get(dnlib.normalize(parsed.role_dn), parsed.role_dn)
    members = tuple(m if m == "*" else mapping.get(dnlib.normalize(m), m) for m in parsed.members)
    if role == parsed.role_dn and members == parsed.members:
        return None
    return serialise_assignment(replace(parsed, role_dn=role, members=members))


def _modifications(
    entry: Entry, attributes: Sequence[str], mapping: Mapping[str, str]
) -> list[Modification]:
    mods: list[Modification] = []
    for attr in attributes:
        rewritten = _rewrite_values(entry.texts(attr), mapping)
        if rewritten is not None:
            mods.append(Modification("replace", attr, [v.encode("utf-8") for v in rewritten]))
    acl_values = entry.texts(schema.ATTR.ACL_ENTRY)
    new_values = [_rewrite_assignment(v, mapping) or v for v in acl_values]
    if new_values != acl_values:
        mods.append(
            Modification("replace", schema.ATTR.ACL_ENTRY, [v.encode("utf-8") for v in new_values])
        )
    return mods


def _apply(
    directory: DirectoryClient,
    holders: Sequence[Entry],
    attrs: Sequence[str],
    mapping: Mapping[str, str],
) -> None:
    for holder in holders:
        mods = _modifications(holder, attrs, mapping)
        if not mods:
            continue
        try:
            directory.modify(holder.dn, mods)
        except DirectoryError as exc:
            log.warning("reference_rewrite_failed", dn=holder.dn, error=type(exc).__name__)


def propagate(
    directory: DirectoryClient,
    registry: TypeRegistry,
    old_dns: Sequence[str],
    old_root: str,
    new_root: str,
) -> None:
    """Rewrite every reference to ``old_dns`` (a renamed subtree) after the rename.

    ``old_dns`` comes from :func:`subtree_dns` called before the rename. Standard and
    registered DN attributes and the ACL assignments (roles and members) are updated.
    """
    # imported here: heracles.core.references imports heracles.objects, which imports this module
    from heracles.core.references import dn_attributes

    mapping = _moved(old_dns, old_root, new_root)
    attrs = dn_attributes(registry)
    base = directory.base_dn
    wanted = [*attrs, schema.ATTR.ACL_ENTRY]
    for start in range(0, len(old_dns), _CHUNK):
        chunk = list(old_dns[start : start + _CHUNK])
        clauses = [filters.equals(a, d) for d in chunk for a in attrs]
        try:
            holders = list(directory.search(base, filters.or_(clauses), Scope.SUBTREE, wanted))
        except DirectoryError:
            continue
        _apply(directory, holders, attrs, mapping)
    # ACL assignments hold the DNs base64 encoded: one pass over the entries carrying them.
    try:
        carriers = list(
            directory.search(base, f"({schema.ATTR.ACL_ENTRY}=*)", Scope.SUBTREE, wanted)
        )
    except DirectoryError:
        return
    _apply(directory, carriers, [], mapping)


__all__ = ["propagate", "subtree_dns"]
