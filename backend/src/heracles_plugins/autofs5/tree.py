"""Tree builder for autofs5 automount maps and entries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope


def build_autofs_tree(
    directory: DirectoryClient,
    root_dn: str,
    can_read: Callable[[str, str], bool] | None = None,
) -> list[dict[str, Any]]:
    """Build a tree of automount maps and their entries rooted at ``root_dn``.

    ``can_read(dn, type_name)`` filters the entries: an unreadable entry is omitted.
    """
    try:
        root_entry = directory.get(root_dn)
    except NoSuchObjectError:
        return []
    if root_entry is None:
        return []

    try:
        entries = list(directory.search(root_dn, "(objectClass=*)", Scope.SUBTREE))
    except NoSuchObjectError:
        return []

    maps: dict[str, dict[str, Any]] = {}
    automount_entries: list[dict[str, Any]] = []

    for entry in entries:
        classes = {c.lower() for c in entry.texts("objectClass")}
        if "automountmap" in classes:
            if can_read is not None and not can_read(entry.dn, "automountMap"):
                continue
            label = entry.text("ou") or entry.text("automountMapName") or entry.dn
            maps[dnlib.normalize(entry.dn)] = {
                "dn": entry.dn,
                "type": "automountMap",
                "label": label,
                "description": entry.text("description") or "",
                "allowed_children": ["automount"],
                "children": [],
            }
        elif "automount" in classes:
            if can_read is not None and not can_read(entry.dn, "automount"):
                continue
            key = entry.text("automountKey") or entry.text("cn") or entry.dn
            automount_entries.append(
                {
                    "dn": entry.dn,
                    "parent_dn": dnlib.normalize(dnlib.parent(entry.dn) or ""),
                    "type": "automount",
                    "label": key,
                    "information": entry.text("automountInformation") or "",
                    "description": entry.text("description") or "",
                    "allowed_children": [],
                    "children": [],
                }
            )

    # Attach automount entries to their parent maps
    for child in automount_entries:
        parent_norm = child.pop("parent_dn")
        if parent_norm in maps:
            maps[parent_norm]["children"].append(child)

    norm_root = dnlib.normalize(root_dn)
    if norm_root in maps:
        return [maps[norm_root]]
    return list(maps.values())
