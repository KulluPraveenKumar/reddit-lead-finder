"""Provider implementations. The ONLY package allowed to name a vendor."""

from .base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LLMProvider,
    ProviderCapabilities,
    ValidationResult,
)
from .fake import FakeProvider, ScriptedResponse
from .health import CircuitState, HealthRegistry, ProviderHealth
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from .registry import (
    DEFAULT_PROVIDER,
    PROVIDER_REGISTRY,
    ProviderDescriptor,
    build_provider,
    get_descriptor,
    selectable_descriptors,
)
from .router import NoProviderAvailableError, ProviderRouter

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "LLMProvider",
    "ProviderCapabilities",
    "ValidationResult",
    "FakeProvider",
    "ScriptedResponse",
    "OpenRouterProvider",
    "OpenAIProvider",
    "ProviderHealth",
    "HealthRegistry",
    "CircuitState",
    "ProviderRouter",
    "NoProviderAvailableError",
    "PROVIDER_REGISTRY",
    "DEFAULT_PROVIDER",
    "ProviderDescriptor",
    "build_provider",
    "get_descriptor",
    "selectable_descriptors",
]
