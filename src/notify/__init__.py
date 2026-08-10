"""The notification tier: what happened, told to the operator, at zero token cost.

**No model is involved in a notification, ever** (R17, AD-28). Bodies are rendered
from SQL in ``renderers.py``; the decision to send is a deterministic table in
:mod:`src.notify.service`. That is not an optimisation -- it is the reason this
package exists as code rather than as an agent skill. ``docs/22`` §7 adjudicated
it directly: a ``telegram-notifier`` skill *"would make every notification cost a
model call; today they cost nothing"*, and roughly thirty messages a month would
become the most frequent metered call in the system.

The consequence worth stating: notifications keep arriving when every AI budget is
exhausted. A cost control that silenced alerts would be switched off.

This module is the package's public surface and nothing else -- one import site
for callers, so a later stage can move a definition between modules without
editing every caller. The boundary fences that constrain the package live in
``tests/test_boundaries.py``; one of them, grep fence 3 (R4), had been claimed as
a universal acceptance criterion since P1 and did not exist until P7 wrote it.

Specification: ``docs/34-implementation-plan.md`` §P7 ·
``docs/P7-IMPLEMENTATION-REVIEW.md`` · ``docs/P7-DECISION-ANALYSIS.md``.
"""

from __future__ import annotations

from src.notify.renderers import RENDERERS, render
from src.notify.service import (
    DISPATCH_ORDER,
    EVENT_KINDS,
    FAILED_EVENT,
    GATE_NUMBERS,
    POLICY,
    QUIET_HOURS_EXEMPT,
    SENT_EVENT,
    TRANSITION_KINDS,
    Decision,
    Kind,
    NotificationService,
    NotifySettings,
    Sent,
    decide,
    hash_chat_id,
    parse_quiet_window,
    quiet_hours,
)

__all__ = [
    "DISPATCH_ORDER",
    "EVENT_KINDS",
    "FAILED_EVENT",
    "GATE_NUMBERS",
    "POLICY",
    "QUIET_HOURS_EXEMPT",
    "RENDERERS",
    "SENT_EVENT",
    "TRANSITION_KINDS",
    "Decision",
    "Kind",
    "NotificationService",
    "NotifySettings",
    "Sent",
    "decide",
    "hash_chat_id",
    "parse_quiet_window",
    "quiet_hours",
    "render",
]
