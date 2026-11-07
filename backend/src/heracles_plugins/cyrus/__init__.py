"""Cyrus plugin: IMAP service tab on servers."""

from __future__ import annotations

from heracles.attributes import BooleanAttr, IntAttr, SelectAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "cyrus"

CONNECT_OPTIONS_1: tuple[tuple[str, str], ...] = (
    ("", _("None")),
    ("/ssl", _("SSL")),
    ("/tls", _("TLS")),
    ("/notls", _("No TLS")),
    ("none", _("None")),
    ("ssl", _("SSL")),
    ("tls", _("TLS")),
    ("notls", _("No TLS")),
)

CONNECT_OPTIONS_2: tuple[tuple[str, str], ...] = (
    ("", _("None")),
    ("/novalidate-cert", _("Do not validate certificate")),
    ("/validate-cert", _("Validate certificate")),
    ("/readonly", _("Read-only")),
    ("/debug", _("Debug")),
    ("none", _("None")),
    ("novalidate-cert", _("Do not validate certificate")),
    ("validate-cert", _("Validate certificate")),
    ("readonly", _("Read-only")),
    ("debug", _("Debug")),
)

MAIL_SERVICE_CLASSES: tuple[str, ...] = (
    "fdDovecotServer",
    "fdCyrusServer",
    "fdPostfixServer",
    "fdSieveServer",
    "goSpamServer",
    "fdZimbraServer",
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


class CyrusServiceTab(Tab):
    """Cyrus IMAP service tab on servers."""

    name = "cyrus"
    acl_key = "serviceCyrus"
    label = _("Cyrus")
    description = _("Cyrus IMAP service")
    optional = True
    object_classes = ("fdCyrusServer",)

    connection = Section(
        _("Connection"),
        StringAttr(
            "cyrusConnectURL",
            _("Connect URL"),
            description=_("Cyrus IMAP server URL or host name"),
        ),
        IntAttr(
            "cyrusConnectPort",
            _("Connect port"),
            min=1,
            max=65535,
            description=_("Cyrus IMAP connection port"),
        ),
        SelectAttr(
            "cyrusConnectOptions1",
            _("Connection options 1"),
            options=CONNECT_OPTIONS_1,
            default="",
        ),
        SelectAttr(
            "cyrusConnectOptions2",
            _("Connection options 2"),
            options=CONNECT_OPTIONS_2,
            default="",
        ),
    )
    admin = Section(
        _("Administration"),
        StringAttr(
            "fdCyrusAdmin",
            _("Admin user"),
            description=_("Cyrus administrator login"),
        ),
        StringAttr(
            "fdCyrusPassword",
            _("Admin password"),
            description=_("Cyrus administrator password"),
        ),
    )
    options = Section(
        _("Options"),
        BooleanAttr(
            "fdCyrusUseSlashes",
            _("Use slashes"),
            default=False,
            description=_("Use / as hierarchy separator instead of . in mailbox names"),
        ),
        StringAttr(
            "fdCyrusAutocreateFolders",
            _("Autocreate folders"),
            description=_(
                "Comma-separated list of folders to automatically create for new mailboxes"
            ),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Cyrus plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("server", CyrusServiceTab),),
    )


__all__ = [
    "CONNECT_OPTIONS_1",
    "CONNECT_OPTIONS_2",
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "CyrusServiceTab",
    "mail_servers",
    "plugin",
]
