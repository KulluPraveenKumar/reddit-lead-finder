"""Tier 3 — optional, local, never authoritative.

**The unavailable path is the default path.** P0 measured neither ``model2vec``
nor ``sqlite_vec`` as installed, and deliberately did not install them, because
absent is the state [AD-16] exists to protect. So the tests that matter most here
are the ones that show the tier contributing **nothing** without failing anything.

No test in this file reaches the network. ``StaticModel.from_pretrained``
downloads a model and [35 §2.1] check 6 blocks the socket for the whole suite —
which is exactly why :class:`~src.dedupe.semantic.Encoder` is a ``Protocol``.
"""

from __future__ import annotations

import math

import pytest

from src.dedupe import DedupItem, DedupSettings
from src.dedupe.groups import build_groups
from src.dedupe.semantic import DEFAULT_MODEL, cosine, is_available, load_encoder, similar_pairs


class FakeEncoder:
    """Vectors by lookup. The paraphrases point almost the same way; the pizza does not."""

    VECTORS = {
        "which crm should i use\nrecommend something for a small team": [1.0, 0.0, 0.0],
        "customer relationship software suggestions\nwhat do you all like": [0.99, 0.141, 0.0],
        "best deep dish pizza in chicago\nvisiting next week": [0.0, 0.0, 1.0],
    }

    def encode(self, texts):
        return [self.VECTORS[t] for t in texts]


class ExplodingEncoder:
    def encode(self, texts):
        raise RuntimeError("the weights are corrupt")


class MiscountingEncoder:
    """Returns **two** vectors for three texts — the count that actually misleads.

    ⚠️ An earlier version returned **one**, and mutation **M20** (deleting the
    count guard) survived against it: with one vector the pair loop has nothing
    to pair and returns ``[]`` whether or not the guard exists. Two vectors is
    the case where a missing guard silently pairs **the wrong texts** — the
    failure the guard is for. P9's **T5** again: the survivor was the fixture.
    """

    def encode(self, texts):
        return [[1.0, 0.0], [1.0, 0.0]]


PARAPHRASES = [
    DedupItem(("lead", 1), "Which CRM should I use", "Recommend something for a small team"),
    DedupItem(("lead", 2), "Customer relationship software suggestions", "What do you all like"),
    DedupItem(("lead", 3), "Best deep dish pizza in Chicago", "Visiting next week"),
]


# ------------------------------------------------------------------ cosine


def test_cosine_of_a_vector_with_itself_is_exactly_one():
    """Clamped. Floating-point error puts this at 1.0000000000000002 often enough
    to matter, and a threshold that can be beaten by rounding is not a threshold."""
    v = [0.3, -0.7, 0.1, 0.9]
    assert cosine(v, v) == 1.0


def test_cosine_of_orthogonal_vectors_is_zero():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_of_opposite_vectors_is_minus_one():
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_cosine_never_leaves_the_unit_interval():
    assert -1.0 <= cosine([1e200, 1e200], [1e200, 1e200]) <= 1.0


def test_cosine_of_a_zero_vector_is_zero_not_an_error():
    """An empty post is not similar to anything — the same answer ``signature``
    gives for the same input."""
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_refuses_mismatched_widths():
    with pytest.raises(ValueError, match="different widths"):
        cosine([1.0], [1.0, 2.0])


def test_cosine_matches_the_textbook_definition():
    a, b = [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]
    expected = sum(x * y for x, y in zip(a, b, strict=True)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )
    assert cosine(a, b) == pytest.approx(expected)


# ------------------------------------------------------------ availability


def test_is_available_reports_the_truth_about_this_host():
    """Whichever way it goes, it must not raise. P0 measured ``model2vec`` absent."""
    assert is_available() in (True, False)


def test_load_encoder_returns_none_when_the_library_is_missing(monkeypatch):
    """The no-op path, which is the normal path on every host so far."""
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "model2vec":
            raise ImportError("No module named 'model2vec'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    monkeypatch.setattr("src.dedupe.semantic._warned", False)
    assert load_encoder() is None


def test_is_available_and_load_encoder_when_the_library_is_present(monkeypatch):
    """The **installed** arm, which no host in this project has ever had.

    P0 measured ``model2vec`` absent and deliberately left it that way, so this
    path would otherwise ship untested — the exact shape of gap that makes an
    optional feature fail the first time someone enables it. A stub module is
    injected into ``sys.modules`` rather than installing the package: the real
    ``from_pretrained`` **downloads weights**, and [35 §2.1] check 6 blocks the
    socket for the whole suite.
    """
    import sys
    import types

    stub = types.ModuleType("model2vec")

    class StaticModel:
        @classmethod
        def from_pretrained(cls, name):
            model = cls()
            model.name = name
            return model

        def encode(self, texts):
            return [[1.0, 0.0] for _ in texts]

    stub.StaticModel = StaticModel
    monkeypatch.setitem(sys.modules, "model2vec", stub)

    assert is_available() is True

    encoder = load_encoder("some/model")
    assert encoder is not None
    assert encoder.name == "some/model"
    assert similar_pairs(["a", "b"], 0.99, encoder) == [(0, 1, 1.0)]


def test_a_library_that_is_present_but_broken_still_degrades_cleanly(monkeypatch):
    """``except Exception``, not ``except ImportError``: an installed model2vec
    that cannot reach its weights raises something else entirely, and the
    required behaviour for every such failure is identical."""
    import sys
    import types

    stub = types.ModuleType("model2vec")

    class StaticModel:
        @classmethod
        def from_pretrained(cls, name):
            raise OSError("could not download weights")

    stub.StaticModel = StaticModel
    monkeypatch.setitem(sys.modules, "model2vec", stub)
    monkeypatch.setattr("src.dedupe.semantic._warned", False)

    assert load_encoder() is None


def test_the_absence_is_reported_once_per_process_not_once_per_run(monkeypatch, caplog):
    """On a host where the library is simply not installed — which P0 says is
    every host — a per-call warning is a log nobody reads twice."""
    import logging

    monkeypatch.setattr("src.dedupe.semantic._warned", False)
    with caplog.at_level(logging.INFO, logger="src.dedupe.semantic"):
        load_encoder("definitely/not-a-model")
        first = len(caplog.records)
        load_encoder("definitely/not-a-model")
        second = len(caplog.records)

    assert first >= 1
    assert second == first, "the second call must not log again"


def test_the_default_model_is_a_static_distillation():
    """No GPU, no server — which is what let AD-16 call this optional and cheap."""
    assert DEFAULT_MODEL == "minishlab/potion-base-8M"


# --------------------------------------------------------- similar_pairs


def test_no_encoder_means_no_pairs():
    assert similar_pairs(["a", "b"], 0.88, None) == []


def test_having_no_encoder_is_silent_not_an_error_path(caplog):
    """The guard must *guard*, not be replaced by an exception it catches.

    Deleting `encoder is None` from the guard still returns ``[]`` — via
    ``AttributeError`` inside the ``try`` — so the return value cannot tell the
    two apart, and mutation **M18** survived on that. What differs is the
    **log**: the exception path warns, and on every host in this project there is
    no encoder, so the mutation would emit a warning on **every run forever**
    about a state that is entirely normal.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="src.dedupe.semantic"):
        assert similar_pairs(["a", "b", "c"], 0.88, None) == []

    assert caplog.records == [], (
        "no encoder is the normal state (P0 measured model2vec absent); it must not warn"
    )


def test_fewer_than_two_texts_means_no_pairs():
    assert similar_pairs(["only one"], 0.88, FakeEncoder()) == []
    assert similar_pairs([], 0.88, FakeEncoder()) == []


def test_an_encoder_that_raises_contributes_nothing_and_does_not_propagate():
    """AD-16's *never authoritative*: a broken optional layer must not fail a run."""
    assert similar_pairs(["a", "b"], 0.88, ExplodingEncoder()) == []


def test_an_encoder_returning_the_wrong_count_contributes_nothing():
    """The silent-corruption arm. Zipping mismatched lists would pair the wrong texts."""
    assert similar_pairs(["a", "b", "c"], 0.88, MiscountingEncoder()) == []


def test_pairs_come_back_most_similar_first():
    texts = list(FakeEncoder.VECTORS)
    pairs = similar_pairs(texts, 0.5, FakeEncoder())
    assert pairs == sorted(pairs, key=lambda p: (-p[2], p[0], p[1]))


def test_a_pair_below_the_threshold_is_not_returned():
    texts = list(FakeEncoder.VECTORS)
    assert similar_pairs(texts, 0.999, FakeEncoder()) == []


# -------------------------------------------- the acceptance criteria


def test_tier_three_groups_paraphrases_that_share_no_five_grams():
    """[34 §P10] acceptance: *"Tier 3 groups paraphrase pairs sharing no 5-grams;
    tiers 1–2 do not."* Both halves, in one test."""
    from src.dedupe.minhash import shingles

    a = "which crm should i use\nrecommend something for a small team"
    b = "customer relationship software suggestions\nwhat do you all like"
    assert shingles(a) & shingles(b) == set(), "the fixture must share no 5-gram"

    without = build_groups(PARAPHRASES, DedupSettings(semantic_threshold=None))
    assert without.groups == (), "tiers 1-2 must not group a paraphrase"

    with_tier3 = build_groups(
        PARAPHRASES, DedupSettings(semantic_threshold=0.88), encoder=FakeEncoder()
    )
    assert len(with_tier3.groups) == 1
    assert with_tier3.groups[0].method == "semantic"
    assert set(with_tier3.groups[0].members) == {("lead", 1), ("lead", 2)}


def test_disabling_tier_three_produces_the_identical_lead_set():
    """[34 §P10] acceptance: *"with the semantic layer disabled the same run
    produces the identical lead set."*

    Compares **whole sets**, not counts. Tier 3 is additive by construction: it
    can merge items tiers 1 and 2 left ungrouped, it never splits a group, and it
    never removes an item from the run.
    """
    off = build_groups(PARAPHRASES, DedupSettings(semantic_threshold=None))
    on = build_groups(PARAPHRASES, DedupSettings(semantic_threshold=0.88), encoder=FakeEncoder())

    universe = {item.key for item in PARAPHRASES}
    for result in (off, on):
        # Every item is still present: grouped items plus ungrouped items is the
        # whole corpus, with nothing added and nothing lost.
        ungrouped = universe - result.grouped_keys
        assert result.grouped_keys | ungrouped == universe
        assert result.content_hashes.keys() == universe

    # And the exact/minhash groups are byte-identical with tier 3 on or off.
    assert [g for g in off.groups if g.method != "semantic"] == [
        g for g in on.groups if g.method != "semantic"
    ]


def test_tier_three_off_is_the_shipped_default():
    """``semantic_threshold: null``. A default that lies about what runs is worse
    than one that does not — and P0 measured the library absent everywhere."""
    assert DedupSettings().semantic_threshold is None
    assert build_groups(PARAPHRASES, DedupSettings()).groups == ()


def test_tier_three_configured_but_unavailable_is_a_clean_no_op():
    """Threshold set, no encoder — the state a host reaches by setting 0.88
    without installing ``model2vec``. It must produce the tier-1/2 answer, not
    an error."""
    configured = build_groups(PARAPHRASES, DedupSettings(semantic_threshold=0.88), encoder=None)
    baseline = build_groups(PARAPHRASES, DedupSettings(semantic_threshold=None))
    assert configured.groups == baseline.groups
