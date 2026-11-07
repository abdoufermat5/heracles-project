from __future__ import annotations

import base64
from datetime import UTC, date, datetime
from typing import Any

import pytest

from heracles.attributes import (
    Attribute,
    BooleanAttr,
    CompositeAttr,
    DateAttr,
    DateTimeAttr,
    DepartmentAttr,
    DisplayAttr,
    EmailAttr,
    FileAttr,
    FloatAttr,
    HiddenAttr,
    ImageAttr,
    IntAttr,
    ListAttr,
    MultiSelectAttr,
    ObjectRefAttr,
    PasswordAttr,
    PhoneAttr,
    PostalAddressAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
    UrlAttr,
    ValidationError,
    parse_generalized_time,
    set_default_password_hasher,
)

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8

OPTS = [("fr", "Français"), ("en", "English")]

ROUND_TRIPS: list[tuple[Attribute[Any], list[bytes], Any, Any]] = [
    (StringAttr("a", "A"), [b"caf\xc3\xa9"], "café", "café"),
    (TextAttr("a", "A"), [b"l1\nl2"], "l1\nl2", "l1\nl2"),
    (IntAttr("a", "A"), [b"42"], 42, 42),
    (FloatAttr("a", "A"), [b"1.5"], 1.5, 1.5),
    (BooleanAttr("a", "A"), [b"TRUE"], True, True),
    (BooleanAttr("a", "A"), [b"FALSE"], False, False),
    (SelectAttr("a", "A", options=OPTS), [b"fr"], "fr", "fr"),
    (MultiSelectAttr("a", "A", options=OPTS), [b"fr", b"en"], ["fr", "en"], ["fr", "en"]),
    (DateAttr("a", "A"), [b"20240229000000Z"], date(2024, 2, 29), "2024-02-29"),
    (
        DateTimeAttr("a", "A"),
        [b"20240229123045Z"],
        datetime(2024, 2, 29, 12, 30, 45, tzinfo=UTC),
        "2024-02-29T12:30:45Z",
    ),
    (EmailAttr("a", "A"), [b"j@x.org"], "j@x.org", "j@x.org"),
    (PhoneAttr("a", "A"), [b"+33 1 23 45"], "+33 1 23 45", "+33 1 23 45"),
    (UrlAttr("a", "A"), [b"https://x.org/a"], "https://x.org/a", "https://x.org/a"),
    (HiddenAttr("a", "A"), [b"secret"], "secret", "secret"),
    (
        ObjectRefAttr("a", "A", ref_type="user"),
        [b"uid=a,dc=x"],
        "uid=a,dc=x",
        "uid=a,dc=x",
    ),
    (
        PostalAddressAttr("a", "A"),
        [b"1 rue X$75000 Paris"],
        "1 rue X\n75000 Paris",
        "1 rue X\n75000 Paris",
    ),
    (FileAttr("a", "A"), [b"\x00\x01"], b"\x00\x01", "AAE="),
    (
        ImageAttr("a", "A"),
        [JPEG],
        JPEG,
        "data:image/jpeg;base64," + base64.b64encode(JPEG).decode(),
    ),
    (
        ListAttr("a", "A", StringAttr("a", "A")),
        [b"x", b"y"],
        ["x", "y"],
        ["x", "y"],
    ),
]


@pytest.mark.parametrize(("attr", "raw", "value", "js"), ROUND_TRIPS)
def test_round_trip(attr: Attribute[Any], raw: list[bytes], value: Any, js: Any) -> None:
    assert attr.from_ldap(raw) == value
    assert attr.to_ldap(value) == raw
    assert attr.to_json(value) == js
    assert attr.from_json(js) == value
    assert attr.validate(value) == []


@pytest.mark.parametrize(("attr", "_raw", "_value", "_js"), ROUND_TRIPS)
def test_empty_values(attr: Attribute[Any], _raw: Any, _value: Any, _js: Any) -> None:
    assert attr.from_ldap([]) is None
    assert attr.to_ldap(None) == []
    assert attr.from_json(None) is None
    assert attr.to_json(None) is None
    assert attr.validate(None) == []


def test_required() -> None:
    assert StringAttr("a", "A", required=True).validate(None)
    assert StringAttr("a", "A", required=True).validate("")
    assert BooleanAttr("a", "A", required=True).validate(False) == []
    assert IntAttr("a", "A", required=True).validate(0) == []
    assert ListAttr("a", "A", StringAttr("a", "A"), required=True).validate([])


def test_string_constraints() -> None:
    attr = StringAttr("a", "A", pattern=r"[a-z]+", min_length=2, max_length=4)
    assert attr.validate("abc") == []
    assert attr.validate("a")
    assert attr.validate("abcde")
    assert attr.validate("AB")
    assert attr.constraints() == {"pattern": "[a-z]+", "min_length": 2, "max_length": 4}


def test_string_from_json_errors() -> None:
    with pytest.raises(ValidationError):
        StringAttr("a", "A").from_json(3)
    assert StringAttr("a", "A").from_json("") is None


def test_int_float() -> None:
    attr = IntAttr("a", "A", min=1, max=5)
    assert attr.validate(0) and attr.validate(6) and attr.validate(3) == []
    assert attr.from_json(3.0) == 3
    assert attr.from_ldap([b"x"]) is None
    for bad in (True, "3", 3.5):
        with pytest.raises(ValidationError):
            attr.from_json(bad)
    with pytest.raises(ValidationError):
        FloatAttr("a", "A").from_json(float("nan"))
    assert FloatAttr("a", "A").from_json(2) == 2.0
    assert FloatAttr("a", "A").from_ldap([b"inf"]) is None


def test_boolean_edge() -> None:
    attr = BooleanAttr("a", "A")
    assert attr.from_ldap([b"true"]) is True
    assert attr.from_ldap([b"maybe"]) is None
    with pytest.raises(ValidationError):
        attr.from_json("true")


def test_select_validation() -> None:
    sel = SelectAttr("a", "A", options=OPTS)
    assert sel.validate("de")
    assert MultiSelectAttr("a", "A", options=OPTS).validate(["fr", "de"])
    with pytest.raises(ValidationError):
        MultiSelectAttr("a", "A").from_json("fr")


def test_dates() -> None:
    assert DateAttr("a", "A").to_ldap(date(2020, 1, 2)) == [b"20200102000000Z"]
    assert DateAttr("a", "A").from_ldap([b"20200102123000Z"]) == date(2020, 1, 2)
    with pytest.raises(ValidationError):
        DateAttr("a", "A").from_json("02/01/2020")
    dt = DateTimeAttr("a", "A")
    assert dt.from_json("2024-03-01T10:00:00+02:00") == datetime(2024, 3, 1, 8, 0, tzinfo=UTC)
    assert dt.from_json("2024-03-01T10:00:00") == datetime(2024, 3, 1, 10, 0, tzinfo=UTC)
    assert dt.to_ldap(datetime(2024, 3, 1, 8, 0, tzinfo=UTC)) == [b"20240301080000Z"]
    with pytest.raises(ValidationError):
        dt.from_json("yesterday")


def test_generalized_time_variants() -> None:
    assert parse_generalized_time("20240301080000.5Z") == datetime(
        2024, 3, 1, 8, 0, 0, 500000, tzinfo=UTC
    )
    assert parse_generalized_time("202403010800+0200") == datetime(2024, 3, 1, 6, 0, tzinfo=UTC)
    assert parse_generalized_time("garbage") is None
    assert parse_generalized_time("20241301000000Z") is None


def test_email_phone_url() -> None:
    assert EmailAttr("a", "A").validate("nope")
    assert PhoneAttr("a", "A").validate("abc")
    assert PhoneAttr("a", "A").validate("(01) 23.45-67/89") == []
    assert UrlAttr("a", "A").validate("not a url")


def test_postal_address_escaping() -> None:
    attr = PostalAddressAttr("a", "A")
    value = "A$B\\C\nline 2"
    raw = attr.to_ldap(value)
    assert raw == [b"A\\24B\\5CC$line 2"]
    assert attr.from_ldap(raw) == value
    assert attr.from_json("a\r\nb") == "a\nb"
    assert attr.to_ldap("  ") == []


def test_image_validation_and_json() -> None:
    attr = ImageAttr("a", "A", max_size=(10, 20))
    assert attr.validate(PNG) == []
    assert attr.validate(b"GIF89a")
    assert attr.to_json(PNG).startswith("data:image/png;base64,")  # type: ignore[union-attr]
    assert attr.from_json(base64.b64encode(JPEG).decode()) == JPEG
    with pytest.raises(ValidationError):
        attr.from_json("data:image/png,AAAA")
    with pytest.raises(ValidationError):
        attr.from_json("!!!notbase64")
    assert attr.describe()["image"] == {"max_width": 10, "max_height": 20}


def test_password_semantics() -> None:
    calls: list[str] = []

    def hasher(plain: str) -> str:
        calls.append(plain)
        return "{TEST}" + plain[::-1]

    attr = PasswordAttr("userPassword", "Password", hasher=hasher)
    assert attr.from_ldap([b"{SSHA}xyz"]) is None
    assert attr.to_json("whatever") is None
    assert attr.from_json(None) is None  # unchanged
    assert attr.from_json("") == ""  # remove
    assert attr.to_ldap(None) == [] and attr.to_ldap("") == []
    assert attr.to_ldap("abc") == [b"{TEST}cba"]
    assert calls == ["abc"]
    assert attr.validate(None) == []
    assert PasswordAttr("p", "P", required=True).validate("")
    assert PasswordAttr("p", "P", min_length=5).validate("abc")


def test_password_without_hasher() -> None:
    set_default_password_hasher(None)
    with pytest.raises(RuntimeError):
        PasswordAttr("p", "P").to_ldap("abc")
    set_default_password_hasher(lambda p: "H" + p)
    try:
        assert PasswordAttr("p", "P").to_ldap("x") == [b"Hx"]
    finally:
        set_default_password_hasher(None)


def test_object_ref_and_department() -> None:
    ref = ObjectRefAttr("a", "A", ref_type="user")
    assert ref.validate("garbage")
    assert ref.validate("uid=a,dc=x") == []
    assert ref.describe()["ref_type"] == "user"
    assert DepartmentAttr("base", "Dept").stored is False


def test_display() -> None:
    attr = DisplayAttr("cn", "Name", compute=lambda v: f"{v['a']}!")
    assert attr.readonly
    assert attr.compute({"a": "x"}) == "x!"
    assert attr.validate(None) == []
    assert attr.describe()["kind"] == "display"


def test_list_of_composites() -> None:
    comp = CompositeAttr(
        "c", "C", [StringAttr("a", "A"), IntAttr("b", "B"), BooleanAttr("c", "C")], separator=";"
    )
    lst = ListAttr("l", "L", comp)
    raw = [b"x;1;TRUE", b"y;;"]
    value = lst.from_ldap(raw)
    assert value == [{"a": "x", "b": 1, "c": True}, {"a": "y", "b": None, "c": None}]
    assert lst.to_ldap(value) == [b"x;1;TRUE", b"y;;"]
    assert lst.from_json(lst.to_json(value)) == value


def test_composite() -> None:
    comp = CompositeAttr("c", "C", [StringAttr("a", "A"), StringAttr("b", "B")], separator=":")
    assert comp.from_ldap([b"x:y"]) == {"a": "x", "b": "y"}
    assert comp.from_ldap([b"x"]) == {"a": "x", "b": None}
    assert comp.from_ldap([b":"]) is None
    assert comp.to_ldap({"a": "x", "b": None}) == [b"x:"]
    assert comp.to_ldap({"a": None, "b": None}) == []
    assert comp.from_json({"a": "1", "b": "2"}) == {"a": "1", "b": "2"}
    assert comp.to_json({"a": "1", "b": None}) == {"a": "1", "b": None}
    assert comp.validate({"a": "x:y", "b": "z"})
    with pytest.raises(ValidationError):
        comp.from_json({"zzz": 1})
    with pytest.raises(ValidationError):
        comp.from_json([])
    # separator inside last field is preserved by maxsplit
    assert comp.from_ldap([b"x:y:z"]) == {"a": "x", "b": "y:z"}
    with pytest.raises(ValueError):
        CompositeAttr("c", "C", [], separator="")


def test_composite_subfield_error_has_label() -> None:
    comp = CompositeAttr("c", "C", [IntAttr("n", "Number")])
    with pytest.raises(ValidationError, match="Number"):
        comp.from_json({"n": "x"})
    required_sub = CompositeAttr("c", "C", [StringAttr("n", "Number", required=True)])
    assert required_sub.validate({"n": None}) == ["Number: This field is required."]


def test_list_validation() -> None:
    lst = ListAttr("l", "L", EmailAttr("l", "L"), min_length=1, max_length=2)
    assert lst.validate(["bad"]) == ["Invalid email address."]
    assert lst.validate(["a@b.c", "a@b.d", "a@b.e"])
    with pytest.raises(ValidationError):
        lst.from_json("x")
    assert lst.from_json(["a@b.c", None, ""]) == ["a@b.c"]
