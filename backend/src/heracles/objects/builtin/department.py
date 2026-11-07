"""Built-in department types (``ou`` / ``o`` / ``l`` / ``c`` / ``dc`` variants)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from heracles.attributes import ObjectRefAttr, StringAttr, TextAttr
from heracles.i18n import _
from heracles.objects._compat import DEPARTMENT_MARKER
from heracles.objects.model import ObjectType, Reference, Section, Tab


def _department_tab(
    main_attr: str, label: str, structural: Sequence[str], *, pattern: str | None = None
) -> type[Tab]:
    """Build the main tab of a department variant (they differ by naming attribute)."""
    namespace: dict[str, Any] = {
        "name": "main",
        "label": _("Department"),
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
    }
    return cast("type[Tab]", type("Main", (Tab,), namespace))


class DepartmentType(ObjectType):
    """Shared metadata of all department variants (they live directly under a department)."""

    icon = "building"
    category = "directory"
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
    Main = _department_tab("ou", _("Name"), ("organizationalUnit",))


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
    Main = _department_tab("o", _("Name"), ("organization",))


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
    Main = _department_tab("l", _("Name"), ("locality",))


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
    Main = _department_tab("c", _("Country code"), ("country",), pattern=r"[A-Za-z]{2}")


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
    Main = _department_tab("dc", _("Domain component"), ("domain",))


DEPARTMENT_TYPES: tuple[type[DepartmentType], ...] = (
    OuDepartment,
    OrganizationDepartment,
    LocalityDepartment,
    CountryDepartment,
    DomainDepartment,
)
