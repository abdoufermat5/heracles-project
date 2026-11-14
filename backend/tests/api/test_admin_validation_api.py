"""The access-control endpoints answer 422 with ``fields`` for values the forms refuse."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from heracles.server import build_demo_app
from tests.api.test_admin_api import (
    BASE,
    BMARTIN,
    HELPDESK_ROLE,
    PARIS,
    Api,
    dnp,
)

TEMPLATES = [{"index": 0, "blocks": [{"object": "user/user", "rights": "r"}]}]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_demo_app(), base_url="http://testserver") as c:
        yield c


@pytest.fixture
def admin(client: TestClient) -> Api:
    return Api(client).login("admin")


def _fields(response: object) -> dict[str, str]:
    assert getattr(response, "status_code") == 422, getattr(response, "text")  # noqa: B009
    return getattr(response, "json")()["error"]["fields"]  # type: ignore[no-any-return]  # noqa: B009


@pytest.mark.parametrize("cn", ["", "  ", "a,b", "a#b", "a=b", "x" * 65])
def test_role_name_is_refused(admin: Api, cn: str) -> None:
    fields = _fields(admin.post("/acl/roles", {"cn": cn, "templates": TEMPLATES}))
    assert list(fields) == ["cn"]


def test_duplicate_role_name_is_refused(admin: Api) -> None:
    body = {"cn": "helpdesk", "templates": TEMPLATES}
    assert "cn" in _fields(admin.post("/acl/roles", body))


def test_role_description_and_base_are_checked(admin: Api) -> None:
    assert "description" in _fields(
        admin.post("/acl/roles", {"cn": "ok", "description": "d" * 600, "templates": TEMPLATES})
    )
    assert "base" in _fields(
        admin.post("/acl/roles", {"cn": "ok", "base": "garbage", "templates": TEMPLATES})
    )
    assert "base" in _fields(
        admin.post("/acl/roles", {"cn": "ok", "base": f"ou=nowhere,{BASE}", "templates": TEMPLATES})
    )
    assert admin.get("/acl/roles").json() and all(
        r["cn"] != "ok" for r in admin.get("/acl/roles").json()
    )


def test_role_update_refuses_a_long_description(admin: Api) -> None:
    fields = _fields(admin.put(f"/acl/roles/{dnp(HELPDESK_ROLE)}", {"description": "d" * 600}))
    assert list(fields) == ["description"]


@pytest.mark.parametrize(
    ("patch", "key"),
    [
        ({"user_filter": "uid=x"}, "assignments.0.user_filter"),
        ({"target_filter": "(&(a=1)"}, "assignments.0.target_filter"),
        ({"members": ["nope"]}, "assignments.0.members"),
        ({"members": [f"uid=ghost,ou=people,{BASE}"]}, "assignments.0.members"),
        ({"role": "nope"}, "assignments.0.role"),
        ({"role": f"cn=ghost,ou=aclroles,{BASE}"}, "assignments.0.role"),
    ],
)
def test_assignment_is_refused(admin: Api, patch: dict[str, object], key: str) -> None:
    item: dict[str, object] = {
        "scope": "subtree",
        "role": HELPDESK_ROLE,
        "members": [BMARTIN],
        **patch,
    }
    fields = _fields(admin.put(f"/acl/assignments/{dnp(PARIS)}", {"assignments": [item]}))
    assert list(fields) == [key]
    assert admin.get(f"/acl/assignments/{dnp(PARIS)}").json()["assignments"] == []


def test_check_rights_refuses_malformed_dns(admin: Api) -> None:
    fields = _fields(admin.post("/acl/check", {"user": "nobody", "dn": "", "object": "user/user"}))
    assert set(fields) == {"user", "dn"}
