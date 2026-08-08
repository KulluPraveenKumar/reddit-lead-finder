"""Watermark diff, advance, and overflow detection.

Stage 2 of [28 §3](../../docs/28-discovery-redesign.md). Pure functions over
dicts and a small frozen state object: **no session, no client, no config.**
That is what lets the overflow fixture be a list literal rather than a database,
and it is why every branch below is reachable from a unit test.

Two decisions here are load-bearing and neither is obvious from the schema:

**The diff is on the id set, never on id comparison.** ``t3_`` fullnames are
base-36 and look ordered, but Reddit does not guarantee ordering across shards,
so ``id > last_seen_fullname`` is a plausible-looking test that is wrong in a way
no fixture would show. ``last_seen_utc`` exists *only* to detect overflow.

**"Oldest" is computed, not indexed.** A feed is newest-first today, so the
oldest entry is the last one -- but reading ``posts[-1]`` bakes that ordering
into the overflow check, which is the one check that must not quietly stop
working. ``min`` over ``created_utc`` costs nothing and holds whatever order the
feed arrives in.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

#: Weight given to the newest observation when updating the post-rate EWMA.
#: Low enough that one quiet hour does not convince the scheduler a busy
#: subreddit has died.
RATE_ALPHA = 0.3


@dataclass(frozen=True)
class WatermarkState:
    """The parts of a ``discovery_watermarks`` row this module reasons about.

    A plain value object rather than the ORM model, so the diff can be tested
    without a database and so nothing here can accidentally hold a session
    open across a network call (T0).
    """

    last_seen_fullname: str | None = None
    last_seen_utc: datetime.datetime | None = None
    consecutive_empty: int = 0
    observed_rate_per_hour: float | None = None


@dataclass(frozen=True)
class DiffResult:
    """What one poll found."""

    new_posts: list[dict]
    overflow: bool
    seen: int

    @property
    def is_empty(self) -> bool:
        return not self.new_posts


def oldest_created(posts: list[dict]) -> datetime.datetime | None:
    """The earliest ``created_utc`` in the batch, ignoring entries without one."""
    stamps = [p["created_utc"] for p in posts if p.get("created_utc") is not None]
    return min(stamps) if stamps else None


def newest_created(posts: list[dict]) -> datetime.datetime | None:
    stamps = [p["created_utc"] for p in posts if p.get("created_utc") is not None]
    return max(stamps) if stamps else None


def detect_overflow(posts: list[dict], watermark: WatermarkState | None) -> bool:
    """Did the window move past us between polls?

    True only when the *oldest* post the feed still carries is newer than the
    newest post we have already seen -- which means everything in between
    existed, scrolled off the 100-item ceiling, and was never collected. That is
    R19's silent gap, and it is an error rather than a shrug.

    **Three cases are explicitly not overflow, and each is an ordinary path:**

    * no watermark at all -- a cold start legitimately sees a full feed;
    * a watermark that has never advanced (``last_seen_utc IS NULL``) -- same
      thing, one poll later;
    * an empty feed -- a quiet subreddit, which stage 2 is supposed to believe.

    Collapsing any of them into overflow would fire R19's error on the two most
    ordinary states in the system, and an error that fires constantly is an
    error nobody reads.
    """
    if watermark is None or watermark.last_seen_utc is None or not posts:
        return False
    oldest = oldest_created(posts)
    if oldest is None:
        return False
    return oldest > watermark.last_seen_utc


def diff(
    posts: list[dict],
    known_ids: set[str],
    watermark: WatermarkState | None = None,
) -> DiffResult:
    """Split a feed into what is new and whether we lost anything getting here.

    ``known_ids`` is supplied by the caller from a single ``IN`` query, so this
    function stays free of the database. Order is preserved: the feed's own
    ordering is the best available proxy for recency, and downstream stages
    process in that order.
    """
    new_posts = [p for p in posts if p.get("id") and p["id"] not in known_ids]
    return DiffResult(
        new_posts=new_posts,
        overflow=detect_overflow(posts, watermark),
        seen=len(posts),
    )


def advance(
    watermark: WatermarkState | None,
    posts: list[dict],
    result: DiffResult,
    *,
    elapsed_hours: float | None = None,
) -> WatermarkState:
    """The watermark after a poll.

    Idempotent with respect to re-running the same feed (R9): the new state is
    derived from the feed's contents, not incremented from the old one, so a
    reclaimed job that replays an identical poll lands on an identical row.

    ``consecutive_empty`` is the one counter that does accumulate, and it is
    reset by *finding something* rather than by polling -- a re-run that finds
    nothing new because the first run already collected it is genuinely an
    empty poll from the scheduler's point of view.
    """
    previous = watermark or WatermarkState()

    newest_stamp = newest_created(posts)
    last_seen_utc = previous.last_seen_utc
    if newest_stamp is not None and (last_seen_utc is None or newest_stamp > last_seen_utc):
        last_seen_utc = newest_stamp

    last_fullname = previous.last_seen_fullname
    if posts and posts[0].get("id"):
        last_fullname = posts[0]["id"]

    empty = previous.consecutive_empty + 1 if result.is_empty else 0

    return WatermarkState(
        last_seen_fullname=last_fullname,
        last_seen_utc=last_seen_utc,
        consecutive_empty=empty,
        observed_rate_per_hour=_update_rate(
            previous.observed_rate_per_hour, len(result.new_posts), elapsed_hours
        ),
    )


def _update_rate(
    previous: float | None, new_count: int, elapsed_hours: float | None
) -> float | None:
    """EWMA of new posts per hour, or the previous value when unmeasurable.

    Returns ``None`` rather than ``0.0`` when there is nothing to learn from --
    no elapsed time, or a first poll. ``0.0`` means "measured, and it is dead",
    which sends the scheduler to ``max_interval``; ``None`` means "not yet
    known", which is a different instruction.
    """
    if elapsed_hours is None or elapsed_hours <= 0:
        return previous
    observed = new_count / elapsed_hours
    if previous is None:
        return observed
    return (RATE_ALPHA * observed) + ((1 - RATE_ALPHA) * previous)
