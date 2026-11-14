# ruff: noqa: S105
# (attribute *names* such as the token attribute are not secrets)
"""Heracles LDAP schema names.

The objectClass and attribute names Heracles stores in the directory. They are
defined by the Heracles schema (``deploy/ldap/schema/``, generated from
:mod:`heracles.schema.definitions`); once deployed they must not change. They are
never shown in the end-user UI.
"""

from __future__ import annotations

import re
from dataclasses import astuple, dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ObjectClasses:
    """Heracles objectClass names."""

    DEPARTMENT: str = "hrcDepartment"
    OBJECT_GROUP: str = "hrcGroupOfNames"
    ACL_ROLE: str = "hrcRole"
    ACL_ASSIGNMENT: str = "hrcAcl"
    SNAPSHOT: str = "hrcSnapshotObject"
    LOCK: str = "hrcLockEntry"
    TOKEN: str = "hrcTokenEntry"
    MAIL_TEMPLATE: str = "hrcMailTemplate"
    TEMPLATE: str = "hrcTemplate"
    TASKS: str = "hrcTasks"
    TASKS_MAIL: str = "hrcTasksMail"
    TASKS_GRANULAR: str = "hrcTasksGranular"
    TASKS_CONF: str = "hrcTasksConf"
    MAIN_CONFIG: str = "hrcConf"
    PLUGINS_CONFIG: str = "hrcPluginsConf"
    RECOVERY_CONFIG: str = "hrcPasswordRecoveryConf"
    DASHBOARD_CONFIG: str = "hrcDashboardPluginConf"


@dataclass(frozen=True, slots=True)
class StandardClasses:
    """Standard objectClasses used as-is."""

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
    """Heracles attribute names."""

    # Department / object group
    GROUP_OBJECTS: str = "hrcGroupObjects"
    # ACL
    ACL_TEMPLATE: str = "hrcAclTemplate"
    ACL_ENTRY: str = "hrcAclEntry"
    # Snapshot
    SNAPSHOT_TIMESTAMP: str = "hrcSnapshotTimestamp"
    SNAPSHOT_DN: str = "hrcSnapshotDN"
    SNAPSHOT_DATA: str = "hrcSnapshotData"
    SNAPSHOT_DATA_SOURCE: str = "hrcSnapshotDataSource"
    SNAPSHOT_OBJECT_TYPE: str = "hrcSnapshotObjectType"
    SNAPSHOT_HASH: str = "hrcSnapshotHash"
    # Edit lock
    LOCK_USER_DN: str = "hrcUserDn"
    LOCK_OBJECT_DN: str = "hrcObjectDn"
    LOCK_TIMESTAMP: str = "hrcLockTimestamp"
    # Token
    TOKEN_USER_DN: str = "hrcTokenUserDN"
    TOKEN_TYPE: str = "hrcTokenType"
    TOKEN: str = "hrcToken"
    TOKEN_TIMESTAMP: str = "hrcTokenTimestamp"
    # Mail template
    MAIL_TEMPLATE_BODY: str = "hrcMailTemplateBody"
    MAIL_TEMPLATE_SUBJECT: str = "hrcMailTemplateSubject"
    MAIL_TEMPLATE_SIGNATURE: str = "hrcMailTemplateSignature"
    MAIL_TEMPLATE_READ_RECEIPT: str = "hrcMailTemplateReadReceipt"


@dataclass(frozen=True, slots=True)
class StandardAttrs:
    """Standard attribute names Heracles relies on."""

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
    APP: str = "ou=heracles"
    LOCKS: str = "ou=locks,ou=heracles"
    TOKENS: str = "ou=tokens,ou=heracles"
    RECOVERY_TOKENS: str = "ou=recovery,ou=tokens,ou=heracles"
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

APP_OU: Final = "ou=heracles"
"""Application organizational unit (never shown)."""

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

CORE_OBJECT_CLASSES: Final = frozenset(str(v) for v in astuple(OC))
"""All core Heracles objectClass names (original case)."""

PLUGIN_OBJECT_CLASSES: Final = frozenset(
    {
        # dns
        "dNSZone",
        "hrcDNSView",
        "hrcDNSAcl",
        # systems
        "device",
        "ieee802Device",
        "ipHost",
        "hrcServer",
        "hrcWorkstation",
        "hrcTerminal",
        "hrcPrinter",
        "hrcPhone",
        "hrcMobilePhone",
        "hrcNetworkInterface",
        # tasks / reminders
        "hrcTasksReminder",
        # password policies
        "pwdPolicyChecker",
        # personal information
        "hrcPersonalInfo",
        # mail
        "hrcMailAccount",
        "hrcGroupMail",
        "hrcMailAliasRedirection",
        "hrcMailAliasDistribution",
        # samba
        "sambaSamAccount",
        "sambaGroupMapping",
        "sambaDomain",
        "sambaIdmapEntry",
        "sambaUnixIdPool",
        # workflow tasks
        "hrcAuditEvent",
        "hrcAuditTasks",
        "hrcArchivedObject",
        "hrcArchiveTasks",
        "hrcTasksLifeCycle",
        "hrcTasksNotifications",
        "hrcExtractorTasks",
        "hrcTasksAutomaticGroups",
        # applications, groups, service accounts, forms
        "hrcDesktopApplication",
        "hrcWebApplication",
        "hrcApplicationRights",
        "groupOfURLs",
        "extensibleObject",
        "simpleSecurityObject",
        "hrcInvitation",
        "hrcRegistration",
        "hrcUserRegistration",
        "hrcPublicForm",
        # network: ipam, netgroups, autofs, IPMI, web links
        "hrcIpamVlan",
        "hrcIpamSubnet",
        "nisNetgroup",
        "automountMap",
        "automount",
        "hrcIpmiClient",
        "hrcWebLinkAccount",
        # security: kerberos, certificates, PGP, physical keys, PKI references
        "krbPrincipalAux",
        "krbTicketPolicyAux",
        "strongAuthenticationUser",
        "hrcGpgAccount",
        "pgpKeyInfo",
        "pgpServerInfo",
        "hrcPhysicalKey",
        "hrcEjbcaCertificates",
        # mail and collaboration services
        "hrcCyrusServer",
        "hrcDovecotServer",
        "hrcPostfixServer",
        "hrcSieveServer",
        "hrcZimbraServer",
        "hrcSpamAssassinServer",
        "hrcSpamAssassinUser",
        "hrcMailInBlackUser",
        # account extensions
        "hrcNextCloudAccount",
        "PureFTPdUser",
        "hrcQuotaService",
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
"""objectClasses used by the first-party plugins (standard and Heracles schemas)."""

# --- P3 objects ---
TEMPLATE_FIELD_ATTR: Final = "hrcTemplateField"
"""Multi-valued attribute of a template entry; each value is ``<attribute>:<value>``."""

INCREMENTAL_STATES_ATTR: Final = "hrcIncrementalModifierStates"
"""Attribute of the main configuration entry holding incremental counters (``<id>;<value>``)."""

TEMPLATES_RDN: Final = "ou=templates"
"""Container of the templates of a type, relative to the type's own container."""
# --- end P3 objects ---

# --- P3 admin ---------------------------------------------------------------

MAIL_TEMPLATE_CONFIG_CLASS: Final = "hrcMailTemplateConf"
"""Auxiliary class of the configuration entry holding the mail template settings."""

TAB_HOOK_ATTR: Final = "hrcTabHook"
"""Multi-valued attribute of the configuration entry holding the triggers."""

DISPLAY_HOOK_OUTPUT_ATTR: Final = "hrcDisplayHookOutput"
"""Single-valued boolean: show the successful output of a trigger to the user."""

TASKS_GRANULAR_MASTER_ATTR: Final = "hrcTasksGranularMaster"
TASKS_GRANULAR_STATUS_ATTR: Final = "hrcTasksGranularStatus"
TASKS_GRANULAR_NEXT_EXEC_ATTR: Final = "hrcTasksGranularNextExec"
TASKS_GRANULAR_LAST_EXEC_ATTR: Final = "hrcTasksGranularLastExec"
TASKS_GRANULAR_TYPE_ATTR: Final = "hrcTasksGranularType"
TASKS_STATUS_ATTR: Final = "hrcTasksStatus"
TASKS_NEXT_EXEC_ATTR: Final = "hrcTasksNextExec"
TASKS_LAST_EXEC_ATTR: Final = "hrcTasksLastExec"
TASKS_CREATION_DATE_ATTR: Final = "hrcTasksCreationDate"
"""Task bookkeeping attributes (read by the task dashboard)."""

# Heracles configuration key -> attribute name, for the configuration entry.
CONFIG_ATTRS: Final[dict[str, str]] = {
    # look and feel
    "language": "hrcLanguage",
    "theme": "hrcTheme",
    "timezone": "hrcTimezone",
    # core
    "schema_check": "hrcSchemaCheck",
    "account_primary_attribute": "hrcAccountPrimaryAttribute",
    "next_id_hook": "hrcNextIdHook",
    "strict_naming_rules": "hrcStrictNamingRules",
    "min_id": "hrcMinId",
    "uid_number_base": "hrcUidNumberBase",
    "gid_number_base": "hrcGidNumberBase",
    "user_rdn": "hrcUserRDN",
    "group_rdn": "hrcGroupRDN",
    "acl_role_rdn": "hrcAclRoleRDN",
    "ogroup_rdn": "hrcOGroupRDN",
    "token_rdn": "hrcTokenRDN",
    "orchestrator_token_rdn": "hrcOrchestratorTokenRDN",
    "recovery_token_rdn": "hrcRecoveryTokenRDN",
    "id_allocation_method": "hrcIdAllocationMethod",
    "gid_pool_min": "hrcGidNumberPoolMin",
    "gid_pool_max": "hrcGidNumberPoolMax",
    "uid_pool_min": "hrcUidNumberPoolMin",
    "uid_pool_max": "hrcUidNumberPoolMax",
    "cn_pattern": "hrcCnPattern",
    "restrict_role_members": "hrcRestrictRoleMembers",
    "split_postal_address": "hrcSplitPostalAddress",
    "postal_address_pattern": "hrcPostalAddressPattern",
    "max_avatar_size": "hrcMaxAvatarSize",
    "given_name_required": "hrcGivenNameRequired",
    "list_summary": "hrcListSummary",
    "modification_detection_attribute": "hrcModificationDetectionAttribute",
    "ldap_size_limit": "hrcLdapSizeLimit",
    "wildcard_foreign_keys": "hrcWildcardForeignKeys",
    "store_filter_settings": "hrcStoreFilterSettings",
    "shells": "hrcShells",
    "default_shell": "hrcDefaultShell",
    "acl_tab_on_objects": "hrcAclTabOnObjects",
    "department_categories": "hrcDepartmentCategories",
    "plugins_menu_blacklist": "hrcPluginsMenuBlacklist",
    "acl_target_filter_limit": "hrcAclTargetFilterLimit",
    "management_config": "hrcManagementConfig",
    "management_user_config": "hrcManagementUserConfig",
    "incremental_modifier_states": "hrcIncrementalModifierStates",
    "ogroup_default_user": "hrcOGroupDefaultUser",
    "force_sasl_password_ask": "hrcForceSaslPasswordAsk",
    "config_checksum": "hrcConfigMd5",
    # password
    "password_default_hash": "hrcPasswordDefaultHash",
    "password_min_length": "hrcPasswordMinLength",
    "password_min_differ": "hrcPasswordMinDiffer",
    "force_password_default_hash": "hrcForcePasswordDefaultHash",
    "password_allowed_hashes": "hrcPasswordAllowedHashes",
    "handle_expired_accounts": "hrcHandleExpiredAccounts",
    "sasl_realm": "hrcSaslRealm",
    "sasl_exop": "hrcSaslExop",
    # login and session
    "login_attribute": "hrcLoginAttribute",
    "session_lifetime": "hrcSessionLifeTime",
    "login_method": "hrcLoginMethod",
    "http_auth_enabled": "hrcHttpAuthActivated",
    "http_header_auth_enabled": "hrcHttpHeaderAuthActivated",
    "http_header_name": "hrcHttpHeaderAuthHeaderName",
    "cas_enabled": "hrcCasActivated",
    "cas_host": "hrcCasHost",
    "cas_port": "hrcCasPort",
    "cas_context": "hrcCasContext",
    "cas_ca_cert_path": "hrcCasServerCaCertPath",
    "cas_verbose": "hrcCasVerbose",
    "cas_new_library": "hrcCasLibraryBool",
    "cas_service_name": "hrcCasClientServiceName",
    # ssl
    "force_ssl": "hrcForceSSL",
    "warn_ssl": "hrcWarnSSL",
    "ssl_ca_cert_path": "hrcSslCaCertPath",
    "ssl_key_path": "hrcSslKeyPath",
    "ssl_cert_path": "hrcSslCertPath",
    # snapshots
    "snapshots_enabled": "hrcEnableSnapshots",
    "snapshot_base": "hrcSnapshotBase",
    "automatic_snapshots": "hrcEnableAutomaticSnapshots",
    "snapshot_min_retention": "hrcSnapshotMinRetention",
    "snapshot_retention_days": "hrcSnapshotRetentionDays",
    "snapshot_source_data": "hrcSnapshotSourceData",
    # triggers
    "tab_hooks": TAB_HOOK_ATTR,
    "display_hook_output": DISPLAY_HOOK_OUTPUT_ATTR,
    # password recovery
    "recovery_enabled": "hrcPasswordRecoveryActivated",
    "recovery_email": "hrcPasswordRecoveryEmail",
    "recovery_mail_subject": "hrcPasswordRecoveryMailSubject",
    "recovery_mail_body": "hrcPasswordRecoveryMailBody",
    "recovery_mail2_subject": "hrcPasswordRecoveryMail2Subject",
    "recovery_mail2_body": "hrcPasswordRecoveryMail2Body",
    "recovery_validity": "hrcPasswordRecoveryValidity",
    "recovery_salt": "hrcPasswordRecoverySalt",
    "recovery_use_alternate": "hrcPasswordRecoveryUseAlternate",
    "recovery_login_attribute": "hrcPasswordRecoveryLoginAttribute",
    # tasks
    "tasks_rdn": "hrcTasksRDN",
    "tasks_last_exec_time": "hrcTasksConfLastExecTime",
    "tasks_max_emails": "hrcTasksConfMaxEmails",
    "tasks_interval_emails": "hrcTasksConfIntervalEmails",
    # mail templates
    "mail_domain": "hrcMailDomain",
    "mail_template_rdn": "hrcMailTemplateRDN",
    # dashboard
    "dashboard_prefix": "hrcDashboardPrefix",
    "dashboard_digits": "hrcDashboardNumberOfDigit",
    "dashboard_expired_days": "hrcDashboardExpiredAccountsDays",
    # debugging
    "display_errors": "hrcDisplayErrors",
    "ldap_max_query_time": "hrcLdapMaxQueryTime",
    "ldap_stats": "hrcLdapStats",
    "debug_level": "hrcDebugLevel",
    "debug_logging": "hrcDebugLogging",
    "logging": "hrcLogging",
}

CONFIG_ATTR_CLASS: Final[dict[str, str]] = {
    **{
        a: OC.PLUGINS_CONFIG
        for a in ("hrcOGroupRDN", "hrcForceSaslPasswordAsk", "hrcOGroupDefaultUser")
    },
    **{
        a: OC.RECOVERY_CONFIG
        for a in (
            "hrcPasswordRecoveryActivated",
            "hrcPasswordRecoveryEmail",
            "hrcPasswordRecoveryMailSubject",
            "hrcPasswordRecoveryMailBody",
            "hrcPasswordRecoveryMail2Subject",
            "hrcPasswordRecoveryMail2Body",
            "hrcPasswordRecoveryValidity",
            "hrcPasswordRecoverySalt",
            "hrcPasswordRecoveryUseAlternate",
            "hrcPasswordRecoveryLoginAttribute",
        )
    },
    **{
        a: OC.DASHBOARD_CONFIG
        for a in (
            "hrcDashboardPrefix",
            "hrcDashboardNumberOfDigit",
            "hrcDashboardExpiredAccountsDays",
        )
    },
    **{
        a: OC.TASKS_CONF
        for a in (
            "hrcTasksRDN",
            "hrcTasksConfLastExecTime",
            "hrcTasksConfMaxEmails",
            "hrcTasksConfIntervalEmails",
        )
    },
    "hrcMailTemplateRDN": MAIL_TEMPLATE_CONFIG_CLASS,
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


# --- P3 compat ---
@dataclass(frozen=True, slots=True)
class SsoConfigAttrs:
    """Single-valued attributes of the main configuration entry describing the login methods."""

    LOGIN_METHOD: str = "hrcLoginMethod"
    HTTP_AUTH_ACTIVATED: str = "hrcHttpAuthActivated"
    HTTP_HEADER_AUTH_ACTIVATED: str = "hrcHttpHeaderAuthActivated"
    HTTP_HEADER_AUTH_HEADER_NAME: str = "hrcHttpHeaderAuthHeaderName"
    CAS_ACTIVATED: str = "hrcCasActivated"
    CAS_HOST: str = "hrcCasHost"
    CAS_PORT: str = "hrcCasPort"
    CAS_CONTEXT: str = "hrcCasContext"
    CAS_SERVER_CA_CERT_PATH: str = "hrcCasServerCaCertPath"
    CAS_VERBOSE: str = "hrcCasVerbose"
    CAS_LIBRARY_BOOL: str = "hrcCasLibraryBool"
    CAS_CLIENT_SERVICE_NAME: str = "hrcCasClientServiceName"


SSO_ATTR: Final = SsoConfigAttrs()
