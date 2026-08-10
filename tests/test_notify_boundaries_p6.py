"""P7 Stage 6 -- proof that the notification wiring did not re-open P6's guarantees.

Stage 5 delivered the wiring itself, because ``dispatch_pending`` is unusable
without a caller and the lock-discipline tests need the real handler. This file is
Stage 6's other half: the checks that the wiring **cost nothing** elsewhere.

Three properties, none of which had a test before:

* **G4/G5** -- ``handle_discover`` still commits **exactly once**, before its fetch.
  P7 deliberately does not touch that handler, and this is what makes "deliberately"
  checkable. A second commit there would perturb the transaction structure P6's
  overflow and watermark tests depend on.
* **D7's atomicity** -- ``fail()``'s enqueue lives in the same transaction as the
  ``FAILED`` transition, so a rollback cannot leave a job pointing at a run that
  never failed.
* **No I/O in ``fail()``** -- it enqueues; it does not send. ``fail()`` is reachable
  from a web route, and a network call there would violate **R8** and re-open trap
  **T0** from the web side, which is where P3 originally lost its sign-off.
"""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import Job, Run, RunEvent
from src.notify import SENT_EVENT
from src.orchestration.handlers.discover import DISCOVER_JOB, handle_discover
from src.orchestration.handlers.finalize import handle_finalize_run
from src.orchestration.job_queue import JobQueue
from src.orchestration.run_service import FINALIZE_JOB, RunOptions, RunService
from src.orchestration.states import JobState, RunState

T0 = datetime.datetime(2026, 8, 10, 12, 0)


@pytest.fixture
def session(temp_db):
    with Session(database.ENGINE) as s:
        yield s


class CommitCounter:
    """Wraps ``Session.commit`` and counts the calls.

    Counting the method rather than watching for a ``COMMIT`` statement: SQLAlchemy
    issues the latter through the DBAPI connection, not as a cursor execute, so a
    statement listener never sees it. What this test is about is the *handler's*
    behaviour, and the handler's behaviour is how many times it calls ``commit``.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.count = 0
        self._original = session.commit

    def __enter__(self) -> CommitCounter:
        def counting_commit(*args, **kwargs):
            self.count += 1
            return self._original(*args, **kwargs)

        self.session.commit = counting_commit  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc) -> None:
        self.session.commit = self._original  # type: ignore[method-assign]


# ---------------------------------------------------------------- G4 and G5


@pytest.fixture
def fake_feed(monkeypatch):
    """The one line that would open a network client. Copied from P6's own tests."""
    calls = {"count": 0, "posts": [], "committed_before_fetch": None}

    class FakeClient:
        def fetch_feed(self, subreddits, *, sort="new", limit=None, query=None):
            calls["count"] += 1
            return list(calls["posts"])

        def get_new_posts(self, subreddit, limit=100):
            calls["html_walks"] = calls.get("html_walks", 0) + 1
            return []

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: FakeClient())
    return calls


def _discover_job(session, run_id, **payload):
    job = Job(
        run_id=run_id,
        job_type=DISCOVER_JOB,
        payload_json=json.dumps({"subreddits": ["SaaS"], "channel": "listing", **payload}),
        state="running",
        available_at=T0,
        created_at=T0,
    )
    session.add(job)
    session.commit()
    return job


@pytest.fixture
def discovering_run(session):
    row = Run(state="DISCOVERING", started_at=T0, updated_at=T0)
    session.add(row)
    session.commit()
    return row


def test_discover_commits_exactly_once(session, discovering_run, fake_feed):
    """**G4/G5.** P7 must not have added a commit to this handler.

    ``handle_discover`` has one ``session.commit()``, and its position is
    load-bearing: it commits the start event *before* fetching, so SQLite's single
    write lock is not held across the feed request. P6 asserts the *position* with
    a test that inspects the session from inside the fetch; nothing asserted the
    *count*, so a second commit could be added without any test objecting -- and a
    second commit is exactly what a careless P7 would have added to dispatch a
    notification from here.

    P7's answer is to dispatch from ``finalize_run`` instead and leave this
    handler alone. This is what makes that decision enforceable rather than
    merely stated.
    """
    job = _discover_job(session, discovering_run.id)

    with CommitCounter(session) as counter:
        handle_discover(session, job)

    assert counter.count == 1, (
        f"handle_discover committed {counter.count} times. P7 dispatches from "
        "finalize_run precisely so this stays at one -- a second commit perturbs "
        "the transaction structure P6's overflow and watermark tests rely on."
    )


def test_discover_sends_no_notification_of_its_own(session, discovering_run, fake_feed):
    """The handler is untouched, so it writes no ``notify.*`` row.

    ``discovery.overflow`` reaches the operator through ``finalize_run``'s drain
    (late, per assumption A9), not from here.

    **The run is seeded with a real overflow first**, and that is what makes this
    test able to fail. A run in ``DISCOVERING`` has only ``profiling`` and
    ``discovering`` transitions behind it, neither of which is notifiable -- so a
    stray ``dispatch_pending`` planted in this handler would find no evidence,
    send nothing, and leave this assertion green. A surviving mutation said
    exactly that. With an overflow row present there *is* something to send, so a
    stray dispatch really does write a ``notify.sent`` row and really does fail.
    """
    session.add(
        RunEvent(
            run_id=discovering_run.id,
            event="discovery.overflow",
            level="error",
            data_json=json.dumps({"subreddit": "SaaS", "seen": 100, "html_recovered": 3}),
        )
    )
    session.commit()

    job = _discover_job(session, discovering_run.id)
    handle_discover(session, job)

    notify_rows = (
        session.query(RunEvent)
        .filter(RunEvent.run_id == discovering_run.id, RunEvent.event.like("notify.%"))
        .all()
    )
    assert notify_rows == [], (
        "handle_discover dispatched a notification. P7 dispatches from finalize_run "
        "so this handler's single-commit structure (G4/G5) stays untouched."
    )


def test_the_discover_handler_source_has_exactly_one_commit():
    """Belt and braces, at the source level.

    The runtime count above can only observe the paths a test drives. A commit
    added inside the overflow-recovery branch would be missed by a poll with
    nothing new. Counting them in the source catches that -- and P6's own
    module docstring is explicit that the ordering is deliberate.
    """
    import inspect

    from src.orchestration.handlers import discover

    source = inspect.getsource(discover)
    commits = [
        line.strip()
        for line in source.splitlines()
        if "session.commit()" in line and not line.strip().startswith("#")
    ]
    assert len(commits) == 1, f"expected one commit in discover.py, found {commits}"


# ------------------------------------------------------- D7's atomicity


def test_fail_enqueues_the_drain_in_the_same_transaction_as_the_transition(session):
    """A rollback must not leave a job pointing at a run that never failed.

    The enqueue joins the caller's transaction rather than opening one of its own.
    If it committed independently, a rollback after ``fail()`` would leave a
    ``finalize_run`` job for a run still in ``SCRAPING`` -- and the worker would
    claim it and finalise a run that is still working.
    """
    service = RunService(session, JobQueue(database.ENGINE))
    run = service.create(None, RunOptions(subreddits=("a",)))
    session.commit()

    service.fail(run.id, "boom")
    # Deliberately NOT committed.
    session.rollback()

    with Session(database.ENGINE) as fresh:
        reloaded = fresh.get(Run, run.id)
        assert reloaded.state == RunState.SCRAPING.value, "the failure rolled back"
        finalisers = (
            fresh.query(Job).filter(Job.run_id == run.id, Job.job_type == FINALIZE_JOB).all()
        )
        assert finalisers == [], (
            "the enqueue survived a rollback that undid the FAILED transition -- "
            "the worker would finalise a run that is still scraping"
        )


def test_fail_performs_no_network_call(session, monkeypatch):
    """**R8 and T0 from the web side.** ``fail()`` enqueues; it does not send.

    It is reachable from a Flask request, and P3 lost a sign-off to a network call
    holding the write lock. Any transport being constructed or used here would be
    the same defect in a new place, so the guard is that the notification package
    is never touched at all.
    """
    import src.notify.service as notify_service

    def explode(*args, **kwargs):
        raise AssertionError("fail() must not dispatch a notification")

    monkeypatch.setattr(notify_service.NotificationService, "dispatch_pending", explode)

    service = RunService(session, JobQueue(database.ENGINE))
    run = service.create(None, RunOptions(subreddits=("a",)))
    session.commit()

    service.fail(run.id, "boom")  # must not raise
    session.commit()

    with Session(database.ENGINE) as fresh:
        assert fresh.get(Run, run.id).state == RunState.FAILED.value
        assert (
            fresh.query(Job).filter(Job.run_id == run.id, Job.job_type == FINALIZE_JOB).count() == 1
        )


# --------------------------------------------- run.failed, through the worker


def test_run_failed_is_delivered_by_the_worker_draining_the_enqueued_job(session, monkeypatch):
    """D7 end to end: the enqueue is claimed and the message goes out.

    Stage 5 proved ``fail()`` enqueues and that a failed run dispatches. This is
    the join between them -- the worker claiming that job and the notification
    actually leaving -- which is the only path an operator's failure alert takes.
    """
    sends: list[tuple[str, str]] = []

    class Recording:
        name = "fake"

        def send(self, *, chat_id, markdown):
            sends.append((chat_id, markdown))
            return f"fake-{len(sends)}"

    import src.notify.service as notify_service
    from src.notify import NotifySettings

    original = notify_service.NotificationService.__init__

    def patched(self, s, transport=None, settings=None):
        original(
            self,
            s,
            Recording(),
            NotifySettings(enabled=True, transport="fake", telegram_chat_id="42"),
        )

    monkeypatch.setattr(notify_service.NotificationService, "__init__", patched)

    service = RunService(session, JobQueue(database.ENGINE))
    run = service.create(None, RunOptions(subreddits=("a",)))
    session.commit()
    service.fail(run.id, "the pool was blocked")
    session.commit()

    # The worker claims by `(priority, id)`, so the failed attempt's still-queued
    # scrape jobs come first -- exactly as a real worker would see them. What
    # matters is that the finaliser `fail()` enqueued is genuinely reachable, so
    # claim until it comes round rather than assuming it is first.
    queue = JobQueue(database.ENGINE)
    claimed = None
    claimed_types = []
    for _ in range(10):
        job_row = queue.claim("test-worker")
        if job_row is None:
            break
        claimed_types.append(job_row.job_type)
        if job_row.job_type == FINALIZE_JOB:
            claimed = job_row
            break

    assert claimed is not None, (
        f"the worker never reached the finaliser fail() enqueued; claimed {claimed_types}"
    )

    with Session(database.ENGINE) as handler_session:
        job = handler_session.get(Job, claimed.id)
        result = handle_finalize_run(handler_session, job)

    assert "skipped" in result, "a failed run is already terminal"
    assert result["notified"] == ["run.failed", "gate.reached"]
    assert len(sends) == 2
    assert "FAILED" in sends[0][1]
    assert "the pool was blocked" in sends[0][1]

    with Session(database.ENGINE) as fresh:
        kinds = [
            json.loads(e.data_json)["kind"]
            for e in fresh.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.event == SENT_EVENT)
            .order_by(RunEvent.id)
        ]
        assert kinds == ["run.failed", "gate.reached"]


def test_the_worker_claimable_job_is_the_only_side_effect_of_failing(session):
    """``fail()`` adds one job and nothing else claimable."""
    service = RunService(session, JobQueue(database.ENGINE))
    run = service.create(None, RunOptions(subreddits=("a", "b")))
    session.commit()

    before = (
        session.query(Job).filter(Job.run_id == run.id, Job.state == JobState.QUEUED.value).count()
    )
    service.fail(run.id, "boom")
    session.commit()
    after = (
        session.query(Job).filter(Job.run_id == run.id, Job.state == JobState.QUEUED.value).count()
    )
    assert after == before + 1
