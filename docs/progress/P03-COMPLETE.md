# P03 — COMPLETE

**Phase name:** P3 — Run service, API, run pages (Stage B — Orchestration)
**Plan:** [34-implementation-plan.md §P3](../34-implementation-plan.md)
**Completion date:** 2026-08-07
**Companions:** [PHASE-03-COMPLETION-REPORT.md](../PHASE-03-COMPLETION-REPORT.md) ·
[PHASE-03-HANDOVER.md](../PHASE-03-HANDOVER.md) · [testing/P03-testing.md](../testing/P03-testing.md)

> ⚠️ **P3 of the frozen P0–P30 plan — NOT the legacy "Phase 03."**
> [`testing/phase-03-testing.md`](../testing/phase-03-testing.md) belongs to the old eight-phase
> numbering. The two schemes are unrelated.

---

## Objective

> *"The operator can start a run from the UI, watch it, cancel it, and see it resume after a
> restart."*

**Met.** Stage B is complete: P1 gave orchestration a vocabulary, P2 a runtime, and P3 the service,
the API and the pages that drive them. **The pipeline runs end to end for the first time** — before
this phase, nothing put work in the queue at all.

---

## Files changed

**Twenty-one files: eight new, thirteen modified; plus five new test files.**

| File | Change |
|---|---|
| `src/orchestration/run_service.py` | new |
| `src/orchestration/handlers/scrape.py` | new |
| `src/orchestration/handlers/finalize.py` | new |
| `src/dashboard/routes_runs.py` | new |
| `src/dashboard/templates/runs.html` | new |
| `src/dashboard/templates/run_progress.html` | new |
| `src/dashboard/templates/run_missing.html` | new |
| `tests/baseline/api_scrape_contract.json` | new — recorded **before** the route was touched |
| `src/dashboard/routes.py` | modified — the `/api/scrape` shim; the **only** edit to this file |
| `src/dashboard/app.py` | modified — blueprint, `start_worker` / `stop_worker` / `get_worker` |
| `src/dashboard/routes_health.py` | modified — the `queue` block |
| `src/dashboard/nav.py` | modified — the **Runs** entry |
| `src/dashboard/templates/_base_ai.html` | modified — the shared `poll()` helper |
| `src/dashboard/templates/index.html` | modified — the sidebar button now navigates |
| `src/orchestration/__init__.py` | modified — re-exports, and a docstring that was no longer true |
| `src/orchestration/handlers/__init__.py` | modified — registry 1 → 3 |
| `src/orchestration/job_queue.py` | modified — `requeue()` |
| `src/orchestration/worker.py` | modified — `Worker.thread`, `Worker.join()` |
| `src/db/repositories/runs.py` | modified — `counts_by_state_for_runs()` |
| `src/scrapers/subreddit_scraper.py` | modified — two additive keyword arguments |
| `src/config.py` | modified — **UTF-8 read**; a latent defect (report §5.2) |
| `main.py` | modified — `schedule` enqueues and runs a worker |
| `config.yaml` | modified — `orchestration.enabled` |
| `tests/conftest.py` | modified — the `app` fixture disables the in-process worker |

**No migration.** `alembic heads` is still one `0004`.

---

## New tests

| File | Covers |
|---|---|
| `tests/test_run_service.py` | The forced walk, the duplicate-run guard, cancel, retry, progress |
| `tests/test_handlers_scrape.py` | Both handlers through a real worker; idempotence; kill/resume 10/10 |
| `tests/test_run_api.py` | Every endpoint; the 50 ms budget at 5,000 jobs; worker wiring; redaction |
| `tests/test_scrape_contract.py` | The recorded contract, and the rollback path |
| `tests/test_run_pages.py` | Both pages, the nav, the poll disciplines, template redaction |
| `tests/test_schedule_and_health.py` | The scheduler's skip-and-continue, and queue health |

Modified: `tests/test_concurrency_soak.py` (a reader on the real `RunService.progress` path),
`tests/test_maintenance.py` and `tests/test_navigation_and_pages.py` (phase-boundary guards that had
to move forward one phase).

---

## ⚠️ Behaviour change an operator will notice

`POST /api/scrape` and `python main.py schedule` now collect **subreddit leads only**. The frozen
job-type list has no keyword or user type; those stages arrive in P5/P17.

**Workarounds, both supported:** `python main.py scrape` still runs all three, and
`orchestration.enabled: false` restores the previous behaviour everywhere.

---

## Decisions taken with the operator

1. The run **walks both review gates** — the transition table admits no other path.
   [ARCHITECTURE_FREEZE §11.1](../ARCHITECTURE_FREEZE.md).
2. The shim runs **`scrape_subreddit` only** — the change above.
3. `orchestration.enabled` **is** implemented, resolving a self-conflict in the plan row.

---

## Defects fixed

1. `retry()` doubled a run's work when the failed attempt still had jobs queued.
2. `config.yaml` was read with the locale encoding — one non-ASCII character broke every command.
3. `RunService.fail()` stored its error unredacted into a column the run page renders.
4. The run list issued one count query per row.

---

## Verification

**579 passed, 2 skipped** (and again under `-W error::DeprecationWarning`) · **151 new tests** ·
`ruff` clean · **97 %** coverage on `src/orchestration/` · one alembic head, round-trip on a live-DB
copy with 459 leads intact · `check_schema.py` **25/25** · **10-minute soak: 64,950 claims, 133,653
reads, 68,248 progress polls, 0 errors** · progress **p95 < 50 ms at 5,000 jobs** · 3 mutations, 3
detected.

---

## Status

**P3 is complete pending the manual sign-off table in
[testing/P03-testing.md](../testing/P03-testing.md).**
Next: [P4 — Network provider abstraction](../34-implementation-plan.md), whose entry conditions are
in [PHASE-03-HANDOVER §8](../PHASE-03-HANDOVER.md).
