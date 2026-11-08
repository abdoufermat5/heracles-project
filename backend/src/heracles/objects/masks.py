"""Mask language of object templates: ``%[modifiers|]attribute%`` placeholders.

Pure functions: no directory access. The environment (clock, random source,
incremental counters) is injected through :class:`MaskEnv`.

Syntax
------
* ``%attr%`` is replaced by the value of ``attr``; ``%%`` is a literal ``%``.
  A value starting with ``%%`` is kept untouched, prefix included (binary data).
* ``%mods|attr%`` applies the modifiers left to right. A modifier is one
  character, optionally followed by bracketed, comma separated arguments
  (``s[0,1]``). Inside brackets a backslash escapes ``, [ ] % \\``; any other
  backslash sequence is kept (``\\d`` stays a regex class).
* Array modifiers (upper case or digit) work on all values of the attribute:
  ``F`` first, ``L`` last, ``J[sep]`` join (default separator: none), ``C``
  count, ``M[/regex/]`` keep matching values, ``4`` / ``6`` keep IPv4 / IPv6.
* String modifiers (lower case) work on the first value; ``t`` and ``s`` may
  produce several *candidates*:
  ``c`` comment (empty string, a missing attribute is then not an error),
  ``b`` base64 encode (``b[d]`` decode), ``u`` upper, ``l`` lower, ``i`` title
  case, ``a`` remove accents, ``t`` transliterate to ASCII (plain, then with
  expansions such as ``ä`` to ``ae``), ``p[from,to]`` regex replace (no
  argument: remove white space; one argument: remove the matches),
  ``s[start,length]`` substring (``start`` may be negative; ``length`` may be a
  range ``a-b`` giving one candidate per length, shortest first),
  ``r[min,max,charset]`` random string (``d`` digits, ``l`` letters, ``b`` both;
  default ``8,8,b``), ``d[date,format]`` date (default ``now`` and ``Y-m-d``;
  format ``epoch`` is the number of days since 1970-01-01; ``date`` may also be
  ``YYYY-MM-DD``, ``+3 days`` / ``-1 month`` style offsets, or ``@`` for the
  input value), ``n[id,start,step]`` incremental number.
* At the end the first value of what is left is used.
"""

from __future__ import annotations

import base64
import binascii
import calendar
import ipaddress
import itertools
import re
import secrets
import string
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

MAX_CANDIDATES = 64
ARRAY_MODIFIERS = "FLJCM46"
STRING_MODIFIERS = "cbulatpsrdni"
_ATTR_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.;-]*")
_ESCAPABLE = ",[]%\\|"


class MaskError(ValueError):
    """Invalid mask or impossible resolution."""


class MissingAttributeError(MaskError):
    """A referenced attribute has no value."""

    def __init__(self, attr: str) -> None:
        super().__init__(f"attribute {attr!r} has no value")
        self.attr = attr


class MaskCycleError(MaskError):
    """Template values reference each other in a loop."""

    def __init__(self, cycle: Sequence[str]) -> None:
        super().__init__("circular reference: " + " -> ".join(cycle))
        self.cycle = list(cycle)


@dataclass(frozen=True, slots=True)
class Modifier:
    """One parsed modifier."""

    code: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Literal:
    """Plain text."""

    text: str


@dataclass(frozen=True, slots=True)
class Placeholder:
    """``%mods|attr%``."""

    attr: str
    modifiers: tuple[Modifier, ...] = ()

    @property
    def optional(self) -> bool:
        """True when the ``c`` (comment) modifier makes the attribute optional."""
        return any(m.code == "c" for m in self.modifiers)


type Segment = Literal | Placeholder


# ------------------------------------------------------------------ parsing


def _unescape(raw: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw) and raw[i + 1] in _ESCAPABLE:
            out.append(raw[i + 1])
            i += 2
        else:
            out.append(raw[i])
            i += 1
    return "".join(out)


def _close_bracket(text: str, start: int) -> int:
    """Index of the ``]`` closing the bracket opened just before ``start``."""
    depth = 1
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise MaskError("unbalanced '[' in modifier arguments")


def _split_args(raw: str) -> tuple[str, ...]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            current.append(raw[i : i + 2])
            i += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    parts.append("".join(current))
    return tuple(_unescape(p) for p in parts)


def parse_modifiers(text: str) -> tuple[Modifier, ...]:
    """Parse the modifier part of a placeholder."""
    out: list[Modifier] = []
    i = 0
    while i < len(text):
        code = text[i]
        if code not in ARRAY_MODIFIERS + STRING_MODIFIERS:
            raise MaskError(f"unknown modifier {code!r}")
        i += 1
        args: tuple[str, ...] = ()
        if i < len(text) and text[i] == "[":
            end = _close_bracket(text, i + 1)
            raw = text[i + 1 : end]
            args = (_unescape(raw),) if code in "JM" else _split_args(raw)
            i = end + 1
        out.append(Modifier(code, args))
    return tuple(out)


def _find_end(value: str, start: int) -> int:
    depth = 0
    i = start
    while i < len(value):
        ch = value[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "%" and depth <= 0:
            return i
        i += 1
    raise MaskError("unterminated placeholder (use '%%' for a literal '%')")


def _split_modifiers(content: str) -> tuple[str, str]:
    depth = 0
    i = 0
    while i < len(content):
        ch = content[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "|" and depth <= 0:
            return content[:i], content[i + 1 :]
        i += 1
    return "", content


def parse_mask(value: str) -> tuple[Segment, ...]:
    """Split ``value`` into literals and placeholders."""
    if value.startswith("%%"):
        return (Literal(value),)
    segments: list[Segment] = []
    buf: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != "%":
            buf.append(ch)
            i += 1
            continue
        if value[i + 1 : i + 2] == "%":
            buf.append("%")
            i += 2
            continue
        end = _find_end(value, i + 1)
        mods_text, attr = _split_modifiers(value[i + 1 : end])
        attr = attr.strip()
        if _ATTR_RE.fullmatch(attr) is None:
            raise MaskError(f"invalid attribute name {attr!r}")
        if buf:
            segments.append(Literal("".join(buf)))
            buf = []
        segments.append(Placeholder(attr, parse_modifiers(mods_text)))
        i = end + 1
    if buf:
        segments.append(Literal("".join(buf)))
    return tuple(segments)


def references(value: str) -> list[Placeholder]:
    """Placeholders of ``value`` (raises :class:`MaskError` if it is not valid)."""
    return [s for s in parse_mask(value) if isinstance(s, Placeholder)]


# --------------------------------------------------------------- evaluation


def _now() -> datetime:
    return datetime.now(UTC)


def _no_counter(id_: str, start: int, step: int) -> int:
    del id_, step
    return start


@dataclass(slots=True)
class MaskEnv:
    """Side-effect providers of the evaluation (replaceable in tests)."""

    now: Callable[[], datetime] = _now
    choice: Callable[[str], str] = secrets.choice
    randint: Callable[[int, int], int] = lambda lo, hi: lo + secrets.randbelow(hi - lo + 1)
    counter: Callable[[str, int, int], int] = _no_counter


_SPECIAL_LETTERS = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "Ä": "Ae",
    "Ö": "Oe",
    "Ü": "Ue",
    "ß": "ss",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ø": "o",
    "Ø": "O",
    "đ": "d",
    "Đ": "D",
    "ł": "l",
    "Ł": "L",
    "þ": "th",
    "Þ": "Th",
}


def strip_accents(text: str) -> str:
    """Remove combining marks (``é`` -> ``e``)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _ascii(text: str) -> str:
    return strip_accents(text).encode("ascii", "ignore").decode("ascii")


def transliterate(text: str) -> list[str]:
    """ASCII candidates of ``text``: plain, then with language specific expansions."""
    plain = _ascii(text)
    expanded = _ascii("".join(_SPECIAL_LETTERS.get(c, c) for c in text))
    return list(dict.fromkeys([plain, expanded]))


def _int_arg(modifier: Modifier, index: int, default: int) -> int:
    if index >= len(modifier.args) or modifier.args[index].strip() == "":
        return default
    try:
        return int(modifier.args[index].strip())
    except ValueError:
        raise MaskError(
            f"modifier {modifier.code!r}: {modifier.args[index]!r} is not a number"
        ) from None


def _regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise MaskError(f"invalid regular expression {pattern!r}: {exc}") from None


def _array_modifier(mod: Modifier, values: list[str]) -> list[str]:
    match mod.code:
        case "F":
            return values[:1]
        case "L":
            return values[-1:]
        case "J":
            return [(mod.args[0] if mod.args else "").join(values)]
        case "C":
            return [str(len(values))]
        case "M":
            raw = mod.args[0] if mod.args else ""
            if len(raw) >= 2 and raw.startswith("/") and raw.endswith("/"):
                raw = raw[1:-1]
            rx = _regex(raw)
            return [v for v in values if rx.search(v)]
        case "4" | "6":
            wanted = 4 if mod.code == "4" else 6
            kept: list[str] = []
            for v in values:
                try:
                    if ipaddress.ip_address(v.strip()).version == wanted:
                        kept.append(v)
                except ValueError:
                    continue
            return kept
        case _:
            raise MaskError(f"unknown array modifier {mod.code!r}")


_MONTHS = [calendar.month_name[i] for i in range(1, 13)]
_DAYS = [calendar.day_name[i] for i in range(7)]
_OFFSET_RE = re.compile(r"([+-]\d+)\s*(hour|day|week|month|year)s?", re.IGNORECASE)


def _add_months(day: datetime, months: int) -> datetime:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return day.replace(year=year, month=month + 1, day=min(day.day, last))


def _parse_date(spec: str, current: str, env: MaskEnv) -> datetime:
    spec = spec.strip()
    if spec in ("", "now"):
        return env.now()
    if spec == "@":
        spec = current.strip()
    match = _OFFSET_RE.fullmatch(spec)
    if match:
        amount, unit = int(match.group(1)), match.group(2).lower()
        base = env.now()
        if unit == "hour":
            return base + timedelta(hours=amount)
        if unit == "day":
            return base + timedelta(days=amount)
        if unit == "week":
            return base + timedelta(weeks=amount)
        if unit == "month":
            return _add_months(base, amount)
        return _add_months(base, amount * 12)
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(spec, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise MaskError(f"invalid date {spec!r}")


def format_date(moment: datetime, fmt: str) -> str:
    """Format with a small subset of the usual date format letters.

    ``Y y m n d j H G i s M F D l U`` are supported; ``\\x`` outputs ``x``;
    ``epoch`` is the number of days since 1970-01-01.
    """
    if fmt == "epoch":
        return str((moment.date() - date(1970, 1, 1)).days)
    out: list[str] = []
    i = 0
    while i < len(fmt):
        ch = fmt[i]
        i += 1
        if ch == "\\" and i < len(fmt):
            out.append(fmt[i])
            i += 1
            continue
        table: dict[str, str] = {
            "Y": f"{moment.year:04d}",
            "y": f"{moment.year % 100:02d}",
            "m": f"{moment.month:02d}",
            "n": str(moment.month),
            "d": f"{moment.day:02d}",
            "j": str(moment.day),
            "H": f"{moment.hour:02d}",
            "G": str(moment.hour),
            "i": f"{moment.minute:02d}",
            "s": f"{moment.second:02d}",
            "M": _MONTHS[moment.month - 1][:3],
            "F": _MONTHS[moment.month - 1],
            "D": _DAYS[moment.weekday()][:3],
            "l": _DAYS[moment.weekday()],
            "U": str(int(moment.timestamp())),
        }
        out.append(table.get(ch, ch))
    return "".join(out)


_CHARSETS = {
    "d": string.digits,
    "l": string.ascii_letters,
    "b": string.ascii_letters + string.digits,
}


def _string_modifier(mod: Modifier, text: str, env: MaskEnv) -> list[str]:
    code = mod.code
    if code == "c":
        return [""]
    if code == "b":
        if mod.args and mod.args[0].strip() == "d":
            try:
                return [base64.b64decode(text.encode(), validate=True).decode("utf-8")]
            except (binascii.Error, UnicodeDecodeError):
                raise MaskError("value is not valid base64 text") from None
        return [base64.b64encode(text.encode("utf-8")).decode("ascii")]
    if code == "u":
        return [text.upper()]
    if code == "l":
        return [text.lower()]
    if code == "i":
        return [re.sub(r"[^\W_]+", lambda m: m.group().capitalize(), text)]
    if code == "a":
        return [strip_accents(text)]
    if code == "t":
        return transliterate(text)
    if code == "p":
        args = list(mod.args)
        if not args or (len(args) == 1 and args[0] == ""):
            return [re.sub(r"\s+", "", text)]
        replacement = args[1] if len(args) > 1 else ""
        return [_regex(args[0]).sub(replacement, text)]
    if code == "s":
        return _substring(mod, text)
    if code == "r":
        low, high = _int_arg(mod, 0, 8), _int_arg(mod, 1, 8)
        charset = _CHARSETS.get(mod.args[2].strip() if len(mod.args) > 2 else "b")
        if charset is None or low < 0 or high < low or high > 256:
            raise MaskError("invalid random string arguments")
        size = env.randint(low, high)
        return ["".join(env.choice(charset) for _ in range(size))]
    if code == "d":
        spec = mod.args[0] if mod.args else "now"
        fmt = mod.args[1] if len(mod.args) > 1 else "Y-m-d"
        return [format_date(_parse_date(spec, text, env), fmt)]
    if code == "n":
        ident = mod.args[0].strip() if mod.args and mod.args[0].strip() else "default"
        if ";" in ident:
            raise MaskError("counter identifiers cannot contain ';'")
        return [str(env.counter(ident, _int_arg(mod, 1, 0), _int_arg(mod, 2, 1)))]
    raise MaskError(f"unknown string modifier {code!r}")  # pragma: no cover


def _substring(mod: Modifier, text: str) -> list[str]:
    start = _int_arg(mod, 0, 0)
    if start < 0:
        start = max(0, len(text) + start)
    rest = text[start:]
    spec = mod.args[1].strip() if len(mod.args) > 1 else ""
    if not spec:
        return [rest]
    bounds = re.fullmatch(r"(\d+)(?:-(\d+))?", spec)
    if bounds is None:
        raise MaskError(f"invalid substring length {spec!r}")
    low = int(bounds.group(1))
    high = int(bounds.group(2)) if bounds.group(2) is not None else low
    if high < low:
        raise MaskError(f"invalid substring length {spec!r}")
    return list(dict.fromkeys(rest[:n] for n in range(low, min(high, len(rest)) + 1)))


def evaluate_placeholder(ph: Placeholder, values: Sequence[str], env: MaskEnv) -> list[str]:
    """Candidate strings of one placeholder applied to the attribute ``values``."""
    arrays: list[list[str]] = [list(values)]
    for mod in ph.modifiers:
        nxt: list[list[str]] = []
        for array in arrays:
            if mod.code in ARRAY_MODIFIERS:
                nxt.append(_array_modifier(mod, array))
            else:
                first = array[0] if array else ""
                nxt.extend([c] for c in _string_modifier(mod, first, env))
        arrays = nxt[:MAX_CANDIDATES]
    out = [a[0] if a else "" for a in arrays]
    return list(dict.fromkeys(out))


type Lookup = Callable[[str], Sequence[str] | None]


def candidates(value: str, lookup: Lookup, env: MaskEnv) -> list[str]:
    """Every resolved form of ``value`` (cartesian product of the placeholders' candidates).

    ``lookup(attr)`` returns the values of an attribute (case-insensitive name) or
    ``None``. A missing attribute raises :class:`MissingAttributeError` unless the
    placeholder uses the ``c`` modifier.
    """
    parts: list[list[str]] = []
    for seg in parse_mask(value):
        if isinstance(seg, Literal):
            parts.append([seg.text])
            continue
        found = lookup(seg.attr)
        if not found and not seg.optional:
            raise MissingAttributeError(seg.attr)
        parts.append(evaluate_placeholder(seg, list(found or []), env) or [""])
    out: list[str] = []
    for combo in itertools.islice(itertools.product(*parts), MAX_CANDIDATES):
        text = "".join(combo)
        if text not in out:
            out.append(text)
    return out or [""]


# ---------------------------------------------------------- whole templates


def required_fields(definitions: Mapping[str, Sequence[str]]) -> list[str]:
    """Attributes referenced (not optionally) but not defined by the template.

    ``definitions`` maps attribute names to raw template values. Result keeps the
    first-seen order and the spelling of the first reference.
    """
    defined = {k.lower() for k in definitions}
    found: dict[str, str] = {}
    for values in definitions.values():
        for raw in values:
            for ph in references(raw):
                key = ph.attr.lower()
                if not ph.optional and key not in defined:
                    found.setdefault(key, ph.attr)
    return list(found.values())


def resolution_order(
    definitions: Mapping[str, Sequence[str]], supplied: Collection[str] = ()
) -> list[str]:
    """Defined attributes in dependency order; raises :class:`MaskCycleError`.

    Attributes in ``supplied`` (user provided) are not resolved and break loops.
    Keys of the result are lower-cased.
    """
    defs = {k.lower(): v for k, v in definitions.items()}
    given = {k.lower() for k in supplied}
    deps: dict[str, list[str]] = {}
    for key, values in defs.items():
        if key in given:
            continue
        refs = {ph.attr.lower() for raw in values for ph in references(raw)}
        deps[key] = sorted(r for r in refs if r in defs and r not in given)
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(key: str, path: list[str]) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            start = path.index(key)
            raise MaskCycleError([*path[start:], key])
        state[key] = 1
        for dep in deps.get(key, []):
            visit(dep, [*path, key])
        state[key] = 2
        order.append(key)

    for key in deps:
        visit(key, [])
    return order


def resolve_definitions(
    definitions: Mapping[str, Sequence[str]],
    supplied: Mapping[str, Sequence[str]],
    env: MaskEnv,
    choose: Callable[[str, list[str]], str] | None = None,
) -> dict[str, list[str]]:
    """Resolve every defined attribute (lower-cased keys), dependencies first.

    ``supplied`` holds user provided values; they take precedence over the
    template definition. ``choose(attr, candidates)`` picks among the candidates
    of one value (default: the first one); empty results are dropped.
    """
    known: dict[str, list[str]] = {k.lower(): list(v) for k, v in supplied.items() if v}
    defs = {k.lower(): v for k, v in definitions.items()}
    for key in resolution_order(definitions, list(known)):
        resolved: list[str] = []
        for raw in defs[key]:
            options = candidates(raw, lambda a: known.get(a.lower()), env)
            picked = choose(key, options) if choose is not None else options[0]
            if picked != "":
                resolved.append(picked)
        if resolved:
            known[key] = resolved
    return {k: v for k, v in known.items() if k in defs and k not in {s.lower() for s in supplied}}


@dataclass(slots=True)
class CounterState:
    """Incremental counters (``<id>;<value>`` strings) with pending updates."""

    stored: dict[str, int] = field(default_factory=lambda: {})
    pending: dict[str, int] = field(default_factory=lambda: {})

    @classmethod
    def parse(cls, values: Sequence[str]) -> CounterState:
        stored: dict[str, int] = {}
        for raw in values:
            ident, sep, number = raw.rpartition(";")
            if not sep:
                continue
            try:
                stored[ident] = int(number)
            except ValueError:
                continue
        return cls(stored)

    def next(self, ident: str, start: int, step: int) -> int:
        """Next value for ``ident`` (``start`` the first time), recorded as pending."""
        last = self.pending.get(ident, self.stored.get(ident))
        value = start if last is None else last + step
        self.pending[ident] = value
        return value

    def serialise(self) -> list[str]:
        merged = {**self.stored, **self.pending}
        return [f"{ident};{value}" for ident, value in sorted(merged.items())]


__all__ = [
    "ARRAY_MODIFIERS",
    "MAX_CANDIDATES",
    "STRING_MODIFIERS",
    "CounterState",
    "Literal",
    "MaskCycleError",
    "MaskEnv",
    "MaskError",
    "MissingAttributeError",
    "Modifier",
    "Placeholder",
    "candidates",
    "evaluate_placeholder",
    "format_date",
    "parse_mask",
    "parse_modifiers",
    "references",
    "required_fields",
    "resolution_order",
    "resolve_definitions",
    "strip_accents",
    "transliterate",
]
