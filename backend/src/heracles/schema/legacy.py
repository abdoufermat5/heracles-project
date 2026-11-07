# ruff: noqa: S105
# (attribute *names* such as the token attribute are not secrets)
"""Directory data-compatibility identifiers.

Heracles operates on directories that already contain the "compatibility
schema". The objectClass and attribute
names below are fixed *data identifiers*: they are stored in existing
directories and must never change, and they are never shown in the UI or the
v2 API. This module is the ONLY place in the code base allowed to spell them;
every other module imports the constants from here.
"""

from __future__ import annotations

import re
from dataclasses import astuple, dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ObjectClasses:
    """Compatibility objectClass names (data identifiers)."""

    DEPARTMENT: str = "gosaDepartment"
    OBJECT_GROUP: str = "gosaGroupOfNames"
    ACL_ROLE: str = "gosaRole"
    ACL_ASSIGNMENT: str = "gosaAcl"
    SNAPSHOT: str = "gosaSnapshotObject"
    LOCK: str = "fdLockEntry"
    TOKEN: str = "fdTokenEntry"
    MAIL_TEMPLATE: str = "fdMailTemplate"
    TEMPLATE: str = "fdTemplate"
    TASKS: str = "fdTasks"
    TASKS_MAIL: str = "fdTasksMail"
    TASKS_GRANULAR: str = "fdTasksGranular"
    TASKS_CONF: str = "fdTasksConf"
    MAIN_CONFIG: str = "fusionDirectoryConf"
    PLUGINS_CONFIG: str = "fusionDirectoryPluginsConf"
    RECOVERY_CONFIG: str = "fdPasswordRecoveryConf"
    DASHBOARD_CONFIG: str = "fdDashboardPluginConf"


@dataclass(frozen=True, slots=True)
class StandardClasses:
    """Standard (non-compatibility) objectClasses used as-is."""

    INET_ORG_PERSON: str = "inetOrgPerson"
    ORGANIZATIONAL_PERSON: str = "organizationalPerson"
    PERSON: str = "person"
    GROUP_OF_NAMES: str = "groupOfNames"
    POSIX_GROUP: str = "posixGroup"
    ORGANIZATIONAL_ROLE: str = "organizationalRole"
    ORGANIZATIONAL_UNIT: str = "organizationalUnit"
    ORGANIZATION: str = "organization"
    LOCALITY: str = "locality"
    COUNTRY: str = "country"
    DC_OBJECT: str = "dcObject"
    DOMAIN: str = "domain"
    POSIX_ACCOUNT: str = "posixAccount"
    SHADOW_ACCOUNT: str = "shadowAccount"
    PUBLIC_KEY: str = "ldapPublicKey"
    SUDO_ROLE: str = "sudoRole"
    PWD_POLICY: str = "pwdPolicy"
    TOP: str = "top"


@dataclass(frozen=True, slots=True)
class Attrs:
    """Compatibility attribute names (data identifiers)."""

    # Department / object group
    GROUP_OBJECTS: str = "gosaGroupObjects"
    # ACL
    ACL_TEMPLATE: str = "gosaAclTemplate"
    ACL_ENTRY: str = "gosaAclEntry"
    # Snapshot
    SNAPSHOT_TIMESTAMP: str = "gosaSnapshotTimestamp"
    SNAPSHOT_DN: str = "gosaSnapshotDN"
    SNAPSHOT_DATA: str = "gosaSnapshotData"
    SNAPSHOT_DATA_SOURCE: str = "fdSnapshotDataSource"
    SNAPSHOT_OBJECT_TYPE: str = "fdSnapshotObjectType"
    SNAPSHOT_HASH: str = "fdSnapshotHash"
    # Edit lock
    LOCK_USER_DN: str = "fdUserDn"
    LOCK_OBJECT_DN: str = "fdObjectDn"
    LOCK_TIMESTAMP: str = "fdLockTimestamp"
    # Token
    TOKEN_USER_DN: str = "fdTokenUserDN"
    TOKEN_TYPE: str = "fdTokenType"
    TOKEN: str = "fdToken"
    TOKEN_TIMESTAMP: str = "fdTokenTimestamp"
    # Mail template
    MAIL_TEMPLATE_BODY: str = "fdMailTemplateBody"
    MAIL_TEMPLATE_SUBJECT: str = "fdMailTemplateSubject"
    MAIL_TEMPLATE_SIGNATURE: str = "fdMailTemplateSignature"
    MAIL_TEMPLATE_READ_RECEIPT: str = "fdMailTemplateReadReceipt"


@dataclass(frozen=True, slots=True)
class StandardAttrs:
    """Standard attribute names Heracles relies on (not compatibility-specific)."""

    OBJECT_CLASS: str = "objectClass"
    CN: str = "cn"
    OU: str = "ou"
    DESCRIPTION: str = "description"
    MEMBER: str = "member"
    ROLE_OCCUPANT: str = "roleOccupant"
    USER_PASSWORD: str = "userPassword"
    UID: str = "uid"


@dataclass(frozen=True, slots=True)
class DefaultRdns:
    """Default container RDNs (relative to a department or the base)."""

    USERS: str = "ou=people"
    GROUPS: str = "ou=groups"
    ROLES: str = "ou=roles"
    ACL_ROLES: str = "ou=aclroles"
    APP: str = "ou=fusiondirectory"
    LOCKS: str = "ou=locks,ou=fusiondirectory"
    TOKENS: str = "ou=tokens,ou=fusiondirectory"
    RECOVERY_TOKENS: str = "ou=recovery,ou=tokens,ou=fusiondirectory"
    SNAPSHOTS: str = "ou=snapshots"
    SYSTEMS: str = "ou=systems"
    SERVERS: str = "ou=servers,ou=systems"
    WORKSTATIONS: str = "ou=workstations,ou=systems"
    TERMINALS: str = "ou=terminals,ou=systems"
    PRINTERS: str = "ou=printers,ou=systems"
    PHONES: str = "ou=phones,ou=systems"
    NETDEVICES: str = "ou=netdevices,ou=systems"
    MOBILE: str = "ou=mobile,ou=systems"
    SUDO: str = "ou=sudoers"
    DSA: str = "ou=dsa"
    ALIAS: str = "ou=alias"
    APPS: str = "ou=apps"


OC: Final = ObjectClasses()
STD_OC: Final = StandardClasses()
ATTR: Final = Attrs()
STD_ATTR: Final = StandardAttrs()
RDN: Final = DefaultRdns()

APP_OU: Final = "ou=fusiondirectory"
"""Application organizational unit literal (data identifier, never shown)."""

CONFIG_RDN: Final = "cn=config"
"""RDN of the main configuration entry, below the application OU."""

USER_LOCK_SENTINEL: Final = "{CRYPT}!"
"""``userPassword`` value used to lock an account that has no password."""

LOCKED_PASSWORD_RE: Final = re.compile(r"^[^}]*}!")
"""Matches a ``userPassword`` whose scheme prefix is followed by ``!`` (locked)."""

DEPARTMENT_STRUCTURAL_CLASSES: Final = (
    STD_OC.ORGANIZATIONAL_UNIT,
    STD_OC.ORGANIZATION,
    STD_OC.LOCALITY,
    STD_OC.COUNTRY,
    STD_OC.DC_OBJECT,
    STD_OC.DOMAIN,
)
"""Structural classes that may carry the department marker."""

COMPAT_OBJECT_CLASSES: Final = frozenset(str(v) for v in astuple(OC))
"""All compatibility objectClass names (original case)."""
