"""AI metrics: the numbers that predict a cost problem before the invoice does.

Every one of these comes from data the provider already returns, so the whole
suite costs nothing to collect. The one that matters most is
``prefix_cache_ratio``: cached input is priced ~50x below uncached, so a cache
that silently stops hitting is a 50x cost increase with no other symptom.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

#: Below this, /health/ai renders red with the 50x explanation.
CACHE_HIT_TARGET = 0.85
REPAIR_RATE_TARGET = 0.05
EMPTY_RATE_TARGET = 0.02


@dataclass
class AIMetrics:
    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    repairs: int = 0
    empty_responses: int = 0
    invalid_json: int = 0
    schema_errors: int = 0
    truncated: int = 0

    input_tokens_cached: int = 0
    input_tokens_uncached: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    _latencies: deque[int] = field(default_factory=lambda: deque(maxlen=500))
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _prefix_hashes: set[str] = field(default_factory=set)

    # ------------------------------------------------------------- recording

    def record_call(
        self,
        *,
        cached: int = 0,
        uncached: int = 0,
        out: int = 0,
        cost: float = 0.0,
        latency_ms: int = 0,
        from_cache: bool = False,
        truncated: bool = False,
        prefix_hash: str | None = None,
    ) -> None:
        with self._lock:
            self.calls += 1
            if from_cache:
                self.cache_hits += 1
            else:
                self.input_tokens_cached += cached
                self.input_tokens_uncached += uncached
                self.output_tokens += out
                self.cost_usd += cost
                if latency_ms:
                    self._latencies.append(latency_ms)
            if truncated:
                self.truncated += 1
            if prefix_hash:
                self._prefix_hashes.add(prefix_hash)

    def record_repair(self, branch: str) -> None:
        with self._lock:
            self.repairs += 1
            if branch == "empty_content":
                self.empty_responses += 1
            elif branch == "invalid_json":
                self.invalid_json += 1
            elif branch == "schema_error":
                self.schema_errors += 1

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1

    # -------------------------------------------------------------- readouts

    @property
    def prefix_cache_ratio(self) -> float:
        total = self.input_tokens_cached + self.input_tokens_uncached
        return self.input_tokens_cached / total if total else 0.0

    @property
    def response_cache_ratio(self) -> float:
        return self.cache_hits / self.calls if self.calls else 0.0

    @property
    def repair_rate(self) -> float:
        return self.repairs / self.calls if self.calls else 0.0

    @property
    def empty_rate(self) -> float:
        return self.empty_responses / self.calls if self.calls else 0.0

    @property
    def mean_latency_ms(self) -> int:
        return int(sum(self._latencies) / len(self._latencies)) if self._latencies else 0

    @property
    def p95_latency_ms(self) -> int:
        if not self._latencies:
            return 0
        ordered = sorted(self._latencies)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]

    @property
    def prefix_stable(self) -> bool:
        """One distinct prefix hash per run is the healthy state.

        More than one means something volatile crept into the frozen half and
        the cache is missing on every call after the first.
        """
        return len(self._prefix_hashes) <= 1

    @property
    def distinct_prefixes(self) -> int:
        return len(self._prefix_hashes)

    def health(self) -> dict[str, dict]:
        """Metric -> value, target, and whether it is currently OK."""
        return {
            "prefix_cache_ratio": {
                "value": round(self.prefix_cache_ratio, 4),
                "target": CACHE_HIT_TARGET,
                "ok": self.prefix_cache_ratio >= CACHE_HIT_TARGET or self.calls < 2,
                "note": (
                    "Cached input is priced ~50x below uncached. A low ratio means the "
                    "frozen prefix is not byte-stable."
                ),
            },
            "repair_rate": {
                "value": round(self.repair_rate, 4),
                "target": REPAIR_RATE_TARGET,
                "ok": self.repair_rate <= REPAIR_RATE_TARGET,
                "note": "Share of calls that needed the repair ladder.",
            },
            "empty_rate": {
                "value": round(self.empty_rate, 4),
                "target": EMPTY_RATE_TARGET,
                "ok": self.empty_rate <= EMPTY_RATE_TARGET,
                "note": "Share of calls returning empty content.",
            },
            "prefix_stable": {
                "value": self.distinct_prefixes,
                "target": 1,
                "ok": self.prefix_stable,
                "note": "Distinct frozen prefixes seen. More than 1 breaks caching.",
            },
        }

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "failures": self.failures,
            "repairs": self.repairs,
            "empty_responses": self.empty_responses,
            "invalid_json": self.invalid_json,
            "schema_errors": self.schema_errors,
            "truncated": self.truncated,
            "input_tokens_cached": self.input_tokens_cached,
            "input_tokens_uncached": self.input_tokens_uncached,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "prefix_cache_ratio": round(self.prefix_cache_ratio, 4),
            "response_cache_ratio": round(self.response_cache_ratio, 4),
            "repair_rate": round(self.repair_rate, 4),
            "empty_rate": round(self.empty_rate, 4),
            "mean_latency_ms": self.mean_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "distinct_prefixes": self.distinct_prefixes,
            "prefix_stable": self.prefix_stable,
        }

    def reset(self) -> None:
        with self._lock:
            self.calls = self.cache_hits = self.failures = self.repairs = 0
            self.empty_responses = self.invalid_json = self.schema_errors = self.truncated = 0
            self.input_tokens_cached = self.input_tokens_uncached = self.output_tokens = 0
            self.cost_usd = 0.0
            self._latencies.clear()
            self._prefix_hashes.clear()
