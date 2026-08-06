"""Navigation model.

One list, defined once, injected into every template by a context processor. A
nav defined per-template drifts the moment a page is added, and the page that
gets forgotten is always the newest one — which is exactly the failure this
module exists to prevent.

**Only implemented pages appear.** A greyed-out "Projects (coming soon)" link
teaches an operator that the product is half-built and trains them to ignore the
nav; a link that 404s is worse still. Future phases add an entry here when the
page exists, and not before.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    url: str
    title: str = ""
    #: Visual grouping: operational pages on the left, system pages after a
    #: divider. Purely presentational.
    group_start: bool = False
    group_end: bool = False
    #: The phase that introduces this page. Documentation, not behaviour --
    #: it keeps the roadmap and the nav honest with each other.
    phase: int = 1


#: The full navigation, in display order.
#:
#: Deliberately absent until their phase lands (docs/10):
#:   Projects  - Phase 4    Runs      - Phase 3
#:   Discovery - Phase 5    Quality   - Phase 8
NAV_ITEMS: list[NavItem] = [
    NavItem(
        key="dashboard",
        label="Dashboard",
        url="/",
        title="Leads, activity and scraper status",
        phase=0,
    ),
    NavItem(
        key="configuration",
        label="Configuration",
        url="/configuration",
        title="Subreddits, keywords, search queries and scoring weights",
        phase=0,
    ),
    NavItem(
        key="settings_ai",
        label="AI Provider",
        url="/settings/ai",
        title="API key, provider selection, connection test, budget caps",
        group_start=True,
        phase=1,
    ),
    NavItem(
        key="health_ai",
        label="AI Health",
        url="/health/ai",
        title="Cost, cache, latency, circuit breaker and provider health",
        phase=1,
    ),
    NavItem(
        key="health_proxies",
        label="Proxies",
        url="/health/proxies",
        title="Proxy pool state, exit IPs, block rate and IP-leak check",
        phase=2,
    ),
    NavItem(
        key="about",
        label="About",
        url="/about",
        title="What is built, what is not, and how to verify it",
        group_end=True,
        phase=1,
    ),
]


_STATUS_LABEL = {
    "valid": "AI ready",
    "unconfigured": "AI not configured",
    "invalid_key": "AI key rejected",
    "insufficient_balance": "AI needs credit",
    "unreachable": "AI unreachable",
    "undecryptable": "AI key unreadable",
}

_STATUS_TOOLTIP = {
    "valid": "Provider connected. Click for cost, cache and latency.",
    "unconfigured": "No API key configured. AI features are disabled; scraping still works.",
    "invalid_key": "The provider rejected the stored key. Open AI Provider to replace it.",
    "insufficient_balance": "The key is valid but the account needs credit. Nothing is broken.",
    "unreachable": "Could not reach the provider. Usually a network issue; scraping is unaffected.",
    "undecryptable": "APP_SECRET_KEY changed, so the stored key cannot be read. Re-enter it.",
}


def nav_context() -> dict:
    """Context processor payload: the nav items and a live AI status pill.

    Rendered server-side so the pill is correct on first paint. Fetching it via
    JS would show "unknown" for a beat on every page load, which reads as a
    fault rather than a load.

    Never raises. A nav that can 500 the page it decorates is worse than a nav
    without a status pill.
    """
    ai = None
    try:
        from .app import get_ai_service

        service = get_ai_service()
        status = service.credentials.status()
        ai = {
            "status": status.status,
            "label": _STATUS_LABEL.get(status.status, status.status),
            "tooltip": _STATUS_TOOLTIP.get(status.status, ""),
            "provider": service.provider_name,
        }
    except Exception:
        log.debug("nav: AI status unavailable", exc_info=True)
        ai = {
            "status": "unconfigured",
            "label": "AI unavailable",
            "tooltip": "AI status could not be read. Scraping is unaffected.",
            "provider": "",
        }

    return {"nav_items": NAV_ITEMS, "nav_ai": ai}


@dataclass
class NavRegistry:
    """Test seam: lets a test assert the nav matches the implemented routes."""

    items: list[NavItem] = field(default_factory=lambda: list(NAV_ITEMS))

    def urls(self) -> list[str]:
        return [item.url for item in self.items]

    def keys(self) -> list[str]:
        return [item.key for item in self.items]
