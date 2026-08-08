"""Egress providers: one class per *way* of reaching the internet, not per vendor.

``ManagedProxyProvider`` covers every managed residential vendor because they all
speak the same ``user-session-xxx:pass@gateway:port`` shape, so a vendor swap is
a configuration change (``docs/29`` §3.1).
"""

from .base import (
    Capacity,
    Lease,
    NetworkProvider,
    Outcome,
    ProviderHealth,
    ProviderUnavailable,
    Rotation,
)
from .direct import DirectProvider
from .managed_gateway import ManagedProxyProvider
from .managed_list import WebshareDatacenterProvider
from .null import NullProvider
from .registry import ProviderConfigError, build_provider, provider_types

__all__ = [
    "NetworkProvider",
    "Lease",
    "Outcome",
    "Rotation",
    "ProviderHealth",
    "Capacity",
    "ProviderUnavailable",
    "DirectProvider",
    "WebshareDatacenterProvider",
    "ManagedProxyProvider",
    "NullProvider",
    "build_provider",
    "provider_types",
    "ProviderConfigError",
]
