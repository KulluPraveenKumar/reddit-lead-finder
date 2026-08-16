"""The P11 stage end to end — the criteria only a live call site can prove.

docs/34 §P11's Acceptance row, against a real database:

* every collected item has a `prescores` row, admitted or not
* **A2 measured** — the real hard-filter rate against the assumed 73%
* a group of N yields **N distinct pre-scores** *(transferred from P10, D1)*
* the intra-run collapse rate is measured *(transferred from P10)*
* `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` = **0**
* the rollback leaves items with `intent_score` only
"""

from __future__ import annotations

import datetime

import pytest

from src.db.models import AICall, DedupGroup, DedupMember, Lead, Prescore, Run, RunEvent
from src.orchestration.handlers.prescore import run_prescore_stage
from src.scoring import DECISION_ADMIT, DECISION_GROUPED, DECISION_REJECT, STAGE_FULL

#: The clock every fixture in this file is built relative to.
#:
#: ⚠️ **It tracks the real clock, and pinning it to a literal date is a time
#: bomb — measured, not theorised.** This was
#: ``datetime.datetime(2026, 8, 15, 12, 0, 0)`` and the suite went red on
#: **2026-08-16** ([DI36](../docs/DEFERRED-IMPROVEMENTS.md)).
#:
#: The reason is a split that is easy to miss: the stage's *lead selection* is
#: bounded by ``Lead.scraped_at >= run.started_at``, which is relative to a row
#: and so is perfectly stable — but ``recency_decay`` is measured against the
#: **real** clock (``handlers/prescore.py``: ``now = datetime.now(UTC)``). So a
#: fixture pinned to a literal date does not age with the scorer. The lead
#: written as *"one hour old"* was a day old by the next morning and a week old
#: by the next Friday, while the *"28 days old"* one sat near the decay floor and
#: barely moved. In ``test_the_group_representative_is_chosen_by_pre_score_not_
#: by_upvotes`` the two totals were separated by about half a point and closed at
#: roughly that rate per day: ``59.19`` against ``59.26`` on the second morning.
#:
#: **Naive UTC, not ``datetime.now()``.** This machine is UTC+5:30, so the local
#: form would place every fixture five and a half hours in the future relative to
#: the scorer — an error large enough to change a recency score and invisible on
#: a UTC-configured host. ``src/db/models.py``'s ``_utcnow`` and the stage both
#: use exactly this expression; the schema stores naive UTC throughout.
#:
#: ``microsecond=0`` only so failure messages are readable.
NOW = datetime.datetime.now(datetime.UTC).replace(tzinfo=None, microsecond=0)

CONFIG = {
    "keywords": {
        "high_intent": ["looking for", "any recommendations", "what tool do you use"],
        "medium_intent": ["how do i", "struggling with", "need help with"],
    },
    "pipeline": {"prescore_enabled": True, "prescore_admission_floor": 35},
    "scraping": {"max_comment_posts": 0},  # no network in this suite
    "gate": {"metadata_holdout_rate": 0.02},
    "dedup": {"exact_enabled": True, "minhash_enabled": True},
}

STRONG_BODY = (
    "We are a five person team and our spreadsheets are falling apart. I have been "
    "struggling with keeping track of who spoke to which customer and I need help with "
    "picking something that does not cost a fortune every single month to operate. "
)


@pytest.fixture
def session(temp_db):
    from src.db.database import get_session

    with get_session() as s:
        yield s


@pytest.fixture
def run(session):
    row = Run(state="scraping", started_at=NOW - datetime.timedelta(hours=1))
    session.add(row)
    session.commit()
    return row


def add_lead(session, reddit_id, title, body=STRONG_BODY, **kwargs):
    defaults = {
        "subreddit": "SaaS",
        "author": "a_real_person",
        "url": f"https://www.reddit.com/r/SaaS/comments/{reddit_id}/x/",
        "post_type": "post",
        "score": 40,
        "num_comments": 12,
        "intent_score": 30.0,
        "created_utc": NOW - datetime.timedelta(days=1),
        "scraped_at": NOW,
    }
    lead = Lead(reddit_id=reddit_id, title=title, body=body, **{**defaults, **kwargs})
    session.add(lead)
    session.commit()
    return lead


# ------------------------------------------------- DI36: the clock itself


def test_the_fixture_clock_tracks_the_scorer_in_naive_utc():
    """[DI36](../docs/DEFERRED-IMPROVEMENTS.md), pinned so it cannot come back.

    Two ways to break :data:`NOW`, and only one of them is loud:

    * **A literal date.** Caught immediately — the fixtures stop ageing with the
      scorer and `test_the_group_representative_…` fails within a day. That is
      the bug this test exists because of.
    * **``datetime.now()`` instead of naive UTC.** Silent. This host is UTC+5:30,
      so every fixture lands *in the future* relative to the scorer's clock —
      and ``recency_decay`` **clamps a future timestamp to 1.0**, so the ordering
      the other tests assert still holds and nothing complains. The "28 days old"
      lead would really be 27.8 days old, and on a UTC-configured host the whole
      problem would be invisible. Measured: a mutation to the local form passed
      all 19 tests in this file.

    So the assertion is on the *offset from real UTC*, not on any score.
    """
    reference = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    drift = abs((NOW - reference).total_seconds())

    assert NOW.tzinfo is None, "the schema stores naive datetimes throughout"
    assert drift < 300, (
        f"NOW is {drift:.0f}s from real UTC. A literal date makes the fixtures stop "
        f"ageing with the scorer (DI36); a local-time clock puts them "
        f"{drift / 3600:.1f}h in the future, which recency_decay hides by clamping to 1.0."
    )


# ------------------------------------------------------- AC1: every item


def test_every_collected_item_gets_a_prescores_row_admitted_or_not(session, run):
    """docs/34 §P11's first acceptance line, and P6's transferred obligation."""
    add_lead(session, "t3_a", "Looking for a CRM - any recommendations?")
    add_lead(session, "t3_b", "[HIRING] Senior backend engineer")
    add_lead(session, "t3_c", "Shipped a small update", body="short")

    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    rows = session.query(Prescore).filter(Prescore.run_id == run.id).all()
    assert len(rows) == 3
    assert {r.stage for r in rows} == {STAGE_FULL}
    assert {r.gate_decision for r in rows} == {DECISION_ADMIT, DECISION_REJECT}


def test_every_prescore_row_stores_all_six_components(session, run):
    add_lead(session, "t3_a", "Looking for a CRM - any recommendations?")
    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    import json

    row = session.query(Prescore).filter(Prescore.run_id == run.id).one()
    components = json.loads(row.components_json)
    assert {
        "keyword_tier",
        "keyword_density",
        "question_form",
        "recency",
        "engagement",
        "length",
    } <= set(components)


def test_the_three_absent_components_are_recorded_as_absent_not_as_zero(session, run):
    """So a P12 reader can tell "did not exist yet" from "scored 0.0" — by then
    the components WILL exist, and a row that cannot distinguish them is a row
    that will be misread."""
    import json

    add_lead(session, "t3_a", "Looking for a CRM - any recommendations?")
    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    row = session.query(Prescore).filter(Prescore.run_id == run.id).one()
    components = json.loads(row.components_json)
    assert set(components["_absent"]) == {"pain_phrase", "competitor", "subreddit_fit"}
    for name in components["_absent"]:
        assert name not in components or name == "_absent"


def test_re_running_the_stage_writes_no_second_row(session, run):
    """R9 idempotence. A lease expiring mid-stage and re-running would otherwise
    DOUBLE every funnel count — the failure P6's identical guard prevents."""
    add_lead(session, "t3_a", "Looking for a CRM - any recommendations?")

    run_prescore_stage(session, run.id, CONFIG)
    session.commit()
    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    assert session.query(Prescore).filter(Prescore.run_id == run.id).count() == 1


# --------------------------------------------------------- AC7: 0 AI calls


def test_the_stage_makes_no_ai_call(session, run):
    """docs/34 §P11's bold criterion, and docs/35 §6's P11 row.

    Asserted as the criterion is written — a count over `ai_calls` for this run —
    rather than by trusting that the fence covers it. The fence proves the import
    is impossible; this proves the row count is zero on a real run.
    """
    for i in range(6):
        add_lead(session, f"t3_{i}", f"Looking for a CRM {i} - any recommendations?")

    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    assert session.query(AICall).filter(AICall.run_id == run.id).count() == 0
    assert session.query(AICall).count() == 0


# --------------------------------------- AC8: N distinct pre-scores, D1


def test_a_group_of_n_yields_n_distinct_prescores(session, run):
    """The criterion transferred from P10 by freeze §11.1.

    P10 proved N distinct MEMBERS and no score mutation; the pre-scores were
    P11's because `src/scoring/prescore.py` is P11's Files row. This is the other
    half — and it is the whole of docs/06c §4.4: **group for analysis, score
    individually**. Three near-identical threads with different engagement and
    recency are worth different amounts as leads, and emitting three identical
    numbers would make the operator correctly stop trusting the ranking.
    """
    body = STRONG_BODY * 2
    a = add_lead(session, "t3_a", "Which CRM should I use?", body=body, score=90, num_comments=40)
    b = add_lead(
        session,
        "t3_b",
        "**Which CRM should I use?**",
        body=body,
        score=5,
        num_comments=1,
        created_utc=NOW - datetime.timedelta(days=20),
    )
    c = add_lead(
        session,
        "t3_c",
        "Which CRM should I use?",
        body=body,
        score=30,
        num_comments=12,
        created_utc=NOW - datetime.timedelta(days=8),
    )

    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    rows = {r.lead_id: r for r in session.query(Prescore).filter(Prescore.run_id == run.id).all()}
    assert len(rows) == 3, "N members keep N rows"

    totals = [rows[x.id].total for x in (a, b, c)]
    assert len(set(totals)) == 3, f"a group of 3 must yield 3 DISTINCT pre-scores, got {totals}"

    # And the group actually formed, or the assertion above proves nothing.
    assert session.query(DedupGroup).filter(DedupGroup.run_id == run.id).count() == 1
    assert session.query(DedupMember).count() == 3


def test_two_members_identical_in_every_scored_dimension_share_a_pre_score(session, run):
    """⚠ **Measured on the live archive, 2026-08-15: "N distinct pre-scores" is
    not literally satisfiable, and that is determinism rather than a defect.**

    Leads 108/109 are one repost pair created **one minute apart** with identical
    text, both at 0 upvotes and 0 comments. Every component agrees to four
    decimals and the totals are both **32.28**; likewise 403/404, three minutes
    apart, both **47.61**. Two of the 23 real groups therefore yield fewer
    distinct numbers than they have members.

    What docs/06c §4.4 actually requires is *"group for analysis, **score
    individually**"* — that each member gets its **own** score, computed from its
    **own** metadata. Two posts identical in every scored dimension getting
    identical numbers is that rule working. Forcing distinctness would mean
    adding decimal places until sub-minute age differences showed up, which is
    gaming a criterion rather than measuring a lead.

    So the property asserted is the one that carries the meaning:
    **N members, N independently computed scores, and any difference in a scored
    input produces a different number** — which
    `test_a_group_of_n_yields_n_distinct_prescores` demonstrates directly.
    """
    body = STRONG_BODY * 2
    first = add_lead(session, "t3_a", "Which CRM should I use?", body=body, score=0, num_comments=0)
    second = add_lead(
        session, "t3_b", "Which CRM should I use?", body=body, score=0, num_comments=0
    )

    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    rows = {r.lead_id: r for r in session.query(Prescore).filter(Prescore.run_id == run.id).all()}
    assert len(rows) == 2, "N members still get N rows — that half always holds"
    assert rows[first.id].total == rows[second.id].total

    # And selection stays deterministic on the tie, via P10's trailing row-id
    # tie-break — otherwise two identical runs would enrich different members.
    group = session.query(DedupGroup).filter(DedupGroup.run_id == run.id).one()
    assert group.representative_lead_id == max(first.id, second.id)


def test_the_group_representative_is_chosen_by_pre_score_not_by_upvotes(session, run):
    """docs/06c §4.3's ordering, restored. P10 shipped `DedupItem.rank` defaulting
    to None with a `(score, created_utc, row_id)` fallback precisely so P11 could
    fill it in **without a signature change** — this is that fill.

    ⚠ **The two orderings are made to DISAGREE here, deliberately.** If the
    highest-upvoted member is also the highest pre-scored one, P10's fallback
    picks the same representative and the test passes without `rank` being
    supplied at all — which is exactly what mutation M29 exploited. So the member
    with far more upvotes is given a stale timestamp, making `recency` (the
    heaviest component at 0.25) outweigh `engagement`: the pre-score prefers the
    fresh one, raw upvotes prefer the stale one, and only one answer can be
    right.
    """
    body = STRONG_BODY * 2
    fresh = add_lead(
        session,
        "t3_a",
        "Which CRM should I use?",
        body=body,
        score=1,
        num_comments=1,
        created_utc=NOW - datetime.timedelta(hours=1),
    )
    upvoted_but_stale = add_lead(
        session,
        "t3_b",
        "**Which CRM should I use?**",
        body=body,
        score=5_000,
        num_comments=400,
        created_utc=NOW - datetime.timedelta(days=28),
    )

    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    scores = {
        r.lead_id: r.total for r in session.query(Prescore).filter(Prescore.run_id == run.id).all()
    }
    assert scores[fresh.id] > scores[upvoted_but_stale.id], (
        "the fixture must make pre-score and upvotes disagree, or it proves nothing"
    )

    group = session.query(DedupGroup).filter(DedupGroup.run_id == run.id).one()
    assert group.representative_lead_id == fresh.id


def test_a_grouped_member_is_recorded_as_grouped_and_keeps_its_own_score(session, run):
    """`prescores.gate_decision` has four values and `grouped` is one of them.

    The member passed the gate; it is resolved by reusing the representative's
    analysis rather than being discarded, which is what docs/06c §8's worked
    example counts. Its `total` is untouched — P10's G6, upheld across the
    boundary.
    """
    body = STRONG_BODY * 2
    add_lead(session, "t3_a", "Which CRM should I use?", body=body, score=90, num_comments=40)
    add_lead(session, "t3_b", "**Which CRM should I use?**", body=body, score=88, num_comments=39)

    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    decisions = [r.gate_decision for r in session.query(Prescore).filter(Prescore.run_id == run.id)]
    assert sorted(decisions) == [DECISION_ADMIT, DECISION_GROUPED]
    assert all(r.total > 0 for r in session.query(Prescore).filter(Prescore.run_id == run.id))


# ------------------------------------------------------- AC2 and the funnel


def test_the_funnel_sums_and_measures_the_hard_filter_rate(session, run):
    """**A2 measured** — docs/34 §P11's bold criterion, against the assumed 73%."""
    add_lead(session, "t3_a", "Looking for a CRM - any recommendations?")
    add_lead(session, "t3_b", "[HIRING] Senior backend engineer")
    add_lead(session, "t3_c", "Now hiring a designer")
    add_lead(session, "t3_d", "Weekly megathread")

    payload = run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    full = payload["full"]
    assert full["collected"] == 4
    assert full["admitted"] + full["rejected"] == full["collected"]
    assert full["sums"] is True
    assert payload["hard_filter_rate"] == pytest.approx(0.75)
    assert payload["hard_filter_rate_assumed"] == 0.73


def test_the_funnel_lands_on_the_run_timeline_and_the_progress_payload(session, run):
    """Task 2: "funnel counts to `run_events` AND the progress page"."""
    from src.orchestration.run_service import RunService

    add_lead(session, "t3_a", "Looking for a CRM - any recommendations?")
    run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    events = session.query(RunEvent).filter(RunEvent.event == "pipeline.funnel").all()
    assert len(events) == 1

    progress = RunService(session).progress(run.id).to_dict()
    assert progress["funnel"]["full"]["collected"] == 1


def test_the_whole_nested_payload_survives_the_round_trip(session, run):
    """`emit_event` stores `redact(json.dumps(data, default=str))` and
    `RunService.funnel` reads it back. A nested dict that came back flattened,
    stringified or redacted into nonsense would leave the run page rendering
    blanks while the stage reported success — so a nested field is read, not just
    a top-level one.
    """
    from src.orchestration.run_service import RunService

    add_lead(session, "t3_a", "Looking for a CRM - any recommendations?")
    add_lead(session, "t3_b", "[HIRING] Senior backend engineer")
    written = run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    read_back = RunService(session).progress(run.id).to_dict()["funnel"]
    assert read_back["full"]["rejected_by_reason"] == written["full"]["rejected_by_reason"]
    assert read_back["full"]["detail_by_reason"]["structural_noise"] == {"hiring": 1}
    assert read_back["comments"]["eligible"] == written["comments"]["eligible"]
    assert read_back["hard_filter_rate"] == written["hard_filter_rate"]


def test_a_holdout_audited_lead_is_not_rescored_into_the_a2_denominator(session, run):
    """A2 correctness.

    The holdout stores its 2% sample as real leads inside this run's window, so
    they would otherwise be picked up here — items stage 3 **already rejected**,
    stored *because* they were rejected. Counting them would put a population
    selected for being rejected into the hard-filter denominator, biasing A2
    upwards by an amount that grows with the holdout rate.
    """
    from src.scoring import SOURCE_HOLDOUT_AUDIT

    add_lead(session, "t3_real", "Looking for a CRM - any recommendations?")
    add_lead(
        session,
        "t3_audit",
        "Weekly megathread for questions",
        source=SOURCE_HOLDOUT_AUDIT,
    )

    payload = run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    assert payload["full"]["collected"] == 1
    assert session.query(Prescore).filter(Prescore.run_id == run.id).count() == 1
    # The audited lead is still a real, labellable lead (06c §6.1).
    assert session.query(Lead).filter(Lead.source == SOURCE_HOLDOUT_AUDIT).count() == 1


def test_a_run_with_no_funnel_yet_reports_none_rather_than_zeroes(session, run):
    """`run_progress.html`'s rule since P3: "a zero is a measurement; a blank is
    an honest 'not yet'". Zeroes would read as "nothing was collected and
    nothing was filtered", which is a different and wrong statement."""
    from src.orchestration.run_service import RunService

    assert RunService(session).progress(run.id).to_dict()["funnel"] is None


def test_the_collapse_rate_is_measured_for_this_run(session, run):
    """P10's transferred metric. P10 measured 5.74% on a cross-run ARCHIVE and
    recorded that it is flat down to a 0.60 threshold, so the shortfall is not
    under-detection. P11 has the first live call site and measures within a run.

    **The threshold is not tuned here** — CONFIG carries no `jaccard_threshold`,
    so the shipped 0.85 applies.

    ⚠ **One group of THREE, so `grouped` (2) and `groups` (1) differ.** With a
    group of two they are both 1 and a rate computed from the wrong one is
    indistinguishable — the fixture would pass while measuring clusters formed
    instead of members resolved. docs/06c §8 is explicit that grouping *"does not
    discard 142 items — it discards 95 and keeps 47 representatives"*.
    """
    body = STRONG_BODY * 2
    add_lead(session, "t3_a", "Which CRM should I use?", body=body)
    add_lead(session, "t3_b", "**Which CRM should I use?**", body=body)
    add_lead(session, "t3_c", "which crm should i use", body=body)
    add_lead(session, "t3_d", "Looking for a project tracker - any recommendations?")

    payload = run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    assert payload["groups"] == 1
    assert payload["grouped"] == 2, "two members resolved, one representative kept"
    assert payload["collapse_rate"] == pytest.approx(0.5)


# ------------------------------------------------------------- the rollback


def test_the_rollback_writes_nothing_and_leaves_intent_score_alone(session, run):
    """docs/34 §P11's Rollback row, executed rather than documented."""
    lead = add_lead(session, "t3_a", "Looking for a CRM - any recommendations?")
    before = lead.intent_score

    payload = run_prescore_stage(
        session, run.id, {**CONFIG, "pipeline": {"prescore_enabled": False}}
    )
    session.commit()

    assert payload == {"skipped": "disabled"}
    assert session.query(Prescore).count() == 0
    assert session.query(DedupGroup).count() == 0
    assert session.query(RunEvent).filter(RunEvent.event == "pipeline.funnel").count() == 0
    assert session.get(Lead, lead.id).intent_score == before


def test_a_run_that_collected_nothing_is_a_clean_no_op(session, run):
    assert run_prescore_stage(session, run.id, CONFIG) == {"skipped": "no_leads"}


def test_leads_from_before_the_run_started_are_not_rescored(session, run):
    """`leads` has no `run_id`, so the stage is bounded by `scraped_at >=
    run.started_at`. Exact under the one-active-run-at-a-time constraint
    `RunService.active_for_project` already enforces."""
    add_lead(
        session,
        "t3_old",
        "Looking for a CRM - any recommendations?",
        scraped_at=NOW - datetime.timedelta(days=30),
    )
    add_lead(session, "t3_new", "Looking for a CRM - any recommendations?")

    payload = run_prescore_stage(session, run.id, CONFIG)
    session.commit()

    assert payload["full"]["collected"] == 1
    assert session.query(Prescore).count() == 1


# ---------------------------------------------------------- fail soft, AD-9


def test_a_failing_stage_does_not_fail_a_run_that_collected_leads(session, run, monkeypatch):
    """AD-9. The pre-score is enrichment on leads that are already durable."""
    from src.orchestration.handlers import finalize

    def boom(*args, **kwargs):
        raise RuntimeError("scoring exploded")

    monkeypatch.setattr(
        "src.orchestration.handlers.prescore.run_prescore_stage", boom, raising=True
    )
    add_lead(session, "t3_a", "Looking for a CRM - any recommendations?")

    result = finalize._prescore(session, run.id)
    session.commit()

    assert "error" in result
    assert session.query(Lead).count() == 1
    warnings = session.query(RunEvent).filter(RunEvent.event == "pipeline.funnel.failed").all()
    assert len(warnings) == 1
    assert warnings[0].level == "warning"
