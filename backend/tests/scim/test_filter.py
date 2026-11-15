"""SCIM filter parser, LDAP compiler and evaluator (RFC 7644 3.4.2.2)."""

from __future__ import annotations

import pytest

from heracles.scim.errors import INVALID_FILTER, ScimError
from heracles.scim.filter import (
    And,
    Compare,
    Not,
    Or,
    ValuePath,
    attributes_of,
    matches,
    parse,
    split_path,
    to_ldap,
)

ENT = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"


def resolve(path: str) -> str | None:
    table = {
        "username": "uid",
        "name.familyname": "sn",
        "name.givenname": "givenName",
        "title": "title",
        "emails.value": "mail",
        "emails.type": "mailType",
        "active": "hrcActive",
        "meta.lastmodified": "modifyTimestamp",
        "userType": "employeeType",
        f"{ENT}:employeenumber".lower(): "employeeNumber",
    }
    return table.get(path)


def ldap(text: str) -> str:
    return to_ldap(parse(text), resolve)


class TestParse:
    def test_simple(self) -> None:
        assert parse('userName eq "bjensen"') == Compare("userName", "eq", "bjensen")

    @pytest.mark.parametrize("op", ["eq", "ne", "co", "sw", "ew", "gt", "ge", "lt", "le"])
    def test_every_operator(self, op: str) -> None:
        assert parse(f'title {op} "x"') == Compare("title", op, "x")

    def test_operators_case_insensitive(self) -> None:
        assert parse('title EQ "x"') == Compare("title", "eq", "x")
        assert parse("title PR") == Compare("title", "pr")

    def test_pr_has_no_value(self) -> None:
        assert parse("title pr") == Compare("title", "pr", None)

    def test_literals(self) -> None:
        assert parse("a eq true") == Compare("a", "eq", True)
        assert parse("a eq false") == Compare("a", "eq", False)
        assert parse("a eq null") == Compare("a", "eq", None)
        assert parse("a gt 12") == Compare("a", "gt", 12)
        assert parse("a lt -1.5") == Compare("a", "lt", -1.5)

    def test_string_escapes(self) -> None:
        assert parse(r'a eq "x\"y\\zé"') == Compare("a", "eq", 'x"y\\zé')

    def test_string_with_brackets_and_spaces(self) -> None:
        assert parse('a eq "x ) [ and y"') == Compare("a", "eq", "x ) [ and y")

    def test_logical_keywords_case_insensitive(self) -> None:
        f = parse("a eq 1 AND b eq 2 Or NOT (c eq 3)")
        assert isinstance(f, Or)

    def test_precedence_and_over_or(self) -> None:
        f = parse("a pr or b pr and c pr")
        assert f == Or(Compare("a", "pr"), And(Compare("b", "pr"), Compare("c", "pr")))

    def test_precedence_not_over_and(self) -> None:
        f = parse("not (a pr) and b pr")
        assert f == And(Not(Compare("a", "pr")), Compare("b", "pr"))

    def test_parentheses(self) -> None:
        f = parse("(a pr or b pr) and c pr")
        assert f == And(Or(Compare("a", "pr"), Compare("b", "pr")), Compare("c", "pr"))

    def test_left_associative(self) -> None:
        f = parse("a pr and b pr and c pr")
        assert f == And(And(Compare("a", "pr"), Compare("b", "pr")), Compare("c", "pr"))

    def test_value_path(self) -> None:
        f = parse('emails[type eq "work" and value co "@example.com"]')
        assert f == ValuePath(
            "emails",
            And(Compare("type", "eq", "work"), Compare("value", "co", "@example.com")),
        )

    def test_value_path_sub_attribute(self) -> None:
        f = parse('emails[type eq "work"].value co "x"')
        assert f == ValuePath(
            "emails", And(Compare("type", "eq", "work"), Compare("value", "co", "x"))
        )

    def test_value_path_sub_attribute_presence(self) -> None:
        f = parse('emails[type eq "work"].value')
        assert f == ValuePath("emails", And(Compare("type", "eq", "work"), Compare("value", "pr")))

    def test_urn_path_kept(self) -> None:
        f = parse(f'{ENT}:employeeNumber eq "1"')
        assert f == Compare(f"{ENT}:employeeNumber", "eq", "1")

    def test_rfc_examples(self) -> None:
        examples = [
            'userName eq "bjensen"',
            'name.familyName co "O\'Malley"',
            'userName sw "J"',
            'urn:ietf:params:scim:schemas:core:2.0:User:userName sw "J"',
            "title pr",
            'meta.lastModified gt "2011-05-13T04:42:34Z"',
            'meta.lastModified ge "2011-05-13T04:42:34Z"',
            'meta.lastModified lt "2011-05-13T04:42:34Z"',
            'meta.lastModified le "2011-05-13T04:42:34Z"',
            'title pr and userType eq "Employee"',
            'title pr or userType eq "Intern"',
            f'schemas eq "{ENT}"',
            'userType eq "Employee" and (emails co "example.com" or emails.value co "example.org")',
            'userType ne "Employee" and not (emails co "example.com" '
            'or emails.value co "example.org")',
            'userType eq "Employee" and (emails.type eq "work")',
            'userType eq "Employee" and emails[type eq "work" and value co "@example.com"]',
            'emails[type eq "work" and value co "@example.com"] '
            'or ims[type eq "xmpp" and value co "@foo.com"]',
        ]
        for text in examples:
            parse(text)

    def test_whitespace_tolerated(self) -> None:
        assert parse('  a   eq\t"x"  ') == Compare("a", "eq", "x")


class TestParseErrors:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "a",
            "a foo 1",
            "a eq",
            "a co",
            "(a eq 1",
            "a eq 1)",
            "a eq 1 b",
            "a eq 1 and",
            "and a eq 1",
            "a eq 1 or or b eq 2",
            "a[b[c eq 1]]",
            "a[b eq 1",
            "a b eq 1",
            'a eq "unterminated',
            "a eq bareword",
            "a co 5",
            "a gt true",
            "a gt null",
            "not a eq 1",
            "not (a eq 1",
            "a eq 1 ]",
            "()",
            "1abc eq 2",
            "a eq 1 a eq 2",
            'a eq "x\\q"',
        ],
    )
    def test_invalid(self, text: str) -> None:
        with pytest.raises(ScimError) as exc:
            parse(text)
        assert exc.value.status == 400
        assert exc.value.scim_type == INVALID_FILTER
        assert exc.value.detail


class TestToLdap:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ('userName eq "bjensen"', "(uid=bjensen)"),
            ('userName ne "bjensen"', "(!(uid=bjensen))"),
            ('userName co "jen"', "(uid=*jen*)"),
            ('userName sw "bj"', "(uid=bj*)"),
            ('userName ew "en"', "(uid=*en)"),
            ("title pr", "(title=*)"),
            ('title gt "b"', "(&(title>=b)(!(title=b)))"),
            ('title ge "b"', "(title>=b)"),
            ('title lt "b"', "(&(title<=b)(!(title=b)))"),
            ('title le "b"', "(title<=b)"),
            ("active eq true", "(hrcActive=TRUE)"),
            ("active eq false", "(hrcActive=FALSE)"),
            ("title eq null", "(!(title=*))"),
            ("title ne null", "(title=*)"),
            ("title gt 5", "(&(title>=5)(!(title=5)))"),
            ('NAME.FAMILYNAME eq "x"', "(sn=x)"),
        ],
    )
    def test_operators(self, text: str, expected: str) -> None:
        assert ldap(text) == expected

    def test_logic(self) -> None:
        assert ldap('title pr and userName eq "a"') == "(&(title=*)(uid=a))"
        assert ldap('title pr or userName eq "a"') == "(|(title=*)(uid=a))"
        assert ldap("not (title pr)") == "(!(title=*))"

    def test_precedence(self) -> None:
        assert (
            ldap('title pr or userName eq "a" and active eq true')
            == "(|(title=*)(&(uid=a)(hrcActive=TRUE)))"
        )

    def test_value_path(self) -> None:
        assert (
            ldap('emails[type eq "work" and value co "@x.org"]')
            == "(&(mailType=work)(mail=*@x.org*))"
        )

    def test_value_path_sub(self) -> None:
        assert ldap('emails[type eq "work"].value co "z"') == "(&(mailType=work)(mail=*z*))"

    def test_urn_path_passes_full_lower_path(self) -> None:
        seen: list[str] = []

        def spy(path: str) -> str | None:
            seen.append(path)
            return "x"

        to_ldap(parse(f'{ENT}:employeeNumber eq "1"'), spy)
        assert seen == [f"{ENT}:employeeNumber".lower()]
        assert ldap(f'{ENT}:employeeNumber eq "1"') == "(employeeNumber=1)"

    def test_escaping(self) -> None:
        assert ldap('userName eq "a*b(c)d\\\\e"') == "(uid=a\\2ab\\28c\\29d\\5ce)"
        assert ldap('userName eq "a\\u0000b"') == "(uid=a\\00b)"
        assert ldap('userName co "*"') == "(uid=*\\2a*)"

    def test_injection_attempt(self) -> None:
        assert ldap('userName eq "x)(uid=*"') == "(uid=x\\29\\28uid=\\2a)"

    def test_unresolvable(self) -> None:
        with pytest.raises(ScimError) as exc:
            ldap('password eq "x"')
        assert exc.value.scim_type == INVALID_FILTER
        assert exc.value.status == 400

    def test_unresolvable_inside_value_path(self) -> None:
        with pytest.raises(ScimError):
            ldap('emails[bogus eq "x"]')


class TestAttributesOf:
    def test_collects(self) -> None:
        f = parse('userName eq "a" and (title pr or emails[type eq "work"])')
        assert attributes_of(f, resolve) == {"uid", "title", "mailType"}

    def test_unresolvable(self) -> None:
        with pytest.raises(ScimError):
            attributes_of(parse("nope pr"), resolve)


USER = {
    "userName": "BJensen",
    "name": {"givenName": "Barbara", "familyName": "Jensen"},
    "title": "Engineer",
    "active": True,
    "age": 42,
    "nick": "",
    "tags": [],
    "emails": [
        {"value": "bj@Example.com", "type": "work", "primary": True},
        {"value": "bj@home.org", "type": "home"},
    ],
    "members": [{"value": "u1"}, {"value": "u2"}],
    ENT: {"employeeNumber": "701984", "manager": {"value": "m1"}},
}


class TestMatches:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ('userName eq "bjensen"', True),
            ('USERNAME eq "BJENSEN"', True),
            ('userName ne "bjensen"', False),
            ('userName ne "other"', True),
            ('userName co "JEN"', True),
            ('userName sw "bj"', True),
            ('userName sw "jen"', False),
            ('userName ew "SEN"', True),
            ('name.familyName eq "jensen"', True),
            ('name.familyName eq "x"', False),
            ("title pr", True),
            ("nick pr", False),
            ("tags pr", False),
            ("missing pr", False),
            ("name pr", True),
            ("active eq true", True),
            ("active eq false", False),
            ("active eq 1", False),
            ("age eq 42", True),
            ("age gt 41", True),
            ("age gt 42", False),
            ("age ge 42", True),
            ("age lt 43", True),
            ("age le 41", False),
            ('age eq "42"', False),
            ('title gt "a"', True),
            ('title lt "a"', False),
            ('title gt "ENGINEER"', False),
            ('title ge "engineer"', True),
            ("missing eq null", True),
            ("title eq null", False),
            ("nick eq null", True),
            ("missing ne null", False),
            ('missing eq "x"', False),
            ('missing ne "x"', True),
            ('age co "4"', False),
            ('emails.value co "home"', True),
            ('emails.type eq "WORK"', True),
            ('emails.type ne "work"', False),
            ('emails[type eq "work" and value co "example.com"]', True),
            ('emails[type eq "home" and value co "example.com"]', False),
            ('emails[type eq "work" or type eq "none"]', True),
            ("emails[primary eq true]", True),
            ('emails[not (type eq "work")]', True),
            ('emails[type eq "work"].value co "example"', True),
            ('emails[type eq "work"].value co "home"', False),
            ('members[value eq "u2"]', True),
            ('members[value eq "u9"]', False),
            ('missing[value eq "u9"]', False),
            (f'{ENT}:employeeNumber eq "701984"', True),
            (f'{ENT}:employeeNumber eq "1"', False),
            (f"{ENT}:employeeNumber pr", True),
            (f"{ENT}:missing pr", False),
            (f'{ENT}:manager.value eq "m1"', True),
            ('urn:ietf:params:scim:schemas:core:2.0:User:userName eq "bjensen"', True),
            ('urn:other:2.0:Thing:attr eq "x"', False),
            ("title pr and active eq true", True),
            ("title pr and active eq false", False),
            ("nick pr or title pr", True),
            ("not (title pr)", False),
        ],
    )
    def test_cases(self, text: str, expected: bool) -> None:
        assert matches(parse(text), USER) is expected

    def test_does_not_mutate(self) -> None:
        import copy

        before = copy.deepcopy(USER)
        matches(parse('emails[type eq "work"]'), USER)
        assert before == USER

    def test_split_path(self) -> None:
        assert split_path("userName") == (None, "userName")
        assert split_path(f"{ENT}:employeeNumber") == (ENT, "employeeNumber")
        assert split_path(f"{ENT}:manager.value") == (ENT, "manager.value")
        assert split_path(ENT) == (ENT, "")
