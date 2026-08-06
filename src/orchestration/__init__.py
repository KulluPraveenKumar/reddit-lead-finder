"""Orchestration: the persisted run state machine and durable job queue.

P1 ships the *vocabulary* — states, transitions, and the three tables that hold
them. The queue and worker that act on it arrive in P2, and the service and API
that drive it in P3. Nothing in this package executes work yet, which is why it
has no dependency on ``src.ai``, ``src.net`` or ``src.scrapers``.

Specification: ``docs/04-system-design.md`` §1-3, ``docs/13-phase-03.md``.
"""

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

__all__ = [
    "GATE_STATES",
    "JOB_TRANSITIONS",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "IllegalTransition",
    "JobState",
    "RunState",
    "assert_job_transition",
    "assert_transition",
    "can_transition",
    "is_gate",
    "is_terminal",
]
