"""Certificates plugin: X.509 user certificates (``userCertificate;binary``)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from heracles.attributes import (
    JSON,
    AnyAttribute,
    Attribute,
    DisplayAttr,
    ListAttr,
    TextAttr,
    ValidationError,
)
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "certificates"


@dataclass(frozen=True, slots=True)
class CertificateInfo:
    """Parsed X.509 certificate details."""

    subject: str
    issuer: str
    not_valid_before: datetime
    not_valid_after: datetime
    serial_number: str
    fingerprint: str


def virtual[A: AnyAttribute](attr: A) -> A:
    """Mark an attribute as virtual (never written to LDAP)."""
    attr.stored = False
    return attr


def to_der(data: bytes | str) -> bytes:
    """Convert PEM string/bytes or DER bytes into canonical DER bytes."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    raw_str = raw.decode("utf-8", errors="ignore").strip()

    if "-----BEGIN CERTIFICATE-----" in raw_str:
        pem_part = raw_str[raw_str.index("-----BEGIN CERTIFICATE-----") :]
        end_marker = "-----END CERTIFICATE-----"
        if end_marker in pem_part:
            pem_part = pem_part[: pem_part.index(end_marker) + len(end_marker)]
        cert = x509.load_pem_x509_certificate(pem_part.encode("ascii"))
        return cert.public_bytes(serialization.Encoding.DER)

    try:
        decoded = base64.b64decode(raw, validate=True)
        if b"-----BEGIN CERTIFICATE-----" in decoded:
            cert = x509.load_pem_x509_certificate(decoded)
            return cert.public_bytes(serialization.Encoding.DER)
        cert = x509.load_der_x509_certificate(decoded)
        return cert.public_bytes(serialization.Encoding.DER)
    except (binascii.Error, ValueError):
        pass

    cert = x509.load_der_x509_certificate(raw)
    return cert.public_bytes(serialization.Encoding.DER)


def parse_cert(der: bytes) -> CertificateInfo | None:
    """Extract metadata from raw DER bytes."""
    try:
        cert = x509.load_der_x509_certificate(der)
        return CertificateInfo(
            subject=cert.subject.rfc4514_string(),
            issuer=cert.issuer.rfc4514_string(),
            not_valid_before=cert.not_valid_before_utc,
            not_valid_after=cert.not_valid_after_utc,
            serial_number=hex(cert.serial_number),
            fingerprint=cert.fingerprint(hashes.SHA256()).hex(":"),
        )
    except Exception:
        return None


def summarize_certificates(values: dict[str, Any]) -> str | None:
    """Format human-readable summary of loaded certificates."""
    raw = values.get("userCertificate;binary")
    if not isinstance(raw, list) or not raw:
        return None
    items = cast("list[object]", raw)
    lines: list[str] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, bytes):
            continue
        info = parse_cert(item)
        if info is None:
            lines.append(f"#{idx}: {_('Invalid certificate')}")
            continue
        nb = info.not_valid_before.strftime("%Y-%m-%d %H:%M:%S UTC")
        na = info.not_valid_after.strftime("%Y-%m-%d %H:%M:%S UTC")
        lines.append(
            f"#{idx}: Subject: {info.subject} | Issuer: {info.issuer} | "
            f"Valid: {nb} to {na} | SHA-256: {info.fingerprint}"
        )
    return "\n".join(lines) or None


class CertificateAttr(Attribute[bytes]):
    """X.509 certificate stored as DER bytes in LDAP."""

    kind = "certificate"

    def from_ldap(self, values: list[bytes]) -> bytes | None:
        return values[0] if values else None

    def to_ldap(self, value: bytes | None) -> list[bytes]:
        return [value] if value else []

    def from_json(self, data: object) -> bytes | None:
        if data is None or data == "":
            return None
        if not isinstance(data, (str, bytes)):
            raise ValidationError(_("Expected a base64 DER string or PEM certificate."))
        try:
            return to_der(data)
        except Exception as exc:
            raise ValidationError(
                _("Invalid X.509 certificate: {msg}").format(msg=str(exc))
            ) from None

    def to_json(self, value: bytes | None) -> JSON:
        return base64.b64encode(value).decode("ascii") if value else None


class UserCertificatesTab(Tab):
    """X.509 user certificates tab on user accounts."""

    name = "certificates"
    acl_key = "userCertificates"
    label = _("Certificates")
    optional = True
    object_classes = ("strongAuthenticationUser",)

    certs = Section(
        _("X.509 certificates"),
        ListAttr(
            "userCertificate;binary",
            _("Certificates (DER/PEM)"),
            CertificateAttr("certificate", _("Certificate")),
        ),
        DisplayAttr(
            "certificateSummary",
            _("Parsed certificates"),
            compute=summarize_certificates,
        ),
        virtual(TextAttr("pem_import", _("Paste PEM certificate to import"))),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        if not ctx.values.get("userCertificate;binary") and ctx.dn:
            entry = ctx.directory.get(ctx.dn, ["userCertificate"])
            if entry is not None:
                fallback = entry.get("userCertificate")
                if fallback:
                    loaded_fallback: list[bytes] = []
                    for v in fallback:
                        try:
                            loaded_fallback.append(to_der(v))
                        except Exception:
                            loaded_fallback.append(v)
                    ctx.values["userCertificate;binary"] = loaded_fallback
        ctx.values["certificateSummary"] = summarize_certificates(ctx.values)
        ctx.values["pem_import"] = ""

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        pem_text = ctx.values.get("pem_import")
        if isinstance(pem_text, str) and pem_text.strip():
            try:
                der = to_der(pem_text)
                current = ctx.values.get("userCertificate;binary")
                current_certs: list[bytes] = (
                    [b for b in cast("list[object]", current) if isinstance(b, bytes)]
                    if isinstance(current, list)
                    else []
                )
                current_certs.append(der)
                ctx.values["userCertificate;binary"] = current_certs
                ctx.values["pem_import"] = ""
            except Exception as exc:
                ctx.error("pem_import", _("Invalid PEM certificate: {msg}").format(msg=str(exc)))


def plugin() -> Plugin:
    """Entry point of the certificates plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("user", UserCertificatesTab),),
    )


__all__ = [
    "PLUGIN_NAME",
    "CertificateAttr",
    "CertificateInfo",
    "UserCertificatesTab",
    "parse_cert",
    "plugin",
    "summarize_certificates",
    "to_der",
]
