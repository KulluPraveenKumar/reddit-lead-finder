"""The durable job queue: claim-with-lease over the ``jobs`` table.

**Why a table and not Celery/RQ/Redis.** One operator, one machine, one SQLite
file (``ARCHITECTURE_FREEZE`` §5). A queue that lives in the same file as the
data it operates on gets crash-consistency, backup and inspection for free, and
costs one index.

Three properties are load-bearing, and each is asserted in
``tests/test_job_queue.py``:

1. **The claim is atomic under N workers.** ``BEGIN IMMEDIATE`` takes the write
   lock *before* the SELECT, and the UPDATE carries ``AND state='queued'``.
   Either one alone loses the race (``docs/PHASE-01-HANDOVER.md`` T1): without
   the immediate lock two workers can both read the same row; without the guard
   two workers can both write it.
2. **``attempts`` is incremented at claim time, not at failure time.** A worker
   that dies mid-job has still consumed an attempt, which is what stops a job
   that reliably kills its worker from being retried forever.
3. **Backoff grows and is jittered.** Fixed backoff synchronises every failing
   job onto the same retry instant, which is how a transient upstream outage
   turns into a self-inflicted thundering herd.

Specification: ``docs/04-system-design.md`` §2, ``docs/13-phase-03.md`` §9.1.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import Job
from src.obs.logging import redact
from src.orchestration.states import JobState, assert_job_transition

log = logging.getLogger(__name__)

#: Attempts allowed per job type, before the job is failed for good.
#: ``docs/04`` §2.3. Scraping gets more because its failures are usually a
#: transient block; anything that costs money gets fewer.
MAX_ATTEMPTS: dict[str, int] = {
    "analyze_website": 3,
    "discover_subreddits": 3,
    "generate_keywords": 3,
    "scrape_subreddit": 5,
    "scrape_comments": 5,
    "enrich_leads": 3,
    "finalize_run": 3,
    "maintenance": 2,
}

#: Applied to a job type not in the table. Three is the conservative choice: an
#: unknown type is more likely a typo than a workload we have reasoned about.
DEFAULT_MAX_ATTEMPTS = 3

#: Ten minutes. Past this the delay stops being a backoff and starts being an
#: outage nobody was told about.
BACKOFF_CAP_SECONDS = 600.0

#: SQLAlchemy stores ``DateTime`` in SQLite as this exact string. The claim query
#: is raw SQL, so it must produce byte-identical text or the ``<=`` comparison
#: silently compares different formats and claims nothing — or everything.
_SQLITE_DATETIME = "%Y-%m-%d %H:%M:%S.%f"


def utcnow() -> datetime:
    """Naive UTC, matching ``models._utcnow``.

    The whole schema stores naive UTC. Mixing an aware datetime into a
    comparison against these columns is the kind of bug that produces a queue
    which claims nothing and reports no error.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def backoff_seconds(attempts: int) -> float:
    """Jittered exponential backoff, capped. ``docs/04`` §2.3.

    The jitter band is ±20%, which is deliberately narrow enough that successive
    delays never overlap (12 < 16 < 24 < 32): "the backoff grew" stays a testable
    claim rather than a probabilistic one.
    """
    base = min(BACKOFF_CAP_SECONDS, (2**attempts) * 5)
    return min(BACKOFF_CAP_SECONDS, base * random.uniform(0.8, 1.2))


class RetryableError(Exception):
    """A failure the same job might survive on a later attempt.

    Handlers raise this for a timeout, a 429 or a transient block. Anything else
    that escapes a handler is treated as non-retryable, because a bug does not
    become correct by being run again.
    """


class JobQueue:
    """Enqueue, claim, heartbeat, complete, fail, reclaim.

    Holds an ``Engine``, not a ``Session``: the claim needs a raw connection to
    issue ``BEGIN IMMEDIATE``, and every other operation is a short transaction
    of its own. Queue writes are deliberately *not* part of a handler's
    transaction — a job must be marked failed even when the handler's work is
    rolled back.
    """

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        if database.ENGINE is None:
            database.init_db()
        assert database.ENGINE is not None
        return database.ENGINE

    # -- write path ---------------------------------------------------------

    def enqueue(
        self,
        job_type: str,
        *,
        run_id: int | None = None,
        payload: dict[str, Any] | None = None,
        priority: int = 100,
        available_at: datetime | None = None,
        max_attempts: int | None = None,
        session: Session | None = None,
    ) -> Job:
        """Add a job. Pass ``session`` to enlist in the caller's transaction.

        A handler that enqueues its successor must pass its own session, so that
        "this stage finished" and "the next stage is queued" commit together —
        the atomicity ``docs/13`` §3 exists to protect.
        """
        job = Job(
            run_id=run_id,
            job_type=job_type,
            payload_json=json.dumps(payload or {}, default=str),
            state=JobState.QUEUED.value,
            priority=priority,
            attempts=0,
            max_attempts=max_attempts or MAX_ATTEMPTS.get(job_type, DEFAULT_MAX_ATTEMPTS),
            available_at=available_at or utcnow(),
            created_at=utcnow(),
        )
        if session is not None:
            session.add(job)
            session.flush()
        else:
            with self._session() as own:
                own.add(job)
                own.flush()
                own.expunge(job)
        log.debug("job enqueued", extra={"run_id": run_id, "job_id": job.id})
        return job

    def claim(self, worker_id: str, lease_seconds: int = 900) -> Job | None:
        """Take the next due job, or ``None``. Safe for any number of workers.

        Returns a **detached** ``Job``: the caller gets a snapshot to hand to a
        handler, not a live row it might accidentally mutate behind the queue's
        back.
        """
        now = utcnow()
        expires = now + timedelta(seconds=lease_seconds)

        with self._immediate() as cursor:
            row = cursor.execute(
                "SELECT id FROM jobs "
                " WHERE state = 'queued' AND available_at <= ? "
                " ORDER BY priority ASC, id ASC LIMIT 1",
                (_sqlite_dt(now),),
            ).fetchone()
            if row is None:
                return None
            job_id = int(row[0])
            if self._claim_update(cursor, job_id, worker_id, now, expires) == 0:
                return None  # lost the race; the next tick tries again

        job = self.get(job_id)
        if job is not None:
            log.info(
                "job claimed",
                extra={"run_id": job.run_id, "job_id": job.id, "stage": job.job_type},
            )
        return job

    @staticmethod
    def _claim_update(
        cursor: Any, job_id: int, worker_id: str, now: datetime, expires: datetime
    ) -> int:
        """The claiming UPDATE. Returns rows changed — 0 means the race was lost.

        A named method rather than an inline string so the ``AND state='queued'``
        guard can be tested on its own. It has to be: ``BEGIN IMMEDIATE`` already
        serialises the two workers in the race test, so removing this guard
        breaks nothing *there* — which would leave the project's stated
        "either alone loses the race" belief untested in both directions.
        The guard earns its place as the backstop for any future caller that
        claims outside an immediate transaction.
        """
        return cursor.execute(
            "UPDATE jobs "
            "   SET state = 'running', worker_id = ?, started_at = ?, "
            "       lease_expires_at = ?, attempts = attempts + 1 "
            " WHERE id = ? AND state = 'queued'",
            (worker_id, _sqlite_dt(now), _sqlite_dt(expires), job_id),
        ).rowcount

    def heartbeat(self, job_id: int, extend_seconds: int = 900) -> None:
        """Push the lease out. Called from the worker's heartbeat thread.

        Only extends a job still ``running``: a heartbeat that resurrected the
        lease on a job the queue had already reclaimed would give two workers a
        claim on it.
        """
        with self._session() as session:
            session.query(Job).filter(Job.id == job_id, Job.state == JobState.RUNNING.value).update(
                {Job.lease_expires_at: utcnow() + timedelta(seconds=extend_seconds)},
                synchronize_session=False,
            )

    def complete(self, job_id: int, result: dict[str, Any] | None = None) -> None:
        """Mark a job done. A no-op if it already reached a terminal state.

        The tolerated case is real, not theoretical: a job whose lease expired
        while its handler was still working is reclaimed — possibly all the way
        to ``failed`` — and the original worker then finishes and reports
        success. Raising here would kill that worker over a race the design
        already handles by requiring idempotent handlers.
        """
        with self._session() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            if job.state in _TERMINAL_JOB_STATES:
                log.warning(
                    "completed job was already %s",
                    job.state,
                    extra={"run_id": job.run_id, "job_id": job.id, "stage": job.job_type},
                )
                return
            assert_job_transition(job.state, JobState.DONE)
            job.state = JobState.DONE.value
            job.result_json = json.dumps(result or {}, default=str)
            job.finished_at = utcnow()
            job.lease_expires_at = None
            job.error = None
            log.info(
                "job done", extra={"run_id": job.run_id, "job_id": job.id, "stage": job.job_type}
            )

    def fail(self, job_id: int, error: str, *, retryable: bool = True) -> None:
        """Requeue with backoff, or fail for good once the attempts are spent.

        Idempotent in the direction that matters: calling this on a job already
        in a terminal state does nothing rather than raising. A queue that threw
        while recording a failure would turn one bad job into a dead worker.
        """
        with self._session() as session:
            job = session.get(Job, job_id)
            if job is None or job.state in _TERMINAL_JOB_STATES:
                return

            job.error = redact(error)[:4000]
            job.worker_id = None
            job.lease_expires_at = None

            if retryable and job.attempts < job.max_attempts:
                delay = backoff_seconds(job.attempts)
                assert_job_transition(job.state, JobState.QUEUED)
                job.state = JobState.QUEUED.value
                job.available_at = utcnow() + timedelta(seconds=delay)
                log.warning(
                    "job retrying in %.1fs (attempt %d of %d)",
                    delay,
                    job.attempts,
                    job.max_attempts,
                    extra={"run_id": job.run_id, "job_id": job.id, "stage": job.job_type},
                )
            else:
                assert_job_transition(job.state, JobState.FAILED)
                job.state = JobState.FAILED.value
                job.finished_at = utcnow()
                log.error(
                    "job failed after %d attempts",
                    job.attempts,
                    extra={"run_id": job.run_id, "job_id": job.id, "stage": job.job_type},
                )

    def reclaim_expired(self) -> int:
        """Return jobs whose lease has passed. Called every worker tick.

        A reclaimed job goes back to ``queued`` **only while it has attempts
        left**; otherwise it is failed here. Without that branch a job that kills
        its worker every time would be reclaimed forever, and ``max_attempts``
        would bound only the failures the worker survived long enough to report.
        """
        now = utcnow()
        with self._session() as session:
            expired = (
                session.query(Job)
                .filter(
                    Job.state == JobState.RUNNING.value,
                    Job.lease_expires_at.isnot(None),
                    Job.lease_expires_at < now,
                )
                .all()
            )
            for job in expired:
                job.worker_id = None
                job.lease_expires_at = None
                if job.attempts < job.max_attempts:
                    assert_job_transition(job.state, JobState.QUEUED)
                    job.state = JobState.QUEUED.value
                    job.available_at = now
                else:
                    assert_job_transition(job.state, JobState.FAILED)
                    job.state = JobState.FAILED.value
                    job.finished_at = now
                    job.error = "lease expired with no attempts remaining"
                log.warning(
                    "job lease expired, now %s",
                    job.state,
                    extra={"run_id": job.run_id, "job_id": job.id, "stage": job.job_type},
                )
            return len(expired)

    def requeue(self, job_id: int) -> Job | None:
        """Force one failed job back into the queue. The operator's override.

        Lives here rather than in the route because nothing outside this class
        writes a job's state (``PHASE-02-HANDOVER`` G4) — a route setting
        ``job.state = 'queued'`` would skip ``assert_job_transition`` and could
        resurrect a job that is currently running.

        ``FAILED -> QUEUED`` is the only legal source, so no state check is
        needed here: anything else raises and the API answers 409.

        A job that exhausted its attempts is granted exactly one more. An
        operator pressing retry is information the automatic budget did not have
        — usually "I fixed the thing that was breaking it" — and requeueing
        without it would fail the job again on the next claim, which looks like
        the button not working.
        """
        with self._session() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None

            assert_job_transition(job.state, JobState.QUEUED)
            job.state = JobState.QUEUED.value
            job.available_at = utcnow()
            job.worker_id = None
            job.lease_expires_at = None
            job.finished_at = None
            job.error = None
            if job.attempts >= job.max_attempts:
                job.max_attempts = job.attempts + 1

            log.info(
                "job requeued by operator",
                extra={"run_id": job.run_id, "job_id": job.id, "stage": job.job_type},
            )
            session.flush()
            session.expunge(job)
            return job

    def cancel_queued(self, run_id: int) -> int:
        """Cancel every queued job of a run. Running jobs are left alone."""
        with self._session() as session:
            return (
                session.query(Job)
                .filter(Job.run_id == run_id, Job.state == JobState.QUEUED.value)
                .update({Job.state: JobState.CANCELLED.value}, synchronize_session=False)
            )

    # -- read path ----------------------------------------------------------

    def get(self, job_id: int) -> Job | None:
        """A detached snapshot of one job."""
        with self._session() as session:
            job = session.get(Job, job_id)
            if job is not None:
                session.expunge(job)
            return job

    # -- plumbing -----------------------------------------------------------

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """Short transaction bound to this queue's engine.

        Short on purpose: K13 is SQLite writer contention, and the mitigation is
        holding the write lock for as little time as possible.
        """
        session = Session(bind=self.engine, expire_on_commit=False)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def _immediate(self) -> Iterator[Any]:
        """A transaction that takes the write lock **before** the first read.

        ``Engine.begin()`` is not enough: pysqlite emits a *deferred* ``BEGIN``,
        which upgrades to a write lock only at the first write — leaving a window
        in which two workers have both read the same job id. The lock has to be
        taken up front, and the driver's own ``BEGIN`` suppressed, so this uses a
        raw connection and says ``BEGIN IMMEDIATE`` itself.
        """
        raw = self.engine.raw_connection()
        cursor = raw.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            yield cursor
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            cursor.close()
            raw.close()


def payload_of(job: Job) -> dict[str, Any]:
    """A job's payload as a dict. Malformed JSON is an empty payload.

    A handler crashing on ``json.loads`` would be indistinguishable from the work
    itself failing, and the payload is written by this module — so a parse error
    is this module's bug, and the handler should not pay for it.
    """
    try:
        loaded = json.loads(job.payload_json or "{}")
    except (TypeError, ValueError):
        log.warning("job payload is not JSON", extra={"job_id": job.id})
        return {}
    return loaded if isinstance(loaded, dict) else {}


_TERMINAL_JOB_STATES = frozenset(
    {JobState.DONE.value, JobState.FAILED.value, JobState.CANCELLED.value}
)


def _sqlite_dt(value: datetime) -> str:
    return value.strftime(_SQLITE_DATETIME)
