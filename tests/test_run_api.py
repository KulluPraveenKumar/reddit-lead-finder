"""The run and job endpoints, over the real Flask app.

The `app` fixture disables the in-process worker, so nothing here races a
background thread. Where a test needs work executed it drives `Worker.tick()`
itself, which is deterministic and lets the test assert on the state *between*
two jobs -- something a live worker makes impossible.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import Job, Run, RunEvent
from src.orchestration.handlers import REGISTRY
from src.orchestration.job_queue import JobQueue, utcnow
from src.orchestration.run_service import RunOptions, RunService
from src.orchestration.states import JobState, RunState
from src.orchestration.worker import Worker


@pytest.fixture
def session(app):
    with Session(bind=database.ENGINE, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def worker(app):
    return Worker(JobQueue(database.ENGINE), REGISTRY, poll_interval=0.0)


@pytest.fixture
def stub_scraper(monkeypatch):
    """No network, no leads -- these tests are about the HTTP surface."""
    from src.orchestration.handlers import scrape as scrape_handler

    class _Nothing:
        def run(self, session, subreddits=None, run_id=None):
            return 0

    monkeypatch.setattr(scrape_handler, "build_scraper", lambda config: _Nothing())
    monkeypatch.setattr(scrape_handler, "load_config", lambda: {})


def _make_run(session, subreddits=("saas", "startups"), project_id=None):
    run = RunService(session, JobQueue(database.ENGINE)).create(
        project_id, RunOptions(subreddits=tuple(subreddits))
    )
    session.commit()
    return run


# ------------------------------------------------------------------- create


def test_post_runs_creates_a_run_and_queues_its_jobs(client):
    response = client.post("/api/runs", json={"options": {"subreddits": ["saas", "startups"]}})

    assert response.status_code == 201
    body = response.get_json()
    assert body["state"] == RunState.SCRAPING.value
    assert body["options"]["subreddits"] == ["saas", "startups"]

    jobs = client.get(f"/api/jobs?run_id={body['id']}").get_json()
    assert len(jobs["jobs"]) == 2


def test_post_runs_falls_back_to_the_configured_subreddits(client, session):
    """An operator pressing the button has already chosen their subreddits."""
    from src.db.models import DashboardSubreddit

    session.add(DashboardSubreddit(name="devops"))
    session.commit()

    body = client.post("/api/runs", json={}).get_json()
    assert "devops" in body["options"]["subreddits"]


def test_second_run_for_the_same_project_returns_409_with_the_run_id(client):
    """AC7. The UI navigates to the existing run rather than starting another."""
    first = client.post("/api/runs", json={"options": {"subreddits": ["saas"]}}).get_json()

    response = client.post("/api/runs", json={"options": {"subreddits": ["saas"]}})

    assert response.status_code == 409
    assert response.get_json()["run_id"] == first["id"]


def test_the_409_body_names_the_conflict(client):
    client.post("/api/runs", json={"options": {"subreddits": ["saas"]}})
    body = client.post("/api/runs", json={"options": {"subreddits": ["saas"]}}).get_json()
    assert "already active" in body["error"]


# --------------------------------------------------------------------- read


def test_get_run_returns_the_full_run(client, session):
    run = _make_run(session)
    body = client.get(f"/api/runs/{run.id}").get_json()

    assert body["id"] == run.id
    assert body["stats"]["subreddits_total"] == 2
    assert body["finished_at"] is None


def test_get_missing_run_is_404(client):
    assert client.get("/api/runs/9999").status_code == 404


def test_run_list_is_newest_first(client, session):
    first = _make_run(session, project_id=1)
    second = _make_run(session, project_id=2)

    body = client.get("/api/runs").get_json()
    assert [r["id"] for r in body][:2] == [second.id, first.id]


def test_run_list_filters_by_project_and_state(client, session):
    _make_run(session, project_id=1)
    other = _make_run(session, project_id=2)

    by_project = client.get("/api/runs?project_id=2").get_json()
    assert [r["id"] for r in by_project] == [other.id]

    by_state = client.get(f"/api/runs?state={RunState.COMPLETE.value}").get_json()
    assert by_state == []


def test_run_list_carries_the_columns_the_table_shows(client, session):
    _make_run(session)
    row = client.get("/api/runs").get_json()[0]
    assert "leads_found" in row and "duration_seconds" in row and "job_counts" in row


def test_run_list_counts_every_run_in_one_query(client, session):
    """No N+1: fifty rows must not mean fifty count queries.

    Invisible at ten runs and obvious at a thousand, which is exactly the kind
    of regression a timing test on a small fixture would never catch.
    """
    for index in range(6):
        run = _make_run(session, ("a", "b"), project_id=index)
        run.state = RunState.COMPLETE.value
        session.commit()

    from sqlalchemy import event

    counting: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        if "count" in statement.lower() and "jobs" in statement.lower():
            counting.append(statement)

    event.listen(database.ENGINE, "before_cursor_execute", record)
    try:
        rows = client.get("/api/runs").get_json()
    finally:
        event.remove(database.ENGINE, "before_cursor_execute", record)

    assert len(rows) == 6
    assert all(row["jobs_total"] == 2 for row in rows)
    assert len(counting) == 1, f"{len(counting)} count queries for 6 runs"


# ----------------------------------------------------------------- progress


def test_progress_reflects_real_job_counts(client, session, worker, stub_scraper):
    """AC2, over HTTP rather than through the service."""
    run = _make_run(session, ("a", "b", "c", "d"))

    worker.tick()
    worker.tick()

    body = client.get(f"/api/runs/{run.id}/progress").get_json()
    assert body["jobs_total"] == 4
    assert body["jobs_done"] == 2
    assert body["percent"] == 50
    assert body["terminal"] is False


def test_progress_of_a_finished_run_is_terminal(client, session, worker, stub_scraper):
    run = _make_run(session, ("a",))
    for _ in range(5):
        if not worker.tick():
            break

    body = client.get(f"/api/runs/{run.id}/progress").get_json()
    assert body["state"] == RunState.COMPLETE.value
    assert body["terminal"] is True
    assert body["percent"] == 100


def test_progress_answers_within_the_budget_at_five_thousand_jobs(client, session):
    """AC2's 50 ms budget, measured at the volume docs/13 §6 names.

    Measured as a p95 over repeated calls rather than a single timing: one slow
    call on a laptop proves nothing, and one fast call proves less.
    """
    run = _make_run(session, ())
    _seed_jobs(run.id, 5000)

    url = f"/api/runs/{run.id}/progress"
    client.get(url)  # warm the connection pool and the query plan

    timings = []
    for _ in range(20):
        start = time.perf_counter()
        response = client.get(url)
        timings.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 200

    timings.sort()
    p95 = timings[int(len(timings) * 0.95) - 1]
    assert p95 < 50, f"progress p95 was {p95:.1f} ms over 5,000 jobs (budget 50 ms)"


def test_progress_issues_one_query_for_the_job_counts(client, session):
    """T2. Loading Job rows and counting in Python is the failure mode here.

    Counting statements rather than timing: a per-state query would still be fast
    on a small table, so the budget test above would not catch the regression
    that matters at 5,000 rows.
    """
    run = _make_run(session, ("a", "b"))

    from sqlalchemy import event

    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        if "FROM jobs" in statement:
            statements.append(statement)

    event.listen(database.ENGINE, "before_cursor_execute", record)
    try:
        client.get(f"/api/runs/{run.id}/progress")
    finally:
        event.remove(database.ENGINE, "before_cursor_execute", record)

    assert len(statements) == 1, statements
    assert "count" in statements[0].lower()


def _seed_jobs(run_id: int, count: int) -> None:
    """Bulk-insert jobs without the ORM, so seeding does not dominate the test."""
    now = utcnow()
    rows = [
        {
            "run_id": run_id,
            "job_type": "scrape_subreddit",
            "payload_json": "{}",
            "state": "done" if index % 2 else "queued",
            "priority": 100,
            "attempts": 1,
            "max_attempts": 5,
            "available_at": now,
            "created_at": now,
        }
        for index in range(count)
    ]
    with Session(bind=database.ENGINE) as bulk:
        bulk.bulk_insert_mappings(Job, rows)
        bulk.commit()


# ------------------------------------------------------------------- events


def test_events_feed_is_incremental(client, session):
    """AC10. The client passes the last id it saw; it must not get it twice."""
    run = _make_run(session)

    first = client.get(f"/api/runs/{run.id}/events").get_json()
    assert first["events"]
    assert first["last_id"] == first["events"][-1]["id"]

    again = client.get(f"/api/runs/{run.id}/events?after={first['last_id']}").get_json()
    assert again["events"] == []
    assert again["last_id"] == first["last_id"]


def test_events_carry_the_walk_explanations(client, session):
    run = _make_run(session)
    events = client.get(f"/api/runs/{run.id}/events").get_json()["events"]

    messages = " ".join(e["message"] or "" for e in events)
    assert "Subreddit review already satisfied" in messages


def test_events_of_an_unknown_run_are_empty_not_an_error(client):
    """A feed is a stream; asking about a run with nothing yet is not a fault."""
    body = client.get("/api/runs/4242/events").get_json()
    assert body["events"] == []


# --------------------------------------------------------------------- cancel


def test_cancel_stops_the_run_and_cancels_queued_jobs(client, session):
    """AC6."""
    run = _make_run(session)

    response = client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 200
    assert response.get_json()["state"] == RunState.CANCELLED.value

    session.expire_all()
    states = {j.state for j in session.query(Job).filter(Job.run_id == run.id)}
    assert states == {JobState.CANCELLED.value}


def test_cancelling_a_cancelled_run_is_409_naming_both_states(client, session):
    """AC12 over HTTP."""
    run = _make_run(session)
    client.post(f"/api/runs/{run.id}/cancel")

    response = client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 409
    error = response.get_json()["error"]
    assert "cancelled" in error


def test_cancelling_a_missing_run_is_404(client):
    assert client.post("/api/runs/9999/cancel").status_code == 404


# ---------------------------------------------------------------------- retry


def test_retry_from_failed_restarts_the_run(client, session):
    run = _make_run(session)
    RunService(session, JobQueue(database.ENGINE)).fail(run.id, "boom")
    session.commit()

    response = client.post(f"/api/runs/{run.id}/retry")

    assert response.status_code == 200
    assert response.get_json()["state"] == RunState.SCRAPING.value


def test_retry_from_a_running_run_is_409(client, session):
    """AC12: 'retry only from FAILED' is enforced by the table, not by an if."""
    run = _make_run(session)

    response = client.post(f"/api/runs/{run.id}/retry")

    assert response.status_code == 409
    assert "scraping" in response.get_json()["error"]


# ----------------------------------------------------------------------- jobs


def test_jobs_endpoint_lists_a_run_and_its_counts(client, session):
    run = _make_run(session, ("a", "b", "c"))
    body = client.get(f"/api/jobs?run_id={run.id}").get_json()

    assert len(body["jobs"]) == 3
    assert body["counts"] == {"queued": 3}
    assert body["jobs"][0]["payload"]["subreddit"] == "a"


def test_jobs_endpoint_without_a_run_returns_nothing(client):
    """The whole jobs table is not a debug page."""
    assert client.get("/api/jobs").get_json()["jobs"] == []


def test_job_retry_requeues_a_failed_job(client, session):
    run = _make_run(session, ("a",))
    job = session.query(Job).filter(Job.run_id == run.id).one()
    job.state = JobState.FAILED.value
    job.attempts = 5
    job.max_attempts = 5
    job.error = "gave up"
    session.commit()

    response = client.post(f"/api/jobs/{job.id}/retry")

    assert response.status_code == 200
    body = response.get_json()
    assert body["state"] == JobState.QUEUED.value
    assert body["error"] is None
    assert body["max_attempts"] == 6, "an exhausted job must get one more attempt"


def test_job_retry_of_a_done_job_is_409(client, session):
    """DONE is terminal. Requeueing it would re-run work that succeeded."""
    run = _make_run(session, ("a",))
    job = session.query(Job).filter(Job.run_id == run.id).one()
    job.state = JobState.DONE.value
    session.commit()

    assert client.post(f"/api/jobs/{job.id}/retry").status_code == 409


def test_job_retry_of_a_missing_job_is_404(client):
    assert client.post("/api/jobs/9999/retry").status_code == 404


# -------------------------------------------------------- worker integration


def test_create_app_starts_no_worker_when_the_switch_is_off(client):
    """AC8's other half, and the reason the whole suite stays deterministic."""
    from src.dashboard.app import get_worker

    assert get_worker() is None


def test_create_app_starts_a_worker_when_the_switch_is_on(temp_db, monkeypatch):
    """The operator's default: `python main.py dashboard` and nothing else."""
    monkeypatch.setenv("WORKER_INPROCESS", "true")
    from src.dashboard.app import create_app, get_worker, stop_worker

    stop_worker()
    try:
        create_app(run_migrations=False)
        worker = get_worker()
        assert worker is not None and not worker.stopping
        assert worker.thread is not None and worker.thread.is_alive()
    finally:
        stop_worker()


def test_stopping_the_worker_waits_for_its_thread_to_exit(temp_db, monkeypatch):
    """F5: a thread that outlives its test polls an engine that is being disposed.

    `stop()` only sets an event, so without the join the next thing this process
    does -- dispose the engine, end the test -- races the loop's last claim.
    """
    monkeypatch.setenv("WORKER_INPROCESS", "true")
    from src.dashboard.app import create_app, get_worker, stop_worker

    stop_worker()
    create_app(run_migrations=False)
    worker = get_worker()
    assert worker is not None
    thread = worker.thread

    stop_worker()

    assert thread is not None and not thread.is_alive()
    assert get_worker() is None


def test_starting_the_worker_twice_starts_one_worker(temp_db, monkeypatch):
    """Two workers in one process would compete for the same jobs."""
    monkeypatch.setenv("WORKER_INPROCESS", "true")
    from src.dashboard.app import create_app, get_worker, stop_worker

    stop_worker()
    try:
        create_app(run_migrations=False)
        first = get_worker()
        create_app(run_migrations=False)
        assert get_worker() is first
    finally:
        stop_worker()


# ------------------------------------------------------------------ redaction


def test_no_credential_reaches_a_run_or_job_response(client, session):
    """R15 / F3, at the two sinks P3 adds.

    The leak is never where the guard is looking: both columns are redacted on
    write, and this asserts it again at the boundary that renders them.
    """
    secret = "sk-leakedcredential0123456789"
    run = _make_run(session, ("a",))
    service = RunService(session, JobQueue(database.ENGINE))
    service.fail(run.id, f"provider rejected key {secret}")
    session.commit()

    # Claimed first: a queued job cannot fail without running, and taking the
    # shortcut would test a state the queue never produces.
    queue = JobQueue(database.ENGINE)
    claimed = queue.claim("worker-test")
    assert claimed is not None
    queue.fail(claimed.id, f"auth failed with {secret}", retryable=False)

    for path in (
        f"/api/runs/{run.id}",
        f"/api/runs/{run.id}/progress",
        f"/api/runs/{run.id}/events",
        f"/api/jobs?run_id={run.id}",
        "/api/runs",
    ):
        assert secret not in client.get(path).get_data(as_text=True), f"leaked from {path}"


def test_run_error_is_redacted_in_the_database_not_just_the_response(client, session):
    """Redacting at the edge would leave the credential on disk."""
    secret = "sk-storedcredential0123456789"
    run = _make_run(session, ("a",))
    RunService(session, JobQueue(database.ENGINE)).fail(run.id, f"key {secret} rejected")
    session.commit()

    session.expire_all()
    stored = session.query(Run).filter(Run.id == run.id).one()
    assert secret not in (stored.error or "")


def test_event_messages_are_redacted(client, session):
    from src.obs.events import emit_event

    secret = "sk-eventcredential0123456789"
    run = _make_run(session, ("a",))
    emit_event(session, run.id, "test.leak", message=f"using {secret}")
    session.commit()

    stored = session.query(RunEvent).filter(RunEvent.event == "test.leak").one()
    assert secret not in (stored.message or "")
