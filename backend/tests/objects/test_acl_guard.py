"""The ACL assignment subset rule is enforced on every write of the ACL attribute.

The generic ``acl`` tab of the administration plugin saves ``hrcAclEntry`` through
:class:`ObjectService`, so these tests save that attribute directly, exactly as the tab
does once its ``prepare`` hook has serialised the assignments.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from heracles.acl import FULL_RIGHTS, NO_RIGHTS, Rights
from heracles.acl import admin as acl_admin
from heracles.attributes import HiddenAttr, ListAttr
from heracles.ldap import dn as dnlib
from heracles.objects import (
    AllowAll,
    ObjectService,
    ObjectState,
    ObjectValidationError,
    Section,
    Tab,
    TypeRegistry,
)
from heracles.objects.builtin import register_builtin_types
from heracles.schema import names as schema
from tests.objects.fakes import FakeDirectory

BASE = "dc=example,dc=com"
PARIS = f"ou=Paris,{BASE}"
ROLES = f"ou=aclroles,{BASE}"
BROAD = f"cn=broad,{ROLES}"
NARROW = f"cn=narrow,{ROLES}"


class AclEntryTab(Tab):
    """What the administration plugin's tab sends to the service: ``hrcAclEntry``."""

    name = "acl"
    label = "Access control"
    optional = True
    object_classes = ("hrcAcl",)

    assignments = Section(
        "Assignments",
        ListAttr(
            schema.ATTR.ACL_ENTRY,
            "Stored values",
            HiddenAttr(schema.ATTR.ACL_ENTRY, "Value"),
        ),
    )


class GuardPolicy(AllowAll):
    """A policy reporting fixed effective rights, like the ACL engine does."""

    def __init__(self, held: Mapping[tuple[str, str], Rights] | None = None) -> None:
        self.held = {
            (dnlib.normalize(dn), key): rights for (dn, key), rights in (held or {}).items()
        }
        self.calls: list[tuple[str, str, str]] = []

    def permissions(self, dn: str, object_key: str, attribute: str) -> Rights:
        self.calls.append((dnlib.normalize(dn), object_key, attribute))
        return self.held.get((dnlib.normalize(dn), object_key), NO_RIGHTS)


class IgnoresAcl(GuardPolicy):
    """A bootstrap administrator's policy: every right everywhere."""

    def permissions(self, dn: str, object_key: str, attribute: str) -> Rights:
        return FULL_RIGHTS


@pytest.fixture
def directory() -> FakeDirectory:
    d = FakeDirectory(BASE)
    d.put(BASE, objectClass=["dcObject", "organization"], dc="example", o="Example")
    d.put(ROLES, objectClass="organizationalUnit", ou="aclroles")
    d.put(
        PARIS,
        objectClass=["organizationalUnit", "hrcDepartment"],
        ou="Paris",
        description="Paris office",
    )
    d.put(BROAD, objectClass="hrcRole", hrcAclTemplate=["0:user/user;rwcdm#sn;rw"])
    d.put(NARROW, objectClass="hrcRole", hrcAclTemplate=["0:user/user;r"])
    return d


@pytest.fixture
def registry() -> TypeRegistry:
    reg = TypeRegistry()
    register_builtin_types(reg)
    reg.attach_tab("department", AclEntryTab)
    return reg


def _assignment(role_dn: str, *, index: int = 0, members: Sequence[str] = ("*",)) -> str:
    encoded = ",".join(acl_admin.encode_member(member) for member in members)
    return f"{index}:subtree:{acl_admin.encode_member(role_dn)}:{encoded}"


def _store(directory: FakeDirectory, *values: str) -> None:
    """Put assignments on the department as an earlier save left them."""
    entry = directory.entries[dnlib.normalize(PARIS)]
    classes = entry.attrs.setdefault("objectClass", [])
    if b"hrcAcl" not in classes:
        classes.append(b"hrcAcl")
    entry.attrs[schema.ATTR.ACL_ENTRY] = [value.encode() for value in values]


def _save(service: ObjectService, values: list[str] | None) -> ObjectState:
    return service.update(
        "department",
        PARIS,
        {"acl": {"active": True, "values": {schema.ATTR.ACL_ENTRY: values}}},
    )


def _stored(directory: FakeDirectory) -> list[str]:
    return directory.entries[dnlib.normalize(PARIS)].texts(schema.ATTR.ACL_ENTRY)


def test_new_assignment_above_the_caller_is_refused(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    policy = GuardPolicy({(PARIS, "user/user"): Rights.parse("r")})
    service = ObjectService(directory, registry, policy=policy)

    with pytest.raises(ObjectValidationError) as refused:
        _save(service, [_assignment(BROAD)])

    assert "user/user:rwcdm" in refused.value.fields["acl"]
    assert (dnlib.normalize(PARIS), "user/user", "") in policy.calls  # evaluated at the saved entry
    assert _stored(directory) == []


def test_assignment_within_the_caller_rights_passes(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    policy = GuardPolicy({(PARIS, "user/user"): Rights.parse("rwcdm")})
    service = ObjectService(directory, registry, policy=policy)

    lesser = _save(service, [_assignment(NARROW)])
    assert lesser.tabs["acl"].values[schema.ATTR.ACL_ENTRY] == [_assignment(NARROW)]

    equal = _save(service, [_assignment(BROAD)])
    assert equal.tabs["acl"].values[schema.ATTR.ACL_ENTRY] == [_assignment(BROAD)]


def test_policy_ignoring_the_acl_passes(directory: FakeDirectory, registry: TypeRegistry) -> None:
    service = ObjectService(directory, registry, policy=IgnoresAcl())

    state = _save(service, [_assignment(BROAD)])

    assert state.tabs["acl"].values[schema.ATTR.ACL_ENTRY] == [_assignment(BROAD)]


def test_unchanged_broader_assignment_passes(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    raw = _assignment(BROAD)
    _store(directory, raw)
    policy = GuardPolicy({(PARIS, "user/user"): Rights.parse("r")})
    service = ObjectService(directory, registry, policy=policy)

    state = _save(service, [raw])

    assert state.tabs["acl"].values[schema.ATTR.ACL_ENTRY] == [raw]
    assert policy.calls == []  # stored values are not evaluated again


def test_renumbered_broader_assignment_passes(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    _store(directory, _assignment(BROAD, index=0))
    service = ObjectService(
        directory, registry, policy=GuardPolicy({(PARIS, "user/user"): Rights.parse("r")})
    )

    state = _save(service, [_assignment(BROAD, index=7)])

    assert state.tabs["acl"].values[schema.ATTR.ACL_ENTRY] == [_assignment(BROAD, index=7)]


def test_removing_a_broader_assignment_passes(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    _store(directory, _assignment(BROAD))
    service = ObjectService(
        directory, registry, policy=GuardPolicy({(PARIS, "user/user"): Rights.parse("r")})
    )

    state = _save(service, None)

    assert state.tabs["acl"].values.get(schema.ATTR.ACL_ENTRY) is None
    assert _stored(directory) == []


def test_adding_a_member_to_a_broader_assignment_is_refused(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    _store(directory, _assignment(BROAD, members=("*",)))
    service = ObjectService(
        directory, registry, policy=GuardPolicy({(PARIS, "user/user"): Rights.parse("r")})
    )

    with pytest.raises(ObjectValidationError) as refused:
        _save(service, [_assignment(BROAD, members=(f"uid=jdoe,ou=people,{BASE}",))])

    assert "user/user:rwcdm" in refused.value.fields["acl"]


def test_without_a_permissions_policy_assignments_are_not_checked(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    service = ObjectService(directory, registry)

    state = _save(service, [_assignment(BROAD)])

    assert state.tabs["acl"].values[schema.ATTR.ACL_ENTRY] == [_assignment(BROAD)]


def test_create_with_an_assignment_above_the_caller_is_refused(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    created = f"ou=New,{BASE}"
    policy = GuardPolicy({(created, "user/user"): Rights.parse("r")})
    service = ObjectService(directory, registry, policy=policy)

    with pytest.raises(ObjectValidationError) as refused:
        service.create(
            "department",
            BASE,
            {
                "main": {"values": {"ou": "New", "description": "New office"}},
                "acl": {
                    "active": True,
                    "values": {schema.ATTR.ACL_ENTRY: [_assignment(BROAD)]},
                },
            },
        )

    assert "user/user:rwcdm" in refused.value.fields["acl"]
    assert directory.get(created) is None
