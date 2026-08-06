"""Test double. The entire AI suite runs on this with zero network calls.

Two jobs:

1. **Replay recorded responses** so the pipeline can be exercised end to end.
2. **Simulate every failure** the real provider can produce — 401, 402, 429,
   5xx, timeouts, empty content, invalid JSON, schema violations. A test double
   that only does the happy path leaves the error handling untested, which is
   the half most likely to be wrong.

One honest limitation, stated here so nobody forgets it: this class *simulates*
``prompt_cache_hit_tokens``. A green test proving the field is read correctly
says nothing about whether DeepSeek's real prefix cache is hitting. That can
only be verified with a live key (AC14).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ..errors import (
    InsufficientBalanceError,
    InvalidAPIKeyError,
    ProviderServerError,
    ProviderUnreachableError,
    RateLimitedError,
)
from .base import (
    ChatRequest,
    ChatResponse,
    LLMProvider,
    ProviderCapabilities,
    ValidationResult,
)


@dataclass
class ScriptedResponse:
    """One scripted turn: either content or an exception."""

    content: str | None = None
    raises: Exception | None = None
    input_tokens_cached: int = 0
    input_tokens_uncached: int = 100
    output_tokens: int = 50
    latency_ms: int = 42
    finish_reason: str = "stop"


@dataclass
class FakeProvider(LLMProvider):
    """A provider whose behaviour is fully scripted.

    Usage:
        FakeProvider(responses=["{...}", "{...}"])                # sequence
        FakeProvider(handler=lambda req: ScriptedResponse(...))   # dynamic
        FakeProvider(default_payload={"ok": True})                # constant
    """

    name: str = "fake"
    display_name: str = "Fake Provider"
    default_model: str = "fake-model-v1"

    responses: list[str | ScriptedResponse | Exception] = field(default_factory=list)
    handler: Callable[[ChatRequest], ScriptedResponse] | None = None
    default_payload: dict[str, Any] | None = None

    #: Simulates a warm prefix cache from call N onward. Purely a fiction for
    #: testing the accounting; proves nothing about the real provider.
    cache_warm_after: int = 1
    simulated_prefix_tokens: int = 3000

    api_key: str | None = "fake-key"
    valid: bool = True
    validation_status: str = "valid"
    validation_error: str | None = None

    capabilities: ProviderCapabilities = field(
        default_factory=lambda: ProviderCapabilities(
            supports_batch_api=False,
            supports_schema_enforcement=False,
            supports_prefix_caching=True,
            cache_chunk_tokens=64,
        )
    )

    def __post_init__(self) -> None:
        self.model = self.default_model
        self.options: dict[str, Any] = {}
        self.calls: list[ChatRequest] = []
        self._index = 0

    # ------------------------------------------------------------------ chat

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls.append(request)
        call_number = len(self.calls)

        scripted = self._next_scripted(request)

        if scripted.raises is not None:
            raise scripted.raises

        content = scripted.content
        if content is None:
            payload = self.default_payload if self.default_payload is not None else {"ok": True}
            content = json.dumps(payload)

        cached = scripted.input_tokens_cached
        uncached = scripted.input_tokens_uncached
        if cached == 0 and call_number > self.cache_warm_after and self.capabilities.supports_prefix_caching:
            cached = self.simulated_prefix_tokens
            uncached = max(0, uncached - cached) if uncached > cached else uncached

        return ChatResponse(
            content=content,
            model=self.model,
            input_tokens_cached=cached,
            input_tokens_uncached=uncached,
            output_tokens=scripted.output_tokens,
            latency_ms=scripted.latency_ms,
            finish_reason=scripted.finish_reason,
            raw={"fake": True, "call": call_number},
        )

    def _next_scripted(self, request: ChatRequest) -> ScriptedResponse:
        if self.handler is not None:
            return self.handler(request)

        if self._index < len(self.responses):
            item = self.responses[self._index]
            self._index += 1
            if isinstance(item, ScriptedResponse):
                return item
            if isinstance(item, Exception):
                return ScriptedResponse(raises=item)
            return ScriptedResponse(content=item)

        # Past the end of the script: keep returning the last behaviour rather
        # than raising. A test that makes one extra call should not fail with
        # IndexError from the fixture.
        return ScriptedResponse()

    # ------------------------------------------------------------ validation

    def validate_credentials(self) -> ValidationResult:
        time.sleep(0)  # keep the shape of a real call without the latency
        if self.valid:
            return ValidationResult(
                ok=True,
                model=self.model,
                context_window=self.context_window(),
                latency_ms=12,
                status="valid",
            )
        return ValidationResult(
            ok=False,
            model=self.model if self.validation_status == "insufficient_balance" else None,
            latency_ms=12,
            error=self.validation_error or "fake validation failure",
            status=self.validation_status,
        )

    def price_per_million(self) -> dict[str, float]:
        # Same shape and order of magnitude as DeepSeek so cost arithmetic in
        # tests exercises realistic numbers.
        return {"input_cached": 0.0028, "input_uncached": 0.14, "output": 0.28}

    def context_window(self) -> int:
        return 128_000

    # ------------------------------------------------------- factory helpers

    @classmethod
    def failing(cls, exc: Exception, **kwargs) -> FakeProvider:
        return cls(responses=[exc], **kwargs)

    @classmethod
    def invalid_key(cls) -> FakeProvider:
        return cls(
            responses=[InvalidAPIKeyError("Fake rejected this key.", status_code=401)],
            valid=False,
            validation_status="invalid_key",
            validation_error="Fake rejected this key.",
        )

    @classmethod
    def no_balance(cls) -> FakeProvider:
        return cls(
            responses=[InsufficientBalanceError("Fake balance exhausted.", status_code=402)],
            valid=False,
            validation_status="insufficient_balance",
            validation_error="Fake balance exhausted.",
        )

    @classmethod
    def unreachable(cls) -> FakeProvider:
        return cls(
            responses=[ProviderUnreachableError("Could not reach Fake")],
            valid=False,
            validation_status="unreachable",
            validation_error="Could not reach Fake",
        )

    @classmethod
    def rate_limited_then_ok(cls, payload: dict[str, Any]) -> FakeProvider:
        return cls(
            responses=[
                RateLimitedError("Fake is rate limiting", status_code=429, retry_after=0.0),
                json.dumps(payload),
            ]
        )

    @classmethod
    def server_error_then_ok(cls, payload: dict[str, Any]) -> FakeProvider:
        return cls(
            responses=[
                ProviderServerError("Fake server error", status_code=503),
                json.dumps(payload),
            ]
        )

    @classmethod
    def empty_then_ok(cls, payload: dict[str, Any]) -> FakeProvider:
        return cls(responses=[ScriptedResponse(content=""), json.dumps(payload)])

    @classmethod
    def fenced_then_ok(cls, payload: dict[str, Any]) -> FakeProvider:
        """First response wrapped in a markdown fence — the classic JSON-mode slip."""
        fenced = "```json\n" + json.dumps(payload) + "\n```"
        return cls(responses=[fenced, json.dumps(payload)])

    @classmethod
    def bad_schema_then_ok(cls, bad: dict[str, Any], good: dict[str, Any]) -> FakeProvider:
        return cls(responses=[json.dumps(bad), json.dumps(good)])

    @classmethod
    def sequence(cls, payloads: Iterable[dict[str, Any]]) -> FakeProvider:
        return cls(responses=[json.dumps(p) for p in payloads])
