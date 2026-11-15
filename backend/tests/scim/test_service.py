"""SCIM service: resources over the object service of the request (ACL, validation, lock)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from heracles.api.deps import CurrentUser
from heracles.auth.passwords import is_locked
from heracles.auth.sessions import Session
from heracles.demo import ADMIN_DN, BASE
from heracles.ldap.client import DirectoryClient, Modification
from heracles.scim.errors import ScimError
from heracles.scim.filter import And, Compare, Not, Or, parse
from heracles.scim.patch import PatchOp
from heracles.scim.schemas import ENTERPRISE_USER_SCHEMA, GROUP_SCHEMA, USER_SCHEMA
from heracles.scim.service import ScimService
from heracles.scim.settings import ScimSettings
from heracles.server import build_demo_app
from heracles_plugins.archive.service import find_archives

BASE_URL = "http://testserver/scim/v2"
HELPDESK = f"uid=helpdesk,ou=people,{BASE}"
LYON_MANAGER = f"uid=cdupont,ou=people,ou=lyon,{BASE}"
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"


@dataclass
class Env:
    app: Any
    directory: DirectoryClient

    def service(self, dn: str = ADMIN_DN, **settings: Any) -> ScimService:
        session = Session(id=f"s-{dn}", user_dn=dn, directory_id="main", created_at=0, last_seen=0)
        user = CurrentUser(session, "main", self.directory)
        return ScimService(user, self.app.state.domain, ScimSettings(**settings), BASE_URL)


@pytest.fixture
def env() -> Iterator[Env]:
    app = build_demo_app()
    with TestClient(app):
        yield Env(app, app.state.heracles.directories["main"])


def user_body(
    name: str = "jsmith", extra: dict[str, Any] | None = None, **more: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schemas": [USER_SCHEMA],
        "userName": name,
        "name": {"givenName": "John", "familyName": "Smith"},
        "emails": [{"value": f"{name}@example.test", "type": "work", "primary": True}],
    }
    body.update(extra or {})
    body.update(more)
    return body


def err(fn: Any, *args: Any, **kwargs: Any) -> ScimError:
    with pytest.raises(ScimError) as info:
        fn(*args, **kwargs)
    return info.value


def userlist(page: Any) -> list[str]:
    return [r["userName"] for r in page.resources]


# ---------------------------------------------------------------- users


def test_create_and_get_user(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body(phoneNumbers=[{"value": "+33 1 23 45 67", "type": "mobile"}]))
    assert made["userName"] == "jsmith"
    assert made["name"] == {"givenName": "John", "familyName": "Smith", "formatted": "John Smith"}
    assert made["emails"] == [{"value": "jsmith@example.test", "type": "work", "primary": True}]
    assert made["phoneNumbers"] == [{"value": "+33 1 23 45 67", "type": "mobile"}]
    assert made["active"] is True
    assert "password" not in made
    meta = made["meta"]
    assert meta["resourceType"] == "User"
    assert meta["location"] == f"{BASE_URL}/Users/{made['id']}"
    assert meta["created"].endswith("Z") and "T" in meta["created"]
    assert meta["version"].startswith('W/"')
    assert users.get(made["id"]) == made


def test_version_changes_with_content_only(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body())
    same = users.replace(made["id"], user_body())
    assert same["meta"]["version"] == made["meta"]["version"]
    other = users.replace(made["id"], user_body(displayName="Johnny"))
    assert other["meta"]["version"] != made["meta"]["version"]


def test_duplicate_username_is_a_conflict(env: Env) -> None:
    users = env.service().users
    users.create(user_body())
    e = err(users.create, user_body())
    assert (e.status, e.scim_type) == (409, "uniqueness")


def test_invalid_login_and_missing_fields(env: Env) -> None:
    users = env.service().users
    e = err(users.create, user_body("bad name!"))
    assert (e.status, e.scim_type) == (400, "invalidValue")
    assert "userName" in e.detail
    e = err(users.create, {"schemas": [USER_SCHEMA]})
    assert (e.status, e.scim_type) == (400, "invalidValue")
    partial = user_body()
    partial["name"] = {"givenName": "J"}
    e = err(users.create, partial)
    assert e.status == 400 and "familyName" in e.detail


def test_unknown_id_is_404(env: Env) -> None:
    users = env.service().users
    assert err(users.get, "no-such-id").status == 404
    assert err(users.delete, "no-such-id").status == 404


def test_password_is_write_only_and_works(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body(password="S3cret-pass-1"))
    assert "password" not in made
    dn = f"uid=jsmith,ou=people,{BASE}"
    assert env.directory.get(dn, ["userPassword"]) is not None
    stored = env.directory.get(dn, ["userPassword"])
    assert stored is not None and stored.text("userPassword")
    users.patch(made["id"], [PatchOp("replace", "password", "An0ther-pass-2")])
    after = env.directory.get(dn, ["userPassword"])
    assert after is not None and after.text("userPassword") != stored.text("userPassword")


def test_put_clears_absent_mapped_attributes_only(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body(displayName="Johnny", title="ignored"))
    dn = f"uid=jsmith,ou=people,{BASE}"
    env.directory.modify(
        dn,
        [Modification("replace", "description", [b"kept"])],
    )
    out = users.replace(made["id"], user_body())
    assert "displayName" not in out
    entry = env.directory.get(dn)
    assert entry is not None and entry.text("description") == "kept"


def test_rename_through_put_keeps_the_id(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body())
    out = users.replace(made["id"], user_body("jsmith2"))
    assert out["id"] == made["id"] and out["userName"] == "jsmith2"
    assert users.get(made["id"])["userName"] == "jsmith2"


def test_active_locks_and_unlocks(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body())
    dn = f"uid=jsmith,ou=people,{BASE}"
    out = users.patch(made["id"], [PatchOp("replace", "active", False)])
    assert out["active"] is False
    entry = env.directory.get(dn, ["userPassword"])
    assert entry is not None and is_locked(entry.text("userPassword") or "")
    assert users.replace(made["id"], user_body())["active"] is False  # absent: unchanged
    assert users.replace(made["id"], user_body(active=True))["active"] is True


def test_create_inactive(env: Env) -> None:
    users = env.service().users
    assert users.create(user_body(active=False))["active"] is False


def test_manager_by_id(env: Env) -> None:
    users = env.service().users
    boss = users.create(user_body("boss"))
    made = users.create(
        user_body(extra={ENTERPRISE_USER_SCHEMA: {"manager": {"value": boss["id"]}}})
    )
    ext = made[ENTERPRISE_USER_SCHEMA]
    assert ext["manager"]["value"] == boss["id"]
    assert ENTERPRISE_USER_SCHEMA in made["schemas"]
    e = err(
        users.create,
        user_body("x1", extra={ENTERPRISE_USER_SCHEMA: {"manager": {"value": "nope"}}}),
    )
    assert (e.status, e.scim_type) == (400, "invalidValue")


def test_enterprise_attribute_through_patch(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body())
    path = f"{ENTERPRISE_USER_SCHEMA}:employeeNumber"
    out = users.patch(made["id"], [PatchOp("add", path, "E-42")])
    assert out[ENTERPRISE_USER_SCHEMA]["employeeNumber"] == "E-42"
    assert ENTERPRISE_USER_SCHEMA in out["schemas"]


def test_patch_touches_only_what_changed(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body())
    dn = f"uid=jsmith,ou=people,{BASE}"
    seen: list[str] = []
    real = env.directory.modify

    def spy(target: str, changes: Any) -> None:
        if target == dn:  # not the audit log
            seen.extend(c.attr for c in changes)
        real(target, changes)

    env.directory.modify = spy  # type: ignore[method-assign]
    users.patch(made["id"], [PatchOp("replace", "displayName", "Johnny")])
    assert seen == ["displayName"]
    seen.clear()
    users.patch(made["id"], [PatchOp("replace", "active", False)])
    assert seen == ["userPassword"]
    assert env.directory.get(dn) is not None


def test_patch_readonly_attribute(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body())
    e = err(users.patch, made["id"], [PatchOp("replace", "id", "x")])
    assert (e.status, e.scim_type) == (400, "mutability")


def test_user_groups_are_read_only_and_listed(env: Env) -> None:
    svc = env.service()
    made = svc.users.create(user_body())
    g = svc.groups.create(
        {"schemas": [GROUP_SCHEMA], "displayName": "devs", "members": [{"value": made["id"]}]}
    )
    got = svc.users.get(made["id"])
    assert got["groups"] == [
        {
            "value": g["id"],
            "$ref": f"{BASE_URL}/Groups/{g['id']}",
            "type": "direct",
            "display": "devs",
        }
    ]
    assert "groups" not in svc.users.search(Compare("userName", "eq", "jsmith")).resources[0]


def test_delete_archives_then_deletes(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body())
    users.delete(made["id"])
    assert err(users.get, made["id"]).status == 404
    assert find_archives(env.directory, "user", {"uid": "jsmith"})


# ---------------------------------------------------------------- search


def test_search_filters_sort_and_paging(env: Env) -> None:
    users = env.service().users
    page = users.search(None)
    assert page.total_results == 7 and page.start_index == 1
    assert userlist(page) == sorted(userlist(page))
    desc = users.search(None, sort_by="userName", descending=True)
    assert userlist(desc) == sorted(userlist(page), reverse=True)
    mid = users.search(None, start_index=3, count=2)
    assert userlist(mid) == userlist(page)[2:4] and mid.total_results == 7
    assert users.search(None, count=0).resources == []
    assert users.search(None, count=0).total_results == 7
    capped = env.service(max_results=2).users.search(None)
    assert len(capped.resources) == 2 and capped.total_results == 7
    one = users.search(Compare("userName", "eq", "jdoe"))
    assert userlist(one) == ["jdoe"] and one.total_results == 1
    ors = users.search(
        Or(
            Compare("userName", "sw", "a"),
            And(Compare("userName", "ew", "e"), Not(Compare("userName", "sw", "j"))),
        )
    )
    assert set(userlist(ors)) == {"admin", "asmith", "dlefevre"}
    assert userlist(users.search(parse('emails.value co "heracles.test" and userName sw "b"'))) == [
        "bmartin"
    ]


def test_search_by_id(env: Env) -> None:
    users = env.service().users
    rid = users.search(Compare("userName", "eq", "jdoe")).resources[0]["id"]
    assert userlist(users.search(Compare("id", "eq", rid))) == ["jdoe"]


def test_search_invalid_filter_and_sort(env: Env) -> None:
    users = env.service().users
    for path in ("active", "groups.value", "meta.created", "password"):
        e = err(users.search, Compare(path, "eq", "x"))
        assert (e.status, e.scim_type) == (400, "invalidFilter"), path
    e = err(users.search, None, sort_by="name.familyName")
    assert (e.status, e.scim_type) == (400, "invalidValue")
    e = err(users.search, None, sort_by="nothing")
    assert e.status == 400


def test_search_reports_active_and_lock(env: Env) -> None:
    users = env.service().users
    made = users.create(user_body(active=False))
    found = users.search(Compare("userName", "eq", "jsmith")).resources[0]
    assert found["id"] == made["id"] and found["active"] is False


# ------------------------------------------------------------------- ACL


def test_acl_create_is_refused_without_the_right(env: Env) -> None:
    e = err(env.service(HELPDESK).users.create, user_body())
    assert e.status == 403


def test_acl_read_scope_and_hidden_resources(env: Env) -> None:
    admin = env.service()
    target = admin.users.search(Compare("userName", "eq", "asmith")).resources[0]["id"]
    manager = env.service(LYON_MANAGER)
    assert err(manager.users.get, target).status == 404
    visible = userlist(manager.users.search(None))
    assert "asmith" not in visible and "cdupont" in visible
    assert manager.users.search(None).total_results == len(visible)


def test_acl_write_and_lock_rights(env: Env) -> None:
    admin = env.service()
    target = admin.users.search(Compare("userName", "eq", "asmith")).resources[0]["id"]
    desk = env.service(HELPDESK)
    assert desk.users.get(target)["userName"] == "asmith"
    assert err(desk.users.patch, target, [PatchOp("replace", "displayName", "X")]).status == 403
    assert desk.users.patch(target, [PatchOp("replace", "active", False)])["active"] is False
    assert err(desk.users.delete, target).status == 403
    manager = env.service(LYON_MANAGER)
    lyon = manager.users.search(Compare("userName", "eq", "dlefevre")).resources[0]["id"]
    assert (
        manager.users.patch(lyon, [PatchOp("replace", "displayName", "DL")])["displayName"] == "DL"
    )
    assert err(manager.users.patch, lyon, [PatchOp("replace", "userName", "../x")]).status == 400


def test_acl_filter_on_unreadable_attribute_is_refused(env: Env) -> None:
    manager = env.service(LYON_MANAGER)
    e = err(manager.users.search, Compare("userName", "eq", "x"), sort_by="id")
    assert e.status == 400


# ---------------------------------------------------------------- groups


def ids_of(env: Env, *names: str) -> list[str]:
    users = env.service().users
    return [users.search(Compare("userName", "eq", n)).resources[0]["id"] for n in names]


def test_group_lifecycle(env: Env) -> None:
    groups = env.service().groups
    a, b, c = ids_of(env, "jdoe", "asmith", "bmartin")
    made = groups.create(
        {"schemas": [GROUP_SCHEMA], "displayName": "team", "members": [{"value": a}]}
    )
    assert made["displayName"] == "team"
    assert made["meta"]["resourceType"] == "Group"
    assert made["meta"]["location"] == f"{BASE_URL}/Groups/{made['id']}"
    assert made["members"] == [
        {"value": a, "$ref": f"{BASE_URL}/Users/{a}", "display": "jdoe", "type": "User"}
    ]
    gid = made["id"]
    out = groups.patch(gid, [PatchOp("add", "members", [{"value": b}, {"value": c}])])
    assert {m["value"] for m in out["members"]} == {a, b, c}
    out = groups.patch(gid, [PatchOp("remove", f'members[value eq "{a}"]')])
    assert {m["value"] for m in out["members"]} == {b, c}
    out = groups.patch(gid, [PatchOp("replace", "displayName", "team2")])
    assert out["displayName"] == "team2" and out["id"] == gid
    out = groups.replace(gid, {"displayName": "team2", "members": [{"value": c}]})
    assert [m["value"] for m in out["members"]] == [c]
    groups.delete(gid)
    assert err(groups.get, gid).status == 404
    assert find_archives(env.directory, "group", {"cn": "team2"})


def test_group_member_patch_is_one_modify(env: Env) -> None:
    svc = env.service()
    created = [svc.users.create(user_body(f"u{i}"))["id"] for i in range(30)]
    g = svc.groups.create({"displayName": "big", "members": [{"value": created[0]}]})
    seen: list[tuple[str, str]] = []
    real = env.directory.modify

    def spy(target: str, changes: Any) -> None:
        if "ou=audit," not in target:  # not the audit log
            seen.extend((target, c.attr) for c in changes)
        real(target, changes)

    env.directory.modify = spy  # type: ignore[method-assign]
    out = svc.groups.patch(
        g["id"], [PatchOp("add", "members", [{"value": i} for i in created[1:]])]
    )
    assert len(out["members"]) == 30
    assert [a for _t, a in seen] == ["member"]


def test_group_member_errors(env: Env) -> None:
    groups = env.service().groups
    (a,) = ids_of(env, "jdoe")
    e = err(groups.create, {"displayName": "g1"})
    assert (e.status, e.scim_type) == (400, "invalidValue")
    e = err(groups.create, {"displayName": "g1", "members": []})
    assert e.status == 400
    e = err(groups.create, {"displayName": "g1", "members": [{"value": "nope"}]})
    assert (e.status, e.scim_type) == (400, "invalidValue")
    admins = groups.search(Compare("displayName", "eq", "admins")).resources[0]
    e = err(groups.create, {"displayName": "g2", "members": [{"value": admins["id"]}]})
    assert e.status == 400  # a group is not a user
    g = groups.create({"displayName": "g3", "members": [{"value": a}]})
    e = err(groups.patch, g["id"], [PatchOp("remove", f'members[value eq "{a}"]')])
    assert (e.status, e.scim_type) == (400, "invalidValue")
    e = err(groups.create, {"displayName": "g3", "members": [{"value": a}]})
    assert (e.status, e.scim_type) == (409, "uniqueness")


def test_group_search(env: Env) -> None:
    groups = env.service().groups
    page = groups.search(None)
    assert [r["displayName"] for r in page.resources] == ["admins", "lyon-staff"]
    assert page.total_results == 2
    one = groups.search(Compare("displayName", "co", "lyon"), sort_by="displayName")
    assert [r["displayName"] for r in one.resources] == ["lyon-staff"]
    assert err(groups.search, Compare("members.value", "eq", "x")).status == 400
    desk = env.service(HELPDESK).groups
    assert desk.search(None).total_results == 0  # no group right
    assert err(desk.get, page.resources[0]["id"]).status == 404


# ---------------------------------------------------------------- rights on related entries


def test_own_password_is_refused_through_scim(env: Env) -> None:
    users = env.service(ADMIN_DN).users
    me = users.search(Compare("userName", "eq", "admin")).resources[0]["id"]
    assert err(users.patch, me, [PatchOp("replace", "password", "Another-pass-1")]).status == 403
    other = users.create(user_body("pwtarget"))["id"]
    users.patch(other, [PatchOp("replace", "password", "Another-pass-1")])


def test_members_the_caller_cannot_see_are_hidden_and_kept(env: Env) -> None:
    lyon_staff = f"cn=lyon-staff,ou=groups,ou=lyon,{BASE}"
    env.directory.modify(lyon_staff, [Modification("add", "member", [ASMITH.encode()])])
    manager = env.service(LYON_MANAGER)
    (group,) = manager.groups.search(Compare("displayName", "eq", "lyon-staff")).resources
    full = manager.groups.get(group["id"])
    shown = {m["display"] for m in full["members"]}
    assert "asmith" not in shown and "cdupont" in shown
    dlefevre = next(m["value"] for m in full["members"] if m["display"] == "dlefevre")
    manager.groups.patch(group["id"], [PatchOp("remove", f'members[value eq "{dlefevre}"]')])
    entry = env.directory.get(lyon_staff, ["member"])
    assert entry is not None
    members = {m.lower() for m in entry.texts("member")}
    assert ASMITH.lower() in members  # hidden member kept
    assert not any("dlefevre" in m for m in members)


def test_ids_of_unreadable_users_are_unknown(env: Env) -> None:
    admin = env.service(ADMIN_DN)
    paris = admin.users.search(Compare("userName", "eq", "asmith")).resources[0]["id"]
    manager = env.service(LYON_MANAGER)
    (group,) = manager.groups.search(Compare("displayName", "eq", "lyon-staff")).resources
    add = [PatchOp("add", "members", [{"value": paris}])]
    assert err(manager.groups.patch, group["id"], add).status == 400
    lyon = manager.users.search(Compare("userName", "eq", "dlefevre")).resources[0]["id"]
    boss = [PatchOp("replace", f"{ENTERPRISE_USER_SCHEMA}:manager", {"value": paris})]
    assert err(manager.users.patch, lyon, boss).status == 400


def test_common_email_filters(env: Env) -> None:
    users = env.service().users
    users.create(user_body("mailfilter"))
    for text in (
        'emails.value eq "mailfilter@example.test"',
        'emails[type eq "work"].value eq "mailfilter@example.test"',
        'emails[value eq "mailfilter@example.test"]',
    ):
        try:
            found = users.search(parse(text)).resources
        except ScimError as exc:
            pytest.fail(f"{text}: {exc.detail}")
        assert [r["userName"] for r in found] == ["mailfilter"], text
