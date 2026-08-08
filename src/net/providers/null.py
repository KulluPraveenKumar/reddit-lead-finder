"""``NullProvider`` — the provider that proves a code path made no network call.

Configured as ``type: null_provider``. It is not a stub and not a placeholder:
it has exactly one behaviour, and that behaviour is the assertion. Give a test
(or a request class you want to prove is never fetched) a ``NullProvider`` and
any attempt to reach the network raises with a message naming what tried.

``null_provider`` rather than ``null`` because YAML parses a bare ``null`` as
``None``, so ``type: null`` would arrive as ``None`` and be reported as a
missing key rather than as this provider.
"""

from __future__ import annotations

from typing import Any

from .base import Capacity, Lease, NetworkProvider, Outcome, ProviderHealth, ProviderUnavailable


class NullProvider(NetworkProvider):
    type = "null_provider"
    exposes_origin_ip = False
    is_metered = False

    @classmethod
    def from_config(cls, name: str, spec: dict[str, Any]) -> NullProvider:
        return cls(name)

    def acquire(self, *, session_key: str | None = None, exclude: set[str] | None = None) -> Lease:
        raise ProviderUnavailable(
            f"provider {self.name!r} is a null provider: this code path must make no "
            "network call, and something tried to."
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
        # Unreachable in practice -- acquire() always raises -- but a provider
        # that raised here instead would turn a caller's cleanup path into a
        # second, confusing failure.
        return None

    def health(self) -> ProviderHealth:
        return ProviderHealth(False, "null provider: never serves a request")

    def capacity(self) -> Capacity:
        return Capacity(usable_exits=0)
