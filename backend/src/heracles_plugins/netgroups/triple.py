"""NIS netgroup triple parsing, formatting, and attribute descriptor."""

from __future__ import annotations

from typing import Any

from heracles.attributes import StringAttr, ValidationError
from heracles.i18n import _


def parse_triple(text: str) -> tuple[str, str, str] | None:
    """Parse '(hostname,username,domainname)' into (host, user, domain), or None if invalid."""
    s = text.strip()
    if not (s.startswith("(") and s.endswith(")")):
        return None
    inner = s[1:-1]
    parts = inner.split(",")
    if len(parts) != 3:
        return None
    return parts[0].strip(), parts[1].strip(), parts[2].strip()


def format_triple(host: str = "", user: str = "", domain: str = "") -> str:
    """Format a netgroup triple '(hostname,username,domainname)'."""
    return f"({host},{user},{domain})"


class TripleAttr(StringAttr):
    """An RFC 2307 NIS netgroup triple '(hostname,username,domainname)'."""

    kind = "triple"

    def __init__(self, name: str, label: str, **kwargs: Any) -> None:
        super().__init__(name, label, **kwargs)

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        if parse_triple(value) is None:
            errors.append(
                _("Invalid NIS netgroup triple format: expected '(hostname,username,domainname)'.")
            )
        return errors

    def from_json(self, data: object) -> str | None:
        if data is None or data == "":
            return None
        if isinstance(data, dict):
            raw_dict: dict[object, object] = data  # pyright: ignore[reportUnknownVariableType]
            host = str(raw_dict.get("host") or "").strip()
            user = str(raw_dict.get("user") or "").strip()
            domain = str(raw_dict.get("domain") or "").strip()
            return format_triple(host, user, domain)
        if isinstance(data, str):
            parsed = parse_triple(data)
            if parsed is None:
                raise ValidationError(
                    _(
                        "Invalid NIS netgroup triple format: "
                        "expected '(hostname,username,domainname)'."
                    )
                )
            return format_triple(*parsed)
        raise ValidationError(_("Expected a string or triple object."))

    def to_ldap(self, value: str | None) -> list[bytes]:
        if not value or not value.strip():
            return []
        parsed = parse_triple(value)
        if parsed is None:
            return [value.strip().encode("utf-8")]
        return [format_triple(*parsed).encode("utf-8")]
