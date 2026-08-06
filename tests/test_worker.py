"""The worker loop: execution, failure classification, shutdown, heartbeat.

The worker is deliberately thin, so most of what is worth asserting is about
what it *refuses* to do — die on a handler's exception, run a job after being
told to stop, or let a handler's rollback erase the record of the failure.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest

from src.db.models import Job, ScrapeRun
from src.orchestration import JobState, RetryableError
from src.orchestration.job_queue import JobQueue, utcnow
from src.orchestration.worker import (
    SHUTDOWN_TIMEOUT_SECONDS,
    Worker,
    start_inprocess_worker,
    worker_inprocess_enabled,
)


@pytest.fixture
def queue(temp_db):
    from src.db import database

    return JobQueue(engine=database.ENGINE)


def _worker(queue, registry, **kwargs):
    kwargs.setdefault("poll_interval", 0.01)
    kwargs.setdefault("worker_id", "test-worker")
    return Worker(queue, registry, **kwargs)


def _state(queue, job_id):
    return queue.get(job_id).state


# -- execution -------------------------------------------------------------


def test_a_successful_handler_completes_the_job_with_its_result(queue):
    worker = _worker(queue, {"maintenance": lambda session, job: {"rows": 4}})
    job = queue.enqueue("maintenance")

    assert worker.tick() is True

    stored = queue.get(job.id)
    assert stored.state == JobState.DONE.value
    assert '"rows": 4' in stored.result_json


def test_tick_on_an_empty_queue_reports_no_work(queue):
    assert _worker(queue, {}).tick() is False


def test_a_handler_returning_none_still_completes(queue):
    worker = _worker(queue, {"maintenance": lambda session, job: None})
    job = queue.enqueue("maintenance")

    worker.tick()

    assert _state(queue, job.id) == JobState.DONE.value


def test_a_retryable_error_requeues_the_job(queue):
    def handler(session, job):
        raise RetryableError("upstream 429")

    worker = _worker(queue, {"maintenance": handler})
    job = queue.enqueue("maintenance")

    worker.tick()

    stored = queue.get(job.id)
    assert stored.state == JobState.QUEUED.value
    assert stored.available_at > utcnow()


def test_any_other_exception_fails_the_job_without_retrying(queue):
    def handler(session, job):
        raise ZeroDivisionError("a bug does not become correct by being run again")

    worker = _worker(queue, {"maintenance": handler})
    job = queue.enqueue("maintenance")

    worker.tick()

    stored = queue.get(job.id)
    assert stored.state == JobState.FAILED.value
    assert stored.attempts == 1


def test_an_unregistered_job_type_fails_without_burning_attempts(queue):
    worker = _worker(queue, {})
    job = queue.enqueue("scrape_subreddit")  # five attempts, none of them useful

    worker.tick()

    stored = queue.get(job.id)
    assert stored.state == JobState.FAILED.value
    assert "no handler registered" in stored.error


def test_a_handlers_writes_roll_back_when_it_raises(queue):
    """The queue's transaction and the handler's are separate on purpose."""

    def handler(session, job):
        session.add(ScrapeRun(scraper_type="subreddit", posts_found=1))
        session.flush()
        raise ValueError("after writing")

    worker = _worker(queue, {"maintenance": handler})
    job = queue.enqueue("maintenance")

    worker.tick()

    from sqlalchemy.orm import Session

    with Session(bind=queue.engine) as session:
        assert session.query(ScrapeRun).count() == 0, "handler write survived a rollback"
    assert _state(queue, job.id) == JobState.FAILED.value, "the failure was rolled back too"


def test_the_loop_survives_a_broken_queue(queue, monkeypatch):
    """One bad tick must not become an outage."""
    worker = _worker(queue, {})
    calls = {"n": 0}

    def explode(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] >= 3:
            worker.stop()
        raise RuntimeError("queue is on fire")

    monkeypatch.setattr(queue, "reclaim_expired", explode)
    worker.run_forever()

    assert calls["n"] >= 3


# -- lease expiry and idempotency -----------------------------------------


def test_a_reclaimed_job_re_runs_without_duplicating_rows(queue):
    """R9. The handler is idempotent, so the second run writes nothing new."""
    runs: list[int] = []

    def handler(session, job):
        runs.append(job.id)
        existing = session.query(ScrapeRun).filter(ScrapeRun.run_id.is_(None)).count()
        if existing == 0:
            session.add(ScrapeRun(scraper_type="subreddit", posts_found=7))
        return {"ran": len(runs)}

    worker = _worker(queue, {"maintenance": handler})
    job = queue.enqueue("maintenance")

    worker.tick()
    # Simulate the worker having died holding the lease, then the job re-running.
    from sqlalchemy.orm import Session

    with Session(bind=queue.engine) as session:
        row = session.get(Job, job.id)
        row.state = JobState.RUNNING.value
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()

    worker.tick()

    assert len(runs) == 2, "the job did not re-run after its lease expired"
    with Session(bind=queue.engine) as session:
        assert session.query(ScrapeRun).count() == 1, "the re-run duplicated a row"


def test_the_heartbeat_thread_extends_a_lease_while_a_handler_runs(queue):
    seen: list[object] = []

    def handler(session, job):
        # Longer than lease/3, so at least one beat lands while this runs.
        time.sleep(1.4)
        seen.append(queue.get(job.id).lease_expires_at)
        return None

    worker = _worker(queue, {"maintenance": handler}, lease_seconds=3)
    job = queue.enqueue("maintenance")
    claimed_until = None

    def capture():
        nonlocal claimed_until
        worker.tick()

    thread = threading.Thread(target=capture)
    thread.start()
    time.sleep(0.05)
    claimed_until = queue.get(job.id).lease_expires_at
    thread.join(timeout=30)

    assert seen and seen[0] > claimed_until, "the lease was never extended"


# -- shutdown --------------------------------------------------------------


def test_stop_ends_the_loop_between_jobs_not_inside_one(queue):
    finished: list[int] = []

    def handler(session, job):
        worker.stop()  # asked to stop while this job is in flight
        time.sleep(0.2)
        finished.append(job.id)
        return None

    worker = _worker(queue, {"maintenance": handler})
    first = queue.enqueue("maintenance")
    second = queue.enqueue("maintenance")

    # Run in a thread with a join deadline rather than calling `run_forever`
    # directly: a worker that ignores `stop()` would hang the whole suite
    # instead of failing, and a test that can only fail by hanging is not
    # evidence anyone will read. Found by mutation testing.
    started = time.monotonic()
    thread = threading.Thread(target=worker.run_forever, name="shutdown-test")
    thread.start()
    thread.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    elapsed = time.monotonic() - started

    assert not thread.is_alive(), (
        f"the worker was still running {SHUTDOWN_TIMEOUT_SECONDS:.0f}s after stop()"
    )
    assert finished == [first.id], "the in-flight job did not finish, or the next one started"
    assert _state(queue, second.id) == JobState.QUEUED.value
    assert elapsed < SHUTDOWN_TIMEOUT_SECONDS, "shutdown must be well inside the 30 s budget"


def test_a_signal_stops_the_worker(queue):
    worker = _worker(queue, {})

    worker._on_signal(15, None)

    assert worker.stopping is True


def test_installing_signal_handlers_off_the_main_thread_does_not_raise(queue):
    """The in-process worker runs in a daemon thread; the host owns the signals."""
    worker = _worker(queue, {})
    errors: list[BaseException] = []

    def install():
        try:
            worker.install_signal_handlers()
        except BaseException as exc:  # noqa: BLE001 - the point is that none escapes
            errors.append(exc)

    thread = threading.Thread(target=install)
    thread.start()
    thread.join(timeout=10)

    assert errors == []


# -- the rollback switch ---------------------------------------------------


def test_worker_inprocess_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("WORKER_INPROCESS", raising=False)
    assert worker_inprocess_enabled() is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off", " off "])
def test_worker_inprocess_can_be_switched_off(monkeypatch, value):
    """The phase's documented rollback. It must work for what an operator types."""
    monkeypatch.setenv("WORKER_INPROCESS", value)
    assert worker_inprocess_enabled() is False


def test_start_inprocess_worker_returns_none_when_disabled(queue, monkeypatch):
    monkeypatch.setenv("WORKER_INPROCESS", "false")
    assert start_inprocess_worker(queue, {}) is None


def test_start_inprocess_worker_runs_a_job_then_stops(queue, monkeypatch):
    monkeypatch.setenv("WORKER_INPROCESS", "true")
    done = threading.Event()
    job = queue.enqueue("maintenance")

    worker = start_inprocess_worker(queue, {"maintenance": lambda s, j: done.set() or {}})
    try:
        assert done.wait(timeout=30), "the in-process worker never ran the job"
        deadline = time.monotonic() + 30
        while _state(queue, job.id) != JobState.DONE.value and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _state(queue, job.id) == JobState.DONE.value
    finally:
        worker.stop()
