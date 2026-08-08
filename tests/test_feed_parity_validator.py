"""The comparison logic inside `scripts/validate_feed_parity.py`.

The script itself is live and deliberately outside the suite. Its *reasoning* is
not, and it needs to be: a drift detector that reports "OK" when it compared
nothing, or that tolerates a difference wide enough to hide a real defect, is
worse than no detector — it manufactures confidence.

These tests run the comparison against constructed post dicts. No network.
"""

from __future__ import annotations

import datetime
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_feed_parity.py"


@pytest.fixture(scope="module")
def validator():
    spec = importlib.util.spec_from_file_location("validate_feed_parity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _html(**overrides) -> dict:
    post = {
        "id": "t3_x1",
        "title": "A title",
        "url": "https://www.reddit.com/r/SaaS/comments/x1/a_title/",
        "author": "someone",
        "subreddit": "SaaS",
        "score": 12,
        "num_comments": 4,
        "body": "the body",
        "created_utc": datetime.datetime(2026, 8, 8, 11, 0, 0),
    }
    return {**post, **overrides}


def _rss(**overrides) -> dict:
    return _html(**{"score": None, "num_comments": None, **overrides})


def test_identical_posts_pass(validator):
    result = validator.compare([_html()], [_rss()])
    assert result["ok"] is True
    assert result["shared"] == 1
    assert result["mismatches"] == []


def test_the_two_intentional_differences_do_not_count_as_drift(validator):
    """`score` and `num_comments` differ on every real post, by design."""
    assert validator.compare([_html()], [_rss()])["ok"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "A different title"),
        ("author", "someone_else"),
        ("subreddit", "startups"),
        ("url", "https://www.reddit.com/r/SaaS/comments/WRONG/a_title/"),
        ("created_utc", datetime.datetime(2026, 8, 8, 12, 0, 0)),
    ],
)
def test_each_compared_field_is_actually_compared(validator, field, value):
    """Guards the exclusion list.

    A field quietly dropped from `COMPARED` would make this script pass forever
    while checking less and less.
    """
    result = validator.compare([_html()], [_rss(**{field: value})])
    assert result["ok"] is False
    assert [m["field"] for m in result["mismatches"]] == [field]


def test_a_link_post_url_is_tolerated_when_the_feed_gives_this_post_s_permalink(validator):
    """The HTML title points off Reddit; the feed points at the post itself."""
    html = _html(url="https://i.redd.it/abc123.png")
    rss = _rss(url="https://www.reddit.com/r/SaaS/comments/x1/a_title/")
    result = validator.compare([html], [rss])
    assert result["ok"] is True
    assert result["tolerated"][0]["field"] == "url"
    assert "link/media post" in result["tolerated"][0]["why"]


def test_a_feed_permalink_for_the_WRONG_post_is_not_tolerated(validator):
    """The tolerance must be narrow enough to still catch the real failure.

    "The urls differ" as a blanket exclusion would let the feed point at an
    entirely different post — which is precisely what this script exists to
    catch. The permalink must carry *this* post's id.
    """
    html = _html(url="https://i.redd.it/abc123.png")
    rss = _rss(url="https://www.reddit.com/r/SaaS/comments/SOMEONE_ELSE/other/")
    result = validator.compare([html], [rss])
    assert result["ok"] is False
    assert result["mismatches"][0]["field"] == "url"


def test_two_reddit_urls_that_differ_are_never_tolerated(validator):
    """Both on Reddit and still different means one of them is wrong."""
    html = _html(url="https://www.reddit.com/r/SaaS/comments/x1/a_title/")
    rss = _rss(url="https://www.reddit.com/r/SaaS/comments/x1/a_different_slug/")
    assert validator.compare([html], [rss])["ok"] is False


def test_a_completely_different_body_is_drift(validator):
    result = validator.compare([_html()], [_rss(body="something else entirely")])
    assert result["ok"] is False
    assert result["mismatches"][0]["field"] == "body"


def test_a_truncated_body_is_tolerated_and_reported(validator):
    """A prefix relationship is truncation or an edit, not a parsing difference.

    Tolerated is not the same as ignored: it appears in the output with the
    reason attached, so a reader can disagree.
    """
    result = validator.compare([_html(body="the body, continued")], [_rss(body="the body")])
    assert result["ok"] is True
    assert result["tolerated"][0]["field"] == "body"
    assert "truncation or an edit" in result["tolerated"][0]["why"]


def test_a_feed_with_no_body_where_html_has_one_is_drift(validator):
    """The direction matters, and only one direction is forgiven.

    "HTML empty, feed full" is the measured endpoint difference. "HTML full,
    feed empty" is the feed parser having stopped working, and every string
    starts with "", so a careless prefix check would tolerate it.
    """
    result = validator.compare([_html(body="the body")], [_rss(body="")])
    assert result["ok"] is False
    assert result["mismatches"][0]["field"] == "body"


def test_an_empty_html_listing_body_is_the_measured_endpoint_difference(validator):
    """2026-08-08: a listing page carries no selftext; the feed does.

    Tolerated and *reported*, with the direction stated, so a reader can see
    which side was empty.
    """
    result = validator.compare([_html(body="")], [_rss(body="real selftext")])
    assert result["ok"] is True
    assert result["tolerated"][0]["field"] == "body"
    assert "carries no selftext" in result["tolerated"][0]["why"]


def test_a_feed_with_no_bodies_at_all_fails_even_though_each_row_is_tolerated(validator):
    """The hole the tolerance above would otherwise open.

    Row by row, "HTML empty, feed empty" is agreement and "HTML empty, feed
    full" is tolerated — so a parser returning "" for everything would be
    reported OK on every single row. P0 measured feed selftext at a median of
    1,089 characters (U2); a feed with none is a regression.
    """
    result = validator.compare(
        [_html(body=""), _html(id="t3_x2", body="")],
        [_rss(body=""), _rss(id="t3_x2", body="")],
    )
    assert result["rss_bodies_missing"] is True
    assert result["ok"] is False


def test_a_feed_that_still_carries_bodies_passes(validator):
    result = validator.compare([_html(body="")], [_rss(body="real selftext")])
    assert result["rss_posts_with_a_body"] == 1
    assert result["rss_bodies_missing"] is False


def test_posts_in_only_one_result_are_coverage_not_mismatches(validator):
    """25 HTML posts vs up to 100 feed posts, seconds apart. Different windows."""
    result = validator.compare(
        [_html(), _html(id="t3_html_only")],
        [_rss(), _rss(id="t3_rss_only")],
    )
    assert result["ok"] is True
    assert result["html_only"] == ["t3_html_only"]
    assert result["rss_only"] == ["t3_rss_only"]
    assert result["shared"] == 1


def test_no_overlap_is_inconclusive_not_ok(validator):
    """The failure mode that would make this tool useless and confident.

    If the two windows never intersect, nothing was compared. Reporting success
    would be the worst available outcome.
    """
    result = validator.compare([_html(id="t3_a")], [_rss(id="t3_b")])
    assert result["shared"] == 0
    assert result["ok"] is False


def test_rss_claiming_a_score_is_a_failure(validator):
    """A feed cannot carry a score.

    If one ever appears, something is fabricating it — which is precisely the
    bug already fixed once for search-sourced scores.
    """
    result = validator.compare([_html()], [_rss(score=7)])
    assert result["ok"] is False
    assert result["rss_reported_a_score"][0]["rss_score"] == 7


def test_every_intentional_difference_carries_a_reason(validator):
    """An exclusion with no stated reason is indistinguishable from an oversight."""
    assert set(validator.INTENTIONAL) == {"score", "num_comments", "body", "url"}
    for reason in validator.INTENTIONAL.values():
        assert len(reason) > 40
    # Each conditional one must say WHERE it applies. "body differs" as a
    # blanket exclusion would cover the search path too, where it does not; the
    # same for `url` and self posts.
    assert "LISTING PAGES ONLY" in validator.INTENTIONAL["body"]
    assert "LINK AND MEDIA POSTS ONLY" in validator.INTENTIONAL["url"]


def test_the_compared_fields_are_the_seven_that_were_specified(validator):
    assert set(validator.COMPARED) == {
        "id",
        "title",
        "author",
        "body",
        "subreddit",
        "url",
        "created_utc",
    }
