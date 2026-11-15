"""``attributes`` / ``excludedAttributes`` projection."""

from __future__ import annotations

import copy
from typing import Any

from heracles.scim.projection import project

ENT = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
CORE = "urn:ietf:params:scim:schemas:core:2.0:User"

USER: dict[str, Any] = {
    "schemas": [CORE, ENT],
    "id": "abc",
    "userName": "bjensen",
    "name": {"givenName": "Barbara", "familyName": "Jensen"},
    "emails": [
        {"value": "a@x.org", "type": "work"},
        {"value": "b@x.org", "type": "home"},
    ],
    "meta": {"created": "2020", "resourceType": "User"},
    ENT: {"employeeNumber": "7", "department": "R&D"},
}


def test_no_filters_returns_copy() -> None:
    out = project(USER)
    assert out == USER
    assert out is not USER
    out["name"]["givenName"] = "X"
    assert USER["name"]["givenName"] == "Barbara"


def test_attributes_keeps_always() -> None:
    assert project(USER, attributes=["userName"]) == {
        "schemas": USER["schemas"],
        "id": "abc",
        "userName": "bjensen",
    }


def test_attributes_case_insensitive() -> None:
    out = project(USER, attributes=["USERNAME"])
    assert out["userName"] == "bjensen"


def test_attributes_sub_attribute() -> None:
    out = project(USER, attributes=["name.givenName"])
    assert out["name"] == {"givenName": "Barbara"}
    assert "userName" not in out


def test_attributes_whole_complex() -> None:
    assert project(USER, attributes=["name"])["name"] == USER["name"]


def test_attributes_multi_valued_sub() -> None:
    out = project(USER, attributes=["emails.value"])
    assert out["emails"] == [{"value": "a@x.org"}, {"value": "b@x.org"}]


def test_attributes_meta_only_when_listed() -> None:
    assert "meta" not in project(USER, attributes=["userName"])
    assert project(USER, attributes=["meta.created"])["meta"] == {"created": "2020"}


def test_attributes_extension_attribute() -> None:
    out = project(USER, attributes=[f"{ENT}:employeeNumber"])
    assert out[ENT] == {"employeeNumber": "7"}
    assert "userName" not in out


def test_attributes_whole_extension() -> None:
    assert project(USER, attributes=[ENT])[ENT] == USER[ENT]


def test_attributes_core_urn_prefix() -> None:
    out = project(USER, attributes=[f"{CORE}:userName"])
    assert out["userName"] == "bjensen"


def test_attributes_unknown_ignored() -> None:
    assert project(USER, attributes=["nope"]) == {"schemas": USER["schemas"], "id": "abc"}


def test_excluded_drops() -> None:
    out = project(USER, excluded=["emails", "meta"])
    assert "emails" not in out
    assert "meta" not in out
    assert out["userName"] == "bjensen"


def test_excluded_sub_attribute() -> None:
    out = project(USER, excluded=["name.familyName"])
    assert out["name"] == {"givenName": "Barbara"}


def test_excluded_sub_of_multi_valued() -> None:
    out = project(USER, excluded=["emails.type"])
    assert out["emails"] == [{"value": "a@x.org"}, {"value": "b@x.org"}]


def test_excluded_extension_attribute() -> None:
    out = project(USER, excluded=[f"{ENT}:employeeNumber"])
    assert out[ENT] == {"department": "R&D"}


def test_excluded_whole_extension() -> None:
    assert ENT not in project(USER, excluded=[ENT])


def test_excluded_never_drops_always() -> None:
    out = project(USER, excluded=["id", "schemas", "userName"])
    assert out["id"] == "abc"
    assert out["schemas"] == USER["schemas"]
    assert "userName" not in out


def test_custom_always() -> None:
    out = project(USER, attributes=["userName"], always=["id", "meta"])
    assert "meta" in out
    assert "schemas" not in out


def test_input_not_mutated() -> None:
    before = copy.deepcopy(USER)
    project(USER, attributes=["name.givenName"])
    project(USER, excluded=["emails"])
    assert before == USER
