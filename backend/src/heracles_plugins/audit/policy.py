"""Audit retention and forwarding that keep the hash chain verifiable.

* :func:`purge_events` deletes a contiguous prefix of the chain (oldest sequence numbers
  first), records the newest purged event as the chain base *before* deleting, and writes
  one ``purge`` event describing the purge (never one event per purged event).
* :func:`forward_events` sends the events not yet forwarded, in chain order, and moves the
  forwarding position only past the events the collector accepted.
* :func:`send_anchor` writes the chain head to the syslog stream: a copy outside the
  directory that a later rewrite of the whole chain cannot match.
* :func:`run_policy` runs them from the ``audit`` configuration, throttled, at each
  scheduler pass.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from heracles.core import audit_chain as chain
from heracles.core.audit import EVENT_CLASS, audit_container, write_event
from heracles.core.generalized_time import parse_generalized_time
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry, NoSuchObjectError, Scope
from heracles.tasks.syslog import AuditConfig, RecordSender

log = structlog.get_logger(__name__)

#: Most events forwarded in one pass (the rest follow at the next ones).
FORWARD_BATCH = 5000
#: Seconds between two purges by the configured policy.
PURGE_INTERVAL = 3600.0
PURGE_ACTION = "purge"

_PURGE_ATTRS = ("cn", "hrcAuditDateTime", chain.SEQUENCE_ATTR, chain.HASH_ATTR)


@dataclass(slots=True)
class PurgeResult:
    purged: int = 0
    through: int = 0  # newest purged sequence number (0: none)
    errors: int = 0


def _time(entry: Entry) -> datetime | None:
    raw = entry.text("hrcAuditDateTime")
    if not raw:
        return None
    try:
        moment = parse_generalized_time(raw)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _events(directory: DirectoryClient, container: str, attrs: tuple[str, ...]) -> list[Entry]:
    try:
        return list(
            directory.search(container, f"(objectClass={EVENT_CLASS})", Scope.ONE, list(attrs))
        )
    except NoSuchObjectError:
        return []


def purge_events(
    directory: DirectoryClient,
    now: datetime,
    *,
    days: int = 0,
    count: int = 0,
    source: str = "task audit",
) -> PurgeResult:
    """Apply a retention policy: events older than ``days``, beyond the newest ``count``.

    Chained events go in sequence order, so the chain stays verifiable from its base.
    """
    result = PurgeResult()
    if days <= 0 and count <= 0:
        return result
    container = audit_container(directory)
    entry = chain.read_container(directory, container)
    if entry is None:
        return result
    base = chain.base_of(entry)
    cutoff = now - timedelta(days=days) if days > 0 else None
    chained: list[tuple[int, Entry]] = []
    legacy: list[Entry] = []
    for event in _events(directory, container, _PURGE_ATTRS):
        seq = chain.sequence_of(event)
        if seq is None:
            legacy.append(event)
        else:
            chained.append((seq, event))
    chained.sort(key=lambda pair: pair[0])
    live = [(s, e) for s, e in chained if s > base.sequence]

    through = 0
    if cutoff is not None:
        for seq, event in live:
            moment = _time(event)
            if moment is not None and moment < cutoff:
                through = max(through, seq)
    if count > 0 and len(live) > count:
        through = max(through, live[len(live) - count - 1][0])
    victims = [e for s, e in chained if s <= max(through, base.sequence)]
    if through:
        newest = next(e for s, e in live if s == through)
        chain.set_base(
            directory, container, chain.Link(through, newest.text(chain.HASH_ATTR) or "")
        )
        result.through = through
        oldest_kept = next((e for s, e in live if s > through), None)
        kept_from = _time(oldest_kept) if oldest_kept is not None else None
    else:
        kept_from = None
    for event in legacy:
        moment = _time(event)
        if moment is None:
            continue
        if (cutoff is not None and moment < cutoff) or (
            kept_from is not None and moment < kept_from
        ):
            victims.append(event)
    for event in victims:
        try:
            directory.delete(event.dn)
        except NoSuchObjectError:
            continue
        except DirectoryError as exc:
            result.errors += 1
            log.warning("audit_purge_failed", dn=event.dn, error=type(exc).__name__)
            continue
        result.purged += 1
    if result.purged:
        policy: list[str] = []
        if days > 0:
            policy.append(f"{days} days")
        if count > 0:
            policy.append(f"{count} events")
        lines = [f"events purged: {result.purged}", f"retention: {', '.join(policy)}"]
        if through:
            lines.append(f"through sequence: {through}")
        lines.append(f"source: {source}")
        try:
            write_event(
                directory,
                action=PURGE_ACTION,
                object_type="audit_event",
                object_dn=container,
                author_dn="",
                attributes=lines,
                now=now,
            )
        except DirectoryError as exc:
            log.warning("audit_purge_event_failed", error=type(exc).__name__)
    return result


def forward_events(
    directory: DirectoryClient, sender: RecordSender, *, batch: int = FORWARD_BATCH
) -> int:
    """Send the events after the forwarding position; returns how many were accepted.

    The first run starts at the current head (the history is not replayed).
    """
    container = audit_container(directory)
    entry = chain.read_container(directory, container)
    head = chain.head_of(entry)
    if entry is None or head is None:
        return 0
    position = chain.forwarded_of(entry)
    if position is None:
        chain.set_forwarded(directory, container, head.sequence)
        return 0
    if position >= head.sequence:
        return 0
    flt = f"(&(objectClass={EVENT_CLASS})({chain.SEQUENCE_ATTR}>={position + 1}))"
    try:
        found = list(directory.search(container, flt, Scope.ONE, list(chain.EVENT_ATTRS)))
    except NoSuchObjectError:
        return 0
    pending = sorted(
        ((s, e) for e in found if (s := chain.sequence_of(e)) is not None and s > position),
        key=lambda pair: pair[0],
    )[:batch]
    sent = 0
    last = position
    try:
        for seq, event in pending:
            sender.send_record(chain.event_record(event))
            sent += 1
            last = seq
    except OSError as exc:
        log.warning("audit.syslog_send_failed", sequence=last + 1, error=str(exc))
    if last != position:
        chain.set_forwarded(directory, container, last)
    return sent


def send_anchor(directory: DirectoryClient, sender: RecordSender, now: datetime) -> bool:
    """Write the chain head to the syslog stream; whether the collector took it."""
    head = chain.head_of(chain.read_container(directory, audit_container(directory)))
    if head is None:
        return False
    record = {
        "kind": "anchor",
        "sequence": head.sequence,
        "hash": head.hash,
        "time": now.astimezone(UTC).isoformat(),
        "directory": directory.base_dn,
    }
    try:
        sender.send_record(record)
    except OSError as exc:
        log.warning("audit.syslog_anchor_failed", error=str(exc))
        return False
    log.info("audit_chain_anchor", sequence=head.sequence, hash=head.hash)
    return True


@dataclass(slots=True)
class PolicyReport:
    purged: int = 0
    forwarded: int = 0
    anchored: bool = False


class _Throttle:
    """When each directory last purged and anchored (per process; the scheduler lease keeps
    one process running the passes, a lease moving only repeats one of them)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[tuple[str, str], datetime] = {}

    def due(self, kind: str, key: str, now: datetime, every: float) -> bool:
        with self._lock:
            last = self._last.get((kind, key))
            return last is None or (now - last).total_seconds() >= every

    def done(self, kind: str, key: str, now: datetime) -> None:
        with self._lock:
            self._last[(kind, key)] = now

    def reset(self) -> None:
        with self._lock:
            self._last.clear()


throttle = _Throttle()


def run_policy(
    directory: DirectoryClient,
    now: datetime,
    config: AuditConfig,
    sender: RecordSender | None,
) -> PolicyReport:
    """One scheduler pass of the configured policy (never raises directory errors)."""
    report = PolicyReport()
    key = directory.base_dn
    try:
        if sender is not None:
            report.forwarded = forward_events(directory, sender)
        retention = config.retention
        if retention.active and throttle.due("purge", key, now, PURGE_INTERVAL):
            report.purged = purge_events(
                directory, now, days=retention.days, count=retention.count, source="policy"
            ).purged
            throttle.done("purge", key, now)
            if sender is not None and report.purged:
                report.forwarded += forward_events(directory, sender)  # the purge event
        if (
            sender is not None
            and config.anchor_minutes > 0
            and throttle.due("anchor", key, now, config.anchor_minutes * 60)
        ):
            report.anchored = send_anchor(directory, sender, now)
            if report.anchored:
                throttle.done("anchor", key, now)
    except DirectoryError as exc:
        log.warning("audit_policy_failed", error=type(exc).__name__)
    return report


__all__ = [
    "PURGE_ACTION",
    "PolicyReport",
    "PurgeResult",
    "forward_events",
    "purge_events",
    "run_policy",
    "send_anchor",
    "throttle",
]
