# Manual Testing Guide — P2: Job queue, worker, structured logging

> ⚠️ **This is P2 of the frozen P0–P30 plan ([34](../34-implementation-plan.md)) — NOT the legacy
> "Phase 02."** [`PHASE-02-STATUS.md`](../PHASE-02-STATUS.md) and
> [`testing/phase-02-testing.md`](phase-02-testing.md) belong to the **old eight-phase numbering**
> (proxy & transport, completed 2026-07-31) and are historical records. The two schemes are
> unrelated.

Written so a **non-developer can validate this phase without guessing**. Every step states what you
should see. If what you see differs, that step's *Possible failure* section tells you what it means.

- **Time:** ~35 minutes for the full suite, ~8 minutes for the smoke path (T1–T3).
- **You need:** a terminal. No browser, no API key, no internet.
- **Destructive steps:** none. Nothing in this guide writes to `data\leads.db`. Every test that
  touches a database uses a temporary one that is deleted afterwards.

Throughout, `>` marks a command to run and `→` marks what you should see.

---

## Before you start

> cd <the folder containing pyproject.toml>
> .\.venv\Scripts\python.exe -m pip install -r requirements.txt

→ Finishes without errors. It should install **one** new package, `python-json-logger`, or say
`Requirement already satisfied` if you have it.

**If the app is already running**, stop it first — a stale process keeps port 5000 and serves you
*old code*, which looks exactly like a broken change:

> powershell "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*dashboard*' } | Stop-Process -Force"

**Confirm the live database is untouched before you begin**, so you can prove it afterwards:

> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db

→ Ends with `OK — all 25 checks passed.`

---

# T1 — The suite is green and the code is clean

**Purpose:** prove the phase ships without lint errors, formatting drift, or failing tests.
**Preconditions:** none.

### Step 1 — Lint

> .\.venv\Scripts\python.exe -m ruff check .

→ **Expected:** `All checks passed!`

### Step 2 — Formatting

> .\.venv\Scripts\python.exe -m ruff format --check .

→ **Expected:** `80 files already formatted`

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `N files would be reformatted` | A file was edited after formatting | Run `ruff format .` and re-run the suite |
| `error: Failed to parse` | A syntax error | The file named cannot be imported; the tests will fail too |

### Step 3 — The full suite

> .\.venv\Scripts\python.exe -m pytest

→ **Expected:** `427 passed, 2 skipped, 11 warnings`

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `424 passed, 5 skipped` | You are on a checkout with no `data\leads.db` | Correct for a fresh clone — the three live-database tests skip. Not a failure |
| `429 passed, 0 skipped` | You have `PROXY_FILE` set | Also correct — the two proxy tests can run |
| Any number **failed** | A real failure | Read the first failure only; the rest are usually consequences |
| `NetworkCallBlocked` | A test tried to reach the internet | **This is the guard working.** Report it — no test may make a network call |

**Acceptance:** ✅ Lint clean, format clean, `0 failed`.

---

# T2 — The worker starts, runs a job, and stops cleanly

**Purpose:** prove `python main.py worker` — the phase's standalone-worker deliverable — actually
runs.
**Preconditions:** T1 passed.

### Step 1 — The command exists

> .\.venv\Scripts\python.exe main.py --help

→ **Expected:** the usage block contains this line:

```
  python main.py worker                    Run the job worker in the foreground
```

### Step 2 — Start the worker

> .\.venv\Scripts\python.exe main.py worker

→ **Expected:** a green panel reading `Worker started. Press Ctrl+C to stop.`, then the startup
banner:

```
Migrations      up to date (0004_orchestration)
AI provider     ...
```

followed by one log line naming this worker:

```
23:42:13 INFO  src.orchestration.worker: worker started  [provider=<your-machine>-<pid>-<id>]
```

Then it sits there quietly. **Silence is correct** — nothing enqueues work until P3, so the worker
polls an empty queue every 2 seconds and says nothing.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `Unknown command: worker` | You are running an old copy of `main.py` | You are in the wrong folder, or the change did not land |
| `no such table: jobs` | The database is behind | Run `.\.venv\Scripts\python.exe main.py migrate status` |
| A wall of log lines | The log level is `DEBUG` | Check `logging.level` in `config.yaml`; `INFO` is expected |

### Step 3 — Stop it

Press **Ctrl+C**.

→ **Expected:** the worker exits **within a couple of seconds**, printing:

```
Worker stopped.
```

It must not need a second Ctrl+C, and it must not print a `KeyboardInterrupt` traceback.

**Acceptance:** ✅ The worker starts, stays quiet, and stops on the first Ctrl+C.

---

# T3 — Two workers racing claim the same job exactly once

**Purpose:** this is the phase's headline risk (**K13**, trap **T1**). If two workers can both take
one job, every later stage does its work twice.
**Preconditions:** T1 passed.

### Step 1 — The race, four workers, one thousand jobs

> .\.venv\Scripts\python.exe -m pytest tests/test_job_queue.py -v -k "exactly_once or lost_updates or claim_update_refuses"

→ **Expected:** exactly three tests, all passing:

```
tests/test_job_queue.py::test_two_workers_claim_a_job_exactly_once PASSED
tests/test_job_queue.py::test_the_claim_update_refuses_a_job_that_is_no_longer_queued PASSED
tests/test_job_queue.py::test_no_lost_updates_over_1000_claim_attempts PASSED
```

The second test starts 4 real threads and drains 1,000 real jobs from a real SQLite file. It takes
10–30 seconds. That is the work being done, not a hang.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `a job was handed to two workers` | The claim is not atomic | **Stop. Do not use this build.** The queue would double every job |
| `the claim raised under contention: database is locked` | The write lock is not being taken up front | Same — report it |
| `a running job was re-claimed` | The `state='queued'` guard is gone | Same |

**Acceptance:** ✅ `3 passed`.

---

# T4 — A failing job retries with a growing delay, then gives up

**Purpose:** prove a transient failure is survived and a permanent one is not retried forever.
**Preconditions:** T1 passed.

### Step 1

> .\.venv\Scripts\python.exe -m pytest tests/test_job_queue.py -v -k "backoff or retry or retries or non_retryable"

→ **Expected:** all pass, including:

```
test_backoff_grows_with_every_attempt_and_never_overlaps PASSED
test_backoff_is_capped_at_ten_minutes PASSED
test_a_retryable_failure_requeues_with_a_future_available_at PASSED
test_retries_stop_at_max_attempts PASSED
test_a_non_retryable_failure_fails_immediately PASSED
```

### Step 2 — See the delay yourself

> .\.venv\Scripts\python.exe -c "from src.orchestration import backoff_seconds; print([round(backoff_seconds(n),1) for n in range(1,7)])"

→ **Expected:** six numbers that **grow**, roughly doubling, and never exceed 600. For example:

```
[8.2, 16.5, 35.8, 94.0, 135.4, 345.3]
```

The exact numbers differ every run — the delay is deliberately jittered so a hundred failing jobs do
not all retry at the same instant.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| The numbers do not grow | Backoff is broken | Report it; a flat backoff hammers a failing service |
| A number above 600 | The cap is gone | Report it; a job could sit unretried for hours |

**Acceptance:** ✅ Tests pass and the six numbers grow.

---

# T5 — A crashed worker's job is picked up again, and runs once

**Purpose:** prove the lease works. This is what makes a restart safe.
**Preconditions:** T1 passed.

### Step 1

> .\.venv\Scripts\python.exe -m pytest tests/test_worker.py tests/test_job_queue.py -v -k "lease or reclaim"

→ **Expected:** `8 passed`, including:

```
test_a_reclaimed_job_re_runs_without_duplicating_rows PASSED
test_an_expired_lease_returns_the_job_to_the_queue PASSED
test_reclaim_leaves_a_live_lease_alone PASSED
test_a_job_out_of_attempts_is_failed_rather_than_reclaimed_forever PASSED
test_the_heartbeat_thread_extends_a_lease_while_a_handler_runs PASSED
```

One of them sleeps for 1.4 seconds on purpose — it has to outlast a heartbeat interval to prove the
lease was extended.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `the re-run duplicated a row` | A handler is not idempotent | Report it; a crash would double-count leads |
| `the lease was never extended` | The heartbeat thread is not running | Report it; long jobs would be stolen mid-flight |

**Acceptance:** ✅ `8 passed`.

---

# T6 — Stopping the worker finishes the job in flight

**Purpose:** the acceptance criterion is *"SIGTERM finishes the in-flight job and exits < 30 s."*
**Preconditions:** T1 passed.

### Step 1

> .\.venv\Scripts\python.exe -m pytest tests/test_worker.py -v -k "stop or signal"

→ **Expected:** `4 passed`:

```
test_stop_ends_the_loop_between_jobs_not_inside_one PASSED
test_a_signal_stops_the_worker PASSED
test_installing_signal_handlers_off_the_main_thread_does_not_raise PASSED
test_start_inprocess_worker_runs_a_job_then_stops PASSED
```

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `the worker was still running 30s after stop()` | Shutdown is broken | Report it; a deployment would need `kill -9`, which loses the job |
| `the in-flight job did not finish, or the next one started` | Stop is checked in the wrong place | Same |

**Acceptance:** ✅ `4 passed`.

---

# T7 — Ten minutes of reading and writing at once, with no lock errors

**Purpose:** **K13**, the phase's top risk. SQLite has one writer; the worker and the dashboard must
not trip over each other.
**Preconditions:** T1 passed. **Takes just over 10 minutes** — start it and make a cup of tea.

### Step 1 — The real soak

> $env:SOAK_SECONDS='600'; .\.venv\Scripts\python.exe -m pytest tests/test_concurrency_soak.py -v -s -k "soak_reports"; Remove-Item Env:\SOAK_SECONDS

→ **Expected:** one line of measured output, then `1 passed`:

```
soak 600s: 27931 claims, 27931 events, 62168 reads, 0 errors
```

Your numbers will differ — they depend on your disk. **The last number must be `0 errors`.** The
first three must all be well above zero; a soak that did no work proves nothing.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `N lock errors in 600s` | Writer contention is not handled | **Stop.** This is K13 occurring. Report the number |
| `the writer never claimed anything` | The soak did no work | Report it; the run is not evidence |
| It finishes in 20 seconds | `SOAK_SECONDS` was not set | Re-run the command exactly as written |

### Step 2 — The settings that make it possible

> .\.venv\Scripts\python.exe -m pytest tests/test_concurrency_soak.py -v -k "pragmas or write_lock"

→ **Expected:** 2 passed. These assert that WAL mode, the 10-second busy timeout and foreign-key
enforcement are actually switched on — not merely written down.

**Acceptance:** ✅ `0 errors` over the full 600 seconds, and both pragma tests pass.

---

# T8 — No credential survives into a log

**Purpose:** **R15** and trap **T4**. The metric is *zero secret tokens in 10 MB of captured log.*
**Preconditions:** T1 passed.

### Step 1 — The 10 MB capture

> .\.venv\Scripts\python.exe -m pytest tests/test_obs.py -v -k "redact or megabytes or credential"

→ **Expected:** `19 passed`, including:

```
test_ten_megabytes_of_log_contains_no_credential PASSED
test_no_credential_survives_a_log_line[...] PASSED   (seven of these)
test_redaction_covers_a_traceback PASSED
test_redaction_covers_extra_fields_not_just_the_message PASSED
```

The 10 MB test writes a real log file containing seven known credential shapes on every line —
API keys, bearer tokens, proxy passwords — and then greps the whole file.

### Step 2 — See it with your own eyes

> .\.venv\Scripts\python.exe -c "from src.obs.logging import redact; print(redact('key sk-abcdef0123456789abcdef via http://user1234:hunter2secret@198.51.100.7:8080'))"

→ **Expected:** exactly this, with both secrets gone and the host still readable:

```
key [REDACTED] via http://user1234:[REDACTED]@198.51.100.7:8080
```

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| Any part of `sk-abcdef...` or `hunter2secret` printed | Redaction is broken | **Stop.** A leaked key in a log is unrecoverable — you cannot un-write a log someone has already sent to a support ticket |

**Acceptance:** ✅ Nothing credential-shaped appears in either output.

---

# T9 — Every log line says which run and job it came from

**Purpose:** [35 §2](../35-testing-strategy.md) check 17 — correlation IDs present, redaction active.
**Preconditions:** T1 passed.

### Step 1

> .\.venv\Scripts\python.exe -m pytest tests/test_obs.py -v -k "context or json_output"

→ **Expected:** `7 passed`, including `test_third_party_loggers_inherit_the_context`.

### Step 2 — Read a real JSON line

> .\.venv\Scripts\python.exe -c "import logging; from src.obs.logging import configure_logging, log_context; configure_logging(fmt='json'); log=logging.getLogger('demo'); ctx=log_context(run_id=42, job_id=7); ctx.__enter__(); log.info('scraping'); ctx.__exit__(None,None,None)"

→ **Expected:** one line of JSON on screen containing all four fields. It arrives on **stderr**, so
in some terminals it appears in red or with a wrapper line around it — that is the terminal, not an
error:

```
{"ts": "...", "level": "INFO", "logger": "demo", "msg": "scraping", "run_id": 42, "job_id": 7}
```

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| No `run_id` or `job_id` | The context filter is not attached | Report it; a support ticket about "a stuck run" becomes unanswerable |
| Plain text, not JSON | `fmt='json'` was not applied | Re-run the command exactly as written |
| **Nothing at all** | Logging was disabled | This was the P2 defect in `migrations/env.py`. Report it — it means the fix did not land |

**Acceptance:** ✅ One JSON line, with `run_id` and `job_id` present.

---

# T10 — Maintenance deletes the four things it should, and nothing else

**Purpose:** trap **T3** — `run_events` is unbounded and this handler owns the purge.
**Preconditions:** T1 passed.

### Step 1

> .\.venv\Scripts\python.exe -m pytest tests/test_maintenance.py -v

→ **Expected:** `13 passed`, including these four in particular:

```
test_done_jobs_older_than_thirty_days_are_purged PASSED
test_events_of_runs_finished_over_ninety_days_ago_are_purged PASSED
test_expired_http_cache_rows_are_purged PASSED
test_metrics_older_than_fourteen_days_are_purged PASSED
```

and, just as importantly:

```
test_ai_cache_is_never_purged PASSED
test_a_failed_job_is_kept_however_old PASSED
test_a_run_is_never_deleted_only_its_events PASSED
```

**`ai_cache` is deliberately never purged.** It is the cost saving: deleting a row costs money to
rebuild and changes no result. If that test ever fails, the purge has grown a table it must not have.

**Acceptance:** ✅ 13 passed.

---

# T11 — The live database is untouched and the legacy contract holds

**Purpose:** **R20**. 459 leads, unchanged scores, all 17 endpoints.
**Preconditions:** T1–T10 done.

### Step 1 — Schema and fingerprint

> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db

→ **Expected:** ends with `OK — all 25 checks passed.`, and above it:

```
  PASS  leads = 459
  PASS  max(intent_score) = 164.28
  PASS  avg(intent_score) = 42.29
  PASS  runs is empty (P1 runs nothing yet)
  PASS  jobs is empty (P1 runs nothing yet)
```

`jobs` being **empty** is correct: P2 builds the queue but nothing enqueues into it until P3.

### Step 2 — The endpoints and pages

> .\.venv\Scripts\python.exe -m pytest tests/test_navigation_and_pages.py tests/test_boundaries.py -q

→ **Expected:** `49 passed`

### Step 3 — Migration state

> .\.venv\Scripts\python.exe -m alembic heads

→ **Expected:** exactly one line — `0004_orchestration (head)`. **P2 adds no migration**, so this is
unchanged from P1.

**Acceptance:** ✅ 25/25 schema checks, 459 leads, one head.

---

## Rollback verification

**Purpose:** prove this phase can be undone in production. P2's rollback is
`WORKER_INPROCESS=false` and not running `main.py worker` ([34 §P2](../34-implementation-plan.md)).

### Step 1 — Switch the worker off

> $env:WORKER_INPROCESS='false'; .\.venv\Scripts\python.exe -c "from src.orchestration import worker_inprocess_enabled, start_inprocess_worker; print('enabled:', worker_inprocess_enabled()); print('worker:', start_inprocess_worker())"; Remove-Item Env:\WORKER_INPROCESS

→ **Expected:**

```
enabled: False
worker: None
```

`None` means no worker was started. Nothing claims, and since nothing enqueues yet either, the system
behaves exactly as it did before P2.

### Step 2 — Confirm it is back on by default

> .\.venv\Scripts\python.exe -c "from src.orchestration import worker_inprocess_enabled; print(worker_inprocess_enabled())"

→ **Expected:** `True`

### Step 3 — Confirm the legacy contract still holds after the rollback

> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db

→ Ends with `OK — all 25 checks passed.` and `leads = 459`.

**No migration to undo.** P2's DB row is *None* — the schema is identical before and after this
phase, which is why the rollback is a single environment variable.

**Acceptance:** ✅ The switch works in both directions and 459 leads are intact.

---

## Coverage map

Every acceptance criterion in [34 §P2](../34-implementation-plan.md), and where it is verified.

| Acceptance criterion | Test |
|---|---|
| Two workers racing claim the same job **once** | T3 |
| Retryable failure retries with growing backoff to `max_attempts` | T4 |
| Lease expiry re-runs without duplicate rows | T5 |
| SIGTERM finishes the in-flight job and exits < 30 s | T6 |
| **10-minute concurrent soak with zero `database is locked`** | T7 |
| A full log capture contains **no credential** | T8 |
| `main.py worker` runs standalone | T2 |
| Metric: 0 lost updates over 1,000 claim attempts | T3 |
| Metric: 0 secret tokens in 10 MB of log | T8 |
| Correlation IDs on every record ([35](../35-testing-strategy.md) check 17) | T9 |
| `maintenance` handler: four purges | T10 |
| Legacy contract: 459 leads, 17 endpoints | T11 |
| Rollback executed and verified | Rollback section |

---

## Sign-off

| Check | Pass |
|---|---|
| T1 — lint, format and 427 tests pass, 0 failed | ☐ |
| T2 — `main.py worker` starts and stops on one Ctrl+C | ☐ |
| T3 — two workers claim one job exactly once; 1,000 attempts, 0 lost | ☐ |
| T4 — backoff grows, is capped, and stops at `max_attempts` | ☐ |
| T5 — an expired lease re-runs the job without duplicating rows | ☐ |
| T6 — stop finishes the job in flight and exits inside 30 s | ☐ |
| T7 — **600-second soak: 0 lock errors** (record the measured line below) | ☐ |
| T8 — no credential in 10 MB of log | ☐ |
| T9 — log lines carry `run_id` and `job_id` | ☐ |
| T10 — four purges; `ai_cache` untouched | ☐ |
| T11 — 459 leads, 25/25 schema checks, one migration head | ☐ |
| Rollback executed and verified (`WORKER_INPROCESS=false`) | ☐ |
| No unexpected errors in any output | ☐ |

**Measured soak result (T7):** `soak 600s: ______ claims, ______ events, ______ reads, ______ errors`

**Tester:** ______________________  **Date:** ______________  **Result:** ☐ Pass ☐ Fail
