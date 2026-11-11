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
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from types import ModuleType
from typing import Any, TypeVar, cast

from heracles import metrics
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    Attributes,
    DirectoryError,
    DirectoryUnavailableError,
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


#: First and longest time a failing server is skipped (doubles at each consecutive failure).
BACKOFF_INITIAL = 2.0
BACKOFF_MAX = 60.0
_READ_ONLY_HINTS = ("shadow", "read-only", "readonly", "read only", "slave", "replica")

Sample = tuple[str, str, str, tuple[str, ...], tuple[str, ...], float]


class _Skip(Exception):  # noqa: N818
    """This server cannot serve the operation: try the next one."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.cause = cause


class _ServerState:
    """Health of one server: skipped until ``down_until``; no writes until ``no_write_until``."""

    __slots__ = ("down_until", "failures", "no_write_until")

    def __init__(self) -> None:
        self.down_until = 0.0
        self.failures = 0
        self.no_write_until = 0.0


class PyLdapDirectory:
    """Directory client backed by python-ldap with a pool of service connections.

    Up to ``config.pool_size`` operations run at the same time, each on its own
    connection; further callers wait for one. Connections are opened on demand and
    kept bound for reuse. With several URIs the servers are tried in order; one that
    fails is skipped for a backoff period (exponential, capped). Writes go to ``uris``
    only, and a server answering a write with a referral or a read-only refusal is
    skipped for writes; searches prefer healthy ``read_uris`` replicas.
    """

    def __init__(
        self,
        config: DirectoryConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        backoff_initial: float = BACKOFF_INITIAL,
        backoff_max: float = BACKOFF_MAX,
    ) -> None:
        self._ldap: Any = _import_ldap()
        self._config = config
        self._clock = clock
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._write_uris = config.write_uris
        self._read_uris = [u for u in config.read_uris if u not in self._write_uris]
        self._state: dict[str, _ServerState] = {u: _ServerState() for u in config.all_uris}
        #: Bound connections nobody is using, with their server (most recently used last).
        self._idle: list[tuple[str, Any]] = []
        self._in_use = 0
        self._slots = threading.BoundedSemaphore(config.pool_size)
        #: Guards ``_idle``, server states and connection set-up (TLS options are process-wide).
        self._lock = threading.RLock()
        self._object_classes: set[str] | None = None
        metrics.REGISTRY.add_collector(self._collect)

    # -- server health -----------------------------------------------------------------

    def server_states(self) -> dict[str, str]:
        """``uri -> "up" | "down"`` (down: skipped until its backoff elapses)."""
        now = self._clock()
        with self._lock:
            return {u: "down" if st.down_until > now else "up" for u, st in self._state.items()}

    def writable(self) -> bool:
        """Whether some server currently accepts writes."""
        return bool(self._candidates(write=True))

    def _mark_down(self, uri: str) -> None:
        with self._lock:
            st = self._state[uri]
            st.failures += 1
            delay = min(self._backoff_max, self._backoff_initial * 2 ** (st.failures - 1))
            st.down_until = self._clock() + delay
        self._drop_idle(uri)

    def _mark_up(self, uri: str) -> None:
        with self._lock:
            st = self._state[uri]
            st.failures = 0
            st.down_until = 0.0

    def _mark_no_write(self, uri: str) -> None:
        with self._lock:
            self._state[uri].no_write_until = self._clock() + self._backoff_max

    def _drop_idle(self, uri: str) -> None:
        with self._lock:
            dropped = [c for u, c in self._idle if u == uri]
            self._idle = [(u, c) for u, c in self._idle if u != uri]
        for conn in dropped:
            self._unbind(conn)

    def _candidates(self, *, write: bool) -> list[str]:
        """Servers to try, best first: healthy ones, replicas before primaries for reads."""
        now = self._clock()
        with self._lock:
            up = [u for u in self._write_uris if self._state[u].down_until <= now]
            if write:
                return [u for u in up if self._state[u].no_write_until <= now]
            replicas = [u for u in self._read_uris if self._state[u].down_until <= now]
            return [*replicas, *up]

    def _collect(self) -> list[Sample]:
        d = self._config.id
        with self._lock:
            used = self._in_use
        out: list[Sample] = [
            (
                "heracles_ldap_pool_in_use",
                "Busy LDAP connections",
                "gauge",
                (d,),
                ("directory",),
                used,
            ),
            (
                "heracles_ldap_pool_size",
                "LDAP pool capacity",
                "gauge",
                (d,),
                ("directory",),
                self._config.pool_size,
            ),
        ]
        for uri, state in self.server_states().items():
            out.append(
                (
                    "heracles_ldap_server_up",
                    "1 when the server is not backed off",
                    "gauge",
                    (d, uri),
                    ("directory", "server"),
                    1.0 if state == "up" else 0.0,
                )
            )
        return out

    # -- connection management ---------------------------------------------------------

    @property
    def base_dn(self) -> str:
        return self._config.base_dn

    def close(self) -> None:
        """Unbind and drop the idle connections (one in use is kept by its operation)."""
        with self._lock:
            idle, self._idle = self._idle, []
        for _uri, conn in idle:
            self._unbind(conn)

    def _unbind(self, conn: Any) -> None:
        with contextlib.suppress(self._ldap.LDAPError):
            conn.unbind_s()

    def _new_connection(self, uri: str) -> Any:
        ldap = self._ldap
        cfg = self._config
        secure = uri.lower().startswith("ldaps://")
        with self._lock:
            conn = ldap.initialize(uri)
            conn.protocol_version = ldap.VERSION3
            conn.set_option(ldap.OPT_REFERRALS, 0)
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, cfg.timeout)
            conn.set_option(ldap.OPT_TIMEOUT, cfg.timeout)
            if cfg.ca_file:
                conn.set_option(ldap.OPT_X_TLS_CACERTFILE, cfg.ca_file)
            if secure or cfg.starttls:
                conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
                conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
        if cfg.starttls and not secure:
            conn.start_tls_s()
        return conn

    def _checkout(self, uri: str) -> tuple[Any, bool]:
        """``(connection, reused)``: an idle bound connection to ``uri``, or a new one."""
        with self._lock:
            for i in range(len(self._idle) - 1, -1, -1):
                if self._idle[i][0] == uri:
                    return self._idle.pop(i)[1], True
        conn = self._new_connection(uri)
        try:
            conn.simple_bind_s(self._config.bind_dn, self._config.bind_password.get_secret_value())
        except self._ldap.INVALID_CREDENTIALS as exc:
            self._unbind(conn)
            raise InvalidCredentialsError("service account bind failed") from exc
        except self._ldap.LDAPError:
            self._unbind(conn)
            raise
        return conn, False

    def _is_down_error(self, exc: BaseException) -> bool:
        ldap = self._ldap
        return isinstance(
            exc, (ldap.SERVER_DOWN, ldap.TIMEOUT, ldap.UNAVAILABLE, ldap.CONNECT_ERROR)
        )

    def _is_read_only_refusal(self, exc: BaseException) -> bool:
        ldap = self._ldap
        if isinstance(exc, ldap.REFERRAL):
            return True
        if isinstance(exc, ldap.UNWILLING_TO_PERFORM):
            return any(h in _describe(cast("Exception", exc)).lower() for h in _READ_ONLY_HINTS)
        return False

    def _attempt(self, uri: str, op: Callable[[Any], T], write: bool, name: str) -> T:
        """Run ``op`` on ``uri``; raise :class:`_Skip` when this server cannot serve it."""
        ldap = self._ldap
        directory = self._config.id
        for attempt in (0, 1):
            conn: Any = None
            reused = False
            started = time.perf_counter()
            try:
                conn, reused = self._checkout(uri)
                result = op(conn)
            except ldap.LDAPError as exc:
                connect_failed = conn is None
                if self._is_down_error(exc) or connect_failed:
                    if conn is not None:
                        self._unbind(conn)
                    metrics.LDAP_ERRORS.inc(directory, uri, "unavailable")
                    if reused and attempt == 0:
                        self._drop_idle(uri)  # stale pooled connections: one fresh attempt
                        continue
                    self._mark_down(uri)
                    raise _Skip(exc) from exc
                self._checkin(uri, conn)
                if write and self._is_read_only_refusal(exc):
                    metrics.LDAP_ERRORS.inc(directory, uri, "read_only")
                    self._mark_no_write(uri)
                    raise _Skip(exc) from exc
                metrics.LDAP_ERRORS.inc(directory, uri, type(exc).__name__)
                raise self._translate(exc) from exc
            except BaseException:
                # unknown state (an operation may be half read): do not reuse it
                if conn is not None:
                    self._unbind(conn)
                raise
            metrics.LDAP_OPERATION_SECONDS.observe(
                time.perf_counter() - started, directory, uri, name
            )
            self._mark_up(uri)
            self._checkin(uri, conn)
            return result
        raise DirectoryUnavailableError("unreachable")  # pragma: no cover

    def _run(self, op: Callable[[Any], T], *, write: bool = False, name: str = "op") -> T:
        """Run ``op`` on a pooled connection, failing over to the next server."""
        with self._slots:
            with self._lock:
                self._in_use += 1
            try:
                candidates = self._candidates(write=write)
                if not candidates:
                    raise DirectoryUnavailableError(
                        "directory unavailable: no server "
                        + ("accepts writes" if write else "is reachable")
                    )
                last: BaseException | None = None
                for uri in candidates:
                    try:
                        return self._attempt(uri, op, write, name)
                    except _Skip as skip:
                        last = skip.cause
                raise DirectoryUnavailableError(f"directory unavailable: {last}") from last
            finally:
                with self._lock:
                    self._in_use -= 1

    def _checkin(self, uri: str, conn: Any) -> None:
        if conn is not None:
            with self._lock:
                self._idle.append((uri, conn))

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

        return iter(self._run(op, name="search"))

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        try:
            return next(self.search(dn, scope=Scope.BASE, attrs=attrs), None)
        except NoSuchObjectError:
            return None

    def add(self, dn: str, attrs: Mapping[str, Sequence[bytes]]) -> None:
        modlist = [(name, list(values)) for name, values in attrs.items()]
        self._run(lambda conn: conn.add_s(dn, modlist), write=True, name="add")

    def modify(self, dn: str, changes: Sequence[Modification]) -> None:
        ldap = self._ldap
        ops = {"add": ldap.MOD_ADD, "replace": ldap.MOD_REPLACE, "delete": ldap.MOD_DELETE}
        modlist = [(ops[c.op], c.attr, list(c.values) or None) for c in changes]
        self._run(lambda conn: conn.modify_s(dn, modlist), write=True, name="modify")

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        if not recursive:
            self._run(lambda conn: conn.delete_s(dn), write=True, name="delete")
            return
        dns = [e.dn for e in self.search(dn, scope=Scope.SUBTREE, attrs=["1.1"])]
        for victim in sorted(dns, key=dnlib.depth, reverse=True):
            self._run(lambda conn, victim=victim: conn.delete_s(victim), write=True, name="delete")

    def rename(self, dn: str, new_rdn: str, new_superior: str | None = None) -> str:
        self._run(
            lambda conn: conn.rename_s(dn, new_rdn, new_superior, 1), write=True, name="rename"
        )
        superior = new_superior if new_superior is not None else dnlib.parent(dn) or ""
        return dnlib.join(new_rdn, superior)

    def check_password(self, dn: str, password: str) -> bool:
        if not password:
            return False
        ldap = self._ldap
        last: BaseException | None = None
        for uri in [*self._candidates(write=False)]:
            try:
                conn = self._new_connection(uri)
                try:
                    conn.simple_bind_s(dn, password)
                finally:
                    self._unbind(conn)
            except ldap.INVALID_CREDENTIALS:
                return False
            except ldap.LDAPError as exc:
                if self._is_down_error(exc):
                    self._mark_down(uri)
                    last = exc
                    continue
                raise DirectoryError(f"password check failed: {exc}") from exc
            return True
        raise DirectoryUnavailableError(f"cannot connect: {last or 'no server is reachable'}")

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

        self._object_classes = self._run(op, name="schema")
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
