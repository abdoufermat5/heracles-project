"""Token entry identifiers used by authentication (re-exported from the schema module)."""
# ruff: noqa: S105  # attribute names, not secrets

from __future__ import annotations

from typing import Final

from heracles.schema.names import ATTR, OC

TOKEN_OBJECT_CLASS: Final = OC.TOKEN
TOKEN_ATTR_CN: Final = "cn"
TOKEN_ATTR_USER_DN: Final = ATTR.TOKEN_USER_DN
TOKEN_ATTR_TYPE: Final = ATTR.TOKEN_TYPE
TOKEN_ATTR_VALUE: Final = ATTR.TOKEN
TOKEN_ATTR_TIMESTAMP: Final = ATTR.TOKEN_TIMESTAMP
TOKEN_TYPE_RECOVERY: Final = "recovery"
