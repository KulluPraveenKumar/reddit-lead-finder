"""Regressions for three bugs found only by running against a live provider.

None of these were visible under `FakeProvider`: they need a real reasoning
model, a real gateway, and a real bill.
"""

from __future__ import annotations

import json

import pytest

from src.ai.providers import ChatMessage, ChatRequest, FakeProvider, ScriptedResponse
from src.ai.providers.openrouter import OpenRouterProvider


def _service(settings, provider):
    from src.ai.service import AIService

    service = AIService(settings, provider=provider)
    service.credentials.set_key("sk-test0123456789abcdef", validate=False)
    return service


# ------------------------------------------------- reasoning-token exhaustion


def test_reasoning_tokens_are_parsed():
    """A reasoning model can spend its whole output budget before emitting text."""
    import responses

    with responses.RequestsMock() as mock:
        mock.add(
            responses.POST,
            "https://openrouter.ai/api/v1/chat/completions",
            json={
                "model": "deepseek/deepseek-v4-flash",
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {
                    "prompt_tokens": 2000,
                    "completion_tokens": 31,
                    "completion_tokens_details": {"reasoning_tokens": 30},
                    "cost": 0.00029,
                },
            },
            status=200,
        )
        result = OpenRouterProvider("sk-x").chat(
            ChatRequest(messages=[ChatMessage("user", "hi")], model="m", max_tokens=30)
        )

    assert result.reasoning_tokens == 30
    assert result.content == ""
    assert result.truncated


def test_budget_starvation_escalates_instead_of_burning_repairs(settings):
    """The fix cannot be a reworded prompt; only a bigger budget helps.

    Sending this down the repair ladder wastes two attempts and real money on a
    fault no rewording can address.
    """
    calls: list[int] = []

    def handler(request):
        calls.append(request.max_tokens)
        if len(calls) == 1:
            # All budget consumed by reasoning; nothing left for content.
            return ScriptedResponse(
                content="", output_tokens=request.max_tokens, finish_reason="length"
            )
        return ScriptedResponse(
            content=json.dumps({"results": [{"id": "item-1", "is_lead": True}]}),
            output_tokens=200,
        )

    provider = FakeProvider(handler=handler)
    # FakeProvider does not model reasoning tokens; finish_reason='length' is
    # the signal the service keys on.
    service = _service(settings, provider)

    result = service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    assert result.results[0].id == "item-1"
    assert len(calls) == 2
    assert calls[1] == calls[0] * 2, "the retry must raise the output budget"
    # Crucially: this consumed no repair-ladder attempts.
    assert service.metrics.repairs == 0
    assert service.metrics.truncated >= 1


def test_escalation_is_bounded(settings):
    """A pathological response must not double its way to a large bill."""
    from src.ai.errors import EmptyContentError
    from src.ai.service import MAX_OUTPUT_CEILING

    seen: list[int] = []

    def handler(request):
        seen.append(request.max_tokens)
        return ScriptedResponse(content="", output_tokens=request.max_tokens, finish_reason="length")

    service = _service(settings, FakeProvider(handler=handler))

    with pytest.raises(EmptyContentError):
        service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    assert max(seen) <= MAX_OUTPUT_CEILING


# --------------------------------------------------------- provider-reported cost


def test_reported_cost_wins_over_local_computation(settings):
    """A gateway applies discounts the token counts do not reveal.

    Measured 2026-07-31: two OpenRouter calls with a byte-identical prefix both
    reported `cached_tokens: 0` while the prompt cost fell 34%. Computing
    locally would overstate the bill on exactly the calls we care about.
    """
    payload = {"results": [{"id": "item-1", "is_lead": True}]}
    provider = FakeProvider(
        handler=lambda _r: ScriptedResponse(content=json.dumps(payload), output_tokens=100)
    )
    service = _service(settings, provider)

    local = service.cost.cost_of(0, 1000, 100)
    service.cost.record(cached=0, uncached=1000, out=100, reported=local / 3)

    assert service.cost.run_spend.cost_usd == pytest.approx(local / 3)
    assert service.cost.run_spend.cost_usd < local


def test_cost_falls_back_to_local_when_unreported(settings):
    service = _service(settings, FakeProvider())
    expected = service.cost.cost_of(0, 1000, 100)
    service.cost.record(cached=0, uncached=1000, out=100, reported=None)
    assert service.cost.run_spend.cost_usd == pytest.approx(expected)


def test_openrouter_reports_its_own_cost():
    provider = OpenRouterProvider("sk-x")
    assert provider._reported_cost({"cost": 0.00123}) == pytest.approx(0.00123)
    assert provider._reported_cost({}) is None


def test_openrouter_parses_openai_shaped_cache_split():
    """Reading DeepSeek's field names here would report 0% cache forever."""
    provider = OpenRouterProvider("sk-x")
    cached, uncached, out = provider._parse_usage(
        {
            "prompt_tokens": 2000,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 1500},
        }
    )
    assert (cached, uncached, out) == (1500, 500, 50)


# ------------------------------------------------------------- one row per call


def test_one_ai_calls_row_per_provider_call(settings, temp_db, enrichment_payload):
    """Two rows per call would inflate calls-per-1,000-posts by the repair rate."""
    from src.db.database import get_session
    from src.db.models import AICall

    bad = {"results": [{"id": "item-1", "buying_intent": "definitely"}]}
    provider = FakeProvider.bad_schema_then_ok(bad, enrichment_payload)
    service = _service(settings, provider)
    service.enrich_batch(items=[{"id": "item-1"}], business_context="ctx")

    session = get_session()
    try:
        rows = session.query(AICall).all()
    finally:
        session.close()

    assert len(provider.calls) == 2
    assert len(rows) == 2, "one row per provider call, not one per event"
    assert {r.outcome for r in rows} == {"schema_error", "ok"}
    # The failed attempt was billed and must be recorded as such.
    assert all(r.cost_usd > 0 for r in rows)
