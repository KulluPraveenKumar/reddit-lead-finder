# Phase 08 — Completion Report · Content & dedup schema

**Phase:** P8 (frozen numbering) · **Revision:** `0006_content_and_dedup`
**Implemented:** 2026-08-11 · **Post-implementation:** 2026-08-13 · **Head commit:** see §8

> ⚠️ **This is not [18-phase-08.md](18-phase-08.md).** That document belongs to the **superseded**
> eight-phase numbering ([lock §2.1](EXECUTION_MODE_LOCK.md)) and describes quality measurement,
> dashboard, export and production readiness — which map to **P25–P27 and P30**, and to migration
> `0010`. `docs/testing/phase-08-testing.md` is its companion and is likewise historical.
> Reading either as P8's specification would build Stage I seventeen phases early.

---

## 1. What was built

**A schema-only migration. No page, no button, no endpoint, no message, no behaviour.**

| | |
|---|---|
| Four new tables | `comments`, `dedup_groups`, `dedup_members`, `minhash_bands` — **all created empty and still empty** |
| Four new `leads` columns | `project_id`, `confidence_score`, `analysis_status`, `source` + 4 indexes |
| One link closed | `prescores.comment_id → comments`, deferred by `0005` |
| New dependency | **none** |
| New job type | **none** |
| Rows written | **zero** |

### 1.1 The finding the whole phase turned on

`docs/05 §7` declared itself *"authoritative"* over the migration chain while describing a chain
[31](31-execution-plan.md)'s reorder had already superseded. Followed literally, P8 would have
authored the wrong revision number and written four `REFERENCES projects(id)` clauses at a revision
where `projects` does not exist.

**That is not a cosmetic error.** Measured on SQLite 3.45.3, in two independent sessions:

```
ADD COLUMN w/ dangling REFERENCES: OK          <- the migration succeeds
SELECT after:                      478         <- reads still work
PRAGMA foreign_key_check:          []          <- reports CLEAN
up / down / up round-trip:         passes      <- pure DDL
check_schema.py:                   OK          <- only reads
INSERT INTO leads:                 FAILED  no such table: main.projects
```

**Every gate in the project reports green while every lead insert is broken** — including one that
sets `project_id` to `NULL`, because SQLite resolves the parent table when it *prepares* a statement,
not when it checks the constraint. P8 ships a guard for the whole class
(`test_no_revision_leaves_a_dangling_foreign_key`, parametrised over every revision `0001..head`) and
the freeze's §11.1 now records the reconciliation.

---

## 2. Acceptance criteria — [34 §P8](34-implementation-plan.md)

| | Criterion | Evidence |
|---|---|---|
| **A1** | Up / down / up round-trip, nothing lost | `test_a1_up_down_up_on_a_copy_of_the_live_database`; 478 leads at every stage; executed drill in [05 §7.1b](05-database-plan.md) |
| **A2** | Existing rows get the documented defaults | `test_a2_every_existing_lead_gets_the_documented_defaults`; live DB reports `(478, 478, 478, 478, 478)` |
| **A3** | No row rewritten | `test_a3_the_alter_did_not_rewrite_a_single_row`; **`leads` rootpage 2 → 2 on the real database** |
| **A5** | The 459 originals and the `intent_score` fingerprint unchanged | `test_a5_the_legacy_intent_score_fingerprint_survives_0006`; `max 164.28`, `avg 42.29`, sha256 `52b2ebb2…` |
| **A6** | *"< 1 s"* | ⚠️ **Deliberately not asserted as a wall-clock test** — see §7 L2 |
| **A7** | A lead inserts at `0006` | `test_a7_a8_a_lead_and_a_comment_can_be_inserted_at_0006`; guide T3a on the live DB |
| **A8** | A comment inserts at `0006` | Same test; guide T3b |
| **A9** | `ck_prescores_one_target` survives the batch rebuild | Two tests — present **and** enforced |

### 2.1 Universal criteria — [34 §1.2](34-implementation-plan.md)

| | Criterion | Status |
|---|---|---|
| U1 | Migration up/down/up | ✅ |
| U2 | One head | ✅ `0006_content_and_dedup` |
| U3 | Full suite green | ✅ 1148 passed, 2 skipped |
| U4 | `ruff check` / `format --check` | ✅ / 127 files |
| U5 | `mypy` | ⚠️ **Not claimed** — O2, see §7 L4 |
| U6 | Grep fences | ✅ 4 of 4, unchanged |
| U7 | Manual guide generated **and executed** | ✅ Part B executed 2026-08-13; **sign-off blank** |

---

## 3. The rollback — executed, not described

On a copy of the live database, 2026-08-11 and again 2026-08-13:

```
start      rev=0005_discovery           leads=478  fp=52b2ebb2aeaf9165
upgrade    rev=0006_content_and_dedup   leads=478  fp=52b2ebb2aeaf9165
           check_schema --revision 0006 : exit=0  OK — all 52 checks passed.
DOWNGRADE  rev=0005_discovery           leads=478  fp=52b2ebb2aeaf9165
           check_schema --skip-p8       : exit=0  OK — all 31 checks passed.
           P8 tables remaining          : NONE
           P8 leads columns remaining   : NONE
re-upgrade rev=0006_content_and_dedup   leads=478  fp=52b2ebb2aeaf9165
```

`fp` is the `intent_score` fingerprint over the 459 baseline rows, and it matches
`tests/baseline/db_fingerprint.json` at every stage.

---

## 4. ⚠️ The numbers manual test T5 compares against

**Recorded because T5 cannot be executed without them.**

| Measurement | Before the live upgrade | After |
|---|---|---|
| **`leads` rootpage** | **2** | **2** |
| **`leads` total** | **478** | **478** |
| `alembic_version` | `0005_discovery` | `0006_content_and_dedup` |
| `prescores` rows | 0 | 0 |
| `prescores` FK parents | `leads`, `runs` | `comments`, `leads`, `runs` |
| Test count | 1131 passed, 2 skipped | **1148 passed, 2 skipped** |
| `check_schema.py` | 31 checks | **51** plain / **52** with `--revision` |

**An unchanged rootpage is the proof that no row was rewritten.** A rebuilt table gets a new root
b-tree page; an `ADD COLUMN` that only edits the table header does not.

**The live database was upgraded on 2026-08-13**, after an M7 backup to
`data/backups/leads-20260813T131507Z.db`.

### 4.1 Mutations by stage

| Stage | Designed | Detected | Equivalent |
|---|---|---|---|
| 3 — models | 4 | 3 | — (1 deferred to Stage 4, killed there) |
| 4 — schema tests | 7 | 6 | 1 (**M7**) |
| 5 — docs / rollback | 3 | 3 | — |
| **Total** | **14** | **12** | **2** |

**Both equivalences are proven by measurement, not asserted:**

- **M5** — a plain `UNIQUE(g, lead)` and a partial `UNIQUE … WHERE lead IS NOT NULL` accept and
  reject *exactly the same inserts*, because SQLite treats NULLs as distinct in a unique index. No
  behavioural test can separate them, so `check_schema.py` asserts the index **is** partial.
- **M7** — `batch_alter_table` does **not** rebuild when its only operation is `add_column`; alembic
  emits a plain `ALTER`. Measured `rootpage 2 → 2`, identical to the unmutated form.

---

## 5. What implementation found that reading had not

**Five things, each found by executing rather than by reading.**

| | Finding | Where it surfaced |
|---|---|---|
| **1** | **Alembic *refuses* `op.add_column` with an inline `ForeignKey` on SQLite** — `NotImplementedError: No support for ALTER of constraints`. So F1 is **unreachable on an existing table** through the ordinary call; it is reachable via `create_table` with an inline FK, or raw `op.execute`. The guard catches both | Stage 1, step 1.3 |
| **2** | **`Prescore.comment_id` was still bare in the models** after Stage 2 closed the FK in the database, so `create_all()` and `alembic upgrade head` disagreed. Stage 3's checklist never mentions `Prescore` | Stage 3 — **F-1** |
| **3** | **`POST_BASELINE_COLUMNS` was insufficient.** `_dump_schema` skips by `sqlite_master.name`, which for an index is the *index's* name, not its table's — so listing `leads` excluded the `CREATE TABLE` row and nothing else, and its four new indexes reached the byte comparison. `0004` never exposed it because `scrape_runs` gained a column and no index | Stage 3 — **F-2** |
| **4** | **The `dedup_members` CHECK assertion was masked by a unique index.** A mutation deleting `ck_dedup_members_one_target` survived, because the both-targets-set insert reused a group that already held `(group_id, lead_id)`. Same species as P7's "masked by a second guard" | Stage 4, mutation M3 |
| **5** | **The rollback could reintroduce F1, and nothing watched for it.** Deleting step 2.9's `drop_constraint` leaves `prescores` referencing a dropped `comments`; every insert then fails. The chain guard walks **upward only** and never observes the post-downgrade state | Stage 5, mutation S3 |

**On finding 5:** step 2.9's stated reason — *"`comments` cannot be dropped while `prescores` points
at it"* — is **not the hazard**. SQLite permits dropping a referenced parent in every configuration
(`foreign_keys` ON and OFF, child table empty and populated; all four measured). The hazard is the
reference left *behind*. `test_a1_up_down_up_on_a_copy_of_the_live_database` was **strengthened**, not
replaced, to catch it.

---

## 6. Documentation landed

| Document | Change |
|---|---|
| [05 §7](05-database-plan.md) | Table renumbered to ten revisions; both *"No tenth revision"* paragraphs struck; the *"three columns in `0007`"* placement corrected |
| [05 §7.1](05-database-plan.md) | The four new `project_id` columns added; **the "deferral is cheap" rationale struck as factually wrong** |
| [05 §7.1a](05-database-plan.md) | Retitled `0006`; *"3 columns"* → 4; `CREATE prescores` deleted; the FK closure added |
| [05 §7.1b](05-database-plan.md) | **New** — the executed rollback |
| [05 §4.1](05-database-plan.md) | `source` DDL adopted from the superseded [16 §115](16-phase-06.md); `project_id` shown bare |
| [05 §5.4/§5.4b](05-database-plan.md) | Three `project_id` columns to `NULL`; the `dedup_members` invariant comment corrected |
| [freeze §11.1](ARCHITECTURE_FREEZE.md) | One reconciliation row |
| [DEFERRED-IMPROVEMENTS](DEFERRED-IMPROVEMENTS.md) | **DI22** — the `dedup_members` invariant, P10's |
| [testing/P08-testing.md](testing/P08-testing.md) | Part B executed; five corrections recorded |

---

## 7. Known limits — stated, not hidden

| # | Limit |
|---|---|
| **L1** | **The manual sign-off table is unsigned.** Part B was executed by machine; T9's four visual checks are the operator's. **No tag** ([lock §6.2](EXECUTION_MODE_LOCK.md)) |
| **L2** | **A6's *"< 1 s"* is not asserted as a timing test.** It is DI18's species, and DI18 failed twice during this phase for machine load. `rootpage` tests the property the stopwatch stood in for |
| **L3** | **The four `project_id` FKs are open until `0007`.** The columns are unconstrained until P12 closes them; nothing enforces that a `project_id` names a real project |
| **L4** | **`mypy` is installed but out of the gate** (O2). Measured **193 errors in 23 files**, 57 of them in `src/db/models.py` — the file P8 edited. Root cause is the legacy `declarative_base()` idiom, so closing it means migrating every model to `Mapped[…]` |
| **L5** | **The `dedup_members` "one group per run" invariant is not enforced and not tested** — it is not expressible in this schema. **DI22**, P10's |
| **L6** | **Two flaky tests fired five times during this phase** — DI18 ×2, the WAL/mtime race ×2, the worker heartbeat ×1. Five extra full-suite runs. **D8 was deferred by the operator and remains open** |
| **L7** | **`check_schema.py` now carries two skip-flags and a pinned count.** Every future revision must update them |

---

## 8. Commits

| Stage | Commit | Subject |
|---|---|---|
| plan | `2e0b41f` | implementation review, decisions, checklist, testing guide |
| — | `762ec2e` | the operator's decisions, and what measuring D6 found |
| 1 | `af2e064` | **the insert guard that the FK round-trip cannot see** |
| 2 | `5e55070` | `0006` content and dedup, with four foreign keys left open |
| 3 | `723249e` | the five models, and the four columns `leads` did not have |
| 4 | `e0ced7c` | prove the migration is metadata-only and the CHECK survived |
| 5 | `74f9380` | the migration table that predated the reorder |
| post | *this commit* | completion report, handover, progress record, guide Part B |

**CI green on every one.**
