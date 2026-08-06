# Phase 03 — Testing: Orchestration (Runs, Jobs, Worker)

---

# PART A — Claude Verification

## A1. Architecture

- [ ] `src/orchestration/` imports nothing from `src/dashboard/`
- [ ] Handlers live in `handlers/`, one module per concern, registered in a single `REGISTRY` dict
- [ ] `RunService` is the only writer of `runs.state`
- [ ] `JobQueue` is the only writer of `jobs.state`
- [ ] `assert_transition` is called on **every** state change (grep: no bare `run.state =`)
- [ ] The worker is startable both in-process and standalone with no code difference
- [ ] `emit_event` is the only writer of `run_events`

## A2. Compilation and imports

- [ ] `python -c "import src.orchestration.worker, src.orchestration.run_service"` succeeds
- [ ] `python main.py worker --help` works
- [ ] Handler registry keys match the documented `job_type` values exactly
- [ ] No circular import between `run_service` and `job_queue`

## A3. Lint / A4. Typing

- [ ] `ruff check .` / `ruff format --check .` clean
- [ ] `RunState` / `JobState` are `str, Enum`
- [ ] `TRANSITIONS` typed `dict[RunState, set[RunState]]`
- [ ] `Handler` type alias defined and used
- [ ] `RunProgress`, `RunOptions`, `Job` are dataclasses or Pydantic models with typed fields

## A5. Edge cases

- [ ] Claim on an empty queue → returns `None`, no exception, no busy-loop
- [ ] Claim when all jobs have `available_at` in the future → `None`
- [ ] Two workers claiming simultaneously → exactly one wins (guard clause)
- [ ] Job with `attempts == max_attempts` → `failed`, not requeued
- [ ] Lease expiry on a job that later completes → completion is a no-op or wins cleanly (documented either way)
- [ ] Cancel a run with no jobs → succeeds
- [ ] Cancel a run mid-job → running job finishes; queued jobs cancelled
- [ ] Retry a run not in `FAILED` → 409
- [ ] Illegal transition → `IllegalTransition` raised, not silently ignored
- [ ] `progress()` on a run with zero jobs → 0%, no divide-by-zero
- [ ] Enqueue with an unknown `job_type` → rejected at enqueue time, not at claim time
- [ ] Payload that is not JSON-serialisable → rejected at enqueue
- [ ] Worker with an empty registry → logs and exits rather than spinning

## A6. Error handling

- [ ] Handler exception → job `failed`, traceback logged, worker survives
- [ ] `RetryableError` → requeued with backoff
- [ ] Non-retryable → `failed` immediately
- [ ] Handler that hangs → lease expires and the job is reclaimed
- [ ] DB error inside a handler → `session_scope` rolls back
- [ ] Worker crash → jobs left `running` are reclaimed on next start

## A7. Security

- [ ] Job payloads contain no secrets (asserted for every job type)
- [ ] `run_events.data_json` passes through the redaction filter
- [ ] `/api/jobs` does not expose payload fields marked sensitive
- [ ] `worker_id` is a random/host identifier, not a credential

## A8. Performance

- [ ] `ix_jobs_claim` column order matches the claim query exactly
- [ ] `EXPLAIN QUERY PLAN` on the claim query uses `ix_jobs_claim`
- [ ] `/api/runs/<id>/progress` < 50 ms with 5,000 jobs
- [ ] `reclaim_expired` uses `ix_jobs_lease`
- [ ] Worker idle loop sleeps rather than spinning (CPU ≈ 0 when idle)
- [ ] Heartbeat interval is `lease_seconds / 3`, not per-second

## A9. Scalability

- [ ] Claim query is correct for N workers (guard clause present even though N=1)
- [ ] `jobs` table growth bounded by the maintenance purge
- [ ] `run_events` growth bounded by the maintenance purge
- [ ] Progress computed by `GROUP BY`, not by loading all job rows

## A10. Logging

- [ ] Every log line inside a handler carries `run_id` and `job_id`
- [ ] Job claim / complete / fail logged
- [ ] State transitions logged with the reason
- [ ] Worker start / stop logged
- [ ] Lease reclamation logged at WARNING

## A11. Retries

- [ ] Per-`job_type` `max_attempts` applied
- [ ] Backoff exponential with jitter, capped at 600 s
- [ ] `available_at` set correctly on requeue
- [ ] Non-fatal job types do not fail the run on exhaustion

## A12. AI verification & efficiency

- [ ] `grep -ri "deepseek" src/ --exclude-dir=ai/providers` → still **0**
- [ ] No handler constructs a prompt, model name, or token count
- [ ] `enrich_leads` is **one** job type running gate → dedup → batch → audit internally
- [ ] There is no per-item job type — a 1,000-item run enqueues **one** enrichment job, not 1,000
- [ ] `InsufficientBalanceError` and `BudgetExceededError` are **non-retryable** in the job queue
- [ ] Job payloads contain **no** API key and no prompt text
- [ ] The Phase-1 AI suite still passes; `/settings/ai` and `/health/ai` still render
- [ ] A stored API key survives the `0004` migration
- [ ] **`ai_calls` count is unchanged by orchestration work**

## A13. Regression

- [ ] `POST /api/scrape` returns the original keys **plus** `run_id`
- [ ] Sidebar "Run Scraper" still triggers a scrape
- [ ] `python main.py scrape` still works synchronously (bypasses the queue)
- [ ] `python main.py schedule` enqueues instead of calling scrapers directly
- [ ] 459 leads intact
- [ ] All 17 legacy endpoints unchanged

## A14. Test suite

- [ ] `pytest` passes; coverage ≥ 80% on `src/orchestration/`
- [ ] A test simulates two workers racing for one job
- [ ] A test kills a "worker" mid-job and asserts reclamation
- [ ] A test asserts every legal transition succeeds and every illegal one raises

---

# PART B — Manual Testing

---

## Test 1 — Run creation and completion

**Preconditions** Migrated DB; proxies healthy; dashboard running.

**Steps**
1. Open `/runs` — should be empty or show historical runs.
2. Click "Run Scraper" in the sidebar (or `POST /api/scrape`).
3. Observe the redirect to `/runs/<id>`.
4. Watch the progress bar and activity feed.
5. Wait for completion.
6. `SELECT id, state, started_at, finished_at FROM runs ORDER BY id DESC LIMIT 1;`

**Expected**
- A `runs` row is created immediately with `state='pending'` then `scraping`
- One `jobs` row per subreddit
- Progress bar advances as jobs complete
- Activity feed shows `scrape.subreddit.start` / `.done` events
- Final state `complete`, `finished_at` set
- Leads appear in the database

**Failure behaviour**
- Run stuck at 0% → worker not running; check `/health`
- Progress never updates → polling or the progress endpoint is broken
- State `failed` → read `runs.error` and the failed job's `error`

**Edge cases**
- Zero subreddits configured → run completes immediately with 0 jobs
- One subreddit fails → run still completes (scrape jobs are non-fatal)
- Run with proxies down → jobs retry, then the run fails cleanly

**Success criteria**
- End-to-end run completes; leads created; progress accurate

---

## Test 2 — Restart resilience

**Preconditions** A run in progress with several queued jobs.

**Steps**
1. Start a run across 4+ subreddits.
2. When roughly half the jobs are done, kill the process (Ctrl-C or `kill`).
3. Note which jobs were `done`, `running`, `queued`.
4. Restart `python main.py dashboard`.
5. Watch `/runs/<id>`.
6. Wait for completion; check for duplicate leads.

**Expected**
- On restart, `reclaim_expired()` returns the `running` job to `queued`
- Remaining jobs execute
- The run reaches `complete`
- **No duplicate leads** — dedup on `reddit_id` holds
- Completed jobs are not re-run

**Failure behaviour**
- Run stuck in `scraping` forever → reclamation not working
- Duplicate leads → a handler is not idempotent
- Completed jobs re-run → claim query is selecting `done` rows

**Edge cases**
- Kill during the very first job → full restart, clean
- Kill twice → still recovers
- Restart after the lease has already expired → immediate reclaim

**Success criteria**
- Run resumes and completes with zero duplicates

---

## Test 3 — Job retry with backoff

**Preconditions** Ability to force a handler failure.

**Steps**
1. Temporarily point the proxy pool at unreachable hosts (or set an env flag that makes the scrape handler raise `RetryableError`).
2. Start a run.
3. Watch `jobs.attempts` and `available_at` over time.
4. Restore connectivity before attempts are exhausted.

**Expected**
- `attempts` increments per try
- `available_at` grows: ≈10 s, 20 s, 40 s, 80 s (with jitter)
- Logs show the backoff duration
- After restoration, the job succeeds
- If exhausted, `state='failed'` with the error recorded

**Failure behaviour**
- Immediate retry with no backoff → backoff not applied
- Infinite retries → `max_attempts` not enforced
- Run fails on the first job error → non-fatal classification missing

**Edge cases**
- Failure on the last allowed attempt → `failed`, run continues (non-fatal type)
- A fatal job type failing → run → `failed`

**Success criteria**
- Backoff observed and growing; attempts capped

---

## Test 4 — Lease expiry and reclamation

**Preconditions** Ability to set a short lease.

**Steps**
1. Set `lease_seconds=10` and disable the heartbeat (test flag).
2. Start a job that takes 30 s.
3. Watch `jobs.lease_expires_at` and `state`.
4. Observe reclamation and re-execution.
5. Check for duplicate side effects.

**Expected**
- Lease expires after 10 s
- `reclaim_expired()` sets the job back to `queued`
- The job is claimed again, `attempts` increments
- **No duplicate leads created**

**Failure behaviour**
- Job never reclaimed → `reclaim_expired` not called each tick
- Duplicates created → handler not idempotent

**Edge cases**
- With the heartbeat **enabled**, a 30 s job does **not** get reclaimed (this is the control case — verify it)
- Two reclamations in a row → still no duplicates

**Success criteria**
- Reclamation works; heartbeat prevents it when enabled; no duplicate data

---

## Test 5 — Cancellation

**Preconditions** A run in progress.

**Steps**
1. Start a run across 5 subreddits.
2. After the second subreddit starts, click **Cancel**.
3. Observe the run and jobs.
4. Check the leads created before cancellation.

**Expected**
- Run state → `cancelled`
- Queued jobs → `cancelled`
- The running job finishes its current page and stops (or completes)
- Leads created before cancellation are **kept**
- UI shows the cancelled state clearly

**Failure behaviour**
- Cancel does nothing → not wired
- Leads deleted → cancellation should not destroy collected work
- Worker keeps processing → cancel flag not checked between pages

**Edge cases**
- Cancel an already-complete run → 409
- Cancel a run at a review gate → succeeds immediately
- Cancel twice → idempotent

**Success criteria**
- Cancellation stops future work, preserves completed work

---

## Test 6 — Duplicate-run guard

**Preconditions** A run in progress.

**Steps**
1. Start a run.
2. While it is running, click "Run Scraper" again.
3. Observe the response and the UI.

**Expected**
- Second request returns **409** with the existing `run_id`
- UI navigates to the existing run instead of starting another
- Exactly one active run exists

**Failure behaviour**
- Two runs created → the [00 §4.9](../00-current-state.md) defect is not fixed
- Hard error page → 409 not handled by the frontend

**Edge cases**
- After the first run completes → a second run starts normally
- Two different projects → both can run (guard is per project)

**Success criteria**
- No double-run possible for one project

---

## Test 7 — Standalone worker

**Preconditions** `WORKER_INPROCESS=false` in `.env`.

**Steps**
1. Terminal A: `python main.py dashboard`
2. Confirm no worker starts (log message).
3. Trigger a run — it should sit in `pending`/queued.
4. Terminal B: `python main.py worker`
5. Watch jobs get claimed and executed.
6. Ctrl-C terminal B mid-job.

**Expected**
- Dashboard alone does not process jobs
- Starting the worker picks up queued jobs immediately
- Both processes write to the same DB without lock errors
- Ctrl-C finishes the in-flight job and exits within 30 s
- `/health` shows the worker as alive while it runs, stale after it stops

**Failure behaviour**
- `database is locked` → WAL/busy_timeout regression from Phase 2
- Worker does not exit on Ctrl-C → shutdown handling missing
- Worker kills the job mid-write → transaction boundary wrong

**Edge cases**
- Two workers started → both claim, no double-execution of the same job
- Worker started with no queued jobs → idles at ~0% CPU

**Success criteria**
- Split-process mode works; graceful shutdown < 30 s

---

## Test 8 — Progress endpoint performance

**Preconditions** A run with many jobs (seed 5,000 job rows via a script).

**Steps**
1. Seed 5,000 `jobs` rows across mixed states for one run.
2. `curl -w "%{time_total}\n" -o /dev/null -s http://127.0.0.1:5000/api/runs/<id>/progress` — 10 times.
3. Record the times.
4. `EXPLAIN QUERY PLAN` the progress query.

**Expected**
- Every call < 50 ms
- Query plan uses `ix_jobs_run`
- Counts are correct

**Failure behaviour**
- \> 200 ms → missing index or the query loads rows instead of aggregating
- Wrong counts → grouping bug

**Edge cases**
- 50,000 jobs → still < 200 ms
- Run with 0 jobs → 0%, no error

**Success criteria**
- < 50 ms at 5,000 jobs, index-backed

---

## Test 9 — Activity feed

**Preconditions** A run in progress.

**Steps**
1. Start a run; open `/runs/<id>`.
2. Watch the activity feed for 2 minutes.
3. Verify new entries appear without a full page reload.
4. Switch to another browser tab for 30 s, then return.
5. Let the run complete; confirm polling stops.

**Expected**
- New events appear every few seconds
- Events are ordered newest-first with timestamps
- Warnings (e.g. proxy blacklisted) render in amber
- Polling pauses while the tab is hidden and resumes on return
- Polling stops entirely on a terminal state

**Failure behaviour**
- Feed never updates → `?after=<id>` incremental fetch broken
- Polling continues forever → terminal-state check missing (this drains battery and hammers the DB)
- Duplicated events → `after` cursor not advancing

**Edge cases**
- Very chatty run (hundreds of events) → feed is capped/scrolled, not unbounded
- Network error mid-poll → backs off to 10 s, does not spam

**Success criteria**
- Live feed works, pauses when hidden, stops when done

---

## Test 10 — Maintenance purge

**Preconditions** Ability to insert old rows.

**Steps**
1. Insert: a `done` job with `finished_at` 40 days ago; a `run_events` row for a run finished 100 days ago; an expired `http_cache` row; a `metrics` row 20 days old.
2. Trigger `POST /api/maintenance/run` (or wait for the schedule).
3. Verify each row is gone.
4. Verify recent rows of each type survive.

**Expected**
- Old job, old event, expired cache, old metric all deleted
- Recent equivalents untouched
- Counts logged per category

**Failure behaviour**
- Nothing deleted → purge not wired
- Recent rows deleted → window boundaries wrong (**data loss**)

**Edge cases**
- Empty tables → no error
- Very large purge → completes without locking the DB for minutes

**Success criteria**
- Correct rows purged; counts logged; recent data safe

---

## Test 11 — Illegal transitions

**Preconditions** A completed run.

**Steps**
1. `POST /api/runs/<id>/retry` on a `complete` run.
2. Attempt an out-of-order transition via a Python shell (`RunService.transition(run, RunState.SCRAPING)` from `COMPLETE`).
3. `POST /api/runs/<id>/cancel` on a `cancelled` run.

**Expected**
- Retry on `complete` → 409 naming both states
- Direct illegal transition → `IllegalTransition` raised
- Cancel on `cancelled` → 409 or idempotent success (documented behaviour, consistently applied)

**Failure behaviour**
- Illegal transition succeeds → the state machine is decorative
- 500 instead of 409 → error mapping missing

**Edge cases**
- `COMPLETE → ANALYZING` **is** legal (re-analysis) — verify it succeeds
- `FAILED → PENDING` is legal — verify it succeeds

**Success criteria**
- Legal transitions succeed; illegal ones return 409 with both states named

---

## Sign-off

| Test | Result | Notes |
|---|---|---|
| 1 Run creation | ☐ Pass ☐ Fail | |
| 2 Restart resilience | ☐ Pass ☐ Fail | |
| 3 Retry & backoff | ☐ Pass ☐ Fail | |
| 4 Lease reclamation | ☐ Pass ☐ Fail | |
| 5 Cancellation | ☐ Pass ☐ Fail | |
| 6 Duplicate-run guard | ☐ Pass ☐ Fail | |
| 7 Standalone worker | ☐ Pass ☐ Fail | |
| 8 Progress performance | ☐ Pass ☐ Fail | |
| 9 Activity feed | ☐ Pass ☐ Fail | |
| 10 Maintenance purge | ☐ Pass ☐ Fail | |
| 11 Illegal transitions | ☐ Pass ☐ Fail | |

**Phase 3 complete when Part A is fully ticked and all 11 Part B tests pass.**
