"""``/api/v2/access``: grant end dates (requests and reviews are added by their modules)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from heracles.api.deps import CurrentUserDep
from heracles.api.domain import DomainDep
from heracles.api.errors import forbidden, not_found, validation
from heracles.core.access_config import access_config
from heracles.core.audit import AuditSink
from heracles.ldap import dn as dnlib
from heracles.objects.registry import PluginRouterContext
from heracles_plugins.access import grants as g
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

    return router
