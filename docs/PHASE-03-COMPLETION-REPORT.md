# PHASE-03 COMPLETION REPORT — Run service, API, run pages

**Phase:** P3 of the frozen [P0–P30 plan](34-implementation-plan.md) · Stage B — Orchestration
**Completed:** 2026-08-07
**Design:** [13-phase-03.md](13-phase-03.md) · **Plan row:** [34 §P3](34-implementation-plan.md)
**Companions:** [PHASE-03-HANDOVER.md](PHASE-03-HANDOVER.md) · [testing/P03-testing.md](testing/P03-testing.md)
**Architecture:** FROZEN. **No amendment.** One [§11.1 reconciliation](ARCHITECTURE_FREEZE.md).

---

## 1. Objective

> *"The operator can start a run from the UI, watch it, cancel it, and see it resume after a
> restart."*

**Met.** Pressing **Run Scrape Now** creates a run, enqueues one job per subreddit, and opens a page
that shows the work happening. Cancel stops the queued jobs and the running one stops at its next
checkpoint. Killing the process and restarting resumes the remainder without duplicating a lead.

This is the phase where the pipeline runs end to end for the first time: P1 gave it a vocabulary, P2
gave it a runtime, and **nothing had ever put work in the queue** until now.

---

## 2. Verification

| Check | Result |
|---|---|
| Full suite | **579 passed, 2 skipped** · 180 s |
| Suite under `-W error::DeprecationWarning` | **579 passed, 2 skipped** — no deprecation warnings |
| New P3 tests | **151** across six files |
| `ruff check` / `ruff format --check` | All checks passed! / 90 files already formatted |
| Coverage, `src/orchestration/` | **97 %** (680 statements, 19 uncovered) — budget is ≥ 80 % |
| — `run_service.py` | 98 % |
| — `handlers/scrape.py` · `handlers/finalize.py` | 94 % · 97 % |
| `alembic heads` | `0004_orchestration (head)` — one head, **no migration added** |
| Migration round-trip on a **copy** of the live DB | `upgrade → downgrade -1 → upgrade` · **459 leads intact** |
| `scripts/check_schema.py` (live DB) | **OK — all 25 checks passed** |
| Live DB after the phase | 459 leads · `intent_score` max 164.28 / avg 42.29 — **unchanged** · orchestration tables still empty (nothing here wrote to it) |
| **10-minute soak** (`SOAK_SECONDS=600`) | **64,950 claims · 64,950 events · 133,653 reads · 68,248 progress polls · 0 errors** |
| Progress endpoint | **p95 < 50 ms at 5,000 jobs**, and **one** query for the counts |
| Mutation testing | 3 mutations on the bold criteria, **3 detected** (§6) |
| `POST /api/scrape` contract | Replayed against a baseline recorded **before** the route was edited |

The soak now includes a reader on the real `RunService.progress` path, not an imitation of its
queries — 68,248 of those polls ran against two concurrent writers with zero lock errors.

---

## 3. The three decisions taken before implementation

The planning pass found eight documentation conflicts. Five were resolved and recorded; three
changed what would be built and were put to the operator.

### 3.1 The run walks both review gates — it cannot do otherwise

`TRANSITIONS` admits exactly one path from `PENDING` to `SCRAPING`, and both `AWAITING_*_REVIEW`
states lie on it:

```
PENDING → PROFILING → DISCOVERING → AWAITING_SUBREDDIT_REVIEW
        → GENERATING_KEYWORDS → AWAITING_KEYWORD_REVIEW
        → AWAITING_OPTIONS → SCRAPING
```

[13 §2.2](13-phase-03.md) said P3 would leave those states unentered. The table — [04
§1.2](04-system-design.md), transcribed by P1 — says they are unavoidable. Both cannot hold.

There is a second, stronger reason the run must also *terminate*: a legacy run carries
`project_id = NULL`, and `active_for_project(None)` renders as `project_id IS NULL`, matching every
legacy run. **A run that never reaches a terminal state would make every subsequent scrape return
409 forever** — an outright R20 break.

`RunService.create()` therefore walks each hop through `transition()`, so `assert_transition`
validates all seven and each appends a `run_events` row explaining, in the operator's words, why the
gate is *satisfied* rather than skipped: a scrape started from the dashboard uses the subreddits the
operator already chose, which is the decision the gate exists to ask for.

Filed as a **[§11.1 documentation reconciliation](ARCHITECTURE_FREEZE.md)**, not a §11 amendment: no
technology, table or decision changed. The gate **pages** remain P18's, exactly as [13
§2.2](13-phase-03.md) intended.

The walk is asserted against a path **recomputed from `TRANSITIONS` by breadth-first search**, not
against the constant the code reads — a test that reads the same constant would pass for any path,
including an illegal one.

### 3.2 ⚠️ The shim collects less than the route it replaced

`POST /api/scrape` ran `SubredditScraper`, `KeywordScraper` **and** `UserScraper`. The frozen
job-type list ([04 §2.4](04-system-design.md)) contains no keyword or user type, and the freeze
closes that list.

**A faithful shim therefore does less work while returning byte-identical JSON.** Every contract
assertion passes and the operator's keyword and user leads quietly stop appearing — the failure most
likely to be discovered in production rather than in review.

Three options were put to the operator; **B1 was chosen**: `scrape_subreddit` only, with the drop
documented rather than hidden. B2 (one handler running all three) would have made the job type's
name a lie and per-subreddit progress impossible; B3 (a hybrid) would have kept two execution models
in one route — the shape P3 exists to remove.

**Recorded in five places**, because a behaviour change an operator notices before they read about it
is a bug report: `config.yaml`, the route docstring, `CHANGELOG.md`, [testing/P03-testing.md
T9](testing/P03-testing.md), and [PHASE-03-HANDOVER §4 T1](PHASE-03-HANDOVER.md).

**Unaffected:** `python main.py scrape` still runs all three, and `orchestration.enabled: false`
restores the previous behaviour everywhere.

### 3.3 `orchestration.enabled` was a self-conflict in the plan

[34 §P3](34-implementation-plan.md) says **Config: None** and, four rows later, names
`orchestration.enabled` as the rollback. It is implemented, default `true`, and the retained legacy
thread path is **kept verbatim** rather than tidied — a rollback path that has been rewritten is one
nobody can trust at the moment they need it.

Its test asserts the three scrapers were **constructed**. Asserting `status_code == 200` would have
passed either way: the route returns before the thread does anything, and `NetworkCallBlocked` dies
silently inside it. A second test asserts the opposite branch, so ignoring the switch fails in both
directions.

---

## 4. What was built

| Area | Delivered |
|---|---|
| **Service** | `RunService` — create, transition, fail, cancel, retry, progress, plus the counters handlers keep. `RunOptions`, `RunProgress`, `RunAlreadyActive`, `RunNotFound`, `orchestration_enabled()` |
| **Handlers** | `scrape_subreddit` (one per subreddit), `finalize_run` (idempotent, non-fatal on a failed subreddit). Registry: 1 → 3 |
| **API** | `GET/POST /api/runs`, `GET /api/runs/<id>`, `/progress`, `/events?after=`, `POST /cancel`, `POST /retry`, `GET /api/jobs`, `POST /api/jobs/<id>/retry` |
| **Shim** | `POST /api/scrape` — original keys and status code, `run_id` added |
| **Pages** | `/runs`, `/runs/<id>` with the live feed, a 404 page, the **Runs** nav entry, and the sidebar button that now goes somewhere |
| **JS** | `poll()` — stops on terminal, backs off after three errors, pauses on `document.hidden` |
| **Worker** | Started from `create_app()` via the existing `WORKER_INPROCESS`; `stop_worker()` joins |
| **CLI** | `main.py schedule` enqueues, runs a worker, and logs-and-skips a tick that meets a live run |
| **Health** | `/api/health` gained `queue`: depth, `oldest_queued_at`, and this process's worker |

**P3 owns no migration.** `alembic heads` is still one `0004`.

### 4.1 Deliberately not built

`approve_subreddits` / `approve_keywords` / `set_options` on `RunService` (P18 — no gate data
exists, and a `TODO` body is the placeholder code the quality bar forbids); the three gate pages
(P18); `/api/runs/<id>/estimate` (P18); cross-process worker liveness (needs a heartbeat table no
current phase owns); every AI, discovery, comment and enrichment job type; the nightly `maintenance`
schedule (P24).

---

## 5. Defects found and fixed during the phase

Three were pre-existing; one was introduced and caught by its own test.

### 5.1 `retry()` doubled a run's work — introduced, caught by the first test run

A run can fail with jobs still queued: one subreddit fails for good while three wait. Those three
stay claimable, so enqueueing a fresh set beside them meant **every subreddit was scraped twice on
retry**. `retry()` now abandons the failed attempt's queued jobs first and records how many it
discarded.

Found by `test_retry_from_failed_re_walks_and_re_queues` on its first execution — not by review.

### 5.2 `config.yaml` was read with the locale's default encoding — pre-existing

`src/config.py` opened the file with `open(path, "r")`. On Windows the default is cp1252, so **one
non-ASCII character anywhere in the file — including in a comment — raised `UnicodeDecodeError` from
every command that loads config**: the dashboard, the scraper, the worker.

Surfaced the moment a `⚠️` was added to a config comment. Fixed at the cause (`encoding="utf-8"`,
which is what YAML specifies) rather than by avoiding the character, with a regression test that
loads a config containing a warning sign, an em dash and a bullet.

Latent since the first commit. It survived three phases because nobody had typed a non-ASCII
character into that file.

### 5.3 `RunService.fail()` stored its error unredacted — introduced, caught by review

`jobs.error` is redacted by `JobQueue.fail`; `run_events` is redacted by `emit_event`. `runs.error`
was not, and it is rendered on `/runs/<id>`.

This is **P2's F3 finding for the third time**: the leak is never where the guard is looking.
Redaction is a property of every write to an operator-visible column, not of the module that first
needed it.

### 5.4 The run list issued one count query per row — introduced, caught by review

`/runs` renders fifty rows each showing "jobs done / total". Counting per row is fifty round trips
for one page, growing with the history. Replaced with a single grouped query
(`counts_by_state_for_runs`), pinned by a test that counts statements — invisible at ten runs and
obvious at a thousand, so a timing test on a small fixture would never have caught it.

---

## 6. Mutation testing

[35 §2.4](35-testing-strategy.md) requires it for every **bold** criterion in [34](34-implementation-plan.md).
Each guarantee was broken in the source, the tests were watched go red, and the source restored.

| Criterion | Mutation | Detected by |
|---|---|---|
| **AC1** — response keys unchanged | Renamed `message` to `status` in the shim | 3 tests in `test_scrape_contract.py` |
| **AC2** — real counts, < 50 ms | Replaced the `GROUP BY` with Python-side row counting | `test_progress_answers_within_the_budget_at_five_thousand_jobs` **and** `test_progress_issues_one_query_for_the_job_counts` |
| **AC7** — 409 with the existing run id | Removed the `active_for_project` guard | 4 tests across 3 files |

AC2 is the informative one: the 50 ms budget is **not decorative**. At 5,000 jobs the wrong
implementation is observably slow, and the query-shape test catches it even on a small fixture where
timing would not.

---

## 7. Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| AC1 | `POST /api/scrape` creates a run and completes it; original keys present | ✅ `test_scrape_completes_the_run`, contract tests |
| AC2 | Progress reflects real job counts, responds < 50 ms | ✅ measured at 5,000 jobs; mutation-verified |
| AC3 | Kill mid-run, restart, remaining jobs resume | ✅ 10/10 parameterised iterations |
| AC4 | Retryable error retried with growing backoff to `max_attempts` | ✅ at queue level (P2). **Not reachable from `scrape_subreddit`** — see §8 |
| AC5 | Lease expiry re-runs without duplicating leads | ✅ real expiry, real reclaim, real second execution |
| AC6 | Cancel stops the run; queued jobs become `cancelled` | ✅ incl. the job in flight stopping at its checkpoint |
| AC7 | Second run for the same project → 409 with the existing id | ✅ mutation-verified |
| AC8 | `main.py worker` standalone with `WORKER_INPROCESS=false` | ✅ and `create_app()` starts no worker when off |
| AC9 | SIGTERM finishes the in-flight job, exits < 30 s | ✅ retained from P2; `Worker.join()` added |
| AC10 | `run_events` renders as a live feed | ✅ incremental, `textContent`, stops on terminal |
| AC11 | Maintenance purges jobs, events, cache rows, metrics | ✅ unchanged from P2 |
| AC12 | Illegal transition → 409 naming both states | ✅ caught by name, never as `ValueError` |
| AC13 | No `database is locked` in a 10-minute soak | ✅ see §2 |
| AC14 | 459 leads intact; legacy endpoints unchanged | ✅ |
| AC15 | `ruff` clean, `pytest` passes, coverage ≥ 80% on `src/orchestration/` | ✅ see §2 |

---

## 8. Honest limitations

**AC4 is met at the queue, not through a real scrape.** `RedditClient._get` catches every transport
failure and returns `None` — its own docstring records that raising instead is Phase 6 work. So a
block never reaches `scrape_subreddit` as an exception, and the handler has **no retry mapping**: a
`except BlockedError: raise RetryableError` clause there today would be a branch that cannot execute,
which is the dead code the quality bar forbids. The retry machinery is fully tested at the queue
level (P2), and the mapping belongs in `handlers/scrape.py` the moment P4 makes the transport raise.

**`/health` does not report cross-process worker liveness.** [13 §14](13-phase-03.md) asks for it;
proving a worker in another process is alive needs a heartbeat row, and P3 owns no migration. It
reports what it can know — depth, `oldest_queued_at`, and whether *this* process holds a worker — and
`oldest_queued_at` is the field that actually detects a stalled queue regardless of any flag.

**The 10-minute soak is run by hand, once.** The suite runs a 20-second version; `SOAK_SECONDS=600`
runs the real one, and its measured output is in §2. A criterion met by a shortened proxy, with the
real run recorded, is honest; shipping the 20-second version *as* the soak would not be.

**Two files were edited that [34 §P3](34-implementation-plan.md)'s Files row does not list** —
`routes_health.py` and `index.html` — both mandated by [13 §7/§10/§14](13-phase-03.md). That row
states it is "a guide, not a contract". `src/scrapers/subreddit_scraper.py` and `src/config.py` were
also touched: the first gained two additive keyword arguments that default to previous behaviour, the
second was the encoding fix in §5.2.

---

## 9. Documentation landed

- [ARCHITECTURE_FREEZE §11.1](ARCHITECTURE_FREEZE.md) — the gate-walk reconciliation
- [13 §2.2](13-phase-03.md) — corrected, and the P3 row marked shipped
- [34 §P3](34-implementation-plan.md) — delivered marker with the three decisions
- [CHANGELOG.md](../CHANGELOG.md) — including the ⚠️ behaviour change
- [docs/README.md](README.md) — phase index
- [testing/P03-testing.md](testing/P03-testing.md) — the manual guide, ten tests
- [PHASE-03-HANDOVER.md](PHASE-03-HANDOVER.md) · [progress/P03-COMPLETE.md](progress/P03-COMPLETE.md)
