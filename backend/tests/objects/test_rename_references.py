"""Renames and moves: the ``m`` / ``c`` rights and the references that follow the object."""

from __future__ import annotations

from typing import Any

import pytest

from heracles.acl import AclAssignment, AclScope, parse_assignment, serialise_assignment
from heracles.ldap import dn as dnlib
from heracles.objects import (
    ObjectService,
    ObjectValidationError,
    PermissionDeniedError,
    TypeRegistry,
)
from heracles.schema import names as schema
from tests.objects.conftest import BASE, PARIS, PARIS_PEOPLE, PEOPLE
from tests.objects.fakes import FakeDirectory

GROUPS = f"ou=groups,{BASE}"
GROUP = f"cn=devs,{GROUPS}"
ROLE_DN = f"cn=manager,ou=aclroles,{BASE}"
MANAGED = f"uid=boss,{PEOPLE}"


class MovePolicy:
    """Allows everything except what a test switches off."""

    def __init__(self, *, move: bool = True, create: bool = True) -> None:
        self.move, self.create = move, create

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        return True

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        return True

    def can_create(self, type_name: str, base: str) -> bool:
        return self.create

    def can_delete(self, dn: str, type_name: str) -> bool:
        return True

    def can_move(self, dn: str) -> bool:
        return self.move


@pytest.fixture
def refs(directory: FakeDirectory, jdoe: str) -> str:
    directory.put(GROUP, objectClass=["groupOfNames"], cn="devs", member=[jdoe, MANAGED])
    directory.put(
        MANAGED,
        objectClass=["inetOrgPerson", "organizationalPerson", "person"],
        uid="boss",
        sn="Boss",
        manager=jdoe,
    )
    value = serialise_assignment(AclAssignment(0, AclScope.SUBTREE, ROLE_DN, (jdoe, "*", MANAGED)))
    directory.put(BASE, objectClass=["dcObject", "organization", "hrcAcl"], dc="example")
    directory.entries[dnlib.normalize(BASE)].attrs[schema.ATTR.ACL_ENTRY] = [value.encode()]
    return jdoe


def members(directory: FakeDirectory) -> list[str]:
    return [v.decode() for v in directory.entries[dnlib.normalize(GROUP)].attrs["member"]]


def assignment(directory: FakeDirectory) -> AclAssignment:
    raw = directory.entries[dnlib.normalize(BASE)].attrs[schema.ATTR.ACL_ENTRY][0].decode()
    parsed = parse_assignment(raw)
    assert isinstance(parsed, AclAssignment)
    return parsed


def test_rename_rewrites_references(
    service: ObjectService, directory: FakeDirectory, refs: str
) -> None:
    state = service.update("user", refs, {"main": {"values": {"uid": "jdupont"}}})
    new = f"uid=jdupont,{PEOPLE}"
    assert state.dn == new
    assert members(directory) == [new, MANAGED]
    assert directory.entries[dnlib.normalize(MANAGED)].attrs["manager"] == [new.encode()]
    parsed = assignment(directory)
    assert parsed.members == (new, "*", MANAGED) and parsed.role_dn == ROLE_DN


def test_move_rewrites_references(
    service: ObjectService, directory: FakeDirectory, refs: str
) -> None:
    new = service.move("user", refs, PARIS)
    assert new == f"uid=jdoe,{PARIS_PEOPLE}"
    assert members(directory) == [new, MANAGED]
    assert assignment(directory).members == (new, "*", MANAGED)


def test_move_by_department_attribute_rewrites_references(
    service: ObjectService, directory: FakeDirectory, refs: str
) -> None:
    service.update("user", refs, {"main": {"values": {"base": PARIS}}})
    assert members(directory)[0] == f"uid=jdoe,{PARIS_PEOPLE}"


def test_move_to_same_department_is_a_noop(
    service: ObjectService, directory: FakeDirectory, refs: str
) -> None:
    assert service.move("user", refs, BASE) == refs
    assert [e for e in directory.log if e[0] == "rename"] == []


def test_move_refuses_a_taken_name(
    service: ObjectService, directory: FakeDirectory, refs: str
) -> None:
    directory.put(
        f"uid=jdoe,{PARIS_PEOPLE}",
        objectClass=["inetOrgPerson", "organizationalPerson", "person"],
        uid="jdoe",
    )
    with pytest.raises(ObjectValidationError):
        service.move("user", refs, PARIS)


@pytest.mark.parametrize("policy", [MovePolicy(move=False), MovePolicy(create=False)])
def test_department_change_needs_move_and_create(
    directory: FakeDirectory, registry: TypeRegistry, refs: str, policy: MovePolicy
) -> None:
    service = ObjectService(directory, registry, policy=policy)
    with pytest.raises(PermissionDeniedError):
        service.update("user", refs, {"main": {"values": {"base": PARIS}}})
    with pytest.raises(PermissionDeniedError):
        service.move("user", refs, PARIS)
    assert [e for e in directory.log if e[0] == "rename"] == []


def test_rename_needs_move_right(
    directory: FakeDirectory, registry: TypeRegistry, refs: str
) -> None:
    service = ObjectService(directory, registry, policy=MovePolicy(move=False))
    changes: dict[str, Any] = {"main": {"values": {"uid": "other"}}}
    with pytest.raises(PermissionDeniedError):
        service.update("user", refs, changes)
    # a change that keeps the DN does not need it
    service.update("user", refs, {"main": {"values": {"sn": "Dupont"}}})


def test_listing_sort_ignores_non_columns(service: ObjectService, directory: FakeDirectory) -> None:
    for uid, password in (("a", "{SSHA}z"), ("b", "{SSHA}a")):
        directory.put(
            f"uid={uid},{PEOPLE}",
            objectClass=["inetOrgPerson", "organizationalPerson", "person"],
            uid=uid,
            userPassword=password,
        )
    page = service.list("user", BASE, sort="userPassword", extra_attrs=["userPassword"])
    assert [row.values["uid"] for row in page.items] == ["a", "b"]
