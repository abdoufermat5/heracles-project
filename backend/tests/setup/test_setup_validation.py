"""The setup API refuses malformed connection, administrator and address values."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from heracles.setup import mode, service
from tests.setup.conftest import AUTH, DIRECTORY

ADMIN = {
    "uid": "root",
    "given_name": "Root",
    "surname": "Admin",
    "mail": "root@example.org",
    "password": "correct horse battery 7",
}


def _body(**patch: Any) -> dict[str, Any]:
    section = {**DIRECTORY, "id": "main", "label": "Example", **patch.pop("directory", {})}
    return {
        "directory": section,
        "admin": {**ADMIN, **patch.pop("admin", {})},
        "plugins": ["posix"],
        "public_url": patch.pop("public_url", None),
    }


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"directory": {"uri": "http://ldap.test"}}, "directory.uri"),
        ({"directory": {"uri": "ldap://"}}, "directory.uri"),
        ({"directory": {"uri": "ldap://bad host"}}, "directory.uri"),
        ({"directory": {"uri": "ldap://ldap.test:99999"}}, "directory.uri"),
        ({"directory": {"uri": "ldap://ldap.test:abc"}}, "directory.uri"),
        ({"directory": {"base_dn": ""}}, "directory.base_dn"),
        ({"directory": {"base_dn": "example.org"}}, "directory.base_dn"),
        ({"directory": {"base_dn": "dc=example,,dc=org"}}, "directory.base_dn"),
        ({"directory": {"bind_dn": "admin"}}, "directory.bind_dn"),
        ({"directory": {"bind_password": ""}}, "directory.bind_password"),
        ({"directory": {"ca_file": "ca.pem"}}, "directory.ca_file"),
        ({"directory": {"uri": "ldaps://ldap.test", "starttls": True}}, "directory.starttls"),
        ({"directory": {"id": "has space"}}, "directory.id"),
        ({"directory": {"label": "x" * 81}}, "directory.label"),
        ({"admin": {"uid": ""}}, "admin.uid"),
        ({"admin": {"uid": "a b"}}, "admin.uid"),
        ({"admin": {"uid": "a,b"}}, "admin.uid"),
        ({"admin": {"uid": "x" * 65}}, "admin.uid"),
        ({"admin": {"given_name": " "}}, "admin.given_name"),
        ({"admin": {"surname": ""}}, "admin.surname"),
        ({"admin": {"mail": "nope"}}, "admin.mail"),
        ({"admin": {"mail": "a@b"}}, "admin.mail"),
        ({"admin": {"password": "short"}}, "admin.password"),
        ({"public_url": "heracles.example.org"}, "public_url"),
        ({"public_url": "ftp://heracles.example.org"}, "public_url"),
    ],
)
def test_apply_refuses(
    server: tuple[TestClient, mode.SetupState],
    patch: dict[str, Any],
    field: str,
) -> None:
    client, state = server
    refused = client.post("/api/v2/setup/apply", json=_body(**patch), headers=AUTH)
    assert refused.status_code == 422, refused.text
    assert field in refused.json()["error"]["fields"]
    assert not state.config_path.exists()


def test_apply_reports_every_field_at_once(server: tuple[TestClient, mode.SetupState]) -> None:
    client, _ = server
    body = _body(directory={"uri": "nope", "base_dn": "x"}, admin={"uid": "", "mail": "z"})
    fields = client.post("/api/v2/setup/apply", json=body, headers=AUTH).json()["error"]["fields"]
    assert {"directory.uri", "directory.base_dn", "admin.uid", "admin.mail"} <= set(fields)


def test_several_uris_and_a_socket_are_accepted() -> None:
    assert service.check_uri("ldap://a.test ldaps://b.test:636") is None
    assert service.check_uri("ldapi://%2Fvar%2Frun%2Fldapi") is None
    assert service.check_uri("ldap://[::1]:389") is None
    assert service.check_uri("   ") is not None


def test_directory_test_refuses_malformed_input_without_connecting(
    server: tuple[TestClient, mode.SetupState],
) -> None:
    client, state = server

    def never(_config: object) -> object:
        raise AssertionError("must not connect")

    state.client_factory = never  # type: ignore[assignment]
    bad = {**DIRECTORY, "uri": "nope", "base_dn": "x", "ca_file": "ca.pem"}
    refused = client.post("/api/v2/setup/directory/test", json=bad, headers=AUTH)
    assert refused.status_code == 422
    assert {"uri", "base_dn", "ca_file"} <= set(refused.json()["error"]["fields"])


def test_directory_test_accepts_an_empty_base_dn(
    server: tuple[TestClient, mode.SetupState],
) -> None:
    """The wizard tests without a base DN first, to suggest the server's naming context."""
    client, _ = server
    ok = client.post(
        "/api/v2/setup/directory/test", json={**DIRECTORY, "base_dn": ""}, headers=AUTH
    )
    assert ok.status_code != 422
