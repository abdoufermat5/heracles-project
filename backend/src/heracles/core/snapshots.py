"""Snapshots of directory subtrees (compatibility entry format below).

A snapshot entry lives at ``<timestamp attribute>=<ts>,<snapshot base>`` and
holds a zlib-compressed LDIF of the object and its whole subtree plus the md5
hex of the uncompressed LDIF.
"""

from __future__ import annotations

import hashlib
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from heracles.core.containers import ensure_container
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    DirectoryError,
    Entry,
    NoSuchObjectError,
    Scope,
)
from heracles.ldap.filter import escape_filter_value
from heracles.ldap.ldif import dump_ldif, parse_ldif
from heracles.schema import names as schema

_A = schema.ATTR
_MAX_ATTEMPTS = 50
_ZLIB_LEVEL = 6


class SnapshotError(DirectoryError):
    """A snapshot is unreadable or fails its integrity check."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Snapshot metadata (the data blob is read on demand)."""

    dn: str
    timestamp: str
    object_dn: str
    object_type: str | None
    source: str
    description: str | None
    hash: str | None

    @property
    def created_at(self) -> datetime | None:
        """Creation time derived from the timestamp RDN value."""
        parsed = _parse_timestamp(self.timestamp)
        if parsed is None:
            return None
        try:
            return datetime.fromtimestamp(parsed[0] + parsed[1] / 1_000_000, UTC)
        except (OverflowError, OSError):
            return None


def _timestamp(now: float, bump: int) -> str:
    """Timestamp RDN value in the historical format ``<sec>-0<8 fraction digits>``.

    The fraction is the decimal part of the second written with 8 digits and its
    leading ``0.`` kept without the dot (e.g. ``1700000000-012345600``).
    """
    total_us = int(now * 1_000_000) + bump
    return f"{total_us // 1_000_000}-0{total_us % 1_000_000:06d}00"


def _parse_timestamp(timestamp: str) -> tuple[int, int] | None:
    """Return ``(seconds, microseconds)`` from a timestamp RDN value.

    Accepts the historical ``<sec>-0<8 digits>`` format and a plain
    ``<sec>-<6 digits microseconds>`` format.
    """
    seconds, _, frac = timestamp.partition("-")
    if not seconds.isdigit() or (frac and not frac.isdigit()):
        return None
    if len(frac) == 9 and frac.startswith("0"):
        micros = int(frac[1:7])
    elif frac:
        micros = int(frac[:6].ljust(6, "0")) if len(frac) > 6 else int(frac)
    else:
        micros = 0
    return int(seconds), micros


class SnapshotService:
    """Create, list, restore and delete snapshots."""

    def __init__(
        self,
        directory: DirectoryClient,
        *,
        snapshot_base: str | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._dir = directory
        self.snapshot_base = snapshot_base or dnlib.join(schema.RDN.SNAPSHOTS, directory.base_dn)
        self._clock = clock or time.time

    def create(
        self,
        object_dn: str,
        *,
        object_type: str | None = None,
        source: str = "Heracles",
        description: str | None = None,
    ) -> Snapshot:
        """Snapshot ``object_dn`` and its subtree.

        Raises:
            NoSuchObjectError: the object does not exist.
        """
        entries = sorted(
            self._dir.search(object_dn, "(objectClass=*)", Scope.SUBTREE),
            key=lambda e: dnlib.depth(e.dn),
        )
        ldif = dump_ldif(entries).encode("utf-8")
        digest = hashlib.md5(ldif, usedforsecurity=False).hexdigest()
        blob = zlib.compress(ldif, _ZLIB_LEVEL)
        ensure_container(self._dir, self.snapshot_base)
        now = self._clock()
        for bump in range(_MAX_ATTEMPTS):
            stamp = _timestamp(now, bump)
            snap_dn = f"{_A.SNAPSHOT_TIMESTAMP}={stamp},{self.snapshot_base}"
            attrs: dict[str, list[bytes]] = {
                "objectClass": [schema.OC.SNAPSHOT.encode()],
                _A.SNAPSHOT_TIMESTAMP: [stamp.encode()],
                _A.SNAPSHOT_DN: [object_dn.encode("utf-8")],
                _A.SNAPSHOT_DATA: [blob],
                _A.SNAPSHOT_HASH: [digest.encode()],
                _A.SNAPSHOT_DATA_SOURCE: [source.encode("utf-8")],
            }
            if object_type:
                attrs[_A.SNAPSHOT_OBJECT_TYPE] = [object_type.encode("utf-8")]
            if description:
                attrs[schema.STD_ATTR.DESCRIPTION] = [description.encode("utf-8")]
            try:
                self._dir.add(snap_dn, attrs)
            except AlreadyExistsError:
                continue
            return Snapshot(snap_dn, stamp, object_dn, object_type, source, description, digest)
        raise SnapshotError("could not allocate a unique snapshot timestamp")

    def get(self, snapshot_dn: str) -> Snapshot | None:
        """Metadata of one snapshot, or ``None``."""
        entry = self._dir.get(
            snapshot_dn,
            [
                _A.SNAPSHOT_TIMESTAMP,
                _A.SNAPSHOT_DN,
                _A.SNAPSHOT_HASH,
                _A.SNAPSHOT_DATA_SOURCE,
                _A.SNAPSHOT_OBJECT_TYPE,
                schema.STD_ATTR.DESCRIPTION,
                "objectClass",
            ],
        )
        if entry is None or not entry.has_object_class(schema.OC.SNAPSHOT):
            return None
        return self._to_snapshot(entry)

    def list_for_dn(self, object_dn: str) -> list[Snapshot]:
        """Snapshots of ``object_dn``, newest first."""
        flt = f"({_A.SNAPSHOT_DN}={escape_filter_value(object_dn)})"
        return [
            s for s in self._list(flt) if dnlib.normalize(s.object_dn) == dnlib.normalize(object_dn)
        ]

    def list_all(self) -> list[Snapshot]:
        """Every snapshot, newest first."""
        return self._list("(objectClass=*)")

    def list_deleted(self, under: str | None = None) -> list[Snapshot]:
        """Latest snapshot of each object that no longer exists.

        ``under`` restricts the result to objects below that DN.
        """
        latest: dict[str, Snapshot] = {}
        for snap in self.list_all():
            key = dnlib.normalize(snap.object_dn)
            if key in latest:
                continue
            if under is not None and not dnlib.is_descendant(snap.object_dn, under):
                continue
            latest[key] = snap
        return [s for s in latest.values() if self._dir.get(s.object_dn, ["objectClass"]) is None]

    def ldif(self, snapshot_dn: str) -> str:
        """Decompressed, integrity-checked LDIF of a snapshot."""
        entry = self._dir.get(snapshot_dn)
        if entry is None:
            raise NoSuchObjectError(snapshot_dn)
        blob = entry.first(_A.SNAPSHOT_DATA)
        if blob is None:
            raise SnapshotError(f"{snapshot_dn} has no data")
        try:
            raw = zlib.decompress(blob)
        except zlib.error as exc:
            raise SnapshotError(f"{snapshot_dn} data is not valid zlib") from exc
        expected = entry.text(_A.SNAPSHOT_HASH)
        if expected and hashlib.md5(raw, usedforsecurity=False).hexdigest() != expected.lower():
            raise SnapshotError(f"{snapshot_dn} failed its integrity check")
        return raw.decode("utf-8")

    def restore(self, snapshot_dn: str) -> list[str]:
        """Re-import the snapshot, replacing the existing subtree.

        Returns the DNs written, parents first.

        Raises:
            NoSuchObjectError: the snapshot, or the parent of the restored
                object, does not exist.
        """
        records = sorted(parse_ldif(self.ldif(snapshot_dn)), key=lambda e: dnlib.depth(e.dn))
        if not records:
            raise SnapshotError(f"{snapshot_dn} is empty")
        root = records[0].dn
        parent = dnlib.parent(root)
        if parent is not None and self._dir.get(parent, ["objectClass"]) is None:
            raise NoSuchObjectError(parent)
        if self._dir.get(root, ["objectClass"]) is not None:
            self._dir.delete(root, recursive=True)
        for entry in records:
            self._dir.add(entry.dn, entry.attrs)
        return [e.dn for e in records]

    def delete(self, snapshot_dn: str) -> None:
        """Remove a snapshot entry."""
        self._dir.delete(snapshot_dn)

    def prune(self, retention_days: int, min_retention_days: int | None = None) -> list[str]:
        """Delete the snapshots older than ``retention_days``.

        ``min_retention_days`` keeps the most recent snapshots whatever the
        retention says. Returns the DNs removed.
        """
        if retention_days <= 0:
            return []
        now = self._clock()
        cutoff = now - retention_days * 86_400
        floor = now - (min_retention_days or 0) * 86_400
        removed: list[str] = []
        for snapshot in self.list_all():
            created = snapshot.created_at
            if created is None:
                continue
            moment = created.timestamp()
            if moment >= cutoff or moment > floor:
                continue
            self._dir.delete(snapshot.dn)
            removed.append(snapshot.dn)
        return removed

    def _list(self, flt: str) -> list[Snapshot]:
        full = f"(&(objectClass={schema.OC.SNAPSHOT}){flt})"
        attrs = [
            _A.SNAPSHOT_TIMESTAMP,
            _A.SNAPSHOT_DN,
            _A.SNAPSHOT_HASH,
            _A.SNAPSHOT_DATA_SOURCE,
            _A.SNAPSHOT_OBJECT_TYPE,
            schema.STD_ATTR.DESCRIPTION,
        ]
        try:
            entries = list(self._dir.search(self.snapshot_base, full, Scope.ONE, attrs))
        except NoSuchObjectError:
            return []
        snaps = [self._to_snapshot(e) for e in entries]
        return sorted(snaps, key=lambda s: _sort_key(s.timestamp), reverse=True)

    @staticmethod
    def _to_snapshot(entry: Entry) -> Snapshot:
        return Snapshot(
            dn=entry.dn,
            timestamp=entry.text(_A.SNAPSHOT_TIMESTAMP) or "",
            object_dn=entry.text(_A.SNAPSHOT_DN) or "",
            object_type=entry.text(_A.SNAPSHOT_OBJECT_TYPE),
            source=entry.text(_A.SNAPSHOT_DATA_SOURCE) or "",
            description=entry.text(schema.STD_ATTR.DESCRIPTION),
            hash=entry.text(_A.SNAPSHOT_HASH),
        )


def _sort_key(timestamp: str) -> tuple[int, int]:
    return _parse_timestamp(timestamp) or (0, 0)
