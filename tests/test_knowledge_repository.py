"""BKB persistence — supersede, upsert, the soft delete, and the origin guard.

[34 §P14](../docs/34-implementation-plan.md) task 4: *"Section supersede; typed
tables upserted on ``(bkb_id, slug)``; vanished slugs soft-deleted"*.
"""

from __future__ import annotations

import json

import pytest

from src.db.models import (
    BKB,
    BKB_SECTION_KEYS,
    BKB_STALENESS_DAYS,
    IntentSignal,
    PainPoint,
    Persona,
)
from src.db.repositories.knowledge import (
    BKB_COMPLETE,
    ORIGIN_WEBSITE,
    TIER_WEIGHTS,
    KnowledgeRepository,
)
from src.knowledge.sections import validate_sections
from tests.conftest import ensure_project


@pytest.fixture
def session(temp_db):
    from src.db.database import get_session

    s = get_session()
    ensure_project(s, 1)
    s.commit()
    yield s
    s.close()


@pytest.fixture
def repo(session):
    return KnowledgeRepository(session)


def _persist(repo, session, payload, project_id=1):
    """One whole analysis, as :func:`src.knowledge.bkb.analyze` performs it."""
    sections = validate_sections(payload)
    bkb = repo.create_bkb(project_id, model="fake-model-v1", prompt_version=1)
    for section in sections:
        repo.upsert_section(bkb.id, section)
    by_key = {s.key: s for s in sections}
    repo.upsert_personas(project_id, bkb.id, by_key["buyer_personas"].items)
    repo.upsert_pain_points(project_id, bkb.id, by_key["pain_points"].items)
    repo.upsert_intent_signals(project_id, bkb.id, by_key["buying_signals"].items)
    session.commit()
    return bkb


# ------------------------------------------------------------------ supersede


def test_the_first_analysis_creates_version_one(repo, session, bkb_payload):
    bkb = _persist(repo, session, bkb_payload)
    assert bkb.version == 1
    assert bkb.superseded_at is None
    assert repo.current(1).id == bkb.id


def test_a_re_analysis_supersedes_rather_than_overwrites(repo, session, bkb_payload):
    """Supersede, never overwrite — the property ``ix_bkb_current`` is built for.

    Keeping the old version is what makes *"what did we think last month, and on
    what evidence?"* answerable, and it is what ``bkb_evidence``'s CASCADE hangs
    off in P15.
    """
    first = _persist(repo, session, bkb_payload)
    second = _persist(repo, session, bkb_payload)

    session.refresh(first)
    assert second.version == 2
    assert first.superseded_at is not None, "the old version must be stamped, not deleted"
    assert session.query(BKB).count() == 2
    assert repo.current(1).id == second.id


def test_exactly_one_bkb_is_ever_live(repo, session, bkb_payload):
    for _ in range(4):
        _persist(repo, session, bkb_payload)
    live = session.query(BKB).filter(BKB.superseded_at.is_(None)).all()
    assert len(live) == 1
    assert live[0].version == 4


def test_supersede_closes_every_live_row_not_merely_the_newest(repo, session, bkb_payload):
    """The invariant is enforced, not assumed.

    A writer that assumes an invariant it does not enforce is how the invariant
    stops being true: if a crash ever left two live rows, superseding only *the*
    current one would leave one live behind the new one — and ``current()``
    would then return a BKB that is two generations old.
    """
    _persist(repo, session, bkb_payload)
    stray = BKB(project_id=1, version=99, model="m", prompt_version=1)
    session.add(stray)
    session.flush()

    assert repo.supersede_current(1) == 2
    session.commit()
    assert session.query(BKB).filter(BKB.superseded_at.is_(None)).count() == 0


def test_the_version_counts_from_the_highest_that_ever_existed(repo, session, bkb_payload):
    """Not from the live one — otherwise "BKB v3" could name two things."""
    _persist(repo, session, bkb_payload)
    _persist(repo, session, bkb_payload)
    repo.supersede_current(1)
    session.commit()

    third = _persist(repo, session, bkb_payload)
    assert third.version == 3


# ------------------------------------------------------------------- sections


def test_all_twenty_three_section_rows_are_written(repo, session, bkb_payload):
    bkb = _persist(repo, session, bkb_payload)
    rows = repo.sections_for(bkb.id)

    assert len(rows) == 23
    assert {r.section_key for r in rows} == set(BKB_SECTION_KEYS)
    assert all(r.status == "ok" for r in rows)


def test_the_payload_null_rule_is_satisfied_by_the_database_not_just_by_us(
    repo, session, bkb_payload
):
    """``ck_bkb_sections_payload_null_rule`` is a CHECK, and it is enforced.

    A rule enforced only by a test is one the next writer can break inside a
    transaction no test observes — 05 §5.1b's whole argument for making it a
    constraint. This asserts the constraint is real by asserting the rows it let
    through.
    """
    bkb = _persist(repo, session, bkb_payload)
    for row in repo.sections_for(bkb.id):
        typed = row.section_key in ("buyer_personas", "pain_points", "buying_signals")
        assert (row.payload_json is None) is typed, row.section_key


def test_staleness_is_seeded_from_p12s_policy_and_group_c_never_stales(repo, session, bkb_payload):
    """P12 shipped ``BKB_STALENESS_DAYS`` as data **so that P14 would seed it**.

    Group C is ``NULL``: those seven accrete continuously from Reddit and are
    getting *fresher*, not older, so an age badge would invite exactly the
    regeneration R12's origin guard exists to prevent.
    """
    bkb = _persist(repo, session, bkb_payload)
    for row in repo.sections_for(bkb.id):
        assert row.staleness_days == BKB_STALENESS_DAYS[row.section_key], row.section_key

    assert repo.sections_for(bkb.id)
    group_c = [r for r in repo.sections_for(bkb.id) if r.section_key == "customer_language"]
    assert group_c[0].staleness_days is None


def test_an_incomplete_section_persists_alongside_the_other_twenty_two(repo, session, bkb_payload):
    """**The acceptance criterion, at the storage layer.**"""
    bkb_payload["buyer_personas"][0]["slug"] = "Not A Slug"
    bkb = _persist(repo, session, bkb_payload)

    rows = {r.section_key: r for r in repo.sections_for(bkb.id)}
    assert len(rows) == 23
    assert rows["buyer_personas"].status == "incomplete"
    assert sum(1 for r in rows.values() if r.status == "ok") == 22


def test_re_persisting_the_same_bkb_id_upserts_rather_than_duplicating(repo, session, bkb_payload):
    """R9: a re-claimed lease must not double every row."""
    bkb = _persist(repo, session, bkb_payload)
    sections = validate_sections(bkb_payload)
    for section in sections:
        repo.upsert_section(bkb.id, section)
    session.commit()

    assert len(repo.sections_for(bkb.id)) == 23


# -------------------------------------------------------------- typed tables


def test_the_three_typed_tables_are_written(repo, session, bkb_payload):
    bkb = _persist(repo, session, bkb_payload)

    assert [p.slug for p in repo.personas_for(bkb.id)] == ["growth-lead"]
    assert len(repo.pain_points_for(bkb.id)) == 3
    assert len(repo.intent_signals_for(bkb.id)) == 3


def test_phrases_json_is_written_because_the_pre_score_will_read_it(repo, session, bkb_payload):
    """P14's obligation to ``src.scoring.ABSENT_COMPONENTS``.

    ⚠ The **component** is deliberately not wired — operator decision D2. This
    test asserts the *data* exists, which is the half P14 owns.
    """
    bkb = _persist(repo, session, bkb_payload)
    pain = next(p for p in repo.pain_points_for(bkb.id) if p.slug == "attribution-gap")

    assert json.loads(pain.phrases_json) == ["no idea which channel actually works"]


def test_the_signal_weight_is_arithmetic_over_the_tier_not_a_number_from_the_model(
    repo, session, bkb_payload
):
    """R6 — *categoricals in, arithmetic out* — at the point it first applies.

    The model emits ``high``/``medium``/``low``. It is never asked for 0.5, and
    ``BuyingSignalOut`` has no weight field to put one in.
    """
    bkb = _persist(repo, session, bkb_payload)
    weights = {s.slug: s.weight for s in repo.intent_signals_for(bkb.id)}

    assert weights["evaluating-alternatives"] == TIER_WEIGHTS["high"]
    assert weights["new-hire"] == TIER_WEIGHTS["low"]


def test_a_second_analysis_updates_the_row_in_place_and_re_points_it(repo, session, bkb_payload):
    """Upsert on ``(project_id, slug)`` — the unique index, honoured.

    The persona keeps its identity across versions, which is what makes a slug a
    stable join key rather than a per-run label.
    """
    first = _persist(repo, session, bkb_payload)
    persona_id = repo.personas_for(first.id)[0].id

    bkb_payload["buyer_personas"][0]["name"] = "Head of Growth"
    second = _persist(repo, session, bkb_payload)

    assert session.query(Persona).count() == 1, "the slug is the identity; no second row"
    persona = repo.personas_for(second.id)[0]
    assert persona.id == persona_id
    assert persona.name == "Head of Growth"


# ------------------------------------------------------------- the soft delete


def test_a_vanished_slug_is_not_deleted_and_is_no_longer_current(repo, session, bkb_payload):
    """**Task 4's "vanished slugs soft-deleted", with no schema change.**

    ``pain_points`` has no ``status`` and no ``deleted_at`` column, and `0007` is
    shipped — so the soft delete is expressed in the columns that exist: a row is
    *current* iff its ``bkb_id`` is the current BKB's. A slug that vanishes is
    simply not re-pointed.
    """
    first = _persist(repo, session, bkb_payload)
    assert len(repo.pain_points_for(first.id)) == 3

    bkb_payload["pain_points"] = bkb_payload["pain_points"][:3]
    del bkb_payload["pain_points"][2]  # "tool-sprawl" vanishes
    bkb_payload["pain_points"].append(
        {"slug": "new-pain", "title": "A newly stated problem", "how_people_phrase_it": ["ugh"]}
    )
    second = _persist(repo, session, bkb_payload)

    current = {p.slug for p in repo.pain_points_for(second.id)}
    assert current == {"attribution-gap", "manual-reporting", "new-pain"}

    vanished = session.query(PainPoint).filter(PainPoint.slug == "tool-sprawl").one()
    assert vanished.bkb_id == first.id, "still attached to the BKB that last claimed it"
    assert session.query(PainPoint).count() == 4, "nothing was deleted"


def test_the_orphaned_slugs_query_names_what_fell_out(repo, session, bkb_payload):
    """The soft delete, made observable.

    Without a query that names them, *"the vanished slug is still there but is
    no longer current"* is a claim about a row rather than something an operator
    or a test can see.
    """
    _persist(repo, session, bkb_payload)
    del bkb_payload["pain_points"][2]
    bkb_payload["pain_points"].append(
        {"slug": "new-pain", "title": "t", "how_people_phrase_it": []}
    )
    second = _persist(repo, session, bkb_payload)

    assert repo.orphaned_slugs(PainPoint, 1, second.id) == ["tool-sprawl"]


# ------------------------------------------------------------- the origin guard


def test_an_operator_edited_row_survives_a_re_analysis_unchanged(repo, session, bkb_payload):
    """R12's near half, and the one P14 cannot avoid taking.

    ``lifecycle.regenerate_section`` and the full origin guard are **P15's**
    ([34 §P15](../docs/34-implementation-plan.md) task 4). P14 must not pre-empt
    it — and must not *break* it either. An operator's edit that a re-analysis
    silently overwrote would make P15's guarantee unreachable, because the row it
    is meant to protect would already be gone.
    """
    first = _persist(repo, session, bkb_payload)
    persona = repo.personas_for(first.id)[0]
    persona.name = "The operator's own wording"
    persona.origin = "operator"
    session.commit()

    bkb_payload["buyer_personas"][0]["name"] = "What the model said this time"
    second = _persist(repo, session, bkb_payload)

    kept = repo.personas_for(second.id)[0]
    assert kept.name == "The operator's own wording", "an operator edit is not overwritten"
    assert kept.origin == "operator"
    assert kept.bkb_id == second.id, "but it IS re-pointed, so it stays current"


def test_a_website_origin_row_is_refreshed_from_the_site(repo, session, bkb_payload):
    """The other side of the guard: the default path still updates.

    A guard that protected everything would freeze the knowledge base after its
    first build.
    """
    _persist(repo, session, bkb_payload)
    bkb_payload["buyer_personas"][0]["name"] = "Refreshed"
    second = _persist(repo, session, bkb_payload)

    persona = repo.personas_for(second.id)[0]
    assert persona.origin == ORIGIN_WEBSITE
    assert persona.name == "Refreshed"


def test_nothing_is_ever_deleted_by_any_path_in_this_repository(repo, session, bkb_payload):
    """R12 is *knowledge accretes*. Row counts may rise; they never fall."""
    _persist(repo, session, bkb_payload)
    before = (
        session.query(Persona).count(),
        session.query(PainPoint).count(),
        session.query(IntentSignal).count(),
    )

    bkb_payload["buyer_personas"] = []
    bkb_payload["pain_points"] = []
    bkb_payload["buying_signals"] = []
    _persist(repo, session, bkb_payload)

    after = (
        session.query(Persona).count(),
        session.query(PainPoint).count(),
        session.query(IntentSignal).count(),
    )
    assert after == before


def test_a_bkb_row_records_the_model_and_prompt_version_that_built_it(repo, session, bkb_payload):
    """AD-8: a prompt change is a behaviour change, so it is pinned on the row."""
    bkb = _persist(repo, session, bkb_payload)
    assert bkb.model == "fake-model-v1"
    assert bkb.prompt_version == 1
    assert bkb.status == BKB_COMPLETE
