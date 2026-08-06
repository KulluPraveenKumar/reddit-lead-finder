"""Proxy pool: rotation, health, blacklisting, per-proxy pacing.

Reddit-agnostic by construction — nothing here knows what a subreddit is. Phase 4
reuses it for website crawling, which only works if that stays true.

Design points worth stating, because each has a cheaper wrong version:

* **Per-proxy pacing, not global.** A global delay wastes the pool: ten proxies
  paced together behave like one. Each endpoint carries its own next-allowed
  time, so ten proxies really are ten times the throughput.
* **A session per proxy.** One shared ``requests.Session`` means one cookie jar
  presented from ten exit IPs — a stronger fingerprint than a single IP would be.
* **Blacklist is per-run, not persistent.** A proxy blocked this hour is usually
  fine tomorrow; persisting the blacklist would shrink the pool permanently for
  a transient cause.
* **Least-recently-used selection, not random.** Random revisits the same proxy
  by chance and wastes the spacing that pacing just bought.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field

import requests

from .proxy_models import ProxyEndpoint, ProxyState, parse_proxy_file
from .retry import ProxyExhaustedError
from .user_agents import headers_for

log = logging.getLogger(__name__)

#: Echoes the caller's IP. Used to prove the exit IP is the proxy's, not ours.
#: Deliberately NOT Reddit: health-checking against the target is the fastest
#: way to get the whole pool flagged.
IP_ECHO_URL = "https://api.ipify.org?format=json"


@dataclass
class ProxyStats:
    requests: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    blocked_responses: int = 0
    total_latency_ms: int = 0
    last_used_at: float = 0.0
    next_allowed_at: float = 0.0
    last_error: str | None = None
    exit_ip: str | None = None
    state: ProxyState = ProxyState.UNTESTED
    blacklisted_at: float | None = None

    @property
    def mean_latency_ms(self) -> int:
        successes = self.requests - self.failures
        return int(self.total_latency_ms / successes) if successes > 0 else 0

    @property
    def failure_rate(self) -> float:
        return self.failures / self.requests if self.requests else 0.0


@dataclass
class PoolSnapshot:
    total: int
    healthy: int
    degraded: int
    blacklisted: int
    untested: int
    circuit_open: bool
    proxies: list[dict] = field(default_factory=list)


class ProxyManager:
    def __init__(
        self,
        endpoints: list[ProxyEndpoint] | None = None,
        *,
        proxy_file: str | None = None,
        delay_range: tuple[float, float] = (3.0, 7.0),
        blacklist_threshold: int = 3,
        blacklist_cooldown: float = 900.0,
        fail_closed: bool = True,
        enabled: bool = True,
    ):
        if endpoints is None and proxy_file:
            endpoints = parse_proxy_file(proxy_file)
        self.endpoints: list[ProxyEndpoint] = list(endpoints or [])
        self.delay_range = delay_range
        self.blacklist_threshold = blacklist_threshold
        self.blacklist_cooldown = blacklist_cooldown
        # With no healthy proxy: stop (True) or fall back to the local IP
        # (False). Defaults to True because a silent fallback would leak the
        # real IP to the target, which is the one outcome the pool exists to
        # prevent.
        self.fail_closed = fail_closed
        self.enabled = enabled and bool(self.endpoints)

        self._stats: dict[str, ProxyStats] = {e.label: ProxyStats() for e in self.endpoints}
        self._sessions: dict[str, requests.Session] = {}
        self._lock = threading.RLock()
        self._cursor = 0

    # ------------------------------------------------------------- sessions

    def session_for(self, endpoint: ProxyEndpoint) -> requests.Session:
        """One session, and therefore one cookie jar, per proxy."""
        with self._lock:
            session = self._sessions.get(endpoint.label)
            if session is None:
                session = requests.Session()
                session.headers.update(headers_for(endpoint.label))
                self._sessions[endpoint.label] = session
            return session

    def stats_for(self, endpoint: ProxyEndpoint) -> ProxyStats:
        return self._stats.setdefault(endpoint.label, ProxyStats())

    # ------------------------------------------------------------ selection

    def _usable(self, now: float) -> list[ProxyEndpoint]:
        usable = []
        for endpoint in self.endpoints:
            stats = self.stats_for(endpoint)
            if stats.state is ProxyState.BLACKLISTED:
                if (
                    stats.blacklisted_at
                    and now - stats.blacklisted_at >= self.blacklist_cooldown
                ):
                    log.info("proxy %s cooldown elapsed; returning to rotation", endpoint.label)
                    stats.state = ProxyState.DEGRADED
                    stats.consecutive_failures = 0
                    stats.blacklisted_at = None
                else:
                    continue
            usable.append(endpoint)
        return usable

    def acquire(self, *, wait: bool = True, timeout: float = 60.0) -> ProxyEndpoint:
        """Return the least-recently-used proxy that is ready, respecting pacing."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                usable = self._usable(now)
                if not usable:
                    raise ProxyExhaustedError(
                        f"All {len(self.endpoints)} proxies are blacklisted. "
                        "Check /health/proxies; they return to rotation after the cooldown."
                    )

                ready = [e for e in usable if self.stats_for(e).next_allowed_at <= now]
                if ready:
                    chosen = min(ready, key=lambda e: self.stats_for(e).last_used_at)
                    stats = self.stats_for(chosen)
                    stats.last_used_at = now
                    stats.next_allowed_at = now + random.uniform(*self.delay_range)
                    return chosen

                soonest = min(self.stats_for(e).next_allowed_at for e in usable)
                sleep_for = max(0.0, soonest - now)

            if not wait:
                raise ProxyExhaustedError("No proxy is ready and waiting was disabled.")
            if time.monotonic() + sleep_for > deadline:
                raise ProxyExhaustedError(
                    f"No proxy became ready within {timeout:.0f}s."
                )
            time.sleep(min(sleep_for, 1.0))

    # ------------------------------------------------------------ reporting

    def record_success(self, endpoint: ProxyEndpoint, latency_ms: int) -> None:
        with self._lock:
            stats = self.stats_for(endpoint)
            stats.requests += 1
            stats.consecutive_failures = 0
            stats.total_latency_ms += latency_ms
            stats.state = ProxyState.HEALTHY
            stats.last_error = None

    def record_failure(
        self, endpoint: ProxyEndpoint, error: str, *, blocked: bool = False
    ) -> None:
        with self._lock:
            stats = self.stats_for(endpoint)
            stats.requests += 1
            stats.failures += 1
            stats.consecutive_failures += 1
            stats.last_error = error[:300]
            if blocked:
                stats.blocked_responses += 1

            if stats.consecutive_failures >= self.blacklist_threshold:
                stats.state = ProxyState.BLACKLISTED
                stats.blacklisted_at = time.monotonic()
                log.warning(
                    "proxy %s blacklisted after %d consecutive failures (%s)",
                    endpoint.label,
                    stats.consecutive_failures,
                    error[:80],
                )
            else:
                stats.state = ProxyState.DEGRADED

    # --------------------------------------------------------------- health

    def health_check(self, endpoint: ProxyEndpoint, timeout: float = 15.0) -> bool:
        """Confirm the proxy works *and* that traffic actually exits through it.

        The exit-IP comparison is the part that matters. A misconfigured proxy
        that silently passes traffic through unchanged still returns 200 to a
        plain reachability check, and the run would then hit Reddit from the
        real IP believing it was protected.
        """
        try:
            response = requests.get(
                IP_ECHO_URL,
                proxies=endpoint.as_requests_proxies(),
                timeout=timeout,
                headers=headers_for(endpoint.label),
            )
            response.raise_for_status()
            exit_ip = (response.json() or {}).get("ip", "")
        except Exception as exc:
            self.record_failure(endpoint, f"health check failed: {type(exc).__name__}")
            return False

        with self._lock:
            stats = self.stats_for(endpoint)
            stats.exit_ip = exit_ip

        if exit_ip and exit_ip != endpoint.host:
            # Not necessarily wrong -- some providers egress from a different
            # address than the one you connect to -- so it is a warning, not a
            # failure. What would be fatal is matching our *own* IP, which
            # local_ip_leaked() checks explicitly.
            log.info(
                "proxy %s reports exit IP %s (differs from its endpoint host)",
                endpoint.label,
                exit_ip,
            )

        self.record_success(endpoint, 0)
        return True

    def local_ip_leaked(self, local_ip: str) -> list[str]:
        """Proxies whose exit IP equals ours. Any hit means the pool is a lie."""
        with self._lock:
            return [
                label
                for label, stats in self._stats.items()
                if stats.exit_ip and stats.exit_ip == local_ip
            ]

    def check_all(self, max_workers: int = 5) -> PoolSnapshot:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            list(pool.map(self.health_check, self.endpoints))
        return self.snapshot()

    def direct_ip(self, timeout: float = 10.0) -> str | None:
        """This machine's address as the internet sees it, fetched *without* a proxy.

        Deliberately unproxied -- it is the reference value the exit IPs are
        compared against, so routing it through the pool would compare the pool
        with itself and never detect a leak.
        """
        try:
            response = requests.get(IP_ECHO_URL, timeout=timeout)
            response.raise_for_status()
            return (response.json() or {}).get("ip") or None
        except Exception as exc:
            log.info("could not determine local egress IP: %s", exc)
            return None

    def health_check_all(self, max_workers: int = 5) -> dict:
        """Check every proxy and report reachability plus any IP leak.

        The local IP is resolved once, before the proxied checks, and reused for
        every comparison.
        """
        local_ip = self.direct_ip()
        self.check_all(max_workers=max_workers)

        reachable = sum(
            1
            for endpoint in self.endpoints
            if self.stats_for(endpoint).state is not ProxyState.BLACKLISTED
            and self.stats_for(endpoint).exit_ip
        )
        return {
            "checked": len(self.endpoints),
            "reachable": reachable,
            "local_ip_known": local_ip is not None,
            # Labels (host:port), never credentials.
            "leaking": self.local_ip_leaked(local_ip) if local_ip else [],
        }

    # -------------------------------------------------------------- circuit

    @property
    def healthy_count(self) -> int:
        with self._lock:
            return sum(
                1
                for e in self.endpoints
                if self.stats_for(e).state in (ProxyState.HEALTHY, ProxyState.UNTESTED)
            )

    @property
    def circuit_open(self) -> bool:
        """True when nothing usable remains — the pool-level breaker."""
        with self._lock:
            return not self._usable(time.monotonic())

    def snapshot(self) -> PoolSnapshot:
        with self._lock:
            rows = []
            counts = dict.fromkeys(ProxyState, 0)
            for endpoint in self.endpoints:
                stats = self.stats_for(endpoint)
                counts[stats.state] += 1
                rows.append(
                    {
                        # label only: never a credential, on any path.
                        "proxy": endpoint.label,
                        "state": str(stats.state),
                        "exit_ip": stats.exit_ip,
                        "requests": stats.requests,
                        "failures": stats.failures,
                        "failure_rate": round(stats.failure_rate, 4),
                        "blocked_responses": stats.blocked_responses,
                        "consecutive_failures": stats.consecutive_failures,
                        "mean_latency_ms": stats.mean_latency_ms,
                        "last_error": stats.last_error,
                    }
                )
            return PoolSnapshot(
                total=len(self.endpoints),
                healthy=counts[ProxyState.HEALTHY],
                degraded=counts[ProxyState.DEGRADED],
                blacklisted=counts[ProxyState.BLACKLISTED],
                untested=counts[ProxyState.UNTESTED],
                circuit_open=self.circuit_open,
                proxies=rows,
            )

    def reset(self) -> None:
        with self._lock:
            for stats in self._stats.values():
                stats.state = ProxyState.UNTESTED
                stats.consecutive_failures = 0
                stats.blacklisted_at = None
                stats.last_error = None


def build_from_settings(settings) -> ProxyManager:
    """Construct from configuration, tolerating an absent proxy file."""
    proxy_file = settings.get("proxy.file", None) or settings.get_secret("PROXY_FILE")
    enabled = bool(settings.get("proxy.enabled", True))

    endpoints: list[ProxyEndpoint] = []
    if proxy_file:
        try:
            endpoints = parse_proxy_file(proxy_file)
        except Exception as exc:
            log.warning("could not load proxy file: %s", exc)
            endpoints = []

    return ProxyManager(
        endpoints,
        delay_range=(
            float(settings.get("proxy.delay_min", 3.0)),
            float(settings.get("proxy.delay_max", 7.0)),
        ),
        blacklist_threshold=int(settings.get("proxy.blacklist_threshold", 3)),
        blacklist_cooldown=float(settings.get("proxy.blacklist_cooldown", 900.0)),
        fail_closed=bool(settings.get("proxy.fail_closed", True)),
        enabled=enabled,
    )
