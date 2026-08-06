"""ProxiedHTTPClient — every outbound request goes through here.

Reddit-agnostic. Phase 4's website fetcher reuses it unchanged, which is the
test of whether the abstraction is real.

The loop, in order, because the order is the design:

    acquire proxy (paced, LRU)
      -> cache lookup            hit? return, no network
      -> request through proxy
      -> classify status         403/429/5xx/timeout
      -> classify BODY           a 200 can still be a block
      -> success: record, cache
      -> failure: record, rotate or back off, retry

**Body classification is the step that is easy to omit and expensive to omit.**
Reddit answers with HTTP 200 and an interstitial; treating that as success
caches a block and reports "no posts found".
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from . import blocks
from .metrics import NetMetrics
from .proxy_manager import ProxyManager
from .retry import BlockedError, NetErrorClass, ProxyExhaustedError, RetryPolicy
from .retry import classify as classify_status

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str = ""
    from_cache: bool = False
    proxy: str | None = None
    latency_ms: int = 0
    attempts: int = 1
    verdict: blocks.BlockVerdict = field(
        default_factory=lambda: blocks.BlockVerdict(blocks.BlockKind.NONE)
    )
    final_url: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and not self.verdict.blocked


class ProxiedHTTPClient:
    def __init__(
        self,
        proxy_manager: ProxyManager | None = None,
        *,
        cache=None,
        metrics: NetMetrics | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout: tuple[float, float] = (10.0, 30.0),
        max_bytes: int = 5_000_000,
    ):
        self.proxies = proxy_manager
        self.cache = cache
        self.metrics = metrics or NetMetrics()
        self.retry = retry_policy or RetryPolicy()
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._direct_session: requests.Session | None = None

    # ---------------------------------------------------------------- fetch

    def get(
        self,
        url: str,
        *,
        expect_selector: str | None = None,
        cache_ttl: int | None = None,
        referer: str | None = None,
        allow_cache: bool = True,
    ) -> FetchResult:
        """Fetch ``url``, rotating proxies and detecting blocks.

        ``expect_selector`` is a CSS selector the response should match. It is
        what lets a 200-with-no-content be distinguished from a 200 that simply
        has nothing to show.
        """
        if allow_cache and self.cache is not None:
            cached = self.cache.get(url)
            if cached is not None:
                self.metrics.record_cache_hit()
                return FetchResult(
                    url=url,
                    status_code=200,
                    text=cached,
                    from_cache=True,
                    verdict=blocks.BlockVerdict(blocks.BlockKind.NONE),
                )

        attempt = 0
        last_error: Exception | None = None

        while attempt < self.retry.max_attempts:
            attempt += 1
            endpoint = None
            session: requests.Session
            proxies: dict[str, str] | None = None

            if self.proxies is not None and self.proxies.enabled:
                try:
                    endpoint = self.proxies.acquire()
                except ProxyExhaustedError as exc:
                    if self.proxies.fail_closed:
                        # Falling back to the local IP here would leak the real
                        # address to the target -- the one thing the pool exists
                        # to prevent -- so this stops instead.
                        raise
                    log.warning("proxy pool exhausted; continuing direct: %s", exc)
                    session, proxies = self._direct(), None
                else:
                    session = self.proxies.session_for(endpoint)
                    proxies = endpoint.as_requests_proxies()
            else:
                if self.proxies is not None and self.proxies.fail_closed and self.proxies.endpoints:
                    raise ProxyExhaustedError("Proxying is disabled but fail_closed is set.")
                session, proxies = self._direct(), None

            headers = {}
            if referer:
                from .user_agents import headers_for

                headers = headers_for(endpoint.label if endpoint else None, referer=referer)

            started = time.perf_counter()
            try:
                response = session.get(
                    url,
                    proxies=proxies,
                    timeout=self.timeout,
                    headers=headers or None,
                    allow_redirects=True,
                    stream=True,
                )
                # Cap the read so a hostile or broken response cannot exhaust
                # memory; the interstitial that started all this was 311 KB.
                body = response.raw.read(self.max_bytes, decode_content=True)
                text = body.decode(response.encoding or "utf-8", errors="replace")
                response.close()
            except Exception as exc:
                latency = int((time.perf_counter() - started) * 1000)
                last_error = exc
                error_class = classify_status(None, exc)
                if endpoint:
                    self.proxies.record_failure(endpoint, f"{type(exc).__name__}: {exc}"[:200])
                self.metrics.record_request(
                    ok=False, latency_ms=latency, proxy=endpoint.label if endpoint else None
                )
                if not self.retry.should_retry(error_class, attempt):
                    break
                time.sleep(self.retry.delay_for(error_class, attempt))
                continue

            latency = int((time.perf_counter() - started) * 1000)
            status = response.status_code

            hits = None
            if expect_selector and status == 200:
                hits = _count(text, expect_selector)
            verdict = blocks.classify(status, text, expect_selector_hits=hits)

            if status == 200 and not verdict.blocked:
                if endpoint:
                    self.proxies.record_success(endpoint, latency)
                self.metrics.record_request(
                    ok=True, latency_ms=latency, proxy=endpoint.label if endpoint else None
                )
                if allow_cache and self.cache is not None and verdict.cacheable:
                    self.cache.put(url, text, ttl=cache_ttl)
                return FetchResult(
                    url=url,
                    status_code=status,
                    text=text,
                    proxy=endpoint.label if endpoint else None,
                    latency_ms=latency,
                    attempts=attempt,
                    verdict=verdict,
                    final_url=str(response.url),
                )

            # Failure, hard or soft.
            reason = verdict.reason or f"HTTP {status}"
            if endpoint:
                self.proxies.record_failure(endpoint, reason, blocked=verdict.blocked)
            self.metrics.record_request(
                ok=False,
                latency_ms=latency,
                proxy=endpoint.label if endpoint else None,
                blocked=verdict.blocked,
            )

            error_class = (
                NetErrorClass.ROTATE
                if verdict.kind is blocks.BlockKind.SOFT
                else classify_status(status)
            )
            last_error = BlockedError(reason, kind=str(verdict.kind), status=status)

            if not self.retry.should_retry(error_class, attempt):
                if error_class is NetErrorClass.FATAL:
                    return FetchResult(
                        url=url,
                        status_code=status,
                        text=text,
                        proxy=endpoint.label if endpoint else None,
                        latency_ms=latency,
                        attempts=attempt,
                        verdict=verdict,
                    )
                break

            retry_after = _retry_after(response)
            delay = self.retry.delay_for(error_class, attempt, retry_after)
            log.info(
                "%s on attempt %d (%s); retrying in %.1fs",
                reason,
                attempt,
                endpoint.label if endpoint else "direct",
                delay,
            )
            time.sleep(delay)

        message = f"Giving up on {url} after {attempt} attempts: {last_error}"
        log.warning(message)
        raise (
            BlockedError(message) if isinstance(last_error, BlockedError) else BlockedError(message)
        )

    # ------------------------------------------------------------- support

    def _direct(self) -> requests.Session:
        if self._direct_session is None:
            from .user_agents import DEFAULT_PROFILE

            self._direct_session = requests.Session()
            self._direct_session.headers.update(DEFAULT_PROFILE.as_dict())
        return self._direct_session


def _count(html: str, selector: str) -> int:
    from bs4 import BeautifulSoup

    try:
        return len(BeautifulSoup(html, "lxml").select(selector))
    except Exception:  # pragma: no cover - a parse failure is not a block
        return 0


def _retry_after(response: Any) -> float | None:
    raw = response.headers.get("Retry-After") if hasattr(response, "headers") else None
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
