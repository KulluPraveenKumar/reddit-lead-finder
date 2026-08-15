"""The funnel sums, reconciles two vocabularies, and refuses to invent a rate.

docs/34 §P11 task 2, docs/06c §3.2, and DI23. docs/35 §6's manual check for this
phase is *"read the funnel counts on the run page; they sum correctly"* — so the
arithmetic is asserted here as well, rather than left for a human to add up.
"""

from __future__ import annotations

import pytest

from src.scoring.funnel import (
    FUNNEL_EVENT,
    TRIAGE_TO_GATE,
    FunnelReport,
    FunnelStage,
    to_gate_vocabulary,
)

# --------------------------------------------------------------- it sums


def test_admitted_plus_rejected_equals_collected():
    stage = FunnelStage("full", collected=10)
    stage.admit(4)
    stage.count("negative_term", n=6)
    assert stage.rejected == 6
    assert stage.sums()


def test_a_funnel_that_lost_an_item_says_so():
    """A funnel that does not sum has lost items between the gate and the
    counter, and that loss is invisible in every other view."""
    stage = FunnelStage("full", collected=10)
    stage.admit(4)
    stage.count("negative_term", n=5)
    assert not stage.sums()
    assert stage.to_dict()["sums"] is False


def test_a_funnel_that_double_counted_also_says_so():
    """The other direction, and it needs its own case.

    Undercounting alone is caught by `==` and by `>=` alike, so a test that only
    loses items lets `sums()` be weakened to `>=` without failing. Double
    counting is what a broken idempotence guard produces — the exact failure
    `prescore_exists` prevents — so it is the direction most likely to happen.
    """
    stage = FunnelStage("full", collected=10)
    stage.admit(6)
    stage.count("negative_term", n=6)
    assert stage.rejected + stage.admitted == 12
    assert not stage.sums()


def test_counting_the_same_reason_twice_accumulates():
    stage = FunnelStage("full", collected=2)
    stage.count("structural_noise", detail="hiring")
    stage.count("structural_noise", detail="megathread")
    assert stage.rejected_by_reason == {"structural_noise": 2}
    assert stage.detail_by_reason["structural_noise"] == {"hiring": 1, "megathread": 1}


# ------------------------------------------------------------- DI23


def test_a_triage_reason_is_mapped_onto_the_gate_vocabulary():
    stage = FunnelStage("metadata", collected=1)
    stage.count("bot_author")
    assert stage.rejected_by_reason == {"bot_or_deleted": 1}


def test_the_five_structural_reasons_collapse_but_keep_their_names():
    stage = FunnelStage("metadata", collected=5)
    for reason in ("hiring", "giveaway", "megathread", "ama", "engagement_bait"):
        stage.count(reason)
    assert stage.rejected_by_reason == {"structural_noise": 5}
    assert stage.detail_by_reason["structural_noise"] == {
        "ama": 1,
        "engagement_bait": 1,
        "giveaway": 1,
        "hiring": 1,
        "megathread": 1,
    }


def test_an_explicit_detail_beats_the_mapped_one():
    """`negative_term` carries the matched term, which the mapping cannot know."""
    stage = FunnelStage("full", collected=1)
    stage.count("negative_term", detail="crypto")
    assert stage.detail_by_reason["negative_term"] == {"crypto": 1}


def test_an_unmapped_reason_is_counted_under_its_own_name():
    """Dropping it would make the funnel under-report by exactly the amount
    nobody noticed — and the run page's headline check is that it sums."""
    stage = FunnelStage("full", collected=1)
    stage.count("some_future_reason")
    assert stage.rejected_by_reason == {"some_future_reason": 1}
    assert stage.sums(), "an unmapped reason must still keep the arithmetic whole"


def test_the_mapping_is_display_only_and_changes_no_writer():
    """P6's triage still writes its own nine spellings; the map is applied at the
    counter. Converging the WRITERS would change shipped behaviour on a live
    path, which is what DI23 says must not happen in passing.
    """
    from src.discovery.triage import REASONS as TRIAGE_REASONS

    assert "bot_author" in TRIAGE_REASONS
    assert "bot_or_deleted" not in TRIAGE_REASONS
    assert TRIAGE_TO_GATE["bot_author"] == "bot_or_deleted"


def test_to_gate_vocabulary_is_a_pure_function():
    assert to_gate_vocabulary("hiring") == ("structural_noise", "hiring")
    assert to_gate_vocabulary("negative_term") == ("negative_term", None)


# ------------------------------------------------------------ the rates


def test_the_hard_filter_rate_excludes_the_tunable_dial():
    """A2 is about the HARD filters. `below_prescore` is docs/06c §3.2's "tunable
    dial", and folding it in would let an operator move A2 by editing one config
    key — a structural rate you can tune is not a measurement of anything.
    """
    report = FunnelReport()
    report.full.collected = 100
    report.full.count("structural_noise", n=50)
    report.full.count("below_prescore", n=30)
    report.full.admit(20)

    assert report.hard_filter_rate == pytest.approx(0.50)
    assert report.full.rejected == 80


def test_a_rate_over_zero_items_is_none_and_not_zero():
    """A rate over nothing is undefined, and reporting 0% would read as "the
    filters removed nothing"."""
    report = FunnelReport()
    assert report.hard_filter_rate is None
    assert report.collapse_rate is None
    assert report.to_dict()["hard_filter_rate"] is None


def test_the_assumed_rate_is_carried_alongside_the_measured_one():
    """docs/34 §P11: "A2 measured — real hard-filter rate recorded AGAINST the
    assumed 73%". A measurement with nothing to compare it to is a number."""
    assert FunnelReport().to_dict()["hard_filter_rate_assumed"] == 0.73


def test_the_collapse_rate_counts_collapsed_members_not_groups():
    """P10's transferred measurement (freeze §11.1). P10 measured 5.74% on a
    cross-run ARCHIVE; P11 has the first live call site and measures within one
    run, which is what the ">8%" target was always about.

    ⚠ `grouped` and `groups` are deliberately different numbers here. A fixture
    where one group holds two items makes them equal, and then a rate computed
    from the wrong one is indistinguishable — docs/06c §8 is explicit that
    grouping *"does not discard 142 items — it discards 95 and keeps 47
    representatives"*, so the rate is about **members resolved**, not clusters
    formed.
    """
    report = FunnelReport()
    report.full.collected = 200
    report.grouped = 20
    report.groups = 7
    assert report.collapse_rate == pytest.approx(0.10)
    assert report.collapse_rate != pytest.approx(report.groups / 200)


def test_both_stages_are_reported_separately():
    """A metadata rejection and a full-stage rejection are facts about different
    populations — the first saw a title, the second saw a body. One combined
    total would let a triage regression hide inside a full-stage improvement."""
    payload = FunnelReport().to_dict()
    assert payload["metadata"]["stage"] == "metadata"
    assert payload["full"]["stage"] == "full"


def test_the_event_name_is_shared_by_the_writer_and_the_reader():
    """Defined in `src/scoring/funnel.py` rather than the handler, so
    `RunService.progress` can read it without importing an orchestration handler
    — which would be a cycle, because the handlers import `RunService`."""
    from src.orchestration.handlers import prescore as stage
    from src.orchestration.run_service import FUNNEL_EVENT as reader_side

    assert stage.FUNNEL_EVENT == FUNNEL_EVENT == reader_side == "pipeline.funnel"
