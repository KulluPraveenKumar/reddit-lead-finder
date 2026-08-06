"""DeepSeek V4 Flash.

This is the only file in ``src/`` allowed to contain the string "deepseek"
outside the registry. A grep test enforces that (docs/03 §2).

Prices and mechanics verified 2026-07-30 (docs/02 §6.2–6.9):

* ``deepseek-v4-flash``, 1M context, 384K max output
* OpenAI-compatible wire format at ``https://api.deepseek.com/v1``
* **Implicit** prefix caching — no ``cache_control`` marker, automatic, in
  64-token chunks, best-effort with no guaranteed hit rate
* Cached input is priced **50x** below uncached, which is why the cached and
  uncached token counts are tracked separately everywhere
* **No batch endpoint** — bulk work uses a bounded concurrency pool instead
"""

from __future__ import annotations

from typing import Any

from .base import ProviderCapabilities
from .openai_compatible import OpenAICompatibleProvider

#: Verified 2026-07-30. Displayed in the UI alongside this date so an operator
#: can see how stale the figures are rather than trusting them indefinitely.
PRICING_VERIFIED_ON = "2026-07-30"


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"
    display_name = "DeepSeek"
    default_model = "deepseek-v4-flash"
    base_url = "https://api.deepseek.com/v1"

    capabilities = ProviderCapabilities(
        # No batch endpoint. Confirmed 2026-07-30; the design uses a bounded
        # adaptive concurrency pool in its place.
        supports_batch_api=False,
        # JSON mode validates SYNTAX, not schema. Client-side Pydantic
        # validation plus the repair ladder is not belt-and-braces here, it is
        # the only schema enforcement that exists.
        supports_schema_enforcement=False,
        supports_prefix_caching=True,
        cache_chunk_tokens=64,
    )

    CONTEXT_WINDOW = 1_000_000
    MAX_OUTPUT_TOKENS = 384_000

    PRICES: dict[str, float] = {
        "input_cached": 0.0028,
        "input_uncached": 0.14,
        "output": 0.28,
    }

    def price_per_million(self) -> dict[str, float]:
        return dict(self.PRICES)

    def context_window(self) -> int:
        return self.CONTEXT_WINDOW

    def _parse_usage(self, usage: dict[str, Any]) -> tuple[int, int, int]:
        """DeepSeek reports the cache split directly.

        ``prompt_cache_hit_tokens`` / ``prompt_cache_miss_tokens`` are the only
        observable evidence that prefix caching is working. If they are absent,
        fall back to treating all input as uncached — pessimistic, so a missing
        field can overstate cost but never hide a cache failure.
        """
        out = int(usage.get("completion_tokens", 0) or 0)
        hit = usage.get("prompt_cache_hit_tokens")
        miss = usage.get("prompt_cache_miss_tokens")

        if hit is not None or miss is not None:
            return int(hit or 0), int(miss or 0), out

        total_in = int(usage.get("prompt_tokens", 0) or 0)
        return 0, total_in, out
