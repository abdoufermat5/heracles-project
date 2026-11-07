"""Postfix plugin: MTA service tab on servers."""

from __future__ import annotations

from heracles.attributes import CompositeAttr, EmailAttr, IntAttr, ListAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "postfix"

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


class PostfixServiceTab(Tab):
    """Postfix MTA service tab on servers."""

    name = "postfix"
    acl_key = "servicePostfix"
    label = _("Postfix")
    description = _("Postfix mail transfer agent service")
    optional = True
    object_classes = ("fdPostfixServer",)

    general = Section(
        _("General"),
        StringAttr(
            "postfixMyHostname",
            _("Host name"),
            description=_(
                "The myhostname parameter specifies the internet host name of this mail system"
            ),
        ),
        StringAttr(
            "postfixMyDomain",
            _("Domain"),
            description=_("The mydomain parameter specifies the local internet domain name"),
        ),
        StringAttr(
            "postfixMyDestinations",
            _("Destinations"),
            description=_(
                "The mydestination parameter specifies the list of domains delivered locally"
            ),
        ),
    )
    limits = Section(
        _("Limits"),
        IntAttr(
            "postfixHeaderSizeLimit",
            _("Header size limit"),
            min=0,
            description=_(
                "Limits the amount of memory devoted to storing a message header in bytes"
            ),
        ),
        IntAttr(
            "postfixMailboxSizeLimit",
            _("Mailbox size limit"),
            min=0,
            description=_("Limits the size of any mailbox in bytes"),
        ),
        IntAttr(
            "postfixMessageSizeLimit",
            _("Message size limit"),
            min=0,
            description=_("Limits the total size of a message in bytes"),
        ),
    )
    tables = Section(
        _("Tables"),
        ListAttr(
            "fdPostfixTransportTable",
            _("Transport table"),
            item=CompositeAttr(
                "transport_entry",
                _("Transport entry"),
                [
                    StringAttr("fdTransportTableMatch", _("Match")),
                    StringAttr("transport", _("Transport")),
                    StringAttr("nexthop", _("Next hop")),
                ],
                separator=";",
            ),
        ),
        ListAttr(
            "fdPostfixCatchallTable",
            _("Catchall table"),
            item=CompositeAttr(
                "catchall_entry",
                _("Catchall entry"),
                [
                    StringAttr("fdCatchallTableDomain", _("Domain")),
                    EmailAttr("fdCatchallTableRecipient", _("Recipient")),
                ],
                separator=";",
            ),
        ),
        ListAttr(
            "fdPostfixDomainAliasTable",
            _("Domain alias table"),
            item=CompositeAttr(
                "alias_entry",
                _("Domain alias entry"),
                [
                    StringAttr("fdDomainAliasTableFrom", _("From domain")),
                    StringAttr("fdDomainAliasTableTo", _("To domain")),
                ],
                separator=";",
            ),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Postfix plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("server", PostfixServiceTab),),
    )


__all__ = [
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "PostfixServiceTab",
    "mail_servers",
    "plugin",
]
