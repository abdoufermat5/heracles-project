from __future__ import annotations

import pytest

from heracles import demo
from heracles.core import setup_checks as sc
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory

BASE = demo.BASE


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


def _by_id(results: list[sc.CheckResult]) -> dict[str, sc.CheckResult]:
    return {r.id: r for r in results}


def test_demo_directory_report(directory: MemoryDirectory) -> None:
    results = _by_id(sc.run_checks(sc.context_for(directory)))
    assert set(results) == set(sc.CHECK_IDS)
    assert results["bind_write"].status == "ok"
    assert results["super_admin"].status == "ok"
    assert results["hidden_users"].status == "ok"
    assert results["users_tree"].status == "ok"
    assert results["groups_tree"].status == "ok"
    assert results["departments"].status == "ok"
    assert results["duplicate_ids"].status == "ok"
    # the demo has neither the marker on the base nor the default roles
    assert results["root_object"].status == "warning"
    assert results["default_roles"].status == "warning"
    assert len(results["default_roles"].dns) == 3


def test_missing_base_is_an_error() -> None:
    empty = MemoryDirectory("dc=none,dc=test")
    ctx = sc.context_for(empty)
    assert sc.check_root(ctx).status == "error"
    assert sc.check_bind_write(ctx).status == "error"


def test_root_fix(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory)
    outcome = sc.run_fix(ctx, "root_object")
    assert outcome.fixed == [BASE]
    assert sc.check_root(ctx).status == "ok"
    entry = directory.get(BASE)
    assert entry is not None
    assert entry.text("ou") == "heracles" and entry.text("description")


def test_default_roles_fix(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory)
    outcome = sc.run_fix(ctx, "default_roles", [f"cn=manager,ou=aclroles,{BASE}"])
    assert outcome.fixed == [f"cn=manager,ou=aclroles,{BASE}"]
    assert len(sc.check_default_roles(ctx).dns) == 2
    sc.run_fix(ctx, "default_roles")
    assert sc.check_default_roles(ctx).status == "ok"
    role = directory.get(f"cn=editownpwd,ou=aclroles,{BASE}")
    assert role is not None and role.texts("hrcAclTemplate") == ["0:user/user;s#userPassword;rw"]


def test_hidden_users(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory)
    ok = f"uid=ghost,ou=people,{BASE}"
    bad = f"uid=nosn,ou=people,{BASE}"
    directory.add(
        ok,
        {
            "objectClass": [b"posixAccount", b"person"],
            "uid": [b"ghost"],
            "cn": [b"Ghost"],
            "sn": [b"G"],
            "uidNumber": [b"1"],
            "gidNumber": [b"1"],
            "homeDirectory": [b"/h"],
        },
    )
    directory.add(
        bad, {"objectClass": [b"posixAccount"], "uid": [b"nosn"], "cn": [b"x"], "uidNumber": [b"2"]}
    )
    result = sc.check_hidden_users(ctx)
    assert result.status == "warning" and set(result.dns) == {ok, bad}
    outcome = sc.run_fix(ctx, "hidden_users")
    assert outcome.fixed == [ok]
    assert list(outcome.failed) == [bad]
    entry = directory.get(ok)
    assert entry is not None and entry.has_object_class("inetOrgPerson")


def test_super_admin_fix_and_create_admin(directory: MemoryDirectory) -> None:
    # remove the full-admin assignment: nobody is left
    directory.modify(
        BASE,
        [
            Modification("delete", "hrcAclEntry"),
            Modification("delete", "objectClass", [b"hrcAcl"]),
        ],
    )
    ctx = sc.context_for(directory)
    assert sc.check_super_admin(ctx).status == "error"
    with_bootstrap = sc.context_for(directory, [f"uid=admin,ou=people,{BASE}"])
    assert sc.check_super_admin(with_bootstrap).status == "warning"

    refused = sc.run_fix(ctx, "super_admin", options={"dn": f"uid=nobody,{BASE}"})
    assert refused.failed and not refused.fixed

    fixed = sc.run_fix(ctx, "super_admin", options={"dn": f"uid=jdoe,ou=people,{BASE}"})
    assert fixed.fixed == [f"uid=jdoe,ou=people,{BASE}"]
    assert sc.check_super_admin(ctx).status == "ok"

    dn = sc.create_admin_user(ctx, "root", password_hash="{SSHA}x")
    assert dn == f"uid=root,ou=people,{BASE}"
    entry = directory.get(dn)
    assert entry is not None and entry.has_object_class("inetOrgPerson")
    base_entry = directory.get(BASE)
    assert base_entry is not None and len(base_entry.texts("hrcAclEntry")) == 2


def test_misplaced_objects_and_move(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory)
    user = f"uid=stray,ou=lyon,{BASE}"
    group = f"cn=stray-group,ou=lyon,{BASE}"
    posix = f"cn=stray-posix,ou=lyon,{BASE}"
    directory.add(
        user,
        {"objectClass": [b"inetOrgPerson"], "uid": [b"stray"], "cn": [b"S"], "sn": [b"S"]},
    )
    directory.add(
        group,
        {"objectClass": [b"groupOfNames"], "cn": [b"stray-group"], "member": [user.encode()]},
    )
    directory.add(
        posix, {"objectClass": [b"posixGroup"], "cn": [b"stray-posix"], "gidNumber": [b"5"]}
    )
    assert sc.check_users_tree(ctx).dns == [user]
    assert sc.check_groups_tree(ctx).dns == [group]
    assert sc.check_posix_groups_tree(ctx).dns == [posix]

    outcome = sc.run_fix(ctx, "users_tree", [user])
    new_user = f"uid=stray,ou=people,ou=lyon,{BASE}"
    assert outcome.fixed == [new_user]
    assert sc.check_users_tree(ctx).status == "ok"
    moved_group = directory.get(group)
    assert moved_group is not None and moved_group.texts("member") == [new_user]  # reference kept
    sc.run_fix(ctx, "groups_tree")
    sc.run_fix(ctx, "posix_groups_tree")
    assert directory.get(f"cn=stray-group,ou=groups,ou=lyon,{BASE}") is not None
    assert sc.check_posix_groups_tree(ctx).status == "ok"


def test_unmarked_departments(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory)
    plain = f"ou=sales,{BASE}"
    directory.add(plain, {"objectClass": [b"organizationalUnit"], "ou": [b"sales"]})
    result = sc.check_departments(ctx)
    assert result.dns == [plain]
    sc.run_fix(ctx, "departments", [plain])
    entry = directory.get(plain)
    assert entry is not None and entry.has_object_class("hrcDepartment")
    assert entry.text("description") == "sales"
    assert sc.check_departments(ctx).status == "ok"


def test_duplicate_ids_report_only(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory)
    for uid in ("a", "b"):
        directory.add(
            f"uid={uid},ou=people,{BASE}",
            {
                "objectClass": [b"inetOrgPerson", b"posixAccount"],
                "uid": [uid.encode()],
                "cn": [b"x"],
                "sn": [b"x"],
                "uidNumber": [b"1000"],
                "gidNumber": [b"1000"],
                "homeDirectory": [b"/h"],
            },
        )
    result = sc.check_duplicate_ids(ctx)
    assert result.status == "warning" and not result.fixable and len(result.dns) == 2
    with pytest.raises(sc.UnknownCheckError):
        sc.run_fix(ctx, "duplicate_ids")
    with pytest.raises(sc.UnknownCheckError):
        sc.run_fix(ctx, "nope")
