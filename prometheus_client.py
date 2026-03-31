"""
Local `prometheus_client` shim (dev/test fallback).

The real project depends on the external `prometheus_client` package.
This sandbox environment may not have it installed, but DevMesh tests only
require that imports work and metric objects support a small set of methods
used by `server.py`.

This shim is not a full Prometheus implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"


class CollectorRegistry:
    def __init__(self) -> None:
        self._metrics: List[object] = []

    def register(self, metric: object) -> None:
        self._metrics.append(metric)


class _BaseMetric:
    def __init__(
        self, name: str, registry: Optional[CollectorRegistry] = None, **_: object
    ) -> None:
        self.name = name
        self._registry = registry
        if registry is not None:
            registry.register(self)

    def labels(self, **_: object) -> "_BaseMetric":
        # DevMesh uses `counter.labels(status="completed").inc()` in one place.
        # We don't model per-label series; we just return self.
        return self


class Counter(_BaseMetric):
    def __init__(
        self,
        name: str,
        documentation: str = "",
        labelnames: Optional[List[str]] = None,
        registry: Optional[CollectorRegistry] = None,
        **kwargs: object,
    ) -> None:
        super().__init__(name, registry=registry)
        self._value = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self._value += float(amount)


class Gauge(_BaseMetric):
    def __init__(
        self,
        name: str,
        documentation: str = "",
        registry: Optional[CollectorRegistry] = None,
        **kwargs: object,
    ) -> None:
        super().__init__(name, registry=registry)
        self._value = 0.0

    def set(self, value: float) -> None:
        self._value = float(value)


class Histogram(_BaseMetric):
    def __init__(
        self,
        name: str,
        documentation: str = "",
        registry: Optional[CollectorRegistry] = None,
        **kwargs: object,
    ) -> None:
        super().__init__(name, registry=registry)
        self._values: List[float] = []

    def observe(self, value: float) -> None:
        self._values.append(float(value))


def generate_latest(registry: Optional[CollectorRegistry] = None) -> bytes:
    # Tests don't parse Prometheus output; they only need this function to exist.
    # Provide a minimal, valid text format.
    _ = registry
    return b"# prometheus_client shim\n"
