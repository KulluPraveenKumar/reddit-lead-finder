"""Rules — the deterministic filter. Every rejection here costs nothing.

P9 gives this package five modules: keyword tiers and negative terms
(``keywords``), structural noise regexes and the length floor (``structural``),
author heuristics (``authors``), and competitor matching behind an interface
whose implementation does not arrive until P15 (``competitors``, Stage 3).

One boundary holds from the first file, because retrofitting it is far more
expensive than starting with it:

* **No AI, ever.** ``ARCHITECTURE_FREEZE`` **R3** names this package first:
  ``rules/``, ``dedupe/``, ``scoring/``, ``knowledge/``, ``feedback/`` and
  ``discovery/policy.py`` never import ``src.ai``. That rule carries
  ``docs/06c`` §2's entire cost argument -- if the code built to avoid paying a
  model could call one, it would be the thing doing the paying.

  The shortest path to breaking it is real and specific: ``src/ai/gate.py``
  already ships ``PreAIGate``, whose rule plugins return a ``GateDecision``. A
  rule here that returned one would have to import it. **It must not.** Hence
  :class:`RuleResult` below, and hence the adapter that turns one into a
  ``GateDecision`` living on the ``src.ai`` side of the boundary, where the
  import is legal -- which is P19's work, not P9's.

  ``tests/test_boundaries.py`` asserts this, and asserts that this package
  exists, so deleting it fails a test rather than quietly reducing the fence to
  a no-op over an empty directory.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The rejection reasons this package can produce -- **four**, not eleven.
#:
#: [34 §P9](../../docs/34-implementation-plan.md)'s acceptance line asks for
#: *"11 rejection reasons implemented and counted"*, and
#: [34 §P19](../../docs/34-implementation-plan.md)'s deliverables row asks for
#: *"``PreAIGate`` with 11 counted reasons"* -- the same eleven, claimed by two
#: phases. Both cannot be true. Mapping
#: [06c §3.2](../../docs/06c-local-first-pipeline.md)'s table to the phase that
#: can produce each, P9's five tasks reach these four; the other seven need a
#: content hash (P10), a MinHash index (P10), comments (P11), a pre-score (P11),
#: a response cache (P19/P20) or an ``ai_budgets`` row (``0009``, P19).
#:
#: Operator decision **D2**, 2026-08-13. ``P9-DECISION-ANALYSIS.md``.
#:
#: **Spelled to match ``src/ai/gate.py``'s ``RejectionReason``, and deliberately
#: not imported from it** -- R3 forbids the import, so the agreement is asserted
#: by ``tests/test_rules_vocabulary.py``, which may import both sides.
NEGATIVE_TERM = "negative_term"
STRUCTURAL_NOISE = "structural_noise"
TOO_SHORT = "too_short"
BOT_OR_DELETED = "bot_or_deleted"

REASONS = frozenset({NEGATIVE_TERM, STRUCTURAL_NOISE, TOO_SHORT, BOT_OR_DELETED})


@dataclass(frozen=True)
class RuleResult:
    """A deterministic judgement, and why. **Deliberately not ``GateDecision``.**

    ``GateDecision`` lives in ``src/ai/gate.py`` and R3 forbids this package
    importing it. A future reader who does not know that will be tempted to
    "simplify" the two into one; the simplification is the defect. The adapter
    between them is P19's, on the side of the boundary where the import is
    legal.

    ``reason`` is one of :data:`REASONS` when ``rejected`` is true, and ``None``
    otherwise. ``detail`` carries the granular sub-reason -- ``"megathread"``
    under ``"structural_noise"``, the matched term under ``"negative_term"`` --
    which is operator decision **D3**: one counted reason so
    ``GateReport.to_dict()``'s fixed key set survives, with the granularity that
    [AD-10b](../../docs/ARCHITECTURE_FREEZE.md) needs kept underneath it. *"5-12%
    structural noise"* is not something an operator can act on; *"8% megathread,
    1% hiring"* is.
    """

    rejected: bool
    reason: str | None = None
    detail: str | None = None


#: The single admitted value. A frozen dataclass compares by value, so this is a
#: convenience rather than a sentinel -- ``result == ADMITTED`` and
#: ``not result.rejected`` are equivalent, and both are used.
ADMITTED = RuleResult(rejected=False)


def reject(reason: str, detail: str | None = None) -> RuleResult:
    """Build a rejection, refusing any reason outside :data:`REASONS`.

    The check is not ceremony. P9's vocabulary is asserted to be a **subset** of
    P19's eleven, and a call site that invented a twelfth string would break that
    claim silently -- the counter would carry a key ``GateReport`` never renders,
    and the funnel would under-report by exactly the amount nobody noticed.
    Mutation M15.
    """
    if reason not in REASONS:
        raise ValueError(f"{reason!r} is not one of the four reasons P9 owns: {sorted(REASONS)}")
    return RuleResult(rejected=True, reason=reason, detail=detail)


__all__ = [
    "ADMITTED",
    "BOT_OR_DELETED",
    "NEGATIVE_TERM",
    "REASONS",
    "STRUCTURAL_NOISE",
    "TOO_SHORT",
    "RuleResult",
    "reject",
]
