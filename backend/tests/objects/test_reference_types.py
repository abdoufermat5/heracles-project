"""An object reference must point at an entry of the declared type."""

from __future__ import annotations

import pytest

from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from tests.objects.conftest import BASE, PEOPLE
from tests.objects.fakes import FakeDirectory

BOB = f"uid=bob,{PEOPLE}"
ROLE = f"cn=ops,ou=roles,{BASE}"


def test_reference_to_the_wrong_type_is_refused(
    directory: FakeDirectory, registry: TypeRegistry, service: ObjectService, jdoe: str
) -> None:
    directory.put(f"ou=roles,{BASE}", objectClass=["organizationalUnit"], ou="roles")
    directory.put(ROLE, objectClass=["organizationalRole"], cn="ops")
    with pytest.raises(ObjectValidationError) as info:
        service.update("user", jdoe, {"main": {"values": {"manager": ROLE}}})
    assert "not a User" in info.value.fields["main.manager"]


def test_reference_to_the_right_type_is_accepted(
    directory: FakeDirectory, registry: TypeRegistry, service: ObjectService, jdoe: str
) -> None:
    directory.put(
        BOB,
        objectClass=["inetOrgPerson", "organizationalPerson", "person"],
        uid="bob",
        sn="Smith",
        givenName="Bob",
        cn="Bob Smith",
    )
    updated = service.update("user", jdoe, {"main": {"values": {"manager": BOB}}})
    assert updated.tabs["main"].values["manager"] == BOB
