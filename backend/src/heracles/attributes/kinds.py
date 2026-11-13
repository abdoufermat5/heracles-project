"""Concrete attribute kinds (single-valued scalars, text, binary, references)."""

from __future__ import annotations

import base64
import binascii
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from heracles.attributes.base import (
    JSON,
    Attribute,
    PasswordHasher,
    ValidationError,
    is_empty,
)
from heracles.i18n import _
from heracles.ldap import dn as dnlib

# ---------------------------------------------------------------------------
# Text family
# ---------------------------------------------------------------------------


class _StrAttr(Attribute[str]):
    """Base for kinds stored as a UTF-8 string."""

    def from_ldap(self, values: list[bytes]) -> str | None:
        if not values:
            return None
        return values[0].decode("utf-8", errors="replace")

    def to_ldap(self, value: str | None) -> list[bytes]:
        if value is None or value == "":
            return []
        return [value.encode("utf-8")]

    def from_json(self, data: object) -> str | None:
        if data is None:
            return None
        if not isinstance(data, str):
            raise ValidationError(_("Expected a string."))
        return data if data != "" else None

    def to_json(self, value: str | None) -> JSON:
        return value

    def _validate(self, value: str) -> list[str]:
        return self._check_text(value)


class StringAttr(_StrAttr):
    """Single-line text."""

    kind = "string"


class TextAttr(_StrAttr):
    """Multi-line text."""

    kind = "text"


_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+|[^@\s]+@[^@\s]+")
_PHONE_RE = re.compile(r"\+?[0-9(][0-9 ().\-/]{2,}")
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:\S+")


class EmailAttr(_StrAttr):
    """E-mail address."""

    kind = "email"

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        if _EMAIL_RE.fullmatch(value) is None:
            errors.append(_("Invalid email address."))
        return errors


class PhoneAttr(_StrAttr):
    """Telephone number (digits, spaces and ``+ ( ) . - /``)."""

    kind = "phone"

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        if _PHONE_RE.fullmatch(value) is None:
            errors.append(_("Invalid phone number."))
        return errors


class UrlAttr(_StrAttr):
    """URL with a scheme."""

    kind = "url"

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        if _URL_RE.fullmatch(value) is None:
            errors.append(_("Invalid URL."))
        return errors


class HiddenAttr(_StrAttr):
    """Stored string that is never shown in forms."""

    kind = "hidden"


class PostalAddressAttr(_StrAttr):
    """Postal address: lines separated by ``$`` in LDAP, newlines in Python/JSON.

    ``\\`` and ``$`` inside a line are escaped as ``\\5C`` and ``\\24``.
    """

    kind = "postal_address"

    def from_ldap(self, values: list[bytes]) -> str | None:
        raw = super().from_ldap(values)
        if raw is None:
            return None
        return "\n".join(_unescape_address(line) for line in raw.split("$"))

    def to_ldap(self, value: str | None) -> list[bytes]:
        if value is None or value.strip() == "":
            return []
        lines = [
            line.strip().replace("\\", "\\5C").replace("$", "\\24")
            for line in value.replace("\r\n", "\n").split("\n")
        ]
        return ["$".join(lines).encode("utf-8")]

    def from_json(self, data: object) -> str | None:
        text = super().from_json(data)
        return text.replace("\r\n", "\n") if text is not None else None


def _unescape_address(line: str) -> str:
    return re.sub(
        r"\\(24|5[cC])",
        lambda m: "$" if m.group(1) == "24" else "\\",
        line,
    )


# ---------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------

_default_hasher: PasswordHasher | None = None


def set_default_password_hasher(hasher: PasswordHasher | None) -> None:
    """Install the process-wide hasher used by password attributes."""
    global _default_hasher
    _default_hasher = hasher


#: ``checker(new_password) -> problems`` (password policy), run during validation.
type PasswordChecker = Callable[[str], list[str]]

_default_checker: PasswordChecker | None = None


def set_default_password_checker(checker: PasswordChecker | None) -> None:
    """Install the process-wide password policy check used by password attributes."""
    global _default_checker
    _default_checker = checker


class PasswordAttr(_StrAttr):
    """Write-only password.

    Python/JSON value semantics: ``None`` = unchanged, ``""`` = remove, any
    other string = new clear-text password (hashed by the injected hasher in
    :meth:`to_ldap`). The value read from the directory is always ``None``.
    """

    kind = "password"
    write_only = True

    def __init__(self, *args: Any, hasher: PasswordHasher | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.hasher = hasher

    def from_ldap(self, values: list[bytes]) -> str | None:
        return None

    def to_ldap(self, value: str | None) -> list[bytes]:
        if value is None or value == "":
            return []
        hasher = self.hasher or _default_hasher
        if hasher is None:
            raise RuntimeError("no password hasher configured")
        return [hasher(value).encode("utf-8")]

    def from_json(self, data: object) -> str | None:
        if data is None:
            return None
        if not isinstance(data, str):
            raise ValidationError(_("Expected a string."))
        return data

    def to_json(self, value: str | None) -> JSON:
        return None

    def validate(self, value: str | None) -> list[str]:
        if value is None:
            return []  # unchanged; "required" is enforced by the service on creation
        if value == "":
            return [_("This field is required.")] if self.required else []
        problems = self._check_text(value)
        if not problems and _default_checker is not None:
            problems = list(_default_checker(value))
        return problems


# ---------------------------------------------------------------------------
# Numbers and booleans
# ---------------------------------------------------------------------------


class IntAttr(Attribute[int]):
    """Integer."""

    kind = "int"

    def from_ldap(self, values: list[bytes]) -> int | None:
        if not values:
            return None
        try:
            return int(values[0].decode("ascii").strip())
        except (ValueError, UnicodeDecodeError):
            return None

    def to_ldap(self, value: int | None) -> list[bytes]:
        return [] if value is None else [str(value).encode("ascii")]

    def from_json(self, data: object) -> int | None:
        if data is None:
            return None
        if isinstance(data, bool) or not isinstance(data, int | float):
            raise ValidationError(_("Expected a number."))
        if isinstance(data, float):
            if not data.is_integer():
                raise ValidationError(_("Expected an integer."))
            return int(data)
        return data

    def to_json(self, value: int | None) -> JSON:
        return value

    def _validate(self, value: int) -> list[str]:
        return self._check_range(value)


class FloatAttr(Attribute[float]):
    """Floating point number."""

    kind = "float"

    def from_ldap(self, values: list[bytes]) -> float | None:
        if not values:
            return None
        try:
            number = float(values[0].decode("ascii").strip())
        except (ValueError, UnicodeDecodeError):
            return None
        return number if math.isfinite(number) else None

    def to_ldap(self, value: float | None) -> list[bytes]:
        return [] if value is None else [repr(float(value)).encode("ascii")]

    def from_json(self, data: object) -> float | None:
        if data is None:
            return None
        if isinstance(data, bool) or not isinstance(data, int | float):
            raise ValidationError(_("Expected a number."))
        if not math.isfinite(data):
            raise ValidationError(_("Expected a finite number."))
        return float(data)

    def to_json(self, value: float | None) -> JSON:
        return value

    def _validate(self, value: float) -> list[str]:
        return self._check_range(value)


class BooleanAttr(Attribute[bool]):
    """Boolean stored as ``TRUE`` / ``FALSE``."""

    kind = "boolean"

    def from_ldap(self, values: list[bytes]) -> bool | None:
        if not values:
            return None
        text = values[0].decode("ascii", errors="replace").strip().upper()
        if text == "TRUE":
            return True
        if text == "FALSE":
            return False
        return None

    def to_ldap(self, value: bool | None) -> list[bytes]:
        if value is None:
            return []
        return [b"TRUE" if value else b"FALSE"]

    def from_json(self, data: object) -> bool | None:
        if data is None:
            return None
        if not isinstance(data, bool):
            raise ValidationError(_("Expected true or false."))
        return data

    def to_json(self, value: bool | None) -> JSON:
        return value


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_GENERALIZED_RE = re.compile(
    r"(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?(?:[.,](\d+))?(Z|[+-]\d{2}(?:\d{2})?)?"
)


def parse_generalized_time(text: str) -> datetime | None:
    """Parse an LDAP GeneralizedTime into an aware UTC datetime (``None`` if invalid)."""
    match = _GENERALIZED_RE.fullmatch(text.strip())
    if match is None:
        return None
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    try:
        moment = datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            tzinfo=UTC,
        )
    except ValueError:
        return None
    if fraction:
        moment += timedelta(seconds=float("0." + fraction))
    if zone and zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        hours = int(zone[1:3])
        minutes = int(zone[3:5] or 0) if len(zone) > 3 else 0
        offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
        moment = moment.replace(tzinfo=offset).astimezone(UTC)
    return moment


class DateAttr(Attribute[date]):
    """Calendar date, stored as GeneralizedTime at midnight UTC (``YYYYMMDD000000Z``)."""

    kind = "date"

    def from_ldap(self, values: list[bytes]) -> date | None:
        if not values:
            return None
        moment = parse_generalized_time(values[0].decode("ascii", errors="replace"))
        return moment.date() if moment else None

    def to_ldap(self, value: date | None) -> list[bytes]:
        if value is None:
            return []
        return [value.strftime("%Y%m%d000000Z").encode("ascii")]

    def from_json(self, data: object) -> date | None:
        if data is None or data == "":
            return None
        if not isinstance(data, str):
            raise ValidationError(_("Expected a date (YYYY-MM-DD)."))
        try:
            return date.fromisoformat(data)
        except ValueError:
            raise ValidationError(_("Expected a date (YYYY-MM-DD).")) from None

    def to_json(self, value: date | None) -> JSON:
        return value.isoformat() if value else None


class DateTimeAttr(Attribute[datetime]):
    """Instant, stored as GeneralizedTime in UTC; Python values are aware (UTC)."""

    kind = "datetime"

    def from_ldap(self, values: list[bytes]) -> datetime | None:
        if not values:
            return None
        return parse_generalized_time(values[0].decode("ascii", errors="replace"))

    def to_ldap(self, value: datetime | None) -> list[bytes]:
        if value is None:
            return []
        return [_as_utc(value).strftime("%Y%m%d%H%M%SZ").encode("ascii")]

    def from_json(self, data: object) -> datetime | None:
        if data is None or data == "":
            return None
        if not isinstance(data, str):
            raise ValidationError(_("Expected an ISO 8601 date and time."))
        try:
            return _as_utc(datetime.fromisoformat(data))
        except ValueError:
            raise ValidationError(_("Expected an ISO 8601 date and time.")) from None

    def to_json(self, value: datetime | None) -> JSON:
        if value is None:
            return None
        return _as_utc(value).isoformat().replace("+00:00", "Z")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# ---------------------------------------------------------------------------
# Binary
# ---------------------------------------------------------------------------

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _b64decode(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError(_("Invalid base64 data.")) from None


#: Default cap of a ``file`` value (the JSON form is base64, 4/3 larger).
MAX_FILE_BYTES = 1024 * 1024
#: Default cap of an ``image`` value (a portrait photo stays well under it).
MAX_IMAGE_BYTES = 512 * 1024


def _size_label(size: int) -> str:
    """Human-readable size used in validation messages."""
    if size and size % (1024 * 1024) == 0:
        return f"{size // (1024 * 1024)} MiB"
    return f"{max(size, 0) // 1024} KiB"


class FileAttr(Attribute[bytes]):
    """Binary file; JSON value is a base64 string.

    ``max_bytes`` is the largest accepted value (1 MiB by default): the value lives in one
    LDAP attribute and travels back to the editor as base64.
    """

    kind = "file"

    def __init__(self, *args: Any, max_bytes: int | None = MAX_FILE_BYTES, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_bytes = max_bytes

    def from_ldap(self, values: list[bytes]) -> bytes | None:
        return values[0] if values else None

    def to_ldap(self, value: bytes | None) -> list[bytes]:
        return [] if not value else [value]

    def from_json(self, data: object) -> bytes | None:
        if data is None or data == "":
            return None
        if not isinstance(data, str):
            raise ValidationError(_("Expected a base64 string."))
        return _b64decode(data)

    def to_json(self, value: bytes | None) -> JSON:
        return base64.b64encode(value).decode("ascii") if value else None

    def _validate(self, value: bytes) -> list[str]:
        if self.max_bytes is not None and len(value) > self.max_bytes:
            return [
                _("The file is too large (maximum {size}).").format(
                    size=_size_label(self.max_bytes)
                )
            ]
        return []


class ImageAttr(FileAttr):
    """JPEG or PNG image; JSON value is a ``data:`` URL.

    ``max_size`` is the display size advertised to the UI; ``max_bytes`` (512 KiB by
    default) caps the stored file and the magic bytes are checked.
    """

    kind = "image"

    def __init__(
        self,
        *args: Any,
        max_size: tuple[int, int] | None = None,
        max_bytes: int | None = MAX_IMAGE_BYTES,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, max_bytes=max_bytes, **kwargs)
        self.max_size = max_size

    @staticmethod
    def mime_type(data: bytes) -> str | None:
        """Detect the MIME type from magic bytes."""
        if data.startswith(_JPEG_MAGIC):
            return "image/jpeg"
        if data.startswith(_PNG_MAGIC):
            return "image/png"
        return None

    def from_json(self, data: object) -> bytes | None:
        if data is None or data == "":
            return None
        if not isinstance(data, str):
            raise ValidationError(_("Expected an image data URL."))
        payload = data
        if data.startswith("data:"):
            header, sep, payload = data.partition(",")
            if not sep or not header.endswith(";base64"):
                raise ValidationError(_("Invalid image data URL."))
        return _b64decode(payload)

    def to_json(self, value: bytes | None) -> JSON:
        if not value:
            return None
        mime = self.mime_type(value) or "application/octet-stream"
        return f"data:{mime};base64,{base64.b64encode(value).decode('ascii')}"

    def _validate(self, value: bytes) -> list[str]:
        problems = super()._validate(value)
        if self.mime_type(value) is None:
            problems.append(_("The image must be a JPEG or PNG file."))
        return problems

    def describe_extra(self) -> dict[str, JSON]:
        width, height = self.max_size if self.max_size else (None, None)
        return {"image": {"max_width": width, "max_height": height}}


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Option:
    """A selectable value with its label."""

    value: str
    label: str


type OptionLike = Option | tuple[str, str]


def _options(options: Sequence[OptionLike]) -> tuple[Option, ...]:
    return tuple(o if isinstance(o, Option) else Option(o[0], o[1]) for o in options)


def _options_json(options: Sequence[Option]) -> JSON:
    return [{"value": o.value, "label": o.label} for o in options]


class SelectAttr(_StrAttr):
    """One value among fixed options."""

    kind = "select"

    def __init__(self, *args: Any, options: Sequence[OptionLike] = (), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.options = _options(options)

    def _validate(self, value: str) -> list[str]:
        if self.options and value not in {o.value for o in self.options}:
            return [_("Invalid choice.")]
        return []

    def describe_extra(self) -> dict[str, JSON]:
        return {"options": _options_json(self.options)}


class MultiSelectAttr(Attribute[list[str]]):
    """Several values among fixed options."""

    kind = "multiselect"
    multivalued = True

    def __init__(self, *args: Any, options: Sequence[OptionLike] = (), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.options = _options(options)

    def from_ldap(self, values: list[bytes]) -> list[str] | None:
        return [v.decode("utf-8", errors="replace") for v in values] or None

    def to_ldap(self, value: list[str] | None) -> list[bytes]:
        return [v.encode("utf-8") for v in value or []]

    def from_json(self, data: object) -> list[str] | None:
        if data is None:
            return None
        if not isinstance(data, list) or not all(isinstance(v, str) for v in data):  # pyright: ignore[reportUnknownVariableType]
            raise ValidationError(_("Expected a list of strings."))
        items = [str(v) for v in data]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        return items or None

    def to_json(self, value: list[str] | None) -> JSON:
        return list(value) if value is not None else None

    def _validate(self, value: list[str]) -> list[str]:
        valid = {o.value for o in self.options}
        if self.options and any(v not in valid for v in value):
            return [_("Invalid choice.")]
        return []

    def describe_extra(self) -> dict[str, JSON]:
        return {"options": _options_json(self.options)}


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


class _DnAttr(_StrAttr):
    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        parts = dnlib.split(value)
        if not parts or any("=" not in p for p in parts):
            errors.append(_("Invalid distinguished name."))
        return errors


class ObjectRefAttr(_DnAttr):
    """DN of an object of type ``ref_type``."""

    kind = "object_ref"

    def __init__(self, *args: Any, ref_type: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.ref_type = ref_type

    @property
    def ref_types(self) -> tuple[str, ...]:
        """Every type a value may name; a subclass accepting several widens ``describe_extra``."""
        declared = self.describe_extra().get("ref_types")
        if isinstance(declared, list):
            names = tuple(str(name) for name in declared)  # pyright: ignore[reportUnknownVariableType]
            if names:
                return names
        return (self.ref_type,)

    def describe_extra(self) -> dict[str, JSON]:
        return {"ref_type": self.ref_type}


class DepartmentAttr(_DnAttr):
    """DN of the department holding the object (virtual: derived from the entry DN)."""

    kind = "department"
    stored = False


# ---------------------------------------------------------------------------
# Computed
# ---------------------------------------------------------------------------


class DisplayAttr(_StrAttr):
    """Read-only computed value.

    ``compute`` receives the tab's current values (by attribute name) and
    returns the text. With ``stored=True`` the result is also written to LDAP
    (e.g. ``cn``).
    """

    kind = "display"

    def __init__(
        self,
        name: str,
        label: str,
        *,
        compute: Callable[[dict[str, Any]], str | None],
        stored: bool = False,
        **kwargs: Any,
    ) -> None:
        kwargs["readonly"] = True
        super().__init__(name, label, **kwargs)
        self.compute = compute
        self.stored = stored

    def validate(self, value: str | None) -> list[str]:
        return []


__all__ = [
    "BooleanAttr",
    "DateAttr",
    "DateTimeAttr",
    "DepartmentAttr",
    "DisplayAttr",
    "EmailAttr",
    "FileAttr",
    "FloatAttr",
    "HiddenAttr",
    "ImageAttr",
    "IntAttr",
    "MultiSelectAttr",
    "ObjectRefAttr",
    "Option",
    "PasswordAttr",
    "PhoneAttr",
    "PostalAddressAttr",
    "SelectAttr",
    "StringAttr",
    "TextAttr",
    "UrlAttr",
    "is_empty",
    "parse_generalized_time",
    "set_default_password_hasher",
]
