"""Run and job states, and the transitions between them.

**Why this is a table and not a set of `if` statements.** The defining feature of
this pipeline is that it *stops* in the middle and waits for a human
(``docs/01`` §3). A run may sit at a gate for a week, across process restarts.
That makes the legal-transition set part of the schema's meaning rather than a
detail of whichever function happens to advance a run, and it makes an illegal
transition a *bug worth raising loudly* rather than a silently absorbed no-op.

Two properties are load-bearing and are asserted in ``tests/test_orchestration.py``:

1. **The two gate states have no timeout.** Not a long one — none. A gate that
   expires is a gate that silently proceeds without the human it exists to wait
   for, which would defeat the quality mechanism the whole design is built on.
   Nothing here or in ``runs`` carries an expiry, and that absence is deliberate.
2. **Every transition is validated before it is written.** ``assert_transition``
   names both states in its error, because "illegal transition" without them is
   unactionable at 3am.

Specification: ``docs/04-system-design.md`` §1.1-1.2.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

_E = TypeVar("_E", bound=StrEnum)


class RunState(StrEnum):
    """The twelve states a run can occupy.

    ``docs/34`` §P1 says eleven; ``docs/04`` §1.1 lists twelve and is the
    specification. Recorded in ``docs/PHASE-01-HANDOVER.md`` as a documentation
    defect rather than silently resolved either way.
    """

    PENDING = "pending"
    PROFILING = "profiling"  # website -> BKB
    DISCOVERING = "discovering"  # subreddit candidates + validation
    AWAITING_SUBREDDIT_REVIEW = "awaiting_subreddit_review"  # GATE 1
    GENERATING_KEYWORDS = "generating_keywords"
    AWAITING_KEYWORD_REVIEW = "awaiting_keyword_review"  # GATE 2
    AWAITING_OPTIONS = "awaiting_options"
    SCRAPING = "scraping"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobState(StrEnum):
    """The five states a queued unit of work can occupy."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: The two states where the pipeline waits for a person.
#:
#: They are named as a set rather than checked inline so that "is this a gate?"
#: has exactly one answer in the codebase. **Neither has a timeout** - see the
#: module docstring.
GATE_STATES: frozenset[RunState] = frozenset(
    {
        RunState.AWAITING_SUBREDDIT_REVIEW,
        RunState.AWAITING_KEYWORD_REVIEW,
    }
)

#: States from which no further work happens without an explicit operator action.
#:
#: ``COMPLETE`` and ``FAILED`` are terminal but *re-enterable* (see TRANSITIONS);
#: ``CANCELLED`` is final. Grouping them says "the worker will not pick this up",
#: which is the question the worker actually asks.
TERMINAL_STATES: frozenset[RunState] = frozenset(
    {
        RunState.COMPLETE,
        RunState.FAILED,
        RunState.CANCELLED,
    }
)

#: Legal run transitions. `docs/04` §1.2.
#:
#: Three edges are easy to mistake for errors and are deliberate:
#:
#: * ``AWAITING_SUBREDDIT_REVIEW -> DISCOVERING`` and
#:   ``AWAITING_KEYWORD_REVIEW -> GENERATING_KEYWORDS`` let the operator say
#:   "regenerate these, I don't like them" without starting over.
#: * ``COMPLETE -> ANALYZING`` lets a prompt-version bump re-analyse a finished
#:   run's leads without re-scraping them.
#: * ``FAILED -> PENDING`` is the full retry.
#:
#: ``CANCELLED`` maps to the empty set: cancellation is final. A cancelled run
#: that could be resumed would make "cancel" mean "pause", and the two need
#: different guarantees.
TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.PENDING: frozenset({RunState.PROFILING, RunState.CANCELLED, RunState.FAILED}),
    RunState.PROFILING: frozenset({RunState.DISCOVERING, RunState.FAILED, RunState.CANCELLED}),
    RunState.DISCOVERING: frozenset(
        {RunState.AWAITING_SUBREDDIT_REVIEW, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.AWAITING_SUBREDDIT_REVIEW: frozenset(
        {RunState.GENERATING_KEYWORDS, RunState.DISCOVERING, RunState.CANCELLED}
    ),
    RunState.GENERATING_KEYWORDS: frozenset(
        {RunState.AWAITING_KEYWORD_REVIEW, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.AWAITING_KEYWORD_REVIEW: frozenset(
        {RunState.AWAITING_OPTIONS, RunState.GENERATING_KEYWORDS, RunState.CANCELLED}
    ),
    RunState.AWAITING_OPTIONS: frozenset({RunState.SCRAPING, RunState.CANCELLED}),
    RunState.SCRAPING: frozenset({RunState.ANALYZING, RunState.FAILED, RunState.CANCELLED}),
    RunState.ANALYZING: frozenset({RunState.COMPLETE, RunState.FAILED, RunState.CANCELLED}),
    RunState.COMPLETE: frozenset({RunState.ANALYZING}),
    RunState.FAILED: frozenset({RunState.PENDING}),
    RunState.CANCELLED: frozenset(),
}

#: Legal job transitions. Simpler than runs because a job has no human in it.
#:
#: ``RUNNING -> QUEUED`` is lease reclamation: a worker died holding the job and
#: the queue takes it back. ``FAILED -> QUEUED`` is the retry with backoff.
JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset(
        {JobState.DONE, JobState.FAILED, JobState.QUEUED, JobState.CANCELLED}
    ),
    JobState.DONE: frozenset(),
    JobState.FAILED: frozenset({JobState.QUEUED}),
    JobState.CANCELLED: frozenset(),
}


class IllegalTransition(ValueError):
    """A transition that the state machine does not permit.

    A ``ValueError`` rather than a bespoke base class: callers that want to map
    it to an HTTP 409 catch it by name, and callers that do not should crash.
    """


def assert_transition(current: RunState | str, target: RunState | str) -> None:
    """Raise unless ``current -> target`` is legal.

    Accepts strings so a value read straight from the database can be checked
    without the caller remembering to coerce it - the column is a VARCHAR, and
    forgetting the coercion is exactly the kind of mistake that would make this
    guard silently pass.
    """
    cur, tgt = _coerce(current, RunState), _coerce(target, RunState)
    if tgt not in TRANSITIONS[cur]:
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS[cur])) or "(none - terminal)"
        raise IllegalTransition(
            f"illegal run transition {cur.value} -> {tgt.value}; allowed from {cur.value}: {allowed}"
        )


def assert_job_transition(current: JobState | str, target: JobState | str) -> None:
    """Raise unless ``current -> target`` is legal for a job."""
    cur, tgt = _coerce(current, JobState), _coerce(target, JobState)
    if tgt not in JOB_TRANSITIONS[cur]:
        allowed = ", ".join(sorted(s.value for s in JOB_TRANSITIONS[cur])) or "(none - terminal)"
        raise IllegalTransition(
            f"illegal job transition {cur.value} -> {tgt.value}; "
            f"allowed from {cur.value}: {allowed}"
        )


def can_transition(current: RunState | str, target: RunState | str) -> bool:
    """Non-raising form, for a UI that wants to grey out a button."""
    try:
        assert_transition(current, target)
    except IllegalTransition:
        return False
    return True


def is_gate(state: RunState | str) -> bool:
    """Is the run waiting for a person? Gates never time out."""
    return _coerce(state, RunState) in GATE_STATES


def is_terminal(state: RunState | str) -> bool:
    """Will the worker leave this run alone?"""
    return _coerce(state, RunState) in TERMINAL_STATES


def _coerce(value: _E | str, enum: type[_E]) -> _E:
    """String -> enum, with an error that names the valid values.

    ``KeyError: 'awaiting_review'`` tells the reader nothing. Listing the twelve
    legal values turns a typo into a two-second fix.

    Uses a ``TypeVar`` rather than PEP 695 ``def _coerce[T: StrEnum]``: the
    project floor is Python 3.11 (``pyproject.toml``), and the newer syntax is a
    3.12 feature that ``ruff`` correctly rejects.
    """
    if isinstance(value, enum):
        return value
    try:
        return enum(value)
    except ValueError:
        valid = ", ".join(sorted(m.value for m in enum))
        raise IllegalTransition(f"unknown {enum.__name__} {value!r}; valid: {valid}") from None
