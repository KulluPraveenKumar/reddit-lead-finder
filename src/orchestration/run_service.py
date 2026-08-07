"""``RunService`` — the only thing that moves a run between states.

The state machine in :mod:`src.orchestration.states` says which moves are legal.
This module is what actually makes them, and it exists so that "advance the run"
has one implementation rather than one per route. Every transition here goes
through :func:`~src.orchestration.states.assert_transition` and appends a
``run_events`` row in the caller's transaction, per ``docs/04`` §1.2 — a state
change the timeline does not record is a state change nobody can explain
afterwards.

Three properties are load-bearing, and each is asserted in
``tests/test_run_service.py``:

1. **A run reaches ``SCRAPING`` by walking, not by jumping.** ``TRANSITIONS``
   admits exactly one path from ``PENDING``, and it passes through both review
   gates. See :data:`SCRAPE_WALK`.
2. **One active run per project.** ``RunRepository.active_for_project`` excludes
   terminal states rather than listing active ones, so a state added later counts
   as active by default (``PHASE-02-HANDOVER`` T3).
3. **Cancellation is cooperative for the job in flight.** ``cancel()`` marks
   queued jobs cancelled and raises a flag in ``runs.stats_json``; the running
   handler checks it between units. Nothing kills a thread mid-write.

Specification: ``docs/04-system-design.md`` §1.3, ``docs/13-phase-03.md`` §9.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.db.models import Run
from src.db.repositories.runs import JobRepository, RunRepository
from src.obs.events import emit_event
from src.orchestration.job_queue import JobQueue, utcnow
from src.orchestration.states import (
    TERMINAL_STATES,
    IllegalTransition,
    JobState,
    RunState,
    assert_transition,
)

log = logging.getLogger(__name__)

#: The hops a scrape run makes from ``PENDING`` to ``SCRAPING``, with the reason
#: each one is passed through rather than paused at.
#:
#: **This walk is forced, not chosen.** ``TRANSITIONS`` admits exactly one path
#: from ``PENDING`` to ``SCRAPING``, and both review gates lie on it. A run
#: started from the dashboard has no website to profile and no candidates to
#: review — its subreddits come from the Configuration page, which is the
#: operator having already made the decision each gate exists to ask for. So the
#: gates are *satisfied*, not skipped, and each one says so on the run page.
#:
#: ``docs/13`` §2.2 reads "the states exist, but nothing enters them yet". That
#: sentence and the transition table cannot both hold; the table is the
#: specification (``docs/04`` §1.2) and P1 transcribed it. Recorded as a
#: documentation reconciliation in ``ARCHITECTURE_FREEZE`` §11.1.
#:
#: The messages are written for the operator watching the feed, not for the state
#: machine — they are rendered live on ``/runs/<id>``.
SCRAPE_WALK: tuple[tuple[RunState, str], ...] = (
    (
        RunState.PROFILING,
        "No website to profile — this scrape was started from the dashboard.",
    ),
    (
        RunState.DISCOVERING,
        "No subreddit discovery needed — using the list from the Configuration page.",
    ),
    (
        RunState.AWAITING_SUBREDDIT_REVIEW,
        "Subreddit review already satisfied: you chose these subreddits yourself.",
    ),
    (
        RunState.GENERATING_KEYWORDS,
        "No keyword generation — this run scrapes subreddit listings only.",
    ),
    (
        RunState.AWAITING_KEYWORD_REVIEW,
        "Keyword review already satisfied: scoring uses the keywords you configured.",
    ),
    (
        RunState.AWAITING_OPTIONS,
        "Using the default scraping options.",
    ),
    (
        RunState.SCRAPING,
        "Scraping started — working through the configured subreddits one at a time.",
    ),
)

#: Job type enqueued once per subreddit, and the one that closes the run.
SCRAPE_JOB = "scrape_subreddit"
FINALIZE_JOB = "finalize_run"


class RunAlreadyActive(Exception):
    """This project already has a run in flight.

    Carries the existing run's id because that is what the caller needs: the API
    answers ``409`` with it and the UI navigates there instead of starting a
    second run (``docs/13`` §9.4 — the double-click problem, solved structurally
    rather than with a disabled button).
    """

    def __init__(self, run_id: int) -> None:
        super().__init__(f"run {run_id} is already active for this project")
        self.run_id = run_id


class RunNotFound(LookupError):
    """No run with that id."""


@dataclass(frozen=True)
class RunOptions:
    """What the operator chose for this run.

    ``docs/07`` §5 defines fourteen fields. **Only the one P3 can honour is
    here.** The rest select behaviour that lives in stages this phase does not
    build — comment fetching, search mode, pagination depth — and a field carried
    in ``options_json`` that no code reads is not configuration, it is a promise
    the system does not keep. They arrive with the stages that read them.
    """

    subreddits: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"subreddits": list(self.subreddits)}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> RunOptions:
        """Tolerant of a missing or malformed payload — the DB is the only writer."""
        if not isinstance(raw, dict):
            return cls()
        subs = raw.get("subreddits") or []
        if not isinstance(subs, list):
            return cls()
        return cls(subreddits=tuple(str(s) for s in subs))


@dataclass(frozen=True)
class RunProgress:
    """What ``/api/runs/<id>/progress`` returns. ``docs/04`` §1.3.

    Polled every three seconds with a 50 ms budget, so every field is either
    already on the ``runs`` row or comes from the single ``GROUP BY`` in
    ``JobRepository.counts_by_state`` (``PHASE-02-HANDOVER`` T2).
    """

    state: str
    stage_label: str
    percent: int
    jobs_total: int
    jobs_done: int
    jobs_failed: int
    leads_found: int
    llm_cost_usd: float
    started_at: datetime | None
    updated_at: datetime | None
    last_error: str | None
    cancel_requested: bool = False
    job_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "stage_label": self.stage_label,
            "percent": self.percent,
            "jobs_total": self.jobs_total,
            "jobs_done": self.jobs_done,
            "jobs_failed": self.jobs_failed,
            "leads_found": self.leads_found,
            "llm_cost_usd": self.llm_cost_usd,
            "started_at": _iso(self.started_at),
            "updated_at": _iso(self.updated_at),
            "last_error": self.last_error,
            "cancel_requested": self.cancel_requested,
            "job_counts": self.job_counts,
            "terminal": self.state in {s.value for s in TERMINAL_STATES},
        }


class RunService:
    """Create, advance, cancel, retry and report on runs.

    Takes a ``Session`` rather than opening its own, for the reason ``docs/04``
    §1.2 gives: a transition must commit in the same transaction as its cause.
    The caller owns the commit.
    """

    def __init__(self, session: Session, queue: JobQueue | None = None) -> None:
        self.session = session
        # Bound to the session's engine, not the process-global one: a service
        # working against a test database must not enqueue into the real one.
        self.queue = queue or JobQueue(_engine_of(session))
        self.runs = RunRepository(session)
        self.jobs = JobRepository(session)

    # -- creation -----------------------------------------------------------

    def create(self, project_id: int | None, options: RunOptions) -> Run:
        """Start a run and queue its work. Raises :class:`RunAlreadyActive`.

        Everything here happens in the caller's transaction: the run row, the
        seven walk transitions, their ``run_events`` rows, and the jobs. Either
        the operator gets a run with work queued against it, or they get nothing
        — never a run whose jobs were lost to a rollback.
        """
        existing = self.runs.active_for_project(project_id)
        if existing is not None:
            raise RunAlreadyActive(existing.id)

        run = Run(
            project_id=project_id,
            state=RunState.PENDING.value,
            options_json=json.dumps(options.to_dict()),
            stats_json=json.dumps(
                {
                    "subreddits_total": len(options.subreddits),
                    "subreddits_done": 0,
                    "leads_found": 0,
                }
            ),
            llm_cost_usd=0.0,
            started_at=utcnow(),
            updated_at=utcnow(),
        )
        self.session.add(run)
        self.session.flush()  # assigns run.id, which every event below needs

        emit_event(
            self.session,
            run.id,
            "run.created",
            message=f"Run {run.id} created for {len(options.subreddits)} subreddit(s).",
            subreddits=list(options.subreddits),
        )

        self._walk_to_scraping(run)
        self._enqueue_scrape_jobs(run, options)
        return run

    def _walk_to_scraping(self, run: Run) -> None:
        """Advance ``PENDING -> SCRAPING`` one legal hop at a time.

        Shared by :meth:`create` and :meth:`retry` deliberately. A retry re-enters
        at ``PENDING`` — ``FAILED -> {PENDING}`` is the only edge out of failure —
        so it must make the identical journey. Two copies of this walk would
        drift, and the retry path is the one nobody looks at.
        """
        for target, reason in SCRAPE_WALK:
            self.transition(run.id, target, reason=reason)

    def _enqueue_scrape_jobs(self, run: Run, options: RunOptions) -> None:
        """One job per subreddit, so progress and cancellation have a unit.

        A single job for the whole list would make the progress bar jump from 0
        to 100 (AC2 asserts real counts) and would leave ``cancel_queued`` nothing
        to cancel (AC6).

        ``session=`` is mandatory here and everywhere a stage queues work: it
        enlists the insert in this transaction so the run and its jobs commit
        together (``PHASE-02-HANDOVER`` G1).
        """
        for subreddit in options.subreddits:
            self.queue.enqueue(
                SCRAPE_JOB,
                run_id=run.id,
                payload={"subreddit": subreddit},
                session=self.session,
            )

        if not options.subreddits:
            # Nothing to scrape, so no scrape handler will ever enqueue the
            # finaliser. Without this the run sits in SCRAPING forever and the
            # duplicate-run guard blocks every future run — the empty-list case
            # would quietly wedge the whole feature.
            emit_event(
                self.session,
                run.id,
                "scrape.skipped",
                level="warning",
                message="No subreddits configured, so there is nothing to scrape.",
            )
            self.queue.enqueue(FINALIZE_JOB, run_id=run.id, payload={}, session=self.session)

    # -- state --------------------------------------------------------------

    def transition(self, run_id: int, target: RunState, *, reason: str = "") -> Run:
        """Move a run to ``target``, or raise :class:`IllegalTransition`.

        The raise is the point. An illegal transition is a bug in whoever asked
        for it, and absorbing it silently would leave a run in a state its own
        state machine says is unreachable.
        """
        run = self._get(run_id)
        current = run.state
        assert_transition(current, target)

        run.state = target.value
        run.updated_at = utcnow()
        if target in TERMINAL_STATES:
            run.finished_at = utcnow()

        emit_event(
            self.session,
            run.id,
            "run.transition",
            level="error" if target is RunState.FAILED else "info",
            message=reason or f"{current} → {target.value}",
            from_state=current,
            to_state=target.value,
        )
        return run

    def fail(self, run_id: int, error: str) -> Run:
        """Terminate a run as ``FAILED``, recording why on the row itself."""
        run = self._get(run_id)
        run.error = error[:4000]
        return self.transition(run_id, RunState.FAILED, reason=error)

    def cancel(self, run_id: int, reason: str = "Cancelled by the operator.") -> Run:
        """Cancel queued work and stop the run.

        The job in flight is **not** killed. It finishes its current unit and
        stops at the flag this sets — killing a handler mid-write is what leases
        exist to clean up, not something to do deliberately
        (``PHASE-02-HANDOVER`` T4).

        The flag lives in ``stats_json`` rather than a new column because P3 owns
        no migration, and inventing one for a boolean would break the frozen
        chain.
        """
        run = self._get(run_id)
        self._merge_stats(run, cancel_requested=True)
        cancelled = self.queue.cancel_queued(run_id)
        emit_event(
            self.session,
            run_id,
            "run.cancel_requested",
            level="warning",
            message=f"{reason} {cancelled} queued job(s) cancelled.",
            jobs_cancelled=cancelled,
        )
        return self.transition(run_id, RunState.CANCELLED, reason=reason)

    def retry(self, run_id: int) -> Run:
        """Re-run a failed run from the top. ``FAILED`` only.

        Any other state raises :class:`IllegalTransition`, which the API answers
        as 409 — ``FAILED -> {PENDING}`` is the only edge out of failure, so this
        needs no state check of its own.
        """
        run = self._get(run_id)
        options = RunOptions.from_dict(_load_json(run.options_json))

        # The failed attempt's queued jobs are abandoned before new ones are
        # created. Without this, retrying a run that failed with work still
        # queued doubles that work: the old jobs are still claimable, and the
        # walk below enqueues a fresh set beside them.
        abandoned = self.queue.cancel_queued(run_id)
        if abandoned:
            emit_event(
                self.session,
                run_id,
                "run.retry.abandoned_jobs",
                message=f"Discarded {abandoned} job(s) left queued by the failed attempt.",
                jobs_cancelled=abandoned,
            )

        run.error = None
        run.finished_at = None
        self._merge_stats(run, cancel_requested=False, subreddits_done=0)
        self.transition(run_id, RunState.PENDING, reason="Retrying the run from the beginning.")

        self._walk_to_scraping(run)
        self._enqueue_scrape_jobs(run, options)
        return run

    # -- reporting ----------------------------------------------------------

    def progress(self, run_id: int) -> RunProgress:
        """The poll payload. One ``GROUP BY``; no rows loaded into Python."""
        run = self._get(run_id)
        counts = self.jobs.counts_by_state(run_id)
        stats = _load_json(run.stats_json) or {}

        total = sum(counts.values())
        done = counts.get(JobState.DONE.value, 0) + counts.get(JobState.CANCELLED.value, 0)
        failed = counts.get(JobState.FAILED.value, 0)

        return RunProgress(
            state=run.state,
            stage_label=self._stage_label(run, stats),
            percent=_percent(run.state, total, done),
            jobs_total=total,
            jobs_done=done,
            jobs_failed=failed,
            leads_found=int(stats.get("leads_found", 0) or 0),
            llm_cost_usd=float(run.llm_cost_usd or 0.0),
            started_at=run.started_at,
            updated_at=run.updated_at,
            last_error=run.error,
            cancel_requested=bool(stats.get("cancel_requested")),
            job_counts=counts,
        )

    @staticmethod
    def _stage_label(run: Run, stats: dict[str, Any]) -> str:
        """One human sentence. ``docs/04`` §1.3 wants "Scraping r/SaaS (3 of 7)"."""
        if run.state == RunState.SCRAPING.value:
            total = int(stats.get("subreddits_total", 0) or 0)
            done = int(stats.get("subreddits_done", 0) or 0)
            current = stats.get("current_subreddit")
            where = f" r/{current}" if current else ""
            return f"Scraping{where} ({min(done + 1, total)} of {total})" if total else "Scraping"
        return _STAGE_LABELS.get(run.state, run.state)

    def cancel_requested(self, run_id: int) -> bool:
        """Has the operator asked this run to stop? Checked by handlers between units."""
        run = self.runs.get(run_id)
        if run is None:
            return False
        return bool((_load_json(run.stats_json) or {}).get("cancel_requested"))

    # -- plumbing -----------------------------------------------------------

    def _get(self, run_id: int) -> Run:
        run = self.runs.get(run_id)
        if run is None:
            raise RunNotFound(f"no run with id {run_id}")
        return run

    def _merge_stats(self, run: Run, **updates: Any) -> dict[str, Any]:
        """Read-modify-write ``stats_json``, preserving keys this caller ignores.

        Assigning a fresh dict would silently drop whatever a concurrently
        written counter had put there.
        """
        stats = _load_json(run.stats_json) or {}
        stats.update(updates)
        run.stats_json = json.dumps(stats, default=str)
        run.updated_at = utcnow()
        return stats


#: Labels for the states a run passes through. The walk states appear here
#: because a run is briefly in each of them and a poll can land mid-walk.
_STAGE_LABELS: dict[str, str] = {
    RunState.PENDING.value: "Starting",
    RunState.PROFILING.value: "Profiling",
    RunState.DISCOVERING.value: "Finding subreddits",
    RunState.AWAITING_SUBREDDIT_REVIEW.value: "Subreddit review",
    RunState.GENERATING_KEYWORDS.value: "Generating keywords",
    RunState.AWAITING_KEYWORD_REVIEW.value: "Keyword review",
    RunState.AWAITING_OPTIONS.value: "Choosing options",
    RunState.SCRAPING.value: "Scraping",
    RunState.ANALYZING.value: "Analysing",
    RunState.COMPLETE.value: "Complete",
    RunState.FAILED.value: "Failed",
    RunState.CANCELLED.value: "Cancelled",
}


def _percent(state: str, total: int, done: int) -> int:
    """Job-count progress, pinned to 100 once the run is over.

    A terminal run whose jobs were cancelled would otherwise report something
    like 40% forever, which reads as "still going" on a run that has stopped.
    """
    if state in {s.value for s in TERMINAL_STATES}:
        return 100
    if total <= 0:
        return 0
    return max(0, min(100, round(done * 100 / total)))


def _load_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("run column is not JSON")
        return None
    return loaded if isinstance(loaded, dict) else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _engine_of(session: Session) -> Engine | None:
    bind = session.get_bind()
    return bind if isinstance(bind, Engine) else None


__all__ = [
    "FINALIZE_JOB",
    "SCRAPE_JOB",
    "SCRAPE_WALK",
    "IllegalTransition",
    "RunAlreadyActive",
    "RunNotFound",
    "RunOptions",
    "RunProgress",
    "RunService",
]
