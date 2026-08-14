"""Tier 2 — near-duplicates. A 128-slot signature, LSH banding, Jaccard ≥ 0.85.

[06c §4.2](../../docs/06c-local-first-pipeline.md) fixes the three constants::

    SHINGLE_K   = 5        # character 5-grams
    NUM_PERM    = 128      # MinHash permutations
    LSH_THRESH  = 0.85     # Jaccard

**Character** n-grams rather than word n-grams because Reddit text is noisy —
typos, punctuation and casing vary far more than substance. LSH banding is what
avoids the O(n²) comparison: two items are compared at all only if they collide
in at least one band.

---

## A5, measured — and why this is One-Permutation Hashing

[34 §P10](../../docs/34-implementation-plan.md) asserts *"MinHash indexes and
queries 2,000 items in < 2 s CPU (assumption A5, **measured**)"*, and P0 left A5
unmeasured — it is the reason the phase carries **Medium** risk.

**It was measured before this module was written, and the literal implementation
fails it.** Classic MinHash re-hashes every shingle under 128 independent
permutations, which is O(shingles × 128); on this host, 2,000 items:

===========================  ==================  ===================
Documents                    Classic 128-perm    This module (OPH)
===========================  ==================  ===================
305 chars, 176 shingles      **6.36 s**          **0.27 s**
870 chars, 315 shingles      **11.11 s**         **0.55 s**
Jaccard mean abs error       0.0308              **0.0279**
===========================  ==================  ===================

Measured 2026-08-14, Python 3.12.5, win32, fixed seed. A5's budget is 2 s and
2,000 is ``max_items_per_run`` — the normal case, not the tail.

**One-Permutation Hashing produces the same 128-slot signature**, bands
identically, and is estimated by the same equality-count rule; it is *more*
accurate here, not less. The saving is structural: one hash of a shingle both
**picks its slot** and **supplies its value**, so the cost is O(shingles) rather
than O(shingles × 128). No dependency is added and
[freeze §5](../../docs/ARCHITECTURE_FREEZE.md)'s technology set is untouched —
what changes is how a 128-component sketch is computed, which is why this is
recorded as a [freeze §11.1](../../docs/ARCHITECTURE_FREEZE.md) reconciliation
carrying both measurements rather than a §11 amendment. Operator decision **D5**.

``datasketch`` was not considered available: it is not in
[freeze §5](../../docs/ARCHITECTURE_FREEZE.md) and §12 closes the set, the same
reasoning by which P9 refused ``hypothesis`` for its property tests.
"""

from __future__ import annotations

import random
import zlib
from collections.abc import Iterable, Sequence
from hashlib import blake2b

from . import ItemKey

#: The sentinel for *"no shingle landed in this slot"*. Chosen above every real
#: value: a slot value is ``h // num_perm`` where ``h`` is a 32-bit CRC, so it
#: cannot reach ``1 << 32``.
EMPTY = 1 << 32

#: Seeds the densification probe order. Fixed, because two runs of this system
#: must group the same corpus the same way — and because a failure that only
#: reproduces on some seeds is a failure nobody can bisect. Same reasoning as
#: ``tests/test_rules_properties.py``'s ``SEED``.
_PROBE_SEED = 20260814

#: ``num_perm -> tuple of per-slot probe orders``. Built once per distinct
#: ``num_perm``; the shipped config has exactly one.
_PROBE_CACHE: dict[int, tuple[tuple[int, ...], ...]] = {}


def shingles(text: str, k: int = 5) -> set[str]:
    """The set of character ``k``-grams in ``text``.

    A **set**, not a list: MinHash estimates Jaccard over sets, and counting a
    repeated 5-gram twice would make a post that says the same thing four times
    look less like the post that says it once.

    Boundary, stated because it is the one a caller trips over: text **shorter
    than k** has no k-grams at all. Returning an empty set there would make every
    short post signature-less and therefore never a near-duplicate, so the whole
    string is used as a single shingle instead. Empty text really does return
    the empty set — there is nothing to shingle — and :func:`signature` reports
    ``None`` for it rather than a signature of sentinels that would compare equal
    to every other empty item.
    """
    if k < 1:
        raise ValueError(f"shingle_k must be >= 1, got {k}")
    if not text:
        return set()
    if len(text) <= k:
        return {text}
    return {text[i : i + k] for i in range(len(text) - k + 1)}


def _probe_orders(num_perm: int) -> tuple[tuple[int, ...], ...]:
    """For each slot, the order in which it looks for a neighbour to borrow from.

    A full permutation of every slot, so the search always terminates while any
    slot is occupied, and a function of the **empty slot only** — never of the
    set being hashed. That is what makes densification agree between two
    documents: both walk the same order from the same slot, so if they land on
    the same donor with the same value they agree, and if they do not, they were
    genuinely different there.
    """
    cached = _PROBE_CACHE.get(num_perm)
    if cached is None:
        rng = random.Random(_PROBE_SEED)
        orders = []
        for _ in range(num_perm):
            order = list(range(num_perm))
            rng.shuffle(order)
            orders.append(tuple(order))
        cached = tuple(orders)
        _PROBE_CACHE[num_perm] = cached
    return cached


def _densify(slots: list[int], num_perm: int) -> None:
    """Fill empty slots in place, so short documents still compare meaningfully.

    A 40-character post produces ~36 shingles across 128 slots, so most slots are
    empty. Comparing raw sentinels would score any two short posts as ~100%
    similar purely because they were both short — the estimator would be
    measuring length, not content.

    Each empty slot borrows the value of the first occupied slot in **its own**
    probe order. The order is a function of the empty slot alone, never of the
    document, which is what makes two documents agree: both walk the same
    sequence from the same slot, so they land on the same donor and agree exactly
    when they agreed there.

    ⚠️ **An earlier version XOR-ed a per-slot mask over the borrowed value,
    justified as decorrelating the borrowers. That justification was wrong and
    the mask is gone.** XOR with a constant **preserves equality** — ``a ^ m ==
    b ^ m`` exactly when ``a == b`` — so it could not change the agreement
    pattern :func:`estimate_jaccard` counts, and therefore could not affect the
    estimate at all. Found because mutation **M11**, which deleted the mask,
    survived every test: it survived because it was an *equivalent* mutation, and
    the honest response to an equivalent mutation over dead code is to delete the
    code rather than to write a test that pins it.
    """
    orders = _probe_orders(num_perm)
    for j in range(num_perm):
        if slots[j] != EMPTY:
            continue
        for donor in orders[j]:
            value = slots[donor]
            if value != EMPTY:
                slots[j] = value
                break


def signature(shingle_set: Iterable[str], num_perm: int = 128) -> tuple[int, ...] | None:
    """The ``num_perm``-slot sketch of a shingle set, or ``None`` when it is empty.

    ``None`` rather than a signature of sentinels: an empty set is not similar to
    anything, and a sentinel-filled signature would be *identical* to every other
    empty one, silently grouping every body-less post in a run into one group.
    :class:`LshIndex` refuses ``None`` for the same reason.

    One CRC-32 per shingle. ``slot = h % num_perm`` and ``value = h // num_perm``
    are independent for uniform ``h`` and cost a single divmod, which is what
    puts A5 inside its budget.
    """
    if num_perm < 1:
        raise ValueError(f"num_perm must be >= 1, got {num_perm}")

    slots = [EMPTY] * num_perm
    seen_any = False
    for shingle in shingle_set:
        seen_any = True
        h = zlib.crc32(shingle.encode("utf-8"))
        value, slot = divmod(h, num_perm)
        if value < slots[slot]:
            slots[slot] = value

    if not seen_any:
        return None

    _densify(slots, num_perm)
    return tuple(slots)


def estimate_jaccard(sig_a: Sequence[int], sig_b: Sequence[int]) -> float:
    """The fraction of slots on which two signatures agree.

    That fraction is an unbiased estimator of the Jaccard similarity of the two
    underlying shingle sets — which is the entire reason a signature can stand in
    for the sets it came from.
    """
    if len(sig_a) != len(sig_b):
        raise ValueError(
            f"signatures of different widths do not compare: {len(sig_a)} vs {len(sig_b)}"
        )
    if not sig_a:
        return 0.0
    return sum(1 for x, y in zip(sig_a, sig_b, strict=True) if x == y) / len(sig_a)


def choose_bands(num_perm: int, threshold: float) -> int:
    """How many LSH bands best approximate ``threshold`` at this signature width.

    A pair collides when it agrees on **every** row of **at least one** band, so
    a ``b``-band, ``r``-row scheme has an S-curve whose steep point sits near
    ``(1/b) ** (1/r)``. Picking ``b`` is therefore picking where the filter turns
    on, and it is computed rather than hard-coded so that changing
    ``dedup.jaccard_threshold`` in config actually moves it — a threshold key
    that left the banding at a fixed 8 would be a documented capability that does
    not exist, which is P6's ``density_threshold`` trap.

    Only divisors of ``num_perm`` are considered: a band count that did not
    divide evenly would silently drop the remainder of the signature out of the
    index. For the shipped 128 / 0.85 this returns **8** bands of 16 rows, whose
    curve turns at 0.878.
    """
    divisors = [b for b in range(1, num_perm + 1) if num_perm % b == 0]
    return min(divisors, key=lambda b: abs((1.0 / b) ** (b / num_perm) - threshold))


def bands(signature_: Sequence[int], num_bands: int) -> tuple[str, ...]:
    """Hash each contiguous block of the signature into one short band key.

    16 hex characters from ``blake2b``, against a ``String(32)``
    ``minhash_bands.band_hash`` — chosen to fit the column with room to spare
    rather than to fill it. A truncated digest is still a digest: a band key
    needs to be unlikely to collide, not cryptographic.
    """
    if num_bands < 1 or len(signature_) % num_bands:
        raise ValueError(
            f"{num_bands} bands do not divide a {len(signature_)}-slot signature evenly; "
            "the remainder would drop out of the index unnoticed"
        )
    rows = len(signature_) // num_bands
    out = []
    for b in range(num_bands):
        block = signature_[b * rows : (b + 1) * rows]
        digest = blake2b(
            b",".join(str(v).encode("ascii") for v in block), digest_size=8
        ).hexdigest()
        out.append(digest)
    return tuple(out)


class LshIndex:
    """Banded index over signatures. ``add`` then ``query``; both are O(bands).

    Deliberately in memory and per run. ``minhash_bands`` exists and P10 writes
    it (:func:`~src.dedupe.groups.band_rows`), but reading it back is a
    cross-run capability nothing needs yet: [06c
    §4.2](../../docs/06c-local-first-pipeline.md) scopes the cascade to the items
    a run collected, and a persisted index would need the ``project_id`` that
    ``0007`` has not created.
    """

    def __init__(self, num_perm: int = 128, threshold: float = 0.85) -> None:
        self.num_perm = num_perm
        self.threshold = threshold
        self.num_bands = choose_bands(num_perm, threshold)
        self._buckets: dict[tuple[int, str], list[ItemKey]] = {}
        self._signatures: dict[ItemKey, tuple[int, ...]] = {}

    def add(self, key: ItemKey, signature_: Sequence[int] | None) -> None:
        """Index one item. A ``None`` signature is skipped, not stored."""
        if signature_ is None:
            return
        sig = tuple(signature_)
        self._signatures[key] = sig
        for band_index, band_hash in enumerate(bands(sig, self.num_bands)):
            self._buckets.setdefault((band_index, band_hash), []).append(key)

    def candidates(self, key: ItemKey) -> set[ItemKey]:
        """Keys sharing at least one band with ``key``, excluding ``key`` itself.

        Candidates, not matches. Banding is a **recall** device with a
        deliberately loose curve; the caller still checks
        :func:`estimate_jaccard` against the threshold, and
        ``test_a_band_collision_below_threshold_is_not_a_group`` is what stops a
        future reader from treating a collision as an answer.
        """
        sig = self._signatures.get(key)
        if sig is None:
            return set()
        found: set[ItemKey] = set()
        for band_index, band_hash in enumerate(bands(sig, self.num_bands)):
            found.update(self._buckets.get((band_index, band_hash), ()))
        found.discard(key)
        return found

    def similarity(self, a: ItemKey, b: ItemKey) -> float:
        """Estimated Jaccard between two indexed keys. ``0.0`` if either is absent."""
        sig_a, sig_b = self._signatures.get(a), self._signatures.get(b)
        if sig_a is None or sig_b is None:
            return 0.0
        return estimate_jaccard(sig_a, sig_b)

    def signature_of(self, key: ItemKey) -> tuple[int, ...] | None:
        return self._signatures.get(key)

    def __len__(self) -> int:
        return len(self._signatures)
