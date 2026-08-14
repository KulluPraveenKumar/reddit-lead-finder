"""Author heuristics — and the surnames a careless suffix rule discards.

`*Bot` looks like the simplest rule in the package. It is the one with a real
false-positive class: `Abbot`, `Talbot` and `Cabot` are people, and a
case-insensitive suffix match throws their posts away with nothing to show it
happened.
"""

from __future__ import annotations

import pytest

from src.rules import BOT_OR_DELETED
from src.rules.authors import BOT_AUTHORS, check_author

# ------------------------------------------------------------------ rejections


@pytest.mark.parametrize("author", ["[deleted]", "[removed]", "[DELETED]"])
def test_a_gone_account_is_rejected(author: str):
    result = check_author(author)
    assert result.rejected
    assert result.reason == BOT_OR_DELETED
    assert result.detail == "deleted"


@pytest.mark.parametrize("author", ["AutoModerator", "automoderator", "AutoTLDR", "WikiTextBot"])
def test_a_known_bot_is_rejected(author: str):
    assert check_author(author).rejected


def test_the_known_bot_set_is_matched_exactly_not_as_a_substring():
    """`automoderator` is a name. `NotAutoModeratorFan` is a person."""
    assert check_author("NotAutoModeratorFan").rejected is False


@pytest.mark.parametrize("author", ["MyBot", "SomeHelperBot", "deploy_bot", "news-bot", "x.bot"])
def test_the_bot_suffix_is_rejected(author: str):
    result = check_author(author)
    assert result.rejected
    assert result.detail in {"bot_suffix", "known_bot"}


# -------------------------------------------------------------- false positives


@pytest.mark.parametrize("author", ["Botany_Nerd", "robotics_guy", "botanist", "Robotics_Weekly"])
def test_a_name_containing_bot_is_not_a_bot(author: str):
    """⚠️ Mutation M13 — an unanchored `"bot" in author`.

    All four contain the letters `bot` and none of them is a bot.
    """
    assert not check_author(author).rejected, f"{author!r} is a person"


@pytest.mark.parametrize("author", ["Abbot", "Talbot", "Cabot", "abbot"])
def test_a_surname_ending_in_bot_is_not_a_bot(author: str):
    """⚠️ The reason the suffix rule is case-sensitive on the capital `B`.

    These end in the letters `b-o-t`. A case-insensitive suffix rule discards
    them, and the 2% holdout that would surface it is P11's — so until then the
    loss is invisible. The deliberate cost of getting this right is that a bot
    named `somebot`, lower case with no separator, is missed. A missed bot costs
    one wasted analysis; a discarded human costs a lead nobody can see was lost.
    """
    assert not check_author(author).rejected, f"{author!r} is a surname, not a bot"


def test_the_documented_miss_is_a_miss_and_is_asserted():
    """State the trade explicitly, so changing it is a decision and not a drift."""
    assert not check_author("somebot").rejected


# --------------------------------------------------------------------- flags


def test_skip_bot_authors_false_admits_a_bot():
    """Mutation M12 — a rule that ignores its own off switch."""
    assert not check_author("WikiTextBot", skip_bot_authors=False).rejected
    assert not check_author("MyBot", skip_bot_authors=False).rejected


def test_skip_deleted_authors_false_admits_a_deleted_account():
    assert not check_author("[deleted]", skip_deleted_authors=False).rejected


def test_the_two_flags_are_independent():
    assert check_author("[deleted]", skip_bot_authors=False).rejected
    assert check_author("MyBot", skip_deleted_authors=False).rejected


# ----------------------------------------------------------------- allowlist


def test_the_allowlist_wins_over_every_rule():
    assert not check_author("WikiTextBot", allowlist={"wikitextbot"}).rejected
    assert not check_author("[deleted]", allowlist={"[deleted]"}).rejected


def test_the_allowlist_is_case_insensitive():
    assert not check_author("MyBot", allowlist={"MYBOT"}).rejected


# ------------------------------------------------------------------- absence


@pytest.mark.parametrize("author", [None, "", "   "])
def test_a_missing_author_is_admitted_not_rejected(author):
    """`None` means the collection path reported nothing — not that the account is gone.

    The same zero-versus-unknown distinction DI13 records for `num_comments`. It
    is not this module's place to collapse it.
    """
    assert not check_author(author).rejected


def test_the_known_bot_set_is_lowercase_so_the_casefold_comparison_works():
    """A capital in the set would make that entry unreachable — silently."""
    assert all(name == name.casefold() for name in BOT_AUTHORS)
