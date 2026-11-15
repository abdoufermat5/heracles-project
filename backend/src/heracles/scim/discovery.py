"""Discovery documents (RFC 7644 section 4, RFC 7643 sections 5, 6 and 8.7).

``ServiceProviderConfig``, ``ResourceTypes`` and ``Schemas`` of this version: what is listed
is what the service supports (no ``externalId``, no bulk, no ``x509Certificates`` and so on).
"""

from __future__ import annotations

from typing import Any

from heracles.scim.schemas import (
    ENTERPRISE_USER_SCHEMA,
    GROUP_SCHEMA,
    RESOURCE_TYPE_SCHEMA,
    SCHEMA_SCHEMA,
    SERVICE_PROVIDER_CONFIG_SCHEMA,
    USER_SCHEMA,
)
from heracles.scim.settings import ScimSettings

Doc = dict[str, Any]


def _attr(
    name: str,
    type_: str = "string",
    *,
    description: str,
    multi: bool = False,
    required: bool = False,
    mutability: str = "readWrite",
    returned: str = "default",
    uniqueness: str = "none",
    case_exact: bool = False,
    sub: list[Doc] | None = None,
    canonical: list[str] | None = None,
    references: list[str] | None = None,
) -> Doc:
    out: Doc = {
        "name": name,
        "type": type_,
        "multiValued": multi,
        "description": description,
        "required": required,
        "caseExact": case_exact,
        "mutability": mutability,
        "returned": returned,
        "uniqueness": uniqueness,
    }
    if canonical:
        out["canonicalValues"] = canonical
    if references:
        out["referenceTypes"] = references
    if sub is not None:
        out["subAttributes"] = sub
    return out


def _typed_multi(name: str, description: str, value_description: str, types: list[str]) -> Doc:
    return _attr(
        name,
        "complex",
        multi=True,
        description=description,
        sub=[
            _attr("value", description=value_description),
            _attr("display", description="A human-readable name, primarily for display."),
            _attr("type", description="A label indicating the kind of value.", canonical=types),
            _attr(
                "primary",
                "boolean",
                description="Whether this is the primary value; at most one value may be.",
            ),
        ],
    )


def _user_schema() -> Doc:
    attributes = [
        _attr(
            "userName",
            description="Unique identifier of the user, the sign-in name.",
            required=True,
            uniqueness="server",
        ),
        _attr(
            "name",
            "complex",
            description="The components of the user's name.",
            sub=[
                _attr("formatted", description="The full name, formatted for display."),
                _attr("familyName", description="The family name (surname)."),
                _attr("givenName", description="The given name."),
            ],
        ),
        _attr("displayName", description="The name of the user, suitable for display."),
        _attr("preferredLanguage", description="The preferred language, for example fr or en-US."),
        _attr("userType", description="The relationship between the organization and the user."),
        _attr("active", "boolean", description="Whether the account is usable (not locked)."),
        _attr(
            "password",
            description="The password of the user; it is never returned.",
            mutability="writeOnly",
            returned="never",
        ),
        _typed_multi(
            "emails",
            "E-mail addresses of the user.",
            "The e-mail address.",
            ["work", "home", "other"],
        ),
        _typed_multi(
            "phoneNumbers",
            "Phone numbers of the user.",
            "The phone number.",
            ["work", "home", "mobile", "fax", "pager", "other"],
        ),
        _attr(
            "groups",
            "complex",
            multi=True,
            description="The groups the user belongs to; changed through the Group resource.",
            mutability="readOnly",
            sub=[
                _attr(
                    "value",
                    description="The id of the group.",
                    mutability="readOnly",
                ),
                _attr(
                    "$ref",
                    "reference",
                    description="The URI of the group.",
                    mutability="readOnly",
                    references=["Group"],
                ),
                _attr(
                    "display",
                    description="The name of the group.",
                    mutability="readOnly",
                ),
                _attr(
                    "type",
                    description="How the user belongs to the group.",
                    mutability="readOnly",
                    canonical=["direct", "indirect"],
                ),
            ],
        ),
    ]
    return {
        "id": USER_SCHEMA,
        "name": "User",
        "description": "User account",
        "attributes": attributes,
    }


def _enterprise_schema() -> Doc:
    attributes = [
        _attr("employeeNumber", description="Numeric or alphanumeric identifier of the person."),
        _attr("organization", description="The organization the user belongs to."),
        _attr("department", description="The department the user belongs to."),
        _attr(
            "manager",
            "complex",
            description="The user's manager.",
            sub=[
                _attr("value", description="The id of the manager's User resource."),
                _attr(
                    "$ref",
                    "reference",
                    description="The URI of the manager's User resource.",
                    references=["User"],
                ),
                _attr(
                    "displayName",
                    description="The display name of the manager.",
                    mutability="readOnly",
                ),
            ],
        ),
    ]
    return {
        "id": ENTERPRISE_USER_SCHEMA,
        "name": "EnterpriseUser",
        "description": "Enterprise User",
        "attributes": attributes,
    }


def _group_schema() -> Doc:
    attributes = [
        _attr(
            "displayName",
            description="The name of the group.",
            required=True,
            uniqueness="server",
        ),
        _attr(
            "members",
            "complex",
            multi=True,
            description="The members of the group (users only; at least one is required).",
            sub=[
                _attr(
                    "value",
                    description="The id of the member's User resource.",
                    mutability="immutable",
                ),
                _attr(
                    "$ref",
                    "reference",
                    description="The URI of the member's User resource.",
                    mutability="immutable",
                    references=["User"],
                ),
                _attr(
                    "display",
                    description="The display name of the member.",
                    mutability="readOnly",
                ),
                _attr(
                    "type",
                    description="The type of the member.",
                    mutability="immutable",
                    canonical=["User"],
                ),
            ],
        ),
    ]
    return {
        "id": GROUP_SCHEMA,
        "name": "Group",
        "description": "Group",
        "attributes": attributes,
    }


def schemas(base_url: str) -> list[Doc]:
    """The schema documents, each with its ``meta``."""
    docs = [_user_schema(), _group_schema(), _enterprise_schema()]
    for doc in docs:
        doc["schemas"] = [SCHEMA_SCHEMA]
        doc["meta"] = {
            "resourceType": "Schema",
            "location": f"{base_url}/Schemas/{doc['id']}",
        }
    return docs


def schema(base_url: str, urn: str) -> Doc | None:
    return next((d for d in schemas(base_url) if d["id"] == urn), None)


def resource_types(base_url: str) -> list[Doc]:
    """The resource types: ``User`` (with the enterprise extension) and ``Group``."""
    docs: list[Doc] = [
        {
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "description": "User account",
            "schema": USER_SCHEMA,
            "schemaExtensions": [{"schema": ENTERPRISE_USER_SCHEMA, "required": False}],
        },
        {
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "description": "Group",
            "schema": GROUP_SCHEMA,
        },
    ]
    for doc in docs:
        doc["schemas"] = [RESOURCE_TYPE_SCHEMA]
        doc["meta"] = {
            "resourceType": "ResourceType",
            "location": f"{base_url}/ResourceTypes/{doc['id']}",
        }
    return docs


def resource_type(base_url: str, name: str) -> Doc | None:
    return next((d for d in resource_types(base_url) if d["id"] == name), None)


def service_provider_config(settings: ScimSettings, base_url: str) -> Doc:
    return {
        "schemas": [SERVICE_PROVIDER_CONFIG_SCHEMA],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": settings.max_results},
        "changePassword": {"supported": True},
        "sort": {"supported": True},
        "etag": {"supported": True},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Heracles API token",
                "description": (
                    "Authentication with a Heracles API token, sent as "
                    "'Authorization: Bearer hrc_...'. The token acts with the rights of its "
                    "owner, limited by its scope and object types."
                ),
                "specUri": "https://www.rfc-editor.org/info/rfc6750",
                "primary": True,
            }
        ],
        "meta": {
            "resourceType": "ServiceProviderConfig",
            "location": f"{base_url}/ServiceProviderConfig",
        },
    }


__all__ = [
    "resource_type",
    "resource_types",
    "schema",
    "schemas",
    "service_provider_config",
]
