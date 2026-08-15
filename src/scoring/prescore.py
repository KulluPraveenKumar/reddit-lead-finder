"""Pre-score — a deterministic 0–100, every component stored.

[06c §3.1](../../docs/06c-local-first-pipeline.md). The pre-score is a **recall
instrument, not a precision one** — it casts wide and drops only what is
obviously not a lead. Precision is the AI's job, and the AI is four phases away.

```
    prescore(item, settings) -> PreScore
        .total       0-100, deterministic, re-runnable at zero cost
        .components  every one, persisted to prescores.components_json
        .decision    admit | reject
        .reason      below_prescore | out_of_window | <a rule's> | None
```

**Six components ship, three are declared absent** — operator decision **D1**,
see :data:`~src.scoring.ABSENT_COMPONENTS`. **The weights are cited from
[04 §9.1](../../docs/04-system-design.md)** — operator decision **D2**, see
:data:`~src.scoring.WEIGHTS`.

⚠ **This is not ``PreAIGate``, and it must not become it.** It composes P9's
rules, this phase's arithmetic, and nothing else. The budget, the cache, the
adaptive cut and the object that counts eleven reasons are **P19's**, across the
R3 boundary — which is why nothing here returns a ``GateDecision``. The identical
warning stands on ``src.rules.evaluate`` and on ``dedupe.build_groups``
([PHASE-10-HANDOVER §6](../../docs/PHASE-10-HANDOVER.md)); this is the third and
last of the three libraries P19 will compose.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from src.rules import RuleResult, RulesSettings
from src.rules import evaluate as evaluate_rules
from src.rules.keywords import match_tiers

from . import (
    ABSENT_COMPONENTS,
    DECISION_ADMIT,
    DECISION_REJECT,
    PrescoreSettings,
    below_prescore,
    normalised_weights,
    out_of_window,
)
from .features import (
    engagement,
    keyword_density,
    length_plausibility,
    question_form,
    recency_decay,
    tier_value,
)

#: ``PreScore.detail`` when ``pipeline.prescore_enabled`` is false. A named
#: constant rather than a string literal so a test can assert the rollback took
#: the rollback branch, and not merely that the score happened to be 0.0 —
#: which a real item with no keywords, no engagement and a short body also is.
DISABLED = "prescore_disabled"


@dataclass(frozen=True)
class ScoredItem:
    """One candidate, as the pre-score sees it. Neutral: not a ``Lead``.

    The same shape discipline as ``DedupItem``: a plain value object, so the
    scorer is testable from literals and so nothing in this package needs a
    session. ``row_id`` is the stored ``leads.id`` when there is one — the
    holdout path scores an item *before* it is stored and passes ``None``.
    """

    title: str = ""
    body: str = ""
    author: str | None = None
    subreddit: str | None = None
    score: int | None = None
    num_comments: int | None = None
    created_utc: datetime.datetime | None = None
    row_id: int | None = None

    @property
    def text(self) -> str:
        """Title and body as one string, the form the rules and features read."""
        return f"{self.title}\n{self.body}" if self.body else self.title


@dataclass(frozen=True)
class PreScore:
    """A deterministic judgement, its arithmetic, and why.

    ``components`` is stored verbatim in ``prescores.components_json``. It
    carries the **raw 0–1 component values**, not their weighted contributions,
    because [34 §P11](../../docs/34-implementation-plan.md) asks for *"all
    components persisted"* and P21's explanation surface
    ([freeze R7](../../docs/ARCHITECTURE_FREEZE.md)) renders stored computations
    — a stored contribution would bake this phase's weights into a row that
    outlives them, and re-deriving the component from it would be impossible
    once a weight changed.
    """

    total: float
    components: dict[str, float]
    decision: str
    reason: str | None = None
    detail: str | None = None
    #: Which components did not run, and the phase that supplies each. Persisted
    #: alongside the values so a P12 reader can tell "absent" from "scored 0.0"
    #: without knowing which phase they are reading.
    absent: dict[str, str] = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        return self.decision == DECISION_ADMIT


def prescore(
    item: ScoredItem,
    settings: PrescoreSettings,
    *,
    keyword_tiers: Mapping[str, Sequence[str]] | None = None,
    negative_terms: Sequence[str] = (),
    rules: RulesSettings | None = None,
    now: datetime.datetime | None = None,
) -> PreScore:
    """Score one item and decide whether it is worth enriching.

    The order is **cheapest and most certain first**, and it is the order the
    funnel reports:

    1. **The rollback.** ``pipeline.prescore_enabled: false`` admits everything
       with a zero score and no components — items keep ``intent_score`` only,
       which is [34 §P11](../../docs/34-implementation-plan.md)'s Rollback row
       made real inside this package's own boundary. P9's D4 reasoning: a flag
       read only by a call site would have nothing to disable if the call site
       were removed, and [lock §4](../../docs/EXECUTION_MODE_LOCK.md) requires
       the rollback be *executed*, not documented.
    2. **The window.** ``out_of_window`` is one of P11's two reasons. Checked
       before the rules because it is one subtraction and needs no regex.
    3. **P9's four hard filters**, via ``src.rules.evaluate`` — with ``text``
       supplied, which binds ``min_chars`` to a body for the first time.
    4. **The arithmetic**, and the admission floor.

    **A rejected item is still fully scored.** Every branch below computes the
    components before returning, and that is deliberate rather than wasteful:
    [34 §P11](../../docs/34-implementation-plan.md) requires *"every collected
    item has a ``prescores`` row, admitted or not"*, and a row whose components
    are empty because it was rejected early is a row the holdout audit cannot
    compare against. The cost is six arithmetic operations on an item that has
    already been fetched.
    """
    if not settings.enabled:
        # Admitted with no score and no components. The caller skips the stage
        # entirely on the same flag, so no `prescores` row is written and items
        # keep `intent_score` only; this branch is the second half of that pair,
        # so the rollback holds even if a future call site forgets the first.
        return PreScore(0.0, {}, DECISION_ADMIT, detail=DISABLED)

    hits = match_tiers(item.text, dict(keyword_tiers or {}))
    tier_order = list(keyword_tiers or {})

    components = {
        "keyword_tier": tier_value(hits, tier_order, settings.tier_decay),
        "keyword_density": keyword_density(hits),
        "question_form": question_form(item.title),
        "recency": recency_decay(item.created_utc, window_days=settings.window_days, now=now),
        "engagement": engagement(item.score, item.num_comments),
        "length": length_plausibility(len(item.text), min_chars=settings.min_chars),
    }

    weights = normalised_weights(settings.weights)
    total = round(100.0 * sum(weights.get(k, 0.0) * v for k, v in components.items()), 2)
    absent = dict(ABSENT_COMPONENTS)

    verdict = _hard_filters(item, settings, negative_terms=negative_terms, rules=rules, now=now)
    if verdict.rejected:
        return PreScore(total, components, DECISION_REJECT, verdict.reason, verdict.detail, absent)

    if total < settings.admission_floor:
        cut = below_prescore(detail=f"{total:.2f} < {settings.admission_floor:.2f}")
        return PreScore(total, components, DECISION_REJECT, cut.reason, cut.detail, absent)

    return PreScore(total, components, DECISION_ADMIT, absent=absent)


def _hard_filters(
    item: ScoredItem,
    settings: PrescoreSettings,
    *,
    negative_terms: Sequence[str],
    rules: RulesSettings | None,
    now: datetime.datetime | None,
) -> RuleResult:
    """The window, then P9's four. Returns the first rejection, or ``ADMITTED``.

    These are what [27 §10 A2](../../docs/27-architecture-review.md) calls the
    *hard filters* and assumes remove **~73%** of collected items. This function
    is the one place that assumption can be measured, which is why the funnel
    counts its verdicts separately from the admission cut: A2 is about the hard
    filters, and folding ``below_prescore`` into the same number would measure a
    tunable dial and call it a structural rate.
    """
    if item.created_utc is not None:
        moment = now or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        age_days = (moment - item.created_utc).total_seconds() / 86_400.0
        if age_days > settings.window_days:
            return out_of_window(detail=f"{age_days:.1f}d > {settings.window_days}d")

    return evaluate_rules(
        title=item.title,
        author=item.author,
        text=item.text,
        settings=rules,
        negative_terms=negative_terms,
    )


__all__ = ["DISABLED", "PreScore", "ScoredItem", "prescore"]
