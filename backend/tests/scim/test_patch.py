"""SCIM PATCH (RFC 7644 3.5.2)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from heracles.scim.errors import (
    INVALID_FILTER,
    INVALID_PATH,
    INVALID_SYNTAX,
    INVALID_VALUE,
    MUTABILITY,
    NO_TARGET,
    ScimError,
)
from heracles.scim.patch import PatchOp, apply_patch, parse_patch
from heracles.scim.schemas import PATCH_OP

ENT = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
MULTI = {"emails", "members", "phonenumbers", "addresses"}


def multi(path: str) -> bool:
    return path in MULTI


def ro(path: str) -> bool:
    return path in {"id", "meta"} or path.startswith("meta.")


def run(resource: dict[str, Any], *ops: PatchOp) -> dict[str, Any]:
    return apply_patch(resource, list(ops), multi_valued=multi, readonly=ro)


def user() -> dict[str, Any]:
    return {
        "id": "1",
        "userName": "bjensen",
        "name": {"givenName": "Barbara", "familyName": "Jensen"},
        "title": "Eng",
        "emails": [
            {"value": "work@x.org", "type": "work", "primary": True},
            {"value": "home@x.org", "type": "home"},
        ],
        "meta": {"created": "2020"},
    }


class TestParsePatch:
    def body(self, *ops: dict[str, Any]) -> dict[str, Any]:
        return {"schemas": [PATCH_OP], "Operations": list(ops)}

    def test_ok(self) -> None:
        ops = parse_patch(
            self.body(
                {"op": "Add", "path": "title", "value": "x"},
                {"op": "REPLACE", "value": {"a": 1}},
                {"op": "remove", "path": "title"},
            )
        )
        assert ops == [
            PatchOp("add", "title", "x"),
            PatchOp("replace", None, {"a": 1}),
            PatchOp("remove", "title", None),
        ]

    @pytest.mark.parametrize(
        "body",
        [  # pyright: ignore[reportUnknownArgumentType]
            {},
            {"schemas": ["wrong"], "Operations": [{"op": "add", "value": {}}]},
            {"schemas": [PATCH_OP]},
            {"schemas": [PATCH_OP], "Operations": []},
            {"schemas": [PATCH_OP], "Operations": "x"},
            {"schemas": [PATCH_OP], "Operations": ["x"]},
            {"schemas": [PATCH_OP], "Operations": [{"path": "a", "value": 1}]},
            {"schemas": [PATCH_OP], "Operations": [{"op": "move", "path": "a"}]},
            {"schemas": [PATCH_OP], "Operations": [{"op": 3}]},
            {"schemas": [PATCH_OP], "Operations": [{"op": "add", "path": "a"}]},
            {"schemas": [PATCH_OP], "Operations": [{"op": "replace", "path": "a"}]},
            {"schemas": [PATCH_OP], "Operations": [{"op": "add", "path": "", "value": 1}]},
            {"schemas": [PATCH_OP], "Operations": [{"op": "add", "path": 3, "value": 1}]},
        ],
    )
    def test_invalid_syntax(self, body: dict[str, Any]) -> None:
        with pytest.raises(ScimError) as exc:
            parse_patch(body)
        assert exc.value.status == 400
        assert exc.value.scim_type == INVALID_SYNTAX

    def test_remove_needs_path(self) -> None:
        with pytest.raises(ScimError) as exc:
            parse_patch(self.body({"op": "remove"}))
        assert exc.value.scim_type == NO_TARGET


class TestAdd:
    def test_simple(self) -> None:
        out = run(user(), PatchOp("add", "nickName", "Babs"))
        assert out["nickName"] == "Babs"

    def test_replaces_single_valued(self) -> None:
        assert run(user(), PatchOp("add", "title", "CTO"))["title"] == "CTO"

    def test_case_insensitive_keeps_existing_spelling(self) -> None:
        out = run(user(), PatchOp("add", "USERNAME", "x"))
        assert out["userName"] == "x"
        assert "USERNAME" not in out

    def test_path_spelling_used_when_new(self) -> None:
        assert run(user(), PatchOp("add", "nickName", "x"))["nickName"] == "x"

    def test_sub_attribute(self) -> None:
        out = run(user(), PatchOp("add", "name.middleName", "J"))
        assert out["name"] == {"givenName": "Barbara", "familyName": "Jensen", "middleName": "J"}

    def test_sub_attribute_creates_parent(self) -> None:
        r = user()
        del r["name"]
        assert run(r, PatchOp("add", "name.givenName", "B"))["name"] == {"givenName": "B"}

    def test_multi_valued_appends(self) -> None:
        out = run(user(), PatchOp("add", "emails", [{"value": "new@x.org", "type": "other"}]))
        assert [e["value"] for e in out["emails"]] == ["work@x.org", "home@x.org", "new@x.org"]

    def test_multi_valued_single_object_value(self) -> None:
        out = run(user(), PatchOp("add", "emails", {"value": "n@x.org"}))
        assert len(out["emails"]) == 3

    def test_multi_valued_creates(self) -> None:
        r = user()
        del r["emails"]
        assert run(r, PatchOp("add", "emails", [{"value": "a"}]))["emails"] == [{"value": "a"}]

    def test_multi_valued_no_duplicates_by_value_key(self) -> None:
        out = run(user(), PatchOp("add", "emails", [{"value": "work@x.org", "type": "x"}]))
        assert len(out["emails"]) == 2

    def test_multi_valued_no_duplicates_scalars(self) -> None:
        r = {"members": ["a", "b"]}
        assert run(r, PatchOp("add", "members", ["b", "c"]))["members"] == ["a", "b", "c"]

    def test_multi_valued_dedupe_full_equality_without_value_key(self) -> None:
        r = {"addresses": [{"city": "A"}]}
        out = run(r, PatchOp("add", "addresses", [{"city": "A"}, {"city": "B"}]))
        assert out["addresses"] == [{"city": "A"}, {"city": "B"}]

    def test_complex_attribute_merges(self) -> None:
        out = run(user(), PatchOp("add", "name", {"middleName": "J"}))
        assert out["name"]["givenName"] == "Barbara"
        assert out["name"]["middleName"] == "J"

    def test_no_path_merges_each_key(self) -> None:
        out = run(
            user(),
            PatchOp("add", None, {"title": "CTO", "emails": [{"value": "z@x.org"}], "x": 1}),
        )
        assert out["title"] == "CTO"
        assert len(out["emails"]) == 3
        assert out["x"] == 1

    def test_no_path_dotted_key(self) -> None:
        out = run(user(), PatchOp("add", None, {"name.givenName": "B"}))
        assert out["name"]["givenName"] == "B"
        assert out["name"]["familyName"] == "Jensen"

    def test_no_path_extension_object(self) -> None:
        out = run(user(), PatchOp("add", None, {ENT: {"employeeNumber": "7", "department": "R"}}))
        assert out[ENT] == {"employeeNumber": "7", "department": "R"}

    def test_no_path_extension_merges(self) -> None:
        r = user()
        r[ENT] = {"department": "R"}
        out = run(r, PatchOp("add", None, {ENT: {"employeeNumber": "7"}}))
        assert out[ENT] == {"department": "R", "employeeNumber": "7"}

    def test_no_path_non_object(self) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("add", None, "x"))
        assert exc.value.scim_type == INVALID_VALUE

    def test_no_path_extension_non_object(self) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("add", None, {ENT: "x"}))
        assert exc.value.scim_type == INVALID_VALUE

    def test_urn_path(self) -> None:
        out = run(user(), PatchOp("add", f"{ENT}:employeeNumber", "701984"))
        assert out[ENT] == {"employeeNumber": "701984"}

    def test_urn_path_existing_extension_case_insensitive(self) -> None:
        r = user()
        r[ENT] = {"department": "R"}
        out = run(r, PatchOp("add", f"{ENT.lower()}:employeeNumber", "7"))
        assert out[ENT] == {"department": "R", "employeeNumber": "7"}

    def test_urn_path_with_sub(self) -> None:
        out = run(user(), PatchOp("add", f"{ENT}:manager.value", "m1"))
        assert out[ENT] == {"manager": {"value": "m1"}}

    def test_core_urn_prefix(self) -> None:
        out = run(user(), PatchOp("add", "urn:ietf:params:scim:schemas:core:2.0:User:title", "X"))
        assert out["title"] == "X"

    def test_bare_urn_path(self) -> None:
        out = run(user(), PatchOp("add", ENT, {"employeeNumber": "1"}))
        assert out[ENT] == {"employeeNumber": "1"}

    def test_filter_sub(self) -> None:
        out = run(user(), PatchOp("add", 'emails[type eq "work"].display', "W"))
        assert out["emails"][0]["display"] == "W"
        assert "display" not in out["emails"][1]

    def test_filter_merge_object(self) -> None:
        out = run(user(), PatchOp("add", 'emails[type eq "home"]', {"primary": True}))
        assert out["emails"][1]["primary"] is True

    def test_filter_no_match(self) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("add", 'emails[type eq "nope"].display', "W"))
        assert exc.value.scim_type == NO_TARGET

    def test_sub_on_multi_valued_applies_to_all(self) -> None:
        out = run(user(), PatchOp("add", "emails.display", "D"))
        assert [e["display"] for e in out["emails"]] == ["D", "D"]

    def test_rfc_add_member(self) -> None:
        group = {"displayName": "G", "members": [{"value": "u1"}]}
        out = run(group, PatchOp("add", "members", [{"value": "u2", "display": "Two"}]))
        assert [m["value"] for m in out["members"]] == ["u1", "u2"]


class TestReplace:
    def test_simple(self) -> None:
        assert run(user(), PatchOp("replace", "title", "CTO"))["title"] == "CTO"

    def test_absent_is_added(self) -> None:
        assert run(user(), PatchOp("replace", "nickName", "x"))["nickName"] == "x"

    def test_multi_valued_replaces_all(self) -> None:
        out = run(user(), PatchOp("replace", "emails", [{"value": "only@x.org"}]))
        assert out["emails"] == [{"value": "only@x.org"}]

    def test_multi_valued_wraps_non_list(self) -> None:
        out = run(user(), PatchOp("replace", "emails", {"value": "only@x.org"}))
        assert out["emails"] == [{"value": "only@x.org"}]

    def test_complex_replaced_whole(self) -> None:
        out = run(user(), PatchOp("replace", "name", {"givenName": "X"}))
        assert out["name"] == {"givenName": "X"}

    def test_sub(self) -> None:
        out = run(user(), PatchOp("replace", "name.familyName", "Smith"))
        assert out["name"] == {"givenName": "Barbara", "familyName": "Smith"}

    def test_filter_sub(self) -> None:
        out = run(user(), PatchOp("replace", 'emails[type eq "work"].value', "new@x.org"))
        assert out["emails"][0]["value"] == "new@x.org"
        assert out["emails"][1]["value"] == "home@x.org"

    def test_filter_replaces_element(self) -> None:
        out = run(
            user(), PatchOp("replace", 'emails[type eq "work"]', {"value": "w", "type": "work"})
        )
        assert out["emails"][0] == {"value": "w", "type": "work"}
        assert len(out["emails"]) == 2

    def test_filter_element_needs_object(self) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("replace", 'emails[type eq "work"]', "x"))
        assert exc.value.scim_type == INVALID_VALUE

    def test_filter_no_match(self) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("replace", 'emails[type eq "nope"].value', "x"))
        assert exc.value.status == 400
        assert exc.value.scim_type == NO_TARGET

    def test_filter_on_absent_attribute(self) -> None:
        r = user()
        del r["emails"]
        with pytest.raises(ScimError) as exc:
            run(r, PatchOp("replace", 'emails[type eq "work"].value', "x"))
        assert exc.value.scim_type == NO_TARGET

    def test_no_path_replaces_each_key(self) -> None:
        out = run(user(), PatchOp("replace", None, {"title": "CTO", "name.givenName": "B"}))
        assert out["title"] == "CTO"
        assert out["name"] == {"givenName": "B", "familyName": "Jensen"}

    def test_no_path_extension(self) -> None:
        r = user()
        r[ENT] = {"department": "R", "employeeNumber": "1"}
        out = run(r, PatchOp("replace", None, {ENT: {"employeeNumber": "2"}}))
        assert out[ENT] == {"department": "R", "employeeNumber": "2"}

    def test_urn_path(self) -> None:
        r = user()
        r[ENT] = {"employeeNumber": "1"}
        out = run(r, PatchOp("replace", f"{ENT}:employeeNumber", "2"))
        assert out[ENT]["employeeNumber"] == "2"

    def test_bare_urn_replaces_extension(self) -> None:
        r = user()
        r[ENT] = {"department": "R"}
        assert run(r, PatchOp("replace", ENT, {"employeeNumber": "2"}))[ENT] == {
            "employeeNumber": "2"
        }

    def test_non_object_extension_is_bad_path(self) -> None:
        r = user()
        r[ENT] = "oops"
        with pytest.raises(ScimError) as exc:
            run(r, PatchOp("replace", f"{ENT}:employeeNumber", "2"))
        assert exc.value.scim_type == INVALID_PATH


class TestRemove:
    def test_simple(self) -> None:
        assert "title" not in run(user(), PatchOp("remove", "title"))

    def test_absent_is_noop(self) -> None:
        assert run(user(), PatchOp("remove", "nickName")) == user()

    def test_sub(self) -> None:
        out = run(user(), PatchOp("remove", "name.givenName"))
        assert out["name"] == {"familyName": "Jensen"}

    def test_last_sub_removes_parent(self) -> None:
        r = {"name": {"givenName": "x"}}
        assert run(r, PatchOp("remove", "name.givenName")) == {}

    def test_multi_valued_whole(self) -> None:
        assert "emails" not in run(user(), PatchOp("remove", "emails"))

    def test_filter_removes_matching(self) -> None:
        out = run(user(), PatchOp("remove", 'emails[type eq "work"]'))
        assert out["emails"] == [{"value": "home@x.org", "type": "home"}]

    def test_filter_removing_all_drops_key(self) -> None:
        out = run(user(), PatchOp("remove", "emails[value pr]"))
        assert "emails" not in out

    def test_filter_no_match_noop(self) -> None:
        assert run(user(), PatchOp("remove", 'emails[type eq "nope"]')) == user()

    def test_filter_sub(self) -> None:
        out = run(user(), PatchOp("remove", 'emails[type eq "work"].primary'))
        assert "primary" not in out["emails"][0]
        assert out["emails"][0]["value"] == "work@x.org"

    def test_filter_on_absent_noop(self) -> None:
        r = user()
        del r["emails"]
        assert run(r, PatchOp("remove", 'emails[type eq "work"]')) == r

    def test_remove_members_with_value(self) -> None:
        g = {"members": [{"value": "u1"}, {"value": "u2"}]}
        out = run(g, PatchOp("remove", "members", [{"value": "u1"}]))
        assert out["members"] == [{"value": "u2"}]

    def test_rfc_remove_member_by_filter(self) -> None:
        g = {"members": [{"value": "u1"}, {"value": "u2"}]}
        out = run(g, PatchOp("remove", 'members[value eq "u2"]'))
        assert out["members"] == [{"value": "u1"}]

    def test_remove_urn_attribute_drops_empty_extension(self) -> None:
        r = user()
        r[ENT] = {"employeeNumber": "1"}
        assert ENT not in run(r, PatchOp("remove", f"{ENT}:employeeNumber"))

    def test_remove_urn_attribute_keeps_others(self) -> None:
        r = user()
        r[ENT] = {"employeeNumber": "1", "department": "R"}
        assert run(r, PatchOp("remove", f"{ENT}:employeeNumber"))[ENT] == {"department": "R"}

    def test_remove_missing_extension_noop(self) -> None:
        assert run(user(), PatchOp("remove", f"{ENT}:employeeNumber")) == user()

    def test_remove_bare_urn(self) -> None:
        r = user()
        r[ENT] = {"employeeNumber": "1"}
        assert ENT not in run(r, PatchOp("remove", ENT))


class TestErrors:
    @pytest.mark.parametrize("path", ["id", "meta", "meta.created", "ID", "Meta.Created"])
    @pytest.mark.parametrize("op", ["add", "replace", "remove"])
    def test_readonly(self, path: str, op: str) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp(op, path, "x"))
        assert exc.value.status == 400
        assert exc.value.scim_type == MUTABILITY

    def test_readonly_via_no_path_key(self) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("replace", None, {"id": "x"}))
        assert exc.value.scim_type == MUTABILITY

    def test_readonly_via_filter_sub(self) -> None:
        with pytest.raises(ScimError) as exc:
            apply_patch(
                user(),
                [PatchOp("replace", 'emails[type eq "work"].value', "x")],
                multi_valued=multi,
                readonly=lambda p: p == "emails.value",
            )
        assert exc.value.scim_type == MUTABILITY

    @pytest.mark.parametrize(
        "path",
        [
            "a.b.c",
            "1abc",
            "a b",
            "emails[type eq",
            'emails[type eq "x"]foo',
            "emails[type eq 'x']",
            ".name",
            "name.",
            'emails[type eq "x"].a.b',
        ],
    )
    def test_invalid_path(self, path: str) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("replace", path, "x"))
        assert exc.value.status == 400
        assert exc.value.scim_type in {INVALID_PATH, INVALID_FILTER}

    def test_bad_filter_in_path(self) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("remove", 'emails[type foo "x"]'))
        assert exc.value.scim_type == INVALID_FILTER

    def test_nested_value_path(self) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("remove", "emails[a[b eq 1]]"))
        assert exc.value.status == 400
        assert exc.value.scim_type in {INVALID_PATH, INVALID_FILTER}

    def test_sub_on_scalar(self) -> None:
        with pytest.raises(ScimError) as exc:
            run(user(), PatchOp("add", "title.x", "y"))
        assert exc.value.scim_type == INVALID_PATH

    def test_filter_with_bracket_in_string(self) -> None:
        r = {"emails": [{"value": "a]b", "type": "w"}]}
        out = run(r, PatchOp("replace", 'emails[value eq "a]b"].type', "z"))
        assert out["emails"][0]["type"] == "z"


class TestPurity:
    def test_input_not_mutated(self) -> None:
        r = user()
        r[ENT] = {"department": "R"}
        before = copy.deepcopy(r)
        run(
            r,
            PatchOp("add", "emails", [{"value": "n"}]),
            PatchOp("replace", 'emails[type eq "work"].value', "w"),
            PatchOp("remove", f"{ENT}:department"),
            PatchOp("add", "name.middleName", "J"),
        )
        assert r == before

    def test_value_not_aliased(self) -> None:
        value = [{"value": "n"}]
        out = run({"emails": []}, PatchOp("add", "emails", value))
        out["emails"][0]["value"] = "changed"
        assert value == [{"value": "n"}]

    def test_ops_apply_in_order(self) -> None:
        out = run(
            user(),
            PatchOp("remove", "title"),
            PatchOp("add", "title", "New"),
            PatchOp("replace", "title", "Newer"),
        )
        assert out["title"] == "Newer"

    def test_error_leaves_input_untouched(self) -> None:
        r = user()
        before = copy.deepcopy(r)
        with pytest.raises(ScimError):
            run(r, PatchOp("add", "title", "ok"), PatchOp("replace", "id", "x"))
        assert r == before
