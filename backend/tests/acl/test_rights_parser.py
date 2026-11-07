from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from heracles.acl import (
    AclAssignment,
    AclScope,
    Ignored,
    Rights,
    RoleTemplateValue,
    parse_assignment,
    parse_role_value,
    serialise_assignment,
    serialise_role_value,
)
from heracles.acl.parser import everyone_member
from heracles.acl.rights import FULL_RIGHTS, NO_RIGHTS, RightsParseError
from tests.acl.world import b64


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("", ""),
        ("r", "r"),
        ("cmdrw", "rwcdm"),
        ("rwcdmt", "rwcdmt"),
        ("sr", "sr"),
        ("rs", "sr"),
    ],
)
def test_rights_parse_canonical(text: str, canonical: str) -> None:
    rights = Rights.parse(text)
    assert rights.canonical() == canonical
    assert str(rights) == text  # spelling is preserved for exact round-trip
    assert Rights.parse(canonical) == rights


def test_rights_unknown_letter() -> None:
    with pytest.raises(RightsParseError):
        Rights.parse("rx")


def test_rights_union_full_read_only() -> None:
    assert Rights.parse("r").union(Rights.parse("w")) == Rights.parse("rw")
    assert (Rights.parse("c") | Rights.parse("dm")).canonical() == "cdm"
    assert Rights.parse("rwcdm").is_full
    assert not Rights.parse("rwcd").is_full
    assert not Rights.parse("rwcdt").is_full
    assert FULL_RIGHTS.read_only() == Rights.parse("r")
    assert Rights.parse("rwct").read_only() == Rights.parse("rt")
    assert NO_RIGHTS.is_empty and Rights.parse("s").is_empty
    assert Rights.parse("sr").without_self() == Rights.parse("r")
    assert Rights.parse("r").issubset(Rights.parse("rw"))
    assert not Rights.parse("rw").issubset(Rights.parse("r"))
    assert Rights.parse("rwcdmt").issubset(Rights.parse("rwcdmt"))


def test_role_value_example_roundtrip() -> None:
    value = "0:user/user;cmdrw#sn;rw#givenName;r,user/posixAccount;r"
    parsed = parse_role_value(value)
    assert isinstance(parsed, RoleTemplateValue)
    assert parsed.index == 0
    assert [b.object for b in parsed.blocks] == ["user/user", "user/posixAccount"]
    user = parsed.block_map()["user/user"]
    assert user.rights.create and user.rights.move
    assert [n for n, _ in user.attributes] == ["sn", "givenName"]
    assert user.attribute_rights("SN") == Rights.parse("rw")
    assert serialise_role_value(parsed) == value


def test_role_value_blocks_merge_and_self_attrs() -> None:
    parsed = parse_role_value("1:user/user;r#sn;sw,user/user;w#sn;r")
    assert isinstance(parsed, RoleTemplateValue)
    block = parsed.block_map()["user/user"]
    assert block.rights == Rights.parse("rw")
    assert block.attribute_rights("sn", own=True).without_self() == Rights.parse("rw")
    assert block.attribute_rights("sn", own=False) == Rights.parse("r")
    assert block.all_rights(own=False).without_self() == Rights.parse("rw")


@pytest.mark.parametrize(
    "value",
    ["", "nocolon", "x:all;r", "1:all;rx", "1:;r", "1:all;r#;r", "-1:all;r"],
)
def test_role_value_invalid(value: str) -> None:
    result = parse_role_value(value)
    assert isinstance(result, Ignored)
    assert result.raw == value


def test_role_value_empty_spec() -> None:
    parsed = parse_role_value("3:")
    assert isinstance(parsed, RoleTemplateValue)
    assert parsed.blocks == ()
    assert serialise_role_value(parsed) == "3:"


def test_assignment_roundtrip_variants() -> None:
    role = "cn=r,ou=aclroles,dc=x"
    members = f"{b64('uid=a,dc=x')},{everyone_member()}"
    values = [
        f"0:subtree:{b64(role)}:{members}",
        f"1:base:{b64(role)}:{b64('*')}",
        f"2:subtree:{b64(role)}:{b64('*')}:{b64('(uid=a)')}",
        f"3:subtree:{b64(role)}:{b64('*')}::{b64('(ou=%ou%)')}",
        f"4:base:{b64(role)}:{b64('*')}:{b64('(uid=a)')}:{b64('(cn=*)')}",
    ]
    for value in values:
        parsed = parse_assignment(value)
        assert isinstance(parsed, AclAssignment)
        assert serialise_assignment(parsed) == value
    first = parse_assignment(values[0])
    assert isinstance(first, AclAssignment)
    assert first.members == ("uid=a,dc=x", "*")
    assert first.applies_to_everyone
    third = parse_assignment(values[3])
    assert isinstance(third, AclAssignment)
    assert third.user_filter is None and third.target_filter == "(ou=%ou%)"


@pytest.mark.parametrize(
    "value",
    [
        f"0:one:{b64('cn=r')}:{b64('*')}",
        f"0:psub:{b64('cn=r')}:{b64('*')}",
        f"0:SUBTREE:{b64('cn=r')}:{b64('*')}",
        f"x:subtree:{b64('cn=r')}:{b64('*')}",
        "0:subtree:@@@:Kg==",
        f"0:subtree:{b64('cn=r')}:@@@",
        f"0:subtree:{b64('cn=r')}:Kg==:@@@",
        "0:subtree:Kg==",
        f"0:subtree:{b64('cn=r')}:Kg==:a:b:c",
        f"0:subtree::{b64('*')}",
        "0:subtree:/w==:Kg==",  # invalid UTF-8
    ],
)
def test_assignment_ignored(value: str) -> None:
    result = parse_assignment(value)
    assert isinstance(result, Ignored)
    assert result.reason


# ----------------------------------------------------------- hypothesis

rights_text = st.lists(st.sampled_from(list("rwcdmts")), max_size=6).map("".join)
names = st.text(alphabet="abcdefXYZ/_0-9", min_size=1, max_size=8)
attr_names = st.text(alphabet="abcdefXYZ0-9", min_size=1, max_size=6)


@st.composite
def role_values(draw: st.DrawFn) -> str:
    blocks: list[str] = []
    for _ in range(draw(st.integers(0, 4))):
        text = f"{draw(names)};{draw(rights_text)}"
        for _ in range(draw(st.integers(0, 3))):
            text += f"#{draw(attr_names)};{draw(rights_text)}"
        blocks.append(text)
    return f"{draw(st.integers(0, 999))}:{','.join(blocks)}"


dn_text = st.text(alphabet="abcXYZ=, 0-9é", min_size=1, max_size=20).filter(lambda s: s.strip())
filters = st.none() | st.text(min_size=1, max_size=20)


@st.composite
def assignments(draw: st.DrawFn) -> AclAssignment:
    members = draw(st.lists(dn_text | st.just("*"), max_size=4))
    user_filter = draw(filters)
    target_filter = draw(filters)
    return AclAssignment(
        index=draw(st.integers(0, 999)),
        scope=draw(st.sampled_from(list(AclScope))),
        role_dn=draw(dn_text),
        members=tuple(members),
        user_filter=user_filter,
        target_filter=target_filter,
    )


@given(role_values())
def test_role_value_roundtrip_property(value: str) -> None:
    parsed = parse_role_value(value)
    assert isinstance(parsed, RoleTemplateValue)
    assert serialise_role_value(parsed) == value
    assert parse_role_value(serialise_role_value(parsed)) == parsed


@given(assignments())
def test_assignment_roundtrip_property(assignment: AclAssignment) -> None:
    text = serialise_assignment(assignment)
    parsed = parse_assignment(text)
    assert parsed == assignment
    assert isinstance(parsed, AclAssignment)
    assert serialise_assignment(parsed) == text
