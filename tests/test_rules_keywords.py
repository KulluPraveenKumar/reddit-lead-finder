"""Keyword tiers and negative terms — and the normaliser's two failure directions.

The acceptance criterion says negative terms are *"case- and
punctuation-insensitive"*. Half of that is easy and half of it is a trap: a
normaliser that is too eager makes every multi-word term match text that merely
contains its letters in order.
"""

from __future__ import annotations

import pytest

from src.rules import NEGATIVE_TERM
from src.rules.keywords import check_negative_terms, match_tiers, normalise

# ------------------------------------------------------------------ normalise


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Foo-Bar", "foo bar"),
        ("foo bar", "foo bar"),
        ("FOO.BAR", "foo bar"),
        ("foo   bar", "foo bar"),
        ("  Foo/Bar!  ", "foo bar"),
        ("foo_bar", "foo_bar"),  # underscore is a word character, not punctuation
    ],
)
def test_normalise_folds_case_and_punctuation(raw: str, expected: str):
    """Mutations M8 (no casefold) and M9 (no punctuation handling)."""
    assert normalise(raw) == expected


@pytest.mark.parametrize(
    ("raw", "must_not_equal"),
    [
        ("no tion", "notion"),
        ("c a t", "cat"),
        ("s l a c k", "slack"),
    ],
)
def test_normalise_does_not_join_separate_words(raw: str, must_not_equal: str):
    """⚠️ Mutation M10 — the over-normalisation the criterion does not test for.

    Stripping whitespace instead of collapsing it is a one-character change that
    makes `notion` match `no tion`. The acceptance criterion only asks that
    `Foo-Bar` matches `foo bar`, so without this test the mutation survives.
    """
    assert normalise(raw) != must_not_equal
    assert " " in normalise(raw)


# ------------------------------------------------------------- negative terms


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("This is Foo-Bar territory", "foo bar"),
        ("this is foo bar territory", "FOO-BAR"),
        ("This is FOO.BAR territory", "foo bar"),
        ("plain spam here", "spam"),
    ],
)
def test_a_negative_term_matches_regardless_of_case_or_punctuation(text: str, term: str):
    result = check_negative_terms(text, [term])
    assert result.rejected
    assert result.reason == NEGATIVE_TERM


def test_the_matched_term_is_reported_not_just_the_reason():
    """An operator cannot tune a vocabulary they cannot see firing."""
    result = check_negative_terms("obvious spam post", ["crypto", "spam"])
    assert result.detail == "spam"


def test_a_term_whose_words_are_split_in_the_text_does_not_match():
    """The M10 guard, at the level that actually matters."""
    assert not check_negative_terms("no tion of what to do", ["notion"]).rejected


def test_empty_terms_are_skipped_not_matched():
    """An empty string is a substring of everything; a blank config line is not a filter."""
    assert not check_negative_terms("a perfectly fine post", ["", None or ""]).rejected


def test_no_negative_terms_admits_everything():
    assert not check_negative_terms("anything at all", []).rejected


# ---------------------------------------------------------------- keyword tiers


def test_match_tiers_reads_the_mapping_not_its_keys():
    """⚠️ The test that would have failed against `_triage_config`.

    `src/orchestration/handlers/discover.py` iterates `config["keywords"]` as if
    it were a list, so it yields the tier *names* — `('high_intent',
    'medium_intent')` — and P6's keyword matching has never matched a keyword.
    Measured 2026-08-13. This asserts the correct reading.
    """
    tiers = {
        "high_intent": ["looking for", "any recommendations"],
        "medium_intent": ["how do i", "struggling with"],
    }
    hits = match_tiers("Looking for a tool - any recommendations?", tiers)
    assert hits == {"high_intent": ["looking for", "any recommendations"]}

    # The defective reading would search for the literal tier names instead.
    assert not match_tiers("a post mentioning high_intent nowhere", tiers)


def test_tiers_are_whatever_the_mapping_contains():
    """06c §3.1 wants high/med/low; config.yaml ships two. Neither is hard-coded."""
    hits = match_tiers("this is a low signal post", {"low_intent": ["low signal"]})
    assert hits == {"low_intent": ["low signal"]}


def test_a_keyword_hit_is_not_a_rejection():
    """Tier matching returns what matched. Weighting it is P11's pre-score."""
    hits = match_tiers("looking for a tool", {"high_intent": ["looking for"]})
    assert isinstance(hits, dict)
    assert "looking for" in hits["high_intent"]


def test_keyword_matching_is_case_and_punctuation_insensitive():
    hits = match_tiers("LOOKING-FOR a tool", {"high_intent": ["looking for"]})
    assert hits == {"high_intent": ["looking for"]}


def test_a_tier_with_no_hits_is_absent_rather_than_empty():
    hits = match_tiers("nothing relevant", {"high_intent": ["looking for"]})
    assert hits == {}
