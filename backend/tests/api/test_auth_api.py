from __future__ import annotations

from tests.api.conftest import Env


def test_branding_is_public_and_configurable() -> None:
    from fastapi.testclient import TestClient

    from heracles.api.app import create_app
    from heracles.api.settings import ApiSettings, BrandingSettings
    from tests.auth.fakes import FakeDirectory

    default = TestClient(create_app(ApiSettings(), {"main": FakeDirectory()}))
    assert default.get("/api/v2/branding").json() == {
        "organization": "",
        "logo_url": None,
        "tagline": "",
    }
    branded = ApiSettings(
        branding=BrandingSettings(organization="Example Corp", logo_url="/logo.svg", tagline="IT")
    )
    client = TestClient(create_app(branded, {"main": FakeDirectory()}))
    assert client.get("/api/v2/branding").json() == {
        "organization": "Example Corp",
        "logo_url": "/logo.svg",
        "tagline": "IT",
    }


def test_my_groups_lists_only_my_memberships(env: Env) -> None:
    other = env.user_dn.replace("uid=jdoe", "uid=other")
    base = env.directory.base_dn
    env.directory.add(
        f"cn=staff,ou=groups,{base}",
        {
            "objectClass": [b"groupOfNames"],
            "cn": [b"staff"],
            "description": [b"Everyone"],
            "member": [env.user_dn.encode(), other.encode()],
        },
    )
    env.directory.add(
        f"cn=admins,ou=groups,{base}",
        {"objectClass": [b"groupOfNames"], "cn": [b"admins"], "member": [other.encode()]},
    )
    assert env.client.get("/api/v2/auth/me/groups").status_code == 401
    env.login()
    r = env.client.get("/api/v2/auth/me/groups")
    assert r.status_code == 200
    assert r.json() == [
        {"dn": f"cn=staff,ou=groups,{base}", "name": "staff", "description": "Everyone"}
    ]
