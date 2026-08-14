"""Tier 2 — shingling, the 128-slot signature, banding, and the LSH index.

The estimator is the thing under test. A signature that is fast and wrong groups
unrelated posts, and the operator finds out by reading a *"similar discussions"*
panel that lists a pizza thread under a CRM question.
"""

from __future__ import annotations

import pytest

from src.dedupe.exact import normalise
from src.dedupe.minhash import (
    EMPTY,
    LshIndex,
    bands,
    choose_bands,
    estimate_jaccard,
    shingles,
    signature,
)


def true_jaccard(a: str, b: str, k: int = 5) -> float:
    sa, sb = shingles(a, k), shingles(b, k)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


# --------------------------------------------------------------- shingles


def test_shingles_are_character_ngrams():
    assert shingles("abcdef", 5) == {"abcde", "bcdef"}


def test_shingles_are_a_set_not_a_list():
    """A post that repeats itself four times is not less like the one that says it once."""
    assert shingles("ababababab", 2) == {"ab", "ba"}


def test_text_shorter_than_k_becomes_one_shingle():
    """Boundary. An empty set here would make every short post un-groupable."""
    assert shingles("abc", 5) == {"abc"}
    assert shingles("abcde", 5) == {"abcde"}


def test_empty_text_has_no_shingles():
    assert shingles("", 5) == set()


def test_shingle_k_below_one_is_refused():
    with pytest.raises(ValueError, match="shingle_k must be >= 1"):
        shingles("abc", 0)


# -------------------------------------------------------------- signature


def test_a_signature_has_one_slot_per_permutation():
    sig = signature(shingles("which crm should i use for a small team"), 128)
    assert sig is not None
    assert len(sig) == 128


def test_an_empty_shingle_set_has_no_signature():
    """``None``, not a signature of sentinels.

    A sentinel-filled signature would be **identical** to every other empty one,
    silently grouping every body-less post in a run into a single group.
    """
    assert signature(set(), 128) is None
    assert signature([], 128) is None


def test_densification_leaves_no_sentinel_behind():
    """A 20-character post fills ~16 of 128 slots; the rest must be borrowed.

    Comparing raw sentinels would score any two short posts as ~87% similar
    purely because they were both short — measuring length, not content.
    """
    sig = signature(shingles("tiny post here"), 128)
    assert sig is not None
    assert EMPTY not in sig


def test_the_signature_is_deterministic():
    text = "which crm should i use for a small team of five people"
    assert signature(shingles(text), 128) == signature(shingles(text), 128)


def test_identical_text_has_identical_signatures():
    a = signature(shingles("the same words exactly"), 128)
    b = signature(shingles("the same words exactly"), 128)
    assert a == b
    assert estimate_jaccard(a, b) == 1.0


def test_num_perm_below_one_is_refused():
    with pytest.raises(ValueError, match="num_perm must be >= 1"):
        signature({"abcde"}, 0)


# ------------------------------------------------------------- estimation


@pytest.mark.parametrize(
    "a, b",
    [
        (
            "which crm should i use for my small startup team",
            "which crm should i use for my small startup team",
        ),
        (
            "our spreadsheets are falling apart and we need a real tool",
            "our spreadsheets are falling apart and we need a real system",
        ),
        (
            "best deep dish pizza in chicago for a birthday dinner",
            "which crm should i use for my small startup team",
        ),
    ],
)
def test_the_estimate_tracks_the_true_jaccard(a: str, b: str):
    """Within 0.10 — the accuracy claim the A5 decision rests on.

    Measured mean absolute error over 40 random pairs was **0.0279**; the bound
    here is loose enough that a passing test is not a coincidence and tight
    enough that a broken estimator cannot slip through.
    """
    estimated = estimate_jaccard(signature(shingles(a)), signature(shingles(b)))
    assert abs(estimated - true_jaccard(a, b)) < 0.10


def test_casing_and_punctuation_survive_normalisation_not_shingling():
    """Why ``groups._dedupe_text`` normalises before shingling. Measured 2026-08-14.

    [06c §4.2] chooses character n-grams *because* casing and punctuation *"vary
    far more than substance"* — a statement about what the tier must **absorb**.
    Shingling raw text does the opposite: the pair below estimates ~0.55 raw and
    ~0.98 normalised, and at a 0.85 threshold the raw form misses a repost that
    differs only in capitalisation.
    """
    a = "Which CRM should I use for my small startup team?"
    b = "which crm should i use for my small startup team"

    raw = estimate_jaccard(signature(shingles(a)), signature(shingles(b)))
    clean = estimate_jaccard(signature(shingles(normalise(a))), signature(shingles(normalise(b))))

    assert raw < 0.85, "if this rises, the measurement that justified normalising has changed"
    assert clean > 0.85


def test_signatures_of_different_widths_do_not_compare():
    with pytest.raises(ValueError, match="different widths"):
        estimate_jaccard((1, 2, 3), (1, 2))


def test_estimating_over_empty_signatures_is_zero_not_an_error():
    assert estimate_jaccard((), ()) == 0.0


# ------------------------------------------------------------------ bands


def test_choose_bands_is_computed_from_the_threshold_not_hard_coded():
    """A threshold key that left the banding fixed would be P6's ``density_threshold``.

    The S-curve of a ``b``-band scheme turns near ``(1/b) ** (1/r)``; a higher
    threshold must therefore need fewer bands, and a lower one more.
    """
    assert choose_bands(128, 0.85) == 8
    assert choose_bands(128, 0.95) < 8, "a stricter threshold needs fewer, wider bands"
    assert choose_bands(128, 0.5) > 8, "a looser threshold needs more, narrower bands"


def test_choose_bands_only_returns_divisors():
    for threshold in (0.1, 0.5, 0.85, 0.99):
        assert 128 % choose_bands(128, threshold) == 0


def test_bands_that_do_not_divide_the_signature_are_refused():
    """The remainder would drop out of the index unnoticed."""
    with pytest.raises(ValueError, match="do not divide"):
        bands(tuple(range(128)), 7)


def test_band_hashes_fit_the_column():
    """``minhash_bands.band_hash`` is ``String(32)``."""
    for band_hash in bands(tuple(range(128)), 8):
        assert len(band_hash) <= 32


def test_identical_signatures_produce_identical_bands():
    sig = tuple(range(128))
    assert bands(sig, 8) == bands(sig, 8)


def test_one_changed_slot_changes_exactly_one_band():
    sig = list(range(128))
    before = bands(tuple(sig), 8)
    sig[0] = 999999
    after = bands(tuple(sig), 8)
    assert sum(1 for x, y in zip(before, after, strict=True) if x != y) == 1


# --------------------------------------------------------------- LshIndex


def _sig(text: str):
    return signature(shingles(normalise(text)))


#: A realistic post body. Long enough that changing one word leaves the pair
#: above 0.85, which is what a near-duplicate actually looks like: an 80-character
#: title with one word changed sits near 0.76 and is correctly **not** a
#: near-duplicate at this threshold.
LONG = (
    "our spreadsheets are falling apart and we need a real crm tool for a team of "
    "five people. we have tried a few free options but none of them handle repeat "
    "customers properly and the reporting is useless. budget is tight but we can "
    "pay something monthly if it actually saves us time every week."
)


def test_the_index_finds_a_near_duplicate_as_a_candidate():
    index = LshIndex()
    index.add(("lead", 1), _sig(LONG))
    index.add(("lead", 2), _sig(LONG.replace("five people", "six people")))
    assert ("lead", 2) in index.candidates(("lead", 1))
    assert index.similarity(("lead", 1), ("lead", 2)) >= 0.85


def test_a_differently_worded_post_is_not_a_near_duplicate():
    """The other side of the threshold, asserted so 0.85 means something.

    A suite that only ever showed the tier grouping things would pass just as
    well against a tier that grouped everything.

    The fixture is **well clear** of the threshold (true Jaccard 0.270), not just
    below it, and that is deliberate — see
    :func:`test_near_the_threshold_the_sketch_and_exact_jaccard_can_disagree`.
    """
    index = LshIndex()
    a = "our spreadsheets are falling apart and we need a real crm tool for five people"
    b = "our spreadsheets are falling apart but the budget was cut again this quarter"
    index.add(("lead", 1), _sig(a))
    index.add(("lead", 2), _sig(b))
    assert index.similarity(("lead", 1), ("lead", 2)) < 0.85


def test_near_the_threshold_the_sketch_and_exact_jaccard_can_disagree():
    """A measured property of **any** MinHash, pinned so it is not rediscovered.

    A 128-slot sketch estimates Jaccard to roughly ±0.05, so a pair whose exact
    similarity sits inside that band of the threshold may fall on either side of
    it. Measured 2026-08-14: the pair below is **0.815** exactly and estimates
    **0.859**, so it groups where an exact computation would not.

    This is inherent to sketching, not a defect in this implementation — classic
    128-permutation MinHash measured a *larger* mean error (0.0308 against
    0.0279) on the same corpus. It is pinned here because the alternative is a
    future reader finding one such pair, concluding the estimator is broken, and
    "fixing" it by computing exact Jaccard over every candidate — which is the
    O(n²) cost banding exists to avoid.

    The operational consequence is bounded and benign: a borderline pair is
    grouped, one of the two is enriched, and **both still keep their own score**
    ([06c §4.4]). Nothing is discarded.
    """
    a = "our spreadsheets are falling apart and we need a real crm tool for five people"
    b = a.replace("five people", "six people")

    exact = true_jaccard(a, b)
    estimated = estimate_jaccard(signature(shingles(a)), signature(shingles(b)))

    assert exact < 0.85 < estimated
    assert abs(estimated - exact) < 0.10


def test_the_index_does_not_offer_an_unrelated_post():
    index = LshIndex()
    index.add(("lead", 1), _sig("which crm should i use for my small startup team"))
    index.add(("lead", 2), _sig("best deep dish pizza in chicago for a birthday dinner"))
    assert index.candidates(("lead", 1)) == set()


def test_a_key_is_never_its_own_candidate():
    index = LshIndex()
    index.add(("lead", 1), _sig("which crm should i use"))
    assert ("lead", 1) not in index.candidates(("lead", 1))


def test_a_none_signature_is_skipped_not_stored():
    index = LshIndex()
    index.add(("lead", 1), None)
    assert len(index) == 0
    assert index.candidates(("lead", 1)) == set()
    assert index.signature_of(("lead", 1)) is None


def test_similarity_with_an_unknown_key_is_zero():
    index = LshIndex()
    index.add(("lead", 1), _sig("which crm should i use"))
    assert index.similarity(("lead", 1), ("lead", 99)) == 0.0


def test_candidates_are_recall_and_similarity_is_the_decision():
    """Banding is recall; the Jaccard comparison is the decision.

    Constructed rather than hoped for: two signatures are given an **identical
    first band** and random remaining slots, so they are guaranteed to collide
    while being nowhere near similar. ``candidates()`` offers the pair and
    ``similarity()`` refuses it — which is why ``build_groups`` must consult the
    second before it groups. A version of this test that merely hoped for a
    natural collision would pass vacuously most days.
    """
    index = LshIndex()
    shared_band = list(range(16))
    a = tuple(shared_band + [1000 + i for i in range(112)])
    b = tuple(shared_band + [5000 + i for i in range(112)])
    index.add(("lead", 1), a)
    index.add(("lead", 2), b)

    assert ("lead", 2) in index.candidates(("lead", 1)), "an identical band must collide"
    assert index.similarity(("lead", 1), ("lead", 2)) < 0.85
