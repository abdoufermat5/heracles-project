"""Find the objects that reference a DN (membership, manager, ACL assignments, ...)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from heracles.acl.model import AclAssignment
from heracles.acl.parser import parse_assignment
from heracles.attributes import AnyAttribute, ListAttr, ObjectRefAttr
from heracles.ldap import dn as dnlib
from heracles.ldap import filter as ldapfilter
from heracles.ldap.client import DirectoryClient, Entry, NoSuchObjectError, Scope
from heracles.objects import filters
from heracles.objects.registry import TypeInfo, TypeRegistry
from heracles.schema import names as schema

#: Standard DN-valued attributes searched in addition to the registry's.
STANDARD_DN_ATTRIBUTES = (
    "member",
    "uniqueMember",
    "roleOccupant",
    "manager",
    "owner",
    "seeAlso",
    "secretary",
)
#: Name under which ACL assignments are reported (they are embedded in a longer value).
ACL_ASSIGNMENT = "acl_assignment"

_SKIPPED_CLASSES = (schema.OC.SNAPSHOT, schema.OC.LOCK, schema.OC.TEMPLATE, schema.OC.TOKEN)


@dataclass(frozen=True, slots=True)
class ReferenceHit:
    """``dn`` (of ``type_name``) refers to the target through ``attribute``."""

    dn: str
    type_name: str
    label: str
    attribute: str


def dn_attributes(registry: TypeRegistry) -> list[str]:
    """Names of every attribute known to hold DNs (registry plus standard ones)."""
    names: dict[str, str] = {}
    for name in STANDARD_DN_ATTRIBUTES:
        names.setdefault(name.lower(), name)
    for info in registry.list():
        for ref in info.type.references:
            names.setdefault(ref.attr.lower(), ref.attr)
        for tab in info.tabs:
            for attr in tab.attributes():
                if _holds_dn(attr) and attr.stored:
                    names.setdefault(attr.name.lower(), attr.name)
    return list(names.values())


def _holds_dn(attr: AnyAttribute) -> bool:
    if isinstance(attr, ObjectRefAttr):
        return True
    if isinstance(attr, ListAttr):
        return isinstance(cast("AnyAttribute", attr.item), ObjectRefAttr)  # pyright: ignore[reportUnknownMemberType]
    return False


def _type_of(registry: TypeRegistry, entry: Entry) -> TypeInfo | None:
    for info in registry.list():
        if ldapfilter.matches(entry, info.type.filter):
            return info
    return None


def _label(info: TypeInfo, entry: Entry) -> str:
    for attr in (info.type.name_attr, info.type.main_attr):
        text = entry.text(attr) if attr else None
        if text:
            return text
    return dnlib.rdn(entry.dn).partition("=")[2]


def find_references(
    directory: DirectoryClient, registry: TypeRegistry, target_dn: str
) -> list[ReferenceHit]:
    """Every entry (of a registered type) that mentions ``target_dn``, with the attribute.

    Edit locks, snapshots, tokens and templates are never reported. The caller
    filters the result with the read ACLs.
    """
    attrs = dn_attributes(registry)
    escaped = filters.escape_filter_value(target_dn)
    clauses = [f"({a}={escaped})" for a in attrs]
    clauses.append(f"({schema.ATTR.ACL_ENTRY}=*)")  # DNs are encoded inside the values
    try:
        entries = list(directory.search(directory.base_dn, filters.or_(clauses), Scope.SUBTREE))
    except NoSuchObjectError:
        return []
    wanted = dnlib.normalize(target_dn)
    hits: list[ReferenceHit] = []
    for entry in entries:
        if dnlib.normalize(entry.dn) == wanted or any(
            entry.has_object_class(c) for c in _SKIPPED_CLASSES
        ):
            continue
        found = _matched_attributes(entry, attrs, wanted, target_dn)
        if not found:
            continue
        info = _type_of(registry, entry)
        if info is None:
            continue
        label = _label(info, entry)
        hits.extend(ReferenceHit(entry.dn, info.name, label, a) for a in found)
    return sorted(hits, key=lambda h: (h.type_name, h.label.lower(), h.attribute))


def _matched_attributes(
    entry: Entry, attrs: Iterable[str], wanted: str, target_dn: str
) -> list[str]:
    found: list[str] = []
    for attr in attrs:
        if any(dnlib.normalize(v) == wanted for v in entry.texts(attr)):
            found.append(attr)
    for value in entry.texts(schema.ATTR.ACL_ENTRY):
        parsed = parse_assignment(value)
        if isinstance(parsed, AclAssignment) and wanted in {
            dnlib.normalize(d) for d in (parsed.role_dn, *parsed.members) if d != "*"
        }:
            found.append(ACL_ASSIGNMENT)
            break
    return found


__all__ = [
    "ACL_ASSIGNMENT",
    "STANDARD_DN_ATTRIBUTES",
    "ReferenceHit",
    "dn_attributes",
    "find_references",
]
