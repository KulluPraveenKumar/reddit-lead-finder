"""``finalize_run`` — the job that closes a run.

It exists so that "the run is over" is a decision made in one place, by the
worker, in a transaction — rather than inferred by whoever happens to poll the
progress endpoint next.

**Idempotence is not free here** (``PHASE-02-HANDOVER`` G2). Scraping gets it
from ``reddit_id`` dedup; finalising has to be written for it, because the second
run of this handler would otherwise attempt ``COMPLETE -> ANALYZING -> COMPLETE``
and raise on a run that is already finished correctly. A lease expiring during
the last second of a run is not a failure and must not be reported as one, so a
run that is already terminal is a no-op that says so.

**A failed subreddit does not fail the run.** ``scrape_subreddit`` is non-fatal
(``docs/04`` §2.4, AD-9): partial collection is useful, and eleven subreddits
that worked are not discarded because the twelfth was blocked. The run completes
and the timeline records the shortfall, which is the difference between a result
the operator can trust and a result they have to interpret.

Specification: ``docs/13-phase-03.md`` §9.2, ``docs/04-system-design.md`` §2.4.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Job
from src.obs.events import emit_event
from src.orchestration.job_queue import JobQueue
from src.orchestration.run_service import SCRAPE_JOB, RunService
from src.orchestration.states import JobState, RunState, is_terminal

log = logging.getLogger(__name__)


def handle_finalize_run(session: Session, job: Job) -> dict[str, Any]:
    """Close the run: ``SCRAPING -> ANALYZING -> COMPLETE``.

    ``ANALYZING`` is passed through rather than paused at. P3 has no analysis
    stage — that is P19/P20 — and the transition table has no ``SCRAPING ->
    COMPLETE`` edge, so the state is traversed and the timeline says plainly that
    nothing was analysed. Inventing an edge to avoid a state we do not use yet
    would be an architecture amendment bought with a convenience.
    """
    run_id = job.run_id
    if run_id is None:
        raise ValueError(f"job {job.id} has no run_id; finalize_run must belong to a run")

    service = RunService(session, JobQueue(session.get_bind()))
    run = service.get(run_id)

    if is_terminal(run.state):
        # The idempotent path. Reached when a lease expired near the end and the
        # job was re-claimed, or when the operator cancelled while this was
        # queued. Neither is a failure.
        log.info("run %s is already %s; nothing to finalise", run_id, run.state)
        return {"run_id": run_id, "skipped": run.state}

    counts = _scrape_outcomes(session, run_id)
    stats = service.stats(run_id)
    leads = int(stats.get("leads_found", 0) or 0)
    failed = counts.get(JobState.FAILED.value, 0)
    cancelled = counts.get(JobState.CANCELLED.value, 0)

    if failed or cancelled:
        emit_event(
            session,
            run_id,
            "run.partial",
            level="warning",
            message=(
                f"{failed} subreddit(s) failed and {cancelled} were cancelled. "
                "The run is complete with the leads that were collected."
            ),
            subreddits_failed=failed,
            subreddits_cancelled=cancelled,
        )

    service.transition(
        run_id,
        RunState.ANALYZING,
        reason="Collection finished. No AI analysis runs at this stage.",
    )
    service.transition(
        run_id,
        RunState.COMPLETE,
        reason=f"Run complete — {leads} lead(s) collected.",
    )

    return {
        "run_id": run_id,
        "leads_found": leads,
        "subreddits_done": int(stats.get("subreddits_done", 0) or 0),
        "subreddits_failed": failed,
        "subreddits_cancelled": cancelled,
    }


def _scrape_outcomes(session: Session, run_id: int) -> dict[str, int]:
    """``{job state: count}`` across this run's scrape jobs.

    Counted in SQL rather than by loading the jobs: a run with a hundred
    subreddits should not pull a hundred rows into memory to answer "how many
    failed?".
    """
    from sqlalchemy import func

    rows = (
        session.query(Job.state, func.count(Job.id))
        .filter(Job.run_id == run_id, Job.job_type == SCRAPE_JOB)
        .group_by(Job.state)
        .all()
    )
    return {state: int(count) for state, count in rows}
