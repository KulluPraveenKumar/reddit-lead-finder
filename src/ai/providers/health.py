"""Per-provider health: circuit breaker, latency, failure classification.

A circuit breaker exists to stop a *degraded* provider from consuming the whole
run's latency budget. Without one, a provider that times out on every call still
costs 60 seconds per item before failing, and a 200-item run spends three hours
discovering something the second failure already proved.

Three states, the standard shape:

    CLOSED ──(failures >= threshold)──► OPEN ──(cooldown elapsed)──► HALF_OPEN
       ▲                                                                  │
       └──────────────(probe succeeds)────────────────────────────────────┘
                              (probe fails → back to OPEN)

**What counts as a failure is a deliberate choice.** Only faults that a *retry
against a different provider* could plausibly fix trip the breaker: timeouts,
5xx, connection errors. A 401, a 402, or a schema violation would fail
identically everywhere, so tripping on those would take a working provider out
of service for a problem it does not have.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

from ..errors import (
    AIError,
    InsufficientBalanceError,
    InvalidAPIKeyError,
    ProviderBadRequestError,
    ProviderServerError,
    ProviderUnreachableError,
    RateLimitedError,
)

log = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


def trips_breaker(error: BaseException) -> bool:
    """Would routing this call elsewhere plausibly help?

    Yes for transport and server faults. No for credential, billing, or content
    faults — those are properties of the request or the account, and would
    reproduce on any provider.
    """
    if isinstance(error, InvalidAPIKeyError | InsufficientBalanceError | ProviderBadRequestError):
        return False
    if isinstance(error, ProviderUnreachableError | ProviderServerError | RateLimitedError):
        return True
    if isinstance(error, AIError):
        return error.retryable
    return isinstance(error, OSError | TimeoutError)


@dataclass
class ProviderHealth:
    """Health of one provider. Thread-safe; a pool shares it."""

    name: str
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    #: Consecutive successful probes needed to close the circuit again.
    recovery_successes: int = 2

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_calls: int = 0
    total_failures: int = 0
    opened_at: float | None = None
    last_error: str | None = None
    last_error_at: float | None = None

    _latencies: deque[int] = field(default_factory=lambda: deque(maxlen=200))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ------------------------------------------------------------- recording

    def record_success(self, latency_ms: int = 0) -> None:
        with self._lock:
            self.total_calls += 1
            self.consecutive_failures = 0
            if latency_ms:
                self._latencies.append(latency_ms)

            if self.state is CircuitState.HALF_OPEN:
                self.consecutive_successes += 1
                if self.consecutive_successes >= self.recovery_successes:
                    log.info("provider %s recovered; circuit closed", self.name)
                    self.state = CircuitState.CLOSED
                    self.consecutive_successes = 0
                    self.opened_at = None
                    self.last_error = None
            else:
                self.consecutive_successes = 0

    def record_failure(self, error: BaseException, latency_ms: int = 0) -> None:
        with self._lock:
            self.total_calls += 1
            self.total_failures += 1
            self.last_error = f"{type(error).__name__}: {error}"[:300]
            self.last_error_at = time.monotonic()
            if latency_ms:
                self._latencies.append(latency_ms)

            if not trips_breaker(error):
                # A credential or content fault says nothing about provider
                # health. Recorded for visibility, but it must not open the
                # circuit — that would take a working provider offline.
                return

            self.consecutive_successes = 0

            if self.state is CircuitState.HALF_OPEN:
                log.warning("provider %s probe failed; circuit re-opened", self.name)
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()
                return

            self.consecutive_failures += 1
            if (
                self.state is CircuitState.CLOSED
                and self.consecutive_failures >= self.failure_threshold
            ):
                log.warning(
                    "provider %s failed %d times consecutively; circuit opened for %.0fs",
                    self.name,
                    self.consecutive_failures,
                    self.cooldown_seconds,
                )
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()

    # ------------------------------------------------------------- decisions

    def allows_request(self) -> bool:
        """True if a call may proceed. Moves OPEN -> HALF_OPEN when due."""
        with self._lock:
            if self.state is CircuitState.CLOSED:
                return True
            if self.state is CircuitState.HALF_OPEN:
                return True
            if self.opened_at is None:
                self.state = CircuitState.CLOSED
                return True
            if time.monotonic() - self.opened_at >= self.cooldown_seconds:
                log.info("provider %s cooldown elapsed; probing", self.name)
                self.state = CircuitState.HALF_OPEN
                self.consecutive_successes = 0
                return True
            return False

    @property
    def available(self) -> bool:
        return self.state is not CircuitState.OPEN

    @property
    def seconds_until_retry(self) -> float:
        if self.state is not CircuitState.OPEN or self.opened_at is None:
            return 0.0
        return max(0.0, self.cooldown_seconds - (time.monotonic() - self.opened_at))

    # -------------------------------------------------------------- readouts

    @property
    def failure_rate(self) -> float:
        return self.total_failures / self.total_calls if self.total_calls else 0.0

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
            "provider": self.name,
            "state": str(self.state),
            "available": self.available,
            "consecutive_failures": self.consecutive_failures,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
            "failure_rate": round(self.failure_rate, 4),
            "mean_latency_ms": self.mean_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "seconds_until_retry": round(self.seconds_until_retry, 1),
            "last_error": self.last_error,
        }

    def reset(self) -> None:
        with self._lock:
            self.state = CircuitState.CLOSED
            self.consecutive_failures = 0
            self.consecutive_successes = 0
            self.opened_at = None
            self.last_error = None


class HealthRegistry:
    """Health for every provider seen this process."""

    def __init__(self, *, failure_threshold: int = 3, cooldown_seconds: float = 60.0):
        self._health: dict[str, ProviderHealth] = {}
        self._lock = threading.Lock()
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

    def for_provider(self, name: str) -> ProviderHealth:
        with self._lock:
            if name not in self._health:
                self._health[name] = ProviderHealth(
                    name=name,
                    failure_threshold=self.failure_threshold,
                    cooldown_seconds=self.cooldown_seconds,
                )
            return self._health[name]

    def all(self) -> dict[str, dict]:
        with self._lock:
            return {name: health.to_dict() for name, health in self._health.items()}

    def reset(self) -> None:
        with self._lock:
            for health in self._health.values():
                health.reset()
