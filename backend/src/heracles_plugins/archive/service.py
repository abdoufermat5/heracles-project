"""Archiving of objects: copy selected attributes to an ``fdArchivedObject`` entry."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from heracles.core.containers import ensure_container
from heracles.core.generalized_time import format_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    Entry,
    NoSuchObjectError,
    Scope,
)
from heracles.ldap.filter import escape_filter_value
from heracles.objects.policy import EventContext, NullEvents

ARCHIVE_CLASS = "fdArchivedObject"
ARCHIVE_RDN = "ou=archive"
_SAFE = re.compile(r"[^A-Za-z0-9._@-]+")


class ArchiveError(Exception):
    """The object cannot be archived."""


@dataclass(slots=True)
class ArchiveRule:
    """What to keep of one object type."""

    #: Attributes copied to the archive.
    fields: tuple[str, ...]
    #: Attributes identifying the object (they must have a value); a subset of the kept data.
    unique_fields: tuple[str, ...]


def default_rules() -> dict[str, ArchiveRule]:
    return {
        "user": ArchiveRule(
            fields=(
                "uid",
                "cn",
                "givenName",
                "sn",
                "mail",
                "telephoneNumber",
                "mobile",
                "employeeNumber",
                "employeeType",
                "departmentNumber",
                "uidNumber",
                "gidNumber",
                "description",
            ),
            unique_fields=("uid",),
        ),
        "group": ArchiveRule(fields=("cn", "description", "member"), unique_fields=("cn",)),
    }


@dataclass(slots=True)
class ArchiveSettings:
    """Settings of the archive plugin."""

    #: Archives older than this are purged by the archive task; 0 keeps them forever.
    retention_days: int = 1825
    #: Archive rules by object type name.
    rules: dict[str, ArchiveRule] = field(default_factory=default_rules)


def archive_container(directory: DirectoryClient) -> str:
    return dnlib.join(ARCHIVE_RDN, directory.base_dn)


def _pairs(entry: Entry, names: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for name in names:
        for raw in entry.get(name):
            try:
                out.append(f"{name}={raw.decode('utf-8')}")
            except UnicodeDecodeError:
                continue  # binary values are not archived
    return out


def archive(
    directory: DirectoryClient,
    dn: str,
    type_name: str,
    *,
    settings: ArchiveSettings | None = None,
    now: datetime | None = None,
) -> str:
    """Archive the object ``dn`` of type ``type_name``; returns the DN of the archive entry.

    The archive keeps the attributes of the type's rule as ``name=value`` values, the unique
    fields separately (to find it back with :func:`find_archives`), the date, the type and
    the original DN. The archived object itself is left untouched.

    Raises :class:`ArchiveError` when the type has no rule or the object has no value for a
    unique field, and ``NoSuchObjectError`` when ``dn`` does not exist.
    """
    settings = settings or ArchiveSettings()
    rule = settings.rules.get(type_name)
    if rule is None:
        raise ArchiveError(f"objects of type {type_name!r} are not archived")
    entry = directory.get(dn)
    if entry is None:
        raise NoSuchObjectError(dn)
    unique = _pairs(entry, rule.unique_fields)
    missing = [f for f in rule.unique_fields if not entry.get(f)]
    if missing or not unique:
        raise ArchiveError(f"no value for the unique field {', '.join(missing or ['?'])}")
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    attrs: dict[str, list[bytes]] = {
        "objectClass": [ARCHIVE_CLASS.encode()],
        "fdArchivedDateTime": [format_generalized_time(moment).encode()],
        "fdArchivedObjectType": [type_name.encode()],
        "fdArchivedOriginDn": [dn.encode()],
        "fdArchivedUniqueField": [u.encode() for u in unique],
    }
    kept = _pairs(entry, tuple(dict.fromkeys([*rule.fields, *rule.unique_fields])))
    attrs["fdArchivedField"] = [k.encode() for k in kept]
    key = _SAFE.sub("_", "_".join(u.partition("=")[2] for u in unique)).strip("_") or "object"
    stem = f"{type_name}_{key}_{moment.strftime('%Y%m%d%H%M%S')}"
    container = archive_container(directory)
    ensure_container(directory, container)
    for attempt in range(1, 100):
        cn = stem if attempt == 1 else f"{stem}-{attempt}"
        attrs["cn"] = [cn.encode()]
        new_dn = f"cn={cn},{container}"
        try:
            directory.add(new_dn, attrs)
        except AlreadyExistsError:
            continue
        return new_dn
    raise ArchiveError("cannot find a free archive name")


def find_archives(
    directory: DirectoryClient, type_name: str, unique: Mapping[str, str]
) -> list[Entry]:
    """Archive entries of ``type_name`` whose unique fields equal ``unique`` (newest first)."""
    parts = "".join(
        f"(fdArchivedUniqueField={escape_filter_value(f'{k}={v}')})" for k, v in unique.items()
    )
    flt = (
        f"(&(objectClass={ARCHIVE_CLASS})"
        f"(fdArchivedObjectType={escape_filter_value(type_name)}){parts})"
    )
    try:
        found = list(directory.search(archive_container(directory), flt, Scope.ONE))
    except NoSuchObjectError:
        return []
    found.sort(key=lambda e: (e.text("fdArchivedDateTime") or "", e.dn), reverse=True)
    return found


@dataclass(slots=True)
class ArchiveBeforeDelete(NullEvents):
    """``ObjectEvents`` archiving every deleted object whose type has a rule.

    Wiring (not done by the framework): pass it as ``events=`` of the ``ObjectService``
    handling deletions. The archive is written before the object is deleted; a failure
    vetoes the deletion (``ArchiveError`` or a directory error propagates).
    """

    directory: DirectoryClient
    settings: ArchiveSettings = field(default_factory=ArchiveSettings)

    def pre_delete(self, ctx: EventContext) -> None:
        if ctx.type_name in self.settings.rules:
            archive(self.directory, ctx.dn, ctx.type_name, settings=self.settings)
