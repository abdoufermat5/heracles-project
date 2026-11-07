"""EJBCA plugin: certificate profile objects and user certificate references."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from heracles.attributes import (
    DepartmentAttr,
    DisplayAttr,
    ListAttr,
    ObjectRefAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "ejbca"


@dataclass(slots=True)
class EjbcaSettings:
    """Settings of the EJBCA plugin."""

    certificates_rdn: str = "ou=certificates"


def settings_of(ctx: TabContext) -> EjbcaSettings:
    """Read EJBCA settings from context."""
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, EjbcaSettings) else EjbcaSettings()


def summarize_ejbca_certs(values: dict[str, Any]) -> str | None:
    """Summary of the user's referenced EJBCA certificate objects."""
    raw = values.get("fdEjbcaCertDN")
    if not isinstance(raw, list) or not raw:
        return None
    items = cast("list[object]", raw)
    lines: list[str] = []
    for item in items:
        if isinstance(item, str):
            lines.append(item)
    return "\n".join(lines) or None


class EjbcaCertificate(ObjectType):
    """An EJBCA certificate / profile entry in LDAP."""

    name = "ejbca_certificate"
    label = _("EJBCA certificate")
    label_plural = _("EJBCA certificates")
    category = "access"
    acl_category = "ejbcaCertificate"
    required_object_classes = ("top",)
    filter = "(objectClass=fdEjbcaCertificate)"
    main_attr = "cn"
    rdn = "ou=certificates"
    columns = ("cn", "description", "certificateProfile")
    search_attrs = ("cn", "description", "certificateProfile", "endEntityProfile")

    class Main(Tab):
        name = "main"
        acl_key = "ejbcaCertificate"
        label = _("Certificate")
        object_classes = ("fdEjbcaCertificate", "top")

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Certificate name"), required=True),
            TextAttr("description", _("Description")),
            StringAttr("caCertificateDN", _("CA certificate DN")),
            StringAttr("certificateProfile", _("Certificate profile")),
            StringAttr("endEntityProfile", _("End entity profile")),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if ctx.creating and not ctx.errors:
                ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))


class EjbcaCertificatesTab(Tab):
    """User tab referencing EJBCA certificates."""

    name = "ejbca"
    acl_key = "ejbcaCertificates"
    label = _("EJBCA certificates")
    optional = True
    object_classes = ("fdEjbcaCertificates",)

    certs = Section(
        _("EJBCA certificates"),
        ListAttr(
            "fdEjbcaCertDN",
            _("Certificates"),
            ObjectRefAttr("certificate", _("Certificate"), ref_type="ejbca_certificate"),
        ),
        DisplayAttr("ejbcaSummary", _("Summary"), compute=summarize_ejbca_certs),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        raw_keys = ctx.values.get("fdEjbcaCertDN")
        if not isinstance(raw_keys, list) or not raw_keys:
            ctx.values["ejbcaSummary"] = None
            return
        lines: list[str] = []
        for dn_obj in cast("list[object]", raw_keys):
            if not isinstance(dn_obj, str):
                continue
            entry = ctx.directory.get(dn_obj, ["cn", "description", "certificateProfile"])
            if entry is not None:
                cn = entry.text("cn") or ""
                profile = entry.text("certificateProfile") or ""
                desc = entry.text("description") or ""
                parts = [p for p in (cn, profile, desc) if p]
                lines.append(" - ".join(parts) if parts else dn_obj)
            else:
                lines.append(dn_obj)
        ctx.values["ejbcaSummary"] = "\n".join(lines) if lines else None


def plugin() -> Plugin:
    """Entry point of the EJBCA plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(EjbcaCertificate,),
        tabs=(TabAttachment("user", EjbcaCertificatesTab),),
        settings=EjbcaSettings(),
    )


__all__ = [
    "PLUGIN_NAME",
    "EjbcaCertificate",
    "EjbcaCertificatesTab",
    "EjbcaSettings",
    "plugin",
]
