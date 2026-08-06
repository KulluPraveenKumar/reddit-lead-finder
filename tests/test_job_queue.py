"""The job queue: claiming, retrying, reclaiming — and the race under all three.

The tests that matter here are the concurrent ones. Every serial assertion in
this file would pass against an implementation with no locking at all, which is
why ``test_two_workers_claim_a_job_exactly_once`` and
``test_no_lost_updates_over_1000_claim_attempts`` use real threads against a real
SQLite file rather than asserting on the text of the SQL.
"""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from src.db.models import Job
from src.orchestration import IllegalTransition, JobState
from src.orchestration.job_queue import (
    BACKOFF_CAP_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    MAX_ATTEMPTS,
    JobQueue,
    backoff_seconds,
    payload_of,
    utcnow,
)


@pytest.fixture
def queue(temp_db):
    from src.db import database

    return JobQueue(engine=database.ENGINE)


def _session(queue):
    from sqlalchemy.orm import Session

    return Session(bind=queue.engine, expire_on_commit=False)


def _state(queue, job_id):
    with _session(queue) as session:
        return session.get(Job, job_id).state


# -- enqueue ---------------------------------------------------------------


def test_enqueue_writes_a_queued_job_with_its_type_max_attempts(queue):
    job = queue.enqueue("maintenance", payload={"vacuum": False})

    stored = queue.get(job.id)
    assert stored.state == JobState.QUEUED.value
    assert stored.attempts == 0
    assert stored.max_attempts == MAX_ATTEMPTS["maintenance"] == 2
    assert payload_of(stored) == {"vacuum": False}


def test_unknown_job_type_gets_the_default_attempt_budget(queue):
    job = queue.enqueue("not_a_real_type")
    assert queue.get(job.id).max_attempts == DEFAULT_MAX_ATTEMPTS


def test_enqueue_in_the_callers_transaction_rolls_back_with_it(queue):
    """A handler enqueueing its successor must commit with the work, not before.

    This is the atomicity ``docs/13`` §3 exists to protect, from the failing
    side: if the stage's work rolls back, the next stage must not be queued.
    """
    session = _session(queue)
    try:
        queue.enqueue("maintenance", session=session)
        session.rollback()
    finally:
        session.close()

    assert queue.claim("outsider") is None


def test_enqueue_in_the_callers_transaction_lands_on_commit(queue):
    session = _session(queue)
    try:
        queue.enqueue("maintenance", session=session)
        session.commit()
    finally:
        session.close()

    assert queue.claim("outsider") is not None


def test_payload_of_survives_malformed_json(queue):
    job = queue.enqueue("maintenance")
    with _session(queue) as session:
        session.get(Job, job.id).payload_json = "{not json"
        session.commit()

    assert payload_of(queue.get(job.id)) == {}


# -- claim -----------------------------------------------------------------


def test_claim_returns_none_on_an_empty_queue(queue):
    assert queue.claim("w1") is None


def test_claim_marks_running_and_consumes_an_attempt(queue):
    job = queue.enqueue("maintenance")

    claimed = queue.claim("w1", lease_seconds=60)

    assert claimed.id == job.id
    assert claimed.state == JobState.RUNNING.value
    assert claimed.worker_id == "w1"
    assert claimed.attempts == 1
    assert claimed.lease_expires_at > utcnow()


def test_claim_ignores_a_job_scheduled_for_the_future(queue):
    """The naive-UTC boundary. An aware datetime here claims nothing, silently."""
    queue.enqueue("maintenance", available_at=utcnow() + timedelta(hours=1))

    assert queue.claim("w1") is None


def test_claim_takes_the_due_job_before_the_future_one(queue):
    later = queue.enqueue("maintenance", available_at=utcnow() + timedelta(hours=1))
    due = queue.enqueue("maintenance")

    claimed = queue.claim("w1")

    assert claimed.id == due.id != later.id


def test_claim_honours_priority_then_id(queue):
    normal = queue.enqueue("maintenance", priority=100)
    urgent = queue.enqueue("maintenance", priority=1)
    second_normal = queue.enqueue("maintenance", priority=100)

    assert queue.claim("w1").id == urgent.id
    assert queue.claim("w1").id == normal.id
    assert queue.claim("w1").id == second_normal.id


def test_two_workers_claim_a_job_exactly_once(queue):
    """T1. Both halves of the claim are needed; this fails without either."""
    job = queue.enqueue("maintenance")
    results: list[Job | None] = []
    barrier = threading.Barrier(2)

    def race(worker_id):
        barrier.wait()
        results.append(queue.claim(worker_id))

    threads = [threading.Thread(target=race, args=(f"w{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1, "the same job was claimed twice"
    assert claimed[0].id == job.id
    assert queue.get(job.id).attempts == 1, "attempts incremented more than once"


def test_the_claim_update_refuses_a_job_that_is_no_longer_queued(queue):
    """The ``AND state='queued'`` half of T1, tested where it is observable.

    ``BEGIN IMMEDIATE`` serialises the workers in the race test above, so the
    guard changes no outcome there. Here it is the only thing under test: a job
    another worker already took must return 0 rows changed, not be stolen.
    """
    job = queue.enqueue("maintenance")
    queue.claim("first", lease_seconds=600)

    raw = queue.engine.raw_connection()
    try:
        cursor = raw.cursor()
        changed = queue._claim_update(cursor, job.id, "second", utcnow(), utcnow())
        raw.rollback()
        cursor.close()
    finally:
        raw.close()

    assert changed == 0, "a running job was re-claimed"


def test_no_lost_updates_over_1000_claim_attempts(queue):
    """The phase's metric: 0 lost updates over 1,000 attempts, 4 workers racing."""
    total = 1000
    for _ in range(total):
        queue.enqueue("maintenance")

    claimed_ids: list[int] = []
    failures: list[str] = []
    lock = threading.Lock()

    def drain(worker_id):
        while True:
            try:
                job = queue.claim(worker_id, lease_seconds=600)
            except Exception as exc:  # noqa: BLE001 - asserted on below
                # Collected rather than allowed to kill the thread: a claim that
                # raises `database is locked` is exactly the K13 failure this
                # test exists for, and a dead thread would look like a clean run
                # once the other three finished the work.
                with lock:
                    failures.append(f"{type(exc).__name__}: {exc}")
                return
            if job is None:
                return
            with lock:
                claimed_ids.append(job.id)

    threads = [threading.Thread(target=drain, args=(f"w{i}",)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=180)

    assert failures == [], f"the claim raised under contention: {failures[:3]}"
    assert len(claimed_ids) == total
    assert len(set(claimed_ids)) == total, "a job was handed to two workers"


# -- backoff and retry -----------------------------------------------------


def test_backoff_grows_with_every_attempt_and_never_overlaps():
    """Jitter is ±20% precisely so 'it grew' stays a testable claim."""
    delays = [max(backoff_seconds(n) for _ in range(200)) for n in range(1, 6)]
    mins = [min(backoff_seconds(n) for _ in range(200)) for n in range(1, 6)]

    for earlier_max, later_min in zip(delays, mins[1:], strict=False):
        assert earlier_max < later_min


def test_backoff_is_capped_at_ten_minutes():
    assert all(backoff_seconds(n) <= BACKOFF_CAP_SECONDS for n in range(1, 40))


def test_a_retryable_failure_requeues_with_a_future_available_at(queue):
    job = queue.enqueue("maintenance")
    queue.claim("w1")

    queue.fail(job.id, "upstream timeout", retryable=True)

    stored = queue.get(job.id)
    assert stored.state == JobState.QUEUED.value
    assert stored.available_at > utcnow()
    assert stored.worker_id is None
    assert queue.claim("w2") is None, "a backed-off job must not be claimable yet"


def test_retries_stop_at_max_attempts(queue):
    job = queue.enqueue("maintenance")  # max_attempts == 2

    for _ in range(MAX_ATTEMPTS["maintenance"]):
        with _session(queue) as session:  # skip the backoff wait the last fail set
            session.get(Job, job.id).available_at = utcnow()
            session.commit()
        assert queue.claim("w1") is not None
        queue.fail(job.id, "still failing", retryable=True)

    stored = queue.get(job.id)
    assert stored.attempts == MAX_ATTEMPTS["maintenance"]
    assert stored.state == JobState.FAILED.value


def test_a_non_retryable_failure_fails_immediately(queue):
    job = queue.enqueue("maintenance")
    queue.claim("w1")

    queue.fail(job.id, "no handler registered", retryable=False)

    stored = queue.get(job.id)
    assert stored.state == JobState.FAILED.value
    assert stored.attempts == 1, "a non-retryable failure must not burn the budget"


def test_failure_text_is_redacted_before_it_is_stored(queue):
    """R15: the error column is rendered into a page in P3."""
    job = queue.enqueue("maintenance")
    queue.claim("w1")

    queue.fail(job.id, "auth failed for sk-abcdefghijklmnopqrstuvwxyz", retryable=False)

    assert "sk-abcdefghijklmnop" not in queue.get(job.id).error


def test_failing_an_already_terminal_job_is_a_no_op(queue):
    job = queue.enqueue("maintenance")
    queue.claim("w1")
    queue.complete(job.id)

    queue.fail(job.id, "late report", retryable=False)  # must not raise

    assert _state(queue, job.id) == JobState.DONE.value


# -- complete --------------------------------------------------------------


def test_complete_stores_the_result_and_clears_the_lease(queue):
    job = queue.enqueue("maintenance")
    queue.claim("w1")

    queue.complete(job.id, {"deleted": 3})

    stored = queue.get(job.id)
    assert stored.state == JobState.DONE.value
    assert stored.lease_expires_at is None
    assert "deleted" in stored.result_json


def test_completing_a_job_that_was_already_failed_does_not_raise(queue):
    """The lease-expiry race: reclaimed to failed, then the old worker finishes."""
    job = queue.enqueue("maintenance")
    queue.claim("w1")
    queue.fail(job.id, "gone", retryable=False)

    queue.complete(job.id, {"late": True})

    assert _state(queue, job.id) == JobState.FAILED.value


def test_an_illegal_job_transition_names_both_states():
    from src.orchestration import assert_job_transition

    with pytest.raises(IllegalTransition) as exc:
        assert_job_transition(JobState.DONE, JobState.RUNNING)

    assert "done" in str(exc.value) and "running" in str(exc.value)


# -- heartbeat and reclamation ---------------------------------------------


def test_heartbeat_extends_the_lease(queue):
    job = queue.enqueue("maintenance")
    claimed = queue.claim("w1", lease_seconds=30)
    before = claimed.lease_expires_at

    queue.heartbeat(job.id, extend_seconds=900)

    assert queue.get(job.id).lease_expires_at > before


def test_heartbeat_does_not_resurrect_a_reclaimed_job(queue):
    job = queue.enqueue("maintenance")
    queue.claim("w1", lease_seconds=30)
    _expire_lease(queue, job.id)
    queue.reclaim_expired()

    queue.heartbeat(job.id)

    assert queue.get(job.id).lease_expires_at is None


def test_an_expired_lease_returns_the_job_to_the_queue(queue):
    job = queue.enqueue("maintenance")
    queue.claim("w1", lease_seconds=30)
    _expire_lease(queue, job.id)

    assert queue.reclaim_expired() == 1

    stored = queue.get(job.id)
    assert stored.state == JobState.QUEUED.value
    assert stored.worker_id is None
    assert queue.claim("w2").id == job.id


def test_reclaim_leaves_a_live_lease_alone(queue):
    queue.enqueue("maintenance")
    queue.claim("w1", lease_seconds=900)

    assert queue.reclaim_expired() == 0


def test_a_job_out_of_attempts_is_failed_rather_than_reclaimed_forever(queue):
    """Otherwise a job that kills its worker every time is retried for ever."""
    job = queue.enqueue("maintenance")  # max_attempts == 2
    for _ in range(MAX_ATTEMPTS["maintenance"]):
        queue.claim("w1", lease_seconds=30)
        _expire_lease(queue, job.id)
        queue.reclaim_expired()

    assert _state(queue, job.id) == JobState.FAILED.value


def test_cancel_queued_leaves_running_jobs_alone(queue):
    run_id = _make_run(queue)
    running = queue.enqueue("maintenance", run_id=run_id)
    queue.claim("w1")
    queued = queue.enqueue("maintenance", run_id=run_id)

    assert queue.cancel_queued(run_id) == 1
    assert _state(queue, queued.id) == JobState.CANCELLED.value
    assert _state(queue, running.id) == JobState.RUNNING.value


def _make_run(queue):
    from src.db.models import Run

    with _session(queue) as session:
        run = Run(state="pending")
        session.add(run)
        session.commit()
        return run.id


def _expire_lease(queue, job_id):
    with _session(queue) as session:
        session.get(Job, job_id).lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
