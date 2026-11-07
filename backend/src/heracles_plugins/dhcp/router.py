"""FastAPI router for DHCP endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from heracles.api.deps import CurrentUserDep
from heracles.api.errors import not_found
from heracles_plugins.dhcp.tree import build_dhcp_tree

router = APIRouter(prefix="/dhcp", tags=["dhcp"])


@router.get("/tree")
def get_dhcp_tree(
    user: CurrentUserDep,
    dn: Annotated[str, Query(description="Configuration or section DN")],
) -> list[dict[str, Any]]:
    """Return the nested sections tree rooted at `dn` with allowed_children."""
    tree = build_dhcp_tree(user.directory, dn)
    if not tree:
        raise not_found(f"DHCP section not found: {dn}")
    return tree
