"""SCIM schema and message URNs (RFC 7643, RFC 7644)."""

from __future__ import annotations

from typing import Final

USER_SCHEMA: Final = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA: Final = "urn:ietf:params:scim:schemas:core:2.0:Group"
ENTERPRISE_USER_SCHEMA: Final = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"

LIST_RESPONSE: Final = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_OP: Final = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA: Final = "urn:ietf:params:scim:api:messages:2.0:Error"
SEARCH_REQUEST: Final = "urn:ietf:params:scim:api:messages:2.0:SearchRequest"

SERVICE_PROVIDER_CONFIG_SCHEMA: Final = (
    "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
)
RESOURCE_TYPE_SCHEMA: Final = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_SCHEMA: Final = "urn:ietf:params:scim:schemas:core:2.0:Schema"

#: Media type of SCIM requests and responses (``application/json`` is accepted too).
SCIM_MEDIA_TYPE: Final = "application/scim+json"
