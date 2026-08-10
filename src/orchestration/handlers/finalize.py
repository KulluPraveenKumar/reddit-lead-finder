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
        # job was re-claimed, when the operator cancelled while this was queued,
        # or -- since P7's D7 -- when `RunService.fail()` enqueued this job so the
        # failure would be notified. Neither is a failure.
        #
        # It still **drains**: the run is over, and this is the only handler that
        # will run for it. The state is already committed by whoever set it, so the
        # session is clean and `dispatch_pending` may send.
        log.info("run %s is already %s; nothing to finalise", run_id, run.state)
        sent = _notify(session, run_id)
        return {"run_id": run_id, "skipped": run.state, "notified": sent}

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

    # ⚠️ COMMIT BEFORE THE SEND. Everything above -- both transitions and the
    # `run.partial` event -- is pending in this session, and SQLite has one write
    # lock which a pending write holds until commit. A notification sent from here
    # with the session dirty would hold that lock across a network call to
    # Telegram, locking out every other writer for its duration.
    #
    # That is trap T0, which `PHASE-06-HANDOVER` §5 names as *"the write lock,
    # again, and P7 is where it returns"* -- P3 lost a sign-off to it, and P4, P5
    # and P6 each had to prove they had not re-opened it. `handlers/__init__.py`
    # states the rule: a handler about to block on I/O commits its bookkeeping
    # first. `handle_discover` already ships on it.
    #
    # `dispatch_pending` refuses a dirty session rather than trusting this comment.
    session.commit()

    return {
        "run_id": run_id,
        "leads_found": leads,
        "subreddits_done": int(stats.get("subreddits_done", 0) or 0),
        "subreddits_failed": failed,
        "subreddits_cancelled": cancelled,
        "notified": _notify(session, run_id),
    }


def _notify(session: Session, run_id: int) -> list[str]:
    """Dispatch whatever this run has earned. Never fatal to the run.

    Wrapped because a notification is telemetry: AD-9 is *"fail soft on
    enrichment, loud on collection"*, and a run that collected leads must not be
    reported as failed because Telegram was unreachable. The tier records its own
    failures on the timeline (`notify.failed`), so nothing is silent -- the same
    shape P4 used for its degradation notices.

    Returns the kinds sent, so `jobs.result_json` carries the evidence.
    """
    from src.notify import NotificationService, NotifySettings

    try:
        settings = NotifySettings.from_config(_notify_config())
        sent = NotificationService(session, settings=settings).dispatch_pending(run_id)
        return [s.kind.value for s in sent]
    except Exception:  # noqa: BLE001 - telemetry must not fail a finished run
        log.exception("notification dispatch failed for run %s", run_id)
        return []


def _notify_config() -> dict[str, Any]:
    """The ``notify:`` block, or ``{}``.

    Read here rather than injected so `finalize_run` keeps its two-argument
    handler signature. An unreadable config yields the defaults, which are off --
    a config problem must not turn into a failed run.
    """
    try:
        from src.config import load_config

        return (load_config() or {}).get("notify", {}) or {}
    except Exception:  # noqa: BLE001
        log.warning("could not read the notify config; notifications stay off")
        return {}


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
