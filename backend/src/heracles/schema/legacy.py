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

PLUGIN_OBJECT_CLASSES: Final = frozenset(
    {
        # dns
        "dNSZone",
        "fdDNSView",
        "fdDNSAcl",
        # systems
        "device",
        "ieee802Device",
        "ipHost",
        "fdServer",
        "fdWorkstation",
        "fdTerminal",
        "fdPrinter",
        "fdPhone",
        "fdMobilePhone",
        "fdNetworkInterface",
        # tasks / reminders
        "fdTasksReminder",
        # password policies
        "pwdPolicyChecker",
        # personal information
        "fdPersonalInfo",
        # mail
        "gosaMailAccount",
        "fdGroupMail",
        "mailAliasRedirection",
        "mailAliasDistribution",
        # samba
        "sambaSamAccount",
        "sambaGroupMapping",
        "sambaDomain",
        "sambaIdmapEntry",
        "sambaUnixIdPool",
        # workflow tasks
        "fdAuditEvent",
        "fdAuditTasks",
        "fdArchivedObject",
        "fdArchiveTasks",
        "fdTasksLifeCycle",
        "fdTasksNotifications",
        "fdExtractorTasks",
        "fdTasksAutomaticGroups",
        # applications, groups, service accounts, forms
        "fdDesktopApplication",
        "fdWebApplication",
        "fdApplicationRights",
        "groupOfURLs",
        "extensibleObject",
        "simpleSecurityObject",
        "fdInvitation",
        "fdRegistration",
        "fdUserRegistration",
        "fdPublicForm",
        # network: ipam, netgroups, autofs, IPMI, web links
        "fdIpamVlan",
        "fdIpamSubnet",
        "nisNetgroup",
        "automountMap",
        "automount",
        "ipmiClient",
        "webLink",
        # security: kerberos, certificates, PGP, physical keys, PKI references
        "krbPrincipalAux",
        "krbTicketPolicyAux",
        "strongAuthenticationUser",
        "fdGpgAccount",
        "pgpKeyInfo",
        "pgpServerInfo",
        "fdPhysicalKey",
        "fdEjbcaCertificates",
        # mail and collaboration services
        "fdCyrusServer",
        "fdDovecotServer",
        "fdPostfixServer",
        "fdSieveServer",
        "fdZimbraServer",
        "goSpamServer",
        "fdSpamAssassinUser",
        "fdMailInBlackUser",
        # account extensions
        "fdNextCloudAccount",
        "PureFTPdUser",
        "quotaService",
        "systemQuotas",
        "radiusprofile",
        # dhcp
        "dhcpService",
        "dhcpSharedNetwork",
        "dhcpSubnet",
        "dhcpPool",
        "dhcpGroup",
        "dhcpHost",
        "dhcpClass",
        "dhcpSubClass",
        "dhcpTSigKey",
        "dhcpDnsZone",
        "dhcpFailOverPeer",
    }
)
"""objectClasses used by the first-party plugins (standard and compatibility schemas)."""

# --- P3 objects ---
TEMPLATE_FIELD_ATTR: Final = "fdTemplateField"
"""Multi-valued attribute of a template entry; each value is ``<attribute>:<value>``."""

INCREMENTAL_STATES_ATTR: Final = "fdIncrementalModifierStates"
"""Attribute of the main configuration entry holding incremental counters (``<id>;<value>``)."""

TEMPLATES_RDN: Final = "ou=templates"
"""Container of the templates of a type, relative to the type's own container."""
# --- end P3 objects ---

# --- P3 admin ---------------------------------------------------------------

MAIL_TEMPLATE_CONFIG_CLASS: Final = "fdMailTemplateConf"
"""Auxiliary class of the configuration entry holding the mail template settings."""

TAB_HOOK_ATTR: Final = "fdTabHook"
"""Multi-valued attribute of the configuration entry holding the triggers."""

DISPLAY_HOOK_OUTPUT_ATTR: Final = "fdDisplayHookOutput"
"""Single-valued boolean: show the successful output of a trigger to the user."""

TASKS_GRANULAR_MASTER_ATTR: Final = "fdTasksGranularMaster"
TASKS_GRANULAR_STATUS_ATTR: Final = "fdTasksGranularStatus"
TASKS_GRANULAR_NEXT_EXEC_ATTR: Final = "fdTasksGranularNextExec"
TASKS_GRANULAR_LAST_EXEC_ATTR: Final = "fdTasksGranularLastExec"
TASKS_GRANULAR_TYPE_ATTR: Final = "fdTasksGranularType"
TASKS_STATUS_ATTR: Final = "fdTasksStatus"
TASKS_NEXT_EXEC_ATTR: Final = "fdTasksNextExec"
TASKS_LAST_EXEC_ATTR: Final = "fdTasksLastExec"
TASKS_CREATION_DATE_ATTR: Final = "fdTasksCreationDate"
"""Task bookkeeping attributes (read by the task dashboard)."""

# Heracles configuration key -> attribute name, for the configuration entry.
CONFIG_ATTRS: Final[dict[str, str]] = {
    # look and feel
    "language": "fdLanguage",
    "theme": "fdTheme",
    "timezone": "fdTimezone",
    # core
    "schema_check": "fdSchemaCheck",
    "account_primary_attribute": "fdAccountPrimaryAttribute",
    "next_id_hook": "fdNextIdHook",
    "strict_naming_rules": "fdStrictNamingRules",
    "min_id": "fdMinId",
    "uid_number_base": "fdUidNumberBase",
    "gid_number_base": "fdGidNumberBase",
    "user_rdn": "fdUserRDN",
    "group_rdn": "fdGroupRDN",
    "acl_role_rdn": "fdAclRoleRDN",
    "ogroup_rdn": "fdOGroupRDN",
    "token_rdn": "fdTokenRDN",
    "orchestrator_token_rdn": "fdOrchestratorTokenRDN",
    "recovery_token_rdn": "fdRecoveryTokenRDN",
    "id_allocation_method": "fdIdAllocationMethod",
    "gid_pool_min": "fdGidNumberPoolMin",
    "gid_pool_max": "fdGidNumberPoolMax",
    "uid_pool_min": "fdUidNumberPoolMin",
    "uid_pool_max": "fdUidNumberPoolMax",
    "cn_pattern": "fdCnPattern",
    "restrict_role_members": "fdRestrictRoleMembers",
    "split_postal_address": "fdSplitPostalAddress",
    "postal_address_pattern": "fdPostalAddressPattern",
    "max_avatar_size": "fdMaxAvatarSize",
    "given_name_required": "fdGivenNameRequired",
    "list_summary": "fdListSummary",
    "modification_detection_attribute": "fdModificationDetectionAttribute",
    "ldap_size_limit": "fdLdapSizeLimit",
    "wildcard_foreign_keys": "fdWildcardForeignKeys",
    "store_filter_settings": "fdStoreFilterSettings",
    "shells": "fdShells",
    "default_shell": "fdDefaultShell",
    "acl_tab_on_objects": "fdAclTabOnObjects",
    "department_categories": "fdDepartmentCategories",
    "plugins_menu_blacklist": "fdPluginsMenuBlacklist",
    "acl_target_filter_limit": "fdAclTargetFilterLimit",
    "management_config": "fdManagementConfig",
    "management_user_config": "fdManagementUserConfig",
    "incremental_modifier_states": "fdIncrementalModifierStates",
    "ogroup_default_user": "fdOGroupDefaultUser",
    "force_sasl_password_ask": "fdForceSaslPasswordAsk",
    "config_checksum": "fusionConfigMd5",
    # password
    "password_default_hash": "fdPasswordDefaultHash",
    "password_min_length": "fdPasswordMinLength",
    "password_min_differ": "fdPasswordMinDiffer",
    "force_password_default_hash": "fdForcePasswordDefaultHash",
    "password_allowed_hashes": "fdPasswordAllowedHashes",
    "handle_expired_accounts": "fdHandleExpiredAccounts",
    "sasl_realm": "fdSaslRealm",
    "sasl_exop": "fdSaslExop",
    # login and session
    "login_attribute": "fdLoginAttribute",
    "session_lifetime": "fdSessionLifeTime",
    "login_method": "fdLoginMethod",
    "http_auth_enabled": "fdHttpAuthActivated",
    "http_header_auth_enabled": "fdHttpHeaderAuthActivated",
    "http_header_name": "fdHttpHeaderAuthHeaderName",
    "cas_enabled": "fdCasActivated",
    "cas_host": "fdCasHost",
    "cas_port": "fdCasPort",
    "cas_context": "fdCasContext",
    "cas_ca_cert_path": "fdCasServerCaCertPath",
    "cas_verbose": "fdCasVerbose",
    "cas_new_library": "fdCasLibraryBool",
    "cas_service_name": "fdCasClientServiceName",
    # ssl
    "force_ssl": "fdForceSSL",
    "warn_ssl": "fdWarnSSL",
    "ssl_ca_cert_path": "fdSslCaCertPath",
    "ssl_key_path": "fdSslKeyPath",
    "ssl_cert_path": "fdSslCertPath",
    # snapshots
    "snapshots_enabled": "fdEnableSnapshots",
    "snapshot_base": "fdSnapshotBase",
    "automatic_snapshots": "fdEnableAutomaticSnapshots",
    "snapshot_min_retention": "fdSnapshotMinRetention",
    "snapshot_retention_days": "fdSnapshotRetentionDays",
    "snapshot_source_data": "fdSnapshotSourceData",
    # triggers
    "tab_hooks": TAB_HOOK_ATTR,
    "display_hook_output": DISPLAY_HOOK_OUTPUT_ATTR,
    # password recovery
    "recovery_enabled": "fdPasswordRecoveryActivated",
    "recovery_email": "fdPasswordRecoveryEmail",
    "recovery_mail_subject": "fdPasswordRecoveryMailSubject",
    "recovery_mail_body": "fdPasswordRecoveryMailBody",
    "recovery_mail2_subject": "fdPasswordRecoveryMail2Subject",
    "recovery_mail2_body": "fdPasswordRecoveryMail2Body",
    "recovery_validity": "fdPasswordRecoveryValidity",
    "recovery_salt": "fdPasswordRecoverySalt",
    "recovery_use_alternate": "fdPasswordRecoveryUseAlternate",
    "recovery_login_attribute": "fdPasswordRecoveryLoginAttribute",
    # tasks
    "tasks_rdn": "fdTasksRDN",
    "tasks_last_exec_time": "fdTasksConfLastExecTime",
    "tasks_max_emails": "fdTasksConfMaxEmails",
    "tasks_interval_emails": "fdTasksConfIntervalEmails",
    # mail templates
    "mail_template_rdn": "fdMailTemplateRDN",
    # dashboard
    "dashboard_prefix": "fdDashboardPrefix",
    "dashboard_digits": "fdDashboardNumberOfDigit",
    "dashboard_expired_days": "fdDashboardExpiredAccountsDays",
    # debugging
    "display_errors": "fdDisplayErrors",
    "ldap_max_query_time": "fdLdapMaxQueryTime",
    "ldap_stats": "fdLdapStats",
    "debug_level": "fdDebugLevel",
    "debug_logging": "fdDebugLogging",
    "logging": "fdLogging",
}

CONFIG_ATTR_CLASS: Final[dict[str, str]] = {
    **{
        a: OC.PLUGINS_CONFIG
        for a in ("fdOGroupRDN", "fdForceSaslPasswordAsk", "fdOGroupDefaultUser")
    },
    **{
        a: OC.RECOVERY_CONFIG
        for a in (
            "fdPasswordRecoveryActivated",
            "fdPasswordRecoveryEmail",
            "fdPasswordRecoveryMailSubject",
            "fdPasswordRecoveryMailBody",
            "fdPasswordRecoveryMail2Subject",
            "fdPasswordRecoveryMail2Body",
            "fdPasswordRecoveryValidity",
            "fdPasswordRecoverySalt",
            "fdPasswordRecoveryUseAlternate",
            "fdPasswordRecoveryLoginAttribute",
        )
    },
    **{
        a: OC.DASHBOARD_CONFIG
        for a in ("fdDashboardPrefix", "fdDashboardNumberOfDigit", "fdDashboardExpiredAccountsDays")
    },
    **{
        a: OC.TASKS_CONF
        for a in (
            "fdTasksRDN",
            "fdTasksConfLastExecTime",
            "fdTasksConfMaxEmails",
            "fdTasksConfIntervalEmails",
        )
    },
    "fdMailTemplateRDN": MAIL_TEMPLATE_CONFIG_CLASS,
}
"""Auxiliary class of the configuration entry that allows each non-main attribute."""

CONFIG_ENTRY_CLASSES: Final = (
    OC.MAIN_CONFIG,
    OC.PLUGINS_CONFIG,
    OC.RECOVERY_CONFIG,
    OC.DASHBOARD_CONFIG,
    OC.TASKS_CONF,
    MAIL_TEMPLATE_CONFIG_CLASS,
)
"""Classes the configuration entry may carry (main first)."""
