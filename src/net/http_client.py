"""ProxiedHTTPClient — every outbound request goes through here.

Reddit-agnostic. Phase 13's website fetcher reuses it unchanged, which is the
test of whether the abstraction is real.

The loop, in order, because the order is the design:

    cache lookup               hit? return, no network
      -> policy.acquire        egress chosen by REQUEST CLASS, not globally
      -> request through it
      -> classify status       403/429/5xx/timeout
      -> classify BODY         a 200 can still be a block
      -> policy.release        outcome, latency, bytes -- always, including failure
      -> success: cache
      -> failure: retry through a DIFFERENT exit, enforced

**Body classification is the step that is easy to omit and expensive to omit.**
A target can answer with HTTP 200 and an interstitial; treating that as success
caches a block and reports "nothing found". Which signatures mean "interstitial"
is the *caller's* knowledge, not this layer's -- see ``block_signatures``.

**Retries use a different exit, and it is enforced.** Every label tried is added
to ``tried`` and passed as ``exclude`` on the next acquire. ``docs/29`` §4.2:
retrying the same failing IP is the classic rotating-proxy bug and must not
depend on an ordering side effect.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from . import blocks
from .metrics import NetMetrics
from .policy import DEFAULT_REQUEST_CLASS, EgressExhausted, NetworkPolicy, build_legacy_policy
from .providers import Lease, Outcome
from .proxy_manager import ProxyManager
from .retry import BlockedError, NetErrorClass, RetryPolicy
from .retry import classify as classify_status
from .user_agents import headers_for_profile

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
    #: Which provider served it. ``proxy`` stays the exit label so every
    #: pre-P4 reader of this field keeps working.
    provider: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and not self.verdict.blocked


class ProxiedHTTPClient:
    def __init__(
        self,
        egress: NetworkPolicy | ProxyManager | None = None,
        *,
        cache=None,
        metrics: NetMetrics | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout: tuple[float, float] = (10.0, 30.0),
        max_bytes: int = 5_000_000,
        block_signatures: blocks.BlockSignatures | None = None,
    ):
        # A bare ProxyManager is wrapped rather than handled separately: two
        # request loops would drift, and the pre-P4 arrangement is expressible
        # as a policy exactly (proxy first, stop or degrade per fail_closed).
        if isinstance(egress, NetworkPolicy):
            self.policy = egress
        else:
            self.policy = build_legacy_policy(egress)

        self.cache = cache
        self.metrics = metrics or NetMetrics()
        self.retry = retry_policy or RetryPolicy()
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.block_signatures = block_signatures or blocks.DEFAULT_SIGNATURES

    @property
    def proxies(self) -> ProxyManager | None:
        """The datacenter pool, when one is configured.

        Retained because ``/health/proxies`` and several tests reach for it. It
        is a view onto the policy, not a second source of truth.
        """
        return self.policy.pool

    # ---------------------------------------------------------------- fetch

    def get(
        self,
        url: str,
        *,
        expect_selector: str | None = None,
        cache_ttl: int | None = None,
        referer: str | None = None,
        allow_cache: bool = True,
        request_class: str = DEFAULT_REQUEST_CLASS,
        session_key: str | None = None,
    ) -> FetchResult:
        """Fetch ``url``, choosing egress by ``request_class`` and detecting blocks.

        ``expect_selector`` is a CSS selector the response should match. It is
        what lets a 200-with-no-content be distinguished from a 200 that simply
        has nothing to show.

        ``request_class`` selects the egress policy (``docs/29`` §2.1). It
        defaults to ``html`` -- the proxy-preferred bulk class -- so a caller
        that does not care keeps the behaviour it had before P4.
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
        tried: set[str] = set()

        while attempt < self.retry.max_attempts:
            attempt += 1

            try:
                lease = self.policy.acquire(
                    request_class, session_key=session_key, exclude=tried or None
                )
            except EgressExhausted:
                if attempt == 1:
                    # Nothing could carry the request at all. That is a network
                    # configuration fact, not a fact about this URL, so it is
                    # raised rather than reported as a failed fetch -- which is
                    # what `fail_closed` has always done.
                    raise
                # Every exit the ladder can reach has already been tried for
                # *this* URL. `exclude` is enforced rather than emergent, so
                # there is nothing left to try; retrying a known-failing exit is
                # the bug it exists to prevent. Fall through to the give-up path
                # so the caller sees why the target refused us, not merely that
                # the pool ran out.
                attempt -= 1
                break
            tried.add(lease.label)

            headers = (
                headers_for_profile(lease.profile, referer=referer)
                if referer and lease.profile is not None
                else None
            )

            started = time.perf_counter()
            try:
                response = lease.session.get(
                    url,
                    proxies=lease.proxies,
                    timeout=self.timeout,
                    headers=headers,
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
                self._release(lease, Outcome.ERROR, None, latency, 0)
                self.metrics.record_request(ok=False, latency_ms=latency, proxy=lease.label)
                if not self.retry.should_retry(error_class, attempt):
                    break
                time.sleep(self.retry.delay_for(error_class, attempt))
                continue

            latency = int((time.perf_counter() - started) * 1000)
            status = response.status_code
            # Decompressed length: `decode_content=True` above means this
            # over-states what a metered vendor bills, which makes it a
            # conservative floor for the bandwidth guard rather than an invoice.
            bytes_in = len(body)

            hits = None
            if expect_selector and status == 200:
                hits = _count(text, expect_selector)
            verdict = blocks.classify(
                status, text, expect_selector_hits=hits, signatures=self.block_signatures
            )

            if status == 200 and not verdict.blocked:
                self._release(lease, Outcome.OK, status, latency, bytes_in)
                self.metrics.record_request(ok=True, latency_ms=latency, proxy=lease.label)
                if allow_cache and self.cache is not None and verdict.cacheable:
                    self.cache.put(url, text, ttl=cache_ttl)
                return FetchResult(
                    url=url,
                    status_code=status,
                    text=text,
                    proxy=lease.label,
                    provider=lease.provider,
                    latency_ms=latency,
                    attempts=attempt,
                    verdict=verdict,
                    final_url=str(response.url),
                )

            # Failure, hard or soft.
            reason = verdict.reason or f"HTTP {status}"
            self._release(
                lease,
                Outcome.BLOCKED if verdict.blocked else Outcome.ERROR,
                status,
                latency,
                bytes_in,
            )
            self.metrics.record_request(
                ok=False, latency_ms=latency, proxy=lease.label, blocked=verdict.blocked
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
                        proxy=lease.label,
                        provider=lease.provider,
                        latency_ms=latency,
                        attempts=attempt,
                        verdict=verdict,
                    )
                break

            retry_after = _retry_after(response)
            delay = self.retry.delay_for(error_class, attempt, retry_after)
            log.info(
                "%s on attempt %d (%s); retrying in %.1fs", reason, attempt, lease.label, delay
            )
            time.sleep(delay)

        message = f"Giving up on {url} after {attempt} attempts: {last_error}"
        log.warning(message)
        raise BlockedError(message)

    # ------------------------------------------------------------- support

    def _release(
        self, lease: Lease, outcome: Outcome, status: int | None, latency_ms: int, bytes_in: int
    ) -> None:
        """Always called, on every path, including the exception path.

        A provider that is told about successes and not failures blacklists
        nothing and reports itself healthy forever.
        """
        self.policy.release(
            lease, outcome=outcome, status=status, latency_ms=float(latency_ms), bytes_in=bytes_in
        )

    def drain_degradations(self):
        """Degradation notices recorded since the last drain. See ``NetworkPolicy``."""
        return self.policy.drain_notices()


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
