from __future__ import annotations

from heracles.core.references import ACL_ASSIGNMENT, dn_attributes, find_references
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.schema import names as schema

BASE = "dc=example,dc=com"
ALICE = f"uid=alice,ou=people,{BASE}"
ROLE = f"cn=ops,ou=roles,{BASE}"


def build() -> tuple[MemoryDirectory, TypeRegistry]:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"dcObject", b"organization"], "dc": [b"example"], "o": [b"x"]})
    for ou in ("people", "groups", "roles"):
        d.add(f"ou={ou},{BASE}", {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    d.add(
        ALICE,
        {"objectClass": [b"inetOrgPerson"], "uid": [b"alice"], "cn": [b"Alice"], "sn": [b"A"]},
    )
    d.add(
        f"uid=bob,ou=people,{BASE}",
        {
            "objectClass": [b"inetOrgPerson"],
            "uid": [b"bob"],
            "cn": [b"Bob"],
            "sn": [b"B"],
            "manager": [ALICE.upper().encode()],
        },
    )
    d.add(
        f"cn=staff,ou=groups,{BASE}",
        {"objectClass": [b"groupOfNames"], "cn": [b"staff"], "member": [ALICE.encode()]},
    )
    d.add(
        ROLE,
        {"objectClass": [b"organizationalRole"], "cn": [b"ops"], "roleOccupant": [ALICE.encode()]},
    )
    # entries that must never be reported
    d.add(
        f"ou=templates,ou=people,{BASE}",
        {"objectClass": [b"organizationalUnit"], "ou": [b"templates"]},
    )
    d.add(
        f"cn=t,ou=templates,ou=people,{BASE}",
        {
            "objectClass": [b"top", schema.OC.TEMPLATE.encode()],
            "cn": [b"t"],
            schema.TEMPLATE_FIELD_ATTR: [f"manager:{ALICE}".encode()],
        },
    )
    registry = TypeRegistry()
    register_builtin_types(registry)
    return d, registry


def test_dn_attributes_cover_registry_and_standard_names() -> None:
    _, registry = build()
    names = {n.lower() for n in dn_attributes(registry)}
    assert {"member", "roleoccupant", "manager", "owner", "uniquemember"} <= names


def test_find_references() -> None:
    d, registry = build()
    hits = find_references(d, registry, ALICE)
    assert [(h.type_name, h.label, h.attribute) for h in hits] == [
        ("group", "staff", "member"),
        ("role", "ops", "roleOccupant"),
        ("user", "Bob", "manager"),
    ]


def test_acl_assignment_is_reported() -> None:
    from heracles.acl import serialise_assignment
    from heracles.acl.model import AclAssignment, AclScope
    from heracles.ldap.client import Modification

    d, registry = build()
    value = serialise_assignment(
        AclAssignment(0, AclScope.SUBTREE, f"cn=r,ou=aclroles,{BASE}", (ROLE,))
    ).encode()
    d.modify(
        f"ou=groups,{BASE}",
        [
            Modification("add", "objectClass", [b"hrcDepartment"]),
            Modification("add", schema.ATTR.ACL_ENTRY, [value]),
        ],
    )
    hits = find_references(d, registry, ROLE)
    assert [(h.type_name, h.attribute) for h in hits] == [("department", ACL_ASSIGNMENT)]
