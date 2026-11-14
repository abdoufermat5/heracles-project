"""Mail transport plugin: MTA service tab on servers."""

from __future__ import annotations

from heracles.attributes import CompositeAttr, EmailAttr, IntAttr, ListAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "mail_transport"

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


class MailTransportServiceTab(Tab):
    """Mail transfer agent service tab on servers."""

    name = "mail_transport"
    acl_key = "serviceMailTransport"
    label = _("Mail transport")
    description = _("Mail transfer agent service")
    optional = True
    object_classes = ("hrcMtaServer",)

    general = Section(
        _("General"),
        StringAttr(
            "hrcMtaMyHostname",
            _("Host name"),
            description=_(
                "The myhostname parameter specifies the internet host name of this mail system"
            ),
        ),
        StringAttr(
            "hrcMtaMyDomain",
            _("Domain"),
            description=_("The mydomain parameter specifies the local internet domain name"),
        ),
        StringAttr(
            "hrcMtaMyDestinations",
            _("Destinations"),
            description=_(
                "The mydestination parameter specifies the list of domains delivered locally"
            ),
        ),
    )
    limits = Section(
        _("Limits"),
        IntAttr(
            "hrcMtaHeaderSizeLimit",
            _("Header size limit"),
            min=0,
            description=_(
                "Limits the amount of memory devoted to storing a message header in bytes"
            ),
        ),
        IntAttr(
            "hrcMtaMailboxSizeLimit",
            _("Mailbox size limit"),
            min=0,
            description=_("Limits the size of any mailbox in bytes"),
        ),
        IntAttr(
            "hrcMtaMessageSizeLimit",
            _("Message size limit"),
            min=0,
            description=_("Limits the total size of a message in bytes"),
        ),
    )
    tables = Section(
        _("Tables"),
        ListAttr(
            "hrcMtaTransportTable",
            _("Transport table"),
            item=CompositeAttr(
                "transport_entry",
                _("Transport entry"),
                [
                    StringAttr("hrcTransportTableMatch", _("Match")),
                    StringAttr("transport", _("Transport")),
                    StringAttr("nexthop", _("Next hop")),
                ],
                separator=";",
            ),
        ),
        ListAttr(
            "hrcMtaCatchallTable",
            _("Catchall table"),
            item=CompositeAttr(
                "catchall_entry",
                _("Catchall entry"),
                [
                    StringAttr("hrcCatchallTableDomain", _("Domain")),
                    EmailAttr("hrcCatchallTableRecipient", _("Recipient")),
                ],
                separator=";",
            ),
        ),
        ListAttr(
            "hrcMtaDomainAliasTable",
            _("Domain alias table"),
            item=CompositeAttr(
                "alias_entry",
                _("Domain alias entry"),
                [
                    StringAttr("hrcDomainAliasTableFrom", _("From domain")),
                    StringAttr("hrcDomainAliasTableTo", _("To domain")),
                ],
                separator=";",
            ),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Mail transport plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("server", MailTransportServiceTab),),
    )


__all__ = [
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "MailTransportServiceTab",
    "mail_servers",
    "plugin",
]
