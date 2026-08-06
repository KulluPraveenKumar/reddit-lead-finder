"""HTTP error classification, the concurrency pool, the gate, and credentials.

The HTTP tests use ``responses`` to mock the transport: they exercise the real
request-building and error-classification code without a network call.
"""

from __future__ import annotations

import json

import pytest
import requests
import responses

from src.ai.concurrency import ConcurrencyPool, RateLimiter, RetryPolicy, chunked, run_with_retry
from src.ai.errors import (
    BudgetExceededError,
    InsufficientBalanceError,
    InvalidAPIKeyError,
    ProviderBadRequestError,
    ProviderServerError,
    ProviderUnreachableError,
    RateLimitedError,
)
from src.ai.providers import ChatMessage, ChatRequest
from src.ai.providers.deepseek import DeepSeekProvider

CHAT_URL = "https://api.deepseek.com/v1/chat/completions"


def _request():
    return ChatRequest(
        messages=[ChatMessage("system", "s"), ChatMessage("user", "u")],
        model="deepseek-v4-flash",
        max_tokens=100,
    )


def _ok_body(content='{"ok": true}', **usage):
    body = {
        "model": "deepseek-v4-flash",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, **usage},
    }
    return body


# ------------------------------------------------------- error classification


@responses.activate
def test_401_maps_to_invalid_key():
    responses.add(responses.POST, CHAT_URL, json={"error": "bad key"}, status=401)
    with pytest.raises(InvalidAPIKeyError) as exc:
        DeepSeekProvider("sk-x").chat(_request())
    assert not exc.value.retryable
    assert "copied completely" in exc.value.message


@responses.activate
def test_402_maps_to_insufficient_balance():
    responses.add(responses.POST, CHAT_URL, json={"error": "no credit"}, status=402)
    with pytest.raises(InsufficientBalanceError) as exc:
        DeepSeekProvider("sk-x").chat(_request())
    assert not exc.value.retryable
    assert "credit" in exc.value.message.lower()


@responses.activate
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, RateLimitedError),
        (500, ProviderServerError),
        (503, ProviderServerError),
        (400, ProviderBadRequestError),
        (422, ProviderBadRequestError),
    ],
)
def test_status_classification(status, expected):
    responses.add(responses.POST, CHAT_URL, json={}, status=status)
    with pytest.raises(expected):
        DeepSeekProvider("sk-x").chat(_request())


@responses.activate
@pytest.mark.parametrize(
    "raised",
    [
        requests.exceptions.ConnectionError("refused"),
        # A bare builtin, which `requests` does not always wrap. Unclassified it
        # would escape the retry policy entirely.
        ConnectionError("boom"),
        requests.exceptions.Timeout("slow"),
    ],
)
def test_transport_failures_are_unreachable(raised):
    responses.add(responses.POST, CHAT_URL, body=raised)
    with pytest.raises(ProviderUnreachableError) as exc:
        DeepSeekProvider("sk-x").chat(_request())
    assert exc.value.retryable


@responses.activate
def test_missing_key_never_reaches_the_network():
    from src.ai.errors import ProviderNotConfiguredError

    with pytest.raises(ProviderNotConfiguredError):
        DeepSeekProvider(None).chat(_request())
    assert len(responses.calls) == 0


# -------------------------------------------------------------- wire format


@responses.activate
def test_json_mode_is_requested():
    responses.add(responses.POST, CHAT_URL, json=_ok_body(), status=200)
    DeepSeekProvider("sk-x").chat(_request())
    sent = json.loads(responses.calls[0].request.body)
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["temperature"] == 0.0  # deterministic, and therefore cacheable


@responses.activate
def test_cache_split_is_parsed():
    """The two are priced ~50x apart, so the split cannot be collapsed."""
    responses.add(
        responses.POST,
        CHAT_URL,
        json=_ok_body(prompt_cache_hit_tokens=3000, prompt_cache_miss_tokens=200),
        status=200,
    )
    result = DeepSeekProvider("sk-x").chat(_request())
    assert result.input_tokens_cached == 3000
    assert result.input_tokens_uncached == 200
    assert result.cache_hit_ratio == pytest.approx(3000 / 3200)


@responses.activate
def test_missing_cache_fields_are_pessimistic():
    """A missing field may overstate cost; it must never hide a cache failure."""
    responses.add(responses.POST, CHAT_URL, json=_ok_body(), status=200)
    result = DeepSeekProvider("sk-x").chat(_request())
    assert result.input_tokens_cached == 0
    assert result.input_tokens_uncached == 100


@responses.activate
def test_truncation_is_surfaced():
    """A truncated response is invalid JSON that no retry can repair."""
    body = _ok_body(content='{"partial": ')
    body["choices"][0]["finish_reason"] = "length"
    responses.add(responses.POST, CHAT_URL, json=body, status=200)
    assert DeepSeekProvider("sk-x").chat(_request()).truncated


@responses.activate
def test_empty_choices_is_not_an_exception():
    """The repair ladder handles empty content; raising here would skip it."""
    responses.add(
        responses.POST, CHAT_URL, json={"model": "m", "choices": [], "usage": {}}, status=200
    )
    assert DeepSeekProvider("sk-x").chat(_request()).content == ""


@responses.activate
def test_402_validation_reports_the_key_as_valid():
    """AC6: a 402 means the key is correct and the account needs credit."""
    responses.add(responses.POST, CHAT_URL, json={"error": "no credit"}, status=402)
    result = DeepSeekProvider("sk-x").validate_credentials()
    assert not result.ok
    assert result.status == "insufficient_balance"
    assert result.model  # still known — this is not an unknown-key state


# ------------------------------------------------------------ retry policy


def test_401_and_402_are_never_retried():
    policy = RetryPolicy(max_attempts=3)
    assert not policy.should_retry(InvalidAPIKeyError("x", status_code=401), 1)
    assert not policy.should_retry(InsufficientBalanceError("x", status_code=402), 1)
    assert not policy.should_retry(BudgetExceededError("x"), 1)


def test_transient_errors_are_retried_with_backoff():
    policy = RetryPolicy(max_attempts=3, base_delay=1.0, jitter=0.0)
    error = ProviderServerError("x", status_code=503)
    assert policy.should_retry(error, 1)
    assert policy.should_retry(error, 2)
    assert not policy.should_retry(error, 3)
    assert policy.delay_for(error, 1) == pytest.approx(1.0)
    assert policy.delay_for(error, 2) == pytest.approx(2.0)


def test_retry_after_beats_the_backoff_curve():
    policy = RetryPolicy(base_delay=1.0, jitter=0.0)
    error = RateLimitedError("slow down", retry_after=7.0)
    assert policy.delay_for(error, 1) == pytest.approx(7.0)


def test_run_with_retry_eventually_succeeds():
    attempts = []

    def flaky(attempt):
        attempts.append(attempt)
        if attempt < 3:
            raise ProviderServerError("nope", status_code=500)
        return "done"

    result = run_with_retry(
        flaky, RetryPolicy(max_attempts=3, base_delay=0.0), sleep=lambda _: None
    )
    assert result == "done"
    assert attempts == [1, 2, 3]


# ------------------------------------------------------------ the pool


def test_pool_attributes_results_to_their_own_items():
    """The classic silent-corruption bug: results matched by position."""
    import time

    pool = ConcurrencyPool(initial=4)
    items = list(range(20))

    def work(n):
        # Deliberately inverted duration so completion order differs from
        # submission order. A positional zip would scramble the mapping here.
        time.sleep((20 - n) * 0.002)
        return n * 10

    report = pool.map(items, work)

    assert report.succeeded == 20
    assert report.errors == {}
    for n in items:
        assert report.results[n] == n * 10


def test_pool_isolates_a_failing_item():
    pool = ConcurrencyPool(initial=4)

    def work(n):
        if n == 3:
            raise ValueError("bad item")
        return n

    report = pool.map([1, 2, 3, 4, 5], work)
    assert report.succeeded == 4
    assert report.failed == 1
    assert isinstance(report.errors[3], ValueError)


def test_pool_drains_on_a_stop_error():
    """A 402 mid-run preserves completed work rather than aborting."""
    pool = ConcurrencyPool(initial=2)

    def work(n):
        if n == 2:
            raise InsufficientBalanceError("no credit", status_code=402)
        return n

    report = pool.map([1, 2, 3, 4], work)
    assert report.stopped_early
    assert report.stop_reason == "InsufficientBalanceError"
    assert report.succeeded >= 1


def test_pool_halves_concurrency_under_pressure():
    pool = ConcurrencyPool(initial=8, floor=1)
    pool.on_pressure("rate_limited")
    assert pool.current == 4
    pool.on_pressure("rate_limited")
    assert pool.current == 2


def test_pool_step_up_requires_a_sustained_clean_window():
    """Hysteresis: an intermittent 429 must not make the pool oscillate."""
    pool = ConcurrencyPool(initial=4, ceiling=8)
    for _ in range(19):
        pool.on_success()
    assert pool.current == 4
    pool.on_success()
    assert pool.current == 5


def test_rate_limiter_allows_a_burst_then_throttles():
    limiter = RateLimiter(rate_per_second=1000.0, burst=3)
    assert all(limiter.acquire(timeout=0.5) for _ in range(3))


def test_chunked_splits_evenly_and_keeps_the_remainder():
    assert list(chunked(range(10), 4)) == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]]
    assert list(chunked([], 4)) == []


# -------------------------------------------------------------------- gate


def test_gate_counts_every_rejection_reason():
    """A gate whose statistics are invisible is a gate nobody will tune."""
    from src.ai.gate import GateDecision, PreAIGate, RejectionReason

    def reject_odd(item):
        if item % 2:
            return GateDecision(admitted=False, reason=RejectionReason.TOO_SHORT)
        return None

    gate = PreAIGate(rules=[reject_odd])
    admitted, rejected = gate.filter(list(range(10)))

    assert len(admitted) == 5
    assert len(rejected) == 5
    report = gate.report.to_dict()
    assert report["admitted"] == 5
    assert report["reasons"][RejectionReason.TOO_SHORT] == 5
    # All eleven reported, including zeros: a reason that never appears usually
    # means a rule is not wired up.
    assert set(report["reasons"]) == set(RejectionReason.ALL)


def test_gate_admits_by_default():
    """An empty gate that rejected everything would look like a working pipeline."""
    from src.ai.gate import PreAIGate

    gate = PreAIGate()
    admitted, rejected = gate.filter([1, 2, 3])
    assert len(admitted) == 3 and not rejected


# ------------------------------------------------------------- credentials


def test_key_survives_an_encrypt_decrypt_round_trip(settings):
    from src.ai.credentials import CredentialStore

    store = CredentialStore(settings)
    secret = "sk-roundtrip0123456789abcdef"
    store.set_key(secret, validate=False)
    assert store.get_key() == secret


def test_rotated_app_secret_key_is_a_distinct_state(settings, monkeypatch):
    """AC17 support: never a crash, and 're-enter' rather than 'enter'."""
    from src.ai.credentials import CredentialStore
    from src.db.models import AIStatus

    store = CredentialStore(settings)
    store.set_key("sk-willbecomeunreadable123", validate=False)

    monkeypatch.setenv("APP_SECRET_KEY", "a-completely-different-secret-value-here")
    from src.settings import reset_settings

    reset_settings()
    from src.settings import get_settings

    rotated = CredentialStore(get_settings({}))
    assert rotated.status().status == AIStatus.UNDECRYPTABLE


def test_fingerprint_identifies_without_revealing():
    from src.ai.credentials import fingerprint

    result = fingerprint("sk-abcdefghijklmnop1234")
    assert result == "sk-...1234"
    assert "abcdefghijklmnop" not in result


def test_short_key_is_rejected_before_the_network(settings):
    from src.ai.credentials import CredentialStore

    with pytest.raises(ValueError, match="complete API key"):
        CredentialStore(settings).set_key("sk-short", validate=True)
