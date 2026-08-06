"""The provider boundary.

Four methods and four capability flags. Everything above this line speaks in
domain terms; everything below knows about a vendor. A grep test asserts the
string "deepseek" appears nowhere outside this package.

The capability flags exist so ``AIService`` can pick a better code path without
branching on vendor identity — ``if provider.supports_batch_api`` rather than
``if provider.name == "deepseek"``. The second form is how vendor coupling
creeps back in one conditional at a time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderCapabilities:
    #: Server-side batch endpoint (OpenAI has one; DeepSeek does not).
    supports_batch_api: bool = False
    #: Server-enforced JSON *schema*, as opposed to JSON syntax only.
    supports_schema_enforcement: bool = False
    #: Automatic prefix caching, making a byte-stable prefix worth engineering.
    supports_prefix_caching: bool = False
    #: Granularity of that cache. Prefix padding aligns to this.
    cache_chunk_tokens: int = 0


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class ChatRequest:
    messages: list[ChatMessage]
    model: str
    max_tokens: int = 4096
    #: 0.0 for classification work: we want the same answer for the same input,
    #: and a byte-stable request is also a cacheable one.
    temperature: float = 0.0
    json_mode: bool = True
    stop: list[str] | None = None
    timeout: tuple[float, float] = (10.0, 60.0)  # (connect, read)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResponse:
    content: str
    model: str
    #: Split because cached and uncached input are priced ~50x apart.
    input_tokens_cached: int = 0
    input_tokens_uncached: int = 0
    output_tokens: int = 0
    #: Output tokens spent on reasoning before any content was emitted.
    #: Reasoning models can consume the ENTIRE max_tokens budget here and
    #: return empty content, which looks like a provider fault and is not.
    reasoning_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str | None = None
    #: Cost as reported by the provider, when it reports one. Authoritative:
    #: gateways apply discounts (cache, negotiated rates) that token counts
    #: cannot reveal, so a locally computed figure would be wrong.
    reported_cost_usd: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens_cached + self.input_tokens_uncached

    @property
    def cache_hit_ratio(self) -> float:
        total = self.total_input_tokens
        return self.input_tokens_cached / total if total else 0.0

    @property
    def truncated(self) -> bool:
        """Output hit ``max_tokens``.

        Worth surfacing: a truncated response is usually invalid JSON, and the
        repair ladder would otherwise burn its retries on a problem that only a
        bigger ``max_tokens`` can fix.
        """
        return self.finish_reason == "length"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    model: str | None = None
    context_window: int | None = None
    latency_ms: int = 0
    error: str | None = None
    #: Status for ``ai_provider_state`` — lets 402 report "valid key, no credit"
    #: rather than collapsing into a generic failure.
    status: str = "valid"


class LLMProvider(ABC):
    """Base class for every provider."""

    name: str = "abstract"
    display_name: str = "Abstract Provider"
    default_model: str = ""
    capabilities: ProviderCapabilities = ProviderCapabilities()

    def __init__(self, api_key: str | None = None, *, model: str | None = None, **options):
        self.api_key = api_key
        self.model = model or self.default_model
        self.options = options

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """Issue one completion. Raises the appropriate ``ProviderError``."""

    @abstractmethod
    def validate_credentials(self) -> ValidationResult:
        """Cheapest possible round trip that proves the key works."""

    @abstractmethod
    def price_per_million(self) -> dict[str, float]:
        """``{"input_cached": .., "input_uncached": .., "output": ..}`` in USD."""

    def estimate_cost(
        self, input_cached: int, input_uncached: int, output: int, multiplier: float = 1.0
    ) -> float:
        p = self.price_per_million()
        return (
            (input_cached * p["input_cached"] / 1_000_000)
            + (input_uncached * p["input_uncached"] / 1_000_000)
            + (output * p["output"] / 1_000_000)
        ) * multiplier

    def context_window(self) -> int:
        return 0

    def __repr__(self) -> str:
        return f"<{type(self).__name__} model={self.model}>"
