"""python-ldap implementation of :class:`DirectoryClient`.

python-ldap is an optional dependency (extra ``ldap``) that needs the libldap
and libsasl development headers to build. It is imported lazily so that the
rest of Heracles (and the test-suite using the in-memory fake) works without
it.
"""

from __future__ import annotations

import contextlib
import importlib
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from types import ModuleType
from typing import Any, TypeVar

from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    Attributes,
    DirectoryError,
    Entry,
    InvalidCredentialsError,
    Modification,
    NoSuchObjectError,
    Scope,
    SizeLimitExceededError,
)
from heracles.ldap.config import DirectoryConfig

T = TypeVar("T")


class LdapUnavailableError(DirectoryError):
    """python-ldap is not installed."""


def _import_ldap() -> ModuleType:
    try:
        module = importlib.import_module("ldap")
        importlib.import_module("ldap.controls")
        importlib.import_module("ldap.schema")
    except ImportError as exc:
        raise LdapUnavailableError(
            "python-ldap is not installed; install Heracles with the 'ldap' extra "
            "(requires the libldap2-dev and libsasl2-dev system packages)"
        ) from exc
    return module


class PyLdapDirectory:
    """Directory client backed by python-ldap with a reusable connection."""

    def __init__(self, config: DirectoryConfig) -> None:
        self._ldap: Any = _import_ldap()
        self._config = config
        self._conn: Any = None
        self._lock = threading.RLock()
        self._object_classes: set[str] | None = None

    # -- connection management ---------------------------------------------------

    @property
    def base_dn(self) -> str:
        return self._config.base_dn

    def close(self) -> None:
        """Unbind and drop the cached connection."""
        with self._lock:
            self._drop()

    def _drop(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            self._unbind(conn)

    def _unbind(self, conn: Any) -> None:
        with contextlib.suppress(self._ldap.LDAPError):
            conn.unbind_s()

    def _new_connection(self) -> Any:
        ldap = self._ldap
        cfg = self._config
        conn = ldap.initialize(cfg.uri)
        conn.protocol_version = ldap.VERSION3
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.set_option(ldap.OPT_NETWORK_TIMEOUT, cfg.timeout)
        conn.set_option(ldap.OPT_TIMEOUT, cfg.timeout)
        if cfg.ca_file:
            conn.set_option(ldap.OPT_X_TLS_CACERTFILE, cfg.ca_file)
        if cfg.uri.lower().startswith("ldaps://") or cfg.starttls:
            conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
            conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
        if cfg.starttls and not cfg.uri.lower().startswith("ldaps://"):
            conn.start_tls_s()
        return conn

    def _connection(self) -> Any:
        if self._conn is None:
            conn = self._new_connection()
            try:
                conn.simple_bind_s(
                    self._config.bind_dn, self._config.bind_password.get_secret_value()
                )
            except self._ldap.INVALID_CREDENTIALS as exc:
                raise InvalidCredentialsError("service account bind failed") from exc
            self._conn = conn
        return self._conn

    def _run(self, op: Callable[[Any], T]) -> T:
        """Run ``op`` on the shared connection, reconnecting once if it dropped."""
        ldap = self._ldap
        with self._lock:
            for attempt in (0, 1):
                try:
                    return op(self._connection())
                except (
                    ldap.SERVER_DOWN,
                    ldap.TIMEOUT,
                    ldap.UNAVAILABLE,
                    ldap.CONNECT_ERROR,
                ) as exc:
                    self._drop()
                    if attempt:
                        raise DirectoryError(f"directory unavailable: {exc}") from exc
                except ldap.LDAPError as exc:
                    raise self._translate(exc) from exc
            raise DirectoryError("unreachable")  # pragma: no cover

    def _translate(self, exc: Exception) -> DirectoryError:
        ldap = self._ldap
        if isinstance(exc, ldap.NO_SUCH_OBJECT):
            return NoSuchObjectError(str(exc))
        if isinstance(exc, ldap.ALREADY_EXISTS):
            return AlreadyExistsError(str(exc))
        if isinstance(exc, ldap.INVALID_CREDENTIALS):
            return InvalidCredentialsError(str(exc))
        if isinstance(exc, ldap.SIZELIMIT_EXCEEDED):
            return SizeLimitExceededError(str(exc))
        return DirectoryError(str(exc))

    # -- DirectoryClient -----------------------------------------------------------

    def search(
        self,
        base: str,
        filterstr: str = "(objectClass=*)",
        scope: Scope = Scope.SUBTREE,
        attrs: Sequence[str] | None = None,
        *,
        size_limit: int = 0,
        page_size: int = 500,
    ) -> Iterator[Entry]:
        ldap = self._ldap
        ldap_scope = {
            Scope.BASE: ldap.SCOPE_BASE,
            Scope.ONE: ldap.SCOPE_ONELEVEL,
            Scope.SUBTREE: ldap.SCOPE_SUBTREE,
        }[scope]
        attrlist = list(attrs) if attrs is not None else None

        def op(conn: Any) -> list[Entry]:
            results: list[Entry] = []
            paged = ldap.controls.SimplePagedResultsControl(
                criticality=False, size=page_size, cookie=""
            )
            while True:
                msgid = conn.search_ext(base, ldap_scope, filterstr, attrlist, serverctrls=[paged])
                _rtype, rdata, _rmsgid, ctrls = conn.result3(msgid)
                for dn, raw in rdata:
                    if dn is None:  # search continuation reference
                        continue
                    results.append(Entry(dn=dn, attrs=_to_attrs(raw)))
                    if size_limit and len(results) > size_limit:
                        raise SizeLimitExceededError(f"more than {size_limit} entries")
                cookie = next(
                    (
                        c.cookie
                        for c in ctrls
                        if c.controlType == ldap.controls.SimplePagedResultsControl.controlType
                    ),
                    None,
                )
                if not cookie:
                    return results
                paged.cookie = cookie

        return iter(self._run(op))

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        try:
            return next(self.search(dn, scope=Scope.BASE, attrs=attrs), None)
        except NoSuchObjectError:
            return None

    def add(self, dn: str, attrs: Mapping[str, Sequence[bytes]]) -> None:
        modlist = [(name, list(values)) for name, values in attrs.items()]
        self._run(lambda conn: conn.add_s(dn, modlist))

    def modify(self, dn: str, changes: Sequence[Modification]) -> None:
        ldap = self._ldap
        ops = {"add": ldap.MOD_ADD, "replace": ldap.MOD_REPLACE, "delete": ldap.MOD_DELETE}
        modlist = [(ops[c.op], c.attr, list(c.values) or None) for c in changes]
        self._run(lambda conn: conn.modify_s(dn, modlist))

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        if not recursive:
            self._run(lambda conn: conn.delete_s(dn))
            return
        dns = [e.dn for e in self.search(dn, scope=Scope.SUBTREE, attrs=["1.1"])]
        for victim in sorted(dns, key=dnlib.depth, reverse=True):
            self._run(lambda conn, victim=victim: conn.delete_s(victim))

    def rename(self, dn: str, new_rdn: str, new_superior: str | None = None) -> str:
        self._run(lambda conn: conn.rename_s(dn, new_rdn, new_superior, 1))
        superior = new_superior if new_superior is not None else dnlib.parent(dn) or ""
        return dnlib.join(new_rdn, superior)

    def check_password(self, dn: str, password: str) -> bool:
        if not password:
            return False
        ldap = self._ldap
        with self._lock:
            try:
                conn = self._new_connection()
            except ldap.LDAPError as exc:
                raise DirectoryError(f"cannot connect: {exc}") from exc
        try:
            conn.simple_bind_s(dn, password)
        except ldap.INVALID_CREDENTIALS:
            return False
        except ldap.LDAPError as exc:
            raise DirectoryError(f"password check failed: {exc}") from exc
        finally:
            self._unbind(conn)
        return True

    def schema_object_classes(self) -> set[str]:
        if self._object_classes is not None:
            return set(self._object_classes)
        ldap = self._ldap

        def op(conn: Any) -> set[str]:
            root = conn.search_s("", ldap.SCOPE_BASE, "(objectClass=*)", ["subschemaSubentry"])
            sub_dn = root[0][1]["subschemaSubentry"][0].decode("utf-8")
            sub = conn.search_s(sub_dn, ldap.SCOPE_BASE, "(objectClass=*)", ["objectClasses"])
            schema = ldap.schema.SubSchema(sub[0][1])
            names: set[str] = set()
            for oid in schema.listall(ldap.schema.models.ObjectClass):
                obj = schema.get_obj(ldap.schema.models.ObjectClass, oid)
                names.update(str(n).lower() for n in obj.names)
            return names

        self._object_classes = self._run(op)
        return set(self._object_classes)


def _to_attrs(raw: Mapping[str, Sequence[bytes]]) -> Attributes:
    return {name: [bytes(v) for v in values] for name, values in raw.items()}
