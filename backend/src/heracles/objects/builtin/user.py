"""Built-in ``user`` type."""

from __future__ import annotations

from typing import Any

from heracles.attributes import (
    DepartmentAttr,
    DisplayAttr,
    EmailAttr,
    ImageAttr,
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
from heracles.objects.model import ObjectType, Reference, Section, Tab

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


class User(ObjectType):
    """A person account."""

    name = "user"
    label = _("User")
    label_plural = _("Users")
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


__all__ = ["LANGUAGES", "NAME_RE", "UID_RE", "User"]
