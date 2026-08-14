"""Tier 1 — exact duplicates. One hash, one dictionary, no similarity.

[06c §4.1](../../docs/06c-local-first-pipeline.md): *"``content_hash =
sha256(normalise(title + "\\n" + body))``, where ``normalise`` collapses
whitespace, casefolds, and strips markdown emphasis and trailing edit markers.
Catches crossposts, reposts, and quoted duplicates. One indexed lookup."*

This tier is the cheap one and it runs first, because everything it catches is
something tier 2 would otherwise pay MinHash prices to catch.

⚠️ **:func:`normalise` here is NOT ``src.rules.keywords.normalise``, and merging
them would be a defect.** They have opposite requirements and a reader who sees
two functions with one name will want to fix that:

======================  =========================  ============================
                        ``rules.keywords``         ``dedupe.exact``
======================  =========================  ============================
Punctuation             becomes a **space**        **kept**
Emphasis markers        become a space             **deleted**
Trailing edit blocks    kept                       **stripped**
Why                     ``"no tion"`` must not     ``"**CRM**"`` and ``"CRM"``
                        become ``"notion"``        are the same post
======================  =========================  ============================

P9's mutation M10 is exactly the change that makes its ``normalise`` delete
whitespace instead of collapsing it. The equivalent mistake here is the reverse —
turning ``*`` into a space, so ``"**CRM**"`` normalises to ``" CRM "`` and stops
matching the plain repost it exists to catch.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from . import DedupItem, ItemKey

#: Markdown emphasis, **deleted rather than spaced**: ``**CRM**`` and ``CRM`` are
#: the same words, so the markers must vanish without leaving a gap. Backtick is
#: included because a quoted duplicate is frequently the original wrapped in a
#: code fence.
#:
#: The cost, stated rather than discovered later: ``snake_case`` becomes
#: ``snakecase``. That is acceptable here — both spellings hash deterministically
#: and a post is not made distinct by an underscore — and it is exactly the
#: behaviour that would be wrong in ``rules.keywords``.
_EMPHASIS = re.compile(r"[*_~`]")

#: One or more whitespace characters. Collapsed to a single space, never deleted.
_WHITESPACE = re.compile(r"\s+")

#: A line that opens an edit block: ``EDIT:``, ``Edit 2 -``, ``UPDATE —``.
#:
#: Matched **per line** rather than with one multi-line pattern over the whole
#: body. That is not a style choice: [PHASE-09-HANDOVER §4
#: T6](../../docs/PHASE-09-HANDOVER.md) records a P9 regex whose two ``\\s*``
#: quantifiers around an optional group went quadratic and burned **67.8 seconds**
#: of CPU on a 100,000-space title, and ``re`` has no timeout — a catastrophic
#: backtrack does not raise, it wedges the worker. Post bodies are
#: attacker-supplied. A per-line anchored match cannot backtrack across lines,
#: and the scan below is a single linear pass.
_EDIT_MARKER = re.compile(r"^\s*(?:edit|update)\b\s*\d*\s*[:\-–—]?", re.IGNORECASE)


def strip_trailing_edits(text: str) -> str:
    """Drop everything from the first edit-marker line onward.

    *"I solved it, EDIT: never mind"* and the same post before the edit are the
    same discussion, and grouping them is the point. Cutting at the **first**
    marker rather than the last is deliberate: an author who edits twice produces
    two blocks, and keeping the first one would make the two versions hash
    differently — which is the collision this function exists to create.

    A body that is *only* an edit block normalises to the empty string. That is
    handled by the caller, not here: :func:`content_hash` still hashes the title.
    """
    lines = (text or "").split("\n")
    for i, line in enumerate(lines):
        if _EDIT_MARKER.match(line):
            return "\n".join(lines[:i])
    return text or ""


def normalise(text: str) -> str:
    """Casefold, strip edit blocks, delete emphasis, collapse whitespace.

    Order matters and is not arbitrary. Edits are stripped **first**, while the
    line structure still exists to find them by; whitespace is collapsed **last**,
    once emphasis deletion has finished creating the runs it needs to collapse
    (``"** CRM **"`` -> ``" CRM "`` -> ``"CRM"``).

    Linear in the length of the input. Never raises: ``None`` and ``""`` are the
    empty string, not an error.
    """
    without_edits = strip_trailing_edits(text or "")
    without_emphasis = _EMPHASIS.sub("", without_edits.casefold())
    return _WHITESPACE.sub(" ", without_emphasis).strip()


def content_hash(title: str, body: str) -> str:
    """``sha256`` of the normalised title and body. 64 hex characters.

    ⚠️ **The title and body are normalised separately and then joined**, where
    [06c §4.1](../../docs/06c-local-first-pipeline.md) writes
    ``normalise(title + "\\n" + body)``. Operator decision **D6**, and the
    difference is not cosmetic: :func:`normalise` collapses the joining newline
    into a space, so under the literal parenthesisation
    ``("a b", "c")`` and ``("a", "b c")`` produce the **same hash** — two
    different posts, silently merged into one group, with one of them never
    enriched. Normalising the parts first keeps the boundary, and the separator
    is a character :func:`normalise` can no longer emit.

    This is [lock §8](../../docs/EXECUTION_MODE_LOCK.md)'s continuous-improvement
    rule, not a redesign: same algorithm, same column, same tier, one
    parenthesis moved to close a collision.
    ``test_a_title_body_boundary_shift_is_not_a_duplicate`` is the test.
    """
    payload = f"{normalise(title)}\n{normalise(body)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_item(item: DedupItem) -> str:
    """:func:`content_hash` over a :class:`~src.dedupe.DedupItem`."""
    return content_hash(item.title, item.body)


def group_exact(items: Iterable[DedupItem]) -> dict[str, list[ItemKey]]:
    """Bucket items by content hash. Insertion-ordered, so grouping is stable.

    Returns **every** bucket, including the singletons, because the caller needs
    the hash of an ungrouped item as much as it needs the groups — that hash is
    what [06c §5](../../docs/06c-local-first-pipeline.md)'s incremental
    enrichment keys on. Filtering to ``len > 1`` here would throw it away and
    force a second pass.
    """
    buckets: dict[str, list[ItemKey]] = {}
    for item in items:
        buckets.setdefault(hash_item(item), []).append(item.key)
    return buckets
