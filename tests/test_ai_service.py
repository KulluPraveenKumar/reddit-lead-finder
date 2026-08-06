"""AI Service Layer. Entirely offline — every test uses FakeProvider."""

from __future__ import annotations

import json
import threading

import pytest

from src.ai.errors import (
    BudgetExceededError,
    EmptyContentError,
    InsufficientBalanceError,
    InvalidAPIKeyError,
    SchemaValidationError,
)
from src.ai.providers import FakeProvider, ScriptedResponse
from src.ai.schemas import EnrichmentBatchOut


def _only_id(request):
    """The single item id in a rendered enrichment request."""
    import re as _re

    return _re.search(r'"id":\s*"([^"]+)"', request.messages[1].content).group(1)


def _service(settings, provider):
    from src.ai.service import AIService

    service = AIService(settings, provider=provider)
    service.credentials.set_key("sk-test0123456789abcdef", validate=False)
    return service


# ------------------------------------------------------------------ caching


def test_identical_calls_issue_one_request(settings, enrichment_payload):
    """AC11: the second call is a cache hit at $0.00."""
    provider = FakeProvider(default_payload=enrichment_payload)
    service = _service(settings, provider)
    items = [{"id": "item-1", "title": "t", "body": "b"}]

    first = service.enrich_batch(items=items, business_context="ctx")
    second = service.enrich_batch(items=items, business_context="ctx")

    assert len(provider.calls) == 1
    assert first.results[0].id == second.results[0].id
    assert service.metrics.cache_hits == 1


def test_concurrent_identical_calls_collapse(settings, enrichment_payload):
    """AC12: without the in-flight guard, a pool of 8 issues 8 identical calls."""
    import time

    def slow(_request):
        time.sleep(0.05)
        return ScriptedResponse(content=json.dumps(enrichment_payload))

    provider = FakeProvider(handler=slow)
    service = _service(settings, provider)
    items = [{"id": "item-1", "title": "t", "body": "b"}]

    results = []
    errors = []

    def worker():
        try:
            results.append(service.enrich_batch(items=items, business_context="ctx"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 6
    assert len(provider.calls) == 1


# ------------------------------------------------------------------- repair


def test_empty_content_triggers_perturbed_retry(settings, enrichment_payload):
    """AC13, branch 1."""
    provider = FakeProvider.empty_then_ok(enrichment_payload)
    service = _service(settings, provider)

    result = service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    assert result.results[0].id == "item-1"
    assert len(provider.calls) == 2
    assert service.metrics.empty_responses == 1
    # The hint goes in the USER half; mutating the system half would break the
    # prefix cache for every later call.
    assert provider.calls[0].messages[0].content == provider.calls[1].messages[0].content
    assert provider.calls[1].messages[1].content != provider.calls[0].messages[1].content


def test_fenced_json_is_repaired(settings, enrichment_payload):
    """AC13, branch 2 — the commonest JSON-mode slip."""
    provider = FakeProvider.fenced_then_ok(enrichment_payload)
    service = _service(settings, provider)

    result = service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")
    assert result.results[0].id == "item-1"
    # Fence-stripping happens client side, so no retry is needed at all.
    assert len(provider.calls) == 1


def test_schema_violation_triggers_field_error_retry(settings, enrichment_payload):
    """AC13, branch 3."""
    bad = {"results": [{"id": "item-1", "buying_intent": "definitely_buying"}]}
    provider = FakeProvider.bad_schema_then_ok(bad, enrichment_payload)
    service = _service(settings, provider)

    result = service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    assert result.results[0].id == "item-1"
    assert len(provider.calls) == 2
    assert service.metrics.schema_errors == 1
    assert "buying_intent" in provider.calls[1].messages[1].content


def test_repair_gives_up_after_max_attempts(settings):
    provider = FakeProvider(handler=lambda _r: ScriptedResponse(content=""))
    service = _service(settings, provider)

    with pytest.raises(EmptyContentError):
        service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    assert len(provider.calls) == 3  # initial + 2 repair attempts


# ------------------------------------------------------------------- budget


def test_budget_checked_before_the_call(settings, enrichment_payload):
    """AC15: checking after would mean paying for the call that broke the cap."""
    from src.ai.cost import BudgetLimits
    from src.ai.service import AIService

    provider = FakeProvider(default_payload=enrichment_payload)
    service = AIService(settings, provider=provider, limits=BudgetLimits(max_cost_per_run_usd=0.0))
    service.credentials.set_key("sk-test0123456789abcdef", validate=False)

    with pytest.raises(BudgetExceededError):
        service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    assert len(provider.calls) == 0


def test_call_ceiling_is_independent_of_cost(settings, enrichment_payload):
    """Cost and call count diverge; one dial would miss half the failures."""
    from src.ai.cost import BudgetLimits
    from src.ai.service import AIService

    provider = FakeProvider(default_payload=enrichment_payload)
    service = AIService(
        settings,
        provider=provider,
        limits=BudgetLimits(max_cost_per_run_usd=1000.0, max_calls_per_run=1),
    )
    service.credentials.set_key("sk-test0123456789abcdef", validate=False)

    service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")
    with pytest.raises(BudgetExceededError):
        service.enrich_batch(items=[{"id": "item-2"}], business_context="ctx2")


# -------------------------------------------------------------- batch safety


def test_batch_id_mismatch_is_a_failure(settings):
    """A dropped item must not pass as a complete batch."""
    partial = {"results": [{"id": "item-1", "is_lead": False}]}
    provider = FakeProvider(default_payload=partial)
    service = _service(settings, provider)

    with pytest.raises(SchemaValidationError, match="id mismatch"):
        service.enrich_batch(
            items=[{"id": "item-1"}, {"id": "item-2"}], business_context="ctx"
        )


def test_results_are_matched_by_id_not_position(settings):
    """The classic silent-corruption bug: analyses attached to the wrong posts."""
    shuffled = {
        "results": [
            {"id": "item-3", "is_lead": True, "summary": "third"},
            {"id": "item-1", "is_lead": False, "summary": "first"},
            {"id": "item-2", "is_lead": True, "summary": "second"},
        ]
    }
    provider = FakeProvider(default_payload=shuffled)
    service = _service(settings, provider)

    result = service.enrich_batch(
        items=[{"id": "item-1"}, {"id": "item-2"}, {"id": "item-3"}], business_context="ctx"
    )
    by_id = {r.id: r.summary for r in result.results}
    assert by_id == {"item-1": "first", "item-2": "second", "item-3": "third"}


# ------------------------------------------------------------------- errors


def test_401_is_not_retried_and_marks_state(settings):
    provider = FakeProvider(
        handler=lambda _r: ScriptedResponse(
            raises=InvalidAPIKeyError("rejected", status_code=401)
        )
    )
    service = _service(settings, provider)

    with pytest.raises(InvalidAPIKeyError):
        service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    assert len(provider.calls) == 1


def test_402_is_not_retried(settings):
    provider = FakeProvider(
        handler=lambda _r: ScriptedResponse(
            raises=InsufficientBalanceError("no credit", status_code=402)
        )
    )
    service = _service(settings, provider)

    with pytest.raises(InsufficientBalanceError):
        service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    assert len(provider.calls) == 1


def test_rate_limit_is_retried(settings, enrichment_payload):
    provider = FakeProvider.rate_limited_then_ok(enrichment_payload)
    service = _service(settings, provider)

    result = service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")
    assert result.results[0].id == "item-1"
    assert len(provider.calls) == 2


# ------------------------------------------------------------- observability


def test_every_call_is_recorded(settings, enrichment_payload, temp_db):
    """AC16: tokens, cache split, cost, latency, outcome — for every call."""
    from src.db.database import get_session
    from src.db.models import AICall

    provider = FakeProvider(default_payload=enrichment_payload)
    service = _service(settings, provider)
    service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    session = get_session()
    try:
        rows = session.query(AICall).all()
    finally:
        session.close()

    assert len(rows) == 1
    row = rows[0]
    assert row.stage == "lead_enrichment"
    assert row.outcome == "ok"
    assert row.output_tokens > 0
    assert row.cost_usd > 0
    assert row.prefix_hash


def test_prefix_hash_is_stable_across_calls(settings, enrichment_payload):
    """AC14 support: a drifting prefix silently multiplies input cost by ~50x."""
    provider = FakeProvider(default_payload=enrichment_payload)
    service = _service(settings, provider)

    for index in range(3):
        # Distinct business_context so each call is a cache MISS and actually
        # reaches the provider; a cache hit would prove nothing about prefixes.
        service.enrich_batch(items=[{"id": "item-1"}], business_context=f"ctx-{index}")

    assert service.metrics.distinct_prefixes == 1
    assert service.metrics.prefix_stable


def test_disabled_without_key(settings):
    from src.ai.errors import AIDisabledError
    from src.ai.service import AIService

    service = AIService(settings, provider=FakeProvider())
    assert not service.enabled
    with pytest.raises(AIDisabledError):
        service.enrich_batch(items=[{"id": "x"}], business_context="ctx")


def test_output_is_validated_not_trusted(settings):
    """DeepSeek JSON mode guarantees syntax, not schema."""
    payload = {"results": [{"id": "item-1", "opportunity_score": 99}]}
    provider = FakeProvider(default_payload=payload)
    service = _service(settings, provider)

    with pytest.raises(SchemaValidationError):
        service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")


def test_unknown_slugs_are_dropped_not_fatal(settings):
    """One malformed slug should cost one field, not a whole analysis."""
    payload = {
        "results": [
            {"id": "item-1", "is_lead": True, "matched_pain_slugs": ["Valid Slug!", "good-slug"]}
        ]
    }
    result = EnrichmentBatchOut.model_validate(payload)
    assert result.results[0].matched_pain_slugs == ["good-slug"]


def test_daily_spend_is_resumed_after_a_restart(settings, enrichment_payload, temp_db):
    """The daily cap must be per-DAY, not per-process.

    A fresh AIService (as after a restart) must see the spend already recorded
    in `ai_calls` today. Without seeding, restarting the dashboard would clear
    the cap, making it an observation rather than a limit.

    Asserted on the resumed *total* rather than by tripping the cap: a cap small
    enough to trip is also small enough that a single call's pre-flight estimate
    trips it on its own, which would pass whether or not seeding worked.
    """
    from src.ai.service import AIService

    def provider():
        return FakeProvider(
            handler=lambda req: ScriptedResponse(
                content=json.dumps({"results": [dict(enrichment_payload["results"][0], id=_only_id(req))]})
            )
        )

    first = AIService(settings, provider=provider())
    first.credentials.set_key("sk-test0123456789abcdef", validate=False)
    # Distinct ITEMS, not just distinct context: content-hash dedup keys on the
    # items, so reusing them would collapse these into one call.
    for index in range(3):
        first.enrich_batch(items=[{"id": f"item-{index}"}], business_context="ctx")

    spent = first.cost.day_spend().cost_usd
    assert first.cost.day_spend().calls == 3
    assert spent > 0

    second = AIService(settings, provider=provider())
    second.credentials.set_key("sk-test0123456789abcdef", validate=False)
    assert second.cost.day_spend().cost_usd == 0  # nothing loaded yet

    second.enrich_batch(items=[{"id": "item-99"}], business_context="ctx")

    resumed = second.cost.day_spend()
    assert resumed.calls == 4, "the three earlier calls were forgotten"
    assert resumed.cost_usd > spent, "today's spend did not carry across the restart"


def test_daily_cap_counts_spend_from_before_the_restart(settings, enrichment_payload, temp_db):
    """The consequence of the above: the cap actually stops a restarted process."""
    from src.ai.cost import BudgetLimits
    from src.ai.service import AIService

    def provider():
        return FakeProvider(
            handler=lambda req: ScriptedResponse(
                content=json.dumps({"results": [dict(enrichment_payload["results"][0], id=_only_id(req))]})
            )
        )

    first = AIService(settings, provider=provider())
    first.credentials.set_key("sk-test0123456789abcdef", validate=False)
    for index in range(3):
        first.enrich_batch(items=[{"id": f"item-{index}"}], business_context="ctx")
    spent = first.cost.day_spend().cost_usd

    # The cap is placed in the window between "one call's pre-flight estimate"
    # and "that estimate plus today's existing spend". Below the window the test
    # would pass without seeding (the estimate alone trips it); above it, seeding
    # would not be enough. Only a value inside the window tests the thing.
    #
    # The estimate is deliberately conservative — several times the eventual
    # recorded cost — so the window has to be computed, not guessed.
    probe = AIService(settings, provider=provider())
    probe.credentials.set_key("sk-test0123456789abcdef", validate=False)
    one_call = probe.cost.estimate(
        prefix_tokens=1000, item_tokens=60, output_tokens=225, warm=False
    )
    cap = one_call + spent * 0.5
    assert one_call <= cap < one_call + spent, "cap is outside the discriminating window"

    second = AIService(
        settings,
        provider=provider(),
        limits=BudgetLimits(max_cost_per_day_usd=cap),
    )
    second.credentials.set_key("sk-test0123456789abcdef", validate=False)

    with pytest.raises(BudgetExceededError, match="[Dd]aily"):
        second.enrich_batch(items=[{"id": "item-99"}], business_context="ctx")
