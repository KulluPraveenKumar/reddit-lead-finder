import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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
    score = Column(Integer, default=0)
    num_comments = Column(Integer, default=0)
    intent_score = Column(Float, default=0.0)
    matched_keywords = Column(Text, default="")
    status = Column(String(20), default="new", index=True)
    created_utc = Column(DateTime, nullable=False)
    scraped_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_leads_intent_score", "intent_score"),
        Index("ix_leads_scraped_at", "scraped_at"),
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
