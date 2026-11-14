"""Convert a directory export (LDIF) from the legacy layout to the Heracles schema.

The conversion is offline: export the directory, run :func:`migrate_ldif` (or
``heracles migrate-directory``), load the Heracles schema on the target server and
import the result. Every change is recorded in a :class:`Report`; names with a legacy
prefix that the rename table does not know are errors, never copied silently.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from heracles.acl.model import AclAssignment, AclBlock, Ignored, RoleTemplateValue
from heracles.acl.parser import (
    parse_assignment,
    parse_role_value,
    serialise_assignment,
    serialise_role_value,
)
from heracles.attributes.kinds import parse_generalized_time
from heracles.ldap.client import Entry
from heracles.ldap.ldif import dump_ldif, parse_ldif
from heracles.migrate import legacy_map
from heracles.schema import names as schema
from heracles.schema.definitions import ATTRIBUTE_TYPES, OBJECT_CLASSES
from heracles.schema.model import AttributeType, ObjectClass, Syntax

_CLASSES = {k.lower(): v for k, v in legacy_map.OBJECT_CLASSES.items()}
_ATTRS = {k.lower(): v for k, v in legacy_map.ATTRIBUTES.items()}
_NAMES = {**{k.lower(): v for k, v in legacy_map.FIELDS.items()}, **_ATTRS, **_CLASSES}
_OLD_RDN, _NEW_RDN = legacy_map.APP_RDN
_RDN_RE = re.compile(rf"(?<![^,+\s]){re.escape(_OLD_RDN)}(?=\s*(?:,|$))", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_RDN_TYPE_RE = re.compile(r"(^|[,+]\s*)([A-Za-z][A-Za-z0-9-]*)=")

_TYPES: dict[str, AttributeType] = {a.name.lower(): a for a in ATTRIBUTE_TYPES}
_DEFS: dict[str, ObjectClass] = {c.name.lower(): c for c in OBJECT_CLASSES}
_OWNER: dict[str, ObjectClass] = {}
for _cls in OBJECT_CLASSES:
    for _attr in (*_cls.must, *_cls.may):
        if _attr.startswith("hrc") and _cls.kind == ObjectClass.AUXILIARY:
            _OWNER.setdefault(_attr.lower(), _cls)

#: Attributes whose values are attribute names (one per value).
_NAME_VALUES = frozenset(
    n.lower()
    for n in (
        "hrcAuditAttributes",
        "hrcExtractorTaskAttributes",
        "hrcTasksNotificationsAttributes",
        schema.CONFIG_ATTRS["account_primary_attribute"],
        schema.CONFIG_ATTRS["modification_detection_attribute"],
        schema.CONFIG_ATTRS["login_attribute"],
        schema.CONFIG_ATTRS["recovery_login_attribute"],
    )
)
#: Attributes whose values are ``<attribute><sep><value>``.
_PAIR_VALUES = {
    "hrcarchivedfield": "=",
    "hrcarchiveduniquefield": "=",
    schema.TEMPLATE_FIELD_ATTR.lower(): ":",
}
#: Attributes whose values are LDAP filters or URLs containing filters.
_FILTER_VALUES = frozenset({"memberurl", "labeleduri"})
#: Entries that only make sense while Heracles runs (dropped).
_TRANSIENT_CLASSES = frozenset({schema.OC.LOCK.lower()})


@dataclass
class Report:
    """What the migration did; ``errors`` must be empty before importing."""

    renamed: Counter[str] = field(default_factory=lambda: Counter[str]())
    added_classes: Counter[str] = field(default_factory=lambda: Counter[str]())
    dropped_entries: list[str] = field(default_factory=lambda: list[str]())
    dropped_values: list[str] = field(default_factory=lambda: list[str]())
    errors: list[str] = field(default_factory=lambda: list[str]())

    def rename_table(self) -> list[tuple[str, str]]:
        """``(old, new)`` pairs that occurred, for API v1 script authors."""
        pairs = (k.split(" -> ", 1) for k in sorted(self.renamed, key=str.lower))
        return [(old, new) for old, new in pairs]


def _rename(name: str, table: dict[str, str], report: Report) -> str | None:
    new = table.get(name.lower())
    if new is not None:
        report.renamed[f"{name} -> {new}"] += 1
        return new
    if legacy_map.LEGACY_NAME_RE.match(name):
        return None
    return name


def _rename_dn(dn: str) -> str:
    """Rename the application container and legacy RDN attribute types of ``dn``."""

    def rdn_type(match: re.Match[str]) -> str:
        new = _ATTRS.get(match.group(2).lower())
        return f"{match.group(1)}{new or match.group(2)}="

    return _RDN_TYPE_RE.sub(rdn_type, _RDN_RE.sub(_NEW_RDN, dn))


def _rename_words(text: str, report: Report) -> str:
    """Rename every known legacy name appearing as a word (filters, URLs)."""

    def sub(match: re.Match[str]) -> str:
        word = match.group(0)
        new = _NAMES.get(word.lower())
        if new is None:
            return word
        report.renamed[f"{word} -> {new}"] += 1
        return new

    return _rename_dn(_WORD_RE.sub(sub, text))


def _field_name(name: str, report: Report, where: str) -> str:
    new = _NAMES.get(name.lower())
    if new is not None:
        report.renamed[f"{name} -> {new}"] += 1
        return new
    if legacy_map.LEGACY_NAME_RE.match(name):
        report.errors.append(f"{where}: unknown legacy name {name!r}")
    return name


def _acl_template(value: str, report: Report, where: str) -> str:
    parsed = parse_role_value(value)
    if isinstance(parsed, Ignored):
        report.errors.append(f"{where}: unreadable ACL role value {value!r}")
        return value
    blocks = tuple(
        AclBlock(
            b.object,
            b.rights,
            tuple((_field_name(n, report, where), r) for n, r in b.attributes),
        )
        for b in parsed.blocks
    )
    return serialise_role_value(RoleTemplateValue(parsed.index, blocks))


def _acl_entry(value: str, report: Report, where: str) -> str:
    parsed = parse_assignment(value)
    if isinstance(parsed, Ignored):
        report.errors.append(f"{where}: unreadable ACL assignment {value!r}")
        return value

    def flt(text: str | None) -> str | None:
        return None if text is None else _rename_words(text, report)

    return serialise_assignment(
        AclAssignment(
            index=parsed.index,
            scope=parsed.scope,
            role_dn=_rename_dn(parsed.role_dn),
            members=tuple(_rename_dn(m) for m in parsed.members),
            user_filter=flt(parsed.user_filter),
            target_filter=flt(parsed.target_filter),
        )
    )


def _normalise(attr: AttributeType, value: bytes) -> bytes | None:
    """Canonical form of a typed value, or ``None`` when it does not fit the syntax."""
    if attr.syntax is Syntax.BOOLEAN:
        text = value.decode("ascii", errors="replace").strip().upper()
        return text.encode() if text in ("TRUE", "FALSE") else None
    if attr.syntax is Syntax.INTEGER:
        try:
            return str(int(value.decode("ascii").strip())).encode()
        except (UnicodeDecodeError, ValueError):
            return None
    if attr.syntax is Syntax.TIME:
        moment = parse_generalized_time(value.decode("ascii", errors="replace"))
        return None if moment is None else moment.strftime("%Y%m%d%H%M%SZ").encode()
    return value


class _Migrator:
    def __init__(self, report: Report) -> None:
        self.report = report

    def entry(self, entry: Entry) -> Entry | None:
        where = entry.dn
        classes = [v.decode("utf-8") for v in entry.get("objectClass")]
        renamed = {_CLASSES.get(c.lower(), c).lower() for c in classes}
        if renamed & _TRANSIENT_CLASSES:
            self.report.dropped_entries.append(where)
            return None
        out = Entry(dn=_rename_dn(entry.dn))
        new_classes: list[str] = []
        for cls in classes:
            new = _rename(cls, _CLASSES, self.report)
            if new is None:
                self.report.errors.append(f"{where}: unknown legacy objectClass {cls!r}")
                new = cls
            new_classes.append(new)
        out.attrs["objectClass"] = [c.encode() for c in new_classes]
        for name, values in entry.attrs.items():
            if name.lower() == "objectclass":
                continue
            new_name = _rename(name, _ATTRS, self.report)
            if new_name is None:
                self.report.errors.append(f"{where}: unknown legacy attribute {name!r}")
                new_name = name
            converted = self._values(new_name, values, f"{where} {new_name}")
            if converted:
                out.attrs.setdefault(new_name, []).extend(converted)
        self._rename_naming_value(entry.dn, out)
        self._complete_classes(out)
        self._refresh_snapshot_hash(out)
        return out

    def _values(self, name: str, values: Iterable[bytes], where: str) -> list[bytes]:
        key = name.lower()
        out: list[bytes] = []
        for raw in values:
            value = self._value(key, raw, where)
            attr = _TYPES.get(key)
            if value is not None and attr is not None:
                normal = _normalise(attr, value)
                if normal is None:
                    self.report.dropped_values.append(f"{where}: {value!r} is not a valid value")
                    continue
                value = normal
            if value is not None:
                out.append(value)
        return out

    def _value(self, key: str, raw: bytes, where: str) -> bytes | None:
        if key == schema.ATTR.SNAPSHOT_DATA.lower():
            return self._snapshot(raw, where)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw  # binary (images, keys): copied as is
        return _rename_dn(self._convert(key, text, where)).encode("utf-8")

    def _convert(self, key: str, text: str, where: str) -> str:
        """Rename the legacy names stored inside a text value of attribute ``key``."""
        report = self.report
        if key == schema.ATTR.ACL_TEMPLATE.lower():
            return _acl_template(text, report, where)
        if key == schema.ATTR.ACL_ENTRY.lower():
            return _acl_entry(text, report, where)
        if key in _NAME_VALUES:
            return _field_name(text, report, where)
        if key in _PAIR_VALUES:
            head, found, rest = text.partition(_PAIR_VALUES[key])
            return _field_name(head, report, where) + found + rest if found else text
        if key == "hrcpublicformalteredattributes":
            path, bar, flags = text.partition("|")
            tab, dot, attr = path.rpartition(".")
            return f"{tab}{dot}{_field_name(attr, report, where)}{bar}{flags}"
        if key == schema.CONFIG_ATTRS["plugins_menu_blacklist"].lower():
            return self._plugin_name(text)
        if key in _FILTER_VALUES:
            return _rename_words(text, report)
        return text

    def _plugin_name(self, text: str) -> str:
        """Rename a plugin id stored in a ``<group>|<plugin>`` config value."""
        group, bar, plugin = text.rpartition("|")
        for old, new in legacy_map.PLUGIN_NAMES.items():
            if plugin.strip().lower() == old:
                self.report.renamed[f"{plugin.strip()} -> {new}"] += 1
                return f"{group}{bar}{new}"
            if not bar and text.strip().lower() == old:
                self.report.renamed[f"{text.strip()} -> {new}"] += 1
                return new
        return text

    def _snapshot(self, raw: bytes, where: str) -> bytes:
        try:
            ldif = zlib.decompress(raw).decode("utf-8")
            inner = parse_ldif(ldif)
        except (zlib.error, UnicodeDecodeError, ValueError) as exc:
            self.report.errors.append(f"{where}: unreadable snapshot data ({exc})")
            return raw
        migrated = [e for e in (self.entry(e) for e in inner) if e is not None]
        return zlib.compress(dump_ldif(migrated).encode("utf-8"), 9)

    @staticmethod
    def _rename_naming_value(old_dn: str, entry: Entry) -> None:
        """The application container keeps its RDN value in the entry: rename it too."""
        first = old_dn.split(",", 1)[0].strip()
        if first.lower() != _OLD_RDN.lower():
            return
        rdn_attr, _, old_value = _OLD_RDN.partition("=")
        new_value = _NEW_RDN.partition("=")[2]
        for name, values in entry.attrs.items():
            if name.lower() == rdn_attr:
                entry.attrs[name] = [
                    new_value.encode() if v.decode(errors="replace").lower() == old_value else v
                    for v in values
                ]

    @staticmethod
    def _refresh_snapshot_hash(entry: Entry) -> None:
        data = entry.first(schema.ATTR.SNAPSHOT_DATA)
        if data is None or not entry.get(schema.ATTR.SNAPSHOT_HASH):
            return
        try:
            plain = zlib.decompress(data)
        except zlib.error:
            return
        digest = hashlib.md5(plain, usedforsecurity=False).hexdigest()
        entry.attrs[schema.ATTR.SNAPSHOT_HASH] = [digest.encode()]

    def _complete_classes(self, entry: Entry) -> None:
        """Add the auxiliary class that allows an ``hrc*`` attribute when none does."""
        classes = [c.decode() for c in entry.attrs["objectClass"]]
        allowed: set[str] = set()
        for cls in classes:
            definition = _DEFS.get(cls.lower())
            if definition is not None:
                allowed |= {a.lower() for a in (*definition.must, *definition.may)}
        for name in list(entry.attrs):
            key = name.lower()
            if not key.startswith("hrc") or key in allowed or key not in _TYPES:
                continue
            owner = _OWNER.get(key)
            if owner is None:
                self.report.errors.append(f"{entry.dn}: no objectClass allows {name!r}")
                continue
            classes.append(owner.name)
            allowed |= {a.lower() for a in (*owner.must, *owner.may)}
            self.report.added_classes[owner.name] += 1
        entry.attrs["objectClass"] = [c.encode() for c in classes]


def migrate_entries(entries: Iterable[Entry]) -> tuple[list[Entry], Report]:
    """Migrate ``entries``; returns the converted entries and the report."""
    report = Report()
    migrator = _Migrator(report)
    out = [e for e in (migrator.entry(e) for e in entries) if e is not None]
    return out, report


def migrate_ldif(text: str) -> tuple[str, Report]:
    """Migrate an LDIF export; returns the converted LDIF and the report."""
    entries, report = migrate_entries(parse_ldif(text))
    return dump_ldif(entries), report
