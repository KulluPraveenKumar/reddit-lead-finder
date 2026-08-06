"""OpenAI.

Same wire format as the base class, so this is genuinely the ~30-line subclass
the abstraction promised: base URL, model id, price table, and the cache-split
field name.

**Anthropic and Gemini are deliberately absent.** Both use a different request
and response shape, so each is a real implementation of ``LLMProvider`` rather
than a subclass of this one. Writing them without a key to test against would
produce code that looks finished and has never executed — the abstraction
supports them, and that is a different claim from having them.
"""

from __future__ import annotations

from typing import Any

from .base import ProviderCapabilities
from .openai_compatible import OpenAICompatibleProvider

#: gpt-4o-mini pricing, per 1M tokens. NOT independently verified in this
#: session — no OpenAI key was available. The Settings page shows this date so
#: an operator can see the figure is unconfirmed rather than trusting it.
PRICING_VERIFIED_ON = "unverified"


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    display_name = "OpenAI"
    default_model = "gpt-4o-mini"
    base_url = "https://api.openai.com/v1"

    capabilities = ProviderCapabilities(
        # OpenAI does have a batch endpoint (24h turnaround, 50% discount).
        # Flagged true so the service can choose that path when one exists;
        # wiring it is Phase 7 work and only pays off for non-urgent bulk runs.
        supports_batch_api=True,
        # Structured Outputs enforces a JSON *schema*, not just syntax. The one
        # capability here that DeepSeek lacks.
        supports_schema_enforcement=True,
        supports_prefix_caching=True,
        cache_chunk_tokens=128,
    )

    CONTEXT_WINDOW = 128_000

    PRICES: dict[str, float] = {
        "input_cached": 0.075,
        "input_uncached": 0.15,
        "output": 0.60,
    }

    def price_per_million(self) -> dict[str, float]:
        return dict(self.PRICES)

    def context_window(self) -> int:
        return self.CONTEXT_WINDOW

    def _parse_usage(self, usage: dict[str, Any]) -> tuple[int, int, int]:
        """OpenAI reports the cache split in ``prompt_tokens_details``."""
        out = int(usage.get("completion_tokens", 0) or 0)
        total_in = int(usage.get("prompt_tokens", 0) or 0)
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        if cached is None:
            return 0, total_in, out
        cached = int(cached)
        return cached, max(0, total_in - cached), out
