"""OpenID Connect: provider groups mapped to directory roles held by the session only."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pyotp
import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.domain import invalidate_acl_cache
from heracles.auth.oidc import OidcSettings, mapped_roles
from heracles.auth.sessions import SESSION_ROLES_KEY
from heracles.ldap.client import Modification
from tests.api.test_oidc_login import ASMITH, BASE, ISSUER, make_app, sign_in

LYON_MANAGERS = f"cn=lyon-managers,ou=roles,ou=lyon,{BASE}"
LYON_STAFF = f"cn=lyon-staff,ou=groups,ou=lyon,{BASE}"
CDUPONT = f"uid=cdupont,ou=people,ou=lyon,{BASE}"
DLEFEVRE = f"uid=dlefevre,ou=people,ou=lyon,{BASE}"
MAPPING = {"lyon-admins": [LYON_MANAGERS]}


def can_read_lyon_user(client: TestClient) -> bool:
    """asmith (Paris) reads a Lyon person only through the Lyon managers' assignment."""
    r = client.get(f"/api/v2/objects/user/{quote(DLEFEVRE, safe='')}")
    assert r.status_code in (200, 403, 404), r.text
    return r.status_code == 200


def session_of(client: TestClient, app: Any) -> Any:
    sid = client.cookies.get("heracles_session")
    assert sid
    session = app.state.heracles.sessions.get(sid)
    assert session is not None
    return session


def test_settings_refuse_what_is_not_a_dn() -> None:
    with pytest.raises(ValueError, match="not a DN"):
        OidcSettings(role_mapping={"admins": ["lyon-managers"]})
    with pytest.raises(ValueError, match="full role DN"):
        # what `heracles-readers: [cn=r,ou=roles,dc=example,dc=org]` gives in YAML
        OidcSettings(role_mapping={"admins": ["cn=r", "ou=roles", "dc=example", "dc=org"]})
    with pytest.raises(ValueError, match="empty"):
        OidcSettings(role_mapping={" ": [LYON_MANAGERS]})
    settings = OidcSettings(
        role_mapping={"a": [LYON_MANAGERS], "b": [LYON_MANAGERS.upper(), LYON_STAFF]}
    )
    assert mapped_roles(settings, {"groups": ["b", "a", "other"]}) == [
        LYON_MANAGERS.upper(),
        LYON_STAFF,
    ]
    assert mapped_roles(settings, {"groups": "a"}) == [LYON_MANAGERS]
    assert mapped_roles(settings, {}) == []
    assert mapped_roles(OidcSettings(issuer=ISSUER), {"groups": ["a"]}) == []


def test_a_mapped_group_grants_the_role_for_the_session_and_is_audited() -> None:
    app, provider = make_app(role_mapping=MAPPING)
    with TestClient(app, follow_redirects=False) as client:
        provider.claims = {"groups": ["staff"]}
        assert sign_in(client, provider).headers["location"] == "/dashboard"
        assert not can_read_lyon_user(client)

        provider.claims = {"groups": ["staff", "lyon-admins"]}
        assert sign_in(client, provider).headers["location"] == "/dashboard"
        assert can_read_lyon_user(client)
        assert session_of(client, app).cache[SESSION_ROLES_KEY] == [LYON_MANAGERS]
    directory = app.state.heracles.directories["main"]
    # the directory is untouched: the role is held by the session, not by the entry
    role = directory.get(LYON_MANAGERS)
    assert role is not None and ASMITH not in role.texts("roleOccupant")
    events = list(directory.search(f"ou=audit,{BASE}", "(hrcAuditAction=login)"))
    texts = [" ".join(e.texts("hrcAuditAttributes")) for e in events]
    assert any(f"session role: {LYON_MANAGERS}" in t for t in texts)


def test_the_role_outlives_acl_refreshes_and_invalidations(monkeypatch: pytest.MonkeyPatch) -> None:
    app, provider = make_app(role_mapping=MAPPING)
    with TestClient(app, follow_redirects=False) as client:
        provider.claims = {"groups": ["lyon-admins"]}
        sign_in(client, provider)
        assert can_read_lyon_user(client)
        session = session_of(client, app)
        invalidate_acl_cache(session)
        app.state.heracles.sessions.save(session)
        assert can_read_lyon_user(client)
        # an old resolution is recomputed with the session's roles too
        monkeypatch.setattr("heracles.api.domain.ACL_CACHE_SECONDS", -1.0)
        assert can_read_lyon_user(client)


def test_the_same_person_signing_in_with_a_password_gets_nothing() -> None:
    app, provider = make_app(role_mapping=MAPPING)
    with TestClient(app, follow_redirects=False) as client:
        provider.claims = {"groups": ["lyon-admins"]}
        sign_in(client, provider)
        assert can_read_lyon_user(client)
    with TestClient(app) as client:
        token = client.get("/api/v2/auth/csrf").json()["token"]
        r = client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": "asmith", "password": demo.DEMO_PASSWORD},
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 200, r.text
        assert not can_read_lyon_user(client)


def test_only_role_entries_can_be_mapped() -> None:
    account = f"cn=svc,ou=roles,ou=lyon,{BASE}"
    mapping = {"lyon-admins": [CDUPONT, LYON_STAFF, account, f"cn=missing,ou=roles,{BASE}"]}
    directory = demo.build_demo_directory()
    # a service account: an organizationalRole that binds, holding the Lyon managers' rights
    directory.add(
        account,
        {
            "objectClass": [b"organizationalRole", b"simpleSecurityObject"],
            "cn": [b"svc"],
            "userPassword": [b"x"],
        },
    )
    role = directory.get(LYON_MANAGERS)
    assert role is not None
    acl = directory.get(f"ou=lyon,{BASE}")
    assert acl is not None
    values = [v.replace(LYON_MANAGERS.encode(), account.encode()) for v in acl.attrs["hrcAclEntry"]]
    directory.modify(f"ou=lyon,{BASE}", [Modification("replace", "hrcAclEntry", values)])
    app, provider = make_app(directory, role_mapping=mapping)
    with TestClient(app, follow_redirects=False) as client:
        provider.claims = {"groups": ["lyon-admins"]}
        assert sign_in(client, provider).headers["location"] == "/dashboard"
        assert SESSION_ROLES_KEY not in session_of(client, app).cache
        assert not can_read_lyon_user(client)


def test_a_token_made_in_a_mapped_session_does_not_carry_the_role() -> None:
    app, provider = make_app(role_mapping=MAPPING)
    with TestClient(app, follow_redirects=False) as client:
        provider.claims = {"groups": ["lyon-admins"]}
        sign_in(client, provider)
        headers = {"X-CSRF-Token": client.get("/api/v2/auth/csrf").json()["token"]}
        # the mapped role makes asmith a console user, who may create tokens
        made = client.post(
            "/api/v2/auth/tokens",
            json={"name": "ci", "scope": "read", "expires_in_days": 30},
            headers=headers,
        )
        assert made.status_code == 201, made.text
        secret = str(made.json()["secret"])
    with TestClient(app) as bearer:
        r = bearer.get(
            f"/api/v2/objects/user/{quote(DLEFEVRE, safe='')}",
            headers={"Authorization": f"Bearer {secret}"},
        )
        assert r.status_code in (403, 404), r.text
        own = bearer.get(
            f"/api/v2/objects/user/{quote(ASMITH, safe='')}",
            headers={"Authorization": f"Bearer {secret}"},
        )
        assert own.status_code == 200, own.text


def test_the_role_survives_the_second_factor() -> None:
    app, provider = make_app(role_mapping=MAPPING)
    secret = pyotp.random_base32()
    app.state.heracles.second_factor.store.set_totp_secret(ASMITH, secret)
    with TestClient(app, follow_redirects=False) as client:
        provider.claims = {"groups": ["lyon-admins"]}
        done = sign_in(client, provider)
        assert done.status_code == 302
        assert client.get("/api/v2/auth/me").status_code == 401  # second factor pending
        headers = {"X-CSRF-Token": client.get("/api/v2/auth/csrf").json()["token"]}
        r = client.post(
            "/api/v2/auth/second-factor",
            json={"method": "totp", "code": pyotp.TOTP(secret).now()},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert can_read_lyon_user(client)  # the session id rotated, the role stayed
