"""Attribute base class: LDAP <-> Python <-> JSON conversion and validation."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Protocol

from heracles.i18n import _

type JSON = bool | int | float | str | list[JSON] | dict[str, JSON] | None
"""JSON-compatible value as exchanged with the SPA."""

type Pattern = str | re.Pattern[str]


class ValidationError(ValueError):
    """Raised by ``from_json`` when a JSON value cannot be converted."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PasswordHasher(Protocol):
    """Callable turning a clear-text password into its stored LDAP form."""

    def __call__(self, plaintext: str, /) -> str:
        """Return the hashed value (e.g. ``{SCHEME}...``)."""
        ...


def is_empty(value: object) -> bool:
    """True for ``None`` and empty containers/strings (``False`` and ``0`` are values)."""
    if value is None:
        return True
    if isinstance(value, str | bytes | list | dict):
        return len(value) == 0  # pyright: ignore[reportUnknownArgumentType]
    return False


class Attribute[T](ABC):
    """Declarative attribute descriptor with conversion behaviour.

    ``name`` is the LDAP attribute name (or a virtual name when ``stored`` is
    false). A multi-valued attribute is expressed with
    :class:`heracles.attributes.collections.ListAttr` (or ``MultiSelectAttr``),
    whose Python value is a list.
    """

    kind: str
    multivalued: bool = False
    stored: bool = True
    """False for virtual attributes that never reach the directory."""
    write_only: bool = False
    """True when the value is never read back (passwords)."""

    def __init__(
        self,
        name: str,
        label: str,
        *,
        description: str = "",
        required: bool = False,
        readonly: bool = False,
        default: T | None = None,
        pattern: Pattern | None = None,
        min: float | None = None,
        max: float | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
    ) -> None:
        self.name = name
        self.label = label
        self.description = description
        self.required = required
        self.readonly = readonly
        self.default = default
        self.pattern: re.Pattern[str] | None = (
            re.compile(pattern) if isinstance(pattern, str) else pattern
        )
        self.min = min
        self.max = max
        self.min_length = min_length
        self.max_length = max_length

    # -- conversions -------------------------------------------------------

    @abstractmethod
    def from_ldap(self, values: list[bytes]) -> T | None:
        """Convert raw LDAP values; ``None`` when absent or unparseable."""

    @abstractmethod
    def to_ldap(self, value: T | None) -> list[bytes]:
        """Convert a value to raw LDAP values (``[]`` means "no value")."""

    @abstractmethod
    def from_json(self, data: object) -> T | None:
        """Convert a JSON value; raises :class:`ValidationError`."""

    @abstractmethod
    def to_json(self, value: T | None) -> JSON:
        """Convert a value to its JSON representation."""

    # -- validation --------------------------------------------------------

    def validate(self, value: T | None) -> list[str]:
        """Return human readable problems (empty list when valid)."""
        if value is None or is_empty(value):
            return [_("This field is required.")] if self.required else []
        return self._validate(value)

    def _validate(self, value: T) -> list[str]:
        """Kind specific checks for a non-empty value."""
        return []

    def _check_text(self, text: str) -> list[str]:
        """Apply pattern and length constraints to ``text``."""
        errors: list[str] = []
        if self.min_length is not None and len(text) < self.min_length:
            errors.append(_("Must be at least {n} characters long.").format(n=self.min_length))
        if self.max_length is not None and len(text) > self.max_length:
            errors.append(_("Must be at most {n} characters long.").format(n=self.max_length))
        if self.pattern is not None and self.pattern.fullmatch(text) is None:
            errors.append(_("Invalid format."))
        return errors

    def _check_range(self, number: float) -> list[str]:
        errors: list[str] = []
        if self.min is not None and number < self.min:
            errors.append(_("Must be at least {n}.").format(n=self.min))
        if self.max is not None and number > self.max:
            errors.append(_("Must be at most {n}.").format(n=self.max))
        return errors

    # -- description -------------------------------------------------------

    def constraints(self) -> dict[str, JSON]:
        """The defined constraints, as exposed in the descriptor."""
        out: dict[str, JSON] = {}
        if self.pattern is not None:
            out["pattern"] = self.pattern.pattern
        if self.min is not None:
            out["min"] = self.min
        if self.max is not None:
            out["max"] = self.max
        if self.min_length is not None:
            out["min_length"] = self.min_length
        if self.max_length is not None:
            out["max_length"] = self.max_length
        return out

    def describe_extra(self) -> dict[str, JSON]:
        """Kind specific descriptor keys (options, ref_type, item, ...)."""
        return {}

    def describe(self) -> dict[str, JSON]:
        """Return the ``AttributeDescriptor`` JSON exposed by the API."""
        out: dict[str, JSON] = {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "kind": self.kind,
            "required": self.required,
            "multivalued": self.multivalued,
            "readonly": self.readonly,
            "default": self.to_json(self.default),
            "constraints": self.constraints(),
        }
        out.update(self.describe_extra())
        return out


type AnyAttribute = Attribute[Any]
type ComputeFn = Callable[[dict[str, Any]], str | None]
