"""Resolution tests: members, filters, targets, views."""

from __future__ import annotations

import pytest

from heracles.acl import AclResolver, AssignmentEntry, Rights, escape_filter_value
from heracles.acl.resolver import ancestors, expand_target_filter
from tests.acl.world import BASE, World, b64

SALES = f"ou=sales,{BASE}"
BOB_SALES = f"uid=bob,ou=people,{SALES}"


@pytest.fixture
def w() -> World:
    world = World()
    world.ensure(f"ou=people,{BASE}")
    world.ensure(SALES)
    return world


def perms(w: World, user: str, dn: str, obj: str = "user/user", attr: str = "") -> Rights:
    return w.evaluator(user).permissions(dn, obj, attr)


# ------------------------------------------------------------- member kinds


def test_member_user_group_posix_role_everyone(w: World) -> None:
    alice = w.user("alice")
    stranger = w.user("stranger")
    role = w.acl_role("readers", "0:user/user;r")
    group = w.group("g1", [alice])
    posix = w.posix_group("pg", ["alice"])
    occupation = w.occupation("ops", [alice])

    for members in ([alice], [group], [occupation], ["*"]):
        world = World()
        world.user("alice")
        world.user("stranger")
        world.group("g1", [alice])
        world.occupation("ops", [alice])
        r = world.acl_role("readers", "0:user/user;r")
        world.assign(BASE, r, members)
        assert world.evaluator(alice).permissions(BOB_SALES, "user/user").read
    w.assign(BASE, role, [posix])
    ev = w.evaluator(alice, uid="alice")
    assert ev.permissions(BOB_SALES, "user/user").read
    # posix membership needs the uid
    assert not w.evaluator(alice).permissions(BOB_SALES, "user/user").read
    assert not w.evaluator(stranger, uid="stranger").permissions(BOB_SALES, "user/user").read


def test_member_dn_compare_is_case_insensitive(w: World) -> None:
    alice = w.user("alice")
    role = w.acl_role("readers", "0:user/user;r")
    w.assign(BASE, role, ["UID=Alice, OU=People,DC=Example,DC=Org"])
    assert perms(w, alice, BASE).read


def test_unrelated_member_gets_nothing(w: World) -> None:
    alice, bob = w.user("alice"), w.user("bob")
    role = w.acl_role("readers", "0:user/user;r")
    w.assign(BASE, role, [bob])
    assert perms(w, alice, BASE).is_empty


def test_missing_role_and_empty_members(w: World) -> None:
    alice = w.user("alice")
    w.assign(BASE, f"cn=ghost,ou=aclroles,{BASE}", ["*"])
    w.assign(BASE, w.acl_role("empty"), [])
    assert perms(w, alice, BASE).is_empty


# ---------------------------------------------------------------- filters


def test_user_filter(w: World) -> None:
    alice = w.user("alice", title=["admin"])
    bob = w.user("bob", title=["intern"])
    role = w.acl_role("readers", "0:user/user;r")
    w.assign(BASE, role, ["*"], userfilter="(title=admin)")
    assert perms(w, alice, BASE).read
    assert not perms(w, bob, BASE).read


def test_directory_errors_deny(w: World) -> None:
    ghost = f"uid=ghost,ou=people,{BASE}"  # not in the directory
    role = w.acl_role("readers", "0:user/user;r")
    w.assign(BASE, role, ["*"], userfilter="(uid=ghost)")
    assert perms(w, ghost, BASE).is_empty


def test_target_filter_with_placeholder(w: World) -> None:
    alice = w.user("alice", ou=f"ou=people,{SALES}", departmentNumber=["42"])
    w.client.put(f"cn=a,{SALES}", objectClass=["x"], departmentNumber=["42"])
    w.client.put(f"cn=b,{SALES}", objectClass=["x"], departmentNumber=["7"])
    role = w.acl_role("rw", "0:user/user;rw")
    w.assign(SALES, role, ["*"], targetfilter="(departmentNumber=%departmentNumber%)")
    ev = w.evaluator(alice, attrs={"departmentNumber": ["42"]})
    assert ev.permissions(f"cn=a,{SALES}", "user/user").write
    assert not ev.permissions(f"cn=b,{SALES}", "user/user").write
    # the assignment applies to the matched entries, not to the entry carrying it
    assert not ev.permissions(SALES, "user/user").write


def test_target_filter_placeholder_is_escaped(w: World) -> None:
    alice = w.user("alice")
    w.client.put(f"cn=a,{SALES}", objectClass=["x"], departmentNumber=["42"])
    role = w.acl_role("rw", "0:user/user;rw")
    w.assign(SALES, role, ["*"], targetfilter="(departmentNumber=%departmentNumber%)")
    ev = w.evaluator(alice, attrs={"departmentNumber": ["*"]})
    assert not ev.permissions(f"cn=a,{SALES}", "user/user").write
    ev = w.evaluator(alice, attrs={"departmentNumber": ["4)(cn=*"]})
    assert not ev.permissions(f"cn=a,{SALES}", "user/user").write


def test_target_filter_missing_attribute_applies_to_nothing(w: World) -> None:
    alice = w.user("alice")
    w.client.put(f"cn=a,{SALES}", objectClass=["x"], departmentNumber=["42"])
    role = w.acl_role("rw", "0:user/user;rw")
    w.assign(SALES, role, ["*"], targetfilter="(departmentNumber=%departmentNumber%)")
    resolved = w.resolve(alice)
    assert resolved.rules == {}


def test_target_filter_multivalued_and_dn_placeholder(w: World) -> None:
    alice = w.user("alice")
    w.client.put(f"cn=a,{SALES}", objectClass=["x"], departmentNumber=["1"])
    w.client.put(f"cn=b,{SALES}", objectClass=["x"], departmentNumber=["2"])
    w.client.put(f"cn=c,{SALES}", objectClass=["x"], departmentNumber=["3"])
    role = w.acl_role("rw", "0:user/user;r")
    w.assign(SALES, role, ["*"], targetfilter="(departmentNumber=%departmentnumber%)")
    ev = w.evaluator(alice, attrs={"departmentNumber": ["1", "2"]})
    assert ev.permissions(f"cn=a,{SALES}", "user/user").read
    assert ev.permissions(f"cn=b,{SALES}", "user/user").read
    assert not ev.permissions(f"cn=c,{SALES}", "user/user").read
    w2 = World()
    me = w2.user("me")
    w2.assign(BASE, w2.acl_role("r", "0:user/user;r"), ["*"], targetfilter="(member=%dn%)")
    w2.client.put(f"cn=g,{BASE}", objectClass=["groupOfNames"], member=[me])
    assert w2.evaluator(me).permissions(f"cn=g,{BASE}", "user/user").read


def test_target_limit_overflow_warns(w: World) -> None:
    alice = w.user("alice")
    for i in range(5):
        w.client.put(f"cn=t{i},{SALES}", objectClass=["x"], flag=["yes"])
    role = w.acl_role("rw", "0:user/user;r")
    w.assign(SALES, role, ["*"], targetfilter="(flag=yes)")
    resolved = w.resolve(alice, limit=3)
    assert len(resolved.rules) == 3
    assert [x.code for x in resolved.warnings] == ["target_limit"]
    assert resolved.warnings[0].dn == SALES
    ok = w.resolve(alice, limit=5)
    assert len(ok.rules) == 5 and not ok.warnings


def test_ignored_values_become_warnings(w: World) -> None:
    alice = w.user("alice")
    role = w.acl_role("bad", "garbage", "0:user/user;r")
    w.add_value(BASE, f"0:one:{b64(role)}:{b64('*')}")
    w.assign(BASE, role, ["*"])
    resolved = w.resolve(alice)
    codes = sorted(x.code for x in resolved.warnings)
    assert codes == ["ignored_assignment", "ignored_role_value"]
    assert resolved.nearest_view(BASE) is not None  # the valid parts still apply


# ------------------------------------------------------------------ views


def test_views_scopes_and_ordering(w: World) -> None:
    alice = w.user("alice")
    sub = w.acl_role("sub", "0:user/user;r")
    base = w.acl_role("base", "0:user/user;w")
    w.assign(BASE, sub, ["*"], "subtree")
    w.assign(BASE, base, ["*"], "base")
    w.assign(SALES, base, ["*"], "base")
    resolved = w.resolve(alice)
    assert resolved.targets_by_depth == ["dc=example,dc=org", "ou=sales,dc=example,dc=org"]
    root_view = resolved.views["dc=example,dc=org"]
    assert [r.scope.value for r in root_view] == ["subtree", "base"]
    sales_view = resolved.views["ou=sales,dc=example,dc=org"]
    # own base rule + inherited subtree rule of the base; not the base-scope one
    assert [(r.origin, r.scope.value) for r in sales_view] == [
        ("ou=sales,dc=example,dc=org", "base"),
        ("dc=example,dc=org", "subtree"),
    ]
    assert resolved.nearest_view("uid=x,ou=none,dc=other") is None


# ------------------------------------------------------------ small helpers


def test_helpers() -> None:
    assert escape_filter_value("a*(b)\\\x00") == "a\\2a\\28b\\29\\5c\\00"
    assert list(ancestors("UID=a, DC=x,dc=y")) == ["uid=a,dc=x,dc=y", "dc=x,dc=y", "dc=y"]
    assert expand_target_filter("(a=1)", {}) == ["(a=1)"]
    assert expand_target_filter("(a=%X%)(b=%x%)", {"x": ["1", "2"]}) == [
        "(a=1)(b=1)",
        "(a=2)(b=2)",
    ]
    assert expand_target_filter("(a=%x%)", {}) == []


def test_resolver_with_pure_fake_directory() -> None:
    class Fake:
        def groups_of_user(self, user_dn: str) -> list[str]:
            return ["cn=g,dc=x"]

        def posix_groups_by_uid(self, uid: str) -> list[str]:
            return []

        def roles_of_user(self, user_dn: str) -> list[str]:
            return []

        def assignment_entries(self) -> list[AssignmentEntry]:
            return [
                AssignmentEntry("dc=x", [f"0:subtree:{b64('cn=role,dc=x')}:{b64('CN=G,DC=X')}"])
            ]

        def role_templates(self, role_dn: str) -> list[str]:
            return ["0:all;r"]

        def user_matches_filter(self, user_dn: str, filterstr: str) -> bool:
            return True

        def search_targets(self, base_dn: str, filterstr: str, limit: int) -> list[str]:
            return []

    resolved = AclResolver(Fake()).resolve("uid=u,dc=x")
    assert "dc=x" in resolved.views
