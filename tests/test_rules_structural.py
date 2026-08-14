"""Structural noise, and the near-misses that matter more than the matches.

A regex fence tested only on its matches is untested. The risk in
`src/rules/structural.py` is not that it misses a megathread — it is that it
discards a real lead that happens to use a common word, which nothing in this
system reports. So every pattern here carries a near-miss: a post containing the
pattern's own vocabulary that must be **admitted**.
"""

from __future__ import annotations

import pytest

from src.rules import STRUCTURAL_NOISE
from src.rules.structural import (
    DETAILS,
    STRUCTURAL_PATTERNS,
    check_length,
    check_structural,
    is_too_short,
)

# ---------------------------------------------------------------- the matches


@pytest.mark.parametrize(
    ("title", "detail"),
    [
        ("[HIRING] Senior Python developer, remote", "hiring"),
        ("[hiring] backend engineer", "hiring"),
        ("[For Hire] Full-stack dev available", "hiring"),
        ("We're hiring a designer", "hiring"),
        ("We’re hiring a designer", "hiring"),  # typographic apostrophe
        ("Now hiring: SRE", "hiring"),
        ("Job opening at our startup", "hiring"),
        ("Huge giveaway - 5 licenses to win", "giveaway"),
        ("Free copy of my ebook for the first 20", "giveaway"),
        ("Free license keys inside", "giveaway"),
        ("Raffle for a lifetime plan", "giveaway"),
        ("Weekly megathread - ask your questions here", "megathread"),
        ("Weekly discussion thread", "megathread"),
        ("Monthly thread for self-promotion", "megathread"),
        ("Daily discussion", "megathread"),
        ("AMA: I built a SaaS to $10k MRR", "ama"),
        ("[AMA] founder of a dev tools company", "ama"),
        ("Ask me anything about bootstrapping", "ama"),
        ("Use code SAVE20 at checkout", "promo"),
        ("Promo code inside for my new tool", "promo"),
        ("Discount code for the first 100 signups", "promo"),
        ("Affiliate link in the comments", "promo"),
        ("Upvote if you agree", "promo"),
    ],
)
def test_structural_noise_is_rejected_with_its_pattern_named(title: str, detail: str):
    result = check_structural(title)
    assert result.rejected, f"{title!r} should be structural noise"
    assert result.reason == STRUCTURAL_NOISE
    assert result.detail == detail


def test_matching_is_case_insensitive():
    """Mutation M5 — dropping `re.IGNORECASE`."""
    for title in ("WEEKLY MEGATHREAD", "weekly megathread", "Weekly MegaThread"):
        assert check_structural(title).detail == "megathread"


# ------------------------------------------------------------ the near-misses


@pytest.mark.parametrize(
    "title",
    [
        # ⚠️ The one that matters most. This is a textbook lead for this product,
        # and `src/discovery/triage.py`'s bare `\bhiring\b` rejects it.
        "Our hiring process is broken and I need a tool to fix it",
        "How do you handle hiring at 10 people?",
        "Hiring managers keep ghosting me - is there software for this?",
    ],
)
def test_a_post_about_hiring_is_not_a_hiring_ad(title: str):
    """Mutation M6 — widening `we're hiring` to a bare `hiring`.

    The distinction is between a post *advertising* a job and a post *describing
    a problem with hiring*. The second is exactly what this product exists to
    find, and the word alone cannot tell them apart.
    """
    assert not check_structural(title).rejected, f"{title!r} is a lead, not a hiring ad"


@pytest.mark.parametrize(
    "title",
    [
        "Is there a free alternative to Zendesk?",
        "Looking for a free tier that actually works",
        "Free trials keep auto-renewing on me",
    ],
)
def test_a_post_about_free_things_is_not_a_giveaway(title: str):
    assert not check_structural(title).rejected


@pytest.mark.parametrize(
    "title",
    [
        "Monthly recurring billing is broken in my app",
        "Our weekly standup notes are a mess - any tools?",
        "Daily active users dropped 30% after the redesign",
    ],
)
def test_a_post_mentioning_a_cadence_is_not_a_megathread(title: str):
    """`monthly`/`weekly`/`daily` alone must not fire — only the thread forms."""
    assert not check_structural(title).rejected


@pytest.mark.parametrize(
    "title",
    [
        "Amazon FBA tools - what do you use?",
        "Amateur mistake: I shipped without analytics",
        "Amazing how hard invoicing is",
    ],
)
def test_a_title_starting_with_ama_letters_is_not_an_ama(title: str):
    """`\\bama\\b`, not `ama`. Without the word boundary, `Amazon` is an AMA."""
    assert not check_structural(title).rejected


@pytest.mark.parametrize(
    "title",
    [
        "Looking for a discount on team seats",
        "How do you code review at scale?",
        "Upvoted this yesterday and still no answer",
    ],
)
def test_a_post_mentioning_discounts_or_code_is_not_promo(title: str):
    assert not check_structural(title).rejected


def test_a_hiring_tag_must_be_at_the_start_or_be_an_explicit_phrase():
    """Mutation M7 — keeping only `^\\[hiring\\]` and dropping the phrases.

    The tag form and the phrase form are separate alternatives; dropping either
    loses a real class of hiring ad.
    """
    assert check_structural("[HIRING] dev").detail == "hiring"
    assert check_structural("Great news - we're hiring!").detail == "hiring"


def test_dropping_any_pattern_would_be_caught():
    """Mutation M4 — the parametrised matches above cover all five names."""
    expected = {"hiring", "giveaway", "megathread", "ama", "promo"}
    assert expected == DETAILS
    assert len(STRUCTURAL_PATTERNS) == 5


# --------------------------------------------------------------- the length floor


@pytest.mark.parametrize(
    ("text", "min_chars", "expected"),
    [
        ("", 80, True),
        (None, 80, True),
        ("x" * 79, 80, True),
        ("x" * 80, 80, False),  # mutation M11 — the `<` / `<=` boundary
        ("x" * 81, 80, False),
        ("anything", 0, False),
    ],
)
def test_is_too_short_boundary(text, min_chars, expected):
    assert is_too_short(text, min_chars) is expected


def test_check_length_reports_both_numbers():
    result = check_length("short", 80)
    assert result.rejected
    assert result.detail == "5 < 80"


def test_a_missing_title_is_admitted_by_the_structural_check():
    """A malformed post is a rejection with a reason elsewhere, never an exception here."""
    assert not check_structural("").rejected
    assert not check_structural(None).rejected
