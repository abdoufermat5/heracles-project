"""Mail plugin: mail accounts, group mail, and temporary mail aliases."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, cast, overload

from heracles.attributes import (
    Attribute,
    BooleanAttr,
    DateAttr,
    DepartmentAttr,
    EmailAttr,
    HiddenAttr,
    IntAttr,
    ListAttr,
    StringAttr,
    TextAttr,
    ValidationError,
)
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import NoSuchObjectError, Scope
from heracles.ldap.filter import escape_filter_value
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "mail"
CN_RE = r"[^\s,=+<>#;\"\\][^,=+<>#;\"\\]*"


@dataclass(slots=True)
class MailSettings:
    """Settings of the Mail plugin."""

    mail_template: str | None = None


def settings_of(ctx: TabContext) -> MailSettings:
    """Retrieve the MailSettings from the tab context."""
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, MailSettings) else MailSettings()


def virtual[A: Attribute[Any]](attr: A) -> A:
    """Mark an attribute as virtual (never written to the directory entry)."""
    attr.stored = False
    return attr


# --------------------------------------------------------------- attributes


class UnixTimestampDateAttr(DateAttr):
    """Calendar date stored in LDAP as a Unix timestamp in seconds (as text)."""

    def from_ldap(self, values: list[bytes]) -> date | None:
        if not values:
            return None
        try:
            text = values[0].decode("ascii").strip()
            ts = int(text)
            return datetime.fromtimestamp(ts, tz=UTC).date()
        except (ValueError, UnicodeDecodeError, OSError, OverflowError):
            return None

    def to_ldap(self, value: date | None) -> list[bytes]:
        if value is None:
            return []
        ts = int(datetime.combine(value, time.min, tzinfo=UTC).timestamp())
        return [str(ts).encode("ascii")]

    def from_json(self, data: object) -> date | None:
        if data is None or data == "":
            return None
        if isinstance(data, (int, float)):
            try:
                return datetime.fromtimestamp(int(data), tz=UTC).date()
            except (ValueError, OSError, OverflowError):
                raise ValidationError(_("Expected a date (YYYY-MM-DD).")) from None
        if isinstance(data, str) and data.strip().isdigit():
            try:
                return datetime.fromtimestamp(int(data.strip()), tz=UTC).date()
            except (ValueError, OSError, OverflowError):
                raise ValidationError(_("Expected a date (YYYY-MM-DD).")) from None
        return super().from_json(data)


# ------------------------------------------------------------------ helpers


def fold_ascii(text: str) -> str:
    """ASCII-fold and lowercase text."""
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )


def parse_delivery_mode(raw: str | None) -> tuple[dict[str, bool], str]:
    """Parse delivery mode string into virtual flags and unknown letters."""
    if not raw:
        return {
            "flag_vacation": False,
            "flag_localonly": False,
            "flag_ownmailbox": False,
        }, ""
    text = raw.strip()
    content = text[1:-1] if text.startswith("[") and text.endswith("]") else text
    flags = {
        "flag_vacation": "V" in content,
        "flag_localonly": "L" in content,
        "flag_ownmailbox": "I" in content,
    }
    unknown = "".join(c for c in content if c not in ("V", "L", "I"))
    return flags, unknown


def format_delivery_mode(flags: Mapping[str, Any], original_mode: str | None = None) -> str:
    """Format delivery flags into `[letters]` preserving unknown letters and order."""
    active_flags = {
        "V": bool(flags.get("flag_vacation")),
        "L": bool(flags.get("flag_localonly")),
        "I": bool(flags.get("flag_ownmailbox")),
    }
    chars: list[str] = []
    seen: set[str] = set()
    if original_mode:
        text = original_mode.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        for c in text:
            if c in active_flags:
                if active_flags[c] and c not in seen:
                    chars.append(c)
                    seen.add(c)
            elif c not in seen:
                chars.append(c)
                seen.add(c)
    for c in ("V", "L", "I"):
        if active_flags[c] and c not in seen:
            chars.append(c)
            seen.add(c)
    body = "".join(chars)
    return f"[{body}]"


def check_mail_uniqueness(
    ctx: TabContext,
    *,
    mail_attr: str = "mail",
    alt_attr: str | None = "gosaMailAlternateAddress",
) -> None:
    """Verify that primary mail and alternate addresses are unique across the directory."""
    primary_mail: str | None = None
    raw_mail = ctx.values.get(mail_attr)
    if isinstance(raw_mail, str) and raw_mail.strip():
        primary_mail = raw_mail.strip()

    alt_addresses: list[str] = []
    if alt_attr and alt_attr in ctx.values:
        raw_alts = ctx.values.get(alt_attr)
        if isinstance(raw_alts, list):
            for item in cast("list[object]", raw_alts):
                if isinstance(item, str) and item.strip():
                    alt_addresses.append(item.strip())

    if primary_mail and alt_attr:
        p_lower = primary_mail.lower()
        for a in alt_addresses:
            if a.lower() == p_lower:
                ctx.error(
                    alt_attr,
                    _("Alternate address '{addr}' cannot be the same as primary email.").format(
                        addr=a
                    ),
                )
                break

    if alt_attr:
        seen_alts: set[str] = set()
        for a in alt_addresses:
            al = a.lower()
            if al in seen_alts:
                ctx.error(
                    alt_attr,
                    _("Duplicate alternate address: '{addr}'.").format(addr=a),
                )
                break
            seen_alts.add(al)

    to_query: list[str] = []
    if primary_mail:
        to_query.append(primary_mail)
    for a in alt_addresses:
        if a not in to_query:
            to_query.append(a)

    if not to_query:
        return

    terms = [
        f"(|(mail={escape_filter_value(addr)})(gosaMailAlternateAddress={escape_filter_value(addr)}))"
        for addr in to_query
    ]
    flt = f"(|{''.join(terms)})"
    try:
        found = ctx.directory.search(
            ctx.directory.base_dn,
            flt,
            Scope.SUBTREE,
            ["mail", "gosaMailAlternateAddress"],
        )
    except NoSuchObjectError:
        return

    current_dn = dnlib.normalize(ctx.dn) if ctx.dn else None

    for entry in found:
        if current_dn and dnlib.normalize(entry.dn) == current_dn:
            continue
        entry_mails = {m.strip().lower() for m in entry.texts("mail") if m.strip()}
        entry_alts = {
            a.strip().lower() for a in entry.texts("gosaMailAlternateAddress") if a.strip()
        }
        taken = entry_mails | entry_alts

        if primary_mail and primary_mail.lower() in taken:
            ctx.error(
                mail_attr,
                _("Email address '{mail}' is already in use.").format(mail=primary_mail),
            )
        if alt_attr:
            for a in alt_addresses:
                if a.lower() in taken:
                    ctx.error(
                        alt_attr,
                        _("Alternate address '{addr}' is already in use.").format(addr=a),
                    )


# --------------------------------------------------------------------- tabs


class UserMailTab(Tab):
    """Mail account tab on a user."""

    name = "mail"
    acl_key = "mailAccount"
    label = _("Mail")
    optional = True
    object_classes = ("gosaMailAccount",)

    account = Section(
        _("Account"),
        EmailAttr("mail", _("Email"), required=True),
        StringAttr("gosaMailServer", _("Mail server")),
        IntAttr("gosaMailQuota", _("Quota (MB)"), min=0),
        ListAttr(
            "gosaMailAlternateAddress",
            _("Alternate addresses"),
            EmailAttr("alternateAddress", _("Alternate address")),
        ),
        ListAttr(
            "gosaMailForwardingAddress",
            _("Forwarding addresses"),
            EmailAttr("forwardingAddress", _("Forwarding address")),
        ),
    )
    delivery = Section(
        _("Delivery"),
        virtual(BooleanAttr("flag_localonly", _("Only allow local delivery"), default=False)),
        virtual(BooleanAttr("flag_ownmailbox", _("Keep a copy in own mailbox"), default=False)),
        virtual(BooleanAttr("flag_vacation", _("Vacation message active"), default=False)),
        HiddenAttr("gosaMailDeliveryMode", "gosaMailDeliveryMode"),
    )
    vacation = Section(
        _("Vacation"),
        UnixTimestampDateAttr("gosaVacationStart", _("Vacation start date")),
        UnixTimestampDateAttr("gosaVacationStop", _("Vacation stop date")),
        TextAttr("gosaVacationMessage", _("Vacation message")),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        mode = ctx.values.get("gosaMailDeliveryMode")
        flags, _unk = parse_delivery_mode(str(mode) if mode else None)
        ctx.values.update(flags)
        if not flags.get("flag_vacation"):
            ctx.values["gosaVacationStart"] = None
            ctx.values["gosaVacationStop"] = None
            ctx.values["gosaVacationMessage"] = None

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        # Default domain helper
        if ctx.activating and not ctx.values.get("mail"):
            settings = settings_of(ctx)
            if settings.mail_template:
                main = ctx.main_values()
                uid = fold_ascii(str(main.get("uid") or ""))
                given = fold_ascii(str(main.get("givenName") or ""))
                sn = fold_ascii(str(main.get("sn") or ""))
                try:
                    generated = settings.mail_template.format(
                        uid=uid,
                        givenName=given,
                        given_name=given,
                        sn=sn,
                    ).strip()
                    if generated:
                        ctx.values["mail"] = generated
                except (KeyError, ValueError, IndexError):
                    pass

        # Sync mail attribute between main and mail tab
        mail_val = ctx.values.get("mail")
        main_tab = ctx.tabs.get(ctx.info.main_tab.name)
        if main_tab is not None and "mail" in main_tab.values:
            if mail_val and not main_tab.values.get("mail"):
                main_tab.values["mail"] = mail_val
            elif not mail_val and main_tab.values.get("mail"):
                ctx.values["mail"] = main_tab.values["mail"]

        # Parse delivery mode if explicitly touched
        if ctx.was_touched("gosaMailDeliveryMode"):
            mode_raw = ctx.values.get("gosaMailDeliveryMode")
            if isinstance(mode_raw, str):
                parsed_flags, _unk = parse_delivery_mode(mode_raw)
                for flag_name, flag_val in parsed_flags.items():
                    if not ctx.was_touched(flag_name):
                        ctx.values[flag_name] = flag_val

        # Rebuild gosaMailDeliveryMode
        orig_mode = ctx.original_values().get("gosaMailDeliveryMode") or ctx.values.get(
            "gosaMailDeliveryMode"
        )
        ctx.values["gosaMailDeliveryMode"] = format_delivery_mode(
            ctx.values, str(orig_mode) if orig_mode else None
        )

        # Vacation settings handling
        if not ctx.values.get("flag_vacation"):
            ctx.values["gosaVacationStart"] = None
            ctx.values["gosaVacationStop"] = None
            ctx.values["gosaVacationMessage"] = None
        else:
            start = ctx.values.get("gosaVacationStart")
            stop = ctx.values.get("gosaVacationStop")
            if isinstance(start, date) and isinstance(stop, date) and stop < start:
                ctx.error(
                    "gosaVacationStop",
                    _("Vacation stop date must be on or after start date."),
                )

        # Uniqueness check
        check_mail_uniqueness(ctx)


class GroupMailTab(Tab):
    """Mail tab on a group."""

    name = "mail"
    acl_key = "mailGroup"
    label = _("Mail")
    optional = True
    object_classes = ("fdGroupMail",)

    account = Section(
        _("Account"),
        EmailAttr("mail", _("Email"), required=True),
        StringAttr("gosaMailServer", _("Mail server")),
        ListAttr(
            "gosaMailAlternateAddress",
            _("Alternate addresses"),
            EmailAttr("alternateAddress", _("Alternate address")),
        ),
        ListAttr(
            "gosaMailForwardingAddress",
            _("Forwarding addresses"),
            EmailAttr("forwardingAddress", _("Forwarding address")),
        ),
        BooleanAttr("fdGroupMailLocalOnly", _("Only allow local delivery"), default=False),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        check_mail_uniqueness(ctx)


# ------------------------------------------------------------- alias types


class MailAliasDistribution(ObjectType):
    """Temporary mail distribution alias."""

    name = "mail_alias_distribution"
    label = _("Temporary mail distribution")
    label_plural = _("Temporary mail distributions")
    icon = "mail"
    category = "mail"
    acl_category = "alias"
    filter = "(objectClass=mailAliasDistribution)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=alias"
    columns = ("cn", "mail", "description")
    search_attrs = ("cn", "mail", "description")

    class Main(Tab):
        name = "main"
        acl_key = "mailAliasDistribution"
        label = _("Temporary mail distribution")
        object_classes = ("mailAliasDistribution",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=CN_RE),
            TextAttr("description", _("Description")),
        )
        distribution = Section(
            _("Distribution"),
            EmailAttr("mail", _("Email"), required=True),
            ListAttr(
                "gosaMailAlternateAddress",
                _("Alternate addresses"),
                EmailAttr("alternateAddress", _("Alternate address")),
            ),
            StringAttr("gosaMailServer", _("Mail server")),
            UnixTimestampDateAttr("aliasExpirationDate", _("Expiration date")),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            check_mail_uniqueness(ctx)


class MailAliasRedirection(ObjectType):
    """Temporary mail redirection alias."""

    name = "mail_alias_redirection"
    label = _("Temporary mail redirection")
    label_plural = _("Temporary mail redirections")
    icon = "mail"
    category = "mail"
    acl_category = "alias"
    filter = "(objectClass=mailAliasRedirection)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=alias"
    columns = ("cn", "mail", "description")
    search_attrs = ("cn", "mail", "description")

    class Main(Tab):
        name = "main"
        acl_key = "mailAliasRedirection"
        label = _("Temporary mail redirection")
        object_classes = ("mailAliasRedirection",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=CN_RE),
            TextAttr("description", _("Description")),
        )
        redirection = Section(
            _("Redirection"),
            EmailAttr("mail", _("Email"), required=True),
            ListAttr(
                "gosaMailForwardingAddress",
                _("Forwarding addresses"),
                EmailAttr("forwardingAddress", _("Forwarding address")),
                min_length=1,
                required=True,
            ),
            UnixTimestampDateAttr("aliasExpirationDate", _("Expiration date")),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            check_mail_uniqueness(ctx, alt_attr=None)


# ------------------------------------------------------------------ plugin


class ConditionalTypes(Sequence[type[ObjectType]]):
    """Sequence of alias types conditionally available when their objectClasses exist."""

    def __init__(self, alias_types: Sequence[type[ObjectType]]) -> None:
        self._alias_types = tuple(alias_types)
        self.available: set[str] | None = None

    def _current(self) -> tuple[type[ObjectType], ...]:
        if self.available is not None and not {
            "mailaliasredirection",
            "mailaliasdistribution",
        }.issubset(self.available):
            return ()
        return self._alias_types

    def __len__(self) -> int:
        return len(self._current())

    def __iter__(self) -> Iterator[type[ObjectType]]:
        return iter(self._current())

    @overload
    def __getitem__(self, index: int) -> type[ObjectType]: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[type[ObjectType]]: ...

    def __getitem__(self, index: int | slice) -> type[ObjectType] | Sequence[type[ObjectType]]:
        return self._current()[index]


class MailPlugin(Plugin):
    """Heracles Mail plugin with conditional alias type registration."""

    __slots__ = ("_cond_types",)

    def __init__(
        self,
        name: str,
        version: str,
        cond_types: ConditionalTypes,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, version, types=cond_types, **kwargs)
        object.__setattr__(self, "_cond_types", cond_types)

    def missing_object_classes(self, available: set[str]) -> list[str]:
        self._cond_types.available = available
        return super().missing_object_classes(available)


def plugin() -> Plugin:
    """Entry point of the Mail plugin."""
    cond_types = ConditionalTypes((MailAliasDistribution, MailAliasRedirection))
    return MailPlugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        cond_types=cond_types,
        tabs=(
            TabAttachment("user", UserMailTab),
            TabAttachment("group", GroupMailTab),
        ),
        required_object_classes=("gosaMailAccount",),
        settings=MailSettings(),
    )


def alias_plugin() -> Plugin:
    """Alternative entry point registering alias types as a standalone plugin."""
    return Plugin(
        name="mail_alias",
        version="0.1.0",
        types=(MailAliasDistribution, MailAliasRedirection),
        required_object_classes=("mailAliasRedirection", "mailAliasDistribution"),
    )


__all__ = [
    "CN_RE",
    "PLUGIN_NAME",
    "GroupMailTab",
    "MailAliasDistribution",
    "MailAliasRedirection",
    "MailPlugin",
    "MailSettings",
    "UnixTimestampDateAttr",
    "UserMailTab",
    "alias_plugin",
    "check_mail_uniqueness",
    "fold_ascii",
    "format_delivery_mode",
    "parse_delivery_mode",
    "plugin",
    "settings_of",
    "virtual",
]
