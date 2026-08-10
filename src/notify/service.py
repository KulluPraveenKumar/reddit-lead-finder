"""The deterministic policy: given an event and a clock, notify or suppress.

Everything here is a **pure function of its arguments**. No session, no network,
no clock of its own, no model. ``now`` is passed in rather than read, which is
what makes quiet hours testable at a boundary minute instead of at whatever time
the suite happens to run.

That purity is the point rather than a style preference. ``docs/22`` §4.12
describes a ``notify-policy`` skill that would ask a model about the *"~5%"* of
events a deterministic table cannot classify. **R17 admits no five per cent** --
*"notifications never invoke a model"* -- and AD-28 is equally flat: *"No model
is involved in a notification, ever"* (``docs/21`` §7.1). So the table below
covers **100%** of events, and the residual class that §4.12 routes to a model is
handled by the row §4.12 itself supplies last: *everything else -> Suppress*. No
ambiguity path exists, and ``tests/test_boundaries.py`` fences the package
against ever growing one.

**What this module deliberately does not do.** It does not read the database,
render a body, choose a transport, or send anything. ``decide`` answers one
question and returns; the caller acts. Splitting it this way is what lets the
whole policy be tested without a database at all.

``decide`` is a module-level function rather than a method on the service class
sketched in ``docs/P7-IMPLEMENTATION-REVIEW.md`` §8. The service needs a
``Session``; the policy does not, and giving it one would make every policy test
build a database to answer a question about arithmetic on a payload. The service
arrives with the dispatcher and delegates here.

Specification: ``docs/34-implementation-plan.md`` §P7 tasks 1 and 5 ·
``docs/22-hermes-skills.md`` §4.12 · ``docs/P7-DECISION-ANALYSIS.md`` D2, D2b, D5.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum
from typing import Any


class Kind(StrEnum):
    """The five notification kinds.

    ``ARCHITECTURE_FREEZE`` §7 fixes first delivery at **five** (target nine) and
    names none of them, and the three documents that do name them disagree:
    ``docs/22`` §4.12 lists six, ``docs/21`` §7.1 lists seven, and ``docs/34``
    §P7 task 5 names ``run.failed``, which appears in neither. So the five were
    chosen, on one criterion: **every kind must have a live emitter at revision
    0005**, so that every policy row is driven by a test rather than merely
    covered. P6's F1 is the reason that matters -- coverage reported 87% on a
    branch nothing could reach, and only a surviving mutation found it.

    Three candidates were dropped for having no data source yet, each recorded
    with the trigger that would bring it back (DEFERRED-IMPROVEMENTS DI16):

    * ``lead.high_confidence`` -- needs ``leads.confidence_score``, added in
      ``0006`` and populated in P21. Its config key ``min_confidence_alert`` is
      deliberately **not** shipped: P6's ``density_threshold`` note is the
      precedent, *"a key nothing reads is a documented capability that does not
      exist"*.
    * ``quality.red`` -- needs ``quality_snapshots``, revision ``0010``.
    * ``budget.warning`` -- needs an 80%-of-cap signal. ``src/ai/cost.py`` raises
      at 100% only, and nothing spends anything before P19.

    Values are the ``run_events.event`` strings, so a kind and the timeline row
    that carries it are the same identifier. Dedup rides on ``run_events`` plus
    the transition guard (AD-29); there is no ``notification_log`` table, which
    was withdrawn.
    """

    #: A run reached COMPLETE.
    RUN_COMPLETE = "run.complete"

    #: A run reached FAILED. ``RunService.fail()`` is the only transition into
    #: that state, and it is reachable from a web route -- so delivery is handed
    #: to the worker rather than performed in the request (D7, R8).
    RUN_FAILED = "run.failed"

    #: A run is waiting at a review gate. The rich card -- counts, rejects,
    #: estimate, deep link -- is P18's, which is the first phase with candidates
    #: to count.
    GATE_REACHED = "gate.reached"

    #: Egress degraded during this run. Keyed on a **recorded degradation**, not
    #: on ``healthy < 3`` as ``docs/22`` §4.12 specified -- see :data:`POLICY`.
    PROXY_POOL_DEGRADED = "proxy.pool_degraded"

    #: A watermark overflowed and posts could have been lost. R19 makes this an
    #: **error**, never a silent gap.
    DISCOVERY_OVERFLOW = "discovery.overflow"


#: Kinds that quiet hours may **never** suppress.
#:
#: ``docs/34`` §P7 task 5 exempts ``run.failed`` and ``budget.warning``.
#: ``budget.warning`` is not a shipped kind (D2), so its exemption has nothing to
#: apply to and ``discovery.overflow`` takes the vacated slot: **R19 makes
#: overflow an error**, and an error held back until morning is precisely the
#: silent gap R19 exists to forbid.
#:
#: ``gate.reached`` is deliberately **not** exempt. A gate waits indefinitely by
#: design -- AD-6, and ``runs`` has no expiry column, asserted by
#: ``check_schema.py`` -- so nothing is lost by it arriving after breakfast.
QUIET_HOURS_EXEMPT: frozenset[Kind] = frozenset({Kind.RUN_FAILED, Kind.DISCOVERY_OVERFLOW})

#: ``HH:MM-HH:MM``. Anchored, so trailing rubbish is rejected rather than ignored.
_WINDOW = re.compile(r"^(?P<h1>\d{1,2}):(?P<m1>\d{2})\s*-\s*(?P<h2>\d{1,2}):(?P<m2>\d{2})$")


@dataclass(frozen=True, slots=True)
class Decision:
    """The answer, and the one-line reason ``docs/22`` §4.12 asks for.

    Frozen because a decision that could be edited after the fact would make the
    reason and the outcome capable of disagreeing -- and the reason is the only
    part an operator reads when asking "why did I not get told?".
    """

    notify: bool
    reason: str

    def __bool__(self) -> bool:
        return self.notify


def parse_quiet_window(raw: str | None) -> tuple[time, time] | None:
    """``"22:00-07:00"`` -> ``(time(22, 0), time(7, 0))``. ``None`` means none.

    A **string** rather than ``docs/21`` §13's unstated shape or a ``[22, 7]``
    pair: the format was specified nowhere, and P6's F4 is that *"an unspecified
    constant is a decision, and it belongs in the docstring"*. One readable value
    in a committed file, unambiguous when the window wraps midnight -- which is
    the case a pair of bare hours makes easy to get wrong, and which the tests
    pin at both boundary minutes.

    Raises :class:`ValueError` on anything unparseable. **Loudly, at load.** A
    quiet-hours setting that was silently ignored because it was mistyped would
    send exactly the 3 a.m. message it was added to prevent, and the operator
    would have no way to tell it had not been applied.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    match = _WINDOW.match(text)
    if match is None:
        raise ValueError(
            f"notify.quiet_hours_utc must look like '22:00-07:00' (UTC), got {raw!r}. "
            "Leave it unset for no quiet hours."
        )
    try:
        start = time(int(match["h1"]), int(match["m1"]))
        end = time(int(match["h2"]), int(match["m2"]))
    except ValueError as exc:  # 25:00, 07:99
        raise ValueError(f"notify.quiet_hours_utc has an impossible time: {raw!r} ({exc})") from exc
    return start, end


def quiet_hours(window: tuple[time, time] | None, now: datetime) -> bool:
    """Is ``now`` inside ``window``? UTC throughout.

    Handles the wrapping case, which is the normal one: ``22:00-07:00`` is two
    intervals on a clock face, not one, so a naive ``start <= t < end`` is false
    for every minute of the night it is supposed to cover.

    **Half-open, ``[start, end)``.** With ``22:00-07:00``, 22:00 is quiet and
    07:00 is not -- so the window is exactly as long as it reads, and a window
    whose ends are equal is empty rather than eternal. Both boundary minutes are
    asserted; an off-by-one here silences an alert for a minute a year, which is
    the kind of defect that is never found by looking.
    """
    if window is None:
        return False

    start, end = window
    if start == end:
        return False

    moment = now.astimezone(UTC).time() if now.tzinfo is not None else now.time()
    if start < end:
        return start <= moment < end
    # Wraps midnight: quiet from `start` to 23:59:59.999999 and from 00:00 to `end`.
    return moment >= start or moment < end


@dataclass(frozen=True, slots=True)
class NotifySettings:
    """The ``notify:`` block, validated.

    Both defaults are **off**, and that is load-bearing rather than cautious.
    ``notify.enabled: false`` is the phase's documented rollback
    (``docs/34`` §P7), so shipping it as the default makes the rollback state the
    state every test run and every fresh install already exercises -- rather than
    something proved once during a drill. A tier that began messaging a chat id
    nobody configured, on upgrade, is also a worse first impression than one that
    waits to be asked.

    ``min_confidence_alert`` is **absent on purpose**, not forgotten: it
    configures a threshold against ``leads.confidence_score``, which does not
    exist until ``0006``. See :class:`Kind` and DI16.
    """

    enabled: bool = False
    transport: str = "null"
    telegram_chat_id: str | None = None
    quiet_window: tuple[time, time] | None = None

    @classmethod
    def from_config(cls, raw: Mapping[str, Any] | None) -> NotifySettings:
        """Build from the parsed ``notify:`` mapping. ``None`` or ``{}`` -> defaults.

        Deleting the whole block from ``config.yaml`` must reproduce these
        defaults exactly -- the same property the ``discovery:`` block documents
        for itself, so that a rollback by deletion behaves identically to a
        rollback by flag.
        """
        data = raw or {}
        chat_id = data.get("telegram_chat_id")
        return cls(
            enabled=bool(data.get("enabled", False)),
            transport=str(data.get("transport", "null")),
            telegram_chat_id=None if chat_id is None else str(chat_id),
            quiet_window=parse_quiet_window(data.get("quiet_hours_utc")),
        )


def _count(payload: Mapping[str, Any], key: str) -> int:
    """A non-negative integer from a payload that arrived as JSON.

    ``run_events.data_json`` round-trips through JSON, so a count can reach here
    as ``None``, as a string, or absent. Coercing to 0 rather than raising is
    deliberate: a malformed payload must not be able to stop a *failure* alert.
    """
    value = payload.get(key)
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _run_complete(payload: Mapping[str, Any]) -> Decision:
    """``docs/22`` §4.12: *"Notify if leads > 0 or the run failed."*

    The second clause survives the split that gave failure its own kind: a run
    can reach COMPLETE having collected nothing *because* subreddits failed, and
    ``finalize_run`` already records that as ``run.partial``. Suppressing it
    would hide the one 0-lead run that has something wrong with it.

    A clean run that genuinely found nothing is suppressed. Being told "0 leads"
    every night is how an operator learns to ignore the channel.
    """
    leads = _count(payload, "leads")
    shortfall = _count(payload, "subreddits_failed") + _count(payload, "subreddits_cancelled")

    if leads > 0:
        return Decision(True, f"{leads} lead(s) collected")
    if shortfall > 0:
        return Decision(True, f"no leads, and {shortfall} subreddit(s) did not finish")
    return Decision(False, "the run completed cleanly and found nothing")


def _run_failed(_payload: Mapping[str, Any]) -> Decision:
    """Always. This is the one thing the operator most needs to be told."""
    return Decision(True, "the run failed")


def _gate_reached(payload: Mapping[str, Any]) -> Decision:
    """Always -- ``docs/22`` §4.12. A gate waits for a human, so it must reach one."""
    gate = payload.get("gate")
    return Decision(True, f"gate {gate} is waiting for approval" if gate else "a gate is waiting")


def _proxy_pool_degraded(payload: Mapping[str, Any]) -> Decision:
    """A degradation that **happened**, not a pool that is small.

    ``docs/22`` §4.12 says *"notify if healthy < 3"*. That rule fires on every
    run forever under the shipped configuration: ``config.yaml`` ships
    ``proxy.file: ''`` with ``allow_empty: true`` and says so in its own comment
    -- *"the pool comes up empty and egress goes direct"* -- because P0 measured
    direct as better on every dimension and recommended buying no proxies. With
    no pool, ``healthy`` is 0, and ``0 < 3`` is a permanent alarm about the
    design working as intended.

    So the trigger is P4's buffered degradation notices, which exist for exactly
    this and are already rendered on ``/health``. An event is actionable; a level
    is a description of the operator's own configuration. Recorded as D2b.
    """
    degradations = _count(payload, "degradations")
    if degradations > 0:
        return Decision(True, f"egress degraded {degradations} time(s) during this run")
    return Decision(False, "no degradation was recorded during this run")


def _discovery_overflow(payload: Mapping[str, Any]) -> Decision:
    """Always. R19: overflow is an **error**, never a silent gap.

    The reason line names the subreddits, because overflow is a *per-subreddit*
    fact -- P6's G5 -- and "discovery overflowed" without saying where leaves the
    operator no action to take.
    """
    subs = payload.get("overflowed_subreddits")
    if isinstance(subs, list | tuple) and subs:
        named = ", ".join(f"r/{s}" for s in subs)
        return Decision(True, f"watermark overflow on {named} -- posts may have been missed")
    return Decision(True, "watermark overflow -- posts may have been missed")


#: The deterministic table. ``docs/34`` §P7 task 1.
#:
#: One row per kind, and **every row is exercised by a test that drives it**
#: rather than merely reaching it. That distinction is P6's F1: coverage reported
#: 87% on a file whose branch nothing could reach, and only a surviving mutation
#: found the defect. Selecting the five kinds on "has a live emitter at 0005"
#: (D2) is what makes driving every row possible at all.
POLICY: dict[Kind, Callable[[Mapping[str, Any]], Decision]] = {
    Kind.RUN_COMPLETE: _run_complete,
    Kind.RUN_FAILED: _run_failed,
    Kind.GATE_REACHED: _gate_reached,
    Kind.PROXY_POOL_DEGRADED: _proxy_pool_degraded,
    Kind.DISCOVERY_OVERFLOW: _discovery_overflow,
}


def decide(
    kind: Kind | str,
    payload: Mapping[str, Any] | None = None,
    *,
    settings: NotifySettings,
    now: datetime,
) -> Decision:
    """Notify or suppress. Deterministic, side-effect free, no model.

    ``kind`` accepts a bare string as well as a :class:`Kind` because the caller
    reads ``run_events``, where most rows are not notification kinds at all.
    Anything unrecognised is **suppressed**, which is ``docs/22`` §4.12's own
    last row -- *everything else -> Suppress* -- and is what makes the table
    total rather than leaving a residue for a model to adjudicate (R17).

    Order is load-bearing:

    1. **Disabled** wins over everything. The rollback must be absolute; a kind
       marked exempt from quiet hours must not leak past the off switch.
    2. **The policy row** decides on the merits.
    3. **Quiet hours** may only ever turn a yes into a no, and never for a kind
       in :data:`QUIET_HOURS_EXEMPT`.

    A suppression here is not a discarded notification. Nothing is recorded as
    sent, so a message held back by quiet hours is delivered by a later pass --
    which is why step 3 must not be mistaken for a filter.
    """
    if not settings.enabled:
        return Decision(False, "notifications are disabled (notify.enabled is false)")

    try:
        resolved = Kind(kind)
    except ValueError:
        return Decision(False, f"{kind!r} is not a notification kind")

    decision = POLICY[resolved](payload or {})
    if not decision.notify:
        return decision

    if resolved not in QUIET_HOURS_EXEMPT and quiet_hours(settings.quiet_window, now):
        return Decision(False, f"{decision.reason}, but quiet hours are in effect")

    return decision
