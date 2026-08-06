"""Phase 2: proxy pool, transport, block detection, parsers, lead dedup.

Every test here is offline. The proxy pool is exercised with endpoints that are
never dialled, and the parsers run against saved fixtures, so the suite gives
the same answer whether or not Reddit is reachable today.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from sqlalchemy import inspect

from src.net import blocks, retry
from src.net.blocks import BlockKind
from src.net.cache import HTTPCache
from src.net.http_client import ProxiedHTTPClient
from src.net.proxy_manager import ProxyManager
from src.net.proxy_models import (
    ProxyEndpoint,
    ProxyParseError,
    ProxyState,
    parse_proxy_line,
)
from src.net.retry import NetErrorClass, ProxyExhaustedError, RetryPolicy
from src.net.user_agents import PROFILES, headers_for, pick_profile

FIXTURES = Path(__file__).parent / "fixtures" / "reddit"

# Credentials that must never appear in a repr, a log line, a database column or
# an HTTP health payload. Distinctive strings so a substring check is meaningful.
SECRET_USER = "znmvcxlq"
SECRET_PASS = "5h7k2p9qwerty"


def _endpoint(host="1.2.3.4", port=8080) -> ProxyEndpoint:
    # The credential fields are named with a leading underscore so that the
    # dataclass excludes them from repr(). That makes them positional-ish here;
    # the underscore in the keyword is the point, not a typo.
    return ProxyEndpoint(host, port, SECRET_USER, SECRET_PASS)


# ---------------------------------------------------------------- credentials


class TestCredentialsNeverLeak:
    """AC11. The proxy file is the only place the username and password exist."""

    def test_repr_and_str_show_only_host_and_port(self):
        endpoint = _endpoint()
        for rendered in (repr(endpoint), str(endpoint), f"{endpoint}", endpoint.label):
            assert SECRET_USER not in rendered
            assert SECRET_PASS not in rendered
            assert "1.2.3.4:8080" in rendered or rendered == "1.2.3.4:8080"

    def test_url_does_contain_credentials(self):
        """The one method that must expose them -- so the others provably need not.

        If ``url()`` did not embed the credentials the proxy would not
        authenticate, and a test asserting "no credentials anywhere" would pass
        against a pool that could not connect. Pinning it here makes the
        redaction elsewhere a deliberate choice rather than an accident.
        """
        assert SECRET_PASS in _endpoint().url()

    def test_parse_error_does_not_echo_the_line(self):
        """A malformed line is usually a *correct* line with a typo -- it still
        holds a real password, and an error message ends up in logs and tickets.
        """
        bad = f"1.2.3.4:notaport:{SECRET_USER}:{SECRET_PASS}"
        with pytest.raises(ProxyParseError) as excinfo:
            parse_proxy_line(bad)
        message = str(excinfo.value)
        assert SECRET_USER not in message
        assert SECRET_PASS not in message

    def test_pool_snapshot_is_credential_free(self):
        pool = ProxyManager([_endpoint(), _endpoint("5.6.7.8", 9090)])
        rendered = repr(pool.snapshot())
        assert SECRET_USER not in rendered
        assert SECRET_PASS not in rendered

    def test_proxies_table_has_no_credential_columns(self, temp_db):
        """Schema-level, not convention-level.

        A ``username`` column would eventually be filled by someone reasonably
        trying to make the pool survive a restart. Its absence is what makes a
        copied ``leads.db`` harmless.
        """
        from src.db import database

        columns = {c["name"] for c in inspect(database.ENGINE).get_columns("proxies")}
        forbidden = {"username", "password", "user", "passwd", "secret", "credentials", "auth"}
        assert not (columns & forbidden), f"credential column in proxies: {columns & forbidden}"

    def test_logging_a_failure_emits_no_credentials(self, caplog):
        """AC11 end-to-end: drive the pool through failures and read the log."""
        endpoint = _endpoint()
        pool = ProxyManager([endpoint], blacklist_threshold=2)

        with caplog.at_level(logging.DEBUG):
            for _ in range(3):
                pool.record_failure(endpoint, "connection refused")
            pool.snapshot()

        captured = "\n".join(r.getMessage() for r in caplog.records)
        assert SECRET_USER not in captured
        assert SECRET_PASS not in captured


# ------------------------------------------------------------------ parsing


class TestProxyParsing:
    def test_host_port_user_pass(self):
        endpoint = parse_proxy_line(f"1.2.3.4:6754:{SECRET_USER}:{SECRET_PASS}")
        assert (endpoint.host, endpoint.port) == ("1.2.3.4", 6754)
        assert endpoint.label == "1.2.3.4:6754"

    def test_blank_and_comment_lines_are_skipped(self):
        assert parse_proxy_line("") is None
        assert parse_proxy_line("   ") is None
        assert parse_proxy_line("# a comment") is None

    def test_real_proxy_file_parses(self):
        """Uses the operator's actual file when present -- format drift is a real
        failure mode, and a synthetic fixture would never notice it.

        The path comes from ``PROXY_FILE`` rather than being hardcoded: the file
        holds live credentials and therefore lives outside the repository (R15),
        so its location differs per machine and must not be baked into a test.
        """
        from src.net.proxy_models import parse_proxy_file

        configured = os.environ.get("PROXY_FILE")
        if not configured:
            pytest.skip("PROXY_FILE is not set")
        real = Path(configured)
        if not real.exists():
            pytest.skip(f"PROXY_FILE points at a missing file: {real}")
        endpoints = parse_proxy_file(real)
        assert len(endpoints) >= 1
        assert all(e.host and e.port for e in endpoints)


# ------------------------------------------------------------- header profiles


class TestHeaderCoherence:
    """The block that started Phase 2 was a fingerprint problem, not an IP one.

    The legacy header set paired a Chrome User-Agent with Firefox's
    ``Accept-Language`` and omitted ``Sec-CH-UA`` entirely. Every proxy and the
    local IP got 403; a coherent Chrome profile got 200 through the same proxy
    seconds later. These tests keep the profiles internally consistent.
    """

    def test_chrome_profiles_carry_client_hints(self):
        for profile in PROFILES:
            headers = profile.as_dict()
            if "Chrome/" not in headers["User-Agent"] or "Firefox/" in headers["User-Agent"]:
                continue
            # Chrome sends the client-hint headers lower-cased on the wire, so
            # the comparison is case-insensitive rather than assuming a casing.
            lowered = {k.lower() for k in headers}
            assert "sec-ch-ua" in lowered, f"Chrome profile without sec-ch-ua: {profile.name}"
            assert "sec-ch-ua-platform" in lowered
            assert "sec-fetch-mode" in lowered

    def test_firefox_profiles_do_not_carry_chrome_client_hints(self):
        """Firefox does not send Sec-CH-UA. Sending it is the same class of
        mistake as the original Chrome/Firefox mismatch, in the other direction.
        """
        for profile in PROFILES:
            headers = profile.as_dict()
            if "Firefox/" not in headers["User-Agent"]:
                continue
            lowered = {k.lower() for k in headers}
            assert "sec-ch-ua" not in lowered, f"Firefox profile sending sec-ch-ua: {profile.name}"

    def test_every_profile_declares_a_user_agent_and_accept_language(self):
        for profile in PROFILES:
            headers = profile.as_dict()
            assert headers.get("User-Agent")
            assert headers.get("Accept-Language")

    def test_profile_is_stable_per_seed(self):
        """A proxy that changes browser identity between requests is more
        conspicuous than one that never rotates at all."""
        first = pick_profile("1.2.3.4:8080")
        for _ in range(20):
            assert pick_profile("1.2.3.4:8080").name == first.name

    def test_different_seeds_can_differ(self):
        names = {pick_profile(f"10.0.0.{i}:8080").name for i in range(40)}
        assert len(names) > 1, "every proxy got the same profile -- seeding is broken"

    def test_referer_sets_same_origin_fetch_site(self):
        with_ref = headers_for("seed", referer="https://old.reddit.com/r/SaaS/")
        assert with_ref["Sec-Fetch-Site"] == "same-origin"
        assert with_ref["Referer"] == "https://old.reddit.com/r/SaaS/"

    def test_no_referer_is_not_same_origin(self):
        assert headers_for("seed").get("Sec-Fetch-Site") != "same-origin"
        assert "Referer" not in headers_for("seed")


# --------------------------------------------------------------- block detect


class TestBlockClassification:
    def test_403_is_hard(self):
        verdict = blocks.classify(403, "<html></html>")
        assert verdict.kind is BlockKind.HARD
        assert verdict.blocked

    def test_429_is_hard(self):
        assert blocks.classify(429, "").kind is BlockKind.HARD

    def test_5xx_is_hard(self):
        assert blocks.classify(503, "").kind is BlockKind.HARD

    def test_good_page_with_content_is_not_blocked(self):
        html = "<html><title>SaaS</title><body><div class='thing'>x</div></body></html>"
        verdict = blocks.classify(200, html, expect_selector_hits=25)
        assert verdict.kind is BlockKind.NONE
        assert not verdict.blocked
        assert verdict.cacheable

    def test_soft_block_fixture_is_detected(self):
        """The dangerous case: HTTP 200, 311 KB of HTML, zero posts.

        Without this check the scraper reports "no posts found" and caches the
        interstitial, so the block persists for the whole TTL and looks like a
        quiet subreddit.
        """
        html = (FIXTURES / "soft_block_interstitial.html").read_text(
            encoding="utf-8", errors="replace"
        )
        verdict = blocks.classify(200, html, expect_selector_hits=0)
        assert verdict.kind is BlockKind.SOFT
        assert verdict.blocked

    # The captured interstitial happens to trip two independent detection paths
    # (its title AND its new-Reddit markers), so the fixture test above passes
    # even if one of them is broken. Each path therefore gets its own minimal
    # case, so a regression in one is not masked by the other.

    def test_soft_marker_path_alone(self):
        marker = blocks._SOFT_MARKERS[0][0]
        html = f"<html><title>ok</title><body>{marker}</body></html>"
        assert blocks.classify(200, html, expect_selector_hits=5).kind is BlockKind.SOFT

    def test_interstitial_title_path_alone(self):
        """ "Welcome to Reddit" served in place of a subreddit -- 200, real HTML,
        no posts. This is the exact shape observed live."""
        html = "<html><title>Welcome to Reddit</title><body><p>hi</p></body></html>"
        assert blocks.classify(200, html, expect_selector_hits=0).kind is BlockKind.SOFT

    def test_new_reddit_marker_path_alone(self):
        html = "<html><title>r/SaaS</title><body><shreddit-app></shreddit-app></body></html>"
        assert blocks.classify(200, html, expect_selector_hits=0).kind is BlockKind.SOFT

    def test_a_block_is_never_cacheable(self):
        for kind_html, hits in ((403, ""), (200, "<html>shreddit-app</html>")):
            verdict = blocks.classify(kind_html, hits if isinstance(hits, str) else "")
            if verdict.blocked:
                assert not verdict.cacheable

    def test_empty_is_distinct_from_soft(self):
        """A genuinely empty subreddit must not be reported as a block, or an
        operator chases a proxy problem that does not exist."""
        html = "<html><title>r/emptysub</title><body></body></html>"
        assert blocks.classify(200, html, expect_selector_hits=0).kind is BlockKind.EMPTY

    def test_new_reddit_markers_only_count_when_content_is_missing(self):
        html = "<html><body><shreddit-app></shreddit-app><div class='thing'>p</div></body></html>"
        assert blocks.classify(200, html, expect_selector_hits=12).kind is BlockKind.NONE


# --------------------------------------------------------------------- retry


class TestRetryClassification:
    def test_403_rotates_rather_than_backs_off(self):
        """Waiting does not fix a per-IP block; a different exit IP does."""
        assert retry.classify(403) is NetErrorClass.ROTATE

    def test_429_backs_off(self):
        assert retry.classify(429) is NetErrorClass.BACKOFF

    def test_404_is_fatal(self):
        """Retrying a 404 through ten proxies burns the pool for a page that
        does not exist on any of them."""
        assert retry.classify(404) is NetErrorClass.FATAL

    def test_200_needs_no_retry(self):
        assert retry.classify(200) is NetErrorClass.NONE

    def test_transport_exception_rotates(self):
        assert retry.classify(None, ConnectionError("refused")) is NetErrorClass.ROTATE

    def test_policy_stops_at_max_attempts(self):
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(NetErrorClass.ROTATE, attempt=1)
        assert not policy.should_retry(NetErrorClass.ROTATE, attempt=3)

    def test_policy_never_retries_fatal(self):
        assert not RetryPolicy(max_attempts=5).should_retry(NetErrorClass.FATAL, attempt=1)

    def test_backoff_grows(self):
        policy = RetryPolicy(base_delay=1.0)
        assert policy.delay_for(NetErrorClass.BACKOFF, attempt=3) > policy.delay_for(
            NetErrorClass.BACKOFF, attempt=1
        )


# ---------------------------------------------------------------- proxy pool


class TestProxyManager:
    def test_rotation_visits_every_proxy_before_repeating(self):
        endpoints = [_endpoint(f"10.0.0.{i}") for i in range(4)]
        pool = ProxyManager(endpoints, delay_range=(0.0, 0.0))
        seen = [pool.acquire().label for _ in range(4)]
        assert len(set(seen)) == 4, f"pool repeated before exhausting rotation: {seen}"

    def test_repeated_failures_blacklist_and_open_the_circuit(self):
        endpoint = _endpoint()
        pool = ProxyManager([endpoint], delay_range=(0.0, 0.0), blacklist_threshold=2)
        assert not pool.circuit_open

        pool.record_failure(endpoint, "timeout")
        pool.record_failure(endpoint, "timeout")

        assert pool.stats_for(endpoint).state is ProxyState.BLACKLISTED
        assert pool.circuit_open

    def test_success_clears_the_consecutive_failure_run(self):
        """Consecutive, not cumulative. A proxy that fails twice, works, then
        fails twice again is flaky, not dead, and blacklisting it would shrink
        a ten-proxy pool to nothing over a long run.
        """
        endpoint = _endpoint()
        pool = ProxyManager([endpoint], delay_range=(0.0, 0.0), blacklist_threshold=3)
        pool.record_failure(endpoint, "timeout")
        pool.record_failure(endpoint, "timeout")
        pool.record_success(endpoint, 120)
        assert pool.stats_for(endpoint).consecutive_failures == 0
        pool.record_failure(endpoint, "timeout")
        assert pool.stats_for(endpoint).state is not ProxyState.BLACKLISTED

    def test_acquire_raises_when_the_pool_is_exhausted(self):
        endpoint = _endpoint()
        pool = ProxyManager([endpoint], delay_range=(0.0, 0.0), blacklist_threshold=1)
        pool.record_failure(endpoint, "dead")
        with pytest.raises(ProxyExhaustedError):
            pool.acquire()

    def test_local_ip_leak_is_detected(self):
        endpoint = _endpoint()
        pool = ProxyManager([endpoint])
        pool.stats_for(endpoint).exit_ip = "203.0.113.9"
        assert pool.local_ip_leaked("203.0.113.9") == [endpoint.label]
        assert pool.local_ip_leaked("198.51.100.1") == []

    def test_one_session_per_proxy(self):
        """Shared cookies across exit IPs are a correlation signal -- the same
        session token arriving from ten addresses links them together."""
        a, b = _endpoint("1.1.1.1"), _endpoint("2.2.2.2")
        pool = ProxyManager([a, b])
        assert pool.session_for(a) is pool.session_for(a)
        assert pool.session_for(a) is not pool.session_for(b)


class TestFailClosed:
    """AC12. With no usable proxy the run must stop, not fall back."""

    def test_fail_closed_client_raises_instead_of_using_the_local_ip(self):
        endpoint = _endpoint()
        pool = ProxyManager(
            [endpoint], delay_range=(0.0, 0.0), blacklist_threshold=1, fail_closed=True
        )
        pool.record_failure(endpoint, "dead")

        client = ProxiedHTTPClient(pool)
        with pytest.raises(ProxyExhaustedError):
            client.get("https://old.reddit.com/r/SaaS/new/")

    def test_fail_closed_exit_is_clean(self):
        """A distinct exception type, not a generic crash: the caller has to be
        able to tell "the pool is empty" from "the parser broke"."""
        endpoint = _endpoint()
        pool = ProxyManager(
            [endpoint], delay_range=(0.0, 0.0), blacklist_threshold=1, fail_closed=True
        )
        pool.record_failure(endpoint, "dead")
        client = ProxiedHTTPClient(pool)
        try:
            client.get("https://old.reddit.com/r/SaaS/new/")
        except ProxyExhaustedError as exc:
            assert SECRET_PASS not in str(exc)
        else:
            pytest.fail("fail_closed pool did not raise")


# ----------------------------------------------------------- fake transport


class _FakeRaw:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, amount, decode_content=True):
        return self._body[:amount]


class _FakeResponse:
    def __init__(self, status: int, body: str, headers: dict | None = None, url: str = ""):
        self.status_code = status
        self.raw = _FakeRaw(body.encode("utf-8"))
        self.encoding = "utf-8"
        self.headers = headers or {}
        self.url = url

    def close(self):
        pass


class _FakeSession:
    """Replays a script of responses. Each entry is a response or an exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        item = self.script.pop(0) if self.script else _FakeResponse(200, "<html></html>")
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def no_sleep(monkeypatch):
    """The retry ladder sleeps with a growing backoff.

    Left real, a five-attempt ladder adds tens of seconds to the suite and makes
    timing-sensitive assertions flaky. The delays are asserted through
    RetryPolicy directly instead.
    """
    slept: list[float] = []
    monkeypatch.setattr("src.net.http_client.time.sleep", slept.append)
    return slept


def _client_with(script, **pool_kwargs):
    """A client whose pool hands out a scripted fake session."""
    endpoints = pool_kwargs.pop("endpoints", None) or [_endpoint("9.9.9.1"), _endpoint("9.9.9.2")]
    pool = ProxyManager(endpoints, delay_range=(0.0, 0.0), **pool_kwargs)
    session = _FakeSession(script)
    pool.session_for = lambda endpoint: session  # noqa: ARG005
    return ProxiedHTTPClient(pool), pool, session


class TestTransport:
    def test_successful_fetch_returns_the_body(self, no_sleep):
        html = "<html><title>r/SaaS</title><div class='thing'>post</div></html>"
        client, pool, _ = _client_with([_FakeResponse(200, html)])
        result = client.get("https://old.reddit.com/r/SaaS/new/")
        assert result.ok
        assert result.status_code == 200
        assert "post" in result.text
        assert result.attempts == 1

    def test_403_rotates_to_another_proxy_and_succeeds(self, no_sleep):
        """The live failure mode: one exit IP is blocked, another is not."""
        client, pool, _ = _client_with(
            [_FakeResponse(403, "denied"), _FakeResponse(200, "<div class='thing'>ok</div>")]
        )
        result = client.get("https://old.reddit.com/r/SaaS/new/")
        assert result.ok
        assert result.attempts == 2

    def test_soft_block_is_not_treated_as_success(self, no_sleep):
        """HTTP 200 carrying an interstitial must rotate, not be returned.

        Returning it would report "no posts found" and -- worse -- cache the
        interstitial for the whole TTL.
        """
        interstitial = "<html><title>Welcome to Reddit</title><body></body></html>"
        good = "<html><div class='thing'>post</div></html>"
        client, pool, _ = _client_with([_FakeResponse(200, interstitial), _FakeResponse(200, good)])
        result = client.get("https://old.reddit.com/r/SaaS/new/", expect_selector="div.thing")
        assert result.ok
        assert result.attempts == 2
        assert "Welcome to Reddit" not in result.text

    def test_an_empty_200_is_returned_but_not_cached(self, no_sleep):
        """The case the ``cacheable`` gate exists for.

        A 200 with the right shape and zero content is *not* classified as a
        block -- a genuinely quiet subreddit looks identical -- so it is
        returned to the caller. But it must not be cached: if it was in fact a
        block the classifier could not confirm, caching it would make the
        emptiness outlive its cause for the whole TTL.
        """
        empty = "<html><title>r/quiet</title><body></body></html>"
        cache = HTTPCache(memory_only=True)
        client, pool, _ = _client_with([_FakeResponse(200, empty)])
        client.cache = cache
        url = "https://old.reddit.com/r/quiet/new/"

        result = client.get(url, expect_selector="div.thing")
        assert result.status_code == 200
        assert result.verdict.kind is BlockKind.EMPTY
        assert cache.get(url) is None, "an unconfirmed-empty page was cached"

    def test_a_soft_block_is_never_cached(self, no_sleep):
        interstitial = "<html><title>Welcome to Reddit</title><body></body></html>"
        good = "<html><div class='thing'>post</div></html>"
        cache = HTTPCache(memory_only=True)
        client, pool, _ = _client_with([_FakeResponse(200, interstitial), _FakeResponse(200, good)])
        client.cache = cache
        url = "https://old.reddit.com/r/SaaS/new/"
        client.get(url, expect_selector="div.thing")
        assert cache.get(url) is not None
        assert "Welcome to Reddit" not in cache.get(url)

    def test_successful_fetch_is_cached_and_the_second_call_is_a_hit(self, no_sleep):
        cache = HTTPCache(memory_only=True)
        client, pool, session = _client_with([_FakeResponse(200, "<div class='thing'>x</div>")])
        client.cache = cache
        url = "https://old.reddit.com/r/SaaS/new/"
        client.get(url)
        second = client.get(url)
        assert second.from_cache
        assert len(session.calls) == 1, "cache hit still issued a network call"

    def test_allow_cache_false_bypasses_the_cache(self, no_sleep):
        cache = HTTPCache(memory_only=True)
        client, pool, session = _client_with(
            [
                _FakeResponse(200, "<div class='thing'>a</div>"),
                _FakeResponse(200, "<div class='thing'>b</div>"),
            ]
        )
        client.cache = cache
        url = "https://old.reddit.com/r/SaaS/new/"
        client.get(url)
        second = client.get(url, allow_cache=False)
        assert not second.from_cache
        assert len(session.calls) == 2

    def test_404_is_returned_not_retried(self, no_sleep):
        """Retrying a 404 through every proxy burns the pool for a page that
        does not exist on any of them."""
        client, pool, session = _client_with([_FakeResponse(404, "not found")])
        result = client.get("https://old.reddit.com/r/nope/new/")
        assert result.status_code == 404
        assert not result.ok
        assert len(session.calls) == 1

    def test_persistent_blocks_raise_after_max_attempts(self, no_sleep):
        client, pool, _ = _client_with([_FakeResponse(403, "denied")] * 6)
        with pytest.raises(retry.BlockedError):
            client.get("https://old.reddit.com/r/SaaS/new/")

    def test_transport_exception_is_retried_then_recovers(self, no_sleep):
        import requests as _requests

        client, pool, _ = _client_with(
            [
                _requests.exceptions.ConnectionError("refused"),
                _FakeResponse(200, "<div class='thing'>ok</div>"),
            ]
        )
        assert client.get("https://old.reddit.com/r/SaaS/new/").ok

    def test_bare_oserror_is_classified_not_escaped(self, no_sleep):
        """requests does not always wrap socket errors, so a bare OSError can
        reach the transport. Unclassified, it would escape as an unhandled crash
        instead of rotating to the next proxy."""
        client, pool, _ = _client_with(
            [OSError("connection reset"), _FakeResponse(200, "<div class='thing'>ok</div>")]
        )
        assert client.get("https://old.reddit.com/r/SaaS/new/").ok

    def test_response_body_is_capped(self, no_sleep):
        """A hostile or broken response must not be read into memory unbounded."""
        client, pool, _ = _client_with([_FakeResponse(200, "<div class='thing'>" + "x" * 50_000)])
        client.max_bytes = 1000
        result = client.get("https://old.reddit.com/r/SaaS/new/")
        assert len(result.text) <= 1000

    def test_failures_are_recorded_against_the_proxy_that_failed(self, no_sleep):
        client, pool, _ = _client_with(
            [_FakeResponse(403, "denied"), _FakeResponse(200, "<div class='thing'>ok</div>")]
        )
        client.get("https://old.reddit.com/r/SaaS/new/")
        assert sum(s.failures for s in pool._stats.values()) == 1
        assert sum(s.blocked_responses for s in pool._stats.values()) == 1

    def test_metrics_count_requests_blocks_and_cache_hits(self, no_sleep):
        cache = HTTPCache(memory_only=True)
        client, pool, _ = _client_with(
            [_FakeResponse(403, "denied"), _FakeResponse(200, "<div class='thing'>ok</div>")]
        )
        client.cache = cache
        url = "https://old.reddit.com/r/SaaS/new/"
        client.get(url)
        client.get(url)
        metrics = client.metrics.to_dict()
        assert metrics["requests"] == 2
        assert metrics["successes"] == 1
        assert metrics["blocked"] == 1
        assert metrics["cache_hits"] == 1

    def test_referer_produces_coherent_headers(self, no_sleep):
        client, pool, session = _client_with([_FakeResponse(200, "<div class='thing'>x</div>")])
        client.get(
            "https://old.reddit.com/r/SaaS/new/?count=25",
            referer="https://old.reddit.com/r/SaaS/new/",
        )
        headers = session.calls[0]["headers"]
        assert headers["Referer"] == "https://old.reddit.com/r/SaaS/new/"
        assert headers["Sec-Fetch-Site"] == "same-origin"

    def test_429_retries_on_a_different_proxy(self, no_sleep):
        """AC8. Rate limiting is per-exit-IP, so the retry must change IP.

        Retrying the same proxy would re-hit the same bucket and burn the wait.
        """
        used: list[str] = []
        endpoints = [_endpoint("7.7.7.1"), _endpoint("7.7.7.2")]
        pool = ProxyManager(endpoints, delay_range=(0.0, 0.0))
        session = _FakeSession(
            [
                _FakeResponse(429, "slow down", headers={"Retry-After": "30"}),
                _FakeResponse(200, "<div class='thing'>ok</div>"),
            ]
        )

        def tracking_session_for(endpoint):
            used.append(endpoint.label)
            return session

        pool.session_for = tracking_session_for
        client = ProxiedHTTPClient(pool)

        assert client.get("https://old.reddit.com/r/SaaS/new/").ok
        assert len(used) == 2
        assert used[0] != used[1], f"429 retried on the same proxy: {used}"

    def test_429_retry_after_is_honoured(self, no_sleep):
        """AC8's wait. The slept duration is captured rather than timed."""
        client, pool, _ = _client_with(
            [
                _FakeResponse(429, "slow", headers={"Retry-After": "30"}),
                _FakeResponse(200, "<div class='thing'>ok</div>"),
            ]
        )
        client.get("https://old.reddit.com/r/SaaS/new/")
        assert no_sleep, "no backoff was applied to a 429"
        assert max(no_sleep) >= 30.0, f"Retry-After: 30 was ignored (slept {no_sleep})"

    def test_cloudflare_interstitial_is_neither_parsed_nor_cached(self, no_sleep):
        """AC9. "Just a moment" arrives with HTTP 200 and looks like a real page."""
        cache = HTTPCache(memory_only=True)
        challenge = "<html><title>Just a moment...</title><body>checking</body></html>"
        good = "<html><div class='thing'>post</div></html>"
        client, pool, _ = _client_with([_FakeResponse(200, challenge), _FakeResponse(200, good)])
        client.cache = cache
        url = "https://old.reddit.com/r/SaaS/new/"

        result = client.get(url, expect_selector="div.thing")
        assert "Just a moment" not in result.text
        assert "Just a moment" not in (cache.get(url) or "")

    def test_every_request_exits_through_a_proxy(self, no_sleep):
        """AC2. Zero requests may leave from the local IP."""
        client, pool, session = _client_with(
            [
                _FakeResponse(403, "no"),
                _FakeResponse(403, "no"),
                _FakeResponse(200, "<div class='thing'>ok</div>"),
            ]
        )
        client.get("https://old.reddit.com/r/SaaS/new/")
        assert len(session.calls) == 3
        for call in session.calls:
            assert call["proxies"], "a request went out with no proxy configured"
            assert call["proxies"]["https"].endswith(("9.9.9.1:8080", "9.9.9.2:8080"))

    def test_blacklisting_one_proxy_mid_run_does_not_fail_the_run(self, no_sleep):
        """AC3. Losing a proxy must degrade throughput, not the run."""
        endpoints = [_endpoint("8.8.8.1"), _endpoint("8.8.8.2"), _endpoint("8.8.8.3")]
        client, pool, _ = _client_with(
            [_FakeResponse(403, "no"), _FakeResponse(200, "<div class='thing'>ok</div>")],
            endpoints=endpoints,
            blacklist_threshold=1,
        )
        result = client.get("https://old.reddit.com/r/SaaS/new/")
        assert result.ok
        snapshot = pool.snapshot()
        assert snapshot.blacklisted == 1
        assert not snapshot.circuit_open, "one dead proxy emptied a three-proxy pool"

    def test_429_consults_retry_after(self):
        """Asserted through the policy, not a wall clock -- a timing assertion
        here would be slow and flaky."""
        policy = RetryPolicy(base_delay=1.0)
        honoured = policy.delay_for(NetErrorClass.BACKOFF, attempt=1, retry_after=30.0)
        ignored = policy.delay_for(NetErrorClass.BACKOFF, attempt=1)
        assert honoured > ignored


# --------------------------------------------------------------------- cache


class TestHTTPCacheDatabaseLayer:
    """The DB layer survives a restart; the memory layer does not."""

    def test_body_round_trips_through_the_database(self, temp_db):
        cache = HTTPCache(memory_only=False)
        cache.put("https://example.com/a", "<html>persisted</html>")
        cache.clear_memory()
        assert cache.get("https://example.com/a") == "<html>persisted</html>"

    def test_a_second_cache_instance_sees_the_row(self, temp_db):
        """What "survives a restart" actually means."""
        HTTPCache(memory_only=False).put("https://example.com/b", "durable")
        assert HTTPCache(memory_only=False).get("https://example.com/b") == "durable"

    def test_expired_database_row_is_a_miss_and_is_removed(self, temp_db):
        from src.db.database import get_session
        from src.db.models import HttpCache as HttpCacheRow

        cache = HTTPCache(memory_only=False, ttl=0)
        cache.put("https://example.com/c", "stale")
        cache.clear_memory()
        assert cache.get("https://example.com/c") is None

        session = get_session()
        try:
            assert session.query(HttpCacheRow).filter_by(url="https://example.com/c").count() == 0
        finally:
            session.close()

    def test_put_twice_updates_rather_than_duplicating(self, temp_db):
        from src.db.database import get_session
        from src.db.models import HttpCache as HttpCacheRow

        cache = HTTPCache(memory_only=False)
        cache.put("https://example.com/d", "first")
        cache.put("https://example.com/d", "second")
        cache.clear_memory()
        assert cache.get("https://example.com/d") == "second"

        session = get_session()
        try:
            assert session.query(HttpCacheRow).count() == 1
        finally:
            session.close()

    def test_hits_are_counted_on_the_row(self, temp_db):
        from src.db.database import get_session
        from src.db.models import HttpCache as HttpCacheRow

        cache = HTTPCache(memory_only=False)
        cache.put("https://example.com/e", "body")
        cache.clear_memory()
        cache.get("https://example.com/e")

        session = get_session()
        try:
            assert session.query(HttpCacheRow).one().hits == 1
        finally:
            session.close()

    def test_purge_expired_removes_only_expired_rows(self, temp_db):
        from src.db.database import get_session
        from src.db.models import HttpCache as HttpCacheRow

        HTTPCache(memory_only=False, ttl=0).put("https://example.com/old", "stale")
        HTTPCache(memory_only=False, ttl=3600).put("https://example.com/new", "fresh")

        assert HTTPCache(memory_only=False).purge_expired() == 1

        session = get_session()
        try:
            remaining = {row.url for row in session.query(HttpCacheRow).all()}
            assert remaining == {"https://example.com/new"}
        finally:
            session.close()

    def test_cache_failure_never_breaks_the_caller(self):
        """No database configured at all. A cache is an optimisation; it must
        degrade to a miss rather than take down the fetch it was speeding up."""
        cache = HTTPCache(memory_only=False)
        cache.put("https://example.com/f", "body")
        cache.clear_memory()
        assert cache.get("https://example.com/f") in (None, "body")

    def test_hit_ratio(self):
        cache = HTTPCache(memory_only=True)
        cache.put("https://example.com/g", "x")
        cache.get("https://example.com/g")
        cache.get("https://example.com/absent")
        assert cache.hit_ratio == 0.5


class TestNetMetricsPersistence:
    def test_flush_writes_one_row_per_counter(self, temp_db):
        from src.db.database import get_session
        from src.db.models import Metric
        from src.net.metrics import NetMetrics

        metrics = NetMetrics()
        metrics.record_request(ok=True, latency_ms=120, proxy="1.2.3.4:8080")
        metrics.record_request(ok=False, proxy="1.2.3.4:8080", blocked=True)
        metrics.record_cache_hit()
        metrics.flush_to_db()

        session = get_session()
        try:
            rows = {m.name: m.value for m in session.query(Metric).all()}
        finally:
            session.close()

        assert rows["net.requests"] == 2
        assert rows["net.successes"] == 1
        assert rows["net.failures"] == 1
        assert rows["net.blocked"] == 1
        assert rows["net.cache_hits"] == 1

    def test_flush_without_a_database_does_not_raise(self):
        """Metrics must never break the run they are measuring."""
        from src.net.metrics import NetMetrics

        NetMetrics().flush_to_db()

    def test_percentiles_and_rates(self):
        from src.net.metrics import NetMetrics

        metrics = NetMetrics()
        for latency in range(1, 101):
            metrics.record_request(ok=True, latency_ms=latency)
        metrics.record_request(ok=False)
        assert metrics.mean_latency_ms == 50
        assert 90 <= metrics.p95_latency_ms <= 100
        assert round(metrics.success_rate, 2) == round(100 / 101, 2)

    def test_reset_clears_everything(self):
        from src.net.metrics import NetMetrics

        metrics = NetMetrics()
        metrics.record_request(ok=True, latency_ms=10, proxy="p")
        metrics.reset()
        assert metrics.to_dict()["requests"] == 0
        assert metrics.to_dict()["requests_by_proxy"] == {}


class TestHTTPCache:
    def test_put_then_get_returns_the_body(self):
        cache = HTTPCache(memory_only=True)
        cache.put("https://example.com/a", "<html>body</html>")
        assert cache.get("https://example.com/a") == "<html>body</html>"

    def test_miss_returns_none(self):
        assert HTTPCache(memory_only=True).get("https://example.com/nope") is None

    def test_expired_entry_is_a_miss(self):
        cache = HTTPCache(memory_only=True, ttl=0)
        cache.put("https://example.com/a", "stale")
        assert cache.get("https://example.com/a") is None

    def test_distinct_urls_do_not_collide(self):
        cache = HTTPCache(memory_only=True)
        cache.put("https://example.com/a", "A")
        cache.put("https://example.com/b", "B")
        assert cache.get("https://example.com/a") == "A"
        assert cache.get("https://example.com/b") == "B"

    def test_hits_and_misses_are_counted(self):
        cache = HTTPCache(memory_only=True)
        cache.put("https://example.com/a", "A")
        cache.get("https://example.com/a")
        cache.get("https://example.com/missing")
        assert cache.hits == 1
        assert cache.misses == 1


# ------------------------------------------------------------------ parsers


class TestRedditParsers:
    """Golden-fixture tests. No network, and no dependence on today's Reddit."""

    @pytest.fixture
    def client(self):
        from src.reddit_client import RedditClient

        return RedditClient({"proxy": {"enabled": False}})

    def test_search_page_parses_posts(self, client):
        html = (FIXTURES / "search_page1.html").read_text(encoding="utf-8", errors="replace")
        posts, _ = client._parse_search_results(html)
        assert len(posts) > 0
        first = posts[0]
        assert first["id"].startswith("t3_") or first["id"]
        assert first["title"]
        assert first["url"].startswith("http")

    def test_search_results_carry_no_score(self, client):
        """AC6. Search HTML has no score, so it must be None -- never 0, which
        would read as "nobody upvoted this"."""
        html = (FIXTURES / "search_page1.html").read_text(encoding="utf-8", errors="replace")
        posts, _ = client._parse_search_results(html)
        assert all(p["score"] is None for p in posts)

    def test_search_next_link_paginates_posts_not_subreddits(self, client):
        """The Phase 2 headline bug.

        The search page has **two** ``.nav-buttons`` groups. The first paginates
        the *subreddit* sidebar (``after=t5_``, zero post links); the second
        paginates the posts (``after=t3_``). Following the first paginates
        forever and returns no posts, which is exactly the 25-result ceiling
        that was reported.
        """
        html = (FIXTURES / "search_page1.html").read_text(encoding="utf-8", errors="replace")
        _, next_url = client._parse_search_results(html)
        if next_url is None:
            pytest.skip("fixture has no next page")
        assert "after=t3_" in next_url, f"followed the subreddit pager: {next_url}"
        assert "after=t5_" not in next_url
        assert "type=sr" not in next_url

    def test_listing_page_parses_posts_with_real_scores(self, client):
        html = (FIXTURES / "listing_page1.html").read_text(encoding="utf-8", errors="replace")
        posts, _ = client._parse_listing(html)
        assert len(posts) > 0
        assert any(p["score"] is not None for p in posts), "listing scores were all None"
        # Mutation testing during the fixture anonymisation found this gap: breaking the
        # title selector left every post with an empty title and the test still passed.
        # A listing whose posts have no title is a parser regression, not a quiet subreddit.
        assert all(p["title"] for p in posts), "listing titles were empty"

    def test_soft_block_fixture_yields_no_posts(self, client):
        """The parser must not invent posts from an interstitial, and the block
        classifier -- not the parser -- is what reports why the page was empty.
        """
        html = (FIXTURES / "soft_block_interstitial.html").read_text(
            encoding="utf-8", errors="replace"
        )
        posts, _ = client._parse_listing(html)
        assert posts == []


class TestSearchQueryEncoding:
    """AC5. A query with a space, ``&`` or ``#`` must not corrupt the URL."""

    @pytest.fixture
    def client(self):
        from src.reddit_client import RedditClient

        return RedditClient({"proxy": {"enabled": False}})

    def test_ampersand_is_encoded_not_treated_as_a_separator(self, client):
        url = client._search_url("CRM & sales", subreddit=None, sort="new", time_filter=None)
        assert "%26" in url
        # A raw & would end the q parameter and silently search for "CRM " only.
        assert "q=CRM+%26+sales" in url or "q=CRM%20%26%20sales" in url

    def test_hash_is_encoded_not_treated_as_a_fragment(self, client):
        url = client._search_url("#startup", subreddit=None, sort="new", time_filter=None)
        assert "%23" in url
        assert "#" not in url.split("?", 1)[1]

    def test_space_is_encoded(self, client):
        url = client._search_url("best CRM", subreddit=None, sort="new", time_filter=None)
        assert " " not in url


# --------------------------------------------------------------- lead repo


class TestLeadRepository:
    """AC13. One dedup query per page, not one per post."""

    def _repo(self):
        from src.db.database import get_session
        from src.db.repositories.leads import LeadRepository

        session = get_session()
        return LeadRepository(session), session

    def _add(self, session, reddit_id, **kw):
        import datetime

        from src.db.models import Lead

        session.add(
            Lead(
                reddit_id=reddit_id,
                subreddit=kw.get("subreddit", "SaaS"),
                author="someone",
                title=kw.get("title", "a title"),
                body="",
                url=f"https://old.reddit.com/{reddit_id}",
                intent_score=kw.get("intent_score", 5.0),
                matched_keywords=kw.get("matched_keywords", "[HIGH]looking for"),
                status=kw.get("status", "new"),
                created_utc=datetime.datetime(2026, 1, 1),
            )
        )
        session.commit()

    def test_filter_new_excludes_stored_ids(self, temp_db):
        repo, session = self._repo()
        try:
            self._add(session, "abc123")
            fresh = repo.filter_new([{"id": "abc123"}, {"id": "def456"}])
            assert [p["id"] for p in fresh] == ["def456"]
        finally:
            session.close()

    def test_filter_new_drops_duplicates_within_the_batch(self, temp_db):
        """Pagination can serve the same post twice when the window shifts.

        Both copies passed the old per-post check -- neither was in the database
        yet -- and the ``reddit_id`` unique index then failed the commit for the
        entire page, losing every good lead alongside the duplicate.
        """
        repo, session = self._repo()
        try:
            fresh = repo.filter_new([{"id": "dup"}, {"id": "dup"}, {"id": "other"}])
            assert [p["id"] for p in fresh] == ["dup", "other"]
        finally:
            session.close()

    def test_filter_new_preserves_order(self, temp_db):
        repo, session = self._repo()
        try:
            posts = [{"id": f"p{i}"} for i in range(10)]
            assert [p["id"] for p in repo.filter_new(posts)] == [p["id"] for p in posts]
        finally:
            session.close()

    def test_dedup_is_one_query_per_page(self, temp_db):
        """The point of the repository. Counted at the driver, so a regression
        back to per-post lookups fails here rather than only showing up as a
        slow run.
        """
        from sqlalchemy import event

        from src.db import database

        repo, session = self._repo()
        statements: list[str] = []

        def record(conn, cursor, statement, params, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = database.ENGINE
        event.listen(engine, "before_cursor_execute", record)
        try:
            repo.filter_new([{"id": f"post{i}"} for i in range(100)])
        finally:
            event.remove(engine, "before_cursor_execute", record)
            session.close()

        assert len(statements) == 1, f"100 posts triggered {len(statements)} SELECTs"

    def test_large_batches_are_chunked_not_truncated(self, temp_db):
        """Above SQLite's bound-parameter ceiling the query is split. Splitting
        is fine; dropping the overflow silently would re-insert real duplicates.
        """
        repo, session = self._repo()
        try:
            posts = [{"id": f"bulk{i}"} for i in range(1200)]
            assert len(repo.filter_new(posts)) == 1200
        finally:
            session.close()

    def test_search_sort_by_is_allowlisted(self, temp_db):
        """``getattr(Lead, sort_by)`` would return ``Lead.metadata`` for
        ``?sort=metadata`` and ``desc()`` on a MetaData object raises -- a 500
        from a crafted URL. Unknown names fall back instead.
        """
        repo, session = self._repo()
        try:
            self._add(session, "s1")
            rows, total = repo.search(sort_by="metadata")
            assert total == 1
            assert len(rows) == 1
        finally:
            session.close()

    def test_search_escapes_like_wildcards(self, temp_db):
        """A literal % in the search box must match a literal %, not everything."""
        repo, session = self._repo()
        try:
            self._add(session, "w1", title="100% organic")
            self._add(session, "w2", title="nothing relevant")
            rows, total = repo.search(text="100%")
            assert total == 1
            assert rows[0].reddit_id == "w1"
        finally:
            session.close()

    def test_keyword_breakdown_counts_and_strips_prefixes(self, temp_db):
        repo, session = self._repo()
        try:
            self._add(session, "k1", matched_keywords="[HIGH]looking for, [MED]how do I")
            self._add(session, "k2", matched_keywords="[HIGH]looking for")
            breakdown = {row["keyword"]: row for row in repo.keyword_breakdown()}
            assert breakdown["looking for"]["leads"] == 2
            assert breakdown["looking for"]["intent_level"] == "high"
            assert breakdown["how do I"]["leads"] == 1
            assert breakdown["how do I"]["intent_level"] == "medium"
            assert not any(k.startswith("[") for k in breakdown)
        finally:
            session.close()

    def test_status_counts_totals(self, temp_db):
        repo, session = self._repo()
        try:
            self._add(session, "c1", status="new")
            self._add(session, "c2", status="contacted")
            self._add(session, "c3", status="new")
            counts = repo.status_counts()
            assert counts["new"] == 2
            assert counts["contacted"] == 1
            assert counts["total"] == 3
        finally:
            session.close()


class TestScoringSettingsQueryCount:
    """The old implementation issued ten queries for five values, inside the
    scorer's constructor -- so every scrape run paid it."""

    def _legacy(self, config, session):
        """The previous implementation, verbatim, as the oracle."""
        from src.db.models import Settings

        d = config.get("scoring", {})
        q = lambda k: session.query(Settings).filter_by(key=k).first()  # noqa: E731
        return {
            "keyword_weight": float(
                q("keyword_weight").value if q("keyword_weight") else d.get("keyword_weight", 3)
            ),
            "upvote_weight": float(
                q("upvote_weight").value if q("upvote_weight") else d.get("upvote_weight", 1)
            ),
            "comment_weight": float(
                q("comment_weight").value if q("comment_weight") else d.get("comment_weight", 2)
            ),
            "recency_weight": float(
                q("recency_weight").value if q("recency_weight") else d.get("recency_weight", 1.5)
            ),
            "high_intent_multiplier": float(
                q("high_intent_multiplier").value
                if q("high_intent_multiplier")
                else d.get("high_intent_multiplier", 2)
            ),
        }

    def test_output_matches_the_previous_implementation(self, temp_db):
        from src.db.database import get_session
        from src.db.models import Settings
        from src.subreddit_loader import get_scoring_settings

        session = get_session()
        try:
            # Three stored, two absent, and a config override for one of the
            # absent ones -- so all three precedence branches are exercised.
            session.add(Settings(key="keyword_weight", value="7"))
            session.add(Settings(key="upvote_weight", value="2.5"))
            session.add(Settings(key="recency_weight", value="0"))
            session.commit()

            config = {"scoring": {"comment_weight": 9}}
            assert get_scoring_settings(config, session) == self._legacy(config, session)
        finally:
            session.close()

    def test_settings_key_is_unique(self, temp_db):
        """Why one row per key is safe to assume.

        The refactor replaced a per-key ``.first()`` (lowest rowid wins) with a
        single query. That is only equivalent if a key cannot repeat -- so the
        constraint that makes it equivalent is pinned here rather than assumed.
        """
        from sqlalchemy.exc import IntegrityError

        from src.db.database import get_session
        from src.db.models import Settings

        session = get_session()
        try:
            session.add(Settings(key="keyword_weight", value="3"))
            session.commit()
            session.add(Settings(key="keyword_weight", value="99"))
            with pytest.raises(IntegrityError):
                session.commit()
        finally:
            session.rollback()
            session.close()

    def test_defaults_match_when_nothing_is_stored(self, temp_db):
        from src.db.database import get_session
        from src.subreddit_loader import get_scoring_settings

        session = get_session()
        try:
            assert get_scoring_settings({}, session) == self._legacy({}, session)
        finally:
            session.close()

    def test_it_is_one_query(self, temp_db):
        from sqlalchemy import event

        from src.db import database
        from src.db.database import get_session
        from src.subreddit_loader import get_scoring_settings

        session = get_session()
        selects: list[str] = []

        def record(conn, cursor, statement, params, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(database.ENGINE, "before_cursor_execute", record)
        try:
            get_scoring_settings({}, session)
        finally:
            event.remove(database.ENGINE, "before_cursor_execute", record)
            session.close()

        assert len(selects) == 1, f"scoring settings took {len(selects)} queries"


# ------------------------------------------------------------------ scoring


class TestScoringHandlesUnknownUpvotes:
    """AC6's other half: a None score must not crash the scorer."""

    def test_none_upvotes_scores_as_zero_contribution(self):
        from src.scoring import LeadScorer

        config = {"keywords": {"high_intent": ["looking for"], "medium_intent": []}}
        scorer = LeadScorer(config)
        unknown = scorer.score_post(title="looking for a CRM", upvotes=None, num_comments=None)
        zero = scorer.score_post(title="looking for a CRM", upvotes=0, num_comments=0)
        assert unknown["total"] == zero["total"]

    def test_existing_values_are_unchanged(self):
        """The coercion must not shift any score that already had a number."""
        from src.scoring import LeadScorer

        config = {"keywords": {"high_intent": ["looking for"], "medium_intent": []}}
        scorer = LeadScorer(config)
        result = scorer.score_post(title="looking for a CRM", upvotes=42, num_comments=7)
        assert result["upvote_score"] == 42
        assert result["comment_score"] == 14


# ----------------------------------------------------------- health surface


class TestProxyHealthEndpoints:
    @pytest.fixture
    def client(self, temp_db):
        from src.dashboard.app import create_app, reset_proxy_manager

        reset_proxy_manager()
        app = create_app(run_migrations=False)
        yield app.test_client()
        reset_proxy_manager()

    def test_proxies_page_renders(self, client):
        assert client.get("/health/proxies").status_code == 200

    def test_proxies_api_returns_pool_shape(self, client):
        payload = client.get("/api/health/proxies").get_json()
        for key in ("enabled", "total", "healthy", "circuit_open", "proxies"):
            assert key in payload

    def test_proxies_api_never_returns_credentials(self, client):
        """The health endpoint is the easiest place for a credential to escape:
        it serialises the whole pool and is reachable from a browser."""
        raw = client.get("/api/health/proxies").get_data(as_text=True)
        assert SECRET_USER not in raw
        assert SECRET_PASS not in raw
        assert "password" not in raw.lower()

    def test_top_level_health_summarises_the_pool(self, client):
        proxies = client.get("/api/health").get_json()["proxies"]
        for key in ("enabled", "healthy", "total", "circuit_open"):
            assert key in proxies

    def test_live_check_is_post_only(self, client):
        """A GET would let a link, a prefetch or a browser retry fire ten
        outbound proxy requests."""
        assert client.get("/api/health/proxies/check").status_code == 405

    def test_check_reports_when_the_leak_comparison_could_not_be_made(self, client, monkeypatch):
        """An empty ``leaking`` list is ambiguous on its own.

        If the local address cannot be determined, nothing was compared -- and
        reporting "no leak" would be a false negative on the single check this
        page exists for. ``local_ip_known`` is what disambiguates it.
        """
        from src.dashboard.app import get_proxy_manager

        pool = get_proxy_manager()
        if pool is None:
            pytest.skip("no proxy pool configured on this machine")

        monkeypatch.setattr(pool, "direct_ip", lambda timeout=10.0: None)
        monkeypatch.setattr(pool, "check_all", lambda max_workers=5: pool.snapshot())

        payload = client.post("/api/health/proxies/check").get_json()
        assert payload["leaking"] == []
        assert payload["local_ip_known"] is False, (
            "an unrunnable leak check is indistinguishable from a clean one"
        )

    def test_check_reports_a_successful_comparison(self, client, monkeypatch):
        from src.dashboard.app import get_proxy_manager

        pool = get_proxy_manager()
        if pool is None:
            pytest.skip("no proxy pool configured on this machine")

        monkeypatch.setattr(pool, "direct_ip", lambda timeout=10.0: "203.0.113.7")
        monkeypatch.setattr(pool, "check_all", lambda max_workers=5: pool.snapshot())

        payload = client.post("/api/health/proxies/check").get_json()
        assert payload["local_ip_known"] is True

    def test_a_leaking_proxy_is_reported(self, client, monkeypatch):
        from src.dashboard.app import get_proxy_manager

        pool = get_proxy_manager()
        if pool is None or not pool.endpoints:
            pytest.skip("no proxy pool configured on this machine")

        leaker = pool.endpoints[0]
        monkeypatch.setattr(pool, "direct_ip", lambda timeout=10.0: "203.0.113.7")

        def fake_check_all(max_workers=5):
            pool.stats_for(leaker).exit_ip = "203.0.113.7"  # same as ours
            return pool.snapshot()

        monkeypatch.setattr(pool, "check_all", fake_check_all)

        payload = client.post("/api/health/proxies/check").get_json()
        assert payload["leaking"] == [leaker.label]
        assert SECRET_PASS not in str(payload)

    def test_proxies_page_is_in_the_navigation(self, client):
        """AC: the operator must never have to type the URL."""
        body = client.get("/").get_data(as_text=True)
        assert "/health/proxies" in body


class TestNavigationStillMatchesRoutes:
    def test_every_nav_url_resolves(self, temp_db):
        from src.dashboard.app import create_app
        from src.dashboard.nav import NavRegistry

        client = create_app(run_migrations=False).test_client()
        for url in NavRegistry().urls():
            assert client.get(url).status_code == 200, f"nav points at a broken page: {url}"
