"""Bounds for regular expressions supplied by administrators and run by task runners.

A directory-provided pattern is matched against values the server reads, possibly many
times per run. An unbounded pattern (or an unbounded value) can therefore hold a worker
for minutes: patterns are length-limited, a simple static check refuses nested
quantifiers (the classic exponential form ``(a+)+``), and values are cut before they are
tested.
"""

from __future__ import annotations

import re

from heracles.i18n import _

#: Longest accepted expression.
MAX_PATTERN_LENGTH = 256
#: Longest part of a value a pattern is applied to.
MAX_VALUE_LENGTH = 256

_BRACE_QUANTIFIER = re.compile(r"\{\d+(?:,\d*)?\}")


class PatternError(ValueError):
    """The expression cannot be used (invalid, too long or potentially exponential)."""


def _nested_quantifier(pattern: str) -> bool:
    """True when a quantified group contains another quantifier (``(a+)+``).

    Conservative and syntactic: a group that contains a quantifier and is itself
    quantified is refused, including a quantifier inherited from a nested group
    (``((a+))+``). Character classes and escapes are skipped.
    """
    inside = [False]
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            index += 1
            while index < length:
                if pattern[index] == "\\":
                    index += 2
                    continue
                if pattern[index] == "]":
                    index += 1
                    break
                index += 1
            continue
        if char == "(":
            inside.append(False)
            index += 1
            # ``(?:``, ``(?=``, ``(?P<name>``...: the ``?`` introduces the group, it is
            # not a quantifier of what precedes it.
            if index < length and pattern[index] == "?":
                index += 1
                if index < length and pattern[index] == "P":
                    index += 1
                if index < length and pattern[index] == "<":
                    while index < length and pattern[index] not in ">":
                        index += 1
                    index += 1
                elif index < length and pattern[index] in ":=!":
                    index += 1
            continue
        if char == ")":
            inner = inside.pop() if len(inside) > 1 else False
            index += 1
            quantified = False
            if index < length and pattern[index] in "*+?":
                quantified = True
                index += 1
            elif index < length and pattern[index] == "{":
                match = _BRACE_QUANTIFIER.match(pattern, index)
                if match is not None:
                    quantified = True
                    index = match.end()
            if inner and quantified:
                return True
            inside[-1] = inside[-1] or inner or quantified
            continue
        if char in "*+?":
            inside[-1] = True
        elif char == "{":
            match = _BRACE_QUANTIFIER.match(pattern, index)
            if match is not None:
                inside[-1] = True
                index = match.end()
                continue
        index += 1
    return False


def pattern_problem(expression: str) -> str | None:
    """Why ``expression`` is refused, or ``None`` when it may be used."""
    if len(expression) > MAX_PATTERN_LENGTH:
        return _("The pattern is too long (at most {n} characters).").format(n=MAX_PATTERN_LENGTH)
    try:
        re.compile(expression)
    except re.error as exc:
        return _("Invalid regular expression: {error}").format(error=str(exc))
    if _nested_quantifier(expression):
        return _("The pattern nests quantifiers (such as (a+)+), which can take exponential time.")
    return None


def compile_checked(expression: str) -> re.Pattern[str]:
    """Compile an administrator pattern, refusing unsafe ones with :class:`PatternError`."""
    problem = pattern_problem(expression)
    if problem is not None:
        raise PatternError(problem)
    return re.compile(expression)


def search(regex: re.Pattern[str], value: str) -> bool:
    """Match a value, cut to :data:`MAX_VALUE_LENGTH` so a pathological input stays bounded."""
    return regex.search(value[:MAX_VALUE_LENGTH]) is not None
