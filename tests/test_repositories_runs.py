"""``RunRepository`` and ``JobRepository`` — the read side of orchestration.

P3 builds ``/runs`` and ``/api/runs/<id>/progress`` on these, so the shapes are
fixed here and asserted here rather than discovered there.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from src.db.models import Run
from src.db.repositories.runs import JobRepository, RunRepository
from src.obs.events import emit_event
from src.orchestration.job_queue import JobQueue, utcnow


@pytest.fixture
def engine(temp_db):
    from src.db import database

    return database.ENGINE


@pytest.fixture
def session(engine):
    with Session(bind=engine, expire_on_commit=False) as session:
        yield session


def _run(session, state="scraping", project_id=None) -> Run:
    run = Run(state=state, project_id=project_id)
    session.add(run)
    session.commit()
    return run


# -- RunRepository ---------------------------------------------------------


def test_get_returns_the_run(session):
    run = _run(session)
    assert RunRepository(session).get(run.id).id == run.id


def test_recent_is_newest_first(session):
    first = _run(session)
    second = _run(session)

    assert [r.id for r in RunRepository(session).recent()] == [second.id, first.id]


def test_active_for_project_finds_a_run_in_flight(session):
    run = _run(session, state="awaiting_subreddit_review", project_id=4)

    assert RunRepository(session).active_for_project(4).id == run.id


@pytest.mark.parametrize("state", ["complete", "failed", "cancelled"])
def test_a_terminal_run_is_not_active(session, state):
    """P3's duplicate-run guard hangs off this; a wrong answer here blocks work."""
    _run(session, state=state, project_id=4)

    assert RunRepository(session).active_for_project(4) is None


def test_events_are_returned_in_order_from_a_watermark(session):
    run = _run(session)
    for name in ("a", "b", "c"):
        emit_event(session, run.id, name)
    session.commit()

    first = RunRepository(session).events(run.id)
    after = RunRepository(session).events(run.id, after_id=first[0].id)

    assert [e.event for e in first] == ["a", "b", "c"]
    assert [e.event for e in after] == ["b", "c"]


def test_events_of_another_run_are_not_returned(session):
    mine, theirs = _run(session), _run(session)
    emit_event(session, theirs.id, "not mine")
    session.commit()

    assert RunRepository(session).events(mine.id) == []


# -- JobRepository ---------------------------------------------------------


def test_counts_by_state_groups_a_runs_jobs(session, engine):
    run = _run(session)
    queue = JobQueue(engine=engine)
    for _ in range(3):
        queue.enqueue("maintenance", run_id=run.id)
    queue.claim("w1")

    counts = JobRepository(session).counts_by_state(run.id)

    assert counts == {"queued": 2, "running": 1}


def test_counts_by_state_omits_states_with_no_jobs(session, engine):
    """Absent, not zero — the caller decides what 'no such job' means."""
    run = _run(session)
    JobQueue(engine=engine).enqueue("maintenance", run_id=run.id)

    assert JobRepository(session).counts_by_state(run.id) == {"queued": 1}


def test_for_run_returns_only_that_runs_jobs(session, engine):
    mine, theirs = _run(session), _run(session)
    queue = JobQueue(engine=engine)
    queue.enqueue("maintenance", run_id=mine.id)
    queue.enqueue("maintenance", run_id=theirs.id)

    assert [j.run_id for j in JobRepository(session).for_run(mine.id)] == [mine.id]


def test_queue_depth_reports_the_oldest_queued_job(session, engine):
    queue = JobQueue(engine=engine)
    old = utcnow() - timedelta(hours=2)
    queue.enqueue("maintenance", available_at=old)
    queue.enqueue("maintenance")

    depth = JobRepository(session).queue_depth()

    assert depth["queued"] == 2
    assert depth["running"] == 0
    assert depth["oldest_queued_at"] == old.replace(microsecond=old.microsecond)


def test_queue_depth_on_an_empty_queue_is_all_zeroes(session):
    assert JobRepository(session).queue_depth() == {
        "queued": 0,
        "running": 0,
        "failed": 0,
        "oldest_queued_at": None,
    }
