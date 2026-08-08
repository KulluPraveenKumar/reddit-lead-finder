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


#: Below this many *target* outcomes, ``acceptance_rate`` is treated as neutral
#: rather than as a measurement. A single early success would otherwise read as
#: 100% and pin the whole pool to one exit, destroying the spread that LRU
#: selection exists to provide.
ACCEPTANCE_MIN_SAMPLES = 5

#: A blacklist cooldown never shrinks below this, however much pool pressure
#: scales it down. **Without a floor the mechanism defeats itself:** at zero
#: healthy proxies the scaling factor is zero, every blacklisted proxy returns
#: to rotation instantly, ``_usable()`` is never empty, and therefore
#: ``ProxyExhaustedError`` can never be raised and the circuit can never open --
#: which would silently disable the entire degradation ladder P4 exists to build.
COOLDOWN_FLOOR_SECONDS = 60.0


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
    #: Outcomes against the *real target*, not the health endpoint. A proxy can
    #: answer ipify with 200 and be soft-blocked by the target; only these two
    #: counters can tell the difference (``docs/29`` §4.1).
    target_ok: int = 0
    target_blocked: int = 0

    @property
    def mean_latency_ms(self) -> int:
        successes = self.requests - self.failures
        return int(self.total_latency_ms / successes) if successes > 0 else 0

    @property
    def failure_rate(self) -> float:
        return self.failures / self.requests if self.requests else 0.0

    @property
    def target_samples(self) -> int:
        return self.target_ok + self.target_blocked

    @property
    def acceptance_rate(self) -> float | None:
        """``ok / (ok + blocked)`` against the target, or ``None`` if unknown.

        ``None`` rather than ``0.0`` when there is no evidence: the difference
        between "this exit is rejected" and "nobody has tried yet" is the whole
        value of the signal, and zero would conflate them.
        """
        total = self.target_samples
        return self.target_ok / total if total else None

    @property
    def acceptance_is_measured(self) -> bool:
        return self.target_samples >= ACCEPTANCE_MIN_SAMPLES


#: Pool-wide target outcomes needed before acceptance may open the circuit. A
#: floor breached on three samples is noise; the breaker exists to catch a
#: systemic refusal, not a bad minute.
POOL_ACCEPTANCE_MIN_SAMPLES = 10

#: Pool-wide acceptance below this opens the circuit *before* every proxy has
#: been individually blacklisted (``docs/29`` §4.1). Conservative on purpose: it
#: is a second, earlier trigger, not a replacement for the first.
POOL_ACCEPTANCE_FLOOR = 0.2


@dataclass
class PoolSnapshot:
    total: int
    healthy: int
    degraded: int
    blacklisted: int
    untested: int
    circuit_open: bool
    acceptance_rate: float | None = None
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
        blacklist_cooldown_floor: float = COOLDOWN_FLOOR_SECONDS,
        fail_closed: bool = True,
        enabled: bool = True,
    ):
        if endpoints is None and proxy_file:
            endpoints = parse_proxy_file(proxy_file)
        self.endpoints: list[ProxyEndpoint] = list(endpoints or [])
        self.delay_range = delay_range
        self.blacklist_threshold = blacklist_threshold
        self.blacklist_cooldown = blacklist_cooldown
        self.blacklist_cooldown_floor = blacklist_cooldown_floor
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

    def effective_cooldown(self) -> float:
        """Blacklist cooldown, scaled down by pool pressure but never to zero.

        ``docs/29`` §4.3: a blacklist is a guess about whether the target will
        accept this IP again, and when almost nothing is being accepted, waiting
        longer buys no information. At 2 of 10 healthy a 900 s cooldown becomes
        180 s.

        **The floor is not a rounding detail.** The formula alone reaches zero at
        zero healthy proxies, which would return every blacklisted proxy to
        rotation instantly and make pool exhaustion unobservable -- see
        :data:`COOLDOWN_FLOOR_SECONDS`.
        """
        pool_size = len(self.endpoints)
        if not pool_size:
            return self.blacklist_cooldown
        pressure = self.healthy_count / pool_size
        return max(self.blacklist_cooldown * pressure, self.blacklist_cooldown_floor)

    def _usable(self, now: float) -> list[ProxyEndpoint]:
        cooldown = self.effective_cooldown()
        usable = []
        for endpoint in self.endpoints:
            stats = self.stats_for(endpoint)
            if stats.state is ProxyState.BLACKLISTED:
                if stats.blacklisted_at and now - stats.blacklisted_at >= cooldown:
                    log.info("proxy %s cooldown elapsed; returning to rotation", endpoint.label)
                    stats.state = ProxyState.DEGRADED
                    stats.consecutive_failures = 0
                    stats.blacklisted_at = None
                else:
                    continue
            usable.append(endpoint)
        return usable

    def _selection_key(self, endpoint: ProxyEndpoint) -> tuple[float, float]:
        """Order: highest measured acceptance first, then least-recently-used.

        Acceptance only participates once there is enough evidence to call it a
        measurement (:data:`ACCEPTANCE_MIN_SAMPLES`). Below that every proxy
        scores identically and the ordering collapses to the shipped LRU, which
        is what keeps the pool spread while it is still warming up.
        """
        stats = self.stats_for(endpoint)
        rank = -stats.acceptance_rate if stats.acceptance_is_measured else 0.0
        return (rank, stats.last_used_at)

    def acquire(
        self,
        *,
        wait: bool = True,
        timeout: float = 60.0,
        exclude: set[str] | None = None,
        session_key: str | None = None,
    ) -> ProxyEndpoint:
        """Return the best available proxy that is ready, respecting pacing.

        ``exclude`` is the set of labels already tried for this request, and it
        is **enforced rather than emergent** (``docs/29`` §4.2). LRU ordering
        happens to return a different proxy most of the time; retrying the same
        failing exit is the classic rotating-proxy bug and must not depend on a
        side effect of the ordering.

        ``session_key`` is accepted and ignored: this pool rotates per request
        and pins nothing, which ``docs/12`` §14 records as a deliberate P2
        decision. It is in the signature so every provider's ``acquire`` reads
        the same, and :attr:`WebshareDatacenterProvider.supports_sticky` reports
        ``False`` so no caller is misled.
        """
        excluded = exclude or set()
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

                candidates = [e for e in usable if e.label not in excluded]
                if not candidates:
                    raise ProxyExhaustedError(
                        f"All {len(usable)} usable proxies have already been tried for this "
                        "request. Retrying one of them would repeat a known failure."
                    )

                ready = [e for e in candidates if self.stats_for(e).next_allowed_at <= now]
                if ready:
                    chosen = min(ready, key=self._selection_key)
                    stats = self.stats_for(chosen)
                    stats.last_used_at = now
                    stats.next_allowed_at = now + random.uniform(*self.delay_range)
                    return chosen

                soonest = min(self.stats_for(e).next_allowed_at for e in candidates)
                sleep_for = max(0.0, soonest - now)

            if not wait:
                raise ProxyExhaustedError("No proxy is ready and waiting was disabled.")
            if time.monotonic() + sleep_for > deadline:
                raise ProxyExhaustedError(f"No proxy became ready within {timeout:.0f}s.")
            time.sleep(min(sleep_for, 1.0))

    # ------------------------------------------------------------ reporting

    def record_success(
        self, endpoint: ProxyEndpoint, latency_ms: int, *, target: bool = True
    ) -> None:
        """``target=False`` for the synthetic health probe.

        The probe hits ``api.ipify.org``, not the site being scraped, so counting
        it as target acceptance would report a proxy as *accepted* on the
        strength of a request the target never saw -- which is precisely the
        blind spot ``docs/29`` §4.1 adds this signal to close.
        """
        with self._lock:
            stats = self.stats_for(endpoint)
            stats.requests += 1
            stats.consecutive_failures = 0
            stats.total_latency_ms += latency_ms
            stats.state = ProxyState.HEALTHY
            stats.last_error = None
            if target:
                stats.target_ok += 1

    def record_failure(
        self,
        endpoint: ProxyEndpoint,
        error: str,
        *,
        blocked: bool = False,
        target: bool = True,
    ) -> None:
        with self._lock:
            stats = self.stats_for(endpoint)
            stats.requests += 1
            stats.failures += 1
            stats.consecutive_failures += 1
            stats.last_error = error[:300]
            if blocked:
                stats.blocked_responses += 1
                if target:
                    # Only a refusal by the target counts against acceptance. A
                    # timeout or a connection reset says the transport failed,
                    # not that this exit is unwelcome.
                    stats.target_blocked += 1

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
            self.record_failure(
                endpoint, f"health check failed: {type(exc).__name__}", target=False
            )
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

        self.record_success(endpoint, 0, target=False)
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
    def usable_count(self) -> int:
        """Proxies that could be selected right now, cooldowns applied."""
        with self._lock:
            return len(self._usable(time.monotonic()))

    @property
    def acceptance_rate(self) -> float | None:
        """Pool-wide target acceptance, or ``None`` before there is evidence."""
        with self._lock:
            ok = sum(stats.target_ok for stats in self._stats.values())
            blocked = sum(stats.target_blocked for stats in self._stats.values())
            total = ok + blocked
            return ok / total if total else None

    @property
    def acceptance_collapsed(self) -> bool:
        """Is the *whole pool* being refused by the target?

        The second circuit trigger from ``docs/29`` §4.1. Individual
        blacklisting is a lagging indicator -- it needs three consecutive
        failures per proxy, so a ten-proxy pool spends thirty requests learning
        what this knows after ten.
        """
        with self._lock:
            ok = sum(stats.target_ok for stats in self._stats.values())
            blocked = sum(stats.target_blocked for stats in self._stats.values())
            total = ok + blocked
            if total < POOL_ACCEPTANCE_MIN_SAMPLES:
                return False
            return (ok / total) < POOL_ACCEPTANCE_FLOOR

    @property
    def circuit_open(self) -> bool:
        """True when nothing usable remains, or when the target refuses the pool.

        Two triggers, and the second is new in P4. The first is exhaustion; the
        second is a pool that is reachable, unblacklisted, and being refused
        anyway -- the state 8 of 10 proxies were in during P2's measured run,
        which the health page reported as fine right up to the moment the retry
        ladder blacklisted them.
        """
        with self._lock:
            return not self._usable(time.monotonic()) or self.acceptance_collapsed

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
                        # Reachability and acceptance are reported side by side
                        # on purpose: a proxy that is up and refused looks
                        # identical to a healthy one on every other column.
                        "target_ok": stats.target_ok,
                        "target_blocked": stats.target_blocked,
                        "acceptance_rate": (
                            round(stats.acceptance_rate, 4)
                            if stats.acceptance_rate is not None
                            else None
                        ),
                    }
                )
            pool_acceptance = self.acceptance_rate
            return PoolSnapshot(
                total=len(self.endpoints),
                healthy=counts[ProxyState.HEALTHY],
                degraded=counts[ProxyState.DEGRADED],
                blacklisted=counts[ProxyState.BLACKLISTED],
                untested=counts[ProxyState.UNTESTED],
                circuit_open=self.circuit_open,
                acceptance_rate=(
                    round(pool_acceptance, 4) if pool_acceptance is not None else None
                ),
                proxies=rows,
            )

    def reset(self) -> None:
        with self._lock:
            for stats in self._stats.values():
                stats.state = ProxyState.UNTESTED
                stats.consecutive_failures = 0
                stats.blacklisted_at = None
                stats.last_error = None
                # Acceptance is cleared too: it is evidence about how the target
                # is treating this exit *now*, and a reset says that evidence is
                # stale. Keeping it would let a pre-reset collapse hold the
                # circuit open against fresh, contradicting traffic.
                stats.target_ok = 0
                stats.target_blocked = 0


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
        blacklist_cooldown_floor=float(
            settings.get("proxy.blacklist_cooldown_floor", COOLDOWN_FLOOR_SECONDS)
        ),
        fail_closed=bool(settings.get("proxy.fail_closed", True)),
        enabled=enabled,
    )
