"""The scheduler's enqueue path, and what ``/health`` reports about the queue."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import DashboardSubreddit, Job, Run
from src.orchestration.job_queue import JobQueue, utcnow
from src.orchestration.run_service import RunOptions, RunService


@pytest.fixture
def session(app):
    with Session(bind=database.ENGINE, expire_on_commit=False) as s:
        yield s


# ---------------------------------------------------------------- scheduler


def test_the_scheduler_enqueues_a_run(session):
    """docs/13 §4: `schedule` enqueues instead of calling the scrapers."""
    import main

    session.add(DashboardSubreddit(name="alpha"))
    session.commit()

    run_id = main.enqueue_scheduled_run({})

    session.expire_all()
    assert run_id is not None
    run = session.query(Run).filter(Run.id == run_id).one()
    assert run.state == "scraping"
    assert session.query(Job).filter(Job.run_id == run_id).count() >= 1


def test_the_scheduler_skips_a_tick_while_a_run_is_still_going(session):
    """The loop runs unattended: a routine skip must not end it.

    A 60-minute interval meeting a 70-minute scrape is normal operation, not an
    error, and an exception here would stop the scheduler scraping for good.
    """
    import main

    RunService(session, JobQueue(database.ENGINE)).create(None, RunOptions(subreddits=("a",)))
    session.commit()

    assert main.enqueue_scheduled_run({}) is None

    session.expire_all()
    assert session.query(Run).count() == 1


def test_the_scheduler_resumes_once_the_previous_run_finishes(session):
    """Otherwise one stuck run would silence the scheduler permanently."""
    import main

    service = RunService(session, JobQueue(database.ENGINE))
    first = service.create(None, RunOptions(subreddits=("a",)))
    session.commit()
    assert main.enqueue_scheduled_run({}) is None

    service.cancel(first.id)
    session.commit()

    assert main.enqueue_scheduled_run({}) is not None


# -------------------------------------------------------------------- health


def test_health_reports_queue_depth(client, session):
    RunService(session, JobQueue(database.ENGINE)).create(
        None, RunOptions(subreddits=("a", "b", "c"))
    )
    session.commit()

    queue = client.get("/api/health").get_json()["queue"]

    assert queue["queued"] == 3
    assert queue["running"] == 0
    assert queue["failed"] == 0


def test_health_reports_the_age_of_the_oldest_queued_job(client, session):
    """The field that actually detects a dead worker.

    A liveness flag can only speak for this process. A queue whose oldest job
    has been waiting an hour is stalled regardless of what any flag claims.
    """
    RunService(session, JobQueue(database.ENGINE)).create(None, RunOptions(subreddits=("a",)))
    session.commit()

    assert client.get("/api/health").get_json()["queue"]["oldest_queued_at"] is not None


def test_health_says_this_process_has_no_worker_when_it_does_not(client):
    """Honest about scope: it reports *this* process, and says so in the name."""
    body = client.get("/api/health").get_json()["queue"]

    assert body["inprocess_worker"] is False
    assert body["worker_id"] is None


def test_health_names_the_worker_when_one_is_running(temp_db, monkeypatch):
    monkeypatch.setenv("WORKER_INPROCESS", "true")
    from src.dashboard.app import create_app, stop_worker

    stop_worker()
    try:
        app = create_app(run_migrations=False)
        app.config["TESTING"] = True
        body = app.test_client().get("/api/health").get_json()["queue"]
        assert body["inprocess_worker"] is True
        assert body["worker_id"]
    finally:
        stop_worker()


def test_health_survives_a_queue_it_cannot_read(client, monkeypatch):
    """A health endpoint that 500s is the one thing it must never do."""
    from src.db.repositories import runs as runs_repo

    def explode(self):
        raise RuntimeError("no such table: jobs")

    monkeypatch.setattr(runs_repo.JobRepository, "queue_depth", explode)

    response = client.get("/api/health")
    assert response.status_code == 200
    assert "error" in response.get_json()["queue"]


def test_health_keeps_its_existing_keys(client):
    """Additive only: /health gained `queue` and changed nothing else."""
    body = client.get("/api/health").get_json()

    for key in ("status", "database", "schema", "proxies", "ai"):
        assert key in body, f"/api/health lost {key}"


# ------------------------------------------------------------ queue_depth API


def test_queue_depth_counts_running_and_failed_separately(session):
    """`/health` distinguishes a busy queue from a broken one."""
    from src.db.repositories.runs import JobRepository

    queue = JobQueue(database.ENGINE)
    RunService(session, queue).create(None, RunOptions(subreddits=("a", "b")))
    session.commit()

    claimed = queue.claim("w1")
    assert claimed is not None
    queue.fail(claimed.id, "boom", retryable=False)

    depth = JobRepository(session).queue_depth()
    assert depth["queued"] == 1
    assert depth["failed"] == 1


def test_queue_depth_is_empty_on_a_fresh_install(session):
    from src.db.repositories.runs import JobRepository

    depth = JobRepository(session).queue_depth()
    assert depth["queued"] == 0
    assert depth["oldest_queued_at"] is None


def test_a_job_scheduled_for_later_still_counts_as_queued(session):
    """A backed-off job is waiting work, and /health must not hide it."""
    from datetime import timedelta

    from src.db.repositories.runs import JobRepository

    JobQueue(database.ENGINE).enqueue(
        "maintenance", payload={}, available_at=utcnow() + timedelta(hours=1)
    )

    assert JobRepository(session).queue_depth()["queued"] == 1
