"""Custom attribute types and helpers for the DHCP plugin."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from heracles.attributes import CompositeAttr, ListAttr, SelectAttr, StringAttr, TextAttr
from heracles.attributes.base import ValidationError
from heracles.i18n import _
from heracles_plugins.dhcp.validation import validate_mac


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written directly to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


class MacAddressAttr(StringAttr):
    """A MAC address (6 hex pairs separated by colons or hyphens)."""

    kind = "string"

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        err = validate_mac(value)
        if err is not None:
            errors.append(err)
        return errors


class Base64StringAttr(StringAttr):
    """A string whose content must be valid base64 data."""

    kind = "string"

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        try:
            base64.b64decode(value.strip().encode("ascii"), validate=True)
        except (binascii.Error, ValueError):
            errors.append(_("Invalid base64 data."))
        return errors


class HwAddressAttr(CompositeAttr):
    """Hardware address '<type> <mac>' exposing type select and MAC address."""

    def __init__(
        self,
        name: str = "dhcpHWAddress",
        label: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name,
            label or _("Hardware address"),
            [
                SelectAttr(
                    "type",
                    _("Hardware type"),
                    options=[
                        ("ethernet", _("Ethernet")),
                        ("token-ring", _("Token Ring")),
                    ],
                ),
                MacAddressAttr("mac", _("MAC address")),
            ],
            separator=" ",
            **kwargs,
        )

    def from_json(self, data: object) -> dict[str, Any] | None:
        if data is None or data == "":
            return None
        if isinstance(data, str):
            type_, sep, mac = data.strip().partition(" ")
            if not sep:
                raise ValidationError(_("Hardware address must be '<type> <mac>'."))
            return super().from_json({"type": type_.strip(), "mac": mac.strip()})
        if isinstance(data, dict):
            raw_dict: dict[object, object] = data  # pyright: ignore[reportUnknownVariableType]
            work: dict[str, object] = {str(k): v for k, v in raw_dict.items()}
            if "hardware_type" in work and "type" not in work:
                work["type"] = work.pop("hardware_type")
            if "mac_address" in work and "mac" not in work:
                work["mac"] = work.pop("mac_address")
            return super().from_json(work)
        return super().from_json(data)


def dhcp_options_attr() -> ListAttr[str]:
    """dhcpOption: list of DHCP option statements."""
    return ListAttr[str](
        "dhcpOption",
        _("DHCP options"),
        StringAttr("option", _("Option")),
    )


def dhcp_statements_attr() -> ListAttr[str]:
    """dhcpStatements: list of DHCP configuration statements."""
    return ListAttr[str](
        "dhcpStatements",
        _("DHCP statements"),
        StringAttr("statement", _("Statement")),
    )


def dhcp_comments_attr() -> TextAttr:
    """dhcpComments: section comments."""
    return TextAttr("dhcpComments", _("Comments"))


def dhcp_range_attr() -> ListAttr[str]:
    """dhcpRange: list of '<start> <end>' IP address ranges."""
    return ListAttr[str](
        "dhcpRange",
        _("IP ranges"),
        StringAttr("range", _("Range")),
    )
