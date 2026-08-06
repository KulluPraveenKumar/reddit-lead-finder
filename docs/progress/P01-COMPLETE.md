# P01 — COMPLETE

**Phase name:** P1 — Run & job schema (Stage B — Orchestration)
**Plan:** [34-implementation-plan.md §P1](../34-implementation-plan.md)
**Completion date:** 2026-08-05
**Recorded:** 2026-08-05, retroactively, during recovery from an unexpected shutdown
([`RECOVERY_REPORT.md`](../../RECOVERY_REPORT.md))
**Companions:** [PHASE-01-COMPLETION-REPORT.md](../PHASE-01-COMPLETION-REPORT.md) ·
[PHASE-01-HANDOVER.md](../PHASE-01-HANDOVER.md) · [testing/P01-testing.md](../testing/P01-testing.md)

> ⚠️ **P1 of the frozen P0–P30 plan — NOT the legacy "Phase 01."**
> [`PHASE-01-STATUS.md`](../PHASE-01-STATUS.md), [`MANUAL-TESTING-PHASE-01.md`](../MANUAL-TESTING-PHASE-01.md)
> and [`11-phase-01.md`](../11-phase-01.md) belong to the old eight-phase numbering and were
> completed 2026-07-30. The two schemes are unrelated.

---

## Objective

> *"The database can represent a run that pauses at a human gate and resumes after a restart."*

**Met, within the scope P1 owns.** P1 delivers the *representation* — tables, state vocabulary, and
the guard that rejects impossible transitions. It deliberately delivers **no runtime**: nothing
enqueues, nothing executes, no page renders. Exercising durability end-to-end belongs to P2 and P3.

---

## Git status

**None — the project is not under version control.** Recovery reconstructed the phase timeline from
file modification times instead. Carried as risk **K-R1**; fixing it is the top recommendation in the
recovery report.

---

## Files changed

**Six files. Nothing outside the phase's declared `Files` row was touched.**

| File | Change |
|---|---|
| `migrations/versions/0004_orchestration.py` | new |
| `src/orchestration/states.py` | new |
| `src/orchestration/__init__.py` | new |
| `src/db/models.py` | modified — `Run`, `Job`, `RunEvent` |
| `tests/test_orchestration.py` | new — 35 tests |
| `tests/test_migrations.py` | modified — baseline-guard companion |

### Database changes

Three tables, five indexes, one new column on an existing table:

| Object | Detail |
|---|---|
| `runs` | 10 columns; `project_id` nullable, **no FK** (deferred to `0007`/P12) |
| `jobs` | 16 columns; FK → `runs` **CASCADE** |
| `run_events` | 7 columns; FK → `runs` **CASCADE** |
| `scrape_runs.run_id` | new column; FK → `runs` **SET NULL** |
| `ai_calls.run_id` | FK → `runs` **SET NULL** added here, closing the `0002` deferral |
| Indexes | `ix_jobs_claim` `(state, available_at, priority, id)`, `ix_jobs_run`, `ix_jobs_lease`, `ix_run_events_run`, `ix_runs_project_state` |

The **CASCADE / SET NULL split is load-bearing**: deleting a run must never destroy cost history
(`ai_calls`) or the legacy scrape record (`scrape_runs`), but must clean up its own work items.

### Migration status

| | |
|---|---|
| `alembic heads` | `0004_orchestration (head)` — **one head** |
| `alembic current` (live `data/leads.db`) | `0003_net_infrastructure` |

> **The divergence is intentional.** P1 ships `0004` but does not apply it to the live database.
> Applying it is a deliberate operator action taken when P2 first needs the tables.

### Configuration changes

**None.** No new dependency, framework, table or technology beyond the three tables the phase's DB
row names. `ARCHITECTURE_FREEZE.md` required **no amendment**.

---

## Tests passed

Re-verified during recovery, not carried over from the previous session:

| Gate | Result |
|---|---|
| Full suite (`pytest`) | ✅ **301 passed**, 0 failed, 9 pre-existing warnings, 48.9 s |
| Orchestration | ✅ **35 passed** |
| Migrations | ✅ **9 passed** |
| Architecture boundaries | ✅ **18 passed** |
| Navigation / legacy endpoints | ✅ **31 passed** |
| `ruff check .` | ✅ All checks passed! |
| `ruff format --check` (6 P1 files) | ✅ 6 files already formatted |
| `mypy` | ⚠️ **not runnable** — not installed (blocker B3) |
| Migration round-trip on a live-DB copy | ✅ upgrade → downgrade → upgrade, **459 leads at every stage**; downgrade removes `scrape_runs.run_id` too |
| Live DB integrity | ✅ 459 leads · `intent_score` 164.28 / 42.29 · still at `0003` · mtime 2026-07-31 |
| Mutation testing | ✅ 6 mutations, 6 detected |

**301 passed matches the handover snapshot written minutes before the shutdown**, which is the
strongest single piece of evidence that nothing was left half-applied.

---

## Manual testing completed

⚠️ **NO.** [`docs/testing/P01-testing.md`](../testing/P01-testing.md) exists and is complete — T1–T7,
rollback verification, a 13-row coverage map and a sign-off table — but **the sign-off table is
blank**: all ten checkboxes ☐, Tester and Date empty.

Per [handover §8](../PHASE-01-HANDOVER.md), **P2 must not be started until that table is signed.**
This is the single outstanding gate on the project, and it is a human action.

---

## Documentation updated

| Doc | Change |
|---|---|
| [34 §P1](../34-implementation-plan.md) | Tasks row corrected to **12** `RunState` values (was 11); `scrape_runs.run_id` noted |
| [05 §7](../05-database-plan.md) | Chain table: `0004 orchestration` marked **P1 ✅ shipped 2026-08-05** |
| [13](../13-phase-03.md) | Header note mapping legacy "Phase 03" onto P1 / P2 / P3 |
| [testing/P01-testing.md](../testing/P01-testing.md) | New — manual guide |
| [PHASE-01-HANDOVER.md](../PHASE-01-HANDOVER.md) | New — handover to P2 |
| [PHASE-01-COMPLETION-REPORT.md](../PHASE-01-COMPLETION-REPORT.md) | New — completion report |

All six verified present and correct during recovery. No document outside P1's `Docs` field was
edited **by P1**.

Added later, during recovery: [`docs/README.md`](../README.md) gained an **Execution record**
section — the index had been written before the P0/P1 artefacts existed and linked none of them.
Two cosmetic defects were recorded rather than corrected: the completion report §2.1 says "four new
indexes" but lists **five** (five is right, and is what this document records), and
`docs/02-research-findings.md` is linked from several documents but does not exist — a pre-existing
break, not caused by P1. Both are in [`RECOVERY_REPORT.md`](../../RECOVERY_REPORT.md) §5.3–5.4.

---

## Findings

| # | Finding | Resolution |
|---|---|---|
| **F1** | Doc 34 said *11* `RunState` values; doc 04 §1.1 — the specification — lists **12** | Implemented 12; corrected doc 34. **When the plan and the design disagree, the design wins** |
| **F2** | `test_runs_table_has_no_expiry_column` read the *schema*, so adding `expires_at` to the **model** passed | Added `test_runs_model_has_no_expiry_column` + shared `FORBIDDEN` set. **Found only by mutation testing** |
| **F3** | `test_baseline_matches_create_all` had a built-in expiry once a *planned* column landed | Added `POST_BASELINE_COLUMNS` + a companion test asserting the divergence is exactly as declared — narrowed, never deleted |

---

## Known issues

| ID | Issue | Blocks P2? |
|---|---|---|
| **D1** | P00 **and** P01 manual sign-off tables are unsigned | **Yes** — by the project's own rule |
| **K-R1** | Project is not under version control | No, but it is the top risk |
| **B3** | `mypy` required by doc 35 / FREEZE §5, not installed | No — but the doc-35 gate cannot be claimed in full |
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` | No — gates P23 |
| — | Multireddit volume anomaly | No — scheduled for P6 |

### Technical debt

- `ruff format` is scoped to files each phase touches; **28 legacy files remain unformatted** by
  design, to protect the byte-identical `GET /` guarantee.
- `run_events` is append-only and unbounded — P2's `maintenance` handler owns its purge.

---

## Rollback procedure

```
alembic downgrade 0003
```

**Executed and verified** on a copy of the live database, twice — once during P1 and again during
recovery. Removes `run_events`, `jobs`, `runs`, both foreign keys and `scrape_runs.run_id`. 459 leads
survive; `tests/test_navigation_and_pages.py` still passes.

Low-risk **because nothing in the application reads these tables yet**. That property ends with P2 —
from P2 onward a rollback must also disable the worker.

---

## Next phase

**P2 — Job queue, worker, structured logging.** Not started. **Do not start it** until the P01
sign-off table is signed.

### Traps waiting in P2 (from the handover)

| # | Trap |
|---|---|
| **T1** | `claim()` needs `BEGIN IMMEDIATE` **and** an `AND state='queued'` guard — either alone loses the race. Do not reorder `ix_jobs_claim` |
| **T2** | SQLite writer contention (**K13**, the phase's top risk) — a 10-minute concurrent soak with **zero** `database is locked` |
| **T3** | `run_events` is unbounded — P2 owns the purge |
| **T4** | `RedactingFilter` must cover the credential shapes P0 already proved leak — **zero** credentials in 10 MB of log |

---

## Resume point

**P1 is complete and verified. Do not re-implement it.**

The next action is **not** code. In order:

1. An operator executes and signs [`docs/testing/P01-testing.md`](../testing/P01-testing.md)
   (~20 min, non-destructive). Same for [`P00-testing.md`](../testing/P00-testing.md).
2. Decide on version control (**K-R1**).
3. Optionally install `mypy` (**B3**).
4. Back up `data/leads.db`, then apply `alembic upgrade head` to it — the first operator action P2
   requires:
   ```
   powershell "Copy-Item data\leads.db data\backups\leads-pre-0004.db"
   .\.venv\Scripts\python.exe -m alembic upgrade head
   ```
5. Read [34 §P2](../34-implementation-plan.md) in full — all thirteen fields — and load the
   `phase-manager` skill before the first edit under `src/`.
