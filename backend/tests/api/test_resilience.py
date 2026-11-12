"""Readiness shape, status endpoint, 503 mapping, metrics gating and the version header."""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from heracles.api.app import create_app
from heracles.api.settings import ApiSettings, MetricsSettings
from heracles.ldap.client import DirectoryUnavailableError
from tests.api.conftest import Env
from tests.auth.fakes import FakeDirectory


def test_readyz_shape(env: Env) -> None:
    body = env.client.get("/readyz").json()
    assert body == {
        "status": "ok",
        "directories": {"main": {"ok": True, "servers": {}}},
        "database": True,
    }


def test_readyz_reports_unavailable_directory(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*_a: object, **_k: object) -> None:
        raise DirectoryUnavailableError("down")

    monkeypatch.setattr(env.directory, "get", down)
    r = env.client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["directories"]["main"]["ok"] is False


def test_status_requires_login_and_reports_directories(env: Env) -> None:
    assert env.client.get("/api/v2/status").status_code == 401
    env.login()
    r = env.client.get("/api/v2/status")
    assert r.status_code == 200
    body = r.json()
    assert body["directories"] == {"main": {"available": True, "read_only": False}}
    assert body["version"]
    assert r.headers["x-heracles-version"] == body["version"]


def test_unavailable_directory_answers_503() -> None:
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:  # pyright: ignore[reportUnusedFunction]
        raise DirectoryUnavailableError("all servers down")

    app = create_app(ApiSettings(), {"main": FakeDirectory()}, extra_routers=[router])
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    r = client.get("/api/v2/boom")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "directory_unavailable"


def _app_client(metrics: MetricsSettings) -> TestClient:
    app = create_app(ApiSettings(metrics=metrics), {"main": FakeDirectory()})
    return TestClient(app, base_url="https://testserver")


def test_metrics_gating() -> None:
    assert _app_client(MetricsSettings()).get("/metrics").status_code == 404
    client = _app_client(MetricsSettings(enabled=True))
    client.get("/healthz")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert 'heracles_http_requests_total{method="GET",route="/healthz",status="200"}' in r.text
    restricted = _app_client(MetricsSettings(enabled=True, allowed_networks=["10.0.0.0/8"]))
    assert restricted.get("/metrics").status_code == 404  # the test client is not in 10/8
