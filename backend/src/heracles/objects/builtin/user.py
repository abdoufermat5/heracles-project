"""Built-in ``user`` type."""

from __future__ import annotations

from typing import Any

from heracles.attributes import (
    DepartmentAttr,
    DisplayAttr,
    EmailAttr,
    ImageAttr,
    ListAttr,
    ObjectRefAttr,
    PasswordAttr,
    PhoneAttr,
    PostalAddressAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
    UrlAttr,
)
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Modification, NoSuchObjectError, Scope
from heracles.objects import filters
from heracles.objects.hooks import TabContext
from heracles.objects.model import ObjectType, Reference, Section, Tab
from heracles.schema import names as schema

NAME_RE = r"[^\s,=+<>#;\"\\][^,=+<>#;\"\\]*"
UID_RE = r"[A-Za-z0-9_][A-Za-z0-9._@-]*"

LANGUAGES = (
    ("en", "English"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("it", "Italiano"),
    ("pt", "Português"),
)


def _full_name(values: dict[str, Any]) -> str | None:
    parts = [str(values.get(k) or "").strip() for k in ("givenName", "sn")]
    name = " ".join(p for p in parts if p)
    return name or None


def _role_item() -> ObjectRefAttr:
    item = ObjectRefAttr("roles", _("Role"), ref_type="role")
    item.stored = False  # memberships live on the role entries
    return item


def roles_of(ctx: TabContext, user_dn: str) -> list[str]:
    """DNs of the roles whose occupants include ``user_dn``."""
    flt = filters.and_(
        filters.equals("objectClass", schema.STD_OC.ORGANIZATIONAL_ROLE),
        filters.equals(schema.STD_ATTR.ROLE_OCCUPANT, user_dn),
    )
    try:
        entries = ctx.directory.search(ctx.directory.base_dn, flt, Scope.SUBTREE, ["cn"])
        return sorted(e.dn for e in entries)
    except NoSuchObjectError:
        return []


def _dns(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]


class User(ObjectType):
    """A person account."""

    name = "user"
    label = _("User")
    label_plural = _("Users")
    nav = "primary"
    nav_group = "people"
    count_key = "user"
    icon = "user"
    category = "directory"
    filter = "(objectClass=inetOrgPerson)"
    main_attr = "uid"
    name_attr = "cn"
    rdn = "ou=people"
    columns = ("uid", "cn", "mail")
    search_attrs = ("uid", "cn", "sn", "givenName", "mail")
    references = (
        Reference("group", "member"),
        Reference("role", "roleOccupant"),
        Reference("user", "manager"),
    )

    class Main(Tab):
        name = "main"
        acl_key = "user"
        label = _("User")
        object_classes = ("inetOrgPerson", "organizationalPerson", "person")

        identity = Section(
            _("Identity"),
            StringAttr("sn", _("Last name"), required=True, pattern=NAME_RE),
            StringAttr("givenName", _("First name"), required=True, pattern=NAME_RE),
            StringAttr("initials", _("Initials"), max_length=6),
            DisplayAttr("cn", _("Name"), compute=_full_name, stored=True),
            TextAttr("description", _("Description")),
            ImageAttr("jpegPhoto", _("Picture"), max_size=(200, 200)),
        )
        contact = Section(
            _("Contact"),
            EmailAttr("mail", _("Email")),
            StringAttr("l", _("City")),
            StringAttr("st", _("State")),
            PostalAddressAttr("postalAddress", _("Postal address")),
            StringAttr("roomNumber", _("Room number")),
            PhoneAttr("telephoneNumber", _("Phone")),
            PhoneAttr("mobile", _("Mobile")),
            PhoneAttr("pager", _("Pager")),
            PhoneAttr("facsimileTelephoneNumber", _("Fax")),
            UrlAttr("labeledURI", _("Web page")),
        )
        account = Section(
            _("Account"),
            DepartmentAttr("base", _("Department")),
            StringAttr("uid", _("Login"), required=True, pattern=UID_RE),
            SelectAttr("preferredLanguage", _("Language"), options=LANGUAGES),
            PasswordAttr("userPassword", _("Password")),
        )
        personal = Section(
            _("Personal"),
            StringAttr("displayName", _("Display name")),
            PostalAddressAttr("homePostalAddress", _("Home address")),
            PhoneAttr("homePhone", _("Home phone")),
        )
        organization = Section(
            _("Organization"),
            StringAttr("o", _("Organization")),
            StringAttr("ou", _("Organizational unit")),
            StringAttr("departmentNumber", _("Department number")),
            StringAttr("employeeNumber", _("Employee number")),
            StringAttr("employeeType", _("Employee type")),
            ObjectRefAttr("manager", _("Manager"), ref_type="user"),
        )

    class Roles(Tab):
        """Roles the user occupies; written on the role entries (``roleOccupant``)."""

        name = "roles"
        acl_key = "user"
        label = _("Roles")
        object_classes = ()

        membership = Section(
            _("Roles"),
            ListAttr(
                "roles",
                _("Roles"),
                _role_item(),
                description=_("Roles occupied by this user"),
            ),
        )

        @classmethod
        def on_load(cls, ctx: TabContext) -> None:
            if ctx.dn is not None:
                ctx.values["roles"] = roles_of(ctx, ctx.dn) or None

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if not ctx.was_touched("roles"):
                return
            old = {dnlib.normalize(d) for d in _dns(ctx.original_values().get("roles"))}
            for role_dn in _dns(ctx.values.get("roles")):
                changed = dnlib.normalize(role_dn) not in old
                if not changed:
                    continue
                entry = ctx.directory.get(role_dn)
                if entry is None or not entry.has_object_class(schema.STD_OC.ORGANIZATIONAL_ROLE):
                    ctx.error("roles", _("Not a role: {dn}").format(dn=role_dn))
                elif not ctx.can_write_object(
                    "role", role_dn, "main", schema.STD_ATTR.ROLE_OCCUPANT
                ):
                    ctx.error("roles", _("Cannot change the occupants of {dn}").format(dn=role_dn))
            new = {dnlib.normalize(d) for d in _dns(ctx.values.get("roles"))}
            for role_dn in _dns(ctx.original_values().get("roles")):
                if dnlib.normalize(role_dn) not in new and not ctx.can_write_object(
                    "role", role_dn, "main", schema.STD_ATTR.ROLE_OCCUPANT
                ):
                    ctx.error("roles", _("Cannot change the occupants of {dn}").format(dn=role_dn))

        @classmethod
        def after_save(cls, ctx: TabContext) -> None:
            if ctx.dn is None or not ctx.was_touched("roles"):
                return
            old = {dnlib.normalize(d): d for d in _dns(ctx.original_values().get("roles"))}
            new = {dnlib.normalize(d): d for d in _dns(ctx.values.get("roles"))}
            attr = schema.STD_ATTR.ROLE_OCCUPANT
            user_key = dnlib.normalize(ctx.dn)
            for key, role_dn in new.items():
                if key not in old:
                    entry = ctx.directory.get(role_dn, [attr])
                    if entry is not None and user_key not in {
                        dnlib.normalize(v) for v in entry.texts(attr)
                    }:
                        ctx.directory.modify(
                            role_dn, [Modification("add", attr, [ctx.dn.encode("utf-8")])]
                        )
            for key, role_dn in old.items():
                if key not in new:
                    entry = ctx.directory.get(role_dn, [attr])
                    if entry is None:
                        continue
                    present = [
                        v for v in entry.get(attr) if dnlib.normalize(v.decode()) == user_key
                    ]
                    if present:
                        ctx.directory.modify(role_dn, [Modification("delete", attr, present)])


__all__ = ["LANGUAGES", "NAME_RE", "UID_RE", "User"]
