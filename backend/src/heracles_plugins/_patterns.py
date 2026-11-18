"""Bounds for regular expressions supplied by administrators and run by task runners.

A directory-provided pattern is matched against values the server reads, possibly many
times per run. An unbounded pattern (or an unbounded value) can therefore hold a worker
for minutes: patterns are length-limited, a simple static check refuses nested
quantifiers and overlapping quantified alternations (``(a+)+``, ``(a|a)+``), and
values are cut before they are tested.
"""

from __future__ import annotations

import re
from typing import Any

from heracles.i18n import _

#: Longest accepted expression.
MAX_PATTERN_LENGTH = 256
#: Longest part of a value a pattern is applied to.
MAX_VALUE_LENGTH = 256

_BRACE_QUANTIFIER = re.compile(r"\{\d+(?:,\d*)?\}")


class PatternError(ValueError):
    """The expression cannot be used (invalid, too long or potentially exponential)."""


_LITERAL_BRANCH = re.compile(r"[A-Za-z0-9_ .@-]+")


def _disjoint_literals(branches: list[str]) -> bool:
    """True when every branch is a plain literal and no two start with the same character."""
    if any(_LITERAL_BRANCH.fullmatch(branch) is None for branch in branches):
        return False
    firsts = [branch[0] for branch in branches]
    return len(set(firsts)) == len(firsts)


def _nested_quantifier(pattern: str) -> bool:
    """True when the pattern can take exponential time on a crafted value.

    Conservative and syntactic. Refused: a quantified group that contains another
    quantifier (``(a+)+``, ``((a+))+``) and a quantified group with alternation unless
    its branches are plain literals starting with distinct characters (``(a|a)+``,
    ``(a|ab)+``). Comments ``(?#...)``, character classes and escapes are skipped.
    """
    # Per open group: [contains a quantifier, index where the body starts, "|" positions].
    stack: list[list[Any]] = [[False, 0, []]]
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            index += 1
            if index < length and pattern[index] == "^":
                index += 1
            if index < length and pattern[index] == "]":
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
            index += 1
            if pattern.startswith("?#", index):
                # A comment ends at the first ``)``, whatever it contains.
                end = pattern.find(")", index)
                index = length if end < 0 else end + 1
                continue
            # ``(?:``, ``(?=``, ``(?P<name>``...: the ``?`` introduces the group, it is
            # not a quantifier of what precedes it.
            if index < length and pattern[index] == "?":
                index += 1
                if index < length and pattern[index] == "P":
                    index += 1
                if pattern.startswith(("<=", "<!"), index):
                    index += 2
                elif index < length and pattern[index] == "<":
                    while index < length and pattern[index] != ">":
                        index += 1
                    index += 1
                elif index < length and pattern[index] in ":=!":
                    index += 1
            stack.append([False, index, []])
            continue
        if char == ")":
            if len(stack) == 1:
                index += 1
                continue
            inner, start, bars = stack.pop()
            body_end = index
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
            if quantified:
                if inner:
                    return True
                if bars:
                    cuts = [start - 1, *bars, body_end]
                    branches = [pattern[cuts[i] + 1 : cuts[i + 1]] for i in range(len(cuts) - 1)]
                    if not _disjoint_literals(branches):
                        return True
            stack[-1][0] = stack[-1][0] or inner or quantified
            continue
        if char == "|":
            stack[-1][2].append(index)
        elif char in "*+?":
            stack[-1][0] = True
        elif char == "{":
            match = _BRACE_QUANTIFIER.match(pattern, index)
            if match is not None:
                stack[-1][0] = True
                index = match.end()
                continue
        index += 1
    return False


def pattern_problem(expression: str) -> str | None:
    """Why ``expression`` is refused, or ``None`` when it may be used."""
    if len(expression) > MAX_PATTERN_LENGTH:
        return _("The pattern is too long (at most {n} characters).").format(n=MAX_PATTERN_LENGTH)
    try:
        compiled = re.compile(expression)
    except re.error as exc:
        return _("Invalid regular expression: {error}").format(error=str(exc))
    if compiled.flags & re.VERBOSE:
        return _("The verbose flag (?x) is not allowed.")
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
