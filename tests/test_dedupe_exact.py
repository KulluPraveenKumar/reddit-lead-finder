"""Tier 1 — the content hash, and the normalisation it rests on.

Every test here is about **what counts as the same post**, which is the only
question this tier answers. Getting it too loose merges two conversations into
one and enriches one of them never; too tight and the crosspost the tier exists
for costs a second AI call.
"""

from __future__ import annotations

import pytest

from src.dedupe import DedupItem
from src.dedupe.exact import (
    content_hash,
    group_exact,
    hash_item,
    normalise,
    strip_trailing_edits,
)

# ------------------------------------------------------------- normalise


@pytest.mark.parametrize(
    "a, b",
    [
        ("Which CRM?", "which crm?"),
        ("**Which CRM?**", "Which CRM?"),
        ("_Which_ CRM?", "Which CRM?"),
        ("~~Which~~ CRM?", "Which CRM?"),
        ("`Which CRM?`", "Which CRM?"),
        ("Which   CRM?", "Which CRM?"),
        ("  Which CRM?  ", "Which CRM?"),
        ("Which\nCRM?", "Which CRM?"),
        ("Which\tCRM?", "Which CRM?"),
    ],
)
def test_cosmetic_differences_normalise_away(a: str, b: str):
    assert normalise(a) == normalise(b)


@pytest.mark.parametrize(
    "a, b",
    [
        # Punctuation is KEPT here, unlike rules.keywords.normalise. A question
        # and a statement are different posts.
        ("Which CRM?", "Which CRM"),
        ("no tion", "notion"),
        ("CRM for sales", "CRM for support"),
    ],
)
def test_substantive_differences_survive_normalisation(a: str, b: str):
    assert normalise(a) != normalise(b)


def test_emphasis_is_deleted_not_spaced():
    """The mirror of P9's mutation M10, and the mistake that would break tier 1.

    ⚠️ **The wrapping cases do not distinguish the two.** ``"**CRM**"`` spaced
    gives ``"  crm  "``, which whitespace collapse and ``strip`` reduce back to
    ``"crm"`` — identical to deleting. Mutation **M1** survived on precisely that,
    which is P9's **T5**: the test was checking a case where both readings agree.

    The distinguishing cases are **intra-word**, and they are the ones a real post
    produces: ``C**R**M`` and ``snake_case``.
    """
    assert normalise("**CRM**") == "crm"
    assert normalise("C**R**M") == "crm", "spaced emphasis would give 'c r m'"
    assert normalise("snake_case") == "snakecase", "spaced would give 'snake case'"
    assert normalise("the **best** CRM") == "the best crm"


def test_whitespace_is_collapsed_not_deleted():
    """P9's M10 itself. Deleting whitespace would merge separate words."""
    assert normalise("no tion") == "no tion"


def test_normalise_never_raises_on_empty_or_none():
    assert normalise("") == ""
    assert normalise(None) == ""  # type: ignore[arg-type]


# ------------------------------------------------------- edit markers


@pytest.mark.parametrize(
    "body",
    [
        "The real content\nEDIT: never mind",
        "The real content\nedit: never mind",
        "The real content\nEdit 2: never mind",
        "The real content\nUPDATE — never mind",
        "The real content\n  Edit - never mind",
    ],
)
def test_a_trailing_edit_block_is_stripped(body: str):
    assert strip_trailing_edits(body).strip() == "The real content"


def test_the_first_edit_marker_wins_not_the_last():
    """An author who edits twice must still hash as the pre-edit post."""
    body = "The real content\nEDIT: one\nmore words\nEDIT 2: two"
    assert strip_trailing_edits(body).strip() == "The real content"


def test_a_post_that_is_only_an_edit_normalises_to_nothing():
    """Boundary. The caller still hashes the title, so this is not an error."""
    assert normalise("EDIT: never mind") == ""
    assert content_hash("A real title", "EDIT: never mind") == content_hash("A real title", "")


def test_the_word_edit_mid_sentence_is_not_a_marker():
    """The near-miss fixture. ``_EDIT_MARKER`` anchors at the start of a line.

    P9's structural rules ship one of these per pattern for a reason recorded in
    ``src/rules/structural.py``: a rule that is a little too wide discards real
    content, and nothing in this system reports what it discarded.
    """
    body = "I need to edit the invoice template every month and it is killing me"
    assert strip_trailing_edits(body) == body


# ------------------------------------------------------------ content_hash


def test_the_hash_is_sha256_shaped():
    digest = content_hash("title", "body")
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_the_hash_is_stable_across_calls():
    assert content_hash("Which CRM?", "Small team") == content_hash("Which CRM?", "Small team")


def test_a_title_body_boundary_shift_is_not_a_duplicate():
    """Operator decision **D6**, and the collision it closes.

    [06c §4.1] writes ``sha256(normalise(title + "\\n" + body))``. :func:`normalise`
    collapses the joining newline into a space, so under that literal
    parenthesisation ``("a b", "c")`` and ``("a", "b c")`` hash **identically** —
    two different posts merged into one group, one of them never enriched.
    Normalising the parts first keeps the boundary.
    """
    assert content_hash("a b", "c") != content_hash("a", "b c")


def test_a_crosspost_with_markdown_and_an_edit_is_the_same_post():
    """The three things this tier was specified to catch, in one item."""
    original = content_hash("Which CRM should I use?", "Small team of five.")
    repost = content_hash(
        "**Which CRM should I use?**",
        "Small   team of five.\n\nEDIT: thanks all!",
    )
    assert original == repost


def test_a_different_post_is_a_different_hash():
    assert content_hash("Which CRM?", "Small team") != content_hash("Which CRM?", "Large team")


# ------------------------------------------------------------- group_exact


def _item(row_id: int, title: str, body: str = "") -> DedupItem:
    return DedupItem(key=("lead", row_id), title=title, body=body)


def test_group_exact_buckets_by_hash_and_keeps_insertion_order():
    items = [
        _item(1, "Which CRM?", "Small team"),
        _item(2, "Best pizza?", "Deep dish"),
        _item(3, "**Which CRM?**", "Small team"),
    ]
    buckets = group_exact(items)
    crm = buckets[hash_item(items[0])]
    assert crm == [("lead", 1), ("lead", 3)]


def test_group_exact_returns_singletons_too():
    """P19's incremental enrichment keys on the hash of an *ungrouped* item too.

    Filtering to ``len > 1`` here would throw that away and force a second pass
    over the corpus.
    """
    buckets = group_exact([_item(1, "unique")])
    assert len(buckets) == 1
    assert next(iter(buckets.values())) == [("lead", 1)]


def test_group_exact_on_an_empty_corpus():
    assert group_exact([]) == {}
