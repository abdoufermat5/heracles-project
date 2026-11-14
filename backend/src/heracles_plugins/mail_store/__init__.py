"""Mail store plugin: IMAP service tab on servers."""

from __future__ import annotations

from heracles.attributes import BooleanAttr, IntAttr, SelectAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles_plugins._secrets import CleartextSecretAttr

PLUGIN_NAME = "mail_store"

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


class MailStoreServiceTab(Tab):
    """IMAP mail store service tab on servers."""

    name = "mail_store"
    acl_key = "serviceMailStore"
    label = _("Mail store")
    description = _("IMAP mail store service")
    optional = True
    object_classes = ("hrcMailStoreServer",)

    connection = Section(
        _("Connection"),
        StringAttr(
            "hrcMailStoreConnectURL",
            _("Connect URL"),
            description=_("IMAP mail store server URL or host name"),
        ),
        IntAttr(
            "hrcMailStoreConnectPort",
            _("Connect port"),
            min=1,
            max=65535,
            description=_("IMAP mail store connection port"),
        ),
        SelectAttr(
            "hrcMailStoreConnectOptions1",
            _("Connection options 1"),
            options=CONNECT_OPTIONS_1,
            default="",
        ),
        SelectAttr(
            "hrcMailStoreConnectOptions2",
            _("Connection options 2"),
            options=CONNECT_OPTIONS_2,
            default="",
        ),
    )
    admin = Section(
        _("Administration"),
        StringAttr(
            "hrcMailStoreAdmin",
            _("Admin user"),
            description=_("Mail store administrator login"),
        ),
        CleartextSecretAttr(
            "hrcMailStorePassword",
            _("Admin password"),
            description=_("Mail store administrator password (leave empty to keep it)"),
        ),
    )
    options = Section(
        _("Options"),
        BooleanAttr(
            "hrcMailStoreUseSlashes",
            _("Use slashes"),
            default=False,
            description=_("Use / as hierarchy separator instead of . in mailbox names"),
        ),
        StringAttr(
            "hrcMailStoreAutocreateFolders",
            _("Autocreate folders"),
            description=_(
                "Comma-separated list of folders to automatically create for new mailboxes"
            ),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Mail store plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("server", MailStoreServiceTab),),
    )


__all__ = [
    "CONNECT_OPTIONS_1",
    "CONNECT_OPTIONS_2",
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "MailStoreServiceTab",
    "mail_servers",
    "plugin",
]
