"""Orchestration: the persisted run state machine and durable job queue.

P1 shipped the *vocabulary* — states, transitions, and the three tables that hold
them. P2 adds the *runtime*: a queue that claims work with a lease, a worker that
executes it, and a handler registry. The service and API that drive it arrive in
P3, so nothing here is reachable from a web route yet.

The package still depends on neither ``src.ai`` nor ``src.scrapers``: a queue
that knew what its jobs did would have to change every time a stage did.

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
    "GATE_STATES",
    "JOB_TRANSITIONS",
    "MAX_ATTEMPTS",
    "REGISTRY",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "Handler",
    "IllegalTransition",
    "JobQueue",
    "JobState",
    "RetryableError",
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
