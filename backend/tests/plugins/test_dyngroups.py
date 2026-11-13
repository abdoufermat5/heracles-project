"""Dynamic groups: rule parsing, evaluation, the group tab."""

from __future__ import annotations

import pytest

import heracles_plugins.dyngroups as dyn
from heracles.ldap.client import Entry, Scope
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.dyngroups import (
    MemberRuleError,
    evaluate_members,
    parse_member_rule,
    refresh_dynamic_groups,
    select_members,
)

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"


def user(
    uid: str, dept: str, city: str = "Paris", base: str = PEOPLE
) -> tuple[str, dict[str, list[bytes]]]:
    return f"uid={uid},{base}", {
        "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
        "uid": [uid.encode()],
        "cn": [uid.encode()],
        "sn": [uid.encode()],
        "departmentNumber": [dept.encode()],
        "l": [city.encode()],
    }


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(GROUPS, {"objectClass": [b"organizationalUnit"], "ou": [b"groups"]})
    d.add(f"ou=ext,{BASE}", {"objectClass": [b"organizationalUnit"], "ou": [b"ext"]})
    for args in (
        user("alice", "sales"),
        user("bob", "sales", "Lyon"),
        user("carol", "it"),
        user("dave", "sales", base=f"ou=ext,{BASE}"),
    ):
        d.add(*args)
    d.set_schema_object_classes([*d.schema_object_classes(), "groupOfURLs", "extensibleObject"])
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        dyn.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return ObjectService(directory, registry)


def dn(uid: str, base: str = PEOPLE) -> str:
    return f"uid={uid},{base}"


def new_group(service: ObjectService, rule: str, cn: str = "sales") -> str:
    return service.create(
        "group",
        BASE,
        {
            "main": {"values": {"cn": cn}},
            "dynamic": {"active": True, "values": {"memberURL": rule}},
        },
    )


# ------------------------------------------------------------------ parsing


def test_parse_bare_filter() -> None:
    rule = parse_member_rule(" (departmentNumber=sales) ")
    assert rule.base is None and rule.scope is Scope.SUBTREE
    assert rule.filter == "(departmentNumber=sales)"


def test_parse_ldap_url() -> None:
    rule = parse_member_rule("ldap:///ou=people,dc=test??sub?(l=Par%69s)")
    assert rule.base == "ou=people,dc=test"
    assert rule.scope is Scope.SUBTREE
    assert rule.filter == "(l=Paris)"
    default = parse_member_rule("ldap://host:389/ou=people,dc=test")
    assert default.scope is Scope.BASE and default.filter == "(objectClass=*)"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "sales",
        "http://x/y",
        "ldap://host",
        "ldap:///dc=test??deep?(a=b)",
        "(a=b",
        "ldap:///dc=test??sub?x",
    ],
)
def test_parse_errors(text: str) -> None:
    with pytest.raises(MemberRuleError):
        parse_member_rule(text)


# --------------------------------------------------------------- evaluation


def test_select_members_is_pure() -> None:
    entries = [Entry(*user("alice", "sales")), Entry(*user("carol", "it"))]
    entries.append(
        Entry(
            f"cn=team,{GROUPS}", {"objectClass": [b"groupOfNames"], "departmentNumber": [b"sales"]}
        )
    )
    rule = parse_member_rule("(departmentNumber=sales)")
    assert select_members(entries, rule, directory_base=BASE) == [dn("alice")]
    one = parse_member_rule(f"ldap:///{PEOPLE}??one?(objectClass=*)")
    assert select_members(entries, one, directory_base=BASE) == [dn("alice"), dn("carol")]
    outside = parse_member_rule("ldap:///dc=other??sub?(a=b)")
    with pytest.raises(MemberRuleError):
        select_members(entries, outside, directory_base=BASE)


def test_evaluate_members_searches_the_directory(directory: MemoryDirectory) -> None:
    everywhere = evaluate_members(directory, "(departmentNumber=sales)")
    assert everywhere == [dn("alice"), dn("bob"), dn("dave", f"ou=ext,{BASE}")]
    scoped = evaluate_members(directory, f"ldap:///{PEOPLE}??sub?(departmentNumber=sales)")
    assert scoped == [dn("alice"), dn("bob")]
    assert evaluate_members(directory, "(departmentNumber=none)") == []
    with pytest.raises(MemberRuleError):
        evaluate_members(directory, "(departmentNumber=sales)", max_members=1)
    with pytest.raises(MemberRuleError):
        evaluate_members(directory, "ldap:///dc=elsewhere??sub?(a=b)")


# ---------------------------------------------------------------------- tab


def test_tab_attachment_and_acl(service: ObjectService) -> None:
    info = service.registry.get("group")
    tab = info.tab("dynamic")
    assert tab is not None and info.acl_object(tab) == "ogroup/dynamicGroup"


def test_members_are_computed_on_create_and_update(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    group = new_group(service, "(departmentNumber=sales)")
    entry = directory.get(group) or pytest.fail()
    assert entry.has_object_class("groupOfURLs") and entry.has_object_class("extensibleObject")
    assert entry.text("memberURL") == "(departmentNumber=sales)"
    assert sorted(entry.texts("member")) == sorted(
        [dn("alice"), dn("bob"), dn("dave", f"ou=ext,{BASE}")]
    )
    state = service.load("group", group)
    assert state.tabs["dynamic"].values["computedMembers"] == [
        dn("alice"),
        dn("bob"),
        dn("dave", f"ou=ext,{BASE}"),
    ]
    service.update("group", group, {"dynamic": {"values": {"memberURL": "(departmentNumber=it)"}}})
    assert (directory.get(group) or pytest.fail()).texts("member") == [dn("carol")]


def test_invalid_or_empty_rules_are_refused(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as bad:
        new_group(service, "sales")
    assert "dynamic.memberURL" in bad.value.fields
    with pytest.raises(ObjectValidationError) as empty:
        new_group(service, "(departmentNumber=none)")
    assert "no user" in empty.value.fields["dynamic.memberURL"]
    with pytest.raises(ObjectValidationError):
        service.create(
            "group", BASE, {"main": {"values": {"cn": "x"}}, "dynamic": {"active": True}}
        )


def test_deactivating_keeps_the_members(service: ObjectService, directory: MemoryDirectory) -> None:
    group = new_group(service, "(departmentNumber=it)")
    service.update("group", group, {"dynamic": {"active": False}})
    entry = directory.get(group) or pytest.fail()
    assert not entry.has_object_class("groupOfURLs")
    assert entry.get("memberURL") == []
    assert entry.texts("member") == [dn("carol")]


def test_refresh_updates_changed_groups_only(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    group = new_group(service, "(departmentNumber=it)")
    assert refresh_dynamic_groups(directory) == {}
    directory.add(*user("erin", "it"))
    assert refresh_dynamic_groups(directory) == {group: 2}
    assert sorted((directory.get(group) or pytest.fail()).texts("member")) == [
        dn("carol"),
        dn("erin"),
    ]


# ---------------------------------------------------- the rule is an oracle (S-04)


class _Policy:
    """Everything allowed except reading the attributes in ``hidden``."""

    def __init__(self, *hidden: str) -> None:
        self._hidden = set(hidden)

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        return attr not in self._hidden

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        return True

    def can_create(self, type_name: str, base: str) -> bool:
        return True

    def can_delete(self, dn: str, type_name: str) -> bool:
        return True


def _create_with(service: ObjectService, policy: _Policy, rule: str) -> str:
    restricted = ObjectService(service.directory, service.registry, policy=policy)
    return new_group(restricted, rule)


def test_a_rule_may_only_test_attributes_the_editor_can_read(service: ObjectService) -> None:
    assert _create_with(service, _Policy("l"), "(departmentNumber=sales)")
    with pytest.raises(ObjectValidationError) as hidden:
        _create_with(service, _Policy("l"), "(&(departmentNumber=sales)(l=Par*))")
    assert "dynamic.memberURL" in hidden.value.fields
    # write-only attributes (password hashes) can never be probed
    with pytest.raises(ObjectValidationError) as secret:
        _create_with(service, _Policy(), "(userPassword={SSHA}a*)")
    assert "userpassword" in secret.value.fields["dynamic.memberURL"]
