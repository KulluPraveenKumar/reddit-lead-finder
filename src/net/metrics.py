"""In-process network counters, flushed to the ``metrics`` table."""

from __future__ import annotations

import threading
from collections import Counter, deque
from dataclasses import dataclass, field


@dataclass
class NetMetrics:
    requests: int = 0
    successes: int = 0
    failures: int = 0
    blocked: int = 0
    cache_hits: int = 0
    by_proxy: Counter = field(default_factory=Counter)
    failures_by_proxy: Counter = field(default_factory=Counter)
    _latencies: deque[int] = field(default_factory=lambda: deque(maxlen=500))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(
        self, *, ok: bool, latency_ms: int = 0, proxy: str | None = None, blocked: bool = False
    ) -> None:
        with self._lock:
            self.requests += 1
            if ok:
                self.successes += 1
                if latency_ms:
                    self._latencies.append(latency_ms)
            else:
                self.failures += 1
                if proxy:
                    self.failures_by_proxy[proxy] += 1
            if blocked:
                self.blocked += 1
            if proxy:
                self.by_proxy[proxy] += 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    @property
    def success_rate(self) -> float:
        return self.successes / self.requests if self.requests else 0.0

    @property
    def cache_hit_ratio(self) -> float:
        total = self.requests + self.cache_hits
        return self.cache_hits / total if total else 0.0

    @property
    def mean_latency_ms(self) -> int:
        return int(sum(self._latencies) / len(self._latencies)) if self._latencies else 0

    @property
    def p95_latency_ms(self) -> int:
        if not self._latencies:
            return 0
        ordered = sorted(self._latencies)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]

    def to_dict(self) -> dict:
        return {
            "requests": self.requests,
            "successes": self.successes,
            "failures": self.failures,
            "blocked": self.blocked,
            "cache_hits": self.cache_hits,
            "success_rate": round(self.success_rate, 4),
            "cache_hit_ratio": round(self.cache_hit_ratio, 4),
            "mean_latency_ms": self.mean_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "requests_by_proxy": dict(self.by_proxy),
            "failures_by_proxy": dict(self.failures_by_proxy),
        }

    def flush_to_db(self) -> None:
        """Persist a snapshot. Never allowed to break the run it measures."""
        import contextlib

        with contextlib.suppress(Exception):
            from datetime import UTC, datetime

            from ..db.database import session_scope
            from ..db.models import Metric

            now = datetime.now(UTC).replace(tzinfo=None)
            with session_scope() as session:
                for name, value in [
                    ("net.requests", self.requests),
                    ("net.successes", self.successes),
                    ("net.failures", self.failures),
                    ("net.blocked", self.blocked),
                    ("net.cache_hits", self.cache_hits),
                    ("net.mean_latency_ms", self.mean_latency_ms),
                    ("net.p95_latency_ms", self.p95_latency_ms),
                ]:
                    session.add(Metric(name=name, value=float(value), recorded_at=now))

    def reset(self) -> None:
        with self._lock:
            self.requests = self.successes = self.failures = 0
            self.blocked = self.cache_hits = 0
            self.by_proxy.clear()
            self.failures_by_proxy.clear()
            self._latencies.clear()
