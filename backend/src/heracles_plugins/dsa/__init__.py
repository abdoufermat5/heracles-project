"""DSA plugin: directory service accounts (``simpleSecurityObject``).

A DSA is a non-human account that binds to the directory (mail transfer agents,
web applications, ...). It is an ``organizationalRole`` carrying a password and
lives in ``ou=dsa``. The password is hashed through the process-wide password
hasher (the configured password policy), like user passwords.
"""

from __future__ import annotations

from dataclasses import dataclass

from heracles.attributes import (
    DepartmentAttr,
    PasswordAttr,
    StringAttr,
    TextAttr,
)
from heracles.auth.passwords import PasswordPolicy
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "dsa"
NAME_RE = r"[^\s,=+<>#;\"\\][^,=+<>#;\"\\]*"
MIN_PASSWORD_LENGTH = 8


@dataclass(slots=True)
class DsaSettings:
    """Settings of the DSA plugin.

    ``rdn`` documents the default container; it is the ``ObjectType.rdn`` of the
    type today (the framework does not make type containers configurable yet).
    """

    rdn: str = "ou=dsa"


class DsaPasswordAttr(PasswordAttr):
    """Service account password.

    Hashed by the installed password hasher; when none is installed (library use
    without the web application) the default password policy is used.
    """

    def to_ldap(self, value: str | None) -> list[bytes]:
        if not value:
            return []
        if self.hasher is None:
            try:
                return super().to_ldap(value)
            except RuntimeError:
                return [PasswordPolicy().hash_new(value).encode("utf-8")]
        return super().to_ldap(value)


class Dsa(ObjectType):
    """A directory service account."""

    name = "dsa"
    acl_category = "dsa"
    label = _("Service account")
    label_plural = _("Service accounts")
    icon = "key-round"
    category = "access"
    filter = "(objectClass=simpleSecurityObject)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=dsa"
    columns = ("cn", "description")
    search_attrs = ("cn", "description")

    class Main(Tab):
        name = "main"
        acl_key = "simpleSecurityObject"
        label = _("Service account")
        object_classes = ("organizationalRole", "simpleSecurityObject")

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=NAME_RE),
            TextAttr("description", _("Description")),
            DsaPasswordAttr(
                "userPassword",
                _("Password"),
                required=True,
                min_length=MIN_PASSWORD_LENGTH,
                description=_("Leave empty to keep the current password"),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if ctx.creating:
                ensure_container(ctx.directory, dnlib.join(Dsa.rdn, ctx.base))


def plugin() -> Plugin:
    """Entry point of the DSA plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(Dsa,),
        required_object_classes=("simpleSecurityObject", "organizationalRole"),
        settings=DsaSettings(),
    )


__all__ = ["Dsa", "DsaPasswordAttr", "DsaSettings", "plugin"]
