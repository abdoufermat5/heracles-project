"""Pure diff computation: object state change -> one LDAP modification list."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from heracles.ldap.client import Modification
from heracles.objects.model import Tab
from heracles.objects.state import TabState

OBJECT_CLASS = "objectClass"


def _raw(raw: Mapping[str, Sequence[bytes]], name: str) -> list[bytes]:
    lname = name.lower()
    for key, values in raw.items():
        if key.lower() == lname:
            return list(values)
    return []


def diff_modifications(
    tabs: Sequence[type[Tab]],
    main_attr: str,
    raw: Mapping[str, Sequence[bytes]],
    object_classes: Sequence[str],
    original: Mapping[str, TabState],
    new: Mapping[str, TabState],
) -> list[Modification]:
    """Compute the modifications turning the entry described by ``original`` into ``new``.

    The result is meant for a single ``modify``: objectClass additions first, then
    attribute changes (tab order), then objectClass removals. The RDN attribute is
    never included (it changes through a rename). Write-only attributes are
    written only when their new value is not ``None``.
    """
    present = {c.lower() for c in object_classes}
    active = [t for t in tabs if new[t.name].active]
    claimed_classes = {c.lower() for t in active for c in t.object_classes}
    active_attrs = {a.name.lower() for t in active for a in t.attributes()}

    oc_add: list[bytes] = []
    oc_del: list[bytes] = []
    attr_mods: list[Modification] = []
    skip = {main_attr.lower(), OBJECT_CLASS.lower()}

    for tab in tabs:
        old_state = original.get(tab.name, TabState())
        new_state = new[tab.name]
        if new_state.active:
            for oc in tab.object_classes:
                if oc.lower() not in present and oc.encode() not in oc_add:
                    oc_add.append(oc.encode())
            for attr in tab.attributes():
                if (
                    not attr.stored
                    or attr.name.lower() in skip
                    or attr.name not in new_state.values
                ):
                    continue
                value = new_state.values[attr.name]
                if attr.write_only:
                    if value is None:
                        continue
                elif old_state.active and value == old_state.values.get(attr.name):
                    continue
                new_raw = attr.to_ldap(value)
                old_raw = _raw(raw, attr.name)
                if not new_raw:
                    if old_raw:
                        attr_mods.append(Modification("delete", attr.name))
                elif sorted(new_raw) != sorted(old_raw):
                    attr_mods.append(Modification("replace", attr.name, new_raw))
        elif old_state.active:
            for attr in tab.attributes():
                lname = attr.name.lower()
                if not attr.stored or lname in skip or lname in active_attrs:
                    continue
                if _raw(raw, attr.name):
                    attr_mods.append(Modification("delete", attr.name))
            for oc in tab.object_classes:
                lname = oc.lower()
                if lname in present and lname not in claimed_classes and oc.encode() not in oc_del:
                    oc_del.append(oc.encode())

    mods: list[Modification] = []
    if oc_add:
        mods.append(Modification("add", OBJECT_CLASS, oc_add))
    mods.extend(attr_mods)
    if oc_del:
        mods.append(Modification("delete", OBJECT_CLASS, oc_del))
    return mods
