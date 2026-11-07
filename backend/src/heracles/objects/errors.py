"""Errors raised by the object layer."""

from __future__ import annotations


class ObjectError(Exception):
    """Base class for object layer errors."""


class UnknownTypeError(ObjectError):
    """The object type is not registered."""


class ObjectNotFoundError(ObjectError):
    """The entry does not exist or is not of the requested type."""


class ObjectConflictError(ObjectError):
    """The operation conflicts with an existing entry."""


class PermissionDeniedError(ObjectError):
    """The access policy refused the operation."""


class ObjectValidationError(ObjectError):
    """Invalid input. ``fields`` maps ``"<tab>.<attr>"`` (or ``"<tab>"``) to a message."""

    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in fields.items()))
        self.fields = fields
