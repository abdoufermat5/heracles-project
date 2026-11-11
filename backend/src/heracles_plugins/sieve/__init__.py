"""Sieve plugin: ManageSieve service tab on servers."""

from __future__ import annotations

from heracles.attributes import IntAttr, SelectAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "sieve"

CONNECT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", _("None")),
    ("/ssl", _("SSL")),
    ("/tls", _("TLS")),
    ("/notls", _("No TLS")),
    ("none", _("None")),
    ("ssl", _("SSL")),
    ("tls", _("TLS")),
    ("notls", _("No TLS")),
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


class SieveServiceTab(Tab):
    """ManageSieve service tab on servers."""

    name = "sieve"
    acl_key = "serviceSieve"
    label = _("Sieve")
    description = _("ManageSieve script service")
    optional = True
    object_classes = ("hrcSieveServer",)

    connection = Section(
        _("Connection"),
        StringAttr(
            "hrcSieveConnectURL",
            _("Connect URL"),
            description=_("ManageSieve server URL or host name"),
        ),
        IntAttr(
            "hrcSieveConnectPort",
            _("Connect port"),
            min=1,
            max=65535,
            description=_("ManageSieve connection port"),
        ),
        SelectAttr(
            "hrcSieveConnectOptions",
            _("Connection options"),
            options=CONNECT_OPTIONS,
            default="",
        ),
    )
    admin = Section(
        _("Administration"),
        StringAttr(
            "hrcSieveAdmin",
            _("Admin user"),
            description=_("ManageSieve administrator login"),
        ),
        StringAttr(
            "hrcSievePassword",
            _("Admin password"),
            description=_("ManageSieve administrator password"),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Sieve plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("server", SieveServiceTab),),
    )


__all__ = [
    "CONNECT_OPTIONS",
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "SieveServiceTab",
    "mail_servers",
    "plugin",
]
