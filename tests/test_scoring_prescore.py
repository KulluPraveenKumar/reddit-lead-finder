"""The pre-score: bounded, deterministic, and rejecting for the right reason.

docs/34 §P11's Objective — *"every collected item has a deterministic 0-100 score
with stored components"* — plus the two criteria transferred from P10 by
freeze §11.1, and the six-components-three-absent decision **D1**.
"""

from __future__ import annotations

import datetime

import pytest

from src.rules import RulesSettings
from src.scoring import (
    ABSENT_COMPONENTS,
    BELOW_PRESCORE,
    DECISION_ADMIT,
    DECISION_REJECT,
    OUT_OF_WINDOW,
    WEIGHTS,
    PrescoreSettings,
    normalised_weights,
)
from src.scoring.prescore import DISABLED, ScoredItem, prescore

NOW = datetime.datetime(2026, 8, 15, 12, 0, 0)

TIERS = {
    "high_intent": ["looking for", "any recommendations", "what tool do you use"],
    "medium_intent": ["how do i", "struggling with", "need help with"],
}

LONG_BODY = (
    "We are a five person team and our spreadsheets are falling apart. I have been "
    "struggling with keeping track of who spoke to which customer and I need help with "
    "choosing something that will not cost a fortune to run every month. "
)


def item(**kwargs) -> ScoredItem:
    defaults = {
        "title": "Looking for a CRM - any recommendations?",
        "body": LONG_BODY * 2,
        "author": "a_real_person",
        "score": 42,
        "num_comments": 17,
        "created_utc": NOW - datetime.timedelta(days=1),
    }
    return ScoredItem(**{**defaults, **kwargs})


def score(it: ScoredItem, settings: PrescoreSettings | None = None, **kwargs):
    return prescore(
        it,
        settings or PrescoreSettings(),
        keyword_tiers=TIERS,
        now=NOW,
        **kwargs,
    )


# --------------------------------------------------------------- the bound


def test_the_weights_normalise_to_exactly_one():
    """The 0-100 bound rests on this, and on every feature returning <= 1.0.

    Stored raw and divided at call time rather than pre-divided into constants:
    the cited values stay traceable to docs/04 §9.1, the arithmetic is exact
    (pre-rounded they sum to 1.01), and P12's three components slot in without
    re-tuning the six that shipped.
    """
    assert sum(normalised_weights(WEIGHTS).values()) == pytest.approx(1.0)


def test_a_maximal_item_cannot_exceed_one_hundred():
    result = score(
        item(
            title="Looking for a CRM - any recommendations - what tool do you use?",
            body=LONG_BODY * 20,
            score=10**6,
            num_comments=10**6,
            created_utc=NOW,
        )
    )
    assert 0.0 <= result.total <= 100.0


def test_a_minimal_item_cannot_go_below_zero():
    result = score(item(title="x", body="", score=None, num_comments=None, created_utc=None))
    assert result.total >= 0.0


def test_the_score_is_deterministic():
    """Re-runnable at zero cost is the property the whole local-first argument
    rests on -- and the -5% comment measurement is not reproducible without it."""
    it = item()
    assert len({score(it).total for _ in range(25)}) == 1


# ------------------------------------------------------------- D1, absent


def test_six_components_ship_and_the_three_project_ones_do_not():
    """Operator decision **D1**. Shipping the three at 0.0 would be DI24's own
    failure mode -- a score nobody noticed was always zero -- inside the phase
    whose job is fixing DI24."""
    result = score(item())
    assert set(result.components) == {
        "keyword_tier",
        "keyword_density",
        "question_form",
        "recency",
        "engagement",
        "length",
    }
    assert set(result.absent) == {"pain_phrase", "competitor", "subreddit_fit"}


def test_every_absent_component_names_the_phase_that_supplies_it():
    """A register entry with no owner is an idea. So is an absence with no owner."""
    for name, owner in ABSENT_COMPONENTS.items():
        assert owner.strip(), f"{name} is declared absent with no owning phase"
        assert "P1" in owner or "P15" in owner


def test_an_absent_component_is_never_silently_scored_as_zero():
    """The distinction P12 will need: "did not exist" against "scored 0.0"."""
    result = score(item())
    for name in ABSENT_COMPONENTS:
        assert name not in result.components


# ----------------------------------------------------- the admission floor


def test_a_strong_lead_is_admitted():
    result = score(item())
    assert result.decision == DECISION_ADMIT
    assert result.reason is None
    assert result.total >= 35.0


def test_a_weak_item_is_rejected_below_prescore_with_the_arithmetic_in_the_detail():
    """`below_prescore` is docs/06c §3.2's "tunable dial", and an operator who
    cannot see the number cannot tune it."""
    result = score(
        item(
            title="Shipped a small update today",
            body="A quiet week of cleaning up rough edges that had been bothering me.",
            score=2,
            num_comments=0,
            created_utc=NOW - datetime.timedelta(days=4),
        )
    )
    assert result.decision == DECISION_REJECT
    assert result.reason == BELOW_PRESCORE
    assert "<" in result.detail


def test_the_floor_is_the_balanced_fallback_from_06c():
    """docs/06c §3.3's `balanced` row, fallback column: >= 35. The adaptive cut is
    docs/06f's and needs `ai_budgets` (revision 0009, P19), so at P11 the
    fallback is correct rather than a shortcut."""
    assert PrescoreSettings().admission_floor == 35.0


def test_an_item_exactly_on_the_floor_is_admitted():
    """The comparison is `total < floor`, so equality admits.

    Driven at the exact boundary rather than at 0 and 100, because a `<` -> `<=`
    mutation passes every test that only checks "high admits, low rejects". This
    is the one item in the corpus that distinguishes them.
    """
    exact = score(item()).total
    assert score(item(), PrescoreSettings(admission_floor=exact)).decision == DECISION_ADMIT


def test_an_item_a_hundredth_below_the_floor_is_rejected():
    """The other side of the same boundary."""
    exact = score(item()).total
    just_over = PrescoreSettings(admission_floor=exact + 0.01)
    assert score(item(), just_over).decision == DECISION_REJECT


# --------------------------------------------------------- the hard filters


def test_out_of_window_is_checked_before_the_floor():
    """P11's other reason. An item can be BOTH out of window and above the floor,
    and reporting the floor would hide the real cause from the funnel."""
    result = score(item(created_utc=NOW - datetime.timedelta(days=400)))
    assert result.reason == OUT_OF_WINDOW
    assert result.total >= 35.0, "the fixture must also clear the floor, or it proves nothing"


def test_a_hard_filter_rejection_reports_p9s_reason_not_p11s():
    """`src.rules.evaluate` owns four reasons; the pre-score passes them through
    rather than relabelling, so the funnel counts eight distinct causes."""
    result = score(item(title="[HIRING] Senior backend engineer, remote"))
    assert result.decision == DECISION_REJECT
    assert result.reason == "structural_noise"
    assert result.detail == "hiring"


def test_a_bot_author_is_rejected():
    result = score(item(author="AutoModerator"))
    assert result.reason == "bot_or_deleted"


def test_min_chars_is_bound_to_a_body_for_the_first_time():
    """config.yaml has carried the note since P9: "nothing binds this key to a
    body until P11". This is that binding.

    P9's `evaluate` skips the length check entirely when `text is None`; the
    pre-score always supplies it, so `rules.min_chars` starts doing work.
    """
    short = score(item(body="tiny"))
    assert short.decision == DECISION_REJECT
    assert short.reason == "too_short"


def test_a_negative_term_is_rejected_and_names_the_term():
    result = score(item(), negative_terms=("crm",))
    assert result.reason == "negative_term"
    assert result.detail == "crm"


# ------------------------------------------------ every item is fully scored


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"title": "[HIRING] backend engineer"}, "structural_noise"),
        ({"author": "AutoModerator"}, "bot_or_deleted"),
        ({"created_utc": NOW - datetime.timedelta(days=400)}, OUT_OF_WINDOW),
    ],
)
def test_a_rejected_item_still_carries_all_six_components(kwargs, expected):
    """docs/34 §P11 requires a `prescores` row for every collected item, admitted
    or not -- and a row whose components are empty because it was rejected early
    is a row the holdout audit cannot compare against."""
    result = score(item(**kwargs))
    assert result.reason == expected
    assert len(result.components) == 6
    assert result.total > 0.0


# ----------------------------------------------------------- the rollback


def test_the_rollback_admits_everything_with_no_score_and_says_so():
    """docs/34 §P11's Rollback row: "items keep `intent_score` only".

    The named `DISABLED` detail is what separates the rollback from a real item
    that merely happens to score 0.0 -- which a post with no keywords, no
    engagement and a short body also does.
    """
    result = score(item(title="[HIRING] backend engineer"), PrescoreSettings(enabled=False))
    assert result.decision == DECISION_ADMIT
    assert result.total == 0.0
    assert result.components == {}
    assert result.detail == DISABLED


def test_the_rollback_runs_no_regex_at_all():
    """P9's D4 shape: the flag is honoured INSIDE the package, so it still works
    if a future call site forgets to check it."""
    disabled = PrescoreSettings(enabled=False)
    for title in ("[HIRING] x", "Weekly megathread", ""):
        assert prescore(ScoredItem(title=title), disabled).admitted


def test_deleting_the_config_block_reproduces_the_defaults_exactly():
    """The property `rules:`, `dedup:`, `notify:` and `discovery:` each document.
    A rollback by deletion must behave identically to a rollback by flag."""
    assert PrescoreSettings.from_config(None) == PrescoreSettings.from_config({})
    assert PrescoreSettings.from_config({}) == PrescoreSettings()


# -------------------------------------------------------------- settings


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"admission_floor": -1.0}, "must be in"),
        ({"admission_floor": 101.0}, "must be in"),
        ({"holdout_rate": 1.5}, "must be in"),
        ({"window_days": 0}, "must be >= 1"),
        ({"tier_decay": 0.5}, "must be >= 1.0"),
        ({"weights": {}}, "is empty"),
        ({"weights": {"a": -1.0}}, "must be >= 0"),
        ({"weights": {"a": 0.0}}, "sum to 0"),
    ],
)
def test_a_nonsensical_setting_is_refused_loudly(kwargs, match):
    with pytest.raises(ValueError, match=match):
        PrescoreSettings(**kwargs)


def test_a_tier_decay_below_one_is_refused_because_it_inverts_the_tiers():
    """Below 1.0 the second tier would outrank the first, which inverts the
    meaning of "high intent" rather than tuning it."""
    with pytest.raises(ValueError, match="high_intent_multiplier"):
        PrescoreSettings(tier_decay=0.9)


def test_unknown_config_keys_are_ignored_rather_than_rejected():
    """A config that refused to load because of a stray key would turn a typo
    into an outage -- the rule every settings object here follows."""
    settings = PrescoreSettings.from_config({"pipeline": {"nonsense": True}})
    assert settings.enabled is True


def test_a_tier_whose_value_is_not_a_list_is_skipped_rather_than_iterated():
    """`keyword_tiers_of` is DI24's fix, and it must not introduce DI24's own
    failure in reverse: a tier written as a bare string would iterate into
    single CHARACTERS, and every title containing the letter "a" would match.
    """
    from src.scoring import keyword_tiers_of

    tiers = keyword_tiers_of(
        {"keywords": {"high_intent": "looking for", "medium_intent": ["how do i"], "bad": 7}}
    )
    assert tiers == {"medium_intent": ["how do i"]}


def test_a_keywords_block_that_is_not_a_mapping_yields_nothing():
    """An empty tier map scores every keyword component at 0.0 honestly, rather
    than crashing a run over a malformed optional block."""
    from src.scoring import keyword_tiers_of

    assert keyword_tiers_of({"keywords": ["a", "list"]}) == {}
    assert keyword_tiers_of({}) == {}
    assert keyword_tiers_of(None) == {}


def test_rules_settings_are_threaded_through():
    """`min_chars` reaching the pre-score is what DI-era config comments promised."""
    lenient = score(item(body="tiny"), rules=RulesSettings(min_chars=1))
    assert lenient.reason != "too_short"
