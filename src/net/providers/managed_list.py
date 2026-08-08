"""``WebshareDatacenterProvider`` — today's file-based pool, behind the interface.

Configured as ``type: managed_list``: a file of ``ip:port:user:pass`` lines, one
exit per line. Webshare's datacenter product is the one this was built for, but
nothing here is vendor-specific — any vendor shipping a per-IP list works.

**This is an adapter, not a rewrite.** ``ProxyManager`` keeps its own API and its
own tests; this class translates between it and :class:`NetworkProvider`.
``docs/34`` P4 task 2 says "refactor behind the interface — **behaviour
unchanged**", and the cheapest way to mean that literally is to leave the
implementation alone and add a translation layer that is thin enough to read in
one screen.
"""

from __future__ import annotations

import logging
from typing import Any

from ..proxy_manager import ProxyManager
from ..proxy_models import ProxyEndpoint, parse_proxy_file
from ..retry import ProxyExhaustedError
from ..user_agents import pick_profile
from .base import (
    Capacity,
    Lease,
    NetworkProvider,
    Outcome,
    ProviderHealth,
    ProviderUnavailable,
    Rotation,
)

log = logging.getLogger(__name__)


class WebshareDatacenterProvider(NetworkProvider):
    type = "managed_list"
    exposes_origin_ip = False
    is_metered = False
    #: The pool rotates per request and pins nothing. ``docs/12`` §14 records
    #: sticky sessions as deliberately not built in P2, and P4 does not add them
    #: -- so this reports False rather than accepting a ``session_key`` and
    #: quietly ignoring what the caller asked for.
    supports_sticky = False
    rotation = Rotation.PER_REQUEST

    def __init__(self, name: str, manager: ProxyManager):
        super().__init__(name)
        self.manager = manager

    @classmethod
    def from_config(cls, name: str, spec: dict[str, Any]) -> WebshareDatacenterProvider:
        from .registry import ProviderConfigError

        path = spec.get("file")
        endpoints: list[ProxyEndpoint] = []
        if path:
            try:
                endpoints = parse_proxy_file(path)
            except Exception as exc:
                # An absent or unreadable proxy file must not stop the process:
                # the policy simply finds this provider unhealthy and moves down
                # the ladder. This is the same tolerance `build_from_settings`
                # has always had, and it is what keeps a machine with no proxy
                # file able to scrape.
                log.warning("provider %s: proxy file unusable (%s); pool is empty", name, exc)
        elif not spec.get("allow_empty"):
            raise ProviderConfigError(
                f"provider {name!r} (managed_list) needs a 'file'. Point it at a proxy list, "
                "or set PROXY_FILE and use '${PROXY_FILE}'."
            )

        return cls(
            name,
            ProxyManager(
                endpoints,
                delay_range=(
                    float(spec.get("delay_min", 3.0)),
                    float(spec.get("delay_max", 7.0)),
                ),
                blacklist_threshold=int(spec.get("blacklist_threshold", 3)),
                blacklist_cooldown=float(spec.get("blacklist_cooldown", 900.0)),
                # fail_closed belongs to the policy now (`on_pool_exhausted`).
                # A provider reports whether it can serve; what to do about it
                # is one layer up.
                fail_closed=False,
                enabled=bool(spec.get("enabled", True)),
            ),
        )

    # ----------------------------------------------------------------- lease

    def acquire(self, *, session_key: str | None = None, exclude: set[str] | None = None) -> Lease:
        if not self.manager.enabled:
            raise ProviderUnavailable(f"provider {self.name!r} has no proxies configured")
        try:
            endpoint = self.manager.acquire(exclude=exclude, session_key=session_key)
        except ProxyExhaustedError as exc:
            # Re-raised as ProviderUnavailable so the policy can tell "this
            # provider is out" from "the whole request failed". Both are
            # ProxyExhaustedError subclasses, so any pre-P4 handler still works.
            raise ProviderUnavailable(str(exc)) from exc

        return Lease(
            provider=self.name,
            label=endpoint.label,
            session=self.manager.session_for(endpoint),
            proxies=endpoint.as_requests_proxies(),
            # The same seed `session_for` uses, so the lease reports the profile
            # the session actually carries rather than a second, unrelated one.
            profile=pick_profile(endpoint.label),
            session_key=session_key,
            handle=endpoint,
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
        endpoint = lease.handle
        if endpoint is None:  # pragma: no cover - a lease always carries one
            return
        if outcome is Outcome.OK:
            self.manager.record_success(endpoint, int(latency_ms))
        else:
            self.manager.record_failure(
                endpoint,
                f"HTTP {status}" if status else str(outcome),
                blocked=outcome is Outcome.BLOCKED,
            )

    # ---------------------------------------------------------------- health

    def health(self) -> ProviderHealth:
        if not self.manager.enabled:
            return ProviderHealth(False, "no proxies configured")
        if self.manager.circuit_open:
            acceptance = self.manager.acceptance_rate
            if self.manager.acceptance_collapsed and acceptance is not None:
                return ProviderHealth(
                    False,
                    f"target is refusing the pool ({acceptance:.0%} acceptance)",
                    {"acceptance_rate": round(acceptance, 4)},
                )
            return ProviderHealth(False, "every proxy is blacklisted")
        return ProviderHealth(True, "", {"healthy_proxies": self.manager.healthy_count})

    def capacity(self) -> Capacity:
        return Capacity(usable_exits=self.manager.usable_count)

    def describe(self) -> dict[str, Any]:
        payload = super().describe()
        snapshot = self.manager.snapshot()
        payload.update(
            {
                "total": snapshot.total,
                "blacklisted": snapshot.blacklisted,
                "acceptance_rate": snapshot.acceptance_rate,
            }
        )
        return payload
