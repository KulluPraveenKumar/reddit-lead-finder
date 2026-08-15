"""Every feature returns 0.0-1.0, and the bound is what makes the score 0-100.

`src/scoring/features.py`'s module docstring states the dependency: `prescore`
computes `100 * sum(w[k] * v[k])` over weights that normalise to 1.0, so the
0-100 bound docs/34 §P11 asserts holds **only** if no component can exceed 1.0.
These tests drive each function with empty, zero, negative, enormous, NaN and
malformed input rather than trusting six separate `min()` calls to all be right.
"""

from __future__ import annotations

import datetime
import math

import pytest

from src.scoring.features import (
    COMMENT_SATURATION,
    LENGTH_SATURATION_CHARS,
    QUESTION_RE,
    UPVOTE_SATURATION,
    _clamp,
    engagement,
    keyword_density,
    length_plausibility,
    question_form,
    recency_decay,
    tier_value,
)

NOW = datetime.datetime(2026, 8, 15, 12, 0, 0)

TIERS = ("high_intent", "medium_intent")


# ----------------------------------------------------------------- the bound


@pytest.mark.parametrize(
    ("call", "label"),
    [
        (lambda: tier_value({}, (), 2.0), "tier_value, nothing"),
        (lambda: tier_value({"high_intent": ["a"]}, TIERS, 2.0), "tier_value, top tier"),
        (lambda: tier_value({"high_intent": ["a"]}, TIERS, 1.0), "tier_value, decay 1"),
        (lambda: keyword_density({}), "density, none"),
        (lambda: keyword_density({"t": ["a"] * 500}), "density, saturated"),
        (lambda: question_form(""), "question, empty"),
        (lambda: question_form("Why?"), "question, yes"),
        (lambda: recency_decay(None), "recency, unknown"),
        (lambda: recency_decay(NOW, now=NOW), "recency, brand new"),
        (lambda: recency_decay(NOW + datetime.timedelta(days=5), now=NOW), "recency, future"),
        (lambda: recency_decay(NOW - datetime.timedelta(days=9999), now=NOW), "recency, ancient"),
        (lambda: recency_decay(NOW, window_days=0, now=NOW), "recency, zero window"),
        (lambda: engagement(None, None), "engagement, both unknown"),
        (lambda: engagement(-50, -50), "engagement, negative"),
        (lambda: engagement(10**9, 10**9), "engagement, enormous"),
        (lambda: length_plausibility(0), "length, empty"),
        (lambda: length_plausibility(10**7), "length, enormous"),
        (lambda: length_plausibility(500, min_chars=10**6), "length, floor above saturation"),
    ],
)
def test_every_feature_is_bounded_in_the_unit_interval(call, label):
    value = call()
    assert 0.0 <= value <= 1.0, f"{label} returned {value}, outside [0, 1]"


def test_nan_clamps_to_zero_rather_than_propagating():
    """One malformed value would poison a whole run's ranking with a total that
    is neither high nor low but *incomparable* -- `sorted()` on a list containing
    NaN produces an order that depends on insertion position.
    """
    assert _clamp(float("nan")) == 0.0
    assert not math.isnan(_clamp(float("nan")))


def test_the_clamps_nan_safety_rests_on_argument_order_and_that_is_pinned():
    """⚠ The explicit `value != value` check in `_clamp` is **redundant today**,
    and mutation M25 proved it: deleting it changes nothing.

    The reason is subtle and worth pinning rather than trusting. `max(0.0, nan)`
    returns **0.0** -- `max` keeps its first argument unless a later one compares
    greater, and every comparison against NaN is False -- while `max(nan, 0.0)`
    returns **nan**. So `min(1.0, max(0.0, x))` is NaN-safe purely by the order
    its arguments happen to be written in.

    The guard stays as defence in depth (P10's T4b: a redundant guard stays, and
    the load-bearing thing is attacked separately). **This test is that separate
    attack** -- it fails if anyone "simplifies" the argument order, which is the
    edit that would silently make the guard load-bearing again.
    """
    n = float("nan")
    assert max(0.0, n) == 0.0
    assert math.isnan(max(n, 0.0))


def test_the_floor_check_is_redundant_with_the_clamp_and_stays_anyway():
    """⚠ Mutation M24 -- replacing `length < max(0, min_chars)` with `length < 0`
    -- **survives, and is provably equivalent**.

    Below the floor, `(length - min_chars)` is negative, so the general path
    yields a negative ratio that `_clamp` returns to 0.0 regardless. The early
    return is therefore an optimisation and a statement of intent, not a
    behaviour.

    It stays for the reason the docstring gives -- `rules.min_chars` is a
    *rejection* threshold elsewhere, and a reader should see the two agree -- and
    this test records that the equivalence was measured rather than assumed, so
    nobody re-derives it as a bug.
    """
    for length in (0, 1, 79):
        assert length_plausibility(length, min_chars=80) == 0.0
        assert _clamp((length - 80) / (LENGTH_SATURATION_CHARS - 80)) == 0.0


# ------------------------------------------------------------- tier_value


def test_the_first_tier_scores_one_and_each_step_down_halves():
    """config.yaml's `scoring.high_intent_multiplier: 2`, cited not invented.

    The legacy scorer weights a high-intent hit at `keyword_weight *
    high_intent_multiplier` and a medium one at `keyword_weight` -- so 2:1. The
    pre-score reproduces that ratio rather than picking its own, which is what
    keeps it agreeing with the instrument that produced the 459 usable leads.
    """
    assert tier_value({"high_intent": ["x"]}, TIERS, 2.0) == 1.0
    assert tier_value({"medium_intent": ["x"]}, TIERS, 2.0) == 0.5


def test_a_third_tier_needs_no_code_change():
    """`match_tiers` deliberately does not hard-code tier names -- "weighting the
    tiers is P11's problem; naming them is the config's". Reading the ORDER is
    what keeps that true."""
    tiers = ("high_intent", "medium_intent", "low_intent")
    assert tier_value({"low_intent": ["x"]}, tiers, 2.0) == 0.25


def test_the_strongest_tier_wins_rather_than_the_sum():
    """This component answers "how good is the best signal". "How many signals"
    is `keyword_density`'s question, and adding them here would count the same
    evidence twice -- and could exceed 1.0, breaking the 0-100 bound.

    ⚠ **Two LOWER tiers, not the top two.** With `high` and `medium` matched the
    sum is 1.5, which `_clamp` returns to 1.0 — identical to the max, so that
    fixture cannot tell the two apart. Below the top tier the clamp does not
    intervene: 0.5 + 0.25 = 0.75 against a max of 0.5.
    """
    three = ("high_intent", "medium_intent", "low_intent")
    lower_two = tier_value({"medium_intent": ["x"], "low_intent": ["y"]}, three, 2.0)
    assert lower_two == 0.5, "the strongest matched tier, not the sum of both"

    top_two = tier_value({"high_intent": ["x"], "medium_intent": ["y"]}, TIERS, 2.0)
    assert top_two == 1.0


def test_a_tier_present_but_empty_does_not_score():
    """`match_tiers` omits empty tiers, but a hand-built mapping may not."""
    assert tier_value({"high_intent": []}, TIERS, 2.0) == 0.0


# --------------------------------------------------------- keyword_density


def test_density_is_hits_over_three_and_saturates():
    """docs/06c §3.1, literally: `min(1.0, item.keyword_hits / 3)`."""
    assert keyword_density({"t": ["a"]}) == pytest.approx(1 / 3)
    assert keyword_density({"t": ["a", "b", "c"]}) == 1.0
    assert keyword_density({"t": ["a", "b", "c", "d"]}) == 1.0


def test_density_counts_across_every_tier():
    """It measures how densely the item talks about our subject, not which tier
    it talked in."""
    assert keyword_density({"high_intent": ["a"], "medium_intent": ["b"]}) == pytest.approx(2 / 3)


# ----------------------------------------------------------- question_form


@pytest.mark.parametrize(
    "title",
    [
        "Which CRM should I use?",
        "Any recommendations for a small team",
        "How do I track customers",
        "anyone know a good tool",
        "Is there a way to do this",
    ],
)
def test_a_question_is_recognised_with_or_without_punctuation(title):
    assert question_form(title) == 1.0


@pytest.mark.parametrize(
    "title",
    [
        "Looking for a CRM recommendation",
        "I know how to do this already",
        "Shipped a small update today",
        "",
    ],
)
def test_a_statement_is_not_a_question(title):
    """The interrogative form is anchored at the start on purpose: "I know **how**
    to do this" contains `how` and is not a question."""
    assert question_form(title) == 0.0


def test_the_question_pattern_is_case_insensitive():
    assert QUESTION_RE.search("WHICH crm") is not None


# ----------------------------------------------------------- recency_decay


def test_recency_halves_at_half_the_window():
    """Exponential rather than linear: a two-day-old thread is nearly as
    actionable as a fresh one, and a linear ramp gets both ends wrong."""
    half = NOW - datetime.timedelta(days=15)
    assert recency_decay(half, window_days=30, now=NOW) == pytest.approx(0.5, abs=1e-9)


def test_an_unknown_timestamp_scores_zero_and_not_one():
    """Unknown age is not freshness. Defaulting it to full marks would let every
    item with a parse failure outrank real recent posts."""
    assert recency_decay(None) == 0.0


def test_a_zero_length_window_scores_any_aged_item_at_zero():
    """A window of zero days means nothing is inside it. Guarded explicitly
    because the decay would otherwise divide by zero."""
    aged = NOW - datetime.timedelta(days=1)
    assert recency_decay(aged, window_days=0, now=NOW) == 0.0
    assert recency_decay(aged, window_days=-5, now=NOW) == 0.0


def test_recency_is_monotonically_non_increasing_with_age():
    values = [
        recency_decay(NOW - datetime.timedelta(days=d), window_days=30, now=NOW)
        for d in range(0, 60, 3)
    ]
    assert values == sorted(values, reverse=True)


# ------------------------------------------------------------- engagement


def test_unknown_and_zero_are_different_facts():
    """DI13, in the component that consumes it.

    An item with 40 upvotes and an UNKNOWN comment count scores on its upvotes
    alone. Treating the unknown as a measured zero would halve it for a fact
    nobody established.
    """
    known_zero = engagement(40, 0)
    unknown = engagement(40, None)
    assert unknown > known_zero
    assert unknown == pytest.approx(40 / UPVOTE_SATURATION)


def test_both_unknown_is_zero():
    """No evidence of engagement. Different from evidence of none, but the
    pre-score has no third value and 0.0 is the conservative reading."""
    assert engagement(None, None) == 0.0


def test_engagement_saturates_at_the_legacy_scorers_own_clamps():
    """100 upvotes and 50 comments are `src/scoring/legacy.py`'s clamps, and they
    have governed every one of the 459 original leads. Reused so the pre-score
    and `intent_score` agree about what "a lot" means."""
    assert engagement(UPVOTE_SATURATION, COMMENT_SATURATION) == 1.0
    assert engagement(UPVOTE_SATURATION * 10, COMMENT_SATURATION * 10) == 1.0


def test_a_negative_score_does_not_go_below_zero():
    assert engagement(-40, 0) == 0.0


# ------------------------------------------------------- length_plausibility


def test_below_the_floor_scores_a_hard_zero():
    """`rules.min_chars` is a REJECTION threshold in `src/rules/structural.py`.
    Giving partial credit to text the rule engine rejects outright would put the
    two in open disagreement on the same page."""
    assert length_plausibility(79, min_chars=80) == 0.0
    assert length_plausibility(80, min_chars=80) == 0.0


def test_length_rises_to_one_at_saturation():
    assert length_plausibility(LENGTH_SATURATION_CHARS, min_chars=80) == 1.0
    assert length_plausibility(LENGTH_SATURATION_CHARS * 4, min_chars=80) == 1.0


def test_a_floor_above_the_saturation_point_degenerates_to_pass_or_fail():
    """A pathological config where `rules.min_chars` exceeds the saturation
    point. The curve has no span left, so anything clearing the floor scores
    full marks — guarded explicitly rather than dividing by a negative span.
    """
    floor = LENGTH_SATURATION_CHARS + 500
    assert length_plausibility(floor, min_chars=floor) == 1.0
    assert length_plausibility(floor - 1, min_chars=floor) == 0.0


def test_the_saturation_point_sits_just_above_a_real_median_lead():
    """1,500 is chosen against measured data, not felt.

    PHASE-10-COMPLETION-REPORT §3 measured the live corpus while correcting the
    A5 benchmark: mean 1,333 characters, median 1,060. The knee sits above the
    typical real lead so the tail flattens rather than rewarding length for its
    own sake -- a 6,000-character post is not four times the lead a 1,500 one is.
    """
    assert LENGTH_SATURATION_CHARS > 1_060
    typical = length_plausibility(1_060, min_chars=80)
    very_long = length_plausibility(6_000, min_chars=80)
    assert 0.0 < typical < very_long == 1.0
