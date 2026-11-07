from __future__ import annotations

import pytest

from heracles.attributes import IntAttr, StringAttr
from heracles.objects import ObjectService, Section, Tab, TypeRegistry
from heracles.objects.builtin import User, register_builtin_types
from tests.objects.fakes import FakeDirectory

BASE = "dc=example,dc=com"
PEOPLE = f"ou=people,{BASE}"
PARIS = f"ou=Paris,{BASE}"
PARIS_PEOPLE = f"ou=people,{PARIS}"


class PosixTab(Tab):
    name = "posix"
    label = "POSIX"
    optional = True
    object_classes = ("posixAccount", "shadowAccount")
    main = Section(
        "Unix",
        IntAttr("uidNumber", "UID number", required=True, min=0),
        StringAttr("homeDirectory", "Home", required=True),
        StringAttr("loginShell", "Shell", default="/bin/bash"),
    )


class SshTab(Tab):
    name = "ssh"
    optional = True
    requires = ("posix",)
    object_classes = ("ldapPublicKey",)
    keys = Section("Keys", StringAttr("sshPublicKey", "Key"))


@pytest.fixture
def directory() -> FakeDirectory:
    d = FakeDirectory(BASE)
    d.put(BASE, objectClass=["dcObject", "organization"], dc="example", o="Example")
    d.put(PEOPLE, objectClass="organizationalUnit", ou="people")
    d.put(f"ou=groups,{BASE}", objectClass="organizationalUnit", ou="groups")
    d.put(
        PARIS,
        objectClass=["organizationalUnit", "gosaDepartment"],
        ou="Paris",
        description="Paris office",
    )
    d.put(PARIS_PEOPLE, objectClass="organizationalUnit", ou="people")
    return d


@pytest.fixture
def registry() -> TypeRegistry:
    reg = TypeRegistry()
    register_builtin_types(reg)
    reg.attach_tab("user", PosixTab)
    reg.attach_tab("user", SshTab)
    return reg


@pytest.fixture
def service(directory: FakeDirectory, registry: TypeRegistry) -> ObjectService:
    return ObjectService(directory, registry)


JDOE = f"uid=jdoe,{PEOPLE}"


@pytest.fixture
def jdoe(directory: FakeDirectory) -> str:
    directory.put(
        JDOE,
        objectClass=["inetOrgPerson", "organizationalPerson", "person", "top"],
        uid="jdoe",
        sn="Doe",
        givenName="John",
        cn="John Doe",
        mail="j@x.org",
        userPassword="{SSHA}secret",
    )
    return JDOE


assert User.name == "user"
