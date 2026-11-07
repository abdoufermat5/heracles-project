"""FastAPI router for DHCP endpoints (mounted under ``/api/v2`` with session and CSRF)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from heracles.api.deps import CurrentUserDep
from heracles.api.domain import DomainDep
from heracles.api.errors import not_found
from heracles.objects import UnknownTypeError
from heracles.objects.registry import PluginRouterContext
from heracles_plugins.dhcp.tree import build_dhcp_tree


def build_router(_ctx: PluginRouterContext) -> APIRouter:
    """Router factory (``Plugin.api_routers``)."""
    router = APIRouter(prefix="/dhcp", tags=["dhcp"])

    @router.get("/tree")
    def get_dhcp_tree(
        user: CurrentUserDep,
        domain: DomainDep,
        dn: Annotated[str, Query(description="Configuration or section DN")],
    ) -> list[dict[str, Any]]:
        """Nested sections tree rooted at ``dn`` (readable sections only)."""
        evaluator = domain.evaluator(user)

        def can_read(section_dn: str, type_name: str) -> bool:
            try:
                info = domain.registry.get(type_name)
            except UnknownTypeError:
                return False
            return evaluator.permissions(section_dn, info.acl_object(info.main_tab)).read

        tree = build_dhcp_tree(user.directory, dn, can_read)
        if not tree:
            # same answer for a missing and an unreadable section
            raise not_found(f"DHCP section not found: {dn}")
        return tree

    return router
