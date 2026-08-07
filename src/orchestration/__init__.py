"""Orchestration: the persisted run state machine and durable job queue.

P1 shipped the *vocabulary* — states, transitions, and the three tables that hold
them. P2 added the *runtime*: a queue that claims work with a lease, a worker
that executes it, and a handler registry. P3 adds ``RunService``, the thing that
drives them, and the first two handlers that do real work.

**The dependency rule, and where it now bends.** The queue, the worker and the
state machine still know nothing about what a job does — that is what lets a
stage change without the queue changing. ``handlers/scrape.py`` imports
``src.scrapers`` because a handler is precisely the adapter between the two, and
it is the only module here that does. Nothing in this package imports ``src.ai``.

Specification: ``docs/04-system-design.md`` §1-3, ``docs/13-phase-03.md``.
"""

from src.orchestration.handlers import REGISTRY, Handler
from src.orchestration.job_queue import (
    BACKOFF_CAP_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    MAX_ATTEMPTS,
    JobQueue,
    RetryableError,
    backoff_seconds,
    payload_of,
    utcnow,
)
from src.orchestration.run_service import (
    FINALIZE_JOB,
    SCRAPE_JOB,
    SCRAPE_WALK,
    RunAlreadyActive,
    RunNotFound,
    RunOptions,
    RunProgress,
    RunService,
)
from src.orchestration.states import (
    GATE_STATES,
    JOB_TRANSITIONS,
    TERMINAL_STATES,
    TRANSITIONS,
    IllegalTransition,
    JobState,
    RunState,
    assert_job_transition,
    assert_transition,
    can_transition,
    is_gate,
    is_terminal,
)
from src.orchestration.worker import (
    Worker,
    run_standalone,
    start_inprocess_worker,
    worker_inprocess_enabled,
)

__all__ = [
    "BACKOFF_CAP_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "FINALIZE_JOB",
    "GATE_STATES",
    "JOB_TRANSITIONS",
    "MAX_ATTEMPTS",
    "REGISTRY",
    "SCRAPE_JOB",
    "SCRAPE_WALK",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "Handler",
    "IllegalTransition",
    "JobQueue",
    "JobState",
    "RetryableError",
    "RunAlreadyActive",
    "RunNotFound",
    "RunOptions",
    "RunProgress",
    "RunService",
    "RunState",
    "Worker",
    "assert_job_transition",
    "assert_transition",
    "backoff_seconds",
    "can_transition",
    "is_gate",
    "is_terminal",
    "payload_of",
    "run_standalone",
    "start_inprocess_worker",
    "utcnow",
    "worker_inprocess_enabled",
]
