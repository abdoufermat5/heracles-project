"""``POST /api/v2/invitations/send``: e-mail personal form links (session and CSRF)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from heracles.api.deps import CurrentUserDep, get_state
from heracles.api.domain import DomainDep
from heracles.api.errors import forbidden, not_found, validation
from heracles.api.hosts import request_base
from heracles.objects.registry import PluginRouterContext
from heracles_plugins.invitations.sending import InvitationError, send_invitation

ACL_OBJECT = "invitation/invitation"


class SendRequest(BaseModel):
    invitation: str = Field(min_length=1, max_length=1024, description="DN of the invitation")
    emails: Annotated[list[str], Field(min_length=1, max_length=500)]


def build_router(ctx: PluginRouterContext) -> APIRouter:
    """Router factory (``Plugin.api_routers``)."""
    router = APIRouter(prefix="/invitations", tags=["invitations"])

    @router.post("/send")
    def send(  # pyright: ignore[reportUnusedFunction]
        body: SendRequest, request: Request, user: CurrentUserDep, domain: DomainDep
    ) -> dict[str, Any]:
        """Send the invitation to the given addresses (needs write access to it)."""
        settings: Any = ctx.settings
        if not domain.evaluator(user).permissions(body.invitation, ACL_OBJECT).write:
            raise forbidden("You cannot send this invitation")
        if user.directory.get(body.invitation, ["objectClass"]) is None:
            raise not_found("Invitation not found")
        state = get_state(request)
        base_url = str(getattr(settings, "public_base_url", "") or "") or request_base(
            request, state.settings.allowed_hosts, setting="the invitations public_base_url"
        )
        try:
            report = send_invitation(
                user.directory,
                state.mailer,
                body.invitation,
                body.emails,
                base_url=base_url,
                now=datetime.now(UTC),
                author_dn=user.dn,
                sender=getattr(settings, "from_email", "") or None,
                valid_days=int(getattr(settings, "token_valid_days", 7)),
            )
        except InvitationError as exc:
            raise validation(str(exc)) from exc
        return {"sent": report.sent, "failed": report.failed}

    return router
