"""Lead queries, kept in one place so the scrapers and the dashboard agree.

Before this module every scraper deduplicated with one ``SELECT`` per post
inside the loop -- 100 posts meant 100 round trips, and the cost was paid on
every page of every subreddit. :meth:`LeadRepository.filter_new` does it with a
single ``IN`` query per page instead.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import desc, func

from src.db.models import Lead

# SQLite compiles a bound parameter per element of an IN list and historically
# capped a statement at 999 of them (SQLITE_MAX_VARIABLE_NUMBER). Newer builds
# raise the cap to 32766, but the ceiling is a compile-time option of whichever
# libsqlite3 the host happens to ship, so it is not safe to detect and rely on.
# 500 is below every published default and still turns a 100-post page into one
# query, which is the whole point.
_IN_CHUNK = 500

# Sorting is driven by a query parameter. ``getattr(Lead, name)`` would happily
# return ``Lead.metadata`` (a MetaData object) or ``Lead.__init__``, and
# ``desc()`` on either raises -- a 500 from a crafted URL. An allowlist of real
# columns is the fix; anything unrecognised falls back to intent_score.
_SORTABLE = {
    "intent_score",
    "score",
    "num_comments",
    "created_utc",
    "scraped_at",
    "subreddit",
    "author",
    "status",
}

DEFAULT_SORT = "intent_score"


class LeadRepository:
    """Read/write access to the ``leads`` table.

    Holds a session but never commits: transaction boundaries belong to the
    caller, which is the only way a scraper can batch a whole page into one
    commit.
    """

    def __init__(self, session):
        self.session = session

    # ------------------------------------------------------------------ reads

    def existing_ids(self, reddit_ids: Iterable[str]) -> set[str]:
        """Return the subset of ``reddit_ids`` already stored.

        One query per chunk of 500, not one per id.
        """
        unique = {rid for rid in reddit_ids if rid}
        if not unique:
            return set()

        ordered = list(unique)
        found: set[str] = set()
        for start in range(0, len(ordered), _IN_CHUNK):
            chunk = ordered[start : start + _IN_CHUNK]
            rows = self.session.query(Lead.reddit_id).filter(Lead.reddit_id.in_(chunk)).all()
            found.update(row[0] for row in rows)
        return found

    def filter_new(self, posts: Sequence[dict]) -> list[dict]:
        """Return the posts that are neither stored nor duplicated in the batch.

        Order is preserved. Two filters, not one:

        * already in the database -- the obvious case;
        * repeated *within* ``posts`` -- pagination can serve the same post on
          two pages when new posts shift the window between requests. Both
          copies used to pass the old per-post check, because neither was in
          the database yet, and the ``reddit_id`` unique index then failed the
          commit for the entire page.
        """
        known = self.existing_ids(p.get("id") for p in posts)

        fresh: list[dict] = []
        seen_in_batch: set[str] = set()
        for post in posts:
            rid = post.get("id")
            if not rid or rid in known or rid in seen_in_batch:
                continue
            seen_in_batch.add(rid)
            fresh.append(post)
        return fresh

    def search(
        self,
        *,
        subreddit: str = "",
        status: str = "",
        min_score: float = 0.0,
        text: str = "",
        sort_by: str = DEFAULT_SORT,
        page: int = 1,
        per_page: int = 25,
    ) -> tuple[list[Lead], int]:
        """Filtered, sorted, paginated leads plus the unpaginated total."""
        query = self.session.query(Lead)

        if subreddit:
            query = query.filter(Lead.subreddit == subreddit)
        if status:
            query = query.filter(Lead.status == status)
        if min_score > 0:
            query = query.filter(Lead.intent_score >= min_score)
        if text:
            # ESCAPE so a literal % or _ in the search box matches itself
            # instead of acting as a wildcard.
            pattern = f"%{_escape_like(text)}%"
            query = query.filter(
                Lead.title.ilike(pattern, escape="\\") | Lead.body.ilike(pattern, escape="\\")
            )

        total = query.count()

        column = getattr(Lead, sort_by if sort_by in _SORTABLE else DEFAULT_SORT)
        page = max(1, page)
        per_page = max(1, min(per_page, 500))
        rows = (
            query.order_by(desc(column), desc(Lead.id))
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return rows, total

    def status_counts(self) -> dict[str, int]:
        """All status tallies in one grouped query rather than one COUNT each."""
        rows = self.session.query(Lead.status, func.count(Lead.id)).group_by(Lead.status).all()
        counts = {status or "new": count for status, count in rows}
        counts["total"] = sum(counts.values())
        return counts

    def keyword_breakdown(self, limit: int = 20) -> list[dict]:
        """Lead counts per matched keyword, most frequent first.

        ``matched_keywords`` is a comma-joined string with ``[HIGH]``/``[MED]``
        prefixes, so the split happens in Python. It reads one column of the
        table, not the whole rows, and there is no per-keyword query.
        """
        rows = self.session.query(Lead.matched_keywords).filter(
            Lead.matched_keywords != "", Lead.matched_keywords.isnot(None)
        )

        tally: dict[tuple[str, str], int] = {}
        for (blob,) in rows:
            for token in {t.strip() for t in blob.split(",") if t.strip()}:
                level = "high" if token.startswith("[HIGH]") else "medium"
                keyword = token.removeprefix("[HIGH]").removeprefix("[MED]").strip()
                if keyword:
                    tally[(keyword, level)] = tally.get((keyword, level), 0) + 1

        ordered = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0][0]))
        return [
            {"keyword": keyword, "intent_level": level, "leads": count}
            for (keyword, level), count in ordered[:limit]
        ]

    def subreddit_breakdown(self, limit: int = 20) -> list[dict]:
        """Lead count and mean intent score per subreddit, in one query."""
        rows = (
            self.session.query(
                Lead.subreddit,
                func.count(Lead.id).label("leads"),
                func.avg(Lead.intent_score).label("avg_score"),
            )
            .group_by(Lead.subreddit)
            .order_by(desc(func.count(Lead.id)))
            .limit(limit)
            .all()
        )
        return [
            {
                "subreddit": name,
                "leads": leads,
                "avg_score": round(avg or 0.0, 2),
            }
            for name, leads, avg in rows
        ]


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
