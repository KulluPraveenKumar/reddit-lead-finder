# Phase 03 — Orchestration: Runs, Jobs & Worker

> **Split across three phases by [34](34-implementation-plan.md).** This document remains the design;
> the execution is:
>
> | Phase | Scope | Status |
> |---|---|---|
> | **P1** | `0004` migration, `Run`/`Job`/`RunEvent` models, `RunState`/`JobState`, transition table | ✅ **shipped 2026-08-05** — [PHASE-01-HANDOVER.md](PHASE-01-HANDOVER.md) |
> | **P2** | `JobQueue`, `Worker`, handler registry, `maintenance`, structured logging | ✅ **shipped 2026-08-06** — [PHASE-02-HANDOVER.md](PHASE-02-HANDOVER.md) |
> | **P3** | `RunService`, run API, `/runs` pages, `POST /api/scrape` shim | pending |
>
> **Scheduling is deferred to P24** (`hermes cron` replaces the `schedule` library);
> §2.1's per-project scheduling is out of scope for all three.

**Completion after this phase: 34%**

## 1. Objective

Replace the fire-and-forget daemon thread with a **persisted run state machine and a durable job
queue**, so that the pipeline can pause at human review gates, survive process restarts, retry
individual stages, and report real progress.

This is the phase that makes the two review gates architecturally possible. A thread cannot wait a
day for a human.

## 2. Scope

### 2.1 In scope

- `runs`, `jobs`, `run_events` tables (revision `0004`) + `scrape_runs.run_id`
- `RunState` / `JobState` enums with a validated transition table
- `JobQueue` with atomic claim-and-lease, retry with jittered backoff, lease reclamation
- `Worker` loop with heartbeat, graceful shutdown, and a handler registry
- `RunService`: create, transition, cancel, retry, progress
- Handler for one job type end-to-end — `scrape_subreddit` — proving the machinery with existing code
- `POST /api/scrape` reimplemented as a thin shim over the queue (**identical response shape**)
- In-process worker by default (`WORKER_INPROCESS=true`), separate-process mode supported
- `python main.py worker`
- Run list + run detail pages with live progress
- `maintenance` job for retention purges

### 2.2 Out of scope

- AI job types (Phase 4)
- Discovery / keyword job types (Phase 5)
- Comment / analysis job types (Phases 6–7)
- The review gate UIs (Phase 5) — the *states* exist, but nothing enters them yet
- Multi-worker concurrency (the claim is written to be safe for it; the default is one)

## 3. Architecture

```
  Flask route                                Worker thread/process
  ───────────                                ─────────────────────
  RunService.create()                        loop:
      └─ runs row (PENDING)                    queue.reclaim_expired()
      └─ queue.enqueue(job)                    job = queue.claim(worker_id)
                                               │  BEGIN IMMEDIATE
                                               │  SELECT ... WHERE state='queued'
                                               │  UPDATE ... WHERE id=? AND state='queued'
                                               │  COMMIT
                                               ├─ heartbeat thread extends lease
                                               ├─ handler(session, job)
                                               │     ├─ does work
                                               │     ├─ writes results
                                               │     ├─ appends run_events
                                               │     └─ may transition run + enqueue next job
                                               ├─ queue.complete(job)  or  queue.fail(job)
                                               └─ sleep(poll_interval) when idle

  GET /api/runs/<id>/progress  ──► counts from jobs GROUP BY state + runs.stats_json
```

**The handler is where a stage's outcome and the next stage's enqueue happen in the same
transaction.** That atomicity is what prevents the "stage finished but the next one was never
queued" class of bug.

## 4. Files affected

**New**

| File | Purpose |
|---|---|
| `migrations/versions/0004_orchestration.py` | `runs`, `jobs`, `run_events`, `scrape_runs.run_id` |
| `src/orchestration/__init__.py` | |
| `src/orchestration/states.py` | Enums + `TRANSITIONS` + `assert_transition` |
| `src/orchestration/job_queue.py` | `JobQueue` |
| `src/orchestration/worker.py` | `Worker`, heartbeat, shutdown |
| `src/orchestration/run_service.py` | `RunService`, `RunProgress`, `RunOptions` |
| `src/orchestration/handlers/__init__.py` | `REGISTRY` |
| `src/orchestration/handlers/scrape.py` | `scrape_subreddit` |
| `src/orchestration/handlers/finalize.py` | `finalize_run` |
| `src/orchestration/handlers/maintenance.py` | Retention purges |
| `src/db/repositories/runs.py` | `RunRepository`, `JobRepository` |
| `src/obs/events.py` | `emit_event(session, run_id, event, **data)` |
| `src/obs/logging.py` | Structured JSON logging + `RedactingFilter` |
| `src/dashboard/routes_runs.py` | Run endpoints |
| `src/dashboard/templates/runs.html` | Run list |
| `src/dashboard/templates/run_progress.html` | Run detail |

**Modified**

| File | Change |
|---|---|
| `src/db/models.py` | +`Run`, `Job`, `RunEvent`; `ScrapeRun.run_id` |
| `src/dashboard/routes.py` | `POST /api/scrape` → enqueue; **response shape unchanged** |
| `src/dashboard/app.py` | Registers `routes_runs`; optionally starts the in-process worker |
| `main.py` | `worker` subcommand; `schedule` enqueues instead of calling scrapers |
| `src/scrapers/base.py` | `ScrapeContext` gains `run_id` |

## 5. Database changes

Revision `0004_orchestration` — DDL in [05 §5.3](05-database-plan.md):

- `runs` — state, options, stats, cost, error, timestamps
- `jobs` — type, payload, state, priority, attempts, `available_at`, `worker_id`,
  `lease_expires_at`, result, error
- `run_events` — append-only timeline
- `ALTER TABLE scrape_runs ADD COLUMN run_id INTEGER NULL` — existing 10 rows keep `NULL`

**Deferred foreign key.** `runs.project_id` references `projects`, which does not exist until
`0005` (Phase 4). It is therefore created **nullable and without a `REFERENCES` clause**; the
constraint and the `NOT NULL` tightening are applied in `0005` via `batch_alter_table`. `0004` also
adds the deferred `ai_calls.run_id` FK left open by `0002`. See
[05 §7.1](05-database-plan.md).

```python
# 0004_orchestration, after creating `runs`
with op.batch_alter_table("ai_calls") as b:
    b.create_foreign_key("fk_ai_calls_run", "runs", ["run_id"], ["id"], ondelete="SET NULL")
```

Indexes, with the claim index column order matching the claim query exactly:

```sql
CREATE INDEX ix_jobs_claim ON jobs (state, available_at, priority, id);
CREATE INDEX ix_jobs_run   ON jobs (run_id, state);
CREATE INDEX ix_jobs_lease ON jobs (state, lease_expires_at);
CREATE INDEX ix_runs_project_state ON runs (project_id, state);
CREATE INDEX ix_run_events_run ON run_events (run_id, id);
```

## 6. APIs

**New**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/runs` | List; filter by `project_id`, `state` |
| `POST` | `/api/runs` | `{project_id?, options}` → creates a run, enqueues the first job |
| `GET` | `/api/runs/<id>` | Full run |
| `GET` | `/api/runs/<id>/progress` | **Polled every 3 s — must respond in < 50 ms** |
| `GET` | `/api/runs/<id>/events?after=<id>` | Incremental feed |
| `POST` | `/api/runs/<id>/cancel` | |
| `POST` | `/api/runs/<id>/retry` | From `FAILED` only; 409 otherwise |
| `GET` | `/api/jobs?run_id=` | Debug view |
| `POST` | `/api/jobs/<id>/retry` | Force-requeue one job |

**Modified**

`POST /api/scrape` — now creates a run and enqueues jobs, but **returns
`{"ok": true, "message": "Scrape started in background"}` exactly as today**, plus a new `run_id`
field. Adding a field is backward compatible; changing or removing one is not.

## 7. UI changes

**`/runs`** — a table of recent runs: id, project, state badge, leads found, duration, actions.

**`/runs/<id>`** — the progress page from [09 §3.6](09-dashboard-plan.md): progress bar, stage
label, counters, ETA, cancel button, and a live activity feed backed by `run_events`.

A "Runs" link is added to the header. The existing "Run Scraper" sidebar button now navigates to
the new run page after firing, instead of showing a status line that never updates — a genuine
improvement to an existing feature.

## 8. AI changes

**None functionally** — but this phase is what makes every later AI stage *runnable*. Website
intelligence (P4), discovery (P5), and enrichment (P7) are all multi-minute, multi-call jobs with
retries and human gates in the middle. They exist as `AIService` methods after Phase 1; they become
**executable pipeline stages** only once there is a persisted state machine and a worker to drive
them.

Two orchestration decisions exist specifically to serve the AI stages:

- **`enrich_leads` is a single job running a bounded concurrency pool**, not one job per item.
  DeepSeek has no batch endpoint, and one job per item would multiply queue overhead by thousands
  while losing the shared, cached prompt prefix that makes enrichment cheap.
- **`InsufficientBalanceError` and `BudgetExceededError` are non-retryable and drain the pool
  cleanly**, so a run that runs out of credit finishes as `complete` with `partial_analysis` rather
  than burning its retry budget on an error that will never resolve by itself.

## 9. Backend changes

### 9.1 Atomic claim

```python
def claim(self, worker_id: str, lease_seconds: int = 900) -> Job | None:
    now = utcnow()
    with self.engine.begin() as conn:          # BEGIN IMMEDIATE via isolation_level
        row = conn.execute(text("""
            SELECT id FROM jobs
             WHERE state='queued' AND available_at <= :now
             ORDER BY priority ASC, id ASC LIMIT 1
        """), {"now": now}).first()
        if row is None:
            return None
        n = conn.execute(text("""
            UPDATE jobs
               SET state='running', worker_id=:wid, started_at=:now,
                   lease_expires_at=:exp, attempts=attempts+1
             WHERE id=:id AND state='queued'
        """), {...}).rowcount
        if n == 0:
            return None                        # lost the race; next tick retries
    return self.get(row.id)
```

The `AND state='queued'` guard is what makes this safe for N workers. With one worker it is
redundant; writing it now costs nothing and removes a future footgun.

### 9.2 Handler contract

```python
Handler = Callable[[Session, Job], dict | None]

def handle_scrape_subreddit(session: Session, job: Job) -> dict:
    p = job.payload
    run = session.get(Run, job.run_id)
    ctx = ScrapeContext(**p)
    emit_event(session, run.id, "scrape.subreddit.start", subreddit=ctx.subreddit)
    report = SubredditScraper(client, config, repo).run(session, ctx)
    emit_event(session, run.id, "scrape.subreddit.done", **report.as_dict())
    if _all_scrape_jobs_done(session, run.id):
        JobQueue(session).enqueue("finalize_run", run_id=run.id, payload={})
    return report.as_dict()
```

**Every handler must be idempotent**, because a lease can expire mid-execution and the job will be
re-claimed. For scraping, `reddit_id` dedup provides this for free.

### 9.3 Worker lifecycle

```python
def start_inprocess_worker(app) -> Worker:
    w = Worker(JobQueue(), REGISTRY, poll_interval=2.0)
    t = threading.Thread(target=w.run_forever, name="worker", daemon=True)
    t.start()
    atexit.register(w.stop)
    return w
```

Started from `create_app()` when `WORKER_INPROCESS` is true (the default), so the operator's
`python main.py dashboard` keeps being the only command they need. Graceful shutdown: `stop()` sets
the event, the in-flight job completes, the lease is released.

### 9.4 Concurrency guard

The [00 §4.9](00-current-state.md) double-click problem is solved structurally: `RunService.create`
refuses to create a second run for the same project while one is in a non-terminal state, returning
`409` with the existing run's id. The UI navigates to that run instead of starting another.

### 9.5 Maintenance job

Enqueued daily by the scheduler:

```
DELETE FROM jobs        WHERE state='done'  AND finished_at < now-30d
DELETE FROM run_events  WHERE run_id IN (SELECT id FROM runs WHERE finished_at < now-90d)
DELETE FROM http_cache  WHERE expires_at < now
DELETE FROM metrics     WHERE recorded_at < now-14d
VACUUM                  -- only if the freed page count exceeds a threshold
```

Without this, `http_cache` alone grows without bound.

## 10. Frontend changes

- `runs.html`, `run_progress.html` — new
- `poll()` helper in shared JS: stops on terminal state, backs off after 3 consecutive errors,
  pauses on `document.hidden`
- Sidebar "Run Scraper" button now redirects to `/runs/<new_id>`

## 11. Risks

| Risk | Mitigation |
|---|---|
| Lease expiry causes duplicate work | Every handler idempotent; unique constraints as backstop; `IntegrityError` handled as skip |
| Worker dies silently, jobs sit `running` forever | `reclaim_expired()` every tick; `/health` reports worker liveness via a heartbeat timestamp |
| `POST /api/scrape` contract broken | Contract test replays the recorded request/response; only additive fields allowed |
| Progress endpoint too slow under polling | `GROUP BY state` over `ix_jobs_run`; response asserted < 50 ms in tests |
| Worker and Flask deadlock on SQLite | WAL + `busy_timeout` from Phase 2; worker is the sole bulk writer; short transactions |
| A job loops forever re-enqueueing itself | `max_attempts` per job type, enforced in the queue, not by the handler |
| Cancel leaves orphaned running jobs | `cancel()` marks queued jobs cancelled and sets a run-level flag the running handler checks between pages |

## 12. Dependencies

**Upstream:** Phase 1 (Alembic, WAL, `session_scope`, logging, `AIService`), Phase 2 (proxied client, repositories).

**New packages:** none.

## 13. Acceptance criteria

- [ ] AC1 — `POST /api/scrape` creates a run and completes it; response contains the original keys
- [ ] AC2 — `GET /api/runs/<id>/progress` reflects real job counts and responds in < 50 ms
- [ ] AC3 — Killing the process mid-run and restarting resumes the remaining jobs
- [ ] AC4 — A job that raises a retryable error is retried with growing backoff, up to `max_attempts`
- [ ] AC5 — A job whose lease expires is reclaimed and re-run without duplicating leads
- [ ] AC6 — `POST /api/runs/<id>/cancel` stops the run; queued jobs become `cancelled`
- [ ] AC7 — Starting a second run for the same project returns 409 with the existing run id
- [ ] AC8 — `python main.py worker` runs standalone with `WORKER_INPROCESS=false`
- [ ] AC9 — SIGTERM finishes the in-flight job and exits cleanly within 30 s
- [ ] AC10 — `run_events` renders as a live feed on `/runs/<id>`
- [ ] AC11 — Maintenance purges old jobs, events, cache rows, and metrics
- [ ] AC12 — Illegal transition raises and returns 409 with both states named
- [ ] AC13 — No `database is locked` during a 10-minute concurrent read/write soak
- [ ] AC14 — 459 leads intact; all 17 legacy endpoints unchanged
- [ ] AC15 — `ruff` clean; `pytest` passes; coverage ≥ 80% on `src/orchestration/`

## 14. Completion checklist

- [ ] Revision `0004` with downgrade
- [ ] `RunState` / `JobState` enums + transition table + `assert_transition`
- [ ] `JobQueue.enqueue / claim / heartbeat / complete / fail / reclaim_expired`
- [ ] Claim uses `BEGIN IMMEDIATE` + the `state='queued'` guard
- [ ] Per-job-type `max_attempts` and jittered exponential backoff
- [ ] `Worker` with handler registry, heartbeat thread, graceful shutdown
- [ ] In-process worker default; standalone mode supported
- [ ] `RunService` create / transition / cancel / retry / progress
- [ ] Duplicate-run guard returning 409
- [ ] `scrape_subreddit` handler wrapping the existing scraper
- [ ] `finalize_run` handler
- [ ] `maintenance` handler with all four purges
- [ ] `emit_event` + `run_events`
- [ ] Structured logging with `run_id` / `job_id` and the redaction filter
- [ ] `POST /api/scrape` shim, contract-tested
- [ ] Run endpoints implemented
- [ ] `/runs` and `/runs/<id>` pages with live polling
- [ ] `poll()` helper with backoff and visibility handling
- [ ] `python main.py worker`
- [ ] Scheduler enqueues instead of calling scrapers directly
- [ ] `/health` reports worker liveness and queue depth
- [ ] `docs/testing/phase-03-testing.md` Part A complete
- [ ] `docs/testing/phase-03-testing.md` Part B executed and recorded
