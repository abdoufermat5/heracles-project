"""ETag revalidation of the types and department tree reads."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from heracles.server import build_demo_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_demo_app(), base_url="https://testserver") as c:
        token = c.get("/api/v2/auth/csrf").json()["token"]
        r = c.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": "asmith", "password": "heracles"},
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 200, r.text
        yield c


@pytest.mark.parametrize("path", ["/api/v2/types", "/api/v2/types/user", "/api/v2/tree"])
def test_conditional_get(client: TestClient, path: str) -> None:
    first = client.get(path)
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "private, no-cache"
    again = client.get(path, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b"" and again.headers["etag"] == etag
    assert client.get(path, headers={"If-None-Match": '"other"'}).status_code == 200
    assert client.get(path).json() == first.json()
