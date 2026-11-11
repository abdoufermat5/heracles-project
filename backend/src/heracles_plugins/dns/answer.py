"""Authoritative resolution over the zones stored in the directory.

Pure logic: no dnspython import and no wire format. :mod:`heracles_plugins.dns.server`
turns an :class:`Answer` into a DNS message.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from heracles.ldap.client import DirectoryClient, Entry, NoSuchObjectError, Scope
from heracles_plugins.dns.records import (
    PSEUDO_TYPES,
    RECORD_ATTR_NAMES,
    Record,
    classify,
)

SOA_TYPE: Final = "SOA"
ANY_TYPE: Final = "ANY"
DEFAULT_TTL: Final = 3600

_APEX: Final = "@"
_WILDCARD: Final = "*"
_CNAME: Final = "CNAME"
_MAX_CNAME_HOPS: Final = 8
_MAX_TTL: Final = 2_147_483_647
_ZONE_CLASS: Final = "dNSZone"
_APEX_FILTER: Final = f"(&(objectClass={_ZONE_CLASS})(relativeDomainName={_APEX}))"
_CHILD_FILTER: Final = f"(&(objectClass={_ZONE_CLASS})(!(relativeDomainName={_APEX})))"
#: Types stored as TXT values (the pseudo types keep their own name in :class:`Record`).
_TXT_TYPES: Final[frozenset[str]] = frozenset(("TXT", *PSEUDO_TYPES))


@dataclass(frozen=True, slots=True)
class Zone:
    """One authoritative zone (forward or reverse) built from directory entries."""

    name: str
    ttl: int
    soa: str
    records: Mapping[str, tuple[Record, ...]]


@dataclass(frozen=True, slots=True)
class Answer:
    """Outcome of a query: answer records and the authority data of a negative answer."""

    records: tuple[Record, ...] = ()
    nxdomain: bool = False
    soa: Record | None = None
    zone: str | None = None


# --------------------------------------------------------------------- loading


def _search(directory: DirectoryClient, base: str, flt: str, scope: Scope) -> list[Entry]:
    try:
        return list(directory.search(base, flt, scope))
    except NoSuchObjectError:
        return []


def ttl_of(entry: Entry) -> int:
    """``dNSTTL`` of an entry, or :data:`DEFAULT_TTL` when absent or invalid."""
    text = (entry.text("dNSTTL") or "").strip()
    if not text.isdigit():
        return DEFAULT_TTL
    ttl = int(text)
    return ttl if ttl <= _MAX_TTL else DEFAULT_TTL


def _entry_records(entry: Entry, name: str) -> list[Record]:
    """Records of one entry (same rule as the plugin's ``store._entry_records``)."""
    out: list[Record] = []
    for attr in RECORD_ATTR_NAMES:
        for value in entry.texts(attr):
            rtype = classify(attr, value)
            if rtype is not None:
                out.append(Record(name, rtype, value))
    return out


def _records_by_name(apex: Entry, children: Sequence[Entry]) -> dict[str, tuple[Record, ...]]:
    grouped: dict[str, list[Record]] = {}

    def add(name: str, records: Sequence[Record]) -> None:
        if records:
            grouped.setdefault(name.casefold(), []).extend(records)

    add(_APEX, _entry_records(apex, _APEX))
    for child in children:
        name = (child.text("relativeDomainName") or "").strip()
        if name and name != _APEX:
            add(name, _entry_records(child, name))
    return {key: tuple(values) for key, values in grouped.items()}


def load_zones(directory: DirectoryClient) -> list[Zone]:
    """Zones below the directory base, forward and reverse ones alike."""
    zones: list[Zone] = []
    for apex in _search(directory, directory.base_dn, _APEX_FILTER, Scope.SUBTREE):
        name = (apex.text("zoneName") or "").strip().rstrip(".").casefold()
        if not name:
            continue
        children = _search(directory, apex.dn, _CHILD_FILTER, Scope.ONE)
        zones.append(
            Zone(
                name=name,
                ttl=ttl_of(apex),
                soa=(apex.text("sOARecord") or "").strip(),
                records=_records_by_name(apex, children),
            )
        )
    return zones


# ------------------------------------------------------------------ resolution


def _normalize(name: str) -> str:
    return name.strip().rstrip(".").casefold()


def zone_for(zones: Sequence[Zone], qname: str) -> Zone | None:
    """Longest zone whose origin equals or is a suffix of ``qname``."""
    name = _normalize(qname)
    best: Zone | None = None
    for zone in zones:
        if (name == zone.name or name.endswith("." + zone.name)) and (
            best is None or len(zone.name) > len(best.name)
        ):
            best = zone
    return best


def _soa_record(zone: Zone) -> Record | None:
    return Record(_APEX, SOA_TYPE, zone.soa) if zone.soa else None


def _lookup(zone: Zone, relative: str) -> tuple[Record, ...] | None:
    """Records at ``relative`` (wildcard applied), or ``None`` when the name is absent."""
    records = zone.records.get(relative.casefold())
    if records is not None:
        return records
    if relative == _APEX:
        # the apex always exists, even when it carries nothing but its SOA
        return ()
    wildcard = zone.records.get(_WILDCARD)
    if wildcard is None:
        return None
    return tuple(Record(relative, record.type, record.value) for record in wildcard)


def _match(records: Sequence[Record], qtype: str) -> tuple[Record, ...]:
    if qtype == ANY_TYPE:
        return tuple(records)
    if qtype == "TXT":
        return tuple(record for record in records if record.type in _TXT_TYPES)
    return tuple(record for record in records if record.type == qtype)


def _cname_target(value: str, zone: Zone) -> str | None:
    """Name ``value`` is a CNAME target inside ``zone`` (``None`` when it leaves it)."""
    text = value.strip()
    if not text or text == ".":
        return None
    absolute = "." in text
    target = text.rstrip(".").casefold()
    if not absolute:
        # single-label targets are relative to the same zone
        return target
    if target == zone.name:
        return _APEX
    suffix = "." + zone.name
    if target.endswith(suffix):
        return target[: -len(suffix)]
    return None


def _chase(
    zone: Zone, relative: str, found: tuple[Record, ...], qtype: str
) -> tuple[tuple[Record, ...], bool]:
    """Follow a CNAME chain inside ``zone``; the flag says whether the target answered."""
    chain: list[Record] = []
    current = relative
    current_records: tuple[Record, ...] | None = cast("tuple[Record, ...] | None", found)
    seen = {relative.casefold(), _WILDCARD}
    for _ in range(_MAX_CNAME_HOPS):
        if current_records is None:
            break
        cname = next((record for record in current_records if record.type == _CNAME), None)
        if cname is None:
            break
        chain.append(cname)
        target = _cname_target(cname.value, zone)
        if target is None or target in seen:
            break
        seen.add(target)
        current = target
        current_records = _lookup(zone, current)
        if current_records is None:
            break
        matched = _match(current_records, qtype)
        if matched:
            chain.extend(matched)
            return tuple(chain), True
    return tuple(chain), False


def resolve(zones: Sequence[Zone], qname: str, qtype: str) -> Answer:
    """Resolve one question against the loaded zones."""
    name = _normalize(qname)
    rtype = qtype.strip().upper()
    zone = zone_for(zones, name)
    if zone is None:
        return Answer(nxdomain=True)
    relative = _APEX if name == zone.name else name[: -(len(zone.name) + 1)]
    found = _lookup(zone, relative)
    soa = _soa_record(zone)
    if found is None:
        return Answer(nxdomain=True, soa=soa, zone=zone.name)
    if rtype == SOA_TYPE and relative == _APEX:
        return Answer(records=(soa,) if soa is not None else (), soa=None, zone=zone.name)
    matched = _match(found, rtype)
    if matched:
        return Answer(records=matched, soa=None, zone=zone.name)
    if rtype in (ANY_TYPE, _CNAME) or not any(record.type == _CNAME for record in found):
        return Answer(soa=soa, zone=zone.name)
    records, complete = _chase(zone, relative, found, rtype)
    return Answer(records=records, soa=None if complete else soa, zone=zone.name)
