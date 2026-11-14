"""Spam filter plugin: spam filter service on servers and spam settings on users."""

from __future__ import annotations

from heracles.attributes import (
    BooleanAttr,
    CompositeAttr,
    ListAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
)
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, NoSuchObjectError, Scope
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "spam_filter"

REQUIRED_SCORES: tuple[tuple[str, str], ...] = (
    ("1.0", "1.0"),
    ("2.0", "2.0"),
    ("3.0", "3.0"),
    ("4.0", "4.0"),
    ("5.0", "5.0"),
    ("6.0", "6.0"),
    ("7.0", "7.0"),
    ("8.0", "8.0"),
    ("9.0", "9.0"),
    ("10.0", "10.0"),
    ("1", "1"),
    ("2", "2"),
    ("3", "3"),
    ("4", "4"),
    ("5", "5"),
    ("6", "6"),
    ("7", "7"),
    ("8", "8"),
    ("9", "9"),
    ("10", "10"),
)

SPAM_DIRECTIVES: tuple[tuple[str, str], ...] = (
    ("required_score", _("Required score")),
    ("whitelist_from", _("Whitelist from")),
    ("blacklist_from", _("Blacklist from")),
    ("score", _("Score")),
    ("rewrite_header", _("Rewrite header")),
    ("report_safe", _("Report safe")),
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


class SpamFilterServiceTab(Tab):
    """Spam filter service tab on servers."""

    name = "spam_filter"
    acl_key = "serviceSpamFilter"
    label = _("Spam filter")
    description = _("Spam filtering service")
    optional = True
    object_classes = ("hrcSpamFilterServer",)

    scoring = Section(
        _("Scoring & network"),
        StringAttr(
            "hrcSpamFilterRewriteHeader",
            _("Rewrite header"),
            description=_("Subject header prefix for spam messages"),
        ),
        SelectAttr(
            "hrcSpamFilterRequiredScore",
            _("Required score"),
            options=REQUIRED_SCORES,
            default="5.0",
            description=_("Score required to flag an email as spam"),
        ),
        StringAttr(
            "hrcSpamFilterTrustedNetworks",
            _("Trusted networks"),
            description=_("Networks or hosts considered trusted"),
        ),
    )
    plugins = Section(
        _("Filter plugins"),
        BooleanAttr("hrcSpamFilterEnableBayes", _("Enable Bayes filter"), default=True),
        BooleanAttr("hrcSpamFilterBayesAutolearn", _("Bayes auto-learn"), default=True),
        BooleanAttr("hrcSpamFilterEnableRblCheck", _("Enable RBL checks"), default=True),
        BooleanAttr(
            "hrcSpamFilterEnableDistributedCheck", _("Enable distributed check"), default=False
        ),
        BooleanAttr("hrcSpamFilterEnableChecksumCheck", _("Enable checksum check"), default=False),
        BooleanAttr(
            "hrcSpamFilterEnableCollaborativeCheck", _("Enable collaborative check"), default=False
        ),
    )
    rules = Section(
        _("Custom rule"),
        StringAttr("hrcSpamFilterRuleName", _("Rule name"), description=_("Custom rule name")),
        TextAttr(
            "hrcSpamFilterRuleDesc",
            _("Rule description"),
            description=_("Custom rule description"),
        ),
    )


class SpamFilterUserTab(Tab):
    """Spam filter tab on users."""

    name = "spam_filter"
    acl_key = "spamFilterAccount"
    label = _("Spam filter")
    description = _("User spam filtering settings")
    optional = True
    object_classes = ("hrcSpamFilterUser",)

    settings = Section(
        _("Spam filter rules"),
        ListAttr(
            "hrcSpamFilterRules",
            _("Rules"),
            item=CompositeAttr(
                "rule",
                _("Rule"),
                [
                    SelectAttr(
                        "hrcSpamFilterRules_directive",
                        _("Directive"),
                        options=SPAM_DIRECTIVES,
                    ),
                    StringAttr(
                        "hrcSpamFilterRules_value",
                        _("Value"),
                        description=_("Rule value or pattern"),
                    ),
                ],
                separator=" ",
            ),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Spam filter plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(
            TabAttachment("server", SpamFilterServiceTab),
            TabAttachment("user", SpamFilterUserTab),
        ),
    )


__all__ = [
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "REQUIRED_SCORES",
    "SPAM_DIRECTIVES",
    "SpamFilterServiceTab",
    "SpamFilterUserTab",
    "mail_servers",
    "plugin",
]
