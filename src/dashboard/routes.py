import csv
import io
import datetime
import threading
from flask import Blueprint, render_template, request, jsonify, Response
from sqlalchemy import desc, func

from src.db.database import get_session
from src.db.models import (
    Lead, Subreddit, DashboardSubreddit, DashboardKeyword,
    DashboardSearchQuery, Settings, TrackedUser, ScrapeRun
)

bp = Blueprint("main", __name__)


def _get_setting(session, key, default=None):
    s = session.query(Settings).filter_by(key=key).first()
    return s.value if s else default


def _set_setting(session, key, value):
    s = session.query(Settings).filter_by(key=key).first()
    if s:
        s.value = str(value)
    else:
        s = Settings(key=key, value=str(value))
        session.add(s)


@bp.route("/")
def index():
    session = get_session()
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        subreddit = request.args.get("subreddit", "")
        sort_by = request.args.get("sort", "intent_score")
        min_score = request.args.get("min_score", 0, type=float)
        search = request.args.get("search", "")
        status = request.args.get("status", "")

        query = session.query(Lead)

        if subreddit:
            query = query.filter(Lead.subreddit == subreddit)
        if min_score > 0:
            query = query.filter(Lead.intent_score >= min_score)
        if search:
            query = query.filter(
                Lead.title.ilike(f"%{search}%") | Lead.body.ilike(f"%{search}%")
            )
        if status:
            query = query.filter(Lead.status == status)

        sort_column = getattr(Lead, sort_by, Lead.intent_score)
        query = query.order_by(desc(sort_column))

        total = query.count()
        leads = query.offset((page - 1) * per_page).limit(per_page).all()

        subreddits = session.query(Subreddit).order_by(Subreddit.name).all()
        dash_subreddits = session.query(DashboardSubreddit).order_by(DashboardSubreddit.name).all()
        high_keywords = session.query(DashboardKeyword).filter_by(intent_level="high").order_by(DashboardKeyword.keyword).all()
        med_keywords = session.query(DashboardKeyword).filter_by(intent_level="medium").order_by(DashboardKeyword.keyword).all()
        search_queries = session.query(DashboardSearchQuery).order_by(DashboardSearchQuery.query).all()
        tracked_users = session.query(TrackedUser).order_by(desc(TrackedUser.lead_count)).limit(10).all()
        recent_runs = session.query(ScrapeRun).order_by(desc(ScrapeRun.run_at)).limit(5).all()

        stats = {
            "total_leads": session.query(Lead).count(),
            "total_subreddits": session.query(Subreddit).count(),
            "total_users": session.query(TrackedUser).count(),
            "avg_score": session.query(func.avg(Lead.intent_score)).scalar() or 0,
            "new_leads": session.query(Lead).filter(Lead.status == "new").count(),
            "contacted": session.query(Lead).filter(Lead.status == "contacted").count(),
            "interested": session.query(Lead).filter(Lead.status == "interested").count(),
        }

        chart_data = _get_chart_data(session)

        settings = {
            "keyword_weight": _get_setting(session, "keyword_weight", "3"),
            "upvote_weight": _get_setting(session, "upvote_weight", "1"),
            "comment_weight": _get_setting(session, "comment_weight", "2"),
            "recency_weight": _get_setting(session, "recency_weight", "1.5"),
            "high_intent_multiplier": _get_setting(session, "high_intent_multiplier", "2"),
            "interval_minutes": _get_setting(session, "interval_minutes", "60"),
        }

        return render_template(
            "index.html",
            leads=leads,
            subreddits=subreddits,
            dash_subreddits=dash_subreddits,
            high_keywords=high_keywords,
            med_keywords=med_keywords,
            search_queries=search_queries,
            tracked_users=tracked_users,
            recent_runs=recent_runs,
            stats=stats,
            chart_data=chart_data,
            settings=settings,
            page=page,
            per_page=per_page,
            total=total,
            subreddit=subreddit,
            sort_by=sort_by,
            min_score=min_score,
            search=search,
            status_filter=status,
        )
    finally:
        session.close()


def _get_chart_data(session):
    leads_by_day = []
    rows = (
        session.query(
            func.date(Lead.scraped_at).label("day"),
            func.count(Lead.id).label("count"),
        )
        .group_by(func.date(Lead.scraped_at))
        .order_by("day")
        .limit(30)
        .all()
    )
    for row in rows:
        leads_by_day.append({"day": str(row.day), "count": row.count})

    top_subreddits = []
    rows = (
        session.query(Lead.subreddit, func.count(Lead.id).label("count"))
        .group_by(Lead.subreddit)
        .order_by(desc("count"))
        .limit(10)
        .all()
    )
    for row in rows:
        top_subreddits.append({"subreddit": row[0], "count": row[1]})

    keyword_breakdown = []
    all_keywords = {}
    leads = session.query(Lead.matched_keywords).filter(Lead.matched_keywords != "").all()
    for (kw_str,) in leads:
        for kw in kw_str.split(", "):
            kw = kw.strip()
            if kw:
                clean = kw.replace("[HIGH]", "").replace("[MED]", "")
                all_keywords[clean] = all_keywords.get(clean, 0) + 1
    sorted_kw = sorted(all_keywords.items(), key=lambda x: x[1], reverse=True)[:10]
    for kw, count in sorted_kw:
        keyword_breakdown.append({"keyword": kw, "count": count})

    return {
        "leads_by_day": leads_by_day,
        "top_subreddits": top_subreddits,
        "keyword_breakdown": keyword_breakdown,
    }


# ---- Leads API ----

@bp.route("/api/leads")
def api_leads():
    session = get_session()
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 50, type=int)
        subreddit = request.args.get("subreddit", "")

        query = session.query(Lead)
        if subreddit:
            query = query.filter(Lead.subreddit == subreddit)

        leads = query.order_by(desc(Lead.intent_score)).offset((page - 1) * per_page).limit(per_page).all()

        return jsonify([{
            "id": l.id,
            "reddit_id": l.reddit_id,
            "subreddit": l.subreddit,
            "author": l.author,
            "title": l.title,
            "url": l.url,
            "score": l.score,
            "num_comments": l.num_comments,
            "intent_score": l.intent_score,
            "matched_keywords": l.matched_keywords,
            "status": l.status,
            "created_utc": l.created_utc.isoformat() if l.created_utc else None,
        } for l in leads])
    finally:
        session.close()


@bp.route("/api/leads/<int:lead_id>/status", methods=["PUT"])
def api_lead_status(lead_id):
    data = request.get_json()
    if not data or "status" not in data:
        return jsonify({"error": "status required"}), 400

    valid_statuses = ["new", "contacted", "interested", "rejected"]
    if data["status"] not in valid_statuses:
        return jsonify({"error": f"status must be one of: {valid_statuses}"}), 400

    session = get_session()
    try:
        lead = session.query(Lead).get(lead_id)
        if not lead:
            return jsonify({"error": "not found"}), 404
        lead.status = data["status"]
        session.commit()
        return jsonify({"ok": True, "status": lead.status})
    finally:
        session.close()


@bp.route("/api/leads/<int:lead_id>", methods=["DELETE"])
def api_lead_delete(lead_id):
    session = get_session()
    try:
        lead = session.query(Lead).get(lead_id)
        if not lead:
            return jsonify({"error": "not found"}), 404
        session.delete(lead)
        session.commit()
        return jsonify({"ok": True})
    finally:
        session.close()


@bp.route("/api/leads/export")
def api_leads_export():
    session = get_session()
    try:
        subreddit = request.args.get("subreddit", "")
        status = request.args.get("status", "")
        search = request.args.get("search", "")

        query = session.query(Lead)
        if subreddit:
            query = query.filter(Lead.subreddit == subreddit)
        if status:
            query = query.filter(Lead.status == status)
        if search:
            query = query.filter(
                Lead.title.ilike(f"%{search}%") | Lead.body.ilike(f"%{search}%")
            )

        leads = query.order_by(desc(Lead.intent_score)).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID", "Reddit ID", "Subreddit", "Author", "Title", "URL",
            "Score", "Comments", "Intent Score", "Keywords", "Status",
            "Created UTC", "Scraped At"
        ])
        for l in leads:
            writer.writerow([
                l.id, l.reddit_id, l.subreddit, l.author, l.title, l.url,
                l.score, l.num_comments, l.intent_score, l.matched_keywords,
                l.status, l.created_utc, l.scraped_at,
            ])

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
        )
    finally:
        session.close()


# ---- Subreddits API ----

@bp.route("/api/subreddits", methods=["GET"])
def api_subreddits_list():
    session = get_session()
    try:
        subs = session.query(DashboardSubreddit).order_by(DashboardSubreddit.name).all()
        return jsonify([{"id": s.id, "name": s.name} for s in subs])
    finally:
        session.close()


@bp.route("/api/subreddits", methods=["POST"])
def api_subreddits_add():
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "name required"}), 400

    name = data["name"].strip().lower().replace("r/", "").replace("/", "")
    if not name:
        return jsonify({"error": "invalid name"}), 400

    session = get_session()
    try:
        existing = session.query(DashboardSubreddit).filter_by(name=name).first()
        if existing:
            return jsonify({"error": "already exists"}), 409

        sub = DashboardSubreddit(name=name)
        session.add(sub)
        session.commit()
        return jsonify({"id": sub.id, "name": sub.name}), 201
    finally:
        session.close()


@bp.route("/api/subreddits/<int:sub_id>", methods=["DELETE"])
def api_subreddits_delete(sub_id):
    session = get_session()
    try:
        sub = session.query(DashboardSubreddit).get(sub_id)
        if not sub:
            return jsonify({"error": "not found"}), 404
        session.delete(sub)
        session.commit()
        return jsonify({"ok": True})
    finally:
        session.close()


# ---- Keywords API ----

@bp.route("/api/keywords", methods=["GET"])
def api_keywords_list():
    session = get_session()
    try:
        kws = session.query(DashboardKeyword).order_by(DashboardKeyword.intent_level, DashboardKeyword.keyword).all()
        return jsonify([{"id": k.id, "keyword": k.keyword, "intent_level": k.intent_level} for k in kws])
    finally:
        session.close()


@bp.route("/api/keywords", methods=["POST"])
def api_keywords_add():
    data = request.get_json()
    if not data or "keyword" not in data:
        return jsonify({"error": "keyword required"}), 400

    keyword = data["keyword"].strip().lower()
    intent_level = data.get("intent_level", "high")
    if intent_level not in ["high", "medium"]:
        return jsonify({"error": "intent_level must be high or medium"}), 400

    if not keyword:
        return jsonify({"error": "invalid keyword"}), 400

    session = get_session()
    try:
        existing = session.query(DashboardKeyword).filter_by(keyword=intent_level + ":" + keyword).first()
        if existing:
            return jsonify({"error": "already exists"}), 409

        kw = DashboardKeyword(keyword=intent_level + ":" + keyword, intent_level=intent_level)
        session.add(kw)
        session.commit()
        return jsonify({"id": kw.id, "keyword": keyword, "intent_level": intent_level}), 201
    finally:
        session.close()


@bp.route("/api/keywords/<int:kw_id>", methods=["DELETE"])
def api_keywords_delete(kw_id):
    session = get_session()
    try:
        kw = session.query(DashboardKeyword).get(kw_id)
        if not kw:
            return jsonify({"error": "not found"}), 404
        session.delete(kw)
        session.commit()
        return jsonify({"ok": True})
    finally:
        session.close()


# ---- Search Queries API ----

@bp.route("/api/queries", methods=["GET"])
def api_queries_list():
    session = get_session()
    try:
        queries = session.query(DashboardSearchQuery).order_by(DashboardSearchQuery.query).all()
        return jsonify([{"id": q.id, "query": q.query} for q in queries])
    finally:
        session.close()


@bp.route("/api/queries", methods=["POST"])
def api_queries_add():
    data = request.get_json()
    if not data or "query" not in data:
        return jsonify({"error": "query required"}), 400

    query_text = data["query"].strip()
    if not query_text:
        return jsonify({"error": "invalid query"}), 400

    session = get_session()
    try:
        existing = session.query(DashboardSearchQuery).filter_by(query=query_text).first()
        if existing:
            return jsonify({"error": "already exists"}), 409

        q = DashboardSearchQuery(query=query_text)
        session.add(q)
        session.commit()
        return jsonify({"id": q.id, "query": q.query}), 201
    finally:
        session.close()


@bp.route("/api/queries/<int:q_id>", methods=["DELETE"])
def api_queries_delete(q_id):
    session = get_session()
    try:
        q = session.query(DashboardSearchQuery).get(q_id)
        if not q:
            return jsonify({"error": "not found"}), 404
        session.delete(q)
        session.commit()
        return jsonify({"ok": True})
    finally:
        session.close()


# ---- Settings API ----

@bp.route("/api/settings", methods=["GET"])
def api_settings_get():
    session = get_session()
    try:
        keys = ["keyword_weight", "upvote_weight", "comment_weight", "recency_weight", "high_intent_multiplier", "interval_minutes"]
        result = {}
        for key in keys:
            result[key] = _get_setting(session, key, "")
        return jsonify(result)
    finally:
        session.close()


@bp.route("/api/settings", methods=["PUT"])
def api_settings_put():
    data = request.get_json()
    if not data:
        return jsonify({"error": "data required"}), 400

    session = get_session()
    try:
        for key, value in data.items():
            _set_setting(session, key, value)
        session.commit()
        return jsonify({"ok": True})
    finally:
        session.close()


# ---- Scrape API ----

@bp.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Create a run and enqueue its work. Response shape unchanged (R20).

    The recorded contract is `{"ok": true, "message": "Scrape started in
    background"}` (tests/baseline/api_scrape_contract.json, captured before this
    edit). `run_id` is ADDED; docs/13 §6 permits that and forbids changing or
    removing a key.

    **The status code is part of that contract too.** This route has only ever
    returned 200, and the sidebar button calls it with `fetch(...).then(r =>
    r.json())` and no status check -- a 409 would render to the operator as
    "Scrape complete!". So when a run is already active this returns 200 with
    that run's id, which is also the behaviour docs/13 §9.4 wants: the UI
    navigates to the run in flight instead of starting a second one. The 409 the
    duplicate-run guard produces is exposed on POST /api/runs, where AC7 asserts
    it and where no legacy client is listening.

    ⚠️ Through the queue this runs the SUBREDDIT scraper only. The frozen
    job-type list (docs/04 §2.4) has no keyword or user type; those stages
    arrive in P5/P17. `orchestration.enabled: false` restores the pre-P3
    behaviour, and `python main.py scrape` still runs all three.
    """
    from src.orchestration.run_service import orchestration_enabled

    if not orchestration_enabled():
        return _legacy_scrape()

    from src.dashboard.routes_runs import configured_subreddits
    from src.orchestration.run_service import RunAlreadyActive, RunOptions, RunService

    session = get_session()
    try:
        try:
            run = RunService(session).create(
                None, RunOptions(subreddits=configured_subreddits(session))
            )
            session.commit()
            run_id = run.id
        except RunAlreadyActive as exc:
            # Not an error from this route's point of view: the operator asked
            # for a scrape and there is one running. Point them at it.
            run_id = exc.run_id
        return jsonify(
            {"ok": True, "message": "Scrape started in background", "run_id": run_id}
        )
    finally:
        session.close()


def _legacy_scrape():
    """The pre-P3 daemon thread, retained behind `orchestration.enabled: false`.

    Kept verbatim rather than reimplemented. It is the documented rollback for
    this phase (docs/34 §P3), and a rollback path that had been "tidied up" is
    one nobody can trust at the moment they need it.
    """
    from src.config import load_config
    from src.db.database import init_db
    from src.reddit_client import RedditClient
    from src.scrapers.keyword_scraper import KeywordScraper
    from src.scrapers.subreddit_scraper import SubredditScraper
    from src.scrapers.user_scraper import UserScraper

    def run_scrape():
        config = load_config()
        init_db()
        client = RedditClient(config)
        session = get_session()
        try:
            SubredditScraper(client, config).run(session)
            KeywordScraper(client, config).run(session)
            UserScraper(client, config).run(session)
        except Exception as e:
            print(f"Scrape error: {e}")
        finally:
            session.close()

    thread = threading.Thread(target=run_scrape, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Scrape started in background"})


# ---- Stats API ----

@bp.route("/api/stats")
def api_stats():
    session = get_session()
    try:
        return jsonify({
            "total_leads": session.query(Lead).count(),
            "total_subreddits": session.query(Subreddit).count(),
            "total_users": session.query(TrackedUser).count(),
        })
    finally:
        session.close()
