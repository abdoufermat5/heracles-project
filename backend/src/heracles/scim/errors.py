"""SCIM errors (RFC 7644 section 3.12)."""

from __future__ import annotations

from typing import Any, Final

from heracles.scim.schemas import ERROR_SCHEMA

#: ``scimType`` values of RFC 7644 table 9 used by Heracles.
INVALID_FILTER: Final = "invalidFilter"
TOO_MANY: Final = "tooMany"
UNIQUENESS: Final = "uniqueness"
MUTABILITY: Final = "mutability"
INVALID_SYNTAX: Final = "invalidSyntax"
INVALID_PATH: Final = "invalidPath"
NO_TARGET: Final = "noTarget"
INVALID_VALUE: Final = "invalidValue"
INVALID_VERS: Final = "invalidVers"
SENSITIVE: Final = "sensitive"


class ScimError(Exception):
    """An error answered as a SCIM ``Error`` message."""

    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schemas": [ERROR_SCHEMA],
            "status": str(self.status),
            "detail": self.detail,
        }
        if self.scim_type:
            out["scimType"] = self.scim_type
        return out


def bad_request(detail: str, scim_type: str | None = None) -> ScimError:
    return ScimError(400, detail, scim_type)


def not_found(detail: str = "Resource not found") -> ScimError:
    return ScimError(404, detail)


__all__ = [
    "INVALID_FILTER",
    "INVALID_PATH",
    "INVALID_SYNTAX",
    "INVALID_VALUE",
    "INVALID_VERS",
    "MUTABILITY",
    "NO_TARGET",
    "SENSITIVE",
    "TOO_MANY",
    "UNIQUENESS",
    "ScimError",
    "bad_request",
    "not_found",
]
