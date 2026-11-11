"""Zimbra plugin: collaboration server service tab on servers."""

from __future__ import annotations

from heracles.attributes import BooleanAttr, PasswordAttr, SelectAttr, StringAttr, UrlAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "zimbra"

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
    "hrcDovecotServer",
    "hrcCyrusServer",
    "hrcPostfixServer",
    "hrcSieveServer",
    "hrcSpamAssassinServer",
    "hrcZimbraServer",
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


class ZimbraServiceTab(Tab):
    """Zimbra collaboration server service tab on servers."""

    name = "zimbra"
    acl_key = "serviceZimbra"
    label = _("Zimbra")
    description = _("Zimbra collaboration suite service")
    optional = True
    object_classes = ("hrcZimbraServer",)

    connection = Section(
        _("Server connection"),
        UrlAttr(
            "hrcZimbraServerUri",
            _("Server URI"),
            description=_("Zimbra server administration SOAP URL"),
        ),
        StringAttr(
            "hrcZimbraServerLogin",
            _("Admin login"),
            description=_("Zimbra administrator login"),
        ),
        PasswordAttr(
            "hrcZimbraServerPassword",
            _("Admin password"),
            hasher=lambda p: p,
            description=_("Zimbra administrator password"),
        ),
        StringAttr(
            "hrcZimbraServerUserAgent",
            _("User agent"),
            description=_("HTTP user agent for Zimbra SOAP API"),
        ),
    )
    provisioning = Section(
        _("Account provisioning"),
        SelectAttr(
            "hrcZimbraServerCreationType",
            _("Creation type"),
            options=CREATION_TYPES,
            default="create",
        ),
        SelectAttr(
            "hrcZimbraServerDeletionType",
            _("Deletion type"),
            options=DELETION_TYPES,
            default="delete",
        ),
        BooleanAttr(
            "hrcZimbraServerPasswordSync",
            _("Password sync"),
            default=True,
            description=_("Synchronize user passwords with Zimbra"),
        ),
        BooleanAttr(
            "hrcZimbraServerKeepUnknownAliases",
            _("Keep unknown aliases"),
            default=False,
            description=_("Preserve aliases that are unknown to the directory"),
        ),
        StringAttr(
            "hrcZimbraServerIdAttribute",
            _("ID attribute"),
            description=_("LDAP attribute used as Zimbra identifier"),
        ),
    )
    defaults = Section(
        _("Defaults"),
        StringAttr("hrcZimbraDomain", _("Domain"), description=_("Default Zimbra domain")),
        StringAttr(
            "hrcZimbraDomainCOS",
            _("Class of Service"),
            description=_("Default Class of Service (COS) for Zimbra accounts"),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Zimbra plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("server", ZimbraServiceTab),),
    )


__all__ = [
    "CREATION_TYPES",
    "DELETION_TYPES",
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "ZimbraServiceTab",
    "mail_servers",
    "plugin",
]
