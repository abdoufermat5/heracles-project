"""DN helpers (shared contract).

Minimal, dependency-free helpers. ``normalize`` is used everywhere DNs are
compared; keep its behaviour stable.
"""

from __future__ import annotations

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


def split(dn: str) -> list[str]:
    """Split a DN into RDN strings, honouring backslash escapes."""
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
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail or parts:
        parts.append(tail)
    return [p for p in parts if p]


def normalize(dn: str) -> str:
    """Canonical form for comparisons: trimmed RDNs, lower-cased, ``,`` joined."""
    normalized: list[str] = []
    for rdn in split(dn):
        attr, sep, value = rdn.partition("=")
        normalized.append(f"{attr.strip().lower()}{sep}{value.strip().lower()}")
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
