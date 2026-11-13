from __future__ import annotations

import base64

import pytest

from heracles import demo
from heracles.acl import FULL_RIGHTS, NO_RIGHTS, Rights, admin
from heracles.acl.model import AclAssignment
from heracles.acl.parser import parse_assignment
from heracles.ldap.client import NoSuchObjectError
from heracles.ldap.memory import MemoryDirectory

BASE = demo.BASE
ROLE = f"cn=helpdesk,ou=aclroles,{BASE}"
PARIS = f"ou=paris,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_role_template_json_roundtrip_keeps_spelling() -> None:
    # unusual but valid spellings must survive an unchanged round trip
    raw = "3:user/user;wr#sn;rw,unknown/key;r,all;"
    item = admin.template_to_json(raw)
    assert [b["object"] for b in item["blocks"]] == ["user/user", "unknown/key", "all"]
    assert admin.template_from_json(item) == raw


def test_role_template_changed_structure_is_reserialised() -> None:
    item = admin.template_to_json("0:user/user;r")
    item["blocks"][0]["rights"] = "rw"
    item["blocks"].append({"object": "ogroup/ogroup", "rights": "r", "attributes": []})
    assert admin.template_from_json(item) == "0:user/user;rw,ogroup/ogroup;r"


@pytest.mark.parametrize(
    ("key", "value"),
    [("rights", "rz"), ("object", ""), ("object", "a,b")],
)
def test_role_template_validation(key: str, value: str) -> None:
    item = admin.template_to_json("0:user/user;r")
    item["blocks"][0][key] = value
    with pytest.raises(admin.AclAdminError):
        admin.template_from_json(item)


def test_role_template_attribute_name_validation() -> None:
    item = admin.template_to_json("0:user/user;r")
    item["blocks"][0]["attributes"].append({"name": "x#y", "rights": "r"})
    with pytest.raises(admin.AclAdminError):
        admin.template_from_json(item)


def test_ignored_template_is_kept_verbatim() -> None:
    item = admin.template_to_json("garbage")
    assert item["ignored"] is True
    assert admin.template_from_json(item) == "garbage"


def test_role_lifecycle(directory: MemoryDirectory) -> None:
    roles = admin.list_roles(directory)
    assert {r.cn for r in roles} >= {"helpdesk", "full-admin"}
    container = admin.role_container(directory, f"ou=paris,{BASE}", None)
    dn = admin.create_role(
        directory,
        container=container,
        cn="paris-ops",
        description="Paris ops",
        templates=[{"index": 0, "blocks": [{"object": "user/user", "rights": "r"}]}],
    )
    assert dn == f"cn=paris-ops,ou=aclroles,ou=paris,{BASE}"
    with pytest.raises(admin.AclAdminError):
        admin.create_role(
            directory,
            container=container,
            cn="paris-ops",
            description="",
            templates=[{"blocks": []}],
        )
    updated = admin.update_role(directory, dn, description="", templates=None)
    assert updated.description == ""
    admin.delete_role(directory, dn)
    assert admin.get_role(directory, dn) is None


def test_delete_role_in_use_is_refused(directory: MemoryDirectory) -> None:
    with pytest.raises(admin.RoleInUseError):
        admin.delete_role(directory, ROLE)
    assert admin.get_role(directory, ROLE) is not None
    admin.delete_role(directory, ROLE, force=True)
    assert admin.get_role(directory, ROLE) is None


def test_list_assignments_and_members(directory: MemoryDirectory) -> None:
    items = admin.list_assignments(directory, BASE)
    assert [i["index"] for i in items] == [0, 1, 2]
    assert items[0]["members"][0]["kind"] == "group"
    assert items[1]["members"][0]["kind"] == "user"
    assert items[2]["members"] == [{"dn": "*", "kind": "everyone"}]
    assert items[1]["role_name"] == "helpdesk"


def test_set_assignments_roundtrip_and_reorder(directory: MemoryDirectory) -> None:
    before = directory.get(BASE)
    assert before is not None
    stored = before.texts("hrcAclEntry")
    items = admin.list_assignments(directory, BASE)
    admin.set_assignments(directory, BASE, items)  # unchanged
    after = directory.get(BASE)
    assert after is not None and sorted(after.texts("hrcAclEntry")) == sorted(stored)

    reordered = admin.reorder(items, [2, 0, 1])
    result = admin.set_assignments(directory, BASE, reordered)
    assert [r["role_name"] for r in result] == ["self-service", "full-admin", "helpdesk"]


def test_set_assignments_adds_and_removes_class(directory: MemoryDirectory) -> None:
    new = {
        "index": 0,
        "scope": "base",
        "role": ROLE,
        "members": ["*"],
        "user_filter": "(uid=*)",
        "target_filter": None,
    }
    admin.set_assignments(directory, PARIS, [new])
    entry = directory.get(PARIS)
    assert entry is not None and entry.has_object_class("hrcAcl")
    parsed = parse_assignment(entry.texts("hrcAclEntry")[0])
    assert isinstance(parsed, AclAssignment)
    assert parsed.scope.value == "base"
    assert parsed.user_filter == "(uid=*)"
    admin.set_assignments(directory, PARIS, [])
    entry = directory.get(PARIS)
    assert entry is not None and not entry.has_object_class("hrcAcl")
    assert entry.get("hrcAclEntry") == []


def test_ignored_assignment_survives_and_can_be_removed(directory: MemoryDirectory) -> None:
    legacy_value = f"0:psub:{_b64(ROLE)}:{_b64('*')}"
    from heracles.ldap.client import Modification

    directory.modify(
        PARIS,
        [
            Modification("add", "objectClass", [b"hrcAcl"]),
            Modification("add", "hrcAclEntry", [legacy_value.encode()]),
        ],
    )
    items = admin.list_assignments(directory, PARIS)
    assert items[0]["ignored"] is True
    admin.set_assignments(directory, PARIS, items)
    entry = directory.get(PARIS)
    assert entry is not None and legacy_value in entry.texts("hrcAclEntry")
    admin.set_assignments(directory, PARIS, [])
    entry = directory.get(PARIS)
    assert entry is not None and entry.get("hrcAclEntry") == []


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"scope": "one"}, "scope"),
        ({"role": ""}, "role"),
        ({"members": []}, "members"),
        ({"user_filter": "uid=x"}, "user_filter"),
    ],
)
def test_assignment_validation(
    patch: dict[str, object], field: str, directory: MemoryDirectory
) -> None:
    item: dict[str, object] = {"index": 0, "scope": "subtree", "role": ROLE, "members": ["*"]}
    item.update(patch)
    with pytest.raises(admin.AclAdminError) as exc:
        admin.set_assignments(directory, BASE, [item])
    assert any(k.endswith(field) for k in exc.value.fields)


def test_unknown_entry(directory: MemoryDirectory) -> None:
    with pytest.raises(NoSuchObjectError):
        admin.list_assignments(directory, f"ou=nowhere,{BASE}")


def test_check_rights(directory: MemoryDirectory) -> None:
    bmartin = f"uid=bmartin,ou=people,ou=paris,{BASE}"
    helpdesk = f"uid=helpdesk,ou=people,{BASE}"
    report = admin.check_rights(
        directory,
        user_dn=helpdesk,
        target_dn=bmartin,
        object_key="user/user",
        attributes=["userPassword", "sn"],
    )
    assert report.attributes["userPassword"] == "rw"
    assert report.attributes["sn"] == "r"
    own = admin.check_rights(
        directory, user_dn=bmartin, target_dn=bmartin, object_key="user/user", attributes=["mobile"]
    )
    assert own.attributes["mobile"] == "rw"
    other = admin.check_rights(
        directory,
        user_dn=bmartin,
        target_dn=f"uid=admin,ou=people,{BASE}",
        object_key="user/user",
        attributes=["mobile"],
    )
    assert other.rights == ""


def test_grants_everything() -> None:
    assert admin.grants_everything(["0:all;cmdrw"])
    assert not admin.grants_everything(["0:all;sr", "0:user/user;cmdrw", "bad"])


def test_missing_role_rights_compares_with_the_callers_rights(directory: MemoryDirectory) -> None:
    role = f"cn=full-admin,ou=aclroles,{BASE}"

    def everything(dn: str, obj: str, attribute: str) -> Rights:
        del dn, obj, attribute
        return FULL_RIGHTS

    def nothing(dn: str, obj: str, attribute: str) -> Rights:
        del dn, obj, attribute
        return NO_RIGHTS

    assert admin.missing_role_rights(directory, role, at=BASE, permissions=everything) == []
    assert admin.missing_role_rights(directory, role, at=BASE, permissions=nothing) == ["all:rwcdm"]
    assert (
        admin.missing_role_rights(
            directory, f"cn=ghost,ou=aclroles,{BASE}", at=BASE, permissions=nothing
        )
        == []
    )


def test_new_assignments_ignore_position_and_removals() -> None:
    role = f"cn=helpdesk,ou=aclroles,{BASE}"
    value = f"0:subtree:{_b64(role)}:{_b64('*')}"
    moved = f"5:subtree:{_b64(role)}:{_b64('*')}"
    # a renumbering grants nothing new
    assert admin.new_assignments([value], [moved]) == []
    assert admin.new_assignments([value], []) == []
    assert [a.index for a in admin.new_assignments([], [moved])] == [5]
    # a change of member, scope or filter is a new assignment
    other = f"0:base:{_b64(role)}:{_b64('*')}"
    assert [a.index for a in admin.new_assignments([value], [other])] == [0]


def test_unheld_grants_checks_new_assignments_only(directory: MemoryDirectory) -> None:
    stored = [str(item["raw"]) for item in admin.list_assignments(directory, BASE)]
    role = f"cn=full-admin,ou=aclroles,{BASE}"
    added = f"9:subtree:{_b64(role)}:{_b64('*')}"

    def everything(dn: str, obj: str, attribute: str) -> Rights:
        del dn, obj, attribute
        return FULL_RIGHTS

    def nothing(dn: str, obj: str, attribute: str) -> Rights:
        del dn, obj, attribute
        return NO_RIGHTS

    assert admin.unheld_grants(directory, stored, stored, at=BASE, permissions=nothing) == []
    assert (
        admin.unheld_grants(directory, stored, [*stored, added], at=BASE, permissions=everything)
        == []
    )
    assert admin.unheld_grants(
        directory, stored, [*stored, added], at=BASE, permissions=nothing
    ) == ["all:rwcdm"]
