# Phase Completion Report — P1: Run & Job Schema

**Phase:** P1 — Run & job schema ([34 §P1](34-implementation-plan.md))
**Stage:** B — Orchestration
**Status:** ✅ **COMPLETE**
**Date:** 2026-08-05
**Estimated:** 2 days · Low risk — **Actual:** 1 session · No risk realised
**Depends on:** P0 (signed off — [SPRINT-0-MEASUREMENTS.md](SPRINT-0-MEASUREMENTS.md), [testing/P00-testing.md](testing/P00-testing.md))

> ⚠️ **Not to be confused with the legacy "Phase 01."** [`PHASE-01-STATUS.md`](PHASE-01-STATUS.md),
> [`MANUAL-TESTING-PHASE-01.md`](MANUAL-TESTING-PHASE-01.md) and [`11-phase-01.md`](11-phase-01.md)
> belong to the **old eight-phase numbering** and were completed 2026-07-30. This report is about
> **P1** in the frozen [34](34-implementation-plan.md) plan (P0–P30). The two numbering schemes are
> unrelated.

---

## 1. Objective and whether it was met

> *"The database can represent a run that pauses at a human gate and resumes after a restart."*

**Met, with the scope P1 actually owns.** P1 delivers the *representation* — the tables, the state
vocabulary, and the guard that rejects impossible transitions. It deliberately delivers no runtime:
nothing enqueues, nothing executes, no page renders. Durability across a restart is a property of the
schema (a run's state lives in a row, not in memory, and no column can expire it); *exercising* that
property end-to-end belongs to P2 (worker) and P3 (service and UI).

The one behaviour that could be proven now — that a run parked at a human gate has no mechanism that
could time it out — was proven, by asserting the absence of any expiry column on `runs` in both the
migrated schema and the SQLAlchemy model.

---

## 2. What was delivered

| Deliverable (doc 34) | File | Status |
|---|---|---|
| `0004_orchestration` migration | `migrations/versions/0004_orchestration.py` | ✅ new |
| `Run` / `Job` / `RunEvent` models | `src/db/models.py` | ✅ modified |
| `RunState` / `JobState` enums | `src/orchestration/states.py` | ✅ new |
| `TRANSITIONS` + `assert_transition` | `src/orchestration/states.py` | ✅ new |
| Package surface | `src/orchestration/__init__.py` | ✅ new |
| Tests | `tests/test_orchestration.py` | ✅ new — 35 tests |
| Baseline-guard companion | `tests/test_migrations.py` | ✅ modified |

**Six files. No file outside the phase's declared `Files` row was touched.**

### 2.1 Schema

Three new tables, four new indexes, four foreign keys, one new column on an existing table:

| Object | Detail |
|---|---|
| `runs` | 10 columns; `project_id` **nullable, no FK** (deferred to `0007`, per doc 34's DB row) |
| `jobs` | 16 columns; FK → `runs` **CASCADE** |
| `run_events` | 7 columns; FK → `runs` **CASCADE** |
| `scrape_runs.run_id` | nullable; FK → `runs` **SET NULL** |
| `ai_calls.run_id` | pre-existing column; its FK → `runs` **SET NULL** added here, closing the deferral from `0002` |
| `ix_jobs_claim` | `(state, available_at, priority, id)` — verified in that order |
| `ix_jobs_run` | `(run_id, state)` |
| `ix_jobs_lease` | `(state, lease_expires_at)` |
| `ix_run_events_run` | `(run_id, id)` |
| `ix_runs_project_state` | `(project_id, state)` |

The `SET NULL` / `CASCADE` split is deliberate and asserted: deleting a run must never destroy its
**cost history** (`ai_calls`) or its **legacy scrape record** (`scrape_runs`), but should clean up its
own work items (`jobs`, `run_events`).

### 2.2 State machine

12 `RunState` values, 5 `JobState` values, the transition table transcribed from
[04 §1.2](04-system-design.md), and `assert_transition` raising `IllegalTransition` with a message
that names **both** states plus the legal alternatives:

```
illegal run transition pending -> complete; allowed from pending: cancelled, failed, profiling
```

---

## 3. Acceptance criteria

| Criterion (doc 34) | Evidence | Result |
|---|---|---|
| Upgrade / downgrade / upgrade on a **live-DB copy** | Executed on a copy of `data/leads.db`; 459 leads present at all three stages; downgrade removed both the tables **and** `scrape_runs.run_id` | ✅ |
| `alembic heads` = 1 | `0004_orchestration (head)` — single line | ✅ |
| Illegal transition raises naming both states | Message quoted in §2.2 | ✅ |
| The two `AWAITING_*_REVIEW` states have **no timeout** | No expiry column on `runs` in the migrated schema **or** the model; two separate tests | ✅ |
| `PRAGMA foreign_key_list(ai_calls)` reports the run FK | `[('runs', 'run_id', 'SET NULL')]` | ✅ |
| Legacy contract | §5 below | ✅ |

### Metrics

| Metric | Target | Actual |
|---|---|---|
| Leads intact | 459 | **459** |
| Migration heads | 1 | **1** |
| Changes to existing tables | 0 beyond `scrape_runs.run_id` | **exactly `scrape_runs.run_id`**, enforced by `test_post_baseline_columns_are_exactly_as_declared` |

---

## 4. Gate results

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check` on the six P1 files | **All checks passed!** |
| Format | `ruff format --check` on the six P1 files | **6 files already formatted** |
| Full suite | `pytest` | **301 passed, 9 warnings** (P0 ended at 265) |
| Orchestration tests | `pytest tests/test_orchestration.py` | **35 passed** |
| Fence 1 + 4 (AST) | `tests/test_boundaries.py` | pass |
| Fence 2 — `src.ai` imported inside `src/orchestration/` | grep | **0** |
| Fence 3 — `hermes` referenced inside `src/` | grep | **0** |
| Migration round trip | fresh DB **and** live-DB copy | pass |
| Rollback | `alembic downgrade 0003` | **executed and verified**, not merely documented |
| Mutation discipline | 6 mutations against the bold criteria | **6/6 detected** (see §7) |

The 9 warnings are pre-existing `datetime.utcnow()` deprecations inside SQLAlchemy. They predate P1.

**Format-check scope.** `ruff format --check src tests migrations` reports 28 files needing
reformatting across the whole repo. Those are pre-Phase-1 modules deliberately left unformatted to
protect the byte-identical `GET /` guarantee (AC18) — reformatting a template-adjacent module risks
that snapshot. The gate is therefore scoped to the files the phase touched, which is how P0 ran it too.

---

## 5. Legacy contract

| Guarantee | Verified | Result |
|---|---|---|
| 459 leads | `select count(*) from leads` on `data/leads.db` | **459** |
| `intent_score` fingerprint | max / avg | **164.28 / 42.29** — unchanged |
| Live DB migration state | `alembic_version` | **`0003_net_infrastructure`** — correctly *not* migrated |
| `data/leads.db` mtime | file listing | **2026-07-31** — not written to during P1 |
| 13 CSV columns | `tests/baseline/export_baseline.csv` header + fence test | **13** |
| 17 endpoints / all pages | `tests/test_navigation_and_pages.py` | **31 passed** |
| `GET /` byte-identical | baseline snapshot test in the full suite | pass |

**P1 ships the migration but does not apply it to the live database.** Applying it is an operator
action taken when P2 first needs the tables. This is why `alembic current` reads `0003` while
`alembic heads` reads `0004` — that divergence is expected, not a defect.

---

## 6. Findings

### F1 — Documentation defect: "11 `RunState` values"

`docs/34-implementation-plan.md` P1 **Tasks** specified *eleven* `RunState` values.
[04 §1.1](04-system-design.md) — the specification — lists **twelve**. Twelve were implemented; doc 34
was corrected and annotated. `tests/test_orchestration.py` now asserts the enum against an
**independently transcribed** copy of doc 04 §1.1/§1.2 rather than importing the constant it is meant
to be checking, so this class of drift fails the suite instead of propagating.

### F2 — A test asserted the schema when it should have asserted the model

Mutation testing surfaced this. Adding an `expires_at` column to the `Run` **model** did **not** fail
`test_runs_table_has_no_expiry_column`, because that test reads the *migrated* schema — and the model
is not the migration. The "gates never time out" guarantee (AD-6) therefore had a hole: a future phase
could add an expiry field to the model and only discover the contradiction at the next migration.

Fixed by adding `test_runs_model_has_no_expiry_column` and a shared `FORBIDDEN` frozenset covering
`expires_at`, `timeout_at`, `deadline`, `ttl`. Re-mutation verdict: **DETECTED**.

### F3 — A baseline guard with a known expiry date

`test_baseline_matches_create_all` compared the `0001` DDL against the *current* models. It failed the
moment `scrape_runs.run_id` was added — but that column is *planned* in [05 §4.2](05-database-plan.md),
so the failure was the test being out of date, not the change being wrong.

Rather than weaken it, a `POST_BASELINE_COLUMNS` declaration was added plus a companion test asserting
the divergence is **exactly** what is declared. Verified by mutation: any other baseline change, or
any further change to `scrape_runs`, still fails.

---

## 7. Mutation testing

Applied to every **bold** acceptance criterion, per doc 35 §4.

| # | Mutation | Expected to fail | Verdict |
|---|---|---|---|
| 1 | Remove a `RunState` value | `test_run_states_match_spec` | DETECTED |
| 2 | Add a transition not in doc 04 §1.2 | `test_transitions_match_spec` | DETECTED |
| 3 | Reorder `ix_jobs_claim` columns | `test_claim_index_column_order` | DETECTED |
| 4 | Change `ai_calls` FK to `CASCADE` | `test_ai_calls_fk_is_set_null` | DETECTED |
| 5 | Add `expires_at` to the `runs` **table** | `test_runs_table_has_no_expiry_column` | DETECTED |
| 6 | Add `expires_at` to the `Run` **model** | *(nothing — the hole)* | **NOT DETECTED** → fixed → **DETECTED** |

---

## 8. Documentation landed

| Doc | Change |
|---|---|
| [34 §P1](34-implementation-plan.md) | Tasks row corrected to **12** `RunState` values; `scrape_runs.run_id` noted; delivered/corrected callout added |
| [05 §7](05-database-plan.md) | Chain table: `0004 orchestration` marked **P1 ✅ shipped 2026-08-05**, listing the tables, the new column and the closed `ai_calls` FK deferral |
| [13](13-phase-03.md) | Header note mapping the old "Phase 03" design onto **P1 / P2 / P3**, with P1 marked shipped and scheduling marked deferred to P24 |
| [testing/P01-testing.md](testing/P01-testing.md) | New — manual guide, T1–T7 plus rollback, 13-row coverage map, sign-off table |
| [PHASE-01-HANDOVER.md](PHASE-01-HANDOVER.md) | New — handover to P2 |

**No document outside P1's `Docs` field was edited.**

---

## 9. Architecture: no amendments

P1 produced **no amendment** to `ARCHITECTURE_FREEZE.md`. Nothing measured contradicted an assumption.
No framework, dependency, table or technology was introduced beyond the three tables the phase's DB
row names. F1–F3 are documentation and test defects, not design changes.

---

## 10. Rollback

**Command:** `alembic downgrade 0003`

**Executed and verified** on a copy of the live database. The downgrade removes `run_events`, `jobs`
and `runs`, drops both foreign keys, and drops `scrape_runs.run_id` — a complete reversal, not a
partial one. After rollback, 459 leads remain and `tests/test_navigation_and_pages.py` still passes.

Rollback is low-risk because **nothing in the application reads these tables yet.** That property ends
with P2; from P2 onward a rollback must also disable the worker.

---

## 11. Known blockers carried forward

| ID | Blocker | Impact on P2 |
|---|---|---|
| **B1** | `.env` holds only `APP_SECRET_KEY`; no `DEEPSEEK_API_KEY`, no `TELEGRAM_BOT_TOKEN` | **None.** Gates P23; also blocks V-1 and Hermes Track B |
| **B3** | `mypy` is listed in doc 35 and FREEZE §5 but is **not installed** | **None** for correctness, but the doc-35 gate cannot be run in full until it is |
| — | Multireddit volume anomaly (SaaS 83 / startups 10 / marketing 4 / Entrepreneur 3) | **None.** Scheduled for per-subreddit measurement in P6 |

None of these blocks P2.

---

## 12. Status

**P1 is complete and awaiting sign-off.**

Manual guide: [`docs/testing/P01-testing.md`](testing/P01-testing.md) — ~20 minutes, no destructive
steps, sign-off table at the end.

Per the phase-manager procedure, **P2 has not been started** and will not be started until
`docs/testing/P01-testing.md` carries a signed sign-off table.
