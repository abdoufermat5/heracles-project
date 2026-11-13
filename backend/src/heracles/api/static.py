"""Static SPA serving with history-API fallback."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response

from heracles.api.errors import error_body


def mount_spa(app: FastAPI, directory: Path) -> bool:
    """Serve ``directory`` (if it holds an ``index.html``); returns whether it was mounted."""
    root = directory.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        if path == "api" or path.startswith("api/"):
            return JSONResponse(error_body("not_found", "Not found"), status_code=404)
        if "\x00" in path:  # not a file name: resolve() would raise
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            headers = (
                {"Cache-Control": "public, max-age=31536000, immutable"}
                if path.startswith("assets/")
                else None
            )
            return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True
