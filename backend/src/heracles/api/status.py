"""Directory availability: ``/readyz`` data and ``GET /api/v2/status``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from heracles import metrics
from heracles.api.deps import CurrentUserDep, StateDep
from heracles.api.metrics import build_version
from heracles.api.state import AppState
from heracles.ldap.client import DirectoryClient, DirectoryError

router = APIRouter(tags=["status"])


def directory_state(directory: DirectoryClient) -> tuple[bool, bool, dict[str, str]]:
    """``(readable, writable, {uri: "up"|"down"})`` after a cheap read of the base entry."""
    try:
        readable = directory.get(directory.base_dn, ["objectClass"]) is not None
    except DirectoryError:
        readable = False
    # Directories made of several servers (PyLdapDirectory) expose per-server state.
    states: dict[str, str] = dict(getattr(directory, "server_states", dict)())
    writable_fn = getattr(directory, "writable", None)
    writable = readable and (bool(writable_fn()) if callable(writable_fn) else True)
    return readable, writable, states


def database_ok(state: AppState) -> bool:
    """A cheap query on the application database (``True`` when none is configured)."""
    if state.database is None:
        return True
    try:
        with state.database.connection() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        metrics.DATABASE_ERRORS.inc()
        return False
    return True


def readiness(state: AppState) -> dict[str, Any]:
    dirs: dict[str, Any] = {}
    for dir_id, directory in state.directories.items():
        readable, _writable, servers = directory_state(directory)
        dirs[dir_id] = {"ok": readable, "servers": servers}
    db = database_ok(state)
    ready = db and all(d["ok"] for d in dirs.values())
    return {"status": "ok" if ready else "unavailable", "directories": dirs, "database": db}


@router.get("/status")
def status(_user: CurrentUserDep, state: StateDep) -> dict[str, Any]:
    """Directory availability for the SPA's degraded mode (any authenticated user)."""
    out: dict[str, Any] = {}
    for dir_id, directory in state.directories.items():
        readable, writable, _servers = directory_state(directory)
        out[dir_id] = {"available": readable, "read_only": readable and not writable}
    return {"directories": out, "version": build_version()}
