import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _utcnow() -> datetime.datetime:
    """Timezone-aware UTC now, stored naive to match the existing columns.

    Every ``DateTime`` default in this module goes through here. ``utcnow`` is
    deprecated in 3.12 and raises under ``-W error::DeprecationWarning`` — and
    because SQLAlchemy evaluates column defaults *inside* statement execution,
    that raise surfaces as a ``StatementError`` on INSERT rather than anything
    that names a datetime.

    The ``replace(tzinfo=None)`` is load-bearing, not cosmetic. The whole schema
    stores naive UTC, and ``job_queue.claim`` compares timestamps as formatted
    SQLite strings; an aware value serializes with a ``+00:00`` suffix, so the
    comparison would silently stop matching. Naive-UTC in, naive-UTC out.
    """
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)
    reddit_id = Column(String(20), unique=True, nullable=False, index=True)
    subreddit = Column(String(100), nullable=False, index=True)
    author = Column(String(100), nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text, default="")
    url = Column(Text, nullable=False)
    post_type = Column(String(20), default="post")
    # ⚠️ NO `default=0` on these two, removed in P11 -- this is DI13's substance
    # one layer below where the register found it.
    #
    # The schema has always said `nullable=True` with NO server default
    # (`0001_baseline.py`), and `src/scoring/legacy.py` states the intent
    # plainly: "the Lead row still stores NULL, because 'unknown' and 'zero
    # upvotes' are different facts and conflating them would make the number a
    # quiet lie." A Python-side `default=0` is exactly that conflation --
    # SQLAlchemy applies it whenever the value is None at INSERT -- so the
    # honest unknown `_extract_search_post` produces was overwritten with a
    # confident 0 before it ever reached the database.
    #
    # Measured 2026-08-15 on the live database: **0 of 492 rows carry NULL** in
    # either column, on a corpus where 27 leads came from the search path that
    # cannot know a score. The intent was documented, tested nowhere, and never
    # held.
    #
    # P11 is where it stops being cosmetic: docs/34 §P11 task 4 is "score
    # back-fill for search-sourced leads", and there is nothing to back-fill
    # while the default has already answered the question wrongly.
    #
    # No migration and no schema change: these are Python-side defaults only, so
    # the column definition is untouched and the 459 original rows keep the
    # values they have. New rows record what is actually known.
    score = Column(Integer)
    num_comments = Column(Integer)
    intent_score = Column(Float, default=0.0)
    matched_keywords = Column(Text, default="")
    status = Column(String(20), default="new", index=True)
    created_utc = Column(DateTime, nullable=False)
    scraped_at = Column(DateTime, default=_utcnow)

    # --- 0006_content_and_dedup -------------------------------------------
    #
    # `project_id` carries NO ForeignKey: `projects` arrives in 0007, which
    # closes the constraint (M8). Declaring it here would not merely be
    # premature -- SQLAlchemy would emit `REFERENCES projects(id)` into any
    # create_all(), and SQLite resolves a REFERENCES target when it PREPARES a
    # statement, so every INSERT into leads would fail with "no such table"
    # even with the column set to NULL.
    #
    # `intent_score` above is untouched and keeps its meaning. That is the
    # guarantee that keeps the 459 legacy rows usable.
    project_id = Column(Integer, nullable=True)
    # NULL means "never analysed", which is not the same as 0.0 ("analysed and
    # judged worthless"). Sorting must place NULLs last.
    confidence_score = Column(Float, nullable=True)
    # not_analyzed | pending | analyzed | failed | skipped
    analysis_status = Column(
        String(20), nullable=False, server_default="not_analyzed", default="not_analyzed"
    )
    # scrape | holdout_audit -- R27's fix. A holdout-audited item must become a
    # real, labellable lead, or the yield curve is fitted only on the gate's own
    # admissions and recall collapses invisibly.
    source = Column(String(20), nullable=False, server_default="scrape", default="scrape")

    __table_args__ = (
        Index("ix_leads_intent_score", "intent_score"),
        Index("ix_leads_scraped_at", "scraped_at"),
        Index("ix_leads_project_id", "project_id"),
        Index("ix_leads_confidence_score", "confidence_score"),
        Index("ix_leads_analysis_status", "analysis_status"),
        Index("ix_leads_project_conf", "project_id", text("confidence_score DESC")),
    )

    def __repr__(self):
        return f"<Lead {self.reddit_id}: {self.title[:50]}>"


class Subreddit(Base):
    __tablename__ = "subreddits"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, default="")
    subscriber_count = Column(Integer, default=0)
    last_scraped = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Subreddit r/{self.name}>"


class DashboardSubreddit(Base):
    __tablename__ = "dashboard_subreddits"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    added_at = Column(DateTime, default=_utcnow)

    def __repr__(self):
        return f"<DashboardSubreddit r/{self.name}>"


class DashboardKeyword(Base):
    __tablename__ = "dashboard_keywords"

    id = Column(Integer, primary_key=True)
    keyword = Column(String(200), nullable=False)
    intent_level = Column(String(20), nullable=False, default="high")
    added_at = Column(DateTime, default=_utcnow)

    def __repr__(self):
        return f"<DashboardKeyword [{self.intent_level}] {self.keyword}>"


class DashboardSearchQuery(Base):
    __tablename__ = "dashboard_search_queries"

    id = Column(Integer, primary_key=True)
    query = Column(String(300), nullable=False)
    added_at = Column(DateTime, default=_utcnow)

    def __repr__(self):
        return f"<DashboardSearchQuery {self.query}>"


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)

    def __repr__(self):
        return f"<Settings {self.key}={self.value}>"


class TrackedUser(Base):
    __tablename__ = "tracked_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    post_count = Column(Integer, default=1)
    lead_count = Column(Integer, default=0)
    first_seen = Column(DateTime, default=_utcnow)
    last_seen = Column(DateTime, default=_utcnow)

    def __repr__(self):
        return f"<TrackedUser u/{self.username}>"


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id = Column(Integer, primary_key=True)
    scraper_type = Column(String(50), nullable=False)
    subreddit = Column(String(100), nullable=True)
    posts_found = Column(Integer, default=0)
    leads_found = Column(Integer, default=0)
    run_at = Column(DateTime, default=_utcnow)
    # Added in 0004. NULL on the 10 pre-existing rows, forever: they predate
    # orchestration and belong to no run. This table stays the per-scraper audit
    # record it already is; `runs` is the higher-level concept.
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)

    def __repr__(self):
        return f"<ScrapeRun {self.scraper_type} at {self.run_at}>"


# ---------------------------------------------------------------------------
# Phase 1 — AI Service Layer infrastructure (docs/05 §5.4a)
#
# All three are new tables, so nothing above is touched. `run_id` and
# `project_id` carry no REFERENCES clause: `runs` and `projects` do not exist
# until 0004/0005, which add the constraints via batch_alter_table.
#
# NO CREDENTIAL IS STORED IN ANY OF THESE. The encrypted API key lives in the
# pre-existing `settings` table.
# ---------------------------------------------------------------------------


class AICall(Base):
    """One row per provider call. Source of truth for cost, tokens, cache health."""

    __tablename__ = "ai_calls"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, nullable=True)  # FK added in 0004
    project_id = Column(Integer, nullable=True)  # FK added in 0005
    provider = Column(String(40), nullable=False)
    model = Column(String(60), nullable=False)
    stage = Column(String(60), nullable=False)
    prompt_version = Column(Integer, nullable=False)
    prefix_hash = Column(String(64), nullable=True)

    # Split, not combined: the two are priced 50x apart, so a single "input
    # tokens" column would make cost impossible to reconstruct or audit.
    input_tokens_cached = Column(Integer, nullable=False, default=0)
    input_tokens_uncached = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)

    cost_usd = Column(Float, nullable=False, default=0.0)
    surcharge_multiplier = Column(Float, nullable=False, default=1.0)
    latency_ms = Column(Integer, nullable=True)
    attempt = Column(Integer, nullable=False, default=1)
    outcome = Column(String(30), nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_ai_calls_run", "run_id", "created_at"),
        Index("ix_ai_calls_project", "project_id", "created_at"),
        Index("ix_ai_calls_stage", "stage", "outcome"),
        Index("ix_ai_calls_day", "created_at"),
    )

    def __repr__(self):
        return f"<AICall {self.stage} {self.outcome} ${self.cost_usd:.6f}>"


class AICache(Base):
    """Response cache. Permanent by design.

    An unchanged prompt about unchanged text has an unchanged answer, so there
    is no correctness reason to expire this. Deleting every row costs money to
    rebuild and changes no result (docs/06i §4).
    """

    __tablename__ = "ai_cache"

    cache_key = Column(String(64), primary_key=True)
    provider = Column(String(40), nullable=False)
    model = Column(String(60), nullable=False)
    stage = Column(String(60), nullable=False)
    prompt_version = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=True)
    payload_json = Column(Text, nullable=False)
    hits = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    last_hit_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # The "never analyse identical content twice" index.
        Index("ix_ai_cache_content", "content_hash", "stage", "prompt_version"),
        Index("ix_ai_cache_stage", "stage", "prompt_version"),
    )

    def __repr__(self):
        return f"<AICache {self.stage} {self.cache_key[:12]} hits={self.hits}>"


class AIProviderState(Base):
    """Provider health and validation state. Never a credential."""

    __tablename__ = "ai_provider_state"

    id = Column(Integer, primary_key=True)
    provider = Column(String(40), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="unconfigured")
    key_fingerprint = Column(String(20), nullable=True)  # "sk-…a3f9", display only
    key_sha256 = Column(String(64), nullable=True)  # change detection only
    model_id = Column(String(60), nullable=True)
    context_window = Column(Integer, nullable=True)
    last_validated_at = Column(DateTime, nullable=True)
    last_validation_ms = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f"<AIProviderState {self.provider}={self.status}>"


class AIStatus:
    """The six status states rendered on /settings/ai (docs/09 §2a)."""

    UNCONFIGURED = "unconfigured"
    VALID = "valid"
    INVALID_KEY = "invalid_key"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    UNREACHABLE = "unreachable"
    # Set when APP_SECRET_KEY changed and the stored ciphertext no longer
    # decrypts. Distinct from unconfigured: a key exists, it is just unreadable,
    # and the remedy ("re-enter your key") differs from "enter a key".
    UNDECRYPTABLE = "undecryptable"

    ALL = (
        UNCONFIGURED,
        VALID,
        INVALID_KEY,
        INSUFFICIENT_BALANCE,
        UNREACHABLE,
        UNDECRYPTABLE,
    )


# ---------------------------------------------------------------------------
# Phase 2 - network infrastructure (docs/05 5.6)
#
# `proxies` stores host, port and health ONLY. No username, no password: the
# credentials live in the gitignored proxy file and nowhere else, so a leaked
# database file cannot become a leaked proxy account. A test asserts the column
# list to keep it that way.
# ---------------------------------------------------------------------------


class Proxy(Base):
    """Health and usage for one proxy endpoint. NEVER a credential."""

    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    host = Column(String(120), nullable=False)
    port = Column(Integer, nullable=False)
    state = Column(String(20), nullable=False, default="untested")
    exit_ip = Column(String(45), nullable=True)
    requests = Column(Integer, nullable=False, default=0)
    failures = Column(Integer, nullable=False, default=0)
    blocked_responses = Column(Integer, nullable=False, default=0)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    mean_latency_ms = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    blacklisted_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (Index("ux_proxies_endpoint", "host", "port", unique=True),)

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}"

    def __repr__(self):
        return f"<Proxy {self.label} {self.state}>"


class HttpCache(Base):
    """Short-TTL response cache. Purely an accelerator - safe to purge."""

    __tablename__ = "http_cache"

    cache_key = Column(String(64), primary_key=True)
    url = Column(String(2000), nullable=False)
    body = Column(Text, nullable=False)
    fetched_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    hits = Column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_http_cache_expires", "expires_at"),)

    def __repr__(self):
        return f"<HttpCache {self.url[:50]}>"


class Metric(Base):
    """Time series of in-process counters. Operational, purgeable."""

    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    value = Column(Float, nullable=False, default=0.0)
    recorded_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_metrics_name_time", "name", "recorded_at"),)

    def __repr__(self):
        return f"<Metric {self.name}={self.value}>"


# ---------------------------------------------------------------------------
# P1 - orchestration (docs/05 5.3, docs/04 1-3)
#
# Three new tables. The only change to anything pre-existing is one nullable
# column on `scrape_runs`, which is why the 459 live leads are untouched.
#
# `runs.project_id` carries NO REFERENCES clause: `projects` does not exist
# until 0007, which adds the constraint and tightens the column to NOT NULL via
# batch_alter_table. Same deferred-FK pattern `ai_calls` already uses.
#
# NOTHING HERE EXECUTES WORK. P1 ships the vocabulary; P2 ships the queue and
# worker that act on it.
# ---------------------------------------------------------------------------


class Run(Base):
    """One end-to-end pipeline execution, and where it currently is.

    The state lives in this column and nowhere else. A thread's stack cannot
    wait a week for a human to approve a gate, survive a restart, or be queried
    by the dashboard - which is the entire reason this table exists rather than
    a long-lived function call (docs/01 3).

    There is deliberately **no expiry, timeout or TTL column**. A run may sit at
    a gate indefinitely. See `src.orchestration.states`.
    """

    __tablename__ = "runs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=True)  # FK + NOT NULL added in 0007
    state = Column(String(40), nullable=False)
    options_json = Column(Text, nullable=True)  # RunOptions: limits, window, toggles
    stats_json = Column(Text, nullable=True)  # rolling counters for /progress
    llm_cost_usd = Column(Float, nullable=False, default=0.0)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_runs_project_state", "project_id", "state"),)

    def __repr__(self):
        return f"<Run {self.id} {self.state}>"


class Job(Base):
    """One unit of work, claimed with a lease.

    `lease_expires_at` is what makes a crashed worker recoverable: the queue
    reclaims anything whose lease has passed rather than leaving it `running`
    forever. That in turn is why every handler must be idempotent - a reclaimed
    job runs twice by design, not by accident.
    """

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=True)
    job_type = Column(String(60), nullable=False)
    payload_json = Column(Text, nullable=False, default="{}")
    state = Column(String(20), nullable=False, default="queued")
    priority = Column(Integer, nullable=False, default=100)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    available_at = Column(DateTime, nullable=False, default=_utcnow)
    worker_id = Column(String(80), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    result_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # Column order matches the claim query exactly:
        #   WHERE state=? AND available_at<=? ORDER BY priority, id
        # This is the index the queue lives or dies on.
        Index("ix_jobs_claim", "state", "available_at", "priority", "id"),
        Index("ix_jobs_run", "run_id", "state"),
        Index("ix_jobs_lease", "state", "lease_expires_at"),
    )

    def __repr__(self):
        return f"<Job {self.id} {self.job_type} {self.state}>"


class RunEvent(Base):
    """Append-only timeline for one run. The operator-facing activity feed.

    Distinct from the application log: this is what a *person* reads on the run
    page, so it is queryable, correlated to a run, and never rotated away while
    the run is recent.
    """

    __tablename__ = "run_events"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    level = Column(String(10), nullable=False, default="info")  # info | warning | error
    event = Column(String(80), nullable=False)
    message = Column(Text, nullable=True)
    data_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_run_events_run", "run_id", "id"),)

    def __repr__(self):
        return f"<RunEvent run={self.run_id} {self.event}>"


class DiscoveryWatermark(Base):
    """How far discovery has read one channel. The incremental-sync primitive.

    One row per (subreddit, channel, query). `last_seen_utc` exists *only* to
    detect overflow - the diff itself is on the id set, because `t3_` fullnames
    are base-36 but not reliably ordered across shards.

    There is no `last_etag` / `last_modified`: Reddit sends neither header on
    `.rss` (P0 U4, re-observed 2026-08-08), so there is nothing to store.
    """

    __tablename__ = "discovery_watermarks"

    id = Column(Integer, primary_key=True)
    subreddit = Column(String(100), nullable=False)
    channel = Column(String(20), nullable=False)  # listing | search
    query = Column(String(300), nullable=True)  # NULL for listing
    last_seen_fullname = Column(String(20), nullable=True)
    last_seen_utc = Column(DateTime, nullable=True)
    last_polled_at = Column(DateTime, nullable=True)
    consecutive_empty = Column(Integer, nullable=False, default=0)
    observed_rate_per_hour = Column(Float, nullable=True)
    next_poll_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # Two partial uniques, not one three-column unique. SQLite treats NULLs
        # as distinct in a UNIQUE index, so a single `(subreddit, channel,
        # query)` index would not constrain listing rows at all - `query` is
        # NULL for every one of them. Duplicated listing watermarks are
        # watermark poisoning (docs/28 D2) arriving through the schema.
        Index(
            "ux_watermarks_listing",
            "subreddit",
            "channel",
            unique=True,
            sqlite_where=text("query IS NULL"),
        ),
        Index(
            "ux_watermarks_search",
            "subreddit",
            "channel",
            "query",
            unique=True,
            sqlite_where=text("query IS NOT NULL"),
        ),
        Index("ix_watermarks_due", "next_poll_at"),
    )

    def __repr__(self):
        return f"<DiscoveryWatermark {self.subreddit}/{self.channel}>"


class Prescore(Base):
    """One row per collected item - admitted OR rejected.

    Storing the rejections is the whole point: without them the funnel could
    report *that* items were filtered but never *which*, and the gate would be
    untunable (R11, AD-10b). `stage` distinguishes a provisional judgement made
    from title and snippet alone from a full one made with a body.

    `comment_id` was bare from 0005 until 0006, which creates `comments` and
    closes the constraint (M8). It is declared here now, because the deferral is
    over: leaving it bare would make create_all() and `alembic upgrade head`
    disagree, and a model that under-declares the schema is how a later phase
    "discovers" a constraint the database has had all along.

    The CHECK held throughout without it - it constrains which column is
    populated, not what it points at.
    """

    __tablename__ = "prescores"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    comment_id = Column(
        Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True
    )  # FK closed in 0006
    total = Column(Float, nullable=False)
    components_json = Column(Text, nullable=False)
    stage = Column(String(20), nullable=False, default="full")  # metadata | full
    gate_decision = Column(String(20), nullable=False)  # admit | reject | cached | grouped
    gate_reason = Column(String(30), nullable=True)
    holdout_sampled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "(lead_id IS NOT NULL) <> (comment_id IS NOT NULL)",
            name="ck_prescores_one_target",
        ),
        Index("ix_prescores_run", "run_id", "gate_decision"),
        Index("ix_prescores_reason", "run_id", "gate_reason"),
        Index("ix_prescores_total", "run_id", text("total DESC")),
    )

    def __repr__(self):
        return f"<Prescore {self.stage} {self.gate_decision} {self.total}>"


# ---------------------------------------------------------------------------
# 0006_content_and_dedup
#
# ⚠️ Every `project_id` below is a BARE Column with no ForeignKey. `projects`
# does not exist until 0007, which closes all four constraints with
# batch_alter_table (M8). This is the same pattern `ai_calls.run_id` used from
# 0002 until 0004, and it is not stylistic: a REFERENCES clause naming a table
# that does not exist yet makes every INSERT into that table fail with
# "no such table: main.projects" -- including one setting the column to NULL,
# because SQLite resolves the parent when it prepares the statement rather than
# when it checks the constraint. Guarded by
# tests/test_migrations.py::test_no_revision_leaves_a_dangling_foreign_key.
# ---------------------------------------------------------------------------


class Comment(Base):
    """A comment on a lead. Deduplicated by content, not by id.

    `body_hash` is the real key: `_parse_comments` does not extract a comment
    id, and old.reddit's markup exposes `t1_` ids inconsistently across thread
    depths. A content hash is deterministic, needs no parser change, and
    correctly deduplicates on re-scrape. If a reliable id is later extracted it
    becomes an additional nullable column, not a replacement key.
    """

    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, nullable=True)  # bare until 0007
    reddit_id = Column(String(20), nullable=True)
    author = Column(String(100), nullable=False, server_default="[deleted]", default="[deleted]")
    body = Column(Text, nullable=False)
    score = Column(Integer, nullable=True)
    depth = Column(Integer, nullable=False, server_default="0", default=0)
    created_utc = Column(DateTime, nullable=True)
    scraped_at = Column(DateTime, nullable=False, default=_utcnow)
    analysis_status = Column(
        String(20), nullable=False, server_default="not_analyzed", default="not_analyzed"
    )
    confidence_score = Column(Float, nullable=True)
    body_hash = Column(String(64), nullable=False)  # sha256(lead_id|author|body)

    __table_args__ = (
        Index("ux_comments_hash", "body_hash", unique=True),
        Index("ix_comments_lead", "lead_id"),
        Index("ix_comments_project", "project_id", text("confidence_score DESC")),
    )

    def __repr__(self):
        return f"<Comment {self.id} on lead {self.lead_id}>"


class DedupGroup(Base):
    """One near-duplicate group. The representative is what gets enriched."""

    __tablename__ = "dedup_groups"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=True)  # bare AND nullable until 0007
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    representative_lead_id = Column(
        Integer, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    representative_comment_id = Column(
        Integer, ForeignKey("comments.id", ondelete="SET NULL"), nullable=True
    )
    member_count = Column(Integer, nullable=False, server_default="1", default=1)
    method = Column(String(20), nullable=False)  # exact | minhash
    similarity = Column(Float, nullable=True)  # Jaccard, for minhash groups
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_dedup_groups_project", "project_id", "run_id"),)

    def __repr__(self):
        return f"<DedupGroup {self.id} {self.method} n={self.member_count}>"


class DedupMember(Base):
    """Membership of a dedup group.

    ⚠️ **The two partial uniques do NOT enforce "one group per run".**
    They enforce *"at most once within a group"*, which is weaker. There is no
    `run_id` here -- the run is reachable only through `DedupGroup` -- and SQLite
    cannot express uniqueness across a join, so two groups from the same run can
    each claim the same lead and both indexes stay satisfied. That invariant is
    **application-level and P10's to uphold and test**; no test here claims it.
    """

    __tablename__ = "dedup_members"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("dedup_groups.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)
    is_representative = Column(Boolean, nullable=False, server_default="0", default=False)

    __table_args__ = (
        CheckConstraint(
            "(lead_id IS NOT NULL) <> (comment_id IS NOT NULL)",
            name="ck_dedup_members_one_target",
        ),
        Index(
            "ux_dedup_members_lead",
            "group_id",
            "lead_id",
            unique=True,
            sqlite_where=text("lead_id IS NOT NULL"),
        ),
        Index(
            "ux_dedup_members_comment",
            "group_id",
            "comment_id",
            unique=True,
            sqlite_where=text("comment_id IS NOT NULL"),
        ),
    )

    def __repr__(self):
        target = f"lead {self.lead_id}" if self.lead_id else f"comment {self.comment_id}"
        return f"<DedupMember group {self.group_id}: {target}>"


class MinhashBand(Base):
    """LSH band signatures. Rebuilt per run, purged with the run."""

    __tablename__ = "minhash_bands"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=True)  # bare AND nullable until 0007
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=True)
    band_index = Column(Integer, nullable=False)
    band_hash = Column(String(32), nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)

    __table_args__ = (Index("ix_minhash_lookup", "project_id", "band_index", "band_hash"),)

    def __repr__(self):
        return f"<MinhashBand {self.band_index}:{self.band_hash}>"


# ---------------------------------------------------------------------------
# 0007_projects_and_knowledge_base (P12) — the Business Knowledge Base.
#
# Twelve tables, and two more where `sqlite-vec` loads. This is the revision
# that closes six deferred `project_id` foreign keys, so the four `# bare until
# 0007` comments above are now historical notes about how the columns were
# created rather than statements about the current schema.
#
# NOTHING HERE IS POPULATED BY P12. Every table below is created empty:
# `projects` gets its first row from P16's `project add`, the BKB tables from
# P14's `analyze_business`, the entity registry from P15. P12 ships the shape.
# ---------------------------------------------------------------------------

#: The 23 BKB sections, in the order 06e §2 numbers them. The order is not
#: decorative: `bkb_sections` rows are rendered as four bands in P16's UI, and
#: the groups below are contiguous runs of this list.
BKB_SECTION_KEYS: tuple[str, ...] = (
    # Group A — Identity (generation input, display, rarely matched)
    "company_overview",
    "products_services",
    "features",
    "pricing_positioning",
    "industry",
    "target_market",
    # Group B — Buyer model (the matching surface)
    "ideal_customer_profiles",
    "buyer_personas",
    "pain_points",
    "jobs_to_be_done",
    "value_propositions",
    # Group C — Competitive and linguistic (matching surface)
    "competitor_references",
    "alternative_solutions",
    "customer_language",
    "reddit_terminology",
    "search_intent",
    "buying_signals",
    "common_objections",
    # Group D — Activation and discovery (retrieval-only)
    "outreach_angles",
    "content_themes",
    "seo_entities",
    "geo_entities",
    "negative_signals",
)

#: The three sections whose content lives in a typed table, so their
#: `bkb_sections.payload_json` is NULL and the other twenty are NOT NULL.
#:
#: ⚠️ **`ideal_customer_profiles` is deliberately not here.** It is easy to
#: assume otherwise because an ICP feels structurally like a persona; there is
#: no `icps` table, so its payload is the only copy of an ICP that exists, and
#: exempting it would lose the section entirely. 05 §5.1b flags this exact
#: mistake. `ck_bkb_sections_payload_null_rule` enforces both directions in the
#: schema, and `tests/test_schema_0007.py` asserts this tuple agrees with the
#: CHECK the migration wrote.
BKB_TYPED_SECTION_KEYS: tuple[str, ...] = ("buyer_personas", "pain_points", "buying_signals")

#: `bkb_sections.staleness_days` per section, from the policy in 06h §5.1.
#: Seeded at BKB build time — which is **P14's** job, not this revision's; P12
#: ships the policy as data so that P14 has one place to read it from rather
#: than a table in a document to re-transcribe.
#:
#: **Group C is NULL — it never stales.** Those seven accrete continuously from
#: Reddit and are therefore getting *fresher*, not older; showing them an age
#: badge would invite exactly the regeneration the `origin` guard (R12) exists
#: to prevent.
BKB_STALENESS_DAYS: dict[str, int | None] = {
    # Group A — Identity
    "company_overview": 180,
    "products_services": 180,
    "features": 180,
    "pricing_positioning": 180,
    "industry": 180,
    "target_market": 180,
    # Group B — Buyer model
    "ideal_customer_profiles": 90,
    "buyer_personas": 90,
    "pain_points": 90,
    "jobs_to_be_done": 90,
    "value_propositions": 90,
    # Group C — Competitive and linguistic. NULL = never stales.
    "competitor_references": None,
    "alternative_solutions": None,
    "customer_language": None,
    "reddit_terminology": None,
    "search_intent": None,
    "buying_signals": None,
    "common_objections": None,
    # Group D — Activation and discovery
    "outreach_angles": 180,
    "content_themes": 180,
    "seo_entities": 180,
    "geo_entities": 180,
    "negative_signals": 180,
}

#: The entity kinds `bkb_entities` covers — and only these. `personas`,
#: `pain_points` and `intent_signals` are already typed entity tables with
#: slugs, and `lead_analysis` joins on them, so nothing appears in both
#: registries (05 §5.1a). Two registries for one thing is the failure this
#: scope rule exists to prevent.
BKB_ENTITY_KINDS: tuple[str, ...] = ("competitor", "product", "feature", "tool", "alternative")


class Project(Base):
    """One website being researched. The scoping root for everything below.

    `normalized_url` — scheme+host, lowercased, no trailing slash — is the
    identity, not `website_url`: an operator who pastes `https://Example.com/`
    and later `example.com` means one project both times, and the unique index
    is what makes that true rather than merely intended.
    """

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    website_url = Column(Text, nullable=False)
    normalized_url = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, server_default="active", default="active")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (Index("ux_projects_normalized_url", "normalized_url", unique=True),)

    def __repr__(self):
        return f"<Project {self.id} {self.name}>"


class WebsiteSnapshot(Base):
    """What one fetch of a project's site actually read.

    Separate from `Project` so a re-analysis can compare against the text the
    previous one saw. `content_hash` is the L1 cache key P13 fetches against:
    an unchanged fingerprint within the TTL means zero requests.
    """

    __tablename__ = "website_snapshots"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    url = Column(Text, nullable=False)
    pages_fetched = Column(Integer, nullable=False, server_default="0", default=0)
    extracted_text = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    fetched_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_website_snapshots_project", "project_id"),)

    def __repr__(self):
        return f"<WebsiteSnapshot {self.id} project={self.project_id}>"


class BKB(Base):
    """One generated Business Knowledge Base. Supersede, never overwrite.

    `superseded_at IS NULL` is the current version, which is why the index
    leads with `(project_id, superseded_at)`. Keeping old versions is what makes
    "what did we think last month, and on what evidence?" answerable — and it is
    also what `bkb_evidence`'s CASCADE hangs off, so an evidence row can never
    outlive the claim it supports.
    """

    __tablename__ = "bkb"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    model = Column(String(60), nullable=False)
    prompt_version = Column(Integer, nullable=False)
    prefix_tokens = Column(Integer, nullable=True)  # measured; P15 fills it
    dropped_sections_json = Column(Text, nullable=True)  # omitted from the prefix by budget
    status = Column(
        String(20), nullable=False, server_default="complete", default="complete"
    )  # complete | partial | failed
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    superseded_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_bkb_current", "project_id", "superseded_at"),)

    def __repr__(self):
        return f"<BKB {self.id} project={self.project_id} v{self.version}>"


class BKBSection(Base):
    """One of the 23 sections, versioned independently of the other 22.

    ⚠️ **`payload_json` is NULL for exactly the three keys in
    `BKB_TYPED_SECTION_KEYS`** and NOT NULL for the other twenty. For those
    three the typed table (`personas`, `pain_points`, `intent_signals`) is
    authoritative for content and this row carries section metadata only; a
    second copy here would rot and there would be no way to tell which was
    right. The rule is a `CHECK` in the schema, not a convention — see 05 §5.1b.

    JSON rather than 23 typed tables because sections are read whole, written
    whole, and never filtered by their internal fields. The Pydantic model *is*
    the schema and `prompt_version` records which one applied.
    """

    __tablename__ = "bkb_sections"

    id = Column(Integer, primary_key=True)
    bkb_id = Column(Integer, ForeignKey("bkb.id", ondelete="CASCADE"), nullable=False)
    section_key = Column(String(40), nullable=False)  # one of BKB_SECTION_KEYS
    payload_json = Column(Text, nullable=True)  # NULL iff section_key is typed
    confidence = Column(Float, nullable=True)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    in_prefix = Column(Boolean, nullable=False, server_default="0", default=False)
    edited_by_user = Column(Boolean, nullable=False, server_default="0", default=False)
    status = Column(String(20), nullable=False, server_default="ok", default="ok")  # ok|incomplete
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    last_verified_at = Column(DateTime, nullable=True)
    staleness_days = Column(Integer, nullable=True)  # NULL = never stales; BKB_STALENESS_DAYS
    origin = Column(
        String(20), nullable=False, server_default="website", default="website"
    )  # website | reddit_learned | operator

    __table_args__ = (
        CheckConstraint(
            "(section_key IN ('buyer_personas', 'pain_points', 'buying_signals'))"
            " = (payload_json IS NULL)",
            name="ck_bkb_sections_payload_null_rule",
        ),
        Index("ux_bkb_sections", "bkb_id", "section_key", unique=True),
    )

    def __repr__(self):
        return f"<BKBSection {self.section_key} bkb={self.bkb_id}>"


class Persona(Base):
    """A buyer persona. Backs BKB section 8, and is authoritative for its content.

    Carries **both** `project_id` and `bkb_id` (05 §5.1b). Without `bkb_id`,
    deleting a superseded BKB would cascade its evidence away while leaving the
    persona behind — displayed, and with its provenance silently gone, which is
    worse than either keeping or dropping both.
    """

    __tablename__ = "personas"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    bkb_id = Column(Integer, ForeignKey("bkb.id", ondelete="CASCADE"), nullable=True)
    # The join key the LLM emits. Stable and human-readable, so a prompt can say
    # `pain-attribution-gap` rather than a database integer it has no reason to
    # get right.
    slug = Column(String(60), nullable=False)
    name = Column(String(120), nullable=False)
    job_title = Column(String(160), nullable=True)
    seniority = Column(String(60), nullable=True)
    description = Column(Text, nullable=True)
    goals_json = Column(Text, nullable=True)
    tools_json = Column(Text, nullable=True)
    subreddits_json = Column(Text, nullable=True)
    display_order = Column(Integer, nullable=False, server_default="0", default=0)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    origin = Column(String(20), nullable=False, server_default="website", default="website")

    __table_args__ = (Index("ux_personas_project_slug", "project_id", "slug", unique=True),)

    def __repr__(self):
        return f"<Persona {self.slug} project={self.project_id}>"


class PainPoint(Base):
    """A problem the business solves. Backs BKB section 9.

    `phrases_json` — *how a person phrases this complaint* — is the column the
    pre-score's `pain_phrase` component reads. It is created empty here and
    populated by P14; until then `src.scoring.ABSENT_COMPONENTS` names the
    component absent rather than scoring it zero.
    """

    __tablename__ = "pain_points"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    bkb_id = Column(Integer, ForeignKey("bkb.id", ondelete="CASCADE"), nullable=True)
    slug = Column(String(60), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(Integer, nullable=False, server_default="3", default=3)  # 1..5
    frequency = Column(Integer, nullable=False, server_default="3", default=3)  # 1..5
    phrases_json = Column(Text, nullable=True)
    persona_id = Column(Integer, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    origin = Column(String(20), nullable=False, server_default="website", default="website")

    __table_args__ = (Index("ux_pain_points_project_slug", "project_id", "slug", unique=True),)

    def __repr__(self):
        return f"<PainPoint {self.slug} project={self.project_id}>"


class IntentSignal(Base):
    """A weighted buying signal. Backs BKB section 17.

    `weight` feeds `ConfidenceScorer` in P21 — which is arithmetic over stored
    values, never a model call (R6).
    """

    __tablename__ = "intent_signals"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    bkb_id = Column(Integer, ForeignKey("bkb.id", ondelete="CASCADE"), nullable=True)
    slug = Column(String(60), nullable=False)
    label = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    weight = Column(Float, nullable=False, server_default="0.2", default=0.2)
    tier = Column(
        String(20), nullable=False, server_default="medium", default="medium"
    )  # high | medium | low
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    origin = Column(String(20), nullable=False, server_default="website", default="website")

    __table_args__ = (Index("ux_intent_signals_project_slug", "project_id", "slug", unique=True),)

    def __repr__(self):
        return f"<IntentSignal {self.slug} project={self.project_id}>"


class BKBEntity(Base):
    """A named thing with no typed table: competitor, product, feature, tool,
    alternative — and nothing else. See `BKB_ENTITY_KINDS`.

    `status` and `merged_into_id` exist because entities drift and aliases alone
    do not capture it (06h §7): a competitor acquired by another is neither an
    alias of it nor a separate live entity, and deleting it would orphan every
    evidence row that ever pointed at it.
    """

    __tablename__ = "bkb_entities"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(30), nullable=False)  # one of BKB_ENTITY_KINDS
    slug = Column(String(80), nullable=False)
    canonical_name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    weight = Column(Float, nullable=False, server_default="0.0", default=0.0)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    status = Column(
        String(20), nullable=False, server_default="active", default="active"
    )  # active | merged_into | retired
    merged_into_id = Column(Integer, ForeignKey("bkb_entities.id"), nullable=True)

    __table_args__ = (Index("ux_bkb_entities", "project_id", "kind", "slug", unique=True),)

    def __repr__(self):
        return f"<BKBEntity {self.kind}:{self.slug}>"


class BKBEntityAlias(Base):
    """A surface form of an entity. Resolution tiers 1-3 are lookups over this.

    `alias_norm` — casefolded, punctuation and spacing stripped — carries its
    own non-unique index as well as the composite unique, because the resolver
    queries it without knowing the entity (06e §4).
    """

    __tablename__ = "bkb_entity_aliases"

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("bkb_entities.id", ondelete="CASCADE"), nullable=False)
    alias = Column(String(160), nullable=False)
    alias_norm = Column(String(160), nullable=False)
    source = Column(String(30), nullable=False)  # site|casing|misspelling|acronym|domain|confirmed
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ux_bkb_alias_norm", "entity_id", "alias_norm", unique=True),
        Index("ix_bkb_alias_lookup", "alias_norm"),
    )

    def __repr__(self):
        return f"<BKBEntityAlias {self.alias_norm} entity={self.entity_id}>"


class BKBLink(Base):
    """A typed edge between two knowledge objects.

    Endpoints are `(kind, row id)` pairs so one table can link personas, pains,
    signals and entities without five nullable foreign-key columns. The cost is
    real and is paid knowingly: **the endpoints have no referential integrity**,
    so whichever phase writes a link owns checking that its targets exist.
    """

    __tablename__ = "bkb_links"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    relation = Column(String(40), nullable=False)  # persona_has_pain|pain_answered_by|...
    src_kind = Column(String(30), nullable=False)  # persona|pain_point|intent_signal|bkb_entity
    src_id = Column(Integer, nullable=False)
    dst_kind = Column(String(30), nullable=False)
    dst_id = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index(
            "ux_bkb_links",
            "project_id",
            "relation",
            "src_kind",
            "src_id",
            "dst_kind",
            "dst_id",
            unique=True,
        ),
        Index("ix_bkb_links_src", "src_kind", "src_id"),
    )

    def __repr__(self):
        return f"<BKBLink {self.src_kind}:{self.src_id} -{self.relation}-> {self.dst_kind}:{self.dst_id}>"


class BKBEvidence(Base):
    """Where a claim came from. Every BKB claim has at least one of these.

    `lead_id` / `comment_id` are what make Reddit-learned knowledge auditable:
    *"why does the BKB think this objection exists?"* resolves to real threads
    rather than to a count.

    Two constraints span rows and are therefore application-level, not `CHECK`s:
    a `source_type='ai_inference'` row has **no** quote and no source reference
    — there is nothing to point at and a quote would be a fabrication, which is
    why `quote` is nullable — and zero evidence rows for a claim is a validation
    failure rather than a quiet default.
    """

    __tablename__ = "bkb_evidence"

    id = Column(Integer, primary_key=True)
    bkb_id = Column(Integer, ForeignKey("bkb.id", ondelete="CASCADE"), nullable=False)
    subject_kind = Column(String(30), nullable=False)  # bkb_section|persona|pain_point|bkb_entity
    subject_id = Column(Integer, nullable=False)
    quote = Column(Text, nullable=True)  # a literal substring of the snapshot text
    source_url = Column(String(500), nullable=True)
    snapshot_id = Column(
        Integer, ForeignKey("website_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    source_type = Column(
        String(20), nullable=False, server_default="website", default="website"
    )  # website | reddit_post | reddit_comment | operator | ai_inference
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="SET NULL"), nullable=True)
    confirmed_by = Column(String(80), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_bkb_evidence_subject", "subject_kind", "subject_id"),
        Index("ix_bkb_evidence_source", "source_type"),
    )

    def __repr__(self):
        return f"<BKBEvidence {self.subject_kind}:{self.subject_id} from {self.source_type}>"


class BKBSuggestion(Base):
    """A learned proposal awaiting operator review. **Never auto-applied.**

    `distinct_groups` is what makes the 06e §4.2 threshold checkable: three
    mentions inside one dedup group is one person saying a thing three times,
    which is not evidence of anything.
    """

    __tablename__ = "bkb_suggestions"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(30), nullable=False)  # alias | pain_phrase | entity
    payload_json = Column(Text, nullable=False)
    evidence_json = Column(Text, nullable=False)  # lead ids and spans behind the proposal
    occurrences = Column(Integer, nullable=False, server_default="1", default=1)
    status = Column(
        String(20), nullable=False, server_default="pending", default="pending"
    )  # pending | accepted | rejected
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    decided_at = Column(DateTime, nullable=True)
    pattern_kind = Column(String(30), nullable=True)
    distinct_groups = Column(Integer, nullable=False, server_default="1", default=1)

    __table_args__ = (Index("ix_bkb_suggestions_pending", "project_id", "status"),)

    def __repr__(self):
        return f"<BKBSuggestion {self.kind} project={self.project_id} {self.status}>"


# ⚠️ NEITHER `bkb_embeddings` NOR `bkb_embedding_meta` has a model here, and
# that is deliberate. `bkb_embeddings` is a `vec0` virtual table created only
# when the `sqlite-vec` extension loads; declaring it on `Base` would make
# `create_all()` emit a plain `CREATE TABLE` for it on every host, turning an
# optional recall improvement into a hard dependency — exactly what 05 §5.1a
# refuses. `bkb_embedding_meta` *is* an ordinary table, but the migration
# creates the two together or not at all: a meta table without the vectors it
# indexes is a table of pointers into nothing. Modelling one and not the other
# would let `create_all()` produce a schema the migration cannot produce.
#
# The semantic layer's presence is reported at `/api/health` as `semantic_layer`
# and by `scripts/check_schema.py`, so its absence is visible rather than
# something a reader has to infer from a missing table.
