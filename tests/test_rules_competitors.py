"""Competitor detection against an injected registry.

The registry is a double throughout, because the real one is P15's and its data
lives in tables that arrive in `0007`. That is not a limitation of these tests —
it is the whole design: `competitor_mentions` takes its knowledge as an
argument, so it is testable years before the knowledge exists.
"""

from __future__ import annotations

import pytest

from src.rules import REASONS
from src.rules.competitors import (
    EMPTY_REGISTRY,
    DictionaryEntityRegistry,
    EntityRegistry,
    competitor_mentions,
    mentions_any,
    registry_from_mapping,
)

COMPETITORS = {
    "Notion": ["notion.so", "notion app"],
    "Airtable": ["air table", "airtable.com"],
    "Monday.com": ["monday", "monday dot com"],
}


@pytest.fixture
def registry() -> DictionaryEntityRegistry:
    return registry_from_mapping(COMPETITORS)


# ------------------------------------------------------------------ matching


def test_the_canonical_name_matches(registry):
    assert competitor_mentions("we moved off Notion last year", registry) == ["Notion"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("anyone else fed up with notion.so?", "Notion"),
        ("the notion app keeps losing my edits", "Notion"),
        ("air table is too expensive for us", "Airtable"),
        ("airtable.com pricing changed again", "Airtable"),
        ("monday is a mess to administer", "Monday.com"),
        ("we evaluated monday dot com", "Monday.com"),
    ],
)
def test_an_alias_only_post_resolves_to_the_canonical_name(text, expected, registry):
    """⚠️ Acceptance A3 — *"a post using only a competitor alias matches"*.

    Mutation M14 is a matcher that checks the canonical name and not the
    aliases; every case here contains the alias and **not** the canonical form.
    """
    assert expected not in text  # the canonical name really is absent
    assert competitor_mentions(text, registry) == [expected]


def test_matching_is_case_and_punctuation_insensitive(registry):
    assert competitor_mentions("NOTION.SO is down", registry) == ["Notion"]
    assert competitor_mentions("Air-Table again", registry) == ["Airtable"]


def test_several_competitors_are_all_reported(registry):
    found = competitor_mentions("we compared Notion and air table", registry)
    assert set(found) == {"Notion", "Airtable"}


def test_a_competitor_named_twice_is_reported_once(registry):
    assert competitor_mentions("Notion vs notion.so", registry) == ["Notion"]


# ------------------------------------------------------------- non-matching


@pytest.mark.parametrize(
    "text",
    [
        "this is purely notional at the moment",
        "the notionally correct answer",
        "airtables are not a thing",
        "mondays are the worst",
    ],
)
def test_a_longer_word_containing_the_name_does_not_match(text, registry):
    """Token boundaries, not substrings — `notional` is not `Notion`.

    This is the considered departure from negative-term matching, which *is* a
    substring check. A negative term is operator vocabulary where over-matching
    costs a lead nobody wanted; an entity name is a name.
    """
    assert competitor_mentions(text, registry) == []


def test_a_misspelling_the_operator_did_not_supply_does_not_match(registry):
    """The stated limitation, asserted so it cannot drift into a silent surprise.

    Fuzzy resolution is P15's tier 3. Until then a misspelling matches only if it
    was supplied as an alias.
    """
    assert competitor_mentions("we used Notiom for a while", registry) == []


def test_an_empty_or_missing_text_is_not_an_error(registry):
    assert competitor_mentions("", registry) == []
    assert competitor_mentions(None, registry) == []


# ------------------------------------------------- the absent-registry path


def test_no_registry_finds_nothing_and_does_not_raise():
    """The production state until P15: nothing configured, nothing found."""
    assert competitor_mentions("we moved off Notion last year") == []
    assert mentions_any("we moved off Notion last year") is False


def test_the_empty_registry_is_a_registry_not_a_none():
    """A caller needs no null check, and absent behaves like "no competitors yet"."""
    assert EMPTY_REGISTRY.resolve("Notion") == []
    assert isinstance(EMPTY_REGISTRY, EntityRegistry)


def test_an_empty_alias_is_skipped_not_matched_against_everything():
    """An empty needle is a substring of every text; a blank config line is not a rule."""
    reg = registry_from_mapping({"Notion": ["", "   "]})
    assert reg.resolve("a post about nothing in particular") == []
    assert reg.resolve("we use Notion") == ["Notion"]


# --------------------------------------------------------------- the protocol


def test_any_object_with_resolve_satisfies_the_protocol():
    """Structural typing is why P15 need not inherit from anything here."""

    class Fake:
        def resolve(self, text: str) -> list[str]:
            return ["Whatever"] if "x" in text else []

    assert isinstance(Fake(), EntityRegistry)
    assert competitor_mentions("x marks it", Fake()) == ["Whatever"]


def test_a_custom_registry_is_used_in_place_of_the_default():
    class Always:
        def resolve(self, text: str) -> list[str]:
            return ["Injected"]

    assert competitor_mentions("anything", Always()) == ["Injected"]


# ------------------------------------------------------- not a rejection


def test_a_competitor_mention_is_a_signal_not_a_rejection():
    """⚠️ 06c §3.1 makes this a pre-score *component*, and the pre-score is P11's.

    A post naming a competitor is usually a *better* lead. Nothing in this module
    returns a RuleResult, and no reason is added to the closed vocabulary.
    """
    found = competitor_mentions("we moved off Notion", registry_from_mapping(COMPETITORS))
    assert isinstance(found, list)
    assert "competitor" not in REASONS
    assert not any("competitor" in reason for reason in REASONS)


def test_mentions_any_is_the_boolean_the_prescore_component_wants(registry):
    assert mentions_any("we moved off Notion", registry) is True
    assert mentions_any("nothing relevant here", registry) is False
