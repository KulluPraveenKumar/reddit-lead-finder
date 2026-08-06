"""Configuration and About pages.

These exist to move things *off* the dashboard, not to add features:

* **Configuration** hosts the scraper settings that were crowding the dashboard
  sidebar — subreddits, keywords, search queries, scoring weights. It reuses the
  **existing** legacy endpoints unchanged; nothing here is a new API.
* **About** answers "what is actually built?" — a question that currently has no
  answer inside the product, only in the docs.

``routes.py`` is deliberately not touched: the 17 legacy endpoints keep their
paths, shapes and behaviour, which is what makes the regression guarantee hold.
"""

from __future__ import annotations

import logging

from flask import Blueprint, render_template

from ..db.database import get_session
from ..db.models import (
    DashboardKeyword,
    DashboardSearchQuery,
    DashboardSubreddit,
    Settings,
)

log = logging.getLogger(__name__)

bp = Blueprint("pages", __name__)

#: Same defaults as the legacy dashboard. Duplicated deliberately rather than
#: imported from routes.py, so that file stays untouched.
_SCORING_DEFAULTS = {
    "keyword_weight": "3",
    "upvote_weight": "1",
    "comment_weight": "2",
    "recency_weight": "1.5",
    "high_intent_multiplier": "2",
    "interval_minutes": "60",
}


def _setting(session, key: str, default: str) -> str:
    row = session.query(Settings).filter_by(key=key).one_or_none()
    return row.value if row else default


@bp.route("/configuration")
def configuration():
    session = get_session()
    try:
        return render_template(
            "configuration.html",
            nav_active="configuration",
            dash_subreddits=session.query(DashboardSubreddit)
            .order_by(DashboardSubreddit.name)
            .all(),
            high_keywords=session.query(DashboardKeyword)
            .filter_by(intent_level="high")
            .order_by(DashboardKeyword.keyword)
            .all(),
            med_keywords=session.query(DashboardKeyword)
            .filter_by(intent_level="medium")
            .order_by(DashboardKeyword.keyword)
            .all(),
            search_queries=session.query(DashboardSearchQuery)
            .order_by(DashboardSearchQuery.query)
            .all(),
            settings={k: _setting(session, k, v) for k, v in _SCORING_DEFAULTS.items()},
        )
    finally:
        session.close()


@bp.route("/about")
def about():
    """What is built, what is not, and how to verify it.

    Phase status is read from the migration head rather than hardcoded, so this
    page cannot drift out of date the way a hand-maintained one would.
    """
    from ..db.database import DB_PATH
    from ..db.migrate import MigrationRunner

    schema = {}
    try:
        status = MigrationRunner(DB_PATH).status()
        schema = {
            "current": status.current,
            "head": status.head,
            "up_to_date": status.is_current,
        }
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("about: could not read migration status: %s", exc)
        schema = {"current": "unknown", "head": "unknown", "up_to_date": False, "error": str(exc)}

    lead_count = 0
    session = get_session()
    try:
        from ..db.models import Lead

        lead_count = session.query(Lead).count()
    except Exception:  # pragma: no cover - defensive
        log.debug("about: lead count failed", exc_info=True)
    finally:
        session.close()

    return render_template(
        "about.html",
        nav_active="about",
        schema=schema,
        lead_count=lead_count,
    )
