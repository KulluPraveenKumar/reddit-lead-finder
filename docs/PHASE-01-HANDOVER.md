# PHASE-01 HANDOVER — Run & Job Schema → P2

**From:** P1 — Run & job schema (complete 2026-08-05)
**To:** P2 — Job queue, worker, structured logging
**Companion:** [PHASE-01-COMPLETION-REPORT.md](PHASE-01-COMPLETION-REPORT.md) · [testing/P01-testing.md](testing/P01-testing.md)
**Architecture status:** FROZEN. P1 produced **no amendment**.

> ⚠️ **Not to be confused with the legacy "Phase 01."** [`PHASE-01-STATUS.md`](PHASE-01-STATUS.md),
> [`MANUAL-TESTING-PHASE-01.md`](MANUAL-TESTING-PHASE-01.md) and [`11-phase-01.md`](11-phase-01.md)
> belong to the **old eight-phase numbering** and were completed 2026-07-30. This document is about
> **P1** in the frozen [34](34-implementation-plan.md) plan (P0–P30). The two numbering schemes are
> unrelated.

This document exists so whoever picks up P2 does not have to re-derive P1's decisions from the diff.
It states what exists, what it guarantees, what it deliberately does *not* do, and the four traps
waiting in P2.

---

## 1. What now exists

### 1.1 `src/orchestration/`

```
src/orchestration/
├── __init__.py     re-exports the public surface with __all__
└── states.py       RunState, JobState, TRANSITIONS, JOB_TRANSITIONS,
                    GATE_STATES, TERMINAL_STATES, IllegalTransition,
                    assert_transition, assert_job_transition,
                    can_transition, is_gate, is_terminal
```

Import from the **package**, not the module:

```python
from src.orchestration import RunState, assert_transition, IllegalTransition
```

`states.py` has **no imports outside the standard library**. It does not touch the database, does not
log, and does not know what a job *does*. Keep it that way — it is the one piece of P1 that P2, P3,
P17, P18 and P19 all depend on, and it is cheap to test precisely because it is inert.

### 1.2 Three tables

| Table | Rows represent | Delete behaviour when a run is deleted |
|---|---|---|
| `runs` | one operator-initiated pipeline execution | — |
| `jobs` | one unit of durable work belonging to a run | **CASCADE** |
| `run_events` | one append-only log line belonging to a run | **CASCADE** |
| `scrape_runs.run_id` | link from the legacy scraper record | **SET NULL** — history survives |
| `ai_calls.run_id` | link from a model call to the run that paid for it | **SET NULL** — spend survives |

The `SET NULL` / `CASCADE` split is **load-bearing and tested.** If P2 ever adds a table that records
money or history, it gets `SET NULL`. If it records work-in-progress, it gets `CASCADE`.

---

## 2. Four guarantees P2 must not break

### G1 — A run at a human gate never expires

`runs` has **no** `expires_at`, `timeout_at`, `deadline` or `ttl` column, and neither does the `Run`
model. This is AD-6, and it is enforced by two tests — one against the migrated schema, one against
the model. Do not add a reaper that ages out `awaiting_subreddit_review` or `awaiting_keyword_review`.

`jobs` **does** have `lease_expires_at`. That is a different thing: a *worker* lease, reclaimed when a
worker dies. A run at a gate has no worker and therefore no lease.

### G2 — Every state change goes through `assert_transition`

Do not write `run.state = "scraping"` anywhere. Call `assert_transition(run.state, target)` first. The
error names both states because a support ticket that says *"illegal run transition
`awaiting_options` -> `analyzing`"* is actionable and *"the run got stuck"* is not.

`assert_job_transition` is the same contract for `JobState`.

### G3 — The transition table is transcribed from doc 04, not invented

`tests/test_orchestration.py` holds an **independently transcribed** copy of
[04 §1.1 and §1.2](04-system-design.md) in `SPEC_STATES` and `SPEC_TRANSITIONS`. It deliberately does
**not** import `TRANSITIONS` from the code it is testing. If P2 needs a new edge, change **doc 04
first**, then both copies. A test that imports the thing it asserts proves nothing.

### G4 — Existing tables stay untouched

`tests/test_migrations.py::test_post_baseline_columns_are_exactly_as_declared` asserts that the only
column added to a pre-existing table since `0001` is `scrape_runs.run_id`. P2's DB row is **None** —
if this test starts failing during P2, P2 has exceeded its scope.

---

## 3. What P1 deliberately did NOT do

| Not done | Owner |
|---|---|
| Enqueue anything | P2 |
| Execute anything — there is no worker | P2 |
| Structured logging, `emit_event()` → `run_events` | P2 |
| `RunService`, any HTTP endpoint, any page | P3 |
| Apply `0004` to the **live** database | operator, when P2 needs it |
| `runs.project_id` foreign key | `0007` (P12) — the column is nullable and unconstrained on purpose |
| Scheduling / cron | P24 |

**`data/leads.db` is still at `0003_net_infrastructure`.** That is correct. P1 proved the migration on
a copy. Applying it to the live database is a deliberate operator action, and it is the first thing P2
will need:

```
> cd <the folder containing pyproject.toml>
> powershell "Copy-Item data\leads.db data\backups\leads-pre-0004.db"
> .\.venv\Scripts\python.exe -m alembic upgrade head
```

---

## 4. Traps waiting in P2

**T1 — `claim()` must use `BEGIN IMMEDIATE` *and* an `AND state='queued'` guard.** Either alone loses
the race. `ix_jobs_claim` is `(state, available_at, priority, id)` in that order specifically so the
guarded claim seeks rather than scans; changing the order silently degrades it under load and no test
of *correctness* will notice.

**T2 — SQLite writer contention is K13, the highest-rated risk in the phase.** P2's acceptance
criteria include a 10-minute concurrent read/write soak with **zero** `database is locked`. Budget for
that; it is the reason P2 is rated High while P1 was Low.

**T3 — `run_events` is append-only and unbounded.** P2's `maintenance` handler owns its purge. A
`run_events` table nobody prunes is the most likely source of a slow `/runs/<id>` page in P3.

**T4 — Redaction is a P2 deliverable, and P0 already proved it matters.** The transport work in P0
found that a naïve `repr()` leaks proxy credentials; `_Endpoint` carries `repr=False` on its
credential fields for that reason. P2's `RedactingFilter` must cover the same shapes — its acceptance
criterion is **zero** credentials in 10 MB of captured log.

---

## 5. Findings from P1 worth carrying forward

| # | Finding | What changed | Lesson for P2 |
|---|---|---|---|
| **F1** | Doc 34 said *"11 `RunState` values"*; doc 04 §1.1 lists **12** | Implemented 12; corrected doc 34 | When the plan and the design disagree, **the design wins** — and say so in writing |
| **F2** | `test_runs_table_has_no_expiry_column` read the *schema*, so a mutation to the *model* passed | Added `test_runs_model_has_no_expiry_column` + shared `FORBIDDEN` set | Schema tests and model tests are **not** substitutes. P2 will have the same split |
| **F3** | `test_baseline_matches_create_all` had a known expiry the moment a *planned* column landed | Added `POST_BASELINE_COLUMNS` + a companion test asserting the divergence is exactly as declared | When a guard is genuinely out of date, **narrow it explicitly** — never delete the assertion |

F2 was found only by mutation testing. Keep applying it to every **bold** acceptance criterion; it is
the only check in this project that has actually caught a false-negative test.

---

## 6. Verification snapshot at handover

| | |
|---|---|
| Full suite | **301 passed**, 0 failed, 9 pre-existing warnings |
| Orchestration tests | **35 passed** |
| `ruff check` (P1 files) | All checks passed! |
| `ruff format --check` (P1 files) | 6 files already formatted |
| `alembic heads` | `0004_orchestration (head)` — one head |
| `alembic current` (live DB) | `0003_net_infrastructure` — **intentionally unmigrated** |
| Live DB | 459 leads · `intent_score` max 164.28 / avg 42.29 · mtime 2026-07-31 |
| CSV export | 13 columns |
| Navigation | 31 passed |
| Mutation testing | 6 mutations, 6 detected |

---

## 7. Blockers carried into P2

| ID | Blocker | Blocks P2? |
|---|---|---|
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` | **No** — gates P23 |
| **B3** | `mypy` required by doc 35 / FREEZE §5 but not installed | **No** — but install it before the doc-35 gate is claimed in full |
| — | Multireddit volume anomaly | **No** — scheduled for P6 |

---

## 8. Entry conditions for P2

- [ ] `docs/testing/P01-testing.md` sign-off table signed
- [ ] `alembic upgrade head` applied to `data/leads.db`, with a backup taken first
- [ ] `docs/34-implementation-plan.md` P2 read in full — all thirteen fields
- [ ] `phase-manager` skill loaded before the first edit under `src/`

**P2 must not be started until the first box is ticked.**
