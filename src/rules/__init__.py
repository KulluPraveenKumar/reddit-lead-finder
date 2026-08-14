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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class RulesSettings:
    """The ``rules:`` and ``pipeline:`` blocks, validated.

    Modelled on ``NotifySettings.from_config``, **including its property that
    deleting the whole block reproduces these defaults exactly** -- so a rollback
    by deletion behaves identically to a rollback by flag, which is the property
    the ``discovery:`` block also documents for itself.

    It reads **two** blocks because [34 §P9](../../docs/34-implementation-plan.md)
    puts the keys in two: ``rules.{min_chars,skip_deleted_authors,skip_bot_authors}``
    and ``pipeline.rules_enabled``. So :meth:`from_config` takes the whole config
    mapping rather than one sub-mapping.

    **On ``enabled`` defaulting to ``True``.** This departs from P7's
    default-off precedent deliberately and the choice is recorded rather than
    silently taken. ``pipeline.rules_enabled: false`` is the phase's documented
    *rollback* ([34 §P9](../../docs/34-implementation-plan.md)), so ``true`` is
    normal operation; a filter that shipped off by default would be the
    *"documented capability that does not exist"* trap P6's ``density_threshold``
    note names. The rollback is proved by an explicit test that flips the flag
    (mutation M16), not by the default.

    **On ``min_chars: 80``.** [06b](../../docs/06b-deepseek-optimization.md)'s
    value, cited rather than invented -- [34 §P9](../../docs/34-implementation-plan.md)
    gives no default. Note that 06b measures a *body*; see
    :func:`~src.rules.structural.is_too_short` for why nothing binds it to one
    until P11.
    """

    enabled: bool = True
    min_chars: int = 80
    skip_deleted_authors: bool = True
    skip_bot_authors: bool = True

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> RulesSettings:
        """Build from the parsed config. ``None``, ``{}`` or absent blocks -> defaults.

        Unknown keys are ignored rather than rejected: a config that refused to
        load because of a stray key would turn a typo into an outage, and the
        blocks this reads are optional by construction.
        """
        data = config or {}
        rules = data.get("rules") or {}
        pipeline = data.get("pipeline") or {}
        return cls(
            enabled=bool(pipeline.get("rules_enabled", True)),
            min_chars=int(rules.get("min_chars", 80)),
            skip_deleted_authors=bool(rules.get("skip_deleted_authors", True)),
            skip_bot_authors=bool(rules.get("skip_bot_authors", True)),
        )


def evaluate(
    *,
    title: str,
    author: str | None = None,
    text: str | None = None,
    settings: RulesSettings | None = None,
    negative_terms: Iterable[str] = (),
) -> RuleResult:
    """Run P9's four predicates and return the first rejection, or :data:`ADMITTED`.

    ⚠️ **This is not ``PreAIGate``.** It composes only the rules *this package*
    owns. Dedup, the pre-score and the budget are P10, P11 and P19, and the
    object that counts these reasons is P19's ``GateReport`` -- across the R3
    boundary, which is why nothing here returns a ``GateDecision``.

    **When ``settings.enabled`` is false, this returns admitted immediately and
    no regex runs.** That is the phase's documented rollback
    (``pipeline.rules_enabled: false``) made real inside this package's own
    boundary, which is operator decision **D4**: P9 wires no call site, so a flag
    read by anything else would have nothing to disable, and
    [lock §4](../../docs/EXECUTION_MODE_LOCK.md) requires the rollback be
    *executed and verified*, not merely documented.

    ``text`` is optional and defaults to skipping the length check entirely.
    P9's callers see titles and authors; the body arrives with P11, which is what
    binds ``min_chars`` to it.
    """
    from .authors import check_author
    from .keywords import check_negative_terms
    from .structural import check_length, check_structural

    cfg = settings or RulesSettings()
    if not cfg.enabled:
        return ADMITTED

    # Cheapest and most certain first: a set lookup, then compiled regexes over
    # the title, then the operator's vocabulary, then arithmetic.
    decision = check_author(
        author,
        skip_deleted_authors=cfg.skip_deleted_authors,
        skip_bot_authors=cfg.skip_bot_authors,
    )
    if decision.rejected:
        return decision

    decision = check_structural(title)
    if decision.rejected:
        return decision

    decision = check_negative_terms(title if text is None else f"{title}\n{text}", negative_terms)
    if decision.rejected:
        return decision

    if text is not None:
        decision = check_length(text, cfg.min_chars)
        if decision.rejected:
            return decision

    return ADMITTED


__all__ = [
    "ADMITTED",
    "BOT_OR_DELETED",
    "NEGATIVE_TERM",
    "REASONS",
    "STRUCTURAL_NOISE",
    "TOO_SHORT",
    "RuleResult",
    "RulesSettings",
    "evaluate",
    "reject",
]
