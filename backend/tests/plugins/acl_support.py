"""Helpers of the plugin tests that need a user holding given ACL rights."""

from __future__ import annotations

from heracles.acl import serialise_assignment
from heracles.acl.model import AclAssignment, AclScope
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.schema import names as schema

ACL_CLASSES = ("hrcAcl", "hrcAclRole")


def grant(directory: MemoryDirectory, base: str, member_dn: str, template: str) -> None:
    """Give ``member_dn`` the role ``template`` (``0:user/user;r``...) on the whole of ``base``.

    The directory must have been given the :data:`ACL_CLASSES` object classes.
    """
    role_dn = f"cn=author-role,{base}"
    directory.add(
        role_dn,
        {
            "objectClass": [schema.OC.ACL_ROLE.encode()],
            "cn": [b"author-role"],
            schema.ATTR.ACL_TEMPLATE: [template.encode()],
        },
    )
    value = serialise_assignment(AclAssignment(1, AclScope.SUBTREE, role_dn, (member_dn,))).encode()
    directory.modify(
        base,
        [
            Modification("add", "objectClass", [b"hrcAcl"]),
            Modification("add", schema.ATTR.ACL_ENTRY, [value]),
        ],
    )
