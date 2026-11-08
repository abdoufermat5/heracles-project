"""Deleting a department removes its empty containers, refuses when objects remain."""

from __future__ import annotations

import pytest

from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectConflictError, ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"


def _service() -> tuple[ObjectService, MemoryDirectory]:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    registry = TypeRegistry()
    register_builtin_types(registry)
    return ObjectService(d, registry), d


def test_department_with_empty_containers_is_deleted() -> None:
    service, d = _service()
    dept = service.create("department", BASE, {"main": {"values": {"ou": "x", "description": "X"}}})
    user = service.create(
        "user", dept, {"main": {"values": {"uid": "u", "givenName": "U", "sn": "U"}}}
    )
    assert d.get(f"ou=people,{dept}") is not None  # container created on demand
    with pytest.raises(ObjectConflictError):
        service.delete("department", dept)
    service.delete("user", user)
    service.delete("department", dept)
    assert d.get(dept) is None
    assert d.get(f"ou=people,{dept}") is None
