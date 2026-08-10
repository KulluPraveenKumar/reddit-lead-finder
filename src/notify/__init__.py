"""The notification tier: what happened, told to the operator, at zero token cost.

**No model is involved in a notification, ever** (R17, AD-28). Bodies are rendered
from SQL in :mod:`src.notify.renderers`; the decision to send is a deterministic
table in :mod:`src.notify.service`. That is not an optimisation -- it is the reason
this package exists as code rather than as an agent skill. ``docs/22`` §7 adjudicated
it directly: a ``telegram-notifier`` skill *"would make every notification cost a
model call; today they cost nothing"*, and roughly thirty messages a month would
become the most frequent metered call in the system.

The consequence worth stating: notifications keep arriving when every AI budget is
exhausted. A cost control that silenced alerts would be switched off.

**This module ships before the code it constrains.** P7 Stage 1 creates the package
and its boundary fences and nothing else, because ``PHASE-06-HANDOVER`` §5 T1 says
to establish the fence in the first commit *"as P5 did for src/discovery/ --
retrofitting is far more expensive"*. The fences live in
``tests/test_boundaries.py``; one of them, grep fence 3 (R4), had been claimed as a
universal acceptance criterion since P1 and did not exist.

Specification: ``docs/34-implementation-plan.md`` §P7 ·
``docs/P7-IMPLEMENTATION-REVIEW.md`` · ``docs/P7-DECISION-ANALYSIS.md``.
"""

from __future__ import annotations

from enum import StrEnum


class Kind(StrEnum):
    """The five notification kinds.

    ``ARCHITECTURE_FREEZE`` §7 fixes first delivery at **five** (target nine) and
    names none of them, and the three documents that do name them disagree:
    ``docs/22`` §4.12 lists six, ``docs/21`` §7.1 lists seven, and ``docs/34`` §P7
    task 5 names ``run.failed``, which appears in neither. So the five were chosen,
    on one criterion: **every kind must have a live emitter at revision 0005**, so
    that every policy row is driven by a test rather than merely covered. P6's F1 is
    the reason that matters -- coverage reported 87% on a branch nothing could
    reach, and only a surviving mutation found it.

    Three candidates were dropped for having no data source yet, each recorded with
    the trigger that would bring it back (``docs/P7-DECISION-ANALYSIS.md`` D2):

    * ``lead.high_confidence`` -- needs ``leads.confidence_score``, added in ``0006``
      and populated in P21. Its config key ``min_confidence_alert`` is deliberately
      **not** shipped: P6's ``density_threshold`` note is the precedent, *"a key
      nothing reads is a documented capability that does not exist"*.
    * ``quality.red`` -- needs ``quality_snapshots``, revision ``0010``.
    * ``budget.warning`` -- needs an 80%-of-cap signal. ``src/ai/cost.py`` raises at
      100% only, and nothing spends anything before P19.

    Values are the ``run_events.event`` strings, so a kind and the timeline row that
    carries it are the same identifier. Dedup rides on ``run_events`` plus the
    transition guard (AD-29); there is no ``notification_log`` table, which was
    withdrawn.
    """

    #: A run reached COMPLETE. Dispatched by ``finalize_run`` the moment its
    #: terminal transition commits, which is what makes the "within 10 s"
    #: criterion measurable.
    RUN_COMPLETE = "run.complete"

    #: A run reached FAILED. ``RunService.fail()`` is the only transition into that
    #: state, and it is reachable from a web route -- so delivery is handed to the
    #: worker rather than performed in the request (D7, R8).
    RUN_FAILED = "run.failed"

    #: A run is waiting at a review gate. P7 ships the kind and a thin renderer;
    #: the rich card -- counts, rejects, estimate, deep link -- is P18's, which is
    #: the first phase with candidates to count.
    GATE_REACHED = "gate.reached"

    #: Egress degraded during this run. Keyed on a **recorded degradation**, not on
    #: ``healthy < 3`` as ``docs/22`` §4.12 specified: the shipped config ships no
    #: proxy file at all (P0 measured direct as better and recommended buying
    #: none), so the pool is legitimately empty and a level-based rule would fire
    #: on every run forever. An alert that always fires gets the tier switched off.
    PROXY_POOL_DEGRADED = "proxy.pool_degraded"

    #: A watermark overflowed and posts could have been lost. R19 makes this an
    #: **error**, never a silent gap, and P6 built the per-subreddit detection and
    #: named ``overflowed_subreddits`` as what an alert should list.
    DISCOVERY_OVERFLOW = "discovery.overflow"


__all__ = ["Kind"]
