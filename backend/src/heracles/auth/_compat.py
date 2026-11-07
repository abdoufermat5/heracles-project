# ruff: noqa: S105
"""Legacy directory identifiers needed by the auth package.

TODO: import from heracles.schema.legacy once merged.
"""

from __future__ import annotations

from typing import Final

TOKEN_OBJECT_CLASS: Final = "fdTokenEntry"
TOKEN_ATTR_CN: Final = "cn"
TOKEN_ATTR_USER_DN: Final = "fdTokenUserDN"
TOKEN_ATTR_TYPE: Final = "fdTokenType"
TOKEN_ATTR_VALUE: Final = "fdToken"
TOKEN_ATTR_TIMESTAMP: Final = "fdTokenTimestamp"
TOKEN_TYPE_RECOVERY: Final = "recovery"
