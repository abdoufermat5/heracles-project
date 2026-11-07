"""API v2 integration tests for the certificates plugin tab on users."""

from __future__ import annotations

import base64
import datetime
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from heracles import demo
from heracles.demo import BASE
from heracles.ldap.memory import MemoryDirectory
from heracles.server import build_demo_app

PARIS = f"ou=paris,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


def generate_cert_pem(cn: str = "Test User") -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(x509.NameOID.COMMON_NAME, cn),
            x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "Heracles"),
        ]
    )
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


class Api:
    """Small helper around TestClient handling CSRF and login."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        token = client.get("/api/v2/auth/csrf").json()["token"]
        self.headers = {"X-CSRF-Token": token}

    def login(self, username: str, password: str = "heracles") -> Api:
        r = self.post(
            "/auth/login", {"directory": "main", "username": username, "password": password}
        )
        assert r.status_code == 200, r.text
        token = self.client.get("/api/v2/auth/csrf").json()["token"]
        self.headers = {"X-CSRF-Token": token}
        return self

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v2{path}", params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"/api/v2{path}", json=body, headers=self.headers)

    def patch(self, path: str, body: Any) -> Any:
        return self.client.patch(f"/api/v2{path}", json=body, headers=self.headers)

    def delete(self, path: str) -> Any:
        return self.client.delete(f"/api/v2{path}", headers=self.headers)


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    orig_builder = demo.build_demo_directory

    def _build_demo_dir() -> MemoryDirectory:
        d = orig_builder()
        d.set_schema_object_classes(d.schema_object_classes() | {"strongauthenticationuser"})
        return d

    monkeypatch.setattr(demo, "build_demo_directory", _build_demo_dir)
    with TestClient(build_demo_app()) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


def test_user_descriptor_includes_certificates_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    desc = a.get("/types/user").json()
    tabs = {t["name"]: t for t in desc["tabs"]}
    assert "certificates" in tabs
    tab = tabs["certificates"]
    assert tab["label"] == "Certificates"
    assert tab["optional"] is True


def test_certificates_api_create_and_read(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    pem = generate_cert_pem("Eve Online")

    payload = {
        "base": PARIS,
        "tabs": {
            "main": {
                "values": {
                    "uid": "eve",
                    "sn": "Online",
                    "givenName": "Eve",
                }
            },
            "certificates": {
                "active": True,
                "values": {
                    "userCertificate;binary": [pem],
                },
            },
        },
    }
    r = a.post("/objects/user", payload)
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]

    r_get = a.get(f"/objects/user/{q(dn)}")
    assert r_get.status_code == 200
    data = r_get.json()
    assert "certificates" in data["tabs"]
    certs_data = data["tabs"]["certificates"]["values"]
    assert len(certs_data["userCertificate;binary"]) == 1
    # Raw value in JSON is base64 encoded DER
    b64_val = certs_data["userCertificate;binary"][0]
    der_bytes = base64.b64decode(b64_val)
    assert len(der_bytes) > 100
    assert "CN=Eve Online" in certs_data["certificateSummary"]
