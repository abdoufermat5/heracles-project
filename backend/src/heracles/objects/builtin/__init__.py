"""Built-in core object types."""

from __future__ import annotations

from heracles.objects.builtin.department import (
    DEPARTMENT_TYPES,
    CountryDepartment,
    DepartmentType,
    DomainDepartment,
    LocalityDepartment,
    OrganizationDepartment,
    OuDepartment,
)
from heracles.objects.builtin.group import Group, Role
from heracles.objects.builtin.user import User
from heracles.objects.model import ObjectType
from heracles.objects.registry import TypeRegistry

BUILTIN_TYPES: tuple[type[ObjectType], ...] = (User, Group, Role, *DEPARTMENT_TYPES)


def register_builtin_types(registry: TypeRegistry) -> None:
    """Register the core types."""
    for type_cls in BUILTIN_TYPES:
        registry.register_type(type_cls)


__all__ = [
    "BUILTIN_TYPES",
    "DEPARTMENT_TYPES",
    "CountryDepartment",
    "DepartmentType",
    "DomainDepartment",
    "Group",
    "LocalityDepartment",
    "OrganizationDepartment",
    "OuDepartment",
    "Role",
    "User",
    "register_builtin_types",
]
