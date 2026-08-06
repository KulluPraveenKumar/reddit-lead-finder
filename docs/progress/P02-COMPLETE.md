# P02 — COMPLETE

**Phase name:** P2 — Job queue, worker, structured logging (Stage B — Orchestration)
**Plan:** [34-implementation-plan.md §P2](../34-implementation-plan.md)
**Completion date:** 2026-08-06
**Companions:** [PHASE-02-COMPLETION-REPORT.md](../PHASE-02-COMPLETION-REPORT.md) ·
[PHASE-02-HANDOVER.md](../PHASE-02-HANDOVER.md) · [testing/P02-testing.md](../testing/P02-testing.md)

> ⚠️ **P2 of the frozen P0–P30 plan — NOT the legacy "Phase 02."**
> [`PHASE-02-STATUS.md`](../PHASE-02-STATUS.md) and
> [`testing/phase-02-testing.md`](../testing/phase-02-testing.md) belong to the old eight-phase
> numbering and were completed 2026-07-31. The two schemes are unrelated.

---

## Objective

> *"Work executes durably: claimed with a lease, retried with backoff, resumed after a crash."*

**Met.** The queue claims atomically under N workers, retries with jittered backoff to a per-type
attempt budget, reclaims a crashed worker's job, and fails for good once attempts are spent. The
worker runs it, heartbeats it, and stops gracefully.

**Nothing enqueues yet** — that is P3. The registry ships one handler, `maintenance`, by design.

---

## Files changed

**Thirteen files: six new modules, seven modified; plus seven new test files.**

| File | Change |
|---|---|
| `src/orchestration/job_queue.py` | new |
| `src/orchestration/worker.py` | new |
| `src/orchestration/handlers/__init__.py` | new |
| `src/orchestration/handlers/maintenance.py` | new |
| `src/obs/events.py` | new |
| `src/db/repositories/runs.py` | new |
| `src/orchestration/__init__.py` | modified — re-exports |
| `src/obs/logging.py` | modified — `python-json-logger`, context, exception redaction |
| `main.py` | modified — `worker` subcommand, `logging.file` |
| `requirements.txt` | modified — `+python-json-logger>=3.1` |
| `config.yaml` | modified — `logging.file`, `worker.poll_interval_seconds` |
| `migrations/env.py` | modified — **one line**; a blocking earlier-phase defect (report §6) |
| `tests/conftest.py` | modified — socket-blocking fixture |

**Tests:** `test_job_queue.py` (29) · `test_worker.py` (22) · `test_obs.py` (35) ·
`test_maintenance.py` (13) · `test_repositories_runs.py` (13) · `test_worker_cli.py` (4) ·
`test_concurrency_soak.py` (3) = **119**.

### Database changes

**None.** P2's DB row is *None*. `alembic heads` is a single `0004_orchestration`; the live database
is untouched; `test_post_baseline_columns_are_exactly_as_declared` still passes.

### Configuration changes

`WORKER_INPROCESS` (env, default true) · `logging.file` · `worker.poll_interval_seconds`.
One new dependency: **`python-json-logger>=3.1`**, named by the freeze. No amendment required.

---

## Tests passed

| Gate | Result |
|---|---|
| Full suite | ✅ **427 passed, 2 skipped**, 11 warnings, 95 s |
| `ruff check .` | ✅ All checks passed! |
| `ruff format --check .` | ✅ 80 files already formatted |
| Coverage, `src/orchestration/` | ✅ **97%** (target ≥80%) |
| Boundaries · migrations · navigation · orchestration | ✅ 102 passed |
| Grep fences 2 and 3 | ✅ 0 matches |
| Schema verification | ✅ **25 / 25** |
| Migration round-trip on a live-DB **copy** | ✅ `0004 → 0003 → 0004`, 459 leads at every stage |
| Live DB | ✅ 459 leads · 164.28 / 42.29 · untouched |
| **10-minute soak** | ✅ `27931 claims, 27931 events, 62168 reads, 0 errors` |
| 10 MB log secret grep | ✅ 0 credentials |
| 1,000-attempt claim race, 4 threads | ✅ 0 lost updates |
| Clean-environment CI simulation | ✅ **427 passed, 2 skipped** |
| Mutation testing | ✅ **10 mutations, 10 detected** |
| `mypy` | ⚠️ not runnable — not installed (**O2**) |

---

## Manual testing completed

⚠️ **NO.** [`docs/testing/P02-testing.md`](../testing/P02-testing.md) exists and is complete — T1–T11,
rollback verification, a 13-row coverage map and a sign-off table — but **the sign-off table is
blank.** Every quoted number in it was measured by running the guide's own command.

The operator's session brief declared *Manual Sign-off ✅*; the repository's tables for P00, P01 and
P02 are all still unsigned. **No table was filled in by Claude** — writing a tester's name and date
into a public repository would fabricate a verification record, and only a human can satisfy that
gate.

---

## Documentation updated

| Doc | Change |
|---|---|
| [03 §7](../03-architecture.md) | Logging library named: stdlib `logging` + `python-json-logger` |
| [00 §7](../00-current-state.md) | `+python-json-logger` in the dependency list |
| [13](../13-phase-03.md) | P2 row marked shipped |
| [05 §13](../05-database-plan.md) | Retention table: the `maintenance` job now exists |
| [testing/P02-testing.md](../testing/P02-testing.md) | New — manual guide |
| [PHASE-02-COMPLETION-REPORT.md](../PHASE-02-COMPLETION-REPORT.md) | New |
| [PHASE-02-HANDOVER.md](../PHASE-02-HANDOVER.md) | New |
| [README.md](../README.md) | Execution record table |
| [../CHANGELOG.md](../../CHANGELOG.md) | `[Unreleased]` entry |
| [DEFERRED-IMPROVEMENTS.md](../DEFERRED-IMPROVEMENTS.md) | **DI11** added (F6) |

---

## Findings

| # | Finding | Resolution |
|---|---|---|
| **F1** | The `AND state='queued'` guard changes no outcome while `BEGIN IMMEDIATE` holds the write lock — the docs' *"either alone loses the race"* is imprecise about the mechanism | UPDATE extracted to `_claim_update()` and tested where the guard *is* observable |
| **F2** | The 1,000-attempt race test passed against `BEGIN DEFERRED`; the failure surfaced only as a dead thread | Threads now collect exceptions; the test asserts on them |
| **F3** | **A credential in an exception message reached the log** — a traceback does not exist until a formatter renders it, so the filter had nothing to redact | Both formatters redact the rendered exception |
| **F4** | **The soak passed with `busy_timeout=0`** — one writer never contends with itself | Two writer threads; the same mutation now yields 2,446 lock errors in 20 s |
| **F5** | The shutdown test detected `while True` by hanging, not failing | `run_forever` runs in a thread with a join deadline |
| **F6** | `scripts/check_schema.py` crashes at revision `0003` instead of reporting failures; [P01-testing](../testing/P01-testing.md) claims it reports "5 checks" | Recorded as **DI11**. Does not block P2 |

F1, F3 and F4 were found only by mutation testing.

---

## Known issues

| ID | Issue | Blocks P3? |
|---|---|---|
| **D1** | P00, P01 **and P02** manual sign-off tables unsigned | **Yes** — by the project's own rule |
| **B3 / O2** | `mypy` not installed | No — but the doc-35 gate cannot be claimed in full |
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` | No — gates P23 |
| **DI11** | `check_schema.py` crashes at `0003` | No |
| — | Multireddit volume anomaly | No — scheduled for P6 |

### Technical debt

- The `maintenance` handler exists and is tested, but **nothing schedules it**; scheduling is P24's.
  Until then it is run by hand.
- The soak is synthetic — 28k trivial jobs, not one 20-minute scrape. P3 is the first phase with a
  real handler, and the 900-second lease meets reality there.
- `ruff format` remains scoped; the 5 pre-Phase-1 modules are still excluded by design (**DI4**).

---

## Rollback procedure

```powershell
$env:WORKER_INPROCESS='false'
```

…and do not run `main.py worker`. **Executed and verified**: `worker_inprocess_enabled()` → `False`,
`start_inprocess_worker()` → `None`, no thread started, `check_schema.py` still 25/25 with 459 leads.

**No migration to undo** — P2's DB row is *None*, so the schema is identical before and after.

---

## Next phase

**P3 — Run service, API, run pages.** Not started. **Do not start it** until the sign-off tables are
signed.

### Traps waiting in P3 (from the handover)

| # | Trap |
|---|---|
| **T1** | `POST /api/scrape` may only **add** `run_id`; record the current response before touching the route |
| **T2** | Progress must be one `GROUP BY` over `ix_jobs_run` — 50 ms at 5,000 jobs |
| **T3** | The duplicate-run guard excludes terminal states rather than listing active ones; keep it that way |
| **T4** | `cancel_queued()` cannot stop a running handler; the run-level flag belongs in `runs.stats_json`, **not** a new column |
| **T5** | The in-process worker is a daemon thread and cannot install signal handlers; use `atexit` |
| **T6** | The 900-second lease has never met a real scrape; measure the first one |

---

## Resume point

**P2 is complete and verified. Do not re-implement it.**

The next action is **not** code. In order:

1. An operator executes and signs [`docs/testing/P02-testing.md`](../testing/P02-testing.md)
   (~35 min, non-destructive, no browser or key needed). The same is still outstanding for
   [`P00-testing.md`](../testing/P00-testing.md) and [`P01-testing.md`](../testing/P01-testing.md).
2. Optionally install `mypy` and record its baseline (**O2**).
3. Tag, **only after** the table is signed — [lock §6.2](../EXECUTION_MODE_LOCK.md):
   ```
   git tag -a v0.1.0-p2 -m "P2 complete: job queue, worker, structured logging"
   git push origin v0.1.0-p2
   ```
4. Read [34 §P3](../34-implementation-plan.md) in full — all thirteen fields — plus
   [13 §6](../13-phase-03.md) for the `POST /api/scrape` contract, and load the `phase-manager` skill
   before the first edit under `src/`.
