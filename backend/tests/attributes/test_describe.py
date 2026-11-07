from __future__ import annotations

from heracles.attributes import (
    CompositeAttr,
    ImageAttr,
    IntAttr,
    ListAttr,
    ObjectRefAttr,
    SelectAttr,
    StringAttr,
)


def test_string_descriptor_snapshot() -> None:
    attr = StringAttr(
        "sn", "Last name", description="Family name", required=True, pattern="^a$", max_length=9
    )
    assert attr.describe() == {
        "name": "sn",
        "label": "Last name",
        "description": "Family name",
        "kind": "string",
        "required": True,
        "multivalued": False,
        "readonly": False,
        "default": None,
        "constraints": {"pattern": "^a$", "max_length": 9},
    }


def test_select_descriptor_snapshot() -> None:
    attr = SelectAttr("lang", "Language", options=[("fr", "Français")], default="fr")
    assert attr.describe() == {
        "name": "lang",
        "label": "Language",
        "description": "",
        "kind": "select",
        "required": False,
        "multivalued": False,
        "readonly": False,
        "default": "fr",
        "constraints": {},
        "options": [{"value": "fr", "label": "Français"}],
    }


def test_list_and_ref_descriptor_snapshot() -> None:
    attr = ListAttr("member", "Members", ObjectRefAttr("member", "Member", ref_type="user"))
    d = attr.describe()
    assert d["kind"] == "list" and d["multivalued"] is True
    assert d["item"] == {
        "name": "member",
        "label": "Member",
        "description": "",
        "kind": "object_ref",
        "required": False,
        "multivalued": False,
        "readonly": False,
        "default": None,
        "constraints": {},
        "ref_type": "user",
    }


def test_composite_and_image_descriptor() -> None:
    comp = CompositeAttr("c", "C", [StringAttr("a", "A"), IntAttr("b", "B", min=0, max=10)])
    d = comp.describe()
    assert d["kind"] == "composite"
    fields = d["fields"]
    assert isinstance(fields, list) and len(fields) == 2
    assert fields[1]["constraints"] == {"min": 0, "max": 10}  # type: ignore[index]
    assert ImageAttr("p", "P").describe()["image"] == {"max_width": None, "max_height": None}
    assert ImageAttr("p", "P", max_size=(200, 200)).describe()["image"] == {
        "max_width": 200,
        "max_height": 200,
    }
