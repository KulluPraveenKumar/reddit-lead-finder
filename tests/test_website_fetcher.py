"""P13 — ``WebsiteFetcher``: bounded crawl, direct egress, L1 cache, zero AI.

The three acceptance criteria [34 §P13](../docs/34-implementation-plan.md) sets
in bold each get a test that could actually fail:

* **direct egress** is asserted under ``proxy_only`` **with a healthy pool
  configured**, because under the shipped ``prefer_proxy`` + ``[direct, dc]``
  ladder direct is first anyway and the assertion would pass whatever the code
  did — P5's F3, which this project has now recorded five times;
* **zero fetches on an L1 hit** is a request counter reading exactly 0, not a
  timing or a log line;
* **zero AI calls** is ``COUNT(*) FROM ai_calls``, the idiom
  [35 §6](../docs/35-testing-strategy.md)'s P11 row pins as *"asserted ... not
  inferred from the fence"*.
"""

from __future__ import annotations

import datetime
import logging
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.ai.website_fetcher import (
    ALLOWED_SCHEMES,
    FALLBACK_STRIPPED_TAGS,
    PRIORITY_PATHS,
    THIN_CONTENT_CHARS,
    TRAFILATURA_MISSING_MESSAGE,
    ExtractedSite,
    InvalidWebsiteURL,
    WebsiteFetcher,
    WebsiteSettings,
    WebsiteUnreachable,
    content_hash,
    extract_text,
    normalise_url,
    priority_links,
    save_snapshot,
    validate_url,
)

SITES = Path(__file__).parent / "fixtures" / "sites"

BASE = "https://ledgerloop.example/"


def fixture(name: str) -> str:
    return (SITES / name).read_text(encoding="utf-8")


@pytest.fixture
def without_trafilatura(monkeypatch):
    """Force `import trafilatura` to fail, without uninstalling anything.

    The P12 idiom for a branch that would otherwise never run: that phase
    injected a `sqlite_vec` whose `load()` raises, *"because the extension is
    genuinely absent on every host measured and the branch would otherwise pass
    vacuously"* (docs/35 §6). Here the polarity is reversed — trafilatura is
    genuinely **present** on this host, so the fallback branch is the one that
    never ran, and the operator found the bug that hid in it.
    """
    import builtins

    from src.ai.website_fetcher import reset_trafilatura_warning

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "trafilatura" or name.startswith("trafilatura."):
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    monkeypatch.delitem(sys.modules, "trafilatura", raising=False)
    reset_trafilatura_warning()
    yield
    reset_trafilatura_warning()


@pytest.fixture
def db_session(temp_db):
    """A session on a migrated, empty database — the `test_repositories_runs` idiom."""
    from src.db import database

    with Session(bind=database.ENGINE, expire_on_commit=False) as session:
        yield session


# ------------------------------------------------------------ test doubles


class FakeClient:
    """Stands in for ``ProxiedHTTPClient`` at its one method.

    Records the ``request_class`` of every call, because that argument is the
    whole of this phase's egress guarantee: ``src/net/policy.py`` routes on it,
    and a fetcher that forgot to pass it would silently use the bulk default and
    crawl a customer's site through the proxy pool.
    """

    def __init__(self, pages: dict[str, tuple[int, str]], default=(404, "")):
        self.pages = pages
        self.default = default
        self.calls: list[dict] = []

    def get(self, url, *, request_class=None, allow_cache=True, **kwargs):
        self.calls.append({"url": url, "request_class": request_class})
        status, body = self.pages.get(url, self.default)
        if isinstance(body, BaseException):
            raise body
        return _Result(url, status, body)

    @property
    def urls(self) -> list[str]:
        return [call["url"] for call in self.calls]


class _Result:
    def __init__(self, url, status_code, text):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.final_url = url

    @property
    def ok(self):
        return self.status_code == 200


def a_site(**overrides) -> dict[str, tuple[int, str]]:
    pages = {
        BASE: (200, fixture("landing.html")),
        "https://ledgerloop.example/pricing": (200, fixture("pricing.html")),
        "https://ledgerloop.example/product": (200, fixture("landing.html")),
        "https://ledgerloop.example/features": (200, fixture("landing.html")),
        "https://ledgerloop.example/use-cases": (200, fixture("landing.html")),
        "https://ledgerloop.example/about": (200, fixture("landing.html")),
        "https://ledgerloop.example/customers": (200, fixture("landing.html")),
    }
    pages.update(overrides)
    return pages


# ------------------------------------------------------------- URL validation


class TestURLValidation:
    """AC: *"`file://` rejected at validation"*, and the allowlist behind it."""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "file://C:/Users/someone/.env",
            "javascript:alert(1)",
            "data:text/html,<h1>hi</h1>",
            "ftp://ledgerloop.example/",
            "gopher://ledgerloop.example/",
        ],
    )
    def test_a_non_http_scheme_is_rejected(self, url):
        """An **allowlist**, so the two schemes the plan names by example are not
        the only two that are refused. A denylist of `file` and `javascript`
        would have passed `data:` and `ftp:` — and the requirement is that the
        operator's disk is not reachable from a text box, not that two specific
        strings are."""
        with pytest.raises(InvalidWebsiteURL):
            validate_url(url)

    def test_the_rejection_carries_422(self):
        """P13 ships no route — `POST /api/projects` is P16's — so 422 lives on
        the exception rather than in a response. Without it P16 has to re-derive
        which failures are the caller's fault."""
        assert InvalidWebsiteURL.status_code == 422
        with pytest.raises(InvalidWebsiteURL) as caught:
            validate_url("file:///etc/passwd")
        assert caught.value.status_code == 422

    @pytest.mark.parametrize("url", ["", "   ", None, "https://", "http:///pricing"])
    def test_an_empty_or_hostless_url_is_rejected(self, url):
        with pytest.raises(InvalidWebsiteURL):
            validate_url(url)

    def test_a_bare_host_is_assumed_https(self):
        """The commonest thing an operator types. Refusing it would be pedantry."""
        assert validate_url("ledgerloop.example").startswith("https://ledgerloop.example")

    def test_the_allowlist_is_exactly_http_and_https(self):
        assert {"http", "https"} == ALLOWED_SCHEMES

    def test_validation_happens_before_any_request(self):
        """The point of the criterion: a `file://` URL must not reach the
        transport at all, so the check cannot live after the first fetch."""
        client = FakeClient({})
        with pytest.raises(InvalidWebsiteURL):
            WebsiteFetcher(client).fetch("file:///etc/passwd")
        assert client.calls == []


class TestNormalisation:
    def test_casing_and_a_trailing_slash_are_one_key(self):
        """`https://Example.com/` and `example.com` are one project, which is
        what makes them one L1 cache entry rather than two."""
        assert normalise_url("https://Example.com/") == normalise_url("example.com")
        assert normalise_url("HTTPS://EXAMPLE.COM/pricing") == "https://example.com"


# ------------------------------------------------------------------ crawl


class TestCrawlBudget:
    def test_the_page_budget_includes_the_landing_page(self):
        """`max_pages: 7` is a TOTAL. Reading it as seven *beyond* the landing
        page fetches eight and fails the "≤7 requests per project version"
        metric it was supposed to satisfy."""
        client = FakeClient(a_site())
        site = WebsiteFetcher(client).fetch(BASE)
        assert len(client.calls) == 7
        assert site.requests_made == 7
        assert site.pages_fetched == 7

    def test_a_smaller_budget_is_honoured_exactly(self):
        client = FakeClient(a_site())
        WebsiteFetcher(client, settings=WebsiteSettings(max_pages=3)).fetch(BASE)
        assert len(client.calls) == 3

    def test_a_budget_of_one_fetches_only_the_landing_page(self):
        client = FakeClient(a_site())
        WebsiteFetcher(client, settings=WebsiteSettings(max_pages=1)).fetch(BASE)
        assert client.urls == [BASE]

    def test_priority_paths_are_visited_in_priority_order(self):
        client = FakeClient(a_site())
        WebsiteFetcher(client).fetch(BASE)
        assert client.urls[1:] == [
            "https://ledgerloop.example/pricing",
            "https://ledgerloop.example/product",
            "https://ledgerloop.example/features",
            "https://ledgerloop.example/use-cases",
            "https://ledgerloop.example/about",
            "https://ledgerloop.example/customers",
        ]

    def test_non_priority_internal_pages_are_not_fetched(self):
        """The landing fixture links `/docs`, `/login`, `/integrations` and
        `/bank-reconciliation`. A crawler that followed every internal link would
        spend the budget on a login form."""
        client = FakeClient(a_site())
        WebsiteFetcher(client).fetch(BASE)
        for path in ("/docs", "/login", "/integrations", "/bank-reconciliation"):
            assert not any(url.endswith(path) for url in client.urls)

    def test_offsite_links_are_never_followed(self):
        """The footer links a competitor's `/pricing`. Following it would turn a
        bounded crawl of the customer's site into an unbounded crawl of the web —
        and would put a competitor's copy into the customer's knowledge base."""
        client = FakeClient(a_site())
        WebsiteFetcher(client).fetch(BASE)
        assert all("competitor.example" not in url for url in client.urls)

    def test_the_text_is_truncated_to_the_character_budget(self):
        client = FakeClient(a_site())
        site = WebsiteFetcher(client, settings=WebsiteSettings(max_total_chars=1_000)).fetch(BASE)
        assert len(site.text) == 1_000

    def test_the_shipped_budget_is_forty_kilobytes(self):
        assert WebsiteSettings().max_total_chars == 40_000

    def test_a_fragment_and_a_query_do_not_buy_three_requests(self):
        html = (
            "<html><body><a href='/pricing'>a</a>"
            "<a href='/pricing#plans'>b</a>"
            "<a href='/pricing?ref=nav'>c</a></body></html>"
        )
        assert priority_links(html, BASE, 6) == ["https://ledgerloop.example/pricing"]

    def test_a_link_back_to_the_landing_page_is_not_refetched(self):
        html = "<html><body><a href='/'>home</a><a href='/pricing'>p</a></body></html>"
        assert priority_links(html, "https://ledgerloop.example/pricing", 6) == []


class TestPriorityPaths:
    def test_the_eight_are_the_ones_the_pipeline_document_names(self):
        assert PRIORITY_PATHS == (
            "/pricing",
            "/product",
            "/features",
            "/solutions",
            "/use-cases",
            "/about",
            "/customers",
            "/how-it-works",
        )

    @pytest.mark.parametrize("path", ["/pricing/enterprise", "/about-us", "/pricing/"])
    def test_a_prefix_counts(self, path):
        """Matching exactly would miss most real sites."""
        html = f"<html><body><a href='{path}'>x</a></body></html>"
        assert priority_links(html, BASE, 6)

    def test_a_substring_does_not(self):
        """`/blog/how-we-priced-it` is not a pricing page, and treating it as one
        spends a request from a budget of six on a blog post."""
        html = "<html><body><a href='/blog/how-we-priced-it'>x</a></body></html>"
        assert priority_links(html, BASE, 6) == []


# --------------------------------------------------------------- failures


class TestFailureHandling:
    def test_a_404_landing_page_fails_with_a_readable_message(self):
        """AC: *"a 404 fails with a readable message"*.

        404 classifies as FATAL, so `ProxiedHTTPClient` **returns** a
        `FetchResult` carrying the status rather than raising. Handling only the
        raising shape is how this criterion turns into an unhandled exception
        with a proxy label in it.
        """
        client = FakeClient({BASE: (404, fixture("not_found.html"))})
        with pytest.raises(WebsiteUnreachable) as caught:
            WebsiteFetcher(client).fetch(BASE)
        message = str(caught.value)
        assert "404" in message
        assert BASE in message
        assert "proxy" not in message.lower()

    def test_an_unreachable_landing_page_fails_too(self):
        client = FakeClient({BASE: (200, RuntimeError("connection reset"))})
        with pytest.raises(WebsiteUnreachable):
            WebsiteFetcher(client).fetch(BASE)

    def test_a_failing_internal_page_is_skipped_and_the_crawl_continues(self, caplog):
        """docs/06 §2.3: *"skipped, logged, run continues"*. Six good pages beat
        one exception."""
        pages = a_site(**{"https://ledgerloop.example/pricing": (500, "boom")})
        client = FakeClient(pages)
        with caplog.at_level(logging.INFO):
            site = WebsiteFetcher(client).fetch(BASE)
        assert site.pages_fetched == 6
        assert len(client.calls) == 7
        assert "/pricing" in caplog.text

    def test_an_internal_page_that_raises_is_also_survivable(self):
        pages = a_site(**{"https://ledgerloop.example/about": (200, RuntimeError("timeout"))})
        site = WebsiteFetcher(FakeClient(pages)).fetch(BASE)
        assert site.pages_fetched == 6


class TestThinContent:
    def test_an_spa_shell_is_thin_and_the_fetch_still_completes(self):
        """AC: *"SPA shell sets `thin` and the run still completes"*. This
        project ships no headless browser, so the shell is the whole answer and
        flagging it is the entire mitigation."""
        client = FakeClient({BASE: (200, fixture("spa_shell.html"))})
        site = WebsiteFetcher(client).fetch(BASE)
        assert site.thin is True
        assert site.content_hash
        assert len(site.text) < THIN_CONTENT_CHARS

    def test_thin_content_is_logged_with_its_cause(self, caplog):
        client = FakeClient({BASE: (200, fixture("spa_shell.html"))})
        with caplog.at_level(logging.WARNING):
            WebsiteFetcher(client).fetch(BASE)
        assert "thin" in caplog.text.lower()

    def test_a_real_site_is_not_thin(self):
        site = WebsiteFetcher(FakeClient(a_site())).fetch(BASE)
        assert site.thin is False

    def test_the_threshold_is_five_hundred(self):
        assert THIN_CONTENT_CHARS == 500


# -------------------------------------------------------------- extraction


class TestExtraction:
    def test_the_landing_copy_survives_extraction(self):
        text = extract_text(fixture("landing.html"), BASE)
        assert "Close the books without the spreadsheet" in text

    def test_boilerplate_does_not_dominate(self):
        """The same nav appearing on seven pages would eat a 40 KB budget."""
        text = extract_text(fixture("landing.html"), BASE)
        assert text.count("Log in") <= 1

    def test_a_page_with_no_article_still_yields_its_text(self, without_trafilatura):
        """🔴 **The regression the operator found, and the reason it survived.**

        This test named the BeautifulSoup fallback and **never exercised it**:
        trafilatura was installed, it read `spa_shell.html` perfectly well, and
        the assertion passed on its output. With trafilatura absent the fallback
        actually ran — and returned the bare title `Nimbus`, because `noscript`
        had been added to the strip list and the `<noscript>` block is the only
        sentence a JavaScript-only page has.

        It now forces the fallback, so it cannot pass for the wrong reason again.

        **And it asserts the fallback's exact output, not just that the word is
        present.** `"JavaScript" in text` is true of trafilatura's answer too, so
        that assertion would survive the fixture being silently broken — which is
        the same class of mistake all over again. Only the fallback keeps the
        `<title>`, so the leading `Nimbus` is what makes this test unable to pass
        unless the BeautifulSoup branch really ran. Both strings measured
        2026-08-15.
        """
        text = extract_text(fixture("spa_shell.html"), BASE)
        assert text == "Nimbus\nThis application requires JavaScript."
        assert text != "This application requires JavaScript.", (
            "that is trafilatura's output — the without_trafilatura fixture did not take effect"
        )

    def test_the_fallback_and_trafilatura_agree_that_the_shell_has_a_sentence(self):
        """Both paths must find the same sentence. Asserting only the installed
        path is what let the two diverge silently in the first place."""
        assert "JavaScript" in extract_text(fixture("spa_shell.html"), BASE)

    def test_noscript_is_not_stripped_by_the_fallback(self, without_trafilatura):
        """On a JS-only shell it is frequently the only human-readable text."""
        html = "<html><body><div id='root'></div><noscript>Enable JS.</noscript></body></html>"
        assert "Enable JS." in extract_text(html, BASE)

    def test_the_fallback_strips_exactly_the_five_documented_tags(self):
        """14 §9.1 names five. A sixth is not a free improvement — the sixth this
        phase shipped discarded a whole page's content."""
        assert FALLBACK_STRIPPED_TAGS == ("script", "style", "nav", "footer", "header")

    def test_the_fallback_still_removes_the_menu(self, without_trafilatura):
        """The fix must not have turned the strip list off altogether."""
        text = extract_text(fixture("landing.html"), BASE)
        assert "Close the books without the spreadsheet" in text
        assert text.count("Log in") == 0

    def test_empty_markup_yields_empty_text(self):
        assert extract_text("") == ""
        assert extract_text("   ") == ""

    def test_the_fallback_runs_when_trafilatura_raises(self, monkeypatch):
        """One page's extractor failing must not lose the other six.

        `pytest.importorskip` rather than a bare `import`: this test needs the
        real module to patch, and a bare import made the **suite** require a
        dependency the **module** is written to survive without — which is how
        the operator's run produced a collection-time `ModuleNotFoundError`
        rather than a readable skip.
        """
        trafilatura = pytest.importorskip("trafilatura")

        monkeypatch.setattr(
            trafilatura, "extract", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
        )
        assert "Close the books" in extract_text(fixture("landing.html"), BASE)


class TestMissingDependency:
    """trafilatura is **required**. Its absence must be loud, not absorbed.

    The operator's `ModuleNotFoundError` was the *good* outcome — a test said so
    plainly. What the shipped module did on that same host was quieter and worse:
    every page fell back, the text got worse, and one INFO line per page said
    `trafilatura could not read <url>`, which reads exactly like a routine
    per-page parse failure. A broken install and a stubborn page are different
    problems and now log differently.
    """

    def test_the_fixture_really_does_block_the_import(self, without_trafilatura):
        """The fixture is load-bearing for six tests, so it is checked directly.

        It patches `builtins.__import__`, which every other import on the same
        code path also goes through — `extract_text` does `from bs4 import
        BeautifulSoup` *after* the blocked import. If the passthrough were wrong,
        the fallback would raise instead of running and several tests here would
        be passing on an unintended path.
        """
        with pytest.raises(ModuleNotFoundError):
            import trafilatura  # noqa: F401

        from bs4 import BeautifulSoup  # noqa: F401  - must still import fine

    def test_the_whole_fetch_still_works_without_trafilatura(self, without_trafilatura):
        """It degrades rather than crashing — the fallback is a real fallback."""
        site = WebsiteFetcher(FakeClient(a_site())).fetch(BASE)
        assert site.requests_made == 7
        assert "Close the books without the spreadsheet" in site.text
        assert site.thin is False

    def test_the_absence_is_warned_with_the_command_that_fixes_it(
        self, without_trafilatura, caplog
    ):
        with caplog.at_level(logging.WARNING):
            extract_text(fixture("landing.html"), BASE)
        assert TRAFILATURA_MISSING_MESSAGE in caplog.text
        assert "pip install -r requirements.txt" in caplog.text

    def test_it_is_a_warning_not_an_info_line(self, without_trafilatura, caplog):
        """A per-page INFO is what hid it. A broken installation is not routine."""
        with caplog.at_level(logging.INFO):
            extract_text(fixture("landing.html"), BASE)
        levels = {r.levelname for r in caplog.records if "trafilatura" in r.getMessage()}
        assert "WARNING" in levels

    def test_it_warns_once_per_process_not_once_per_page(self, without_trafilatura, caplog):
        """Seven pages a run would make it noise, and noise gets filtered out."""
        with caplog.at_level(logging.WARNING):
            for _ in range(7):
                extract_text(fixture("landing.html"), BASE)
        matching = [r for r in caplog.records if TRAFILATURA_MISSING_MESSAGE in r.getMessage()]
        assert len(matching) == 1

    def test_a_per_page_failure_is_not_reported_as_a_broken_install(self, monkeypatch, caplog):
        """The other half of the distinction: a page trafilatura chokes on must
        NOT tell the operator to reinstall anything."""
        trafilatura = pytest.importorskip("trafilatura")
        monkeypatch.setattr(
            trafilatura, "extract", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
        )
        with caplog.at_level(logging.INFO):
            extract_text(fixture("landing.html"), BASE)
        assert "pip install" not in caplog.text


class TestContentHash:
    def test_identical_text_hashes_identically(self):
        assert content_hash("abc") == content_hash("abc")

    def test_it_is_sha256_and_sixty_four_hex_characters(self):
        digest = content_hash("abc")
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")

    def test_it_is_over_the_extracted_text_not_the_markup(self):
        """A build id or a rotating asset hash in the markup changes on every
        response. Hashing the raw HTML would make an unchanged site look new on
        every fetch and defeat P14's L2 profile cache entirely."""
        html = fixture("landing.html")
        noisy = html.replace("bundle.js", "bundle.a91f4c.js")
        assert content_hash(extract_text(html, BASE)) == content_hash(extract_text(noisy, BASE))


# ------------------------------------------------------------ direct egress


class TestDirectEgress:
    """AC: *"Fetch goes **direct**, not through the proxy pool"* — R18 / AD-25."""

    def test_every_request_carries_the_website_class(self):
        client = FakeClient(a_site())
        WebsiteFetcher(client).fetch(BASE)
        assert {call["request_class"] for call in client.calls} == {"website"}

    def test_it_goes_direct_even_under_proxy_only_with_a_healthy_pool(self, monkeypatch):
        """**The only configuration in which a bug here is visible.**

        Under the shipped `prefer_proxy` + `[direct, dc]` the direct provider is
        first anyway, so an assertion made there passes whatever the fetcher
        does. `proxy_only` with a *healthy* pool is the case that separates "the
        code asked for the website class" from "direct happened to be first".
        """
        import requests

        from src.net.http_client import ProxiedHTTPClient
        from src.net.policy import ALWAYS_DIRECT, NetworkPolicy, Policy, RequestClass
        from src.net.providers import DirectProvider, WebshareDatacenterProvider
        from src.net.proxy_manager import ProxyManager
        from src.net.proxy_models import ProxyEndpoint

        direct_session = _ScriptedSession(fixture("landing.html"))
        pool_session = _ScriptedSession("<html><body>proxied</body></html>")

        pool = ProxyManager([ProxyEndpoint("203.0.113.10", 8080, "u", "p")], delay_range=(0.0, 0.0))
        pool.session_for = lambda endpoint: pool_session  # noqa: ARG005
        monkeypatch.setattr(DirectProvider, "session", lambda self: direct_session)
        monkeypatch.setattr(requests, "Session", lambda: direct_session)

        policy = NetworkPolicy(
            [DirectProvider("direct"), WebshareDatacenterProvider("dc", pool)],
            policy=Policy.PROXY_ONLY.value,
            ladder=["dc", "direct"],
            classes_by_provider={
                "direct": {c.value for c in RequestClass},
                "dc": {"html", "comments", "validation"},
            },
            direct_classes=set(ALWAYS_DIRECT),
        )
        client = ProxiedHTTPClient(policy, cache=None)

        result = client.get(BASE, request_class=RequestClass.WEBSITE.value)

        assert result.provider == "direct"
        assert pool_session.calls == 0, "a customer's site was crawled through the proxy pool"
        assert direct_session.calls == 1

    def test_the_fetcher_end_to_end_never_touches_the_pool(self, monkeypatch):
        """The criterion as the operator would state it, with nothing faked
        between the fetcher and the policy.

        The two tests above check the halves — that the fetcher asks for the
        `website` class, and that the policy routes that class direct. Neither
        would catch a fetcher wired to a client it built with a different policy,
        which is the whole failure this criterion is about.
        """
        import requests

        from src.net.http_client import ProxiedHTTPClient
        from src.net.policy import ALWAYS_DIRECT, NetworkPolicy, Policy, RequestClass
        from src.net.providers import DirectProvider, WebshareDatacenterProvider
        from src.net.proxy_manager import ProxyManager
        from src.net.proxy_models import ProxyEndpoint

        direct_session = _ScriptedSession(fixture("landing.html"))
        pool_session = _ScriptedSession(fixture("landing.html"))
        pool = ProxyManager([ProxyEndpoint("203.0.113.10", 8080, "u", "p")], delay_range=(0.0, 0.0))
        pool.session_for = lambda endpoint: pool_session  # noqa: ARG005
        monkeypatch.setattr(DirectProvider, "session", lambda self: direct_session)
        monkeypatch.setattr(requests, "Session", lambda: direct_session)

        policy = NetworkPolicy(
            [DirectProvider("direct"), WebshareDatacenterProvider("dc", pool)],
            policy=Policy.PROXY_ONLY.value,
            ladder=["dc", "direct"],
            classes_by_provider={
                "direct": {c.value for c in RequestClass},
                "dc": {"html", "comments", "validation"},
            },
            direct_classes=set(ALWAYS_DIRECT),
        )
        site = WebsiteFetcher(ProxiedHTTPClient(policy, cache=None)).fetch(BASE)

        assert site.requests_made == 7
        assert pool_session.calls == 0, "a customer's site was crawled through the proxy pool"
        assert direct_session.calls == 7

    def test_the_default_client_asks_for_generic_block_signatures(self):
        """docs/08 §10 requires a customer's site to be read *"without Reddit's
        interstitial heuristics being applied to it"*. `ProxiedHTTPClient`
        defaults to the generic set today — but a requirement held only by
        another module's default is not held, and if that default ever gains a
        target-specific marker a customer's page starts reading as a soft block.
        """
        from src.net import blocks

        fetcher = WebsiteFetcher(settings=WebsiteSettings())
        assert fetcher.client.block_signatures.app_markers == ()
        assert fetcher.client.block_signatures.soft_markers == blocks.GENERIC_SOFT_MARKERS

    def test_the_default_client_has_no_transport_cache(self):
        """Two caches answering the same question means a zero-fetch assertion
        satisfied by either proves neither."""
        assert WebsiteFetcher().client.cache is None

    def test_the_per_page_timeout_reaches_the_transport(self):
        fetcher = WebsiteFetcher(settings=WebsiteSettings(per_page_timeout=3))
        assert fetcher.client.timeout[1] == 3.0


class _ScriptedSession:
    """Answers every GET with one body, and counts."""

    def __init__(self, body: str):
        self.body = body
        self.calls = 0
        self.headers: dict = {}

    def get(self, url, **kwargs):
        self.calls += 1
        return _FakeResponse(200, self.body, url)


class _FakeRaw:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, amount, decode_content=True):
        return self._body[:amount]


class _FakeResponse:
    def __init__(self, status, body, url=""):
        self.status_code = status
        self.raw = _FakeRaw(body.encode("utf-8"))
        self.encoding = "utf-8"
        self.headers: dict = {}
        self.url = url

    def close(self):
        pass


# ---------------------------------------------------------------- L1 cache


def _project(session, url=BASE):
    """A project row from a fixture, never from a writer.

    [PHASE-12-HANDOVER §3.2](../docs/PHASE-12-HANDOVER.md): nothing creates a
    project until P16's `project add`, and P13 must not become a second writer
    that P16 then has to reconcile with.
    """
    from src.db.models import Project

    project = Project(name="Ledgerloop", website_url=url, normalized_url=normalise_url(url))
    session.add(project)
    session.flush()
    return project


class TestL1Cache:
    def test_a_second_analysis_inside_the_window_makes_zero_fetches(self, db_session):
        """**The bold acceptance criterion**: *"unchanged fingerprint within 7
        days makes **zero** fetches"*. Counted, not timed."""
        project = _project(db_session)
        client = FakeClient(a_site())
        fetcher = WebsiteFetcher(client)

        first = fetcher.fetch(BASE, session=db_session, project_id=project.id)
        before = len(client.calls)
        second = fetcher.fetch(BASE, session=db_session, project_id=project.id)

        assert len(client.calls) == before, "the L1 hit made a request"
        assert second.requests_made == 0
        assert second.from_cache is True
        assert second.content_hash == first.content_hash

    def test_a_cache_hit_returns_the_same_url_shape_as_a_fresh_fetch(self, db_session):
        """`ExtractedSite.url` must not change shape depending on whether the
        cache hit.

        The row is stored under the **normalised** key (`https://x.example`,
        scheme+host, no trailing slash) while a fresh fetch reports the
        **validated** target (`https://x.example/`, path kept). Returning
        `row.url` on the cached path made the two differ — and P14 reads this
        attribute, so it would have surfaced as a duplicate row three phases
        later rather than as an error here.
        """
        project = _project(db_session)
        fetcher = WebsiteFetcher(FakeClient(a_site()))
        first = fetcher.fetch(BASE, session=db_session, project_id=project.id)
        second = fetcher.fetch(BASE, session=db_session, project_id=project.id)

        assert second.from_cache is True
        assert second.url == first.url

    def test_the_row_is_still_keyed_on_the_normalised_url(self, db_session):
        """The fix above must not have moved the *storage* key — that is what
        makes `https://Example.com/` and `example.com` one cache entry."""
        from src.db.models import WebsiteSnapshot

        project = _project(db_session)
        WebsiteFetcher(FakeClient(a_site())).fetch(BASE, session=db_session, project_id=project.id)
        row = db_session.query(WebsiteSnapshot).one()
        assert row.url == "https://ledgerloop.example"
        assert row.url != BASE

    def test_a_snapshot_older_than_the_window_is_not_reused(self, db_session):
        from src.db.models import WebsiteSnapshot

        project = _project(db_session)
        client = FakeClient(a_site())
        fetcher = WebsiteFetcher(client)
        fetcher.fetch(BASE, session=db_session, project_id=project.id)

        stale = db_session.query(WebsiteSnapshot).one()
        stale.fetched_at = stale.fetched_at - datetime.timedelta(days=8)
        db_session.flush()

        again = fetcher.fetch(BASE, session=db_session, project_id=project.id)
        assert again.from_cache is False
        assert again.requests_made == 7

    def test_the_expired_refetch_writes_a_second_row_even_when_the_text_is_identical(
        self, db_session
    ):
        """`website_snapshots` exists *"so a re-analysis can compare against the
        text the previous one saw"*. Suppressing an insert whose hash happened to
        match would save a few kilobytes and delete the only reason the table is
        separate from `projects`."""
        from src.db.models import WebsiteSnapshot

        project = _project(db_session)
        fetcher = WebsiteFetcher(FakeClient(a_site()))
        fetcher.fetch(BASE, session=db_session, project_id=project.id)
        row = db_session.query(WebsiteSnapshot).one()
        row.fetched_at = row.fetched_at - datetime.timedelta(days=8)
        db_session.flush()

        fetcher.fetch(BASE, session=db_session, project_id=project.id)

        rows = db_session.query(WebsiteSnapshot).all()
        assert len(rows) == 2
        assert rows[0].content_hash == rows[1].content_hash

    def test_casing_and_a_trailing_slash_hit_the_same_cache_entry(self, db_session):
        project = _project(db_session)
        client = FakeClient(a_site())
        fetcher = WebsiteFetcher(client)
        fetcher.fetch(BASE, session=db_session, project_id=project.id)
        before = len(client.calls)

        fetcher.fetch("https://LedgerLoop.example", session=db_session, project_id=project.id)
        assert len(client.calls) == before

    def test_another_projects_snapshot_is_not_reused(self, db_session):
        """The key is (project, URL). Two projects on one URL is unusual and a
        cross-project reuse would be a data-isolation bug, not a saving."""
        one = _project(db_session)
        two = _project(db_session, "https://other.example/")
        client = FakeClient(a_site())
        fetcher = WebsiteFetcher(client)
        fetcher.fetch(BASE, session=db_session, project_id=one.id)
        before = len(client.calls)

        fetcher.fetch(BASE, session=db_session, project_id=two.id)
        assert len(client.calls) > before

    def test_a_zero_ttl_disables_the_cache(self, db_session):
        """Turning it off means *no reuse*, not *everything expires instantly* —
        the two happen to coincide, and only one of them is what an operator
        setting 0 is asking for."""
        project = _project(db_session)
        client = FakeClient(a_site())
        fetcher = WebsiteFetcher(client, settings=WebsiteSettings(cache_ttl_days=0))
        fetcher.fetch(BASE, session=db_session, project_id=project.id)
        before = len(client.calls)
        second = fetcher.fetch(BASE, session=db_session, project_id=project.id)
        assert len(client.calls) > before
        assert second.from_cache is False

    def test_without_a_session_there_is_no_cache_and_no_row(self, db_session):
        from src.db.models import WebsiteSnapshot

        client = FakeClient(a_site())
        fetcher = WebsiteFetcher(client)
        fetcher.fetch(BASE)
        fetcher.fetch(BASE)
        assert len(client.calls) == 14
        assert db_session.query(WebsiteSnapshot).count() == 0

    def test_a_cache_hit_reports_that_it_saw_no_markup(self, db_session):
        """`website_snapshots` stores text and no HTML, so four of the six local
        signals cannot be recomputed from a reuse. Reporting that is what stops a
        consumer recording "this company uses no analytics" as a fact."""
        project = _project(db_session)
        fetcher = WebsiteFetcher(FakeClient(a_site()))
        fetcher.fetch(BASE, session=db_session, project_id=project.id)
        second = fetcher.fetch(BASE, session=db_session, project_id=project.id)
        assert second.html_pages == ()


class TestSnapshotPersistence:
    def test_the_row_records_what_was_read(self, db_session):
        from src.db.models import WebsiteSnapshot

        project = _project(db_session)
        site = WebsiteFetcher(FakeClient(a_site())).fetch(
            BASE, session=db_session, project_id=project.id
        )
        row = db_session.query(WebsiteSnapshot).one()
        assert row.project_id == project.id
        assert row.url == normalise_url(BASE)
        assert row.pages_fetched == 7
        assert row.content_hash == site.content_hash
        assert row.extracted_text == site.text

    def test_save_snapshot_flushes_but_does_not_commit(self, db_session):
        """Nothing in this module holds the SQLite write lock across a fetch —
        the defect that blocked P3's sign-off. It takes a session; it does not
        open or close one."""
        project = _project(db_session)
        site = ExtractedSite(BASE, (("/", "text"),), "text", content_hash("text"), False)
        row = save_snapshot(db_session, project.id, BASE, site)
        assert row.id is not None
        db_session.rollback()
        from src.db.models import WebsiteSnapshot

        assert db_session.query(WebsiteSnapshot).count() == 0


# ----------------------------------------------------------------- no AI


class TestZeroAI:
    def test_the_phase_makes_no_ai_call(self, db_session):
        """**Bold acceptance criterion**, asserted against `ai_calls` rather than
        inferred from the import fence — the idiom docs/35 §6's P11 row pins.
        A fence proves nobody *imported* the AI layer, not that nobody
        *called* it."""
        from src.db.models import AICall

        project = _project(db_session)
        fetcher = WebsiteFetcher(FakeClient(a_site()))
        fetcher.fetch(BASE, session=db_session, project_id=project.id)
        fetcher.fetch(BASE, session=db_session, project_id=project.id)

        assert db_session.query(AICall).count() == 0

    def test_neither_module_imports_a_provider(self):
        """Belt to the braces above: the modules are inside `src/ai/`, so grep
        fence 2 does not cover them and nothing else would notice a provider
        import creeping in."""
        import ast
        from pathlib import Path as _Path

        for name in ("website_fetcher", "site_signals"):
            source = (_Path("src") / "ai" / f"{name}.py").read_text(encoding="utf-8")
            imported = {
                node.module or ""
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.ImportFrom)
            } | {
                alias.name
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            assert not any("providers" in module for module in imported)
            assert not any(module.endswith("ai.service") for module in imported)


# -------------------------------------------------------------------- CLI


class TestCLI:
    """`python -m src.ai.website_fetcher <url>` — the phase's only observable surface.

    P13 ships no page and no route, so without this the manual gate would have
    nothing to look at and *"read the source and trust it"* is not a test step.
    Same basis as P5's `feed` CLI, P9's `python -m src.rules` and P10's
    `python -m src.dedupe`.
    """

    def test_the_report_states_what_was_read(self):
        site = WebsiteFetcher(FakeClient(a_site())).fetch(BASE)
        from src.ai.site_signals import extract
        from src.ai.website_fetcher import render_report

        report = render_report(site, extract(site))
        assert "Requests made    7" in report
        assert "Pages read       7" in report
        assert site.content_hash in report
        assert "no AI call was made" in report

    def test_the_report_names_thin_content_in_words(self):
        """A tester reading `Thin content     no` must not have to know what a
        boolean means, and must not have to guess the threshold."""
        from src.ai.website_fetcher import render_report

        site = WebsiteFetcher(FakeClient({BASE: (200, fixture("spa_shell.html"))})).fetch(BASE)
        assert "Thin content     YES — under 500 characters" in render_report(site)

    def test_it_writes_nothing_to_the_database(self, db_session, monkeypatch):
        """PHASE-12-HANDOVER §3.2 reserves the first `projects` row for P16. A
        CLI that created one to demonstrate the cache would be exactly the second
        writer that handover forbids."""
        from src.ai import website_fetcher
        from src.db.models import Project, WebsiteSnapshot

        monkeypatch.setattr(website_fetcher, "WebsiteFetcher", lambda **kw: _StubFetcher(a_site()))
        assert website_fetcher.main([BASE]) == 0
        assert db_session.query(Project).count() == 0
        assert db_session.query(WebsiteSnapshot).count() == 0

    def test_a_failure_prints_the_readable_message_not_a_traceback(self, capsys, monkeypatch):
        from src.ai import website_fetcher

        monkeypatch.setattr(
            website_fetcher,
            "WebsiteFetcher",
            lambda **kw: _StubFetcher({BASE: (404, fixture("not_found.html"))}),
        )
        assert website_fetcher.main([BASE]) == 1
        out = capsys.readouterr().out
        assert out.startswith("FAILED:")
        assert "404" in out
        assert "Traceback" not in out

    def test_an_invalid_scheme_is_reported_not_raised(self, capsys, monkeypatch):
        from src.ai import website_fetcher

        monkeypatch.setattr(website_fetcher, "WebsiteFetcher", lambda **kw: _StubFetcher({}))
        assert website_fetcher.main(["file:///etc/passwd"]) == 1
        assert "http or https" in capsys.readouterr().out


class _StubFetcher:
    """A real `WebsiteFetcher` over a `FakeClient`, so `main` makes no network call.

    `main` is the only thing in this phase that reaches a live website; a test
    that let it would breach the offline guarantee rather than verify anything.
    """

    def __init__(self, pages):
        self._real = WebsiteFetcher(FakeClient(pages))

    def fetch(self, url, **kwargs):
        return self._real.fetch(url, **kwargs)


# ---------------------------------------------------------------- settings


class TestWebsiteSettings:
    def test_deleting_the_block_reproduces_the_defaults(self):
        """The rollback property `rules:`, `dedup:`, `notify:` and `discovery:`
        all carry. This is the fifth."""
        assert WebsiteSettings.from_config(None) == WebsiteSettings()
        assert WebsiteSettings.from_config({}) == WebsiteSettings()
        assert WebsiteSettings.from_config({"website": None}) == WebsiteSettings()

    def test_the_defaults_are_the_pipeline_documents_constants(self):
        settings = WebsiteSettings()
        assert (
            settings.max_pages,
            settings.max_depth,
            settings.max_total_chars,
            settings.per_page_timeout,
        ) == (7, 2, 40_000, 15.0)
        assert settings.cache_ttl_days == 7

    def test_the_shipped_config_file_matches_the_defaults(self):
        """A config whose values drifted from the documented constants would make
        every test above describe a system nobody runs."""
        from src.config import load_config

        assert WebsiteSettings.from_config(load_config()) == WebsiteSettings()

    def test_an_unknown_key_is_ignored_rather_than_fatal(self):
        """A config that refused to load because of a typo turns a typo into an
        outage."""
        assert WebsiteSettings.from_config({"website": {"nonsense": 1}}) == WebsiteSettings()

    @pytest.mark.parametrize(
        "block",
        [
            {"max_pages": 0},
            {"max_depth": 0},
            {"max_total_chars": 0},
            {"per_page_timeout": 0},
            {"cache_ttl_days": -1},
        ],
    )
    def test_a_nonsensical_value_is_refused_with_its_key_named(self, block):
        with pytest.raises(ValueError, match="website."):
            WebsiteSettings.from_config({"website": block})
