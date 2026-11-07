"""FastAPI router for autofs5 tree endpoint."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from heracles.api.deps import CurrentUserDep
from heracles.api.domain import DomainDep
from heracles.api.errors import not_found
from heracles.objects import UnknownTypeError
from heracles.objects.registry import PluginRouterContext
from heracles_plugins.autofs5.tree import build_autofs_tree


def build_router(_ctx: PluginRouterContext) -> APIRouter:
    """Router factory for Plugin.api_routers."""
    router = APIRouter(prefix="/autofs", tags=["autofs"])

    @router.get("/tree")
    def get_autofs_tree(
        user: CurrentUserDep,
        domain: DomainDep,
        dn: Annotated[str, Query(description="Map or container DN")],
    ) -> list[dict[str, Any]]:
        """Nested automount maps and entries tree rooted at ``dn``."""
        evaluator = domain.evaluator(user)

        def can_read(section_dn: str, type_name: str) -> bool:
            try:
                info = domain.registry.get(type_name)
            except UnknownTypeError:
                return False
            return evaluator.permissions(section_dn, info.acl_object(info.main_tab)).read

        tree = build_autofs_tree(user.directory, dn, can_read)
        if not tree:
            raise not_found(f"Autofs section not found: {dn}")
        return tree

    return router
