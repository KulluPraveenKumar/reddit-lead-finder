"""Provider registry and UI descriptors.

The registry is the *only* place outside ``providers/`` that names a vendor, and
it exists so the Settings dropdown can be built from data rather than from a
hardcoded list in a template. Adding a provider is a subclass plus one entry
here; nothing in the dashboard or the service layer changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import LLMProvider
from .deepseek import PRICING_VERIFIED_ON, DeepSeekProvider
from .fake import FakeProvider
from .openai import PRICING_VERIFIED_ON as OPENAI_VERIFIED_ON
from .openai import OpenAIProvider
from .openrouter import PRICING_VERIFIED_ON as OPENROUTER_VERIFIED_ON
from .openrouter import OpenRouterProvider


@dataclass(frozen=True)
class ProviderDescriptor:
    """Everything the Settings page needs to render a provider option."""

    name: str
    display_name: str
    cls: type[LLMProvider]
    default_model: str
    models: list[str] = field(default_factory=list)
    context_window: int = 0
    #: Shown under the dropdown, e.g. "OpenAI-compatible - 1M context".
    blurb: str = ""
    #: Where an operator goes to get a key. Rendered as a link.
    console_url: str = ""
    #: Where an operator tops up. Shown in the amber 402 state.
    billing_url: str = ""
    pricing: dict[str, float] = field(default_factory=dict)
    pricing_verified_on: str = ""
    selectable: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "default_model": self.default_model,
            "models": list(self.models),
            "context_window": self.context_window,
            "blurb": self.blurb,
            "console_url": self.console_url,
            "billing_url": self.billing_url,
            "pricing": dict(self.pricing),
            "pricing_verified_on": self.pricing_verified_on,
        }


PROVIDER_REGISTRY: dict[str, ProviderDescriptor] = {
    "deepseek": ProviderDescriptor(
        name="deepseek",
        display_name="DeepSeek",
        cls=DeepSeekProvider,
        default_model=DeepSeekProvider.default_model,
        models=[DeepSeekProvider.default_model],
        context_window=DeepSeekProvider.CONTEXT_WINDOW,
        blurb="DeepSeek V4 Flash - OpenAI-compatible - 1M context",
        console_url="https://platform.deepseek.com/api_keys",
        billing_url="https://platform.deepseek.com/top_up",
        pricing=dict(DeepSeekProvider.PRICES),
        pricing_verified_on=PRICING_VERIFIED_ON,
    ),
    "openrouter": ProviderDescriptor(
        name="openrouter",
        display_name="OpenRouter (DeepSeek V4 Flash)",
        cls=OpenRouterProvider,
        default_model=OpenRouterProvider.default_model,
        models=[
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v4-pro",
        ],
        context_window=OpenRouterProvider.CONTEXT_WINDOW,
        blurb=(
            "Gateway to DeepSeek V4 Flash - OpenAI-compatible - 1M context. "
            "Cached input costs 10x more than DeepSeek direct, so the prefix-cache "
            "saving is ~5x rather than ~50x."
        ),
        console_url="https://openrouter.ai/keys",
        billing_url="https://openrouter.ai/credits",
        pricing=dict(OpenRouterProvider.PRICES),
        pricing_verified_on=OPENROUTER_VERIFIED_ON,
    ),
    "openai": ProviderDescriptor(
        name="openai",
        display_name="OpenAI",
        cls=OpenAIProvider,
        default_model=OpenAIProvider.default_model,
        models=["gpt-4o-mini", "gpt-4o"],
        context_window=OpenAIProvider.CONTEXT_WINDOW,
        blurb=(
            "OpenAI - schema-enforced structured output and a batch endpoint, "
            "but ~4x the output price of DeepSeek V4 Flash. Pricing here is "
            "unverified: no key was available to confirm it."
        ),
        console_url="https://platform.openai.com/api-keys",
        billing_url="https://platform.openai.com/settings/organization/billing",
        pricing=dict(OpenAIProvider.PRICES),
        pricing_verified_on=OPENAI_VERIFIED_ON,
    ),
    "fake": ProviderDescriptor(
        name="fake",
        display_name="Fake Provider (testing)",
        cls=FakeProvider,
        default_model=FakeProvider.default_model,
        models=[FakeProvider.default_model],
        context_window=128_000,
        blurb="Offline test double. Never selectable in the UI.",
        pricing={"input_cached": 0.0028, "input_uncached": 0.14, "output": 0.28},
        # Hidden from the dropdown: an operator selecting it would get a
        # working-looking system that silently invents every answer.
        selectable=False,
    ),
}

DEFAULT_PROVIDER = "deepseek"


def get_descriptor(name: str) -> ProviderDescriptor:
    try:
        return PROVIDER_REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown provider {name!r}. Known: {', '.join(sorted(PROVIDER_REGISTRY))}"
        ) from None


def build_provider(name: str, api_key: str | None = None, *, model: str | None = None, **options) -> LLMProvider:
    descriptor = get_descriptor(name)
    return descriptor.cls(api_key=api_key, model=model or descriptor.default_model, **options)


def selectable_descriptors() -> list[ProviderDescriptor]:
    return [d for d in PROVIDER_REGISTRY.values() if d.selectable]
