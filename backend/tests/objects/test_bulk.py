from __future__ import annotations

from heracles.attributes import JSON, ListAttr, ObjectRefAttr, StringAttr
from heracles.objects.builtin.user import User
from heracles.objects.bulk import is_bulk_editable, new_value

SCALAR = StringAttr("l", "City")
LIST = ListAttr("member", "Members", ObjectRefAttr("member", "Member", ref_type="user"))


def test_scalar_operations() -> None:
    assert new_value(SCALAR, "Paris", "set", "Lyon") == "Lyon"
    assert new_value(SCALAR, "Paris", "clear", None) is None
    assert new_value(SCALAR, None, "add", "Lyon") == "Lyon"
    assert new_value(SCALAR, "Paris", "remove", "Lyon") == "Paris"
    assert new_value(SCALAR, "Paris", "remove", "Paris") is None


def test_list_operations_compare_dns_loosely() -> None:
    current: list[JSON] = ["uid=a,ou=people,dc=x", "uid=b,ou=people,dc=x"]
    assert new_value(LIST, current, "add", ["UID=a, ou=people,dc=x", "uid=c,ou=people,dc=x"]) == [
        *current,
        "uid=c,ou=people,dc=x",
    ]
    assert new_value(LIST, current, "add", "uid=c,ou=people,dc=x") == [
        *current,
        "uid=c,ou=people,dc=x",
    ]
    assert new_value(LIST, current, "remove", ["uid=A,ou=people,dc=x"]) == ["uid=b,ou=people,dc=x"]
    assert new_value(LIST, current, "remove", current) is None
    assert new_value(LIST, current, "set", ["uid=z,ou=people,dc=x"]) == ["uid=z,ou=people,dc=x"]
    assert new_value(LIST, None, "add", ["uid=z,ou=people,dc=x"]) == ["uid=z,ou=people,dc=x"]


def test_editable_kinds() -> None:
    main = User.tabs[0]
    editable = {a.name for a in main.attributes() if is_bulk_editable(a)}
    assert {"sn", "mail", "employeeType", "manager"} <= editable
    assert not editable & {"userPassword", "jpegPhoto", "cn", "base"}
