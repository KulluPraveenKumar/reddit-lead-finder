"""Scoring — the deterministic 0–100 pre-score, and the legacy intent score.

P9 built the library that says *"this one item is worthless."* P10 built the one
that says *"these three items are the same conversation."* P11 builds the one
that says **"of what survives, look at this one first"** — a recall instrument,
not a precision one ([06c §3.1](../../docs/06c-local-first-pipeline.md)).

**This package is a package because P11's Files row says so.** It was
``src/scoring.py`` through P10; [34 §P11](../../docs/34-implementation-plan.md)
names ``src/scoring/{prescore,features}.py``, [freeze R3](../../docs/ARCHITECTURE_FREEZE.md)
names ``scoring/`` as a fenced directory, and [35 §2.1](../../docs/35-testing-strategy.md)
row 9's table gives ``src/scoring/`` to P11. The old module moved **byte-for-byte**
to :mod:`src.scoring.legacy` under ``git mv``, and :class:`LeadScorer` is
re-exported here so ``from src.scoring import LeadScorer`` — which
``src/scrapers/`` and ``tests/test_net.py`` both use — keeps working unchanged.

⚠ **``legacy.py`` is not to be reformatted.** It computes ``leads.intent_score``,
which [freeze R20](../../docs/ARCHITECTURE_FREEZE.md) pins by SHA-256 over the
459 original leads, and [DI4](../../docs/DEFERRED-IMPROVEMENTS.md) keeps the
pre-Phase-1 modules out of the formatter for exactly that reason. Its ruff
exemption moved with it in ``pyproject.toml``; a stale path literal there would
have exempted nothing while reading as though it exempted something.

Two boundaries hold, the same two P9 and P10 state:

* **No AI, ever.** R3 names ``scoring/`` third, after ``rules/`` and ``dedupe/``.
  ``tests/test_boundaries.py`` extends fence 2 to this path and asserts the
  package **exists**, so deleting it fails a test rather than quietly reducing
  the fence to a no-op over an empty directory — P5's F3, recorded six times now.
  Fence 2 covers **4 of 6** as of this phase.
* **``RuleResult``, not ``GateDecision``.** ``GateDecision`` lives in
  ``src/ai/gate.py``, across the fence. This package reuses P9's neutral type,
  and the adapter remains P19's ([PHASE-10-HANDOVER §3.4](../../docs/PHASE-10-HANDOVER.md)).

**On owning two reason constants rather than importing ``RejectionReason``** —
P10's shape, followed deliberately rather than P9's handover instruction, exactly
as [PHASE-10-HANDOVER §3.5](../../docs/PHASE-10-HANDOVER.md) directs. Together
with P9's four and P10's two this makes **eight** of P19's eleven;
``tests/test_rules_vocabulary.py`` — the one file permitted to import both sides
— asserts the subset claim at its new size.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.rules import RuleResult

from .legacy import LeadScorer

#: The two rejection reasons this package can produce.
#:
#: **Spelled to match ``src/ai/gate.py``'s ``RejectionReason``, and deliberately
#: not imported from it** — R3 forbids the import, so the agreement is asserted
#: by ``tests/test_rules_vocabulary.py``.
#:
#: ``out_of_window`` is spelled identically in ``src/discovery/triage.py``'s own
#: nine-reason vocabulary. That is [DI23](../../docs/DEFERRED-IMPROVEMENTS.md) —
#: two vocabularies that ship and disagree — and P11 is the phase that must
#: render both on one page. See :mod:`src.scoring.funnel` for the mapping that
#: reconciles them **for display only**, without changing what either module
#: writes.
BELOW_PRESCORE = "below_prescore"
OUT_OF_WINDOW = "out_of_window"

REASONS = frozenset({BELOW_PRESCORE, OUT_OF_WINDOW})

#: ``prescores.stage``. P6 writes ``metadata``; P11 writes ``full``.
STAGE_METADATA = "metadata"
STAGE_FULL = "full"

#: ``prescores.gate_decision``. The column is ``String(20)``; the longest is 7.
#: ``cached`` is the fourth value the column allows and P11 never writes it —
#: it needs a response cache, which is P19/P20's.
DECISION_ADMIT = "admit"
DECISION_REJECT = "reject"
DECISION_GROUPED = "grouped"

#: ``leads.source`` for an item pulled back in by the stage-3 holdout.
#: [06c §6.1](../../docs/06c-local-first-pipeline.md): audited items are
#: persisted as **real, labellable leads**, because storing only the aggregate
#: counts produces *"a metric with no learning signal"*.
SOURCE_SCRAPE = "scrape"
SOURCE_HOLDOUT_AUDIT = "holdout_audit"


def below_prescore(detail: str | None = None) -> RuleResult:
    """Build a ``below_prescore`` rejection, refusing any reason outside :data:`REASONS`.

    ``src.rules.reject``'s guard, reproduced for the same stated reason P10
    reproduced it: that function validates against P9's four and would refuse
    both of P11's. A call site inventing a ninth string would break the
    eight-are-a-subset-of-eleven claim **silently** — the funnel would carry a
    key ``GateReport`` never renders and would under-report by exactly the amount
    nobody noticed.
    """
    return _reason(BELOW_PRESCORE, detail)


def out_of_window(detail: str | None = None) -> RuleResult:
    """Build an ``out_of_window`` rejection. See :func:`below_prescore`."""
    return _reason(OUT_OF_WINDOW, detail)


def _reason(reason: str, detail: str | None) -> RuleResult:
    if reason not in REASONS:
        raise ValueError(f"{reason!r} is not one of the two reasons P11 owns: {sorted(REASONS)}")
    return RuleResult(rejected=True, reason=reason, detail=detail)


# --------------------------------------------------------------- the weights

#: [04 §9.1](../../docs/04-system-design.md)'s **non-AI** weights, cited rather
#: than invented — operator decision **D2**.
#:
#: [06c §3.1](../../docs/06c-local-first-pipeline.md) writes ``100 * sum(W[k] * v
#: for k, v in c.items())`` and **never supplies ``W``**. Grepped across every
#: document in ``docs/`` on 2026-08-15: no frozen document gives the nine
#: pre-score weights. Choosing them is therefore P11's, and the discipline
#: applied is P9's for ``min_chars: 80`` and P10's for ``shingle_k``/``num_perm``
#: /``jaccard_threshold`` — **take the number from a frozen document that has
#: one, rather than inventing it.**
#:
#: 04 §9.1 is the nearest thing: the ``ConfidenceScorer``'s eleven weights, of
#: which four are non-AI and therefore computable without a model —
#: ``keyword 0.10``, ``recency 0.07``, ``engagement 0.05``, ``subreddit 0.03``.
#: The derivation, in full, so a later reader can check it rather than trust it:
#:
#: * ``keyword`` **0.10** splits evenly between the pre-score's two keyword
#:   components, which 04 does not distinguish: 0.05 each.
#: * ``recency`` **0.07** and ``engagement`` **0.05** transfer directly.
#: * ``subreddit`` **0.03** does **not** transfer — ``subreddit_fit`` is one of
#:   the three components P11 does not ship (see below). Its *magnitude* is
#:   reused as 04's own "weak but non-zero" value for the pre-score's two
#:   components that 04 has no analogue for at all, ``question_form`` and
#:   ``length``: 0.03 each.
#:
#: **The raw cited values are stored, and normalised at call time by their own
#: sum** rather than being pre-divided into constants that round to 1.01. Three
#: things follow, and the third is why it is done this way: the arithmetic is
#: exact; the numbers above stay legible and traceable to 04 §9.1; and when P12
#: and P15 supply the three absent components, their weights slot in and the
#: normaliser adjusts **without re-tuning the six that shipped**.
WEIGHTS: dict[str, float] = {
    "keyword_tier": 0.05,
    "keyword_density": 0.05,
    "question_form": 0.03,
    "recency": 0.07,
    "engagement": 0.05,
    "length": 0.03,
}

#: The three components of [06c §3.1](../../docs/06c-local-first-pipeline.md)
#: that P11 **does not ship**, and the phase that supplies each — operator
#: decision **D1**.
#:
#: All three read ``project.*``: ``phrase_overlap(item.text,
#: project.pain_phrases)``, ``competitor_mentions(item.text, project)`` and
#: ``project.subreddit_fit(item.subreddit)``. ``projects``, ``pain_points`` and
#: ``bkb_entities`` arrive in revision ``0007`` with **P12, which depends on
#: P11**, and the entity registry behind competitor matching is **P15** —
#: ``tests/test_boundaries.py::test_the_competitor_registry_was_not_wired_before_p15``
#: fails if it is wired early.
#:
#: **They are declared absent rather than shipped at 0.0**, and the difference is
#: the whole point. A component contributing a silent zero is
#: [DI24](../../docs/DEFERRED-IMPROVEMENTS.md) exactly — a score nobody noticed
#: was always zero — inside the phase whose job is fixing DI24. This is P6's
#: ``density_threshold`` precedent and P10's tier-3-off precedent: *a key nothing
#: reads is a documented capability that does not exist.*
ABSENT_COMPONENTS: dict[str, str] = {
    "pain_phrase": "P12 — `pain_points` arrives in revision 0007",
    "competitor": "P15 — the EntityRegistry over `bkb_entities` (0007)",
    "subreddit_fit": "P12 — `projects` arrives in revision 0007",
}


@dataclass(frozen=True)
class PrescoreSettings:
    """The ``pipeline:``, ``rules:`` and ``gate:`` blocks this package reads.

    Modelled on ``RulesSettings.from_config`` and ``DedupSettings.from_config``,
    **including the property that deleting the whole block reproduces these
    defaults exactly** — so a rollback by deletion behaves identically to a
    rollback by flag. That is now the fifth block documenting it.

    **On ``enabled`` defaulting to ``True``.** ``pipeline.prescore_enabled:
    false`` is [34 §P11](../../docs/34-implementation-plan.md)'s documented
    *rollback* (*"items keep ``intent_score`` only"*), so ``true`` is normal
    operation — P9's reasoning for ``rules_enabled``, applied unchanged.

    **On ``admission_floor: 35``.** [06c §3.3](../../docs/06c-local-first-pipeline.md)'s
    ``balanced`` row, *"Fixed threshold (fallback only) ≥ 35"*, and the same
    number [06b](../../docs/06b-deepseek-optimization.md) ships as
    ``prescore_threshold: 35``. It is the **fallback**, and using it here is
    correct rather than a shortcut: 06c §3.3 says the adaptive cut is derived
    from the pre-score distribution by [06f](../../docs/06f-adaptive-budget.md),
    which is **P19's** — and it also says the fallback applies when adaptive
    budgeting *"cannot run"*. At P11 it structurally cannot: ``ai_budgets``
    arrives in revision ``0009``. The fixed cut is reported as the method, never
    silently substituted, which is what 06c §3.3's closing paragraph requires.

    **On ``tier_decay: 2.0``.** ``config.yaml``'s own ``scoring.high_intent_multiplier``,
    cited not invented. See :func:`~src.scoring.features.tier_value`.
    """

    enabled: bool = True
    admission_floor: float = 35.0
    holdout_rate: float = 0.02
    window_days: int = 30
    min_chars: int = 80
    tier_decay: float = 2.0
    weights: Mapping[str, float] = field(default_factory=lambda: dict(WEIGHTS))

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> PrescoreSettings:
        """Build from the parsed config. ``None``, ``{}`` or absent blocks -> defaults.

        Unknown keys are ignored rather than rejected, matching every other
        settings object in this codebase: a config that refused to load because
        of a stray key would turn a typo into an outage.
        """
        data = config or {}
        pipeline = data.get("pipeline") or {}
        rules = data.get("rules") or {}
        gate = data.get("gate") or {}
        discovery = data.get("discovery") or {}
        scoring = data.get("scoring") or {}
        return cls(
            enabled=bool(pipeline.get("prescore_enabled", True)),
            admission_floor=float(pipeline.get("prescore_admission_floor", 35.0)),
            holdout_rate=float(gate.get("metadata_holdout_rate", 0.02)),
            window_days=int(discovery.get("window_days", 30)),
            min_chars=int(rules.get("min_chars", 80)),
            tier_decay=float(scoring.get("high_intent_multiplier", 2.0) or 2.0),
        )

    def __post_init__(self) -> None:
        if not 0.0 <= self.admission_floor <= 100.0:
            raise ValueError(
                f"pipeline.prescore_admission_floor is a 0-100 pre-score and must be in "
                f"[0, 100], got {self.admission_floor}"
            )
        if not 0.0 <= self.holdout_rate <= 1.0:
            raise ValueError(
                f"gate.metadata_holdout_rate is a fraction of rejects and must be in [0, 1], "
                f"got {self.holdout_rate}"
            )
        if self.window_days < 1:
            raise ValueError(f"discovery.window_days must be >= 1, got {self.window_days}")
        if self.tier_decay < 1.0:
            # Below 1.0 the second tier would outrank the first, which inverts
            # the meaning of "high intent" rather than tuning it.
            raise ValueError(
                f"scoring.high_intent_multiplier must be >= 1.0 (it is how many times more a "
                f"high-intent hit is worth than the next tier), got {self.tier_decay}"
            )
        if not self.weights:
            raise ValueError("PrescoreSettings.weights is empty; the pre-score would be 0 for all")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError(f"every pre-score weight must be >= 0, got {dict(self.weights)}")
        if sum(self.weights.values()) <= 0:
            raise ValueError("pre-score weights sum to 0; the normaliser would divide by zero")


def normalised_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """The cited weights, divided by their own sum so the total is bounded at 100.

    Separated from :func:`~src.scoring.prescore.prescore` so the bound is
    testable on its own, and so the docstring above can say *"normalised at call
    time"* and be checkable.
    """
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def keyword_tiers_of(config: Mapping[str, Any] | None) -> dict[str, Sequence[str]]:
    """The ``keywords:`` block as the **mapping it is**, for ``match_tiers``.

    ⚠ **This is [DI24](../../docs/DEFERRED-IMPROVEMENTS.md)'s fix, and it is one
    line.** ``src/orchestration/handlers/discover.py::_triage_config`` read the
    same block as a *sequence*::

        tuple(str(k) for k in (config or {}).get("keywords", []) or [])

    Iterating a mapping yields its **keys**, so ``TriageConfig.keywords`` was
    ``('high_intent', 'medium_intent')`` and P6 has matched a title only if it
    literally contained the string ``high_intent`` — measured against the shipped
    ``config.yaml`` on 2026-08-13, and its provisional score has been ``0.0`` on
    every real post ever triaged. Nothing noticed because nothing consumed it.
    **P11 is the first consumer**, which is the trigger DI24 records.

    A non-mapping value returns ``{}`` rather than raising: a malformed optional
    block must not stop a run, and an empty tier map scores every keyword
    component at 0.0 honestly rather than crashing.
    """
    raw = (config or {}).get("keywords")
    if not isinstance(raw, Mapping):
        return {}
    tiers: dict[str, Sequence[str]] = {}
    for tier, phrases in raw.items():
        if isinstance(phrases, str) or not isinstance(phrases, Sequence):
            continue
        tiers[str(tier)] = [str(p) for p in phrases if p]
    return tiers


__all__ = [
    "ABSENT_COMPONENTS",
    "BELOW_PRESCORE",
    "DECISION_ADMIT",
    "DECISION_GROUPED",
    "DECISION_REJECT",
    "OUT_OF_WINDOW",
    "REASONS",
    "SOURCE_HOLDOUT_AUDIT",
    "SOURCE_SCRAPE",
    "STAGE_FULL",
    "STAGE_METADATA",
    "WEIGHTS",
    "LeadScorer",
    "PrescoreSettings",
    "RuleResult",
    "below_prescore",
    "keyword_tiers_of",
    "normalised_weights",
    "out_of_window",
]
