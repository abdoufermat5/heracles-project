"""``/api/v2/access/reviews``: access review campaigns (see :mod:`.reviews`).

Campaign managers (administrators, and whoever may write ACL assignments at the base) create,
follow, close and export campaigns; reviewers see and decide their own items.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from heracles.api.deps import CurrentUser, CurrentUserDep, StateDep
from heracles.api.domain import Domain, DomainDep
from heracles.api.errors import ApiError, forbidden, not_found, validation
from heracles.api.state import AppState
from heracles.api.stepup import require_recent_auth
from heracles.api.v2.admin import ASSIGNMENT_KEY, rights_of
from heracles.core.access_config import access_config
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Entry
from heracles.objects import ObjectService
from heracles.objects.policy import AllowAll
from heracles.objects.registry import TypeRegistry
from heracles.storage import Database
from heracles.storage.database import MEMORY
from heracles_plugins.access import approvals as ap
from heracles_plugins.access import reviews as rv
from heracles_plugins.access.rights import holder_types

log = structlog.get_logger(__name__)


class CampaignBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    holders: list[str] = Field(default_factory=lambda: [])
    #: Department (or any base): every group and role below it.
    base: str = ""
    reviewer: str = "owner"
    #: ISO date: the last day reviewers may decide (UTC).
    deadline: str
    default: str = rv.KEEP


class DecisionBody(BaseModel):
    decision: str
    comment: str = ""


def review_store(request: Request, state: AppState) -> rv.ReviewStore:
    app_state = request.app.state
    store: rv.ReviewStore | None = getattr(app_state, "access_reviews", None)
    if store is None:
        database = state.database or getattr(app_state, "access_memory_db", None)
        if database is None:
            database = Database(MEMORY)
            app_state.access_memory_db = database
        store = rv.ReviewStore(database, clock=state.clock)
        app_state.access_reviews = store
    return store


def can_manage(user: CurrentUser, domain: Domain) -> bool:
    return domain.is_admin(user.dn) or rights_of(user, domain, ASSIGNMENT_KEY).write


def _deadline(text: str) -> float:
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise validation("Invalid date", {"deadline": "Use an ISO date"}) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if len(text) == 10:
        moment = moment.replace(hour=23, minute=59, second=59)
    return moment.timestamp()


def _same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and dnlib.normalize(a) == dnlib.normalize(b)


def _counts(items: list[rv.Item], campaign: rv.Campaign) -> dict[str, int]:
    decided = Counter(i.decision for i in items if i.decision)
    return {
        "items": len(items),
        "decided": sum(decided.values()),
        "revoke": decided.get(rv.REVOKE, 0),
        "keep": decided.get(rv.KEEP, 0),
        "failed": sum(1 for i in items if i.outcome == rv.FAILED),
    }


def add_review_routes(router: APIRouter) -> None:
    @router.post("/reviews", status_code=201)
    def create_campaign(  # pyright: ignore[reportUnusedFunction]
        body: CampaignBody,
        request: Request,
        user: CurrentUserDep,
        domain: DomainDep,
        state: StateDep,
    ) -> dict[str, Any]:
        if not can_manage(user, domain):
            raise forbidden("You cannot run access reviews")
        if body.reviewer not in rv.REVIEWER_RULES:
            raise validation("Invalid reviewer", {"reviewer": "owner or manager"})
        if body.default not in (rv.KEEP, rv.REVOKE):
            raise validation("Invalid default", {"default": "keep or revoke"})
        store = review_store(request, state)
        now = store.clock()
        deadline = _deadline(body.deadline)
        if deadline <= now:
            raise validation("Invalid date", {"deadline": "The deadline must be in the future"})
        holders = rv.select_holders(user.directory, body.holders, body.base.strip())
        campaign = rv.new_campaign(
            directory_id=user.directory_id,
            name=body.name.strip(),
            creator=user.dn,
            deadline=deadline,
            rule=body.reviewer,
            default=body.default,
            selector={"holders": sorted(body.holders), "base": body.base.strip()},
            now=now,
        )
        items = rv.build_items(user.directory, campaign.id, holders, body.reviewer, user.dn)
        if not items:
            raise validation("Nothing to review", {"holders": "The selection holds no membership"})
        store.create(campaign, items)
        domain.audit.record_by(
            user,
            "access_review",
            object_type="access_review",
            object_dn=user.directory.base_dn,
            attributes=[
                f"campaign: {campaign.id}",
                f"name: {campaign.name}",
                "status: open",
                f"items: {len(items)}",
            ],
        )
        per_reviewer = Counter(i.reviewer_dn for i in items if i.reviewer_dn)
        cfg = access_config()
        url = state.settings.recovery.base_url.rstrip("/") + "/access/reviews"
        for reviewer, count in per_reviewer.items():
            ap.send_mail(
                state.mailer,
                user.directory,
                cfg,
                "review_assigned",
                ap.mail_addresses(user.directory, [reviewer]),
                {
                    "campaign": campaign.name,
                    "count": str(count),
                    "deadline": datetime.fromtimestamp(deadline, UTC).date().isoformat(),
                    "url": url,
                },
            )
        return {"campaign": campaign.to_json() | {"counts": _counts(items, campaign)}}

    @router.get("/reviews")
    def list_campaigns(  # pyright: ignore[reportUnusedFunction]
        request: Request, user: CurrentUserDep, domain: DomainDep, state: StateDep
    ) -> dict[str, Any]:
        store = review_store(request, state)
        manager = can_manage(user, domain)
        mine = store.items_for_reviewer(user.dn)
        assigned = Counter(i.campaign_id for i in mine if not i.decision)
        out: list[dict[str, Any]] = []
        for campaign in store.campaigns(user.directory_id):
            if not manager and campaign.id not in {i.campaign_id for i in mine}:
                continue
            row = campaign.to_json() | {"to_review": assigned.get(campaign.id, 0)}
            if manager:
                row["counts"] = _counts(store.items(campaign.id), campaign)
            out.append(row)
        return {"items": out, "can_manage": manager}

    @router.get("/reviews/{campaign_id}")
    def get_campaign(  # pyright: ignore[reportUnusedFunction]
        campaign_id: str, request: Request, user: CurrentUserDep, domain: DomainDep, state: StateDep
    ) -> dict[str, Any]:
        store = review_store(request, state)
        campaign = _campaign_or_404(store, user, campaign_id)
        manager = can_manage(user, domain)
        items = store.items(campaign.id)
        visible = items if manager else [i for i in items if _same(i.reviewer_dn, user.dn)]
        if not manager and not visible:
            raise not_found("Campaign not found")
        return {
            "campaign": campaign.to_json() | {"counts": _counts(items, campaign)},
            "items": [
                i.to_json() | {"can_decide": _may_decide(user, manager, campaign, i, store.clock())}
                for i in visible
            ],
            "can_manage": manager,
        }

    @router.post("/reviews/{campaign_id}/items/{item_id}")
    def decide_item(  # pyright: ignore[reportUnusedFunction]
        campaign_id: str,
        item_id: str,
        body: DecisionBody,
        request: Request,
        user: CurrentUserDep,
        domain: DomainDep,
        state: StateDep,
    ) -> dict[str, Any]:
        if body.decision not in (rv.KEEP, rv.REVOKE):
            raise validation("Invalid decision", {"decision": "keep or revoke"})
        store = review_store(request, state)
        campaign = _campaign_or_404(store, user, campaign_id)
        item = next((i for i in store.items(campaign.id) if i.item_id == item_id), None)
        if item is None:
            raise not_found("Item not found")
        if not _may_decide(user, can_manage(user, domain), campaign, item, store.clock()):
            raise forbidden("You cannot decide this item")
        done = store.decide(item, body.decision, body.comment.strip()[:1000], user.dn)
        return {"item": done.to_json()}

    @router.post("/reviews/{campaign_id}/close")
    def close_campaign(  # pyright: ignore[reportUnusedFunction]
        campaign_id: str, request: Request, user: CurrentUserDep, domain: DomainDep, state: StateDep
    ) -> dict[str, Any]:
        """Apply the revocations and close; run again to resume a close that stopped."""
        if not can_manage(user, domain):
            raise forbidden("You cannot close access reviews")
        store = review_store(request, state)
        campaign = _campaign_or_404(store, user, campaign_id)
        service = ObjectService(
            user.directory, domain.registry, policy=AllowAll(), events=domain.events(user)
        )
        try:
            result = rv.close_campaign(
                store, campaign, user.directory, remover(domain.registry, service), user.dn
            )
        except rv.CloseConflictError as exc:
            raise ApiError(409, "conflict", str(exc).capitalize()) from None
        counts = _counts(result.items, result.campaign)
        if result.failed:
            return {
                "campaign": result.campaign.to_json() | {"counts": counts},
                "failed": [i.to_json() for i in result.failed],
            }
        domain.audit.record_by(
            user,
            "access_review",
            object_type="access_review",
            object_dn=user.directory.base_dn,
            attributes=rv.close_audit_lines(result),
        )
        return {"campaign": result.campaign.to_json() | {"counts": counts}, "failed": []}

    @router.get("/reviews/{campaign_id}/report")
    def campaign_report(  # pyright: ignore[reportUnusedFunction]
        campaign_id: str,
        request: Request,
        user: CurrentUserDep,
        domain: DomainDep,
        state: StateDep,
        format: Annotated[str, Query(pattern="^(json|csv)$")] = "json",
    ) -> Response:
        """The review report for auditors (step-up); its hash is in the close audit event."""
        if not can_manage(user, domain):
            raise forbidden("You cannot export access reviews")
        store = review_store(request, state)
        campaign = _campaign_or_404(store, user, campaign_id)
        require_recent_auth(state, user.session)
        doc = rv.report(campaign, store.items(campaign.id))
        digest = rv.report_hash(doc)
        # a closed campaign's report must hash to the value recorded at close (and in the
        # audit log): a row changed in the database afterwards shows up here
        recorded = campaign.report_hash
        matches = (recorded == digest) if recorded else None
        if format == "csv":
            body = rv.report_csv(doc)
            media = "text/csv; charset=utf-8"
        else:
            body = json.dumps(
                {"sha256": digest, "recorded_sha256": recorded, "matches": matches, "report": doc},
                ensure_ascii=False,
                indent=1,
            )
            media = "application/json"
        return Response(
            body,
            media_type=media,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="access-review-{campaign.id}.{format}"'
                ),
                "X-Report-SHA256": digest,
                "X-Report-Matches": "" if matches is None else str(matches).lower(),
            },
        )


def remover(
    registry: TypeRegistry, service: ObjectService
) -> Callable[[Entry, str, list[str]], None]:
    """Remove a membership through the object service of the entry's type."""

    def remove(entry: Entry, kind: str, kept: list[str]) -> None:
        found = holder_types(registry, entry, kind)
        if not found:
            raise RuntimeError(f"no type edits {kind} on {entry.dn}")
        info, tab = found[0]
        service.update(info.name, entry.dn, {tab: {"values": {kind: kept}}})

    return remove


def _campaign_or_404(store: rv.ReviewStore, user: CurrentUser, campaign_id: str) -> rv.Campaign:
    campaign = store.get(campaign_id)
    if campaign is None or campaign.directory_id != user.directory_id:
        raise not_found("Campaign not found")
    return campaign


def _may_decide(
    user: CurrentUser, manager: bool, campaign: rv.Campaign, item: rv.Item, now: float
) -> bool:
    if campaign.status != rv.OPEN or now > campaign.deadline:
        return False
    if _same(item.member_dn, user.dn):
        return False  # nobody reviews their own access
    if item.reviewer_dn:
        return _same(item.reviewer_dn, user.dn) or manager
    return manager


__all__ = ["add_review_routes", "can_manage", "review_store"]
