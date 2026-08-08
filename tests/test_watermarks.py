"""Stage 2 - watermark diff, advance, and overflow detection.

Overflow is R19's rule ("watermark overflow is an error, never a silent gap")
and it is the reason this file leans so hard on the *negative* cases. A check
that reports overflow constantly is as useless as one that never reports it, and
only the false cases can tell the two apart.
"""

from __future__ import annotations

import datetime

from src.discovery.watermarks import (
    WatermarkState,
    advance,
    detect_overflow,
    diff,
    newest_created,
    oldest_created,
)

T0 = datetime.datetime(2026, 8, 8, 12, 0, 0)


def post(pid: str, minutes: int, **extra) -> dict:
    """A feed post, `minutes` after T0."""
    return {
        "id": pid,
        "title": f"post {pid}",
        "url": f"https://www.reddit.com/r/SaaS/comments/{pid}/",
        "author": "example_user_1",
        "subreddit": "SaaS",
        "score": None,
        "num_comments": None,
        "body": "",
        "created_utc": T0 + datetime.timedelta(minutes=minutes),
        **extra,
    }


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------


def test_new_posts_are_those_not_already_known():
    posts = [post("t3_aaa01", 30), post("t3_aaa02", 20), post("t3_aaa03", 10)]
    result = diff(posts, known_ids={"t3_aaa02"})

    assert [p["id"] for p in result.new_posts] == ["t3_aaa01", "t3_aaa03"]
    assert result.seen == 3
    assert not result.is_empty


def test_a_poll_with_nothing_new_returns_no_posts():
    """A1: the idle poll. Everything the feed carries is already collected."""
    posts = [post("t3_aaa01", 30), post("t3_aaa02", 20)]
    result = diff(posts, known_ids={"t3_aaa01", "t3_aaa02"})

    assert result.new_posts == []
    assert result.is_empty
    assert result.seen == 2


def test_diff_preserves_feed_order():
    posts = [post("t3_aaa03", 30), post("t3_aaa01", 20), post("t3_aaa02", 10)]
    result = diff(posts, known_ids=set())
    assert [p["id"] for p in result.new_posts] == ["t3_aaa03", "t3_aaa01", "t3_aaa02"]


def test_an_entry_without_an_id_is_not_treated_as_new():
    posts = [post("", 10), {"id": None, "created_utc": T0}]
    assert diff(posts, known_ids=set()).new_posts == []


def test_diff_does_not_compare_ids_lexically():
    """A-2: base-36 fullnames are not a reliable ordering.

    `t3_zzz` sorts after `t3_aaa`, so any implementation that filtered by
    `id > last_seen_fullname` would drop this post. Set membership does not.
    """
    posts = [post("t3_aaa01", 10)]
    watermark = WatermarkState(last_seen_fullname="t3_zzz99", last_seen_utc=T0)
    assert [p["id"] for p in diff(posts, set(), watermark).new_posts] == ["t3_aaa01"]


# --------------------------------------------------------------------------
# overflow - the one true case
# --------------------------------------------------------------------------


def test_overflow_when_the_feeds_oldest_post_is_newer_than_the_watermark():
    """A2: 150 posts appeared between polls, so the window moved past us."""
    posts = [post(f"t3_new{i:03d}", 200 - i) for i in range(100)]
    watermark = WatermarkState(
        last_seen_fullname="t3_old001",
        last_seen_utc=T0 - datetime.timedelta(hours=3),
    )

    result = diff(posts, known_ids=set(), watermark=watermark)
    assert result.overflow is True


def test_overflow_holds_regardless_of_feed_ordering():
    """ "Oldest" is computed, not read off the end of the list."""
    posts = [post("t3_a", 10), post("t3_b", 90), post("t3_c", 50)]
    watermark = WatermarkState(last_seen_utc=T0 - datetime.timedelta(minutes=5))
    reversed_posts = list(reversed(posts))

    assert detect_overflow(posts, watermark) is True
    assert detect_overflow(reversed_posts, watermark) is True


# --------------------------------------------------------------------------
# overflow - the false cases. M2a: dropping the null-guard is invisible without
# these, because its failure direction is over-reporting.
# --------------------------------------------------------------------------


def test_cold_start_is_not_overflow():
    posts = [post(f"t3_new{i:03d}", i) for i in range(100)]
    assert detect_overflow(posts, None) is False
    assert diff(posts, known_ids=set(), watermark=None).overflow is False


def test_a_watermark_that_never_advanced_is_not_overflow():
    """A row exists but `last_seen_utc IS NULL` - one poll after a cold start."""
    posts = [post(f"t3_new{i:03d}", i) for i in range(100)]
    watermark = WatermarkState(last_seen_fullname=None, last_seen_utc=None)
    assert detect_overflow(posts, watermark) is False


def test_an_empty_feed_is_not_overflow():
    """A quiet subreddit. Stage 2 is supposed to believe this one."""
    watermark = WatermarkState(last_seen_utc=T0 - datetime.timedelta(hours=99))
    assert detect_overflow([], watermark) is False


def test_normal_incremental_poll_is_not_overflow():
    """The feed still carries posts we have seen, so nothing scrolled off."""
    posts = [post("t3_aaa03", 30), post("t3_aaa02", 20), post("t3_aaa01", 10)]
    watermark = WatermarkState(
        last_seen_fullname="t3_aaa01",
        last_seen_utc=T0 + datetime.timedelta(minutes=10),
    )
    assert detect_overflow(posts, watermark) is False


def test_posts_without_timestamps_do_not_trigger_overflow():
    posts = [{"id": "t3_aaa01", "created_utc": None}]
    watermark = WatermarkState(last_seen_utc=T0)
    assert detect_overflow(posts, watermark) is False


# --------------------------------------------------------------------------
# advance
# --------------------------------------------------------------------------


def test_advance_records_the_newest_timestamp_and_the_first_id():
    posts = [post("t3_aaa03", 30), post("t3_aaa02", 20)]
    result = diff(posts, known_ids=set())
    state = advance(None, posts, result)

    assert state.last_seen_fullname == "t3_aaa03"
    assert state.last_seen_utc == T0 + datetime.timedelta(minutes=30)
    assert state.consecutive_empty == 0


def test_advance_never_moves_the_timestamp_backwards():
    """A late-arriving feed must not rewind the watermark and re-open a gap."""
    previous = WatermarkState(last_seen_utc=T0 + datetime.timedelta(hours=5))
    posts = [post("t3_aaa01", 10)]
    state = advance(previous, posts, diff(posts, set()))
    assert state.last_seen_utc == T0 + datetime.timedelta(hours=5)


def test_consecutive_empty_increments_only_on_an_empty_diff():
    previous = WatermarkState(consecutive_empty=2)
    posts = [post("t3_aaa01", 10)]

    empty = advance(previous, posts, diff(posts, known_ids={"t3_aaa01"}))
    assert empty.consecutive_empty == 3

    found = advance(empty, posts, diff(posts, known_ids=set()))
    assert found.consecutive_empty == 0


def test_advance_is_idempotent_for_the_same_feed():
    """R9: a reclaimed job replays the poll and must land on the same row."""
    posts = [post("t3_aaa02", 20), post("t3_aaa01", 10)]
    result = diff(posts, known_ids=set())

    once = advance(None, posts, result)
    twice = advance(once, posts, result)

    assert once.last_seen_fullname == twice.last_seen_fullname
    assert once.last_seen_utc == twice.last_seen_utc


def test_rate_is_none_until_it_can_be_measured():
    """None is "not yet known"; 0.0 would mean "measured, and it is dead"."""
    posts = [post("t3_aaa01", 10)]
    state = advance(None, posts, diff(posts, set()), elapsed_hours=None)
    assert state.observed_rate_per_hour is None


def test_first_measured_rate_is_the_observation():
    posts = [post(f"t3_a{i:03d}", i) for i in range(10)]
    state = advance(None, posts, diff(posts, set()), elapsed_hours=2.0)
    assert state.observed_rate_per_hour == 5.0


def test_rate_is_smoothed_rather_than_replaced():
    previous = WatermarkState(observed_rate_per_hour=10.0)
    posts = [post("t3_aaa01", 10)]
    state = advance(previous, posts, diff(posts, set()), elapsed_hours=1.0)

    # One quiet hour must not convince the scheduler a busy subreddit died.
    assert 1.0 < state.observed_rate_per_hour < 10.0


def test_oldest_and_newest_ignore_missing_timestamps():
    posts = [post("t3_a", 10), {"id": "t3_b", "created_utc": None}, post("t3_c", 50)]
    assert oldest_created(posts) == T0 + datetime.timedelta(minutes=10)
    assert newest_created(posts) == T0 + datetime.timedelta(minutes=50)
    assert oldest_created([]) is None
    assert newest_created([]) is None
