"""Compound attribute kinds: ``list`` and ``composite``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from heracles.attributes.base import JSON, Attribute, ValidationError, is_empty
from heracles.attributes.keys import field_key, item_key
from heracles.i18n import _


class ListAttr[T](Attribute[list[T]]):
    """Ordered multi-valued attribute whose elements are described by ``item``."""

    kind = "list"
    multivalued = True

    def __init__(self, name: str, label: str, item: Attribute[T], **kwargs: Any) -> None:
        super().__init__(name, label, **kwargs)
        self.item = item
        self.stored = item.stored

    def from_ldap(self, values: list[bytes]) -> list[T] | None:
        items: list[T] = []
        for raw in values:
            parsed = self.item.from_ldap([raw])
            if parsed is not None:
                items.append(parsed)
        return items or None

    def to_ldap(self, value: list[T] | None) -> list[bytes]:
        out: list[bytes] = []
        for element in value or []:
            out.extend(self.item.to_ldap(element)[:1])
        return out

    def from_json(self, data: object) -> list[T] | None:
        if data is None:
            return None
        if not isinstance(data, list):
            raise ValidationError(_("Expected a list."))
        items: list[T] = []
        for element in cast("list[object]", data):
            parsed = self.item.from_json(element)
            if parsed is not None:
                items.append(parsed)
        return items or None

    def to_json(self, value: list[T] | None) -> JSON:
        if value is None:
            return None
        return [self.item.to_json(v) for v in value]

    def _validate(self, value: list[T]) -> list[str]:
        errors: list[str] = []
        if self.min_length is not None and len(value) < self.min_length:
            errors.append(_("At least {n} values are required.").format(n=self.min_length))
        if self.max_length is not None and len(value) > self.max_length:
            errors.append(_("At most {n} values are allowed.").format(n=self.max_length))
        for element in value:
            for message in self.item.validate(element):
                if message not in errors:
                    errors.append(message)
        return errors

    def describe_extra(self, key: str = "") -> dict[str, JSON]:
        return {"item": self.item.describe(item_key(key) if key else "")}


class CompositeAttr(Attribute[dict[str, Any]]):
    """Several named sub-fields packed in one LDAP value (``"a;b;c"``).

    Fields are positional: the order of ``fields`` is the order in the packed
    value. Missing trailing parts are read as empty. The separator must not
    occur in a sub-field value (reported by :meth:`validate`).
    """

    kind = "composite"

    def __init__(
        self,
        name: str,
        label: str,
        fields: Sequence[Attribute[Any]],
        *,
        separator: str = ";",
        **kwargs: Any,
    ) -> None:
        super().__init__(name, label, **kwargs)
        if not separator:
            raise ValueError("separator must not be empty")
        self.fields = tuple(fields)
        self.separator = separator

    def _pack_field(self, field: Attribute[Any], value: Any) -> str:
        raw = field.to_ldap(value)
        return raw[0].decode("utf-8") if raw else ""

    def from_ldap(self, values: list[bytes]) -> dict[str, Any] | None:
        if not values:
            return None
        parts = (
            values[0].decode("utf-8", errors="replace").split(self.separator, len(self.fields) - 1)
        )
        parts += [""] * (len(self.fields) - len(parts))
        result: dict[str, Any] = {}
        for field, part in zip(self.fields, parts, strict=True):
            result[field.name] = field.from_ldap([part.encode("utf-8")]) if part else None
        return result if any(v is not None for v in result.values()) else None

    def to_ldap(self, value: dict[str, Any] | None) -> list[bytes]:
        if value is None:
            return []
        parts = [self._pack_field(f, value.get(f.name)) for f in self.fields]
        if not any(parts):
            return []
        return [self.separator.join(parts).encode("utf-8")]

    def from_json(self, data: object) -> dict[str, Any] | None:
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError(_("Expected an object."))
        obj = cast("dict[str, object]", data)
        known = {f.name for f in self.fields}
        unknown = sorted(k for k in obj if k not in known)
        if unknown:
            raise ValidationError(_("Unknown field: {name}.").format(name=unknown[0]))
        result: dict[str, Any] = {}
        for field in self.fields:
            try:
                result[field.name] = field.from_json(obj.get(field.name))
            except ValidationError as exc:
                raise ValidationError(f"{field.label}: {exc.message}") from None
        return result if any(not is_empty(v) for v in result.values()) else None

    def to_json(self, value: dict[str, Any] | None) -> JSON:
        if value is None:
            return None
        return {f.name: f.to_json(value.get(f.name)) for f in self.fields}

    def _validate(self, value: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for field in self.fields:
            sub = value.get(field.name)
            errors.extend(f"{field.label}: {m}" for m in field.validate(sub))
            if self.separator in self._pack_field(field, sub):
                errors.append(
                    _("{label}: must not contain '{sep}'.").format(
                        label=field.label, sep=self.separator
                    )
                )
        return errors

    def describe_extra(self, key: str = "") -> dict[str, JSON]:
        return {"fields": [f.describe(field_key(key, f.name) if key else "") for f in self.fields]}
