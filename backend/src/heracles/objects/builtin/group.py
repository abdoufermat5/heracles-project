"""Built-in ``group`` and ``role`` types."""

from __future__ import annotations

from heracles.attributes import (
    DepartmentAttr,
    ListAttr,
    ObjectRefAttr,
    PhoneAttr,
    StringAttr,
    TextAttr,
)
from heracles.i18n import _
from heracles.objects.model import ObjectType, Reference, Section, Tab

CN_RE = r"[^\s,=+<>#;\"\\][^,=+<>#;\"\\]*"


class Group(ObjectType):
    """A group of users."""

    name = "group"
    acl_category = "ogroup"
    label = _("Group")
    label_plural = _("Groups")
    icon = "users"
    category = "directory"
    filter = "(objectClass=groupOfNames)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=groups"
    columns = ("cn", "description")
    search_attrs = ("cn", "description")
    references = (Reference("group", "member"),)

    class Main(Tab):
        name = "main"
        acl_key = "ogroup"
        label = _("Group")
        object_classes = ("groupOfNames",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=CN_RE),
            TextAttr("description", _("Description")),
        )
        members = Section(
            _("Members"),
            ListAttr(
                "member",
                _("Members"),
                ObjectRefAttr("member", _("Member"), ref_type="user"),
                required=True,
            ),
        )


class Role(ObjectType):
    """An organizational role with occupants."""

    name = "role"
    label = _("Role")
    label_plural = _("Roles")
    icon = "briefcase"
    category = "directory"
    filter = "(objectClass=organizationalRole)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=roles"
    columns = ("cn", "description")
    search_attrs = ("cn", "description")

    class Main(Tab):
        name = "main"
        acl_key = "roleGeneric"
        label = _("Role")
        object_classes = ("organizationalRole",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=CN_RE),
            TextAttr("description", _("Description")),
            PhoneAttr("telephoneNumber", _("Phone")),
        )
        occupants = Section(
            _("Occupants"),
            ListAttr(
                "roleOccupant",
                _("Occupants"),
                ObjectRefAttr("roleOccupant", _("Occupant"), ref_type="user"),
            ),
        )
