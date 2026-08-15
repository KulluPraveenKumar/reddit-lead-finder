# Phase 12 — Completion Report

**Phase:** P12, project & BKB schema · **Completed:** 2026-08-15 · **Risk:** Medium — the largest revision
**Objective:** *"The schema can hold a versioned, evidenced, entity-resolved knowledge base."*

> Reasoning lives in [P12-DECISION-ANALYSIS.md](P12-DECISION-ANALYSIS.md).
> What the next phase must know lives in [PHASE-12-HANDOVER.md](PHASE-12-HANDOVER.md).
> Where an interrupted session resumes lives in [progress/P12-COMPLETE.md](progress/P12-COMPLETE.md).

---

## 1. What was built

`0007_projects_and_knowledge_base` — **twelve tables**, **six** deferred `project_id` foreign keys
closed, one `CHECK`, and a conditional pair that exists only where `sqlite-vec` loads. The seventh
revision of ten, and the first head change since P8.

| | |
|---|---|
| Tables created | `projects`, `website_snapshots`, `bkb`, `bkb_sections`, `personas`, `pain_points`, `intent_signals`, `bkb_entities`, `bkb_entity_aliases`, `bkb_links`, `bkb_evidence`, `bkb_suggestions` |
| Conditional | `bkb_embeddings` (`vec0`) + `bkb_embedding_meta` — **skipped on this host**, `sqlite-vec` absent |
| FKs closed | `ai_calls`, `runs`, `leads`, `comments`, `dedup_groups`, `minhash_bands` — all on `project_id` |
| Rows written | **Zero.** P12 ships shape; P14 and P16 write the content |
| Config keys | **None**, as the phase's Config row specifies |
| Dependencies | **None added** |

**The deletion actions are deliberately not uniform** — `SET NULL` for `ai_calls`, `leads` and
`comments`, `CASCADE` for `runs`, `dedup_groups` and `minhash_bands`. [Freeze §8](ARCHITECTURE_FREEZE.md)
makes *expiring leads* a permanent non-goal (*"a lead is a historical fact"*), so a project deletion
must not take the collected corpus with it; the dedup artefacts are derived per-run data and are
rebuilt from scratch. `test_the_deletion_actions_are_not_uniform` fails if they are ever collapsed.

---

## 2. Files

### Added

| File | Why |
|---|---|
| `migrations/versions/0007_projects_and_knowledge_base.py` | The revision. The phase's **Files** row |
| `tests/test_schema_0007.py` | **29 tests** — the twelve tables, the six keys, the three nullabilities, the payload rule, the conditional pair, the round-trip, `check_schema.py` at both revisions, and what P12 deliberately did not do |
| `docs/P12-DECISION-ANALYSIS.md` | D1–D8, the reasoning behind the three reconciliations and the two declines |
| `docs/PHASE-12-COMPLETION-REPORT.md`, `docs/PHASE-12-HANDOVER.md`, `docs/progress/P12-COMPLETE.md`, `docs/testing/P12-testing.md` | The four execution records [lock §2.1](EXECUTION_MODE_LOCK.md) requires |

### Modified — inside the Files row

| File | Change |
|---|---|
| `src/db/models.py` | Twelve ORM models, plus `BKB_SECTION_KEYS` (23), `BKB_TYPED_SECTION_KEYS` (3), `BKB_STALENESS_DAYS` (23, Group C `None`) and `BKB_ENTITY_KINDS` (5) |

### Modified — outside the Files row, with a reason each

[34 §P12](34-implementation-plan.md)'s Files row names one migration and `src/db/models.py`. Four
other files changed, on the basis P5's `feed` CLI, P6's `triage.py`, P9's `python -m src.rules`,
P10's `__main__.py` and P11's wiring each established — **an acceptance criterion that no file in the
row can satisfy**:

| File | Why it had to change |
|---|---|
| `scripts/check_schema.py` | ⚠️ **Its four *"`project_id` is BARE — deferred to 0007"* assertions, and *"runs has no foreign keys yet"*, are correct at `0006` and false at `0007`.** Left alone it would report a correct schema as broken. They now take a flag and invert, `--skip-p12` continues the `--skip-p1`/`-p6`/`-p8` idiom, and 25 checks were added for `0007`'s own shape |
| `src/dashboard/routes_health.py` | The acceptance criterion *"`/health` reports `semantic_layer: disabled`"* names no other file |
| `src/dashboard/templates/health_ai.html` | So the manual guide has something a non-developer can read, rather than a JSON key |
| `src/scoring/__init__.py` | **One dict.** `ABSENT_COMPONENTS` named P12 as the supplier of `pain_phrase` and `subreddit_fit`; `0007` creates those tables **empty**, so the labels now name P14 and P16 — the phases that write the rows. Leaving them would reproduce [PHASE-11-HANDOVER §6](PHASE-11-HANDOVER.md)'s warning exactly: a constant that keeps passing while asserting a lie |

### Modified — tests the schema change propagated into

None of these is a weakened assertion; each is a test whose premise the revision changed.

| File | Change |
|---|---|
| `tests/conftest.py` | `ensure_project()` — a real parent row, because `runs.project_id` is now a real foreign key |
| `tests/test_repositories_runs.py`, `tests/test_run_api.py`, `tests/test_run_service.py` | Eight tests attached runs to fabricated project ids (`1`, `2`, `4`) that named no row. They passed only because the constraint did not exist. **The fix is a real project, not a relaxed constraint** |
| `tests/test_orchestration.py` | `test_runs_project_id_is_bare_until_0007` → `test_runs_project_id_references_projects_and_stays_nullable`. Its own name carried the expiry date. **The nullability half is unchanged** and is now the load-bearing one. `TestSchemaCheckScript` count 49 → **74**, revision `0006` → `0007` |
| `tests/test_migrations.py` | `test_a1_...` and `test_a3_...` pinned to `0006` instead of `head` — both are P8's tests **about P8's revision**, and `head` silently retargeted them. `test_a3` then failed, correctly reporting `0007`'s legitimate `leads` rebuild as a P8 defect |
| `tests/test_scoring_cli.py`, `tests/test_schedule_and_health.py` | The corrected phase labels; the `semantic_layer` payload |

### Documentation

`docs/ARCHITECTURE_FREEZE.md` §11.1 (three reconciliations) · `docs/34-implementation-plan.md`
§P12 · `docs/05-database-plan.md` §5.1, §7, §7.1, §7.1a · `docs/35-testing-strategy.md` §6 ·
`docs/DEFERRED-IMPROVEMENTS.md` (DI28 answered, DI29 opened) · `docs/README.md`.

---

## 3. The three reconciliations

**None is a [§11](ARCHITECTURE_FREEZE.md) amendment.** No technology, table, decision or dependency
changes in any of them, and the chain stays at ten revisions. Each was **measured before code was
written**, which is what let the right revision be authored rather than a shipped one rewritten.

### 3.1 `runs.project_id` is not tightened to `NOT NULL`

[34 §P12](34-implementation-plan.md)'s DB row and [05 §7.1a](05-database-plan.md) step 3 both require
it. Measured on the live database, before `0007` existed:

```
runs total/null: (11, 11)
```

**Every run that has ever existed has `project_id IS NULL`.** The rebuild's `INSERT … SELECT` fails
on them; the backfill that would fix it is the row rewrite **M5** forbids in as many words; and
**AD-5** is frozen as *"project scoping is additive **and nullable**"*. `RunService.create(project_id:
int | None)` is the shipped signature, and nothing creates a `projects` row until **P16**.

[05 §7.1a](05-database-plan.md) argues P12's side one sentence before asking for the opposite: *"a run
created before Phase 4 has no project to belong to."* The half agreeing with a frozen AD wins. **The
foreign key is still created.**

### 3.2 Six foreign keys close, not four

Four documents gave four counts — [34 §P12](34-implementation-plan.md) four,
[35 §6](35-testing-strategy.md) four, [05 §7.1](05-database-plan.md) **six**,
[05 §7.1a](05-database-plan.md) three — while `check_schema.py` has asserted since P8, in four
separate checks, that `leads`, `comments`, `dedup_groups` and `minhash_bands` are *"deferred to
0007"*. Six is the union and the only count under which those four assertions are ever honoured.

The risky half — `batch_alter_table` over the legacy table R20 pins — was **probed on a copy of the
live database before the revision was written**:

```
BEFORE 492 rows  fp=9327a13dd9ef4185  9 indexes
AFTER  492 rows  fp=9327a13dd9ef4185  9 indexes  fk=[(projects, project_id, id)]
ix_leads_reddit_id UNIQUE preserved · child FKs intact · foreign_key_check [] · integrity ok
VERDICT: SURVIVES
```

Had it come back BROKEN, the answer would have been four with the other two filed as a DI.

### 3.3 `bkb_sections.payload_json` ships nullable, with a `CHECK`

[05 §5.1](05-database-plan.md) declares it `TEXT NOT NULL`; [05 §5.1b](05-database-plan.md) requires
`NULL` for exactly `buyer_personas`, `pain_points` and `buying_signals`. Both cannot hold, and this
phase's acceptance criterion encodes §5.1b. It ships as `ck_bkb_sections_payload_null_rule`, a
biconditional in the idiom the schema already uses twice — **`ideal_customer_profiles` is not
exempt**, which is the mistake §5.1b flags by name.

---

## 4. Validation results

Every figure below is **measured**, on the final code, in the runs recorded here.

| # | Check | Result |
|---:|---|---|
| 1 | **Full pytest** | ✅ **1903 passed, 2 skipped** in 388.07 s · exit 0 · single uninterrupted run |
| 2 | `ruff check .` | ✅ All checks passed |
| 3 | `ruff format --check .` | ✅ 175 files already formatted |
| 4 | **Coverage** | ✅ **89.20%** whole tree (P11: 87%) · `src/{ai,net,scoring}` **90%** against the ≥85% floor · `--cov-fail-under=70` met |
| 5 | **Mutation testing** | ✅ **18 designed · 17 detected · 1 survived · 0 not applied** — the survivor is the deliberate control |
| 6 | **Boundary / fence** | ✅ **81 passed** (`test_boundaries.py`, `test_rules_vocabulary.py`, `test_notify_boundaries_p6.py`), AST-based |
| 7 | **Legacy regression** | ✅ 16 passed · 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns · 17 endpoints |
| 8 | **Schema validation** | ✅ **74/74** fresh `0007` · **51/51** live `0006` with `--skip-p12` · **76/76** upgraded live copy |
| 9 | **Alembic** | ✅ One head, `0007_projects_and_knowledge_base` · linear chain of **seven** · live DB at `0006` |
| 10 | **Rollback** | ✅ **Executed** — up/down/up on a copy of the live database |
| 11 | **CI** | ✅ **Green** — run `31879457795` on `origin/main`, `conclusion: success`, commit `51eecba` |
| — | Performance | ✅ Migration **0.120 s** upgrade, **0.165 s** downgrade, against a 5 s budget |
| — | Cost | ✅ **0 AI calls** — `test_p12_makes_no_ai_call` |
| — | Documentation links | ✅ **100 internal links, 0 broken** across P12's five documents. Repository-wide, 686 checked and **6 broken — all six `02-research-findings.md`**, the pre-existing [DI5](DEFERRED-IMPROVEMENTS.md), none introduced here |
| — | Repository hygiene | ✅ H1–H8 against the staged diff. H1's only hits are `prefix_tokens` matching on *"token"*; H3 found **one real machine path** in the manual guide (`cd C:\Users\…`), corrected to `C:\path\to\reddit-scraper`; `.env`, `data/*.db` and `data/backups/` proven ignored |

### 4.1 The rollback, executed

```
P12 ROLLBACK DRILL - executed on a copy of data/leads.db
==============================================================
start       rev=0006_content_and_dedup             leads=492  fp=9327a13dd9ef4185
            0007 tables : 0   project FKs : 0   integrity=ok  fk_check=[]
            check_schema : exit=0  OK — all 51 checks passed.
            sqlite-vec   : UNAVAILABLE - vector tables skipped (expected here)
upgrade     rev=0007_projects_and_knowledge_base   leads=492  fp=9327a13dd9ef4185
            0007 tables : 12  project FKs : 6   integrity=ok  fk_check=[]
            check_schema : exit=0  OK — all 76 checks passed.
DOWNGRADE   rev=0006_content_and_dedup             leads=492  fp=9327a13dd9ef4185
            0007 tables : 0   project FKs : 0   integrity=ok  fk_check=[]
            check_schema : exit=0  OK — all 51 checks passed.
re-upgrade  rev=0007_projects_and_knowledge_base   leads=492  fp=9327a13dd9ef4185
            0007 tables : 12  project FKs : 6   integrity=ok  fk_check=[]
            check_schema : exit=0  OK — all 76 checks passed.
==============================================================
lead count and fingerprint identical at every stage: YES
```

`fp` is the first 16 hex of the `intent_score` digest over the 459 baseline rows. **Identical at all
four stages**, so neither the six rebuilds nor the rollback lost a row or altered a score.

### 4.2 Mutation testing — two real defects found

**18 designed · 17 detected · 1 survived · 0 not applied.** M10 is the deliberate control, a
comment-only edit; surviving is its correct outcome.

Two mutations survived on the first pass and **both were real defects in P12's own tests**:

**M6 / M6b — two tests passed for the wrong reason.** Replacing the biconditional `=` in the payload
`CHECK` with `>=`, and then `<=`, disables one direction of the rule each. Both left the tests green.
The cause: they asserted rejection by inserting into `bkb_id + 1000`, an id that names no row — so
the `IntegrityError` came from the **foreign key**, and the `CHECK` was never exercised at all. The
tests now insert into a **real** second BKB with a fresh `(bkb_id, section_key)` pair and assert the
error message names `ck_bkb_sections_payload_null_rule`. Both mutations are detected now.

**M14 / M16 — two guards that guarded nothing.** M14 (replacing the schema probe with an import
probe) survived because the test's fake `sqlite_vec` module had `__spec__ = None`, on which
`importlib.util.find_spec` **raises** — so the mutant hit the broad `except` and reported `disabled`
by accident. The fake now carries a real `ModuleSpec`. M16 (disabling `check_schema.py`'s inversion)
survived because **nothing in the suite ran the script against a `0007` database** — its new section
existed only in a throwaway drill. Two tests were added, and a seventeenth mutation (M17, silently
skipping the whole `0007` section) was designed to check the new guard actually guards.

This is [35 §2.4](35-testing-strategy.md) doing exactly what
[PHASE-02-STATUS §7](PHASE-02-STATUS.md) records it for: finding tests that pass for the wrong
reason.

### 4.3 Ten failures during validation, all root-caused

The first full run after implementation failed 10 tests. **None was a defect in the migration**; each
was the new constraint correctly propagating, and each was fixed at root cause:

| Count | Failure | Root cause | Fix |
|---:|---|---|---|
| 8 | `IntegrityError: FOREIGN KEY constraint failed` on `INSERT INTO runs` | The tests attached runs to project ids `1`, `2`, `4` that name no row. They passed only because `runs.project_id` was a **bare column** until `0007` | `ensure_project()` in `conftest.py` — a real parent row. **Not** a relaxed constraint: a test needing referential integrity switched off is testing a database the application never runs against |
| 1 | `test_runs_project_id_is_bare_until_0007` | Its own name carried the expiry date; `0007` landed | Renamed and inverted. The nullability assertion is unchanged |
| 1 | `test_it_names_the_three_absent_components_and_their_phases` | P12 corrected the `ABSENT_COMPONENTS` labels | Asserts P14/P15/P16, **and that `P12` is absent**, so the correction cannot silently revert |

A separate `test_a3_the_alter_did_not_rewrite_a_single_row` failure was caught earlier and is the
most instructive: it asserts `leads.rootpage` is unchanged across `upgrade("head")`, proving `0006`
is metadata-only. `0007` **legitimately does** rebuild `leads` — closing a foreign key requires it —
so as written the test read a correct rebuild as a P8 defect. Pinned to `0006`, with the assertion
untouched.

### 4.4 One unreproduced failure, stated rather than explained away

An intermediate full run reported **1 failed, 1902 passed** in **971 s**. The name was lost to a
shell filter, and the clean run that followed — **388 s**, less than half the wall clock — was
green at 1903 passed. The slow run was competing with the mutation harness for CPU, which is the
documented profile of this repository's three known timing flakes
([DI18](DEFERRED-IMPROVEMENTS.md), [DI20](DEFERRED-IMPROVEMENTS.md),
[DI27](DEFERRED-IMPROVEMENTS.md)). **It is recorded here rather than attributed**, because the
identity was not captured and guessing at one is what [DI27](DEFERRED-IMPROVEMENTS.md) exists to
warn against. The gate's requirement — one clean uninterrupted run — is met by the 388 s run.

### 4.5 The skip count moved from 2 to 9, and it is the flag, not the phase

Plain `pytest` reports **2 skipped**, the same two as P11 (`PROXY_FILE is not set`; `no proxy pool
configured on this machine`). Under `--cov` it reports **9**, and the seven extra are P10's
performance tests skipping themselves deliberately: *"a tracer is active and costs ~3x here …
padding it to survive coverage would stop it meaning what docs/34 §P10 says."* Same 1905 total in
both runs. Nothing to do with P12.

---

## 5. What P12 deliberately did not do

| | Why |
|---|---|
| **`leads.run_id`** ([DI28](DEFERRED-IMPROVEMENTS.md)) | [PHASE-11-HANDOVER §3](PHASE-11-HANDOVER.md) called `0007` the cheap moment. Declined on DI28's **own** trigger text — *"there is no failed measurement, because the window is exact today"* — and [lock §8](EXECUTION_MODE_LOCK.md), which admits a mid-phase improvement only when it relates to the phase. It would also have meant a **second** rebuild of the legacy table. Pinned by `test_leads_has_no_run_id`; the entry stays open, now naming P17 |
| **The three absent pre-score components** | `0007` creates `projects`, `pain_points` and `bkb_entities` **empty**. A component reading an empty table scores `0.0` for every item — [DI24](DEFERRED-IMPROVEMENTS.md) verbatim, and what P11 refused. [PHASE-11-HANDOVER §4](PHASE-11-HANDOVER.md) T2 adds that a seventh weight **rescales every stored `total`**. The labels were corrected instead |
| **Tightening `dedup_groups`/`minhash_bands`** | [05 §7.1](05-database-plan.md) left the choice to P12. P10's cascade and P11's stage write `None` into both on every run; tightening would satisfy a document by breaking shipped code |
| **Adding `sqlite-vec` to `requirements.txt`** | The Config row is None, [freeze §5](ARCHITECTURE_FREEZE.md) lists the vector stack as optional, and P0 measured it absent. `test_sqlite_vec_is_not_a_declared_dependency` holds it |
| **Adding `leads.run_id`, or tightening three columns** | See the rows above — each recorded rather than silently skipped |

### 5.1 ⚠️ The live database was upgraded, and it was not planned

P12 intended to leave `data/leads.db` at `0006` and let the operator run the upgrade from the manual
guide. **It is at `0007`.** Capturing the `/health` output for the guide called `create_app()`, and
`create_app()` → `init_db()` → `ensure_current()` **migrates on startup by design** — the shipped
behaviour that would have upgraded it the first time the operator started the dashboard anyway, and
the same route by which it reached `0006` in P8.

**Nothing was lost, and it is verified rather than assumed:**

* M7's backup was taken **automatically, before the upgrade** —
  `data/backups/leads-20260815T101958Z.db`, 14,319,616 bytes, present on disk.
* `check_schema.py --db data\leads.db` → **76/76**, `leads = 492 (459 baseline + 33 collected
  since)`, `max 164.28`, `avg 42.29`.
* `projects = 0`, `bkb = 0` — the migration seeded nothing.
* The rollback was then run **on a copy**, as the guide's T7 prescribes: `51/51` down, `76/76` back
  up.

It is recorded here, and at the top of [testing/P12-testing.md](testing/P12-testing.md), because an
operator opening the guide expecting to perform the upgrade should not have to discover from a
command's output that it already happened.

---

## 6. Known gap carried forward

**The `vec0` DDL has never executed.** `sqlite_vec` is absent on this host (P0's finding, re-measured
2026-08-15), so `CREATE VIRTUAL TABLE bkb_embeddings USING vec0(embedding FLOAT[256])` is pinned as a
**string** and has never been run by SQLite. There is no honest way to fake it — `vec0` is a C
extension, and a stub that let the branch proceed fails at the DDL with `no such module: vec0`.

Everything around it is tested: the failure is **forced** rather than left to the host's genuine
absence, both tables are asserted skipped together, the warning names its cause and what was skipped,
the DDL string is pinned, and the downgrade is clean where the pair was never created. The residue —
*does `vec0` accept this column spec?* — is **open**, and is **P15's**, the first phase with a reason
to install the extension. Recorded as trap T3 in the handover rather than covered by a test that
would pass without proving it.

---

## 7. Acceptance criteria

| Criterion | Result |
|---|---|
| Upgrade/downgrade/upgrade on a live-DB copy | ✅ Executed; fingerprint identical at all four stages |
| **With `sqlite-vec` unavailable the migration completes** | ✅ Forced by injection, not by the host's absence |
| `/health` reports `semantic_layer: disabled` | ✅ On `/api/health` and on the health page |
| `PRAGMA foreign_key_list` reports all constraints | ✅ **Six**, each with its ON DELETE action |
| One head | ✅ `0007_projects_and_knowledge_base` |
| `payload_json IS NULL` for exactly the three | ✅ `CHECK`, both directions |
| **NOT NULL for the other twenty incl. `ideal_customer_profiles`** | ✅ Asserted explicitly, with its own test |
| 459 intact | ✅ `max 164.28`, `avg 42.29` |
| Migration < 5 s | ✅ **0.120 s** |

---

## 8. Phase discipline — [lock §4](EXECUTION_MODE_LOCK.md)

- [x] Implementation complete — every deliverable
- [x] Automated tests passing — one clean uninterrupted run
- [x] Mutation discipline applied to every **bold** criterion
- [x] Manual testing guide written, every command executed first
- [ ] **Manual testing completed and signed off by a human** — the table is blank, awaiting the operator
- [x] Documentation updated — the phase's **Docs** field, plus three reconciliations
- [x] Progress updated
- [x] Rollback **executed and verified**
- [x] Repository hygiene reviewed
- [x] Git committed · pushed
- [ ] **Git tagged** — *not done, and must not be*: [lock §6.2](EXECUTION_MODE_LOCK.md) forbids
      tagging a phase whose sign-off table is unsigned
- [x] No unresolved blockers
