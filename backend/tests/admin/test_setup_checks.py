from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from heracles import demo
from heracles.acl.model import AclAssignment
from heracles.acl.parser import parse_assignment
from heracles.core import setup_checks as sc
from heracles.ldap.client import DirectoryError, Modification
from heracles.ldap.memory import MemoryDirectory

BASE = demo.BASE

MESSAGE_KEY = re.compile(r"^(?P<check>[a-z_]+)\.(?P<outcome>[a-z_]+)$")

#: ``message_params`` every key of the demo report must carry.
REQUIRED_PARAMS: dict[str, set[str]] = {
    "root_object.unmarked": {"dn"},
    "bind_write.ok": set(),
    "transport.ok": set(),
    "hidden_users.ok": set(),
    "super_admin.ok": {"count"},
    "default_roles.missing": {"count", "roles"},
    "users_tree.ok": {"noun", "rdn"},
    "groups_tree.ok": {"noun", "rdn"},
    "posix_groups_tree.ok": {"noun", "rdn"},
    "departments.ok": set(),
    "duplicate_ids.ok": set(),
    "plugin_data.ok": set(),
}


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


def _by_id(results: list[sc.CheckResult]) -> dict[str, sc.CheckResult]:
    return {r.id: r for r in results}


def _assert_message(result: sc.CheckResult, params: set[str]) -> None:
    match = MESSAGE_KEY.match(result.message_key)
    assert match is not None and match["check"] == result.id
    assert match["outcome"] in sc.MESSAGE_OUTCOMES
    assert set(result.message_params) == params
    for value in result.message_params.values():
        if isinstance(value, list):
            values = cast("list[object]", value)
            assert all(isinstance(v, str) for v in values)
        else:
            assert isinstance(value, int | str)


def test_documented_message_keys_use_the_outcome_vocabulary() -> None:
    for key in sc.CHECK_MESSAGE_PARAMS:
        match = MESSAGE_KEY.match(key)
        assert match is not None and match["outcome"] in sc.MESSAGE_OUTCOMES


def test_every_check_reports_a_translatable_message(directory: MemoryDirectory) -> None:
    results = sc.run_checks(sc.context_for(directory))
    assert [r.id for r in results] == list(sc.CHECK_IDS)
    for result in results:
        _assert_message(result, REQUIRED_PARAMS[result.message_key])
        assert result.message_key in sc.CHECK_MESSAGE_PARAMS
        assert set(sc.CHECK_MESSAGE_PARAMS[result.message_key]) == set(result.message_params)
        assert result.message and result.to_json()["message"] == result.message
    by_id = _by_id(results)
    assert by_id["super_admin"].message_key == "super_admin.ok"
    assert by_id["super_admin"].message_params["count"] >= 1
    assert by_id["root_object"].message_key == "root_object.unmarked"


def test_missing_entries_report_a_key() -> None:
    empty = MemoryDirectory("dc=none,dc=test")
    ctx = sc.context_for(empty)
    for result in (sc.check_root(ctx), sc.check_bind_write(ctx)):
        assert result.message_key == f"{result.id}.missing"
        assert result.message_params == {"dn": ctx.base}


def test_unwritable_base_entry_reports_a_key(
    directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = sc.context_for(directory)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise DirectoryError("unwilling to perform operation")

    monkeypatch.setattr(ctx.directory, "modify", refuse)
    result = sc.check_bind_write(ctx)
    assert result.status == "error"
    assert (result.message_key, result.message_params) == ("bind_write.unwritable", {"dn": BASE})


def test_plaintext_transport_reports_its_uris(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory, plaintext_uris=["ldap://ldap.test"])
    (result,) = sc.run_checks(ctx, ["transport"])
    assert result.message_key == "transport.plaintext"
    assert result.message_params == {"uris": ["ldap://ldap.test"]}


def test_tree_checks_report_a_misplaced_key(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory)
    user = f"uid=stray,ou=lyon,{BASE}"
    directory.add(
        user, {"objectClass": [b"inetOrgPerson"], "uid": [b"stray"], "cn": [b"S"], "sn": [b"S"]}
    )
    directory.add(
        f"cn=stray-group,ou=lyon,{BASE}",
        {"objectClass": [b"groupOfNames"], "cn": [b"stray-group"], "member": [user.encode()]},
    )
    directory.add(
        f"cn=stray-posix,ou=lyon,{BASE}",
        {"objectClass": [b"posixGroup"], "cn": [b"stray-posix"], "gidNumber": [b"5"]},
    )
    expected = {
        "users_tree": ("user", "ou=people"),
        "groups_tree": ("group", "ou=groups"),
        "posix_groups_tree": ("POSIX group", "ou=groups"),
    }
    for result in (
        sc.check_users_tree(ctx),
        sc.check_groups_tree(ctx),
        sc.check_posix_groups_tree(ctx),
    ):
        noun, rdn = expected[result.id]
        assert result.message_key == f"{result.id}.misplaced"
        assert result.message_params == {"count": 1, "noun": noun, "rdn": rdn}


def test_a_failing_check_reports_its_error_type(
    directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_ctx: sc.CheckContext) -> sc.CheckResult:
        raise DirectoryError("nope")

    monkeypatch.setattr(sc, "CHECKS", (("root_object", boom, None),))
    (result,) = sc.run_checks(sc.context_for(directory))
    assert (result.id, result.status) == ("root_object", "error")
    assert result.message_key == "root_object.failed"
    assert result.message_params == {"error": "DirectoryError"}


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
    fixed = sc.check_root(ctx)
    assert fixed.status == "ok"
    assert (fixed.message_key, fixed.message_params) == ("root_object.ok", {})
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


def test_move_rewrites_acl_assignments_that_name_the_moved_entry(
    directory: MemoryDirectory,
) -> None:
    ctx = sc.context_for(directory)
    stray = f"cn=stray-group,ou=lyon,{BASE}"
    directory.add(stray, {"objectClass": [b"groupOfNames"], "cn": [b"stray-group"], "member": []})
    role = sc._ensure_role(ctx, *sc.SUPER_ADMIN_ROLE)  # pyright: ignore[reportPrivateUsage]
    sc._add_base_assignment(ctx, role, stray)  # pyright: ignore[reportPrivateUsage]

    outcome = sc.run_fix(ctx, "groups_tree", [stray])
    moved = f"cn=stray-group,ou=groups,ou=lyon,{BASE}"
    assert outcome.fixed == [moved]
    base_entry = directory.get(BASE)
    assert base_entry is not None
    members = [
        m
        for value in base_entry.texts("hrcAclEntry")
        if isinstance(parsed := parse_assignment(value), AclAssignment)
        for m in parsed.members
    ]
    assert moved in members and stray not in members


def test_super_admin_fix_reports_a_malformed_dn_instead_of_raising(
    directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heracles.ldap.client import DirectoryError

    def refuse(_dn: str, _attrs: object = None) -> None:
        raise DirectoryError("Invalid DN syntax")

    ctx = sc.context_for(directory)
    monkeypatch.setattr(directory, "get", refuse)
    outcome = sc.run_fix(ctx, "super_admin", options={"dn": "not a dn"})
    assert outcome.failed == {"not a dn": "Choose an existing user."} and not outcome.fixed


def test_plaintext_ldap_is_a_warning(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory, plaintext_uris=["ldap://ldap.test"])
    result = sc.run_checks(ctx, ["transport"])[0]
    assert result.status == "warning"
    assert "ldap://ldap.test" in result.message
    assert sc.run_checks(sc.context_for(directory), ["transport"])[0].status == "ok"


def test_plaintext_uris_ignore_starttls_and_tls() -> None:
    from heracles.ldap.config import DirectoryConfig

    plain = DirectoryConfig(id="main", base_dn=BASE, uri="ldap://ldap.test ldaps://secure.test")
    assert sc.plaintext_uris(plain) == ["ldap://ldap.test"]
    assert sc.plaintext_uris(plain.model_copy(update={"starttls": True})) == []
    assert (
        sc.plaintext_uris(DirectoryConfig(id="main", base_dn=BASE, uri="ldaps://secure.test")) == []
    )
    assert sc.insecure_uris(plain) == []  # not a directory client


def test_startup_warns_about_plaintext_ldap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from structlog.testing import capture_logs

    from heracles import server
    from heracles.ldap import pyldap
    from heracles.ldap.config import DirectoryConfig

    def client(config: DirectoryConfig) -> SimpleNamespace:
        return SimpleNamespace(config=config)

    monkeypatch.setattr(pyldap, "PyLdapDirectory", client)
    path = tmp_path / "heracles.yaml"
    path.write_text(
        "directories:\n  - id: main\n    uri: ldap://ldap.test\n    base_dn: dc=test\n",
        encoding="utf-8",
    )
    with capture_logs() as logs:
        server.load_config(path)
    assert any(entry["event"] == "directory_plaintext_ldap" for entry in logs)
