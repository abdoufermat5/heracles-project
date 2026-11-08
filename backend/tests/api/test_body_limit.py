"""Global request-body limit: refused while the body is read, chunked bodies included."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException
from starlette.types import Message, Receive, Scope, Send

from heracles import demo
from heracles.api.middleware import BodyLimitMiddleware
from heracles.api.settings import ApiSettings
from heracles.server import create_full_app

LIMIT = 2_000
IMPORT_LIMIT = 20_000


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = ApiSettings(
        directory_labels={"main": "Demo"},
        admin_dns=[f"uid=admin,ou=people,{demo.BASE}"],
        max_body_bytes=LIMIT,
        max_import_body_bytes=IMPORT_LIMIT,
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": demo.build_demo_directory()})
    with TestClient(app) as test_client:
        yield test_client


def sign_in(client: TestClient) -> dict[str, str]:
    csrf = client.get("/api/v2/auth/csrf").json()["token"]
    login = {"directory": "main", "username": "admin", "password": "heracles"}
    r = client.post("/api/v2/auth/login", json=login, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": client.get("/api/v2/auth/csrf").json()["token"]}


def too_large(r: object) -> bool:
    return getattr(r, "status_code") == 413 and getattr(r, "json")()["error"]["code"] == "too_large"  # noqa: B009


def test_declared_length_above_the_limit_is_refused(client: TestClient) -> None:
    headers = sign_in(client)
    r = client.post("/api/v2/auth/login", content=b"x" * (LIMIT + 1), headers=headers)
    assert too_large(r)
    assert r.headers["X-Request-ID"]  # still gets the common headers


def test_chunked_body_is_counted_while_it_is_read(client: TestClient) -> None:
    headers = {**sign_in(client), "Content-Type": "application/json"}

    def chunks() -> Iterator[bytes]:
        for _ in range(50):  # no Content-Length: 50 KB against a 2 KB limit
            yield b"a" * 1000

    r = client.post("/api/v2/auth/login", content=chunks(), headers=headers)
    assert too_large(r)


@pytest.mark.anyio
async def test_the_stream_is_cut_at_the_limit() -> None:
    """Without Content-Length the middleware stops reading once the limit is crossed."""
    pulled = 0

    async def receive() -> Message:
        nonlocal pulled
        pulled += 1
        return {"type": "http.request", "body": b"a" * 1000, "more_body": True}

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if not message.get("more_body"):
                return

    async def send(message: Message) -> None:
        raise AssertionError("the application answers, not the middleware")

    guarded = BodyLimitMiddleware(app, limit=2_500)
    scope: Scope = {"type": "http", "path": "/x", "headers": []}
    with pytest.raises(HTTPException) as caught:
        await guarded(scope, receive, send)
    assert caught.value.status_code == 413
    assert pulled == 3  # 1000, 2000, 3000 > 2500


def test_small_bodies_and_the_import_allowance(client: TestClient) -> None:
    headers = sign_in(client)
    small = client.post("/api/v2/csv/parse", json={"text": "a,b\n1,2\n"}, headers=headers)
    assert small.status_code == 200
    big_text = "a,b\n" + "1,2\n" * 2_000  # 8 KB: over the common limit, under the import one
    allowed = client.post("/api/v2/csv/parse", json={"text": big_text}, headers=headers)
    assert allowed.status_code == 200 and allowed.json()["total"] == 2_000
    huge = client.post("/api/v2/csv/parse", json={"text": "x" * IMPORT_LIMIT}, headers=headers)
    assert too_large(huge)
    elsewhere = client.post("/api/v2/auth/login", json={"pad": big_text}, headers=headers)
    assert too_large(elsewhere)
