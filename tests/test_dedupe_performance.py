"""A5 — *"MinHash indexes and queries 2,000 items in < 2 s CPU"*, measured.

[34 §P10]'s Acceptance row is emphatic about this one: *"(assumption A5,
**measured**)"*. P0 left it unmeasured and it is the reason the phase carries
**Medium** risk. 2,000 is not a stress number — it is ``max_items_per_run``
([freeze §6]), so this is the *normal* case.

**The literal implementation fails it.** Classic MinHash re-hashes every shingle
under 128 independent permutations — O(shingles × 128). Measured on this host,
2,000 items, before ``src/dedupe/minhash.py`` was written:

=========================  ==================  ==================
Signatures only            Classic 128-perm    Shipped (OPH)
=========================  ==================  ==================
305 chars / 176 shingles   **6.36 s**          **0.27 s**
870 chars / 315 shingles   **11.11 s**         **0.55 s**
=========================  ==================  ==================

End to end — what :func:`test_a5_minhash_indexes_and_queries_2000_items_under_two_seconds`
actually times, which is shingling **plus** signing **plus** banding **plus** the
query stage — the shipped implementation measures **0.59 s** and **0.87 s**.
Both inside A5's 2 s; the classic figures above are already over it before
shingling or querying is counted at all.

Operator decision **D5**, recorded with both measurements in [freeze §11.1].

⚠️ **Sizing, per [PHASE-09-HANDOVER §4 T7].** Every budget here is set so that a
*reverted* or *degraded* implementation still **finishes and reports a verdict**
rather than producing a harness timeout that says nothing. Even the classic
implementation this replaced would complete these tests — slowly, and red, which
is the outcome a performance test exists to produce.
"""

from __future__ import annotations

import random
import sys
import time

import pytest

from src.dedupe import DedupItem, DedupSettings
from src.dedupe.exact import content_hash
from src.dedupe.groups import build_groups
from src.dedupe.minhash import LshIndex, shingles, signature

SEED = 20260814

#: A5's budget.
A5_BUDGET_SECONDS = 2.0


def tracing_is_active() -> bool:
    """Whether a tracer (``coverage``, a debugger, a profiler) is installed.

    ⚠️ **Timing assertions are meaningless under tracing, and this is measured,
    not assumed.** [35 §2.1](../docs/35-testing-strategy.md) check 7 runs the
    whole suite under ``--cov``, and coverage's tracer costs **3.0×** here:
    A5's two cases measure 0.59 s / 0.87 s bare and 1.76 s / 2.63 s instrumented,
    so the 870-char case fails a 2 s budget purely because it was being watched.
    Measured 2026-08-14.

    The response is to **skip the assertion and say so**, not to inflate the
    budget. A5 is a claim about the CPU an operator's run will spend; a budget
    padded to survive instrumentation would no longer be that claim, and the
    number in [34 §P10](../docs/34-implementation-plan.md) would quietly stop
    meaning what it says.

    The criterion is still enforced on every gate: checks 4 and 5 run
    ``pytest tests/…`` **without** coverage, and that is the run this assertion
    fires on. The body above the assertion executes either way, so the code stays
    covered.

    ``coverage.Coverage.current()`` is checked as well as ``sys.gettrace()``
    because coverage's C tracer does not always register through the latter.
    """
    if sys.gettrace() is not None:
        return True
    try:
        import coverage

        return coverage.Coverage.current() is not None
    except Exception:
        return False


def assert_within(elapsed: float, budget: float, message: str) -> None:
    """Assert a timing budget, unless a tracer has made the number meaningless."""
    if tracing_is_active():
        pytest.skip(
            f"timed {elapsed:.2f}s against a {budget}s budget, but a tracer is active and "
            "costs ~3x here. The budget is asserted on the uninstrumented run (docs/35 "
            "§2.1 checks 4-5); padding it to survive coverage would stop it meaning what "
            "docs/34 §P10 says."
        )
    assert elapsed < budget, message


#: Vocabulary for the synthetic corpus. Small on purpose: a realistic subreddit
#: is topically narrow, which is the case that stresses LSH bucketing hardest —
#: a corpus of unrelated noise would collide in no band and make the query stage
#: look free.
WORDS = [
    "crm",
    "tool",
    "looking",
    "for",
    "recommend",
    "startup",
    "saas",
    "help",
    "problem",
    "billing",
    "invoice",
    "team",
    "workflow",
    "spreadsheet",
    "customers",
    "pricing",
    "support",
    "onboarding",
    "churn",
]


def _corpus(n: int, body_words: int, seed: int = SEED) -> list[DedupItem]:
    rng = random.Random(seed)
    items = []
    for row_id in range(1, n + 1):
        body = " ".join(rng.choice(WORDS) for _ in range(body_words))
        items.append(
            DedupItem(
                key=("lead", row_id),
                title="which crm should i use for my team",
                body=body,
            )
        )
    return items


@pytest.mark.parametrize("body_words", [40, 120], ids=["305-char-bodies", "870-char-bodies"])
def test_a5_minhash_indexes_and_queries_2000_items_under_two_seconds(body_words: int):
    """The acceptance criterion itself, both stages, at both document sizes.

    Indexing **and** querying, because A5 names both and because the two have
    different costs: indexing is O(shingles), querying is O(bands) per item plus
    whatever the buckets return.
    """
    items = _corpus(2_000, body_words)
    settings = DedupSettings()

    started = time.perf_counter()

    index = LshIndex(num_perm=settings.num_perm, threshold=settings.jaccard_threshold)
    for item in items:
        index.add(
            item.key,
            signature(
                shingles(f"{item.title}\n{item.body}", settings.shingle_k), settings.num_perm
            ),
        )
    for item in items:
        index.candidates(item.key)

    elapsed = time.perf_counter() - started

    assert len(index) == 2_000
    assert_within(
        elapsed,
        A5_BUDGET_SECONDS,
        f"A5: 2,000 items indexed and queried in {elapsed:.2f}s, budget {A5_BUDGET_SECONDS}s. "
        "Classic 128-permutation MinHash measured 6.36s/11.11s here, which is why this "
        "module ships One-Permutation Hashing (freeze §11.1, 2026-08-14).",
    )


def test_the_whole_cascade_over_2000_items_stays_within_a_run_budget():
    """The number an operator actually waits on: hashing, shingling, signing,
    banding, candidate lookup, Jaccard checks and grouping, end to end.

    Budgeted at 5× A5's own figure rather than at 2 s, because the cascade does
    strictly more than the two stages A5 names and no document fixes a number for
    the whole of it. Loose enough to be a **regression** guard rather than a
    benchmark that goes red on a busy CI runner.
    """
    items = _corpus(2_000, 40)

    started = time.perf_counter()
    result = build_groups(items, DedupSettings())
    elapsed = time.perf_counter() - started

    assert result.content_hashes.keys() == {i.key for i in items}
    assert_within(elapsed, 10.0, f"the full cascade took {elapsed:.2f}s over 2,000 items")


def test_the_exact_tier_alone_is_cheap():
    """Tier 1 runs first precisely because it is the cheap one; if it ever stops
    being cheap, the tier ordering stops paying for itself."""
    items = _corpus(2_000, 40)

    started = time.perf_counter()
    for item in items:
        content_hash(item.title, item.body)
    elapsed = time.perf_counter() - started

    assert_within(elapsed, 1.0, f"2,000 content hashes took {elapsed:.2f}s")


def test_a_topically_identical_corpus_does_not_degrade_to_quadratic():
    """The adversarial shape for LSH: **every** item in one bucket.

    A corpus of 500 identical posts makes every band collide, so ``candidates()``
    returns 499 keys for each of 500 items. That is inherent to the data, not a
    defect — but it must stay a *bounded* cost rather than an unbounded one, and
    the exact tier claims them all first so the near tier never runs the
    comparison at all.

    500 rather than 2,000: the quadratic term is what is being bounded, and at
    2,000 a genuinely quadratic implementation would take long enough to look
    like a hung harness instead of a failed assertion (T7).
    """
    items = [DedupItem(("lead", i), "identical", "identical body text here") for i in range(1, 501)]

    started = time.perf_counter()
    result = build_groups(items, DedupSettings())
    elapsed = time.perf_counter() - started

    assert len(result.groups) == 1
    assert result.groups[0].member_count == 500
    assert_within(elapsed, 5.0, f"500 identical items took {elapsed:.2f}s")


def test_collapse_rate_is_measurable_on_a_corpus_with_known_duplicates():
    """[34 §P10]'s Metrics row asks for *"collapse rate > 8% on real data"*.

    Real data is the completion report's measurement over the live 459 leads;
    what a test can hold is that the *metric* responds to duplicates rather than
    reporting a constant. A corpus seeded with 10% exact duplicates must collapse
    by about 10%.
    """
    base = _corpus(900, 40)
    duplicates = [
        DedupItem(key=("lead", 1000 + i), title=base[i].title, body=base[i].body)
        for i in range(100)
    ]
    result = build_groups(base + duplicates, DedupSettings())

    rate = result.collapse_rate(len(base) + len(duplicates))
    assert 0.08 < rate < 0.15, f"collapse rate {rate:.1%} on a corpus seeded with 10% duplicates"
