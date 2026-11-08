"""Administrators' view and reset of a user's second factors."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs
from webauthn.helpers import bytes_to_base64url

from heracles.api.state import AppState
from heracles.auth.second_factor import WebAuthnCredential
from heracles.demo import BASE
from heracles.server import build_demo_app
from heracles_plugins.audit.events import events_for

PARIS = f"ou=paris,{BASE}"
ASMITH = f"uid=asmith,ou=people,{PARIS}"
BMARTIN = f"uid=bmartin,ou=people,{PARIS}"
ADMIN = f"uid=admin,ou=people,{BASE}"
DLEFEVRE = f"uid=dlefevre,ou=people,ou=lyon,{BASE}"
HELPDESK = f"uid=helpdesk,ou=people,{BASE}"
KEY_A = b"key-a"
KEY_B = b"key-b"


class Api:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.headers = {"X-CSRF-Token": client.get("/api/v2/auth/csrf").json()["token"]}

    def login(self, username: str, password: str = "heracles") -> Any:
        r = self.client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": username, "password": password},
            headers=self.headers,
        )
        assert r.status_code == 200, r.text
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}
        return r.json()

    def get(self, dn: str, suffix: str = "") -> Any:
        return self.client.get(f"/api/v2/users/{quote(dn, safe='')}/second-factors{suffix}")

    def delete(self, dn: str, suffix: str = "") -> Any:
        return self.client.delete(
            f"/api/v2/users/{quote(dn, safe='')}/second-factors{suffix}", headers=self.headers
        )


@pytest.fixture
def app() -> FastAPI:
    return build_demo_app()


@pytest.fixture
def state(app: FastAPI) -> Iterator[AppState]:
    with TestClient(app):
        yield cast("AppState", app.state.heracles)


def api_for(app: FastAPI, username: str) -> Api:
    api = Api(TestClient(app, base_url="http://testserver"))
    api.login(username)
    return api


def enroll(state: AppState, dn: str) -> None:
    """TOTP, two security keys and recovery codes for ``dn``."""
    state.second_factor.enroll_totp(dn, "x")
    state.second_factor.regenerate_recovery_codes(dn, 4)
    state.second_factor.store.add_webauthn_credential(
        dn, WebAuthnCredential(KEY_A, b"pk-a", 3, "Desk key")
    )
    state.second_factor.store.add_webauthn_credential(
        dn, WebAuthnCredential(KEY_B, b"pk-b", 0, "Phone")
    )


def test_summary_lists_registrations_without_secrets(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    r = api_for(app, "helpdesk").get(ASMITH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "totp": True,
        "security_keys": [
            {"id": bytes_to_base64url(KEY_A), "label": "Desk key"},
            {"id": bytes_to_base64url(KEY_B), "label": "Phone"},
        ],
        "recovery_codes": 4,
        "can_reset": True,
    }
    secret = state.second_factor.store.totp_secret(ASMITH)
    assert secret and secret not in r.text
    assert "pk-a" not in r.text


def test_summary_of_a_user_without_factors(app: FastAPI, state: AppState) -> None:
    r = api_for(app, "helpdesk").get(BMARTIN)
    assert r.json() == {"totp": False, "security_keys": [], "recovery_codes": 0, "can_reset": True}


def test_normal_users_are_refused(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    user = api_for(app, "bmartin")
    assert user.get(ASMITH).status_code == 403
    assert user.delete(ASMITH).status_code == 403
    assert user.delete(ASMITH, f"/webauthn/{bytes_to_base64url(KEY_A)}").status_code == 403
    assert state.second_factor.summary(ASMITH).totp
    assert len(state.second_factor.summary(ASMITH).security_keys) == 2


def test_requires_login(app: FastAPI, state: AppState) -> None:
    anonymous = Api(TestClient(app, base_url="http://testserver"))
    assert anonymous.get(ASMITH).status_code == 401
    assert anonymous.delete(ASMITH).status_code == 401


def test_object_rights_cover_the_attribute_within_their_scope(
    app: FastAPI, state: AppState
) -> None:
    # cdupont has rw on every user/user attribute in Lyon, like for the password
    enroll(state, DLEFEVRE)
    enroll(state, ASMITH)
    manager = api_for(app, "cdupont")
    assert manager.get(ASMITH).status_code == 403
    assert manager.delete(ASMITH).status_code == 403
    assert manager.delete(DLEFEVRE).status_code == 204
    assert state.second_factor.summary(DLEFEVRE).empty
    assert not state.second_factor.summary(ASMITH).empty


def test_read_right_views_but_cannot_reset(app: FastAPI, state: AppState) -> None:
    admin = api_for(app, "admin")
    role = admin.client.post(
        "/api/v2/admin/acl/roles",
        json={
            "base": PARIS,
            "cn": "factor-viewers",
            "templates": [
                {
                    "index": 0,
                    "blocks": [
                        {
                            "object": "user/user",
                            "rights": "r",
                            "attributes": [{"name": "secondFactor", "rights": "r"}],
                        }
                    ],
                }
            ],
        },
        headers=admin.headers,
    )
    assert role.status_code == 201, role.text
    assignment = {
        "index": 0,
        "scope": "subtree",
        "role": role.json()["dn"],
        "members": [BMARTIN],
        "user_filter": None,
        "target_filter": None,
    }
    saved = admin.client.put(
        f"/api/v2/admin/acl/assignments/{quote(PARIS, safe='')}",
        json={"assignments": [assignment]},
        headers=admin.headers,
    )
    assert saved.status_code == 200, saved.text

    enroll(state, ASMITH)
    viewer = api_for(app, "bmartin")
    r = viewer.get(ASMITH)
    assert r.status_code == 200, r.text
    assert r.json()["totp"] is True and r.json()["can_reset"] is False
    assert viewer.delete(ASMITH).status_code == 403
    assert viewer.delete(ASMITH, f"/webauthn/{bytes_to_base64url(KEY_A)}").status_code == 403
    assert len(state.second_factor.summary(ASMITH).security_keys) == 2


def test_acl_administrator_may_reset(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    r = api_for(app, "admin").delete(ASMITH)
    assert r.status_code == 204, r.text
    assert state.second_factor.summary(ASMITH).empty


def test_bootstrap_administrator_may_reset() -> None:
    from heracles import demo
    from heracles.api.settings import ApiSettings
    from heracles.server import create_full_app

    settings = ApiSettings(admin_dns=[BMARTIN], directory_labels={"main": "Demo"})
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": demo.build_demo_directory()})
    with TestClient(app, base_url="http://testserver"):
        state = cast("AppState", app.state.heracles)
        enroll(state, ASMITH)
        assert api_for(app, "bmartin").delete(ASMITH).status_code == 204
        assert state.second_factor.summary(ASMITH).empty


def test_reset_removes_everything_and_login_no_longer_asks(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    first = Api(TestClient(app, base_url="http://testserver"))
    assert first.login("asmith")["status"] == "second_factor"

    assert api_for(app, "helpdesk").delete(ASMITH).status_code == 204

    store = state.second_factor.store
    assert store.totp_secret(ASMITH) is None
    assert store.recovery_hashes(ASMITH) == []
    assert store.webauthn_credentials(ASMITH) == []
    assert state.second_factor.methods_for(ASMITH) == []
    second = Api(TestClient(app, base_url="http://testserver"))
    assert second.login("asmith")["status"] == "ok"
    assert second.client.get("/api/v2/auth/me").status_code == 200


def test_reset_leaves_other_users_alone(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    enroll(state, BMARTIN)
    assert api_for(app, "helpdesk").delete(ASMITH).status_code == 204
    assert state.second_factor.summary(BMARTIN).totp
    assert len(state.second_factor.summary(BMARTIN).security_keys) == 2


def test_remove_a_single_security_key(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    helpdesk = api_for(app, "helpdesk")
    r = helpdesk.delete(ASMITH, f"/webauthn/{bytes_to_base64url(KEY_A)}")
    assert r.status_code == 204, r.text
    summary = state.second_factor.summary(ASMITH)
    assert [c.credential_id for c in summary.security_keys] == [KEY_B]
    assert summary.totp and summary.recovery_codes == 4
    again = helpdesk.delete(ASMITH, f"/webauthn/{bytes_to_base64url(KEY_A)}")
    assert again.status_code == 404
    assert helpdesk.delete(ASMITH, "/webauthn/***").status_code == 404


def test_cannot_remove_a_key_through_another_user(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    r = api_for(app, "helpdesk").delete(BMARTIN, f"/webauthn/{bytes_to_base64url(KEY_A)}")
    assert r.status_code == 404
    assert len(state.second_factor.summary(ASMITH).security_keys) == 2


def test_unknown_user_is_not_found(app: FastAPI, state: AppState) -> None:
    ghost = f"uid=ghost,ou=people,{PARIS}"
    helpdesk = api_for(app, "helpdesk")
    assert helpdesk.get(ghost).status_code == 404
    assert helpdesk.delete(ghost).status_code == 404


def test_nobody_resets_their_own_factors_here(app: FastAPI, state: AppState) -> None:
    helpdesk = api_for(app, "helpdesk")
    enroll(state, HELPDESK)
    assert helpdesk.get(HELPDESK).json()["can_reset"] is False
    assert helpdesk.delete(HELPDESK).status_code == 403
    assert helpdesk.delete(HELPDESK, f"/webauthn/{bytes_to_base64url(KEY_A)}").status_code == 403
    assert state.second_factor.summary(HELPDESK).totp


def test_reset_is_logged_and_audited(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    helpdesk = api_for(app, "helpdesk")
    with capture_logs() as logs:
        assert helpdesk.delete(ASMITH).status_code == 204
    [entry] = [e for e in logs if e["event"] == "second_factor_reset"]
    assert entry["actor"] == HELPDESK
    assert entry["target"] == ASMITH
    assert entry["removed"] == [
        "authenticator app",
        "security key: Desk key",
        "security key: Phone",
        "recovery codes: 4",
    ]
    assert "secret" not in str(entry).lower()

    directory = state.directories["main"]
    [event] = events_for(directory, ASMITH)
    assert event.text("fdAuditAction") == "modify"
    assert event.text("fdAuditAuthorDN") == HELPDESK
    attrs = [v.decode() for v in event.attrs["fdAuditAttributes"]]
    assert attrs == [
        "delete secondFactor: authenticator app, security key: Desk key, "
        "security key: Phone, recovery codes: 4"
    ]


def test_single_key_removal_is_audited(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    with capture_logs() as logs:
        r = api_for(app, "helpdesk").delete(ASMITH, f"/webauthn/{bytes_to_base64url(KEY_B)}")
        assert r.status_code == 204
    [entry] = [e for e in logs if e["event"] == "second_factor_reset"]
    assert entry["removed"] == ["security key: Phone"]
    [event] = events_for(state.directories["main"], ASMITH)
    assert [v.decode() for v in event.attrs["fdAuditAttributes"]] == [
        "delete secondFactor: security key: Phone"
    ]


def test_refused_reset_leaves_no_trace(app: FastAPI, state: AppState) -> None:
    enroll(state, ASMITH)
    with capture_logs() as logs:
        assert api_for(app, "bmartin").delete(ASMITH).status_code == 403
    assert not [e for e in logs if e["event"] == "second_factor_reset"]
    assert events_for(state.directories["main"], ASMITH) == []
