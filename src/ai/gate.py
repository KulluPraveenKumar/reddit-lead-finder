"""PreAIGate — the only path to the AI service.

The rules land in Phase 6, when there is scraped content to apply them to. What
exists now is the **boundary and its accounting**: every rejection is counted by
reason, because a gate whose statistics are invisible is a gate nobody will ever
tune, and aggressive filtering without measurement is indistinguishable from
quality loss.

The eleven reasons are fixed here rather than in Phase 6 so the counters, the UI,
and the holdout audit all agree on the vocabulary from the start.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class RejectionReason:
    """The eleven counted reasons (docs/06c §3.2)."""

    ALREADY_ANALYZED = "already_analyzed"
    DUPLICATE_EXACT = "duplicate_exact"
    DUPLICATE_NEAR = "duplicate_near"
    NEGATIVE_TERM = "negative_term"
    STRUCTURAL_NOISE = "structural_noise"
    TOO_SHORT = "too_short"
    BOT_OR_DELETED = "bot_or_deleted"
    OUT_OF_WINDOW = "out_of_window"
    DOWNVOTED = "downvoted"
    BELOW_PRESCORE = "below_prescore"
    BUDGET_EXHAUSTED = "budget_exhausted"

    ALL = (
        ALREADY_ANALYZED,
        DUPLICATE_EXACT,
        DUPLICATE_NEAR,
        NEGATIVE_TERM,
        STRUCTURAL_NOISE,
        TOO_SHORT,
        BOT_OR_DELETED,
        OUT_OF_WINDOW,
        DOWNVOTED,
        BELOW_PRESCORE,
        BUDGET_EXHAUSTED,
    )

    #: Never sampled by the holdout audit: these rejections are provably
    #: correct, and auditing them would spend calls proving arithmetic works.
    NEVER_AUDITED = (
        ALREADY_ANALYZED,
        DUPLICATE_EXACT,
        DUPLICATE_NEAR,
        BUDGET_EXHAUSTED,
    )


@dataclass
class GateDecision:
    admitted: bool
    reason: str | None = None
    detail: str | None = None


@dataclass
class GateReport:
    considered: int = 0
    admitted: int = 0
    rejected: int = 0
    reasons: Counter = field(default_factory=Counter)

    def record(self, decision: GateDecision) -> None:
        self.considered += 1
        if decision.admitted:
            self.admitted += 1
        else:
            self.rejected += 1
            self.reasons[decision.reason or "unknown"] += 1

    @property
    def admission_rate(self) -> float:
        return self.admitted / self.considered if self.considered else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "admitted": self.admitted,
            "rejected": self.rejected,
            "admission_rate": round(self.admission_rate, 4),
            # All eleven, including zeros. A reason that never appears is
            # information — it usually means a rule is not wired up.
            "reasons": {reason: self.reasons.get(reason, 0) for reason in RejectionReason.ALL},
        }


class PreAIGate:
    """Nothing reaches a provider without passing through here.

    Phase 1 ships the boundary and its accounting; Phase 6 adds the rules. The
    default is *admit*, because an empty gate that silently rejected everything
    would look identical to a working pipeline with nothing to do.
    """

    def __init__(self, rules: list[Any] | None = None):
        self.rules = rules or []
        self.report = GateReport()

    def evaluate(self, item: Any) -> GateDecision:
        for rule in self.rules:
            decision = rule(item)
            if decision is not None and not decision.admitted:
                self.report.record(decision)
                return decision
        decision = GateDecision(admitted=True)
        self.report.record(decision)
        return decision

    def filter(self, items: list[Any]) -> tuple[list[Any], list[tuple[Any, GateDecision]]]:
        admitted: list[Any] = []
        rejected: list[tuple[Any, GateDecision]] = []
        for item in items:
            decision = self.evaluate(item)
            if decision.admitted:
                admitted.append(item)
            else:
                rejected.append((item, decision))
        return admitted, rejected

    def reset(self) -> None:
        self.report = GateReport()
