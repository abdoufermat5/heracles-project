"""EJBCA plugin: certificates published in the directory by the PKI, referenced by users.

The PKI publishes certificate entries itself (under ``ou=certificates``); Heracles only
shows them (read-only: name and the X.509 details of ``userCertificate;binary``) and lets
users, servers and other systems reference them (``hrcEjbcaCertificates``). No call is made
to the PKI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from heracles.attributes import DisplayAttr, ListAttr, ObjectRefAttr, StringAttr
from heracles.i18n import _
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext
from heracles_plugins.certificates import CertificateAttr, parse_cert, virtual

PLUGIN_NAME = "ejbca"
CERT_ATTR = "userCertificate;binary"
#: Types that can reference PKI certificates.
REFERENCING_TYPES = (
    "user",
    "server",
    "workstation",
    "terminal",
    "printer",
    "component",
    "phone",
    "mobile_phone",
)


@dataclass(slots=True)
class EjbcaSettings:
    """Settings of the EJBCA plugin."""

    certificates_rdn: str = "ou=certificates"


def describe_certificate(der: object) -> str | None:
    """One-line summary of a DER certificate."""
    if not isinstance(der, bytes):
        return None
    info = parse_cert(der)
    if info is None:
        return _("Invalid certificate")
    return _("Subject: {s} | Issuer: {i} | Valid until: {d} | SHA-256: {f}").format(
        s=info.subject,
        i=info.issuer,
        d=info.not_valid_after.strftime("%Y-%m-%d"),
        f=info.fingerprint,
    )


class EjbcaCertificate(ObjectType):
    """A certificate entry published by the PKI (read-only)."""

    name = "ejbca_certificate"
    label = _("PKI certificate")
    label_plural = _("PKI certificates")
    category = "access"
    acl_category = "ejbcaCertificate"
    filter = f"({CERT_ATTR}=*)"
    main_attr = "cn"
    rdn = "ou=certificates"
    columns = ("cn",)
    search_attrs = ("cn",)

    class Main(Tab):
        name = "main"
        acl_key = "ejbcaCertificate"
        label = _("Certificate")
        object_classes = ()

        certificate = Section(
            _("Certificate"),
            StringAttr("cn", _("Name"), readonly=True),
            CertificateAttr(CERT_ATTR, _("Certificate (DER)"), readonly=True),
            virtual(DisplayAttr("certificateSummary", _("Details"), compute=lambda v: None)),
        )

        @classmethod
        def on_load(cls, ctx: TabContext) -> None:
            ctx.values["certificateSummary"] = describe_certificate(ctx.values.get(CERT_ATTR))

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if ctx.creating:
                ctx.error("cn", _("Certificates are published by the PKI, not created here."))


def _summarize_refs(values: dict[str, Any]) -> str | None:
    return values.get("ejbcaSummary") if isinstance(values.get("ejbcaSummary"), str) else None


class EjbcaCertificatesTab(Tab):
    """References to PKI certificates (users and systems)."""

    name = "ejbca"
    acl_key = "ejbcaCertificates"
    label = _("PKI certificates")
    optional = True
    object_classes = ("hrcEjbcaCertificates",)

    certs = Section(
        _("PKI certificates"),
        ListAttr(
            "hrcEjbcaCertDN",
            _("Certificates"),
            ObjectRefAttr("certificate", _("Certificate"), ref_type="ejbca_certificate"),
            required=True,
        ),
        virtual(DisplayAttr("ejbcaSummary", _("Summary"), compute=_summarize_refs)),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        lines: list[str] = []
        for dn in cast("list[object]", ctx.values.get("hrcEjbcaCertDN") or []):
            if not isinstance(dn, str):
                continue
            entry = ctx.directory.get(dn, ["cn", CERT_ATTR])
            if entry is None:
                lines.append(_("{dn} (not found)").format(dn=dn))
                continue
            detail = describe_certificate(entry.first(CERT_ATTR))
            lines.append(
                f"{entry.text('cn') or dn}: {detail}" if detail else entry.text("cn") or dn
            )
        ctx.values["ejbcaSummary"] = "\n".join(lines) or None


def _attachment(type_name: str) -> TabAttachment:
    # one tab class per target type (a tab class can only be attached once per type)
    return TabAttachment(type_name, EjbcaCertificatesTab)


def plugin() -> Plugin:
    """Entry point of the EJBCA plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(EjbcaCertificate,),
        tabs=tuple(_attachment(t) for t in REFERENCING_TYPES),
        required_object_classes=("hrcEjbcaCertificates",),
        settings=EjbcaSettings(),
    )


__all__ = [
    "CERT_ATTR",
    "PLUGIN_NAME",
    "REFERENCING_TYPES",
    "EjbcaCertificate",
    "EjbcaCertificatesTab",
    "EjbcaSettings",
    "describe_certificate",
    "plugin",
]
