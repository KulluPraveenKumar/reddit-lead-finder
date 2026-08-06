"""Retention purges. Four deletes, one conditional ``VACUUM``.

``docs/13`` §9.5 and ``docs/05`` §13. Without this, ``http_cache`` alone grows
without bound and eventually dominates the database file — it is written on
every fetch and read by nothing once expired.

**``ai_cache`` is deliberately absent from this list.** It is the cost saving
(AD-14, R14): an unchanged prompt about unchanged text has an unchanged answer,
so expiring a row costs money to rebuild and changes no result. Its growth is
bounded by distinct prompt/content pairs, not by time. Purging it belongs to a
prompt-version retirement, which is P25's, not to a nightly job.

The handler is idempotent because deletion is: running it twice deletes the same
rows once. That matters — R9 requires it, and a lease can expire mid-purge.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.db.models import HttpCache, Job, Metric, Run, RunEvent
from src.orchestration.job_queue import payload_of, utcnow

log = logging.getLogger(__name__)

#: Retention windows, in days. Each is the point past which the row answers no
#: question anybody asks.
DONE_JOBS_DAYS = 30
RUN_EVENTS_DAYS = 90
METRICS_DAYS = 14

#: Free pages that must accumulate before a ``VACUUM`` is worth its cost.
#: VACUUM rewrites the whole file and takes an exclusive lock, so running it for
#: a handful of pages would trade a real outage for an imaginary saving. At the
#: 4 KiB default page size this is roughly 8 MB of reclaimable space.
VACUUM_FREELIST_PAGES = 2000


def handle_maintenance(session: Session, job: Job) -> dict[str, Any]:
    """Purge expired rows and report what went.

    Returns the per-table counts rather than logging and discarding them: they
    land in ``jobs.result_json``, which is what makes "did retention actually run
    last night?" a query instead of a log hunt.

    ``job``'s payload accepts ``{"vacuum": false}`` to skip the compaction step —
    the switch exists because VACUUM is the only part of this handler that takes
    an exclusive lock, and an operator debugging contention needs a way to turn
    it off without editing code.
    """
    now = utcnow()

    deleted = {
        "jobs": _purge_done_jobs(session, now),
        "run_events": _purge_run_events(session, now),
        "http_cache": _purge_http_cache(session, now),
        "metrics": _purge_metrics(session, now),
    }

    report: dict[str, Any] = {"deleted": deleted, "total": sum(deleted.values())}
    log.info("maintenance purged %d rows", report["total"])

    report["vacuumed"] = _maybe_vacuum(session) if payload_of(job).get("vacuum", True) else False
    return report


def _purge_done_jobs(session: Session, now: datetime) -> int:
    """Completed jobs older than 30 days. Failed ones stay: they are evidence."""
    cutoff = now - timedelta(days=DONE_JOBS_DAYS)
    return (
        session.query(Job)
        .filter(Job.state == "done", Job.finished_at.isnot(None), Job.finished_at < cutoff)
        .delete(synchronize_session=False)
    )


def _purge_run_events(session: Session, now: datetime) -> int:
    """Events belonging to runs that finished more than 90 days ago.

    Scoped by the *run's* finish time, not the event's: a timeline is only
    readable whole, and half a feed is worse than none.
    """
    cutoff = now - timedelta(days=RUN_EVENTS_DAYS)
    stale = session.query(Run.id).filter(Run.finished_at.isnot(None), Run.finished_at < cutoff)
    return (
        session.query(RunEvent)
        .filter(RunEvent.run_id.in_(stale.scalar_subquery()))
        .delete(synchronize_session=False)
    )


def _purge_http_cache(session: Session, now: datetime) -> int:
    """Expired HTTP cache rows. Purely an accelerator — safe to delete."""
    return (
        session.query(HttpCache)
        .filter(HttpCache.expires_at.isnot(None), HttpCache.expires_at < now)
        .delete(synchronize_session=False)
    )


def _purge_metrics(session: Session, now: datetime) -> int:
    """Counter samples older than 14 days."""
    cutoff = now - timedelta(days=METRICS_DAYS)
    return (
        session.query(Metric).filter(Metric.recorded_at < cutoff).delete(synchronize_session=False)
    )


def _maybe_vacuum(session: Session) -> bool:
    """``VACUUM`` only when enough pages are actually free.

    **This is the one place a handler commits**, and it is unavoidable rather
    than careless: SQLite refuses to VACUUM inside a transaction, and the deletes
    above are exactly what created the free pages being counted. Committing here
    is safe because the purges are the handler's entire body — there is no later
    work whose rollback this could strand.
    """
    session.commit()
    engine = session.get_bind()
    with engine.connect() as conn:
        free = conn.execute(text("PRAGMA freelist_count")).scalar() or 0
        if free < VACUUM_FREELIST_PAGES:
            log.debug("skipping vacuum: %d free pages", free)
            return False
        conn.exec_driver_sql("VACUUM")
        log.info("vacuumed, %d free pages reclaimed", free)
    return True
