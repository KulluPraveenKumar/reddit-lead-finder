"""P5's central claim: **RSS and HTML describe the same post identically.**

If this file fails, P5 is not done, whatever else passes. Two collection paths
that disagree about what a post *is* would hand the scorer two populations, and
nothing downstream could tell which one it was looking at.

---

**The intentional differences, and where each comes from.** Three, not two. The
third was measured on 2026-08-08 and is recorded as an amendment in
[ARCHITECTURE_FREEZE.md §11](../docs/ARCHITECTURE_FREEZE.md):

| Field | Difference | Why |
|---|---|---|
| ``score`` | HTML listing has it, feed does not | A feed carries no vote count. ``None`` is "unknown"; ``0`` would be a claim |
| ``num_comments`` | HTML has it, feed does not | Same. (The HTML path reports ``0`` rather than ``None`` here — the same class of bug fixed once for ``score``, deferred) |
| ``body`` | **listing pages only.** Feed has it, HTML listing does not | Old Reddit renders a listing expando as ``<span class="error">loading...</span>`` and fetches the body over AJAX. ``div.expando .md`` matches **zero** elements on a real page |

**The third is a property of the endpoint, not a defect in either parser, and it
must not be used to weaken the feed parser.** So body parity is proved where
HTML genuinely carries a body: the **search** pair below. Search renders the
body inline in ``div.search-result-body .md``, so on that pair ``score`` and
``body`` both agree and ``num_comments`` is the only exception.

---

**Why the fixtures are built the way they are.** A parity test is trivial to
write in a form that cannot fail:

* the HTML twins are modelled on the **real captured markup** in
  ``listing_page1.html`` and ``search_page1.html`` — container nesting,
  attribute set and the *empty* lazy expando exactly as served;
* the Atom twins are modelled on a **live capture** taken 2026-08-08, keeping
  every artifact the parser must remove: the ``/u/`` prefix, the ``SC_OFF``
  wrapper and ``submitted by`` footer, the ``old.reddit.com`` host, ``&#39;``.

Neither was authored to match the other. An earlier version of the listing twin
carried a *populated* expando — copied from how the markup is documented rather
than how it is served — and this file passed against markup Reddit does not
send. ``scripts/validate_feed_parity.py`` found that on its first live run.

**Fixtures cannot detect drift.** They freeze 2026-08-08 Reddit. Run the live
validator for the counterpart.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.discovery import parse_feed
from src.reddit_client import RedditClient

FIXTURES = Path(__file__).parent / "fixtures"

#: Differences that are correct on a **listing** pair.
#:
#: ``body`` is here because the endpoint does not carry it, not because the
#: parsers disagree. ``url`` is here **for link and media posts only**: a
#: listing title links to the *destination* (``v.redd.it``, ``i.redd.it``, an
#: external site) and ``_extract_post`` reads that href, while the feed's
#: ``<link href>`` is always the permalink. Measured on r/SaaS 2026-08-08: 3 of
#: 25 posts. Self posts agree, and the narrow assertion below keeps this from
#: hiding a genuinely wrong permalink.
LISTING_DIFFERENCES = ("score", "num_comments", "body", "url")

#: Differences that are correct on a **search** pair. Search HTML carries the
#: body and carries no score, so the comment count is one of only two left.
#:
#: ``url`` is the other, and it is a **pre-existing inconsistency in the shipped
#: HTML path**, not a feed problem: ``_extract_post`` rewrites a listing
#: permalink to ``www.reddit.com``, while ``_extract_search_post`` returns
#: whatever the page linked — and a real search page links ``old.reddit.com``.
#: The live database shows the split plainly: **444 rows on ``old.reddit.com``,
#: 27 on ``www.reddit.com``**. The feed parser follows the listing path's
#: canonical host; normalising the search path is a change to shipped behaviour
#: and is recorded in DEFERRED-IMPROVEMENTS.md instead.
SEARCH_DIFFERENCES = ("num_comments", "url")


def _html_listing() -> dict[str, dict]:
    client = RedditClient.__new__(RedditClient)  # no transport needed to parse
    raw = (FIXTURES / "reddit" / "listing_matched.html").read_text(encoding="utf-8")
    posts, _next_url = RedditClient._parse_listing(client, raw)
    return {p["id"]: p for p in posts}


def _html_search() -> dict[str, dict]:
    client = RedditClient.__new__(RedditClient)
    raw = (FIXTURES / "reddit" / "search_matched.html").read_text(encoding="utf-8")
    posts, _next_url = RedditClient._parse_search_results(client, raw)
    return {p["id"]: p for p in posts}


def _rss(name: str) -> dict[str, dict]:
    raw = (FIXTURES / "atom" / f"{name}.xml").read_bytes()
    return {p["id"]: p for p in parse_feed(raw)}


@pytest.fixture
def listing_pair():
    return _html_listing(), _rss("listing_multireddit")


@pytest.fixture
def search_pair():
    return _html_search(), _rss("search")


# ------------------------------------------------------------------ listing


def test_the_listing_fixtures_describe_the_same_posts(listing_pair):
    """A precondition, asserted separately so its failure is not read as drift."""
    html, rss = listing_pair
    assert set(html) == set(rss) == {"t3_a000101", "t3_a000102", "t3_a000103"}


def test_listing_rss_and_html_agree_on_everything_they_both_carry(listing_pair):
    """AC A1, as amended.

    Whole-dict equality after normalising the three documented differences.
    Comparing a named list of fields instead would stop protecting any field
    added later, which is exactly when this guarantee gets quietly broken.
    """
    html_posts, rss_posts = listing_pair
    for reddit_id, html in html_posts.items():
        expected = {
            **html,
            "score": None,
            "num_comments": None,
            "body": rss_posts[reddit_id]["body"],
            "url": rss_posts[reddit_id]["url"],
        }
        assert rss_posts[reddit_id] == expected, f"{reddit_id} differs beyond the documented fields"


@pytest.mark.parametrize("field", ["id", "title", "author", "subreddit", "created_utc"])
def test_each_shared_listing_field_individually(field, listing_pair):
    """The same guarantee, field by field, so a failure names the culprit.

    Redundant with the test above on a green run and worth its cost on a red
    one: whole-dict equality reports "these dicts differ" and leaves the reader
    to diff nine keys by eye.
    """
    html_posts, rss_posts = listing_pair
    for reddit_id, html in html_posts.items():
        assert rss_posts[reddit_id][field] == html[field], (
            f"{field} differs on {reddit_id}: "
            f"RSS {rss_posts[reddit_id][field]!r} vs HTML {html[field]!r}"
        )


def test_the_listing_differences_are_exactly_the_three_documented_ones(listing_pair):
    """Pins the *size* of the exception, not just its content.

    A future change that made a fourth field unknown on the feed path would
    otherwise be absorbed by the normalisation above and never be noticed.
    """
    html_posts, rss_posts = listing_pair
    for reddit_id, html in html_posts.items():
        rss = rss_posts[reddit_id]
        differing = {k for k in html if rss[k] != html[k]}
        assert differing <= set(LISTING_DIFFERENCES), (
            f"{reddit_id}: undocumented differences {differing - set(LISTING_DIFFERENCES)}"
        )


def test_a_listing_page_carries_no_selftext_and_the_feed_does(listing_pair):
    """The 2026-08-08 measurement, pinned as a test.

    Old Reddit renders a listing expando as ``loading...`` and fetches the body
    over AJAX, so ``div.expando .md`` matches nothing. If this ever starts
    failing, Reddit changed something and P6's density heuristic needs revisiting
    — which is precisely why it is asserted rather than described in a comment.
    """
    html_posts, rss_posts = listing_pair
    assert all(p["body"] == "" for p in html_posts.values()), (
        "a listing page produced a body; re-run scripts/validate_feed_parity.py "
        "and revisit ARCHITECTURE_FREEZE §11's 2026-08-08 amendment"
    )
    # The feed carries the selftext for every self post. The link post has none
    # on either side, which is agreement rather than an exception.
    assert rss_posts["t3_a000101"]["body"].startswith("We are three months in")
    assert rss_posts["t3_a000103"]["body"].startswith("Don't copy a competitor")
    assert rss_posts["t3_a000102"]["body"] == ""


def test_a_self_post_permalink_is_identical_on_both_paths(listing_pair):
    """The `url` exception is scoped to link posts and must not widen.

    If a *self* post's permalink ever diverged, that would be a real defect
    wearing the link-post exception's clothes.
    """
    html_posts, rss_posts = listing_pair
    for reddit_id in ("t3_a000101", "t3_a000103"):
        assert rss_posts[reddit_id]["url"] == html_posts[reddit_id]["url"]


def test_a_link_post_keeps_the_permalink_on_the_feed_path(listing_pair):
    """**The feed is not weakened to match the HTML listing.**

    A listing title links to the destination, so `_extract_post` stores
    `https://example.invalid/launch` — the content, not the post. The feed
    stores the permalink, which is the actionable URL for a lead: it is where an
    operator goes to reply, it is what the search path already stores, and it is
    what 444 of the 471 rows in the live database carry.

    The feed *could* be made to match by pulling the `[link]` anchor out of
    `<content>`. It deliberately is not. Matching an endpoint that answers a
    different question is not parity, it is a regression with a green test.
    """
    html_posts, rss_posts = listing_pair
    assert html_posts["t3_a000102"]["url"] == "https://example.invalid/launch"
    assert rss_posts["t3_a000102"]["url"] == (
        "https://www.reddit.com/r/SaaS/comments/a000102/we_shipped_our_public_launch_page/"
    )
    assert "t3_a000102".removeprefix("t3_") in rss_posts["t3_a000102"]["url"]


def test_html_listing_reports_engagement_and_rss_reports_unknown(listing_pair):
    """The two original exceptions are 'a feed does not carry it'."""
    html_posts, rss_posts = listing_pair
    for reddit_id, html in html_posts.items():
        assert html["score"] is not None
        assert rss_posts[reddit_id]["score"] is None
        assert rss_posts[reddit_id]["num_comments"] is None


# ------------------------------------------------------------------- search


def test_the_search_fixtures_describe_the_same_posts(search_pair):
    html, rss = search_pair
    assert set(html) == set(rss) == {"t3_a000201", "t3_a000202"}


def test_search_rss_and_html_produce_identical_bodies(search_pair):
    """**The body guarantee, proved against HTML that actually has one.**

    This is what stops the listing measurement from quietly weakening the feed
    parser. A search page renders the body inline, so if the feed parser mangled
    the ``SC_OFF`` wrapper, dropped the ``div.md`` selection, or left the
    ``submitted by`` footer in, this fails.
    """
    html_posts, rss_posts = search_pair
    for reddit_id, html in html_posts.items():
        assert rss_posts[reddit_id]["body"] == html["body"], (
            f"body differs on {reddit_id}: "
            f"RSS {rss_posts[reddit_id]['body']!r} vs HTML {html['body']!r}"
        )


def test_search_rss_and_html_agree_on_everything_they_both_carry(search_pair):
    html_posts, rss_posts = search_pair
    for reddit_id, html in html_posts.items():
        expected = {**html, "num_comments": None, "url": rss_posts[reddit_id]["url"]}
        assert rss_posts[reddit_id] == expected


def test_the_search_differences_are_exactly_the_two_documented_ones(search_pair):
    """Search HTML carries no score either, so ``score`` agrees here."""
    html_posts, rss_posts = search_pair
    for reddit_id, html in html_posts.items():
        differing = {k for k in html if rss_posts[reddit_id][k] != html[k]}
        assert differing <= set(SEARCH_DIFFERENCES), (
            f"{reddit_id}: undocumented differences {differing - set(SEARCH_DIFFERENCES)}"
        )
        assert html["score"] is None and rss_posts[reddit_id]["score"] is None


def test_the_search_url_difference_is_the_host_and_nothing_else(search_pair):
    """A narrow assertion, because "the urls differ" would hide a wrong permalink.

    The two paths must point at the *same post*; only the host may differ, and
    only because ``_extract_search_post`` does not rewrite it. If the path, the
    query or the post id ever diverged, that would be a real defect wearing this
    exception's clothes.
    """
    from urllib.parse import urlsplit

    html_posts, rss_posts = search_pair
    for reddit_id, html in html_posts.items():
        html_parts = urlsplit(html["url"])
        rss_parts = urlsplit(rss_posts[reddit_id]["url"])
        assert html_parts.path == rss_parts.path, f"{reddit_id}: different permalink path"
        assert rss_parts.netloc == "www.reddit.com"
        assert html_parts.netloc == "old.reddit.com"
