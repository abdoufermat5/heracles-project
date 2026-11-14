"""Identifiers of the external LDAP schemas that the real servers read.

Heracles keeps its own ``hrc*`` schema (:mod:`heracles.schema.definitions`). Two
plugins, however, must write the standard attributes that the installed servers
read from the directory unchanged:

* ``smb_accounts`` — the SMB domain schema (``deploy/ldap/schema/12-smb.ldif``):
  ``sambaSamAccount``, ``sambaGroupMapping``, ``sambaDomain``, ``sambaIdmapEntry``,
  ``sambaUnixIdPool`` and their ``samba*`` attributes;
* ``ftp_accounts`` — the FTP server's account schema
  (``deploy/ldap/schema/13-ftp.ldif``): ``PureFTPdUser`` and its ``FTP*``
  attributes.

Those servers ignore ``hrc*`` names, so the plugins keep the external ones. This
module holds them: it is the single place allowed to spell them, and
``backend/tests/test_no_legacy_names.py`` reads :data:`EXTERNAL_SCHEMA_NAMES` to
allow exactly these identifiers (and nothing else) outside it. Module ids, tab
names, labels and UI strings stay generic (``smb_accounts``, ``ftp_accounts``,
"SMB", "FTP").
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------- SMB objectClasses

#: Auxiliary class of a user or machine account (``uid`` and ``sambaSID`` required).
SMB_ACCOUNT_CLASS: Final = "sambaSamAccount"
#: Auxiliary class of a POSIX group (``gidNumber``, ``sambaSID``, ``sambaGroupType``).
SMB_GROUP_MAPPING_CLASS: Final = "sambaGroupMapping"
#: Structural class of a domain entry (``sambaDomainName`` and ``sambaSID`` required).
SMB_DOMAIN_CLASS: Final = "sambaDomain"
#: Auxiliary class mapping a SID to a unix id (optional id-mapping setting).
SMB_IDMAP_CLASS: Final = "sambaIdmapEntry"
#: Auxiliary class holding the unix id pool of a domain.
SMB_UNIX_ID_POOL_CLASS: Final = "sambaUnixIdPool"

# ----------------------------------------------------------------- FTP objectClass

#: Auxiliary class of an FTP account.
FTP_ACCOUNT_CLASS: Final = "PureFTPdUser"

# --------------------------------------------------------------------- attributes

SMB_ATTRIBUTES: Final = (
    "sambaAcctFlags",
    "sambaAlgorithmicRidBase",
    "sambaDomainName",
    "sambaForceLogoff",
    "sambaGroupType",
    "sambaHomeDrive",
    "sambaHomePath",
    "sambaKickoffTime",
    "sambaLMPassword",
    "sambaLockoutDuration",
    "sambaLockoutObservationWindow",
    "sambaLockoutThreshold",
    "sambaLogonHours",
    "sambaLogonScript",
    "sambaLogonToChgPwd",
    "sambaMaxPwdAge",
    "sambaMinPwdAge",
    "sambaMinPwdLength",
    "sambaMungedDial",
    "sambaNTPassword",
    "sambaNextGroupRid",
    "sambaNextRid",
    "sambaNextUserRid",
    "sambaPasswordHistory",
    "sambaPrimaryGroupSID",
    "sambaProfilePath",
    "sambaPwdHistoryLength",
    "sambaPwdLastSet",
    "sambaRefuseMachinePwdChange",
    "sambaSID",
    "sambaSIDList",
    "sambaUserWorkstations",
)
"""``samba*`` attributes the SMB plugins read or write."""

FTP_ATTRIBUTES: Final = (
    "FTPDownloadBandwidth",
    "FTPDownloadRatio",
    "FTPQuotaFiles",
    "FTPQuotaMBytes",
    "FTPStatus",
    "FTPUploadBandwidth",
    "FTPUploadRatio",
)
"""``FTP*`` attributes the FTP plugin reads or writes."""

EXTERNAL_SCHEMA_NAMES: Final = frozenset(
    {
        SMB_ACCOUNT_CLASS,
        SMB_GROUP_MAPPING_CLASS,
        SMB_DOMAIN_CLASS,
        SMB_IDMAP_CLASS,
        SMB_UNIX_ID_POOL_CLASS,
        FTP_ACCOUNT_CLASS,
        *SMB_ATTRIBUTES,
        *FTP_ATTRIBUTES,
    }
)
"""Every external schema identifier Heracles writes (see the module docstring)."""

__all__ = [
    "EXTERNAL_SCHEMA_NAMES",
    "FTP_ACCOUNT_CLASS",
    "FTP_ATTRIBUTES",
    "SMB_ACCOUNT_CLASS",
    "SMB_ATTRIBUTES",
    "SMB_DOMAIN_CLASS",
    "SMB_GROUP_MAPPING_CLASS",
    "SMB_IDMAP_CLASS",
    "SMB_UNIX_ID_POOL_CLASS",
]
