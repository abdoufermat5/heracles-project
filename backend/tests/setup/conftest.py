"""Fixtures shared by the setup tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.settings import ApiSettings
from heracles.ldap.client import DirectoryClient
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
