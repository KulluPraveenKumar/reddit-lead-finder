"""``RedditClient.get_feed`` — URL construction, routing, and failure modes.

No network: the transport is a double that records what it was asked for. That
is deliberate and is what the gate requires ([34 §1.2](../docs/34-implementation-plan.md):
"no live network or API calls"). The live counterpart is
``scripts/validate_feed_parity.py``, which is not part of the suite.

What is actually being protected here is not "does it build a URL" but three
properties that are invisible until they are wrong:

* the **request class** reaches the policy, so feeds go direct (R18);
* the **cache is bypassed**, so a watermark cannot be starved by a stale hit;
* the **off switch** genuinely stops the request, so rollback level 1 is real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.discovery import FeedParseError
from src.net import BlockedError, ProxyExhaustedError
from src.net.blocks import BlockKind, BlockVerdict
from src.reddit_client import FeedDisabled, RedditClient

FIXTURES = Path(__file__).parent / "fixtures" / "atom"


class FakeResult:
    def __init__(self, text: str = "", status_code: int = 200, blocked: bool = False):
        self.text = text
        self.status_code = status_code
        self.verdict = BlockVerdict(BlockKind.SOFT if blocked else BlockKind.NONE)
        self._blocked = blocked

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and not self._blocked


class FakeHTTP:
    """Records every call. Raises whatever it was told to, or returns a body."""

    def __init__(self, result=None, raises: Exception | None = None):
        self.calls: list[dict] = []
        self._result = result
        self._raises = raises

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self._raises is not None:
            raise self._raises
        return self._result if self._result is not None else FakeResult()


def _client(config=None, http=None) -> RedditClient:
    return RedditClient(config=config or {}, http_client=http or FakeHTTP())


def _feed_bytes(name: str = "listing_multireddit") -> str:
    return (FIXTURES / f"{name}.xml").read_text(encoding="utf-8")


# ------------------------------------------------------------- URL shapes


def test_many_subreddits_become_one_multireddit_request():
    """U1: the RSS budget is per IP, so combining is mandatory, not an option.

    Twelve subreddits polled one at a time cost twelve minutes of wall clock.
    """
    url = _client()._feed_url(["SaaS", "startups", "Entrepreneur"])
    assert url == "https://old.reddit.com/r/SaaS+startups+Entrepreneur/new/.rss?limit=100"


def test_the_sort_appears_in_the_path():
    assert "/hot/.rss" in _client()._feed_url(["SaaS"], sort="hot")


def test_an_unknown_sort_is_refused():
    """Reddit answers an unknown sort with the default and says nothing.

    Accepting it would mean asking for `top` and quietly getting `new`.
    """
    with pytest.raises(ValueError, match="sort must be one of"):
        _client()._feed_url(["SaaS"], sort="controversial-ish")


def test_a_query_builds_the_boolean_search_feed():
    """U3: `(subreddit:a OR subreddit:b)` works, turning 120 requests into 12."""
    url = _client()._feed_url(["SaaS", "startups"], query="looking for")
    assert url.startswith("https://old.reddit.com/search.rss?q=")
    assert "subreddit%3ASaaS+OR+subreddit%3Astartups" in url
    assert "%22looking+for%22" in url


def test_a_query_is_url_encoded():
    """The P2 bug, not repeated.

    An unencoded `&` terminates the `q` parameter and searches for the fragment
    before it; an unencoded `#` turns the rest into a fragment never sent at
    all. Both fail quietly and return plausible results for the wrong search.
    """
    url = _client()._feed_url(["SaaS"], query="pricing & scale #saas")
    assert "&scale" not in url
    assert "#" not in url


def test_the_limit_is_clamped_to_what_reddit_honours():
    """U5 measured 100 as the ceiling; 0 would ask for an empty feed."""
    assert "limit=100" in _client()._feed_url(["SaaS"], limit=500)
    assert "limit=1" in _client()._feed_url(["SaaS"], limit=0)
    assert "limit=25" in _client()._feed_url(["SaaS"], limit=25)


def test_the_host_defaults_to_old_reddit():
    """07 §1 permits only old.reddit.com; U6 measured it serving RSS identically."""
    assert _client()._feed_url(["SaaS"]).startswith("https://old.reddit.com/")


def test_a_trailing_slash_on_the_configured_host_does_not_double_up():
    """`https://old.reddit.com//r/SaaS/...` is the kind of URL nobody notices."""
    url = _client()._feed_url(["SaaS"], host="https://old.reddit.com/")
    assert url == "https://old.reddit.com/r/SaaS/new/.rss?limit=100"


def test_get_feed_honours_the_configured_host():
    """The config key is wired through `get_feed`, not merely accepted."""
    http = FakeHTTP(FakeResult(_feed_bytes()))
    _client({"discovery": {"rss_host": "https://old.reddit.com"}}, http).get_feed(["SaaS"])
    assert http.calls[0]["url"].startswith("https://old.reddit.com/r/SaaS/")


def test_subreddit_names_are_normalised():
    """`r/SaaS`, ` SaaS `, and `SaaS` are the same subreddit."""
    assert _client()._feed_url([" r/SaaS ", "startups/"]) == (
        "https://old.reddit.com/r/SaaS+startups/new/.rss?limit=100"
    )


def test_a_bare_string_is_treated_as_one_subreddit():
    """`get_feed("SaaS")` would otherwise build `/r/S+a+a+S/` — valid and wrong."""
    assert _client()._feed_url("SaaS") == "https://old.reddit.com/r/SaaS/new/.rss?limit=100"


def test_no_subreddits_is_refused():
    with pytest.raises(ValueError, match="at least one subreddit"):
        _client()._feed_url([])


# ----------------------------------------------------------------- routing


def test_a_feed_request_uses_the_rss_class():
    """R18: RSS is direct under every policy value, and it is code, not config.

    Dropping this argument would send feeds through the datacenter pool, which
    is both slower and the thing the freeze rule exists to prevent.
    """
    http = FakeHTTP(FakeResult(_feed_bytes()))
    _client(http=http).get_feed(["SaaS"])
    assert http.calls[0]["request_class"] == "rss"


def test_a_feed_request_bypasses_the_http_cache():
    """[28 §11 D5]: the watermark is the cache.

    A 15-minute TTL serving a stale feed to a 15-minute poll means the watermark
    never advances and new posts are lost with no error anywhere.
    """
    http = FakeHTTP(FakeResult(_feed_bytes()))
    _client(http=http).get_feed(["SaaS"])
    assert http.calls[0]["allow_cache"] is False


def test_one_call_makes_exactly_one_request():
    """A feed has no `next` link, and a second request costs ~60 s (U1)."""
    http = FakeHTTP(FakeResult(_feed_bytes()))
    _client(http=http).get_feed(["SaaS", "startups"])
    assert len(http.calls) == 1


def test_the_configured_host_and_limit_are_used():
    config = {"discovery": {"rss_host": "https://old.reddit.com", "rss_limit": 25}}
    http = FakeHTTP(FakeResult(_feed_bytes()))
    _client(config, http).get_feed(["SaaS"])
    assert "limit=25" in http.calls[0]["url"]


# ------------------------------------------------------------------ results


def test_a_feed_is_parsed_into_posts():
    posts = _client(http=FakeHTTP(FakeResult(_feed_bytes()))).get_feed(["SaaS", "startups"])
    assert [p["id"] for p in posts] == ["t3_a000101", "t3_a000102", "t3_a000103"]


def test_the_limit_trims_the_returned_posts():
    """Not only the URL. Reddit may return more than asked; the caller may not."""
    posts = _client(http=FakeHTTP(FakeResult(_feed_bytes()))).get_feed(["SaaS"], limit=2)
    assert len(posts) == 2


def test_an_empty_feed_returns_no_posts():
    result = FakeResult((FIXTURES / "empty.xml").read_text(encoding="utf-8"))
    assert _client(http=FakeHTTP(result)).get_feed(["SaaS"]) == []


# ----------------------------------------------------------------- failures


def test_a_malformed_feed_raises_rather_than_returning_nothing():
    """The two failures must not look alike.

    `[]` means "this subreddit is quiet", which a poller believes. A damaged
    response must not be able to say that.
    """
    result = FakeResult((FIXTURES / "malformed.xml").read_text(encoding="utf-8"))
    with pytest.raises(FeedParseError):
        _client(http=FakeHTTP(result)).get_feed(["SaaS"])


@pytest.mark.parametrize(
    "error",
    [ProxyExhaustedError("pool empty"), BlockedError("blocked"), RuntimeError("socket died")],
)
def test_a_transport_failure_returns_no_posts(error):
    """`_get`'s contract, preserved: the caller already handles "nothing came back".

    Making the transport raise is P6's change, together with the handler that
    maps it to a run outcome ([PHASE-04-HANDOVER §4 T1](../docs/PHASE-04-HANDOVER.md)).
    """
    assert _client(http=FakeHTTP(raises=error)).get_feed(["SaaS"]) == []


def test_a_non_ok_response_returns_no_posts():
    assert _client(http=FakeHTTP(FakeResult("", status_code=429))).get_feed(["SaaS"]) == []


def test_a_soft_blocked_response_returns_no_posts():
    """HTTP 200 carrying an interstitial is not a feed."""
    assert _client(http=FakeHTTP(FakeResult("<html/>", blocked=True))).get_feed(["SaaS"]) == []


# ---------------------------------------------------------------- rollback


def test_the_off_switch_refuses_and_makes_no_request():
    """Rollback level 1. It raises rather than returning `[]` for the same
    reason a malformed feed does: a disabled collector must not be mistakable
    for a quiet one."""
    http = FakeHTTP(FakeResult(_feed_bytes()))
    client = _client({"discovery": {"rss_enabled": False}}, http)
    with pytest.raises(FeedDisabled):
        client.get_feed(["SaaS"])
    assert http.calls == []


def test_an_absent_discovery_block_falls_back_to_defaults():
    """Rollback level 2: deleting the config block must not break anything.

    The same fallback discipline P4's `network:` block has, and the documented
    second rollback level.
    """
    http = FakeHTTP(FakeResult(_feed_bytes()))
    posts = RedditClient(config={}, http_client=http).get_feed(["SaaS"])
    assert len(posts) == 3
    assert "limit=100" in http.calls[0]["url"]


def test_an_empty_discovery_block_falls_back_to_defaults():
    """`discovery:` with nothing under it parses as None, not {}."""
    http = FakeHTTP(FakeResult(_feed_bytes()))
    assert len(RedditClient(config={"discovery": None}, http_client=http).get_feed(["SaaS"])) == 3


# ------------------------------------------------------- the frozen surface


def test_the_six_frozen_methods_are_untouched():
    """AD-2. P5 adds a seventh method; it changes none of the six.

    Signature-level, because a return-shape change would still be caught by the
    scraper tests but a quietly added keyword argument would not.
    """
    import inspect

    expected = {
        "get_new_posts": ["self", "subreddit", "limit"],
        "get_hot_posts": ["self", "subreddit", "limit"],
        "search_posts": ["self", "query", "subreddit", "limit", "sort", "time_filter"],
        "get_post_comments": ["self", "post_url", "limit"],
        "get_user_posts": ["self", "username", "limit"],
        "get_subreddit_info": ["self", "subreddit_name"],
    }
    for name, params in expected.items():
        actual = list(inspect.signature(getattr(RedditClient, name)).parameters)
        assert actual == params, f"{name} signature changed: {actual}"
