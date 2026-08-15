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
| **2026-08-08** | **The HTML listing page carries no selftext.** Old Reddit renders a listing expando as `<div class="expando expando-uninitialized"><span class="error">loading...</span></div>` and fetches the body over AJAX, so `div.expando .md` — the selector `_extract_post` has always used — matches **zero** elements. Measured three ways: live `/r/startups/new/` (25 expandos, 0 bodies), the shipped P0 capture `tests/fixtures/reddit/listing_page1.html` (25 expandos, 0 bodies), and `search_page1.html` for contrast (22 bodies via `div.search-result-body .md`). Found by `scripts/validate_feed_parity.py` on its first live run: 25 of 25 shared posts differed on `body` | [28 §2.2](28-discovery-redesign.md)'s comparison table — *"HTML listing page · **Selftext body** ✅"* — and the conclusion built on it: *"an HTML listing page carries 25 posts with body and score … if full data is needed for more than ~25% of discovered posts, HTML listing is the cheaper source"* | **The HTML listing carries title, author, permalink, timestamp, score and comment count — and no body.** The feed is the *only* bulk source of selftext; HTML **search** still carries bodies inline and is unaffected. RSS's role as primary discovery is strengthened, not changed. **[34 §P6](34-implementation-plan.md) task 5's density-adaptive body fetch (listing ≥25%, permalink <25%, hysteresis 30/20) rests on the refuted premise and must be redesigned in P6** — its listing branch would fetch a page that has no bodies to give. P5's acceptance criterion gains `body` as a third intentional difference, scoped to listing pages | **P5** |
| **2026-08-08** | **`url` means different things on the two endpoints.** A listing title links to the post's *destination*, so `_extract_post` stores `https://v.redd.it/…` or `https://i.redd.it/….png` for link and media posts; the feed's `<link href>` is always the permalink. Measured on r/SaaS 2026-08-08: **3 of 25**. Separately, `_extract_search_post` does not normalise its host at all, so search-sourced leads carry `old.reddit.com` — the live database splits **444 `old.reddit.com` / 27 `www.reddit.com`** across 471 rows | Nothing stated it. [34 §P5](34-implementation-plan.md)'s *"identical `Lead` dicts … except `score`/`num_comments`"* implicitly assumed `url` agreed | **The feed keeps the permalink.** It is the actionable URL for a lead, it is what the search path already stores, and it is what 444 of 471 existing rows carry. The feed is **not** changed to echo the listing's external URL, which would trade a useful value for a matching one. Recorded as a documented difference scoped to link/media posts, asserted narrowly (the feed permalink must carry *this* post's id) so it cannot hide a wrong permalink. Normalising `_extract_search_post`'s host is deferred — it changes shipped behaviour | **P5** |
| **2026-08-05** | **U1 — RSS rate-limit scope.** A *different* feed requested immediately after a successful one returns 429. Recovery measured at 60 s (30 s still 429) | [28 §3](28-discovery-redesign.md) treated multireddit combining as an optimisation available in the pessimistic branch | **Multireddit combining is mandatory.** Twelve subreddits polled individually cost 12 minutes of wall clock at 1 request/min; combined they cost one request | **P0** |

### 11.1 Documentation reconciliations — *not* amendments

Inconsistencies **between frozen documents**, where no technology, table or decision changes. Recorded
here for traceability; they do not consume the amendment path.

| Date | Inconsistency | Resolution |
|---|---|---|
| 2026-08-11 | **[05 §7](05-database-plan.md) declares itself *"authoritative"* over the migration chain and contradicts [§4.1](#41-the-frozen-chain) on the number, name and content of every revision from `0005` onward.** It predates [31](31-execution-plan.md)'s reorder: it puts `projects_and_knowledge_base` at `0005` and `content_and_dedup` at `0007`, where the shipped chain has `discovery` at `0005` and `content_and_dedup` at `0006`. It also says *"no tenth revision"* twice, where §4.1 lists ten; describes the `leads` change as *"three columns"*, where §4.1 says *"+4"*; and its §7.1a ordering block ends in `CREATE prescores`, a statement that would fail with *"table prescores already exists"* because the 2026-08-08 reconciliation below moved `prescores` into `0005`. Its §7.1 deferred-FK table lists three columns and **none of the four `project_id` columns `0006` creates**, and its §7.1 prose calls deferral *"cheap"* on the grounds that SQLite ignores a `REFERENCES` clause unless `PRAGMA foreign_keys` is on | **§4.1 wins; [05 §7](05-database-plan.md), §7.1, §7.1a, §4.1 and §5.4/§5.4b are reconciled to it.** No technology, table or decision changes — a revision-numbering table that predated a reorder was brought into line with the chain that shipped. **The "cheap" claim is struck as factually wrong**, and that correction is the substantive one: a `REFERENCES` clause naming a table that does not exist yet makes **every `INSERT` into the child table fail** with `no such table`, *regardless of the pragma* and even with the column set to `NULL`, because SQLite resolves the parent at statement-prepare time. It is silent — the migration applies, `foreign_key_check` returns `[]`, the up/down/up round-trip passes and `check_schema.py` reports OK. Measured on SQLite 3.45.3 in two independent sessions. Deferral under **M8** is therefore mandatory, not an optimisation, and `tests/test_migrations.py::test_no_revision_leaves_a_dangling_foreign_key` now enforces it over every revision `0001..head`. `leads.source`, defined only in the superseded [16 §115](16-phase-06.md) while §4.1 counted it in *"+4"*, is adopted into [05 §4.1](05-database-plan.md) verbatim. Reasoning: [P8-DECISION-ANALYSIS §D1–D4](P8-DECISION-ANALYSIS.md), [P8-IMPLEMENTATION-REVIEW §F1–F5](P8-IMPLEMENTATION-REVIEW.md) |
| 2026-08-05 | [35 §2.1](35-testing-strategy.md) specifies grep fences 1 and 4 as `grep -ri`, which matches **docstrings and comments** and therefore fails against correct, shipped code. The shipped enforcement `tests/test_boundaries.py` is AST-based and passes | [35 §2.1](35-testing-strategy.md) corrected to invoke `tests/test_boundaries.py`. The implementation was right; the documentation was wrong |
| 2026-08-05 | [35 §2.1](35-testing-strategy.md) check 3 requires `mypy`; §5 of this document omits it from the technology list | `mypy` added to §5 as a dev tool. No new technology is introduced — one was omitted from a list |
| 2026-08-08 | **Conditional GET is described as P5 work in four places** — [34 §P5](34-implementation-plan.md)'s Deliverables, Files, Tasks 4–5 and Acceptance; [28 §12](28-discovery-redesign.md)'s file table; [28](28-discovery-redesign.md)'s **D-AC2**; and [35 §6](35-testing-strategy.md)'s P5 row — while the 2026-08-05 amendment above already deleted the layer. D-AC2 is void by its own wording: *"**With U4 supported**, an unchanged feed returns 304."* U4 was refuted | **All four are corrected to say the capability does not exist.** No technology, table or decision changes — the amendment path for U4 was consumed on 2026-08-05, and filing a second amendment would reopen a settled measurement. P5 ships no `if_none_match`, no `if_modified_since` and no 304 branch; `tests/test_boundaries.py::test_conditional_get_has_not_been_reintroduced` prevents a future phase from re-adding it by following the stale text. Re-observed live on 2026-08-08: `Cache-Control: private, max-age=3600`, no `ETag`, no `Last-Modified`. Reasoning: [P5-DECISION-ANALYSIS §D1](P5-DECISION-ANALYSIS.md) |
| 2026-08-08 | [28 §7.2](28-discovery-redesign.md) says `http_cache` *"serves the feed; **zero network**"*, while [28 §11 D5](28-discovery-redesign.md) says *"discovery requests bypass `http_cache` **entirely**"*. `get_feed` must do one or the other | **D5 wins; §7.2's "0 requests" row is corrected to one request.** D5 is a risk mitigation with a downstream acceptance criterion behind it ([34 §P6](34-implementation-plan.md): *"discovery bypasses `http_cache` (statement counter)"*), and the failure it names is real: a 15-minute TTL serving a stale feed to a 15-minute poll leaves the watermark permanently unadvanced. Same correction the U4 amendment already applied to §4.3's "0 bytes". Reasoning: [P5-DECISION-ANALYSIS §D2](P5-DECISION-ANALYSIS.md) |
| 2026-08-08 | **The 2026-08-08 amendment above was recorded but not yet applied.** [28 §3](28-discovery-redesign.md)'s stage-4 box still described the density-adaptive body fetch, [28 §3.1](28-discovery-redesign.md)(2) still argued for the 25% crossover, and [28 §9 D7](28-discovery-redesign.md) still mitigated it with 30/20 hysteresis — all three describing a mechanism whose listing branch returns no bodies at any density | The stale text in [28 §3](28-discovery-redesign.md), [28 §3.1](28-discovery-redesign.md)(2) and [28 §9 D7](28-discovery-redesign.md) | **All three corrected. Stage 4 is body *accounting*, not a fetch:** the feed supplies ~97% of bodies in the request stage 1 already makes, the remaining ~3% are link/media posts with no selftext on any endpoint, and `score`/`num_comments`/comments are P11's. **P6 ships no threshold and no `density_threshold` key**, enforced by `tests/test_boundaries.py::test_the_density_heuristic_was_not_reintroduced`. [28 §9 D3](28-discovery-redesign.md) additionally corrected to say the HTML fallback restores **discovery, not bodies**. No technology, table or decision changes — the amendment path was consumed on 2026-08-08 and this applies it ([handover F7](PHASE-05-HANDOVER.md): an amendment must be applied, not merely recorded). Re-measured live 2026-08-08: 0 of 25 bodies on the listing, 100 of 100 on the feed | **P6** |
| 2026-08-08 | [28 §10](28-discovery-redesign.md) specifies `ALTER TABLE prescores ADD COLUMN stage`, while §4.1 of this document says `0005` **creates** `prescores` including `stage`. Both cannot hold. **Verified in P6:** `prescores` appears in no migration `0001`–`0004`, in no module under `src/`, and in none of the live database's 18 tables — the `ALTER` could never have executed | [28 §10](28-discovery-redesign.md)'s `ALTER` statement, and [05 §5.4](05-database-plan.md)'s inline `comment_id REFERENCES comments(id)` | **§4.1 wins; [28 §10](28-discovery-redesign.md) is corrected to a `CREATE`.** [33 §2.4](33-final-review.md) moved the table into this revision and §4.1 records it there. [05 §5.4](05-database-plan.md)'s column list stands, but its inline `comment_id` FK violates **M8** and is created **bare**, with the constraint deferred to `0006` where `comments` exists. No table, decision or technology changes — one document transcribed a pre-move statement | **P6** |
| 2026-08-08 | **[34 §P6](34-implementation-plan.md) task 4 cannot be implemented as written.** It requires metadata triage to write "a provisional prescore with `stage='metadata'`" for each triaged item. `prescores` carries `CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))` ([05 §5.4](05-database-plan.md)), so every row must point at a stored `Lead` — but a triage **rejection** is by definition a post that was never stored (`subreddit_scraper.py:60` persists a lead only when it clears `is_lead(min_score=3)`). Found by mutation testing: two mutations survived because the prescore branch was unreachable | [34 §P6](34-implementation-plan.md) task 4's "provisional prescore" | **P6 records the stage-3 funnel as counters on `run_events`, keyed by rejection reason, and writes no `prescores` rows.** Writing them only for *admissions* would produce a funnel that looks auditable while silently omitting every rejection — precisely [AD-10b](03-architecture.md)'s prohibition. The table and its repository still ship (§4.1 puts them in `0005`). Per-item auditability and the 2% stage-3 holdout stay with **P11**, whose Deliverables, Task 6 and `gate.metadata_holdout_rate` already own them. **No schema change and no eleventh table** — the two alternatives (storing every rejected post as a `Lead`; relaxing the CHECK and adding a `reddit_id` column) were considered and declined, the first because it changes what `leads` means to the operator, the second because it needs a schema amendment for capability P11 owns | **P6** |
| 2026-08-10 | **Four documents give four different sets of notification kinds.** §7 above fixes first delivery at **five** and names none. [22 §4.12](22-hermes-skills.md) lists **six** (`gate.reached`, `run.complete`, `lead.high_confidence`, `budget.warning`, `quality.red`, `proxy.pool_degraded`); [21 §7.1](21-hermes-architecture.md) lists **seven**; and [34 §P7](34-implementation-plan.md) task 5 names **`run.failed`**, which appears in neither list. The identities were therefore unfixed by anything, while the count was fixed at five | [22 §4.12](22-hermes-skills.md)'s six-row table read as the delivery list, and [21 §7.1](21-hermes-architecture.md)'s seven-item enumeration | **The five are `run.complete`, `run.failed`, `gate.reached`, `discovery.overflow`, `proxy.pool_degraded`**, chosen on one criterion: **a live emitter at revision `0005`**, so every policy row is driven by a test rather than merely covered (P6's F1). Three candidates were dropped for having no data source: `lead.high_confidence` needs `leads.confidence_score` (`0006`, populated P21), `quality.red` needs `quality_snapshots` (`0010`), and `budget.warning` needs an 80%-of-cap signal that does not exist — `src/ai/cost.py` raises at 100% only. Each is recorded with its trigger as [DI16](DEFERRED-IMPROVEMENTS.md). **`notify.min_confidence_alert` is deliberately not shipped**, on P6's `density_threshold` precedent: a key nothing reads is a documented capability that does not exist. Separately, [22 §4.12](22-hermes-skills.md)'s `proxy.pool_degraded` rule — *"notify if healthy < 3"* — is respecified as *a degradation recorded during this run*: `config.yaml` ships no proxy file because P0 measured direct as better and recommended buying none, so the pool is legitimately empty and the documented rule would fire on **every run forever**. No table, technology or decision changes; §7's count is met exactly. Reasoning: [P7-DECISION-ANALYSIS §D2, §D2b](P7-DECISION-ANALYSIS.md) | **P7** |
| 2026-08-10 | **`notification_log` is withdrawn, and two documents still key on it.** [22 §4.12](22-hermes-skills.md)'s Caching row says *"`notification_log` dedup key"* and [21 §13](21-hermes-architecture.md) says *"`hermes send` fails; `notification_log` records the error"* — while §3 above lists that table under **"Withdrawn and not to be reinstated"** (AD-29) | Both sentences | **§3 and AD-29 win; both are stale.** [34 §P7](34-implementation-plan.md)'s DB row was already correct — *"None — dedup rides on `run_events` + the transition guard"* — and P7 ships **no table and no migration**: dedup is a `notify.sent` row per `(run_id, kind)`, and a failure is a `notify.failed` row at `level="error"`. [21 §13](21-hermes-architecture.md)'s *"retried by the maintenance job"* is separately unbuildable today, because **nothing enqueues `maintenance`** ([DI17](DEFERRED-IMPROVEMENTS.md)); P7 routes around it by having `RunService.fail()` enqueue `finalize_run`. No technology, table or decision changes — two documents transcribed a pre-withdrawal design | **P7** |
| 2026-08-14 | **P9's three config keys have two documented homes.** [34 §P9](34-implementation-plan.md)'s Config row places them at `rules.{min_chars,skip_deleted_authors,skip_bot_authors}`; [06b](06b-deepseek-optimization.md)'s configuration listing gives **the same three keys in the same order** under `ai:`, as `ai.prefilter.{min_chars: 80, skip_deleted_authors, skip_bot_authors}`. 06b also supplies the only default value for `min_chars` that appears in any document, and [34 §P9](34-implementation-plan.md) supplies none | [06b](06b-deepseek-optimization.md)'s `ai.prefilter:` placement | **[34 §P9](34-implementation-plan.md) wins; the block ships as top-level `rules:`, and 06b's `min_chars: 80` is adopted as its default.** On authority, 34 is the definitive execution guide; on the merits, nesting the rule engine's configuration under `ai:` invites exactly the coupling **R3** forbids — a reader wiring `rules/keywords.py` to an `ai.*` key is one step from importing `src.ai` to read it, which is the boundary P9 exists to establish. The value is **cited rather than invented**: 80 is 06b's number, and it is recorded there that 06b measures a **body** (its prefilter runs immediately before an AI call), while P9's rules see titles and authors only — so the key ships with its predicate text-agnostic and unbound until **P11** supplies a body. `pipeline.rules_enabled` is a separate new block, matching [34 §P9](34-implementation-plan.md)'s Rollback row rather than [31 Sprint 3](31-execution-plan.md)'s shared `pipeline.local_qualification`, because a phase whose rollback is shared with two unbuilt phases cannot be rolled back independently as [34 §1](34-implementation-plan.md) requires. **No technology, table or decision changes** — one document listed a key block under a heading another document had already moved it out of. Reasoning: [P9-IMPLEMENTATION-REVIEW §3.8](P9-IMPLEMENTATION-REVIEW.md) | **P9** |
| 2026-08-14 | **A5 fails against the literal reading of [34 §P10](34-implementation-plan.md) task 2, *"MinHash 128 perms".*** Classic MinHash re-hashes every shingle under 128 independent permutations — O(shingles × 128). Measured on this host before any implementation existed, 2,000 items (`max_items_per_run`, so the normal case): **6.36 s** for 305-char documents and **11.11 s** for 870-char ones, against A5's **2 s**. Jaccard mean absolute error over 40 pairs: 0.0308 | The implicit reading that 128 *slots* requires 128 *permutations* | **`src/dedupe/minhash.py` ships One-Permutation Hashing with densification.** The same 128-slot signature, the same LSH banding, the same equality-count Jaccard estimator — and **more** accurate, at 0.0279 mean absolute error. The saving is structural: one hash of a shingle both picks its slot and supplies its value, so cost is O(shingles) rather than O(shingles × 128). Measured **0.27 s / 0.55 s** for signatures and **0.59 s / 0.87 s** end to end including shingling, banding and the query stage — inside A5 at both document sizes. **No technology, table, decision or dependency changes**; what changes is how a 128-component sketch is computed, which is why this is a reconciliation rather than a §11 amendment. [06c §4.2](06c-local-first-pipeline.md) anticipated it exactly: *"Performance is a design target, not a measured claim … this number is validated in testing rather than assumed here."* `datasketch` was refused under §5 and §12, the same reasoning by which P9 refused `hypothesis`. A related **measured property is pinned rather than hidden**: a 128-slot sketch estimates Jaccard to ~±0.05, so a pair at exactly 0.815 estimates 0.859 and groups — `test_near_the_threshold_the_sketch_and_exact_jaccard_can_disagree` records it so a future reader does not "fix" it by computing exact Jaccard over every candidate, which is the O(n²) cost banding exists to avoid. Reasoning: [P10-DECISION-ANALYSIS §D5](P10-DECISION-ANALYSIS.md) | **P10** |
| 2026-08-14 | **[34 §P10](34-implementation-plan.md)'s Acceptance line *"a group of N yields **N distinct pre-scores**"* is not satisfiable in P10.** [06c §4.3](06c-local-first-pipeline.md) ranks representatives by `(prescore.total, score, created_utc)`, but `src/scoring/prescore.py` is [34 §P11](34-implementation-plan.md)'s **Files** row and **P11 depends on P10**. Verified 2026-08-14: `src/` contains the `prescores` table, its repository and P6's recorded decision *not* to write to it — and no scorer. There is nothing to rank by and nothing to count. The identical shape as P9's *"11 rejection reasons implemented and counted"* | The N-distinct-pre-scores assertion, and `choose_representative`'s dependence on a pre-score | **`DedupItem.rank` carries the pre-score, defaults to `None`, and the ordering falls back to `(score, created_utc, row_id)`** — P11 fills it in without a signature change. P10 proves the checkable half: grouping preserves **N distinct members** and **mutates no per-item score field**, which is what [06c §4.4](06c-local-first-pipeline.md)'s *group for analysis, score individually* actually requires of this phase. The N-distinct-pre-scores assertion moves to **P11** with the pre-scores that make it verifiable. Building a minimal scorer inside P10 was rejected: it creates a second implementation in `src/scoring/`, outside P10's Files row, for P11 to reconcile or delete. **No table, technology or decision changes.** Reasoning: [P10-DECISION-ANALYSIS §D1](P10-DECISION-ANALYSIS.md) | **P10** |
| 2026-08-14 | **[34 §P10](34-implementation-plan.md)'s Metrics row, *"collapse rate > 8% on real data"*, is an intra-run quantity measured against a cross-run archive.** Measured on a read-only copy of `data/leads.db` (488 leads): **5.74%** at the shipped 0.85 threshold — and **flat at 5.74% all the way down to 0.60**, so loosening finds zero additional duplicates and the shortfall is not under-detection. Two structural reasons: (1) all 488 `reddit_id` values are **distinct** — the column is `UNIQUE` — so the *"3–8% residual overlap"* [28 §L3](28-discovery-redesign.md) attributes to ID dedup, the figure most plausibly behind the >8% target, is already spent before the cascade sees the data; (2) [06c §3.2](06c-local-first-pipeline.md)'s 3–8% `duplicate_exact` and 8–20% `duplicate_near` are both explicitly *"this run"*, while the live database holds **59 scrape runs across 4 subreddits from 2024-03-18 to 2026-08-13**, and 12.3% of its leads carry an empty body | Reading the Metrics row as measurable against the stored lead archive | **The measurement is recorded and the metric is read as the intra-run quantity it was always about.** The intra-run measurement belongs to **P11**, the first phase with a live call site and funnel counters — P10 is library-only ([34 §P10](34-implementation-plan.md)'s Files row lists no handler), so it structurally cannot make it. **No threshold was tuned to chase the number**, and the flatness measurement proves tuning could not have reached it. Amending the target to 5.74% was rejected: it would bake a cross-run figure into a metric written about a run. **No table, technology or decision changes.** Reasoning: [P10-DECISION-ANALYSIS §D7](P10-DECISION-ANALYSIS.md) | **P10** |
| 2026-08-14 | **[06c §4.2](06c-local-first-pipeline.md) forbids the semantic tier that [34 §P10](34-implementation-plan.md) task 3, §5 above and [AD-16](03-architecture.md) all require.** Its closing paragraph reads *"**No embedding model, no vector database, no embeddings API.** That tier is deliberately excluded: it needs new infrastructure and new per-item cost to catch a tail Jaccard already largely covers."* Meanwhile task 3 specifies *"Model2Vec + `sqlite-vec`, cosine ≥ 0.88, no-op when unavailable"*, §5's technology table lists *"Vectors — Model2Vec + `sqlite-vec`, optional"*, and AD-16 names the semantic layer as local, optional and never authoritative | [06c §4.2](06c-local-first-pipeline.md)'s exclusion paragraph | **§5, AD-16 and [34 §P10](34-implementation-plan.md) win; 06c's paragraph predates AD-16 and is corrected.** The objection it raises is answered rather than overruled: Model2Vec is a **static** distillation — one matrix lookup per token, no GPU, no server, no API — and `sqlite-vec` is a SQLite extension, not a datastore, so neither is the *"new infrastructure and new per-item cost"* the paragraph rejects. P10 ships the tier **off by default** (`dedup.semantic_threshold: null`) on a measured basis: P0 found neither library installed ([SPRINT-0-MEASUREMENTS §3.1](SPRINT-0-MEASUREMENTS.md)), so an on-by-default tier would be off in practice on every host, and a default that lies about what runs is worse than one that does not. **No table, technology or decision changes** — one document retained an exclusion a later decision had reversed. Reasoning: [P10-DECISION-ANALYSIS §D2](P10-DECISION-ANALYSIS.md) | **P10** |
| 2026-08-15 | **[06c §3.1](06c-local-first-pipeline.md) writes `100 * sum(W[k] * v for k, v in c.items())` and never supplies `W`.** Grepped across every document in `docs/` on 2026-08-15: **no frozen document gives the nine pre-score weights**, and the 0–100 bound [34 §P11](34-implementation-plan.md) asserts depends on them. Separately, **three of the nine components have no data source at revision `0006`** — `pain_phrase`, `competitor` and `subreddit_fit` all read `project.*`, and `projects`/`pain_points`/`bkb_entities` arrive in `0007` with **P12, which depends on P11**, while the entity registry behind competitor matching is P15's and `tests/test_boundaries.py::test_the_competitor_registry_was_not_wired_before_p15` fails if it is wired early | The implicit reading that P11 ships all nine components, and that the weights are specified somewhere | **Six components ship; three are declared explicitly absent, each naming the phase that supplies it (`src/scoring/ABSENT_COMPONENTS`), and the weights are cited from [04 §9.1](04-system-design.md)'s non-AI classes rather than invented** — operator decisions **D1** and **D2**. Shipping the three at `0.0` was rejected: a component contributing a silent zero is **[DI24](DEFERRED-IMPROVEMENTS.md) exactly**, inside the phase whose job is fixing DI24, and it is P6's `density_threshold` precedent — *a key nothing reads is a documented capability that does not exist*. The weights take `keyword 0.10` (split evenly across the pre-score's two keyword components), `recency 0.07` and `engagement 0.05` directly from 04 §9.1, and reuse its `subreddit 0.03` **magnitude** for `question_form` and `length`, which 04 has no analogue for; the raw cited values are **stored and normalised by their own sum at call time**, so the arithmetic is exact, the numbers stay traceable, and P12's three slot in **without re-tuning the six that shipped**. The same discipline by which P9 adopted `min_chars: 80` from 06b and P10 adopted 06c's `shingle_k`/`num_perm`/`jaccard_threshold`. **No technology, table, decision or dependency changes** — one document omitted a constant and a later phase supplied the data source for three of nine terms. Reasoning: [P11-DECISION-ANALYSIS §D1–D2](P11-DECISION-ANALYSIS.md) | **P11** |
| 2026-08-15 | **[34 §P11](34-implementation-plan.md)'s *"every collected item has a `prescores` row, admitted or not"* is not satisfiable for a metadata-triage reject, and P6 filed this exact wall.** `prescores` carries `CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))`, so every row must point at a stored `Lead` — and a triage rejection is by definition a post that was never stored. P6's 2026-08-08 reconciliation recorded that the two ways out both *"need a schema amendment for capability P11 owns"*, and P11's **DB** row is `None` while [§4.1](#41-the-frozen-chain) fixes the chain at ten revisions | Reading the line as covering the ~98% of triage rejects that are never stored | **The 2% holdout sample is persisted as real leads with `leads.source='holdout_audit'`, which is what makes its `prescores` row possible** — operator decision **D3**, and [06c §6.1](06c-local-first-pipeline.md) already required it for an independent reason: *"Audited items are persisted as real, labellable leads … Storing only the aggregate counts — as the original design did — produced a metric with no learning signal"*, because P19's yield curve can only be fitted on leads an operator can see and label. `leads.source` exists since `0006` and carries no CHECK. The other ~98% stay as `run_events` counters in P6's shape. **The line holds in full for stage 4**: every item the run *collected* gets a row, admitted or not. **No schema change, no eleventh revision, no migration.** Reasoning: [P11-DECISION-ANALYSIS §D3](P11-DECISION-ANALYSIS.md) | **P11** |
| 2026-08-15 | **The *"a group of N yields N distinct pre-scores"* criterion, transferred to P11 by the 2026-08-14 entry above, is not literally satisfiable on real data.** Measured on a read-only copy of `data/leads.db` (492 leads) on 2026-08-15: of **23** groups, **two** yield fewer distinct totals than they have members. Leads **108/109** are a repost pair created **one minute apart** with identical text, both at 0 upvotes and 0 comments — every component agrees to four decimals and both total **32.28**; leads **403/404** are three minutes apart and both total **47.61**. The cause is arithmetic, not a defect: a 60-second age difference moves the recency component by ~0.003%, which is below the second decimal place the total is rounded to | The literal reading that N members must produce N *numerically distinct* numbers | **The checkable property is *"N members, N independently computed scores, and any difference in a scored input produces a different number"*, and that is what ships.** [06c §4.4](06c-local-first-pipeline.md) asks for *"group for analysis, **score individually**"* — that each member gets its **own** score from its **own** metadata — and two posts identical in every scored dimension scoring identically **is that rule working**, not failing. Increasing the stored precision until sub-minute age differences separate the totals was rejected: it games a criterion rather than measuring a lead, and a pre-score is a ranking instrument where two decimals are already more than the ordering needs. Representative selection stays **deterministic** under the tie via P10's trailing `row_id` tie-break, so two identical runs enrich the same member — pinned by `test_two_members_identical_in_every_scored_dimension_share_a_pre_score`. **No technology, table, decision or dependency changes.** Reasoning: [P11-DECISION-ANALYSIS §D4](P11-DECISION-ANALYSIS.md) | **P11** |
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
