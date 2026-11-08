"""Copy an object to another department."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from heracles.attributes import DepartmentAttr, DisplayAttr
from heracles.objects.service import ObjectService

#: Attributes that identify one object: never copied (the user must supply them).
UNIQUE_ATTRIBUTES = frozenset(
    {"uid", "uidnumber", "gidnumber", "mail", "employeenumber", "macaddress", "iphostnumber"}
)


def copy_object(
    service: ObjectService,
    type_name: str,
    dn: str,
    base: str,
    values: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """Create a copy of ``dn`` in department ``base`` and return its DN.

    Every active tab is copied with the values the user may read. The naming
    attribute, the unique attributes (:data:`UNIQUE_ATTRIBUTES` plus the tabs'
    ``unique_attributes``), passwords and computed or virtual attributes are left
    out; ``values`` (``{tab: {attribute: json}}``) supplies them. Required ones
    that are missing make the creation fail with a validation error.
    """
    info = service.registry.get(type_name)
    state = service.load(type_name, dn)
    tabs: dict[str, Any] = {}
    for tab in info.tabs:
        tab_state = state.tabs[tab.name]
        if not tab_state.active:
            if not tab.optional:
                tabs[tab.name] = {"active": True, "values": {}}
            continue
        skipped = {a.lower() for a in tab.unique_attributes} | UNIQUE_ATTRIBUTES
        skipped.add(info.type.main_attr.lower())
        copied: dict[str, Any] = {}
        for attr in tab.attributes():
            if (
                not attr.stored
                or attr.write_only
                or isinstance(attr, DisplayAttr | DepartmentAttr)
                or attr.name.lower() in skipped
                or attr.name not in tab_state.values
            ):
                continue
            copied[attr.name] = attr.to_json(tab_state.values[attr.name])
        tabs[tab.name] = {"active": True, "values": copied}
    for tab_name, attrs in (values or {}).items():
        entry = tabs.setdefault(tab_name, {"active": True, "values": {}})
        entry["values"].update(attrs)
    return service.create(type_name, base, tabs)


__all__ = ["UNIQUE_ATTRIBUTES", "copy_object"]
