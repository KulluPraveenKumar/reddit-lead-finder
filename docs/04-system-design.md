# 04 — System Design

Component-level design. Interfaces are specified precisely enough that implementation is
transcription, not invention. Signatures shown are the contract; bodies are illustrative.

---

## 1. Run state machine

### 1.1 States

```python
# src/orchestration/states.py
class RunState(str, Enum):
    PENDING                   = "pending"
    PROFILING                 = "profiling"                    # website → profile/ICP/personas/pains/vocab
    DISCOVERING               = "discovering"                  # subreddit candidates + validation + rank
    AWAITING_SUBREDDIT_REVIEW = "awaiting_subreddit_review"    # ◄ GATE 1
    GENERATING_KEYWORDS       = "generating_keywords"
    AWAITING_KEYWORD_REVIEW   = "awaiting_keyword_review"      # ◄ GATE 2
    AWAITING_OPTIONS          = "awaiting_options"             # scraping option selection
    SCRAPING                  = "scraping"
    ANALYZING                 = "analyzing"
    COMPLETE                  = "complete"
    FAILED                    = "failed"
    CANCELLED                 = "cancelled"
```

### 1.2 Legal transitions

```python
TRANSITIONS: dict[RunState, set[RunState]] = {
    PENDING:                   {PROFILING, CANCELLED, FAILED},
    PROFILING:                 {DISCOVERING, FAILED, CANCELLED},
    DISCOVERING:               {AWAITING_SUBREDDIT_REVIEW, FAILED, CANCELLED},
    AWAITING_SUBREDDIT_REVIEW: {GENERATING_KEYWORDS, DISCOVERING, CANCELLED},   # re-discover allowed
    GENERATING_KEYWORDS:       {AWAITING_KEYWORD_REVIEW, FAILED, CANCELLED},
    AWAITING_KEYWORD_REVIEW:   {AWAITING_OPTIONS, GENERATING_KEYWORDS, CANCELLED},
    AWAITING_OPTIONS:          {SCRAPING, CANCELLED},
    SCRAPING:                  {ANALYZING, FAILED, CANCELLED},
    ANALYZING:                 {COMPLETE, FAILED, CANCELLED},
    COMPLETE:                  {ANALYZING},      # re-analysis of an existing run
    FAILED:                    {PENDING},        # full retry
    CANCELLED:                 set(),
}

def assert_transition(current: RunState, target: RunState) -> None:
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"{current} -> {target}")
```

**Design notes.**
- The two `AWAITING_*_REVIEW` states have **no timeout**. A run may sit there indefinitely; that is
  the point of a gate.
- The backward edges (`AWAITING_SUBREDDIT_REVIEW → DISCOVERING`) exist so the user can say
  "regenerate these, I don't like them" without starting over.
- `COMPLETE → ANALYZING` exists so a prompt-version bump can re-analyse a finished run's leads
  without re-scraping.
- Every transition is written inside the same DB transaction that writes its cause, and appends a
  `run_events` row.

### 1.3 RunService interface

```python
class RunService:
    def create(self, project_id: int, options: RunOptions) -> Run: ...
    def transition(self, run_id: int, target: RunState, *, reason: str = "") -> Run: ...
    def approve_subreddits(self, run_id: int, subreddit_ids: list[int]) -> Run: ...
    def approve_keywords(self, run_id: int, keyword_ids: list[int]) -> Run: ...
    def set_options(self, run_id: int, options: RunOptions) -> Run: ...
    def cancel(self, run_id: int, reason: str) -> Run: ...
    def retry(self, run_id: int) -> Run: ...
    def progress(self, run_id: int) -> RunProgress: ...
```

`RunProgress` is what the UI polls:

```python
@dataclass
class RunProgress:
    state: RunState
    stage_label: str          # human string, e.g. "Scraping r/SaaS (3 of 7)"
    percent: int              # 0-100, derived from job counts per stage
    jobs_total: int
    jobs_done: int
    jobs_failed: int
    leads_found: int
    llm_cost_usd: float
    started_at: datetime
    updated_at: datetime
    last_error: str | None
```

---

## 2. Job queue

### 2.1 Schema-backed queue semantics

`jobs` is a table (full DDL in [05-database-plan.md](05-database-plan.md)). The queue implements
**claim-with-lease**:

```python
class JobQueue:
    def enqueue(self, job_type: str, *, run_id: int | None, payload: dict,
                priority: int = 100, available_at: datetime | None = None) -> Job: ...

    def claim(self, worker_id: str, lease_seconds: int = 900) -> Job | None:
        """
        Atomically select the highest-priority queued job whose available_at <= now,
        set state=running, worker_id, lease_expires_at = now + lease_seconds,
        and return it. Returns None when the queue is empty.
        """

    def heartbeat(self, job_id: int, extend_seconds: int = 900) -> None: ...
    def complete(self, job_id: int, result: dict | None = None) -> None: ...
    def fail(self, job_id: int, error: str, *, retryable: bool = True) -> None: ...
    def reclaim_expired(self) -> int:
        """Return leases whose lease_expires_at < now to state=queued. Called each worker tick."""
```

### 2.2 Atomic claim on SQLite

SQLite has no `SELECT ... FOR UPDATE SKIP LOCKED`. With a single worker this is trivially safe, but
the implementation must still be correct if a second worker is ever started:

```sql
BEGIN IMMEDIATE;                       -- take the write lock up front
SELECT id FROM jobs
 WHERE state = 'queued' AND available_at <= :now
 ORDER BY priority ASC, id ASC
 LIMIT 1;
UPDATE jobs
   SET state='running', worker_id=:wid, lease_expires_at=:exp, started_at=:now,
       attempts = attempts + 1
 WHERE id = :id AND state = 'queued';   -- guard clause: 0 rows updated ⇒ lost the race, retry
COMMIT;
```

`BEGIN IMMEDIATE` plus the `AND state='queued'` guard makes the claim safe under any number of
workers. This is why we can defer multi-worker support without designing ourselves into a corner.

### 2.3 Retry policy

```python
MAX_ATTEMPTS = {"analyze_website": 3, "discover_subreddits": 3, "generate_keywords": 3,
                "scrape_subreddit": 5, "scrape_comments": 5, "enrich_leads": 3,
                "finalize_run": 3, "maintenance": 2}

def backoff_seconds(attempts: int) -> float:
    return min(600, (2 ** attempts) * 5) * random.uniform(0.8, 1.2)   # jittered, capped at 10 min
```

On `fail(retryable=True)` with `attempts < MAX_ATTEMPTS[job_type]`: set `state='queued'`,
`available_at = now + backoff_seconds(attempts)`. Otherwise `state='failed'`, and the run
transitions to `FAILED` unless the job type is marked non-fatal (comment scraping and per-item
analysis are non-fatal — see AD-9 in [03-architecture.md](03-architecture.md)).

### 2.4 Job types

| `job_type` | Payload | Handler | Fatal on exhaustion? |
|---|---|---|---|
| `analyze_business` | `{run_id}` | `handlers/website.py` — **one** consolidated AI call | Yes |
| `validate_subreddits` | `{run_id}` | `handlers/discovery.py` — live validation + rank, **no AI** | Yes |
| `scrape_subreddit` | `{run_id, subreddit, mode, keyword_ids, limits}` | `handlers/scrape.py` | No — partial results are useful |
| `scrape_comments` | `{run_id, lead_ids[]}` | `handlers/comments.py` | No |
| `enrich_leads` | `{run_id}` | `handlers/enrich.py` — runs gate → dedup → batch → audit | No |
| `finalize_run` | `{run_id}` | `handlers/finalize.py` | Yes |
| `maintenance` | `{}` | `handlers/maintenance.py` | No |

There is deliberately **no** `submit_batch` / `poll_batch` pair. DeepSeek has no batch endpoint, so
`enrich_leads` runs a bounded concurrency pool inside a single job
([§6.5](#65-bulk-enrichment--bounded-concurrency)). This removes an entire job type, a polling
loop, four result states, and a 24-hour expiry path from the design.

---

## 3. Worker

```python
class Worker:
    def __init__(self, queue: JobQueue, registry: dict[str, Handler],
                 poll_interval: float = 2.0, worker_id: str | None = None): ...

    def run_forever(self) -> None:
        while not self._stop.is_set():
            self.queue.reclaim_expired()
            job = self.queue.claim(self.worker_id)
            if job is None:
                self._stop.wait(self.poll_interval)
                continue
            self._execute(job)

    def _execute(self, job: Job) -> None:
        handler = self.registry[job.job_type]
        with session_scope() as s, heartbeat_thread(self.queue, job.id):
            try:
                result = handler(s, job)
                self.queue.complete(job.id, result)
            except RetryableError as e:
                self.queue.fail(job.id, str(e), retryable=True)
            except Exception as e:
                log.exception("job_failed", job_id=job.id)
                self.queue.fail(job.id, repr(e), retryable=False)
```

**Design notes.**
- A heartbeat thread extends the lease every `lease_seconds / 3` so long scrape jobs don't get
  reclaimed mid-flight.
- `session_scope()` commits on success and rolls back on exception, so a handler that throws
  half-way leaves no partial writes — except the deliberate incremental commits inside scrape
  handlers, which use their own nested scopes per page (preserving today's per-subreddit commit
  behaviour that survives a mid-run crash).
- Graceful shutdown: `SIGTERM`/`SIGINT` sets `_stop`; the in-flight job finishes; the lease is
  released.

---

## 4. Proxy service

Full specification in [08-proxy-service.md](08-proxy-service.md). Interface summary:

```python
@dataclass(frozen=True)
class ProxyEndpoint:
    host: str; port: int; username: str; password: str
    @property
    def key(self) -> str:  return f"{self.host}:{self.port}"        # the ONLY form ever logged
    @property
    def url(self) -> str:  return f"http://{self.username}:{self.password}@{self.host}:{self.port}"

class ProxyManager:
    def acquire(self, *, session_key: str | None = None) -> ProxyLease: ...
    def release(self, lease: ProxyLease, *, ok: bool, status: int | None, latency_ms: float) -> None: ...
    def blacklist(self, key: str, seconds: int, reason: str) -> None: ...
    def health_check_all(self) -> dict[str, bool]: ...
    def stats(self) -> list[ProxyStats]: ...
    def healthy_count(self) -> int: ...
```

```python
class ProxiedHTTPClient:
    def get(self, url: str, *, session_key: str | None = None,
            timeout: tuple[float, float] | None = None,
            headers: dict | None = None,
            use_cache: bool = True,
            max_attempts: int | None = None) -> Response: ...
```

`session_key` is the sticky-session handle: passing the same key returns the same proxy while it is
healthy. Used to keep one subreddit's whole pagination walk on one IP.

---

## 5. Reddit client (refactored)

**Public API unchanged.** Internals:

```python
class RedditClient:
    def __init__(self, config=None, http: ProxiedHTTPClient | None = None):
        self.http = http or build_default_client(config)

    def _get(self, url: str, *, session_key: str | None = None) -> str | None:
        try:
            resp = self.http.get(url, session_key=session_key)
            return resp.text
        except ProxyExhaustedError:
            raise                                     # fatal, propagates to the job handler
        except ScraperError as e:
            log.warning("reddit_get_failed", url=redact(url), error=str(e))
            return None                               # preserves existing caller contract
```

### 5.0 `get_feed` — the seventh method *(P5, additive)*

```python
def get_feed(self, subreddits, *, sort="new", limit=None, query=None) -> list[dict]:
    """One Atom feed -> posts in `_extract_post`'s shape. AD-2: additive only."""
```

Deliberately **not** paginated, unlike every other method here: a feed has no `next` link, carries
100 items in one response, and P0 measured the budget at one request per ~60 s **per IP**, so a
second request costs a minute. Many subreddits go in one multireddit URL for the same reason.

Routing is `request_class="rss"` → always direct ([R18](ARCHITECTURE_FREEZE.md)) and
`allow_cache=False` ([28 D5](28-discovery-redesign.md)). Parsing is
`src/discovery/feed_parser.py`; a malformed feed raises `FeedParseError` while a transport failure
returns `[]`, and the two must stay distinguishable. Field mapping and the four measured differences
from the HTML paths: [07 §2a](07-scraping-pipeline.md).

> ◐ The `_get` sketch above is the pre-P4 design, not the shipped signature. The shipped method is
> `_get(self, url, *, expect_selector=None)` and it **swallows** `ProxyExhaustedError`, returning
> `None`. Making it raise is P6's, with the handler that maps the exception to a run outcome.

### 5.1 Pagination fix

```python
def _next_url(self, soup: BeautifulSoup) -> str | None:
    link = soup.select_one("span.nextprev a[rel='nofollow next']")   # works for listing AND search
    if not link:
        return None
    href = link.get("href", "")
    if href.startswith("/"):
        href = f"{BASE_URL}{href}"
    return href or None
```

Both `_parse_listing` and `_parse_search_results` return `(posts, next_url)` instead of
`(posts, after)`, and the loops follow the URL directly. This fixes
[00 §4.1](00-current-state.md) and preserves the `count=` parameter.

### 5.2 Query encoding fix

```python
from urllib.parse import urlencode, quote_plus

def search_posts(self, query, subreddit=None, limit=50, sort="new", t=None):
    params = {"q": query, "sort": sort}
    if subreddit:
        params["restrict_sr"] = "on"
    if t:
        params["t"] = t                     # hour|day|week|month|year|all
    base = f"{BASE_URL}/r/{subreddit}/search" if subreddit else f"{BASE_URL}/search"
    url = f"{base}?{urlencode(params, quote_via=quote_plus)}"
```

New optional `sort` and `t` parameters are **keyword-only with existing defaults**, so all current
call sites are unaffected. `t` is what implements the run's time-window option.

### 5.3 Score semantics fix

`_extract_search_post` returns `"score": None` instead of `0`. `LeadScorer.score_post` treats
`upvotes is None` as "unknown" and omits the upvote term from the total **and** from the effective
threshold, rather than scoring it as zero. This removes the scale mismatch in
[00 §4.3](00-current-state.md) without changing any score for a listing-sourced lead.

---

## 6. AI subsystem

Full design in [06a — AI Service Layer](06a-ai-service-layer.md) and
[06b — DeepSeek Integration](06b-deepseek-optimization.md). This section covers the interfaces the
rest of the system binds to.

### 6.1 The single entry point

```python
class AIService:
    def __init__(self, provider: LLMProvider, prompts: PromptManager,
                 context: ContextBuilder, cache: ResponseCache,
                 cost: CostTracker, pool: ConcurrencyPool,
                 limiter: RateLimiter, metrics: AIMetrics): ...

    # FOUR model-invoking methods — see 06a §1.
    def analyze_business(self, site: ExtractedSite,
                         signals: LocalSiteSignals) -> BusinessIntelligence: ...
    def regenerate_section(self, key: SectionKey, ctx: ProjectContext) -> BaseModel: ...
    def enrich_batch(self, items, ctx, on_result) -> BatchReport: ...
    def suggest_outreach(self, lead, analysis, ctx) -> OutreachSuggestion: ...   # lazy
    # Operations — no model call except test_connection
    def test_connection(self) -> ConnectionResult: ...
    def estimate_cost(self, plan: WorkloadPlan) -> CostEstimate: ...
```

**No caller anywhere passes a model name, a prompt, a temperature, or a token count**, and no caller
reaches `AIService` without passing `PreAIGate` first ([06c](06c-local-first-pipeline.md)). Both
enforced by grep tests ([03 §2](03-architecture.md)).

### 6.2 The provider boundary

```python
class LLMProvider(ABC):
    name: str
    default_model: str

    @abstractmethod
    def chat(self, req: ChatRequest, *, timeout: tuple[float, float]) -> ChatResponse: ...
    @abstractmethod
    def validate_credentials(self) -> ConnectionResult: ...
    @abstractmethod
    def price_table(self) -> PriceTable: ...
    @abstractmethod
    def classify_error(self, exc_or_status) -> AIErrorClass: ...

    supports_prefix_caching: bool       # DeepSeek: True (implicit, no marker)
    supports_schema_enforcement: bool   # DeepSeek: False (JSON syntax only)
    supports_batch_api: bool            # DeepSeek: False
    cache_chunk_tokens: int             # DeepSeek: 64
```

The capability flags are how the service adapts without knowing the vendor:

| Flag | `False` behaviour | `True` behaviour |
|---|---|---|
| `supports_batch_api` | `enrich_batch` uses the concurrency pool | Uses the provider's batch endpoint |
| `supports_schema_enforcement` | Client-side repair ladder engaged | Ladder bypassed; server validates |
| `supports_prefix_caching` | Prefix padding skipped; estimator drops the cache assumption | `ContextBuilder` pads to `cache_chunk_tokens` |

### 6.3 The unified call path

All four model-invoking methods funnel through one internal method, so caching, dedup, retry,
repair, cost, and metrics are implemented exactly once.

```python
def _call(self, stage: str, *, context: ProjectContext | None, variables: dict,
          output_model: type[BaseModel], max_tokens: int,
          run_id=None, project_id=None) -> BaseModel:

    rendered = self.prompts.render(stage, context=context, variables=variables)
    key = sha256(provider.name, model, stage, rendered.version,
                 rendered.system, rendered.user)

    if hit := self.cache.get(key):                       # layer 2: response cache
        self.metrics.inc("ai.cache_hit", stage=stage)
        return output_model.model_validate_json(hit)

    with self.dedupe.guard(key):                         # layer 4: in-flight guard
        self.cost.check_budget(run_id, self._estimate(rendered, max_tokens))
        self.limiter.acquire(estimated_tokens)

        for attempt in range(1, MAX_REPAIR + 2):
            resp = self._chat_with_transport_retry(rendered, max_tokens)
            self._record(resp, stage, rendered.version, run_id, project_id)

            outcome, obj_or_err = self.repairer.evaluate(resp, output_model)
            if outcome is OK:
                self.cache.put(key, obj_or_err)
                return obj_or_err
            rendered = self.repairer.amend(rendered, outcome, obj_or_err)   # 3-branch ladder

        raise SchemaValidationError(stage)
```

Two retry loops, deliberately distinct:

- **Transport retry** (`_chat_with_transport_retry`) — 429/500/503/timeout. Backoff, jitter, and on
  429/503 it halves the concurrency ceiling. Non-retryable classes (401, 402, 400, 422) raise
  immediately.
- **Repair retry** (the `for` loop) — empty content, invalid JSON, schema violation. Each amends the
  prompt differently; empty-content perturbation deliberately forfeits the cache hit for that call.

### 6.4 The frozen prefix

```python
system = (
    ROLE_TASK_RULES[stage]      # identical for this stage, every project
    + RUBRIC[stage]             # identical for this stage
    + JSON_SHAPE[stage]         # identical for this stage — vendor requirement
    + context_block             # identical for this project, sorted JSON, chunk-padded
)
user = render_item(variables)   # the ONLY varying part
```

**Enforced invariants**, each a test:

- `context_block` built with `json.dumps(..., sort_keys=True, separators=(",",":"))`
- No timestamp, UUID, run id, lead id, or counter anywhere in `system`
- Every list sorted by `slug`
- Padded to a `cache_chunk_tokens` boundary
- `prefix_hash` constant for the life of a run — a change raises `PrefixDriftError`
- `prompt_cache_hit_tokens > 0` from the second call; a persistent zero raises a **loud** warning
  into `run_events` because it means the input bill is up to 50× the estimate

### 6.5 Bulk enrichment — bounded concurrency

DeepSeek has no batch endpoint ([02 §6.3a](02-research-findings.md)).

```python
def enrich_batch(self, items, ctx, on_result) -> BatchReport:
    if self.provider.supports_batch_api:
        return self._provider_batch(items, ctx, on_result)      # future providers

    batches = chunk(items, self.batch_size)        # default 8 — a MEASURED ceiling
    with ThreadPoolExecutor(max_workers=self.pool.current) as ex:
        futures = {ex.submit(self._analyze_batch, b, ctx): b for b in batches}
        for fut in as_completed(futures):
            batch = futures[fut]                   # ← level 1: future → batch
            results = fut.result()                 #   level 2: echoed id → item
            if len(results) != len(batch):         #   length mismatch = batch failure
                self._split_and_retry(batch, ex, on_result); continue
            try:
                on_result(item, fut.result())
            except InsufficientBalanceError:
                self.pool.drain(); raise           # stop cleanly, preserve completed work
            except BudgetExceededError:
                self.pool.drain(); raise
            except AIError as e:
                on_result(item, Failure(e))        # isolate: one item's failure is not the run's
```

`futures[fut]` is the correctness mechanism that replaces `custom_id`. **Attribution by array
position is the defect class this design must never permit**, and it has a dedicated blocking test
that returns results in shuffled completion order.

**Adaptive ceiling:** sustained 429/503, or p95 latency past a threshold, halves `pool.current`
(floor 1); a clean window steps it back up (ceiling 16). Because DeepSeek slows rather than refuses,
latency is the primary signal.

### 6.6 Credentials

```python
class CredentialStore:
    def set_key(self, provider: str, raw_key: str, *, validate: bool = True) -> ConnectionResult: ...
    def get_key(self, provider: str) -> str | None: ...          # internal use only
    def fingerprint(self, provider: str) -> str | None: ...      # "sk-…a3f9"
    def status(self, provider: str) -> CredentialStatus: ...     # state + last validation
    def mark_invalid(self, provider: str, reason: str) -> None: ...
    def clear(self, provider: str) -> None: ...
```

- Fernet-encrypted with a data key derived from `APP_SECRET_KEY` via HKDF; ciphertext lives in the
  **existing** `settings` table under `ai.provider.<name>.api_key_enc`.
- **No endpoint ever returns the plaintext.** Settings shows a masked fingerprint plus a SHA-256
  digest for change detection. There is no "reveal" action.
- `set_key` validates before persisting unless explicitly forced.
- A 401 at any point calls `mark_invalid`, which surfaces on Settings and `/health`.
- `APP_SECRET_KEY` missing at startup → AI disabled with a clear message; scraping unaffected.

### 6.7 Stage configuration

| Stage | `max_tokens` | Temp | Context received |
|---|---:|---:|---|
| `website_analysis` | 4096 | 0.4 | Site text |
| `icp_generation` | 4096 | 0.4 | BusinessProfile |
| `persona_generation` | 4096 | 0.4 | Profile + ICP |
| `pain_extraction` | 4096 | 0.4 | Profile + ICP |
| `buying_intent` | 3072 | 0.4 | Profile + ICP + pains |
| `reddit_vocabulary` | 3072 | 0.4 | Profile + ICP + personas + pains |
| `subreddit_recommendation` | 3072 | 0.4 | ICP + personas + vocabulary |
| `keyword_generation` | 3072 | 0.4 | Vocabulary + pains + one subreddit |
| `post_analysis` | 1536 | 0.2 | **Full frozen context** + one post |
| `comment_analysis` | 1024 | 0.2 | Full frozen context + comment + parent title |
| `opportunity_summary` | 1024 | 0.3 | Context + lead + analysis |
| `outreach_suggestion` | 1024 | 0.3 | Context + lead + analysis |

Only the two enrichment stages carry the full context — and those are exactly the stages where it is
cached at $0.0028/M, so the large prefix is nearly free.

---

## 7. Subreddit discovery

```python
class DiscoveryService:
    def discover(self, project: Project) -> list[SubredditCandidate]:
        cands: dict[str, SubredditCandidate] = {}
        self._merge(cands, self._from_llm(project),      channel="llm")
        self._merge(cands, self._from_search(project),   channel="search")
        self._merge(cands, self._from_sidebars(cands),   channel="sidebar")
        validated = [c for c in cands.values() if self.validator.validate(c)]
        return self.ranker.rank(validated, project)
```

**Channel 2 (search harvest)** is the empirical backbone:

```python
def _from_search(self, project) -> list[SubredditCandidate]:
    counts = Counter(); totals = Counter()
    for term in project.vocabulary.core_terms[:12]:            # bounded
        posts = self.reddit.search_posts(term, subreddit=None, limit=50, sort="relevance")
        for p in posts:
            if p["subreddit"]:
                counts[p["subreddit"].lower()] += 1
    # hit_density = counts[sub] / sum(counts.values())
```

**Channel 3 (sidebar graph)** parses `a[href^='/r/']` inside `div.titlebox .md` of already-validated
subreddits, one hop only.

**Validator** — the hallucination filter:

```python
def validate(self, c: SubredditCandidate) -> bool:
    info = self.reddit.get_subreddit_info(c.name)
    if info is None:                       c.reject("not_found");    return False
    if info["subscribers"] < MIN_SUBS:     c.reject("too_small");    return False
    if self._is_private_or_banned(info):   c.reject("inaccessible"); return False
    c.subscribers  = info["subscribers"]
    c.description  = info["description"]
    return True
```

Every rejection reason is persisted so the UI can show "12 proposed, 9 validated, 3 rejected
(2 not found, 1 too small)" — which is both a trust signal and the hallucination-rate metric.

**Ranker** implements the formula from [02 §5.2](02-research-findings.md), storing all five
components on the row.

---

## 8. Scraping engine

```python
class BaseScraper:
    def run(self, session, ctx: ScrapeContext) -> ScrapeReport: ...

@dataclass
class ScrapeContext:
    run_id: int
    project_id: int | None
    subreddit: str
    mode: Literal["listing", "search"]
    queries: list[str]
    limit_per_query: int
    time_window: str | None          # old.reddit `t` param
    fetch_comments: bool
    max_comments_per_post: int
    min_score: float                 # qualification threshold
```

### 8.1 Batched dedup (kills the N+1 from [00 §4.4](00-current-state.md))

```python
def _filter_new(self, session, posts: list[dict]) -> list[dict]:
    ids = [p["id"] for p in posts]
    existing = set(
        session.execute(select(Lead.reddit_id).where(Lead.reddit_id.in_(ids))).scalars()
    )
    return [p for p in posts if p["id"] not in existing]
```

One query per page of 25 instead of 25 queries.

### 8.2 Comment scraper

```python
class CommentScraper(BaseScraper):
    def run(self, session, ctx) -> ScrapeReport:
        for lead in self._candidate_leads(session, ctx):
            html = self.reddit._get(lead.url, session_key=f"sub:{lead.subreddit}")
            if not html: continue
            comments = self.reddit._parse_comments(html)[: ctx.max_comments_per_post]
            self._backfill_score(session, lead, html)          # fixes NULL search score
            for c in comments:
                if self._prefilter(c):
                    session.add(Comment(lead_id=lead.id, project_id=ctx.project_id, **c))
            session.commit()
```

Candidate selection is deliberately narrow — comments are the most expensive collection step
(1 request per post, no pagination reuse). Default: posts whose keyword score already qualifies
**and** whose `num_comments >= 3`, capped at `max_comment_posts_per_run` (default 100).

### 8.3 Ordering determinism fix

`main.py` and `routes.py` currently disagree on scraper order ([00 §4.10](00-current-state.md)).
Both are changed to the canonical order **subreddit → keyword → user**, and a constant
`SCRAPER_ORDER` in `src/scrapers/__init__.py` becomes the single definition both import.

---

## 9. Hybrid confidence engine

Replaces the keyword-dominant scoring of the original application. **Five classes of signal feed one
deterministic function.** The AI contributes judgement; Python contributes arithmetic.

```
  RULE-BASED SIGNALS          AI SIGNALS (DeepSeek)         REDDIT METRICS
  ┌────────────────────┐   ┌────────────────────────┐   ┌──────────────────┐
  │ keyword matches    │   │ buying_intent (5-stage)│   │ upvotes          │
  │ negative terms     │   │ matched pain slugs     │   │ comment count    │
  │ subreddit fit      │   │ matched signal slugs   │   │ subreddit size   │
  │ structural noise   │   │ icp_match (4-level)    │   └────────┬─────────┘
  │ (legacy LeadScorer)│   │ persona match          │            │
  └─────────┬──────────┘   │ urgency · sentiment    │            │
            │              │ competitor mention     │            │
            │              │ opportunity_score 0-10 │            │
            │              └───────────┬────────────┘            │
            │                          │                         │
            │      RECENCY ────────────┼──────────── ENGAGEMENT ─┤
            │      age of the post     │      votes × comments   │
            │                          │                         │
            └──────────────────────────┼─────────────────────────┘
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  ConfidenceScorer — pure Python          │
                    │  weighted · clamped · penalised          │
                    │  every component persisted for the UI    │
                    └──────────────────┬───────────────────────┘
                                       ▼
                            confidence_score  0–100
```

```python
class ConfidenceScorer:
    """The AI emits categoricals; this turns them into a number.
    Deterministic, re-runnable with zero API calls, fully explainable."""

    def score(self, lead, analysis: LeadAnalysis | None,
              project: Project, weights: ScoreWeights) -> ConfidenceBreakdown:
        a = analysis
        c = {
            # ── AI signals ───────────────────────────────────────────────
            "intent":      INTENT_VALUE[a.buying_intent] if a else 0.0,
            "pain_match":  min(1.0, len(a.matched_pain_slugs) / 3) if a else 0.0,
            "signals":     min(1.0, sum(project.signal_weight(s)
                                        for s in a.matched_signal_slugs)) if a else 0.0,
            "icp_match":   ICP_VALUE[a.icp_match] if a else 0.0,
            "persona":     1.0 if a and a.persona_slug else 0.0,
            "urgency":     URGENCY_VALUE[a.urgency] if a else 0.0,
            "ai_opinion":  (a.opportunity_score / 10) if a else 0.0,
            # ── rule-based signals (legacy, preserved) ───────────────────
            "keyword":     min(1.0, (lead.intent_score or 0) / 50),
            "subreddit":   project.subreddit_fit(lead.subreddit),
            # ── Reddit metrics ───────────────────────────────────────────
            "engagement":  self._engagement(lead.score, lead.num_comments),   # None-safe
            # ── recency ──────────────────────────────────────────────────
            "recency":     self._recency(lead.created_utc),
        }
        total = 100 * sum(weights[k] * v for k, v in c.items())
        total *= self._penalties(lead, a)     # negative terms, deleted author, competitor-only
        return ConfidenceBreakdown(
            total=round(min(100.0, max(0.0, total)), 2),
            components=c,
            has_ai=a is not None,
        )
```

### 9.1 Default weights

Stored in `settings`, editable in the UI, and they must sum to 1.0 (validated on save).

| Class | Component | Weight | Rationale |
|---|---|---:|---|
| **AI** | `intent` | 0.22 | The strongest single predictor |
| **AI** | `pain_match` | 0.14 | Relevance to what we actually sell |
| **AI** | `signals` | 0.12 | Explicit buying language |
| **AI** | `icp_match` | 0.10 | Right company, not just right topic |
| **AI** | `persona` | 0.07 | Right person |
| **AI** | `urgency` | 0.05 | Timeline pressure |
| **AI** | `ai_opinion` | 0.05 | The model's holistic read — deliberately small |
| **Rules** | `keyword` | 0.10 | Preserves the signal that produced 459 usable leads |
| **Rules** | `subreddit` | 0.03 | The gate already filtered subreddits |
| **Metrics** | `engagement` | 0.05 | Weak but non-zero |
| **Recency** | `recency` | 0.07 | A two-year-old thread is not a lead |
| | | **1.00** | AI 0.75 · rules 0.13 · metrics 0.05 · recency 0.07 |

`ai_opinion` is capped at **0.05** on purpose. The model's own 0–10 gut read is a useful tiebreak
but it is the least interpretable input, and letting it dominate would reintroduce exactly the
black-box scoring this design exists to avoid.

`INTENT_VALUE = {unaware: 0.0, problem_aware: 0.35, solution_aware: 0.6, evaluating: 0.85, ready_to_buy: 1.0}`
`ICP_VALUE = {none: 0.0, weak: 0.3, partial: 0.65, strong: 1.0}`
`URGENCY_VALUE = {none: 0.0, low: 0.25, medium: 0.5, high: 0.8, critical: 1.0}`

### 9.2 Degradation without AI

With the AI signals absent (no key, out of balance, over budget, or `ai.enabled: false`), the seven
AI components are 0.0 and the remaining weight (0.25) still produces a usable ordering from keyword
score, subreddit fit, engagement, and recency.

**`ConfidenceBreakdown.has_ai` records which mode produced the score**, so the UI can show
*"scored without AI"* rather than implying an enriched result. A run must never present a
degraded score as a full one.

### 9.3 Properties (property-tested)

- Output always in `[0, 100]`, for every input including all-None
- A lead with no analysis still scores — never NULL after scoring has run
- Changing weights and rescoring requires **zero** API calls and completes in < 2 s for 10,000 leads
- Every component is persisted, so the UI breakdown is stored data, not a re-derivation
- Weights that do not sum to 1.0 are rejected at save
- Re-scoring the same inputs twice yields the identical number

---

## 10. Configuration resolution

```python
# src/settings.py
def get(key: str, default=None, cast=str):
    #  1. os.environ[key.upper()]
    #  2. settings table row
    #  3. config.yaml dotted path
    #  4. default
```

Nothing else in the codebase reads `os.environ`. `config.yaml` gains:

```yaml
proxy:
  enabled: true
  file: "${PROXY_FILE}"          # env-interpolated; never a literal path with credentials
  rotation: round_robin          # round_robin | random | least_used
  health_check_url: "https://api.ipify.org?format=json"
  health_check_interval_s: 300
  max_consecutive_failures: 3
  blacklist_seconds: 900
  connect_timeout_s: 10
  read_timeout_s: 30
  max_attempts: 4
  min_delay_s: 3.0
  max_delay_s: 7.0
  sticky_sessions: true

ai:
  enabled: true
  provider: deepseek                    # PROVIDER_REGISTRY key
  models:
    default: "deepseek-v4-flash"        # per-stage overrides supported
  concurrency: {initial: 8, floor: 1, ceiling: 16}
  budget:
    max_cost_per_run_usd: 2.00
    max_cost_per_day_usd: 5.00
  cache:
    responses_enabled: true
    content_dedup_enabled: true
    min_prefix_tokens_for_cache: 512
  # NO api_key here — entered on /settings/ai, Fernet-encrypted into `settings`.
  # Full block in 06b §9.

pricing:
  verified_on: "2026-07-30"
  peak_surcharge: {enabled: false, multiplier: 2.0,
                   windows_utc: ["01:00-04:00", "06:00-10:00"]}

scraping:
  default_limit_per_query: 100
  default_time_window: "month"
  fetch_comments: true
  max_comments_per_post: 30
  max_comment_posts_per_run: 100

limits:
  max_subreddits_per_run: 15
  max_keywords_per_subreddit: 20
  max_leads_per_run: 2000
```

Existing keys (`subreddits`, `keywords`, `scoring`, `schedule`, `dashboard`) are untouched, so the
current validator keeps passing.

---

## 11. Observability

**Structured logs.** Every record carries `ts, level, event, run_id, job_id, project_id` plus
event-specific fields. A `RedactingFilter` scrubs anything matching proxy-credential or API-key
patterns before the record is emitted.

**Metrics** flushed to the `metrics` table each minute and rendered at `GET /health`:

| Metric | Type |
|---|---|
| `http.requests_total{outcome}` | counter |
| `http.latency_ms` | histogram (p50/p95/p99) |
| `proxy.requests{proxy_key,outcome}` | counter |
| `proxy.healthy_count` | gauge |
| `proxy.blacklisted_count` | gauge |
| `llm.calls{stage,model,outcome}` | counter |
| `llm.tokens{direction,model}` | counter |
| `llm.cost_usd{model}` | counter |
| `llm.cache_hit_ratio` | gauge |
| `jobs.queued / running / failed` | gauge |
| `leads.created{project_id}` | counter |

**`run_events`** is the user-facing timeline: an append-only row per meaningful event, rendered as
a live log on the run progress page.

**`GET /health`** returns `{status, worker_alive, queue_depth, proxies_healthy, proxies_total,
db_writable, last_run_state}` — one endpoint that answers "is this thing working".
