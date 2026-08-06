"""Provider routing: primary, fallback chain, circuit breaker.

The rule the research is unanimous on, and which this module exists to enforce:
**the application must not branch on provider names.** Callers ask the router
for "a provider that can serve this call" and get one. Adding a provider is a
registry entry, never a conditional.

Failover is deliberately conservative. It fires on faults that a *different*
provider could plausibly fix — timeouts, 5xx, connection errors — and never on
credential, billing, or content faults, which would reproduce everywhere. A
router that failed over on a 401 would burn every configured key in sequence
against the same bad request.

Two things it deliberately does not do:

* **No load balancing.** Spreading traffic across providers would destroy prefix
  cache locality, which is the largest cost lever in the system. The fallback
  chain is for *failure*, not for spreading load.
* **No cross-provider result mixing within a batch.** A batch that half-fails is
  retried whole on the fallback, because two providers' judgements are not
  calibrated against each other and mixing them would make the confidence score
  incomparable between leads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .base import LLMProvider
from .health import HealthRegistry, ProviderHealth, trips_breaker

log = logging.getLogger(__name__)


class NoProviderAvailableError(Exception):
    """Every candidate is unconfigured or circuit-open."""


@dataclass
class RouteAttempt:
    provider: str
    ok: bool
    error: str | None = None
    latency_ms: int = 0


class ProviderRouter:
    """Chooses a provider and records what happened.

    Constructed with a *primary* and an ordered fallback list. Only providers
    with a configured key are considered: an unconfigured fallback is not a
    fallback, and discovering that mid-incident is the worst possible time.
    """

    def __init__(
        self,
        settings,
        *,
        primary: str,
        fallbacks: list[str] | None = None,
        health: HealthRegistry | None = None,
        credential_factory=None,
    ):
        self.settings = settings
        self.primary = primary
        self.fallbacks = list(fallbacks or [])
        self.health = health or HealthRegistry()
        self._credential_factory = credential_factory
        self._providers: dict[str, LLMProvider] = {}
        self.attempts: list[RouteAttempt] = []

    # ------------------------------------------------------------- discovery

    def _credentials(self, name: str):
        if self._credential_factory is not None:
            return self._credential_factory(name)
        from ..credentials import CredentialStore

        return CredentialStore(self.settings, name)

    def is_configured(self, name: str) -> bool:
        try:
            return self._credentials(name).has_key()
        except Exception:
            return False

    def build(self, name: str) -> LLMProvider:
        if name not in self._providers:
            from .registry import build_provider

            key = self._credentials(name).get_key()
            model = self.settings.get(f"ai.models.{name}", None) or self.settings.get(
                "ai.model", None
            )
            self._providers[name] = build_provider(name, key, model=model)
        return self._providers[name]

    def invalidate(self, name: str | None = None) -> None:
        """Drop cached providers so the next call picks up a new key or model."""
        if name is None:
            self._providers.clear()
        else:
            self._providers.pop(name, None)

    # --------------------------------------------------------------- routing

    def candidates(self) -> list[str]:
        """Primary first, then fallbacks. Order is intent, not preference."""
        ordered = [self.primary, *[f for f in self.fallbacks if f != self.primary]]
        seen: set[str] = set()
        return [n for n in ordered if not (n in seen or seen.add(n))]

    def available(self) -> list[str]:
        """Configured *and* not circuit-open."""
        return [
            name
            for name in self.candidates()
            if self.is_configured(name) and self.health.for_provider(name).allows_request()
        ]

    def select(self) -> tuple[str, LLMProvider]:
        """The provider to use right now.

        Raises rather than silently returning the primary when everything is
        open: a caller that gets a provider back is entitled to assume it is
        usable.
        """
        for name in self.candidates():
            if not self.is_configured(name):
                continue
            if not self.health.for_provider(name).allows_request():
                continue
            return name, self.build(name)

        configured = [n for n in self.candidates() if self.is_configured(n)]
        if not configured:
            raise NoProviderAvailableError(
                "No AI provider is configured. Add a key on the Settings page."
            )
        waits = {n: round(self.health.for_provider(n).seconds_until_retry) for n in configured}
        soonest = min(waits.values()) if waits else 0
        raise NoProviderAvailableError(
            f"All configured providers are temporarily unavailable ({', '.join(configured)}). "
            f"Next retry in about {soonest}s."
        )

    def run(self, fn, *, allow_failover: bool = True):
        """Call ``fn(name, provider)``, failing over where that could help.

        ``fn`` must be idempotent: on failover it is called again from scratch.
        Everything routed through here is a stateless completion, so it is.
        """
        self.attempts = []
        errors: list[tuple[str, BaseException]] = []

        for name in self.candidates():
            if not self.is_configured(name):
                continue
            health = self.health.for_provider(name)
            if not health.allows_request():
                log.info("skipping %s: circuit %s", name, health.state)
                continue

            provider = self.build(name)
            try:
                result = fn(name, provider)
            except Exception as exc:
                latency = getattr(exc, "latency_ms", 0) or 0
                health.record_failure(exc, latency)
                self.attempts.append(
                    RouteAttempt(
                        provider=name, ok=False, error=f"{type(exc).__name__}: {exc}"[:200]
                    )
                )
                errors.append((name, exc))

                if not allow_failover or not trips_breaker(exc):
                    # A credential or content fault reproduces everywhere;
                    # trying the next provider wastes time and money.
                    raise
                log.warning("provider %s failed (%s); trying next", name, type(exc).__name__)
                continue

            latency = getattr(result, "latency_ms", 0) or 0
            health.record_success(latency)
            self.attempts.append(RouteAttempt(provider=name, ok=True, latency_ms=latency))
            return name, result

        if errors:
            raise errors[-1][1]
        raise NoProviderAvailableError("No configured provider was available to serve the request.")

    # -------------------------------------------------------------- readouts

    def status(self) -> dict:
        rows = []
        for name in self.candidates():
            health: ProviderHealth = self.health.for_provider(name)
            rows.append(
                {
                    **health.to_dict(),
                    "role": "primary" if name == self.primary else "fallback",
                    "configured": self.is_configured(name),
                }
            )
        return {
            "primary": self.primary,
            "fallbacks": self.fallbacks,
            "providers": rows,
            "available": self.available(),
        }
