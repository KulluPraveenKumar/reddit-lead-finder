from src.db.models import DashboardSubreddit, DashboardKeyword, DashboardSearchQuery, Settings


def get_all_subreddits(config, session):
    config_subs = [s.lower() for s in config.get("subreddits", [])]
    db_subs = [s.name.lower() for s in session.query(DashboardSubreddit).all()]
    combined = list(set(config_subs + db_subs))
    combined.sort()
    return combined


def get_all_keywords(config, session):
    config_high = [k.lower() for k in config.get("keywords", {}).get("high_intent", [])]
    config_med = [k.lower() for k in config.get("keywords", {}).get("medium_intent", [])]

    db_high = []
    db_med = []
    for kw in session.query(DashboardKeyword).filter_by(intent_level="high").all():
        keyword = kw.keyword.split(":", 1)[1] if ":" in kw.keyword else kw.keyword
        db_high.append(keyword.lower())
    for kw in session.query(DashboardKeyword).filter_by(intent_level="medium").all():
        keyword = kw.keyword.split(":", 1)[1] if ":" in kw.keyword else kw.keyword
        db_med.append(keyword.lower())

    high = list(set(config_high + db_high))
    medium = list(set(config_med + db_med))
    high.sort()
    medium.sort()
    return high, medium


def get_all_search_queries(session):
    return [q.query for q in session.query(DashboardSearchQuery).all()]


#: Setting key -> fallback used when the row is absent. The fallbacks are the
#: same values the previous implementation inlined.
_SCORING_DEFAULTS = {
    "keyword_weight": 3,
    "upvote_weight": 1,
    "comment_weight": 2,
    "recency_weight": 1.5,
    "high_intent_multiplier": 2,
}


def get_scoring_settings(config, session):
    """Scoring weights: database row, else config, else the built-in default.

    One query for all five keys. The previous version issued *ten* -- each key
    was queried once to test for existence and again to read the value -- and it
    ran inside the scorer's constructor, so a scrape paid it per run. The result
    is unchanged, value for value.
    """
    defaults = config.get("scoring", {})

    # `settings.key` is UNIQUE, so one row per key and a plain dict would do.
    # setdefault + ordering keeps this identical to the old `.first()` (lowest
    # rowid wins) even if that constraint is ever relaxed -- the cost is nil and
    # it removes the need to re-derive the equivalence later.
    stored: dict[str, str] = {}
    for row in session.query(Settings).order_by(Settings.id):
        stored.setdefault(row.key, row.value)

    return {
        key: float(stored[key] if key in stored else defaults.get(key, fallback))
        for key, fallback in _SCORING_DEFAULTS.items()
    }
