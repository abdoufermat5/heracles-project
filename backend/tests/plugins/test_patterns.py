"""Bounds applied to administrator-provided regular expressions of task runners."""

from __future__ import annotations

import re

import pytest

from heracles_plugins import _patterns as patterns


def test_pattern_length_is_capped() -> None:
    assert patterns.pattern_problem("a" * patterns.MAX_PATTERN_LENGTH) is None
    problem = patterns.pattern_problem("a" * (patterns.MAX_PATTERN_LENGTH + 1))
    assert problem is not None and "too long" in problem


def test_invalid_pattern_is_reported() -> None:
    assert patterns.pattern_problem("(") is not None
    with pytest.raises(patterns.PatternError):
        patterns.compile_checked("(")


@pytest.mark.parametrize(
    "expression",
    ["(a+)+", "(a*)*", r"(\d+){2,}", "((a+))+", "(?:a+)+", "(a+)?"],
)
def test_nested_quantifiers_are_refused(expression: str) -> None:
    # ``(a+)?`` is refused too: conservative, an optional unbounded group is still quadratic.
    problem = patterns.pattern_problem(expression)
    assert problem is not None and "quantifier" in problem


@pytest.mark.parametrize(
    "expression",
    [
        "^stu-",
        r"mail:@example\.com$",
        "(?:ab)+",
        "(a|b)+",
        "a+?",
        "(a|a)+?",
        r"\(a\+\)\+",
        "[a+]+",
        "^a{2,4}$",
    ],
)
def test_ordinary_patterns_are_accepted(expression: str) -> None:
    assert patterns.pattern_problem(expression) is None


def test_search_cuts_the_tested_value() -> None:
    long_value = "a" * (patterns.MAX_VALUE_LENGTH + 44)
    long_pattern = re.compile(f"^a{{{patterns.MAX_VALUE_LENGTH + 44}}}$")
    exact_pattern = re.compile(f"^a{{{patterns.MAX_VALUE_LENGTH}}}$")
    assert patterns.search(long_pattern, long_value) is False
    assert patterns.search(exact_pattern, long_value) is True
