"""Tree builder for DHCP configuration and section hierarchies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles_plugins.dhcp.validation import (
    ALLOWED_CHILDREN_BY_CLASS,
    TYPE_BY_CLASS,
    find_dhcp_class,
)


def build_dhcp_tree(
    directory: DirectoryClient,
    root_dn: str,
    can_read: Callable[[str, str], bool] | None = None,
) -> list[dict[str, Any]]:
    """Build a nested tree of DHCP sections rooted at ``root_dn``.

    ``can_read(dn, type_name)`` filters the sections: an unreadable section is left
    out together with everything below it (an unreadable root gives an empty tree).

    Returns ``[{dn, type, label, allowed_children: [...], children: [...]}]``
    or an empty list if ``root_dn`` does not exist or is not a DHCP section.
    """
    try:
        root_entry = directory.get(root_dn)
    except NoSuchObjectError:
        return []
    if root_entry is None:
        return []

    root_oc = find_dhcp_class(root_entry)
    if root_oc is None:
        return []

    try:
        entries = list(directory.search(root_dn, "(objectClass=*)", Scope.SUBTREE))
    except NoSuchObjectError:
        return []

    nodes: dict[str, dict[str, Any]] = {}
    for entry in entries:
        oc = find_dhcp_class(entry)
        if oc is None:
            continue
        type_name = TYPE_BY_CLASS[oc.lower()]
        if can_read is not None and not can_read(entry.dn, type_name):
            continue
        allowed_classes = ALLOWED_CHILDREN_BY_CLASS.get(oc, frozenset())
        allowed_children = sorted(TYPE_BY_CLASS[c.lower()] for c in allowed_classes)
        node: dict[str, Any] = {
            "dn": entry.dn,
            "type": type_name,
            "label": entry.text("cn") or entry.dn,
            "allowed_children": allowed_children,
            "children": [],
        }
        nodes[dnlib.normalize(entry.dn)] = node

    norm_root = dnlib.normalize(root_dn)
    if norm_root not in nodes:
        return []

    # Sort entries by depth to connect child nodes to parents
    for entry in sorted(entries, key=lambda e: dnlib.depth(e.dn)):
        key = dnlib.normalize(entry.dn)
        if key == norm_root or key not in nodes:
            continue
        parent_dn = dnlib.normalize(dnlib.parent(entry.dn) or "")
        if parent_dn in nodes:
            nodes[parent_dn]["children"].append(nodes[key])

    def _child_key(child: dict[str, Any]) -> tuple[str, str]:
        return (str(child.get("label", "")).lower(), str(child.get("dn", "")))

    # Deterministically sort children by label and DN
    for node in nodes.values():
        children_list: list[dict[str, Any]] = node["children"]
        children_list.sort(key=_child_key)
    return [nodes[norm_root]]
