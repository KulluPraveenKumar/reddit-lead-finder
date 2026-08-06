"""Bounded adaptive concurrency pool, retry policy, and rate limiter.

DeepSeek has no batch endpoint, so bulk work is a thread pool. The single most
important property here is **attribution**: results are matched back to items
via ``futures[future] -> item``, never by position. Positional matching is the
classic silent-corruption bug in batched LLM pipelines — every lead gets an
analysis, none of them raises an error, and they belong to the wrong posts.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, TypeVar

from .errors import (
    AIError,
    BudgetExceededError,
    InsufficientBalanceError,
    InvalidAPIKeyError,
    ProviderError,
    RateLimitedError,
)

log = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


# ------------------------------------------------------------------- retries


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: float = 0.25

    def should_retry(self, error: BaseException, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        # 401 and 402 are never retried: the same request earns the same answer,
        # and retrying a 402 burns latency proving the account is still empty.
        if isinstance(error, InvalidAPIKeyError | InsufficientBalanceError | BudgetExceededError):
            return False
        if isinstance(error, AIError):
            return error.retryable
        return False

    def delay_for(self, error: BaseException, attempt: int) -> float:
        if isinstance(error, RateLimitedError) and error.retry_after:
            # Honour the server's own guidance over our backoff curve.
            return min(float(error.retry_after), self.max_delay)
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        # Jitter so a pool of 8 that all hit a 429 do not all retry in lockstep.
        return delay * (1 + random.uniform(-self.jitter, self.jitter))


# --------------------------------------------------------------- rate limiter


class RateLimiter:
    """Token bucket. Smooths bursts rather than capping throughput."""

    def __init__(self, rate_per_second: float = 8.0, burst: int = 16):
        self.rate = rate_per_second
        self.burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                shortfall = (tokens - self._tokens) / self.rate
            if time.monotonic() + shortfall > deadline:
                return False
            time.sleep(min(shortfall, 0.25))


# ----------------------------------------------------------------- the pool


@dataclass
class PoolReport:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: dict[Any, Any] = field(default_factory=dict)
    errors: dict[Any, BaseException] = field(default_factory=dict)
    stopped_early: bool = False
    stop_reason: str | None = None
    final_concurrency: int = 0
    duration_s: float = 0.0


class ConcurrencyPool:
    """Adaptive pool: halves on pressure, steps up on a clean window."""

    def __init__(self, initial: int = 8, floor: int = 1, ceiling: int = 16, *, rate_limiter: RateLimiter | None = None):
        self.initial = max(1, initial)
        self.floor = max(1, floor)
        self.ceiling = max(self.floor, ceiling)
        self.current = min(max(self.initial, self.floor), self.ceiling)
        self.rate_limiter = rate_limiter
        self._lock = threading.Lock()
        self._clean_streak = 0
        self.adaptations: list[tuple[str, int]] = []

    def on_pressure(self, reason: str = "rate_limited") -> None:
        with self._lock:
            previous = self.current
            self.current = max(self.floor, self.current // 2)
            self._clean_streak = 0
            if self.current != previous:
                self.adaptations.append((f"down:{reason}", self.current))
                log.warning("concurrency %d -> %d (%s)", previous, self.current, reason)

    def on_success(self) -> None:
        with self._lock:
            self._clean_streak += 1
            # Hysteresis: only step up after a sustained clean window, so an
            # intermittent 429 cannot make the pool oscillate.
            if self._clean_streak >= 20 and self.current < self.ceiling:
                previous = self.current
                self.current += 1
                self._clean_streak = 0
                self.adaptations.append(("up:clean", self.current))
                log.info("concurrency %d -> %d (clean window)", previous, self.current)

    def map(
        self,
        items: Sequence[T],
        fn: Callable[[T], R],
        *,
        key: Callable[[T], Any] | None = None,
        on_result: Callable[[T, R], None] | None = None,
        stop_on: tuple[type[BaseException], ...] = (
            InvalidAPIKeyError,
            InsufficientBalanceError,
            BudgetExceededError,
        ),
    ) -> PoolReport:
        """Run ``fn`` over ``items``, attributing every result to its own item."""
        report = PoolReport(total=len(items))
        if not items:
            return report

        key_of = key or (lambda item: item)
        started = time.perf_counter()
        workers = self.current

        with ThreadPoolExecutor(max_workers=workers) as executor:
            # THE mapping. Never a positional zip of items and results.
            futures: dict[Future, T] = {}
            stop = threading.Event()

            def wrapped(item: T) -> R:
                if stop.is_set():
                    raise RuntimeError("pool stopped")
                if self.rate_limiter and not self.rate_limiter.acquire():
                    raise RateLimitedError("Local rate limiter timed out")
                return fn(item)

            for item in items:
                futures[executor.submit(wrapped, item)] = item

            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                except stop_on as exc:
                    # Drain rather than abort: work already completed is
                    # preserved, which is what makes a 402 mid-run survivable.
                    report.errors[key_of(item)] = exc
                    report.failed += 1
                    report.stopped_early = True
                    report.stop_reason = type(exc).__name__
                    stop.set()
                    continue
                except RateLimitedError as exc:
                    self.on_pressure("rate_limited")
                    report.errors[key_of(item)] = exc
                    report.failed += 1
                    continue
                except ProviderError as exc:
                    if getattr(exc, "status_code", None) in (500, 502, 503, 504):
                        self.on_pressure("server_error")
                    report.errors[key_of(item)] = exc
                    report.failed += 1
                    continue
                except Exception as exc:  # noqa: BLE001 — one item must not kill the pool
                    report.errors[key_of(item)] = exc
                    report.failed += 1
                    continue

                self.on_success()
                report.results[key_of(item)] = result
                report.succeeded += 1
                if on_result is not None:
                    on_result(item, result)

        report.final_concurrency = self.current
        report.duration_s = time.perf_counter() - started
        return report


def run_with_retry(
    fn: Callable[[int], R],
    policy: RetryPolicy,
    *,
    on_retry: Callable[[BaseException, int, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> R:
    """Call ``fn(attempt)`` with retries. ``attempt`` is 1-based."""
    attempt = 1
    while True:
        try:
            return fn(attempt)
        except Exception as exc:
            if not policy.should_retry(exc, attempt):
                raise
            delay = policy.delay_for(exc, attempt)
            if on_retry:
                on_retry(exc, attempt, delay)
            sleep(delay)
            attempt += 1


def chunked(items: Iterable[T], size: int) -> Iterable[list[T]]:
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
