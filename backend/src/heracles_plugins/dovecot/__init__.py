"""Dovecot plugin: IMAP/POP3 service tab on servers."""

from __future__ import annotations

from heracles.attributes import IntAttr, SelectAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "dovecot"

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


class DovecotServiceTab(Tab):
    """Dovecot service tab on servers."""

    name = "dovecot"
    acl_key = "serviceDovecot"
    label = _("Dovecot")
    description = _("Dovecot IMAP/POP3 service")
    optional = True
    object_classes = ("hrcDovecotServer",)

    connection = Section(
        _("Connection"),
        StringAttr(
            "hrcDovecotConnectURL",
            _("Connect URL"),
            description=_("Dovecot server URL or host name"),
        ),
        IntAttr(
            "hrcDovecotConnectPort",
            _("Connect port"),
            min=1,
            max=65535,
            description=_("Dovecot connection port"),
        ),
        SelectAttr(
            "hrcDovecotConnectOptions1",
            _("Connection options 1"),
            options=CONNECT_OPTIONS_1,
            default="",
        ),
        SelectAttr(
            "hrcDovecotConnectOptions2",
            _("Connection options 2"),
            options=CONNECT_OPTIONS_2,
            default="",
        ),
    )
    admin = Section(
        _("Administration"),
        StringAttr(
            "hrcDovecotAdmin",
            _("Admin user"),
            description=_("Dovecot administrator login"),
        ),
        StringAttr(
            "hrcDovecotPassword",
            _("Admin password"),
            description=_("Dovecot administrator password"),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Dovecot plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("server", DovecotServiceTab),),
    )


__all__ = [
    "CONNECT_OPTIONS_1",
    "CONNECT_OPTIONS_2",
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "DovecotServiceTab",
    "mail_servers",
    "plugin",
]
