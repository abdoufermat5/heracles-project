"""Groupware plugin: collaboration server service tab on servers."""

from __future__ import annotations

from heracles.attributes import BooleanAttr, PasswordAttr, SelectAttr, StringAttr, UrlAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "groupware"

DELETION_TYPES: tuple[tuple[str, str], ...] = (
    ("delete", _("Delete")),
    ("close", _("Close / Lock")),
    ("maintenance", _("Maintenance")),
    ("none", _("None")),
)

CREATION_TYPES: tuple[tuple[str, str], ...] = (
    ("create", _("Create account")),
    ("none", _("Do not create")),
)

MAIL_SERVICE_CLASSES: tuple[str, ...] = (
    "hrcImapServer",
    "hrcMailStoreServer",
    "hrcMtaServer",
    "hrcSieveServer",
    "hrcSpamFilterServer",
    "hrcGroupwareServer",
)


def mail_servers(directory: DirectoryClient) -> list[str]:
    """Return the names (cn) of servers with at least one active mail service."""
    flt_parts = "".join(f"(objectClass={c})" for c in MAIL_SERVICE_CLASSES)
    flt = f"(|{flt_parts})"
    try:
        entries = directory.search(directory.base_dn, flt, Scope.SUBTREE, attrs=["cn"])
    except NoSuchObjectError:
        return []
    servers: set[str] = set()
    for entry in entries:
        cn = entry.text("cn")
        if cn:
            servers.add(cn)
    return sorted(servers)


class GroupwareServiceTab(Tab):
    """Groupware server service tab on servers."""

    name = "groupware"
    acl_key = "serviceGroupware"
    label = _("Groupware")
    description = _("Groupware suite service")
    optional = True
    object_classes = ("hrcGroupwareServer",)

    connection = Section(
        _("Server connection"),
        UrlAttr(
            "hrcGroupwareServerUri",
            _("Server URI"),
            description=_("Groupware server administration SOAP URL"),
        ),
        StringAttr(
            "hrcGroupwareServerLogin",
            _("Admin login"),
            description=_("Groupware administrator login"),
        ),
        PasswordAttr(
            "hrcGroupwareServerPassword",
            _("Admin password"),
            hasher=lambda p: p,
            description=_("Groupware administrator password"),
        ),
        StringAttr(
            "hrcGroupwareServerUserAgent",
            _("User agent"),
            description=_("HTTP user agent for Groupware SOAP API"),
        ),
    )
    provisioning = Section(
        _("Account provisioning"),
        SelectAttr(
            "hrcGroupwareServerCreationType",
            _("Creation type"),
            options=CREATION_TYPES,
            default="create",
        ),
        SelectAttr(
            "hrcGroupwareServerDeletionType",
            _("Deletion type"),
            options=DELETION_TYPES,
            default="delete",
        ),
        BooleanAttr(
            "hrcGroupwareServerPasswordSync",
            _("Password sync"),
            default=True,
            description=_("Synchronize user passwords with Groupware"),
        ),
        BooleanAttr(
            "hrcGroupwareServerKeepUnknownAliases",
            _("Keep unknown aliases"),
            default=False,
            description=_("Preserve aliases that are unknown to the directory"),
        ),
        StringAttr(
            "hrcGroupwareServerIdAttribute",
            _("ID attribute"),
            description=_("LDAP attribute used as Groupware identifier"),
        ),
    )
    defaults = Section(
        _("Defaults"),
        StringAttr("hrcGroupwareDomain", _("Domain"), description=_("Default Groupware domain")),
        StringAttr(
            "hrcGroupwareDomainServiceClass",
            _("Class of Service"),
            description=_("Default Class of Service (COS) for Groupware accounts"),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Groupware plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("server", GroupwareServiceTab),),
    )


__all__ = [
    "CREATION_TYPES",
    "DELETION_TYPES",
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "GroupwareServiceTab",
    "mail_servers",
    "plugin",
]
