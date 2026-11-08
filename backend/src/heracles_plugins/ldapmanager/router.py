"""``/api/v2`` routes of the import / export tools and the raw LDIF of one object."""

from __future__ import annotations

import importlib
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from heracles.api.deps import CurrentUserDep
from heracles.api.domain import DomainDep
from heracles.api.errors import ApiError, forbidden, not_found, validation
from heracles.api.v2.objects import object_errors
from heracles.attributes import JSON
from heracles.ldap.client import DirectoryError, NoSuchObjectError, Scope
from heracles.ldap.filter import FilterError, matches, parse_filter
from heracles.ldap.ldif import FOLD_WIDTH, LdifError, dump_entry, iter_ldif, parse_ldif
from heracles.objects import (
    ObjectConflictError,
    ObjectValidationError,
    PermissionDeniedError,
)
from heracles.objects.registry import PluginRouterContext
from heracles_plugins.ldapmanager import csv_import as csvlib
from heracles_plugins.ldapmanager import ldif_import as importer
from heracles_plugins.ldapmanager.access import Access

_SCOPES = {"base": Scope.BASE, "one": Scope.ONE, "sub": Scope.SUBTREE, "subtree": Scope.SUBTREE}
PREVIEW_ROWS = 10


class LdifImportBody(BaseModel):
    """Body of ``POST /ldif/import``."""

    text: Annotated[str, Field(description="The LDIF document")]
    overwrite: bool = False
    remove_missing: bool = False
    dry_run: bool = False


class CsvParseBody(BaseModel):
    text: str
    separator: str = ","
    has_header: bool = True


class CsvColumn(BaseModel):
    column: Annotated[int, Field(ge=0)]
    field: str


class CsvImportBody(CsvParseBody):
    mapping: list[CsvColumn]
    #: ``"<tab>.<attribute>" -> value`` applied to every line before the mapped cells.
    fixed: dict[str, str] = Field(default_factory=lambda: {})
    template: str | None = None
    base: str | None = None


def _templates() -> Any:
    try:
        return importlib.import_module("heracles.objects.templates")
    except ImportError:
        raise ApiError(501, "not_implemented", "Object templates are not available") from None


def build_router(ctx: PluginRouterContext) -> APIRouter:
    """Router factory (``Plugin.api_routers``)."""
    del ctx
    router = APIRouter(tags=["ldapmanager"])

    @router.get("/ldapmanager/access")
    def access(user: CurrentUserDep, domain: DomainDep) -> dict[str, bool]:
        """What the connected user may do (the page hides the tabs it cannot use)."""
        gate = Access(domain, user)
        base = user.directory.base_dn
        return {
            "ldif_export": gate.can_export_ldif(base),
            "ldif_import": gate.can_import_ldif(base),
            "csv_import": gate.can_import_csv(base),
        }

    # -- LDIF export --------------------------------------------------------------------------
    @router.get("/ldif/export")
    def export_ldif(
        user: CurrentUserDep,
        domain: DomainDep,
        base: Annotated[str | None, Query(description="Entry or subtree to export")] = None,
        filter: Annotated[str, Query(description="LDAP filter")] = "(objectClass=*)",
        scope: Annotated[Literal["base", "one", "sub", "subtree"], Query()] = "sub",
        wrap: Annotated[int, Query(ge=0, le=1000, description="Wrap after N columns")] = FOLD_WIDTH,
        filename: Annotated[str, Query(max_length=100)] = "export.ldif",
    ) -> StreamingResponse:
        gate = Access(domain, user)
        directory = user.directory
        start = base or directory.base_dn
        gate.require_export(start)
        try:
            parse_filter(filter)
        except FilterError as exc:
            raise validation(f"Invalid filter: {exc}", {"filter": str(exc)}) from None
        if directory.get(start) is None:
            raise not_found(f"Entry not found: {start}")

        def entries() -> Any:
            try:
                for entry in directory.search(start, filter, _SCOPES[scope]):
                    shown = gate.visible(entry)
                    if shown is not None:
                        yield shown
            except NoSuchObjectError:
                return

        safe = "".join(c for c in filename if c.isalnum() or c in "._-") or "export.ldif"
        return StreamingResponse(
            iter_ldif(entries(), wrap=wrap),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{safe}"'},
        )

    # -- LDIF import --------------------------------------------------------------------------
    @router.post("/ldif/import")
    def import_ldif(
        body: LdifImportBody, user: CurrentUserDep, domain: DomainDep
    ) -> dict[str, JSON]:
        """Import raw LDIF records (no object-level validation): needs ``ldif`` write rights."""
        gate = Access(domain, user)
        if len(body.text.encode("utf-8")) > importer.MAX_BYTES:
            raise validation("The LDIF document is too large", {"text": "too large"})
        try:
            entries = parse_ldif(body.text)
        except (LdifError, UnicodeDecodeError) as exc:
            raise validation(f"Invalid LDIF: {exc}", {"text": str(exc)}) from None
        if not entries:
            raise validation("The LDIF document contains no entry", {"text": "empty"})
        if len(entries) > importer.MAX_ENTRIES:
            raise validation(
                f"At most {importer.MAX_ENTRIES} entries can be imported at once",
                {"text": "too many entries"},
            )
        if not any(gate.can_import_ldif(e.dn) for e in entries):
            raise forbidden("You are not allowed to import LDIF")
        options = importer.ImportOptions(body.overwrite, body.remove_missing)
        # Who may edit the configuration (hence the triggers) may also import it.
        admin = domain.is_admin(user.dn) or (
            gate.evaluator.permissions(user.directory.base_dn, "config/config").write
        )
        results = importer.run_import(
            user.directory,
            entries,
            options,
            allowed=gate.can_import_ldif,
            apply=not body.dry_run,
            protected=None if admin else importer.configuration_entry(user.directory),
        )
        return {
            "dry_run": body.dry_run,
            "summary": cast("dict[str, JSON]", importer.summarize(results)),
            "results": [
                {
                    "index": r.index,
                    "dn": r.dn,
                    "action": r.action,
                    "changes": list(r.changes),
                    "error": r.error,
                }
                for r in results
            ],
        }

    # -- raw LDIF of one object (used by the editor's "View LDIF" dialog) -----------------------
    @router.get("/objects/{type_name}/{dn:path}/ldif", response_class=PlainTextResponse)
    def object_ldif(
        type_name: str,
        dn: str,
        user: CurrentUserDep,
        domain: DomainDep,
        wrap: Annotated[int, Query(ge=0, le=1000)] = FOLD_WIDTH,
    ) -> PlainTextResponse:
        gate = Access(domain, user)
        with object_errors():
            info = domain.registry.get(type_name)
        entry = user.directory.get(dn)
        if entry is None or not matches(entry, parse_filter(info.type.filter)):
            raise not_found(f"Object not found: {dn}")
        shown = gate.visible(entry, types=[info])
        if shown is None:
            raise forbidden(f"You cannot read {dn}")
        return PlainTextResponse(
            dump_entry(shown, wrap=wrap), media_type="text/plain; charset=utf-8"
        )

    # -- CSV import ---------------------------------------------------------------------------
    @router.post("/csv/parse")
    def csv_parse(body: CsvParseBody, user: CurrentUserDep, domain: DomainDep) -> dict[str, JSON]:
        """Parse a CSV document: the columns and the first rows (for the preview)."""
        del user, domain
        try:
            parsed = csvlib.parse_csv(body.text, body.separator, has_header=body.has_header)
        except csvlib.CsvError as exc:
            raise validation(str(exc), {"text": str(exc)}) from None
        return {
            "columns": list(parsed.columns),
            "rows": [list(r) for r in parsed.rows[:PREVIEW_ROWS]],
            "total": len(parsed.rows),
        }

    @router.get("/csv/{type_name}/fields")
    def csv_fields(
        type_name: str,
        user: CurrentUserDep,
        domain: DomainDep,
        template: Annotated[str | None, Query()] = None,
    ) -> list[JSON]:
        """The attributes a column can be mapped to (limited to a template's fields)."""
        with object_errors():
            info = domain.registry.get(type_name)
            fields = csvlib.importable_fields(info)
            if template:
                service, _policy = domain.service(user, info.name)
                wanted = _templates().template_fields(service, info.name, template)
                fields = csvlib.template_fields_only(fields, cast("dict[str, list[str]]", wanted))
        tabs = {t.name: t.display_label() for t in info.tabs}
        return [
            {
                "key": f.key,
                "tab": f.tab,
                "tab_label": tabs[f.tab],
                "attribute": f.attribute.name,
                "label": f.attribute.label,
                "kind": f.attribute.kind,
                "required": f.attribute.required,
                "multivalued": f.attribute.multivalued,
            }
            for f in fields
        ]

    @router.post("/csv/{type_name}/import")
    def csv_import(
        type_name: str, body: CsvImportBody, user: CurrentUserDep, domain: DomainDep
    ) -> dict[str, JSON]:
        """Create one object per CSV line through the normal creation path."""
        gate = Access(domain, user)
        directory = user.directory
        default_base = body.base or directory.base_dn
        if not gate.can_import_csv(default_base):
            raise forbidden("You are not allowed to import CSV files")
        with object_errors():
            info = domain.registry.get(type_name)
        try:
            parsed = csvlib.parse_csv(body.text, body.separator, has_header=body.has_header)
        except csvlib.CsvError as exc:
            raise validation(str(exc), {"text": str(exc)}) from None
        available = csvlib.importable_fields(info)
        service, _policy = domain.service(user, info.name)
        if body.template:
            module = _templates()
            with object_errors():
                wanted = module.template_fields(service, info.name, body.template)
            available = csvlib.template_fields_only(available, cast("dict[str, list[str]]", wanted))
        by_key = {f.key: f for f in available}
        errors: dict[str, str] = {}
        mapping: list[tuple[int, csvlib.Field]] = []
        for item in body.mapping:
            target = by_key.get(item.field)
            if target is None:
                errors[f"mapping.{item.field}"] = "Unknown field"
            elif item.column >= len(parsed.columns):
                errors[f"mapping.{item.field}"] = "Unknown column"
            else:
                mapping.append((item.column, target))
        fixed: dict[str, csvlib.Field] = {}
        for key in body.fixed:
            found = by_key.get(key)
            if found is None:
                errors[f"fixed.{key}"] = "Unknown field"
            else:
                fixed[key] = found
        if errors:
            raise validation("Invalid mapping", errors)

        results: list[JSON] = []
        imported = 0
        for row, line in zip(parsed.rows, parsed.lines, strict=True):
            outcome: dict[str, JSON] = {"line": line, "dn": None, "error": None}
            try:
                values = csvlib.row_values(info, row, mapping, fixed, body.fixed)
                if body.template:
                    with object_errors():
                        resolved = _templates().apply_template(
                            service, info.name, body.template, values
                        )
                    payload = csvlib.payload_of(info, cast("dict[str, dict[str, Any]]", resolved))
                else:
                    payload = csvlib.payload_of(info, values)
                base = default_base
                for tab_values in payload.values():
                    department = tab_values["values"].get("base")
                    if isinstance(department, str) and department:
                        base = department
                outcome["dn"] = service.create(info.name, base, payload)
                imported += 1
            except csvlib.CsvError as exc:
                outcome["error"] = str(exc)
            except ObjectValidationError as exc:
                outcome["error"] = "; ".join(f"{k}: {v}" for k, v in exc.fields.items())
            except (PermissionDeniedError, ObjectConflictError) as exc:
                outcome["error"] = str(exc)
            except ApiError as exc:
                outcome["error"] = exc.message
            except DirectoryError as exc:
                outcome["error"] = type(exc).__name__
            results.append(outcome)
        return {"imported": imported, "failed": len(results) - imported, "results": results}

    return router
