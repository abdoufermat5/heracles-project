from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from heracles.objects import masks
from heracles.objects.masks import (
    CounterState,
    MaskCycleError,
    MaskEnv,
    MaskError,
    MissingAttributeError,
    candidates,
    parse_mask,
    required_fields,
    resolution_order,
    resolve_definitions,
)

NOW = datetime(2026, 11, 8, 10, 30, 5, tzinfo=UTC)


def make_env() -> MaskEnv:
    return MaskEnv(
        now=lambda: NOW,
        choice=lambda charset: charset[0],
        randint=lambda lo, hi: hi,
    )


def lookup_of(values: dict[str, list[str]]) -> Callable[[str], list[str] | None]:
    low = {k.lower(): v for k, v in values.items()}
    return lambda a: low.get(a.lower())


def ev(value: str, **attrs: list[str]) -> list[str]:
    return candidates(value, lookup_of(attrs), make_env())


def test_literal_and_escaped_percent() -> None:
    assert ev("100%% sure") == ["100% sure"]
    assert ev("plain") == ["plain"]


def test_double_percent_prefix_is_untouched() -> None:
    assert ev("%%abc%x%") == ["%%abc%x%"]


def test_simple_substitution_is_case_insensitive() -> None:
    assert ev("%givenName% %sn%", givenname=["John"], SN=["Doe"]) == ["John Doe"]


def test_missing_attribute_is_an_error_unless_commented() -> None:
    with pytest.raises(MissingAttributeError) as exc:
        ev("%sn%")
    assert exc.value.attr == "sn"
    assert ev("x%c|sn%y") == ["xy"]


def test_unterminated_and_unknown() -> None:
    with pytest.raises(MaskError):
        parse_mask("50% off")
    with pytest.raises(MaskError):
        parse_mask("%z|sn%")
    with pytest.raises(MaskError):
        parse_mask("%bad name%")
    with pytest.raises(MaskError):
        parse_mask("%s[0|sn%")


def test_case_modifiers() -> None:
    assert ev("%u|a%", a=["abc"]) == ["ABC"]
    assert ev("%l|a%", a=["ABC"]) == ["abc"]
    assert ev("%i|a%", a=["jean-pierre DUPONT"]) == ["Jean-Pierre Dupont"]


def test_accents_and_transliteration() -> None:
    assert ev("%a|a%", a=["Chloé"]) == ["Chloe"]
    assert ev("%t|a%", a=["Müller"]) == ["Muller", "Mueller"]
    assert ev("%t|a%", a=["Zoé"]) == ["Zoe"]
    assert ev("%t|a%", a=["Straße"]) == ["Strae", "Strasse"]


def test_substring_variants() -> None:
    assert ev("%s[0,1]|a%", a=["John"]) == ["J"]
    assert ev("%s[1]|a%", a=["John"]) == ["ohn"]
    assert ev("%s[-2]|a%", a=["John"]) == ["hn"]
    assert ev("%s[0,1-3]|a%", a=["John"]) == ["J", "Jo", "Joh"]
    assert ev("%s[0,2-9]|a%", a=["abc"]) == ["ab", "abc"]
    with pytest.raises(MaskError):
        ev("%s[0,x]|a%", a=["abc"])


def test_modifiers_chain_left_to_right() -> None:
    assert ev("%s[0,1]l|a%%l|b%", a=["John"], b=["DOE"]) == ["jdoe"]
    assert ev("%lt|a%", a=["Éric"]) == ["eric"]


def test_array_modifiers() -> None:
    vals = {"m": ["a@x", "b@y", "c@z"]}
    assert ev("%F|m%", **vals) == ["a@x"]
    assert ev("%L|m%", **vals) == ["c@z"]
    assert ev("%J[, ]|m%", **vals) == ["a@x, b@y, c@z"]
    assert ev("%J|m%", **vals) == ["a@xb@yc@z"]
    assert ev("%C|m%", **vals) == ["3"]
    assert ev("%M[/@[xy]$/]J[+]|m%", **vals) == ["a@x+b@y"]
    ips = {"ip": ["10.0.0.1", "::1", "nonsense"]}
    assert ev("%4|ip%", **ips) == ["10.0.0.1"]
    assert ev("%6|ip%", **ips) == ["::1"]


def test_replace() -> None:
    assert ev("%p|a%", a=["a b  c"]) == ["abc"]
    assert ev("%p[b]|a%", a=["abc"]) == ["ac"]
    assert ev("%p[\\d+,#]|a%", a=["a12b3"]) == ["a#b#"]
    assert ev("%p[\\,,;]|a%", a=["a,b"]) == ["a;b"]


def test_base64() -> None:
    assert ev("%b|a%", a=["hello"]) == ["aGVsbG8="]
    assert ev("%b[d]|a%", a=["aGVsbG8="]) == ["hello"]
    with pytest.raises(MaskError):
        ev("%b[d]|a%", a=["!!!"])


def test_random_uses_environment() -> None:
    assert ev("%c|x%%r[4,4,d]|x%", x=["z"]) == ["0000"]
    assert ev("%r[3,5,l]|x%", x=["z"]) == ["aaaaa"]
    assert ev("%r|x%", x=["z"]) == ["a" * 8]
    with pytest.raises(MaskError):
        ev("%r[3,2,d]|x%", x=["z"])


def test_dates() -> None:
    assert ev("%cd|x%") == ["2026-11-08"]
    assert ev("%cd[now,d/m/Y H:i:s]|x%") == ["08/11/2026 10:30:05"]
    assert ev("%cd[now,epoch]|x%") == [
        str((NOW.date() - NOW.date().replace(year=1970, month=1, day=1)).days)
    ]
    assert ev("%cd[+3 days,Y-m-d]|x%") == ["2026-11-11"]
    assert ev("%cd[-1 month,Y-m-d]|x%") == ["2026-10-08"]
    assert ev("%cd[+1 year,Y-m-d]|x%") == ["2027-11-08"]
    assert ev("%cd[2020-02-29,\\Y\\m Ymd]|x%") == ["Ym 20200229"]
    assert ev("%d[@,F j]|a%", a=["2024-07-04"]) == ["July 4"]
    assert ev("%cd[+2 weeks,M D]|x%") == ["Nov Sun"]
    with pytest.raises(MaskError):
        ev("%cd[yesterday]|x%")


def test_month_offset_is_clamped() -> None:
    env = MaskEnv(now=lambda: datetime(2026, 1, 31, tzinfo=UTC))
    assert candidates("%cd[+1 month]|x%", lookup_of({}), env) == ["2026-02-28"]


def test_incremental_counter() -> None:
    state = CounterState.parse(["uid;1000", "other;5", "junk"])
    env = MaskEnv(counter=state.next)
    out = candidates("%cn[uid,500,2]|x%-%cn[new,10]|x%", lookup_of({}), env)
    assert out == ["1002-10"]
    assert candidates("%cn[uid,500,2]|x%", lookup_of({}), env) == ["1004"]
    assert state.serialise() == ["new;10", "other;5", "uid;1004"]
    with pytest.raises(MaskError):
        candidates("%cn[a;b]|x%", lookup_of({}), env)


def test_cartesian_candidates_are_bounded_and_deduplicated() -> None:
    out = ev("%s[0,1-2]|a%.%s[0,1-2]|b%", a=["abc"], b=["xyz"])
    assert out == ["a.x", "a.xy", "ab.x", "ab.xy"]


def test_required_fields() -> None:
    defs = {
        "cn": ["%givenName% %sn%"],
        "uid": ["%s[0,1]l|givenName%%l|sn%"],
        "mail": ["%uid%@example.org"],
        "description": ["%c|note%"],
    }
    assert required_fields(defs) == ["givenName", "sn"]


def test_resolution_order_and_cycles() -> None:
    defs = {"mail": ["%uid%@x"], "uid": ["%sn%"], "cn": ["static"]}
    order = resolution_order(defs)
    assert order.index("uid") < order.index("mail")
    with pytest.raises(MaskCycleError) as exc:
        resolution_order({"a": ["%b%"], "b": ["%a%"]})
    assert exc.value.cycle[0] == exc.value.cycle[-1]
    with pytest.raises(MaskCycleError):
        resolution_order({"a": ["x%a%"]})
    # a user supplied value breaks the loop
    assert resolution_order({"a": ["%b%"], "b": ["%a%"]}, ["a"]) == ["b"]


def test_resolve_definitions_in_dependency_order() -> None:
    defs = {
        "mail": ["%uid%@example.org"],
        "uid": ["%s[0,1]l|givenName%%l|sn%"],
        "cn": ["%givenName% %sn%"],
        "objectClass": ["top"],
    }
    out = resolve_definitions(defs, {"givenName": ["John"], "sn": ["Doe"]}, make_env())
    assert out == {
        "mail": ["jdoe@example.org"],
        "uid": ["jdoe"],
        "cn": ["John Doe"],
        "objectclass": ["top"],
    }


def test_supplied_values_override_definitions() -> None:
    defs = {"uid": ["%l|sn%"], "mail": ["%uid%@x"]}
    out = resolve_definitions(defs, {"sn": ["Doe"], "uid": ["custom"]}, make_env())
    assert out == {"mail": ["custom@x"]}


def test_choose_hook_picks_candidates_and_drops_empty() -> None:
    defs = {"uid": ["%t|sn%"], "empty": ["%c|x%"], "mail": ["%uid%@x"]}

    def choose(attr: str, options: list[str]) -> str:
        return options[-1] if attr == "uid" else options[0]

    out = resolve_definitions(defs, {"sn": ["Müller"]}, make_env(), choose)
    assert out == {"uid": ["Mueller"], "mail": ["Mueller@x"]}


def test_missing_field_raises() -> None:
    with pytest.raises(MissingAttributeError):
        resolve_definitions({"cn": ["%sn%"]}, {}, make_env())


def test_masks_module_exports() -> None:
    assert "F" in masks.ARRAY_MODIFIERS
