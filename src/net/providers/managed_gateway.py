"""``ManagedProxyProvider`` — one generic gateway, every managed vendor.

Configured as ``type: managed_gateway``. **This class is the design's main
economy** (``docs/29`` §3.1): Decodo, IPRoyal, NetNut, SOAX, Oxylabs, Bright Data
and Webshare's residential product all expose a *single* gateway host where
rotation, geo and session pinning are encoded in the **username**, not in the
address:

    user-session-abc123:password@gateway.vendor.com:7000

So one class plus a per-vendor config block covers the entire market, and
switching vendor is four lines of YAML -- ``gateway``, ``username``,
``password``, ``session_param`` -- with no Python change. A per-vendor class per
vendor would be six classes that differ by a format string.

**Sticky sessions are real here**, unlike the datacenter list: ``session_param``
renders a caller's ``session_key`` into the username, and the vendor keeps that
identity on one exit. This is what a cursor walk needs. Nothing in P4 passes a
``session_key`` -- the first caller is P5/P6 -- but the mechanism is the
vendor's, not ours, so it ships with the provider that owns it.

**Bandwidth is a budgeted resource.** These vendors bill per GB, and one that
silently runs out mid-run looks exactly like a network outage. ``capacity()``
reports what is left and ``health()`` turns unhealthy below
``bandwidth_floor_gb``, so the policy degrades to the next rung *before* the
vendor starts refusing.
"""

from __future__ import annotations

import threading
from typing import Any
from urllib.parse import quote

import requests

from ..user_agents import HeaderProfile, pick_profile
from .base import (
    Capacity,
    Lease,
    NetworkProvider,
    Outcome,
    ProviderHealth,
    ProviderUnavailable,
    Rotation,
)

_GB = 1024**3


class ManagedProxyProvider(NetworkProvider):
    type = "managed_gateway"
    exposes_origin_ip = False
    is_metered = True
    supports_sticky = True
    rotation = Rotation.STICKY_SESSION

    def __init__(
        self,
        name: str,
        *,
        gateway: str,
        username: str,
        password: str,
        session_param: str = "",
        metered: bool = True,
        bandwidth_budget_gb: float | None = None,
        bandwidth_floor_gb: float = 0.0,
        enabled: bool = True,
    ):
        super().__init__(name)
        self.gateway = gateway
        self._username = username
        self._password = password
        self.session_param = session_param
        self.metered = metered
        self.bandwidth_budget_gb = bandwidth_budget_gb
        self.bandwidth_floor_gb = bandwidth_floor_gb
        self.enabled = enabled

        self._lock = threading.RLock()
        self._bytes_used = 0
        self._sessions: dict[str, requests.Session] = {}
        self._ok = 0
        self._blocked = 0

    @classmethod
    def from_config(cls, name: str, spec: dict[str, Any]) -> ManagedProxyProvider:
        from .registry import ProviderConfigError

        gateway = str(spec.get("gateway") or "").strip()
        if not gateway:
            raise ProviderConfigError(
                f"provider {name!r} (managed_gateway) needs a 'gateway' as host:port"
            )
        if ":" not in gateway:
            raise ProviderConfigError(
                f"provider {name!r}: gateway {gateway!r} needs a port, e.g. 'gateway.vendor.com:7000'"
            )

        username = spec.get("username")
        password = spec.get("password")
        if not username or not password:
            # A ${VAR} that resolved to nothing lands here, which is the common
            # case: the block is right and the environment variable is missing.
            raise ProviderConfigError(
                f"provider {name!r} (managed_gateway) needs a username and password. "
                "Set them via ${ENV_VAR} references -- config.yaml is committed and must "
                "never contain a credential."
            )

        return cls(
            name,
            gateway=gateway,
            username=str(username),
            password=str(password),
            session_param=str(spec.get("session_param") or ""),
            metered=bool(spec.get("metered", True)),
            bandwidth_budget_gb=(
                float(spec["bandwidth_budget_gb"])
                if spec.get("bandwidth_budget_gb") is not None
                else None
            ),
            bandwidth_floor_gb=float(spec.get("bandwidth_floor_gb", 0.0)),
            enabled=bool(spec.get("enabled", True)),
        )

    # ------------------------------------------------------------- identity

    def username_for(self, session_key: str | None) -> str:
        """The vendor username, with a sticky suffix when one is asked for.

        ``session_param`` is a vendor-specific template such as
        ``-session-{key}``. Rendering it here rather than in the policy is what
        keeps every vendor difference inside one class.
        """
        if not session_key or not self.session_param:
            return self._username
        return self._username + self.session_param.format(key=session_key)

    def _proxy_url(self, session_key: str | None) -> str:
        user = quote(self.username_for(session_key), safe="")
        password = quote(self._password, safe="")
        # http:// for both schemes: HTTPS tunnels via CONNECT over an HTTP
        # proxy. An https:// proxy URL means TLS *to the proxy*, which is the
        # single most common misconfiguration with these vendors.
        return f"http://{user}:{password}@{self.gateway}"

    def profile_for(self, session_key: str | None) -> HeaderProfile:
        """One profile per sticky identity, pinned for its lifetime."""
        return pick_profile(f"{self.name}:{session_key or ''}")

    def session(self, session_key: str | None) -> requests.Session:
        """One session per sticky identity, so cookie jars do not cross exits."""
        key = session_key or ""
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = requests.Session()
                session.headers.update(self.profile_for(session_key).as_dict())
                self._sessions[key] = session
            return session

    # ----------------------------------------------------------------- lease

    @property
    def bytes_used(self) -> int:
        with self._lock:
            return self._bytes_used

    @property
    def gb_remaining(self) -> float | None:
        if self.bandwidth_budget_gb is None:
            return None
        return max(0.0, self.bandwidth_budget_gb - self.bytes_used / _GB)

    def acquire(self, *, session_key: str | None = None, exclude: set[str] | None = None) -> Lease:
        if not self.enabled:
            raise ProviderUnavailable(f"provider {self.name!r} is disabled")

        health = self.health()
        if not health.healthy:
            raise ProviderUnavailable(f"provider {self.name!r}: {health.reason}")

        label = self.label_for(session_key)
        if exclude and label in exclude:
            # A gateway rotates per request, so a fresh call normally yields a
            # different exit -- but a *sticky* lease deliberately does not. When
            # the caller has already tried this identity, honour the exclusion
            # rather than handing back the same exit and calling it a retry.
            raise ProviderUnavailable(
                f"provider {self.name!r}: session {label!r} has already been tried"
            )

        return Lease(
            provider=self.name,
            label=label,
            session=self.session(session_key),
            proxies={
                "http": self._proxy_url(session_key),
                "https": self._proxy_url(session_key),
            },
            profile=self.profile_for(session_key),
            session_key=session_key,
            handle=session_key,
        )

    def label_for(self, session_key: str | None) -> str:
        """The safe identifier. Gateway host and session name only, no credential."""
        if session_key and self.session_param:
            return f"{self.gateway}#{session_key}"
        return self.gateway

    def release(
        self,
        lease: Lease,
        *,
        outcome: Outcome,
        status: int | None = None,
        latency_ms: float = 0.0,
        bytes_in: int = 0,
    ) -> None:
        with self._lock:
            # Counted on every outcome: a blocked response still transferred
            # bytes the vendor bills for. Counting only successes would let a
            # run of blocks exhaust a plan while the counter reported plenty
            # left.
            self._bytes_used += max(0, bytes_in)
            if outcome is Outcome.OK:
                self._ok += 1
            elif outcome is Outcome.BLOCKED:
                self._blocked += 1

    # ---------------------------------------------------------------- health

    def health(self) -> ProviderHealth:
        if not self.enabled:
            return ProviderHealth(False, "disabled")

        remaining = self.gb_remaining
        if self.metered and remaining is not None and remaining <= self.bandwidth_floor_gb:
            return ProviderHealth(
                False,
                f"bandwidth floor reached ({remaining:.3f} GB left, "
                f"floor {self.bandwidth_floor_gb:.3f} GB)",
                {"gb_remaining": round(remaining, 4)},
            )
        return ProviderHealth(True, "", {"gb_remaining": remaining})

    def capacity(self) -> Capacity:
        remaining = self.gb_remaining
        return Capacity(
            usable_exits=1 if self.enabled else 0,
            bytes_remaining=remaining * _GB if remaining is not None else None,
        )

    def describe(self) -> dict[str, Any]:
        payload = super().describe()
        with self._lock:
            ok, blocked = self._ok, self._blocked
        total = ok + blocked
        payload.update(
            {
                # Gateway host only. The username carries the credential and the
                # session identity, and it never appears here.
                "gateway": self.gateway,
                "gb_used": round(self.bytes_used / _GB, 4),
                "gb_budget": self.bandwidth_budget_gb,
                "acceptance_rate": round(ok / total, 4) if total else None,
            }
        )
        return payload
