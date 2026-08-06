"""Reddit-agnostic network layer: proxies, transport, caching, metrics.

Nothing here knows what a subreddit is. Phase 4's website fetcher reuses it
unchanged, which is the test of whether that separation is real.
"""

from .blocks import BlockKind, BlockVerdict
from .blocks import classify as classify_block
from .cache import HTTPCache
from .http_client import FetchResult, ProxiedHTTPClient
from .metrics import NetMetrics
from .proxy_manager import ProxyManager, build_from_settings
from .proxy_models import ProxyEndpoint, ProxyParseError, ProxyState, parse_proxy_file
from .retry import BlockedError, NetErrorClass, ProxyExhaustedError, RetryPolicy
from .user_agents import PROFILES, HeaderProfile, headers_for

__all__ = [
    "BlockKind",
    "BlockVerdict",
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
]
