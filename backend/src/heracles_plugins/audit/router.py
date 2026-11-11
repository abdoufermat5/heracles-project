"""``GET /api/v2/audit``: search, page through and export the audit log."""

from __future__ import annotations

import base64
import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import Response

from heracles.api.deps import CurrentUserDep
from heracles.api.domain import DomainDep
from heracles.api.errors import forbidden, validation
from heracles.attributes import JSON
from heracles.core.audit import EVENT_CLASS, audit_container
from heracles.core.generalized_time import parse_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry, NoSuchObjectError, Scope
from heracles.ldap.filter import escape_filter_value
from heracles.objects.registry import PluginRouterContext

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
#: Most rows an export contains.
MAX_EXPORT = 50_000
#: Attributes tried, in order, to give a directory entry a readable label.
LABEL_ATTRS = ("displayName", "cn", "uid", "ou", "o", "l", "c", "dc", "description")
_EVENT_ATTRS = (
    "cn",
    "hrcAuditDateTime",
    "hrcAuditAction",
    "hrcAuditAuthorDN",
    "hrcAuditAuthorIP",
    "hrcAuditObjectType",
    "hrcAuditObject",
    "hrcAuditAttributes",
    "hrcAuditResult",
)


@dataclass(slots=True)
class Event:
    """One audit entry, parsed."""

    dn: str
    time: datetime
    action: str
    author: str
    ip: str
    object_type: str
    object: str
    attributes: list[str]
    result: str

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.time.strftime("%Y%m%d%H%M%S%f"), self.dn)


def parse_event(entry: Entry) -> Event | None:
    raw = entry.text("hrcAuditDateTime")
    if not raw:
        return None
    try:
        moment = parse_generalized_time(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return Event(
        dn=entry.dn,
        time=moment.astimezone(UTC),
        action=entry.text("hrcAuditAction") or "",
        author=entry.text("hrcAuditAuthorDN") or "",
        ip=entry.text("hrcAuditAuthorIP") or "",
        object_type=entry.text("hrcAuditObjectType") or "",
        object=entry.text("hrcAuditObject") or "",
        attributes=[v.decode("utf-8", "replace") for v in entry.get("hrcAuditAttributes")],
        result=entry.text("hrcAuditResult") or "success",
    )


def parse_moment(text: str | None, field: str, *, end: bool = False) -> datetime | None:
    """An ISO date or date-time (UTC when no offset); a bare date ``to`` covers that day."""
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise validation("Invalid date", {field: "Use an ISO date or date-time"}) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if end and len(text) == 10:
        moment = moment.replace(hour=23, minute=59, second=59, microsecond=999999)
    return moment.astimezone(UTC)


def encode_cursor(event: Event) -> str:
    return base64.urlsafe_b64encode("|".join(event.sort_key).encode()).decode()


def decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        stamp, _, dn = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
    except (ValueError, UnicodeDecodeError):
        raise validation("Invalid cursor", {"cursor": "Invalid cursor"}) from None
    return (stamp, dn)


class Labels:
    """Best-effort DN to readable label resolution, cached for one request."""

    def __init__(self, directory: DirectoryClient) -> None:
        self._directory = directory
        self._cache: dict[str, str] = {}

    def __call__(self, dn: str) -> str:
        if not dn:
            return ""
        key = dnlib.normalize(dn) if "=" in dn else dn
        found = self._cache.get(key)
        if found is None:
            found = self._cache[key] = self._resolve(dn)
        return found

    def _resolve(self, dn: str) -> str:
        if "=" not in dn:
            return dn
        fallback = dnlib.rdn(dn).partition("=")[2].replace("\\", "") or dn
        try:
            entry = self._directory.get(dn, list(LABEL_ATTRS))
        except DirectoryError:
            return fallback
        if entry is None:
            return fallback
        for attr in LABEL_ATTRS:
            text = entry.text(attr)
            if text:
                return text
        return fallback


def _login_note(event: Event) -> str:
    for line in event.attributes:
        if line.startswith("login: "):
            return line[len("login: ") :]
    return ""


def event_json(event: Event, labels: Labels) -> dict[str, JSON]:
    actor_label = labels(event.author) if event.author else _login_note(event)
    return {
        "dn": event.dn,
        "time": event.time.isoformat(),
        "action": event.action,
        "actor": {"dn": event.author, "label": actor_label},
        "object": {
            "dn": event.object,
            "type": event.object_type,
            "label": labels(event.object),
        },
        "ip": event.ip,
        "attributes": list(event.attributes),
        "result": event.result,
    }


@dataclass(slots=True)
class AuditQuery:
    start: datetime | None
    end: datetime | None
    actor: str
    object: str
    actions: list[str]
    type: str
    result: str
    q: str


def _ldap_filter(query: AuditQuery) -> str:
    parts = [f"(objectClass={EVENT_CLASS})"]
    if query.actions:
        parts.append(
            "(|"
            + "".join(f"(hrcAuditAction={escape_filter_value(a)})" for a in query.actions)
            + ")"
        )
    if query.type:
        parts.append(f"(hrcAuditObjectType={escape_filter_value(query.type)})")
    if query.result:
        parts.append(f"(hrcAuditResult={escape_filter_value(query.result)})")
    return "(&" + "".join(parts) + ")"


def _matches(event: Event, query: AuditQuery) -> bool:
    if query.start and event.time < query.start:
        return False
    if query.end and event.time > query.end:
        return False
    if query.actor and dnlib.normalize(event.author) != dnlib.normalize(query.actor):
        return False
    if query.object and not (
        dnlib.is_descendant(event.object, query.object)
        if "=" in event.object
        else event.object == query.object
    ):
        return False
    if query.q:
        needle = query.q.lower()
        haystack = " ".join(
            [
                event.action,
                event.author,
                event.ip,
                event.object_type,
                event.object,
                *event.attributes,
            ]
        ).lower()
        if needle not in haystack:
            return False
    return True


def find_events(directory: DirectoryClient, query: AuditQuery) -> list[Event]:
    """Matching events, newest first."""
    try:
        entries = directory.search(
            audit_container(directory), _ldap_filter(query), Scope.ONE, list(_EVENT_ATTRS)
        )
        parsed = [e for entry in entries if (e := parse_event(entry)) is not None]
    except NoSuchObjectError:
        return []
    found = [e for e in parsed if _matches(e, query)]
    found.sort(key=lambda e: e.sort_key, reverse=True)
    return found


def _safe(cell: str) -> str:
    """Neutralise spreadsheet formulas."""
    return "'" + cell if cell[:1] in ("=", "+", "-", "@", "\t", "\r") else cell


def csv_export(events: Iterable[Event], labels: Labels) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "time",
            "action",
            "result",
            "actor_dn",
            "actor",
            "object_type",
            "object_dn",
            "object",
            "ip",
            "attributes",
        ]
    )
    for event in events:
        item = event_json(event, labels)
        actor: Any = item["actor"]
        obj: Any = item["object"]
        row = [
            event.time.isoformat(),
            event.action,
            event.result,
            actor["dn"],
            actor["label"],
            event.object_type,
            obj["dn"],
            obj["label"],
            event.ip,
            "; ".join(event.attributes),
        ]
        writer.writerow([_safe(str(c)) for c in row])
    return out.getvalue()


def build_router(ctx: PluginRouterContext) -> APIRouter:
    """Router factory (``Plugin.api_routers``)."""
    del ctx
    router = APIRouter(prefix="/audit", tags=["audit"])

    @router.get("")
    def list_audit(  # pyright: ignore[reportUnusedFunction]
        user: CurrentUserDep,
        domain: DomainDep,
        from_: Annotated[str | None, Query(alias="from")] = None,
        to: str | None = None,
        actor: str = "",
        object: Annotated[str, Query(description="DN; matches it and everything below")] = "",
        action: Annotated[list[str] | None, Query()] = None,
        type: str = "",
        result: str = "",
        q: str = "",
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        format: Annotated[str, Query(pattern="^(json|csv)$")] = "json",
    ) -> Any:
        """Events newest first. Needs the read right on the audit event category."""
        info = domain.registry.get("audit_event")
        base = user.directory.base_dn
        if not domain.evaluator(user).permissions(base, info.acl_object(info.main_tab)).read:
            raise forbidden("You cannot read the audit log")
        query = AuditQuery(
            start=parse_moment(from_, "from"),
            end=parse_moment(to, "to", end=True),
            actor=actor.strip(),
            object=object.strip(),
            actions=[a for a in (action or []) if a],
            type=type.strip(),
            result=result.strip(),
            q=q.strip(),
        )
        events = find_events(user.directory, query)
        labels = Labels(user.directory)
        if format == "csv":
            body = csv_export(events[:MAX_EXPORT], labels)
            return Response(
                body,
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
            )
        after = decode_cursor(cursor)
        if after is not None:
            events = [e for e in events if e.sort_key < after]
        page = events[:limit]
        more = len(events) > limit
        return {
            "items": [event_json(e, labels) for e in page],
            "next_cursor": encode_cursor(page[-1]) if more and page else None,
        }

    return router
