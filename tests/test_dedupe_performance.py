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

Operator decision **D5**, recorded with both measurements in [freeze §11.1].

---

## Revised 2026-08-15, after this test failed P10 acceptance testing

The operator's acceptance run measured **2.206 s** where the same commit had
measured **0.92 s** on the **same machine** minutes earlier. Investigation found
no regression — the implementation is deterministic — but **two defects in this
file**, neither of which is fixed by relaxing anything:

**1. It measured wall clock where A5 says CPU.** [34 §P10](../docs/34-implementation-plan.md)
reads *"< 2 s **CPU**"*. See :func:`cpu_seconds` for what the corrected clock
does and — importantly — does **not** protect against.

**2. Its corpus was lighter than production.** Every document was a fixed 305 or
870 characters, while real leads measure **mean 1,333 / median 1,060**, with
**56.4% at or above 870**. The larger of the two cases sat *below* the real
median, so A5 was being asserted against a workload lighter than the one P11 will
hand it. See :data:`REAL_LENGTH_PERCENTILES`.

The corrected benchmark is **harder**, not easier. Neither the 2 s budget nor any
assertion was weakened, and no `src/` code changed.

⚠️ **Sizing, per [PHASE-09-HANDOVER §4 T7].** Every budget here is set so that a
*reverted* or *degraded* implementation still **finishes and reports a verdict**
rather than producing a harness timeout that says nothing. Even the classic
implementation this replaced would complete these tests — slowly, and red, which
is the outcome a performance test exists to produce.
"""

from __future__ import annotations

import random
import string
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


def cpu_seconds() -> float:
    """The clock A5 actually specifies.

    [34 §P10](../docs/34-implementation-plan.md) reads *"MinHash indexes and
    queries 2,000 items in **< 2 s CPU**"*. This test asserted
    ``time.perf_counter()`` — **wall clock** — from the day it was written, which
    is a defect against the criterion's own wording and the reason the assertion
    failed during P10 acceptance testing at 2.206 s while the same commit
    measured 0.92 s on the same machine minutes earlier.

    **What ``process_time`` measures:** CPU time (user + system) consumed by this
    process, summed across its threads. It does **not** advance while the process
    is descheduled, sleeping, or blocked on I/O — so a run that loses the core to
    a browser, an antivirus sweep or the dashboard from
    ``docs/testing/P10-testing.md`` T10 no longer charges that stolen time to the
    dedup cascade.

    **What it does NOT measure, and this is the honest limit of the fix.** It is
    *not* immune to contention. Measured on this host 2026-08-15, the same 2,000
    items under 24 competing processes: **wall clock inflated 2.08×, CPU time
    1.97×**. Only about 5% of the observed slowdown was descheduling; the rest is
    the same instructions genuinely costing more CPU-seconds under cache and SMT
    pressure. Switching clocks makes the test measure *the right quantity*; it
    does not make an absolute threshold immune to a busy machine.

    **Why not ``time.thread_time()``**, which is narrower still: the work here is
    single-threaded, so the two agree — but ``process_time`` is the quantity a
    budget is naturally written about (the cost the *run* pays), and a background
    thread inside this process burning CPU during a real run genuinely would be
    part of that cost. The narrower clock would hide it.
    """
    return time.process_time()


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
    """Assert a CPU budget, unless a tracer has made the number meaningless."""
    if tracing_is_active():
        pytest.skip(
            f"measured {elapsed:.2f}s CPU against a {budget}s budget, but a tracer is active "
            "and costs ~3x here. The budget is asserted on the uninstrumented run (docs/35 "
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

#: The length distribution of **real** leads, measured 2026-08-15 over all 488
#: rows of ``data/leads.db`` as ``len(title + "\n" + body)``. Percentile, chars.
#:
#: ⚠️ **The corpus this replaced was not representative, and that is why A5 read
#: as comfortable when it is not.** The old benchmark generated every document at
#: a fixed 305 or 870 characters. Against the real distribution:
#:
#: * **85.0%** of real leads are at least 305 characters
#: * **56.4%** are at least 870 characters
#: * the real **median is 1,060** and the **mean 1,333**, with p90 at 2,913 and
#:   p95 at 4,260
#:
#: So the larger of the two old cases sat *below* the median real post, and the
#: benchmark was measuring a workload lighter than the one P11 will hand it.
#: Cost in this cascade is close to linear in characters — shingling alone is 42%
#: of the total — so an undersized corpus understates the budget directly.
#:
#: Only the **length distribution** is taken from real data. The text itself is
#: generated from :data:`WORDS`; no Reddit content, author or permalink enters
#: the repository ([lock §5.1](../docs/EXECUTION_MODE_LOCK.md) H2).
REAL_LENGTH_PERCENTILES: tuple[tuple[float, int], ...] = (
    (0.00, 27),
    (0.05, 70),
    (0.10, 106),
    (0.25, 522),
    (0.50, 1060),
    (0.75, 1721),
    (0.90, 2913),
    (0.95, 4260),
    (0.99, 5094),
    (1.00, 5125),
)

#: Measured mean and median of the same 488 real leads, asserted against the
#: generated corpus by :func:`test_the_benchmark_corpus_matches_real_data` so the
#: benchmark cannot silently drift back into being easy.
REAL_MEAN_CHARS = 1333
REAL_MEDIAN_CHARS = 1060

#: The fixed title every generated document carries, counted against its target
#: length so that ``len(title + "\n" + body)`` lands on the drawn value.
BENCH_TITLE = "which crm should i use for my team"

#: Mean **distinct** character 5-grams per real lead, and per character — measured
#: 2026-08-15 over the same 488 rows.
#:
#: ⚠️ **This, not character count, is what the cascade actually pays for.**
#: :func:`~src.dedupe.minhash.shingles` returns a **set**, so cost tracks distinct
#: 5-grams. Matching real data on length alone is not enough, and the first
#: version of this corpus proved it: it hit the right mean length (1,380 chars)
#: while producing **391** distinct 5-grams against a real **1,053** — 2.7× too
#: little work, and therefore *still* an easy benchmark wearing a representative
#: label.
#:
#: The cause was vocabulary saturation. :data:`WORDS` holds 19 words, and 19 words
#: can only spell so many distinct 5-grams: measured, a document built from that
#: pool yields **65** distinct 5-grams whether it is 259 characters long or 7,799.
#: Length was being matched while the work was not.
REAL_DISTINCT_SHINGLES = 1053
REAL_SHINGLES_PER_CHAR = 0.84

#: Vocabulary size for the generated corpus, chosen by measurement rather than by
#: taste: a pool of 19 words reproduces 0.32 distinct 5-grams per character, 100
#: gives 0.67, 500 gives 0.91, and real prose sits at **0.84**. Real Reddit text is
#: topically narrow but lexically varied, which is what this reproduces —
#: :data:`WORDS` supplies the topic, the rest supplies the variety.
BENCH_VOCABULARY_SIZE = 400


def _vocabulary(seed: int = SEED) -> list[str]:
    """Topic words plus filler, sized to real text's 5-gram diversity."""
    rng = random.Random(seed)
    pool = list(WORDS)
    while len(pool) < BENCH_VOCABULARY_SIZE:
        pool.append("".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(4, 11))))
    return pool


def _length_for(u: float) -> int:
    """Interpolate a document length from the measured percentile table."""
    points = REAL_LENGTH_PERCENTILES
    for (p_lo, len_lo), (p_hi, len_hi) in zip(points, points[1:], strict=False):
        if u <= p_hi:
            span = p_hi - p_lo
            frac = 0.0 if span == 0 else (u - p_lo) / span
            return int(len_lo + frac * (len_hi - len_lo))
    return points[-1][1]


def _representative_corpus(n: int = 2000, seed: int = SEED) -> list[DedupItem]:
    """``n`` documents whose length distribution matches real leads.

    This is the corpus A5 is asserted against, because it is the workload P11
    will actually process: ``max_items_per_run`` items drawn from the same length
    distribution as the leads already in the database.

    Deterministic under ``seed`` — a performance test whose *input* varied
    between runs could not distinguish a regression from a different corpus.
    """
    rng = random.Random(seed)
    pool = _vocabulary(seed)
    header = len(BENCH_TITLE) + 1  # the title and the "\n" join
    items = []
    for row_id in range(1, n + 1):
        target_chars = _length_for(rng.random())
        # Fill to the target LENGTH rather than converting to a word count via a
        # constant. The first version of this divided by the real corpus's 6.05
        # chars-per-word, but the word pool averages 7.47 including its space, so
        # every document came out 23% too long and the corpus mean landed at
        # 1,774 against a real 1,333. Filling directly is exact and cannot drift
        # if the vocabulary is ever edited -- and it was the corpus self-check
        # below, not a person, that caught the arithmetic.
        parts: list[str] = []
        length = header
        while length < target_chars:
            word = rng.choice(pool)
            parts.append(word)
            length += len(word) + 1
        items.append(
            DedupItem(
                key=("lead", row_id),
                title=BENCH_TITLE,
                body=" ".join(parts),
            )
        )
    return items


def _corpus(n: int, body_words: int, seed: int = SEED) -> list[DedupItem]:
    """Fixed-length documents. Retained only for the tier-1 and adversarial
    cases below, where document *shape* rather than realistic size is the point.
    A5 itself uses :func:`_representative_corpus`."""
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


def test_the_benchmark_corpus_matches_real_data():
    """The benchmark asserts its own representativeness.

    Without this, a future edit could quietly shrink the corpus and A5 would go
    green by measuring less work — which is exactly how the 870-character version
    passed for a phase while the real median was 1,060.
    """
    items = _representative_corpus()
    lengths = sorted(len(f"{i.title}\n{i.body}") for i in items)
    mean = sum(lengths) / len(lengths)
    median = lengths[len(lengths) // 2]

    assert len(items) == 2000, "A5 is specified at max_items_per_run"
    assert abs(mean - REAL_MEAN_CHARS) / REAL_MEAN_CHARS < 0.15, (
        f"generated mean {mean:.0f} chars against a real {REAL_MEAN_CHARS}"
    )
    assert abs(median - REAL_MEDIAN_CHARS) / REAL_MEDIAN_CHARS < 0.20, (
        f"generated median {median} chars against a real {REAL_MEDIAN_CHARS}"
    )
    # And the tail is present -- a corpus of uniformly median-sized documents
    # would match on the mean while missing the p90/p95 posts that cost most.
    assert lengths[int(len(lengths) * 0.90)] > 2000, "the long tail is missing"

    # ⚠️ The one that matters most, and the one the first version of this corpus
    # failed while passing every length check above. `shingles()` returns a SET,
    # so the cascade pays per DISTINCT 5-gram. A corpus can match real data on
    # every length percentile and still be 2.7x too easy.
    distinct = [len(shingles(f"{i.title}\n{i.body}", 5)) for i in items]
    mean_distinct = sum(distinct) / len(distinct)
    per_char = mean_distinct / mean

    assert abs(mean_distinct - REAL_DISTINCT_SHINGLES) / REAL_DISTINCT_SHINGLES < 0.25, (
        f"generated {mean_distinct:.0f} distinct 5-grams/doc against a real "
        f"{REAL_DISTINCT_SHINGLES} -- the benchmark is measuring less work than production"
    )
    assert abs(per_char - REAL_SHINGLES_PER_CHAR) / REAL_SHINGLES_PER_CHAR < 0.25, (
        f"generated {per_char:.2f} distinct 5-grams per character against a real "
        f"{REAL_SHINGLES_PER_CHAR} -- vocabulary saturation makes long documents cheap"
    )


def test_a5_minhash_indexes_and_queries_2000_items_under_two_seconds():
    """The acceptance criterion itself, on the workload P11 will actually process.

    Indexing **and** querying, because A5 names both and because the two have
    different costs: indexing is O(shingles), querying is O(bands) per item plus
    whatever the buckets return.

    **Two corrections, both made after this assertion failed P10 acceptance
    testing at 2.206 s.** Neither relaxes it:

    1. It measures **CPU time**, which is what A5 says. See :func:`cpu_seconds`.
    2. It runs on a **representative** corpus — 2,000 documents drawn from the
       measured length distribution of real leads — rather than 2,000 documents
       of a fixed 305 or 870 characters, the larger of which sat *below* the real
       median of 1,060. See :data:`REAL_LENGTH_PERCENTILES`.

    The second correction makes this test **harder**, not easier, and it is the
    one that matters: the budget is tighter against real data than the old
    benchmark ever showed.
    """
    items = _representative_corpus()
    settings = DedupSettings()

    started = cpu_seconds()

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

    elapsed = cpu_seconds() - started

    assert len(index) == 2_000
    assert_within(
        elapsed,
        A5_BUDGET_SECONDS,
        f"A5: 2,000 representative items indexed and queried in {elapsed:.2f}s CPU, budget "
        f"{A5_BUDGET_SECONDS}s. Classic 128-permutation MinHash measured 6.36s/11.11s on a "
        "LIGHTER corpus, which is why this module ships One-Permutation Hashing "
        "(freeze §11.1, 2026-08-14).",
    )


def test_the_whole_cascade_over_2000_items_stays_within_a_run_budget():
    """The number an operator actually waits on: hashing, shingling, signing,
    banding, candidate lookup, Jaccard checks and grouping, end to end.

    Budgeted at 5× A5's own figure rather than at 2 s, because the cascade does
    strictly more than the two stages A5 names and no document fixes a number for
    the whole of it. Loose enough to be a **regression** guard rather than a
    benchmark that goes red on a busy CI runner.

    On the **representative** corpus, like A5 — this is the one number that
    answers *"how long does an operator wait?"*, so measuring it on documents
    lighter than real ones would answer a question nobody asked.
    """
    items = _representative_corpus()

    started = cpu_seconds()
    result = build_groups(items, DedupSettings())
    elapsed = cpu_seconds() - started

    assert result.content_hashes.keys() == {i.key for i in items}
    assert_within(elapsed, 10.0, f"the full cascade took {elapsed:.2f}s CPU over 2,000 items")


def test_the_exact_tier_alone_is_cheap():
    """Tier 1 runs first precisely because it is the cheap one; if it ever stops
    being cheap, the tier ordering stops paying for itself.

    Deliberately kept on the **fixed-size** corpus. Its budget was calibrated
    against 305-character documents, and changing the corpus and the budget in the
    same edit would destroy the baseline this guard exists to hold — the drift it
    watches for is in `content_hash`, not in how long a post is.
    """
    items = _corpus(2_000, 40)

    started = cpu_seconds()
    for item in items:
        content_hash(item.title, item.body)
    elapsed = cpu_seconds() - started

    assert_within(elapsed, 1.0, f"2,000 content hashes took {elapsed:.2f}s CPU")


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

    started = cpu_seconds()
    result = build_groups(items, DedupSettings())
    elapsed = cpu_seconds() - started

    assert len(result.groups) == 1
    assert result.groups[0].member_count == 500
    assert_within(elapsed, 5.0, f"500 identical items took {elapsed:.2f}s CPU")


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
