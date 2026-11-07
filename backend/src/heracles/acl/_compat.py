"""Compatibility-schema identifiers used by the ACL package.

These are data identifiers that will live in ``heracles.schema.legacy``.
"""

from __future__ import annotations

OC_ACL = "gosaAcl"  # TODO: import from heracles.schema.legacy once merged
ATTR_ACL_ENTRY = "gosaAclEntry"  # TODO: import from heracles.schema.legacy once merged
OC_ACL_ROLE = "gosaRole"  # TODO: import from heracles.schema.legacy once merged
ATTR_ACL_TEMPLATE = "gosaAclTemplate"  # TODO: import from heracles.schema.legacy once merged

# Standard schema names (not legacy specific).
OC_GROUP_OF_NAMES = "groupOfNames"
OC_POSIX_GROUP = "posixGroup"
OC_ROLE = "organizationalRole"
