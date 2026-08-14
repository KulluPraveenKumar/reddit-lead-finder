"""Acceptance *"property test: no input crashes"*, read the way P9 learned to read it.

Two departures, both inherited deliberately from ``tests/test_rules_properties.py``:

* **"No input crashes" includes "no input hangs."**
  [PHASE-09-HANDOVER §4 T6] is emphatic: the property tests found P9's only real
  defect, and they found it as **67.8 seconds of CPU**, not as an exception. ``re``
  has no timeout and a catastrophic backtrack raises nothing — it wedges the
  worker. P10's shingling, normalisation and edit-marker scan take the **same
  attacker-supplied text**, so every property here is bounded in wall clock as
  well as in outcome.
* **No ``hypothesis``.** It is not installed and not in ``requirements.txt``, and
  [freeze §5] closes the technology set. Generation is stdlib ``random`` under a
  **fixed seed**, so a failure reproduces exactly rather than "sometimes on
  Tuesdays".
"""

from __future__ import annotations

import random
import string
import time
import unicodedata

import pytest

from src.dedupe import DedupItem, DedupSettings
from src.dedupe.exact import content_hash, group_exact, normalise, strip_trailing_edits
from src.dedupe.groups import build_groups, validate_membership
from src.dedupe.minhash import LshIndex, bands, estimate_jaccard, shingles, signature
from src.dedupe.semantic import cosine

SEED = 20260814

#: Inputs chosen because each has broken a text pipeline somewhere before. The
#: whitespace runs are the shape that cost P9 67.8 seconds; the RTL override and
#: the lone surrogate-adjacent codepoints are the shape that breaks encoders.
HOSTILE: tuple[str, ...] = (
    "",
    " ",
    "\n",
    "\r\n",
    "\t\t\t",
    " " * 10_000,
    "\n" * 5_000,
    "*" * 10_000,
    "_" * 10_000,
    "`" * 10_000,
    "~" * 10_000,
    "EDIT:" * 2_000,
    "edit: " + "x" * 10_000,
    "a" * 50_000,
    "ab" * 25_000,
    "‮" + "reversed text",
    "café",
    unicodedata.normalize("NFD", "café"),
    "🙂" * 2_000,
    "\x00\x01\x02",
    "\\" * 1_000,
    "[" * 1_000 + "]" * 1_000,
    "(" * 1_000,
    "[hiring] " * 500,
    "  \t \n  mixed \r\n whitespace \t  ",
)

#: Anything slower than this on a single hostile input is a hang, not slowness.
#: Sized the way [PHASE-09-HANDOVER §4 T7] requires: generous enough that a
#: **reverted** implementation still finishes and reports a verdict, rather than
#: producing a harness timeout that says nothing.
BUDGET_SECONDS = 2.0


def _rng() -> random.Random:
    return random.Random(SEED)


def _random_text(rng: random.Random, max_len: int = 400) -> str:
    alphabet = string.printable + "áéíóúüñ日本語🙂‮́"
    return "".join(rng.choice(alphabet) for _ in range(rng.randrange(max_len)))


@pytest.mark.parametrize("text", HOSTILE, ids=lambda t: repr(t[:24]))
def test_no_hostile_input_crashes_or_hangs_the_exact_tier(text: str):
    started = time.perf_counter()
    normalise(text)
    strip_trailing_edits(text)
    content_hash(text, text)
    elapsed = time.perf_counter() - started
    assert elapsed < BUDGET_SECONDS, (
        f"{elapsed:.2f}s on {text[:24]!r} -- this is a hang, not slowness"
    )


@pytest.mark.parametrize("text", HOSTILE, ids=lambda t: repr(t[:24]))
def test_no_hostile_input_crashes_or_hangs_the_minhash_tier(text: str):
    started = time.perf_counter()
    sig = signature(shingles(text, 5), 128)
    if sig is not None:
        bands(sig, 8)
    elapsed = time.perf_counter() - started
    assert elapsed < BUDGET_SECONDS, (
        f"{elapsed:.2f}s on {text[:24]!r} -- this is a hang, not slowness"
    )


def test_whitespace_scaling_is_not_quadratic():
    """P9's own regression, transplanted to the module that inherits the input.

    Sized per T7 so a reverted fix still *finishes*: 8,000 against 32,000, not
    against 128,000. A first draft of P9's equivalent used 128,000 and took over
    fifteen minutes under mutation, producing a harness timeout rather than a
    verdict.
    """

    def timed(n: int) -> float:
        text = " " * n
        started = time.perf_counter()
        normalise(text)
        signature(shingles(text, 5), 128)
        return time.perf_counter() - started

    small = max(timed(8_000), 1e-4)
    large = timed(32_000)
    # Four times the input must not cost more than ~sixteen times the time; a
    # quadratic path costs sixteen and a catastrophic one costs unboundedly more.
    assert large / small < 40, f"{small:.4f}s -> {large:.4f}s looks super-linear"


# ------------------------------------------------------- invariants


def test_normalise_is_idempotent():
    """Normalising twice must equal normalising once, or the hash of a hash
    differs from the hash and tier 1 stops being a function of the content."""
    rng = _rng()
    for _ in range(300):
        text = _random_text(rng)
        once = normalise(text)
        assert normalise(once) == once


def test_the_content_hash_is_a_function_of_its_input():
    rng = _rng()
    for _ in range(200):
        title, body = _random_text(rng, 80), _random_text(rng, 200)
        assert content_hash(title, body) == content_hash(title, body)


def test_a_signature_is_always_the_requested_width_or_none():
    rng = _rng()
    for _ in range(200):
        sig = signature(shingles(_random_text(rng), 5), 128)
        assert sig is None or len(sig) == 128


def test_estimated_similarity_is_always_a_probability():
    rng = _rng()
    for _ in range(200):
        a = signature(shingles(_random_text(rng) or "x", 5), 128)
        b = signature(shingles(_random_text(rng) or "y", 5), 128)
        assert 0.0 <= estimate_jaccard(a, b) <= 1.0


def test_a_text_is_always_perfectly_similar_to_itself():
    rng = _rng()
    for _ in range(200):
        text = _random_text(rng) or "x"
        sig = signature(shingles(text, 5), 128)
        if sig is not None:
            assert estimate_jaccard(sig, sig) == 1.0


def test_cosine_is_symmetric_and_bounded():
    rng = _rng()
    for _ in range(200):
        a = [rng.uniform(-5, 5) for _ in range(16)]
        b = [rng.uniform(-5, 5) for _ in range(16)]
        assert cosine(a, b) == pytest.approx(cosine(b, a))
        assert -1.0 <= cosine(a, b) <= 1.0


def test_every_item_lands_in_at_most_one_group_whatever_the_corpus():
    """DI22 as a property, over corpora generated to contain overlap.

    The unit tests construct the cases a reader can imagine. This one runs the
    cascade over 40 random corpora built from a small phrase pool, so exact and
    near duplicates arise by accident and in combinations nobody chose.
    """
    rng = _rng()
    phrases = [
        "which crm should i use for my small team",
        "our spreadsheets are falling apart and we need something better",
        "best deep dish pizza in chicago for a birthday",
        "how do i track repeat customers without paying a fortune",
    ]
    for _ in range(40):
        items = []
        for row_id in range(1, rng.randrange(3, 14)):
            base = rng.choice(phrases)
            body = base if rng.random() < 0.5 else base + " " + _random_text(rng, 40)
            items.append(DedupItem(("lead", row_id), rng.choice(phrases), body))
        result = build_groups(items, DedupSettings())
        validate_membership(result.groups)

        seen: set = set()
        for group in result.groups:
            for key in group.members:
                assert key not in seen
                seen.add(key)


def test_grouping_never_invents_or_loses_an_item():
    """Whatever the corpus, grouped ∪ ungrouped is exactly the corpus."""
    rng = _rng()
    for _ in range(40):
        items = [
            DedupItem(("lead", i), _random_text(rng, 60), _random_text(rng, 200))
            for i in range(1, rng.randrange(3, 12))
        ]
        universe = {i.key for i in items}
        result = build_groups(items, DedupSettings())
        assert result.grouped_keys <= universe
        assert result.content_hashes.keys() == universe


def test_group_exact_partitions_the_corpus():
    """Every item is in exactly one bucket, and no bucket is empty."""
    rng = _rng()
    for _ in range(40):
        items = [
            DedupItem(("lead", i), _random_text(rng, 40), _random_text(rng, 80))
            for i in range(1, rng.randrange(3, 12))
        ]
        buckets = group_exact(items)
        flattened = [k for keys in buckets.values() for k in keys]
        assert sorted(flattened) == sorted(i.key for i in items)
        assert all(keys for keys in buckets.values())


def test_the_index_never_returns_a_key_it_was_not_given():
    rng = _rng()
    index = LshIndex()
    keys = []
    for i in range(1, 40):
        key = ("lead", i)
        keys.append(key)
        index.add(key, signature(shingles(_random_text(rng, 200) or "x", 5), 128))
    for key in keys:
        assert index.candidates(key) <= set(keys)
