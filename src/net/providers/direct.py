"""``DirectProvider`` — the operator's own connection, governed.

Configured as ``type: direct``. **The only provider with
``exposes_origin_ip = True``**, which is the flag the policy reads to know that
requests through it are attributable to the operator.

Two properties define it.

**A pinned, coherent header profile.** Measured twice, six days apart, on
different addresses: a hand-assembled header set gets HTTP 403 from
``old.reddit.com`` on every request, from the local IP *and* from all ten
proxies; the shipped coherent profile returns 200 on the same path seconds later
(``docs/PHASE-02-STATUS`` §3.1, ``docs/SPRINT-0-MEASUREMENTS`` §1.5). The block
was a fingerprint problem, not an address problem. So this provider takes a
**whole** :class:`HeaderProfile` and never assembles one field at a time --
mixing a UA from one profile with an Accept-Language from another reproduces the
outage exactly, and it looks like an IP ban.

**An hourly governor.** ``docs/29`` §2.2's answer to the objection that a
fallback to the operator's own IP is *unbounded and silent*: the fallback is
capped at ``network.direct.max_requests_per_hour`` (120, a frozen budget) and
reaching the cap is reported rather than absorbed. A capped, visible fallback is
a different thing from the uncapped one ``docs/08`` §7 rejected.

The governor counts in a **rolling one-hour window** rather than resetting on the
clock hour, because a fixed reset lets 240 requests through in two minutes either
side of the boundary.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

import requests

from ..user_agents import DEFAULT_PROFILE, HeaderProfile
from .base import (
    Capacity,
    Lease,
    NetworkProvider,
    Outcome,
    ProviderHealth,
    ProviderUnavailable,
    Rotation,
)

#: ARCHITECTURE_FREEZE §6. Steady-state collection is measured at ≤80 requests a
#: *day*, so this is roughly 36× headroom -- it is a guard against a runaway
#: loop, not a throttle on normal operation.
DEFAULT_MAX_REQUESTS_PER_HOUR = 120

_WINDOW_SECONDS = 3600.0


class DirectProvider(NetworkProvider):
    type = "direct"
    exposes_origin_ip = True
    is_metered = False
    supports_sticky = False
    rotation = Rotation.NONE

    def __init__(
        self,
        name: str = "direct",
        *,
        max_requests_per_hour: int = DEFAULT_MAX_REQUESTS_PER_HOUR,
        profile: HeaderProfile | None = None,
        enabled: bool = True,
    ):
        super().__init__(name)
        self.max_requests_per_hour = max_requests_per_hour
        self.profile = profile or DEFAULT_PROFILE
        self.enabled = enabled
        self._lock = threading.RLock()
        self._window: deque[float] = deque()
        self._session: requests.Session | None = None

    @classmethod
    def from_config(cls, name: str, spec: dict[str, Any]) -> DirectProvider:
        return cls(
            name,
            max_requests_per_hour=int(
                spec.get("max_requests_per_hour", DEFAULT_MAX_REQUESTS_PER_HOUR)
            ),
            enabled=bool(spec.get("enabled", True)),
        )

    # -------------------------------------------------------------- governor

    def _prune(self, now: float) -> None:
        while self._window and now - self._window[0] >= _WINDOW_SECONDS:
            self._window.popleft()

    @property
    def requests_this_hour(self) -> int:
        with self._lock:
            self._prune(time.monotonic())
            return len(self._window)

    @property
    def remaining_this_hour(self) -> int:
        return max(0, self.max_requests_per_hour - self.requests_this_hour)

    # ----------------------------------------------------------------- lease

    def session(self) -> requests.Session:
        """One session for the life of the process: one cookie jar, one identity.

        A new session per request would present a fresh, empty cookie jar from
        the same address every time, which is a *more* remarkable pattern than a
        consistent one.
        """
        with self._lock:
            if self._session is None:
                self._session = requests.Session()
                # The whole profile, atomically. See the module docstring.
                self._session.headers.update(self.profile.as_dict())
            return self._session

    def acquire(self, *, session_key: str | None = None, exclude: set[str] | None = None) -> Lease:
        if not self.enabled:
            raise ProviderUnavailable(f"provider {self.name!r} is disabled")
        if exclude and self.name in exclude:
            # There is exactly one exit here -- our own address -- so an
            # exclusion naming it leaves nothing to try. Retrying it would be
            # the same bug `exclude` exists to prevent, one provider along.
            raise ProviderUnavailable(
                f"provider {self.name!r} has one exit and it has already been tried"
            )

        with self._lock:
            now = time.monotonic()
            self._prune(now)
            if len(self._window) >= self.max_requests_per_hour:
                raise ProviderUnavailable(
                    f"direct-connection hourly limit reached "
                    f"({len(self._window)} of {self.max_requests_per_hour}). "
                    "This cap bounds how much traffic can reach the target from this machine's "
                    "own address; it resets as the oldest requests age out of the hour."
                )
            self._window.append(now)

        return Lease(
            provider=self.name,
            label=self.name,
            session=self.session(),
            proxies=None,
            profile=self.profile,
            session_key=session_key,
            handle=None,
        )

    def release(
        self,
        lease: Lease,
        *,
        outcome: Outcome,
        status: int | None = None,
        latency_ms: float = 0.0,
        bytes_in: int = 0,
    ) -> None:
        # The governor counts requests *issued*, not requests that succeeded:
        # a blocked request reached the target from this address just as much as
        # a successful one did, and it is exposure that is being bounded.
        return None

    # ---------------------------------------------------------------- health

    def health(self) -> ProviderHealth:
        if not self.enabled:
            return ProviderHealth(False, "disabled")
        used = self.requests_this_hour
        if used >= self.max_requests_per_hour:
            return ProviderHealth(
                False,
                f"hourly limit reached ({used} of {self.max_requests_per_hour})",
                {"requests_this_hour": used, "max_requests_per_hour": self.max_requests_per_hour},
            )
        return ProviderHealth(
            True,
            "",
            {"requests_this_hour": used, "max_requests_per_hour": self.max_requests_per_hour},
        )

    def capacity(self) -> Capacity:
        return Capacity(
            usable_exits=1 if self.enabled else 0,
            requests_per_minute=self.max_requests_per_hour / 60.0,
        )

    def describe(self) -> dict[str, Any]:
        payload = super().describe()
        payload.update(
            {
                "requests_this_hour": self.requests_this_hour,
                "max_requests_per_hour": self.max_requests_per_hour,
                "header_profile": self.profile.name,
            }
        )
        return payload
