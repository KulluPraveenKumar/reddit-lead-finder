"""Comments — stored once per distinct body, whatever a re-scrape does.

[34 §P11](../../../docs/34-implementation-plan.md) task 5: *"``body_hash`` dedup
with ``begin_nested()`` + ``IntegrityError`` skip"*, and the acceptance line
*"re-running comment extraction creates **zero** duplicates"*.

**Why the hash and not an id.** ``src/db/models.py::Comment`` states it: the
parser extracts no comment id, and old Reddit exposes ``t1_`` ids inconsistently
across thread depths, so ``body_hash`` is the real key and ``ux_comments_hash``
makes it ``UNIQUE``.

**Why a savepoint and not a pre-check.** ``SELECT`` then ``INSERT`` is a race
with a second writer and, worse, a lie under SQLAlchemy's unit of work: the
duplicate is not detected at ``session.add()`` but at the **flush**, by which
point the whole transaction is poisoned and every *other* comment in the batch is
lost with it. ``begin_nested()`` issues a ``SAVEPOINT``, so a collision rolls
back exactly one row and the batch continues. That is the difference between
"re-running creates zero duplicates" and "re-running creates zero comments".
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import Comment

log = logging.getLogger(__name__)

#: How many ids one ``IN`` clause carries. SQLite's default parameter ceiling is
#: 999; ``src/db/repositories/discovery.py`` uses the same figure for the same
#: reason, and the two are kept equal deliberately.
_MAX_IN_CLAUSE = 900


def body_hash(lead_id: int, author: str | None, body: str) -> str:
    """``sha256(lead_id|author|body)`` — the spelling ``models.py`` documents.

    **Scoped to the lead on purpose.** The same boilerplate reply — *"Have you
    tried Notion?"* — appears under many posts, and it is a distinct comment each
    time because it is evidence about a *different* discussion. A global content
    hash would store the first one and silently discard the rest, which would
    make comment coverage look complete while being arbitrarily incomplete.

    The author is included for the same reason at one level down: two people
    posting *"same here"* under one thread are two people agreeing, not a
    duplicate. ``None`` folds to ``[deleted]``, which is the literal string both
    collection paths already produce and what the column defaults to — so a
    removed account hashes consistently rather than by whether the parser
    happened to return ``None`` or the string.

    ⚠ **The author is length-prefixed, and a bare separator is not enough.** The
    first version of this function joined the three fields with ``\\x00`` on the
    stated grounds that the character *"cannot occur in any of the three
    fields"*. It can: a Python ``str`` holds ``\\x00`` perfectly well, and a body
    containing one made the encoding ambiguous —
    ``body_hash(1, "a\\x00b", "c")`` and ``body_hash(1, "a", "b\\x00c")`` both
    encoded to ``1\\x00a\\x00b\\x00c`` and collided. Measured, not reasoned
    about: ``test_the_encoding_is_unambiguous_even_when_a_field_contains_a_null``
    is the test that caught the claim being false.

    The consequence was small but real and in the worst direction — a **silently
    dropped comment**, because a collision looks exactly like the duplicate the
    unique index is there to refuse. Prefixing the author's length makes the
    split unambiguous whatever any field contains.
    """
    author = (author or "[deleted]").strip() or "[deleted]"
    payload = f"{lead_id}\x00{len(author)}\x00{author}\x00{body}".encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CommentWrite:
    """The outcome of one batch. Counted rather than inferred from the row count.

    ``skipped`` is the number the unique index refused — the quantity the
    acceptance criterion is about. A caller that only knew ``stored`` could not
    tell "nothing new" from "nothing worked".
    """

    stored: int = 0
    skipped: int = 0


class CommentRepository:
    """Reads and writes for ``comments``. The only writer P11 ships."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_many(self, lead_id: int, comments: Iterable[dict]) -> CommentWrite:
        """Store a lead's comments, skipping any body already stored for it.

        Each row goes in its own ``SAVEPOINT``. The cost is one savepoint per
        comment; the alternative is one lost batch per collision, and a re-scrape
        collides on **every** row by construction.

        A comment with an empty body is skipped without touching the database:
        ``_parse_comments`` already drops those, so reaching here means the shape
        changed, and hashing ``""`` would make one empty-body row per lead look
        like a real comment forever.
        """
        stored = skipped = 0
        for raw in comments:
            body = (raw.get("body") or "").strip()
            if not body:
                skipped += 1
                continue

            author = raw.get("author")
            digest = body_hash(lead_id, author, body)

            try:
                with self.session.begin_nested():
                    self.session.add(
                        Comment(
                            lead_id=lead_id,
                            reddit_id=raw.get("reddit_id"),
                            author=(author or "[deleted]"),
                            body=body,
                            score=raw.get("score"),
                            depth=int(raw.get("depth") or 0),
                            created_utc=raw.get("created_utc"),
                            body_hash=digest,
                        )
                    )
            except IntegrityError:
                # The unique index did its job. Expected on every re-scrape, so
                # this is debug and not a warning: logging it at warning would
                # make a correct idempotent re-run look like a fault.
                log.debug("comment already stored for lead %s (%s)", lead_id, digest[:12])
                skipped += 1
            else:
                stored += 1

        return CommentWrite(stored=stored, skipped=skipped)

    def count_for_lead(self, lead_id: int) -> int:
        return self.session.query(Comment.id).filter(Comment.lead_id == lead_id).count()

    def counts_for_leads(self, lead_ids: Sequence[int]) -> dict[int, int]:
        """How many comments each lead already has — one ``GROUP BY``, not N queries.

        Used by the comment scraper to skip leads it has already covered, so a
        re-run spends its request budget on leads with none rather than
        re-fetching pages it will then discard row by row. **This is where the
        request saving actually comes from**; the savepoint skip above is the
        correctness half, and this is the cost half.
        """
        from sqlalchemy import func

        counts: dict[int, int] = {}
        unique = [i for i in dict.fromkeys(lead_ids) if i]
        for start in range(0, len(unique), _MAX_IN_CLAUSE):
            chunk = unique[start : start + _MAX_IN_CLAUSE]
            rows = (
                self.session.query(Comment.lead_id, func.count(Comment.id))
                .filter(Comment.lead_id.in_(chunk))
                .group_by(Comment.lead_id)
                .all()
            )
            counts.update(dict(rows))
        return counts


__all__ = ["CommentRepository", "CommentWrite", "body_hash"]
