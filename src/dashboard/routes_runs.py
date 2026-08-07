"""Run and job endpoints, plus the two pages that render them.

A new blueprint, not an addition to ``routes.py``. That file holds the 17 legacy
endpoints and the guarantee that they are byte-for-byte what they were (R20); the
way to keep that true is to stop editing it. Its one P3 change is the
``/api/scrape`` shim, and nothing else.

**Error mapping is uniform and deliberate:**

* :class:`RunNotFound` → ``404``
* :class:`IllegalTransition` → ``409``, with both states named in the message
* :class:`RunAlreadyActive` → ``409``, carrying the existing ``run_id`` so the
  caller can navigate to it instead of guessing

``IllegalTransition`` is caught **by name**, never as ``ValueError``. It happens
to subclass one so that a caller who does not know about it still crashes rather
than proceeding, but catching ``ValueError`` here would quietly turn an unrelated
bug — a bad int, a malformed payload — into a plausible-looking 409.

Specification: ``docs/13-phase-03.md`` §6, ``docs/09-dashboard-plan.md`` §4.2.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from src.db.database import get_session
from src.db.models import Job, Run, RunEvent
from src.db.repositories.runs import JobRepository, RunRepository
from src.orchestration.job_queue import JobQueue
from src.orchestration.run_service import (
    RunAlreadyActive,
    RunNotFound,
    RunOptions,
    RunService,
)
from src.orchestration.states import IllegalTransition

log = logging.getLogger(__name__)

bp = Blueprint("runs", __name__)

#: Most rows anyone wants on one page. The run list is an operator's recent
#: history, not an archive; the archive is the database.
RUN_LIST_LIMIT = 50

#: Events returned per poll. The feed is incremental — the client passes the last
#: id it saw — so this bounds one response, not the timeline.
EVENT_PAGE_LIMIT = 200


# ---------------------------------------------------------------- error paths


@bp.errorhandler(RunNotFound)
def _not_found(exc: RunNotFound):
    return jsonify({"error": str(exc)}), 404


@bp.errorhandler(IllegalTransition)
def _illegal(exc: IllegalTransition):
    # The message already names both states; docs/13 AC12 requires that, and it
    # is the difference between an actionable 409 and a mystery.
    return jsonify({"error": str(exc)}), 409


@bp.errorhandler(RunAlreadyActive)
def _already_active(exc: RunAlreadyActive):
    return jsonify({"error": str(exc), "run_id": exc.run_id}), 409


# ------------------------------------------------------------------ run pages


@bp.route("/runs")
def runs_page():
    session = get_session()
    try:
        runs = RunRepository(session).recent(limit=RUN_LIST_LIMIT)
        return render_template(
            "runs.html",
            nav_active="runs",
            runs=[_run_summary(session, run) for run in runs],
        )
    finally:
        session.close()


@bp.route("/runs/<int:run_id>")
def run_page(run_id: int):
    session = get_session()
    try:
        run = RunRepository(session).get(run_id)
        if run is None:
            return render_template("run_missing.html", nav_active="runs", run_id=run_id), 404
        return render_template(
            "run_progress.html",
            nav_active="runs",
            run=_run_json(run),
            progress=RunService(session).progress(run_id).to_dict(),
        )
    finally:
        session.close()


# -------------------------------------------------------------------- run API


@bp.route("/api/runs", methods=["GET"])
def api_runs_list():
    session = get_session()
    try:
        query = session.query(Run).order_by(Run.id.desc())
        project_id = request.args.get("project_id", type=int)
        if project_id is not None:
            query = query.filter(Run.project_id == project_id)
        state = request.args.get("state", "").strip()
        if state:
            query = query.filter(Run.state == state)
        return jsonify([_run_summary(session, run) for run in query.limit(RUN_LIST_LIMIT)])
    finally:
        session.close()


@bp.route("/api/runs", methods=["POST"])
def api_runs_create():
    data = request.get_json(silent=True) or {}
    options = RunOptions.from_dict(data.get("options"))
    project_id = data.get("project_id")

    session = get_session()
    try:
        if not options.subreddits:
            options = RunOptions(subreddits=configured_subreddits(session))
        run = RunService(session).create(project_id, options)
        session.commit()
        return jsonify(_run_json(run)), 201
    finally:
        session.close()


@bp.route("/api/runs/<int:run_id>", methods=["GET"])
def api_run_get(run_id: int):
    session = get_session()
    try:
        run = RunRepository(session).get(run_id)
        if run is None:
            raise RunNotFound(f"no run with id {run_id}")
        return jsonify(_run_json(run))
    finally:
        session.close()


@bp.route("/api/runs/<int:run_id>/progress", methods=["GET"])
def api_run_progress(run_id: int):
    """The poll target. One ``GROUP BY`` and one row read — nothing else.

    ``docs/13`` §6 gives this a 50 ms budget at 5,000 jobs, which is what rules
    out loading the run's jobs and counting them in Python.
    """
    session = get_session()
    try:
        return jsonify(RunService(session).progress(run_id).to_dict())
    finally:
        session.close()


@bp.route("/api/runs/<int:run_id>/events", methods=["GET"])
def api_run_events(run_id: int):
    """Incremental feed. ``after`` is the highest id the client already has."""
    after = request.args.get("after", 0, type=int)
    session = get_session()
    try:
        events = RunRepository(session).events(run_id, after_id=after, limit=EVENT_PAGE_LIMIT)
        return jsonify(
            {
                "events": [_event_json(event) for event in events],
                "last_id": events[-1].id if events else after,
            }
        )
    finally:
        session.close()


@bp.route("/api/runs/<int:run_id>/cancel", methods=["POST"])
def api_run_cancel(run_id: int):
    session = get_session()
    try:
        run = RunService(session).cancel(run_id)
        session.commit()
        return jsonify(_run_json(run))
    finally:
        session.close()


@bp.route("/api/runs/<int:run_id>/retry", methods=["POST"])
def api_run_retry(run_id: int):
    """From ``FAILED`` only. Anything else is a 409 naming both states."""
    session = get_session()
    try:
        run = RunService(session).retry(run_id)
        session.commit()
        return jsonify(_run_json(run))
    finally:
        session.close()


# -------------------------------------------------------------------- job API


@bp.route("/api/jobs", methods=["GET"])
def api_jobs_list():
    """Debug view. Scoped to one run by default — the whole table is not a page."""
    run_id = request.args.get("run_id", type=int)
    session = get_session()
    try:
        repo = JobRepository(session)
        jobs = repo.for_run(run_id) if run_id is not None else []
        return jsonify(
            {
                "jobs": [_job_json(job) for job in jobs],
                "counts": repo.counts_by_state(run_id),
            }
        )
    finally:
        session.close()


@bp.route("/api/jobs/<int:job_id>/retry", methods=["POST"])
def api_job_retry(job_id: int):
    session = get_session()
    try:
        job = JobQueue(session.get_bind()).requeue(job_id)
        if job is None:
            return jsonify({"error": f"no job with id {job_id}"}), 404
        return jsonify(_job_json(job))
    finally:
        session.close()


# ------------------------------------------------------------- serialisation


def _run_json(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "state": run.state,
        "options": _json_column(run.options_json),
        "stats": _json_column(run.stats_json),
        "llm_cost_usd": float(run.llm_cost_usd or 0.0),
        # Redacted on write by RunService.fail, like every other operator-facing
        # string. Repeated here as a fact worth knowing, not as a second guard.
        "error": run.error,
        "started_at": _iso(run.started_at),
        "updated_at": _iso(run.updated_at),
        "finished_at": _iso(run.finished_at),
    }


def _run_summary(session, run: Run) -> dict[str, Any]:
    """A list row: the run, plus the numbers and labels the table shows.

    The display strings are built here rather than by a Jinja filter so the JSON
    endpoint and the page show the same thing. A filter would give the page one
    formatting and every API consumer another.
    """
    stats = _json_column(run.stats_json) or {}
    payload = _run_json(run)
    payload["leads_found"] = int(stats.get("leads_found", 0) or 0)
    payload["duration_seconds"] = _duration(run)
    payload["duration_label"] = _duration_label(payload["duration_seconds"])
    payload["started_label"] = _time_label(run.started_at)
    payload["job_counts"] = JobRepository(session).counts_by_state(run.id)
    payload["jobs_total"] = sum(payload["job_counts"].values())
    payload["jobs_done"] = payload["job_counts"].get("done", 0)
    return payload


def _duration_label(seconds: float | None) -> str:
    """``18m 22s``. Empty for a run that has not started, never ``0s``."""
    if seconds is None:
        return "—"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m"


def _time_label(value) -> str:
    """``08-07 14:22`` — UTC, like every stored timestamp in this schema."""
    return value.strftime("%m-%d %H:%M") if value else "—"


def _job_json(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "run_id": job.run_id,
        "job_type": job.job_type,
        "state": job.state,
        "payload": _json_column(job.payload_json),
        "priority": job.priority,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "available_at": _iso(job.available_at),
        "worker_id": job.worker_id,
        "result": _json_column(job.result_json),
        # Redacted by JobQueue.fail before it was ever stored.
        "error": job.error,
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
    }


def _event_json(event: RunEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "level": event.level,
        "event": event.event,
        # Both redacted by emit_event on the way in (R15).
        "message": event.message,
        "data": _json_column(event.data_json),
        "created_at": _iso(event.created_at),
    }


def configured_subreddits(session) -> tuple[str, ...]:
    """The subreddits the operator configured — ``config.yaml`` plus the dashboard.

    Public, and the **only** answer to "which subreddits does a run scrape?".
    ``/api/scrape`` and ``POST /api/runs`` both call it, because two derivations
    of that list would drift and the drift would be invisible: both would scrape
    something plausible.

    It delegates to ``get_all_subreddits``, which is what the CLI has always
    used, so the orchestrated path targets exactly what the legacy path did.
    """
    from src.orchestration.handlers.scrape import load_config
    from src.subreddit_loader import get_all_subreddits

    return tuple(get_all_subreddits(load_config(), session))


def _duration(run: Run) -> float | None:
    end = run.finished_at or run.updated_at
    if not run.started_at or not end:
        return None
    return max(0.0, (end - run.started_at).total_seconds())


def _json_column(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        log.warning("stored column is not JSON")
        return None


def _iso(value) -> str | None:
    return value.isoformat() if value else None
