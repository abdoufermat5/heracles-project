"""References to a deleted entry are dropped (spec 05, lifecycle)."""

from __future__ import annotations

from structlog.testing import capture_logs

from heracles.acl.model import AclAssignment, AclScope
from heracles.acl.parser import parse_assignment, serialise_assignment
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.schema import names as schema

BASE = "dc=example,dc=com"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
ROLES = f"ou=roles,{BASE}"
ACL_ROLES = f"ou=aclroles,{BASE}"
ALICE = f"uid=alice,{PEOPLE}"
BOB = f"uid=bob,{PEOPLE}"
CAROL = f"uid=carol,{PEOPLE}"
GROUP = f"cn=team,{GROUPS}"
ROLE = f"cn=ops,{ROLES}"
ACL_ROLE = f"cn=managers,{ACL_ROLES}"


def _directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"dcObject", b"organization"], "dc": [b"example"]})
    for dn, rdn in (
        (PEOPLE, "people"),
        (GROUPS, "groups"),
        (ROLES, "roles"),
        (ACL_ROLES, "aclroles"),
    ):
        d.add(dn, {"objectClass": [b"organizationalUnit"], "ou": [rdn.encode()]})
    return d


def _service() -> tuple[ObjectService, MemoryDirectory]:
    d = _directory()
    registry = TypeRegistry()
    register_builtin_types(registry)
    return ObjectService(d, registry), d


def _user(d: MemoryDirectory, dn: str, uid: str) -> None:
    d.add(
        dn,
        {
            "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
            "uid": [uid.encode()],
            "sn": [uid.title().encode()],
            "givenName": [uid.title().encode()],
            "cn": [uid.title().encode()],
        },
    )


def _assignment(members: list[str], role: str = ACL_ROLE, index: int = 0) -> bytes:
    return serialise_assignment(
        AclAssignment(index, AclScope.SUBTREE, role, tuple(members))
    ).encode()


def _acls(d: MemoryDirectory, values: list[bytes]) -> None:
    d.modify(
        BASE,
        [
            Modification("add", "objectClass", [schema.OC.ACL_ASSIGNMENT.encode()]),
            Modification("add", schema.ATTR.ACL_ENTRY, values),
        ],
    )


def test_delete_removes_member_occupant_and_manager() -> None:
    service, d = _service()
    _user(d, ALICE, "alice")
    _user(d, BOB, "bob")
    _user(d, CAROL, "carol")
    d.add(
        GROUP,
        {
            "objectClass": [b"groupOfNames"],
            "cn": [b"team"],
            "member": [ALICE.encode(), BOB.encode()],
        },
    )
    d.add(
        ROLE,
        {
            "objectClass": [b"organizationalRole"],
            "cn": [b"ops"],
            "roleOccupant": [ALICE.encode(), BOB.encode()],
        },
    )

    service.delete("user", ALICE)

    group = d.get(GROUP)
    assert group is not None and group.texts("member") == [BOB]
    role = d.get(ROLE)
    assert role is not None and role.texts("roleOccupant") == [BOB]


def test_delete_removes_the_manager_reference() -> None:
    service, d = _service()
    _user(d, ALICE, "alice")
    _user(d, CAROL, "carol")
    d.modify(CAROL, [Modification("add", "manager", [ALICE.encode()])])

    service.delete("user", ALICE)

    carol = d.get(CAROL)
    assert carol is not None and carol.get("manager") == []


def test_delete_updates_and_drops_acl_assignments() -> None:
    service, d = _service()
    _user(d, ALICE, "alice")
    _user(d, BOB, "bob")
    _acls(d, [_assignment([ALICE, BOB], index=0), _assignment([BOB], index=1)])

    service.delete("user", ALICE)

    base = d.get(BASE)
    assert base is not None
    assert base.has_object_class(schema.OC.ACL_ASSIGNMENT)
    parsed = [parse_assignment(v) for v in base.texts(schema.ATTR.ACL_ENTRY)]
    assert [p.members for p in parsed if isinstance(p, AclAssignment)] == [(BOB,), (BOB,)]


def test_delete_of_a_role_drops_the_assignment() -> None:
    service, d = _service()
    _user(d, BOB, "bob")
    d.add(ROLE, {"objectClass": [b"organizationalRole"], "cn": [b"ops"]})
    _acls(d, [_assignment([BOB], role=ROLE)])

    service.delete("role", ROLE)

    base = d.get(BASE)
    assert base is not None
    assert not base.has_object_class(schema.OC.ACL_ASSIGNMENT)
    assert base.get(schema.ATTR.ACL_ENTRY) == []


def test_mandatory_member_is_kept_with_a_warning() -> None:
    service, d = _service()
    _user(d, ALICE, "alice")
    solo = f"cn=solo,{GROUPS}"
    d.add(solo, {"objectClass": [b"groupOfNames"], "cn": [b"solo"], "member": [ALICE.encode()]})

    with capture_logs() as logs:
        service.delete("user", ALICE)

    kept = d.get(solo)
    assert kept is not None and kept.texts("member") == [ALICE]
    assert any(entry["event"] == "reference_to_deleted_object_kept" for entry in logs)
