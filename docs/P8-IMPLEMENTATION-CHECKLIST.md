# P8 IMPLEMENTATION CHECKLIST — Content & dedup schema

**Written:** 2026-08-11 · **Revision:** `0006_content_and_dedup` · **Days / Risk:** 2 · Low
**Status:** not started. **Blocked on [D1 and D2](P8-DECISION-ANALYSIS.md).**

> ⛔ **Do not begin Stage 1 until the operator has settled
> [D1](P8-DECISION-ANALYSIS.md) and [D2](P8-DECISION-ANALYSIS.md).** D1 determines whether the
> migration emits a `REFERENCES` clause — get it wrong and every lead insert fails while every gate
> reports green ([review F1](P8-IMPLEMENTATION-REVIEW.md)). D2 determines the revision's filename and
> `down_revision`; get it wrong and `alembic heads` returns two.

Six stages. **The gate is run at the end of every stage, not only at the end of the phase**
([lock §3](EXECUTION_MODE_LOCK.md) steps 5–7). CI must be green after each commit.

| Stage | What lands | Commit type |
|---|---|---|
| [0](#stage-0) | Pre-flight — nothing is written | — |
| [1](#stage-1) | **The guard that would have caught F1**, before the migration it constrains | `test(P8)` |
| [2](#stage-2) | `0006_content_and_dedup.py` | `feat(P8)` |
| [3](#stage-3) | `src/db/models.py` — five model classes, four `leads` columns | `feat(P8)` |
| [4](#stage-4) | Migration and schema tests | `test(P8)` |
| [5](#stage-5) | Documentation, the §11.1 reconciliation, and the **executed** rollback | `docs(P8)` |

---

<a id="stage-0"></a>
## Stage 0 — Pre-flight gate

Nothing is written in this stage. Every line is a check.

- [ ] **0.1** Load the `phase-manager` skill — [lock §3](EXECUTION_MODE_LOCK.md) requires it before
      the first edit under `src/`
- [ ] **0.2** `git status --short` → empty
      ⚠️ **This will not be empty on this machine until `config.yaml` is reverted.** P7's live
      Telegram test (T11) left `notify.enabled: true`, `transport: bot_api` and a **real chat id** in
      it. `git checkout -- config.yaml` — and **never commit it**, which is what **R15** exists to
      prevent. Leave `.env` alone: it is git-ignored and the token is worth keeping.
      **It also turns the suite red** — three tests assert the shipped default is off:
      `test_the_notify_config_block_ships_and_defaults_to_off`,
      `test_the_shipped_config_block_builds_the_transport_it_names`, and the lazy-transport test.
      Measured 2026-08-11: 3 failures with the live config, 0 attributable to it once reverted
- [ ] **0.3** `git rev-parse HEAD` == `git rev-parse origin/main`
- [ ] **0.4** Latest CI run on `HEAD` is **success**
- [ ] **0.5** `python -m alembic heads` → exactly `0005_discovery (head)`
- [ ] **0.6** `python scripts\check_schema.py` → **OK — all 31 checks passed**
- [ ] **0.7** `python -m pytest` → green, one uninterrupted run. Record the count (baseline **1133**)
      ⚠️ **One known flake, and P8 must decide about it rather than absorb it.**
      `tests/test_orchestration.py::TestSchemaCheckScript::test_does_not_write_to_the_database_it_checks`
      is a WAL/mtime race. It failed on the P8 pre-flight run (`1 failed, 1130 passed, 2 skipped`)
      and passed immediately on re-run of the same test, unchanged (`4 passed`). **That is now the
      third occurrence** — [PHASE-07-HANDOVER §8](PHASE-07-HANDOVER.md) proposed it as *DI20* after
      the first. **A re-run is not a pass**, and a phase whose rule is *"green CI after every stage"*
      cannot rely on a coin flip five stages running. **See D8** — this is a decision, not a footnote
- [ ] **0.7a** Confirm **D8** is answered: register DI20 properly, or fix the flake first
- [ ] **0.8** Read `docs/PHASE-07-HANDOVER.md` in full; its entry conditions checked, its traps known
- [ ] **0.9** Confirm **D1 = Option A** and **D2 = freeze §4.1** are approved, in writing
- [ ] **0.10** Confirm **D6** (`mypy` / O2) is answered — closed in P8, or re-deferred with a reason
- [ ] **0.11** Take the M7 backup **before any migration is run against any copy**
- [ ] **0.12** Record `SELECT COUNT(*) FROM prescores` on the live copy. Expected **0** — if not, the
      `batch_alter_table` in step 2.8 copies real rows and Stage 4 must assert they survive
- [ ] **0.13** ⚠️ **Record the pre-migration `leads` rootpage** — step 4.4 and manual test **T5**
      both compare against it, and neither can be executed if it was never captured. Measured
      2026-08-11 at `0005`: **2**

      ```powershell
      python -c "import sqlite3; c=sqlite3.connect('data/leads.db'); print('leads rootpage =', c.execute('SELECT rootpage FROM sqlite_master WHERE type=? AND name=?', ('table','leads')).fetchone()[0])"
      ```
- [ ] **0.14** Record the current `leads` total (**478** on 2026-08-11) and the test count
      (**1133**). Both move as the scraper runs; the manual guide anchors on the recorded value, not
      on a hardcoded one

> ⚠️ **0.15 — Read this before opening any file.** `docs/18-phase-08.md` and
> `docs/testing/phase-08-testing.md` are the **superseded** eight-phase numbering
> ([lock §2.1](EXECUTION_MODE_LOCK.md)). They describe quality metrics, exports and production
> readiness — **P25–P27 and P30**. They are read-only. P8 is a schema migration.

---

<a id="stage-1"></a>
## Stage 1 — The guard, before the code it constrains

**This stage exists because of [review F1](P8-IMPLEMENTATION-REVIEW.md).** Writing it first means the
guard is proven to *fail* against the defective form and *pass* against the correct one — which is
the only way to know it guards anything.

- [ ] **1.1** Add `tests/test_migrations.py::test_no_revision_leaves_a_dangling_foreign_key`
      ([D5 Option B](P8-DECISION-ANALYSIS.md)). For each revision `0001..head`: upgrade a temp DB to
      it, then for **every table**, read `PRAGMA foreign_key_list(<table>)` and assert each
      referenced parent table **exists at that revision**. Any that does not is a dangling FK, and
      inserts into that table are already broken

      ⚠️ **Scope it this way, not as "insert into every table."** A universal-insert guard needs a
      valid fixture row for `jobs`, `run_events`, `prescores` (FK **plus** the `<>` CHECK),
      `dedup_members` and more, at each of six revisions — far past the useful cost, and the kind of
      thing that stalls Stage 1. The defect class is precisely *a `REFERENCES` target that does not
      exist yet*, and `foreign_key_list` names it directly with no fixtures at all
- [ ] **1.1b** Add the two concrete inserts as well — a lead and a comment at `0006` (**A7/A8**).
      These are cheap, and they prove the failure mode end to end rather than by proxy
- [ ] **1.2** Confirm the guard passes at `0005` **before** `0006` exists — it must be green on
      today's chain, or it is testing nothing
- [ ] **1.3** ⚠️ **Prove the guard bites.** Temporarily write `0006` with the *defective* inline
      `REFERENCES projects(id)` on `leads.project_id`. The new test **must fail** with
      `no such table: main.projects`. **Revert immediately.** Record the failure output in the
      completion report — it is the evidence that F1 was real
- [ ] **1.4** Confirm, in the same throwaway state, that `python scripts\check_schema.py`,
      `PRAGMA foreign_key_check` and the up/down/up round-trip **all still pass** with the defect
      present. This is the finding, and it must be demonstrated, not asserted
- [ ] **1.5** `pytest tests/test_migrations.py` green; working tree contains no leftover `0006`
- [ ] **1.6** Gate + commit: `test(P8): the insert guard that the FK round-trip cannot see`

---

<a id="stage-2"></a>
## Stage 2 — `migrations/versions/0006_content_and_dedup.py`

Statement order is the corrected [05 §7.1a](05-database-plan.md) sequence from
[review F5](P8-IMPLEMENTATION-REVIEW.md). It is a real constraint, not a formality.

- [ ] **2.1** File `0006_content_and_dedup.py`; `revision = "0006_content_and_dedup"`,
      `down_revision = "0005_discovery"`
- [ ] **2.2** Docstring, following `0005_discovery.py`'s idiom, stating: the four bare `project_id`
      columns and **why** (M8, `projects` arrives in `0007`); that `prescores` is *altered* here, not
      created; and that no row is rewritten
- [ ] **2.3** **`ALTER leads` — four columns, all metadata-only, `project_id` BARE:**
  - [ ] `project_id INTEGER NULL` — ⚠️ **no `REFERENCES` clause** (D1)
  - [ ] `confidence_score REAL NULL`
  - [ ] `analysis_status VARCHAR(20) NOT NULL DEFAULT 'not_analyzed'`
  - [ ] `source VARCHAR(20) NOT NULL DEFAULT 'scrape'` (D3)
  - [ ] Four indexes: `ix_leads_project_id`, `ix_leads_confidence_score`, `ix_leads_analysis_status`,
        `ix_leads_project_conf (project_id, confidence_score DESC)`
  - [ ] ⚠️ **No index on `source`** — 4 columns, 4 indexes (D3)
- [ ] **2.4** `CREATE comments` — [05 §5.4](05-database-plan.md) verbatim, **except** `project_id`
      bare (D1). `ux_comments_hash` UNIQUE on `body_hash`; `ix_comments_lead`; `ix_comments_project`
- [ ] **2.5** `CREATE dedup_groups` — `project_id` **nullable and bare** (D1, D4); FKs to `leads` and
      `comments` are in-revision and stay inline; `ix_dedup_groups_project`
- [ ] **2.6** `CREATE dedup_members` — FKs to `dedup_groups`/`leads`/`comments` inline; the
      `CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))`; both **partial** unique indexes
- [ ] **2.7** `CREATE minhash_bands` — `project_id` **nullable and bare** (D1, D4);
      `ix_minhash_lookup`
- [ ] **2.8** `batch_alter_table("prescores")` → `create_foreign_key("fk_prescores_comment", "comments", ["comment_id"], ["id"], ondelete="CASCADE")`
      — closes the FK `0005` deferred
- [ ] **2.9** `downgrade()` in **exact reverse order**, with the `prescores` constraint dropped
      **first** (it references `comments`, which cannot be dropped while it points at it — the
      `0004_orchestration.py:112` pattern)
- [ ] **2.10** ⚠️ **No `gate_audits`.** [05 §5.4b](05-database-plan.md) lists it beside the dedup
      tables; [freeze §4.1](ARCHITECTURE_FREEZE.md) places it in `0009` (P19)
- [ ] **2.11** ⚠️ **No rows are written.** P8 creates empty tables
- [ ] **2.12** `python -m alembic heads` → one head
- [ ] **2.13** Gate + commit: `feat(P8): 0006 content and dedup, with four foreign keys left open`

---

<a id="stage-3"></a>
## Stage 3 — `src/db/models.py`

- [ ] **3.1** `Lead` gains the four columns, matching the migration exactly. `project_id` is
      `Column(Integer, nullable=True)` — **no `ForeignKey`** until `0007` (D1)
- [ ] **3.2** `Comment` model — [34 §P8](34-implementation-plan.md) names it a deliverable
- [ ] **3.3** `DedupGroup`, `DedupMember`, `MinhashBand` models (D7 d2 — `test_post_baseline_columns_are_exactly_as_declared`
      reflects `Base.metadata` and diverges without them)
- [ ] **3.4** Every `DateTime` default uses the existing `_utcnow`, never `datetime.utcnow`
      (D7 d3) — `test_no_datetime_column_defaults_to_a_deprecated_or_local_clock` enforces it
- [ ] **3.5** Update `POST_BASELINE_COLUMNS` in `tests/test_migrations.py`: `leads` gains
      `project_id`, `confidence_score`, `analysis_status`, `source` (D7 d6)
- [ ] **3.6** ⚠️ `src/db/models.py` is **not** in the `ruff format` exclusion list — confirm before
      editing, and do not reformat neighbouring legacy code (DI4)
- [ ] **3.7** ⚠️ `leads.score` stays as it is. [05 §4.1](05-database-plan.md)'s nullable-`score`
      change is a **model-level** note with no `ALTER`; changing it now would perturb the legacy
      contract for no P8 benefit. Record it as P11's, where the search-score back-fill lands
- [ ] **3.8** Gate + commit: `feat(P8): the five models, and the four columns leads did not have`

---

<a id="stage-4"></a>
## Stage 4 — Migration and schema tests

Every **bold** acceptance criterion in [34 §P8](34-implementation-plan.md) gets mutation discipline
([lock §4](EXECUTION_MODE_LOCK.md)).

- [ ] **4.1** **A7/A8 — the F1 guard, now against the real `0006`:** at revision `0006`, insert a
      lead and a comment; both succeed. Stage 1's parametrised test should now cover this
      automatically — confirm it picked `0006` up rather than silently skipping it
- [ ] **4.2** **A2 — defaults over all 478 rows.** On a live-DB copy after upgrade:
      `project_id IS NULL`, `confidence_score IS NULL`, `analysis_status='not_analyzed'`,
      `source='scrape'` for **every** row. Assert the count is 478, not a sample
- [ ] **4.3** **A2/A5 — the 459 original leads and the `intent_score` fingerprint are unchanged.**
      `max = 164.28`, `avg = 42.29` — the values `check_schema.py` already pins
- [ ] **4.4** **A3 — no row rewritten.** Assert the `ALTER` was metadata-only by comparing `rootpage`
      for `leads` in `sqlite_master` before and after (D7 d7). ⚠️ **Not a wall-clock assertion** —
      that is DI18's trap, and A6's *"< 1 s"* is the same species
- [ ] **4.5** **A9 — `ck_prescores_one_target` survives the rebuild.** Assert the named CHECK is
      still present in `sqlite_master` **after** step 2.8. Named-constraint reflection is the known
      weak spot of `batch_alter_table` ([review §4.2](P8-IMPLEMENTATION-REVIEW.md))
- [ ] **4.6** `fk_prescores_comment` is present and **enforced**: inserting a `prescores` row with a
      non-existent `comment_id` raises. Assert the effect, not the presence
- [ ] **4.7** **A1 — up / down / up on a copy of the live DB**, 478 leads at every stage, one head at
      every stage
- [ ] **4.8** Both partial unique indexes on `dedup_members` behave: a duplicate `(group_id, lead_id)`
      raises; a `NULL` `lead_id` does not collide
- [ ] **4.9** `ux_comments_hash` rejects a duplicate `body_hash`
- [ ] **4.10** Extend `scripts/check_schema.py` for the four new tables and four new `leads` columns.
      Record the new check count (baseline **31**)
- [ ] **4.11** ⚠️ **The dedup_members invariant is NOT asserted.** *"At most one group per run"* is
      not expressible in this schema ([review F7](P8-IMPLEMENTATION-REVIEW.md)). Do not write a test
      that appears to check it. Record it for P10 instead
- [ ] **4.12** Gate + commit: `test(P8): prove the migration is metadata-only and the CHECK survived`

---

<a id="stage-5"></a>
## Stage 5 — Documentation, reconciliation, and the executed rollback

The [D2](P8-DECISION-ANALYSIS.md) edits. **None of these was made during the review.**

- [ ] **5.1** [05 §7](05-database-plan.md) table — renumber `0005`–`0009` to
      [freeze §4.1](ARCHITECTURE_FREEZE.md); add `0010`
- [ ] **5.2** [05 §7](05-database-plan.md) prose — strike *"No tenth revision"* (**both**
      occurrences); correct *"the three `leads` columns land in `0007` (Phase 6)"*; correct
      *"`0007` is the only one that touches `leads` … drops the three added columns"*
- [ ] **5.3** [05 §7.1](05-database-plan.md) — add the four deferred FKs (`leads.project_id`,
      `comments.project_id`, `dedup_groups.project_id`, `minhash_bands.project_id`), each created at
      `0006`, referencing `projects` (`0007`), FK added in `0007`
- [ ] **5.4** [05 §7.1a](05-database-plan.md) — retitle to `0006`; "3 columns" → **4**; **delete**
      step 6 `CREATE prescores`; **add** the `prescores.comment_id` closure as the final step
- [ ] **5.5** [05 §4.1](05-database-plan.md) — add the `source` DDL from
      [16 §115](16-phase-06.md) (D3); note that `project_id` ships bare and is constrained in `0007`
- [ ] **5.6** [05 §5.4](05-database-plan.md), [§5.4b](05-database-plan.md) — `comments.project_id`,
      `dedup_groups.project_id` and `minhash_bands.project_id` to `NULL`, each with a comment naming
      `0007` (D1, D4)
- [ ] **5.7** [freeze §11.1](ARCHITECTURE_FREEZE.md) — **one** new row, dated 2026-08-11, phase
      **P8**, recording the 05 §7/§7.1/§7.1a reconciliation and the four deferred FKs. State
      explicitly that no technology, table or decision changes
- [ ] **5.8** [DEFERRED-IMPROVEMENTS](DEFERRED-IMPROVEMENTS.md) — add the `dedup_members`
      *"one group per run"* invariant ([review F7](P8-IMPLEMENTATION-REVIEW.md)) with **P10** as its
      trigger. **Do not** add DI20; it does not exist and inventing it would be worse than the gap
- [ ] **5.9** ⚠️ **Execute the rollback, do not merely document it**
      ([lock §4](EXECUTION_MODE_LOCK.md)). On a copy: `alembic downgrade 0005_discovery`, then
      `check_schema.py` → 31 checks pass, 478 leads, fingerprint intact; then `upgrade head` again.
      Record the actual terminal output
- [ ] **5.10** Gate + commit: `docs(P8): the migration table that predated the reorder`

---

## Post-implementation — [lock §3](EXECUTION_MODE_LOCK.md) steps 8–16

- [ ] **P.1** `docs/testing/P08-testing.md` — Part A generated, sign-off table present
- [ ] **P.2** ⚠️ **Execute every command in the guide before shipping it.** Two guides have already
      shipped with commands that could not produce the output they promised
      ([DI19](DEFERRED-IMPROVEMENTS.md), and P7's 31 corrections). Reading them is not executing them
- [ ] **P.3** ⚠️ Every command in the guide is **PowerShell**. A bash-escaped command silently
      no-ops on this machine and reads as a passing test
- [ ] **P.4** `docs/PHASE-08-COMPLETION-REPORT.md` — **must record the pre- and post-migration
      `leads` rootpage** from 0.13/4.4, the pre- and post- lead totals, and the pre- and post- test
      counts. Manual test **T5** compares against the rootpage value and cannot be executed if the
      report omits it
- [ ] **P.5** `docs/PHASE-08-HANDOVER.md` — **must** carry:
  - **P12 inherits four `batch_alter_table` rebuilds**, one over `leads`, M7 backup first (D1)
  - **P12 must decide** whether `dedup_groups.project_id` / `minhash_bands.project_id` become
    `NOT NULL`; [34 §P12](34-implementation-plan.md) currently tightens only `runs.project_id` (D4)
  - **DI14 fires in P10** — the 444/27 permalink host split, in tables P8 just created
  - **DI13 fires in P11** — `num_comments = 0` vs `None`
  - The `dedup_members` invariant is **application-level, P10's** (F7)
  - **DI15 did not fire in P8** — no job type was added; the trigger passes to P11
- [ ] **P.6** `docs/progress/P08-COMPLETE.md`, ending in a resume point
- [ ] **P.7** `docs/README.md` execution table updated
- [ ] **P.8** Repository Hygiene Review — [lock §5](EXECUTION_MODE_LOCK.md) H1–H8, on the **staged**
      diff. ⚠️ H3: no `C:\Users\` path in any document
- [ ] **P.9** Push
- [ ] **P.10** ⚠️ **Do not tag** until the manual sign-off table is signed
      ([lock §6.2](EXECUTION_MODE_LOCK.md)). O3 already has two unsigned tables; P8 must not add a
      third
- [ ] **P.11** **STOP.** Report, and wait for explicit approval

---

## Stage summary

| Stage | Files | Tests added | Risk |
|---|---|---|---|
| 0 | none | none | — |
| 1 | `tests/test_migrations.py` | 1 (parametrised over every revision) | Low |
| 2 | `migrations/versions/0006_content_and_dedup.py` | — | **The whole phase's risk lives here** |
| 3 | `src/db/models.py`, `tests/test_migrations.py` | — | Low |
| 4 | `tests/test_migrations.py`, `scripts/check_schema.py` | ~10 | Low |
| 5 | `docs/05`, `docs/ARCHITECTURE_FREEZE`, `docs/DEFERRED-IMPROVEMENTS` | — | Low |

**Expected footprint:** ~200 lines of migration, ~90 lines of models, ~150 lines of tests, and seven
document targets. No new package, no new dependency, no runtime code path, no AI call, no network
call.

> **The one thing that must not be got wrong:** step **2.3**. A `REFERENCES projects(id)` there
> breaks every lead insert in the shipped scraper, and the up/down/up round-trip, `check_schema.py`,
> `PRAGMA foreign_key_check` and P8's own acceptance criteria **all report success anyway**.
> Stage 1 exists solely to make that impossible to ship.
