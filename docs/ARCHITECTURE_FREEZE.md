# ARCHITECTURE FREEZE

**Frozen: 2026-08-05** · Supersedes nothing; governs everything.

> This document is the **binding constraint set** for implementation. No future work may violate it.
>
> **It may be amended in exactly one way:** a Validation Sprint or a phase's acceptance testing
> proves a stated assumption false. The amendment is then recorded in §11 with the measurement that
> forced it, the date, and the decision it replaces. **No other amendment path exists** — not a
> better idea, not a new framework, not a blog post.
>
> If a proposed change is not answering a failed measurement, the answer is no.

---

## 1. What this system is

**Paste a website URL; get a ranked list of Reddit conversations where real people are describing
the problem that website solves, with evidence for why each one is a lead.**

One operator. One machine. One SQLite file. Two processes. Two AI boundaries.

```
┌─ CONTROL PLANE ─ Hermes ───────────────────────────────────────┐
│ Telegram conversation · gate approval · scheduling · reporting  │
│ AGENT KEY · capped $1/day · no terminal · no DB access          │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP localhost, 5 tools, bearer token
┌───────────────────────────▼─────────────────────────────────────┐
│ DATA PLANE ─ the platform                                       │
│                                                                 │
│  Flask ─ 17 legacy endpoints · projects · runs · gates · leads   │
│  Orchestration ─ RunStateMachine · JobQueue · Worker (sole writer)│
│  DISCOVERY ─ RSS change detection → watermark → metadata triage  │
│              → density-adaptive body fetch → comments            │
│  DETERMINISTIC ─ rules · dedupe · prescore · budget · confidence  │
│              (grep-fenced from src.ai AND from hermes)           │
│  KNOWLEDGE ─ BKB 23 sections · entities · evidence · prefix      │
│  AI SERVICE ─ PreAIGate → AIService → LLMProvider                │
│              PIPELINE KEY · 4 ceilings · frozen prefix · B=8     │
│  NETWORK ─ NetworkPolicy → {Direct, ManagedProxy} per class      │
└─────────────────────────────────────────────────────────────────┘
                            │
                    data/leads.db  (SQLite + WAL, 0600, one writer)
```

---

## 2. Frozen architecture rules

**Violating any of these is a defect, not a design choice.** Each is grep- or test-enforced where
the second column says so.

| # | Rule | Enforced by |
|---|---|---|
| **R1** | `old.reddit.com` and public `.rss` only. **No Reddit API, OAuth, PRAW, or account of any kind** | Grep: `praw`, `asyncpraw`, `oauth`, `client_secret` → 0 |
| **R2** | `AIService` is the only path from the pipeline to a model | Grep: no `deepseek` outside `src/ai/providers/` |
| **R3** | `rules/`, `dedupe/`, `scoring/`, `knowledge/`, `feedback/`, `discovery/policy.py` **never import `src.ai`** | Grep fence 2 |
| **R4** | **`src/` never imports Hermes.** The platform does not depend on the control plane | Grep fence 3 |
| **R5** | `src/net/` contains no Reddit identifier | Grep fence 4 |
| **R6** | The AI never produces the final score. Categoricals in, arithmetic out | `ConfidenceScorer` is pure Python; property tests |
| **R7** | Explanations render stored computations. **No explanation field may come from a model call whose output is not also an input to the score** | Grep: `confidence_reasoning` rendered by `scoring/explain.py`; reconciliation test |
| **R8** | The worker is the **sole bulk writer**. Web routes write single rows only | Review + WAL contention test |
| **R9** | Every job handler is idempotent | Lease-expiry re-run tests |
| **R10** | Nothing reaches a model without passing `PreAIGate` | Component with tests; the only caller of `AIService` in the enrichment path |
| **R11** | Every gate that discards items **must be audited**. A 2% holdout applies to the admission gate *and* to metadata triage | `gate_audits`; miss rate published per run |
| **R12** | Knowledge accretes. Regeneration deletes only `origin='website'` rows | Write-path guard; regenerate-twice test |
| **R13** | Every `lead_analysis` row pins `bkb_id`, `weights_version`, `ruleset_version` — **unless** `reused_cross_project=1`, where `bkb_id IS NULL` and no slugs are set | Schema + test |
| **R14** | Deleting `ai_cache` + `http_cache` changes no score. Deleting Hermes memory changes no score, no BKB section, no run outcome | Snapshot / delete / re-score / compare |
| **R15** | Secrets never enter the database, a log, an API response, a template, or the repository | Redaction filter + full-log grep + endpoint scan |
| **R16** | Reddit content reaches the agent only inside an `untrusted_content` envelope, and the agent has no terminal, file, browser or code toolset | Config assertion + injection fixture |
| **R17** | Notifications never invoke a model | `src/notify/` imports neither `src.ai` nor an agent runtime; token assertion |
| **R18** | Egress is chosen **per request class**. RSS, health checks and the customer's own website are always direct | Policy test |
| **R19** | Watermark overflow is an **error**, never a silent gap | Overflow fixture |
| **R20** | The legacy contract holds after every phase: **459 leads, unchanged `intent_score`, `GET /` byte-identical, 13 CSV columns, 17 endpoints** | Regression suite, every phase |

---

## 3. Frozen decision register

AD-1 … AD-24 in [03 §6](03-architecture.md) stand as written, with the amendments below. AD-25 …
AD-31 are in [32 §4](32-documentation-consistency.md).

| AD | Decision | Status |
|---|---|---|
| AD-1 | Proxy layer is Reddit-agnostic infrastructure | ✅ Frozen |
| AD-2 | `RedditClient` public API frozen | ✅ **Amended** — `get_feed()` added; additive only |
| AD-3 | Run state machine lives in the database | ✅ Frozen |
| AD-4 | Scoring is two-tier and additive | ✅ Frozen |
| AD-5 | Project scoping is additive and nullable | ✅ Frozen |
| AD-6 | Repositories terminate query sprawl | ✅ Frozen |
| AD-7 | Every external boundary retried, timed, metered | ✅ Frozen |
| AD-8 | Prompts are versioned files | ✅ Frozen |
| AD-9 | Fail soft on enrichment, loud on collection | ✅ Frozen |
| AD-10 | One AI boundary, provider-agnostic | ✅ Frozen |
| AD-10a | Local-first: AI is the last enrichment step | ✅ Frozen |
| AD-10b | Aggressive filtering requires continuous measurement | ✅ **Amended** — extends to metadata triage |
| AD-11 | The AI never produces the final score | ✅ Frozen |
| AD-12 | Secrets at runtime, encrypted at rest | ✅ Frozen |
| AD-13 | The BKB is the platform's core asset | ✅ Frozen |
| AD-14 | The AI budget is derived, never configured | ✅ Frozen |
| AD-15 | Explanations are renderings, never generated | ✅ Frozen |
| AD-16 | Semantic layer is local, optional, never authoritative | ✅ Frozen |
| AD-17 | Knowledge accretes; regeneration replaces only what it wrote | ✅ Frozen |
| AD-18 | Four memory classes, one file | ✅ **Amended** — fifth class: agent memory |
| AD-19 | Every decision pins its versions | ✅ **Amended** — cross-project reuse exception |
| AD-20 | Hermes is the operator tier, never the pipeline | ✅ Frozen |
| AD-21 | The high-volume path never enters an agent loop | ✅ Frozen |
| AD-22 | The agent tier has its own credential, ledger and ceiling | ✅ Frozen |
| AD-23 | The agent tier is toolless by default | ✅ Frozen |
| AD-24 | Reddit content reaches the agent as data, never instruction | ✅ Frozen |
| AD-25 | Egress is a policy, not a mandate | ✅ Frozen |
| AD-26 | Discovery is metadata-first | ✅ Frozen |
| AD-27 | The watermark is the sync primitive; overflow is an error | ✅ Frozen |
| AD-28 | Notifications never invoke a model | ✅ Frozen |
| AD-29 | The agent tier adds no tables | ✅ Frozen |
| AD-30 | Deployment is systemd and unix users, not containers | ✅ Frozen |
| AD-31 | Framework defaults are audited, not inherited | ✅ Frozen |

**Withdrawn and not to be reinstated:** `agent_events` / `notification_log` tables; the
`0005_agent_tier` migration and its renumbering; two-container Docker deployment.

---

## 4. Frozen migration rules

| # | Rule |
|---|---|
| **M1** | **One linear chain, one head.** `alembic heads` returns exactly one, always |
| **M2** | **No suffixed revisions** (`0005a`). No revision inserted out of sequence once shipped |
| **M3** | Revisions `0001`–`0003` are **applied to the live database and immutable** |
| **M4** | Revisions `0004`–`0010` are unshipped and are **authored in phase order** — this is not renumbering |
| **M5** | **Additive only.** No existing column is dropped, renamed or retyped. No migration rewrites a row |
| **M6** | Every revision has a **tested `downgrade()`** |
| **M7** | A timestamped backup via the SQLite backup API precedes every upgrade |
| **M8** | Forward references use a **bare column plus a deferred FK** added later by `batch_alter_table` |
| **M9** | Every revision is tested **up, down, and up again** against a copy of the live 459-lead database |
| **M10** | `0001` is **stamped, not applied**, on the existing database |

### 4.1 The frozen chain

| Rev | Title | Phase | Contents |
|---|---|---|---|
| `0001` | `baseline` | ✅ shipped | The 8 original tables |
| `0002` | `ai_infrastructure` | ✅ shipped | `ai_calls`, `ai_cache`, `ai_provider_state` |
| `0003` | `net_infrastructure` | ✅ shipped | `proxies`, `http_cache`, `metrics` |
| `0004` | `orchestration` | P1 | `runs`, `jobs`, `run_events`, `scrape_runs.run_id` |
| `0005` | `discovery` | P6 | `discovery_watermarks`, **`prescores`** (incl. `stage`; `comment_id` FK deferred) |
| `0006` | `content_and_dedup` | P8 | `comments`, `dedup_groups`, `dedup_members`, `minhash_bands`, `leads` +4 |
| `0007` | `projects_and_knowledge_base` | P12 | `projects`, `website_snapshots`, `bkb*`, `personas`, `pain_points`, `intent_signals` + deferred FKs |
| `0008` | `targeting` | P17 | `project_subreddits`, `project_keywords` |
| `0009` | `enrichment` | P19 | `lead_analysis` (incl. `reused_cross_project`), `gate_audits`, `ai_budgets` |
| `0010` | `monitoring_and_quality` | P25 | `lead_labels`, `golden_items`, `golden_runs`, `quality_snapshots`, `calibration_maps`, `patterns` |

**Ten revisions. No eleventh without an amendment under §11.**

---

## 5. Frozen technology set

| Layer | Choice | Not |
|---|---|---|
| Language | Python 3.12 | — |
| Web | Flask + Jinja, no build step | FastAPI, React, npm |
| DB | SQLite + WAL, one file | Postgres, MySQL |
| Migrations | Alembic | Hand-rolled SQL |
| Queue | `jobs` table | Celery, RQ, Redis, Dramatiq |
| Cache | SQLite tables | Redis, memcached |
| HTTP | `requests` + per-proxy `HTTPAdapter` | httpx, aiohttp |
| HTML | BeautifulSoup + lxml | selectolax, regex |
| **Atom** | **`lxml` directly** | **`feedparser` — one format, one source** |
| Text extraction | `trafilatura` | readability-lxml, newspaper3k |
| Validation | Pydantic v2 | dataclasses + manual |
| **Logging** | **stdlib `logging` + `python-json-logger`** | **`structlog`, `loguru`, OpenTelemetry** |
| Concurrency | Threads + bounded `ThreadPoolExecutor` | asyncio |
| Vectors | Model2Vec + `sqlite-vec`, optional | Pinecone, Weaviate, Qdrant, Chroma |
| AI provider | DeepSeek V4 Flash (direct), OpenRouter failover | Vendor SDK |
| Agent runtime | Hermes 0.20.0, pinned | LangChain, LangGraph, AutoGen |
| Scheduler | `hermes cron` | APScheduler, system cron |
| Messaging | Telegram | Slack, Discord, email |
| Deployment | systemd, two unix users, one VPS | Docker, Kubernetes |
| Lint / test | ruff, pytest, responses, **mypy** *(dev only — §11.1)* | flake8, black, isort, unittest |

**Adding anything to the left column requires an amendment. Adding anything from the right column is
prohibited.**

---

## 6. Frozen budgets

| Ceiling | Value | Scope |
|---|---|---|
| `max_cost_per_run_usd` | $2.00 | Pipeline |
| `max_cost_per_day_usd` | $5.00 | Pipeline |
| `max_ai_calls_per_run` | 500 | Pipeline |
| `max_items_per_run` | 2,000 | Pipeline |
| `agent.max_cost_per_day_usd` | **$1.00** | Agent tier |
| `agent.max_turns` | **12** | Per turn-loop |
| `network.direct.max_requests_per_hour` | 120 | Direct egress governor |

| Target | Value |
|---|---|
| Posts never sent to a model, 30-day window | **≥ 95%** |
| Call reduction vs one-call-per-post, every run | **≥ 95%** |
| Steady-state Reddit requests/day | **≤ 80** |
| Gate miss rate | **< 5%** |
| Agent turns/month | **≤ 350** |
| ◐ Platform AI spend/month | **≈ $0.34** |
| Hard monthly ceiling, both tiers | **$180** |

---

## 7. Frozen scope limits

| Component | First delivery | Target | Expansion requires |
|---|---|---|---|
| Hermes seam tools | **5** | 17 | A stated operator need, per tool |
| Hermes skills | **3** | 13 | Same |
| Hermes profiles | **1** | 1 | A second human operator |
| Notification kinds | **5** | 9 | Operator request |
| Discovery channels | 4 | 4 | — |
| BKB sections | 23 | 23 | — |

▶ The first two rows exist because a tool schema and a skill description are paid on **every turn**.
Shipping 17 tools to use 5 is a permanent tax for a capability nobody asked for.

---

## 8. Non-goals — permanent

| Not building | Why |
|---|---|
| **Posting, commenting, or DMing on Reddit** | Violates Reddit norms; risks the operator's accounts. **The platform has no Reddit write path and never will.** Drafting for a human to send is in scope; sending is not |
| Reddit account, login, OAuth, API key | The failure mode that terminated the category leader |
| Aged or rented Reddit accounts | Ban evasion |
| Unified outreach inbox | This is a discovery tool |
| Multi-user accounts, auth, RBAC | Single-operator, self-hosted |
| Real-time streaming ingest | Batch + scheduled is sufficient and far cheaper |
| A JS build pipeline | Server-rendered Jinja works and has zero toolchain cost |
| Full-site crawling | Bounded page fetch only |
| Agent-orchestrated pipeline | The steps are known in advance |
| Learned rankers, online training, LLM-as-judge | Data volume is two orders of magnitude short |
| Topic modelling / clustering | The data is already labelled; discovery is a `GROUP BY` |
| Event sourcing, immutable ledgers, cryptographic sealing | Built for regulated decisions about people |
| Vector database, graph database, RAG over raw text | Solve scale problems we do not have |
| Separate datastores | Each adds a backup story, a consistency problem, a failure mode |
| Confidence decay curves | An ICP does not become 3% less true each week |
| Expiring leads | A lead is a historical fact |
| Distributed tracing, OpenTelemetry | Instrumentation for a scale we do not have |
| MCP servers | Largest single expansion of attack surface and per-turn cost, for no current need |
| Cloud terminal backends (Modal, Daytona, Vercel, Singularity) | One VPS |
| Voice, TTS, image generation, wake word, browser automation | No use case; Level-0 tax and attack surface |
| External memory providers (Honcho, Mem0, …) | Second source of truth for what the BKB owns |
| Hermes batch runner for enrichment | One full agent loop per item — the wrong shape |

---

## 9. Deferred features — with their trigger

▶ Available, not scheduled. Each names the evidence that would justify it.

| Feature | Trigger |
|---|---|
| Residential proxy purchase | P0's U8 shows an unacceptable block rate at the reduced volume |
| Postgres | A second concurrent operator |
| Redis | A second worker host (which needs Postgres first) |
| Docker | A second host, or a need to run off this VPS |
| Second Hermes profile | A second human operator with different permissions |
| Remaining 12 seam tools / 10 skills | A stated operator need, one at a time |
| MCP | A CRM or calendar integration |
| Headless browser | JS-only sites become a material share of projects |
| `a.morecomments` expansion | Comment coverage measured as insufficient |
| Author cross-posting (channel 5) | Discovery recall measured as insufficient |
| SERP / AI-visibility tracking | A different product |
| `deepseek-v4-pro` for Tier 2 | Golden-set evidence, never intuition |
| Segmented calibration | ≥500 total labels **and** ≥200 within a segment |
| Multi-tenant SaaS | Not a goal |

---

## 10. Known risks carried into implementation

| # | Risk | Severity | Mitigation | Owner phase |
|---|---|---|---|---|
| K1 | **Reddit changes its HTML** — parsers silently return zero | Critical | Golden fixtures; daily Atom canary; RSS moves the hot path off CSS | P5, P30 |
| K2 | **Prefix cache silently stops hitting** → up to 50× cost | Critical | `prompt_cache_hit_tokens>0` asserted from call 2; `prefix_hash` constant; loud warning | P20 |
| K3 | **Concurrent result mis-attribution** | Critical | `futures[fut]` mapping; blocking shuffled-order test | P20 |
| K4 | **Degenerate learning loop** — yield curve fitted only on admitted leads | Critical | Holdout leads are labellable; test fails if the fit query filters to admitted | P19, P25 |
| K5 | **Regeneration deletes Reddit-learned knowledge** | Critical | `origin` guard on the write path; regenerate-twice assertion | P15 |
| K6 | **API key leaked** | Critical | Fernet at rest; never returned; redaction; grep tests | All |
| K7 | **Datacenter proxies blocked** (measured 67%) | High | P0 U8 re-measures at the new volume; policy degrades; residential is one config change | P0, P4 |
| K8 | **RSS deprecated or throttled further** | High | HTML path retained, not deleted; `rss_enabled: false` restores it; canary detects | P5, P6 |
| K9 | **Watermark overflow loses posts silently** | High | Overflow is an error with an HTML fallback (R19) | P6 |
| K10 | **Metadata triage discards good leads** | High | Stage-3 holdout audit (R11) | P6 |
| K11 | **Hermes v0.20.0 breaking change** | Medium | Version pinned; `hermes update` disabled; platform has no dependency on it | P23 |
| K12 | **Agent spend unbounded** | High | Separate key; `pre_llm_call` governor; `max_turns: 12`; ledger | P24 |
| K13 | **SQLite `database is locked`** under worker + web | High | WAL, `busy_timeout`, single writer, short transactions | P2 |
| K14 | **Migration corrupts the live database** | Critical | Backup before every upgrade; tested downgrade; suite runs on a copy | All |
| K15 | **Batch quality degradation** past B=8 | High | Measured sweep; id echo; length mismatch splits | P20 |
| K16 | **Adaptive budget returns nonsense** on a flat curve | High | `n<200` bypass; 5%/90% clamps; `method` persisted | P19 |
| K17 | **Disk fills** — `ai_cache` has no TTL by design | Medium | `/health` reports free disk and DB size; maintenance alerts | P29 |
| K18 | **Prompt injection from Reddit content** | Critical | No dangerous toolsets; `untrusted_content` envelope; injection fixture | P23 |

---

## 11. Amendment log

Every entry must contain: the measurement that failed, the date, the decision being replaced, the
replacement, and the phase that discovered it.

| Date | Measurement that failed | Decision replaced | Replacement | Phase |
|---|---|---|---|---|
| **2026-08-05** | **U4 — conditional GET.** Reddit sends neither `ETag` nor `Last-Modified` on `.rss`; only `Cache-Control: private, max-age=3600`. Measured on 4 feeds, 2 hosts | [28 §5.1](28-discovery-redesign.md) **layer L1 (conditional GET)**, and the "idle poll costs 0 bytes" claim in [28 §4.3](28-discovery-redesign.md) | **Layer L1 is deleted.** An idle poll costs one full request, measured at 56,241 bytes for a 25-entry feed. `discovery_watermarks` drops `last_etag` and `last_modified`. [AD-26](#) and [AD-27](#) are unaffected — the poll is still one request against the current design's 390 | **P0** |
| **2026-08-05** | **U1 — RSS rate-limit scope.** A *different* feed requested immediately after a successful one returns 429. Recovery measured at 60 s (30 s still 429) | [28 §3](28-discovery-redesign.md) treated multireddit combining as an optimisation available in the pessimistic branch | **Multireddit combining is mandatory.** Twelve subreddits polled individually cost 12 minutes of wall clock at 1 request/min; combined they cost one request | **P0** |

### 11.1 Documentation reconciliations — *not* amendments

Inconsistencies **between frozen documents**, where no technology, table or decision changes. Recorded
here for traceability; they do not consume the amendment path.

| Date | Inconsistency | Resolution |
|---|---|---|
| 2026-08-05 | [35 §2.1](35-testing-strategy.md) specifies grep fences 1 and 4 as `grep -ri`, which matches **docstrings and comments** and therefore fails against correct, shipped code. The shipped enforcement `tests/test_boundaries.py` is AST-based and passes | [35 §2.1](35-testing-strategy.md) corrected to invoke `tests/test_boundaries.py`. The implementation was right; the documentation was wrong |
| 2026-08-05 | [35 §2.1](35-testing-strategy.md) check 3 requires `mypy`; §5 of this document omits it from the technology list | `mypy` added to §5 as a dev tool. No new technology is introduced — one was omitted from a list |
| 2026-08-07 | [13 §2.2](13-phase-03.md) states that P3 leaves the two review-gate states unentered — *"the states exist, but nothing enters them yet"*. The transition table in [04 §1.2](04-system-design.md), transcribed by P1, admits **exactly one** path from `PENDING` to `SCRAPING`, and **both gates lie on it**. The two statements cannot both hold | **The table is the specification; [13 §2.2](13-phase-03.md) is corrected.** A run walks all seven hops through `RunService.transition()`, so every one is validated by `assert_transition` and appends a `run_events` row naming why the gate is *satisfied* rather than skipped — a scrape started from the dashboard uses the subreddits the operator already chose, which is the decision each gate exists to ask for. **No state, transition, table or technology changes**, so this is a reconciliation and not an amendment. The gate **UIs** remain P18's, as [13 §2.2](13-phase-03.md) intended. Forced, not chosen: `SCRAPING ← AWAITING_OPTIONS ← AWAITING_KEYWORD_REVIEW ← GENERATING_KEYWORDS ← AWAITING_SUBREDDIT_REVIEW ← DISCOVERING ← PROFILING ← PENDING` |

---

## 12. The freeze statement

> As of **2026-08-05**, the architecture described across [03](03-architecture.md),
> [04](04-system-design.md), [05](05-database-plan.md), [06*](06-ai-pipeline.md),
> [21](21-hermes-architecture.md), [28](28-discovery-redesign.md), [29](29-network-and-proxy-strategy.md)
> and this document is **frozen**.
>
> Implementation proceeds phase by phase per [34](34-implementation-plan.md), one phase at a time,
> each gated by [35](35-testing-strategy.md).
>
> **No phase may introduce a technology, a table, a migration, an AI call, a dependency, or a
> capability that is not named in this document.**
>
> If implementation reveals that it must, that is an amendment under §11 — and it requires a failed
> measurement, not an argument.
