"""Deterministic polling policy. Zero AI, by rule.

[28 §8.1](../../docs/28-discovery-redesign.md), implemented as written. **This
module must never import ``src.ai``** (R3, and an acceptance criterion of its
own) -- every number below is arithmetic over data the platform already stores,
and paying a model to compute arithmetic is [AD-10a](../../docs/03-architecture.md)
inverted.

The governing constraint is the one in the original docstring, and it is the
whole reason the design works: **RSS returns at most 100 items.** A subreddit
producing 20 posts/hour must be polled at least every 5 hours or the window
overflows and posts are lost silently. ``window_target`` defaults to 60, a 40%
safety margin against a burst.

No session, no client, no config file: ``next_interval`` takes a state and a
config object and returns a duration. That is what makes the < 1 ms budget
measurable and the whole module testable from literals.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from .watermarks import WatermarkState


@dataclass(frozen=True)
class PolicyConfig:
    """Tuning for :func:`next_interval`. Defaults are [28 §8.1](../../docs/28-discovery-redesign.md)'s.

    There is deliberately **no** ``density_threshold`` here. The density-adaptive
    body fetch it configured was removed in P6: it chose between an HTML listing
    page and a permalink for post bodies, and P5 measured that a listing page
    carries no body at all (freeze §11, 2026-08-08). A config key nothing reads
    is a documented capability that does not exist.
    """

    min_interval: datetime.timedelta = datetime.timedelta(minutes=15)
    max_interval: datetime.timedelta = datetime.timedelta(hours=24)
    window_target: int = 60
    empty_backoff: float = 0.5
    empty_cap: int = 6
    yield_boost: float = 1.0
    #: Assumed posts/hour until a rate has actually been measured. Distinct from
    #: a measured zero, which means the subreddit is dead.
    #:
    #: [28 §8.1](../../docs/28-discovery-redesign.md) names every other default
    #: but not this one, so it is chosen here. It equals ``window_target``, i.e.
    #: "until measured, assume the window fills in one hour", for two reasons:
    #:
    #: 1. It errs toward the failure that matters. Guessing too slow loses posts
    #:    silently (R19); guessing too fast costs a request. Those are not
    #:    symmetric.
    #: 2. It costs almost nothing, because it applies only until the *second*
    #:    poll -- the first poll measures an elapsed time and the EWMA takes
    #:    over. A value that sent a new channel to ``max_interval`` would make
    #:    an unmeasured channel indistinguishable from a dead one, which is the
    #:    distinction ``observed_rate_per_hour=None`` exists to preserve.
    default_rate: float = 60.0


def next_interval(
    watermark: WatermarkState,
    cfg: PolicyConfig,
    *,
    yield_ratio: float = 0.0,
) -> datetime.timedelta:
    """How long until this channel should be polled again.

    ``yield_ratio`` (qualifying leads per collected post, 0..1) is passed in
    rather than queried, so this module holds no session and the caller owns the
    SQL. See [28 §8.2](../../docs/28-discovery-redesign.md).
    """
    rate = watermark.observed_rate_per_hour
    if rate is None:
        rate = cfg.default_rate
    if rate <= 0:
        # Measured as dead. Poll it daily, not never: a dead subreddit
        # occasionally wakes up, and `max_interval` is how we notice.
        return cfg.max_interval

    # Time for `window_target` new posts to appear, comfortably inside the
    # 100-item ceiling.
    hours = cfg.window_target / rate
    interval = datetime.timedelta(hours=hours)

    # Slow down where nothing has been found for a while.
    empty = min(max(watermark.consecutive_empty, 0), cfg.empty_cap)
    interval *= 1 + (cfg.empty_backoff * empty)

    # Speed up where leads actually come from.
    interval /= 1 + (cfg.yield_boost * max(yield_ratio, 0.0))

    return _clamp(interval, cfg.min_interval, cfg.max_interval)


def _clamp(
    value: datetime.timedelta,
    low: datetime.timedelta,
    high: datetime.timedelta,
) -> datetime.timedelta:
    """Bound the interval both ways.

    The clamp is not decoration. Without the ceiling a quiet subreddit computes
    an interval of weeks and is effectively dropped; without the floor a busy
    one computes seconds and burns the per-IP rate limit (U1) for the whole
    process. ``low`` wins a contradictory config, because polling too often is
    recoverable and never polling is not.
    """
    if high < low:
        return low
    return max(low, min(value, high))


def due_at(
    now: datetime.datetime,
    watermark: WatermarkState,
    cfg: PolicyConfig,
    *,
    yield_ratio: float = 0.0,
) -> datetime.datetime:
    """``next_poll_at`` for a watermark just polled at ``now``."""
    return now + next_interval(watermark, cfg, yield_ratio=yield_ratio)


def shortened_after_overflow(interval: datetime.timedelta, cfg: PolicyConfig) -> datetime.timedelta:
    """Halve the interval after an overflow, never below ``min_interval``.

    [28 §9 D1](../../docs/28-discovery-redesign.md) requires overflow to shorten
    the interval as well as raise an error. Halving is the response to "the
    window moved past us": whatever rate we believed, it was at least twice too
    slow.
    """
    return _clamp(interval / 2, cfg.min_interval, cfg.max_interval)
