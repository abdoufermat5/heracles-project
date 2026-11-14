"""Role and assignment values are refused before they reach the directory."""

from __future__ import annotations

import pytest

from heracles import demo
from heracles.acl import admin
from heracles.ldap.memory import MemoryDirectory

BASE = demo.BASE
ROLE = f"cn=helpdesk,ou=aclroles,{BASE}"
PARIS = f"ou=paris,{BASE}"
USER = f"uid=bmartin,ou=people,{PARIS}"
TEMPLATES = [{"index": 0, "blocks": [{"object": "user/user", "rights": "r"}]}]


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


def _create(directory: MemoryDirectory, cn: str, description: str = "") -> str:
    return admin.create_role(
        directory,
        container=admin.role_container(directory, PARIS, None),
        cn=cn,
        description=description,
        templates=TEMPLATES,
    )


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "a,b",
        "a#b",
        "a;b",
        "a:b",
        "a+b",
        "a=b",
        'a"b',
        "a<b",
        "a>b",
        "a\\b",
        "a\nb",
        "x" * 65,
    ],
)
def test_role_name_is_refused(directory: MemoryDirectory, name: str) -> None:
    with pytest.raises(admin.AclAdminError) as exc:
        _create(directory, name)
    assert list(exc.value.fields) == ["cn"]
    assert admin.list_roles(directory, f"ou=aclroles,{PARIS}") == []


@pytest.mark.parametrize("name", ["team-lead", "Équipe Paris", "ops (night)", "x" * 64])
def test_role_name_is_accepted(directory: MemoryDirectory, name: str) -> None:
    assert admin.check_role_name(name) is None
    assert admin.get_role(directory, _create(directory, name)) is not None


def test_role_description_is_bounded(directory: MemoryDirectory) -> None:
    with pytest.raises(admin.AclAdminError) as exc:
        _create(directory, "ok-name", "d" * (admin.ROLE_DESCRIPTION_MAX + 1))
    assert list(exc.value.fields) == ["description"]
    dn = _create(directory, "ok-name", "d" * admin.ROLE_DESCRIPTION_MAX)
    with pytest.raises(admin.AclAdminError):
        admin.update_role(directory, dn, description="d" * 513, templates=None)


def test_attribute_exception_names_must_be_attributes() -> None:
    item = admin.template_to_json("0:user/user;r")
    item["blocks"][0]["attributes"].append({"name": "not an attribute", "rights": "r"})
    with pytest.raises(admin.AclAdminError) as exc:
        admin.template_from_json(item)
    assert list(exc.value.fields) == ["templates.blocks.0.attributes.0.name"]


def test_role_container_must_be_an_existing_department(directory: MemoryDirectory) -> None:
    admin.check_department(directory, PARIS)
    for bad in ("nonsense", f"ou=nowhere,{BASE}", "ou=paris,dc=elsewhere,dc=org"):
        with pytest.raises(admin.AclAdminError) as exc:
            admin.check_department(directory, bad)
        assert list(exc.value.fields) == ["base"]


def _item(**patch: object) -> dict[str, object]:
    item: dict[str, object] = {"index": 0, "scope": "subtree", "role": ROLE, "members": [USER]}
    item.update(patch)
    return item


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"user_filter": "uid=x"}, "user_filter"),
        ({"user_filter": "(uid=x"}, "user_filter"),
        ({"user_filter": "(uid)"}, "user_filter"),
        ({"user_filter": "(&)"}, "user_filter"),
        ({"user_filter": "(uid=x))"}, "user_filter"),
        ({"target_filter": "(&(a=1)(b"}, "target_filter"),
        ({"target_filter": "just text"}, "target_filter"),
        ({"members": ["not a dn"]}, "members"),
        ({"members": ["uid=a,,dc=x"]}, "members"),
        ({"members": [{"dn": "x"}]}, "members"),
        ({"role": "garbage"}, "role"),
        ({"role": f"cn=ghost,ou=aclroles,{BASE}"}, "role"),
        ({"members": [f"uid=ghost,ou=people,{BASE}"]}, "members"),
    ],
)
def test_assignment_values_are_refused(
    directory: MemoryDirectory, patch: dict[str, object], field: str
) -> None:
    before = directory.get(PARIS)
    with pytest.raises(admin.AclAdminError) as exc:
        admin.set_assignments(directory, PARIS, [_item(**patch)])
    assert [k.removeprefix("assignments.0.") for k in exc.value.fields] == [field]
    assert directory.get(PARIS) == before  # nothing was written


@pytest.mark.parametrize(
    "patch",
    [
        {"user_filter": "(department=Sales)", "target_filter": "(manager=%dn%)"},
        {"user_filter": "(&(uid=*)(!(uid=guest)))"},
        {"members": ["*"]},
        {"scope": "base"},
    ],
)
def test_assignment_values_are_accepted(
    directory: MemoryDirectory, patch: dict[str, object]
) -> None:
    saved = admin.set_assignments(directory, PARIS, [_item(**patch)])
    assert len(saved) == 1
    assert saved[0]["ignored"] is False


def test_stale_references_survive_when_unchanged(directory: MemoryDirectory) -> None:
    """Deleting a role must not lock the other assignments of the entry out of editing."""
    admin.set_assignments(directory, PARIS, [_item()])
    directory.delete(USER)
    items = admin.list_assignments(directory, PARIS)
    assert items[0]["members"][0]["kind"] == "missing"
    admin.set_assignments(directory, PARIS, items)  # unchanged: accepted
    with pytest.raises(admin.AclAdminError):
        admin.set_assignments(directory, PARIS, [*items, _item(index=1)])  # new value, stale user


def test_check_rights_refuses_malformed_input(directory: MemoryDirectory) -> None:
    with pytest.raises(admin.AclAdminError) as exc:
        admin.check_rights(
            directory,
            user_dn="nobody",
            target_dn="",
            object_key=" ",
            attributes=["bad name"],
        )
    assert set(exc.value.fields) == {"user", "dn", "object", "attributes"}
