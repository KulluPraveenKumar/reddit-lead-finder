"""``scrape_subreddit`` — one subreddit, one job.

This is the handler that proves the machinery on existing code. It adds no
scraping logic: it scopes :class:`~src.scrapers.subreddit_scraper.SubredditScraper`
to a single subreddit, records what happened on the run's timeline, and queues
the finaliser once it is the last one standing.

**Why one job per subreddit and not one per run.** A single job would make the
progress bar jump from 0 to 100 (``docs/13`` AC2 asserts real counts), would give
``cancel_queued`` nothing to cancel (AC6), and would put a twelve-subreddit scrape
inside one lease. One job per subreddit gives progress a unit, cancellation a
checkpoint, and retry a granularity that does not redo work that succeeded.

**Idempotence** (R9, ``PHASE-02-HANDOVER`` G2) comes free from ``reddit_id``
dedup: ``LeadRepository.filter_new`` drops posts already stored, so a job whose
lease expired mid-scrape and was re-claimed writes no duplicate lead. That is
what makes the ordering below safe — see :func:`handle_scrape_subreddit`.

**No retry mapping, deliberately.** ``RedditClient._get`` catches every transport
failure and returns ``None``; its own docstring records that raising instead is
Phase 6 work. So a block does not reach this handler as an exception, and a
``except BlockedError: raise RetryableError`` clause here would be a branch that
cannot execute. When the transport starts raising, the mapping belongs here.

Specification: ``docs/13-phase-03.md`` §9.2, ``docs/04-system-design.md`` §2.4.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Job
from src.obs.events import emit_event
from src.orchestration.job_queue import JobQueue, payload_of
from src.orchestration.run_service import FINALIZE_JOB, SCRAPE_JOB, RunService
from src.orchestration.states import JobState

log = logging.getLogger(__name__)

#: Job states from which no further work happens. A scrape job that failed for
#: good still counts as finished for the purpose of "is this run done?" —
#: ``scrape_subreddit`` is non-fatal (``docs/04`` §2.4, AD-9), so one blocked
#: subreddit must not strand the eleven that worked.
_SETTLED = frozenset({JobState.DONE.value, JobState.FAILED.value, JobState.CANCELLED.value})


def build_scraper(config: dict[str, Any]):
    """Construct the scraper and its transport.

    A named seam rather than an inline constructor: this is the one line in the
    orchestrated path that opens a network client, so it is the line a test needs
    to replace, and the one an operator debugging transport wants to find.
    """
    from src.reddit_client import RedditClient
    from src.scrapers.subreddit_scraper import SubredditScraper

    return SubredditScraper(RedditClient(config), config)


def load_config() -> dict[str, Any]:
    """Scraper configuration, or an empty mapping if the file cannot be read.

    A missing ``config.yaml`` must not fail a job: the subreddit to scrape comes
    from the job payload, and the scoring weights fall back to their defaults.
    """
    try:
        from src.config import load_config as _load

        return _load() or {}
    except Exception as exc:  # noqa: BLE001 - a config read must not fail a job
        log.warning("could not load config, using defaults: %s", exc)
        return {}


def handle_scrape_subreddit(session: Session, job: Job) -> dict[str, Any]:
    """Scrape one subreddit, then queue the finaliser if this was the last job.

    **Ordering note.** ``SubredditScraper.run`` commits its own leads per
    subreddit, so by the time this function returns, the leads are durable while
    the stats update and the finalise enqueue are not yet. If this handler raises
    after that point, the worker rolls back only the latter and the job is
    retried — and because the scrape is idempotent, the retry writes no duplicate
    leads and re-evaluates the finalise check. The window closes itself; it does
    not need a second transaction to close it.
    """
    service = RunService(session, JobQueue(session.get_bind()))
    subreddit = str(payload_of(job).get("subreddit") or "").strip()
    run_id = job.run_id

    if run_id is None:
        raise ValueError(f"job {job.id} has no run_id; scrape jobs must belong to a run")
    if not subreddit:
        raise ValueError(f"job {job.id} has no subreddit in its payload")

    if service.cancel_requested(run_id):
        # Checked between units, never inside one. The operator asked the run to
        # stop, and the queued jobs are already cancelled -- this is the one that
        # was claimed before the request landed.
        emit_event(
            session,
            run_id,
            "scrape.subreddit.skipped",
            level="warning",
            message=f"Skipped r/{subreddit} — the run was cancelled.",
            subreddit=subreddit,
        )
        return {"subreddit": subreddit, "skipped": "cancelled"}

    service.note_subreddit_started(run_id, subreddit)
    emit_event(
        session,
        run_id,
        "scrape.subreddit.start",
        message=f"Scraping r/{subreddit}…",
        subreddit=subreddit,
    )

    # **Commit before the scrape, and never remove this.**
    #
    # The two calls above leave the session dirty. The scrape below spends
    # minutes on the network, and its first query — ``LeadScorer`` reading
    # ``settings`` — autoflushes those pending writes, which takes SQLite's
    # single write lock. Nothing releases it until the scrape commits, so every
    # other writer waits out ``busy_timeout`` and then fails: cancelling a run
    # mid-scrape returned "database is locked" as an HTTP 500 (T4).
    #
    # K13 is writer contention, and P2's mitigation is stated as short
    # transactions. A transaction that spans a network fetch is the opposite of
    # short, and no timeout value fixes it — the lock simply must not be held
    # across I/O.
    #
    # Committing here is safe for G1: the atomic unit that matters is "this
    # stage finished **and** the next one is queued", and both of those happen
    # after the scrape, in the transaction the worker commits. What is committed
    # here is progress telemetry, which is *more* correct early — it is what
    # makes "Scraping r/x" appear on the run page while the scrape is running
    # rather than after it has finished.
    session.commit()

    scraper = build_scraper(load_config())
    leads = scraper.run(session, subreddits=[subreddit], run_id=run_id)
    leads = int(leads or 0)

    service.note_subreddit_finished(run_id, leads)

    emit_event(
        session,
        run_id,
        "scrape.subreddit.done",
        message=f"r/{subreddit} done — {leads} lead(s).",
        subreddit=subreddit,
        leads=leads,
    )

    if _is_last_scrape_job(session, run_id, job.id):
        # Enqueued with this session so "the last subreddit finished" and "the
        # run will be finalised" commit together (G1). Without the shared
        # session, a rollback here would leave a run that scraped everything and
        # never closed.
        JobQueue(session.get_bind()).enqueue(
            FINALIZE_JOB, run_id=run_id, payload={}, session=session
        )

    return {"subreddit": subreddit, "leads": leads}


def _is_last_scrape_job(session: Session, run_id: int, current_job_id: int) -> bool:
    """Is every other scrape job for this run settled, and no finaliser queued?

    The current job is excluded because it is still ``running``: the queue marks
    it ``done`` in its own transaction *after* this handler returns (G3), so
    counting it would mean the finaliser is never queued at all.

    The finaliser check is not redundant under a single worker, but it is the
    guard that keeps this correct under several — two workers finishing the last
    two subreddits at once would otherwise both queue one.
    """
    unfinished = (
        session.query(Job)
        .filter(
            Job.run_id == run_id,
            Job.job_type == SCRAPE_JOB,
            Job.id != current_job_id,
            Job.state.notin_(_SETTLED),
        )
        .count()
    )
    if unfinished:
        return False

    already_queued = (
        session.query(Job).filter(Job.run_id == run_id, Job.job_type == FINALIZE_JOB).count()
    )
    return already_queued == 0
