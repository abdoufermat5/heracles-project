"""A tiny Prometheus text-format registry (counters, gauges, histograms).

Kept in-house to avoid a dependency; process-wide, thread-safe. Components record
into the module-level :data:`REGISTRY`; the ``/metrics`` endpoint renders it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence

DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

Labels = tuple[str, ...]


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _fmt(names: Sequence[str], values: Labels, extra: str = "") -> str:
    parts = [f'{n}="{_esc(v)}"' for n, v in zip(names, values, strict=True)]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


class _Metric:
    kind = ""

    def __init__(self, name: str, doc: str, labels: Sequence[str]) -> None:
        self.name = name
        self.doc = doc
        self.labels = tuple(labels)
        self._lock = threading.Lock()

    def header(self) -> list[str]:
        return [f"# HELP {self.name} {self.doc}", f"# TYPE {self.name} {self.kind}"]

    def render(self) -> list[str]:
        raise NotImplementedError


class Counter(_Metric):
    kind = "counter"

    def __init__(self, name: str, doc: str, labels: Sequence[str] = ()) -> None:
        super().__init__(name, doc, labels)
        self._values: dict[Labels, float] = {}

    def inc(self, *labels: str, amount: float = 1.0) -> None:
        with self._lock:
            self._values[labels] = self._values.get(labels, 0.0) + amount

    def render(self) -> list[str]:
        with self._lock:
            items = sorted(self._values.items())
        return [f"{self.name}{_fmt(self.labels, k)} {v}" for k, v in items]


class Gauge(_Metric):
    kind = "gauge"

    def __init__(self, name: str, doc: str, labels: Sequence[str] = ()) -> None:
        super().__init__(name, doc, labels)
        self._values: dict[Labels, float] = {}

    def set(self, value: float, *labels: str) -> None:
        with self._lock:
            self._values[labels] = value

    def render(self) -> list[str]:
        with self._lock:
            items = sorted(self._values.items())
        return [f"{self.name}{_fmt(self.labels, k)} {v}" for k, v in items]


class Histogram(_Metric):
    kind = "histogram"

    def __init__(
        self,
        name: str,
        doc: str,
        labels: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_BUCKETS,
    ) -> None:
        super().__init__(name, doc, labels)
        self.buckets = tuple(sorted(buckets))
        self._data: dict[Labels, tuple[list[int], float]] = {}

    def observe(self, value: float, *labels: str) -> None:
        with self._lock:
            counts, total = self._data.get(labels, ([0] * (len(self.buckets) + 1), 0.0))
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[i] += 1
            counts[-1] += 1
            self._data[labels] = (counts, total + value)

    def render(self) -> list[str]:
        with self._lock:
            items = sorted((k, (list(c), t)) for k, (c, t) in self._data.items())
        out: list[str] = []
        for key, (counts, total) in items:
            for bound, count in zip(self.buckets, counts, strict=False):
                out.append(f"{self.name}_bucket{_fmt(self.labels, key, f'le="{bound}"')} {count}")
            out.append(f"{self.name}_bucket{_fmt(self.labels, key, 'le="+Inf"')} {counts[-1]}")
            out.append(f"{self.name}_sum{_fmt(self.labels, key)} {total}")
            out.append(f"{self.name}_count{_fmt(self.labels, key)} {counts[-1]}")
        return out


Collector = Callable[[], Iterable[tuple[str, str, str, Labels, Sequence[str], float]]]


class Registry:
    def __init__(self) -> None:
        self._metrics: list[_Metric] = []
        self._collectors: list[Collector] = []
        self._lock = threading.Lock()

    def counter(self, name: str, doc: str, labels: Sequence[str] = ()) -> Counter:
        return self._add(Counter(name, doc, labels))

    def gauge(self, name: str, doc: str, labels: Sequence[str] = ()) -> Gauge:
        return self._add(Gauge(name, doc, labels))

    def histogram(self, name: str, doc: str, labels: Sequence[str] = ()) -> Histogram:
        return self._add(Histogram(name, doc, labels))

    def _add[M: _Metric](self, metric: M) -> M:
        with self._lock:
            self._metrics.append(metric)
        return metric

    def add_collector(self, collector: Collector) -> None:
        """Register a callable yielding ``(name, help, type, label_values, label_names, value)``
        samples read at scrape time (pool usage, scheduler state, ...)."""
        with self._lock:
            self._collectors.append(collector)

    def remove_collector(self, collector: Collector) -> None:
        """Forget a collector registered with :meth:`add_collector` (no-op when unknown)."""
        with self._lock:
            self._collectors = [c for c in self._collectors if c != collector]

    def render(self) -> str:
        lines: list[str] = []
        for metric in list(self._metrics):
            lines += metric.header() + metric.render()
        seen: set[str] = set()
        for collector in list(self._collectors):
            try:
                samples = list(collector())
            except Exception:
                samples = []
            for name, doc, kind, values, names, value in samples:
                if name not in seen:
                    seen.add(name)
                    lines += [f"# HELP {name} {doc}", f"# TYPE {name} {kind}"]
                lines.append(f"{name}{_fmt(names, values)} {value}")
        return "\n".join(lines) + "\n"


REGISTRY = Registry()

LDAP_OPERATION_SECONDS = REGISTRY.histogram(
    "heracles_ldap_operation_seconds", "LDAP operation latency", ("directory", "server", "op")
)
LDAP_ERRORS = REGISTRY.counter(
    "heracles_ldap_errors_total", "LDAP operation errors", ("directory", "server", "kind")
)
DATABASE_ERRORS = REGISTRY.counter(
    "heracles_database_errors_total", "Application database errors", ()
)
HTTP_REQUESTS = REGISTRY.counter(
    "heracles_http_requests_total", "HTTP requests", ("method", "route", "status")
)
HTTP_SECONDS = REGISTRY.histogram(
    "heracles_http_request_seconds", "HTTP request latency", ("method", "route")
)
