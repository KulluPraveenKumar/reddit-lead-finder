# PHASE-02 COMPLETION REPORT — Job queue, worker, structured logging

**Phase:** P2 — Job queue, worker, structured logging (Stage B — Orchestration)
**Plan:** [34-implementation-plan.md §P2](34-implementation-plan.md)
**Completed:** 2026-08-06
**Companions:** [PHASE-02-HANDOVER.md](PHASE-02-HANDOVER.md) · [testing/P02-testing.md](testing/P02-testing.md) ·
[progress/P02-COMPLETE.md](progress/P02-COMPLETE.md)
**Architecture status:** FROZEN. P2 produced **no amendment**.

> ⚠️ **P2 of the frozen P0–P30 plan — NOT the legacy "Phase 02."**
> [`PHASE-02-STATUS.md`](PHASE-02-STATUS.md) and [`testing/phase-02-testing.md`](testing/phase-02-testing.md)
> belong to the old eight-phase numbering (proxy & transport, completed 2026-07-31) and are
> historical records. The two schemes are unrelated.

---

## 1. Objective

> *"Work executes durably: claimed with a lease, retried with backoff, resumed after a crash."*

**Met.** A job can be enqueued, claimed atomically by one of N workers, heartbeated while it runs,
retried with growing jittered backoff, reclaimed after a crash, and failed for good once its attempts
are spent — all recorded in one SQLite file, surviving process restart.

**What P2 deliberately does not do:** nothing enqueues yet. The queue is complete and the worker
runs, but no route, page or pipeline stage puts work into it — that is P3. The handler registry
therefore ships with **exactly one** handler, `maintenance`, which is the only job type whose work
exists today.

---

## 2. Scope, and the fence around it

[13-phase-03.md](13-phase-03.md) is the design document for **P1 + P2 + P3 combined**; its AC1–AC15
and its 20-item completion checklist span all three. [34 §P2](34-implementation-plan.md) is the
authoritative scope, and it is what was built.

| In scope — delivered | Out of scope — belongs to P3 |
|---|---|
| `JobQueue` (enqueue / claim / heartbeat / complete / fail / reclaim / cancel_queued) | `RunService` |
| `Worker` loop, heartbeat thread, graceful shutdown | `routes_runs.py`, `/runs`, `/runs/<id>` |
| Handler registry + `maintenance` handler | `POST /api/scrape` shim |
| Structured JSON logging, redaction, correlation context | `scrape_subreddit` / `finalize_run` handlers |
| `emit_event()` → `run_events` | Duplicate-run 409 guard |
| `RunRepository`, `JobRepository` | `poll()` helper, templates |
| `main.py worker` | Wiring the worker into `create_app()` — see §3 |

### 2.1 One judgment call, stated

[13 §9.3](13-phase-03.md) starts an in-process worker from `create_app()`. **`src/dashboard/app.py`
is in P3's Files row, not P2's.** Resolution: P2 ships `worker_inprocess_enabled()` and
`start_inprocess_worker()` in `src/orchestration/worker.py`, defines the `WORKER_INPROCESS`
environment variable, and delivers the standalone `main.py worker` command — which is P2's actual
acceptance line. `app.py` was not touched. P3 calls the helper.

---

## 3. Files changed

**Eleven files: seven new, four modified.** Nothing outside the phase's declared scope was touched,
with one exception justified in §6.

| File | Change |
|---|---|
| `src/orchestration/job_queue.py` | **new** — `JobQueue`, `MAX_ATTEMPTS`, `backoff_seconds`, `RetryableError` |
| `src/orchestration/worker.py` | **new** — `Worker`, heartbeat, shutdown, `WORKER_INPROCESS` |
| `src/orchestration/handlers/__init__.py` | **new** — `REGISTRY`, `Handler` |
| `src/orchestration/handlers/maintenance.py` | **new** — four purges + conditional `VACUUM` |
| `src/obs/events.py` | **new** — `emit_event()` |
| `src/db/repositories/runs.py` | **new** — `RunRepository`, `JobRepository` |
| `src/orchestration/__init__.py` | modified — re-exports the runtime surface |
| `src/obs/logging.py` | modified — `python-json-logger`, `ContextFilter`, `log_context`, exception redaction |
| `main.py` | modified — `worker` subcommand; `logging.file` passed through |
| `requirements.txt` | modified — `+python-json-logger>=3.1` |
| `config.yaml` | modified — `logging.file`, `worker.poll_interval_seconds` |
| `migrations/env.py` | modified — **one line**, a blocking defect; §6 |
| `tests/conftest.py` | modified — socket-blocking fixture |

**Test files (new):** `test_job_queue.py`, `test_worker.py`, `test_worker_cli.py`, `test_obs.py`,
`test_maintenance.py`, `test_concurrency_soak.py`, `test_repositories_runs.py` — **119 tests**.

### 3.1 Database changes

**None.** P2's DB row is *None*. `alembic heads` is still a single `0004_orchestration`, the live
database is untouched, and
`tests/test_migrations.py::test_post_baseline_columns_are_exactly_as_declared` — the guard that fails
if a phase exceeds its scope (G4) — still passes.

### 3.2 Configuration changes

| Key | Default | Purpose |
|---|---|---|
| `WORKER_INPROCESS` (env) | `true` | Whether a host process starts a worker thread. **The phase's rollback switch** — an environment variable, not a config key, because a rollback you perform by editing a committed file is one you cannot perform quickly |
| `logging.file` | `''` (stderr only) | A path adds a second handler that always writes JSON |
| `logging.format` | `console` | `json` for anything that will be grepped |
| `worker.poll_interval_seconds` | `2.0` | How long to wait before re-polling an empty queue |

### 3.3 The one new dependency

`python-json-logger>=3.1` — named by [freeze §5](ARCHITECTURE_FREEZE.md) and
[33 §3.2](33-final-review.md), and the only dependency P2 adds.

**The floor is 3.1, not the 2.0 doc 33 proposed.** Measured, not preferred: the
`pythonjsonlogger.jsonlogger` import path that 2.x offers emits a `DeprecationWarning` from 3.0
onward, and the replacement `pythonjsonlogger.json` does not exist before 3.1. A `>=2.0` floor would
make whether the suite emits a warning depend on which version the resolver happened to pick. Raising
a floor introduces no technology; the freeze already names the library.

---

## 4. Acceptance criteria

Every criterion from [34 §P2](34-implementation-plan.md), with the evidence.

| Criterion | Result | Evidence |
|---|---|---|
| Two workers racing claim the same job **once** | ✅ | `test_two_workers_claim_a_job_exactly_once` — 2 threads on a barrier; exactly one claim, `attempts == 1` |
| A retryable failure retries with growing backoff to `max_attempts` | ✅ | `test_a_retryable_failure_requeues_with_a_future_available_at`, `test_retries_stop_at_max_attempts`, `test_backoff_grows_with_every_attempt_and_never_overlaps` |
| Lease expiry re-runs without duplicate rows | ✅ | `test_a_reclaimed_job_re_runs_without_duplicating_rows` — handler runs twice, one row written |
| SIGTERM finishes the in-flight job and exits < 30 s | ✅ | `test_stop_ends_the_loop_between_jobs_not_inside_one` — the second job stays `queued`; thread joins inside the budget |
| **10-minute concurrent read/write soak, zero `database is locked`** | ✅ | Measured: `soak 600s: 27931 claims, 27931 events, 62168 reads, 0 errors` |
| A full log capture contains **no credential** | ✅ | `test_ten_megabytes_of_log_contains_no_credential` — 10 MB written, 7 credential shapes, 0 survivors |
| `main.py worker` runs standalone | ✅ | `tests/test_worker_cli.py`, and started for real: banner, `worker started` log line, quiet poll |

### 4.1 Metrics

| Metric | Target | Measured |
|---|---|---|
| Claim contention — lost updates over 1,000 attempts | 0 | **0** (4 threads, 1,000 jobs, 1,000 distinct claims) |
| Soak lock errors | 0 | **0** over 600 s |
| Secret tokens in 10 MB of captured log | 0 | **0** |
| Coverage, `src/orchestration/` | ≥80% ([13](13-phase-03.md) AC15); ≥70% ([34](34-implementation-plan.md)) | **97%** (385 statements, 13 missed) |
| Coverage, all new/changed modules | — | **97%** (`job_queue` 94 · `worker` 98 · `maintenance` 95 · `logging` 97 · `events` 100 · `repositories/runs` 97) |

---

## 5. Test results

| Gate | Result |
|---|---|
| `ruff check .` | ✅ All checks passed! |
| `ruff format --check .` | ✅ 80 files already formatted |
| Full suite | ✅ **427 passed, 2 skipped**, 11 warnings, 95 s |
| New P2 tests | ✅ **119 passed** |
| Boundaries / migrations / navigation / orchestration | ✅ 102 passed |
| Fence 2 (`src.ai` imports) | ✅ 0 matches |
| Fence 3 (`hermes` imports) | ✅ 0 matches |
| Fences 1 & 4 (AST) | ✅ `tests/test_boundaries.py` passes |
| Schema verification | ✅ **OK — all 25 checks passed** |
| Migration round-trip on a **copy** | ✅ `0004 → 0003 → 0004`; 459 leads at every stage; one head |
| Live database | ✅ 459 leads · 164.28 / 42.29 · untouched |
| Clean-environment CI simulation | ✅ fresh venv from `requirements.txt`: install, lint, format, **427 passed, 2 skipped** |
| Offline guarantee | ✅ verified by probe — internet blocked, loopback allowed |
| `mypy` | ⚠️ **not run** — still not installed (**O2**, operator's decision) |

**The three expected suite lines**, unchanged in shape from P1, moved by +119:

| Environment | Expected |
|---|---|
| Developer machine | `427 passed, 2 skipped` — **measured** |
| Developer machine with `PROXY_FILE` | `429 passed, 0 skipped` — derived: the 2 skips are the proxy-file tests |
| CI (tracked files only, no `data/`) | `424 passed, 5 skipped` — **derived, not measured**: 429 collected, minus the 3 live-database guards that skip when `data/` is absent. P1 measured the same 3-test difference (308/2 → 305/5) |

The 11 warnings are the 9 pre-existing SQLAlchemy `utcnow()` deprecations plus 2 more of the **same**
warning, newly reached because P2's tests touch `ScrapeRun`. No new warning class was introduced.

### 5.1 Mutation testing — 10 mutations, 10 detected

Required by [35 §2.4](35-testing-strategy.md) for every **bold** criterion. **Two mutations survived
on the first attempt and the tests were strengthened until they did not** — which is the entire point
of the exercise.

| # | Mutation | Detected by | Note |
|---|---|---|---|
| 1 | Drop `AND state='queued'` from the claim UPDATE | `test_the_claim_update_refuses_a_job_that_is_no_longer_queued` | **Survived first.** §7 F1 |
| 2 | `BEGIN IMMEDIATE` → `BEGIN DEFERRED` | `test_no_lost_updates_over_1000_claim_attempts` | Strengthened first. §7 F2 |
| 3 | `redact()` returns its input unchanged | 16 tests in `test_obs.py` + `test_boundaries.py` | |
| 4 | Stop redacting the formatted traceback | `test_redaction_covers_a_traceback` | This mutation **was the original code**. §7 F3 |
| 5 | Emit an ISO/aware datetime into the claim query | 3 `available_at` tests | The naive-UTC boundary |
| 6 | `busy_timeout=10000` → `0` | 20-s soak + 2 pragma tests | **Survived the soak first.** §7 F4 |
| 7 | Reclaim ignores the remaining-attempts guard | `test_a_job_out_of_attempts_is_failed_rather_than_reclaimed_forever` | |
| 8 | (probe) Attempt a real socket connection | the autouse `block_network` fixture | Confirms the guarantee is machine-enforced |
| 9 | Remove `ContextFilter` from the handlers | `test_configure_logging_puts_both_filters_on_every_handler` | |
| 10 | `while not self._stop.is_set()` → `while True` | `test_stop_ends_the_loop_between_jobs_not_inside_one` | Detected by **hanging** first. §7 F5 |

---

## 6. The defect found in an earlier phase, and why it was fixed here

**`migrations/env.py` called `fileConfig(config.config_file_name)` — whose default is
`disable_existing_loggers=True`.**

`init_db()` runs migrations **in-process on every application start**, so that line executed inside
the live application and switched off every logger created before it. Every logger in this codebase
is created at import time, which is before it. The symptom is the worst kind: no error, no warning,
just a log file that stops after the migration banner.

It was found because `emit_event`'s log assertion returned an empty list, and it **blocks P2** — the
phase's deliverable is structured logging, and [35 §2](35-testing-strategy.md) check 17 cannot be
satisfied by a logger that has been disabled. Under the execution-mode rule for earlier-phase
defects (*"fix it only if it blocks the current phase"*), it was fixed: one argument,
`disable_existing_loggers=False`, with the reasoning inline.

Nothing else outside P2's Files row was modified.

---

## 7. Findings

| # | Finding | Resolution |
|---|---|---|
| **F1** | **The `AND state='queued'` guard is not observable through the race.** [13 §9.1](13-phase-03.md) and [handover T1](PHASE-01-HANDOVER.md) both say *"either alone loses the race"*. Measured: with `BEGIN IMMEDIATE` holding the write lock across SELECT, UPDATE and COMMIT, removing the guard changes **no** outcome — the race test passed against the mutation | The UPDATE was extracted to `JobQueue._claim_update()` so the guard is testable where it *is* observable: against a job another worker already holds. Doc 13's wording is right about the danger and imprecise about the mechanism — the guard is the backstop for any future caller claiming **outside** an immediate transaction, not an independent half of the same lock |
| **F2** | The 1,000-attempt race test **passed** against `BEGIN DEFERRED`; the failure surfaced only as an unhandled thread exception | The drain threads now collect exceptions and the test asserts on them. A thread that dies looks like a clean run once the others finish the work |
| **F3** | **A credential in an exception message reached the log.** `RedactingFilter` redacts `record.exc_text`, but a traceback does not exist until a *formatter* renders it — so the filter had nothing to redact | Both formatters now redact the rendered exception. Found by writing the test before assuming the filter was sufficient. This is P0's leak lesson repeating: the leak is never where the guard is looking |
| **F4** | **The soak was not sensitive enough to prove what it claimed.** With one writer thread, setting `busy_timeout=0` left it green: a single writer never contends with itself | Two writer threads. The same mutation now produces 2,446 lock errors in 20 seconds. A soak that cannot produce contention cannot prove its absence |
| **F5** | The shutdown test detected `while True` by **hanging the suite**, not by failing | `run_forever` now runs in a thread with a join deadline. A test that can only fail by hanging is not evidence anyone will read |
| **F6** | `scripts/check_schema.py` **crashes** at revision `0003` (`no such table: runs` in `check_row_counts`) rather than reporting failures. [testing/P01-testing.md](testing/P01-testing.md) says it reports *"5 checks"* there | Recorded in [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) as **DI11**. It does **not** block P2, whose rollback involves no downgrade |

F1, F3 and F4 were each found by mutation testing. It has now caught a false-negative test in every
phase it has been applied to.

---

## 8. Rollback

**Executed and verified**, not merely documented.

```powershell
$env:WORKER_INPROCESS='false'
```

→ `worker_inprocess_enabled()` returns `False`; `start_inprocess_worker()` returns `None`; no worker
thread starts. Do not run `main.py worker`, and nothing claims. Since nothing enqueues either, the
system behaves exactly as it did before P2.

**There is no migration to undo.** P2's DB row is *None*, so the schema is byte-identical before and
after this phase — which is why the rollback is one environment variable. Verified afterwards:
`check_schema.py` reports 25/25 and 459 leads.

---

## 9. Risks carried forward

| # | Risk | Severity | Note |
|---|---|---|---|
| **R1** | **Manual sign-off tables for P00, P01 and P02 are unsigned** | Blocking, procedurally | The operator's status declares sign-off complete; the files still show blank tables. **No table was filled in by Claude** — writing a tester's name into a public repository would fabricate a verification record. Under [lock §6.2](EXECUTION_MODE_LOCK.md) this also means **P2 is not tagged** (it requires no tag) |
| R2 | `mypy` still not installed | Medium | **O2**, unchanged. The [35 §2](35-testing-strategy.md) gate cannot be claimed in full. Deliberately not installed here — choosing the baseline is the operator's call |
| R3 | The queue has never run under real load | Medium | The soak is synthetic: 28k trivial jobs, not one 20-minute scrape. P3 is the first phase where a real handler runs, and `scrape_subreddit` is where the lease length (900 s) meets reality |
| R4 | `run_events` growth is bounded only by a handler nobody schedules yet | Low | The `maintenance` purge exists and is tested; **nothing enqueues it** until P24 adds scheduling. Until then it is run by hand |
| R5 | `VACUUM` in the maintenance handler commits mid-handler | Low | Unavoidable — SQLite refuses to VACUUM in a transaction. Guarded by a 2,000-page threshold and a `{"vacuum": false}` payload switch, and documented at the call site |
| R6 | K13 is mitigated, not eliminated | Medium | WAL + `busy_timeout=10000` + short transactions + a single bulk writer. The pragmas are now asserted rather than assumed |

---

## 10. Definition of Done

| Line | Status |
|---|---|
| Implementation complete — every deliverable in the phase's row | ✅ |
| Automated tests passing — one clean run | ✅ 427 passed, 2 skipped |
| Mutation discipline applied to every **bold** criterion | ✅ 10/10 |
| Manual testing guide generated | ✅ [testing/P02-testing.md](testing/P02-testing.md) |
| **Manual testing completed and signed off by a human** | ⬜ **Outstanding** — R1 |
| Documentation updated — the phase's **Docs** field | ✅ [03 §7](03-architecture.md), [00 §7](00-current-state.md) |
| Progress updated | ✅ [progress/P02-COMPLETE.md](progress/P02-COMPLETE.md) |
| Rollback **executed and verified** | ✅ §8 |
| Repository hygiene reviewed | ✅ H1–H8 |
| Git committed and pushed | ✅ |
| Git tagged | ⬜ **Deliberately not** — [lock §6.2](EXECUTION_MODE_LOCK.md) forbids tagging an unsigned phase, and P2 requires no tag |
| No unresolved blockers | ✅ technical; R1 is procedural |
