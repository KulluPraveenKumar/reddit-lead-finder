# PHASE-03 HANDOVER — Run service, API, run pages → P4

**From:** P3 — Run service, API, run pages (complete 2026-08-07)
**To:** P4 — Network provider abstraction
**Companion:** [PHASE-03-COMPLETION-REPORT.md](PHASE-03-COMPLETION-REPORT.md) · [testing/P03-testing.md](testing/P03-testing.md)
**Architecture status:** FROZEN. P3 produced **no amendment** — one §11.1 reconciliation.

> ⚠️ **Not to be confused with the legacy "Phase 03."** [`testing/phase-03-testing.md`](testing/phase-03-testing.md)
> belongs to the **old eight-phase numbering** and is a historical record. This document is about
> **P3** in the frozen [34](34-implementation-plan.md) plan (P0–P30). The two schemes are unrelated.

This document exists so whoever picks up P4 does not have to re-derive P3's decisions from the diff.

---

## 1. What now exists

```
src/orchestration/
├── run_service.py     RunService, RunOptions, RunProgress, SCRAPE_WALK,
│                      RunAlreadyActive, RunNotFound, orchestration_enabled
├── job_queue.py       + requeue()  — the operator's force-retry
├── worker.py          + Worker.thread / Worker.join()
└── handlers/
    ├── scrape.py      handle_scrape_subreddit, build_scraper, load_config
    └── finalize.py    handle_finalize_run

src/dashboard/
├── routes_runs.py     all run + job endpoints, /runs and /runs/<id>, configured_subreddits()
├── routes.py          POST /api/scrape is a shim; _legacy_scrape() retained behind the switch
├── app.py             + start_worker / stop_worker / get_worker
└── templates/         runs.html, run_progress.html, run_missing.html; poll() in _base_ai.html
```

**The pipeline runs end to end for the first time.** Press the button, a run is created, jobs are
claimed, leads are written, the run completes, and the page shows it happening.

### 1.1 The interfaces P4 will use

```python
service = RunService(session)                        # session-scoped; the caller commits
run = service.create(project_id, RunOptions(...))    # raises RunAlreadyActive
service.transition(run_id, RunState.X, reason="…")   # validated + timelined
service.progress(run_id).to_dict()                   # the poll payload
service.cancel_requested(run_id)                     # handlers check this between units
service.note_subreddit_finished(run_id, leads)       # the stats_json counters

from src.orchestration.handlers.scrape import build_scraper   # the network seam
```

---

## 2. Six guarantees P4 must not break

### G1 — `RunService` takes a session; the caller owns the commit

The run row, its seven walk transitions, their `run_events` rows and its jobs all commit together.
A service that opened its own session would give you a run whose jobs were lost to a rollback.

### G2 — A run reaches `SCRAPING` by walking, and the walk has one implementation

`SCRAPE_WALK` is traversed by `_walk_to_scraping()`, used by **both** `create()` and `retry()`.
`FAILED → {PENDING}` is the only edge out of failure, so a retry makes the identical journey. Two
copies would drift, and the retry path is the one nobody looks at.

### G3 — `build_scraper()` is the only line in the orchestrated path that opens a network client

**This is P4's entry point.** When `NetworkPolicy` lands, it is constructed here and nowhere else in
`src/orchestration/`. Every test in the suite fakes this one function to stay offline.

### G4 — The cancel flag lives in `runs.stats_json`

Not a column: P3 owns no migration and a column for one boolean would break the frozen chain. P4
owns no migration either. `RunService.cancel_requested()` is the only reader.

### G5 — `POST /api/scrape` may only gain fields, and may not gain status codes

`tests/baseline/api_scrape_contract.json` was recorded **before** the route was touched.
`tests/test_scrape_contract.py` replays it. The status code is part of that contract: the sidebar
does `fetch(...).then(r => r.json())` with no status check, so a 409 renders as "Scrape complete!".

### G6 — Nothing writes a job state outside `JobQueue`

P2's G4, still true. `POST /api/jobs/<id>/retry` goes through `JobQueue.requeue()`, which runs
`assert_job_transition` and grants one extra attempt to an exhausted job.

---

## 3. What P3 deliberately did NOT do

| Not done | Owner |
|---|---|
| Keyword and user scraping through the queue. **See §4 T1 — this is a live behaviour change** | P5 / P17 |
| `approve_subreddits`, `approve_keywords`, `set_options` on `RunService` — no gate data exists, and a `TODO` body is placeholder code | P18 |
| The gate **pages** `/runs/<id>/subreddits`, `/runs/<id>/keywords`, `/runs/<id>/options` | P18 |
| `GET /api/runs/<id>/estimate` | P18 |
| Cross-process worker liveness on `/health` — needs a heartbeat table | The phase that adds one |
| Any migration. `alembic heads` is still one `0004` | — |
| Scheduling the nightly `maintenance` job | P24 |
| Multi-worker concurrency. The claim is safe for it; the default is one | — |

---

## 4. Traps waiting in P4

**T1 — a scrape now collects less than it did, and that is intentional.** `POST /api/scrape` and
`python main.py schedule` run `scrape_subreddit` only; the keyword and user scrapers are not reached
from those paths. The frozen job-type list has no type for them. **Do not "fix" this in P4** — it is
P5/P17's, and `orchestration.enabled: false` plus `python main.py scrape` are the documented
workarounds. An operator reporting "fewer leads than before" is seeing this, not a regression.

**T2 — every test in the suite is offline because it fakes `build_scraper`.** P4 replaces what that
function constructs. If you change its signature, roughly a dozen tests across four files patch it by
name. Keep the name and the one-argument shape, or update them all deliberately.

**T3 — `create_app()` starts a worker thread.** `tests/conftest.py`'s `app` fixture sets
`WORKER_INPROCESS=false` **before** `create_app` runs, because a background thread claiming jobs
turns every queue assertion into a race with itself. Any new fixture that builds an app needs the
same, and `stop_worker()` **joins** the thread — `stop()` alone only sets an event, and the engine
gets disposed underneath a still-running loop.

**T4 — the handler's transaction is not the scraper's.** `SubredditScraper.run()` commits its own
leads per subreddit, so when the handler returns, the leads are durable and the stats update and the
finalise enqueue are not yet. If the handler then raises, the worker rolls back only the latter and
the job is retried — and because the scrape is idempotent, the retry writes no duplicate leads and
re-evaluates the finalise check. **The window closes itself.** Do not "fix" it by wrapping the
scraper's commit; that would lose partial collection on every failure.

**T5 — `RedditClient._get` swallows every transport failure and returns `None`.** So a block does not
reach the handler as an exception, and `scrape_subreddit` has **no retry mapping** — a
`except BlockedError: raise RetryableError` clause there today would be a branch that cannot execute.
**P4 is where that changes.** When the transport starts raising, the mapping belongs in
`handlers/scrape.py`, and AC4's end-to-end retry becomes assertable through a real scrape.

**T6 — the run page renders `jobs.error` and `run_events.message` into HTML.** Both are redacted on
write, and `tests/test_run_pages.py` asserts it again at the template. `RunService.fail()` was
storing its error **unredacted** until this phase caught it — the third time P2's F3 pattern has
appeared. Assume the fourth sink exists.

**T7 — `_is_last_scrape_job` excludes the current job on purpose.** The queue marks it `done` in its
own transaction *after* the handler returns (P2's G3), so counting it would mean the finaliser is
never queued at all. It also checks that no finaliser exists yet, which is what keeps this correct
under more than one worker.

---

## 5. Findings from P3 worth carrying forward

| # | Finding | Lesson for P4 |
|---|---|---|
| **F1** | `retry()` doubled the work. A run can fail with jobs still queued; those stay claimable, so a fresh set was enqueued beside them. Found by the first run of the new test file, not by review | **Retry paths need the same tests as first-run paths.** They are exercised rarely and read rarely |
| **F2** | `config.yaml` was read with the locale's default encoding. One `⚠️` in a comment raised `UnicodeDecodeError` from every command that loads config | A latent bug can sit for three phases because nobody typed a non-ASCII character. **Fix the encoding, not the character** |
| **F3** | `RunService.fail()` stored the error unredacted into a column the run page renders | P2's F3, again, in a new sink. Redaction is a property of *every write to an operator-visible column*, not of the module that first needed it |
| **F4** | The first test double for the scraper was not idempotent, so the idempotence test failed for a reason the product does not have | **A fake must reproduce the property under test.** A fake that is easier than reality tests the fake |
| **F5** | Two tests asserted strings the page never contains (`/api/runs/1/progress`, built in JS as `'/api/runs/' + RUN_ID + '/progress'`) | Assert on what the artefact contains, not on what you pictured it containing |
| **F6** | Mutation testing: replacing the progress `GROUP BY` with Python-side counting failed **both** the 50 ms budget test and the query-shape test | The budget test is real, not decorative — at 5,000 jobs the wrong implementation is observably slow |

---

## 6. Verification snapshot at handover

| | |
|---|---|
| Full suite | **579 passed, 2 skipped** · 180 s |
| Under `-W error::DeprecationWarning` | **579 passed, 2 skipped** |
| New P3 tests | **151** |
| `ruff check` / `ruff format --check` | All checks passed! / 90 files already formatted |
| Coverage, `src/orchestration/` | **97 %** |
| `alembic heads` | `0004_orchestration (head)` — one head, no migration added |
| Round-trip on a live-DB copy | `upgrade → downgrade -1 → upgrade` · 459 leads intact |
| `check_schema.py` | **OK — all 25 checks passed** |
| Live DB | 459 leads · `intent_score` max 164.28 / avg 42.29 · orchestration tables empty |
| 10-minute soak | `64950 claims, 133653 reads, 68248 progress polls, **0 errors**` |
| Progress p95 at 5,000 jobs | **< 50 ms**, one query |
| Mutation testing | 3 mutations, 3 detected |

---

## 7. Blockers carried into P4

| ID | Blocker | Blocks P4? |
|---|---|---|
| **D1** | P00–P03 manual sign-off tables are unsigned | **By the project's own rule, yes.** [lock §4](EXECUTION_MODE_LOCK.md) requires manual testing completed and signed by a human. P3 was implemented on the operator's declaration that P2's sign-off is complete; the tables in the repository are still blank |
| **B3 / O2** | `mypy` required by [35 §2](35-testing-strategy.md) check 3, not installed | **No** — but the gate cannot be claimed in full |
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` | **No** — gates P23 |
| **R7** | GitHub CI runs for recent commits | **No** — external; check `gh run list` at the start of P4 |
| **N1** | **New in P3.** Keyword and user leads are no longer collected by the button or the scheduler | **No** — it is P5/P17's scope, documented in three places, with two workarounds |

---

## 8. Entry conditions for P4

- [ ] `docs/testing/P03-testing.md` sign-off table signed (and P00–P02, still outstanding)
- [ ] `docs/34-implementation-plan.md` P4 read in full — all thirteen fields
- [ ] [08](08-proxy-service.md) §3a/§7/§3.4/§10 read — P4's design owns four documents, not one
- [ ] P0's **U8 block-rate measurement** re-read from [SPRINT-0-MEASUREMENTS.md](SPRINT-0-MEASUREMENTS.md); it is P4's stated dependency and decides whether residential proxies are bought
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] **All 251 `src/net/` tests recorded green before the refactor begins** — P4's acceptance says they must pass or each change be justified, and that is only checkable against a recorded baseline
