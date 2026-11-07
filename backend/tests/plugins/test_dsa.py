"""DSA plugin: service accounts with a hashed password."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import heracles_plugins.dsa as dsa
from heracles.attributes import set_default_password_hasher
from heracles.auth.passwords import PasswordPolicy
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.set_schema_object_classes([*d.schema_object_classes(), "simpleSecurityObject"])
    return d


@pytest.fixture
def registry(directory: MemoryDirectory) -> TypeRegistry:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        dsa.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return registry


@pytest.fixture
def service(directory: MemoryDirectory, registry: TypeRegistry) -> Iterator[ObjectService]:
    set_default_password_hasher(PasswordPolicy().hash_new)
    yield ObjectService(directory, registry)
    set_default_password_hasher(None)


def values(**extra: object) -> dict[str, object]:
    return {"main": {"values": {"cn": "mta", "description": "Mail agent", **extra}}}


def test_acl_and_container(registry: TypeRegistry) -> None:
    info = registry.get("dsa")
    assert info.acl_object(info.main_tab) == "dsa/simpleSecurityObject"
    assert info.type.rdn == "ou=dsa"


def test_create_hashes_password_and_creates_container(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create("dsa", BASE, values(userPassword="s3cretpass1"))
    assert dn == f"cn=mta,ou=dsa,{BASE}"
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("simpleSecurityObject")
    assert entry.has_object_class("organizationalRole")
    stored = entry.text("userPassword") or ""
    assert stored.startswith("{SSHA}") and "s3cretpass1" not in stored
    page = service.list("dsa")
    assert [r.values["cn"] for r in page.items] == ["mta"]


def test_password_required_on_creation_and_checked(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as missing:
        service.create("dsa", BASE, values())
    assert "main.userPassword" in missing.value.fields
    with pytest.raises(ObjectValidationError) as short:
        service.create("dsa", BASE, values(userPassword="short"))
    assert "main.userPassword" in short.value.fields


def test_update_keeps_or_changes_password(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create("dsa", BASE, values(userPassword="s3cretpass1"))
    first = (directory.get(dn) or pytest.fail()).text("userPassword")
    service.update("dsa", dn, {"main": {"values": {"description": "Changed"}}})
    entry = directory.get(dn) or pytest.fail()
    assert entry.text("userPassword") == first
    assert entry.text("description") == "Changed"
    service.update("dsa", dn, {"main": {"values": {"userPassword": "another-secret"}}})
    assert (directory.get(dn) or pytest.fail()).text("userPassword") != first


def test_password_falls_back_to_default_policy_without_installed_hasher(
    directory: MemoryDirectory, registry: TypeRegistry
) -> None:
    set_default_password_hasher(None)
    dn = ObjectService(directory, registry).create("dsa", BASE, values(userPassword="s3cretpass1"))
    assert (directory.get(dn) or pytest.fail()).text(
        "userPassword",
    ) is not None


def test_plugin_disabled_without_schema() -> None:
    registry = TypeRegistry()
    status = registry.register_plugin(dsa.plugin(), {"organizationalrole"})
    assert not status.enabled
    assert status.missing_object_classes == ["simpleSecurityObject"]
