"""Provider health, circuit breaking, and failover (Improvement 1)."""

from __future__ import annotations

import pytest

from src.ai.errors import (
    InsufficientBalanceError,
    InvalidAPIKeyError,
    ProviderBadRequestError,
    ProviderServerError,
    ProviderUnreachableError,
    RateLimitedError,
)
from src.ai.providers import FakeProvider, ScriptedResponse
from src.ai.providers.health import CircuitState, HealthRegistry, ProviderHealth, trips_breaker
from src.ai.providers.router import NoProviderAvailableError, ProviderRouter

# ------------------------------------------------------- what trips a breaker


@pytest.mark.parametrize(
    ("error", "should_trip"),
    [
        (ProviderUnreachableError("timeout"), True),
        (ProviderServerError("502", status_code=502), True),
        (RateLimitedError("429", status_code=429), True),
        # These reproduce on ANY provider. Tripping on them would take a
        # healthy provider offline for a fault it does not have.
        (InvalidAPIKeyError("401", status_code=401), False),
        (InsufficientBalanceError("402", status_code=402), False),
        (ProviderBadRequestError("400", status_code=400), False),
    ],
)
def test_only_transport_faults_trip_the_breaker(error, should_trip):
    assert trips_breaker(error) is should_trip


# ------------------------------------------------------------ state machine


def test_circuit_opens_after_threshold_failures():
    health = ProviderHealth("p", failure_threshold=3)
    for _ in range(2):
        health.record_failure(ProviderUnreachableError("down"))
    assert health.state is CircuitState.CLOSED
    assert health.allows_request()

    health.record_failure(ProviderUnreachableError("down"))
    assert health.state is CircuitState.OPEN
    assert not health.allows_request()


def test_credential_failures_never_open_the_circuit():
    health = ProviderHealth("p", failure_threshold=2)
    for _ in range(10):
        health.record_failure(InvalidAPIKeyError("401", status_code=401))
    assert health.state is CircuitState.CLOSED
    assert health.allows_request()
    # Still counted, because an operator needs to see it.
    assert health.total_failures == 10


def test_circuit_probes_after_cooldown_then_closes():
    health = ProviderHealth("p", failure_threshold=1, cooldown_seconds=0.0, recovery_successes=2)
    health.record_failure(ProviderServerError("500", status_code=500))
    assert health.state is CircuitState.OPEN

    assert health.allows_request()  # cooldown elapsed -> probe
    assert health.state is CircuitState.HALF_OPEN

    health.record_success(50)
    assert health.state is CircuitState.HALF_OPEN, "one probe is not enough"
    health.record_success(50)
    assert health.state is CircuitState.CLOSED


def test_a_failed_probe_reopens_immediately():
    health = ProviderHealth("p", failure_threshold=1, cooldown_seconds=0.0)
    health.record_failure(ProviderServerError("500", status_code=500))
    health.allows_request()
    assert health.state is CircuitState.HALF_OPEN

    health.record_failure(ProviderServerError("500", status_code=500))
    assert health.state is CircuitState.OPEN


def test_success_resets_the_failure_run():
    health = ProviderHealth("p", failure_threshold=3)
    health.record_failure(ProviderUnreachableError("x"))
    health.record_failure(ProviderUnreachableError("x"))
    health.record_success(10)
    health.record_failure(ProviderUnreachableError("x"))
    assert health.state is CircuitState.CLOSED, "failures must be consecutive to trip"


def test_health_reports_latency_percentiles():
    health = ProviderHealth("p")
    for ms in range(1, 101):
        health.record_success(ms)
    assert health.mean_latency_ms == 50
    assert 90 <= health.p95_latency_ms <= 100


# ---------------------------------------------------------------- the router


def _router(settings, *, primary, fallbacks, configured):
    class _Creds:
        def __init__(self, name):
            self.name = name

        def has_key(self):
            return self.name in configured

        def get_key(self):
            return "sk-key" if self.name in configured else None

    return ProviderRouter(
        settings,
        primary=primary,
        fallbacks=fallbacks,
        health=HealthRegistry(failure_threshold=1, cooldown_seconds=0.0),
        credential_factory=_Creds,
    )


def test_router_prefers_the_primary(settings):
    router = _router(settings, primary="a", fallbacks=["b"], configured={"a", "b"})
    router._providers = {"a": FakeProvider(), "b": FakeProvider()}
    name, _ = router.run(lambda n, p: ScriptedResponse(content="{}"))
    assert name == "a"


def test_router_skips_an_unconfigured_primary(settings):
    """An unconfigured fallback is not a fallback."""
    router = _router(settings, primary="a", fallbacks=["b"], configured={"b"})
    router._providers = {"b": FakeProvider()}
    name, _ = router.run(lambda n, p: ScriptedResponse(content="{}"))
    assert name == "b"


def test_router_fails_over_on_a_transport_fault(settings):
    router = _router(settings, primary="a", fallbacks=["b"], configured={"a", "b"})
    router._providers = {"a": FakeProvider(), "b": FakeProvider()}

    def fn(name, provider):
        if name == "a":
            raise ProviderUnreachableError("a is down")
        return ScriptedResponse(content="{}")

    name, _ = router.run(fn)
    assert name == "b"
    assert [a.provider for a in router.attempts] == ["a", "b"]


def test_router_does_not_fail_over_on_a_credential_fault(settings):
    """A 401 would reproduce on every provider; failing over burns every key."""
    router = _router(settings, primary="a", fallbacks=["b"], configured={"a", "b"})
    router._providers = {"a": FakeProvider(), "b": FakeProvider()}
    tried: list[str] = []

    def fn(name, provider):
        tried.append(name)
        raise InvalidAPIKeyError("bad key", status_code=401)

    with pytest.raises(InvalidAPIKeyError):
        router.run(fn)
    assert tried == ["a"], "must not try the fallback"


def test_router_skips_an_open_circuit(settings):
    router = _router(settings, primary="a", fallbacks=["b"], configured={"a", "b"})
    router._providers = {"a": FakeProvider(), "b": FakeProvider()}
    health = router.health.for_provider("a")
    health.cooldown_seconds = 999
    health.record_failure(ProviderServerError("down", status_code=500))
    assert health.state is CircuitState.OPEN

    name, _ = router.run(lambda n, p: ScriptedResponse(content="{}"))
    assert name == "b"


def test_router_raises_a_useful_error_when_nothing_is_configured(settings):
    router = _router(settings, primary="a", fallbacks=["b"], configured=set())
    with pytest.raises(NoProviderAvailableError, match="No AI provider is configured"):
        router.select()


def test_router_status_lists_roles_and_health(settings):
    router = _router(settings, primary="a", fallbacks=["b"], configured={"a"})
    status = router.status()
    assert status["primary"] == "a"
    roles = {row["provider"]: row["role"] for row in status["providers"]}
    assert roles == {"a": "primary", "b": "fallback"}
    configured = {row["provider"]: row["configured"] for row in status["providers"]}
    assert configured == {"a": True, "b": False}


# ----------------------------------------------------------- service wiring


def test_service_records_provider_health(settings, enrichment_payload):
    from src.ai.service import AIService

    provider = FakeProvider(default_payload=enrichment_payload)
    service = AIService(settings, provider=provider)
    service.credentials.set_key("sk-test0123456789abcdef", validate=False)
    service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    health = service.health.for_provider(service.provider_name)
    assert health.total_calls == 1
    assert health.total_failures == 0
    assert health.state is CircuitState.CLOSED


def test_service_health_ignores_faults_a_retry_fixed(settings, enrichment_payload):
    """A transient blip the retry policy absorbed is not evidence of ill health."""
    from src.ai.service import AIService

    provider = FakeProvider.server_error_then_ok(enrichment_payload)
    service = AIService(settings, provider=provider)
    service.credentials.set_key("sk-test0123456789abcdef", validate=False)
    service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    health = service.health.for_provider(service.provider_name)
    assert health.total_failures == 0
    assert health.state is CircuitState.CLOSED


def test_provider_comparison_prices_the_same_workload(settings):
    from src.ai.service import AIService

    service = AIService(settings, provider=FakeProvider())
    rows = service.provider_comparison(items=1000)

    by_name = {r["provider"]: r for r in rows}
    assert "deepseek" in by_name and "openrouter" in by_name
    # Same uncached price, 10x cached: the differential must reflect that.
    assert by_name["deepseek"]["cache_differential"] == 50.0
    assert by_name["openrouter"]["cache_differential"] == 5.0
    # Warm must beat cold everywhere, or the cache is not worth engineering for.
    for row in rows:
        assert row["warm_cache_usd"] < row["cold_cache_usd"]
        assert row["pricing_verified_on"]
