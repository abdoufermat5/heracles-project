"""``/api/v2/access``: grant end dates (requests and reviews are added by their modules)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from heracles.api.deps import CurrentUser, CurrentUserDep, StateDep
from heracles.api.domain import Domain, DomainDep
from heracles.api.errors import ApiError, forbidden, not_found, validation
from heracles.api.state import AppState
from heracles.core.access_config import AccessConfig, access_config
from heracles.core.audit import AuditSink
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Entry
from heracles.objects.registry import PluginRouterContext
from heracles.storage import Database
from heracles.storage.database import MEMORY
from heracles_plugins.access import approvals as ap
from heracles_plugins.access import grants as g
from heracles_plugins.access.requests import (
    APPROVED,
    CANCELLED,
    FAILED,
    PENDING,
    REJECTED,
    AccessRequest,
    AccessRequestStore,
)
from heracles_plugins.access.rights import can_change_grants, can_read_grants


class EndDateBody(BaseModel):
    holder: str
    kind: str
    member: str
    #: ISO date or date-time (UTC without offset; a bare date ends that day); null: permanent.
    until: str | None = None
    acl_scope: str = ""
    acl_role: str = ""


def parse_until(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise validation("Invalid date", {"until": "Use an ISO date or date-time"}) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if len(text) == 10:
        moment = moment.replace(hour=23, minute=59, second=59)
    return moment.astimezone(UTC)


def check_until(until: datetime | None, *, now: datetime | None = None) -> None:
    """An end date lies in the future and within ``access.max_days``."""
    now = now or datetime.now(UTC)
    limit = access_config().max_days
    if until is None:
        if limit:
            raise validation(
                "End date required", {"until": f"Give an end date (at most {limit} days)"}
            )
        return
    if until <= now:
        raise validation("Invalid date", {"until": "The end date must be in the future"})
    if limit and until > now + timedelta(days=limit, hours=24):
        raise validation("Invalid date", {"until": f"At most {limit} days from now"})


log = structlog.get_logger(__name__)


def build_router(ctx: PluginRouterContext) -> APIRouter:
    del ctx
    router = APIRouter(prefix="/access", tags=["access"])

    @router.get("/grants")
    def list_end_dates(  # pyright: ignore[reportUnusedFunction]
        user: CurrentUserDep, domain: DomainDep, holder: str = "", member: str = ""
    ) -> dict[str, Any]:
        """End dates on one entry (``holder``) or of one person (``member``)."""
        directory = user.directory
        if holder:
            entry = directory.get(holder)
            if entry is None:
                raise not_found("Entry not found")
            items = [
                x
                for x in g.grants_of(entry)
                if g.holds(entry, x) and can_read_grants(user, domain, entry, x.kind)
            ]
        elif member:
            wanted = dnlib.normalize(member)
            items = [
                x
                for entry in g.find_dated(directory)
                for x in g.grants_of(entry)
                if dnlib.normalize(x.member) == wanted
                and g.holds(entry, x)
                and can_read_grants(user, domain, entry, x.kind)
            ]
        else:
            raise validation("Missing filter", {"holder": "Give holder or member"})
        return {"items": [x.to_json() for x in items]}

    @router.get("/status")
    def status() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        """Cheap probe: the access plugin is on (404 otherwise)."""
        return {"enabled": True}

    @router.get("/me")
    def my_end_dates(user: CurrentUserDep) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """End dates of the signed-in person's own access."""
        return {"items": [x.to_json() for x in g.dated_memberships(user.directory, user.dn)]}

    @router.put("/grants")
    def put_end_date(  # pyright: ignore[reportUnusedFunction]
        body: EndDateBody, user: CurrentUserDep, domain: DomainDep
    ) -> dict[str, Any]:
        """Set or clear the end date of one grant (the rights of its editors)."""
        entry = user.directory.get(body.holder)
        if entry is None:
            raise not_found("Entry not found")
        kind = body.kind
        if not can_change_grants(user, domain, entry, kind):
            raise forbidden("You cannot change this access")
        until = parse_until(body.until)
        if until is not None:
            check_until(until)
        try:
            grant = g.set_end_date(
                user.directory,
                entry.dn,
                kind,
                body.member,
                until,
                acl_scope=body.acl_scope,
                acl_role=body.acl_role,
            )
        except g.GrantError as exc:
            raise validation("Invalid grant", {"member": str(exc)}) from None
        sink: AuditSink = domain.audit
        sink.record_by(
            user,
            "modify",
            object_type="grant",
            object_dn=entry.dn,
            attributes=[
                f"member: {body.member}",
                f"kind: {kind}",
                f"until: {until.isoformat() if until else 'permanent'}",
            ],
        )
        return {"grant": grant.to_json() if grant else None}

    # -- requests --------------------------------------------------------------------

    @router.get("/requestable")
    def list_requestable(  # pyright: ignore[reportUnusedFunction]
        user: CurrentUserDep,
    ) -> dict[str, Any]:
        """Groups and roles the signed-in person may ask to join."""
        cfg = access_config()
        items: list[dict[str, Any]] = []
        for entry in ap.requestable(user.directory, cfg):
            kind = ap.kind_of(entry)
            if kind is None:
                continue
            ends = None
            if ap.holds_membership(entry, user.dn):
                ends = ap.current_end_date(_dated(user, entry), kind, user.dn)
                if ends is None:
                    continue  # held for good: nothing to ask for
            items.append(
                {
                    "dn": entry.dn,
                    "kind": kind,
                    "label": ap.label_of(entry),
                    "description": entry.text("description") or "",
                    # held until this date: a request extends it
                    "renews": ends.isoformat() if ends else None,
                }
            )
        items.sort(key=lambda i: str(i["label"]).lower())
        return {"items": items, "max_days": cfg.max_days}

    @router.post("/requests", status_code=201)
    def create_request(  # pyright: ignore[reportUnusedFunction]
        body: RequestBody,
        request: Request,
        user: CurrentUserDep,
        domain: DomainDep,
        state: StateDep,
    ) -> dict[str, Any]:
        """Ask to join a requestable group or role (for oneself)."""
        cfg = access_config()
        target = ap.requestable_entry(user.directory, cfg, body.target)
        if target is None:
            raise validation("Not requestable", {"target": "This access cannot be requested"})
        kind = ap.kind_of(target)
        assert kind is not None
        if ap.holds_membership(target, user.dn) and (
            ap.current_end_date(_dated(user, target), kind, user.dn) is None
        ):
            raise validation("Already granted", {"target": "You already have this access"})
        reason = body.reason.strip()
        if not reason:
            raise validation("Reason required", {"reason": "Say why you need this access"})
        until = parse_until(body.until)
        check_until(until)
        store = _store(request, state)
        if store.pending_for(user.directory_id, user.dn, target.dn) is not None:
            raise validation("Already requested", {"target": "A request is already waiting"})
        created = store.add(
            directory_id=user.directory_id,
            requester_dn=user.dn,
            member_dn=user.dn,
            target_dn=target.dn,
            target_kind=kind,
            target_label=ap.label_of(target),
            reason=reason[:1000],
            until=until.isoformat() if until else None,
        )
        domain.audit.record_by(
            user,
            "access_request",
            object_type="access_request",
            object_dn=target.dn,
            attributes=[f"request: {created.id}", "status: pending", f"reason: {created.reason}"],
        )
        approvers = sorted(ap.approvers_of(user.directory, cfg, target))
        ap.send_mail(
            state.mailer,
            user.directory,
            cfg,
            "request_submitted",
            ap.mail_addresses(user.directory, approvers),
            {
                "requester": user.dn,
                "member": user.dn,
                "target": created.target_label,
                "reason": created.reason,
                "until": created.until or "none",
                "url": state.settings.recovery.base_url.rstrip("/") + "/access/requests",
            },
        )
        return {"request": created.to_json()}

    @router.get("/requests")
    def list_requests(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        user: CurrentUserDep,
        domain: DomainDep,
        state: StateDep,
        view: str = "mine",
        status: str = "",
    ) -> dict[str, Any]:
        """``view=mine`` (default), ``to_approve`` (pending ones the caller may decide) or
        ``all`` (administrators and approvers: every request they may decide)."""
        store = _store(request, state)
        cfg = access_config()
        if view == "mine":
            items = store.list(user.directory_id, member_dn=user.dn, status=status or None)
            return {"items": [r.to_json() for r in items]}
        if view not in ("to_approve", "all"):
            raise validation("Invalid view", {"view": "mine, to_approve or all"})
        wanted = PENDING if view == "to_approve" else (status or None)
        out = [
            r.to_json() | {"can_decide": r.status == PENDING}
            for r in store.list(user.directory_id, status=wanted)
            if _may_decide(user, domain, cfg, r)
        ]
        return {"items": out}

    @router.post("/requests/{request_id}/approve")
    def approve(  # pyright: ignore[reportUnusedFunction]
        request_id: str,
        body: DecisionBody,
        request: Request,
        user: CurrentUserDep,
        domain: DomainDep,
        state: StateDep,
    ) -> dict[str, Any]:
        return {
            "request": _decide(request, user, domain, state, request_id, APPROVED, body.comment)
        }

    @router.post("/requests/{request_id}/reject")
    def reject(  # pyright: ignore[reportUnusedFunction]
        request_id: str,
        body: DecisionBody,
        request: Request,
        user: CurrentUserDep,
        domain: DomainDep,
        state: StateDep,
    ) -> dict[str, Any]:
        return {
            "request": _decide(request, user, domain, state, request_id, REJECTED, body.comment)
        }

    @router.post("/requests/{request_id}/cancel")
    def cancel(  # pyright: ignore[reportUnusedFunction]
        request_id: str, request: Request, user: CurrentUserDep, domain: DomainDep, state: StateDep
    ) -> dict[str, Any]:
        store = _store(request, state)
        found = store.get(request_id)
        if (
            found is None
            or found.directory_id != user.directory_id
            or dnlib.normalize(found.requester_dn) != dnlib.normalize(user.dn)
        ):
            raise not_found("Request not found")
        done = store.decide(found, CANCELLED, by=user.dn)
        if done is None:
            raise ApiError(409, "conflict", "The request was already decided")
        domain.audit.record_by(
            user,
            "access_request",
            object_type="access_request",
            object_dn=found.target_dn,
            attributes=[f"request: {found.id}", "status: cancelled"],
        )
        return {"request": done.to_json()}

    @router.get("/queue")
    def work_queue(  # pyright: ignore[reportUnusedFunction]
        request: Request, user: CurrentUserDep, domain: DomainDep, state: StateDep
    ) -> dict[str, int]:
        """How many items wait for the caller (the dashboard work queue)."""
        store = _store(request, state)
        cfg = access_config()
        approvals = sum(
            1
            for r in store.list(user.directory_id, status=PENDING)
            if _may_decide(user, domain, cfg, r)
        )
        return {"approvals": approvals}

    return router


def _dated(user: CurrentUser, entry: Entry) -> Entry:
    """``entry`` with its end dates (the requestable search does not read them)."""
    full = user.directory.get(entry.dn, ["objectClass", g.GRANT_ATTR, "member", "roleOccupant"])
    return full or entry


class RequestBody(BaseModel):
    target: str
    reason: str
    until: str | None = None


class DecisionBody(BaseModel):
    comment: str = ""


def _store(request: Request, state: AppState) -> AccessRequestStore:
    app_state = request.app.state
    store: AccessRequestStore | None = getattr(app_state, "access_requests", None)
    if store is None:
        database = state.database or Database(MEMORY)  # demo and tests: per process
        store = AccessRequestStore(database, clock=state.clock)
        app_state.access_requests = store
    return store


def _may_decide(user: CurrentUser, domain: Domain, cfg: AccessConfig, r: AccessRequest) -> bool:
    target = user.directory.get(r.target_dn, ["objectClass", "owner"])
    if target is None:
        return domain.is_admin(user.dn)
    return ap.can_approve(user, domain, cfg, target, r)


def _decide(
    request: Request,
    user: CurrentUser,
    domain: Domain,
    state: AppState,
    request_id: str,
    status: str,
    comment: str,
) -> dict[str, Any]:
    store = _store(request, state)
    cfg = access_config()
    found = store.get(request_id)
    if found is None or found.directory_id != user.directory_id:
        raise not_found("Request not found")
    if not _may_decide(user, domain, cfg, found):
        raise forbidden("You cannot decide this request")
    comment = comment.strip()[:1000]
    if (
        status == APPROVED
        and found.until
        and datetime.fromisoformat(found.until) <= datetime.now(UTC)
    ):
        raise validation(
            "End date passed", {"comment": "The requested end date has passed: reject it"}
        )
    if status == REJECTED and not comment:
        raise validation("Comment required", {"comment": "Say why the request is rejected"})
    done = store.decide(found, status, by=user.dn, comment=comment)
    if done is None:
        raise ApiError(409, "conflict", "The request was already decided")
    if status == APPROVED:
        try:
            ap.apply(user, domain, done, datetime.now(UTC))
        except Exception as exc:  # whatever went wrong, the request must not stay "approved"
            log.warning("access_apply_failed", request=done.id, error=str(exc))
            done = store.fail(done, str(exc)[:500] or type(exc).__name__)
    domain.audit.record_by(
        user,
        "access_request",
        object_type="access_request",
        object_dn=done.target_dn,
        attributes=[
            f"request: {done.id}",
            f"status: {done.status}",
            f"member: {done.member_dn}",
            *([f"comment: {done.comment}"] if done.comment else []),
            *([f"error: {done.error}"] if done.error else []),
        ],
        result="failure" if done.status == FAILED else "success",
    )
    ap.send_mail(
        state.mailer,
        user.directory,
        cfg,
        "request_decided",
        ap.mail_addresses(user.directory, [done.requester_dn]),
        {
            "target": done.target_label,
            "status": done.status,
            "decided_by": user.dn,
            "comment": done.comment,
        },
    )
    return done.to_json()
