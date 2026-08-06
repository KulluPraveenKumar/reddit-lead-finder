"""``emit_event`` — the operator-facing timeline for a run.

This is deliberately **not** the application log. The log is for whoever is
debugging the process; ``run_events`` is for the person watching ``/runs/<id>``
in a browser, so it is queryable, correlated to one run, and written in the same
transaction as the work it describes.

Writing both from one call is the point: a stage that appends to the timeline and
forgets to log, or logs and forgets the timeline, produces two accounts of the
same run that disagree. One call, two sinks, one truth.

Specification: ``docs/13-phase-03.md`` §4, ``docs/04-system-design.md`` §1.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import RunEvent
from src.obs.logging import redact

log = logging.getLogger(__name__)

#: The levels ``run_events.level`` accepts. Kept as a set rather than an enum
#: because it is a display hint for one template, not a state machine.
LEVELS = frozenset({"info", "warning", "error"})


def emit_event(
    session: Session,
    run_id: int,
    event: str,
    *,
    level: str = "info",
    message: str | None = None,
    **data: Any,
) -> RunEvent:
    """Append one row to ``run_events`` and log the same fact.

    The row is **added, not committed**. The caller's transaction owns it, which
    is what makes "the stage finished and the next one was queued" atomic — the
    timeline can never claim a stage completed in a transaction that rolled back.

    ``data`` is stored as JSON. It is redacted on the way in: this table is
    rendered into an HTML page, and R15 says a credential never reaches a
    template.
    """
    if level not in LEVELS:
        raise ValueError(f"unknown run_event level {level!r}; valid: {', '.join(sorted(LEVELS))}")

    payload = json.dumps(data, default=str) if data else None
    row = RunEvent(
        run_id=run_id,
        level=level,
        event=event,
        message=redact(message) if message else None,
        data_json=redact(payload) if payload else None,
    )
    session.add(row)

    log.log(
        _LOG_LEVELS[level],
        message or event,
        extra={"run_id": run_id, "event": event},
    )
    return row


_LOG_LEVELS = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}
