"""Dedupe — near-identical discussions are analysed once and scored individually.

P9 built the library that says *"this one item is worthless."* P10 builds the one
that says *"these three items are the same conversation."* The point is not
tidiness, it is cost: three near-identical *"which CRM should I use"* threads cost
three AI enrichments today and one after this phase, because the group is analysed
through a **representative** and the shared judgement is linked to every member.

**The subtle half, and the one that would be a silent quality regression if it
were lost:** [06c §4.4](../../docs/06c-local-first-pipeline.md) — *group for
analysis, score individually*. Three threads with different authors, subreddits
and recency have genuinely different value as leads. One shared ``lead_analysis``;
three different ``confidence_score`` values. Collapsing the scores too would emit
three identical numbers for three different-value leads, and the operator would
correctly stop trusting the ranking. **Nothing in this package writes, mutates or
reads a per-item score**, and ``test_grouping_mutates_no_per_item_score`` is what
holds that.

Three tiers, each cheaper to be wrong about than the next:

1. ``exact`` — ``sha256(normalise(title + "\\n" + body))``. Crossposts, reposts,
   quoted duplicates. One indexed lookup.
2. ``minhash`` — a 128-slot signature over character 5-grams, LSH banding,
   Jaccard ≥ 0.85. Banding is what avoids the O(n²) comparison.
3. ``semantic`` — Model2Vec cosine ≥ 0.88, catching paraphrases that share no
   5-grams. **Optional, and a no-op when the libraries are absent**
   ([AD-16](../../docs/03-architecture.md)). P0 measured both as not installed,
   so absent is the *normal* case and the one the tests exercise.

Two boundaries hold from the first file:

* **No AI, ever.** [freeze R3](../../docs/ARCHITECTURE_FREEZE.md) names
  ``dedupe/`` second, after ``rules/``. ``tests/test_boundaries.py`` extends
  fence 2 to this path and asserts the package **exists**, so deleting it fails a
  test rather than quietly reducing the fence to a no-op over an empty directory
  — P5's F3, which this project has now recorded five times.
* **``RuleResult``, not ``GateDecision``.** ``GateDecision`` lives in
  ``src/ai/gate.py`` and R3 forbids the import. This package reuses P9's neutral
  type, which is legal (``src.rules`` is inside the same fence), and the adapter
  to ``GateDecision`` remains P19's.

**On owning two reason constants rather than extending ``src.rules.REASONS``**
— operator decision **D3**. [PHASE-09-HANDOVER §3.3](../../docs/PHASE-09-HANDOVER.md)
asked P10 to add them to ``src/rules/__init__.py``; that file is outside
[34 §P10](../../docs/34-implementation-plan.md)'s **Files** row, and
[lock §3](../../docs/EXECUTION_MODE_LOCK.md) step 4 says *"every file in the
phase's Files row, and nothing outside it"*. So the constants live here, spelled
to match ``RejectionReason`` and deliberately not imported from it, and
``tests/test_rules_vocabulary.py`` — the one file permitted to import both sides
— asserts that all **six** stay a subset of P19's eleven. The cost of that choice
is that ``src.rules.reject``'s guard does not cover them, so :func:`duplicate`
below reproduces it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.rules import RuleResult

#: The two rejection reasons this package can produce.
#:
#: **Spelled to match ``src/ai/gate.py``'s ``RejectionReason``, and deliberately
#: not imported from it** — R3 forbids the import, so the agreement is asserted
#: by ``tests/test_rules_vocabulary.py``, which may import both sides. Together
#: with P9's four this makes six of P19's eleven; the remaining five need
#: comments (P11), a pre-score (P11), a response cache (P19/P20) or an
#: ``ai_budgets`` row (``0009``, P19).
DUPLICATE_EXACT = "duplicate_exact"
DUPLICATE_NEAR = "duplicate_near"

REASONS = frozenset({DUPLICATE_EXACT, DUPLICATE_NEAR})

#: The three tier names, which are also ``dedup_groups.method`` values. The
#: column is ``String(20)``; the longest here is 8.
METHOD_EXACT = "exact"
METHOD_MINHASH = "minhash"
METHOD_SEMANTIC = "semantic"

METHODS = (METHOD_EXACT, METHOD_MINHASH, METHOD_SEMANTIC)

#: Which reason a group of each method produces for its **non-representative**
#: members. Tier 3 reports ``duplicate_near`` rather than inventing a twelfth
#: string: a paraphrase is a near-duplicate, and P19's vocabulary has no
#: ``duplicate_semantic``. The tier that found it is not lost — it is
#: ``DedupGroup.method``, and it reaches the reason as ``detail``.
_REASON_FOR_METHOD = {
    METHOD_EXACT: DUPLICATE_EXACT,
    METHOD_MINHASH: DUPLICATE_NEAR,
    METHOD_SEMANTIC: DUPLICATE_NEAR,
}


def duplicate(reason: str, detail: str | None = None) -> RuleResult:
    """Build a duplicate rejection, refusing any reason outside :data:`REASONS`.

    This is ``src.rules.reject``'s guard, reproduced rather than reused, because
    that function validates against P9's four and would refuse both of P10's.
    The check is not ceremony for the same reason it was not there: a call site
    that invented a new string would break the six-are-a-subset-of-eleven claim
    silently — the counter would carry a key ``GateReport`` never renders, and
    the funnel would under-report by exactly the amount nobody noticed.
    Mutation M8.
    """
    if reason not in REASONS:
        raise ValueError(f"{reason!r} is not one of the two reasons P10 owns: {sorted(REASONS)}")
    return RuleResult(rejected=True, reason=reason, detail=detail)


def reason_for_method(method: str) -> str:
    """The rejection reason a group of ``method`` gives its non-representatives."""
    try:
        return _REASON_FOR_METHOD[method]
    except KeyError:
        raise ValueError(f"{method!r} is not one of {list(METHODS)}") from None


@dataclass(frozen=True)
class DedupSettings:
    """The ``dedup:`` block, validated.

    Modelled on ``RulesSettings.from_config``, **including its property that
    deleting the whole block reproduces these defaults exactly** — so a rollback
    by deletion behaves identically to a rollback by flag. The ``rules:``,
    ``notify:`` and ``discovery:`` blocks all document the same property, and
    this is the fourth.

    The defaults are [06c §4.2](../../docs/06c-local-first-pipeline.md)'s
    literal constants, cited rather than invented::

        SHINGLE_K   = 5        # character 5-grams
        NUM_PERM    = 128      # MinHash permutations
        LSH_THRESH  = 0.85     # Jaccard

    ``semantic_threshold`` defaults to **``None``**, which is
    [34 §P10](../../docs/34-implementation-plan.md)'s own rollback value and
    means *tier 3 does not run*. That is not timidity: P0 measured neither
    ``model2vec`` nor ``sqlite_vec`` as installed, so an on-by-default tier 3
    would be off in practice on every host anyway — and a default that lies
    about what runs is worse than one that does not.

    ``num_perm`` is validated to be a positive multiple of :data:`BANDS` so that
    banding divides evenly; a config that made it otherwise would silently drop
    the remainder of the signature from the LSH index.
    """

    exact_enabled: bool = True
    minhash_enabled: bool = True
    shingle_k: int = 5
    num_perm: int = 128
    jaccard_threshold: float = 0.85
    semantic_threshold: float | None = None

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> DedupSettings:
        """Build from the parsed config. ``None``, ``{}`` or an absent block -> defaults.

        Unknown keys are ignored rather than rejected, matching
        ``RulesSettings.from_config``: a config that refused to load because of a
        stray key would turn a typo into an outage.

        ``semantic_threshold`` is read with a sentinel rather than
        ``get("semantic_threshold", None)`` so that an explicit ``null`` and an
        absent key behave identically — both mean *off*, and a YAML ``null``
        arrives as ``None`` exactly as an absent key does. The sentinel exists so
        the two are not merely equal by accident.
        """
        data = config or {}
        block = data.get("dedup") or {}
        raw_threshold = block.get("semantic_threshold", None)
        return cls(
            exact_enabled=bool(block.get("exact_enabled", True)),
            minhash_enabled=bool(block.get("minhash_enabled", True)),
            shingle_k=int(block.get("shingle_k", 5)),
            num_perm=int(block.get("num_perm", 128)),
            jaccard_threshold=float(block.get("jaccard_threshold", 0.85)),
            semantic_threshold=None if raw_threshold is None else float(raw_threshold),
        )

    def __post_init__(self) -> None:
        if self.shingle_k < 1:
            raise ValueError(f"dedup.shingle_k must be >= 1, got {self.shingle_k}")
        if self.num_perm < 1:
            raise ValueError(f"dedup.num_perm must be >= 1, got {self.num_perm}")
        if not 0.0 <= self.jaccard_threshold <= 1.0:
            raise ValueError(
                f"dedup.jaccard_threshold is a Jaccard similarity and must be in [0, 1], "
                f"got {self.jaccard_threshold}"
            )
        if self.semantic_threshold is not None and not 0.0 <= self.semantic_threshold <= 1.0:
            raise ValueError(
                f"dedup.semantic_threshold is a cosine similarity and must be in [0, 1] "
                f"or null (off), got {self.semantic_threshold}"
            )


#: ``("lead", 12)`` or ``("comment", 5)``.
#:
#: A tuple and not a bare integer because ``dedup_members`` targets **either** a
#: lead or a comment — ``CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT
#: NULL))`` — and lead 12 is not comment 12. Collapsing the two id spaces into
#: one integer would make the DI22 membership guarantee below silently wrong for
#: any run that carried both.
ItemKey = tuple[str, int]

KIND_LEAD = "lead"
KIND_COMMENT = "comment"


@dataclass(frozen=True)
class DedupItem:
    """One candidate for grouping. Neutral: not a ``Lead``, not a ``Comment``.

    ⚠️ **It carries no ``url``, and that is deliberate.**
    [DI14](../../docs/DEFERRED-IMPROVEMENTS.md) records that the live database
    splits **444 ``old.reddit.com`` / 27 ``www.reddit.com``** across 471 rows,
    and P9's handover flagged P10 as *"the first place that bites"*. It does not
    bite, because **the cascade is content-keyed throughout** — the exact tier
    hashes title and body, the near tier shingles them, and identity is
    :attr:`key`, the database primary key. Nothing here joins on, reads or
    compares a URL, and there is no field for one to arrive in.
    ``test_no_dedupe_module_mentions_url`` holds that shape, so DI14 stays open
    on its own merits rather than being closed by accident.

    :attr:`rank` is P11's pre-score, injected rather than computed — operator
    decision **D1**. [06c §4.3](../../docs/06c-local-first-pipeline.md) ranks
    representatives by ``(prescore.total, score, created_utc)``, but
    ``src/scoring/prescore.py`` is P11's Files row and **P11 depends on P10**, so
    there is no pre-score to rank by yet. It defaults to ``None``, the ranking
    falls back to ``(score, created_utc)``, and P11 fills it in without a
    signature change.
    """

    key: ItemKey
    title: str = ""
    body: str = ""
    score: int | None = None
    created_utc: datetime | None = None
    rank: float | None = None

    @property
    def kind(self) -> str:
        return self.key[0]

    @property
    def row_id(self) -> int:
        return self.key[1]

    def __post_init__(self) -> None:
        kind = self.key[0]
        if kind not in (KIND_LEAD, KIND_COMMENT):
            raise ValueError(
                f"DedupItem.key[0] is {kind!r}; dedup_members targets a lead or a comment "
                f"and nothing else (ck_dedup_members_one_target)"
            )


__all__ = [
    "DUPLICATE_EXACT",
    "DUPLICATE_NEAR",
    "KIND_COMMENT",
    "KIND_LEAD",
    "METHODS",
    "METHOD_EXACT",
    "METHOD_MINHASH",
    "METHOD_SEMANTIC",
    "REASONS",
    "DedupItem",
    "DedupSettings",
    "ItemKey",
    "RuleResult",
    "duplicate",
    "reason_for_method",
]
