"""The adaptive polling policy - [28 §8.1](../docs/28-discovery-redesign.md).

The clamp gets the most attention here because it is the guard that keeps a
misconfigured or freshly-measured rate from either dropping a subreddit
(interval of weeks) or burning the per-IP rate limit (interval of seconds).
"""

from __future__ import annotations

import datetime
import time

import pytest

from src.discovery.policy import (
    PolicyConfig,
    due_at,
    next_interval,
    shortened_after_overflow,
)
from src.discovery.watermarks import WatermarkState

CFG = PolicyConfig()
HOUR = datetime.timedelta(hours=1)


def test_a_dead_subreddit_is_polled_at_the_maximum_not_never():
    state = WatermarkState(observed_rate_per_hour=0.0)
    assert next_interval(state, CFG) == CFG.max_interval


def test_a_negative_rate_is_treated_as_dead():
    state = WatermarkState(observed_rate_per_hour=-5.0)
    assert next_interval(state, CFG) == CFG.max_interval


def test_an_unmeasured_rate_uses_the_default_not_zero():
    """None means "not yet known" and must not send a new channel to 24h.

    A measured 0.0 goes to `max_interval` because the subreddit is dead. An
    unmeasured None must not land in the same place, or the two states become
    indistinguishable and a brand-new channel is polled once a day while it
    still knows nothing about itself.
    """
    unmeasured = WatermarkState(observed_rate_per_hour=None)
    dead = WatermarkState(observed_rate_per_hour=0.0)

    assert next_interval(unmeasured, CFG) < next_interval(dead, CFG)
    assert next_interval(unmeasured, CFG) == HOUR


def test_the_interval_targets_the_window_before_the_hundred_item_ceiling():
    """20 posts/hour and a 60-post target is a 3-hour interval."""
    state = WatermarkState(observed_rate_per_hour=20.0)
    assert next_interval(state, CFG) == 3 * HOUR


def test_a_busier_subreddit_is_polled_more_often():
    slow = WatermarkState(observed_rate_per_hour=5.0)
    fast = WatermarkState(observed_rate_per_hour=40.0)
    assert next_interval(fast, CFG) < next_interval(slow, CFG)


def test_the_window_target_stays_inside_the_rss_ceiling():
    """The whole design rests on this: 100 items is a hard ceiling (U5)."""
    assert CFG.window_target < 100


def test_empty_polls_back_the_interval_off():
    busy = WatermarkState(observed_rate_per_hour=20.0)
    quiet = WatermarkState(observed_rate_per_hour=20.0, consecutive_empty=4)
    assert next_interval(quiet, CFG) > next_interval(busy, CFG)


def test_the_empty_backoff_stops_at_the_cap():
    at_cap = WatermarkState(observed_rate_per_hour=20.0, consecutive_empty=CFG.empty_cap)
    way_past = WatermarkState(observed_rate_per_hour=20.0, consecutive_empty=500)
    assert next_interval(at_cap, CFG) == next_interval(way_past, CFG)


def test_yield_speeds_up_a_productive_subreddit():
    state = WatermarkState(observed_rate_per_hour=20.0)
    assert next_interval(state, CFG, yield_ratio=0.5) < next_interval(state, CFG)


def test_a_negative_yield_cannot_slow_the_interval_down():
    state = WatermarkState(observed_rate_per_hour=20.0)
    assert next_interval(state, CFG, yield_ratio=-3.0) == next_interval(state, CFG)


# --------------------------------------------------------------------------
# the clamp
# --------------------------------------------------------------------------


def test_a_torrent_is_clamped_to_the_minimum():
    state = WatermarkState(observed_rate_per_hour=100_000.0)
    assert next_interval(state, CFG) == CFG.min_interval


def test_a_trickle_is_clamped_to_the_maximum():
    state = WatermarkState(observed_rate_per_hour=0.001)
    assert next_interval(state, CFG) == CFG.max_interval


def test_the_result_is_always_within_the_clamp():
    """Property test over the whole reachable input space."""
    for rate in (0.01, 0.5, 1, 7, 20, 60, 500, 10_000):
        for empty in (0, 1, 3, 6, 50):
            for yield_ratio in (0.0, 0.1, 0.9, 5.0):
                state = WatermarkState(observed_rate_per_hour=rate, consecutive_empty=empty)
                interval = next_interval(state, CFG, yield_ratio=yield_ratio)
                assert CFG.min_interval <= interval <= CFG.max_interval


def test_a_contradictory_config_favours_polling_too_often():
    """Polling too often is recoverable; never polling is not."""
    cfg = PolicyConfig(
        min_interval=datetime.timedelta(hours=6),
        max_interval=datetime.timedelta(hours=1),
    )
    state = WatermarkState(observed_rate_per_hour=20.0)
    assert next_interval(state, cfg) == cfg.min_interval


# --------------------------------------------------------------------------
# overflow response, scheduling, budget
# --------------------------------------------------------------------------


def test_overflow_halves_the_interval():
    """D1: whatever rate we believed, it was at least twice too slow."""
    assert shortened_after_overflow(8 * HOUR, CFG) == 4 * HOUR


def test_a_shortened_interval_still_respects_the_floor():
    assert shortened_after_overflow(CFG.min_interval, CFG) == CFG.min_interval


def test_due_at_is_now_plus_the_interval():
    now = datetime.datetime(2026, 8, 8, 12, 0, 0)
    state = WatermarkState(observed_rate_per_hour=20.0)
    assert due_at(now, state, CFG) == now + 3 * HOUR


def test_the_policy_computes_an_interval_in_under_a_millisecond():
    """A metric of the phase: policy computes an interval in < 1 ms."""
    state = WatermarkState(observed_rate_per_hour=20.0, consecutive_empty=3)

    start = time.perf_counter()
    for _ in range(1_000):
        next_interval(state, CFG, yield_ratio=0.2)
    per_call_ms = ((time.perf_counter() - start) / 1_000) * 1_000

    assert per_call_ms < 1.0, f"{per_call_ms:.4f} ms per call"


# --------------------------------------------------------------------------
# the deleted heuristic
# --------------------------------------------------------------------------


def test_there_is_no_density_threshold_setting():
    """P6 removed the density-adaptive body fetch; its config key went with it.

    The heuristic chose between an HTML listing page and a permalink for post
    bodies. P5 measured that a listing page carries no body at all (freeze §11,
    2026-08-08), so the listing branch spent a request and returned nothing at
    any density. A key nothing reads is a documented capability that does not
    exist, which is the defect this asserts against.
    """
    assert not hasattr(PolicyConfig(), "density_threshold")
    with pytest.raises(TypeError):
        PolicyConfig(density_threshold=0.25)
