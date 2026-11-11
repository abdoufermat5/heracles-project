"""DNS plugin: zones, records and reverse zones stored with the ``dNSZone`` schema.

Storage layout (below ``ou=dns`` of a department)::

    zoneName=example.com                       apex entry: SOA, NS, MX, ... (relativeDomainName=@)
      relativeDomainName=www                   one entry per other name of the zone
      zoneName=2.0.192.in-addr.arpa            reverse zone (same SOA/NS as the forward zone)
        relativeDomainName=10                  PTR entries, maintained from A/AAAA records

ACL: records are edited through the virtual attribute ``dnsRecord``, so the
permission check of the ``dnsZone/dnsZone`` object applies to the attribute
``dnsRecord`` (a role can allow ``dnsRecord`` writes without allowing the SOA).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from heracles.attributes import (
    BooleanAttr,
    CompositeAttr,
    DepartmentAttr,
    DisplayAttr,
    HiddenAttr,
    IntAttr,
    ListAttr,
    ObjectRefAttr,
    SelectAttr,
    StringAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab
from heracles.objects.hooks import TabContext
from heracles_plugins.dns import store
from heracles_plugins.dns.records import (
    HOST_RE,
    NAME_RE,
    RECORD_TYPES,
    REVERSE_RE,
    ZONE_RE,
    Record,
    Soa,
    next_serial,
    normalize_host,
    normalize_mail,
    normalize_value,
    parse_soa,
    valid_mailbox,
    validate_record,
    validate_records,
)

PLUGIN_NAME = "dns"
ZONE_FILTER = (
    "(&(objectClass=dNSZone)(relativeDomainName=@)(!(|(zoneName=*.arpa)(zoneName=*.arpa.))))"
)
SOA_FIELDS = ("soaPrimary", "soaMail", "soaRefresh", "soaRetry", "soaExpire", "soaMinimum")
#: ACL attribute name of the record list (see module docstring).
RECORDS = "dnsRecord"
_UNIT_SEPARATOR = "\x1f"


@dataclass(slots=True)
class DnsSettings:
    """Settings of the DNS plugin."""

    #: Write fully qualified names with a trailing dot (``ns1.example.com.``).
    final_dot: bool = True


def settings_of(ctx: TabContext) -> DnsSettings:
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, DnsSettings) else DnsSettings()


def _ensure_container(ctx: TabContext) -> None:
    """Create the ``ou=dns`` container of the department when a first object is added."""
    if ctx.creating:
        ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))


def today() -> date:
    """Current date (a seam for tests)."""
    return date.today()


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


# --------------------------------------------------------------- attributes


class RecordAttr(CompositeAttr):
    """One resource record ``{name, type, value}`` checked per record type."""

    def __init__(self, name: str = "record", label: str = "") -> None:
        super().__init__(
            name,
            label or _("Record"),
            [
                StringAttr(
                    "name",
                    _("Name"),
                    required=True,
                    pattern=NAME_RE,
                    description=_("Name relative to the zone, '@' for the zone itself"),
                ),
                SelectAttr(
                    "type", _("Type"), required=True, options=[(t, t) for t in RECORD_TYPES]
                ),
                StringAttr("value", _("Value"), required=True),
            ],
            separator=_UNIT_SEPARATOR,
        )

    def _validate(self, value: dict[str, Any]) -> list[str]:
        errors = super()._validate(value)
        if errors:
            return errors
        problem = validate_record(str(value["name"]), str(value["type"]), str(value["value"]))
        return [problem] if problem else []


def to_records(value: object) -> list[Record]:
    """Records of a ``dnsRecord`` attribute value."""
    out: list[Record] = []
    if not isinstance(value, list):
        return out
    for element in cast("list[object]", value):
        if not isinstance(element, dict):
            continue
        item = cast("dict[str, Any]", element)
        name, rtype, text = item.get("name"), item.get("type"), item.get("value")
        if isinstance(name, str) and isinstance(rtype, str) and isinstance(text, str):
            out.append(Record(name, rtype, text))
    return out


class RecordListAttr(ListAttr[dict[str, Any]]):
    """List of records; errors name the offending (1-based) position."""

    def _validate(self, value: list[dict[str, Any]]) -> list[str]:
        errors: list[str] = []
        if self.max_length is not None and len(value) > self.max_length:
            errors.append(_("At most {n} values are allowed.").format(n=self.max_length))
        for index, element in enumerate(value, start=1):
            errors.extend(
                _("Record {n}: {message}").format(n=index, message=message)
                for message in self.item.validate(element)
            )
        if not errors:
            errors.extend(validate_records(to_records(value)))
        return errors


def soa_serial(values: dict[str, Any]) -> str | None:
    soa = parse_soa(values.get("sOARecord"))
    return soa.serial if soa is not None else None


def _records_key(value: object) -> frozenset[tuple[str, str, str]]:
    return frozenset((r.name.casefold(), r.type, r.value) for r in to_records(value))


# ----------------------------------------------------------------- the zone


class DnsZone(ObjectType):
    """A forward DNS zone with its records and reverse zones."""

    name = "dns_zone"
    acl_category = "dnsZone"
    label = _("DNS zone")
    label_plural = _("DNS zones")
    icon = "globe"
    category = "network"
    filter = ZONE_FILTER
    main_attr = "zoneName"
    name_attr = "zoneName"
    rdn = "ou=dns"
    columns = ("zoneName", "dNSTTL")
    search_attrs = ("zoneName",)

    class Main(Tab):
        name = "main"
        acl_key = "dnsZone"
        label = _("DNS zone")
        object_classes = ("dNSZone",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr(
                "zoneName",
                _("Zone name"),
                required=True,
                pattern=ZONE_RE,
                description=_("Domain name of the zone, without trailing dot"),
            ),
            IntAttr(
                "dNSTTL",
                _("Default TTL (seconds)"),
                min=0,
                max=2147483647,
                description=_("Time to live of the apex entry"),
            ),
            HiddenAttr("relativeDomainName", "relativeDomainName", default="@"),
            HiddenAttr("sOARecord", "sOARecord"),
        )
        soa = Section(
            _("Start of authority"),
            virtual(
                StringAttr(
                    "soaPrimary",
                    _("Primary name server"),
                    required=True,
                    description=_("Host name of the primary name server"),
                )
            ),
            virtual(
                StringAttr(
                    "soaMail",
                    _("Administrator mailbox"),
                    required=True,
                    description=_("hostmaster.example.com. form; an email address is converted"),
                )
            ),
            virtual(IntAttr("soaRefresh", _("Refresh (seconds)"), min=0, default=10800)),
            virtual(IntAttr("soaRetry", _("Retry (seconds)"), min=0, default=3600)),
            virtual(IntAttr("soaExpire", _("Expire (seconds)"), min=0, default=604800)),
            virtual(IntAttr("soaMinimum", _("Minimum TTL (seconds)"), min=0, default=3600)),
            DisplayAttr("soaSerial", _("Serial"), compute=soa_serial),
        )
        reverse = Section(
            _("Reverse zones"),
            virtual(
                ListAttr(
                    "reverseZones",
                    _("Reverse zones"),
                    StringAttr("zone", _("Reverse zone"), pattern=REVERSE_RE),
                    description=_("Names ending in .in-addr.arpa or .ip6.arpa"),
                )
            ),
        )
        records = Section(
            _("Records"),
            virtual(RecordListAttr(RECORDS, _("Records"), RecordAttr())),
        )

        # ------------------------------------------------------------- hooks

        @classmethod
        def on_load(cls, ctx: TabContext) -> None:
            values = ctx.values
            soa = parse_soa(values.get("sOARecord"))
            if soa is not None:
                values["soaPrimary"] = soa.primary
                values["soaMail"] = soa.mail
                values["soaRefresh"] = soa.refresh
                values["soaRetry"] = soa.retry
                values["soaExpire"] = soa.expire
                values["soaMinimum"] = soa.minimum
            if ctx.dn is None:
                return
            reverse = [
                e.text("zoneName") or "" for e in store.read_reverse_zones(ctx.directory, ctx.dn)
            ]
            values["reverseZones"] = [z for z in reverse if z] or None
            records = store.read_records(ctx.directory, ctx.dn)
            values[RECORDS] = [
                {"name": r.name, "type": r.type, "value": r.value} for r in records
            ] or None

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            values = ctx.values
            final_dot = settings_of(ctx).final_dot
            original = ctx.original_values()
            zone = values.get("zoneName")
            if isinstance(zone, str):
                values["zoneName"] = zone.strip().rstrip(".")
            _ensure_container(ctx)
            values["relativeDomainName"] = "@"

            reverse = values.get("reverseZones")
            if ctx.was_touched("reverseZones") and isinstance(reverse, list):
                names = [str(z).strip().rstrip(".") for z in cast("list[object]", reverse)]
                values["reverseZones"] = list(dict.fromkeys(names)) or None

            records_touched = ctx.was_touched(RECORDS)
            if records_touched:
                values[RECORDS] = cls._normalized_records(values.get(RECORDS), final_dot)
            records_changed = records_touched and _records_key(values.get(RECORDS)) != _records_key(
                original.get(RECORDS)
            )
            cls._prepare_soa(ctx, final_dot, records_changed=records_changed)

        @staticmethod
        def _normalized_records(value: object, final_dot: bool) -> list[dict[str, Any]] | None:
            seen: set[tuple[str, str, str]] = set()
            out: list[dict[str, Any]] = []
            if not isinstance(value, list):
                return None
            for element in cast("list[object]", value):
                if not isinstance(element, dict):
                    continue
                item = dict(cast("dict[str, Any]", element))
                name, rtype, text = item.get("name"), item.get("type"), item.get("value")
                if isinstance(name, str):
                    item["name"] = name.strip()
                if isinstance(rtype, str):
                    item["type"] = rtype.strip().upper()
                if isinstance(rtype, str) and isinstance(text, str):
                    item["value"] = normalize_value(item["type"], text, final_dot)
                key = (str(item["name"]).casefold(), str(item["type"]), str(item["value"]))
                if key not in seen:
                    seen.add(key)
                    out.append(item)
            return out or None

        @classmethod
        def _prepare_soa(cls, ctx: TabContext, final_dot: bool, *, records_changed: bool) -> None:
            values = ctx.values
            original = ctx.original_values()
            soa_touched = ctx.creating or any(ctx.was_touched(k) for k in SOA_FIELDS)
            if soa_touched:
                primary = values.get("soaPrimary")
                mail = values.get("soaMail")
                if isinstance(primary, str) and primary.strip():
                    primary = normalize_host(primary, final_dot)
                    values["soaPrimary"] = primary
                    if HOST_RE.fullmatch(primary) is None and primary != ".":
                        ctx.error("soaPrimary", _("Expected a host name."))
                if isinstance(mail, str) and mail.strip():
                    mail = normalize_host(normalize_mail(mail), final_dot)
                    values["soaMail"] = mail
                    if not valid_mailbox(mail):
                        ctx.error("soaMail", _("Expected a mailbox like hostmaster.example.com."))
            soa_changed = ctx.creating or any(values.get(k) != original.get(k) for k in SOA_FIELDS)
            if not (soa_changed or records_changed):
                return
            current = parse_soa(values.get("sOARecord"))
            if current is None and not ctx.creating and not soa_touched:
                return  # foreign, unparsable SOA: leave it alone
            primary, mail = values.get("soaPrimary"), values.get("soaMail")
            if not (isinstance(primary, str) and primary and isinstance(mail, str) and mail):
                return  # reported as required by validation

            def number(key: str, default: int) -> int:
                found = values.get(key)
                return found if isinstance(found, int) else default

            serial = next_serial(current.serial if current else None, today())
            values["sOARecord"] = Soa(
                primary,
                mail,
                serial,
                number("soaRefresh", 10800),
                number("soaRetry", 3600),
                number("soaExpire", 604800),
                number("soaMinimum", 3600),
            ).format()

        @classmethod
        def after_save(cls, ctx: TabContext) -> None:
            values = ctx.values
            zone, dn = values.get("zoneName"), ctx.dn
            if dn is None or not isinstance(zone, str):
                return
            if not (ctx.creating or any(tab == ctx.tab_name for tab, _attr in ctx.touched)):
                return
            directory = ctx.directory
            final_dot = settings_of(ctx).final_dot
            old = ctx.original_values().get("zoneName")
            previous = old if isinstance(old, str) and old != zone else None
            if previous is not None:
                store.rename_children(directory, dn, zone)
            if ctx.creating or ctx.was_touched(RECORDS):
                store.write_records(directory, dn, zone, to_records(values.get(RECORDS)))
            wanted: list[str] | None = None
            if ctx.creating or ctx.was_touched("reverseZones"):
                raw = values.get("reverseZones")
                wanted = (
                    [str(z) for z in cast("list[object]", raw)] if isinstance(raw, list) else []
                )
            store.sync_reverse_zones(
                directory,
                dn,
                zone,
                wanted=wanted,
                previous_name=previous,
                final_dot=final_dot,
            )

        @classmethod
        def before_delete(cls, ctx: TabContext) -> None:
            if ctx.dn is not None:
                store.delete_subtree(ctx.directory, ctx.dn)


# ---------------------------------------------------------- views and ACLs


class DnsAcl(ObjectType):
    """An address match list (``hrcDNSAcl``)."""

    name = "dns_acl"
    acl_category = "dnsAcl"
    label = _("DNS access list")
    label_plural = _("DNS access lists")
    icon = "shield"
    category = "network"
    filter = "(objectClass=hrcDNSAcl)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=dns"
    columns = ("cn",)
    search_attrs = ("cn",)

    class Main(Tab):
        name = "main"
        acl_key = "dnsAcl"
        label = _("DNS access list")
        object_classes = ("hrcDNSAcl",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=r"[A-Za-z0-9_][A-Za-z0-9_.-]*"),
            ListAttr(
                "hrcDNSAclMatchList",
                _("Address match list"),
                StringAttr(
                    "element",
                    _("Element"),
                    pattern=r"!?[A-Za-z0-9_.:/-]+(?: [A-Za-z0-9_.-]+)?",
                    description=_(
                        "Address, network, key, ACL name or any/none/localhost/localnets"
                    ),
                ),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            _ensure_container(ctx)


class DnsView(ObjectType):
    """A server view (``hrcDNSView``)."""

    name = "dns_view"
    acl_category = "dnsView"
    label = _("DNS view")
    label_plural = _("DNS views")
    icon = "eye"
    category = "network"
    filter = "(objectClass=hrcDNSView)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=dns"
    columns = ("cn",)
    search_attrs = ("cn",)

    class Main(Tab):
        name = "main"
        acl_key = "dnsView"
        label = _("DNS view")
        object_classes = ("hrcDNSView",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=r"[A-Za-z0-9_][A-Za-z0-9_.-]*"),
            BooleanAttr("hrcDNSViewMatchRecursiveOnly", _("Match recursive queries only")),
        )
        matching = Section(
            _("Matching"),
            ListAttr(
                "hrcDNSViewMatchClientsAcl",
                _("Clients"),
                ObjectRefAttr("client", _("Access list"), ref_type="dns_acl"),
                description=_("Access lists the client must match"),
            ),
            ListAttr(
                "hrcDNSViewMatchDestinationsAcl",
                _("Destinations"),
                ObjectRefAttr("destination", _("Access list"), ref_type="dns_acl"),
                description=_("Access lists the destination must match"),
            ),
        )
        zones = Section(
            _("Zones"),
            ListAttr(
                "hrcDNSZoneDn",
                _("Zones"),
                ObjectRefAttr("zone", _("Zone"), ref_type="dns_zone"),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            _ensure_container(ctx)


def plugin() -> Plugin:
    """Entry point of the DNS plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        # view/ACL types are only registered when their objectClasses are loaded
        types=(DnsZone, DnsView, DnsAcl),
        tabs=(),
        required_object_classes=("dNSZone",),
        settings=DnsSettings(),
    )


__all__ = [
    "DnsAcl",
    "DnsSettings",
    "DnsView",
    "DnsZone",
    "RecordAttr",
    "RecordListAttr",
    "plugin",
    "to_records",
]
