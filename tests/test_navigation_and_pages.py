"""Navigation, page rendering, and the discoverability contract.

The bug these guard against: a Phase-1 feature that exists but that nobody can
reach without typing a URL. Every implemented page must be one click from every
other page, and no nav entry may point at something unbuilt.
"""

from __future__ import annotations

import re

import pytest

from src.dashboard.nav import NAV_ITEMS

PAGES = ["/", "/configuration", "/about", "/settings/ai", "/health/ai", "/health", "/settings"]


# --------------------------------------------------------------- the contract


def test_every_nav_target_resolves(client):
    """A nav link that 404s turns 'not built yet' into 'broken'."""
    for item in NAV_ITEMS:
        response = client.get(item.url)
        assert response.status_code == 200, (
            f"{item.label} -> {item.url} gave {response.status_code}"
        )


def test_nav_appears_on_every_page(client):
    """Including the legacy dashboard, which had no navigation at all."""
    for path in PAGES:
        body = client.get(path).get_data(as_text=True)
        assert 'class="appnav"' in body, f"{path} has no navigation"
        for item in NAV_ITEMS:
            assert f'href="{item.url}"' in body, f"{path} is missing the {item.label} link"


def test_no_nav_entry_points_at_an_unbuilt_phase(client):
    """Phases 2-8 must not appear until they exist.

    ``/runs`` left this list in P3, which built it. The list shrinks as phases
    land; an entry removed while the page is still missing is caught by
    ``test_every_nav_target_resolves``, which would then 404.
    """
    forbidden = ("/projects", "/discovery", "/quality", "/leads/")
    for path in PAGES:
        body = client.get(path).get_data(as_text=True)
        nav = body[body.find('class="appnav"') : body.find("</nav>")]
        for url in forbidden:
            assert f'href="{url}"' not in nav, f"{path} links to unbuilt {url}"


def test_ai_settings_is_reachable_without_typing_a_url(client):
    """The original complaint, as an assertion."""
    body = client.get("/").get_data(as_text=True)
    assert 'href="/settings/ai"' in body
    assert 'href="/health/ai"' in body


def test_active_page_is_marked(client):
    for path, expected in [
        ("/configuration", "configuration"),
        ("/settings/ai", "settings_ai"),
        ("/health/ai", "health_ai"),
        ("/about", "about"),
    ]:
        body = client.get(path).get_data(as_text=True)
        item = next(i for i in NAV_ITEMS if i.key == expected)
        pattern = re.compile(
            r'href="' + re.escape(item.url) + r'"\s*\n?\s*class="[^"]*active', re.MULTILINE
        )
        assert pattern.search(body), f"{path} does not mark {expected} active"


def test_nav_status_pill_reflects_ai_state(client, settings):
    """Rendered server-side, so it is right on first paint."""
    body = client.get("/").get_data(as_text=True)
    assert "appnav-ai" in body
    assert "AI not configured" in body

    from src.dashboard.app import get_ai_service

    get_ai_service().credentials.set_key("sk-test0123456789abcdef", validate=False)
    body = client.get("/").get_data(as_text=True)
    assert "AI ready" in body


def test_nav_survives_a_broken_ai_service(client, monkeypatch):
    """A nav that can 500 the page it decorates is worse than no nav."""
    import src.dashboard.nav as nav_module

    def boom():
        raise RuntimeError("AI subsystem exploded")

    monkeypatch.setattr("src.dashboard.app.get_ai_service", boom)
    context = nav_module.nav_context()
    assert context["nav_ai"]["status"] == "unconfigured"
    assert client.get("/").status_code == 200


# ------------------------------------------------------------------- pages


@pytest.mark.parametrize("path", PAGES)
def test_page_renders_without_template_errors(client, path):
    response = client.get(path)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    # Jinja renders an unresolved expression as literal text rather than failing.
    assert "{{" not in body, f"{path} has an unrendered Jinja expression"
    assert "{%" not in body, f"{path} has an unrendered Jinja tag"
    assert "<title>" in body, f"{path} has no page title"


@pytest.mark.parametrize("path", PAGES)
def test_no_broken_internal_links(client, path):
    """Every internal href on every page must resolve."""
    body = client.get(path).get_data(as_text=True)
    hrefs = {h for h in re.findall(r'href="(/[^"#?]*)"', body) if not h.startswith("/static")}
    for href in sorted(hrefs):
        assert client.get(href).status_code == 200, f"{path} links to {href} which 404s"


def test_configuration_page_shows_every_config_surface(client):
    body = client.get("/configuration").get_data(as_text=True)
    for marker in ("subreddit-input", "high-kw-input", "med-kw-input", "query-input"):
        assert marker in body, f"configuration page is missing {marker}"
    for weight in (
        "setting-keyword_weight",
        "setting-upvote_weight",
        "setting-comment_weight",
        "setting-recency_weight",
        "setting-high_intent_multiplier",
        "setting-interval_minutes",
    ):
        assert weight in body, f"configuration page is missing {weight}"


def test_about_page_states_what_is_not_built(client):
    body = client.get("/about").get_data(as_text=True)
    assert "Not built yet" in body
    assert "Business Knowledge Base" in body
    # And explains the pnpm question, which is where people land first.
    assert "package.json" in body


# ------------------------------------------------------- dashboard declutter


def test_dashboard_no_longer_hosts_configuration(client):
    """Config moved to /configuration; the dashboard links to it instead."""
    body = client.get("/").get_data(as_text=True)
    for moved in ("high-kw-input", "med-kw-input", "query-input", "setting-keyword_weight"):
        assert moved not in body, f"{moved} is still on the dashboard"
    assert 'href="/configuration"' in body


def test_dashboard_keeps_operational_widgets(client):
    """Decluttering must not remove what the dashboard is *for*."""
    body = client.get("/").get_data(as_text=True)
    for kept in ("Total Leads", "New Leads", "Avg Intent Score", "leadsOverTime", "Run Scraper"):
        assert kept in body, f"dashboard lost {kept}"


def test_dashboard_has_the_ai_status_widget(client):
    body = client.get("/").get_data(as_text=True)
    assert 'id="ai-strip"' in body
    for metric in ("ai-model", "ai-validated", "ai-latency", "ai-cost", "ai-circuit", "ai-calls"):
        assert f'id="{metric}"' in body, f"AI widget missing {metric}"


def test_dashboard_javascript_has_no_orphan_element_references(client):
    """The bug this caught for real: handlers bound to removed inputs.

    They threw 'Cannot read properties of null' on every page load, which is
    invisible server-side and fatal to everything after it in the script.
    """
    body = client.get("/").get_data(as_text=True)
    ids = set(re.findall(r'id="([a-zA-Z0-9_-]+)"', body))
    referenced = set(re.findall(r"getElementById\('([a-zA-Z0-9_-]+)'\)", body))
    assert referenced <= ids, f"JS references non-existent ids: {sorted(referenced - ids)}"


def test_dashboard_onclick_handlers_are_all_defined(client):
    body = client.get("/").get_data(as_text=True)
    defined = set(re.findall(r"function ([a-zA-Z_][a-zA-Z0-9_]*)", body))
    called = set(re.findall(r'onclick="([a-zA-Z_][a-zA-Z0-9_]*)', body))
    assert called <= defined, f"onclick calls undefined: {sorted(called - defined)}"


# ---------------------------------------------------------------- regression


def test_legacy_endpoints_still_respond(client):
    """The 17 legacy endpoints keep their paths and shapes."""
    for path in (
        "/api/leads",
        "/api/leads/export",
        "/api/stats",
        "/api/settings",
        "/api/subreddits",
        "/api/keywords",
        "/api/queries",
    ):
        assert client.get(path).status_code == 200, f"{path} regressed"


def test_csv_export_still_has_thirteen_columns(client):
    body = client.get("/api/leads/export").get_data(as_text=True)
    header = body.lstrip("﻿").splitlines()[0]
    assert len(header.split(",")) == 13


def test_configuration_uses_only_existing_endpoints(client):
    """The Configuration page must not have invented an API."""
    body = client.get("/configuration").get_data(as_text=True)
    endpoints = set(re.findall(r"api\('(/api/[^']*)'", body))
    allowed_prefixes = ("/api/subreddits", "/api/keywords", "/api/queries", "/api/settings")
    for endpoint in endpoints:
        assert endpoint.startswith(allowed_prefixes), f"unexpected endpoint {endpoint}"
