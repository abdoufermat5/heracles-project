"""The application uses the SQLite database when one is configured."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.app import create_app
from heracles.api.settings import ApiSettings, DatabaseSettings
from heracles.api.state import AppState
from heracles.auth.second_factor import InMemorySecondFactorStore, WebAuthnCredential
from heracles.auth.second_factor_db import SqliteSecondFactorStore
from tests.auth.fakes import FakeDirectory


def _app(path: Path | None) -> tuple[TestClient, str]:
    directory = FakeDirectory()
    user_dn = directory.add_user("jdoe", "s3cretpass", mail="jdoe@example.com")
    app = create_app(ApiSettings(database=DatabaseSettings(path=path)), {"main": directory})
    return TestClient(app, base_url="https://testserver"), user_dn


def _state(client: TestClient) -> AppState:
    return cast(AppState, cast(FastAPI, client.app).state.heracles)


def _login(client: TestClient) -> dict[str, object]:
    token = client.get("/api/v2/auth/csrf").json()["token"]
    r = client.post(
        "/api/v2/auth/login",
        json={"directory": "main", "username": "jdoe", "password": "s3cretpass"},
        headers={"X-CSRF-Token": token},
    )
    return r.json()


def test_second_factors_survive_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "data" / "heracles.db"
    client, user_dn = _app(path)
    state = _state(client)
    assert isinstance(state.second_factor.store, SqliteSecondFactorStore)
    assert state.database is not None
    state.second_factor.store.add_webauthn_credential(
        user_dn, WebAuthnCredential(b"k", b"pk", 0, "Key")
    )
    assert _login(client)["status"] == "second_factor"
    state.database.close()

    restarted, _ = _app(path)
    assert _login(restarted) == {"status": "second_factor", "methods": ["webauthn"]}


def test_without_a_database_the_stores_stay_in_memory() -> None:
    client, _ = _app(None)
    state = _state(client)
    assert state.database is None
    assert isinstance(state.second_factor.store, InMemorySecondFactorStore)


def test_production_app_defaults_the_database_to_the_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heracles import server

    config = tmp_path / "heracles.yaml"
    config.write_text(
        "directories:\n"
        "  - id: main\n"
        "    uri: ldap://127.0.0.1:1\n"
        "    base_dn: dc=example,dc=com\n"
        "api: {}\n"
    )
    monkeypatch.setenv("HERACLES_DATA_DIR", str(tmp_path / "var"))
    captured: dict[str, ApiSettings] = {}

    def fake_full_app(settings: ApiSettings, *_args: object, **_kw: object) -> object:
        captured["settings"] = settings
        return object()

    monkeypatch.setattr(server, "create_full_app", fake_full_app)

    # no LDAP connection is needed to assemble the settings
    def fake_directory(_cfg: object) -> object:
        return object()

    monkeypatch.setitem(
        sys.modules, "heracles.ldap.pyldap", SimpleNamespace(PyLdapDirectory=fake_directory)
    )
    server.build_app(config)
    assert captured["settings"].database.path == tmp_path / "var" / "heracles.db"
