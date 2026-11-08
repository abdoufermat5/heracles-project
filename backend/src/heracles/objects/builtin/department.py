"""Built-in department types (``ou`` / ``o`` / ``l`` / ``c`` / ``dc`` variants)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from heracles.attributes import ObjectRefAttr, StringAttr, TextAttr
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Entry, Scope
from heracles.objects._compat import DEPARTMENT_MARKER
from heracles.objects.errors import ObjectConflictError
from heracles.objects.hooks import TabContext
from heracles.objects.model import ObjectType, Reference, Section, Tab


def _department_tab(
    main_attr: str,
    label: str,
    structural: Sequence[str],
    *,
    acl_key: str,
    pattern: str | None = None,
) -> type[Tab]:
    """Build the main tab of a department variant (they differ by naming attribute)."""
    namespace: dict[str, Any] = {
        "name": "main",
        "label": _("Department"),
        "acl_key": acl_key,
        "object_classes": (*structural, DEPARTMENT_MARKER),
        "identity": Section(
            _("Identity"),
            StringAttr(main_attr, label, required=True, pattern=pattern or r"[^,=+<>#;\"\\]+"),
            TextAttr("description", _("Description"), required=True),
        ),
        "details": Section(
            _("Details"),
            StringAttr("businessCategory", _("Category")),
            ObjectRefAttr("manager", _("Manager"), ref_type="user"),
        ),
        "before_delete": classmethod(_remove_empty_containers),
    }
    return cast("type[Tab]", type("Main", (Tab,), namespace))


def _is_plain_container(entry: Entry) -> bool:
    """An organizational unit used only as a container (not a department)."""
    classes = {c.lower() for c in entry.texts("objectClass")} - {"top"}
    return classes == {"organizationalunit"}


def _remove_empty_containers(cls: type[Tab], ctx: TabContext) -> None:
    """Allow deleting a department that only holds empty type containers.

    Containers (``ou=people``, ``ou=groups``, ...) are created on demand; they are removed
    with the department. A department that still holds objects is not deleted.
    """
    del cls
    if ctx.dn is None:
        return
    below = [
        e
        for e in ctx.directory.search(ctx.dn, "(objectClass=*)", Scope.SUBTREE, ["objectClass"])
        if dnlib.normalize(e.dn) != dnlib.normalize(ctx.dn)
    ]
    if any(not _is_plain_container(e) for e in below):
        raise ObjectConflictError(_("The department is not empty."))
    for entry in sorted(below, key=lambda e: -dnlib.depth(e.dn)):
        ctx.directory.delete(entry.dn)


class DepartmentType(ObjectType):
    """Shared metadata of all department variants (they live directly under a department)."""

    icon = "building"
    category = "directory"
    acl_category = "department"
    rdn = ""
    columns = ("description",)
    references = (Reference("user", "manager"),)


def _filter(structural: str) -> str:
    return f"(&(objectClass={structural})(objectClass={DEPARTMENT_MARKER}))"


class OuDepartment(DepartmentType):
    """Organizational unit department."""

    name = "department"
    label = _("Department")
    label_plural = _("Departments")
    filter = _filter("organizationalUnit")
    main_attr = "ou"
    name_attr = "ou"
    columns = ("ou", "description")
    search_attrs = ("ou", "description")
    Main = _department_tab("ou", _("Name"), ("organizationalUnit",), acl_key="department")


class OrganizationDepartment(DepartmentType):
    """Organization (``o``) department."""

    name = "department_o"
    label = _("Organization")
    label_plural = _("Organizations")
    filter = _filter("organization")
    main_attr = "o"
    name_attr = "o"
    columns = ("o", "description")
    search_attrs = ("o", "description")
    Main = _department_tab("o", _("Name"), ("organization",), acl_key="organization")


class LocalityDepartment(DepartmentType):
    """Locality (``l``) department."""

    name = "department_l"
    label = _("Locality")
    label_plural = _("Localities")
    filter = _filter("locality")
    main_attr = "l"
    name_attr = "l"
    columns = ("l", "description")
    search_attrs = ("l", "description")
    Main = _department_tab("l", _("Name"), ("locality",), acl_key="locality")


class CountryDepartment(DepartmentType):
    """Country (``c``) department."""

    name = "department_c"
    label = _("Country")
    label_plural = _("Countries")
    filter = _filter("country")
    main_attr = "c"
    name_attr = "c"
    columns = ("c", "description")
    search_attrs = ("c", "description")
    Main = _department_tab(
        "c", _("Country code"), ("country",), acl_key="country", pattern=r"[A-Za-z]{2}"
    )


class DomainDepartment(DepartmentType):
    """Domain component (``dc``) department."""

    name = "department_dc"
    label = _("Domain")
    label_plural = _("Domains")
    filter = _filter("domain")
    main_attr = "dc"
    name_attr = "dc"
    columns = ("dc", "description")
    search_attrs = ("dc", "description")
    Main = _department_tab("dc", _("Domain component"), ("domain",), acl_key="domain")


DEPARTMENT_TYPES: tuple[type[DepartmentType], ...] = (
    OuDepartment,
    OrganizationDepartment,
    LocalityDepartment,
    CountryDepartment,
    DomainDepartment,
)
