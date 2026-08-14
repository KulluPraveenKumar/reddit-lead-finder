"""Tier 3 — paraphrases. Optional, local, never authoritative.

*"Which CRM should I use"* and *"any recommendations for customer relationship
software"* are the same question and share **no** character 5-gram. Tiers 1 and 2
cannot see that; an embedding can.

[AD-16](../../docs/03-architecture.md) — *semantic layer is local, optional,
never authoritative* — is the whole shape of this module, and
[34 §P10](../../docs/34-implementation-plan.md) task 3 spells it out: *"Model2Vec
+ ``sqlite-vec``, cosine ≥ 0.88, **no-op when unavailable**"*. P0 measured
``model2vec`` and ``sqlite_vec`` as **not installed**
([SPRINT-0-MEASUREMENTS §3.1](../../docs/SPRINT-0-MEASUREMENTS.md)) and
deliberately did not install them, because *absent* is the state AD-16 exists to
protect. So the unavailable path is not an edge case here — it is the **default
path on every host this project has ever run on**, and it is the one the tests
exercise.

**Why in memory, and why no ``sqlite-vec``.** The vector tables
(``bkb_embeddings``, ``bkb_embedding_meta``) arrive in ``0007``, which is
**P12**. [34 §P10](../../docs/34-implementation-plan.md)'s **DB** row is
*"None (tables from P8)"* and [freeze §4.1](../../docs/ARCHITECTURE_FREEZE.md)
permits no eleventh revision, so this tier compares within the run's own item set
and stores nothing. Operator decision **D2**: the config key is genuinely read
and the path genuinely runs when the library is present, rather than shipping a
key nothing reads — P6's ``density_threshold`` and P7's
``notify.min_confidence_alert`` are the two precedents for refusing that.

**The acceptance criterion that governs this file** is *"with the semantic layer
disabled the same run produces the identical lead set"*. Everything here is
additive: tier 3 can only merge items tiers 1 and 2 left ungrouped, it never
splits a group, and it never removes an item from the run.
``test_disabling_tier_three_produces_the_identical_lead_set`` is the assertion,
and it compares whole result sets rather than counts.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Protocol

log = logging.getLogger(__name__)

#: The Model2Vec distillation to load when none is injected. A *static* model —
#: no GPU, no server, one matrix lookup per token — which is why AD-16 could call
#: the semantic layer optional without also calling it expensive.
DEFAULT_MODEL = "minishlab/potion-base-8M"

#: Whether the absence of the library has already been reported. One line per
#: process, not one per run: on a host where it is simply not installed — which
#: P0 says is every host — a per-run warning is a log nobody reads twice.
_warned = False


class Encoder(Protocol):
    """Anything that turns texts into vectors.

    A ``Protocol`` rather than a concrete class so the tests can supply vectors
    directly. That is not only convenience: ``StaticModel.from_pretrained``
    **downloads a model**, and [35 §2.1](../../docs/35-testing-strategy.md) check
    6 blocks the socket for the whole suite. A tier that could only be tested by
    reaching the network could not be tested at all here.
    """

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


def is_available() -> bool:
    """``True`` when ``model2vec`` can be imported.

    Checked at call time and not cached, so a host that installs the package does
    not have to restart the worker to get tier 3 — and so a test can exercise
    both arms in one process without reaching into module state.
    """
    try:
        import model2vec  # noqa: F401
    except Exception:
        return False
    return True


def load_encoder(model_name: str = DEFAULT_MODEL) -> Encoder | None:
    """Load the static model, or ``None`` if it cannot be loaded.

    ``except Exception`` and not ``except ImportError``: a model2vec that is
    installed but cannot reach its weights raises something else entirely, and
    the required behaviour for **every** such failure is identical — this tier
    goes away and the other two carry the run. AD-16's *never authoritative*
    means a broken optional layer must never be able to fail a run.
    """
    global _warned
    try:
        from model2vec import StaticModel

        return StaticModel.from_pretrained(model_name)
    except Exception as exc:
        if not _warned:
            _warned = True
            log.info(
                "semantic dedup tier is off: %s. Tiers 1 and 2 are unaffected and the "
                "run produces the same lead set (AD-16).",
                exc,
            )
        return None


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, clamped to ``[-1, 1]``.

    Clamped because floating-point error puts a vector's similarity with itself
    at ``1.0000000000000002`` often enough to matter, and a threshold comparison
    that can be beaten by rounding is a threshold that sometimes is not one.
    A zero-length vector returns ``0.0`` rather than raising: an empty post is
    not similar to anything, which is the same answer :func:`~src.dedupe.minhash.signature`
    gives for the same input.
    """
    if len(a) != len(b):
        raise ValueError(f"vectors of different widths do not compare: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


def similar_pairs(
    texts: Sequence[str],
    threshold: float,
    encoder: Encoder | None,
) -> list[tuple[int, int, float]]:
    """Index pairs whose cosine similarity reaches ``threshold``, most similar first.

    Returns ``[]`` — never raises, never partially groups — when ``encoder`` is
    ``None``, when there are fewer than two texts, or when encoding fails. That
    is the *"no-op when unavailable"* half of task 3, and it is the behaviour the
    identical-lead-set criterion rests on.

    O(n²) in the number of items, deliberately, and bounded by its caller: tier 3
    only ever sees the items tiers 1 and 2 left **ungrouped**, and
    :func:`~src.dedupe.groups.build_groups` caps that set. An LSH scheme over
    dense vectors would need the ``sqlite-vec`` index that ``0007`` has not
    created, which is P12's.
    """
    if encoder is None or len(texts) < 2:
        return []
    try:
        vectors = [list(map(float, v)) for v in encoder.encode(list(texts))]
    except Exception as exc:
        log.warning("semantic encoding failed; tier 3 contributes nothing this run: %s", exc)
        return []

    if len(vectors) != len(texts):
        log.warning(
            "encoder returned %d vectors for %d texts; tier 3 contributes nothing this run",
            len(vectors),
            len(texts),
        )
        return []

    pairs: list[tuple[int, int, float]] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            score = cosine(vectors[i], vectors[j])
            if score >= threshold:
                pairs.append((i, j, score))
    # Most similar first, then by index, so grouping is deterministic when two
    # pairs tie -- a run that grouped differently on a re-run would make the
    # identical-lead-set criterion unverifiable.
    pairs.sort(key=lambda p: (-p[2], p[0], p[1]))
    return pairs
