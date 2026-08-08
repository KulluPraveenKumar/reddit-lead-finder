"""Reddit-agnostic network layer: proxies, transport, caching, metrics.

Nothing here knows what a subreddit is. Phase 4's website fetcher reuses it
unchanged, which is the test of whether that separation is real.
"""

from .blocks import BlockKind, BlockSignatures, BlockVerdict
from .blocks import classify as classify_block
from .cache import HTTPCache
from .egress import get_policy, policy_error, reset_policy
from .http_client import FetchResult, ProxiedHTTPClient
from .metrics import NetMetrics
from .policy import (
    DegradationNotice,
    EgressExhausted,
    NetworkPolicy,
    OnPoolExhausted,
    Policy,
    RequestClass,
    build_policy_from_config,
    build_policy_from_settings,
)
from .providers import NetworkProvider, Outcome, build_provider, provider_types
from .proxy_manager import ProxyManager, build_from_settings
from .proxy_models import ProxyEndpoint, ProxyParseError, ProxyState, parse_proxy_file
from .retry import BlockedError, NetErrorClass, ProxyExhaustedError, RetryPolicy
from .user_agents import PROFILES, HeaderProfile, headers_for

__all__ = [
    "BlockKind",
    "BlockVerdict",
    "BlockSignatures",
    "classify_block",
    "HTTPCache",
    "NetMetrics",
    "ProxiedHTTPClient",
    "FetchResult",
    "ProxyManager",
    "build_from_settings",
    "ProxyEndpoint",
    "ProxyState",
    "ProxyParseError",
    "parse_proxy_file",
    "RetryPolicy",
    "NetErrorClass",
    "BlockedError",
    "ProxyExhaustedError",
    "HeaderProfile",
    "PROFILES",
    "headers_for",
    # P4 -- egress is a policy, not a mandate (AD-25).
    "NetworkPolicy",
    "NetworkProvider",
    "RequestClass",
    "Policy",
    "OnPoolExhausted",
    "EgressExhausted",
    "DegradationNotice",
    "Outcome",
    "build_policy_from_config",
    "build_policy_from_settings",
    "build_provider",
    "provider_types",
    "get_policy",
    "policy_error",
    "reset_policy",
]
