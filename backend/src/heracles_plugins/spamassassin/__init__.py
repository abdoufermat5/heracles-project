"""SpamAssassin plugin: spam filter service on servers and spam settings on users."""

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

PLUGIN_NAME = "spamassassin"

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


class SpamAssassinServiceTab(Tab):
    """SpamAssassin service tab on servers."""

    name = "spamassassin"
    acl_key = "serviceSpamAssassin"
    label = _("SpamAssassin")
    description = _("SpamAssassin spam filter service")
    optional = True
    object_classes = ("hrcSpamAssassinServer",)

    scoring = Section(
        _("Scoring & network"),
        StringAttr(
            "hrcSpamAssassinRewriteHeader",
            _("Rewrite header"),
            description=_("Subject header prefix for spam messages"),
        ),
        SelectAttr(
            "hrcSpamAssassinRequiredScore",
            _("Required score"),
            options=REQUIRED_SCORES,
            default="5.0",
            description=_("Score required to flag an email as spam"),
        ),
        StringAttr(
            "hrcSpamAssassinTrustedNetworks",
            _("Trusted networks"),
            description=_("Networks or hosts considered trusted"),
        ),
    )
    plugins = Section(
        _("Filter plugins"),
        BooleanAttr("hrcSpamAssassinEnableBayes", _("Enable Bayes filter"), default=True),
        BooleanAttr("hrcSpamAssassinBayesAutolearn", _("Bayes auto-learn"), default=True),
        BooleanAttr("hrcSpamAssassinEnableRblCheck", _("Enable RBL checks"), default=True),
        BooleanAttr("hrcSpamAssassinEnableRazor", _("Enable Razor"), default=False),
        BooleanAttr("hrcSpamAssassinEnableDcc", _("Enable DCC"), default=False),
        BooleanAttr("hrcSpamAssassinEnablePyzor", _("Enable Pyzor"), default=False),
    )
    rules = Section(
        _("Custom rule"),
        StringAttr("hrcSpamAssassinRuleName", _("Rule name"), description=_("Custom rule name")),
        TextAttr(
            "hrcSpamAssassinRuleDesc",
            _("Rule description"),
            description=_("Custom rule description"),
        ),
    )


class SpamAssassinUserTab(Tab):
    """SpamAssassin tab on users."""

    name = "spamassassin"
    acl_key = "spamAssassinAccount"
    label = _("SpamAssassin")
    description = _("Spam filtering settings")
    description = _("User SpamAssassin spam filter settings")
    optional = True
    object_classes = ("hrcSpamAssassinUser",)

    settings = Section(
        _("SpamAssassin rules"),
        ListAttr(
            "hrcSpamAssassinRules",
            _("Rules"),
            item=CompositeAttr(
                "rule",
                _("Rule"),
                [
                    SelectAttr(
                        "hrcSpamAssassinRules_directive",
                        _("Directive"),
                        options=SPAM_DIRECTIVES,
                    ),
                    StringAttr(
                        "hrcSpamAssassinRules_value",
                        _("Value"),
                        description=_("Rule value or pattern"),
                    ),
                ],
                separator=" ",
            ),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the SpamAssassin plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(
            TabAttachment("server", SpamAssassinServiceTab),
            TabAttachment("user", SpamAssassinUserTab),
        ),
    )


__all__ = [
    "MAIL_SERVICE_CLASSES",
    "PLUGIN_NAME",
    "REQUIRED_SCORES",
    "SPAM_DIRECTIVES",
    "SpamAssassinServiceTab",
    "SpamAssassinUserTab",
    "mail_servers",
    "plugin",
]
