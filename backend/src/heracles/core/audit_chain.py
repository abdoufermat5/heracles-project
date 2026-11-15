"""Tamper evidence for the audit log: every event hashes the previous one.

Each event entry below ``ou=audit`` carries a sequence number (``hrcAuditSequence``), the
hash of the previous event (``hrcAuditPreviousHash``) and its own hash (``hrcAuditHash``),
computed over the stored values. The container carries the ``hrcAuditChain`` class:

* ``hrcAuditChainHead``: ``"<sequence> <hash>"`` of the newest event, so that deleting the
  newest events is detected too;
* ``hrcAuditChainBase``: ``"<sequence> <hash>"`` of the newest *purged* event, written by the
  retention purge before it deletes anything, so a legitimate purge is not a break;
* ``hrcAuditForwarded``: sequence of the last event sent to syslog.

Writers are concurrent (several workers, the scheduler, replicas) and LDAP has no
transactions, so the event ``add`` is the commit point: the event RDN is its sequence
number (``cn=0000000042``); two writers taking the same number collide on the add, and the
loser moves on to the next one. The head is updated after the add with a compare-and-swap
(delete the old value, add the new one); a head that lags behind (a writer stopped between
the two operations) is caught up by the next writer and only reported by
:func:`verify_chain`.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import structlog

from heracles.core.generalized_time import parse_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    DirectoryError,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)

log = structlog.get_logger(__name__)

EVENT_CLASS = "hrcAuditEvent"
CHAIN_CLASS = "hrcAuditChain"
HEAD_ATTR = "hrcAuditChainHead"
BASE_ATTR = "hrcAuditChainBase"
FORWARDED_ATTR = "hrcAuditForwarded"
SEQUENCE_ATTR = "hrcAuditSequence"
HASH_ATTR = "hrcAuditHash"
PREVIOUS_ATTR = "hrcAuditPreviousHash"

#: ``hrcAuditPreviousHash`` of the first event.
GENESIS = "0" * 64
#: Version of the canonical form (part of every hash).
CANONICAL_VERSION = 1
#: Attempts at taking a sequence number before giving up (then the event is written
#: without chaining, and a warning is logged).
MAX_ATTEMPTS = 64
#: Digits of the event RDN (``cn=0000000042``): RDNs sort like sequence numbers.
CN_DIGITS = 10

#: Attributes read to verify an event.
EVENT_ATTRS = (
    "cn",
    "hrcAuditDateTime",
    "hrcAuditAction",
    "hrcAuditAuthorDN",
    "hrcAuditAuthorIP",
    "hrcAuditObjectType",
    "hrcAuditObject",
    "hrcAuditAttributes",
    "hrcAuditResult",
    SEQUENCE_ATTR,
    HASH_ATTR,
    PREVIOUS_ATTR,
)
CONTAINER_ATTRS = ("objectClass", HEAD_ATTR, BASE_ATTR, FORWARDED_ATTR)


class ChainError(DirectoryError):
    """The chain cannot be extended (old schema, constant contention, damaged chain)."""


@dataclass(frozen=True, slots=True)
class Link:
    """A position in the chain: a sequence number and the hash of that event."""

    sequence: int
    hash: str

    def text(self) -> str:
        return f"{self.sequence} {self.hash}"

    @classmethod
    def parse(cls, raw: str | None) -> Link | None:
        if not raw:
            return None
        seq, _, digest = raw.strip().partition(" ")
        try:
            return cls(int(seq), digest.strip())
        except ValueError:
            return None


START = Link(0, GENESIS)


# -- canonical form ---------------------------------------------------------------------------


def _values(attrs: Mapping[str, Sequence[bytes]], name: str) -> list[str]:
    lname = name.lower()
    for key, values in attrs.items():
        if key.lower() == lname:
            return [bytes(v).decode("utf-8", "replace") for v in values]
    return []


def _one(attrs: Mapping[str, Sequence[bytes]], name: str) -> str:
    values = _values(attrs, name)
    return values[0] if values else ""


def _time(raw: str) -> str:
    """The event time in one spelling, whatever the server gives back."""
    if not raw:
        return ""
    try:
        moment = parse_generalized_time(raw)
    except ValueError:
        return raw
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y%m%d%H%M%S.%fZ")


def canonical(attrs: Mapping[str, Sequence[bytes]], sequence: int, previous: str) -> bytes:
    """The bytes an event hash covers, built from the *stored* attribute values.

    Value order of ``hrcAuditAttributes`` is not kept by LDAP and DN values can come back
    re-spelled, so the attribute lines are sorted and the author DN is normalised.
    """
    author = _one(attrs, "hrcAuditAuthorDN")
    doc = {
        "v": CANONICAL_VERSION,
        "sequence": sequence,
        "previous": previous,
        "time": _time(_one(attrs, "hrcAuditDateTime")),
        "action": _one(attrs, "hrcAuditAction"),
        "type": _one(attrs, "hrcAuditObjectType"),
        "object": _one(attrs, "hrcAuditObject"),
        "author": dnlib.normalize(author) if author else "",
        "ip": _one(attrs, "hrcAuditAuthorIP"),
        "result": _one(attrs, "hrcAuditResult"),
        "attributes": sorted(_values(attrs, "hrcAuditAttributes")),
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def event_hash(attrs: Mapping[str, Sequence[bytes]], sequence: int, previous: str) -> str:
    return hashlib.sha256(canonical(attrs, sequence, previous)).hexdigest()


def event_cn(sequence: int) -> str:
    return str(sequence).zfill(CN_DIGITS)


# -- reading the container ---------------------------------------------------------------------


def _reader(directory: DirectoryClient) -> Callable[[str, Sequence[str]], Entry | None]:
    """``get`` from a server accepting writes when the client knows one (replicas lag)."""
    primary = getattr(directory, "get_primary", None)
    if callable(primary):
        return primary  # type: ignore[return-value]
    return directory.get


def read_container(directory: DirectoryClient, container: str) -> Entry | None:
    return _reader(directory)(container, list(CONTAINER_ATTRS))


def head_of(entry: Entry | None) -> Link | None:
    return Link.parse(entry.text(HEAD_ATTR)) if entry is not None else None


def base_of(entry: Entry | None) -> Link:
    return (Link.parse(entry.text(BASE_ATTR)) if entry is not None else None) or START


def _start_chain(directory: DirectoryClient, container: str) -> None:
    """Give the container the chain class and an empty head (once; races are harmless)."""
    entry = read_container(directory, container)
    if entry is None:
        raise NoSuchObjectError(container)
    if head_of(entry) is not None:
        return
    changes = [Modification("add", HEAD_ATTR, [START.text().encode()])]
    if not entry.has_object_class(CHAIN_CLASS):
        changes.insert(0, Modification("add", "objectClass", [CHAIN_CLASS.encode()]))
    try:
        directory.modify(container, changes)
    except DirectoryError:
        if head_of(read_container(directory, container)) is None:
            raise


def _move_head(directory: DirectoryClient, container: str, seen: Link, new: Link) -> None:
    """Compare-and-swap the head from ``seen`` to ``new``; never moves it backwards."""
    current = seen
    for _ in range(MAX_ATTEMPTS):
        try:
            directory.modify(
                container,
                [
                    Modification("delete", HEAD_ATTR, [current.text().encode()]),
                    Modification("add", HEAD_ATTR, [new.text().encode()]),
                ],
            )
            return
        except DirectoryError:
            found = head_of(read_container(directory, container))
            if found is None or found.sequence >= new.sequence:
                return  # someone else moved it on (or the chain was reset)
            current = found
    log.warning("audit_chain_head_stuck", sequence=new.sequence)


# -- appending ---------------------------------------------------------------------------------


def append(
    directory: DirectoryClient,
    container: str,
    attrs: Mapping[str, Sequence[bytes]],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Add ``attrs`` (an event without RDN and chain values) as the next event; its DN.

    Raises :class:`ChainError` when the chain cannot be extended; the caller then writes
    the event without chaining.
    """
    try:
        _start_chain(directory, container)
        head = head_of(read_container(directory, container))
    except DirectoryError as exc:
        raise ChainError(f"chain unavailable: {exc}") from exc
    if head is None:
        raise ChainError("chain head missing")
    previous = head
    read = _reader(directory)
    for attempt in range(MAX_ATTEMPTS):
        sequence = previous.sequence + 1
        cn = event_cn(sequence)
        full: dict[str, list[bytes]] = {k: list(v) for k, v in attrs.items()}
        full["cn"] = [cn.encode()]
        full[SEQUENCE_ATTR] = [str(sequence).encode()]
        full[PREVIOUS_ATTR] = [previous.hash.encode()]
        full[HASH_ATTR] = [event_hash(full, sequence, previous.hash).encode()]
        dn = f"cn={cn},{container}"
        try:
            directory.add(dn, full)
        except AlreadyExistsError:
            taken = read(dn, [HASH_ATTR, SEQUENCE_ATTR])
            digest = taken.text(HASH_ATTR) if taken is not None else None
            if taken is not None and digest:
                previous = Link(sequence, digest)
            elif taken is not None:
                raise ChainError(f"event {sequence} carries no hash") from None
            else:  # deleted under us, or not visible yet
                sleep(0.01 * (attempt + 1))
            continue
        except DirectoryError as exc:
            raise ChainError(f"event refused: {exc}") from exc
        _move_head(directory, container, head, Link(sequence, full[HASH_ATTR][0].decode()))
        return dn
    raise ChainError("no free sequence number")


def set_base(directory: DirectoryClient, container: str, base: Link) -> None:
    """Record the newest purged event (before purging it)."""
    directory.modify(container, [Modification("replace", BASE_ATTR, [base.text().encode()])])


def set_forwarded(directory: DirectoryClient, container: str, sequence: int) -> None:
    directory.modify(container, [Modification("replace", FORWARDED_ATTR, [str(sequence).encode()])])


def forwarded_of(entry: Entry | None) -> int | None:
    raw = entry.text(FORWARDED_ATTR) if entry is not None else None
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def event_record(entry: Entry) -> dict[str, Any]:
    """An event as plain data (syslog forwarding, exports)."""
    raw = entry.text("hrcAuditDateTime") or ""
    try:
        moment = parse_generalized_time(raw)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        when = moment.astimezone(UTC).isoformat()
    except ValueError:
        when = raw
    return {
        "kind": "event",
        "sequence": sequence_of(entry),
        "hash": entry.text(HASH_ATTR) or "",
        "previous": entry.text(PREVIOUS_ATTR) or "",
        "dn": entry.dn,
        "time": when,
        "action": entry.text("hrcAuditAction") or "",
        "type": entry.text("hrcAuditObjectType") or "",
        "object": entry.text("hrcAuditObject") or "",
        "author": entry.text("hrcAuditAuthorDN") or "",
        "ip": entry.text("hrcAuditAuthorIP") or "",
        "result": entry.text("hrcAuditResult") or "success",
        "attributes": [v.decode("utf-8", "replace") for v in entry.get("hrcAuditAttributes")],
    }


# -- verification ------------------------------------------------------------------------------


@dataclass(slots=True)
class Break:
    """Where the chain stops being trustworthy."""

    sequence: int
    dn: str
    reason: str

    def to_json(self) -> dict[str, object]:
        return {"sequence": self.sequence, "dn": self.dn, "reason": self.reason}


@dataclass(slots=True)
class Verification:
    """What :func:`verify_chain` found."""

    checked: int = 0
    unchained: int = 0
    base: Link = START
    head: Link | None = None
    last: Link | None = None
    first_break: Break | None = None
    warnings: list[str] = field(default_factory=lambda: [])

    @property
    def ok(self) -> bool:
        return self.first_break is None

    def to_json(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "unchained": self.unchained,
            "base": self.base.text(),
            "head": self.head.text() if self.head else None,
            "first_break": self.first_break.to_json() if self.first_break else None,
            "warnings": list(self.warnings),
        }


def sequence_of(entry: Entry) -> int | None:
    raw = entry.text(SEQUENCE_ATTR)
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def verify_events(
    events: Iterable[Entry], *, base: Link = START, head: Link | None = None
) -> Verification:
    """Check a set of event entries against the chain rules.

    Every sequence number above ``base`` up to the newest must be present exactly once,
    link to the previous hash and hash to its stored value; ``head`` must name the newest.
    """
    result = Verification(base=base, head=head)
    chained: dict[int, Entry] = {}
    for entry in events:
        seq = sequence_of(entry)
        if seq is None:
            result.unchained += 1
            continue
        if seq <= base.sequence:
            continue  # purged range: a purge left it behind
        if seq in chained:
            result.first_break = result.first_break or Break(seq, entry.dn, "duplicate sequence")
            continue
        chained[seq] = entry
    if result.first_break is not None:
        return result
    previous = base
    for seq in sorted(chained):
        entry = chained[seq]
        if seq != previous.sequence + 1:
            result.first_break = Break(
                previous.sequence + 1,
                "",
                f"events {previous.sequence + 1} to {seq - 1} are missing",
            )
            return result
        stored_prev = entry.text(PREVIOUS_ATTR) or ""
        if stored_prev != previous.hash:
            result.first_break = Break(seq, entry.dn, "does not link to the previous event")
            return result
        digest = entry.text(HASH_ATTR) or ""
        if event_hash(entry.attrs, seq, stored_prev) != digest:
            result.first_break = Break(seq, entry.dn, "content altered (hash mismatch)")
            return result
        previous = Link(seq, digest)
        result.checked += 1
    result.last = previous if chained else None
    if head is None:
        if chained:
            result.first_break = Break(previous.sequence, "", "chain head missing")
        return result
    if head.sequence > previous.sequence:
        result.first_break = Break(
            previous.sequence + 1,
            "",
            f"events {previous.sequence + 1} to {head.sequence} are missing (newest deleted)",
        )
    elif head.sequence == previous.sequence and head.hash != previous.hash:
        result.first_break = Break(head.sequence, "", "chain head does not match the newest event")
    elif head.sequence < previous.sequence:
        result.warnings.append(
            f"chain head ({head.sequence}) lags behind the newest event ({previous.sequence})"
        )
    if result.unchained and chained:
        result.warnings.append(
            f"{result.unchained} events carry no sequence number (written before chaining, "
            "or when the chain was unavailable)"
        )
    return result


def verify_chain(directory: DirectoryClient, container: str) -> Verification:
    """Verify the audit log of ``directory`` (see :func:`verify_events`)."""
    entry = read_container(directory, container)
    if entry is None:
        return Verification()
    try:
        events = list(
            directory.search(
                container, f"(objectClass={EVENT_CLASS})", Scope.ONE, list(EVENT_ATTRS)
            )
        )
    except NoSuchObjectError:
        events = []
    return verify_events(events, base=base_of(entry), head=head_of(entry))


__all__ = [
    "BASE_ATTR",
    "CHAIN_CLASS",
    "GENESIS",
    "HASH_ATTR",
    "HEAD_ATTR",
    "PREVIOUS_ATTR",
    "SEQUENCE_ATTR",
    "Break",
    "ChainError",
    "Link",
    "Verification",
    "append",
    "canonical",
    "event_hash",
    "event_record",
    "read_container",
    "set_base",
    "verify_chain",
    "verify_events",
]
