"""Settings of the SCIM endpoint (``api.scim`` in the configuration file)."""

from __future__ import annotations

from pydantic import BaseModel, Field

#: SCIM attribute path (lower-cased, enterprise ones with their URN) -> LDAP attribute of the
#: ``user`` type, for the plain single-valued string attributes. Special attributes (``id``,
#: ``active``, ``password``, ``emails``, ``phoneNumbers``, ``groups``, ``meta``, the
#: enterprise ``manager``) are handled by the service itself.
DEFAULT_USER_ATTRIBUTES: dict[str, str] = {
    "username": "uid",
    "name.familyname": "sn",
    "name.givenname": "givenName",
    "name.formatted": "cn",
    "displayname": "displayName",
    "preferredlanguage": "preferredLanguage",
    "usertype": "employeeType",
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:user:employeenumber": "employeeNumber",
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:user:organization": "o",
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:user:department": "ou",
}


class ScimSettings(BaseModel):
    enabled: bool = True
    #: Department DN where new users are created (empty: the directory base).
    user_base: str = ""
    #: Department DN where new groups are created (empty: the directory base).
    group_base: str = ""
    #: Operational attribute holding the stable resource ``id``.
    id_attribute: str = "entryUUID"
    #: Overrides/additions to :data:`DEFAULT_USER_ATTRIBUTES` (same key format).
    user_attributes: dict[str, str] = Field(default_factory=lambda: {})
    #: Largest ``count`` of a list request (``tooMany`` above, ``count`` is capped).
    max_results: int = Field(default=200, ge=1)

    def user_attribute_map(self) -> dict[str, str]:
        merged = dict(DEFAULT_USER_ATTRIBUTES)
        merged.update({k.lower(): v for k, v in self.user_attributes.items()})
        return merged


__all__ = ["DEFAULT_USER_ATTRIBUTES", "ScimSettings"]
