"""``RunService`` — creation, the forced walk, cancellation, retry, progress.

The walk is tested against an **independently derived** path rather than against
``SCRAPE_WALK`` itself: a test that reads the same constant the code reads would
pass for any path at all, including an illegal one. Here the expected sequence is
recomputed from ``TRANSITIONS`` by breadth-first search, so the assertion is
"this is the only legal route", not "this is what the module happens to say".
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import Job, Run, RunEvent
from src.orchestration.job_queue import JobQueue
from src.orchestration.run_service import (
    FINALIZE_JOB,
    SCRAPE_WALK,
    RunAlreadyActive,
    RunNotFound,
    RunOptions,
    RunService,
)
from src.orchestration.states import TRANSITIONS, IllegalTransition, JobState, RunState


@pytest.fixture
def session(temp_db):
    with Session(bind=database.ENGINE, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def service(session):
    return RunService(session)


def _create(service, session, subreddits=("saas", "startups"), project_id=None):
    run = service.create(project_id, RunOptions(subreddits=tuple(subreddits)))
    session.commit()
    return run


def _shortest_legal_path(start: RunState, goal: RunState) -> list[RunState]:
    """The shortest legal route between two states, derived from ``TRANSITIONS``.

    Independent of anything in ``run_service``. If someone adds a shortcut edge
    to the transition table, this returns the shortcut and the walk test fails —
    which is the correct outcome, because the walk would then be taking a longer
    route than the machine allows.
    """
    queue: list[list[RunState]] = [[start]]
    seen = {start}
    while queue:
        path = queue.pop(0)
        if path[-1] is goal:
            return path[1:]
        for nxt in sorted(TRANSITIONS[path[-1]], key=lambda s: s.value):
            if nxt not in seen:
                seen.add(nxt)
                queue.append([*path, nxt])
    raise AssertionError(f"no legal path {start} -> {goal}")


# ------------------------------------------------------------------ creation


def test_create_walks_the_only_legal_path_to_scraping(service, session):
    """AC1 support. The route is forced by the table, not chosen by this module."""
    expected = _shortest_legal_path(RunState.PENDING, RunState.SCRAPING)

    run = _create(service, session)

    assert run.state == RunState.SCRAPING.value
    assert [state for state, _reason in SCRAPE_WALK] == expected

    hops = [
        json.loads(e.data_json)["to_state"]
        for e in session.query(RunEvent)
        .filter(RunEvent.run_id == run.id, RunEvent.event == "run.transition")
        .order_by(RunEvent.id)
    ]
    assert hops == [s.value for s in expected]


def test_the_walk_passes_through_both_review_gates(service, session):
    """Made explicit because it contradicts docs/13 §2.2 and must stay visible.

    If a future change makes the gates avoidable, this test should be *deleted
    deliberately*, not discovered to be failing.
    """
    from src.orchestration.states import GATE_STATES

    walked = {state for state, _ in SCRAPE_WALK}
    assert walked >= GATE_STATES


def test_every_walk_hop_explains_itself_to_the_operator(service, session):
    """AC10: these events render live. A bare state name is not an explanation."""
    run = _create(service, session)
    messages = [
        e.message
        for e in session.query(RunEvent)
        .filter(RunEvent.run_id == run.id, RunEvent.event == "run.transition")
        .order_by(RunEvent.id)
    ]
    assert len(messages) == len(SCRAPE_WALK)
    for message in messages:
        assert message and len(message) > 20, f"unhelpful walk message: {message!r}"
        assert "->" not in message and "→" not in message


def test_create_enqueues_one_job_per_subreddit(service, session):
    """AC2/AC6 both need per-subreddit granularity."""
    run = _create(service, session, subreddits=("saas", "startups", "entrepreneur"))

    jobs = session.query(Job).filter(Job.run_id == run.id).all()
    assert len(jobs) == 3
    assert {json.loads(j.payload_json)["subreddit"] for j in jobs} == {
        "saas",
        "startups",
        "entrepreneur",
    }
    assert {j.job_type for j in jobs} == {"scrape_subreddit"}
    assert {j.state for j in jobs} == {JobState.QUEUED.value}


def test_run_and_jobs_commit_together_or_not_at_all(session, temp_db):
    """G1. A run whose jobs were lost to a rollback is worse than no run."""
    service = RunService(session)
    service.create(None, RunOptions(subreddits=("saas",)))
    session.rollback()

    with Session(bind=database.ENGINE) as fresh:
        assert fresh.query(Run).count() == 0
        assert fresh.query(Job).count() == 0


def test_no_subreddits_still_finalises(service, session):
    """The empty list would otherwise wedge every future run.

    With no scrape jobs, no scrape handler ever enqueues the finaliser, so the
    run sits in SCRAPING forever — and because the duplicate-run guard treats a
    non-terminal run as active, every later scrape returns 409.
    """
    run = _create(service, session, subreddits=())

    jobs = session.query(Job).filter(Job.run_id == run.id).all()
    assert [j.job_type for j in jobs] == ["finalize_run"]

    warnings = (
        session.query(RunEvent).filter(RunEvent.run_id == run.id, RunEvent.level == "warning").all()
    )
    assert any("nothing to scrape" in (w.message or "") for w in warnings)


# ------------------------------------------------------- duplicate-run guard


def test_second_run_for_the_same_project_is_refused_with_the_existing_id(service, session):
    """AC7 — docs/13 §9.4, the double-click problem."""
    first = _create(service, session)

    with pytest.raises(RunAlreadyActive) as excinfo:
        service.create(None, RunOptions(subreddits=("saas",)))

    assert excinfo.value.run_id == first.id


def test_the_guard_releases_once_the_run_is_terminal(service, session):
    """Otherwise the first scrape would be the last one this install ever ran."""
    first = _create(service, session)
    service.cancel(first.id)
    session.commit()

    second = _create(service, session)
    assert second.id != first.id


@pytest.mark.parametrize("terminal", [RunState.COMPLETE, RunState.FAILED, RunState.CANCELLED])
def test_every_terminal_state_releases_the_guard(session, temp_db, terminal):
    """Excluding terminal states must mean *all three*, not the two we thought of."""
    service = RunService(session)
    run = service.create(None, RunOptions(subreddits=("saas",)))
    run.state = terminal.value
    session.commit()

    assert service.runs.active_for_project(None) is None


def test_a_run_for_another_project_does_not_block_this_one(session, temp_db):
    service = RunService(session)
    service.create(1, RunOptions(subreddits=("saas",)))
    session.commit()

    other = service.create(2, RunOptions(subreddits=("saas",)))
    assert other.project_id == 2


# ---------------------------------------------------------------- transition


def test_illegal_transition_raises_and_names_both_states(service, session):
    """AC12. "illegal transition" without the states is unactionable at 3am."""
    run = _create(service, session)

    with pytest.raises(IllegalTransition) as excinfo:
        service.transition(run.id, RunState.PROFILING)

    message = str(excinfo.value)
    assert "scraping" in message and "profiling" in message


def test_illegal_transition_is_a_valueerror_subclass():
    """The API catches it by name; this records why that is safe to rely on."""
    assert issubclass(IllegalTransition, ValueError)


def test_unknown_run_id_raises_run_not_found(service):
    with pytest.raises(RunNotFound):
        service.transition(999, RunState.CANCELLED)


def test_terminal_transition_stamps_finished_at(service, session):
    run = _create(service, session)
    assert run.finished_at is None

    service.cancel(run.id)
    session.commit()
    assert run.finished_at is not None


def test_fail_records_the_reason_on_the_run_row(service, session):
    run = _create(service, session)
    service.fail(run.id, "the scraper could not reach reddit")
    session.commit()

    assert run.state == RunState.FAILED.value
    assert "could not reach reddit" in run.error


# -------------------------------------------------------------- cancellation


def test_cancel_marks_queued_jobs_cancelled_and_stops_the_run(service, session):
    """AC6."""
    run = _create(service, session, subreddits=("saas", "startups"))

    service.cancel(run.id)
    session.commit()

    assert run.state == RunState.CANCELLED.value
    states = {j.state for j in session.query(Job).filter(Job.run_id == run.id)}
    assert states == {JobState.CANCELLED.value}


def test_cancel_leaves_the_job_in_flight_alone(service, session):
    """T4. A running handler is stopped by the flag, not by killing its thread."""
    run = _create(service, session, subreddits=("saas", "startups"))
    running = session.query(Job).filter(Job.run_id == run.id).first()
    running.state = JobState.RUNNING.value
    session.commit()

    service.cancel(run.id)
    session.commit()

    session.refresh(running)
    assert running.state == JobState.RUNNING.value
    assert service.cancel_requested(run.id) is True


def test_cancel_flag_lives_in_stats_json_not_a_new_column(service, session):
    """P3 owns no migration; a column here would break the frozen chain."""
    run = _create(service, session)
    service.cancel(run.id)
    session.commit()

    assert json.loads(run.stats_json)["cancel_requested"] is True
    assert not hasattr(Run, "cancel_requested")


def test_cancelling_a_cancelled_run_is_refused(service, session):
    """CANCELLED is final -- 'cancel' must not quietly mean 'pause'."""
    run = _create(service, session)
    service.cancel(run.id)
    session.commit()

    with pytest.raises(IllegalTransition):
        service.cancel(run.id)


# --------------------------------------------------------------------- retry


def test_retry_from_failed_re_walks_and_re_queues(service, session):
    """The retry path must make the identical journey, not a shortcut."""
    run = _create(service, session, subreddits=("saas", "startups"))
    service.fail(run.id, "boom")
    session.commit()

    service.retry(run.id)
    session.commit()

    assert run.state == RunState.SCRAPING.value
    assert run.error is None
    assert run.finished_at is None

    queued = session.query(Job).filter(Job.run_id == run.id, Job.state == JobState.QUEUED.value)
    assert queued.count() == 2


def test_retry_abandons_work_left_queued_by_the_failed_attempt(service, session):
    """Found by the first run of this file: retry was doubling the work.

    A run can fail with jobs still queued -- one subreddit's job fails for good
    while three are waiting. Those three stay claimable, so enqueueing a fresh
    set beside them meant every subreddit was scraped twice on retry.

    **The count changed from 6 to 7 in P7**, and it is a contract change rather
    than a loosened number: ``fail()`` now enqueues a ``finalize_run`` job so a
    failed run gets its notification (D7). That job must be **cancelled** by a
    retry, and the assertion below is the load-bearing half of this test now --
    if it were left queued, the worker would claim it against a run that is
    already back in ``SCRAPING`` and **finalise the retried attempt
    prematurely**, which is a far worse defect than the notification this trades
    away. The trade is recorded in ``docs/P7-STAGE5-FLOW.md``: an operator who
    presses retry has already seen the failure on the run page.
    """
    run = _create(service, session, subreddits=("a", "b", "c"))
    service.fail(run.id, "boom")
    session.commit()

    service.retry(run.id)
    session.commit()

    jobs = session.query(Job).filter(Job.run_id == run.id).all()
    assert len(jobs) == 7, "the old jobs should still exist as evidence"
    assert sum(j.state == JobState.QUEUED.value for j in jobs) == 3
    assert sum(j.state == JobState.CANCELLED.value for j in jobs) == 4

    finalisers = [j for j in jobs if j.job_type == FINALIZE_JOB]
    assert len(finalisers) == 1, "fail() enqueues exactly one finaliser"
    assert finalisers[0].state == JobState.CANCELLED.value, (
        "a finaliser left queued across a retry would finalise the NEW attempt"
    )
    assert not [j for j in jobs if j.job_type == FINALIZE_JOB and j.state == JobState.QUEUED.value]


def test_retry_walks_the_same_path_as_create(service, session):
    """One helper, not two copies -- the drift this prevents is invisible."""
    run = _create(service, session)
    service.fail(run.id, "boom")
    session.commit()

    before = session.query(RunEvent).filter(RunEvent.event == "run.transition").count()
    service.retry(run.id)
    session.commit()
    after = session.query(RunEvent).filter(RunEvent.event == "run.transition").count()

    # PENDING plus the full walk again.
    assert after - before == len(SCRAPE_WALK) + 1


def test_retry_clears_a_previous_cancellation_request(service, session):
    """A stale flag would stop the retried run before it did anything."""
    run = _create(service, session)
    service._merge_stats(run, cancel_requested=True)
    run.state = RunState.FAILED.value
    session.commit()

    service.retry(run.id)
    session.commit()
    assert service.cancel_requested(run.id) is False


@pytest.mark.parametrize(
    "state", [RunState.SCRAPING, RunState.COMPLETE, RunState.CANCELLED, RunState.PENDING]
)
def test_retry_is_refused_from_anything_but_failed(service, session, state):
    run = _create(service, session)
    run.state = state.value
    session.commit()

    with pytest.raises(IllegalTransition):
        service.retry(run.id)


# ------------------------------------------------------------------ progress


def test_progress_reflects_real_job_counts(service, session):
    """AC2. Counted in SQL, not by loading rows."""
    run = _create(service, session, subreddits=("a", "b", "c", "d"))
    jobs = session.query(Job).filter(Job.run_id == run.id).order_by(Job.id).all()
    jobs[0].state = JobState.DONE.value
    jobs[1].state = JobState.DONE.value
    jobs[2].state = JobState.FAILED.value
    session.commit()

    progress = service.progress(run.id)
    assert progress.jobs_total == 4
    assert progress.jobs_done == 2
    assert progress.jobs_failed == 1
    assert progress.percent == 50


def test_progress_counts_only_this_run(service, session):
    """A shared counter would make every run's bar wrong the moment there are two."""
    first = _create(service, session, subreddits=("a", "b"))
    first.state = RunState.COMPLETE.value
    session.commit()
    second = _create(service, session, subreddits=("c",))

    assert service.progress(second.id).jobs_total == 1


def test_progress_pins_a_terminal_run_to_one_hundred(service, session):
    """A cancelled run stuck at 40% reads as still running."""
    run = _create(service, session, subreddits=("a", "b"))
    service.cancel(run.id)
    session.commit()

    assert service.progress(run.id).percent == 100


def test_progress_reports_zero_percent_with_no_jobs(service, session):
    run = _create(service, session, subreddits=())
    session.query(Job).filter(Job.run_id == run.id).delete()
    session.commit()

    assert service.progress(run.id).percent == 0


def test_progress_stage_label_names_the_subreddit(service, session):
    run = _create(service, session, subreddits=("saas", "startups"))
    service._merge_stats(run, subreddits_done=1, current_subreddit="startups")
    session.commit()

    assert service.progress(run.id).stage_label == "Scraping r/startups (2 of 2)"


def test_progress_serialises_to_json_safe_types(service, session):
    run = _create(service, session)
    payload = service.progress(run.id).to_dict()
    json.dumps(payload)  # raises if a datetime leaked through
    assert payload["terminal"] is False


def test_every_run_state_has_a_stage_label():
    """A state with no label would render its raw enum value at the operator."""
    from src.orchestration.run_service import _STAGE_LABELS

    assert {s.value for s in RunState} == set(_STAGE_LABELS)


# --------------------------------------------------------------------- misc


def test_service_enqueues_into_its_own_session_database(session, temp_db):
    """A service on a test database must not enqueue into the process-global one."""
    service = RunService(session)
    assert service.queue.engine is database.ENGINE


def test_options_round_trip_through_the_stored_json(service, session):
    run = _create(service, session, subreddits=("saas", "startups"))
    restored = RunOptions.from_dict(json.loads(run.options_json))
    assert restored.subreddits == ("saas", "startups")


@pytest.mark.parametrize("raw", [None, {}, {"subreddits": "notalist"}, {"other": 1}])
def test_options_tolerate_a_malformed_payload(raw):
    assert RunOptions.from_dict(raw).subreddits == ()


def test_merge_stats_preserves_keys_it_does_not_write(service, session):
    """Assigning a fresh dict would drop a counter another writer had set."""
    run = _create(service, session)
    service._merge_stats(run, leads_found=7)
    service._merge_stats(run, cancel_requested=True)

    stats = json.loads(run.stats_json)
    assert stats["leads_found"] == 7
    assert stats["cancel_requested"] is True
    assert stats["subreddits_total"] == 2


def test_queue_is_reused_when_supplied(session, temp_db):
    queue = JobQueue(database.ENGINE)
    assert RunService(session, queue).queue is queue
