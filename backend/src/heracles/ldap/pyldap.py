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
from typing import Any, TypeVar, cast

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
    """Directory client backed by python-ldap with a pool of service connections.

    Up to ``config.pool_size`` operations run at the same time, each on its own
    connection; further callers wait for one. Connections are opened on demand and
    kept bound for reuse.
    """

    def __init__(self, config: DirectoryConfig) -> None:
        self._ldap: Any = _import_ldap()
        self._config = config
        #: Bound connections nobody is using (most recently used last).
        self._idle: list[Any] = []
        self._slots = threading.BoundedSemaphore(config.pool_size)
        #: Guards ``_idle`` and connection set-up (TLS options are process-wide).
        self._lock = threading.RLock()
        self._object_classes: set[str] | None = None

    # -- connection management ---------------------------------------------------

    @property
    def base_dn(self) -> str:
        return self._config.base_dn

    def close(self) -> None:
        """Unbind and drop the idle connections (one in use is kept by its operation)."""
        with self._lock:
            idle, self._idle = self._idle, []
        for conn in idle:
            self._unbind(conn)

    def _unbind(self, conn: Any) -> None:
        with contextlib.suppress(self._ldap.LDAPError):
            conn.unbind_s()

    def _new_connection(self) -> Any:
        ldap = self._ldap
        cfg = self._config
        with self._lock:
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

    def _checkout(self) -> Any:
        """An idle service connection, or a new bound one."""
        with self._lock:
            if self._idle:
                return self._idle.pop()
        conn = self._new_connection()
        try:
            conn.simple_bind_s(self._config.bind_dn, self._config.bind_password.get_secret_value())
        except self._ldap.INVALID_CREDENTIALS as exc:
            self._unbind(conn)
            raise InvalidCredentialsError("service account bind failed") from exc
        except self._ldap.LDAPError:
            self._unbind(conn)
            raise
        return conn

    def _run(self, op: Callable[[Any], T]) -> T:
        """Run ``op`` on a pooled connection, reconnecting once if it dropped."""
        ldap = self._ldap
        with self._slots:
            for attempt in (0, 1):
                conn: Any = None
                try:
                    conn = self._checkout()
                    result = op(conn)
                except (
                    ldap.SERVER_DOWN,
                    ldap.TIMEOUT,
                    ldap.UNAVAILABLE,
                    ldap.CONNECT_ERROR,
                ) as exc:
                    # the connection is dead, and the idle ones are probably as stale
                    if conn is not None:
                        self._unbind(conn)
                    self.close()
                    if attempt:
                        raise DirectoryError(f"directory unavailable: {exc}") from exc
                except ldap.LDAPError as exc:
                    self._checkin(conn)
                    raise self._translate(exc) from exc
                except BaseException:
                    # unknown state (an operation may be half read): do not reuse it
                    if conn is not None:
                        self._unbind(conn)
                    raise
                else:
                    self._checkin(conn)
                    return result
            raise DirectoryError("unreachable")  # pragma: no cover

    def _checkin(self, conn: Any) -> None:
        if conn is not None:
            with self._lock:
                self._idle.append(conn)

    def _translate(self, exc: Exception) -> DirectoryError:
        ldap = self._ldap
        message = _describe(exc)
        if isinstance(exc, ldap.NO_SUCH_OBJECT):
            return NoSuchObjectError(message)
        if isinstance(exc, ldap.ALREADY_EXISTS):
            return AlreadyExistsError(message)
        if isinstance(exc, ldap.INVALID_CREDENTIALS):
            return InvalidCredentialsError(message)
        if isinstance(exc, ldap.SIZELIMIT_EXCEEDED):
            return SizeLimitExceededError(message)
        return DirectoryError(message)

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


def _describe(exc: Exception) -> str:
    """Readable message from a python-ldap exception (its args hold a result dict)."""
    info: object = exc.args[0] if exc.args else None
    if isinstance(info, dict):
        details = cast("dict[str, object]", info)
        parts = [str(details.get("desc") or type(exc).__name__)]
        if details.get("info"):
            parts.append(str(details["info"]))
        if details.get("matched"):
            parts.append(f"(matched: {details['matched']})")
        return " ".join(parts)
    return str(exc)
