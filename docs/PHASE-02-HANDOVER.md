# PHASE-02 HANDOVER — Job queue, worker, logging → P3

**From:** P2 — Job queue, worker, structured logging (complete 2026-08-06)
**To:** P3 — Run service, API, run pages
**Companion:** [PHASE-02-COMPLETION-REPORT.md](PHASE-02-COMPLETION-REPORT.md) · [testing/P02-testing.md](testing/P02-testing.md)
**Architecture status:** FROZEN. P2 produced **no amendment**.

> ⚠️ **Not to be confused with the legacy "Phase 02."** [`PHASE-02-STATUS.md`](PHASE-02-STATUS.md)
> and [`testing/phase-02-testing.md`](testing/phase-02-testing.md) belong to the **old eight-phase
> numbering** (proxy & transport) and were completed 2026-07-31. This document is about **P2** in the
> frozen [34](34-implementation-plan.md) plan (P0–P30). The two schemes are unrelated.

This document exists so whoever picks up P3 does not have to re-derive P2's decisions from the diff.

---

## 1. What now exists

```
src/orchestration/
├── __init__.py        re-exports the whole runtime surface
├── states.py          P1 — unchanged
├── job_queue.py       JobQueue, MAX_ATTEMPTS, backoff_seconds, RetryableError, payload_of, utcnow
├── worker.py          Worker, start_inprocess_worker, run_standalone, worker_inprocess_enabled
└── handlers/
    ├── __init__.py    REGISTRY, Handler
    └── maintenance.py handle_maintenance — four purges

src/obs/
├── logging.py         configure_logging, log_context, redact, RedactingFilter, ContextFilter
└── events.py          emit_event

src/db/repositories/runs.py   RunRepository, JobRepository
```

Import from the **package**, not the module:

```python
from src.orchestration import JobQueue, Worker, RetryableError, utcnow
```

### 1.1 The interfaces P3 will use

```python
queue = JobQueue()                                  # engine from src.db.database
queue.enqueue("scrape_subreddit", run_id=run.id, payload={...}, session=s)
queue.cancel_queued(run_id)                         # -> rows cancelled; running jobs untouched

JobRepository(session).counts_by_state(run_id)      # -> {"queued": 3, "done": 7}  the progress query
JobRepository(session).queue_depth()                # -> {"queued", "running", "failed", "oldest_queued_at"}
RunRepository(session).active_for_project(pid)      # -> Run | None   the 409 guard
RunRepository(session).events(run_id, after_id=n)   # -> the incremental feed
```

---

## 2. Five guarantees P3 must not break

### G1 — `enqueue(session=...)` is how a stage queues its successor

Passing a session enlists the insert in the **caller's** transaction, so "this stage finished" and
"the next stage is queued" commit together. Calling `enqueue()` without a session opens its own short
transaction and commits immediately — correct for a web route creating the first job, **wrong** for a
handler, where it would queue the next stage even if the current one rolled back. Both paths are
tested.

### G2 — Every handler is idempotent, because every handler runs twice eventually

A lease expires; the job is reclaimed; the handler runs again. That is designed behaviour, not a
failure. `scrape_subreddit` gets this free from `reddit_id` dedup. `finalize_run` will not — write it
so that finalising an already-finalised run is a no-op.

### G3 — The queue's transaction is not the handler's

The handler gets its own `Session`, committed by the worker on success and rolled back on any
exception. The queue records `complete`/`fail` in a **separate** short transaction, so a rollback
never erases the record of *why* it rolled back. Do not "simplify" these into one.

### G4 — Nothing writes a job state outside `JobQueue`

`assert_job_transition` runs inside the queue's methods. A route that sets `job.state = 'cancelled'`
directly bypasses it. Use `cancel_queued()`.

### G5 — `WORKER_INPROCESS` is the rollback switch, and it is an environment variable

`start_inprocess_worker()` already honours it and returns `None` when disabled. When P3 calls it from
`create_app()`, **do not add a second config key for the same thing** — one switch, one place.

---

## 3. What P2 deliberately did NOT do

| Not done | Owner |
|---|---|
| Enqueue anything at all. **Nothing puts work in the queue yet** | P3 |
| `RunService` — create / transition / cancel / retry / progress | P3 |
| Any HTTP endpoint or page; `POST /api/scrape` shim | P3 |
| Start the worker from `create_app()` — `src/dashboard/app.py` is P3's file | P3 |
| `scrape_subreddit`, `finalize_run` handlers — the registry has **one** entry | P3 |
| Scheduling the `maintenance` job. The handler exists; nothing runs it nightly | P24 |
| Any migration. `alembic heads` is still one `0004` | — |

**`data/leads.db` is at `0004_orchestration` and needs no change for P3.** The `runs`, `jobs` and
`run_events` tables exist and are empty. P3 is the phase that first writes rows to them.

---

## 4. Traps waiting in P3

**T1 — `POST /api/scrape` must keep its exact response keys.** [13 §6](13-phase-03.md): it returns
`{"ok": true, "message": "Scrape started in background"}` today, and may only **add** `run_id`.
Changing or removing a key breaks R20. Record the current response before touching the route.

**T2 — the progress endpoint has a 50 ms budget at 5,000 jobs.** `JobRepository.counts_by_state()` is
one `GROUP BY` over `ix_jobs_run` and is the intended implementation. Do not load `Job` rows and count
in Python; do not add a second query per state.

**T3 — the duplicate-run guard is `RunRepository.active_for_project()`, and it excludes terminal
states rather than listing active ones.** If P12 adds a thirteenth `RunState`, that method treats it
as active automatically. Keep it that way — the failure mode of the other spelling is a run that can
be started twice.

**T4 — cancellation cannot stop a running handler.** `cancel_queued()` marks queued jobs cancelled;
the job in flight finishes. [13 §11](13-phase-03.md) calls for a run-level flag the handler checks
between pages. That flag is P3's to add, and `runs.stats_json` is where it belongs — **not** a new
column (that would need a migration P3 does not own).

**T5 — the in-process worker runs in a daemon thread, so it cannot install signal handlers.**
`install_signal_handlers()` is guarded and silently does nothing off the main thread. Flask owns the
signals in that mode; call `worker.stop()` from an `atexit` hook, as [13 §9.3](13-phase-03.md) shows.

**T6 — the lease is 900 s and no current handler comes close.** `scrape_subreddit` is the first that
might. The heartbeat extends it every 300 s while the handler runs, so a long scrape is safe — but a
handler that blocks the thread without returning to the loop (a `time.sleep` inside a retry, say) is
still covered, whereas one that forks or waits on a subprocess is not. Measure the first real scrape.

---

## 5. Findings from P2 worth carrying forward

| # | Finding | Lesson for P3 |
|---|---|---|
| **F1** | The `AND state='queued'` guard changes no outcome while `BEGIN IMMEDIATE` holds the lock. The docs said "either alone loses the race"; measurement says otherwise | When a document explains a mechanism, **test the mechanism, not the sentence.** The guard was extracted so it could be tested where it is observable |
| **F3** | A credential in an *exception message* reached the log: the filter redacts `exc_text`, but a traceback does not exist until a formatter renders it | The leak is never where the guard is looking. P3 renders `jobs.error` and `run_events.message` into HTML — both are redacted on write, but assert it at the template too |
| **F4** | The soak passed with `busy_timeout=0` because one writer never contends with itself | **A test that cannot fail is not evidence.** Before trusting a concurrency test, break the thing it guards and watch it go red |
| **F5** | A shutdown test detected an infinite loop by hanging the suite | Give any test that could hang a join deadline |
| **F6** | `migrations/env.py` silently disabled every logger in the running application | Documented in the completion report §6. If logging ever goes quiet again, look there first |

F1, F3 and F4 were found only by mutation testing.

---

## 6. Verification snapshot at handover

| | |
|---|---|
| Full suite | **428 passed, 2 skipped**, 11 warnings, **95–170 s** (wall-clock bound: the claim race and the soak dominate) |
| New P2 tests | **120 passed** |
| `ruff check` / `ruff format --check` | All checks passed! / 80 files already formatted |
| Coverage, `src/orchestration/` | **97%** |
| `alembic heads` | `0004_orchestration (head)` — one head |
| `alembic current` (live DB) | `0004_orchestration` |
| `check_schema.py` | **OK — all 25 checks passed** |
| Live DB | 459 leads · `intent_score` max 164.28 / avg 42.29 · orchestration tables empty. mtime moved (the worker was started against it once); no row written |
| 10-minute soak | `27931 claims, 27931 events, 62168 reads, **0 errors**` |
| Mutation testing | 10 mutations, 10 detected |
| Clean-environment CI simulation | install · lint · format · **428 passed, 2 skipped** |

---

## 7. Blockers carried into P3

| ID | Blocker | Blocks P3? |
|---|---|---|
| **D1** | P00, P01 **and P02** manual sign-off tables are unsigned | **By the project's own rule, yes.** [lock §4](EXECUTION_MODE_LOCK.md) requires manual testing completed and signed by a human. P2 was implemented on the operator's declaration that sign-off is complete; the tables in the repository are still blank |
| **B3 / O2** | `mypy` required by [35 §2](35-testing-strategy.md) check 3, not installed | **No** — but the gate cannot be claimed in full |
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` | **No** — gates P23 |
| **R7** | GitHub created no CI run for either P2 commit, with Actions enabled and the workflow active | **No** — external. Verified locally twice in a clean venv. Check `gh run list` at the start of P3; `gh workflow run CI --ref main` forces one |
| — | Multireddit volume anomaly | **No** — scheduled for P6 |

---

## 8. Entry conditions for P3

- [ ] `docs/testing/P02-testing.md` sign-off table signed (and P00/P01, still outstanding)
- [ ] `docs/34-implementation-plan.md` P3 read in full — all thirteen fields
- [ ] [13 §6](13-phase-03.md) read for the `POST /api/scrape` response contract — **T1**
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] The current `POST /api/scrape` response recorded verbatim, before the route is touched
