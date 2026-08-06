"""The ``maintenance`` handler: four purges, and the two tables it must not touch.

Every purge test asserts on **both** sides — the row that goes and the row that
stays. A DELETE with a wrong column name deletes nothing and passes any test that
only counts what survived.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from src.db.models import AICache, HttpCache, Job, Metric, Run, RunEvent
from src.orchestration.handlers import REGISTRY
from src.orchestration.handlers.maintenance import (
    DONE_JOBS_DAYS,
    METRICS_DAYS,
    RUN_EVENTS_DAYS,
    handle_maintenance,
)
from src.orchestration.job_queue import JobQueue, utcnow


@pytest.fixture
def engine(temp_db):
    from src.db import database

    return database.ENGINE


@pytest.fixture
def session(engine):
    with Session(bind=engine, expire_on_commit=False) as session:
        yield session


def _run(session, *, finished_days_ago: int | None) -> Run:
    finished = None if finished_days_ago is None else utcnow() - timedelta(days=finished_days_ago)
    run = Run(state="complete" if finished else "scraping", finished_at=finished)
    session.add(run)
    session.flush()
    return run


def _job(session, *, state: str = "done", **kwargs) -> Job:
    job = Job(job_type="maintenance", payload_json="{}", state=state, **kwargs)
    session.add(job)
    session.flush()
    return job


def _maintenance_job(session) -> Job:
    job = Job(job_type="maintenance", payload_json='{"vacuum": false}', state="running")
    session.add(job)
    session.flush()
    return job


# -- the four purges -------------------------------------------------------


def test_done_jobs_older_than_thirty_days_are_purged(session):
    old = _job(session, finished_at=utcnow() - timedelta(days=DONE_JOBS_DAYS + 1))
    recent = _job(session, finished_at=utcnow() - timedelta(days=DONE_JOBS_DAYS - 1))

    report = handle_maintenance(session, _maintenance_job(session))

    assert report["deleted"]["jobs"] == 1
    # Queried, not `session.get`: the purges are bulk deletes with
    # `synchronize_session=False`, so the identity map still holds the object
    # the database no longer has.
    surviving = _job_ids(session)
    assert old.id not in surviving
    assert recent.id in surviving


def test_a_failed_job_is_kept_however_old(session):
    """A failure is evidence. Only `done` rows are noise once they are old."""
    failed = _job(session, state="failed", finished_at=utcnow() - timedelta(days=400))

    handle_maintenance(session, _maintenance_job(session))

    assert failed.id in _job_ids(session)


def _job_ids(session) -> set[int]:
    return {row.id for row in session.query(Job.id).all()}


def test_events_of_runs_finished_over_ninety_days_ago_are_purged(session):
    old_run = _run(session, finished_days_ago=RUN_EVENTS_DAYS + 1)
    recent_run = _run(session, finished_days_ago=RUN_EVENTS_DAYS - 1)
    live_run = _run(session, finished_days_ago=None)
    for run in (old_run, recent_run, live_run):
        session.add(RunEvent(run_id=run.id, level="info", event="x"))
    session.flush()

    report = handle_maintenance(session, _maintenance_job(session))

    assert report["deleted"]["run_events"] == 1
    remaining = {row.run_id for row in session.query(RunEvent).all()}
    assert remaining == {recent_run.id, live_run.id}


def test_expired_http_cache_rows_are_purged(session):
    session.add(HttpCache(cache_key="a", url="u", body="b", expires_at=utcnow() - timedelta(1)))
    session.add(HttpCache(cache_key="b", url="u", body="b", expires_at=utcnow() + timedelta(1)))
    session.add(HttpCache(cache_key="c", url="u", body="b", expires_at=None))
    session.flush()

    report = handle_maintenance(session, _maintenance_job(session))

    assert report["deleted"]["http_cache"] == 1
    assert {row.cache_key for row in session.query(HttpCache).all()} == {"b", "c"}


def test_metrics_older_than_fourteen_days_are_purged(session):
    session.add(Metric(name="old", recorded_at=utcnow() - timedelta(days=METRICS_DAYS + 1)))
    session.add(Metric(name="new", recorded_at=utcnow() - timedelta(days=METRICS_DAYS - 1)))
    session.flush()

    report = handle_maintenance(session, _maintenance_job(session))

    assert report["deleted"]["metrics"] == 1
    assert {row.name for row in session.query(Metric).all()} == {"new"}


# -- what maintenance must never touch -------------------------------------


def test_ai_cache_is_never_purged(session):
    """R14 / AD-14: the cache is the cost saving, and it has no TTL by design."""
    session.add(
        AICache(
            cache_key="k",
            provider="deepseek",
            model="deepseek-v4-flash",
            stage="enrich",
            prompt_version=1,
            payload_json="{}",
        )
    )
    session.flush()

    handle_maintenance(session, _maintenance_job(session))

    assert session.query(AICache).count() == 1


def test_a_run_is_never_deleted_only_its_events(session):
    run = _run(session, finished_days_ago=RUN_EVENTS_DAYS + 10)
    session.add(RunEvent(run_id=run.id, level="info", event="x"))
    session.flush()

    handle_maintenance(session, _maintenance_job(session))

    assert session.get(Run, run.id) is not None


# -- shape and idempotency -------------------------------------------------


def test_the_report_names_all_four_tables_and_totals_them(session):
    report = handle_maintenance(session, _maintenance_job(session))

    assert set(report["deleted"]) == {"jobs", "run_events", "http_cache", "metrics"}
    assert report["total"] == sum(report["deleted"].values())
    assert report["vacuumed"] is False


def test_running_maintenance_twice_deletes_the_same_rows_once(session):
    """R9 — a lease can expire mid-purge, so this runs twice by design."""
    _job(session, finished_at=utcnow() - timedelta(days=DONE_JOBS_DAYS + 1))

    first = handle_maintenance(session, _maintenance_job(session))
    second = handle_maintenance(session, _maintenance_job(session))

    assert first["deleted"]["jobs"] == 1
    assert second["deleted"]["jobs"] == 0


def test_vacuum_is_skipped_when_too_few_pages_are_free(session):
    report = handle_maintenance(session, _maintenance_job(session))
    assert report["vacuumed"] is False


def test_vacuum_runs_when_the_payload_asks_and_pages_are_free(session, monkeypatch):
    from src.orchestration.handlers import maintenance

    monkeypatch.setattr(maintenance, "VACUUM_FREELIST_PAGES", 0)
    job = Job(job_type="maintenance", payload_json="{}", state="running")
    session.add(job)
    session.flush()

    assert handle_maintenance(session, job)["vacuumed"] is True


# -- registration ----------------------------------------------------------


def test_maintenance_is_the_only_handler_p2_registers(engine):
    """P2 owns one job type. The rest arrive with the stages that need them."""
    assert set(REGISTRY) == {"maintenance"}
    assert REGISTRY["maintenance"] is handle_maintenance


def test_the_worker_runs_maintenance_end_to_end(engine):
    from src.orchestration.worker import Worker

    queue = JobQueue(engine=engine)
    job = queue.enqueue("maintenance", payload={"vacuum": False})

    Worker(queue, poll_interval=0.01, worker_id="w1").tick()

    stored = queue.get(job.id)
    assert stored.state == "done"
    assert '"total": 0' in stored.result_json
