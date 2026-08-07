# P3 IMPLEMENTATION CHECKLIST — Run service, API, run pages

**Status:** awaiting approval. **No source file has been modified.**
**Phase:** P3 of the frozen P0–P30 plan ([34 §P3](34-implementation-plan.md)).
**Design doc:** [13-phase-03.md](13-phase-03.md) · **Predecessor:** [PHASE-02-HANDOVER.md](PHASE-02-HANDOVER.md)

Documents read in full for this pass: [34 §P3](34-implementation-plan.md) (all thirteen fields),
[13](13-phase-03.md) (all fourteen sections), [PHASE-02-HANDOVER](PHASE-02-HANDOVER.md),
[04 §1–3](04-system-design.md), [05 §5.3](05-database-plan.md), [09 §2/§3.6/§4/§5](09-dashboard-plan.md),
[07 §5](07-scraping-pipeline.md) (`RunOptions`), [ARCHITECTURE_FREEZE](ARCHITECTURE_FREEZE.md),
[35 §1–2](35-testing-strategy.md). Source read: `src/orchestration/*`, `src/obs/*`,
`src/db/repositories/runs.py`, `src/db/models.py`, `src/dashboard/*`, `src/scrapers/*`,
`main.py`, `config.yaml`, `tests/conftest.py`, `tests/test_boundaries.py`,
`tests/baseline/api_contract.json`.

---

## 0. THREE DECISIONS — ✅ ANSWERED 2026-08-07

| # | Decision | Outcome |
|---|---|---|
| **D-A** | Gate-state fast-forward | ✅ **Approved as proposed**, incl. the ARCHITECTURE_FREEZE §11.1 reconciliation entry |
| **D-B** | Scope of the `/api/scrape` shim | ✅ **B1** — `scrape_subreddit` only; keyword and user scraping are dropped in P3 and documented as a behaviour change |
| **D-C** | `orchestration.enabled` | ✅ **C1** — implemented in `config.yaml` (default `true`), with the retained legacy thread path exercised by a test |

The reasoning behind each is kept below, unedited, as the record of why.

### D-A — The run must fast-forward through the two gate states (recommend: approve)

`SCRAPING` is reachable from `PENDING` only via
`PENDING → PROFILING → DISCOVERING → AWAITING_SUBREDDIT_REVIEW → GENERATING_KEYWORDS →
AWAITING_KEYWORD_REVIEW → AWAITING_OPTIONS → SCRAPING`. **Both gate states are mandatory on every
legal path.** This is forced by `TRANSITIONS` (P1, transcribed from [04 §1.2](04-system-design.md)),
which P3 must not modify.

It directly contradicts [13 §2.2](13-phase-03.md): *"the review gate UIs (Phase 5) — the states
exist, but nothing enters them yet."*

The run also **must** reach a terminal state, for a reason stronger than AC1: a legacy run carries
`project_id = NULL`, and `RunRepository.active_for_project(None)` renders as `project_id IS NULL`,
matching every legacy run. A run that never terminates makes the duplicate-run guard return **409 on
every subsequent `POST /api/scrape` forever** — an outright R20 break.

**Proposal:** `RunService.create()` walks each hop through `transition()`, so `assert_transition`
validates every one (nothing is bypassed), appending a `run_events` row per hop naming the reason
honestly — e.g. `"legacy scrape: subreddit gate satisfied by the configured subreddit list"`.
`finalize_run` then does `SCRAPING → ANALYZING → COMPLETE`.

Filed as an [ARCHITECTURE_FREEZE §11.1](ARCHITECTURE_FREEZE.md) **documentation reconciliation**, not
a §11 amendment: no technology, table or decision changes — it is an inconsistency between two frozen
documents, the same category as the twelve-vs-eleven `RunState` resolution in P1.

### D-B — `POST /api/scrape` runs three scrapers today; the queue has a job type for one

`/api/scrape` currently runs `SubredditScraper`, `KeywordScraper` **and** `UserScraper`. The frozen
job-type list ([04 §2.4](04-system-design.md), mirrored in `MAX_ATTEMPTS`) contains no keyword or user
scraper type, and the freeze closes that list. A faithful shim therefore **does less work than the
route it replaces** while returning byte-identical JSON — the contract test and every response
assertion pass, and the operator's keyword and user leads quietly stop appearing.

| # | Option | Behaviour | Cost |
|---|---|---|---|
| **B1** | One `scrape_subreddit` job per subreddit; keyword + user scraping **dropped** in P3 | Regression in what a scrape collects | Honest job types; documented behaviour change the operator will notice |
| **B2** | `scrape_subreddit` handler runs **all three** scrapers | Behaviour preserved exactly | The job type's name lies; per-subreddit progress (AC2) becomes impossible |
| **B3** | Subreddit work through the queue; keyword + user still on the legacy thread | Behaviour preserved | Two execution models in one route — the shape P3 exists to remove |

**My recommendation: B1**, with the drop stated in the completion report, the manual guide and
`CHANGELOG.md`, and keyword/user scraping restored when their stages land (P5/P17). B2 and B3 both
buy compatibility by making the orchestration layer dishonest on its first day. But this is a visible
product regression, so it is your call, not mine.

### D-C — `orchestration.enabled`

[34 §P3](34-implementation-plan.md) says **Config: None** and, four rows later, **Rollback:
`orchestration.enabled: false` → `POST /api/scrape` uses the legacy thread path (retained)**. A
direct self-conflict. It is a *different* switch from `WORKER_INPROCESS` (that one governs whether a
host process starts a worker), so implementing it does not violate handover G5.

- **C1 (recommend):** implement `orchestration.enabled` in `config.yaml`, default `true`; the legacy
  thread path is retained behind it **and tested**, so the rollback row is real rather than fiction.
- **C2:** treat "Config: None" as authoritative, do not implement it, delete the legacy path, and
  record the rollback row as unimplementable in the completion report.

C1 costs one config key and one test; C2 leaves the documented rollback unavailable. Untested
retained code would be the dead code the quality rules forbid — so C1 is only acceptable *with* its
test.

---

## 1. Every P3 acceptance criterion

From [13 §13](13-phase-03.md) (AC1–AC15) and [34 §P3](34-implementation-plan.md) Acceptance/Metrics.

| # | Criterion | How it is proven | Mutation-tested? |
|---|---|---|---|
| AC1 | `POST /api/scrape` creates a run and completes it; response contains the original keys | `tests/test_run_api.py` — response keys `== {"ok","message"} ∪ {"run_id"}`, values byte-identical; worker driven to completion | **Yes** (bold in 34) |
| AC2 | `GET /api/runs/<id>/progress` reflects real job counts, **< 50 ms** | Counts asserted against seeded jobs; p95 measured over a **5,000-job** seed | **Yes** (bold in 34) |
| AC3 | Kill mid-run, restart, remaining jobs resume | Simulated process death (worker discarded mid-run, new `Worker` on the same DB); 10 iterations |  |
| AC4 | Retryable error retries with growing backoff to `max_attempts` | Already covered by P2 `test_job_queue.py`; re-asserted end-to-end through a run |  |
| AC5 | Lease expiry re-runs without duplicating leads | Handler idempotence test — run twice, lead count unchanged (`reddit_id` dedup) |  |
| AC6 | Cancel stops the run; queued jobs become `cancelled` | `POST /api/runs/<id>/cancel` → `cancel_queued` count + run state `CANCELLED` |  |
| AC7 | Second run for the same project → **409 with the existing run id** | `tests/test_run_api.py`; body contains `run_id` of the in-flight run | **Yes** (bold in 34) |
| AC8 | `python main.py worker` standalone with `WORKER_INPROCESS=false` | Extends existing `tests/test_worker_cli.py`; asserts `create_app()` starts **no** worker when disabled |  |
| AC9 | SIGTERM finishes the in-flight job, exits < 30 s | P2 coverage retained; join deadline on the test (F5) |  |
| AC10 | `run_events` renders as a live feed on `/runs/<id>` | Page contains the feed container; `/api/runs/<id>/events?after=` returns only newer rows |  |
| AC11 | Maintenance purges jobs, events, cache rows, metrics | Already green in `tests/test_maintenance.py` — re-run, not rewritten |  |
| AC12 | Illegal transition → **409 naming both states** | `IllegalTransition` caught **by name** (it subclasses `ValueError`; a broad `except ValueError` would swallow unrelated bugs) |  |
| AC13 | No `database is locked` in a 10-minute concurrent read/write soak | Extends `tests/test_concurrency_soak.py` with the run API as a second reader |  |
| AC14 | 459 leads intact; 17 legacy endpoints unchanged | `tests/test_boundaries.py` + `live_db_copy` |  |
| AC15 | `ruff` clean; `pytest` passes; **coverage ≥ 80 %** on `src/orchestration/` | Note: [34](34-implementation-plan.md) universal row says ≥70 % on new modules; **13 AC15's 80 % is the stricter number and is what I will hold** |  |

Mutation discipline ([35 §2.4](35-testing-strategy.md)): for each **bold** row, break the guarantee
in the source, watch the test go red, restore. P2's F4 is the reason — a test that has never been
seen to fail is not evidence.

---

## 2. Files created

| File | Purpose |
|---|---|
| `src/orchestration/run_service.py` | `RunService`, `RunOptions`, `RunProgress` |
| `src/orchestration/handlers/scrape.py` | `handle_scrape_subreddit` |
| `src/orchestration/handlers/finalize.py` | `handle_finalize_run` |
| `src/dashboard/routes_runs.py` | All run/job endpoints (new blueprint — `routes.py` is not rewritten) |
| `src/dashboard/templates/runs.html` | Run list |
| `src/dashboard/templates/run_progress.html` | Run detail + live feed |
| `tests/test_run_service.py` | Service unit tests incl. the transition walk and the 409 guard |
| `tests/test_run_api.py` | Endpoint tests, the `/api/scrape` contract test, the < 50 ms budget |
| `tests/test_handlers_scrape.py` | `scrape_subreddit` + `finalize_run`, idempotence, cancel flag |
| `tests/test_run_pages.py` | Page rendering, nav, **F3 template-redaction assertion** |
| `docs/testing/P03-testing.md` | Manual guide (Part A written, Part B executed) |
| `docs/PHASE-03-COMPLETION-REPORT.md` | After implementation |
| `docs/PHASE-03-HANDOVER.md` | After implementation |

## 3. Files modified

| File | Change | Sanctioned by |
|---|---|---|
| `src/dashboard/app.py` | Register `routes_runs`; start the in-process worker via the **existing** `start_inprocess_worker()` + `atexit` (handover G5, T5) | 34 §P3 Files |
| `src/dashboard/routes.py` | `POST /api/scrape` → shim. **The only edit in this file.** Additive `run_id` only | 34 §P3 Files |
| `src/dashboard/nav.py` | Add the `Runs` entry (currently listed as deliberately absent, "Runs — Phase 3") | 13 §7 |
| `src/dashboard/templates/_base_ai.html` | Add the shared `poll()` helper beside `api()`/`toast()` — **there is no static/ directory** | 09 §5.2 |
| `src/dashboard/templates/index.html` | Sidebar "Run Scraper" navigates to `/runs/<new_id>` instead of a status line that never updates. Minimal edit to the inline `runScrape()`; `index.html` does **not** extend `_base_ai.html` | 13 §7, §10 — **not** in 34's file list (§7 below) |
| `src/dashboard/routes_health.py` | `/health` reports queue depth (§7 D-3 scopes worker liveness) | 13 §14 — **not** in 34's file list |
| `src/orchestration/handlers/__init__.py` | Register `scrape_subreddit`, `finalize_run` | 34 §P3 Tasks |
| `src/orchestration/__init__.py` | Re-export `RunService`; **fix the docstring** — it claims the package imports neither `src.ai` nor `src.scrapers`, and `handlers/scrape.py` makes the second half false | Doc edit P3 owns |
| `main.py` | `schedule` enqueues instead of calling scrapers directly | 13 §4 |
| `config.yaml` | `orchestration.enabled` — **only if D-C = C1** | 34 §P3 Rollback |
| `tests/conftest.py` | The `app` fixture sets `WORKER_INPROCESS=false` **before** `create_app()` runs, so `create_app()` starting a worker does not change behaviour for the 428 existing tests. Tests that need a worker drive `tick()` explicitly | Consequence of the `create_app()` wiring |
| `tests/test_navigation_and_pages.py` | Nav↔routes assertions gain the `Runs` entry | Consequence of the nav change |
| `docs/34-implementation-plan.md`, `docs/13-phase-03.md`, `docs/ARCHITECTURE_FREEZE.md` §11.1, `CHANGELOG.md` | Phase-owned doc edits, incl. the D-A reconciliation | 34 §P3 Docs |

**Not touched:** `migrations/` (P3 owns no migration — `alembic heads` stays one `0004`),
`src/db/models.py`, `src/db/repositories/runs.py` (the P2 read surface is sufficient),
`src/orchestration/{states,job_queue,worker}.py`, `src/scrapers/*`, `src/ai/*`, `src/net/*`.

---

## 4. Endpoints

Per [13 §6](13-phase-03.md). All in `routes_runs.py`; all JSON errors as `{"error": ...}`, matching
the legacy convention.

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/runs` | Filter by `project_id`, `state` |
| `POST` | `/api/runs` | `{project_id?, options}` → run + first jobs; **409 + existing `run_id`** if one is active |
| `GET` | `/api/runs/<id>` | Full run |
| `GET` | `/api/runs/<id>/progress` | **Poll target — one `GROUP BY` via `JobRepository.counts_by_state()` (handover T2). No per-state query, no rows loaded into Python** |
| `GET` | `/api/runs/<id>/events?after=<id>` | `RunRepository.events(run_id, after_id=)` |
| `POST` | `/api/runs/<id>/cancel` | `cancel_queued()` + run-level flag in `stats_json` (T4 — **not** a new column) |
| `POST` | `/api/runs/<id>/retry` | From `FAILED` only; 409 otherwise |
| `GET` | `/api/jobs?run_id=` | Debug view |
| `POST` | `/api/jobs/<id>/retry` | Force-requeue one job — **through `JobQueue`, never a direct state write** (G4) |
| `POST` | `/api/scrape` | **Modified.** Keys unchanged, `run_id` added |

Pages: `GET /runs`, `GET /runs/<id>`.

---

## 5. UI

- **`/runs`** — id, project, state badge, leads found, duration, actions. Extends `_base_ai.html`,
  reusing `.pill`/`table.data`/`.card`; no second visual language ([09 §1.3](09-dashboard-plan.md)).
- **`/runs/<id>`** — [09 §3.6](09-dashboard-plan.md): progress bar, stage label, counters, cancel,
  live `run_events` feed. Fields with no P3 source (AI cost, funnel, proxy counts) are **omitted, not
  faked** — they arrive with the stages that produce them.
- **`poll(url, onUpdate, intervalMs=3000)`** in `_base_ai.html`: stops on terminal state, backs off to
  10 s after 3 consecutive errors, pauses on `document.hidden`, resumes on `visibilitychange`.

## 6. Backend services / repositories

**`RunService`** ([04 §1.3](04-system-design.md)) — P3 implements `create`, `transition`, `cancel`,
`retry`, `progress`. `approve_subreddits`, `approve_keywords`, `set_options` are **P18's** (no gate
data exists) and are not stubbed — a `TODO` body is the placeholder code the quality rules forbid.

`RunOptions` ([07 §5](07-scraping-pipeline.md)) — only the fields P3 can honour
(`mode`, `limit_per_query`, `min_score_threshold`, subreddit list); the rest are P6/P8 and are absent
rather than ignored. `RunProgress` per [04 §1.3](04-system-design.md), with `leads_found` from
`stats_json` and `llm_cost_usd` from `runs.llm_cost_usd` (0.0 in P3).

**Repositories: no change.** `RunRepository` and `JobRepository` already expose everything P3 needs
(handover §1.1). `active_for_project()` stays as written — terminal-state exclusion, not an active
list (T3).

**Handlers** — both idempotent (G2, R9); both enqueue successors with `session=` so the stage outcome
and the next enqueue commit together (G1); both check the `stats_json` cancel flag between units (T4).

---

## 7. Conflicts and ambiguities found in the documentation

| # | Conflict | Resolution |
|---|---|---|
| **D-1** | [13 §2.2](13-phase-03.md) "nothing enters the gate states" vs `TRANSITIONS` making them mandatory | **Decision D-A above** |
| **D-2** | 34 §P3 "Config: None" vs its own Rollback row naming `orchestration.enabled` | **Decision D-C above** |
| **D-3** | [13 §14](13-phase-03.md) wants `/health` to report **worker liveness**; there is no `workers` table and P3 owns no migration. With an idle queue and no running job, nothing on disk proves a worker is alive | Scope down and say so: report **queue depth, oldest-queued age, and whether this process holds an in-process worker**. Cross-process liveness needs a table P3 does not own; recorded as carried into the phase that adds one |
| **D-4** | [13 §4](13-phase-03.md) lists `src/scrapers/base.py ~` (`ScrapeContext` gains `run_id`); [13 §9.2](13-phase-03.md) sketches `SubredditScraper(client, config, repo).run(session, ctx)` → `report.as_dict()` | **P6-era signatures.** `src/scrapers/base.py` and `ScrapeContext` do not exist, and 34 assigns `base.py` to P6. P3 wraps the **existing** `SubredditScraper(client, config).run(session) -> int` and creates no `ScrapeContext` |
| **D-5** | [13 §4](13-phase-03.md) lists `src/obs/{events,logging}.py`, `src/db/repositories/runs.py`, `states.py`, `job_queue.py`, `worker.py`, `handlers/maintenance.py` as P3 files | All shipped in P1/P2. 13 is the three-phase design doc; 34's split is authoritative |
| **D-6** | `routes_health.py` and `index.html` are edited by P3 but are absent from 34's P3 file list | 34 states the Files row is *"a guide, not a contract"*; both edits are mandated by [13 §7/§10/§14](13-phase-03.md). Recorded here so the deviation is visible, and kept minimal |
| **D-7** | Coverage: 13 AC15 ≥80 % on `src/orchestration/` vs 34's universal ≥70 % on new modules | Hold **80 %** |
| **D-8** | 34 §P3 "Depends on P2" vs 13 §12 "Upstream: Phase 1, Phase 2" (old numbering) | 34 governs |

**Belongs to a later phase — will NOT be implemented:** gate UIs and `approve_*`/`set_options`
(P18); `/api/runs/<id>/estimate` (P18 options screen); projects and `project_id` FK (P12); any AI,
discovery, comment, enrichment or notification job type; scheduling the nightly `maintenance` job
(P24 — `hermes cron`); multi-worker concurrency; `ScrapeContext`/`base.py` (P6); any migration.

---

## 8. Dependencies on P2 — the five guarantees, and where P3 touches each

| Guarantee | P3's obligation |
|---|---|
| **G1** `enqueue(session=…)` enlists in the caller's transaction | Both handlers pass their session; routes creating the first job do not. Both paths tested |
| **G2** Every handler is idempotent | `scrape_subreddit` inherits it from `reddit_id` dedup; `finalize_run` is written so finalising twice is a no-op |
| **G3** The queue's transaction is not the handler's | Not merged, not "simplified" |
| **G4** Nothing writes a job state outside `JobQueue` | `POST /api/jobs/<id>/retry` and cancel go through `JobQueue`, never `job.state = …` |
| **G5** `WORKER_INPROCESS` is the one switch | `create_app()` calls `start_inprocess_worker()`, which already honours it. **No second config key for the same thing** (`orchestration.enabled` governs a different question) |

Plus the P2 traps: **T1** response contract, **T2** progress query shape, **T3** `active_for_project`
spelling, **T4** cancel flag in `stats_json`, **T5** `atexit` not signals for the in-process worker,
**T6** measure the first real scrape against the 900 s lease.

---

## 9. Risk assessment

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R-1 | The `/api/scrape` shim silently collects less than the route it replaces | **High** | Decision D-B; whichever option, stated in the completion report, manual guide and `CHANGELOG.md` |
| R-2 | `/api/scrape` is **not** in `tests/baseline/api_contract.json` — the replay only issues `client.get(path)`, so a POST route is uncovered and adding `run_id` would not fail it | **High** | Record the current response **verbatim before the first edit** (handover §8), then write a **dedicated additive-only contract test** for the POST route |
| R-3 | Progress endpoint misses the 50 ms budget under real volume | Medium | `counts_by_state()` `GROUP BY` over `ix_jobs_run`; p95 measured at a seeded **5,000 jobs**, not on an empty table |
| R-4 | Web + worker contention returns `database is locked` | **High** (K13) | WAL + `busy_timeout` from P2; worker stays the sole bulk writer; routes write single rows; soak extended with the run API as a second reader |
| R-5 | A credential in `jobs.error` or `run_events.message` reaches rendered HTML | **High** (F3, R15) | Redacted on write already; **asserted again at the template** — a credential-shaped string seeded into both columns must not appear in `/runs/<id>` output |
| R-6 | Cancel cannot stop a running handler | Medium | `stats_json` flag checked between subreddits; documented as "the job in flight finishes" |
| R-7 | The in-process worker makes tests flaky or slow (`create_app()` now starts a thread) | Medium | `conftest.py`'s `app` fixture sets `WORKER_INPROCESS=false`; tests that need a worker drive `tick()` explicitly. Join deadline on anything that could hang (F5) |
| R-8 | A test hangs the suite instead of failing | Medium | F5 — every thread join and poll loop gets a deadline |
| R-9 | The fast-forward walk hides a genuine illegal transition | Medium | Every hop goes through `transition()`; a test asserts the exact recorded hop sequence and its `run_events` rows |
| R-10 | Lease expiry mid-scrape duplicates work | Medium | AC5; `reddit_id` dedup; `IntegrityError` handled as skip |
| R-11 | D1 (unsigned P00/P01/P02 sign-off tables) and R7 (no hosted CI run for the P2 commits) | — | **Treated as satisfied by your opening declaration** (§10). Not re-litigated |

---

## 10. Assumptions

1. P2 is signed off; D1's blank sign-off tables and R7's missing hosted CI run are accepted as
   closed on your declaration. I will run `gh run list` once at the start of implementation and
   report what I see, without blocking on it.
2. `data/leads.db` stays at `0004_orchestration`; P3 writes the first rows to `runs`/`jobs`/`run_events`.
3. Legacy runs carry `project_id = NULL`; the duplicate-run guard therefore serialises **all** legacy
   scrapes — one at a time, which is the [13 §9.4](13-phase-03.md) double-click fix working as intended.
4. `python-json-logger` remains the only added dependency; P3 adds **none** ([13 §12](13-phase-03.md)).
5. The suite stays offline; no test touches `data/leads.db` except through `live_db_copy`.
6. Windows + `.venv` is the reference environment; CI parity is checked via `.github/workflows/ci.yml`.

---

## 10a. Consequences of D-B = B1 and D-C = C1, folded in

- **The scheduler drops the same two scrapers.** `main.py cmd_schedule` enqueues instead of calling
  scrapers directly, so under B1 the *scheduled* path loses keyword and user scraping exactly as
  `/api/scrape` does. Both are stated together in the completion report, the manual guide and
  `CHANGELOG.md`. **`python main.py scrape` still runs all three** — that is the operator's retained
  workaround and it belongs in the manual guide.
- **The scheduler now meets the duplicate-run guard.** If a run is still active when the 60-minute
  tick fires, `RunService.create` returns the 409 condition. `cmd_schedule` must **log and skip**,
  never die — the loop runs unattended. Tested.
- **`retry()` re-walks the same chain.** `FAILED → {PENDING}` is the only edge out of `FAILED`, so a
  retry lands in `PENDING` and must traverse the same seven hops back to `SCRAPING`. It **reuses the
  `create()` walk helper**, not a second copy — two copies drift, and the retry path is where nobody
  looks.
- **The walk's events are written for a human.** The walk emits ~7 `run_events` rows at create time
  and AC10 renders them live, so an operator watching a legacy scrape sees them scroll past. Messages
  are phrased for the person reading the page, not for the state machine.
- **C1's legacy-path test must not pass for the wrong reason** (F4). With
  `orchestration.enabled: false` the retained path spawns a daemon thread; `NetworkCallBlocked` dies
  silently inside it and the route returns 200 regardless, so asserting `status_code == 200` proves
  nothing. The test **monkeypatches the three scraper classes and asserts they were constructed**.
  Then: break the branch condition, watch it go red, restore.

## 11. Implementation order (logical commits, tests run after each)

0. **Record the current `POST /api/scrape` response verbatim** into `tests/baseline/` and commit that
   alone — **before any edit to `routes.py`** (handover §8; R-2). Its value is destroyed by doing it
   in any later step.
1. `RunService` + `RunOptions`/`RunProgress`, incl. the transition walk (shared by `create` and
   `retry`) and the 409 guard → `tests/test_run_service.py`
2. `scrape_subreddit` + `finalize_run` handlers + registry → `tests/test_handlers_scrape.py`
3. `routes_runs.py` endpoints + `create_app` wiring + in-process worker + `conftest.py` fixture change → `tests/test_run_api.py`
4. `POST /api/scrape` shim + `orchestration.enabled` + its contract test + the legacy-path test
5. `/runs` and `/runs/<id>`, `poll()`, nav, sidebar redirect → `tests/test_run_pages.py`
6. `main.py schedule` enqueues (incl. log-and-skip on an active run); `/health` queue depth
7. Performance (5,000-job p95), soak, mutation pass on the three bold criteria
8. Full gate, then docs: completion report, handover, `docs/testing/P03-testing.md`, progress update

## 12. Final gate before declaring P3 complete

- [ ] `pytest`
- [ ] `pytest -W error::DeprecationWarning`
- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `python scripts/check_schema.py --db data/leads.db` → all checks pass
- [ ] `alembic heads` → one head, `0004_orchestration`; migration round-trip on a **copy** of the live DB
- [ ] `tests/test_boundaries.py` (fences 1 and 4) + fences 2 and 3 by grep
- [ ] Coverage ≥ 80 % on `src/orchestration/`
- [ ] Legacy contract: 459 leads, 13 CSV columns, 17 endpoints, `intent_score` fingerprint
- [ ] Mutation pass on AC1, AC2, AC7 — each broken, seen red, restored
- [ ] GitHub Actions compatible (clean-venv simulation, as in P2)
- [ ] `docs/testing/P03-testing.md` Part A written, Part B executed and recorded
