# 34 — Implementation Plan

> **The definitive execution guide.** 31 phases across 10 stages, 83 engineer-days.
>
> Every phase is **deployable, testable, reversible and independently mergeable.** No phase begins
> until the previous one has passed both automated ([35 §2](35-testing-strategy.md)) and manual
> ([35 §5](35-testing-strategy.md)) validation.
>
> Governed by [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md). Rationale in
> [31](31-execution-plan.md).

---

## 1. How to use this document

**One phase per session.** The workflow is fixed:

```
read the phase  →  implement  →  automated tests  →  fix  →  re-run
     →  generate the manual guide  →  WAIT FOR APPROVAL  →  next phase
```

▶ Claude must never implement more than one phase in a session, and never begin a phase whose
predecessor has not been approved. The `.claude/skills/phase-manager` skill enforces this.

### 1.1 Phase field key

| Field | Meaning |
|---|---|
| **Objective** | The one thing this phase makes true |
| **Deliverables** | What exists at the end |
| **Files** | Expected to change — a guide, not a contract |
| **DB / Config** | Migration and configuration deltas |
| **Depends on** | Phases that must be approved first |
| **Tasks** | Ordered implementation steps |
| **Acceptance** | Binary pass/fail; the phase is not done until all pass |
| **Metrics** | Numbers that prove it works, not that it exists |
| **Time / Risk** | Engineer-days · Low / Medium / High |
| **Rollback** | How to undo it in production |
| **Docs** | Documentation edits owned by this phase |

### 1.2 Universal acceptance criteria

**Every phase, without exception:**

- [ ] `ruff check` and `ruff format --check` pass
- [ ] `pytest` passes; **no live network or API calls**
- [ ] Coverage ≥70% on new modules (≥85% on `src/ai/`, `src/net/`, `src/scoring/`, `src/knowledge/`)
- [ ] All four grep fences pass ([ARCHITECTURE_FREEZE](ARCHITECTURE_FREEZE.md) R2–R5)
- [ ] `alembic upgrade head` → `downgrade -1` → `upgrade head` on a **copy** of the live DB
- [ ] **Legacy contract:** 459 leads, `intent_score` fingerprint unchanged, `GET /` byte-identical, 13 CSV columns, 17 endpoints identical
- [ ] Manual testing guide generated and executed
- [ ] Documentation edits landed

---

## 2. Phase index

| # | Phase | Stage | Rev | Days | Risk |
|---|---|---|---|---:|---|
| **P0** | Validation Sprint | A — Validation | — | 3 | None |
| P1 | Run & job schema | B — Orchestration | `0004` | 2 | Low |
| P2 | Job queue, worker, logging | B | — | 3 | **High** |
| P3 | Run service, API, run pages | B | — | 3 | Low |
| P4 | Network provider abstraction | C — Collection | — | 3 | Medium |
| P5 | RSS client & Atom parser | C | — | 2 | Low |
| P6 | Watermarks & incremental discovery | C | `0005` | 3 | **High** |
| P7 | Notification tier | C | — | 2 | Low |
| P8 | Content & dedup schema | D — Qualification | `0006` | 2 | Low |
| P9 | Rule engine | D | — | 2 | Low |
| P10 | Dedup cascade | D | — | 3 | Medium |
| P11 | Pre-score, funnel & comments | D | — | 2 | Medium |
| P12 | Project & BKB schema | E — Knowledge | `0007` | 2 | Medium |
| P13 | Website fetch & local signals | E | — | 2 | Low |
| P14 | `analyze_business` | E | — | 3 | **High** |
| P15 | Entities, evidence, lifecycle, prefix | E | — | 3 | **High** |
| P16 | Project UI | E | — | 2 | Low |
| P17 | Discovery channels & ranking | F — Targeting | `0008` | 4 | Medium |
| P18 | Review gates | F | — | 4 | Medium |
| P19 | PreAIGate & adaptive budget | G — Enrichment | `0009` | 3 | **High** |
| P20 | Batched enrichment & holdout | G | — | 4 | **High** |
| P21 | Confidence & explanations | G | — | 3 | Medium |
| P22 | Lead UI | G | — | 2 | Low |
| P23 | Hermes runtime & seam API | H — Agent | — | 3 | Medium |
| P24 | Plugin, governor, skills, cron | H | — | 4 | Medium |
| P25 | Labels & golden set | I — Quality | `0010` | 3 | Medium |
| P26 | Calibration, drift, quality page | I | — | 3 | Low |
| P27 | Exports | I | — | 2 | Low |
| P28 | Deployment | J — Production | — | 2 | Medium |
| P29 | Backup, restore, runbook | J | — | 2 | Medium |
| P30 | Security review & CI | J | — | 2 | Low |
| | | | | **83** | |

---

# STAGE A — VALIDATION

## P0 — Validation Sprint

| | |
|---|---|
| **Objective** | Convert 16 assumptions into measurements. **No production code.** |
| **Deliverables** | `scripts/probe/` (throwaway); `docs/SPRINT-0-MEASUREMENTS.md`; six go/no-go decisions |
| **Files** | `scripts/probe/*.py` only. **Nothing under `src/`** |
| **DB / Config** | None. The live database is not opened |
| **Depends on** | — |
| **Tasks** | 1. Track A: probe U1–U8 ([31 §3.1](31-execution-plan.md)) — RSS limit scope, selftext, boolean search, conditional GET, `limit=100`, host parity, shared budget, **block rate at reduced volume**<br>2. Track B: M-1…M-12 ([31 §3.2](31-execution-plan.md)) — Hermes token costs, `hermes send` cost, transport reachability, memory-review frequency<br>3. Track C: V-1…V-6 — **DeepSeek vs OpenRouter**, price re-verification, `sqlite-vec`, Model2Vec, baseline post volume, surcharge status<br>4. Record every result with method, date and raw output<br>5. Record the six go/no-go decisions |
| **Acceptance** | All 16 answered and recorded · each states which decision it settles and which document changes · conflicts flagged not smoothed · provider decision made · **no file under `src/` modified** · go/no-go recorded for RSS, direct-first networking, Hermes |
| **Metrics** | 16/16 measured · 0 files changed in `src/` · 0 rows written to `data/leads.db` |
| **Time / Risk** | **3 days · None** |
| **Rollback** | N/A — nothing changed |
| **Docs** | **New** `SPRINT-0-MEASUREMENTS.md`; correct [02 §6.2](02-research-findings.md) prices; record the provider decision in [ARCHITECTURE_FREEZE §5](ARCHITECTURE_FREEZE.md) |

> ⚠️ **If U2 and U3 are both unfavourable**, the discovery redesign still delivers −64% in steady
> state ([28 §4.2](28-discovery-redesign.md)). **If M-5 fails**, notifications switch to transport
> T3. **If U8 shows a high block rate**, residential proxies are purchased in P4. None of these is a
> redesign; all are branches the design already carries.

---

# STAGE B — ORCHESTRATION

## P1 — Run & job schema

| | |
|---|---|
| **Objective** | The database can represent a run that pauses at a human gate and resumes after a restart |
| **Deliverables** | `0004_orchestration`; `Run`/`Job`/`RunEvent` models; `RunState`/`JobState` enums; `TRANSITIONS` + `assert_transition` |
| **Files** | `migrations/versions/0004_orchestration.py` +; `src/db/models.py` ~; `src/orchestration/{__init__,states}.py` + |
| **DB** | `runs`, `jobs`, `run_events`; `scrape_runs.run_id` nullable; `ix_jobs_claim(state, available_at, priority, id)`, `ix_jobs_run`, `ix_jobs_lease`, `ix_run_events_run`. `runs.project_id` nullable, **no FK** (deferred to `0007`) |
| **Config** | None |
| **Depends on** | P0 |
| **Tasks** | 1. Write `0004` with a tested `downgrade()`<br>2. Add the three models; leave the existing 8 untouched **except `scrape_runs.run_id`**<br>3. `states.py`: **12** `RunState` values, `JobState`, the transition table, `assert_transition` raising `IllegalTransition`<br>4. `ai_calls.run_id` **and `scrape_runs.run_id`** FKs added here via `batch_alter_table` |

> ✅ **DELIVERED 2026-08-05.** Report: [PHASE-01-HANDOVER.md](PHASE-01-HANDOVER.md).
> **Corrected during implementation:** this row said *"11 `RunState` values"*.
> [04 §1.1](04-system-design.md) — the specification — lists **twelve**. Twelve were implemented and
> are asserted against an independently transcribed copy of the spec in `tests/test_orchestration.py`.
| **Acceptance** | Upgrade/downgrade/upgrade on a live-DB copy · `alembic heads` = 1 · illegal transition raises naming both states · the two `AWAITING_*_REVIEW` states have **no timeout** · `PRAGMA foreign_key_list(ai_calls)` reports the run FK · legacy contract |
| **Metrics** | 459 leads intact · 1 head · 0 changes to existing tables beyond `scrape_runs.run_id` |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | `alembic downgrade 0003` |
| **Docs** | [05 §7](05-database-plan.md) chain table; [13](13-phase-03.md) → P1–P3 mapping |

## P2 — Job queue, worker, structured logging

| | |
|---|---|
| **Objective** | Work executes durably: claimed with a lease, retried with backoff, resumed after a crash |
| **Deliverables** | `JobQueue` (enqueue/claim/heartbeat/complete/fail/reclaim); `Worker` loop; handler registry; `maintenance` handler; **structured JSON logging with redaction** |
| **Files** | `src/orchestration/{job_queue,worker}.py` +; `src/orchestration/handlers/{__init__,maintenance}.py` +; `src/obs/{logging,events}.py` +; `src/db/repositories/runs.py` +; `main.py` ~ (`worker` subcommand); `requirements.txt` ~ |
| **DB** | None |
| **Config** | `WORKER_INPROCESS=true`; `logging.format: json`, `logging.file`, `logging.level` |
| **Depends on** | P1 |
| **Tasks** | 1. `claim()` with `BEGIN IMMEDIATE` + `AND state='queued'` guard<br>2. Per-type `MAX_ATTEMPTS`; jittered exponential backoff capped at 600 s<br>3. `reclaim_expired()` each tick; heartbeat thread at `lease/3`<br>4. `Worker.run_forever` + SIGTERM/SIGINT graceful stop<br>5. **stdlib `logging` + `python-json-logger`** ([33 §3.2](33-final-review.md)); `RedactingFilter`; every record carries `run_id`/`job_id`/`project_id` when in scope<br>6. `emit_event()` → `run_events`<br>7. `maintenance` handler: four purges |

> ✅ **DELIVERED 2026-08-06.** Report: [PHASE-02-COMPLETION-REPORT.md](PHASE-02-COMPLETION-REPORT.md) ·
> Handover: [PHASE-02-HANDOVER.md](PHASE-02-HANDOVER.md).
> **Measured during implementation:** the 10-minute soak recorded *27,931 claims, 27,931 events,
> 62,168 reads, 0 errors*, and mutation testing showed that the `AND state='queued'` guard is **not**
> independently observable while `BEGIN IMMEDIATE` holds the write lock — task 1's two halves are
> lock + backstop, not two independent halves of one lock (completion report §7 F1).
> The `python-json-logger` floor is **`>=3.1`**, not the `>=2.0` [33 §3.2](33-final-review.md)
> proposed; the reason is in the completion report §3.3.
| **Acceptance** | Two workers racing claim the same job **once** · a retryable failure retries with growing backoff to `max_attempts` · lease expiry re-runs without duplicate rows · SIGTERM finishes the in-flight job and exits < 30 s · **10-minute concurrent read/write soak with zero `database is locked`** · a full log capture contains **no credential** · `main.py worker` runs standalone |
| **Metrics** | Claim contention 0 lost updates over 1,000 attempts · soak: 0 lock errors · redaction: 0 secret tokens in 10 MB of captured log |
| **Time / Risk** | **3 days · High** — SQLite writer contention is K13 |
| **Rollback** | `WORKER_INPROCESS=false` and do not run `main.py worker`; nothing enqueues yet |
| **Docs** | [03 §7](03-architecture.md) names the logging library; [00 §7](00-current-state.md) `+python-json-logger` |

## P3 — Run service, API, run pages

| | |
|---|---|
| **Objective** | The operator can start a run from the UI, watch it, cancel it, and see it resume after a restart |
| **Deliverables** | `RunService`; run endpoints; `/runs` and `/runs/<id>`; `POST /api/scrape` as a shim with an **unchanged response shape**; `poll()` helper |
| **Files** | `src/orchestration/run_service.py` +; `src/dashboard/routes_runs.py` +; `templates/{runs,run_progress}.html` +; `src/dashboard/{app,routes}.py` ~ |
| **DB** | None |
| **Config** | None |
| **Depends on** | P2 |
| **Tasks** | 1. `RunService`: create / transition / cancel / retry / progress<br>2. Duplicate-run guard → **409 with the existing run id**<br>3. `GET /api/runs/<id>/progress` from `jobs GROUP BY state`<br>4. `GET /api/runs/<id>/events?after=` incremental feed<br>5. `POST /api/scrape` → enqueue; response keeps its original keys **plus** `run_id`<br>6. Run list and progress pages; `poll()` stops on terminal, backs off after 3 errors, pauses on `document.hidden` |

> ✅ **DELIVERED 2026-08-07.** Report: [PHASE-03-COMPLETION-REPORT.md](PHASE-03-COMPLETION-REPORT.md) ·
> Handover: [PHASE-03-HANDOVER.md](PHASE-03-HANDOVER.md).
> **Three decisions this row did not settle**, resolved with the operator before implementation:
> **(a)** the run **walks both review gates** — the transition table admits no other path from
> `PENDING` to `SCRAPING`, recorded as a reconciliation in
> [ARCHITECTURE_FREEZE §11.1](ARCHITECTURE_FREEZE.md);
> **(b)** the shim runs **`scrape_subreddit` only**. The frozen job-type list
> ([04 §2.4](04-system-design.md)) has no keyword or user type, so `POST /api/scrape` and the
> scheduler no longer run those two scrapers — a deliberate, documented behaviour change until
> P5/P17. `python main.py scrape` still runs all three;
> **(c)** this row says *Config: None* and its own **Rollback** row names `orchestration.enabled` —
> a self-conflict. The key **is** implemented, default `true`, and the retained legacy thread path is
> exercised by a test that asserts scraper *construction* (asserting a 200 would pass either way).
> **Measured:** progress p95 **&lt; 50 ms at 5,000 jobs**, verified by mutation — replacing the
> `GROUP BY` with Python-side counting fails both the budget test and the query-shape test.
| **Acceptance** | `POST /api/scrape` returns the original keys · progress reflects real job counts and responds **< 50 ms** · killing the process mid-run and restarting resumes remaining jobs · cancel marks queued jobs cancelled · second run for the same project → 409 · illegal transition → 409 naming both states · `run_events` renders live |
| **Metrics** | Progress p95 < 50 ms at 5,000 jobs · resume success 10/10 kill tests · contract test on `/api/scrape` passes |
| **Time / Risk** | **3 days · Low** |
| **Rollback** | `orchestration.enabled: false` → `POST /api/scrape` uses the legacy thread path (retained) |
| **Docs** | [13](13-phase-03.md) §2.1 scheduling deferred; [09 §2](09-dashboard-plan.md) IA |

---

# STAGE C — COLLECTION

## P4 — Network provider abstraction

| | |
|---|---|
| **Objective** | Egress is a policy chosen per request class, with a degradation ladder — not a mandate |
| **Deliverables** | `NetworkProvider` ABC + capability flags; `DirectProvider`, `WebshareDatacenterProvider` (refactor of today's pool), `ManagedProxyProvider`, `NullProvider`; `NetworkPolicy`; **target-acceptance health**; `on_pool_exhausted` ladder |
| **Files** | `src/net/providers/{base,direct,managed_list,managed_gateway,null}.py` +; `src/net/policy.py` +; `src/net/{proxy_manager,http_client}.py` ~; `config.yaml` ~ |
| **DB** | None |
| **Config** | `network.policy`, `network.direct.{enabled,max_requests_per_hour,classes}`, `network.providers[]`, `network.ladder`, `network.on_pool_exhausted` |
| **Depends on** | P0 (U8 block-rate result) |
| **Tasks** | 1. Define the ABC and flags (`exposes_origin_ip`, `is_metered`, `supports_sticky`, `rotation`)<br>2. Refactor `ProxyManager` behind `WebshareDatacenterProvider` — **behaviour unchanged**<br>3. `DirectProvider` with a pinned header profile and an hourly governor<br>4. `ManagedProxyProvider` — one generic gateway class covering every residential vendor<br>5. `NetworkPolicy.acquire(request_class, session_key)`; ladder degradation<br>6. Add `target_ok`/`target_blocked`/`acceptance_rate` to `ProxyRuntime`; selection prefers acceptance<br>7. Make `exclude=tried` **explicit**<br>8. Cooldown scaled by pool pressure<br>9. Bandwidth floor → metered provider reports unhealthy |
> ✅ **DELIVERED 2026-08-08.** Report: [PHASE-04-COMPLETION-REPORT.md](PHASE-04-COMPLETION-REPORT.md) ·
> Handover: [PHASE-04-HANDOVER.md](PHASE-04-HANDOVER.md).
> **Three decisions taken before implementation**, analysed in
> [P4-DECISION-ANALYSIS.md](P4-DECISION-ANALYSIS.md):
> **(a) `policy` decides eligibility, `ladder` decides order.** The three-value enum cannot express
> "direct first, proxy as fallback", which is what P0 measured; keeping order in `ladder` ships the
> measurement with **no frozen-document change**. Ships `prefer_proxy` + `[direct, dc]`;
> **(b) target-specific block signatures are injected by the caller**, so `src/net/` is Reddit-free —
> without this, grep fence 4 cannot pass;
> **(c) degradation notices are buffered and drained after the scrape**, because `emit_event` dirties
> the caller's session and P3's F7 proved what that costs across a network call.
> **Corrected during implementation:** this row's *"all **251** `src/net/` tests"* is not
> reproducible — the only file importing `src.net` collects **114**, a third of them covering
> parsers and scoring. The measured baseline (583 suite-wide, 2 skipped) was used instead.
> **Found:** grep fence 4 was specified in three documents and ticked as delivered in
> [12 §14](12-phase-02.md), **did not exist**, and failed on seven identifiers when written.
| **Acceptance** | RSS, health and website classes go **direct** under `prefer_proxy` · bulk HTML uses a proxy when healthy and degrades per policy · degradation emits a **visible `run_events` warning** and respects the hourly cap · `ProxyLeakError` still fatal · a proxy healthy on ipify but soft-blocked on target reports **degraded** · **all 251 `src/net/` tests pass or their change is justified** · vendor swap is config-only · retries use a different exit, enforced · credentials in no log/DB/response/UI · `src/net/` has zero Reddit identifiers |
| **Metrics** | 251/251 tests · 0 credential tokens across all endpoint responses · provider construction from config for all 5 types |
| **Time / Risk** | **3 days · Medium** — touches shipped, tested code |
| **Rollback** | `network.policy: proxy_only` + `on_pool_exhausted: fail_run` → exact pre-P4 behaviour |
| **Docs** | [08](08-proxy-service.md) §3a/§7/§3.4/§10; [07 §1](07-scraping-pipeline.md); [03 §8](03-architecture.md) |

## P5 — RSS client & Atom parser

| | |
|---|---|
| **Objective** | Reddit feeds are fetched and parsed into the same post shape the HTML extractor produces |
| **Deliverables** | `RedditClient.get_feed()`; `src/discovery/feed_parser.py` using **`lxml`, no new dependency**; golden Atom fixtures; ~~conditional-GET support~~ ⛔ **STRUCK — U4 refuted in P0** ([freeze §11.1](ARCHITECTURE_FREEZE.md)). Replaced by `scripts/validate_feed_parity.py`, a live drift detector |
| **Files** | `src/discovery/{__init__,feed_parser}.py` +; `src/reddit_client.py` ~ (**additive only**); `src/net/http_client.py` ~ (~~`if_none_match`, `if_modified_since`, 304 handling~~ ⛔ struck — **`x-ratelimit-reset` instead**); `tests/fixtures/atom/*.xml` + `.expected.json` +; `main.py` ~ (`feed` command, additive — [35 §6](35-testing-strategy.md) requires a CLI); `scripts/validate_feed_parity.py` + |
| **DB** | None |
| **Config** | `discovery.rss_enabled: true`, `discovery.rss_limit: 100`, `discovery.rss_host` |
| **Depends on** | P4, P0 (U1–U6) |
| **Tasks** | 1. `get_feed(subreddits: list[str], sort, limit, query=None)` → multireddit or search URL<br>2. Atom parse with `lxml`: id, title, author, link, updated, content<br>3. **Return the same dict shape as `_extract_post`**, with `score=None`, `num_comments=None`<br>4. ~~304 handled as success-with-no-body~~ ⛔ **STRUCK**<br>5. ~~Capture and persist `ETag`/`Last-Modified`~~ ⛔ **STRUCK** — the server sends neither<br>6. Honour `x-ratelimit-reset` on 429<br>7. Golden fixtures: listing feed, search feed, empty feed, malformed feed |
| **Acceptance** | RSS and HTML produce **identical `Lead` dicts** for the same `reddit_id` except the **four documented differences** — `score`, `num_comments`, `body` *(listing pages only: the listing carries none)* and `url` *(link/media posts only: the listing title points at the destination)*, all measured and recorded in [freeze §11](ARCHITECTURE_FREEZE.md) · `limit=100` returns up to 100 entries · ~~a 304 is success~~ ⛔ **STRUCK** · a malformed feed raises `ParseError`, never a silent empty list · **no new runtime dependency** · fixtures assert field-by-field |
| **Metrics** | Parse 100 entries < 50 ms · 4 fixtures with `.expected.json` · `pip list` diff = 0 new packages |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | `discovery.rss_enabled: false`; `get_feed` is additive and simply unused |
| **Docs** | [07](07-scraping-pipeline.md) new §2a; [04 §5](04-system-design.md) `get_feed`; [00 §7](00-current-state.md) |

> ✅ **DELIVERED 2026-08-08.** Report: [PHASE-05-COMPLETION-REPORT.md](PHASE-05-COMPLETION-REPORT.md) ·
> Handover: [PHASE-05-HANDOVER.md](PHASE-05-HANDOVER.md) ·
> Review: [P5-IMPLEMENTATION-REVIEW.md](P5-IMPLEMENTATION-REVIEW.md).
> **Five decisions taken before implementation**, analysed in
> [P5-DECISION-ANALYSIS.md](P5-DECISION-ANALYSIS.md): **(a)** conditional GET is **not built** — the
> U4 amendment already deleted it, so this row's Deliverables, Files, Tasks 4–5 and one acceptance
> criterion are struck as a [§11.1 reconciliation](ARCHITECTURE_FREEZE.md); **(b)** `get_feed`
> bypasses `http_cache` per [28 D5](28-discovery-redesign.md); **(c)** a `feed` CLI is added because
> [35 §6](35-testing-strategy.md) requires one; **(d)** `created_utc` prefers `<published>` over
> `<updated>`, body comes from `div.md`; **(e)** the transport keeps returning `None` — raising is P6's.
> **Found, and this is the phase's most consequential result:** the operator-requested live parity
> validator failed on its first run, 25 of 25 posts, and proved that **the HTML listing page carries
> no selftext at all** — refuting [28 §2.2](28-discovery-redesign.md) and invalidating the premise of
> **P6 task 5's density heuristic**. Two amendments recorded in [freeze §11](ARCHITECTURE_FREEZE.md).
> P6 owns the redesign; P5 did not attempt it.

## P6 — Watermarks & incremental discovery

| | |
|---|---|
| **Objective** | Collection costs one request when nothing has changed, and never silently loses a post |
| **Deliverables** | `0005_discovery`; `discovery_watermarks`; **`prescores` (moved here, [33 §2.4](33-final-review.md))**; the six-stage discovery pipeline; adaptive polling policy; overflow detection |
| **Files** | `migrations/versions/0005_discovery.py` +; `src/discovery/{watermarks,policy}.py` +; `src/db/repositories/discovery.py` +; `src/scrapers/base.py` ~; `src/orchestration/handlers/discover.py` + |
| **DB** | `discovery_watermarks`; **`prescores`** incl. `stage` — `comment_id` created **without** a `REFERENCES` clause, FK added in `0006` |
| **Config** | `discovery.{min_interval,max_interval,window_target,empty_backoff,empty_cap,yield_boost,density_threshold}` |
| **Depends on** | P5 |
| **Tasks** | 1. `0005` with watermarks + prescores<br>2. Stage 1 change detection — one multireddit request, ~~conditional GET~~ ⛔ **struck, U4 refuted**<br>3. Stage 2 watermark diff — single `IN` query; **overflow check**: feed's oldest newer than `last_seen_utc` → **error + HTML fallback + shorten interval**<br>4. Stage 3 metadata triage on title + snippet → provisional prescore with `stage='metadata'`<br>5. ⚠️ **REDESIGN REQUIRED** — ~~Stage 4 density-adaptive body fetch (listing ≥25%, permalink <25%, hysteresis 30/20)~~. **P5 measured that an HTML listing page carries no selftext**, so the "listing ≥25%" branch fetches a page with no bodies in it ([freeze §11](ARCHITECTURE_FREEZE.md), 2026-08-08). The feed already supplies bodies for ~97% of posts, so the real choice is *feed body vs permalink fetch*, not *listing vs permalink*. See [PHASE-05-HANDOVER.md](PHASE-05-HANDOVER.md) §4<br>6. Stage 5 keyword search via RSS<br>7. `policy.next_interval()` — EWMA rate, empty backoff, yield boost, clamps. **Zero AI, no `src.ai` import**<br>8. **Discovery bypasses `http_cache`** (D5) — `get_feed` already does; assert it |
| **Acceptance** | A poll with nothing new issues **exactly one** request and creates zero rows · overflow is **logged as an error** and triggers HTML fallback (fixture: 150 new posts) · **steady-state daily requests ≤ 80** · cold start collects ≥95% of what the HTML design collects · `discovery/policy.py` makes **zero** AI calls and imports no `src.ai` · discovery bypasses `http_cache` (statement counter) · with `rss_enabled: false` the HTML path passes every test |
| **Metrics** | Idle poll = 1 request · steady state ≤ 80 req/day · overflow detection 10/10 · policy computes an interval in < 1 ms |
| **Time / Risk** | **3 days · High** — K9 overflow, K8 RSS dependency |
| **Rollback** | `discovery.rss_enabled: false` → HTML listing walk, exactly as before; `alembic downgrade 0004` |
| **Docs** | [28 §10](28-discovery-redesign.md) `prescores.stage` in `CREATE TABLE`; [05](05-database-plan.md) chain + deferred FK; [07 §5](07-scraping-pipeline.md), [07 §7](07-scraping-pipeline.md), [07 §8](07-scraping-pipeline.md); [06c §3](06c-local-first-pipeline.md) L0/L1 |

> ✅ **DELIVERED 2026-08-08.** Report: [PHASE-06-COMPLETION-REPORT.md](PHASE-06-COMPLETION-REPORT.md) ·
> Handover: [PHASE-06-HANDOVER.md](PHASE-06-HANDOVER.md) ·
> Review: [P6-IMPLEMENTATION-REVIEW.md](P6-IMPLEMENTATION-REVIEW.md).
> **Task 5's redesign, which this row asked for:** the density-adaptive body fetch is **deleted, not
> replaced.** Its inputs do not exist — the listing branch returns no bodies at any density, the feed
> already supplies ~97% in the request stage 1 makes anyway, the remaining ~3% are link/media posts
> with no selftext on any endpoint, and `score`/`num_comments`/comments belong to **P11**. Stage 4 is
> now body *accounting* (`body_source`), and no `density_threshold` key ships. Three
> [§11.1 reconciliations](ARCHITECTURE_FREEZE.md) apply the amendment to [28 §3](28-discovery-redesign.md),
> §3.1(2), D3 and D7.
> **Two further conflicts were found and resolved during implementation**, both recorded as
> reconciliations: [28 §10](28-discovery-redesign.md)'s `ALTER TABLE prescores` is a `CREATE` (the
> table exists in no earlier migration), and **task 4's "provisional prescore" cannot be written** —
> the CHECK constraint requires every prescore to name a stored `Lead`, and a triage rejection is a
> post that was never stored. **Found by mutation testing**, when two mutations survived because the
> branch was unreachable. P6 records the stage-3 funnel as **counters keyed by rejection reason**;
> per-item auditability and the 2% holdout remain P11's, which already owns them.
> **N2 closed:** the transport now raises `TransportError` carrying `retryable`, and the six frozen
> `RedditClient` methods keep their `None` contract by catching it.

## P7 — Notification tier

| | |
|---|---|
| **Objective** | The operator learns what happened, at **zero token cost** |
| **Deliverables** | `src/notify/` — policy table, SQL renderers, three-implementation transport; five notification kinds |
| **Files** | `src/notify/{__init__,service,renderers,transport}.py` +; `src/orchestration/handlers/*.py` ~ (emit points); `config.yaml` ~ |
| **DB** | None — dedup rides on `run_events` + the transition guard (AD-29) |
| **Config** | `notify.{enabled,transport,telegram_chat_id,quiet_hours_utc,min_confidence_alert}`; `TELEGRAM_BOT_TOKEN` in `.env` |
| **Depends on** | P3, P0 (M-5, M-9, M-10) |
| **Tasks** | 1. Deterministic policy table ([22 §4.12](22-hermes-skills.md)) — 5 kinds<br>2. Markdown renderers **from SQL**; no model, no HTTP client import<br>3. Transport interface + T1 (`hermes serve`) / T2 (subprocess) / T3 (**direct Bot API**), selected by config<br>4. Query-based dedup against `run_events`<br>5. Quiet hours, with `run.failed` and `budget.warning` exempt<br>6. Retry on failure; failures recorded, never silent<br>7. Add the Telegram token to `RedactingFilter` |
| **Acceptance** | A completed run delivers a message **within 10 s** · **zero tokens consumed** · `src/notify/renderers.py` imports neither `src.ai` nor an HTTP client · re-running `finalize_run` after lease expiry sends **one** message, not two · transport down → recorded, run unaffected · quiet hours suppress non-critical only · bot token in no log |
| **Metrics** | Token cost = **0** · duplicate rate = 0 over 20 lease-expiry replays · delivery p95 < 10 s |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | `notify.enabled: false` |
| **Docs** | [21 §7.1](21-hermes-architecture.md) transport; [09](09-dashboard-plan.md) new §8 |

---

# STAGE D — LOCAL QUALIFICATION

## P8 — Content & dedup schema

| | |
|---|---|
| **Objective** | The schema can hold comments, duplicate groups and the four new lead columns |
| **Deliverables** | `0006_content_and_dedup`; `Comment` model; `leads` +4 columns; deferred FK from `0005` closed |
| **Files** | `migrations/versions/0006_content_and_dedup.py` +; `src/db/models.py` ~ |
| **DB** | `comments`, `dedup_groups`, `dedup_members`, `minhash_bands`; `leads` + `project_id`, `confidence_score`, `analysis_status`, `source`; `prescores.comment_id` FK added; `project_id` **nullable** on dedup tables (FK deferred to `0007`) |
| **Config** | None |
| **Depends on** | P6 |
| **Tasks** | 1. Table creation in dependency order: `comments` → `dedup_groups` → `dedup_members` → `minhash_bands`<br>2. `leads` ALTERs with defaults — metadata-only in SQLite<br>3. `ux_comments_hash` on `body_hash`<br>4. `batch_alter_table` for `prescores.comment_id` |
| **Acceptance** | Upgrade/downgrade/upgrade on a live-DB copy · **459 rows get `project_id=NULL`, `confidence_score=NULL`, `analysis_status='not_analyzed'`, `source='scrape'`** — all semantically correct · no row rewritten · one head |
| **Metrics** | 459 intact · `intent_score` fingerprint unchanged · ALTER completes in < 1 s |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | `alembic downgrade 0005` |
| **Docs** | [05](05-database-plan.md) §7 + §7.1a ordering |

## P9 — Rule engine

| | |
|---|---|
| **Objective** | Every deterministic rejection reason works and is counted |
| **Deliverables** | `src/rules/` — keywords, negatives, structural, authors, competitors |
| **Files** | `src/rules/{__init__,keywords,structural,authors,competitors}.py` + |
| **DB** | None |
| **Config** | `rules.{min_chars,skip_deleted_authors,skip_bot_authors}` |
| **Depends on** | P8 |
| **Tasks** | 1. Keyword matching with tiers and negatives — set membership + compiled regex<br>2. Structural regex: hiring, giveaway, megathread, AMA, promo<br>3. Author heuristics: `[deleted]`, AutoModerator, `*Bot`, allowlist<br>4. Competitor matching **via the entity registry interface** (stub until P15; dictionary fallback)<br>5. Every rejection returns a **counted reason string** |
| **Acceptance** | **Four** rejection predicates implemented — `negative_term`, `structural_noise`, `too_short`, `bot_or_deleted` — each returning a reason drawn from `RejectionReason`'s spelling; three operate on data P9's callers have, and `too_short` is text-agnostic until P11 binds it to a body. **Counting them is P19's** · **`grep -rn "import.*src\.ai" src/rules/` returns nothing** · a post using only a competitor alias matches · negative terms are case- and punctuation-insensitive · property test: no input crashes |
| **Metrics** | Rule evaluation < 1 ms/item · 100% branch coverage on rejection reasons |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | `pipeline.rules_enabled: false` |
| **Docs** | [06c §2](06c-local-first-pipeline.md) |

> **Reconciliation, P9, 2026-08-14 — the Acceptance row said *"11 rejection reasons implemented and
> counted"*, and that was not satisfiable.** §P19's Deliverables row below claims the same eleven
> (*"`PreAIGate` with 11 counted reasons"*), and both cannot be true.
> Mapping [06c §3.2](06c-local-first-pipeline.md)'s table to the phase that can produce each, P9's
> five Tasks reach **four**; the other seven need a content hash (P10), a MinHash index (P10),
> comments (P11), a pre-score (P11), a response cache (P19/P20) or an `ai_budgets` row (`0009`, P19).
> *"Counted"* was independently unsatisfiable: P9's **DB** row is `None`, so there is no store to
> count into, and `GateReport` lives in `src/ai/gate.py` — across the **R3** boundary from
> `src/rules/`. Operator decision **D2**, recorded in
> [P9-DECISION-ANALYSIS.md](P9-DECISION-ANALYSIS.md). **§P19's row is deliberately left unchanged:**
> it is the one that was correct. The Objective row is likewise untouched — *"works and is counted"*
> remains true of the pipeline as a whole, once P19 supplies the counter.

## P10 — Dedup cascade

| | |
|---|---|
| **Objective** | Near-identical discussions are analysed once and scored individually |
| **Deliverables** | `src/dedupe/` — exact, MinHash+LSH, optional semantic, representative selection |
| **Files** | `src/dedupe/{__init__,exact,minhash,semantic,groups}.py` +; `requirements.txt` ~ |
| **DB** | None (tables from P8) |
| **Config** | `dedup.{exact_enabled,minhash_enabled,shingle_k,num_perm,jaccard_threshold,semantic_threshold}` |
| **Depends on** | P9, P0 (V-3/V-4) |
| **Tasks** | 1. Exact: `sha256(normalise(title + "\n" + body))`<br>2. MinHash 128 perms, char 5-grams, LSH banding, Jaccard ≥ 0.85<br>3. Semantic tier: Model2Vec + `sqlite-vec`, cosine ≥ 0.88, **no-op when unavailable**<br>4. `choose_representative` by `(prescore, score, created_utc)`<br>5. Persist `dedup_groups` + `dedup_members` |
| **Acceptance** | Tier 3 groups paraphrase pairs sharing no 5-grams; tiers 1–2 do not · **with the semantic layer disabled the same run produces the identical lead set** · a group of N yields **N distinct pre-scores** · **MinHash indexes and queries 2,000 items in < 2 s CPU** (assumption A5, measured) · no `src.ai` import |
| **Metrics** | 2,000 items < 2 s · collapse rate > 8% on real data · 0 leads lost when tier 3 is off |
| **Time / Risk** | **3 days · Medium** — A5 is unmeasured |
| **Rollback** | `dedup.minhash_enabled: false` / `semantic_threshold: null` |
| **Docs** | [06c §4](06c-local-first-pipeline.md); [AD-16](03-architecture.md) degradation confirmed |

> **Reconciliations, P10, 2026-08-14 — four, each carrying the measurement that forced it.** Recorded
> in full at [freeze §11.1](ARCHITECTURE_FREEZE.md) and reasoned at
> [P10-DECISION-ANALYSIS.md](P10-DECISION-ANALYSIS.md). **None is a §11 amendment**: no technology,
> table, decision or dependency changes in any of them.
>
> 1. **Task 2's *"MinHash 128 perms"*, read as 128 independent permutations, misses A5 by 3–5.5×** —
>    measured **6.36 s / 11.11 s** for 2,000 items against a **2 s** budget, before any code was
>    written. `src/dedupe/minhash.py` ships **One-Permutation Hashing**: the same 128-slot signature,
>    the same banding, the same estimator, measured **0.27 s / 0.55 s** and *more* accurate.
>    **A5 is now measured and met** — 0.59 s / 0.87 s end to end.
> 2. **The Acceptance row's *"a group of N yields N distinct pre-scores"* is not satisfiable here.**
>    `src/scoring/prescore.py` is §P11's Files row and **P11 depends on P10**. `DedupItem.rank`
>    carries the pre-score as an injected value; the assertion moves to P11. P10 proves grouping
>    preserves N distinct members and mutates no per-item score.
> 3. **The Metrics row's *"collapse rate > 8% on real data"* is an intra-run quantity.** Measured
>    **5.74%** on the live 488 leads and **flat down to a 0.60 threshold**, because ID-level dedup is
>    already spent (all 488 `reddit_id` distinct) and the corpus is 59 runs over 29 months rather
>    than one run. The intra-run measurement belongs to **P11**, which has the first live call site.
>    No threshold was tuned.
> 4. **[06c §4.2](06c-local-first-pipeline.md) forbade the tier task 3 requires** — *"No embedding
>    model, no vector database, no embeddings API"* — while [freeze §5](ARCHITECTURE_FREEZE.md) lists
>    Model2Vec and `sqlite-vec` and [AD-16](03-architecture.md) names the layer. 06c predates AD-16
>    and is corrected; the tier ships **off by default**, because P0 measured both libraries absent.
>
> **The Files row is honoured, and two files sit outside it deliberately.** `src/dedupe/__main__.py`
> exists because [35 §1](35-testing-strategy.md) requires a manual guide a non-developer can execute
> and this phase adds no page, endpoint or row — the precedent P5's `feed` CLI, P6's `triage.py` and
> P9's `python -m src.rules` each set, under §1.1's *"a guide, not a contract"*. And P10 declares its
> two rejection reasons **in `src/dedupe/`** rather than extending `src/rules/REASONS` as
> [PHASE-09-HANDOVER §3.3](PHASE-09-HANDOVER.md) proposed, because `src/rules/__init__.py` is outside
> this row and [lock §3](EXECUTION_MODE_LOCK.md) step 4 forbids editing it. The six-of-eleven subset
> claim is asserted across both packages by `tests/test_rules_vocabulary.py`.

## P11 — Pre-score, funnel & comments

| | |
|---|---|
| **Objective** | Every collected item has a deterministic 0–100 score with stored components, and the funnel is visible |
| **Deliverables** | `scoring/prescore.py`; full-stage prescores; funnel counters on the run page; `CommentScraper` ordered by pre-score; **Stage-3 holdout audit** |
| **Files** | `src/scoring/{prescore,features}.py` +; `src/scrapers/comment_scraper.py` +; `src/db/repositories/comments.py` +; `templates/run_progress.html` ~ |
| **DB** | None |
| **Config** | `scraping.{max_comments_per_post,max_comment_posts,min_post_comments_for_comment_fetch}`; `gate.metadata_holdout_rate: 0.02` |
| **Depends on** | P10 |
| **Tasks** | 1. Nine-component pre-score, all components persisted, `stage='full'`<br>2. Funnel counts to `run_events` and the progress page<br>3. `CommentScraper` — candidates **ordered by pre-score**, skipping below the admission floor<br>4. Score back-fill for search-sourced leads during comment fetch<br>5. `body_hash` dedup with `begin_nested()` + `IntegrityError` skip<br>6. **Stage-3 holdout**: 2% of metadata-triage rejects get bodies fetched and full-scored |
| **Acceptance** | Every collected item has a `prescores` row, admitted or not · **A2 measured** — real hard-filter rate recorded against the assumed 73% · comment candidates ordered by pre-score; collected comments fall ≥5% with **no** reduction in admitted items · re-running comment extraction creates zero duplicates · search-sourced `score` back-filled · **metadata-triage miss rate published and < 5%** · `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` = **0** |
| **Metrics** | Filter rate measured · comment requests −5% or better · triage miss rate < 5% · **0 AI calls** |
| **Time / Risk** | **2 days · Medium** |
| **Rollback** | `pipeline.prescore_enabled: false` → items keep `intent_score` only |
| **Docs** | [06c §3](06c-local-first-pipeline.md), [06c §8](06c-local-first-pipeline.md) worked example re-derived |

> **End of Stage D is the best debugging position in the plan.** The full funnel runs, every
> rejection has a counted reason, nothing is probabilistic, and nothing has cost money.

> **Reconciliations, P11, 2026-08-15 — three, each carrying the measurement that forced it.**
> Recorded in full at [freeze §11.1](ARCHITECTURE_FREEZE.md) and reasoned at
> [P11-DECISION-ANALYSIS.md](P11-DECISION-ANALYSIS.md). **None is a §11 amendment**: no technology,
> table, decision or dependency changes in any of them, and P11 ships **no migration**.
>
> 1. **[06c §3.1](06c-local-first-pipeline.md) never supplies `W`, and three of its nine components
>    have no data source at `0006`.** Six ship; `pain_phrase`, `competitor` and `subreddit_fit` are
>    **declared absent** with the phase that supplies each (P12, P15, P12), because a component
>    contributing a silent zero is DI24 inside the phase that fixes DI24. The weights are cited from
>    [04 §9.1](04-system-design.md)'s non-AI classes and normalised at call time, so P12's three slot
>    in without re-tuning the six. **D1, D2.**
> 2. **The `prescores` CHECK wall P6 filed is discharged without a schema change.** The 2% holdout
>    sample is persisted as real leads with `source='holdout_audit'` — which
>    [06c §6.1](06c-local-first-pipeline.md) already required so the audit has a learning signal —
>    and that is what makes its `prescores` row possible. **D3.**
> 3. **"A group of N yields N distinct pre-scores" is not literally satisfiable.** Measured on the
>    live 492 leads: two of 23 real groups are repost pairs created **one minute apart** whose
>    components agree to four decimals. What ships is the property that carries the meaning — N
>    independently computed scores, distinct whenever any scored input differs — with selection kept
>    deterministic under the tie. **D4.**
>
> **A2 is measured**, which is what the Acceptance row asks: *"real hard-filter rate **recorded**
> against the assumed 73%"*. On the full 492-lead archive the hard filters remove **75.4%** against
> the assumed 73% — but **68.9 points of that is `out_of_window`**, because the archive spans 29
> months and the window is 30 days. Restricted to the in-window population the hard filters remove
> **20.9%** and **73.2%** are admitted. Both numbers are published rather than one being chosen:
> [06c §8](06c-local-first-pipeline.md)'s 73% counts `already_analyzed` (26% of its example, and
> P19/P20's response cache) and `negative_term` (its single largest hard filter, and
> `discovery.negative_terms` ships **empty**), neither of which P11 can produce. The intra-run
> measurement arrives with them.
>
> **The Files row is honoured, and the files outside it are enumerated in
> [PHASE-11-COMPLETION-REPORT §2](PHASE-11-COMPLETION-REPORT.md) with a reason each.** The row lists
> four modules and a template, and **every acceptance criterion in this phase needs a live call
> site** — *"every collected item has a `prescores` row"*, *"A2 measured"*, *"comment requests −5%"*,
> *"miss rate published"*, *"`COUNT(*) FROM ai_calls` = 0"* — while the row names no handler. Wiring
> is therefore the phase, under [§1.1](#)'s *"a guide, not a contract"* and the precedent P5's `feed`
> CLI, P6's `triage.py`, P9's `python -m src.rules` and P10's `__main__.py` each set.

---

# STAGE E — KNOWLEDGE

## P12 — Project & BKB schema

| | |
|---|---|
| **Objective** | The schema can hold a versioned, evidenced, entity-resolved knowledge base |
| **Deliverables** | `0007_projects_and_knowledge_base`; 12 tables (+2 conditional); all deferred FKs closed |
| **Files** | `migrations/versions/0007_projects_and_knowledge_base.py` +; `src/db/models.py` ~ |
| **DB** | `projects`, `website_snapshots`, `bkb`, `bkb_sections`, `personas`, `pain_points`, `intent_signals`, `bkb_entities`, `bkb_entity_aliases`, `bkb_links`, `bkb_evidence`, `bkb_suggestions`, conditional `bkb_embeddings` + `bkb_embedding_meta`. Closes FKs on `ai_calls.project_id`, `runs.project_id` (+ `NOT NULL`), `dedup_groups.project_id`, `minhash_bands.project_id` |
| **Config** | None |
| **Depends on** | P11 |
| **Tasks** | 1. Create in the [05 §7.1a](05-database-plan.md) order (15 steps)<br>2. **Wrap `sqlite-vec` in try/except** — a missing extension logs a warning and skips both vector tables<br>3. `batch_alter_table` for all four deferred FKs<br>4. `staleness_days` seeded per section group; Group C = `NULL` |
| **Acceptance** | Upgrade/downgrade/upgrade on a live-DB copy · **with `sqlite-vec` unavailable the migration completes** and `/health` reports `semantic_layer: disabled` · `PRAGMA foreign_key_list` reports all four constraints · one head · `payload_json IS NULL` for exactly `buyer_personas`/`pain_points`/`buying_signals`, **NOT NULL for the other twenty including `ideal_customer_profiles`** |
| **Metrics** | 459 intact · 4 FKs present · migration < 5 s |
| **Time / Risk** | **2 days · Medium** — the largest revision |
| **Rollback** | `alembic downgrade 0006` |
| **Docs** | [05 §5.1](05-database-plan.md), [05 §7.1a](05-database-plan.md) |

## P13 — Website fetch & local signals

| | |
|---|---|
| **Objective** | A URL becomes clean text plus locally extracted facts, with **zero AI** |
| **Deliverables** | `WebsiteFetcher` (**direct egress**, AD-25); `site_signals.py`; L1 fingerprint cache |
| **Files** | `src/ai/{website_fetcher,site_signals}.py` +; `requirements.txt` ~ (`+trafilatura`); `tests/fixtures/sites/*.html` + |
| **DB** | Writes `website_snapshots` |
| **Config** | `website.{max_pages,max_depth,max_total_chars,per_page_timeout,cache_ttl_days}` |
| **Depends on** | P12, P4 |
| **Tasks** | 1. Bounded crawl: landing + ≤6 priority paths, ≤40 KB, 15 s/page<br>2. **`request_class="website"` → direct egress**<br>3. `trafilatura` extraction, BeautifulSoup fallback<br>4. Local signals: competitor regex, pricing regex, tech markers, schema.org JSON-LD, social links, nav taxonomy<br>5. `content_hash`; L1 cache hit within 7 days = **zero fetches**<br>6. `thin_content` when < 500 chars<br>7. URL scheme allowlist; `file://`/`javascript:` → 422 |
| **Acceptance** | Fetch goes **direct**, not through the proxy pool · unchanged fingerprint within 7 days makes **zero** fetches · SPA shell sets `thin` and the run still completes · a 404 fails with a readable message · `file://` rejected at validation · **zero AI calls in this phase** |
| **Metrics** | ≤7 requests per project version · L1 hit = 0 requests · extraction ≤ 40 KB |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | `alembic downgrade 0006`; no consumer yet |
| **Docs** | [08 §10](08-proxy-service.md) and [14 §9.1](14-phase-04.md) — **egress is direct** ([33 §2.2](33-final-review.md)) |

## P14 — `analyze_business`

| | |
|---|---|
| **Objective** | **One** AI call produces 23 validated BKB sections, with per-section failure isolation |
| **Deliverables** | `AIService.analyze_business()`; `BusinessIntelligence` schemas; `business_intelligence.v1.md`; section persistence with supersede |
| **Files** | `src/ai/{service,schemas}.py` ~; `src/ai/prompts/business_intelligence.v1.md` ~; `src/knowledge/{bkb,sections}.py` +; `src/db/repositories/knowledge.py` +; `src/orchestration/handlers/website.py` + |
| **DB** | Writes `bkb`, `bkb_sections`, `personas`, `pain_points`, `intent_signals` |
| **Config** | `ai.max_tokens.business_intelligence: 12000` |
| **Depends on** | P13, P0 (V-1 provider decision) |
| **Tasks** | 1. Finalise the 23-section Pydantic schema<br>2. Prompt with all six mandatory sections incl. `# JSON Shape`<br>3. **Per-section validation** — a failure marks that section `incomplete`, the other 22 persist<br>4. Section supersede; typed tables upserted on `(bkb_id, slug)`; vanished slugs soft-deleted<br>5. L2 profile cache on fingerprint + prompt version<br>6. Slug pattern and duplicate validation |
| **Acceptance** | **Exactly one** `ai_calls` row with `stage='business_intelligence'` per analysis · all 23 sections persist · total cost **< $0.05** and displayed · re-analysis of an unchanged fingerprint makes **zero** calls · a forced schema failure in one section leaves the other 22 persisted · 1–5 personas, 3–12 pains, 3–12 signals · golden-set comparison shows no regression vs the staged baseline |
| **Metrics** | 1 call/project · < $0.05 · 23/23 sections · repair rate < 5% |
| **Time / Risk** | **3 days · High** — K5, and the largest single call |
| **Rollback** | `ai.enabled: false`; BKB tables sit empty and nothing downstream exists yet |
| **Docs** | [06 §3](06-ai-pipeline.md); [06d](06d-ai-budget-and-scale.md) becomes the **cost authority** ([33 §2.5](33-final-review.md)) |

## P15 — Entities, evidence, lifecycle, prefix

| | |
|---|---|
| **Objective** | Knowledge is queryable, evidenced, age-aware, and **structurally protected from regeneration** |
| **Deliverables** | `EntityRegistry` 4-tier resolver; alias generation; `bkb_evidence` with typed sources; `lifecycle.py` with the **origin guard**; `PrefixBuilder`; `SemanticIndex` |
| **Files** | `src/knowledge/{entities,links,evidence,lifecycle,prefix,semantic_index,suggestions}.py` + |
| **DB** | Writes entities, aliases, links, evidence |
| **Config** | `knowledge.prefix_token_budget: 4000` |
| **Depends on** | P14 |
| **Tasks** | 1. `resolve()`: exact → normalised → fuzzy (Levenshtein ≤2 on tokens >5) → embedding (≥0.82)<br>2. Five alias generators: site comparison pages, casing/spacing, misspellings, acronyms, domains<br>3. Evidence with `source_type`; **`ai_inference` carries no quote**; website quotes validated as literal substrings<br>4. **Origin guard**: `regenerate_section` deletes only `origin='website'`; `reddit_learned`/`operator` rows are re-pointed to the new `bkb_id`, never deleted<br>5. `staleness_days` per group; Group C never stales; **staleness never alters a score**<br>6. `PrefixBuilder` — budget enforced, **drops logged**<br>7. `SemanticIndex` no-ops cleanly when disabled |
| **Acceptance** | Resolver returns the canonical entity for exact, casing, spacing and single-character-misspelling forms · every claim has ≥1 evidence row; **zero evidence fails validation** · `ai_inference` cannot be auto-promoted, including by repetition · **regenerate every section twice and lose no `reddit_learned` or `operator` row** (seed rows of each origin first, or the test proves nothing) · advance the clock past every threshold, re-score, **every score unchanged** · Group C sections have `staleness_days IS NULL` · prefix ≤ budget with drops logged and visible · a `merged_into` entity resolves to its survivor |
| **Metrics** | Resolution < 1 ms · prefix ≤ 4,000 tokens · 0 rows lost across 2 regenerations |
| **Time / Risk** | **3 days · High** — K5 is the most likely real bug in the plan |
| **Rollback** | `alembic downgrade 0006` |
| **Docs** | [06e](06e-business-knowledge-base.md), [06h](06h-knowledge-lifecycle.md) |

## P16 — Project UI

| | |
|---|---|
| **Objective** | The operator can browse, edit and regenerate the knowledge base |
| **Deliverables** | `/projects`, `/projects/<id>` with four BKB bands; inline edit; per-section regenerate; cost chip; prefix markers |
| **Files** | `src/dashboard/routes_projects.py` +; `templates/{base,projects,project_detail}.html` +/~; `main.py` ~ (`project add`) |
| **DB** | None |
| **Config** | None |
| **Depends on** | P15 |
| **Tasks** | 1. Extract `base.html`; convert `index.html` to extend it with **byte-identical output**<br>2. Four bands; `▣`/`○` prefix markers; origin markers per row<br>3. Inline edit → `PUT` → toast; sets `edited_by_user`, bumps that section's version only<br>4. Regenerate with confirm-on-edited (409 unless `?force=true`)<br>5. Cost chip and prefix token count<br>6. `thin_content` amber banner |
| **Acceptance** | **`GET /` renders byte-identically after the `base.html` extraction** (snapshot diff) · editing bumps only that section's version · regenerating one section does not alter others · prefix membership rendered correctly · Group C shows **no** age badge · with no API key `/projects` explains why and links to Settings, and `main.py scrape` still works |
| **Metrics** | `GET /` snapshot identical · page < 500 ms · 23 sections rendered |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | Remove the blueprint registration |
| **Docs** | [09 §3.2](09-dashboard-plan.md) |

---

# STAGE F — TARGETING

## P17 — Discovery channels, validation & ranking

| | |
|---|---|
| **Objective** | The ICP becomes a ranked, live-validated list of real subreddits — with **zero AI calls** |
| **Deliverables** | `0008_targeting`; four discovery channels; live validator; five-component ranker; deterministic keyword generation |
| **Files** | `migrations/versions/0008_targeting.py` +; `src/discovery/{candidates,validator,ranker,service}.py` +; `src/ai/keyword_generator.py` +; `src/orchestration/handlers/{discovery,keywords}.py` +; `src/reddit_client.py` ~ (`get_related_subreddits`) |
| **DB** | `project_subreddits`, `project_keywords` |
| **Config** | `limits.{max_subreddits_per_run,max_keywords_per_subreddit}`, `discovery.min_subscribers` |
| **Depends on** | P16, P6 |
| **Tasks** | 1. Channel 1 — BKB-proposed (already in the P14 output, **no extra call**)<br>2. Channel 2 — sitewide search harvest with hit-density counting, **via RSS**<br>3. Channel 3 — sidebar graph, one hop<br>4. Channel 4 — semantic match of descriptions against ICP vectors<br>5. Validator — live, uncached; four rejection reasons persisted<br>6. Ranker — five components persisted; **log-scaled** subscriber weight<br>7. **Keyword generation is a set intersection** over BKB sections — zero AI |
| **Acceptance** | ≥10 validated candidates for a typical B2B SaaS ICP · every candidate records `source_channels` · a hallucinated subreddit is rejected `not_found` and shown · **≥70% of proposed subreddits survive validation** · ranking components persisted and rendered · **`SELECT COUNT(*) FROM ai_calls WHERE run_id=? AND stage IN ('subreddit_recommendation','keyword_generation')` = 0** |
| **Metrics** | ≥10 candidates · ≥70% survival · **0 AI calls** · validation ≤ 2 requests/candidate |
| **Time / Risk** | **4 days · Medium** |
| **Rollback** | `alembic downgrade 0007`; runs use a manual subreddit list, which Stage C already supports |
| **Docs** | [15](15-phase-05.md) → P17/P18 mapping |

## P18 — Review gates

| | |
|---|---|
| **Objective** | A human approves targets before anything is scraped, from the dashboard or Telegram |
| **Deliverables** | Gate 1 and Gate 2 UIs; options screen with live estimate; approval endpoints; **gate notifications** |
| **Files** | `src/dashboard/routes_review.py` +; `templates/{review_subreddits,review_keywords,run_options}.html` +; `src/orchestration/run_service.py` ~; `src/notify/service.py` ~ |
| **DB** | None |
| **Config** | None |
| **Depends on** | P17, P7 |
| **Tasks** | 1. Gate 1: provenance, `[why?]` breakdown, **collapsed rejected list with reasons**, select-top-N, live-validating manual add<br>2. Gate 2: grouped keywords, tier badges, **negative-term panel on the same page**, live estimate<br>3. Options: every toggle recomputes requests/minutes/items/USD<br>4. `approve_subreddits` / `approve_keywords` / `set_options` transitions<br>5. `gate.reached` notification with counts, rejects, estimate and a deep link |
| **Acceptance** | The run enters `AWAITING_SUBREDDIT_REVIEW` and **stays indefinitely** · restarting the process leaves it at the gate unchanged · approving with zero selections → 422 · manually adding a non-existent subreddit → 422 with a readable reason · regenerating **preserves `user_added` rows** · the estimate is within ±30% of the observed run · a gate card is delivered **exactly once per gate per run at $0.00** |
| **Metrics** | Gate survives restart 10/10 · estimate within ±30% · 1 notification per gate |
| **Time / Risk** | **4 days · Medium** |
| **Rollback** | `gates.enabled: false` → auto-approve top-N (development only, never default) |
| **Docs** | [09 §3.3–3.5](09-dashboard-plan.md) |

---

# STAGE G — ENRICHMENT

## P19 — PreAIGate & adaptive budget

| | |
|---|---|
| **Objective** | How much AI runs is **derived from the data**, bounded, and explainable |
| **Deliverables** | `0009_enrichment`; `PreAIGate` with 11 counted reasons; `AdaptiveBudget` (knee + floor + marginal + clamps); `YieldCurve`; `ai_budgets` |
| **Files** | `migrations/versions/0009_enrichment.py` +; `src/ai/gate.py` ~; `src/scoring/{budget,knee,yield_curve}.py` +; `src/feedback/yield_curve.py` + |
| **DB** | `lead_analysis` (incl. `reused_cross_project`), `gate_audits`, `ai_budgets` |
| **Config** | `ai.budget.{strategy,mode,adaptive.*,ceilings.*}` |
| **Depends on** | P18 |
| **Tasks** | 1. `PreAIGate` — 11 reasons, each counted and persisted<br>2. Kneedle, returning `None` on a flat curve<br>3. `admission_count()` — knee × mode bias → floor → marginal → clamps, with **`method` accumulation**<br>4. `YieldCurve` fitted from `lead_labels`; **inactive below 200 labels**; the fit query **must not filter to admitted leads**<br>5. `ai_budgets` row per run<br>6. Options screen shows the method, the knee, the floor, the clamps and the **fixed-cut counterfactual** |
| **Acceptance** | **Each of the five [06f §4](06f-adaptive-budget.md) distributions replayed as a fixture produces the documented `count` and `method`** · `ai_budgets` written for **100%** of runs · over 20 `balanced` runs a clamp binds on **< 10%** · with < 200 labels no `+marginal` in `method` · **a test inspects the fit query and fails if it filters to admitted leads** · hash sampling asserted uncorrelated with pre-score |
| **Metrics** | 5/5 fixtures · 100% `ai_budgets` · clamps < 10% |
| **Time / Risk** | **3 days · High** — K4, K16 |
| **Rollback** | `ai.budget.strategy: fixed` → the mode's fixed threshold |
| **Docs** | [06f](06f-adaptive-budget.md) |

## P20 — Batched enrichment & holdout

| | |
|---|---|
| **Objective** | Admitted items are enriched in batches of 8, correctly attributed, within budget, and the gate is audited |
| **Deliverables** | `enrich_batch()`; two-level attribution; adaptive concurrency; holdout audit; incremental enrichment; batch-size sweep |
| **Files** | `src/ai/{service,concurrency,holdout}.py` ~/+; `src/ai/prompts/enrichment_batch.v1.md` ~; `src/orchestration/handlers/enrich.py` +; `src/db/repositories/analysis.py` +; `tests/fixtures/golden_leads.jsonl` + |
| **DB** | Writes `lead_analysis`, `gate_audits` |
| **Config** | `ai.batching.*`, `ai.concurrency.*` |
| **Depends on** | P19 |
| **Tasks** | 1. `enrich_batch` — B=8, `futures[fut]` → batch, echoed `id` → item<br>2. **Length mismatch = batch failure** → split in half, retry both<br>3. First batch issued **alone** to warm the cache; then open the pool<br>4. Adaptive concurrency: halve on 429/503 or p95 latency; step up on a clean window<br>5. Content-hash dedup + group fan-out<br>6. **Holdout: 2% of rejects**, deterministic hash sampling, persisted as leads with `source='holdout_audit'`<br>7. **Cross-project reuse of negatives only**, with `bkb_id IS NULL` and `reused_cross_project=1`<br>8. **Batch-size sweep** at B ∈ {1,4,8,12,16} on the 40-item golden set |
| **Acceptance** | **Results correctly attributed under shuffled concurrent completion (blocking test)** · every element echoes its input `id` · **`prompt_cache_hit_tokens > 0` from item 2; ratio > 85%** · two items with identical text produce **one** analysis linked to both · a re-run with 50 new items issues ≤50 calls · **AI calls per 1,000 collected ≤ 30** · **gate miss rate measured and < 5%** with `worst_reason` reported · a 402 preserves completed work · **cross-project reuse never shares a positive judgement** · sweep executed; the shipped B is the largest within 0.02 F1 of B=1 |
| **Metrics** | ≤30 calls/1,000 · cache hit > 85% · miss rate < 5% · mismatch rate < 1% · repair rate < 5% |
| **Time / Risk** | **4 days · High** — K2, K3, K15 |
| **Rollback** | `ai.enabled: false` → deterministic scores only, `has_ai=false` |
| **Docs** | [06 §5](06-ai-pipeline.md), [06b §4.6](06b-deepseek-optimization.md) |

## P21 — Confidence & explanations

| | |
|---|---|
| **Objective** | A deterministic 0–100 score whose displayed breakdown **is** the arithmetic |
| **Deliverables** | `ConfidenceScorer`; `scoring/explain.py`; ten explanation fields; closed-set slug validation; free rescore |
| **Files** | `src/scoring/{confidence,explain}.py` +; `src/dashboard/routes_leads.py` ~ |
| **DB** | Writes `leads.confidence_score`, `comments.confidence_score` |
| **Config** | `scoring.weights` (11 components, must sum to 1.0) |
| **Depends on** | P20 |
| **Tasks** | 1. `ConfidenceScorer` — 11 components across four signal classes; penalties<br>2. `has_ai` recorded; degraded mode still produces a usable ordering<br>3. `explain.py` renders `confidence_reasoning` **from stored components only**<br>4. Ten explanation fields; **five computed locally at zero cost**; four closed-set; one constrained prose<br>5. Slug reconciliation — unknown slugs **dropped with a warning**, never used to create rows<br>6. `POST /api/runs/<id>/rescore` |
| **Acceptance** | Scores in `[0,100]` for every input including all-None · **the displayed breakdown reconciles exactly to `leads.confidence_score`** ([33 §2](33-final-review.md) C2) · rescoring 10,000 leads takes **< 2 s with zero API calls** · weights not summing to 1.0 rejected at save · **all 459 legacy `intent_score` values unchanged** · an injected invented persona slug **fails validation and is never persisted** · `confidence_reasoning` is grep-confirmed to come from `explain.py` · locally-computed fields cost **zero** additional AI calls |
| **Metrics** | Rescore 10k < 2 s, 0 calls · reconciliation exact on 100 fixtures · 459 unchanged |
| **Time / Risk** | **3 days · Medium** |
| **Rollback** | `confidence_score` is a new column; nothing reads it until P22 |
| **Docs** | [04 §9.1](04-system-design.md) authoritative; **[09 §3.8](09-dashboard-plan.md) regenerated and the "signal boost" removed** (C1, C2) |

## P22 — Lead UI

| | |
|---|---|
| **Objective** | The operator can triage ranked leads with evidence visible on the row |
| **Deliverables** | Lead table with confidence, evidence quote and chips; seven filters; detail drawer with the class-grouped breakdown; weights editor |
| **Files** | `templates/{run_leads,lead_detail}.html` +; `src/dashboard/routes_leads.py` ~ |
| **DB** | None |
| **Config** | None |
| **Depends on** | P21 |
| **Tasks** | 1. Confidence badge, colour-graded, **NULL sorts last** · "no AI" marker on degraded rows<br>2. **Evidence quote on the row**<br>3. Seven enrichment filters wired to query params<br>4. Detail drawer, deep-linkable, with every component's value/weight/contribution<br>5. Entity links back to BKB sections, **version-pinned**<br>6. Weights editor with `Rescore all` |
| **Acceptance** | Lead list **< 200 ms at 10,000 rows** · NULL confidence sorts last · evidence shows a verified tick or "not verifiable" · every matched slug resolves to its BKB section **including after a regeneration** (pinned, not dangling) · all 17 legacy endpoints unchanged |
| **Metrics** | < 200 ms at 10k · drawer < 300 ms · 0 dangling entity links |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | Revert templates; API unchanged |
| **Docs** | [09 §3.7–3.8](09-dashboard-plan.md) |

---

# STAGE H — AGENT

## P23 — Hermes runtime & seam API

| | |
|---|---|
| **Objective** | Hermes runs, bounded and toolless, and can read the platform over HTTP |
| **Deliverables** | Hermes 0.20.0 pinned; profile with `--no-skills`; audited config; `SOUL.md`/`AGENTS.md`; `/api/agent/*` with **5 tools** |
| **Files** | `hermes-home/{config.yaml,SOUL.md,AGENTS.md}` +; `src/dashboard/routes_agent.py` +; `.env.example` ~ |
| **DB** | None (AD-29) |
| **Config** | The full [30 §2.7](30-ai-call-inventory.md) block: `title_generation: false`, `approvals: off`, `max_turns: 12`, `micro_compact: false`, both `write_approval: true`, `disabled_toolsets`, `reasoning_effort: low`; `AGENT_API_TOKEN`; separate `AGENT_DEEPSEEK_KEY` |
| **Depends on** | P22, P0 Track B |
| **Tasks** | 1. Install; create the profile with `--no-skills`; commit `hermes-home/` **without secrets**<br>2. Apply the audited config; **verify every model-invoking path is disabled or accounted for** (AD-31)<br>3. `SOUL.md` with all four load-bearing rules; `AGENTS.md` with no numbers and no business facts<br>4. Telegram bot; `TELEGRAM_ALLOWED_USERS`; DM pairing verified<br>5. `/api/agent/*` — 5 read tools, bearer auth, bound to localhost<br>6. **`untrusted_content` envelope** on every route returning Reddit text |
| **Acceptance** | `agent.disabled_toolsets` verified **at runtime**: terminal, file, browser, code, web, media absent · `max_turns: 12` · both `write_approval: true` · **`title_generation` produces zero calls** · seam requires the bearer token and is unreachable off-localhost · an unknown Telegram user is denied and issued a pairing code · **`grep -rn "import.*hermes" src/` returns nothing** · **stopping Hermes breaks nothing in the pipeline** |
| **Metrics** | 0 title-generation calls · 0 `hermes` imports in `src/` · pipeline unaffected by gateway stop |
| **Time / Risk** | **3 days · Medium** — K11 |
| **Rollback** | `systemctl stop hermes-gateway`; notifications continue via P7's transport |
| **Docs** | **New** `HERMES-SETUP.md`, `HERMES-SEAM.md`; [21 §4](21-hermes-architecture.md) target-surface header |

## P24 — Plugin, governor, skills, cron

| | |
|---|---|
| **Objective** | The agent can act within a hard budget, and scheduling moves to `hermes cron` |
| **Deliverables** | `hermes_reddit` plugin; `pre_llm_call` governor; `post_llm_call` ledger → `ai_calls`; **3 skills**; cron migration; `/health/ai` agent band |
| **Files** | `hermes-home/plugins/hermes_reddit/*` +; `hermes-home/skills/*/SKILL.md` +; `src/dashboard/routes_health.py` ~; `main.py` ~ (remove `schedule`) |
| **DB** | None — agent turns write to `ai_calls` with `stage='agent.%'` (AD-29) |
| **Config** | `agent.max_cost_per_day_usd: 1.00`; `cron.model` pinned; `cron.model_drift_guard: true` |
| **Depends on** | P23 |
| **Tasks** | 1. Plugin `register()` — 5 tools + 2 hooks<br>2. Governor: block above cap; soft nudge at 80%<br>3. Ledger: every turn → `ai_calls` with the `agent.` prefix<br>4. **Add `WHERE stage NOT LIKE 'agent.%'` to every efficiency query** ([27 §5.1](27-architecture-review.md))<br>5. Three skills: `reddit-run-control`, `quality-analyst`, `operator-onboarding` — descriptions ≤12 words<br>6. Cron job creates runs via `POST /api/agent/runs`; it **triggers, never executes**<br>7. Run both schedulers in parallel for one week, then remove `schedule` |
| **Acceptance** | **The governor blocks at the cap with zero provider calls** · **notifications keep flowing while the agent is capped** · every turn appears in `ai_calls` · **an agent row does not move the calls-per-1,000 metric** (test) · approving a gate from Telegram produces an **identical** `runs` transition and `run_events` row to the dashboard button · **no accept-all affordance** · a cron job's process makes no provider call beyond its own turn · agent spend ≤ $1.00/month · skill lint passes (≤15 skills, ≤12-word descriptions, four sections) |
| **Metrics** | Governor: 0 calls when blocked · agent spend ≤ $1/mo · efficiency metric unmoved by agent rows |
| **Time / Risk** | **4 days · Medium** — K12 |
| **Rollback** | Stop the gateway; re-enable `schedule` (retained for one week) |
| **Docs** | [22 §3](22-hermes-skills.md) first-delivery header; [24](24-cost-optimization.md); [09 §4.2](09-dashboard-plan.md) |

---

# STAGE I — QUALITY

## P25 — Labels & golden set

| | |
|---|---|
| **Objective** | Ground truth exists, and a bad prompt version cannot ship |
| **Deliverables** | `0010_monitoring_and_quality`; label capture with reason chips; **100-item golden set as a blocking gate**; `patterns` |
| **Files** | `migrations/versions/0010_monitoring_and_quality.py` +; `src/quality/{golden,report}.py` +; `src/knowledge/patterns.py` +; `src/dashboard/routes_leads.py` ~ |
| **DB** | `lead_labels`, `golden_items`, `golden_runs`, `quality_snapshots`, `calibration_maps`, `patterns`; `projects` monitoring columns |
| **Config** | `quality.golden_f1_tolerance: 0.02` |
| **Depends on** | P24 |
| **Tasks** | 1. `0010` with all six tables<br>2. Label control on **both** the list row and the drawer; optional one-click reason chips<br>3. **Expand the golden set from 40 to 100** and document the expansion ([33 §2](33-final-review.md) C3)<br>4. Blocking gate: a prompt version does not ship if F1 drops > 0.02<br>5. Golden result caching on `(prompt_version, model, batch_size)`<br>6. `patterns` — nightly `GROUP BY`, joined to `dedup_members` so a group counts once |
| **Acceptance** | `PUT /api/leads/<id>/label` reachable from row and drawer · **a deliberately degraded prompt version is refused with the delta reported** and the previous version stays active · a re-run at an unchanged `(version, model, B)` makes **zero** calls · **nightly aggregation makes zero AI calls** · a 40-repost thread contributes `distinct_groups = 1` · below-threshold patterns render greyed with **no promote control** |
| **Metrics** | Golden gate blocks 1/1 degraded version · patterns: 0 AI calls · label capture < 2 clicks |
| **Time / Risk** | **3 days · Medium** |
| **Rollback** | `alembic downgrade 0009` |
| **Docs** | [06g §4.4](06g-explainability-and-quality.md) golden set = 100 with the 40-item precursor named |

## P26 — Calibration, drift & quality page

| | |
|---|---|
| **Objective** | The operator can tell whether the system is still right, and what to do when it is not |
| **Deliverables** | ECE/Brier/isotonic **at display time only**; PSI drift; `hallucinated_span_rate`; `/health/quality`; researcher view; retention by memory class |
| **Files** | `src/quality/{calibration,drift}.py` +; `src/dashboard/routes_analytics.py` +; `templates/{health,calibration}.html` +; `src/orchestration/handlers/maintenance.py` ~ |
| **DB** | Writes `quality_snapshots`, `calibration_maps` |
| **Config** | `retention.*` per memory class |
| **Depends on** | P25 |
| **Tasks** | 1. ECE (10 bins), Brier, reliability diagram; **`insufficient_data` below 100 labels**<br>2. Isotonic fit **applied at display time**; `leads.confidence_score` stays raw<br>3. PSI on the score histogram vs a 30-day baseline; category priors; repair and span rates<br>4. `/health/quality` — four bands, every number drillable, **the documented action rendered**<br>5. Researcher view toggle, off by default, persisted per user<br>6. Retention for all five memory classes, incl. Hermes memory and `ai_calls` **after** aggregation<br>7. `/health` gains free disk and DB size (K17) |
| **Acceptance** | **Applying a calibration map changes displayed confidences and leaves the sort order identical** · under-powered metrics report `insufficient_data`, never a number · a synthetically shifted distribution raises PSI > 0.2 and triggers a golden run · an injected non-substring span is dropped, the lead survives, the metric increments · **the ECE action reads "recalibrate", never "reweight"** · **`DELETE FROM ai_cache; DELETE FROM http_cache;` changes no score** · **deleting Hermes memory changes no score, no BKB section, no run outcome** · `ai_calls` aggregated before purge |
| **Metrics** | Sort order identical after recalibration · 0 score changes after cache deletion · quality page < 500 ms |
| **Time / Risk** | **3 days · Low** — mostly SQL |
| **Rollback** | `quality.calibration_enabled: false` |
| **Docs** | [06g](06g-explainability-and-quality.md), [06i §4](06i-feedback-and-memory.md) fifth class |

## P27 — Exports

| | |
|---|---|
| **Objective** | Data leaves the system in three formats without breaking existing importers |
| **Deliverables** | `src/export/` — CSV (extended), JSON, XLSX; all streaming |
| **Files** | `src/export/{__init__,csv_export,json_export,xlsx_export}.py` +; `src/dashboard/routes.py` ~; `requirements.txt` ~ (`+openpyxl`) |
| **DB** | None |
| **Config** | None |
| **Depends on** | P26 |
| **Tasks** | 1. Move CSV out of `routes.py`; **original 13 columns first and unchanged**, 8 appended<br>2. JSON: nested lead → analysis → breakdown → comments<br>3. XLSX: `Leads` (frozen header, autofilter, conditional colour) + `Summary`<br>4. Streaming generators for all three<br>5. Exports honour every active filter |
| **Acceptance** | **Default CSV output is byte-identical to Phase 0 for legacy leads** · header order snapshot-tested · JSON validates against its documented schema · XLSX opens in Excel and LibreOffice with both sheets · a 10,000-row export does not materialise in memory |
| **Metrics** | 13 columns default · 10k export peak RSS < 100 MB · byte-identical legacy CSV |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | `format` defaults to `csv`; new formats simply unused |
| **Docs** | [18 §9.1](18-phase-08.md) |

---

# STAGE J — PRODUCTION

## P28 — Deployment

| | |
|---|---|
| **Objective** | Both processes run on a VPS, on boot, isolated by unix permissions |
| **Deliverables** | Two systemd units, two unix users, `chmod 0600` on the database, Caddy with TLS + basic auth |
| **Files** | `deploy/{platform.service,hermes.service,Caddyfile,install.sh}` +; `docs/RUNBOOK.md` + |
| **DB** | None |
| **Config** | `.env` at `0600`, owned by the platform user |
| **Depends on** | P27 |
| **Tasks** | 1. Users `reddit-platform` and `reddit-hermes`; **the Hermes user has no read access to `data/`**<br>2. Two systemd units, `Restart=on-failure`, boot-enabled<br>3. Caddy: TLS, basic auth, `:443` → `127.0.0.1:5000`; **`/api/agent/*` blocked externally**<br>4. `hermes update` disabled in the unit environment<br>5. Startup smoke check |
| **Acceptance** | Both services start on boot and restart on failure · **attempting to read `data/leads.db` as the Hermes user fails with EACCES** (asserted by actually running it) · `/api/agent/*` unreachable through Caddy from outside · stopping the gateway breaks nothing · TLS valid |
| **Metrics** | Boot 2/2 · EACCES confirmed · external seam access = 403 |
| **Time / Risk** | **2 days · Medium** — first real deployment |
| **Rollback** | Previous venv retained; symlink switch; `systemctl restart` |
| **Docs** | **New** `RUNBOOK.md`; **[21 §8.1](21-hermes-architecture.md) redrawn as systemd** |

## P29 — Backup, restore & runbook

| | |
|---|---|
| **Objective** | The system can be recovered, and someone has actually proved it |
| **Deliverables** | Nightly backup; **an executed restore drill**; secret rotation for five secrets; disk monitoring; degraded-mode decision tree |
| **Files** | `scripts/{backup,restore}.py` +; `docs/RUNBOOK.md` ~; `src/orchestration/handlers/maintenance.py` ~ |
| **DB** | None |
| **Config** | `backup.{enabled,keep,path}` |
| **Depends on** | P28 |
| **Tasks** | 1. Nightly backup via the **SQLite backup API** + a `hermes-home` archive<br>2. `restore.py` with a dry-run mode<br>3. **Execute a restore drill and record the timing**<br>4. Rotation procedures: `APP_SECRET_KEY` (and the re-enter-key consequence), pipeline key, agent key, Telegram token, proxy credentials<br>5. Disk-space alert on `/health` and in the maintenance job<br>6. Notification backlog policy (K6/P6)<br>7. Degraded-mode decision tree |
| **Acceptance** | **A restored backup opens, has ≥459 leads, and renders `GET /`** · the drill is executed and timed, not just documented · rotating `APP_SECRET_KEY` produces the `UNDECRYPTABLE` state with a "re-enter your key" message, **never a crash** · disk below threshold raises a notification · `RUNBOOK.md` covers all seven procedures |
| **Metrics** | Restore drill: pass, timed · backup < 5 s · 7/7 runbook procedures |
| **Time / Risk** | **2 days · Medium** |
| **Rollback** | Backups are additive; disabling changes nothing |
| **Docs** | `RUNBOOK.md` |

## P30 — Security review & CI

| | |
|---|---|
| **Objective** | Both planes reviewed, and the gates run automatically on every push |
| **Deliverables** | Full security checklist executed; GitHub Actions pipeline; canary scheduled |
| **Files** | `.github/workflows/ci.yml` +; `scripts/canary.py` +; `docs/RUNBOOK.md` ~ |
| **DB** | None |
| **Config** | None |
| **Depends on** | P29 |
| **Tasks** | 1. Security checklist across both planes: secrets in repo/DB/logs/exports, `|safe` grep, `pip-audit`, injection fixtures, Flask `debug=False`, secret key from env with no fallback, no Reddit auth anywhere<br>2. CI: lint → offline tests → **four grep fences** → skill lint → migration up/down on a live-DB copy → deploy → smoke<br>3. Schedule the canary — an Atom feed that parses proves reachability (K1)<br>4. Rollback drill in CI |
| **Acceptance** | Full checklist passes · `pip-audit` clean · **CI blocks on any failing lint, test, grep fence, or migration** · the canary alerts on zero extraction · a rollback drill restores the previous version · **all phases' manual guides re-executed and recorded** |
| **Metrics** | 0 security findings · CI < 10 min · canary alerts 1/1 on a simulated break |
| **Time / Risk** | **2 days · Low** |
| **Rollback** | CI is additive |
| **Docs** | [10 §10](10-implementation-roadmap.md) production checklist ticked; [README](README.md) final pass |

---

## 3. Dependency graph

```
P0 ──► P1 ──► P2 ──► P3 ──┬──► P4 ──► P5 ──► P6 ──► P7 ──┐
                          │                              │
                          └──────────────────────────────┼──► P8 ──► P9 ──► P10 ──► P11
                                                         │                            │
                                                         │    ┌───────────────────────┘
                                                         │    ▼
                                                         │   P12 ──► P13 ──► P14 ──► P15 ──► P16
                                                         │                                    │
                                                         │    ┌───────────────────────────────┘
                                                         │    ▼
                                                         └─► P17 ──► P18 ──► P19 ──► P20 ──► P21 ──► P22
                                                                                                      │
                                                              ┌───────────────────────────────────────┘
                                                              ▼
                                                             P23 ──► P24 ──► P25 ──► P26 ──► P27
                                                                                               │
                                                                    ┌──────────────────────────┘
                                                                    ▼
                                                                   P28 ──► P29 ──► P30
```

**Strictly sequential.** ▶ P4–P7 and P8–P11 could in principle be parallelised by two developers, but
with one implementer the sequence is the safest order and every phase is independently mergeable
regardless.

---

## 4. What must never happen

| Never | Because |
|---|---|
| Implement two phases in one session | The gate between them is the quality mechanism |
| Skip the manual guide because "the tests pass" | Automated tests do not catch a page that renders wrong |
| Add a table not in [ARCHITECTURE_FREEZE §4.1](ARCHITECTURE_FREEZE.md) | It is an amendment, and needs a failed measurement |
| Add a dependency not in [ARCHITECTURE_FREEZE §5](ARCHITECTURE_FREEZE.md) | Same |
| Renumber a migration | M2 |
| Merge with a failing grep fence | The fences are the architecture's only mechanical enforcement |
| Proceed after a failed acceptance criterion | The criterion was chosen because it matters |
| "Fix" a failing test by changing the assertion | If the assertion was wrong, that is an amendment with reasoning |
