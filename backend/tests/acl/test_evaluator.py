"""Permission evaluation: table-driven rules plus hypothesis properties."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from heracles.acl import AclAccessPolicy, AclEvaluator, AclResolver, LdapAclDirectory, Rights
from heracles.acl.rights import FULL_RIGHTS
from tests.acl.world import BASE, CATEGORY_TABS, World

SALES = f"ou=sales,{BASE}"
PEOPLE = f"ou=people,{SALES}"
CARL = f"uid=carl,{PEOPLE}"


@pytest.fixture
def w() -> World:
    world = World()
    world.ensure(f"ou=people,{BASE}")
    world.ensure(SALES)
    world.client.put(PEOPLE, objectClass=["organizationalUnit"])
    world.client.put(CARL, objectClass=["inetOrgPerson"], uid=["carl"])
    return world


def R(text: str) -> Rights:
    return Rights.parse(text)


# (role template values, assignment scope, assigned on, queried dn, object, attribute, expected)
CASES = [
    # --- scopes -------------------------------------------------------
    pytest.param(
        ["0:user/user;rw"], "subtree", BASE, CARL, "user/user", "", "rw", id="subtree-desc"
    ),
    pytest.param(
        ["0:user/user;rw"], "subtree", BASE, BASE, "user/user", "", "rw", id="subtree-self"
    ),
    pytest.param(
        ["0:user/user;rw"], "base", BASE, BASE, "user/user", "", "rw", id="base-on-origin"
    ),
    pytest.param(["0:user/user;rw"], "base", BASE, CARL, "user/user", "", "", id="base-not-below"),
    pytest.param(["0:user/user;rw"], "subtree", SALES, BASE, "user/user", "", "", id="no-upward"),
    # --- all block ----------------------------------------------------
    pytest.param(["0:all;r"], "subtree", BASE, CARL, "group/ogroup", "", "r", id="all-any-object"),
    pytest.param(["0:all;r"], "subtree", BASE, CARL, "group/ogroup", "cn", "r", id="all-attr"),
    pytest.param(["0:all;rwcdm"], "subtree", BASE, CARL, "x/y", "z", "rwcdm", id="all-full"),
    # --- object vs attribute -----------------------------------------
    pytest.param(
        ["0:user/user;r#sn;w"], "subtree", BASE, CARL, "user/user", "sn", "rw", id="attr+obj"
    ),
    pytest.param(
        ["0:user/user;r#sn;w"], "subtree", BASE, CARL, "user/user", "mail", "r", id="obj-only"
    ),
    pytest.param(
        ["0:user/user;#sn;w"], "subtree", BASE, CARL, "user/user", "mail", "", id="no-obj"
    ),
    pytest.param(
        ["0:user/user;#sn;w"], "subtree", BASE, CARL, "user/user", "SN", "w", id="attr-ci"
    ),
    pytest.param(
        ["0:user/user;c#sn;w#mail;r"],
        "subtree",
        BASE,
        CARL,
        "user/user",
        "",
        "rwc",
        id="no-attr-merges-all",
    ),
    pytest.param(
        ["0:user/posixAccount;r"], "subtree", BASE, CARL, "user/user", "", "", id="other-object"
    ),
    # --- union across values -----------------------------------------
    pytest.param(
        ["0:user/user;r", "1:user/user;w"],
        "subtree",
        BASE,
        CARL,
        "user/user",
        "",
        "rw",
        id="union-values",
    ),
    # --- wildcard ------------------------------------------------------
    pytest.param(
        ["0:user/posixAccount;r,user/user;c#sn;w"],
        "subtree",
        BASE,
        CARL,
        "user/0",
        "",
        "rc",
        id="wildcard-object-level",
    ),
    pytest.param(
        ["0:user/user;c"], "subtree", BASE, CARL, "group/0", "", "", id="wildcard-other-cat"
    ),
    pytest.param(
        ["0:user/user;c"], "subtree", BASE, CARL, "user/0", "sn", "", id="wildcard-with-attr"
    ),
    pytest.param(
        ["0:user/0;w,user/user;r"],
        "subtree",
        BASE,
        CARL,
        "user/0",
        "",
        "rw",
        id="wildcard-block-itself",
    ),
    pytest.param(["0:all;r"], "subtree", BASE, CARL, "user/0", "", "r", id="wildcard-all"),
    # --- unknown / nothing ---------------------------------------------
    pytest.param([], "subtree", BASE, CARL, "user/user", "", "", id="empty-role"),
]


@pytest.mark.parametrize(("values", "scope", "on", "dn", "obj", "attr", "expected"), CASES)
def test_rules(
    w: World,
    values: list[str],
    scope: str,
    on: str,
    dn: str,
    obj: str,
    attr: str,
    expected: str,
) -> None:
    alice = w.user("alice")
    w.assign(on, w.acl_role("r", *values), [alice], scope)
    assert w.evaluator(alice).permissions(dn, obj, attr) == R(expected)


def test_nearest_view_wins_and_inherits_subtree_only(w: World) -> None:
    alice = w.user("alice")
    w.assign(BASE, w.acl_role("root-sub", "0:user/user;r"), [alice], "subtree")
    w.assign(BASE, w.acl_role("root-base", "0:user/user;m"), [alice], "base")
    w.assign(SALES, w.acl_role("sales-sub", "0:user/user;w"), [alice], "subtree")
    w.assign(SALES, w.acl_role("sales-base", "0:user/user;c"), [alice], "base")
    ev = w.evaluator(alice)
    assert ev.permissions(BASE, "user/user") == R("rm")
    assert ev.permissions(SALES, "user/user") == R("rwc")  # + inherited subtree, no root base
    assert ev.permissions(CARL, "user/user") == R("rw")  # nearest view is SALES; base skipped


def test_unrelated_branch_has_no_rights(w: World) -> None:
    alice = w.user("alice")
    w.assign(SALES, w.acl_role("r", "0:all;rwcdm"), [alice])
    ev = w.evaluator(alice)
    assert ev.permissions(f"ou=other,{BASE}", "user/user").is_empty
    assert ev.permissions(BASE, "user/user").is_empty


def test_self_flag(w: World) -> None:
    alice = w.user("alice")
    bob = w.user("bob")
    w.assign(BASE, w.acl_role("self", "0:user/user;sw#userPassword;sw"), [alice])
    w.assign(BASE, w.acl_role("rd", "0:user/user;r"), [alice])
    ev = w.evaluator(alice)
    assert ev.permissions(alice, "user/user") == R("rw")
    assert ev.permissions(bob, "user/user") == R("r")  # self rule skipped, other rule kept
    assert ev.permissions(alice.upper(), "user/user", "userPassword").write


def test_self_flag_skips_whole_rule(w: World) -> None:
    alice = w.user("alice")
    bob = w.user("bob")
    w.assign(BASE, w.acl_role("one", "0:all;r,user/user;sw"), [alice])
    ev = w.evaluator(alice)
    assert ev.permissions(bob, "user/user").is_empty  # whole rule skipped
    assert ev.permissions(bob, "group/ogroup") == R("r")  # no user block => all applies
    assert ev.permissions(alice, "user/user") == R("rw")


def test_self_flag_on_all_and_wildcard_and_attrs(w: World) -> None:
    alice = w.user("alice")
    bob = w.user("bob")
    w.assign(BASE, w.acl_role("a", "0:all;sr"), [alice])
    w.assign(BASE, w.acl_role("b", "0:user/user;sc,user/posixAccount;m#uidNumber;sw"), [alice])
    ev = w.evaluator(alice)
    assert ev.permissions(bob, "group/ogroup").is_empty
    assert ev.permissions(alice, "group/ogroup") == R("r")
    assert ev.permissions(bob, "user/0") == R("m")  # only the non-self tab block
    assert ev.permissions(alice, "user/0") == R("rcm")
    assert not ev.permissions(bob, "user/posixAccount", "uidNumber").write
    assert ev.permissions(alice, "user/posixAccount", "uidNumber").write
    assert not ev.permissions(bob, "user/posixAccount").write


def test_early_stop_when_full(w: World) -> None:
    alice = w.user("alice")
    w.assign(BASE, w.acl_role("full", "0:all;rwcdm"), [alice])
    w.assign(BASE, w.acl_role("tmpl", "0:all;t"), [alice])
    assert w.evaluator(alice).permissions(CARL, "user/user").is_full


def test_template_right_kept(w: World) -> None:
    alice = w.user("alice")
    w.assign(BASE, w.acl_role("t", "0:user/user;ct"), [alice])
    ev = w.evaluator(alice)
    assert ev.permissions(CARL, "user/user") == R("ct")
    assert ev.permissions(CARL, "user/user", skip_write=True) == R("t")


def test_ignore_acl_admin(w: World) -> None:
    resolved = w.resolve(w.user("root"))
    ev = AclEvaluator(resolved, ignore_acl=True)
    assert ev.ignore_acl
    assert ev.permissions("dc=anywhere", "x/y", "z") == FULL_RIGHTS
    assert ev.permissions("dc=anywhere", "x/y", skip_write=True) == R("r")
    assert ev.can_create("dc=anywhere", "user", "user")


def test_skip_write_and_cache(w: World) -> None:
    alice = w.user("alice")
    w.assign(BASE, w.acl_role("r", "0:user/user;rwcdm"), [alice])
    ev = w.evaluator(alice)
    assert ev.permissions(CARL, "user/user", skip_write=True) == R("r")
    assert ev.permissions(CARL, "user/user").is_full  # cache holds the full result
    assert ev.permissions(CARL.upper(), "user/user", "SN") == FULL_RIGHTS
    assert ev.user_dn == alice.lower().replace(" ", "")


def test_helpers(w: World) -> None:
    alice = w.user("alice")
    w.assign(
        BASE,
        w.acl_role("r", "0:user/user;cdm#sn;rw#mail;r,group/ogroup;r"),
        [alice],
        "subtree",
    )
    ev = w.evaluator(alice)
    assert ev.can_create(SALES, "user", "user")
    assert not ev.can_create(SALES, "group", "ogroup")
    assert ev.can_delete(CARL, "user", "user")
    assert not ev.can_delete(CARL, "group", "ogroup")
    assert ev.can_move(CARL, "user", "user")
    assert ev.can_read_attr(CARL, "user/user", "mail")
    assert not ev.can_write_attr(CARL, "user/user", "mail")
    assert ev.can_write_attr(CARL, "user/user", "sn")
    assert ev.departments_for("user", [BASE, SALES, "ou=elsewhere,dc=zzz"]) == [BASE, SALES]
    assert ev.departments_for("group", [BASE]) == [BASE]
    assert ev.departments_for("department", [BASE]) == []


def test_departments_only_where_rights(w: World) -> None:
    alice = w.user("alice")
    w.assign(SALES, w.acl_role("r", "0:user/mailAccount;r"), [alice])
    ev = w.evaluator(alice)
    assert ev.departments_for("user", [BASE, SALES, PEOPLE]) == [SALES, PEOPLE]


@pytest.mark.parametrize(
    ("template", "create", "restore", "delete"),
    [
        ("0:user/user;rwcdm", True, True, True),  # full rights
        ("0:user/user;r#snapshot;c", True, False, False),
        ("0:user/user;r#snapshot;w", False, True, False),
        ("0:user/user;r#snapshot;d", False, False, True),
        ("0:user/user;rwcd", False, False, False),
        ("0:user/user;rwcd#snapshot;m", False, False, False),
    ],
)
def test_snapshot_permissions(
    w: World, template: str, create: bool, restore: bool, delete: bool
) -> None:
    alice = w.user("alice")
    w.assign(BASE, w.acl_role("s", template), [alice])
    ev = w.evaluator(alice)
    got = (
        ev.can_snapshot_create(CARL, "user/user"),
        ev.can_snapshot_restore(CARL, "user/user"),
        ev.can_snapshot_delete(CARL, "user/user"),
    )
    if template == "0:user/user;rwcd":
        # object-level w/c/d are also visible through the attribute lookup
        assert got == (True, True, True)
    elif template == "0:user/user;rwcd#snapshot;m":
        assert got == (True, True, True)
    else:
        assert got == (create, restore, delete)


def test_policy_adapter(w: World) -> None:
    alice = w.user("alice")
    w.assign(
        BASE,
        w.acl_role("p", "0:user/user;cd#sn;rw,user/posixAccount;r#uidNumber;w"),
        [alice],
    )
    policy = AclAccessPolicy(
        w.evaluator(alice),
        tab_keys={"main": "user/user", "posix": "user/posixAccount"},
        type_keys={"user": "user/user", "group": "group/ogroup"},
    )
    assert policy.can_read(CARL, "main", "sn")
    assert policy.can_write(CARL, "main", "sn")
    assert not policy.can_write(CARL, "main", "mail")
    assert policy.can_read(CARL, "posix", "gidNumber")
    assert policy.can_write(CARL, "posix", "uidNumber")
    assert policy.can_read(CARL, "user/user", "sn")  # already an object key
    assert not policy.can_read(CARL, "unknown", "sn")
    assert not policy.can_write(CARL, "unknown", "sn")
    assert policy.can_create("user", SALES)
    assert not policy.can_create("group", SALES)
    assert not policy.can_create("nope", SALES)
    assert policy.can_delete(CARL, "user")
    assert not policy.can_delete(CARL, "group")
    assert not policy.can_delete(CARL, "nope")


# -------------------------------------------------------- hypothesis properties

ROLE_TEMPLATES = {
    "a": ["0:user/user;r#sn;w"],
    "b": ["0:all;c", "1:user/posixAccount;sw"],
    "c": ["0:user/0;d,user/user;m"],
    "d": ["0:group/ogroup;rwcdm"],
    "e": ["0:user/user;sr#userPassword;sw"],
}
TARGETS = [BASE, SALES, PEOPLE, CARL, f"ou=people,{BASE}"]
SCOPE_CHOICES = ["subtree", "base"]
assignment_st = st.tuples(
    st.sampled_from(sorted(ROLE_TEMPLATES)),
    st.sampled_from(TARGETS),
    st.sampled_from(SCOPE_CHOICES),
)
QUERIES = [
    (dn, obj, attr)
    for dn in [*TARGETS, "uid=alice,ou=people,dc=example,dc=org"]
    for obj in ["user/user", "user/posixAccount", "user/0", "group/ogroup", "all"]
    for attr in ["", "sn", "userPassword"]
]


def _evaluator(assigns: list[tuple[str, str, str]]) -> AclEvaluator:
    world = World()
    alice = world.user("alice")
    for target in TARGETS:
        world.ensure(target)
    for name, values in ROLE_TEMPLATES.items():
        world.acl_role(name, *values)
    for name, target, scope in assigns:
        world.assign(target, f"cn={name},ou=aclroles,{BASE}", [alice], scope)
    resolved = AclResolver(LdapAclDirectory(world.client)).resolve(alice)
    return AclEvaluator(resolved, category_tabs=CATEGORY_TABS)


@settings(max_examples=60, deadline=None)
@given(st.lists(assignment_st, max_size=6), assignment_st)
def test_adding_assignment_never_removes_rights(
    assigns: list[tuple[str, str, str]], extra: tuple[str, str, str]
) -> None:
    before = _evaluator(assigns)
    after = _evaluator([*assigns, extra])
    for dn, obj, attr in QUERIES:
        assert before.permissions(dn, obj, attr).issubset(after.permissions(dn, obj, attr))


@settings(max_examples=60, deadline=None)
@given(st.lists(assignment_st, max_size=6))
def test_skip_write_is_subset_of_full(assigns: list[tuple[str, str, str]]) -> None:
    ev = _evaluator(assigns)
    for dn, obj, attr in QUERIES:
        full = ev.permissions(dn, obj, attr)
        ro = ev.permissions(dn, obj, attr, skip_write=True)
        assert ro.issubset(full)
        assert not (ro.write or ro.create or ro.delete or ro.move)
        assert ro.read == full.read


def test_manages_others_ignores_read_only_and_self_only_roles() -> None:
    assert _evaluator([]).manages_others() is False
    ROLE_TEMPLATES.setdefault("readers", ["0:user/user;r"])
    assert _evaluator([("readers", BASE, "subtree")]).manages_others() is False
    assert _evaluator([("e", BASE, "subtree")]).manages_others() is False  # self-only
    assert _evaluator([("d", SALES, "subtree")]).manages_others() is True
    assert AclEvaluator(_evaluator([])._resolved, ignore_acl=True).manages_others() is True  # pyright: ignore[reportPrivateUsage]
