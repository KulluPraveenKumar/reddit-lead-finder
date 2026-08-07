"""Read-side queries over ``runs``, ``jobs`` and ``run_events``.

Repositories exist so query logic does not sprawl into routes (AD-6). Everything
here is aggregation or a bounded list, computed in SQL rather than by loading
rows into Python — ``progress()`` is polled every three seconds by the run page
P3 builds, and it has a stated 50 ms budget.

The write path lives in :mod:`src.orchestration.job_queue`, not here. Splitting
them keeps one answer to "who changes a job's state?", which is the question that
matters when two processes are touching the same row.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Job, Run, RunEvent


class RunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, run_id: int) -> Run | None:
        return self.session.get(Run, run_id)

    def recent(self, limit: int = 50) -> list[Run]:
        return self.session.query(Run).order_by(Run.id.desc()).limit(limit).all()

    def active_for_project(self, project_id: int | None) -> Run | None:
        """The project's run that is still in flight, if any.

        P3's duplicate-run guard is built on this. Terminal states are excluded
        rather than listed, so a thirteenth ``RunState`` cannot silently become
        "active" by being forgotten here.
        """
        from src.orchestration.states import TERMINAL_STATES

        terminal = [state.value for state in TERMINAL_STATES]
        return (
            self.session.query(Run)
            .filter(Run.project_id == project_id, Run.state.notin_(terminal))
            .order_by(Run.id.desc())
            .first()
        )

    def events(self, run_id: int, *, after_id: int = 0, limit: int = 200) -> list[RunEvent]:
        """The run's timeline, incrementally. ``after_id`` is the last id seen."""
        return (
            self.session.query(RunEvent)
            .filter(RunEvent.run_id == run_id, RunEvent.id > after_id)
            .order_by(RunEvent.id.asc())
            .limit(limit)
            .all()
        )


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, job_id: int) -> Job | None:
        return self.session.get(Job, job_id)

    def for_run(self, run_id: int, *, limit: int = 500) -> list[Job]:
        return (
            self.session.query(Job)
            .filter(Job.run_id == run_id)
            .order_by(Job.id.asc())
            .limit(limit)
            .all()
        )

    def counts_by_state(self, run_id: int | None = None) -> dict[str, int]:
        """``{state: count}`` — one ``GROUP BY`` over ``ix_jobs_run``.

        Missing states are absent rather than zero: the caller decides what an
        absent state means, and inventing zeros here would hide the difference
        between "no such job" and "none left".
        """
        query = self.session.query(Job.state, func.count(Job.id))
        if run_id is not None:
            query = query.filter(Job.run_id == run_id)
        return {state: int(count) for state, count in query.group_by(Job.state).all()}

    def counts_by_state_for_runs(self, run_ids: list[int]) -> dict[int, dict[str, int]]:
        """``{run_id: {state: count}}`` for many runs in **one** query.

        The run list renders fifty rows, each showing "jobs done / total". Asking
        :meth:`counts_by_state` per row is fifty round trips for one page, and it
        grows with the history rather than staying flat — the kind of N+1 that is
        invisible at ten runs and obvious at a thousand.

        Runs with no jobs are absent, matching :meth:`counts_by_state`: the
        caller decides what an absent run means.
        """
        if not run_ids:
            return {}
        rows = (
            self.session.query(Job.run_id, Job.state, func.count(Job.id))
            .filter(Job.run_id.in_(run_ids))
            .group_by(Job.run_id, Job.state)
            .all()
        )
        counts: dict[int, dict[str, int]] = {}
        for run_id, state, count in rows:
            counts.setdefault(run_id, {})[state] = int(count)
        return counts

    def queue_depth(self) -> dict[str, Any]:
        """Queue health, independent of any run. Feeds ``/health`` in P3."""
        counts = self.counts_by_state()
        oldest = (
            self.session.query(func.min(Job.available_at)).filter(Job.state == "queued").scalar()
        )
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "failed": counts.get("failed", 0),
            "oldest_queued_at": oldest,
        }
