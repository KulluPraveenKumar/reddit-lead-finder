"""Funnel — the run's counters, and the one place two vocabularies are reconciled.

[34 §P11](../../docs/34-implementation-plan.md) task 2: *"Funnel counts to
``run_events`` and the progress page."* [06c §3.2](../../docs/06c-local-first-pipeline.md):
*"Every reason is counted, persisted on the run, and rendered. A gate whose
statistics are invisible is a gate nobody will ever tune."*

⚠ **[DI23](../../docs/DEFERRED-IMPROVEMENTS.md) lands here, and P11 is the phase
that must render two disagreeing vocabularies on one page.**

| Module | Phase | Reasons | Status |
|---|---|---|---|
| ``src/discovery/triage.py`` | P6 | **9** | live, counting into ``run_events`` |
| ``src/rules/`` + ``src/dedupe/`` + ``src/scoring/`` | P9, P10, P11 | **8** | live from this phase |
| ``src/ai/gate.py::RejectionReason`` | P1 | **11** | declared, still no writer |

The two live vocabularies genuinely disagree: triage says ``bot_author`` where
the rules say ``bot_or_deleted``, and it splits structural noise five ways
(``hiring``, ``giveaway``, ``megathread``, ``ama``, ``engagement_bait``) where
the rules report one ``structural_noise`` and carry the granularity in
``RuleResult.detail``.

**They are reconciled for DISPLAY and nothing else.** :data:`TRIAGE_TO_GATE`
maps triage's nine onto the eleven; neither module's writes change. That
restraint is the point rather than timidity — converging the *writers* would
change P6's shipped behaviour on a live path, which is precisely what DI23 says
must not happen in passing, and [freeze §11](../../docs/ARCHITECTURE_FREEZE.md)
would need a failed measurement rather than an argument. The mapping is asserted
against both sides by ``tests/test_rules_vocabulary.py``, the one file permitted
to import them all.

**Stages are counted separately and never summed into one number.** A metadata
rejection and a full-stage rejection are different facts about different
populations — the first saw a title, the second saw a body — and a single
"rejected" total would let a triage regression hide inside a full-stage
improvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import STAGE_FULL, STAGE_METADATA

#: ``src/discovery/triage.py``'s nine reasons, mapped onto ``src/ai/gate.py``'s
#: eleven. **Display only.** Every value here is spelled to match
#: ``RejectionReason`` and is deliberately not imported from it — R3 forbids the
#: import from inside this fence, the same constraint P9 and P10 both worked
#: under.
#:
#: The five structural reasons collapse to one ``structural_noise`` **and keep
#: their own name as the detail**, which is P9's operator decision D3 applied to
#: P6's data: *"5-12% structural noise" is not something an operator can act on;
#: "8% megathread, 1% hiring" is.*
TRIAGE_TO_GATE: dict[str, str] = {
    "no_title": "too_short",
    "bot_author": "bot_or_deleted",
    "hiring": "structural_noise",
    "giveaway": "structural_noise",
    "megathread": "structural_noise",
    "ama": "structural_noise",
    "engagement_bait": "structural_noise",
    "out_of_window": "out_of_window",
    "negative_term": "negative_term",
}

#: Which triage reasons carry their own name through as the sub-reason.
_KEEPS_DETAIL = frozenset({"hiring", "giveaway", "megathread", "ama", "engagement_bait"})

#: The ``run_events.event`` name the funnel payload is stored under.
#:
#: Defined **here** rather than in the handler that writes it, so that
#: ``RunService.progress`` can read the row without importing an orchestration
#: handler — which would be a cycle, because the handlers import ``RunService``.
#: The writer and the reader agree on one constant instead of two literals.
FUNNEL_EVENT = "pipeline.funnel"


def to_gate_vocabulary(reason: str) -> tuple[str, str | None]:
    """``("structural_noise", "hiring")`` — the counted reason and its detail.

    An **unmapped** reason passes through unchanged with no detail rather than
    being dropped or renamed to ``unknown``. Dropping it would make the funnel
    under-report by exactly the amount nobody noticed — the failure
    ``src.rules.reject``'s guard exists to prevent — and a run whose counters do
    not sum is the one thing task 2's acceptance line checks by hand.
    """
    mapped = TRIAGE_TO_GATE.get(reason)
    if mapped is None:
        return reason, None
    return mapped, (reason if reason in _KEEPS_DETAIL else None)


@dataclass
class FunnelStage:
    """One stage's counters. ``collected`` is the denominator every rate uses."""

    stage: str
    collected: int = 0
    admitted: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    detail_by_reason: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def rejected(self) -> int:
        return sum(self.rejected_by_reason.values())

    def count(self, reason: str, *, detail: str | None = None, n: int = 1) -> None:
        """Record ``n`` rejections for ``reason``, keeping the sub-reason underneath."""
        mapped, mapped_detail = to_gate_vocabulary(reason)
        detail = detail or mapped_detail
        self.rejected_by_reason[mapped] = self.rejected_by_reason.get(mapped, 0) + n
        if detail:
            bucket = self.detail_by_reason.setdefault(mapped, {})
            bucket[detail] = bucket.get(detail, 0) + n

    def admit(self, n: int = 1) -> None:
        self.admitted += n

    def sums(self) -> bool:
        """``admitted + rejected == collected``. **The funnel's own arithmetic.**

        [35 §6](../../docs/35-testing-strategy.md)'s P11 row makes this the
        manual guide's headline check — *"Read the funnel counts on the run page;
        they sum correctly"* — so it is asserted in code as well, rather than
        left for a human to add up. A funnel that does not sum has lost items
        somewhere between the gate and the counter, and that loss is invisible in
        every other view.
        """
        return self.admitted + self.rejected == self.collected

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "collected": self.collected,
            "admitted": self.admitted,
            "rejected": self.rejected,
            "rejected_by_reason": dict(sorted(self.rejected_by_reason.items())),
            "detail_by_reason": {
                k: dict(sorted(v.items())) for k, v in sorted(self.detail_by_reason.items())
            },
            "sums": self.sums(),
        }


@dataclass
class FunnelReport:
    """Both stages, the hard-filter rate (A2), the collapse rate, and the miss rate.

    This is what reaches ``run_events`` and ``/api/runs/<id>/progress``. It is a
    value object with no session, for the reason ``NetworkPolicy`` accumulates
    notices as values: the thing that measures must not be the thing that holds
    a write lock across a fetch.
    """

    metadata: FunnelStage = field(default_factory=lambda: FunnelStage(STAGE_METADATA))
    full: FunnelStage = field(default_factory=lambda: FunnelStage(STAGE_FULL))
    #: Items removed by the dedup cascade, and the intra-run collapse rate —
    #: the measurement transferred to P11 from P10 (freeze §11.1).
    grouped: int = 0
    groups: int = 0
    #: The holdout report, as `MissRate.to_dict()`, or None when nothing was sampled.
    holdout: dict[str, object] | None = None

    @property
    def hard_filter_rate(self) -> float | None:
        """**A2** — the share of collected items the *hard filters* remove.

        [27 §10](../../docs/27-architecture-review.md) assumes **~73%** and marks
        it *"❓ Sprint 3, on real data"*. This is that measurement.

        ⚠ **``below_prescore`` is deliberately excluded from the numerator.** It
        is [06c §3.2](../../docs/06c-local-first-pipeline.md)'s *"tunable dial"*,
        not a hard filter — folding it in would let an operator move A2 by
        editing one config key, and a structural rate you can tune is not a
        measurement of anything. ``None`` when nothing was collected: a rate over
        zero items is not 0%, it is undefined, and reporting 0% would read as
        *"the filters removed nothing"*.
        """
        denominator = self.full.collected
        if denominator <= 0:
            return None
        hard = self.full.rejected - self.full.rejected_by_reason.get("below_prescore", 0)
        return hard / denominator

    @property
    def collapse_rate(self) -> float | None:
        """The **intra-run** collapse rate — P10's transferred measurement.

        [PHASE-10-HANDOVER §4 T1](../../docs/PHASE-10-HANDOVER.md): P10 measured
        **5.74%** against a *"> 8%"* target on the stored archive, and **flat all
        the way down to a 0.60 threshold**, so the shortfall is not
        under-detection and *"do not tune ``jaccard_threshold`` to reach a
        number"*. P11 has the first live call site, so it measures the intra-run
        quantity the target was always about. **Reported, never tuned for.**
        """
        if self.full.collected <= 0:
            return None
        return self.grouped / self.full.collected

    def to_dict(self) -> dict[str, object]:
        return {
            "metadata": self.metadata.to_dict(),
            "full": self.full.to_dict(),
            "grouped": self.grouped,
            "groups": self.groups,
            "collapse_rate": _round(self.collapse_rate),
            "hard_filter_rate": _round(self.hard_filter_rate),
            "hard_filter_rate_assumed": 0.73,
            "holdout": self.holdout,
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


__all__ = [
    "FUNNEL_EVENT",
    "TRIAGE_TO_GATE",
    "FunnelReport",
    "FunnelStage",
    "to_gate_vocabulary",
]
