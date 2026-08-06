# 03 — Architecture

## 1. Architectural style

**A modular monolith: one Python process, layered, with a single background worker thread and a
SQLite datastore.**

This is a deliberate choice, not a default. The operator runs one command on one machine. Every
distributed-systems affordance (broker, cache server, separate DB server) would add a failure mode
without removing one. The layering is strict enough that any layer can later be extracted behind a
process boundary if that ever becomes necessary — see [§9 Evolution](#9-evolution-paths).

---

## 2. Layer diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  PRESENTATION                                                            │
│  src/dashboard/  ·  Flask Blueprints  ·  Jinja templates  ·  inline JS   │
│  main.py CLI (rich)                                                      │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ calls services, never repositories directly
┌───────────────────────────────▼──────────────────────────────────────────┐
│  ORCHESTRATION                                                           │
│  src/orchestration/  ·  RunStateMachine · JobQueue · Worker · Scheduler   │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ dispatches to
┌───────────────────────────────▼──────────────────────────────────────────┐
│  DOMAIN SERVICES                                                         │
│  src/rules/         keywords · negatives · structural · competitors ·    │
│                     authors — DETERMINISTIC, no AI                       │
│  src/dedupe/        exact content hash · MinHash+LSH · semantic tier ·   │
│                     group selection                                      │
│  src/discovery/     subreddit candidate generation + validation + rank   │
│  src/scrapers/      subreddit · keyword · comment · user  (existing +)   │
│  src/scoring/       LeadScorer · prescore · ConfidenceScorer (hybrid) ·  │
│                     AdaptiveBudget (knee · floor · marginal · clamps)    │
│  src/quality/       golden set · calibration · drift · holdout audit     │
│  src/feedback/      labels + reasons · yield curve — DETERMINISTIC       │
│  src/export/        CSV · JSON · XLSX                                    │
│                                                                          │
│  ── AI is reached ONLY after PreAIGate admits the work ──                │
│                                                                          │
│  ── these call AIService by DOMAIN METHOD, never a model vendor ──       │
└──────┬────────────────────────────────────────────────┬──────────────────┘
       │ reads business understanding                   │ invokes a model
┌──────▼──────────────────────────────────────────────┐ │
│  KNOWLEDGE                            src/knowledge/ │ │
│  BusinessKnowledgeBase — 23 typed sections           │ │
│  EntityRegistry — canonical entities + alias tiers   │ │
│  SemanticIndex  — Model2Vec + sqlite-vec (OPTIONAL)  │ │
│  PrefixBuilder  — the ~3.5k-token matching surface   │ │
│  Lifecycle      — staleness, freshness, origin guard │ │
│  Patterns       — nightly GROUP BY, zero AI          │ │
│  KnowledgeSuggestions — proposals, operator-gated    │ │
│                                                      │ │
│  Read by discovery, rules, scoring, enrichment, UI.  │ │
│  Written by the website stage and by ACCEPTED        │ │
│  suggestions only — never by enrichment directly.    │ │
└──────────────────────────────────────────────────────┘ │
                                                         │
┌────────────────────────────────────────────────────────▼─────────────────┐
│  AI SERVICE LAYER      src/ai/     analyze_business() · enrich_batch() … │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ AIService — the ONLY entry point to any model                      │  │
│  │ PromptManager · ContextBuilder · SchemaValidator · ResponseRepairer │  │
│  │ ResponseCache · DedupeGuard · ConcurrencyPool · RateLimiter        │  │
│  │ CostTracker · AIMetrics · RetryPolicy · Credentials                 │  │
│  └────────────────────────────┬───────────────────────────────────────┘  │
│                               │ LLMProvider (ABC)                        │
│      ┌────────────────────────┼────────────────────────┐                 │
│      ▼                        ▼                        ▼                 │
│  DeepSeekProvider    OpenAICompatibleProvider    (future: Anthropic,     │
│  ★ deepseek-v4-flash   (shared base class)        Gemini, Ollama, vLLM)  │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ uses
┌───────────────────────────────▼──────────────────────────────────────────┐
│  INFRASTRUCTURE                                                          │
│  src/net/       ProxyManager · ProxiedHTTPClient · RetryPolicy · Cache   │
│  src/reddit_client.py   (existing, refactored onto ProxiedHTTPClient)    │
│  src/db/        models · database · repositories · migrations            │
│  src/obs/       structured logging · metrics · run events                │
│  src/settings.py  env + DB settings resolution + encrypted secrets       │
└──────────────────────────────────────────────────────────────────────────┘
```

**The AI Service Layer is its own tier**, not a domain service. It sits between domain logic and
infrastructure because it is consumed by many domains (discovery, scoring, enrichment, export) and
because its provider boundary is the seam that keeps a vendor change from touching business logic.
Full design in [06a](06a-ai-service-layer.md).

**The Knowledge tier is also its own tier, and it is deliberately *beside* the AI layer rather than
inside it.** The Business Knowledge Base is produced by an AI call but is not owned by the AI layer:
it is read constantly by code that must never touch a model — the rule engine, the pre-score, the
entity resolver, the dashboard. Putting it inside `src/ai/` would mean the deterministic pipeline
imports the AI package to do keyword matching, which is precisely the coupling
[AD-10a](#ad-10a--local-first-ai-is-the-last-enrichment-step) exists to prevent.

The write path is narrow on purpose: **the BKB is written by the website-intelligence stage and by
accepted suggestions — never by enrichment directly.** Everything else reads. That is what makes the
knowledge base a shared, versioned source of truth rather than a mutable global, and it is why
knowledge can accrete from Reddit ([06h §4](06h-knowledge-lifecycle.md)) without one mis-scored lead
being able to poison it. Full design in [06e](06e-business-knowledge-base.md) and
[06h](06h-knowledge-lifecycle.md).

### Dependency rule

Arrows point **downward only**. Infrastructure never imports domain; domain never imports
orchestration; orchestration never imports presentation. Enforced by a lint rule
(`ruff` `flake8-tidy-imports` banned-module patterns) plus a test that walks the import graph.

Concretely: `src/net/` must not know what a subreddit is; `src/scrapers/` must not know what a Flask
request is; **nothing outside `src/ai/providers/` may contain the string `deepseek`.**

Three grep-enforced rules, each a test:

```bash
grep -ri "reddit\|subreddit\|lead" src/net/                       # → 0
grep -ri "deepseek\|api.deepseek.com\|chat/completions" src/ \
     --exclude-dir=ai/providers                                    # → 0
grep -rn "response_format\|max_tokens\|temperature" src/ \
     --exclude-dir=ai                                              # → 0
grep -rn "import.*src\.ai" src/knowledge/ src/rules/ src/dedupe/ \
     src/scoring/ src/feedback/                                    # → 0
```

The fourth rule is the Knowledge tier's boundary: **the knowledge base, rule engine, dedup, scoring,
and feedback must be importable and testable with no AI package present at all.** If that grep ever
returns a line, the local-first guarantee has been broken somewhere, and the funnel's cost argument
along with it. `src/feedback/` is included because a yield curve or a label router that reached for a
model would be the most expensive possible way to do arithmetic.

---

## 3. Target package layout

New files are marked `+`, modified `~`, untouched files are listed for reference.

```
reddit-scraper/
├── main.py                              ~ new subcommands: worker, migrate, project
├── config.yaml                          ~ new sections: proxy, ai, scraping, limits
├── .env.example                         + APP_SECRET_KEY, PROXY_FILE, FLASK_SECRET (no AI key)
├── requirements.txt                     ~
├── pyproject.toml                       + ruff + pytest config
├── alembic.ini                          +
├── migrations/                          + Alembic env + versions/
│
├── docs/                                + this documentation set
│
├── src/
│   ├── config.py                        ~ env overlay, new sections, secrets never in YAML
│   ├── settings.py                      + typed settings resolution (env > DB > YAML > default)
│   │
│   ├── net/                             + INFRASTRUCTURE — reusable, Reddit-agnostic
│   │   ├── proxy_manager.py             +   pool, rotation, health, blacklist, sticky
│   │   ├── proxy_models.py              +   ProxyEndpoint dataclass, ProxyState enum
│   │   ├── http_client.py               +   ProxiedHTTPClient: retry, backoff, timeouts
│   │   ├── retry.py                     +   RetryPolicy, classify_error()
│   │   ├── user_agents.py               +   consistent header profiles
│   │   ├── cache.py                     +   HTTP response cache (SQLite-backed)
│   │   └── metrics.py                   +   in-process counters + DB flush
│   │
│   ├── reddit_client.py                 ~ same public API; transport delegated to net/
│   │
│   ├── rules/                          + DOMAIN — deterministic, zero AI
│   │   ├── keywords.py                  +   matching, tiers, negatives
│   │   ├── structural.py                +   hiring/giveaway/megathread regex
│   │   ├── competitors.py               +   dictionary + alias matching
│   │   └── authors.py                   +   bot / deleted / normalisation
│   │
│   ├── dedupe/                          + DOMAIN — deterministic, zero AI
│   │   ├── exact.py                     +   tier 1: content-hash dedup
│   │   ├── minhash.py                   +   tier 2: MinHash + LSH near-duplicate
│   │   ├── semantic.py                  +   tier 3: vector neighbours (optional, degrades)
│   │   └── groups.py                    +   representative selection
│   │
│   ├── knowledge/                       + KNOWLEDGE TIER — read by everything, written by one
│   │   ├── lifecycle.py                 +   staleness state, freshness policy, origin guard
│   │   ├── patterns.py                  +   nightly GROUP BY over lead_analysis (zero AI)
│   │   ├── bkb.py                       +   BusinessKnowledgeBase: load, version, section access
│   │   ├── sections.py                  +   the 23 typed section models + registry
│   │   ├── entities.py                  +   EntityRegistry: 4-tier resolve(), alias generation
│   │   ├── links.py                     +   typed edges, polymorphic endpoints
│   │   ├── evidence.py                  +   verbatim span storage + substring validation
│   │   ├── prefix.py                    +   PrefixBuilder: the ~3.5k-token matching surface
│   │   ├── semantic_index.py            +   Model2Vec + sqlite-vec; no-ops if unavailable
│   │   └── suggestions.py               +   learned proposals, operator-gated, never auto-applied
│   │
│   ├── feedback/                        + DOMAIN — operator judgement, zero AI
│   │   ├── labels.py                    +   label + reason capture and routing
│   │   └── yield_curve.py               +   P(is_lead | prescore) — MUST include audit leads
│   │
│   ├── quality/                         + DOMAIN — measurement, zero AI except golden replay
│   │   ├── golden.py                    +   100-item set, blocking regression on prompt change
│   │   ├── calibration.py               +   ECE, Brier, isotonic fit (display-time only)
│   │   ├── drift.py                     +   PSI, category priors, span/repair rates
│   │   └── report.py                    +   nightly + weekly rollups into quality_snapshots
│   │
│   ├── ai/                              + AI SERVICE LAYER
│   │   ├── service.py                   +   AIService — the ONLY entry point to any model
│   │   ├── gate.py                      +   PreAIGate — nothing calls AI without passing
│   │   ├── holdout.py                   +   2% reject audit → gate miss rate
│   │   ├── site_signals.py              +   local website signal extraction
│   │   ├── schemas.py                   +   Pydantic output models for every stage
│   │   ├── context.py                   +   ContextBuilder — the frozen, cacheable prefix
│   │   ├── prompts.py                   +   PromptManager: load, render, version, hash
│   │   ├── prompts/                     +   12 versioned .md templates + _shared/
│   │   ├── repair.py                    +   3-branch ladder: empty / invalid JSON / schema
│   │   ├── cache.py                     +   response cache · content dedup · in-flight guard
│   │   ├── concurrency.py               +   bounded adaptive pool (replaces a batch API)
│   │   ├── cost.py                      +   PriceTable · CostTracker · budget guard
│   │   ├── metrics.py                   +   cache-hit ratio, repair rate, token/cost counters
│   │   ├── errors.py                    +   AI exception hierarchy (incl. 401/402 as states)
│   │   ├── credentials.py               +   encrypted key storage, validation, fingerprints
│   │   ├── website_fetcher.py           +   bounded crawl + readability extraction
│   │   └── providers/                   +   THE VENDOR BOUNDARY
│   │       ├── base.py                  +     LLMProvider ABC · ChatRequest/ChatResponse
│   │       ├── openai_compatible.py     +     shared OpenAI wire format
│   │       ├── deepseek.py              +     ★ DeepSeekProvider (deepseek-v4-flash)
│   │       ├── fake.py                  +     test double — the whole suite runs on this
│   │       └── registry.py              +     PROVIDER_REGISTRY + Settings-UI descriptors
│   │
│   ├── discovery/                       + DOMAIN
│   │   ├── candidates.py                +   channels 1–3
│   │   ├── validator.py                 +   live old.reddit existence/health check
│   │   └── ranker.py                    +   the weighted formula
│   │
│   ├── scrapers/
│   │   ├── base.py                      +   shared run/report/dedup scaffolding
│   │   ├── subreddit_scraper.py         ~   project-aware, batched dedup
│   │   ├── keyword_scraper.py           ~   project-aware, batched dedup, encoded queries
│   │   ├── comment_scraper.py           +   wires up the existing, unused _parse_comments
│   │   └── user_scraper.py              ~   unchanged behaviour, base-class refactor
│   │
│   ├── scoring/
│   │   ├── __init__.py                  ~   re-exports LeadScorer for import compatibility
│   │   ├── lead_scorer.py               ~   moved from src/scoring.py, logic unchanged
│   │   ├── prescore.py                  +   the deterministic 0–100 recall instrument
│   │   ├── budget.py                    +   AdaptiveBudget: knee · floor · marginal · clamps
│   │   ├── knee.py                      +   Kneedle; returns None on a curve with no knee
│   │   ├── yield_curve.py               +   P(is_lead | prescore), fitted from lead_labels
│   │   ├── explain.py                   +   renders confidence_reasoning from stored components
│   │   └── confidence.py                +   ConfidenceScorer — the 0–100 blend
│   │
│   ├── orchestration/                   + ORCHESTRATION
│   │   ├── states.py                    +   RunState / JobState enums + legal transitions
│   │   ├── run_service.py               +   create/advance/approve/cancel a run
│   │   ├── job_queue.py                 +   enqueue / claim / complete / fail / lease-reclaim
│   │   ├── worker.py                    +   the single worker loop
│   │   ├── handlers/                    +   one module per job type
│   │   └── scheduler.py                 ~   existing `schedule` usage, now enqueues jobs
│   │
│   ├── export/                          +
│   │   ├── csv_export.py                ~   moved from routes.py, columns extended
│   │   ├── json_export.py               +
│   │   └── xlsx_export.py               +
│   │
│   ├── obs/                             +
│   │   ├── logging.py                   +   structured JSON logs, secret redaction
│   │   └── events.py                    +   run_events append-only timeline
│   │
│   ├── db/
│   │   ├── models.py                    ~   existing 8 models untouched + ~12 new
│   │   ├── database.py                  ~   WAL pragmas, session_scope() contextmanager
│   │   └── repositories/                +   query objects; kills N+1 and inline SQL in routes
│   │
│   └── dashboard/
│       ├── app.py                       ~   registers multiple blueprints
│       ├── routes.py                    ~   legacy routes preserved verbatim
│       ├── routes_projects.py           +
│       ├── routes_runs.py               +
│       ├── routes_review.py             +   the two gates
│       ├── routes_leads.py              +   detail drawer, AI fields
│       └── templates/
│           ├── base.html                +   extracted shell
│           ├── index.html               ~   legacy dashboard, still works
│           ├── projects.html            +
│           ├── project_detail.html      +
│           ├── review_subreddits.html   +
│           ├── review_keywords.html     +
│           └── run_progress.html        +
│
└── tests/                               +
    ├── fixtures/html/                   +   golden old.reddit pages
    ├── fixtures/llm/                    +   recorded LLM responses
    ├── unit/  integration/  migration/  +
    └── conftest.py                      +
```

---

## 4. The three long-lived runtime roles

| Role | Started by | Responsibility | Writes to DB? |
|---|---|---|---|
| **Web** | `python main.py dashboard` | Serve UI + API, enqueue jobs, read state | Yes — small, fast, user-initiated writes only |
| **Worker** | `python main.py worker` (or auto-spawned in-process, see below) | Claim jobs, run the pipeline, write results | Yes — the bulk writer |
| **Scheduler** | `python main.py schedule` | Time-triggered run creation | Enqueue only |

**Deployment default:** `python main.py dashboard` spawns the worker as a daemon thread in the same
process (`WORKER_INPROCESS=true`, the default), so the operator's experience is unchanged from
today — one command, everything works. Setting `WORKER_INPROCESS=false` and running
`python main.py worker` separately is supported for operators who want isolation, and is what makes
the write-discipline rules below non-negotiable rather than theoretical.

**Single-writer discipline.** Even in-process, the worker is the only component that performs bulk
writes. Web routes write only single rows (status change, approval, settings). This keeps WAL
contention to a minimum and means the separate-process mode works without change.

---

## 5. Data flow of one complete run

```
POST /api/projects {url}
   └─► ProjectService.create()          → projects row
   └─► RunService.start(project)        → runs row, state=PENDING
   └─► JobQueue.enqueue("analyze_website", run_id)

Worker claims job
   ├─ WebsiteFetcher.fetch(url)          [net/ ProxiedHTTPClient + cache]
   ├─ ProfileGenerator.run(text)         [llm/ Opus 5, parse→BusinessProfile]
   ├─ IcpGenerator.run(profile)          → ICP + personas
   ├─ PainGenerator.run(profile, icp)    → pain_points, intent_signals
   ├─ VocabularyGenerator.run(...)       → reddit_vocabulary
   ├─ persist all artefacts
   └─ enqueue("discover_subreddits")     run.state = PROFILING → DISCOVERING

Worker claims job
   ├─ Candidates: LLM proposal ∪ sitewide search harvest ∪ sidebar graph
   ├─ Validator: live old.reddit fetch per candidate → drop invalid
   ├─ Ranker: weighted score, ordered
   ├─ persist project_subreddits (status=proposed)
   └─ run.state = AWAITING_SUBREDDIT_REVIEW      ◄── GATE 1, worker idles

User edits + POST /api/runs/<id>/approve-subreddits
   └─► RunService.approve_subreddits()
   └─► enqueue("generate_keywords")       run.state = GENERATING_KEYWORDS

Worker claims job
   ├─ KeywordGenerator per approved subreddit
   ├─ persist project_keywords (status=proposed)
   └─ run.state = AWAITING_KEYWORD_REVIEW        ◄── GATE 2, worker idles

User edits + POST /api/runs/<id>/approve-keywords {options}
   └─► enqueue one "scrape_subreddit" job per approved subreddit

Worker claims each scrape job
   ├─ RedditClient.search_posts / get_new_posts   [proxied, retried, cached]
   ├─ batched dedup against leads.reddit_id
   ├─ insert Lead rows (project_id set, analysis_status='pending')
   ├─ optionally enqueue "scrape_comments" per qualifying post
   └─ when all scrape jobs done → enqueue("analyze_leads")

Worker claims analyze job
   ├─ deterministic pre-filter
   ├─ cost estimate vs. budget
   ├─ bounded adaptive concurrency pool (DeepSeek has no batch endpoint)
   ├─ persist lead_analysis rows
   ├─ ConfidenceScorer.score() → leads.confidence_score
   └─ run.state = COMPLETE

Dashboard renders ranked leads · Export
```

Every arrow that crosses a stage boundary is a **database write followed by a job enqueue**. There
is no in-memory hand-off between stages. That is what makes the pipeline resumable, individually
retryable, and observable.

---

## 6. Key architectural decisions

### AD-1 — The proxy layer is Reddit-agnostic infrastructure

`src/net/` knows nothing about Reddit. It exposes `ProxiedHTTPClient.get(url, **opts) -> Response`.
`RedditClient` becomes a *consumer*. Consequence: website fetching in Phase 4 gets proxying,
retries, caching, and metrics for free, and the proxy layer is unit-testable with zero Reddit
knowledge.

### AD-2 — `RedditClient`'s public API is frozen

`get_new_posts`, `get_hot_posts`, `search_posts`, `get_post_comments`, `get_user_posts`,
`get_subreddit_info` keep their exact signatures and return shapes. Only `_get()` and the two
pagination bugs change. The three existing scrapers therefore need **no changes** to keep working
in Phase 1, which is what makes Phase 1 independently deployable.

### AD-3 — The run state machine lives in the database

State is a column on `runs`, transitions are validated in `orchestration/states.py`, and every
transition appends to `run_events`. No state lives only in a thread's stack.

### AD-4 — Scoring is two-tier and additive

`LeadScorer` (existing, keyword-based) is unchanged and continues to write `leads.intent_score`.
`ConfidenceScorer` (new) reads AI analysis + non-AI features and writes a **new**
`leads.confidence_score` column. Nothing recomputes or invalidates the 459 existing rows.

### AD-5 — Project scoping is additive and nullable

`leads.project_id` is `NULLABLE` with `ON DELETE SET NULL`. Existing rows keep `NULL` and remain
visible in the legacy dashboard, which filters on `project_id IS NULL OR project_id = :p` when no
project is selected. **This single decision is what makes the whole migration non-destructive.**

### AD-6 — Repositories terminate query sprawl

All non-trivial queries move into `src/db/repositories/`. Routes call repository methods. This is
where the batched dedup lookup lives, where the N+1 dies, and where the project-scope filter is
applied consistently in one place instead of thirty.

### AD-7 — Every external boundary is retried, timed, and metered

Reddit HTTP, website HTTP, and the LLM API each have: a timeout, a retry policy, a circuit
condition, a structured log line, and a metric. No bare `requests.get`, no bare SDK call.

### AD-8 — Prompts are versioned files, not string literals

`src/ai/prompts/<stage>.v<N>.md`. The loader records `(stage, version)` on every artefact and every
analysis row, and the version participates in the response-cache key. Prompt iteration becomes safe
and measurable. Each file carries six mandatory sections including a `# JSON Shape` example — a
DeepSeek requirement, test-enforced.

### AD-10 — One AI boundary, provider-agnostic by construction

`AIService` exposes **domain methods** (`analyze_website`, `recommend_subreddits`,
`enrich_batch`). Business logic never sees a model name, a prompt, a token, or a JSON body — and
reaches the service only after `PreAIGate` admits the work.
Below `AIService`, `LLMProvider` is an ABC with capability flags (`supports_batch_api`,
`supports_schema_enforcement`, `supports_prefix_caching`, `cache_chunk_tokens`) that let the service
select the better code path without branching on vendor identity.

Consequences: adding an OpenAI-compatible provider is a ~40-line subclass; adding Anthropic or
Gemini is one file; and the entire AI test suite runs against `FakeProvider` with **no live API
calls in CI**. See [06a §12](06a-ai-service-layer.md).

### AD-10a — Local-first: AI is the last enrichment step

Every task that a regex, a hash, a set-membership test, a dictionary lookup, a SQL query, or
arithmetic can decide is done deterministically **before** any provider call. `PreAIGate` is a
component with tests, not a convention, and it is the only path to `AIService`.

Enforced by grep test: `src/rules/`, `src/dedupe/`, `src/scoring/`, and `src/knowledge/` may not
import `src.ai`.

Consequence: AI calls scale with **unique, high-value candidates**, not with scraped volume —
~1 call per 48 collected posts rather than 1 per post. Full design in
[06c](06c-local-first-pipeline.md).

### AD-10b — Aggressive filtering requires continuous measurement

A gate that silently discards a good lead is worse than no gate. A **holdout audit** re-admits ~2%
of rejected candidates, enriches them anyway, and publishes a **gate miss rate**. Cost optimisation
that cannot be measured is indistinguishable from quality loss, and this is the mechanism that
distinguishes them.

### AD-11 — The AI never produces the final score

The model emits **categorical judgements** — `buying_intent`, `urgency`, `icp_match`, matched
slugs, a coarse `opportunity_score` — and a deterministic Python `ConfidenceScorer` combines them
with rule-based signals, Reddit metrics, recency, and engagement into the 0–100
`confidence_score`.

This buys reproducibility, free re-ranking on a weight change (zero API calls), measurable
calibration, graceful degradation when AI is unavailable, and an explainable breakdown in the UI.
Asking the model for a number would forfeit all five.

### AD-12 — Secrets are entered at runtime, encrypted at rest, and never in config

The DeepSeek API key is entered on a Settings page, Fernet-encrypted into the **existing**
`settings` table, and never appears in `config.yaml`, any log, any API response, or any template.
The encryption is documented as **defence in depth, not a security boundary** — on a single-tenant
self-hosted box the data key lives on the same machine. It protects against a copied database file
or a backup in cloud storage, not against filesystem access.

**A design consequence worth noting:** because the key lives in the pre-existing `settings` table
and the AI service's other tables (`ai_calls`, `ai_cache`, `ai_provider_state`) are all *new*,
`create_all()` handles them and the AI layer needs no `ALTER`. That is what allows the AI Service
Layer to land in Phase 1 rather than waiting behind the schema work.

### AD-9 — Fail soft on enrichment, fail loud on collection

An LLM failure on one post marks that post `analysis_failed`, leaves its keyword score intact, and
the run continues. A proxy pool exhaustion or a systematic 403 aborts the run with a persisted
error and a visible banner.

### AD-13 — The Business Knowledge Base is the platform's core asset

A website is not an input to one call; it becomes a **persisted, versioned, entity-resolved model of
the business** that every later stage reads from ([06e](06e-business-knowledge-base.md)).

**Consequences that bind the rest of the architecture:**
- The BKB gets its own tier, read-only to everything except the website-intelligence stage.
- Sections version **independently** — regenerating personas must not invalidate the competitor
  registry, because they have different lifetimes and different evidence.
- Every claim carries a **verbatim evidence span** and a source URL, making the knowledge base
  auditable rather than a pile of plausible assertions.
- **The BKB outlives runs.** Archiving a project keeps it, because it is the expensive artefact and
  the reason a second project on the same domain is nearly free.

*This replaces the earlier `ai_artifacts` design, which produced four blobs, used them once, and
discarded the structure — the specific weakness identified in both competitors
([02a §3](02a-competitor-analysis.md)).*

### AD-14 — The AI budget is derived, never configured

How many candidates reach AI is computed **per run from the pre-score distribution** — knee, quality
floor, marginal value, clamps — not from a threshold or a percentage
([06f](06f-adaptive-budget.md)).

Two structural requirements follow:
- **The deciding rule is persisted and displayed.** `Budget.method` (`knee+floor+clamped_min`) is
  stored on every run; a number whose provenance is unknown cannot be tuned or trusted.
- **The budget is validated after the fact.** The knee operates on a *proxy* for value and can be in
  the wrong place; the holdout audit is the only thing that would notice. The knee decides how many;
  the audit decides whether the knee was right.

### AD-15 — Explanations are renderings of the computation, never generated about it

No explanation field may come from a model call whose output is not also an input to the score
([06g §1](06g-explainability-and-quality.md)). The confidence breakdown *is* the arithmetic, printed;
five of the ten explanation fields are computed locally at zero cost; four are **closed-set
selections** from BKB slugs, so an invented persona fails validation; only one is free prose, capped
and constrained to reference the others.

Post-hoc rationalisation is rejected outright: an explanation generated *from* a score can be fluent
and wrong, and a plausible wrong explanation is worse than none.

### AD-17 — Knowledge accretes; regeneration replaces only what it wrote

Every BKB content row carries an `origin` (`website` | `reddit_learned` | `operator`), and
**regeneration deletes only `origin='website'` rows** ([06h §5.2](06h-knowledge-lifecycle.md)).

Without this, regenerating `customer_language` or `competitor_references` from the website would
destroy months of Reddit-learned knowledge — the platform's most valuable accumulated asset — and
nobody would notice, because the section would still look populated. A UI warning does not hold:
someone clicks through it, or a job calls the handler directly. **Making merge-not-replace a
property of the write path makes the data loss structurally impossible instead of procedurally
discouraged.**

Two corollaries:
- **Knowledge ages visibly, never silently.** `last_verified_at` plus a per-type staleness threshold,
  rendered as a badge. **Continuous confidence decay is rejected** — an ICP does not become 3% less
  true each week, and a decaying number would be unexplainable in a platform built on explainability.
- **Staleness never alters a score.** A clock-dependent score would break the reproduction guarantee
  in AD-19.

### AD-18 — Four memory classes, one database file

`durable knowledge` · `evidence` · `operational` · `disposable cache` — logically separated by
retention rule, physically one SQLite file ([06i §4](06i-feedback-and-memory.md)).

The enforceable form of the rule: **deleting every row in the disposable class must not change any
lead's score.** That single assertion stops cache from becoming state, which is how caches turn into
undocumented databases nobody dares clear. Operational rows are purged only *after* aggregation, so
purging costs granularity and never a number anyone is looking at.

**Separation of concerns does not require separation of storage.** Separate datastores are rejected:
each would add a backup story, a consistency problem, and a failure mode, in exchange for a
boundary that documentation and retention policy already provide.

### AD-19 — Every decision pins the versions that produced it

`lead_analysis` records `bkb_id`, `prompt_version`, `weights_version`, and `ruleset_version`, giving:

> **Given the same lead, the same pinned versions, and the same cached analysis, re-running the
> scorer produces a byte-identical breakdown.**

This holds because scoring is deterministic Python over stored components (AD-11) and reads no wall
clock — recency is computed against the *run's* timestamp, not `now()`.

Without pinning, an explanation for a six-month-old lead would silently cite whatever the knowledge
base says *today*, while still looking correct — worse than a broken link. Event sourcing,
immutable ledgers, and cryptographic sealing are **rejected**: they exist for regulated decisions
about people, and cost a permanent architectural burden to deliver nothing here.

### AD-16 — The semantic layer is local, optional, and never authoritative

Static embeddings (Model2Vec, ~30 MB, CPU) in `sqlite-vec` inside the existing database — no vector
service, no embeddings API, no GPU ([06e §5](06e-business-knowledge-base.md), reversing
[02 §6.10](02-research-findings.md)).

Three constraints keep it safe to depend on:
- **It never rejects.** Embeddings only group or surface candidates. A false neighbour costs a shared
  analysis, never a wrong score.
- **It runs last in the cascade**, after exact hashing and MinHash, which are both faster *and* more
  precise. Cheap recall first, expensive precision second.
- **It degrades cleanly.** If `sqlite-vec` will not load, the migration skips the vector tables, every
  consumer falls back to its lexical path, and `/health` reports `semantic_layer: disabled`. A hard
  dependency on a loadable extension would make the schema un-installable in exchange for a recall
  improvement — not a trade worth making.

---

## 7. Cross-cutting concerns

| Concern | Mechanism |
|---|---|
| **Configuration** | Precedence: env var → DB `settings` row → `config.yaml` → hardcoded default. Resolved once in `src/settings.py`; nothing reads `os.environ` directly. |
| **Secrets** | `.env` via `python-dotenv`, never in YAML, never in the DB, never in a log. `.env` and the proxy file are gitignored. A `redact()` filter strips anything matching a credential pattern from log records. |
| **Logging** | **stdlib `logging` + `python-json-logger`** (`ARCHITECTURE_FREEZE` §5, [33 §3.2](33-final-review.md)) — *not* `structlog` or `loguru`. Structured JSON to file, human-readable to console. Every line carries `run_id`, `job_id`, `project_id` when in scope, injected by a `ContextFilter` from a `ContextVar` so third-party libraries are correlated too. Proxy identity is always `ip:port`, never with credentials. Shipped in P2: `src/obs/logging.py`. |
| **Metrics** | In-process counters flushed to a `metrics` table each minute: requests, successes, failures by class, latency percentiles, per-proxy stats, LLM tokens and USD, leads created. Rendered on a `/health` page. |
| **Errors** | Typed exception hierarchy: `ScraperError` → {`ProxyExhaustedError`, `RateLimitedError`, `ParseError`}, `LLMError` → {`SchemaValidationError`, `BudgetExceededError`}. Handlers map these to job outcomes. |
| **Idempotency** | Every job handler is safe to re-run: dedup on `reddit_id`, upsert on artefacts, LLM cache on analysis. A lease expiry that re-runs a job must not double-insert. |
| **Time** | All new code uses `datetime.now(timezone.utc)`. Stored as naive UTC in SQLite to stay byte-compatible with the 459 existing rows; conversion happens at the boundary in one helper. |
| **Backward compatibility** | Legacy CLI commands, legacy routes, legacy templates, and the legacy DB all keep working. Verified by a dedicated regression suite run after every phase. |

---

## 8. Technology decisions

| Choice | Selected | Rejected alternatives | Why |
|---|---|---|---|
| AI provider | **DeepSeek V4 Flash** | Claude, GPT, Gemini | $0.14/$0.28 per 1M; 1M context; 50× cache discount; OpenAI-compatible so alternatives stay cheap to add |
| AI transport | `requests` against `/v1/chat/completions` | `openai` SDK | Wire format is one endpoint; the SDK adds weight, implies vendor coupling, and hides the retry semantics we must own |
| Structured output | JSON mode + client-side Pydantic + repair ladder | Trusting the model | DeepSeek guarantees syntax, not schema |
| Bulk enrichment | Bounded adaptive concurrency pool | Batch API | **DeepSeek has no batch endpoint** |
| Secret storage | Fernet in the `settings` table, key from env | Plaintext, OS keyring | No new table, no new dependency beyond `cryptography`; keyring is absent on headless servers |
| HTTP | `requests` + `HTTPAdapter` pooling | `httpx`, `aiohttp` | Already present; sync fits a single worker; per-proxy adapters give connection pooling for free |
| HTML parse | `BeautifulSoup` + `lxml` | `selectolax`, regex | Already present and working; parse cost is not the bottleneck |
| Text extraction | `trafilatura` | `readability-lxml`, `newspaper3k` | Best boilerplate removal; single dependency; graceful `bs4` fallback |
| DB | SQLite + WAL | Postgres | One operator, one machine; documented upgrade path |
| Migrations | Alembic | hand-rolled SQL | Standard, works with existing SQLAlchemy metadata, supports stamping |
| Queue | SQLite `jobs` table | Celery, RQ, Huey | Review gates already force run state into the DB; a broker duplicates it |
| Scheduler | existing `schedule` | APScheduler, cron | Already works, already understood |
| LLM access | `AIService` + `LLMProvider` ABC | direct provider calls | One vendor boundary; a provider swap touches no business logic |
| Validation | Pydantic v2 | dataclasses + manual | Required by `messages.parse()`; free retry-on-invalid |
| Web | Flask + Jinja | FastAPI, React | Already present; no build step; server-rendering is adequate |
| Charts | Chart.js CDN | — | Already present |
| Test | pytest + responses | unittest | Fixtures, parametrisation, HTTP mocking |
| Lint | ruff | flake8+black+isort | One tool, fast, includes import-boundary rules |

---

## 9. Evolution paths

Documented so they are *available*, not *scheduled*. None of these are phases.

| Trigger | Change | Cost |
|---|---|---|
| Multiple concurrent operators | SQLite → Postgres | Change the URL; Alembic revisions are portable; drop the WAL pragmas. Repositories mean no query rewrites. |
| Runs exceed one machine | Worker → separate host | Already supported by `WORKER_INPROCESS=false`; needs a shared DB, i.e. Postgres first |
| Job volume outgrows the table | `jobs` table → Redis/RQ | `JobQueue` is an interface; swap the implementation. Run state stays in the DB regardless. |
| Semantic subreddit matching wanted | Add embeddings + a vector column | Additive; a fourth discovery channel |
| Multi-tenant SaaS | Add `users`, `organizations`, auth | `project_id` already gives the scoping seam |
| **A second AI provider is wanted** | Subclass `OpenAICompatibleProvider` (OpenAI, Together, Groq, DeepInfra, vLLM, Ollama) or implement `LLMProvider` (Anthropic, Gemini) | ~40 lines or ~150 lines. **Zero** changes to `AIService`'s public methods, handlers, scrapers, scoring, or prompts. |
| **Provider fallback / routing** | `AIService` holds an ordered provider list; on `INSUFFICIENT_BALANCE` or sustained failure, fall through to the next | The registry and capability flags already exist; this is a policy layer above them |
| **Self-hosted model** | Ollama/vLLM provider pointed at localhost | Capability flags mark it as no-prefix-cache, no-schema-enforcement; the service adapts automatically |
