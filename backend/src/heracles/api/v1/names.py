"""Mapping layer between API v1 names and Heracles descriptors.

API v1 addresses

* a **type** by an upper-case identifier (``USER``, ``OGROUP``...; case-insensitive on input,
  the Heracles name is accepted too);
* a **tab** by its ACL object key (the part after ``<category>/`` of
  :meth:`TypeInfo.acl_object`), e.g. ``user``, ``posixAccount``, ``personalInfo``;
* an **attribute** by its LDAP attribute name (case-insensitive).

Two tabs of one type may share an ACL key; the later ones are exposed as
``<key>_<heracles tab name>`` so that the mapping stays bijective.
"""

from __future__ import annotations

from dataclasses import dataclass

from heracles.attributes import AnyAttribute
from heracles.objects import TypeInfo, TypeRegistry
from heracles.objects.errors import UnknownTypeError
from heracles.objects.model import Tab

#: v1 identifiers that differ from ``name.upper()``.
_TYPE_IDS: dict[str, str] = {
    "group": "OGROUP",
    "department_o": "ORGANIZATION",
    "department_l": "LOCALITY",
    "department_c": "COUNTRY",
    "department_dc": "DCOBJECT",
    "acl_role": "ACLROLE",
    "acl_assignment": "ACLASSIGNMENT",
}
#: Extra spellings accepted on input.
_TYPE_ALIASES: dict[str, str] = {"domain": "department_dc", "domain_component": "department_dc"}


def type_id(info: TypeInfo) -> str:
    """The v1 identifier of a registered type."""
    return _TYPE_IDS.get(info.name, info.name.upper())


def resolve_type(registry: TypeRegistry, name: str) -> TypeInfo:
    """Type from a v1 identifier or a Heracles name (case-insensitive)."""
    wanted = name.strip().lower()
    wanted = _TYPE_ALIASES.get(wanted, wanted)
    for info in registry.list():
        if type_id(info).lower() == wanted or info.name.lower() == wanted:
            return info
    raise UnknownTypeError(name)


@dataclass(frozen=True, slots=True)
class V1Tab:
    """A tab together with its v1 name."""

    name: str
    tab: type[Tab]


def v1_tabs(info: TypeInfo) -> list[V1Tab]:
    """The tabs of ``info`` in order, with unique v1 names."""
    out: list[V1Tab] = []
    seen: set[str] = set()
    for tab in info.tabs:
        key = info.acl_object(tab).partition("/")[2]
        name = key if key.lower() not in seen else f"{key}_{tab.name}"
        seen.add(name.lower())
        out.append(V1Tab(name, tab))
    return out


def find_tab(info: TypeInfo, name: str) -> V1Tab | None:
    """Tab by v1 name (case-insensitive); the Heracles tab name is accepted as a fallback."""
    tabs = v1_tabs(info)
    wanted = name.lower()
    for item in tabs:
        if item.name.lower() == wanted:
            return item
    for item in tabs:
        if item.tab.name.lower() == wanted:
            return item
    return None


def v1_tab_name(info: TypeInfo, tab_name: str) -> str:
    """v1 name of the tab called ``tab_name`` in Heracles."""
    for item in v1_tabs(info):
        if item.tab.name == tab_name:
            return item.name
    return tab_name


def heracles_tab_name(info: TypeInfo, name: str) -> str | None:
    found = find_tab(info, name)
    return found.tab.name if found else None


def find_attribute(tab: type[Tab], name: str) -> AnyAttribute | None:
    """Attribute of ``tab`` by LDAP name (case-insensitive)."""
    exact = tab.attribute(name)
    if exact is not None:
        return exact
    wanted = name.lower()
    return next((a for a in tab.attributes() if a.name.lower() == wanted), None)


def locate_attribute(info: TypeInfo, name: str) -> tuple[type[Tab], AnyAttribute] | None:
    """First tab owning the attribute called ``name``, with the attribute."""
    for tab in info.tabs:
        attr = find_attribute(tab, name)
        if attr is not None:
            return tab, attr
    return None
