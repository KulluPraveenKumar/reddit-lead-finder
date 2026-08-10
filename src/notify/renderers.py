"""Markdown bodies, built from SQL. No model, no network, no writes.

Every figure in a rendered message comes from a query issued **here**. No renderer
accepts a pre-computed total from its caller, and that restriction is the whole
point rather than a stylistic preference: a notification is the only view of a run
some operators will ever read, and a number passed in by a caller can disagree
with the database that produced it. ``docs/34`` §P7 task 2 states it as
*"Markdown renderers **from SQL**"*.

The signature is therefore ``(session, run_id)`` and nothing else -- there is no
payload parameter to smuggle an aggregate through. Where a value cannot be
computed from the database, the renderer **omits the line** instead of inventing
one.

**Read-only.** Nothing here inserts, updates or deletes, asserted by a test that
counts write statements rather than by inspection. That is not merely tidy: this
runs from a job handler immediately after a commit and immediately before a
network call (D3), so a write here would dirty the session and hold SQLite's
single write lock across the send -- trap T0, the defect P3 lost a sign-off to.

**No escaping is applied.** Telegram's parse modes disagree about what must be
escaped -- ``MarkdownV2`` requires it for a dozen characters that ``HTML`` does
not -- and the parse mode is chosen by the transport, which does not exist yet.
Escaping here would either hard-code one transport's rules into every body or
double-escape once the transport did it properly. The markup is deliberately
minimal (``*bold*`` and nothing else) so that the choice stays cheap for Stage 4.

Specification: ``docs/34-implementation-plan.md`` §P7 task 2 ·
``docs/P7-IMPLEMENTATION-CHECKLIST.md`` Stage 3.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import Job, Run, RunEvent, ScrapeRun
from src.notify.service import Kind
from src.orchestration.states import JobState, RunState

#: ``job_type`` of the per-subreddit collection jobs, one per subreddit.
#:
#: Imported as a literal rather than from ``run_service`` on purpose: importing
#: it would pull ``RunService`` -- and with it ``JobQueue`` and the enqueue path --
#: into a module whose entire contract is that it only reads. The value is
#: asserted against ``run_service.SCRAPE_JOB`` by a test, so the duplication
#: cannot drift silently.
SCRAPE_JOB = "scrape_subreddit"

#: Which gate each waiting state is, in the operator's language.
#:
#: ``AWAITING_OPTIONS`` is included because the transition table puts it on the
#: only path from ``PENDING`` to ``SCRAPING`` -- a run genuinely waits there --
#: even though ``docs/34`` §P18 numbers only two gates. Leaving it out would have
#: produced a message that could not say what it was waiting for.
GATE_LABELS: dict[str, str] = {
    RunState.AWAITING_SUBREDDIT_REVIEW.value: "Gate 1 — subreddit review",
    RunState.AWAITING_KEYWORD_REVIEW.value: "Gate 2 — keyword review",
    RunState.AWAITING_OPTIONS.value: "Run options",
}


# --------------------------------------------------------------------- queries


def _run(session: Session, run_id: int):
    """The run's own columns, read with a query rather than ``session.get``.

    ``session.get`` is served from the identity map when the caller already holds
    the object -- which the dispatcher always will, because it renders
    immediately after a handler transitioned the run. That would make this module
    render *the caller's in-memory object*, not the database, and the difference
    is not academic: an attribute mutated but not yet flushed would be reported as
    fact. Found by the read-only test, which observed that rendering a gate issued
    no SQL at all.

    Selecting columns rather than the entity also keeps the read narrow: nothing
    here needs ``options_json`` or ``stats_json``, and the latter is precisely the
    stored aggregate this stage exists to avoid rendering from.
    """
    row = session.execute(
        select(
            Run.id,
            Run.state,
            Run.error,
            Run.llm_cost_usd,
            Run.started_at,
            Run.updated_at,
            Run.finished_at,
        ).where(Run.id == run_id)
    ).one_or_none()
    if row is None:
        raise LookupError(f"run {run_id} does not exist")
    return row


def collection_totals(session: Session, run_id: int) -> tuple[int, int]:
    """``(leads, posts)`` summed over this run's ``scrape_runs`` audit rows.

    This is the honest SQL source for "how many leads did the run find".
    ``leads`` carries no ``run_id`` -- it gains ``project_id`` in ``0006`` and
    never a run link -- so counting the table directly would count every lead
    ever collected. ``scrape_runs.run_id`` has been populated since P3
    (``subreddit_scraper.py``), and one row per scraper per run is exactly the
    grain needed here.

    Deliberately **not** ``runs.stats_json``, which is a rolling counter written
    by the handler for the progress endpoint. Reading it would make the message a
    view of what a handler last remembered rather than of what was recorded.
    """
    row = session.execute(
        select(
            func.coalesce(func.sum(ScrapeRun.leads_found), 0),
            func.coalesce(func.sum(ScrapeRun.posts_found), 0),
        ).where(ScrapeRun.run_id == run_id)
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


def subreddit_job_counts(session: Session, run_id: int) -> dict[str, int]:
    """``{job state: count}`` over this run's per-subreddit jobs.

    One ``GROUP BY`` rather than loading rows: a run with a hundred subreddits
    should not pull a hundred jobs into memory to answer "how many failed?" --
    the same reasoning ``finalize_run`` records for its own counter.
    """
    rows = session.execute(
        select(Job.state, func.count(Job.id))
        .where(Job.run_id == run_id, Job.job_type == SCRAPE_JOB)
        .group_by(Job.state)
    ).all()
    return {str(state): int(count) for state, count in rows}


def _events(session: Session, run_id: int, event: str) -> list[dict[str, Any]]:
    """Every ``run_events`` row of one kind, oldest first, payload decoded.

    ``created_at`` is folded into the payload so a renderer can order or date a
    row without a second query. A row whose ``data_json`` is unreadable yields an
    empty payload rather than raising: a corrupt timeline entry must not be able
    to stop a message about the thing it was recording.
    """
    rows = session.execute(
        select(RunEvent.data_json, RunEvent.message, RunEvent.created_at)
        .where(RunEvent.run_id == run_id, RunEvent.event == event)
        .order_by(RunEvent.id)
    ).all()

    out: list[dict[str, Any]] = []
    for data_json, message, created_at in rows:
        try:
            payload = json.loads(data_json) if data_json else {}
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["message"] = message
        payload["created_at"] = created_at
        out.append(payload)
    return out


# ----------------------------------------------------------------- formatting


def _duration(start: datetime, end: datetime) -> str | None:
    """``4m 12s``, or ``None`` when the clock went backwards.

    Returning ``None`` rather than ``"unknown"`` is what lets the caller drop the
    line entirely -- a message reading "Duration: unknown" is worse than one that
    does not mention duration.

    Both arguments are required rather than optional, and there is **no None
    guard**. ``runs.started_at`` and ``runs.updated_at`` are both
    ``nullable=False``, and the caller passes ``finished_at or updated_at``, so
    neither can be ``None``. A guard for it would be a branch nothing can reach --
    P6's F1, where exactly that shape of branch reported 87% coverage while
    proving nothing, and only a surviving mutation exposed it. The negative case
    below *is* reachable: NTP steps clocks backwards.
    """
    seconds = int((end - start).total_seconds())
    if seconds < 0:
        return None
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _lines(title: str, fields: Sequence[tuple[str, str | None]], *, note: str = "") -> str:
    """``*title*`` then ``- Label: value`` per field, omitting empty values.

    One shape for every kind, so a reader who has seen one message can read the
    next -- and so the tests can parse a body back into a mapping and assert
    field by field instead of searching for substrings, which is what makes a
    changed label a test failure rather than a silent regression.
    """
    body = [f"*{title}*"]
    if note:
        body.extend(["", note])
    # ``is not None``, not a truthiness or an ``in (None, "")`` check. A renderer
    # signals "this line cannot be sourced" with None and never with "" -- every
    # value it builds falls back to explanatory text rather than to an empty
    # string. Testing for "" as well would be a branch nothing can reach, which
    # is P6's F1; a truthiness test would additionally drop a legitimate "0".
    rendered = [f"- {label}: {value}" for label, value in fields if value is not None]
    if rendered:
        body.append("")
        body.extend(rendered)
    return "\n".join(body)


# ------------------------------------------------------------------ renderers


def render_run_complete(session: Session, run_id: int) -> str:
    run = _run(session, run_id)
    leads, posts = collection_totals(session, run_id)
    counts = subreddit_job_counts(session, run_id)

    done = counts.get(JobState.DONE.value, 0)
    failed = counts.get(JobState.FAILED.value, 0)
    cancelled = counts.get(JobState.CANCELLED.value, 0)
    total = sum(counts.values())

    fields: list[tuple[str, str | None]] = [
        ("Leads", str(leads)),
        ("Posts scanned", str(posts)),
        ("Subreddits", f"{done} of {total}" if total else None),
        ("Failed", str(failed) if failed else None),
        ("Cancelled", str(cancelled) if cancelled else None),
        ("Duration", _duration(run.started_at, run.finished_at or run.updated_at)),
        ("AI cost", f"${float(run.llm_cost_usd or 0.0):.4f}"),
    ]
    return _lines(f"Run {run_id} complete", fields)


def render_run_failed(session: Session, run_id: int) -> str:
    """A failure reports what was **kept**, not only what broke.

    AD-9 -- *"a failure never discards completed work"* -- is a promise the
    operator can only verify if the message says how much survived. Leading with
    the error and then the salvage is what makes "the run failed" actionable
    rather than alarming.
    """
    run = _run(session, run_id)
    leads, posts = collection_totals(session, run_id)
    counts = subreddit_job_counts(session, run_id)

    fields: list[tuple[str, str | None]] = [
        ("Error", (run.error or "").strip() or "no error was recorded"),
        ("Leads kept", str(leads)),
        ("Posts scanned", str(posts)),
        ("Subreddits done", str(counts.get(JobState.DONE.value, 0))),
        ("Subreddits failed", str(counts.get(JobState.FAILED.value, 0))),
        ("Duration", _duration(run.started_at, run.finished_at or run.updated_at)),
    ]
    return _lines(f"Run {run_id} FAILED", fields, note="Collected work has been kept.")


def render_gate_reached(session: Session, run_id: int) -> str:
    """Degrades to what the database can answer, which today is the gate itself.

    ``docs/34`` §P18 owns the rich card -- candidate counts, the rejected list,
    the cost estimate, the deep link -- because it is the first phase with
    candidates to count. Those figures live in ``project_subreddits`` and
    ``project_keywords``, created by revision ``0008``, which **does not exist**.
    So this renderer queries neither, and omits every line it cannot source
    rather than printing a zero that would read as "nothing was found".

    A run that is not at a gate is still rendered. The dispatcher decides *when*
    to send; a renderer that raised because the state had moved on would turn a
    late notification into a failed one.
    """
    run = _run(session, run_id)
    gate = GATE_LABELS.get(run.state)

    fields: list[tuple[str, str | None]] = [
        ("Waiting at", gate or f"state {run.state}"),
        (
            "Since",
            run.updated_at.isoformat(sep=" ", timespec="seconds") if run.updated_at else None,
        ),
    ]
    note = (
        "Waiting for your approval. A gate has no timeout — the run will wait."
        if gate
        else "This run is no longer at a gate."
    )
    return _lines(f"Run {run_id} needs approval", fields, note=note)


def render_proxy_pool_degraded(session: Session, run_id: int) -> str:
    """One line per ladder step that actually degraded, from ``run_events``.

    The source is P4's ``net.degraded`` rows, which its own decision (c) buffers
    during the scrape and drains afterwards -- deduplicated to *"one notice per
    ladder step per run"*. That is why this renders a list of steps rather than a
    pool size: it reports what happened, not how many proxies are configured.
    Reading ``proxies`` instead would report the operator's own configuration
    back to them (D2b).
    """
    notices = _events(session, run_id, "net.degraded")

    fields: list[tuple[str, str | None]] = [("Degradations", str(len(notices)))]
    for notice in notices:
        step = f"{notice.get('from_provider') or '?'} → {notice.get('to_provider') or '?'}"
        reason = str(notice.get("reason") or "").strip()
        request_class = str(notice.get("request_class") or "").strip()
        detail = f"{reason} ({request_class} traffic)" if request_class else reason
        fields.append((step, detail or "no reason recorded"))

    return _lines(
        f"Run {run_id} — egress degraded",
        fields,
        note="Collection continued on the next rung of the ladder.",
    )


def render_discovery_overflow(session: Session, run_id: int) -> str:
    """Names **every** overflowed subreddit, because overflow is per-subreddit.

    P6's G5: one ``discovery.overflow`` row is written per subreddit, and its
    detection is per-subreddit precisely because a combined multireddit request
    keyed on ``subreddits[0]`` would leave the rest unable to detect overflow at
    all. Summarising here -- "3 subreddits overflowed" -- would undo in the
    message exactly what P6 built in the data, and leave the operator without the
    one fact they can act on.

    R19 makes this an error rather than a statistic: posts may have been lost.
    """
    rows = _events(session, run_id, "discovery.overflow")

    fields: list[tuple[str, str | None]] = [("Subreddits affected", str(len(rows)))]
    for row in rows:
        subreddit = str(row.get("subreddit") or "?")
        seen = row.get("seen")
        recovered = row.get("html_recovered")
        parts = []
        if seen is not None:
            parts.append(f"{seen} seen")
        if recovered is not None:
            parts.append(f"{recovered} recovered by HTML walk")
        fields.append((f"r/{subreddit}", ", ".join(parts) or "no counts recorded"))

    return _lines(
        f"Run {run_id} — watermark overflow",
        fields,
        note="Posts may have been missed. The poll interval was halved.",
    )


#: One renderer per kind. Total over :class:`Kind`, asserted by a test.
RENDERERS: dict[Kind, Callable[[Session, int], str]] = {
    Kind.RUN_COMPLETE: render_run_complete,
    Kind.RUN_FAILED: render_run_failed,
    Kind.GATE_REACHED: render_gate_reached,
    Kind.PROXY_POOL_DEGRADED: render_proxy_pool_degraded,
    Kind.DISCOVERY_OVERFLOW: render_discovery_overflow,
}


def render(kind: Kind | str, session: Session, run_id: int) -> str:
    """Render one notification body.

    Raises :class:`ValueError` for anything that is not a notification kind.
    Unlike :func:`src.notify.service.decide`, which suppresses an unknown event
    because it is *given* every timeline row, reaching here with one is a bug:
    the dispatcher renders only what the policy already said to send.
    """
    try:
        resolved = Kind(kind)
    except ValueError as exc:
        raise ValueError(f"{kind!r} is not a notification kind") from exc
    return RENDERERS[resolved](session, run_id)


__all__ = [
    "GATE_LABELS",
    "RENDERERS",
    "collection_totals",
    "render",
    "render_discovery_overflow",
    "render_gate_reached",
    "render_proxy_pool_degraded",
    "render_run_complete",
    "render_run_failed",
    "subreddit_job_counts",
]
