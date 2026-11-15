"""Access reviews: campaigns asking reviewers to keep or revoke existing grants.

A campaign snapshots the memberships of the selected groups and roles (listed DNs and/or every
group and role below a department) when it is created. Each item gets a reviewer: an owner of
the group or role, or the member's manager (``reviewer``), falling back to the campaign's
creator; nobody reviews their own access. Reviewers decide ``keep`` or ``revoke`` until the
deadline. Closing applies the revocations (through the object service, the closer as author),
treats undecided items as the campaign's ``default``, and records each item's outcome; a close
that stopped half way can be run again (it only touches items not applied yet). The report is
a deterministic document; its SHA-256 goes into the ``access_review`` audit event of the close,
so the hash chain of the audit log vouches for it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import secrets
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any

import structlog

from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry, NoSuchObjectError, Scope
from heracles.storage import Database
from heracles_plugins.access import approvals as ap
from heracles_plugins.access import grants as g

log = structlog.get_logger(__name__)

COMPONENT = "access_reviews"

MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE access_reviews (
        id TEXT PRIMARY KEY,
        directory_id TEXT NOT NULL,
        name TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL,
        deadline REAL NOT NULL,
        reviewer_rule TEXT NOT NULL,
        default_decision TEXT NOT NULL,
        status TEXT NOT NULL,
        selector TEXT NOT NULL,
        closed_by TEXT NOT NULL DEFAULT '',
        closed_at REAL,
        report_hash TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE access_review_items (
        campaign_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        holder_dn TEXT NOT NULL,
        holder_label TEXT NOT NULL,
        kind TEXT NOT NULL,
        member_dn TEXT NOT NULL,
        reviewer_dn TEXT NOT NULL,
        reviewer_key TEXT NOT NULL,
        decision TEXT NOT NULL DEFAULT '',
        comment TEXT NOT NULL DEFAULT '',
        decided_by TEXT NOT NULL DEFAULT '',
        decided_at REAL,
        outcome TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (campaign_id, item_id)
    );
    CREATE INDEX access_review_items_reviewer ON access_review_items (reviewer_key);
    """,
)

OPEN = "open"
CLOSING = "closing"
CLOSED = "closed"
KEEP = "keep"
REVOKE = "revoke"
REVIEWER_RULES = ("owner", "manager")

#: Item outcomes after the close.
KEPT = "kept"
REVOKED = "revoked"
GONE = "gone"  # the membership or the entry was gone at close (removed or renamed meanwhile)
KEPT_LAST = "kept: last member"
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Campaign:
    id: str
    directory_id: str
    name: str
    created_by: str
    created_at: float
    deadline: float
    reviewer_rule: str
    default_decision: str
    status: str
    selector: dict[str, Any]
    closed_by: str = ""
    closed_at: float | None = None
    report_hash: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "deadline": self.deadline,
            "reviewer": self.reviewer_rule,
            "default": self.default_decision,
            "status": self.status,
            "selector": self.selector,
            "closed_by": self.closed_by,
            "closed_at": self.closed_at,
            "report_hash": self.report_hash,
        }


@dataclass(frozen=True, slots=True)
class Item:
    campaign_id: str
    item_id: str
    holder_dn: str
    holder_label: str
    kind: str
    member_dn: str
    reviewer_dn: str  # "" when nobody but the campaign managers may decide
    decision: str = ""
    comment: str = ""
    decided_by: str = ""
    decided_at: float | None = None
    outcome: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.item_id,
            "holder": {"dn": self.holder_dn, "label": self.holder_label, "kind": self.kind},
            "member": self.member_dn,
            "reviewer": self.reviewer_dn,
            "decision": self.decision,
            "comment": self.comment,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "outcome": self.outcome,
        }


_CAMPAIGN_COLS = (
    "id, directory_id, name, created_by, created_at, deadline, reviewer_rule, default_decision,"
    " status, selector, closed_by, closed_at, report_hash"
)
_ITEM_COLS = (
    "campaign_id, item_id, holder_dn, holder_label, kind, member_dn, reviewer_dn, decision,"
    " comment, decided_by, decided_at, outcome"
)
_SELECT_CAMPAIGN = "SELECT " + _CAMPAIGN_COLS + " FROM access_reviews"  # noqa: S608
_SELECT_ITEM = "SELECT " + _ITEM_COLS + " FROM access_review_items"  # noqa: S608


def _campaign(row: Any) -> Campaign:
    closed = row["closed_at"]
    return Campaign(
        id=row["id"],
        directory_id=row["directory_id"],
        name=row["name"],
        created_by=row["created_by"],
        created_at=float(row["created_at"]),
        deadline=float(row["deadline"]),
        reviewer_rule=row["reviewer_rule"],
        default_decision=row["default_decision"],
        status=row["status"],
        selector=json.loads(row["selector"] or "{}"),
        closed_by=row["closed_by"] or "",
        closed_at=None if closed is None else float(closed),
        report_hash=row["report_hash"] or "",
    )


def _item(row: Any) -> Item:
    decided = row["decided_at"]
    return Item(
        campaign_id=row["campaign_id"],
        item_id=row["item_id"],
        holder_dn=row["holder_dn"],
        holder_label=row["holder_label"],
        kind=row["kind"],
        member_dn=row["member_dn"],
        reviewer_dn=row["reviewer_dn"],
        decision=row["decision"] or "",
        comment=row["comment"] or "",
        decided_by=row["decided_by"] or "",
        decided_at=None if decided is None else float(decided),
        outcome=row["outcome"] or "",
    )


class ReviewStore:
    def __init__(self, database: Database, clock: Callable[[], float] = time.time) -> None:
        self._db = database
        self._clock = clock
        database.migrate(COMPONENT, MIGRATIONS)

    @property
    def clock(self) -> Callable[[], float]:
        return self._clock

    def create(self, campaign: Campaign, items: Sequence[Item]) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO access_reviews (" + _CAMPAIGN_COLS + ")"  # noqa: S608
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    campaign.id,
                    campaign.directory_id,
                    campaign.name,
                    campaign.created_by,
                    campaign.created_at,
                    campaign.deadline,
                    campaign.reviewer_rule,
                    campaign.default_decision,
                    campaign.status,
                    json.dumps(campaign.selector, sort_keys=True),
                    "",
                    None,
                    "",
                ),
            )
            for item in items:
                conn.execute(
                    "INSERT INTO access_review_items (" + _ITEM_COLS + ", reviewer_key)"  # noqa: S608
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.campaign_id,
                        item.item_id,
                        item.holder_dn,
                        item.holder_label,
                        item.kind,
                        item.member_dn,
                        item.reviewer_dn,
                        "",
                        "",
                        "",
                        None,
                        "",
                        dnlib.normalize(item.reviewer_dn) if item.reviewer_dn else "",
                    ),
                )

    def get(self, campaign_id: str) -> Campaign | None:
        with self._db.connection() as conn:
            row = conn.execute(_SELECT_CAMPAIGN + " WHERE id = ?", (campaign_id,)).fetchone()
        return _campaign(row) if row is not None else None

    def campaigns(self, directory_id: str) -> list[Campaign]:
        with self._db.connection() as conn:
            rows = conn.execute(
                _SELECT_CAMPAIGN + " WHERE directory_id = ? ORDER BY created_at DESC, id",
                (directory_id,),
            ).fetchall()
        return [_campaign(r) for r in rows]

    def items(self, campaign_id: str) -> list[Item]:
        with self._db.connection() as conn:
            rows = conn.execute(
                _SELECT_ITEM + " WHERE campaign_id = ? ORDER BY holder_label, member_dn, item_id",
                (campaign_id,),
            ).fetchall()
        return [_item(r) for r in rows]

    def items_for_reviewer(self, reviewer_dn: str) -> list[Item]:
        with self._db.connection() as conn:
            rows = conn.execute(
                _SELECT_ITEM + " WHERE reviewer_key = ? ORDER BY campaign_id, holder_label",
                (dnlib.normalize(reviewer_dn),),
            ).fetchall()
        return [_item(r) for r in rows]

    def decide(self, item: Item, decision: str, comment: str, by: str) -> Item:
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE access_review_items SET decision = ?, comment = ?, decided_by = ?,"
                " decided_at = ? WHERE campaign_id = ? AND item_id = ?",
                (decision, comment, by, now, item.campaign_id, item.item_id),
            )
        return replace(item, decision=decision, comment=comment, decided_by=by, decided_at=now)

    def set_outcome(self, item: Item, outcome: str) -> Item:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE access_review_items SET outcome = ? WHERE campaign_id = ? AND item_id = ?",
                (outcome, item.campaign_id, item.item_id),
            )
        return replace(item, outcome=outcome)

    def move(
        self, campaign: Campaign, from_status: str, to_status: str, **fields: Any
    ) -> Campaign | None:
        """Compare-and-set the campaign status (``None`` when it was not ``from_status``)."""
        sets = ["status = ?"]
        params: list[Any] = [to_status]
        for name in ("closed_by", "closed_at", "report_hash"):
            if name in fields:
                sets.append(f"{name} = ?")
                params.append(fields[name])
        params += [campaign.id, from_status]
        with self._db.transaction() as conn:
            cur = conn.execute(
                "UPDATE access_reviews SET " + ", ".join(sets) + " WHERE id = ? AND status = ?",  # noqa: S608
                tuple(params),
            )
            if not cur.rowcount:
                return None
        return replace(campaign, status=to_status, **fields)


# -- building a campaign -------------------------------------------------------------------------

_HOLDER_ATTRS = ["objectClass", "cn", "owner", "member", "roleOccupant"]


def select_holders(directory: DirectoryClient, holders: Iterable[str], base: str) -> list[Entry]:
    """The groups and roles a campaign covers (listed DNs, and those below ``base``)."""
    found: dict[str, Entry] = {}
    flt = "(|(objectClass=groupOfNames)(objectClass=organizationalRole))"
    for dn in holders:
        try:
            entry = next(iter(directory.search(dn, flt, Scope.BASE, _HOLDER_ATTRS)), None)
        except (NoSuchObjectError, DirectoryError):
            entry = None
        if entry is not None:
            found[dnlib.normalize(entry.dn)] = entry
    if base:
        try:
            for entry in directory.search(base, flt, Scope.SUBTREE, _HOLDER_ATTRS):
                found[dnlib.normalize(entry.dn)] = entry
        except NoSuchObjectError:
            pass
    return list(found.values())


def _manager(directory: DirectoryClient, member: str) -> str:
    try:
        entry = directory.get(member, ["manager"])
    except DirectoryError:
        return ""
    return (entry.text("manager") or "") if entry is not None else ""


def build_items(
    directory: DirectoryClient,
    campaign_id: str,
    holders: Sequence[Entry],
    rule: str,
    creator: str,
) -> list[Item]:
    items: list[Item] = []
    owners_cache: dict[str, list[str]] = {}
    for holder in holders:
        kind = ap.kind_of(holder)
        if kind is None:
            continue
        key = dnlib.normalize(holder.dn)
        if key not in owners_cache:
            owners_cache[key] = sorted(ap.expand_members(directory, holder.texts("owner")))
        for member in holder.texts(kind):
            member_key = dnlib.normalize(member)
            if rule == "manager":
                candidates = [m for m in [_manager(directory, member)] if m]
            else:
                candidates = list(owners_cache[key])
            reviewer = next((c for c in candidates if dnlib.normalize(c) != member_key), "")
            if not reviewer and dnlib.normalize(creator) != member_key:
                reviewer = creator
            items.append(
                Item(
                    campaign_id=campaign_id,
                    item_id=secrets.token_hex(6),
                    holder_dn=holder.dn,
                    holder_label=ap.label_of(holder),
                    kind=kind,
                    member_dn=member,
                    reviewer_dn=reviewer,
                )
            )
    return items


def new_campaign(
    *,
    directory_id: str,
    name: str,
    creator: str,
    deadline: float,
    rule: str,
    default: str,
    selector: dict[str, Any],
    now: float,
) -> Campaign:
    return Campaign(
        id=secrets.token_hex(8),
        directory_id=directory_id,
        name=name,
        created_by=creator,
        created_at=now,
        deadline=deadline,
        reviewer_rule=rule,
        default_decision=default,
        status=OPEN,
        selector=selector,
    )


# -- closing -----------------------------------------------------------------------------------


def effective_decision(item: Item, campaign: Campaign) -> str:
    return item.decision or campaign.default_decision


def revoke_one(
    directory: DirectoryClient,
    item: Item,
    remove: Callable[[Entry, str, list[str]], None],
) -> str:
    """Remove one reviewed membership; the outcome to record."""
    entry = g.read_primary(directory, item.holder_dn, [*_HOLDER_ATTRS, g.GRANT_ATTR])
    if entry is None:
        return GONE
    current = entry.texts(item.kind)
    wanted = dnlib.normalize(item.member_dn)
    if not any(dnlib.normalize(v) == wanted for v in current):
        return GONE
    if g.is_last_mandatory(entry, item.kind):
        return KEPT_LAST
    remove(entry, item.kind, [v for v in current if dnlib.normalize(v) != wanted])
    return REVOKED


@dataclass(slots=True)
class CloseResult:
    campaign: Campaign
    items: list[Item]
    failed: list[Item]
    digest: str = ""


class CloseConflictError(Exception):
    """The campaign is closed, or another close got there first."""


def close_campaign(
    store: ReviewStore,
    campaign: Campaign,
    directory: DirectoryClient,
    remove: Callable[[Entry, str, list[str]], None],
    closer: str,
) -> CloseResult:
    """Apply the revocations and close (``closer`` is ``""`` for the scheduler).

    Resumable: items already applied are left alone. With failures the campaign stays
    ``closing``; otherwise it is ``closed`` with the hash of its report.
    """
    if campaign.status == CLOSED:
        raise CloseConflictError("the campaign is closed")
    if campaign.status == OPEN:
        moved = store.move(campaign, OPEN, CLOSING)
        if moved is None:
            raise CloseConflictError("the campaign is being closed")
        campaign = moved
    for item in store.items(campaign.id):
        if item.outcome and item.outcome != FAILED:
            continue  # applied by an earlier close
        if effective_decision(item, campaign) == KEEP:
            store.set_outcome(item, KEPT)
            continue
        try:
            outcome = revoke_one(directory, item, remove)
        except Exception as exc:  # recorded per item; the close can be run again
            log.warning("review_revoke_failed", item=item.item_id, error=str(exc))
            outcome = FAILED
        store.set_outcome(item, outcome)
    items = store.items(campaign.id)
    failed = [i for i in items if i.outcome == FAILED]
    if failed:
        return CloseResult(campaign, items, failed)
    now = store.clock()
    doc = report(replace(campaign, closed_by=closer, closed_at=now), items)
    digest = report_hash(doc)
    closed = store.move(
        campaign, CLOSING, CLOSED, closed_by=closer, closed_at=now, report_hash=digest
    )
    if closed is None:
        raise CloseConflictError("the campaign was closed meanwhile")
    return CloseResult(closed, items, [], digest)


def close_audit_lines(result: CloseResult) -> list[str]:
    outcomes: dict[str, int] = {}
    for item in result.items:
        outcomes[item.outcome] = outcomes.get(item.outcome, 0) + 1
    return [
        f"campaign: {result.campaign.id}",
        f"name: {result.campaign.name}",
        "status: closed",
        f"report sha256: {result.digest}",
        *(f"{name}: {count}" for name, count in sorted(outcomes.items())),
    ]


# -- report ------------------------------------------------------------------------------------


def report(campaign: Campaign, items: Sequence[Item]) -> dict[str, Any]:
    """The campaign and every item with its decision and outcome (no volatile fields)."""
    return {
        "campaign": {
            "id": campaign.id,
            "name": campaign.name,
            "created_by": campaign.created_by,
            "created_at": campaign.created_at,
            "deadline": campaign.deadline,
            "reviewer": campaign.reviewer_rule,
            "default": campaign.default_decision,
            "selector": campaign.selector,
            "closed_by": campaign.closed_by,
            "closed_at": campaign.closed_at,
        },
        "items": [
            {
                "holder": i.holder_dn,
                "kind": i.kind,
                "member": i.member_dn,
                "reviewer": i.reviewer_dn,
                "decision": i.decision or f"(default) {campaign.default_decision}",
                "comment": i.comment,
                "decided_by": i.decided_by,
                "decided_at": i.decided_at,
                "outcome": i.outcome,
            }
            for i in sorted(
                items, key=lambda x: (x.holder_dn.lower(), x.member_dn.lower(), x.item_id)
            )
        ],
    }


def report_hash(doc: dict[str, Any]) -> str:
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def report_csv(doc: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    columns = [
        "holder",
        "kind",
        "member",
        "reviewer",
        "decision",
        "comment",
        "decided_by",
        "decided_at",
        "outcome",
    ]
    writer.writerow(columns)
    for row in doc["items"]:
        cells = ["" if row[c] is None else str(row[c]) for c in columns]
        writer.writerow(["'" + c if c[:1] in ("=", "+", "-", "@") else c for c in cells])
    return out.getvalue()


__all__ = [
    "CLOSED",
    "CLOSING",
    "KEEP",
    "OPEN",
    "REVIEWER_RULES",
    "REVOKE",
    "Campaign",
    "CloseConflictError",
    "CloseResult",
    "Item",
    "ReviewStore",
    "build_items",
    "close_audit_lines",
    "close_campaign",
    "effective_decision",
    "new_campaign",
    "report",
    "report_csv",
    "report_hash",
    "revoke_one",
    "select_holders",
]
