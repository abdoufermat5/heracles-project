"""DN helpers (shared contract).

Minimal, dependency-free helpers. ``normalize`` is used everywhere DNs are
compared; keep its behaviour stable.
"""

from __future__ import annotations

from functools import lru_cache

_SPECIAL = ',+"\\<>;='


def escape_rdn_value(value: str) -> str:
    """Escape an RDN attribute value (RFC 4514)."""
    out: list[str] = []
    for i, ch in enumerate(value):
        if ch in _SPECIAL or (ch == "#" and i == 0) or (ch == " " and i in (0, len(value) - 1)):
            out.append("\\" + ch)
        elif ch == "\x00":
            out.append("\\00")
        else:
            out.append(ch)
    return "".join(out)


def _is_escaped(text: str, index: int) -> bool:
    """True when the character at ``index`` is preceded by an odd number of backslashes."""
    count = 0
    while index - 1 - count >= 0 and text[index - 1 - count] == "\\":
        count += 1
    return count % 2 == 1


def strip_rdn(text: str) -> str:
    """Trim surrounding whitespace; an escaped trailing space is part of the value."""
    text = text.lstrip()
    end = len(text)
    while end and text[end - 1].isspace() and not _is_escaped(text, end - 1):
        end -= 1
    return text[:end]


def split(dn: str) -> list[str]:
    """Split a DN into RDN strings, honouring backslash escapes."""
    if "\\" not in dn:  # nothing escaped: every comma separates
        return [p for p in (part.strip() for part in dn.split(",")) if p]
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for ch in dn:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            current.append(ch)
            escaped = True
        elif ch == ",":
            parts.append(strip_rdn("".join(current)))
            current = []
        else:
            current.append(ch)
    tail = strip_rdn("".join(current))
    if tail or parts:
        parts.append(tail)
    return [p for p in parts if p]


_HEX = frozenset("0123456789abcdefABCDEF")
#: Characters that must be escaped inside an RDN value (RFC 4514 section 2.4).
_VALUE_SPECIAL = frozenset('"+,;<>\\')


def unescape_rdn_value(value: str) -> str:
    """Decode the escapes of an RDN value: ``\\<char>`` and ``\\XX`` (UTF-8 hex pairs)."""
    if "\\" not in value:
        return value
    out = bytearray()
    i = 0
    size = len(value)
    while i < size:
        ch = value[i]
        if ch == "\\" and i + 1 < size:
            pair = value[i + 1 : i + 3]
            if len(pair) == 2 and pair[0] in _HEX and pair[1] in _HEX:
                out.append(int(pair, 16))
                i += 3
            else:
                out += value[i + 1].encode("utf-8", "surrogatepass")
                i += 2
            continue
        out += ch.encode("utf-8", "surrogatepass")
        i += 1
    return out.decode("utf-8", "surrogateescape")


def _canonical_value(value: str) -> str:
    """Lower-cased value in one escaping style, so that ``\\,``, ``\\2c`` and ``\\2C`` agree."""
    text = unescape_rdn_value(strip_rdn(value)).lower()
    last = len(text) - 1
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch in _VALUE_SPECIAL or (i == 0 and ch in "# ") or (i == last and ch == " "):
            out.append("\\" + ch)
        elif ch == "\x00":
            out.append("\\00")
        else:
            out.append(ch)
    return "".join(out)


@lru_cache(maxsize=32768)
def normalize(dn: str) -> str:
    """Canonical form for comparisons: trimmed RDNs, lower-cased, ``,`` joined.

    Memoised: the same DNs are compared over and over (ACL evaluation, sorting).
    """
    normalized: list[str] = []
    for rdn in split(dn):
        attr, sep, value = rdn.partition("=")
        normalized.append(f"{attr.strip().lower()}{sep}{_canonical_value(value)}")
    return ",".join(normalized)


def parent(dn: str) -> str | None:
    """Parent DN, or ``None`` for a single-RDN DN."""
    parts = split(dn)
    return ",".join(parts[1:]) if len(parts) > 1 else None


def rdn(dn: str) -> str:
    """First RDN of ``dn``."""
    parts = split(dn)
    return parts[0] if parts else ""


def depth(dn: str) -> int:
    """Number of RDN components."""
    return len(split(dn))


def is_descendant(dn: str, ancestor: str, *, include_self: bool = True) -> bool:
    """True if ``dn`` is below ``ancestor`` (case-insensitive)."""
    d, a = normalize(dn), normalize(ancestor)
    if d == a:
        return include_self
    return d.endswith("," + a)


def _clean_fragment(fragment: str) -> str:
    """Trim whitespace and separating commas, keeping escaped trailing characters."""
    text = fragment.lstrip().lstrip(",").lstrip()
    while text and text[-1] in (" ", ","):
        body = text[:-1]
        # A character preceded by an odd number of backslashes is escaped: keep it.
        if (len(body) - len(body.rstrip("\\"))) % 2 == 1:
            break
        text = body
    return text


def join(*parts: str) -> str:
    """Join DN fragments, ignoring empty ones and separating commas.

    Escaped trailing characters (``\\ `` or ``\\,``) are preserved.
    """
    return ",".join(c for c in (_clean_fragment(p) for p in parts if p) if c)
