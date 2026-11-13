from __future__ import annotations

import argparse
import stat
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.settings import ApiSettings
from heracles.cli import init as init_cli
from heracles.ldap.client import DirectoryClient, InvalidCredentialsError
from heracles.ldap.config import DirectoryConfig
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app
from heracles.setup import mode, service

BASE = "dc=example,dc=org"
TOKEN = "t0ken"
DIRECTORY = {
    "uri": "ldap://ldap.test",
    "starttls": False,
    "ca_file": None,
    "bind_dn": f"cn=admin,{BASE}",
    "bind_password": "secret",
    "base_dn": BASE,
}
AUTH = {"X-Setup-Token": TOKEN}


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERACLES_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("HERACLES_CONFIG", raising=False)
    monkeypatch.delenv("HERACLES_LDAP_URI", raising=False)


@pytest.fixture
def directory() -> MemoryDirectory:
    memory = MemoryDirectory(BASE, object_classes=service.required_classes())
    memory.add(BASE, {"objectClass": [b"dcObject", b"organization"], "dc": [b"example"]})
    return memory


@pytest.fixture
def server(directory: MemoryDirectory, tmp_path: Path) -> tuple[TestClient, mode.SetupState]:
    def factory(_config: DirectoryConfig) -> DirectoryClient:
        return directory

    def build(path: Path) -> FastAPI:
        return create_full_app(ApiSettings(), {"main": directory}, config_path=path)

    state = mode.SetupState(
        token=TOKEN,
        config_path=tmp_path / "data" / "heracles.yaml",
        build_app=build,
        client_factory=factory,
    )
    dispatcher = mode.SetupDispatcher(mode.build_setup_app(state))
    state.on_applied = dispatcher.switch
    service.write_token(TOKEN)
    return TestClient(dispatcher), state


def test_setup_mode_gates_the_api(server: tuple[TestClient, mode.SetupState]) -> None:
    client, state = server
    status = client.get("/api/v2/setup/status").json()
    assert status["setup_required"] is True
    assert status["config_path"] == str(state.config_path)

    other = client.get("/api/v2/auth/csrf")
    assert other.status_code == 503
    assert other.json()["error"]["code"] == "setup_required"

    denied = client.get("/api/v2/setup/plugins")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "setup_token_invalid"
    assert client.post("/api/v2/setup/token/verify", json={"token": "no"}).status_code == 401
    assert client.post("/api/v2/setup/token/verify", json={"token": TOKEN}).status_code == 204

    plugins = client.get("/api/v2/setup/plugins", headers=AUTH).json()
    core = next(p for p in plugins["profiles"] if p["id"] == "core")
    assert "posix" in core["plugins"]
    assert {p["name"] for p in plugins["plugins"]} >= set(core["plugins"])
    assert client.get("/api/v2/setup/schema?format=schema", headers=AUTH).status_code == 200


def test_wrong_tokens_are_rate_limited(server: tuple[TestClient, mode.SetupState]) -> None:
    client, _ = server
    codes = [client.get("/api/v2/setup/plugins").status_code for _ in range(8)]
    assert codes[0] == 401
    assert codes[-1] == 429
    assert client.get("/api/v2/setup/plugins", headers=AUTH).status_code == 429


def test_directory_test_reports_failures_and_results(
    server: tuple[TestClient, mode.SetupState],
) -> None:
    client, state = server
    ok = client.post("/api/v2/setup/directory/test", json=DIRECTORY, headers=AUTH).json()
    assert ok["ok"] is True
    assert ok["base_dn_exists"] is True
    assert ok["can_write"] is True
    assert ok["schema"] == {"installed": True, "missing_classes": []}

    def refuse(_config: DirectoryConfig) -> DirectoryClient:
        raise InvalidCredentialsError("service account bind failed")

    state.client_factory = refuse
    bad = client.post("/api/v2/setup/directory/test", json=DIRECTORY, headers=AUTH)
    assert bad.status_code == 200
    assert bad.json()["ok"] is False
    assert bad.json()["error"]["code"] == "bad_credentials"


def test_apply_writes_the_config_and_switches_mode(
    server: tuple[TestClient, mode.SetupState], directory: MemoryDirectory
) -> None:
    client, state = server
    body: dict[str, Any] = {
        "directory": {**DIRECTORY, "id": "main", "label": "Example"},
        "admin": {
            "uid": "root",
            "given_name": "Root",
            "surname": "Admin",
            "mail": "root@example.org",
            "password": "correct horse battery 7",
        },
        "plugins": ["posix", "audit"],
        "public_url": "https://heracles.example.org",
    }
    weak = {**body, "admin": {**body["admin"], "password": "x"}}
    refused = client.post("/api/v2/setup/apply", json=weak, headers=AUTH)
    assert refused.status_code == 422
    assert "admin.password" in refused.json()["error"]["fields"]
    assert not state.config_path.exists()

    done = client.post("/api/v2/setup/apply", json=body, headers=AUTH)
    assert done.status_code == 200, done.text
    assert done.json() == {"ok": True, "config_path": str(state.config_path), "login_url": "/login"}

    assert stat.S_IMODE(state.config_path.stat().st_mode) == 0o600
    written = yaml.safe_load(state.config_path.read_text())
    admin_dn = f"uid=root,ou=people,{BASE}"
    assert written["api"]["admin_dns"] == [admin_dn]
    assert written["api"]["allowed_hosts"] == ["heracles.example.org"]
    assert written["api"]["session"]["cookie_secure"] is True
    assert written["plugins"]["enabled"] == ["posix", "audit"]
    assert written["directories"][0]["base_dn"] == BASE
    assert directory.get(admin_dn) is not None
    assert not service.token_path().exists()

    # the same process now serves the real application
    assert client.get("/api/v2/setup/status").json()["setup_required"] is False
    assert client.get("/api/v2/auth/csrf").status_code == 200


def test_init_non_interactive(
    directory: MemoryDirectory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "bind.pw").write_text("secret\n")
    (tmp_path / "admin.pw").write_text("correct horse battery 7\n")
    output = tmp_path / "out" / "heracles.yaml"
    args = argparse.Namespace(
        uri="ldap://ldap.test",
        starttls=False,
        ca_file=None,
        bind_dn=f"cn=admin,{BASE}",
        bind_password_file=str(tmp_path / "bind.pw"),
        base_dn=BASE,
        label=None,
        admin_uid="root",
        admin_password_file=str(tmp_path / "admin.pw"),
        admin_mail=None,
        plugins="core",
        public_url=None,
        output=str(output),
        force=False,
        yes=True,
    )
    assert init_cli.run_init(args, factory=lambda _c: directory) == 0
    written = yaml.safe_load(output.read_text())
    assert written["directories"][0]["bind_password"] == "secret"
    assert written["api"]["admin_dns"] == [f"uid=root,ou=people,{BASE}"]
    assert "posix" in written["plugins"]["enabled"]
    capsys.readouterr()

    # a second run refuses to overwrite, and a missing answer fails without prompting
    assert init_cli.run_init(args, factory=lambda _c: directory) == 2
    args.force = True
    args.uri = None
    assert init_cli.run_init(args, factory=lambda _c: directory) == 2
    assert "--uri is required" in capsys.readouterr().err


def test_setup_required_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert service.setup_required(None) is True
    assert service.setup_required(tmp_path / "missing.yaml") is True
    config = tmp_path / "c.yaml"
    config.write_text("api: {}\n")
    assert service.setup_required(config) is True
    config.write_text("directories:\n  - id: a\n    uri: ldap://x\n    base_dn: dc=x\n")
    assert service.setup_required(config) is False
    monkeypatch.setenv("HERACLES_LDAP_URI", "ldap://x")
    assert service.setup_required(None) is False


def test_a_failing_start_leaves_the_setup_retryable(
    server: tuple[TestClient, mode.SetupState], directory: MemoryDirectory
) -> None:
    _client, state = server
    real_build = state.build_app
    attempts: list[int] = []

    def flaky(path: Path) -> FastAPI:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("cannot start yet")
        return real_build(path)

    state.build_app = flaky
    client = TestClient(
        mode.SetupDispatcher(mode.build_setup_app(state)), raise_server_exceptions=False
    )
    body: dict[str, Any] = {
        "directory": {**DIRECTORY, "id": "main"},
        "admin": {"uid": "root", "password": "correct horse battery 7"},
        "plugins": ["posix"],
    }
    assert client.post("/api/v2/setup/apply", json=body, headers=AUTH).status_code == 500
    assert state.token == TOKEN and service.token_path().exists()
    again = client.post("/api/v2/setup/apply", json=body, headers=AUTH)
    assert again.status_code == 200, again.text
    assert state.token == "" and not service.token_path().exists()


def test_token_file_is_private_even_when_a_looser_one_exists() -> None:
    path = service.token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stale", encoding="utf-8")
    path.chmod(0o644)
    assert service.write_token("fresh") == path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="utf-8") == "fresh\n"
