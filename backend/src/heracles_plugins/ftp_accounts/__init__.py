"""FTP plugin: FTP account settings, ratios, bandwidth and quota limits."""

from __future__ import annotations

from heracles.attributes import BooleanAttr, IntAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "ftp_accounts"


class FtpStatusAttr(BooleanAttr):
    """FTP account status boolean (accepts TRUE/FALSE and enabled/disabled)."""

    def from_ldap(self, values: list[bytes]) -> bool | None:
        if not values:
            return None
        text = values[0].decode("ascii", errors="replace").strip().upper()
        if text in ("TRUE", "1", "ENABLED"):
            return True
        if text in ("FALSE", "0", "DISABLED"):
            return False
        return None

    def to_ldap(self, value: bool | None) -> list[bytes]:
        if value is None:
            return []
        return [b"TRUE" if value else b"FALSE"]


class FtpAccountTab(Tab):
    """FTP user account tab (status, ratios, limits and allowed IPs)."""

    name = "ftp_accounts"
    acl_key = "ftpAccount"
    label = _("FTP")
    description = _("FTP account: home, quotas and bandwidth limits")
    optional = True
    object_classes = ("hrcFtpAccount",)

    status = Section(
        _("Status"),
        FtpStatusAttr("hrcFtpStatus", _("FTP enabled"), default=True),
    )
    ratios = Section(
        _("Ratios"),
        IntAttr("hrcFtpUploadRatio", _("Upload ratio"), min=0),
        IntAttr("hrcFtpDownloadRatio", _("Download ratio"), min=0),
    )
    quotas = Section(
        _("Quotas and bandwidth"),
        IntAttr("hrcFtpQuotaFiles", _("File quota"), min=0),
        IntAttr("hrcFtpQuotaMBytes", _("Quota (MB)"), min=0),
        IntAttr("hrcFtpUploadBandwidth", _("Upload bandwidth (KB/s)"), min=0),
        IntAttr("hrcFtpDownloadBandwidth", _("Download bandwidth (KB/s)"), min=0),
    )


def plugin() -> Plugin:
    """Entry point of the FTP plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("user", FtpAccountTab),),
        required_object_classes=(),
    )


__all__ = [
    "PLUGIN_NAME",
    "FtpAccountTab",
    "FtpStatusAttr",
    "plugin",
]
