"""SCIM ``User`` / ``Group`` resources over the Heracles ``user`` / ``group`` object types.

Owner: stream B. Contract (the router, stream C, codes against it):

* ``ScimService(user, domain, settings, base_url)``: one per request. ``user`` is the
  request's :class:`~heracles.api.deps.CurrentUser` (the token's owner), ``domain`` the
  :class:`~heracles.api.domain.Domain`. Every read and write goes through
  ``domain.service(user, type_name)`` (ACL, validation, hooks, audit, snapshots) and the
  account lock / archive paths the console uses; never around them. ``base_url`` is the
  absolute URL of ``/scim/v2`` (``meta.location`` = ``{base_url}/Users/{id}``).
* ``.users`` and ``.groups`` are :class:`ResourceOps`. Every method returns resources in
  SCIM JSON shape with ``schemas``, ``id``, ``meta`` (``resourceType``, ``created``,
  ``lastModified``, ``location``, ``version``); errors are :class:`ScimError` (404 unknown
  id or not readable, 409 ``uniqueness``, 400 ``invalidValue`` / ``mutability`` /
  ``invalidFilter``, 403 when the ACL refuses).
* Decisions: list results do not carry ``groups`` (computing them costs a search per page);
  single-resource reads and writes do. ``version`` ignores ``groups`` so it is the same in both.
  ``active`` is reported only to callers who may read the ``userLock`` attribute and set only
  by callers who may write it; a PUT without ``active`` leaves the lock as it is. A user is
  created before its lock is applied (a refused lock leaves the new, unlocked user).
  Group ``members`` need one directory read per member (id and type) on every group read.
* ``version`` is a weak ETag ``W/"<hash>"`` of the resource without its ``meta``; the router
  compares it with ``If-Match`` / ``If-None-Match``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager  # pyright: ignore[reportDeprecated]
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from heracles.api.accounts import USER_LOCK_ACL, set_account_lock
from heracles.api.errors import ApiError
from heracles.api.filter_rules import filter_checks
from heracles.auth.passwords import is_locked
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import AlreadyExistsError, Entry, NoSuchObjectError, Scope
from heracles.objects import (
    ObjectConflictError,
    ObjectNotFoundError,
    ObjectValidationError,
    PermissionDeniedError,
    TypeInfo,
    UnknownTypeError,
    filters,
)
from heracles.scim import mapping
from heracles.scim.errors import (
    INVALID_FILTER,
    INVALID_VALUE,
    UNIQUENESS,
    ScimError,
    bad_request,
    not_found,
)
from heracles.scim.filter import And, Compare, Filter, Not, Or, ValuePath, attributes_of, to_ldap
from heracles.scim.patch import PatchOp, apply_patch
from heracles.scim.schemas import ENTERPRISE_USER_SCHEMA, GROUP_SCHEMA, USER_SCHEMA
from heracles.scim.settings import ScimSettings

if TYPE_CHECKING:
    from heracles.api.deps import CurrentUser
    from heracles.api.domain import Domain

#: Ids resolved per directory search (one OR of equality filters).
ID_CHUNK = 50
#: Attributes of a user resource that live outside the plain string map.
_USER_READONLY = frozenset({"id", "meta", "groups", "name.formatted"})
_GROUP_READONLY = frozenset({"id", "meta"})
_UNSET: Any = object()


@dataclass(frozen=True, slots=True)
class Page:
    """One page of a list request (``start_index`` is 1-based, as in SCIM)."""

    resources: list[dict[str, Any]]
    total_results: int
    start_index: int


class ResourceOps(Protocol):
    def get(self, resource_id: str) -> dict[str, Any]: ...

    def search(
        self,
        flt: Filter | None,
        *,
        start_index: int = 1,
        count: int | None = None,
        sort_by: str | None = None,
        descending: bool = False,
    ) -> Page: ...

    def create(self, resource: dict[str, Any]) -> dict[str, Any]: ...

    def replace(self, resource_id: str, resource: dict[str, Any]) -> dict[str, Any]: ...

    def patch(self, resource_id: str, ops: list[PatchOp]) -> dict[str, Any]: ...

    def delete(self, resource_id: str) -> None: ...


@dataclass(slots=True)
class _Shared:
    """State shared by the resource types of one request."""

    user: CurrentUser
    domain: Domain
    settings: ScimSettings
    base_url: str
    #: id <-> DN lookups made by this request (lower-cased ids, normalised DNs).
    dn_by_id: dict[str, str] = field(default_factory=lambda: {})
    id_by_dn: dict[str, str] = field(default_factory=lambda: {})

    @property
    def directory(self) -> Any:
        return self.user.directory

    def remember(self, rid: str, dn: str) -> None:
        self.dn_by_id[rid.lower()] = dn
        self.id_by_dn[dnlib.normalize(dn)] = rid

    def reset(self) -> None:
        self.dn_by_id.clear()
        self.id_by_dn.clear()

    def readable_user(self, dn: str) -> bool:
        """Whether the caller may read the user entry ``dn`` (its main tab)."""
        info = self.domain.registry.get("user")
        rights = self.domain.evaluator(self.user).permissions(dn, info.acl_object(info.main_tab))
        return bool(rights.read)

    def id_of(self, dn: str) -> str | None:
        """Id of the user entry ``dn`` (``None`` when it is not a user the caller may read)."""
        key = dnlib.normalize(dn)
        if key in self.id_by_dn:
            return self.id_by_dn[key]
        if not self.readable_user(dn):
            return None
        entry = self.directory.get(dn, [self.settings.id_attribute, "objectClass"])
        if entry is None or not entry.has_object_class("inetOrgPerson"):
            return None
        rid = entry.text(self.settings.id_attribute)
        if rid:
            self.remember(rid, dn)
        return rid or None

    def dns_of(self, info: TypeInfo, ids: list[str]) -> dict[str, str]:
        """DNs of the entries of type ``info`` with these ids (lower-cased id -> DN).

        Only entries the caller may read are found: an id of an entry hidden by the ACL is
        as unknown as a wrong one.
        """
        out: dict[str, str] = {}
        todo: list[str] = []
        for rid in dict.fromkeys(i.lower() for i in ids):
            known = self.dn_by_id.get(rid)
            if known is not None:
                out[rid] = known
            else:
                todo.append(rid)
        attr = self.settings.id_attribute
        for start in range(0, len(todo), ID_CHUNK):
            chunk = todo[start : start + ID_CHUNK]
            flt = filters.and_(
                info.type.filter, filters.or_([filters.equals(attr, rid) for rid in chunk])
            )
            try:
                found = list(
                    self.directory.search(self.directory.base_dn, flt, Scope.SUBTREE, [attr])
                )
            except NoSuchObjectError:
                found = []
            for entry in found:
                rid = entry.text(attr)
                if info.name == "user" and not self.readable_user(entry.dn):
                    continue
                if rid:
                    out[rid.lower()] = entry.dn
                    if info.name == "user":
                        self.remember(rid, entry.dn)
        return out


@contextmanager  # pyright: ignore[reportDeprecated]
def scim_errors(names: Mapping[str, str] | None = None) -> Iterator[None]:
    """Translate object-layer and account errors into SCIM errors."""
    try:
        yield
    except ScimError:
        raise
    except (UnknownTypeError, ObjectNotFoundError, NoSuchObjectError) as exc:
        raise not_found(f"Resource not found: {exc}") from exc
    except PermissionDeniedError as exc:
        raise ScimError(403, str(exc)) from exc
    except ObjectConflictError as exc:
        raise ScimError(409, str(exc), UNIQUENESS) from exc
    except AlreadyExistsError as exc:
        raise ScimError(409, f"Resource already exists: {exc}", UNIQUENESS) from exc
    except ObjectValidationError as exc:
        taken = _("Already in use.")
        if any(message == taken for message in exc.fields.values()):
            raise ScimError(409, "The value is already in use", UNIQUENESS) from exc
        raise bad_request(_describe(exc.fields, names or {}), INVALID_VALUE) from exc
    except ApiError as exc:
        status = exc.status if exc.status in (403, 404, 409) else 400
        raise ScimError(status, exc.message, INVALID_VALUE if status == 400 else None) from exc


def _describe(fields: Mapping[str, str], names: Mapping[str, str]) -> str:
    parts: list[str] = []
    for key, message in fields.items():
        attr = key.partition(".")[2] or key
        parts.append(f"{names.get(attr, attr)}: {message}")
    return "; ".join(parts)


class _Ops:
    """What users and groups share: lookups, metadata, listing, deletion."""

    type_name = ""
    resource_type = ""
    path = ""

    def __init__(self, shared: _Shared) -> None:
        self.s = shared
        self.service, self.policy = shared.domain.service(shared.user, self.type_name)
        self.info = shared.domain.registry.get(self.type_name)
        self.names: dict[str, str] = {}

    # ---- hooks of the subclasses
    def resolve(self, path: str) -> str | None:
        raise NotImplementedError

    def rewrite(self, flt: Filter) -> Filter:
        """Turn tests the directory cannot answer into ones it can (default: none)."""
        return flt

    def render(self, dn: str, state_entry: Entry | None, *, full: bool) -> dict[str, Any]:
        raise NotImplementedError

    def base(self) -> str:
        raise NotImplementedError

    # ---- helpers
    @property
    def id_attr(self) -> str:
        return self.s.settings.id_attribute

    def ops_attrs(self) -> list[str]:
        return [self.id_attr, "createTimestamp", "modifyTimestamp"]

    def location(self, rid: str) -> str:
        return f"{self.s.base_url.rstrip('/')}/{self.path}/{rid}"

    def meta(self, entry: Entry, rid: str, resource: Mapping[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"resourceType": self.resource_type}
        created = mapping.rfc3339(entry.text("createTimestamp"))
        modified = mapping.rfc3339(entry.text("modifyTimestamp"))
        if created:
            out["created"] = created
        if modified or created:
            out["lastModified"] = modified or created
        out["location"] = self.location(rid)
        out["version"] = mapping.version_of(resource)
        return out

    def find_dn(self, rid: str) -> str | None:
        known = self.s.dn_by_id.get(rid.lower()) if self.type_name == "user" else None
        if known is not None:
            return known
        flt = filters.and_(self.info.type.filter, filters.equals(self.id_attr, rid))
        try:
            found = list(
                self.s.directory.search(
                    self.s.directory.base_dn, flt, Scope.SUBTREE, [self.id_attr], size_limit=2
                )
            )
        except NoSuchObjectError:
            return None
        return found[0].dn if len(found) == 1 else None

    def locate(self, rid: str) -> str:
        """DN of the readable resource ``rid`` (404 when unknown or not readable)."""
        dn = self.find_dn(rid)
        if dn is None or not self.policy.can_read(
            dn, self.info.main_tab.name, self.info.type.main_attr
        ):
            raise not_found(f"Resource {rid} not found")
        return dn

    def ops_entry(self, dn: str, extra: list[str] | None = None) -> Entry:
        entry = self.s.directory.get(dn, [*self.ops_attrs(), *(extra or [])])
        if entry is None or not entry.text(self.id_attr):
            raise ScimError(500, f"The entry has no {self.id_attr}")
        return entry

    def values(self, dn: str) -> dict[str, Any]:
        """Readable values of the main tab, in JSON form."""
        state = self.service.load(self.type_name, dn)
        tabs = mapping.obj(self.service.state_json(state).get("tabs")) or {}
        main = mapping.obj(tabs.get("main")) or {}
        return mapping.obj(main.get("values")) or {}

    def get(self, resource_id: str) -> dict[str, Any]:
        self.s.reset()
        with scim_errors(self.names):
            return self.render(self.locate(resource_id), None, full=True)

    def exists(self, attr: str, value: str) -> bool:
        """Whether a readable resource of this type already has ``attr`` = ``value``."""
        page = self.service.list(
            self.type_name,
            self.s.directory.base_dn,
            Scope.SUBTREE,
            limit=1,
            extra_filter=filters.equals(attr, value),
            filter_checks=[("main", attr)],
        )
        return bool(page.total)

    def search(
        self,
        flt: Filter | None,
        *,
        start_index: int = 1,
        count: int | None = None,
        sort_by: str | None = None,
        descending: bool = False,
    ) -> Page:
        self.s.reset()
        start = max(1, start_index)
        cap = self.s.settings.max_results
        wanted = cap if count is None else min(max(0, count), cap)
        extra = ""
        checks: list[tuple[str, str]] = []
        if flt is not None:
            flt = self.rewrite(flt)
            extra = to_ldap(flt, self.resolve)
            attrs = {
                a for a in attributes_of(flt, self.resolve) if a.lower() != self.id_attr.lower()
            }
            try:
                checks = filter_checks(self.info, attrs)
            except ValueError as exc:
                raise bad_request(f"Cannot filter on {exc}", INVALID_FILTER) from exc
        sort = self.sort_key(sort_by)
        captured: dict[str, Entry] = {}

        def capture(entry: Entry) -> bool:
            captured[entry.dn] = entry
            return False

        with scim_errors(self.names):
            page = self.service.list(
                self.type_name,
                self.s.directory.base_dn,
                Scope.SUBTREE,
                limit=max(1, start - 1 + wanted),
                sort=sort,
                descending=descending,
                extra_attrs=[*self.ops_attrs(), *self.extra_list_attrs()],
                locked=capture,
                extra_filter=extra,
                filter_checks=checks,
            )
            resources: list[dict[str, Any]] = []
            if wanted:
                for row in page.items[start - 1 :]:
                    try:
                        resources.append(self.render(row.dn, captured.get(row.dn), full=False))
                    except ObjectNotFoundError:
                        continue  # deleted since the listing
        return Page(resources, page.total or 0, start)

    def extra_list_attrs(self) -> list[str]:
        return []

    def sort_key(self, sort_by: str | None) -> str | None:
        if not sort_by:
            return None
        attr = self.resolve(sort_by.lower())
        columns = {c.lower() for c in (*self.info.type.columns, self.info.type.name_attr) if c}
        columns.add(self.info.type.main_attr.lower())
        if attr is None or attr.lower() not in columns:
            raise bad_request(f"Cannot sort by {sort_by}", INVALID_VALUE)
        return attr

    def archive(self, dn: str) -> None:
        """Archive the object like the console does, when the archive plugin is enabled."""
        from heracles_plugins.archive.service import ArchiveError, ArchiveSettings, archive

        registry = self.s.domain.registry
        settings = registry.settings.get("archive")
        if not isinstance(settings, ArchiveSettings):
            return
        try:
            registry.get("archived_object")
        except UnknownTypeError:
            return  # plugin switched off
        if self.type_name not in settings.rules or settings.archive_on_delete:
            return  # nothing to keep, or the object events archive on deletion
        if not self.policy.can_delete(dn, self.type_name):
            raise PermissionDeniedError(f"cannot archive {dn}")

        def can_read(attr: str) -> bool:
            tab = next(
                (t for t in self.info.tabs if t.attribute(attr) is not None), self.info.main_tab
            )
            return self.policy.can_read(dn, tab.name, attr)

        try:
            archive(
                self.s.directory,
                dn,
                self.type_name,
                settings=settings,
                now=datetime.now(UTC),
                can_read=can_read,
            )
        except ArchiveError as exc:
            raise bad_request(str(exc), INVALID_VALUE) from exc

    def delete(self, resource_id: str) -> None:
        self.s.reset()
        with scim_errors(self.names):
            dn = self.locate(resource_id)
            self.service.load(self.type_name, dn)
            self.archive(dn)
            self.service.delete(self.type_name, dn)


@dataclass(slots=True)
class _Desired:
    """The mapped state a user resource asks for (``None`` clears an attribute)."""

    attrs: dict[str, str | None] = field(default_factory=lambda: {})
    password: str | None = None
    active: bool | None = None


def _text_of(value: Any, what: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise bad_request(f"{what} must be a string", INVALID_VALUE)
    return value or None


class _Users(_Ops):
    type_name = "user"
    resource_type = "User"
    path = "Users"

    def __init__(self, shared: _Shared) -> None:
        super().__init__(shared)
        self.map = shared.settings.user_attribute_map()
        for key, attr in self.map.items():
            self.names.setdefault(attr, mapping.canonical_path(key))
        self.names.update(
            {"mail": "emails", "telephoneNumber": "phoneNumbers", "mobile": "phoneNumbers"}
        )
        self.names.update({"manager": "manager", "userPassword": "password", "uid": "userName"})

    def resolve(self, path: str) -> str | None:
        if path == "id":
            return self.id_attr
        if path in ("emails", "emails.value"):
            return "mail"
        return self.map.get(path)

    def rewrite(self, flt: Filter) -> Filter:
        """The one email (``mail``) has type ``work``: ``type eq "work"`` means "has an email",
        any other type matches nothing. Clients commonly send ``emails[type eq "work"]...``."""
        return _email_types(flt, inside=False)

    def base(self) -> str:
        return self.s.settings.user_base or self.s.directory.base_dn

    def extra_list_attrs(self) -> list[str]:
        return ["userPassword"]

    # ------------------------------------------------------------ output
    def render(self, dn: str, state_entry: Entry | None, *, full: bool) -> dict[str, Any]:
        values = self.values(dn)
        entry = state_entry or self.s.directory.get(dn, [*self.ops_attrs(), "userPassword"])
        if entry is None or not entry.text(self.id_attr):
            raise ObjectNotFoundError(dn)
        rid = entry.text(self.id_attr) or ""
        self.s.remember(rid, dn)
        res: dict[str, Any] = {"schemas": [USER_SCHEMA], "id": rid}
        for key, attr in self.map.items():
            value = values.get(attr)
            if isinstance(value, str) and value:
                mapping.place(res, key, value)
        mail = values.get("mail")
        if isinstance(mail, str) and mail:
            res["emails"] = [{"value": mail, "type": "work", "primary": True}]
        phones: list[dict[str, Any]] = []
        for attr, kind in (("telephoneNumber", "work"), ("mobile", "mobile")):
            number = values.get(attr)
            if isinstance(number, str) and number:
                phones.append({"value": number, "type": kind})
        if phones:
            res["phoneNumbers"] = phones
        if self.can_read_lock(dn):
            res["active"] = not is_locked(entry.text("userPassword") or "")
        manager = values.get("manager")
        if isinstance(manager, str) and manager:
            mid = self.s.id_of(manager)
            if mid:
                res.setdefault(ENTERPRISE_USER_SCHEMA, {})["manager"] = {
                    "value": mid,
                    "$ref": self.location(mid),
                }
        if ENTERPRISE_USER_SCHEMA in res:
            res["schemas"].append(ENTERPRISE_USER_SCHEMA)
        if full:
            groups = self.groups_of(dn)
            if groups:
                res["groups"] = groups
        res["meta"] = self.meta(entry, rid, res)
        return res

    def can_read_lock(self, dn: str) -> bool:
        evaluator = self.s.domain.evaluator(self.s.user)
        return bool(
            evaluator.can_read_attr(dn, self.info.acl_object(self.info.main_tab), USER_LOCK_ACL)
        )

    def can_write_lock(self, dn: str) -> bool:
        evaluator = self.s.domain.evaluator(self.s.user)
        return bool(
            evaluator.can_write_attr(dn, self.info.acl_object(self.info.main_tab), USER_LOCK_ACL)
        )

    def groups_of(self, dn: str) -> list[dict[str, Any]]:
        """Groups (readable by the caller) with ``dn`` among their members: one search."""
        service, _policy = self.s.domain.service(self.s.user, "group")
        captured: dict[str, Entry] = {}

        def capture(entry: Entry) -> bool:
            captured[entry.dn] = entry
            return False

        page = service.list(
            "group",
            self.s.directory.base_dn,
            Scope.SUBTREE,
            limit=1000,
            extra_attrs=[self.id_attr],
            locked=capture,
            extra_filter=filters.equals("member", dn),
            filter_checks=[("main", "member")],
        )
        out: list[dict[str, Any]] = []
        for row in page.items:
            entry = captured.get(row.dn)
            gid = entry.text(self.id_attr) if entry is not None else None
            if not gid:
                continue
            item: dict[str, Any] = {
                "value": gid,
                "$ref": f"{self.s.base_url.rstrip('/')}/Groups/{gid}",
                "type": "direct",
            }
            if row.values.get("cn"):
                item["display"] = row.values["cn"]
            out.append(item)
        return out

    # ------------------------------------------------------------- input
    def desired(self, resource: Mapping[str, Any]) -> _Desired:
        flat = mapping.flatten(resource)
        out = _Desired()
        for key, attr in self.map.items():
            if attr == "cn" or key.endswith("formatted"):
                continue  # computed from the name parts
            out.attrs[attr] = _text_of(flat.get(key), mapping.canonical_path(key))
        out.attrs["mail"] = self._email(flat.get("emails"))
        telephone, mobile = self._phones(flat.get("phonenumbers"))
        out.attrs["telephoneNumber"] = telephone
        out.attrs["mobile"] = mobile
        manager = flat.get(mapping.ENTERPRISE_PREFIX + "manager")
        if manager is None:
            out.attrs["manager"] = None
        else:
            sub = mapping.obj(manager)
            value = sub.get("value") if sub is not None else None
            if not isinstance(value, str) or not value:
                raise bad_request("manager.value must be a user id", INVALID_VALUE)
            out.attrs["manager"] = value
        active = flat.get("active")
        if active is not None:
            if not isinstance(active, bool):
                raise bad_request("active must be a boolean", INVALID_VALUE)
            out.active = active
        out.password = _text_of(flat.get("password"), "password")
        return out

    @staticmethod
    def _items(value: Any, what: str) -> list[dict[str, Any]]:
        if value is None:
            return []
        items = mapping.arr(value)
        if items is None:
            raise bad_request(f"{what} must be a list", INVALID_VALUE)
        out: list[dict[str, Any]] = []
        for item in items:
            sub = mapping.obj(item)
            if sub is None or not isinstance(sub.get("value"), str):
                raise bad_request(f"{what} items need a string value", INVALID_VALUE)
            out.append(sub)
        return out

    def _email(self, value: Any) -> str | None:
        chosen = mapping.primary(self._items(value, "emails"), "work")
        return str(chosen["value"]) or None if chosen else None

    def _phones(self, value: Any) -> tuple[str | None, str | None]:
        items = self._items(value, "phoneNumbers")
        mobiles = [i for i in items if str(i.get("type", "")).lower() == "mobile"]
        others = [i for i in items if i not in mobiles]
        phone = mapping.primary(others, "work")
        mobile = mapping.primary(mobiles)
        return (
            str(phone["value"]) or None if phone else None,
            str(mobile["value"]) or None if mobile else None,
        )

    def tab_values(self, attrs: Mapping[str, str | None], password: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for attr, value in attrs.items():
            if attr == "manager" and value is not None:
                found = self.s.dns_of(self.info, [value])
                if value.lower() not in found:
                    raise bad_request(f"Unknown manager {value}", INVALID_VALUE)
                out[attr] = found[value.lower()]
            else:
                out[attr] = value
        if password is not None:
            out["userPassword"] = password
        return out

    # ------------------------------------------------------------- writes
    def create(self, resource: dict[str, Any]) -> dict[str, Any]:
        self.s.reset()
        want = self.desired(resource)
        login_attr = self.map.get("username", self.info.type.main_attr)
        login = want.attrs.get(login_attr)
        if not login:
            raise bad_request("userName is required", INVALID_VALUE)
        with scim_errors(self.names):
            if self.exists(login_attr, login):
                raise ScimError(409, f"userName {login} is already in use", UNIQUENESS)
            values = {
                k: v for k, v in self.tab_values(want.attrs, want.password).items() if v is not None
            }
            dn = self.service.create(self.type_name, self.base(), {"main": {"values": values}})
            if want.active is False:
                set_account_lock(self.s.user, self.s.domain, dn, True)
            return self.render(dn, None, full=True)

    def replace(self, resource_id: str, resource: dict[str, Any]) -> dict[str, Any]:
        self.s.reset()
        with scim_errors(self.names):
            dn = self.locate(resource_id)
            want = self.desired(resource)
            return self.write(resource_id, dn, want.attrs, want.password, want.active, None)

    def patch(self, resource_id: str, ops: list[PatchOp]) -> dict[str, Any]:
        current = self.get(resource_id)
        patched = apply_patch(
            current,
            ops,
            multi_valued=lambda p: p.split(".")[0].split("[")[0] in mapping.USER_MULTI,
            readonly=lambda p: p in _USER_READONLY or p.split(".")[0] in ("id", "meta", "groups"),
        )
        self.s.reset()
        with scim_errors(self.names):
            dn = self.locate(resource_id)
            before, after = self.desired(current), self.desired(patched)
            changed = {k: v for k, v in after.attrs.items() if before.attrs.get(k) != v}
            active = after.active if after.active != before.active else None
            return self.write(resource_id, dn, changed, after.password, active, changed)

    def write(
        self,
        rid: str,
        dn: str,
        attrs: Mapping[str, str | None],
        password: str | None,
        active: bool | None,
        only: Mapping[str, str | None] | None,
    ) -> dict[str, Any]:
        if password is not None and dnlib.normalize(dn) == dnlib.normalize(self.s.user.dn):
            # same rule as the console and API v1/v2: a token never changes its owner's password
            raise ScimError(403, "Changing your own password needs an interactive sign-in")
        if "manager" in attrs and attrs["manager"] is None:
            current = self.service.load(self.type_name, dn).tabs["main"].values.get("manager")
            if isinstance(current, str) and current and self.s.id_of(current) is None:
                # a manager the caller cannot see is not cleared by omission
                attrs = {k: v for k, v in attrs.items() if k != "manager"}
        current_active: bool | None = None
        if active is not None:
            if not self.can_write_lock(dn):
                raise PermissionDeniedError("cannot lock or unlock this account")
            entry = self.s.directory.get(dn, ["userPassword"])
            if entry is not None and self.can_read_lock(dn):
                current_active = not is_locked(entry.text("userPassword") or "")
        values = self.tab_values(attrs, password)
        if values:
            dn = self.service.update(self.type_name, dn, {"main": {"values": values}}).dn
            self.s.remember(rid, dn)
        if active is not None and active != current_active:
            set_account_lock(self.s.user, self.s.domain, dn, not active)
        return self.render(dn, None, full=True)


def _email_type(cmp: Compare, value_path: str) -> Filter:
    present = Compare(value_path, "pr")
    if cmp.op == "pr":
        return present
    if cmp.op == "eq" and isinstance(cmp.value, str):
        return present if cmp.value.lower() == "work" else Not(present)
    raise bad_request("emails.type supports eq and pr only", INVALID_FILTER)


def _email_types(flt: Filter, *, inside: bool) -> Filter:
    if isinstance(flt, And):
        return And(_email_types(flt.left, inside=inside), _email_types(flt.right, inside=inside))
    if isinstance(flt, Or):
        return Or(_email_types(flt.left, inside=inside), _email_types(flt.right, inside=inside))
    if isinstance(flt, Not):
        return Not(_email_types(flt.inner, inside=inside))
    if isinstance(flt, ValuePath):
        if flt.path.lower() == "emails":
            return ValuePath(flt.path, _email_types(flt.filter, inside=True))
        return flt
    if inside and flt.path.lower() == "type":
        return _email_type(flt, "value")
    if not inside and flt.path.lower() == "emails.type":
        return _email_type(flt, "emails")
    return flt


class _Groups(_Ops):
    type_name = "group"
    resource_type = "Group"
    path = "Groups"

    def __init__(self, shared: _Shared) -> None:
        super().__init__(shared)
        self.names = {"cn": "displayName", "member": "members"}
        self.users = shared.domain.registry.get("user")

    def resolve(self, path: str) -> str | None:
        if path == "id":
            return self.id_attr
        if path == "displayname":
            return "cn"
        return None

    def base(self) -> str:
        return self.s.settings.group_base or self.s.directory.base_dn

    def render(self, dn: str, state_entry: Entry | None, *, full: bool) -> dict[str, Any]:
        values = self.values(dn)
        entry = state_entry or self.s.directory.get(dn, self.ops_attrs())
        if entry is None or not entry.text(self.id_attr):
            raise ObjectNotFoundError(dn)
        rid = entry.text(self.id_attr) or ""
        res: dict[str, Any] = {"schemas": [GROUP_SCHEMA], "id": rid}
        name = values.get("cn")
        if isinstance(name, str) and name:
            res["displayName"] = name
        dns = mapping.arr(values.get("member"))
        if dns is not None:
            members: list[dict[str, Any]] = []
            for member_dn in dns:
                if not isinstance(member_dn, str):
                    continue
                mid = self.s.id_of(member_dn)
                if mid is None:
                    continue  # not a user (or gone): not a SCIM member
                members.append(
                    {
                        "value": mid,
                        "$ref": f"{self.s.base_url.rstrip('/')}/Users/{mid}",
                        "display": dnlib.rdn(member_dn).partition("=")[2],
                        "type": "User",
                    }
                )
            res["members"] = members
        res["meta"] = self.meta(entry, rid, res)
        return res

    def desired(self, resource: Mapping[str, Any]) -> tuple[str | None, list[str] | None]:
        """``(displayName, member ids)``; ``None`` for the ids when ``members`` is absent."""
        flat = mapping.flatten(resource)
        name = _text_of(flat.get("displayname"), "displayName")
        raw = flat.get("members")
        if raw is None:
            return name, None
        items = mapping.arr(raw)
        if items is None:
            raise bad_request("members must be a list", INVALID_VALUE)
        ids: list[str] = []
        for item in items:
            sub = mapping.obj(item)
            value = sub.get("value") if sub is not None else None
            if not isinstance(value, str) or not value:
                raise bad_request("members items need a string value", INVALID_VALUE)
            ids.append(value)
        return name, list(dict.fromkeys(ids))

    def member_dns(self, ids: list[str], dn: str | None = None) -> list[str]:
        """Member DNs for these ids, plus (for an existing group ``dn``) the members SCIM does
        not show: entries that are not users, or users the caller may not read. A client
        cannot remove what it cannot see."""
        found = self.s.dns_of(self.users, ids)
        missing = [i for i in ids if i.lower() not in found]
        if missing:
            shown = ", ".join(missing[:5])
            raise bad_request(f"Unknown or non-user members: {shown}", INVALID_VALUE)
        out = [found[i.lower()] for i in ids]
        if dn is not None:
            current = mapping.arr(
                self.service.load(self.type_name, dn).tabs["main"].values.get("member")
            )
            kept = {dnlib.normalize(d) for d in out}
            for member in current or []:
                if (
                    isinstance(member, str)
                    and dnlib.normalize(member) not in kept
                    and self.s.id_of(member) is None
                ):
                    out.append(member)
                    kept.add(dnlib.normalize(member))
        return out

    def create(self, resource: dict[str, Any]) -> dict[str, Any]:
        self.s.reset()
        name, ids = self.desired(resource)
        if not name:
            raise bad_request("displayName is required", INVALID_VALUE)
        if not ids:
            raise bad_request("A group needs at least one member", INVALID_VALUE)
        with scim_errors(self.names):
            if self.exists("cn", name):
                raise ScimError(409, f"displayName {name} is already in use", UNIQUENESS)
            values = {"cn": name, "member": self.member_dns(ids)}
            dn = self.service.create(self.type_name, self.base(), {"main": {"values": values}})
            return self.render(dn, None, full=True)

    def replace(self, resource_id: str, resource: dict[str, Any]) -> dict[str, Any]:
        self.s.reset()
        with scim_errors(self.names):
            dn = self.locate(resource_id)
            name, ids = self.desired(resource)
            if not ids:
                raise bad_request("A group needs at least one member", INVALID_VALUE)
            if not name:
                raise bad_request("displayName is required", INVALID_VALUE)
            return self.write(dn, {"cn": name, "member": self.member_dns(ids, dn)})

    def patch(self, resource_id: str, ops: list[PatchOp]) -> dict[str, Any]:
        current = self.get(resource_id)
        patched = apply_patch(
            current,
            ops,
            multi_valued=lambda p: p.split(".")[0].split("[")[0] in mapping.GROUP_MULTI,
            readonly=lambda p: p.split(".")[0] in _GROUP_READONLY,
        )
        with scim_errors(self.names):
            dn = self.locate(resource_id)
            old_name, old_ids = self.desired(current)
            name, ids = self.desired(patched)
            changes: dict[str, Any] = {}
            if name != old_name:
                if not name:
                    raise bad_request("displayName is required", INVALID_VALUE)
                changes["cn"] = name
            ids = ids or []  # removing every member drops the attribute from the resource
            if {i.lower() for i in ids} != {i.lower() for i in old_ids or []}:
                if not ids:
                    raise bad_request("A group needs at least one member", INVALID_VALUE)
                changes["member"] = self.member_dns(ids, dn)
            return self.write(dn, changes)

    def write(self, dn: str, values: dict[str, Any]) -> dict[str, Any]:
        if values:
            dn = self.service.update(self.type_name, dn, {"main": {"values": values}}).dn
        return self.render(dn, None, full=True)


class ScimService:
    def __init__(
        self, user: CurrentUser, domain: Domain, settings: ScimSettings, base_url: str
    ) -> None:
        shared = _Shared(user, domain, settings, base_url)
        self._users = _Users(shared)
        self._groups = _Groups(shared)

    @property
    def users(self) -> ResourceOps:
        return self._users

    @property
    def groups(self) -> ResourceOps:
        return self._groups


__all__ = ["Page", "ResourceOps", "ScimService"]
