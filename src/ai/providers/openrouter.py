"""OpenRouter — a gateway that serves DeepSeek models (among ~360 others).

This class is the provider abstraction earning its keep: it is a subclass with a
different base URL, model id, usage-parsing rule and price table. Nothing in
``AIService``, the rule engine, the dashboard, or the schemas changed to support
it.

**Two differences from DeepSeek direct that materially affect the cost model**,
both verified against the live ``/models`` endpoint on 2026-07-31:

1. **Cached input is priced 10x higher than DeepSeek direct** — $0.028/M rather
   than $0.0028/M. The prefix-cache differential is therefore about **5x**, not
   50x. The cache is still worth engineering for, but it stops being the single
   dominant cost lever, and the gate/dedup/incremental savings become
   proportionally more important.
2. **The usage field names differ.** OpenRouter reports the cache split in
   OpenAI's shape (``prompt_tokens_details.cached_tokens``), not DeepSeek's
   ``prompt_cache_hit_tokens``. Parsing the wrong one would silently report a 0%
   cache-hit ratio forever, which looks identical to a genuinely broken cache.

Model ids are namespaced: ``deepseek/deepseek-v4-flash``, not
``deepseek-v4-flash``.
"""

from __future__ import annotations

from typing import Any

from .base import ProviderCapabilities
from .openai_compatible import OpenAICompatibleProvider

#: Verified against https://openrouter.ai/api/v1/models on this date.
PRICING_VERIFIED_ON = "2026-07-31"


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    display_name = "OpenRouter"
    default_model = "deepseek/deepseek-v4-flash"
    base_url = "https://openrouter.ai/api/v1"

    capabilities = ProviderCapabilities(
        supports_batch_api=False,
        supports_schema_enforcement=False,
        # Passed through from the upstream provider, so it depends on the model.
        # True for the DeepSeek models this project uses.
        supports_prefix_caching=True,
        cache_chunk_tokens=64,
    )

    CONTEXT_WINDOW = 1_048_576

    #: USD per 1M tokens. Note `input_cached` is 10x DeepSeek direct.
    PRICES: dict[str, float] = {
        "input_cached": 0.028,
        "input_uncached": 0.14,
        "output": 0.28,
    }

    def price_per_million(self) -> dict[str, float]:
        return dict(self.PRICES)

    def context_window(self) -> int:
        return self.CONTEXT_WINDOW

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        # Optional attribution headers. Sent so usage is identifiable in the
        # OpenRouter dashboard rather than appearing as anonymous traffic.
        headers["HTTP-Referer"] = "https://github.com/local/reddit-lead-finder"
        headers["X-Title"] = "Reddit Lead Finder"
        return headers

    def _reported_cost(self, usage: dict[str, Any]) -> float | None:
        """OpenRouter reports actual charged cost, and it is authoritative.

        Measured 2026-07-31: two calls with a byte-identical 2,014-token prefix
        reported ``cached_tokens: 0`` both times, while the prompt cost fell
        0.000282 -> 0.000186, a 34% drop. The upstream cache **is** working and
        the discount **is** passed through; only the telemetry is missing.

        Computing cost from tokens here would therefore overstate it on every
        cached call. When the provider tells us what it charged, believe it.
        """
        cost = usage.get("cost")
        return float(cost) if cost is not None else None

    def _parse_usage(self, usage: dict[str, Any]) -> tuple[int, int, int]:
        """OpenAI-shaped usage: the cache split lives in ``prompt_tokens_details``.

        Falls back to DeepSeek's field names, then to "all uncached". The
        fallback is pessimistic on purpose: it can overstate cost, but it can
        never make a broken cache look like a working one.
        """
        out = int(usage.get("completion_tokens", 0) or 0)
        total_in = int(usage.get("prompt_tokens", 0) or 0)

        details = usage.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens")

        if cached is None:
            # Some upstreams are proxied through with DeepSeek's own names.
            cached = usage.get("prompt_cache_hit_tokens")

        if cached is None:
            return 0, total_in, out

        cached = int(cached)
        return cached, max(0, total_in - cached), out
