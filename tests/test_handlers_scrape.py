"""``scrape_subreddit`` and ``finalize_run``, driven through a real worker.

The scraper is replaced by a fake that records what it was asked for and writes
the leads it claims to have found. Everything else is real: the queue, the
worker, the transaction boundaries and the state machine. A test that stubbed the
queue as well would prove only that the handler's body runs.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import Job, Lead, RunEvent, ScrapeRun
from src.orchestration.handlers import REGISTRY
from src.orchestration.handlers import scrape as scrape_handler
from src.orchestration.job_queue import JobQueue, utcnow
from src.orchestration.run_service import RunOptions, RunService
from src.orchestration.states import JobState, RunState
from src.orchestration.worker import Worker


class FakeScraper:
    """Stands in for ``SubredditScraper``, with the same call contract.

    Writes real ``Lead`` rows and commits them, because that is what the real
    scraper does and the handler's ordering argument depends on it.

    **It skips `reddit_id`s already stored, because the real scraper does** --
    `LeadRepository.filter_new` is where scraping's idempotence comes from. A
    fake without that would make the idempotence test a test of this class
    rather than of the handler, and it would fail for a reason the product does
    not have.
    """

    def __init__(self, leads_per_subreddit=1, boom=False):
        self.leads_per_subreddit = leads_per_subreddit
        self.boom = boom
        self.calls: list[tuple[list[str], int | None]] = []

    def run(self, session, subreddits=None, run_id=None):
        self.calls.append((list(subreddits or []), run_id))
        if self.boom:
            raise RuntimeError("the scraper exploded")
        written = 0
        for sub in subreddits or []:
            for n in range(self.leads_per_subreddit):
                reddit_id = f"t3_{sub}_{n}"
                if session.query(Lead).filter(Lead.reddit_id == reddit_id).first():
                    continue
                session.add(
                    Lead(
                        reddit_id=reddit_id,
                        subreddit=sub,
                        author="tester",
                        title=f"lead {n} in {sub}",
                        url=f"https://example.invalid/{sub}/{n}",
                        created_utc=utcnow(),
                    )
                )
                written += 1
        session.add(
            ScrapeRun(
                scraper_type="subreddit",
                posts_found=self.leads_per_subreddit * len(subreddits or []),
                leads_found=written,
                run_id=run_id,
            )
        )
        session.commit()
        return written


@pytest.fixture
def fake_scraper(monkeypatch):
    scraper = FakeScraper()
    monkeypatch.setattr(scrape_handler, "build_scraper", lambda config: scraper)
    monkeypatch.setattr(scrape_handler, "load_config", lambda: {})
    return scraper


@pytest.fixture
def session(temp_db):
    with Session(bind=database.ENGINE, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def worker(temp_db):
    return Worker(JobQueue(database.ENGINE), REGISTRY, poll_interval=0.0)


def _start_run(session, subreddits=("saas", "startups")):
    service = RunService(session, JobQueue(database.ENGINE))
    run = service.create(None, RunOptions(subreddits=tuple(subreddits)))
    session.commit()
    return run


def _drain(worker, session=None, limit=20):
    """Run the worker until the queue is empty. Bounded, so a bug cannot hang.

    The worker commits on its own sessions, so this session's identity map still
    holds the rows as they were before. Expiring it models what actually happens
    next in production -- a new request, on a new session, reading the worker's
    committed result. Without it, a passing assertion here would only prove the
    test remembered what it wrote.
    """
    for executed in range(limit):
        if not worker.tick():
            if session is not None:
                session.expire_all()
            return executed
    raise AssertionError(f"queue did not drain within {limit} jobs")


# ------------------------------------------------------------------ registry


def test_registry_holds_exactly_the_three_p3_job_types():
    """A fourth entry here means a phase boundary was crossed."""
    assert set(REGISTRY) == {"maintenance", "scrape_subreddit", "finalize_run"}


# ------------------------------------------------------------ end-to-end run


def test_a_run_scrapes_every_subreddit_and_completes(session, worker, fake_scraper):
    """AC1, end to end through the real worker."""
    run = _start_run(session, ("saas", "startups", "entrepreneur"))

    _drain(worker, session)

    session.refresh(run)
    assert run.state == RunState.COMPLETE.value
    assert [call[0] for call in fake_scraper.calls] == [["saas"], ["startups"], ["entrepreneur"]]
    assert session.query(Lead).count() == 3


def test_each_job_scrapes_exactly_one_subreddit(session, worker, fake_scraper):
    """The whole point of per-subreddit jobs: no job may scrape the whole list."""
    _start_run(session, ("saas", "startups"))
    _drain(worker, session)

    for subreddits, _run_id in fake_scraper.calls:
        assert len(subreddits) == 1


def test_the_scrape_run_audit_row_links_back_to_the_run(session, worker, fake_scraper):
    """`scrape_runs.run_id` has existed since 0004 and been NULL on every row."""
    run = _start_run(session, ("saas",))
    _drain(worker, session)

    rows = session.query(ScrapeRun).all()
    assert rows and all(r.run_id == run.id for r in rows)


def test_finalize_is_queued_only_once_and_only_at_the_end(session, worker, fake_scraper):
    run = _start_run(session, ("saas", "startups", "entrepreneur"))

    worker.tick()  # first subreddit
    assert _finalizers(session, run.id) == 0
    worker.tick()  # second
    assert _finalizers(session, run.id) == 0
    worker.tick()  # third -- now it is the last one standing
    assert _finalizers(session, run.id) == 1

    _drain(worker, session)
    assert _finalizers(session, run.id) == 1


def test_run_completes_with_no_subreddits_configured(session, worker, fake_scraper):
    """The empty case must terminate, or every later run is refused with 409."""
    run = _start_run(session, ())
    _drain(worker, session)

    session.refresh(run)
    assert run.state == RunState.COMPLETE.value
    assert fake_scraper.calls == []


# ------------------------------------------------------------- lead counting


def test_progress_reports_the_leads_actually_written(session, worker, fake_scraper):
    fake_scraper.leads_per_subreddit = 4
    run = _start_run(session, ("saas", "startups"))
    _drain(worker, session)

    service = RunService(session, JobQueue(database.ENGINE))
    assert service.progress(run.id).leads_found == 8
    assert session.query(Lead).count() == 8


# --------------------------------------------------------------- idempotence


def test_re_running_a_scrape_job_writes_no_duplicate_leads(session, worker, fake_scraper):
    """AC5, R9, G2. A lease expires mid-scrape and the job runs again by design."""
    run = _start_run(session, ("saas",))
    job = session.query(Job).filter(Job.run_id == run.id).one()

    handler = REGISTRY["scrape_subreddit"]
    handler(session, job)
    session.commit()
    first = session.query(Lead).count()

    handler(session, job)
    session.commit()

    assert session.query(Lead).count() == first


def test_finalising_an_already_complete_run_is_a_no_op(session, worker, fake_scraper):
    """G2 spells this out: finalize_run does not get idempotence for free."""
    run = _start_run(session, ("saas",))
    _drain(worker, session)
    session.refresh(run)
    assert run.state == RunState.COMPLETE.value

    finaliser = session.query(Job).filter(Job.job_type == "finalize_run").one()
    result = REGISTRY["finalize_run"](session, finaliser)

    assert result["skipped"] == RunState.COMPLETE.value
    session.refresh(run)
    assert run.state == RunState.COMPLETE.value


def test_lease_expiry_reclaims_and_re_runs_without_duplicating(session, worker, fake_scraper):
    """The full AC5 path: a real expiry, a real reclaim, a real second execution."""
    _start_run(session, ("saas",))
    queue = JobQueue(database.ENGINE)

    claimed = queue.claim("worker-a", lease_seconds=900)
    assert claimed is not None
    REGISTRY["scrape_subreddit"](session, claimed)
    session.commit()
    before = session.query(Lead).count()

    # The lease lapses while the handler was still notionally working.
    with Session(bind=database.ENGINE) as s:
        job = s.get(Job, claimed.id)
        job.lease_expires_at = utcnow().replace(year=2000)
        s.commit()

    assert queue.reclaim_expired() == 1
    _drain(worker, session)

    assert session.query(Lead).count() == before


# -------------------------------------------------------------- kill / resume


def test_a_killed_worker_leaves_the_run_resumable(session, fake_scraper):
    """AC3: kill the process mid-run, restart, the remaining jobs finish.

    A killed process is modelled by abandoning the worker while it holds a claim
    -- which is exactly what the database sees. The row stays `running` with a
    lease nobody will renew, and recovery is a *new* worker reclaiming it. No
    state is carried over in memory, because after a kill there is none.
    """
    run = _start_run(session, ("a", "b", "c"))

    first = Worker(JobQueue(database.ENGINE), REGISTRY, poll_interval=0.0)
    first.tick()  # one subreddit done
    claimed = JobQueue(database.ENGINE).claim(first.worker_id, lease_seconds=900)
    assert claimed is not None  # a second job is now held by the "dead" worker
    del first

    # The lease outlives the process, so recovery waits for it to lapse.
    with Session(bind=database.ENGINE) as s:
        s.get(Job, claimed.id).lease_expires_at = utcnow().replace(year=2000)
        s.commit()

    second = Worker(JobQueue(database.ENGINE), REGISTRY, poll_interval=0.0)
    _drain(second, session)

    session.refresh(run)
    assert run.state == RunState.COMPLETE.value
    assert session.query(Lead).count() == 3


@pytest.mark.parametrize("iteration", range(10))
def test_resume_after_a_kill_succeeds_every_time(session, fake_scraper, iteration):
    """docs/34 §P3 Metrics: "resume success 10/10 kill tests".

    Parameterised rather than looped so a failure names which iteration broke,
    and so one flake cannot be hidden by a retry inside the test.
    """
    run = _start_run(session, ("a", "b"))

    dying = Worker(JobQueue(database.ENGINE), REGISTRY, poll_interval=0.0)
    claimed = JobQueue(database.ENGINE).claim(dying.worker_id, lease_seconds=900)
    assert claimed is not None
    with Session(bind=database.ENGINE) as s:
        s.get(Job, claimed.id).lease_expires_at = utcnow().replace(year=2000)
        s.commit()
    del dying

    _drain(Worker(JobQueue(database.ENGINE), REGISTRY, poll_interval=0.0), session)

    session.refresh(run)
    assert run.state == RunState.COMPLETE.value, f"iteration {iteration} did not resume"


# -------------------------------------------------------------- cancellation


def test_a_cancelled_run_skips_the_job_already_claimed(session, worker, fake_scraper):
    """AC6/T4: cancellation cannot stop a running handler, so it stops the next unit."""
    run = _start_run(session, ("saas", "startups"))
    service = RunService(session, JobQueue(database.ENGINE))
    service.cancel(run.id)
    session.commit()

    job = session.query(Job).filter(Job.run_id == run.id).first()
    job.state = JobState.QUEUED.value
    job.available_at = utcnow()
    session.commit()

    result = REGISTRY["scrape_subreddit"](session, job)
    assert result["skipped"] == "cancelled"
    assert fake_scraper.calls == []


def test_the_skip_is_visible_on_the_timeline(session, worker, fake_scraper):
    """A silent skip looks identical to a subreddit with no new posts."""
    run = _start_run(session, ("saas",))
    service = RunService(session, JobQueue(database.ENGINE))
    service.cancel(run.id)
    session.commit()

    job = session.query(Job).filter(Job.run_id == run.id).one()
    job.state = JobState.QUEUED.value
    session.commit()
    REGISTRY["scrape_subreddit"](session, job)
    session.commit()

    events = session.query(RunEvent).filter(RunEvent.event == "scrape.subreddit.skipped").all()
    assert events and events[0].level == "warning"


# ------------------------------------------------------------ partial results


def test_one_failed_subreddit_does_not_fail_the_run(session, worker, fake_scraper):
    """AD-9: scrape_subreddit is non-fatal. Eleven good subreddits are not discarded."""
    run = _start_run(session, ("saas", "startups"))
    jobs = session.query(Job).filter(Job.run_id == run.id).order_by(Job.id).all()
    jobs[0].state = JobState.FAILED.value
    jobs[0].finished_at = utcnow()
    session.commit()

    _drain(worker, session)

    session.refresh(run)
    assert run.state == RunState.COMPLETE.value


def test_a_partial_run_says_so_on_the_timeline(session, worker, fake_scraper):
    """Completing quietly after a failure is a result the operator cannot trust."""
    run = _start_run(session, ("saas", "startups"))
    jobs = session.query(Job).filter(Job.run_id == run.id).order_by(Job.id).all()
    jobs[0].state = JobState.FAILED.value
    session.commit()

    _drain(worker, session)

    partial = session.query(RunEvent).filter(RunEvent.event == "run.partial").all()
    assert partial and partial[0].level == "warning"


def test_a_handler_exception_fails_the_job_and_rolls_back_its_writes(session, worker, monkeypatch):
    """G3: the queue records the failure even though the handler's work is gone."""
    broken = FakeScraper(boom=True)
    monkeypatch.setattr(scrape_handler, "build_scraper", lambda config: broken)
    monkeypatch.setattr(scrape_handler, "load_config", lambda: {})

    run = _start_run(session, ("saas",))
    worker.tick()

    with Session(bind=database.ENGINE) as fresh:
        job = fresh.query(Job).filter(Job.run_id == run.id).one()
        assert job.state == JobState.FAILED.value
        assert "exploded" in job.error


# ---------------------------------------------------------------- validation


def test_a_scrape_job_without_a_run_is_rejected(session, temp_db):
    queue = JobQueue(database.ENGINE)
    job = queue.enqueue("scrape_subreddit", run_id=None, payload={"subreddit": "saas"})

    with pytest.raises(ValueError, match="run_id"):
        REGISTRY["scrape_subreddit"](session, job)


def test_a_scrape_job_without_a_subreddit_is_rejected(session, temp_db):
    run = _start_run(session, ())
    queue = JobQueue(database.ENGINE)
    job = queue.enqueue("scrape_subreddit", run_id=run.id, payload={})

    with pytest.raises(ValueError, match="subreddit"):
        REGISTRY["scrape_subreddit"](session, job)


def test_config_failure_does_not_fail_the_job(monkeypatch):
    """The subreddit comes from the payload; a missing config.yaml is survivable."""
    import src.config

    monkeypatch.setattr(src.config, "load_config", _raise)
    assert scrape_handler.load_config() == {}


def _raise(*_args, **_kwargs):
    raise OSError("config.yaml is missing")


def _finalizers(session, run_id: int) -> int:
    session.expire_all()
    return session.query(Job).filter(Job.run_id == run_id, Job.job_type == "finalize_run").count()


def test_run_result_records_what_the_job_did(session, worker, fake_scraper):
    """jobs.result_json is how 'did last night's run work?' stays a query."""
    _start_run(session, ("saas",))
    _drain(worker, session)

    finaliser = session.query(Job).filter(Job.job_type == "finalize_run").one()
    result = json.loads(finaliser.result_json)
    assert result["leads_found"] == 1
    assert result["subreddits_done"] == 1
