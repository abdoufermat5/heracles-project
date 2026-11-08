"""Pure-FTPd plugin: FTP account settings, ratios, bandwidth and quota limits."""

from __future__ import annotations

from heracles.attributes import BooleanAttr, IntAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "pureftpd"


class PureFtpdStatusAttr(BooleanAttr):
    """Pure-FTPd account status boolean (accepts TRUE/FALSE and enabled/disabled)."""

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


class PureFtpdAccountTab(Tab):
    """Pure-FTPd user account tab (status, ratios, limits and allowed IPs)."""

    name = "pureftpd"
    acl_key = "pureftpdAccount"
    label = _("Pure-FTPd")
    optional = True
    object_classes = ("PureFTPdUser",)

    status = Section(
        _("Status"),
        PureFtpdStatusAttr("FTPStatus", _("FTP enabled"), default=True),
    )
    ratios = Section(
        _("Ratios"),
        IntAttr("FTPUploadRatio", _("Upload ratio"), min=0),
        IntAttr("FTPDownloadRatio", _("Download ratio"), min=0),
    )
    quotas = Section(
        _("Quotas and bandwidth"),
        IntAttr("FTPQuotaFiles", _("File quota"), min=0),
        IntAttr("FTPQuotaMBytes", _("Quota (MB)"), min=0),
        IntAttr("FTPUploadBandwidth", _("Upload bandwidth (KB/s)"), min=0),
        IntAttr("FTPDownloadBandwidth", _("Download bandwidth (KB/s)"), min=0),
    )


def plugin() -> Plugin:
    """Entry point of the Pure-FTPd plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("user", PureFtpdAccountTab),),
        required_object_classes=(),
    )


__all__ = [
    "PLUGIN_NAME",
    "PureFtpdAccountTab",
    "PureFtpdStatusAttr",
    "plugin",
]
