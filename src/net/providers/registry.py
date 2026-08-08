"""Provider construction from configuration.

**This module is the mechanism behind "switching vendors is a config change,
not a code change"** (``docs/29`` §5.4). Every provider is reachable by a
``type`` string, and a new vendor is a new block in ``config.yaml`` rather than
a new class — the reason ``ManagedProxyProvider`` is one generic gateway class
instead of one class per vendor.

Modelled on ``src/ai/providers/registry.py``, which does the same job for model
providers, so the two read alike.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .base import NetworkProvider

log = logging.getLogger(__name__)

#: ``${NAME}`` in a provider value means "read NAME from the environment".
#: Credentials are configured this way so ``config.yaml`` -- which is committed --
#: never holds one. Documented in ``docs/29`` §5.4.
_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


class ProviderConfigError(ValueError):
    """A provider block that cannot be turned into a provider."""


def _registry() -> dict[str, type[NetworkProvider]]:
    """Imported lazily so this module can be imported from any of them."""
    from .direct import DirectProvider
    from .managed_gateway import ManagedProxyProvider
    from .managed_list import WebshareDatacenterProvider
    from .null import NullProvider

    return {
        cls.type: cls
        for cls in (DirectProvider, WebshareDatacenterProvider, ManagedProxyProvider, NullProvider)
    }


def provider_types() -> list[str]:
    return sorted(_registry())


def resolve_value(value: Any, secret_lookup) -> Any:
    """Expand a ``${NAME}`` reference. Anything else is returned unchanged.

    ``secret_lookup`` is injected rather than reading ``os.environ`` here:
    ``src/settings.py`` states that nothing outside it reads the environment for
    configuration, and one module quietly exempting itself is how that stops
    being true.
    """
    if not isinstance(value, str):
        return value
    match = _ENV_REF.match(value.strip())
    if match is None:
        return value
    return secret_lookup(match.group(1))


def build_provider(spec: dict[str, Any], *, secret_lookup=None) -> NetworkProvider:
    """One ``network.providers[]`` block -> one provider.

    Raises :class:`ProviderConfigError` with a readable message rather than a
    ``KeyError``: this is operator-facing configuration, and a stack trace is
    not an error message.
    """
    if secret_lookup is None:
        from src.settings import get_settings

        secret_lookup = get_settings().get_secret

    if not isinstance(spec, dict):
        raise ProviderConfigError(
            f"a network provider must be a mapping, got {type(spec).__name__}"
        )

    name = str(spec.get("name") or "").strip()
    if not name:
        raise ProviderConfigError("a network provider needs a 'name'")

    type_name = spec.get("type")
    if type_name is None:
        # A bare `type: null` in YAML parses as None, which is why the null
        # provider is spelled `null_provider`. Say so, rather than reporting a
        # missing key the operator can see they supplied.
        raise ProviderConfigError(
            f"provider {name!r} has no 'type'. Valid types: {', '.join(provider_types())}. "
            "(A bare 'type: null' parses as no value -- use 'null_provider'.)"
        )

    registry = _registry()
    cls = registry.get(str(type_name))
    if cls is None:
        raise ProviderConfigError(
            f"provider {name!r} has unknown type {type_name!r}. "
            f"Valid types: {', '.join(provider_types())}"
        )

    resolved = {key: resolve_value(value, secret_lookup) for key, value in spec.items()}
    try:
        return cls.from_config(name, resolved)
    except ProviderConfigError:
        raise
    except Exception as exc:
        raise ProviderConfigError(
            f"provider {name!r} ({type_name}) is misconfigured: {exc}"
        ) from exc
