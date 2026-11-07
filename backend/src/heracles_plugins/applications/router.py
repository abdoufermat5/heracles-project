"""``GET /api/v2/me/applications``: applications allowed to the connected user."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from heracles.api.deps import CurrentUserDep
from heracles.attributes import ImageAttr
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, Entry, NoSuchObjectError
from heracles.objects.registry import PluginRouterContext

DESKTOP_CLASS = "fdDesktopApplication"
WEB_CLASS = "fdWebApplication"
RIGHTS_CLASS = "fdApplicationRights"
ALLOWED_ATTR = "fdApplicationAllowed"
FLAGS_ATTR = "fdApplicationFlags"

#: Flag name → letter stored in the flags attribute.
FLAG_LETTERS: tuple[tuple[str, str], ...] = (
    ("flag_group", "G"),
    ("flag_overwrite", "O"),
    ("flag_desktop", "D"),
    ("flag_menu", "M"),
    ("flag_launchbar", "L"),
)

_IMAGE = ImageAttr("image", "Image")


def decode_flags(text: str | None) -> dict[str, bool]:
    """Stored flags (``"[GDM]"``, brackets optional) to ``{"flag_group": True, ...}``."""
    letters = set((text or "").strip().strip("[]").upper())
    return {name: letter in letters for name, letter in FLAG_LETTERS}


def encode_flags(flags: dict[str, Any], previous: str | None = None) -> str:
    """``{"flag_group": True, ...}`` to the stored form ``[GDM]``.

    Letters of ``previous`` that are not known flags are preserved.
    """
    known = {letter for _name, letter in FLAG_LETTERS}
    kept = [c for c in (previous or "").strip().strip("[]") if c.upper() not in known]
    letters = "".join(letter for name, letter in FLAG_LETTERS if flags.get(name))
    return f"[{letters}{''.join(kept)}]"


def application_json(entry: Entry) -> dict[str, Any] | None:
    """Portal description of an application entry (``None`` if it is not one)."""
    is_web = entry.has_object_class(WEB_CLASS)
    if not is_web and not entry.has_object_class(DESKTOP_CLASS):
        return None
    cn = entry.text("cn") or ""
    out: dict[str, Any] = {
        "dn": entry.dn,
        "type": "web_application" if is_web else "application",
        "name": cn,
        "title": entry.text("fdApplicationTitle") or cn,
        "description": entry.text("description") or "",
        "image": _IMAGE.to_json(entry.first("fdApplicationImage")),
        "image_location": entry.text("fdApplicationImageLocation"),
    }
    if is_web:
        out["url"] = entry.text("labeledURI")
    else:
        out["execute_path"] = entry.text("fdApplicationExecutePath")
        out["flags"] = decode_flags(entry.text(FLAGS_ATTR))
    return out


def allowed_applications(directory: DirectoryClient, user_dn: str) -> list[dict[str, Any]]:
    """Applications granted to ``user_dn`` through the roles it occupies."""
    flt = f"(&(objectClass={RIGHTS_CLASS})(roleOccupant=*))"
    wanted = dnlib.normalize(user_dn)
    granted: dict[str, str] = {}
    try:
        roles = list(directory.search(directory.base_dn, flt, attrs=["roleOccupant", ALLOWED_ATTR]))
    except NoSuchObjectError:
        return []
    for role in roles:
        if wanted not in {dnlib.normalize(o) for o in role.texts("roleOccupant")}:
            continue
        for app_dn in role.texts(ALLOWED_ATTR):
            granted.setdefault(dnlib.normalize(app_dn), app_dn)
    apps: list[dict[str, Any]] = []
    for app_dn in granted.values():
        entry = directory.get(app_dn)
        item = application_json(entry) if entry is not None else None
        if item is not None:
            apps.append(item)
    apps.sort(key=lambda a: (str(a["title"]).casefold(), str(a["dn"])))
    return apps


def build_router(_ctx: PluginRouterContext) -> APIRouter:
    """Router factory (``Plugin.api_routers``)."""
    router = APIRouter(prefix="/me", tags=["applications"])

    @router.get("/applications")
    def my_applications(user: CurrentUserDep) -> list[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        """Applications allowed to the connected user through their roles."""
        return allowed_applications(user.directory, user.dn)

    return router
