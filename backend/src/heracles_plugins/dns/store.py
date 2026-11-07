"""Directory side of the DNS plugin: records, reverse zones and PTR maintenance."""

from __future__ import annotations

from collections.abc import Sequence

from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)
from heracles_plugins.dns.records import (
    RECORD_ATTR_NAMES,
    RECORD_ATTRS,
    Record,
    classify,
    fqdn,
    reverse_relative,
    type_to_attr,
)

ZONE_CLASS = "dNSZone"
APEX = "@"
_NOT_APEX = f"(&(objectClass={ZONE_CLASS})(!(relativeDomainName={APEX})))"
_APEX_ONLY = f"(&(objectClass={ZONE_CLASS})(relativeDomainName={APEX}))"

type AttrValues = dict[str, list[str]]


def _children(directory: DirectoryClient, dn: str, flt: str) -> list[Entry]:
    try:
        return list(directory.search(dn, flt, Scope.ONE))
    except NoSuchObjectError:
        return []


def _rdn(zone_dn: str, name: str) -> str:
    return f"relativeDomainName={dnlib.escape_rdn_value(name)},{zone_dn}"


# --------------------------------------------------------------------- reading


def read_records(directory: DirectoryClient, zone_dn: str) -> list[Record]:
    """Records of a forward zone: apex entry attributes plus its name entries."""
    records: list[Record] = []
    apex = directory.get(zone_dn)
    if apex is not None:
        records.extend(_entry_records(apex, APEX))
    for child in _children(directory, zone_dn, _NOT_APEX):
        name = child.text("relativeDomainName")
        if name:
            records.extend(_entry_records(child, name))
    order = {t: i for i, t in enumerate(RECORD_ATTRS)}
    records.sort(key=lambda r: (r.name != APEX, r.name.casefold(), order.get(r.type, 99), r.value))
    return records


def _entry_records(entry: Entry, name: str) -> list[Record]:
    out: list[Record] = []
    for attr in RECORD_ATTR_NAMES:
        for value in entry.texts(attr):
            rtype = classify(attr, value)
            if rtype is not None:
                out.append(Record(name, rtype, value))
    return out


def read_reverse_zones(directory: DirectoryClient, zone_dn: str) -> list[Entry]:
    """Reverse zone entries below a forward zone, sorted by name."""
    found = _children(directory, zone_dn, _APEX_ONLY)
    return sorted(found, key=lambda e: (e.text("zoneName") or "").casefold())


# --------------------------------------------------------------------- records


def _grouped(records: Sequence[Record]) -> dict[str, tuple[str, AttrValues]]:
    """``casefolded name -> (name, {attribute: [values]})`` without duplicates."""
    out: dict[str, tuple[str, AttrValues]] = {}
    for rec in records:
        _name, attrs = out.setdefault(rec.name.casefold(), (rec.name, {}))
        bucket = attrs.setdefault(type_to_attr(rec.type), [])
        if rec.value not in bucket:
            bucket.append(rec.value)
    return out


def _record_mods(entry: Entry, wanted: AttrValues) -> list[Modification]:
    mods: list[Modification] = []
    for attr in RECORD_ATTR_NAMES:
        have = entry.texts(attr)
        want = wanted.get(attr, [])
        if sorted(have) == sorted(want):
            continue
        if want:
            mods.append(Modification("replace", attr, [v.encode("utf-8") for v in want]))
        else:
            mods.append(Modification("delete", attr))
    return mods


def write_records(
    directory: DirectoryClient, zone_dn: str, zone_name: str, records: Sequence[Record]
) -> None:
    """Make the apex entry and the name entries of a zone hold exactly ``records``."""
    desired = _grouped(records)
    apex = directory.get(zone_dn)
    if apex is not None:
        mods = _record_mods(apex, desired.get(APEX, (APEX, {}))[1])
        if mods:
            directory.modify(zone_dn, mods)
    existing: dict[str, Entry] = {}
    for child in _children(directory, zone_dn, _NOT_APEX):
        name = child.text("relativeDomainName")
        if name:
            existing[name.casefold()] = child
    for key, child in existing.items():
        if key not in desired:
            directory.delete(child.dn, recursive=True)
    for key, (name, attrs) in desired.items():
        if key == APEX:
            continue
        child = existing.get(key)
        if child is not None:
            mods = _record_mods(child, attrs)
            if mods:
                directory.modify(child.dn, mods)
            continue
        entry: dict[str, list[bytes]] = {
            "objectClass": [ZONE_CLASS.encode()],
            "zoneName": [zone_name.encode("utf-8")],
            "relativeDomainName": [name.encode("utf-8")],
        }
        for attr, values in attrs.items():
            entry[attr] = [v.encode("utf-8") for v in values]
        directory.add(_rdn(zone_dn, name), entry)


def rename_children(directory: DirectoryClient, zone_dn: str, zone_name: str) -> None:
    """Point the ``zoneName`` of the name entries at the (renamed) zone."""
    for child in _children(directory, zone_dn, _NOT_APEX):
        if child.text("zoneName") != zone_name:
            directory.modify(
                child.dn, [Modification("replace", "zoneName", [zone_name.encode("utf-8")])]
            )


def delete_subtree(directory: DirectoryClient, dn: str) -> None:
    """Delete everything below ``dn`` (not ``dn`` itself), deepest entries first."""
    try:
        below = [
            e
            for e in directory.search(dn, "(objectClass=*)", Scope.SUBTREE, ["objectClass"])
            if dnlib.normalize(e.dn) != dnlib.normalize(dn)
        ]
    except NoSuchObjectError:
        return
    for entry in sorted(below, key=lambda e: dnlib.depth(e.dn), reverse=True):
        directory.delete(entry.dn)


# --------------------------------------------------------------- reverse zones


def sync_reverse_zones(
    directory: DirectoryClient,
    zone_dn: str,
    zone_name: str,
    *,
    wanted: Sequence[str] | None,
    previous_name: str | None,
    final_dot: bool,
) -> None:
    """Bring reverse zones, their SOA/NS copies and the managed PTR entries up to date.

    ``wanted`` is the list of reverse zone names (``None``: leave the set of
    reverse zones as it is). PTR values pointing into the forward zone (under
    its current or previous name) are owned by this function; others are kept.
    """
    forward = directory.get(zone_dn)
    if forward is None:
        return
    soa = forward.texts("sOARecord")
    ns = forward.texts("nSRecord")
    existing = {
        (e.text("zoneName") or "").casefold(): e for e in read_reverse_zones(directory, zone_dn)
    }
    if wanted is not None:
        wanted_keys = {w.casefold(): w for w in wanted}
        for key, entry in list(existing.items()):
            if key not in wanted_keys:
                directory.delete(entry.dn, recursive=True)
                del existing[key]
        for key, name in wanted_keys.items():
            if key in existing:
                continue
            attrs: dict[str, list[bytes]] = {
                "objectClass": [ZONE_CLASS.encode()],
                "zoneName": [name.encode("utf-8")],
                "relativeDomainName": [APEX.encode()],
            }
            dn = f"zoneName={dnlib.escape_rdn_value(name)},{zone_dn}"
            directory.add(dn, attrs)
            created = directory.get(dn)
            if created is not None:
                existing[key] = created
    reverse = sorted(existing.values(), key=lambda e: (e.text("zoneName") or "").casefold())
    for entry in reverse:
        mods: list[Modification] = []
        for attr, want in (("sOARecord", soa), ("nSRecord", ns)):
            if sorted(entry.texts(attr)) != sorted(want):
                mods.append(
                    Modification("replace", attr, [v.encode("utf-8") for v in want])
                    if want
                    else Modification("delete", attr)
                )
        if mods:
            directory.modify(entry.dn, mods)
    _sync_ptrs(directory, zone_dn, zone_name, previous_name, reverse, final_dot)


def _sync_ptrs(
    directory: DirectoryClient,
    zone_dn: str,
    zone_name: str,
    previous_name: str | None,
    reverse: Sequence[Entry],
    final_dot: bool,
) -> None:
    if not reverse:
        return
    names = [(e.text("zoneName") or "") for e in reverse]
    by_length = sorted(range(len(reverse)), key=lambda i: names[i].count("."), reverse=True)
    expected: dict[int, dict[str, list[str]]] = {i: {} for i in range(len(reverse))}
    for rec in read_records(directory, zone_dn):
        if rec.type not in ("A", "AAAA"):
            continue
        for i in by_length:
            relative = reverse_relative(rec.value, names[i])
            if relative is None:
                continue
            host = fqdn(rec.name, zone_name, final_dot)
            bucket = expected[i].setdefault(relative, [])
            if host not in bucket:
                bucket.append(host)
            break
    zones = [z.casefold() for z in (zone_name, previous_name) if z]

    def managed(value: str) -> bool:
        host = value.strip().rstrip(".").casefold()
        return any(host == z or host.endswith("." + z) for z in zones)

    for i, entry in enumerate(reverse):
        want_by_name = expected[i]
        seen: set[str] = set()
        for child in _children(directory, entry.dn, _NOT_APEX):
            relative = child.text("relativeDomainName")
            if not relative:
                continue
            seen.add(relative.casefold())
            current = child.texts("pTRRecord")
            wanted = [v for v in current if not managed(v)]
            wanted.extend(h for h in want_by_name.get(relative.casefold(), []) if h not in wanted)
            if sorted(wanted) == sorted(current):
                continue
            if wanted:
                directory.modify(
                    child.dn,
                    [Modification("replace", "pTRRecord", [v.encode("utf-8") for v in wanted])],
                )
            else:
                directory.delete(child.dn, recursive=True)
        for relative, hosts in want_by_name.items():
            if relative.casefold() in seen:
                continue
            directory.add(
                _rdn(entry.dn, relative),
                {
                    "objectClass": [ZONE_CLASS.encode()],
                    "zoneName": [names[i].encode("utf-8")],
                    "relativeDomainName": [relative.encode("utf-8")],
                    "pTRRecord": [h.encode("utf-8") for h in hosts],
                },
            )
