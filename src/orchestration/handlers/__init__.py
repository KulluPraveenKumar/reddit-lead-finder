"""The handler registry: ``job_type`` → the function that runs it.

A plain dict, not a plugin system or an entry-point scan. ``docs/04`` §2.4 names
seven job types and the freeze closes that list, so the registry is a lookup
table whose contents can be read in one screen — and an unregistered type fails
loudly in the worker rather than being silently skipped.

**P3 registers three.** ``maintenance`` arrived with P2; ``scrape_subreddit`` and
``finalize_run`` are the pair that carries a run from start to finish. Every AI,
discovery and comment type belongs to a later stage, and their absence is the
phase behaving rather than the phase unfinished.

A handler's contract:

* signature ``(session, job) -> dict | None`` — the dict lands in ``jobs.result_json``
* it runs **inside the caller's transaction**; it must not commit
* it must be **idempotent** (R9). A lease can expire mid-execution and the job
  will be re-claimed and re-run, by design
* it raises :class:`~src.orchestration.job_queue.RetryableError` for a failure a
  later attempt might survive, and anything else for one it will not
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Job
from src.orchestration.handlers.finalize import handle_finalize_run
from src.orchestration.handlers.maintenance import handle_maintenance
from src.orchestration.handlers.scrape import handle_scrape_subreddit

Handler = Callable[[Session, Job], dict[str, Any] | None]

REGISTRY: dict[str, Handler] = {
    "maintenance": handle_maintenance,
    "scrape_subreddit": handle_scrape_subreddit,
    "finalize_run": handle_finalize_run,
}

__all__ = [
    "REGISTRY",
    "Handler",
    "handle_finalize_run",
    "handle_maintenance",
    "handle_scrape_subreddit",
]
