"""Helpers to make sure container entries exist."""

from __future__ import annotations

from heracles.ldap import dn as dnlib
from heracles.ldap.client import AlreadyExistsError, DirectoryClient, DirectoryError
from heracles.schema import legacy


def ensure_container(directory: DirectoryClient, container_dn: str) -> None:
    """Create ``container_dn`` and any missing ancestors below the base DN.

    Missing containers are created as ``organizationalUnit`` entries; the base
    DN itself must already exist.
    """
    base = directory.base_dn
    if not dnlib.is_descendant(container_dn, base):
        raise DirectoryError(f"{container_dn} is outside of {base}")
    parts = dnlib.split(container_dn)
    base_depth = dnlib.depth(base)
    for i in range(len(parts) - base_depth - 1, -1, -1):
        current = ",".join(parts[i:])
        if directory.get(current, ["objectClass"]) is not None:
            continue
        attr, _, value = parts[i].partition("=")
        if attr.strip().lower() != "ou":
            raise DirectoryError(f"cannot create container {current}: not an ou RDN")
        try:
            directory.add(
                current,
                {
                    legacy.STD_ATTR.OBJECT_CLASS: [legacy.STD_OC.ORGANIZATIONAL_UNIT.encode()],
                    legacy.STD_ATTR.OU: [value.strip().encode("utf-8")],
                },
            )
        except AlreadyExistsError:
            continue
