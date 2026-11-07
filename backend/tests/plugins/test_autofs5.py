"""Tests for the Autofs5 plugin (automount maps, entries, cascading delete, tree)."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.autofs5 as autofs5
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.schema.legacy import OC

BASE = "dc=test"
PARIS = f"ou=paris,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"top", b"domain"], "dc": [b"test"]})
    d.add(
        PARIS,
        {
            "objectClass": [b"top", b"organizationalUnit", OC.DEPARTMENT.encode()],
            "ou": [b"paris"],
        },
    )
    d.set_schema_object_classes(
        [
            *d.schema_object_classes(),
            "automountMap",
            "automount",
        ]
    )
    return d


@pytest.fixture
def registry(directory: MemoryDirectory) -> TypeRegistry:
    reg = TypeRegistry()
    register_builtin_types(reg)
    status = reg.register_plugin(
        autofs5.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return reg


@pytest.fixture
def service(directory: MemoryDirectory, registry: TypeRegistry) -> ObjectService:
    return ObjectService(directory, registry)


def test_autofs_map_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    values: dict[str, Any] = {
        "ou": "auto.home",
        "description": "User home directories map",
    }
    dn = service.create("automountMap", PARIS, {"main": {"values": values}})
    assert dn == f"ou=auto.home,ou=autofs,{PARIS}"

    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("ou") == "auto.home"
    assert entry.text("description") == "User home directories map"

    loaded = service.load("automountMap", dn)
    assert loaded.tabs["main"].values["ou"] == "auto.home"

    # Update description
    service.update("automountMap", dn, {"main": {"values": {"description": "Updated home map"}}})
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("description") == "Updated home map"

    # Delete
    service.delete("automountMap", dn)
    assert directory.get(dn) is None


def test_automount_entry_creation_and_parent_validation(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    # 1. Create a map
    map_dn = service.create("automountMap", PARIS, {"main": {"values": {"ou": "auto.shares"}}})

    # 2. Create child automount entry under map_dn
    entry_values: dict[str, Any] = {
        "automountKey": "docs",
        "automountInformation": "-fstype=nfs,rw,nosuid storage.example.com:/exports/docs",
        "description": "Company documentation",
    }
    entry_dn = service.create("automount", map_dn, {"main": {"values": entry_values}})
    assert entry_dn == f"automountKey=docs,{map_dn}"

    entry = directory.get(entry_dn)
    assert entry is not None
    assert entry.text("automountKey") == "docs"
    assert "storage.example.com" in (entry.text("automountInformation") or "")

    # 3. Fail creation if parent is not an automountMap
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "automount",
            PARIS,
            {
                "main": {
                    "values": {
                        "automountKey": "invalid",
                        "automountInformation": "server:/path",
                    }
                }
            },
        )
    assert "main.automountKey" in exc_info.value.fields


def test_cascading_delete(service: ObjectService, directory: MemoryDirectory) -> None:
    map_dn = service.create("automountMap", PARIS, {"main": {"values": {"ou": "auto.cascade"}}})
    entry1_dn = service.create(
        "automount",
        map_dn,
        {"main": {"values": {"automountKey": "sub1", "automountInformation": "srv:/sub1"}}},
    )
    entry2_dn = service.create(
        "automount",
        map_dn,
        {"main": {"values": {"automountKey": "sub2", "automountInformation": "srv:/sub2"}}},
    )

    assert directory.get(entry1_dn) is not None
    assert directory.get(entry2_dn) is not None

    # Deleting the map should delete all its children
    service.delete("automountMap", map_dn)
    assert directory.get(map_dn) is None
    assert directory.get(entry1_dn) is None
    assert directory.get(entry2_dn) is None


def test_build_autofs_tree(service: ObjectService, directory: MemoryDirectory) -> None:
    map1_dn = service.create("automountMap", PARIS, {"main": {"values": {"ou": "auto.master"}}})
    service.create(
        "automount",
        map1_dn,
        {"main": {"values": {"automountKey": "/home", "automountInformation": "ldap:auto.home"}}},
    )
    service.create(
        "automount",
        map1_dn,
        {"main": {"values": {"automountKey": "/net", "automountInformation": "-hosts"}}},
    )

    tree = autofs5.build_autofs_tree(directory, map1_dn)
    assert len(tree) == 1
    assert tree[0]["type"] == "automountMap"
    assert tree[0]["label"] == "auto.master"
    assert len(tree[0]["children"]) == 2
    child_labels = {c["label"] for c in tree[0]["children"]}
    assert child_labels == {"/home", "/net"}
