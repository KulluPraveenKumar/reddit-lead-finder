# Phase 12 — Handover

**From:** P12, the project and knowledge-base schema · **Written:** 2026-08-15
**To:** **P13**, and for the debts, **P14**, **P15**, **P16** and **P17**

> Evidence lives in [PHASE-12-COMPLETION-REPORT.md](PHASE-12-COMPLETION-REPORT.md).
> Reasoning lives in [P12-DECISION-ANALYSIS.md](P12-DECISION-ANALYSIS.md).
> Where the next session resumes lives in [progress/P12-COMPLETE.md](progress/P12-COMPLETE.md).

---

## 1. What now exists

**The schema can hold a knowledge base.** `0007_projects_and_knowledge_base` is the seventh revision
and the largest in the chain: **twelve tables**, **six** deferred `project_id` foreign keys closed,
and a conditional pair that exists only where `sqlite-vec` loads.

`alembic heads` is `0007_projects_and_knowledge_base` — the first head change since P8, after four
phases at `0006`.

```
projects ──┬── website_snapshots ──┐
           ├── bkb ──┬── bkb_sections   (23 rows, 3 with a NULL payload)
           │         ├── personas ──── pain_points
           │         ├── intent_signals
           │         └── bkb_evidence ──┘  (+ leads, comments)
           ├── bkb_entities ── bkb_entity_aliases
           ├── bkb_links          (polymorphic endpoints)
           └── bkb_suggestions
```

**Everything is empty.** P12 ships shape, not content: the first `projects` row is **P16**'s, the
first `bkb` is **P14**'s, the entity registry is **P15**'s.

**The public surface P13 will meet:**

```python
from src.db.models import (
    BKB_ENTITY_KINDS,       # competitor|product|feature|tool|alternative — and only these
    BKB_SECTION_KEYS,       # the 23, in 06e §2 order
    BKB_STALENESS_DAYS,     # 23 keys; Group C is None — never stales
    BKB_TYPED_SECTION_KEYS, # the 3 whose payload_json is NULL
    BKB, BKBSection, Persona, PainPoint, IntentSignal, Project, WebsiteSnapshot,
)
```

P13 writes `website_snapshots`, and nothing else here.

---

## 2. Guarantees P13 must not break

| | Guarantee | Enforced by |
|---|---|---|
| **G1** | **`runs.project_id` stays NULLABLE**, and a run can still be created with no project | `test_runs_project_id_is_still_nullable`, `test_a_run_can_still_be_created_without_a_project` |
| **G2** | **All six deferred `project_id` FKs are closed**, with their four distinct ON DELETE actions | `test_all_six_deferred_project_keys_are_closed`, `test_the_deletion_actions_are_not_uniform` |
| **G3** | **`payload_json` is NULL for exactly three sections and NOT NULL for the other twenty** — enforced by `ck_bkb_sections_payload_null_rule`, not by convention | `test_the_three_typed_sections_must_have_a_null_payload`, `test_the_other_twenty_sections_must_have_a_payload`, `test_ideal_customer_profiles_is_not_exempt` |
| **G4** | **The migration completes with `sqlite-vec` absent**, skipping *both* vector tables and saying so | `test_the_migration_completes_with_sqlite_vec_unavailable`, `test_the_skip_is_logged_with_its_cause` |
| **G5** | **Neither vector table is declared on `Base`** — `create_all()` must not produce a schema the migration cannot | `test_neither_vector_table_is_declared_on_the_orm_base` |
| **G6** | **`/health` reports `semantic_layer` from the schema, never from an import** | `test_health_reads_the_schema_rather_than_importing_sqlite_vec` |
| **G7** | **No revision leaves a dangling foreign key** — now covering `0007` | `test_no_revision_leaves_a_dangling_foreign_key`, `test_the_dangling_fk_guard_covers_0007` |
| **G8** | **The 459 original leads and the `intent_score` fingerprint survive the `leads` rebuild** | `test_up_down_up_on_a_copy_of_the_live_database` |
| **G9** | **`sqlite-vec` and `model2vec` stay optional** — no installable line names either | `test_sqlite_vec_is_not_a_declared_dependency` |
| **G10** | One head, always — and the chain is **seven** of its ten | `test_single_head`, `test_the_head_is_0007_and_there_is_still_one_of_them`, `test_the_chain_is_still_ten_revisions_or_fewer` |
| **G11** | `check_schema.py` verifies **both** revisions — bare at `0006`, closed at `0007` | `test_check_schema_verifies_the_0007_shape`, `test_check_schema_still_verifies_a_database_left_at_0006` |

---

## 3. ⚠️ What P13 inherits directly

1. **`website_snapshots` is yours to write, and `content_hash` is the L1 cache key.**
   The table has `project_id`, `url`, `pages_fetched`, `extracted_text`, `content_hash`,
   `fetched_at`. [34 §P13](34-implementation-plan.md)'s *"unchanged fingerprint within 7 days makes
   **zero** fetches"* is a query against `content_hash` and `fetched_at` — the columns exist, the
   cache logic does not.

2. **`projects` has no rows and no writer.** P13 depends on P12 **and P4**, but nothing creates a
   project until **P16**'s `project add`. If P13 needs one to fetch against, it creates it in a
   fixture — not in a migration, and not by adding a writer that P16 then has to reconcile with.

3. **`runs.project_id` is nullable, permanently.** If any P13 code assumes a run has a project,
   it is wrong today and will be wrong after P16 too. See [§4 T1](#4-traps-waiting-in-p13).

---

## 4. Traps waiting in P13

**T1 — 🔴 `NOT NULL` on `runs.project_id` is asked for by two documents and is not buildable.**
[34 §P12](34-implementation-plan.md)'s DB row said *"(+ `NOT NULL`)"* and
[05 §7.1a](05-database-plan.md) step 3 said *"tighten `project_id NOT NULL`"*. Both are corrected
now, but **the reasoning matters more than the correction**: 11 of 11 live runs have it `NULL`, the
rebuild's `INSERT … SELECT` fails on them, the backfill that would fix it is the row rewrite **M5**
forbids, and **AD-5** freezes project scoping as *additive and nullable*. Recorded at
[freeze §11.1](ARCHITECTURE_FREEZE.md). Two tests pin it. **Do not re-attempt it in `0008`.**

**T2 — 🔴 `create_all()` and `upgrade head` do not produce the same schema, on purpose.**
Neither `bkb_embeddings` nor `bkb_embedding_meta` is declared on `Base`, because `bkb_embeddings` is
a `vec0` virtual table that `create_all()` would emit as a plain `CREATE TABLE` on every host —
making an optional recall improvement a hard dependency. Any phase tempted to "complete" the models
by adding them breaks G5. The pair is created by the migration or not at all.

**T3 — the `vec0` DDL has never executed, anywhere.** `sqlite_vec` is absent on this host (P0's
finding, re-measured 2026-08-15), so `CREATE VIRTUAL TABLE bkb_embeddings USING vec0(embedding
FLOAT[256])` is pinned as a **string** and has never been run by SQLite. Everything around it is
tested — the failure path is forced, both tables are asserted skipped together, the warning names its
cause, the downgrade is clean — but *"does `vec0` accept this column spec?"* is **open**. **P15** is
the first phase with a reason to install the extension and will be the first to find out. Budget for
it being wrong.

**T4 — the payload rule is spelled in three places and they must agree.** The migration spells the
three keys literally (a revision is a snapshot and must not import a constant a later phase edits),
`src.db.models.BKB_TYPED_SECTION_KEYS` spells them again, and `scripts/check_schema.py` a third time.
`test_the_migrations_check_and_the_models_constant_agree` pairs the first two — the P9
`test_rules_vocabulary.py` idiom. **`ideal_customer_profiles` is not one of the three**, and that is
the mistake [05 §5.1b](05-database-plan.md) flags by name: there is no `icps` table, so its
`payload_json` is the only copy of an ICP that exists.

**T5 — `staleness_days` is a policy, not a seeded column.** `BKB_STALENESS_DAYS` ships 23 entries
with Group C at `None`; **P14 writes them into rows**, because P14 is the phase that creates a BKB.
A reader looking for seeded values in `0007` will find an empty table and conclude the task was
skipped. It was not — there was nothing to seed.

**T6 — six `batch_alter_table` rebuilds ran against the live table R20 pins.** `leads` was
create-copy-drop-renamed. It was probed before the revision was written and asserted after, but the
lesson generalises: **any future `batch_alter_table` on `leads` needs the same fingerprint-and-index
assertion**, because a reflection that drops the `reddit_id` UNIQUE leaves a database that passes
`integrity_check`, `foreign_key_check` and every row count.

**T7 — `check_schema.py`'s four `project_id` assertions invert at `0007`, and `--skip-p12` is how a
`0006` database is still verified.** The operator's live database **is still at `0006`** until they
run the manual guide. `python scripts/check_schema.py --db data/leads.db` now expects `0007`; add
`--skip-p12` for a database that has not been upgraded. `--skip-p8` implies `--skip-p12`.

**T8 — `test_a1_...` and `test_a3_...` in `test_migrations.py` are pinned to `0006`, not `head`.**
Both are P8's tests about P8's revision, and `head` silently retargeted them when `0007` landed —
`test_a3` then failed, correctly reporting `0007`'s legitimate `leads` rebuild as a P8 defect. **Any
phase adding a revision must check for `upgrade("head")` in tests that mean a specific revision.**

---

## 5. Debts carried forward, by owner

| | Item | Owner |
|---|---|---|
| **DI28** | `leads` has no `run_id`. **Considered and declined in P12** — no failed measurement, and [lock §8](EXECUTION_MODE_LOCK.md) needs the improvement to relate to the phase. Trigger unchanged | **P17**, the next revision (`0008`) |
| **`pain_phrase`** | Absent pre-score component. `pain_points` exists and is **empty** | **P14**, which writes `phrases_json` |
| **`competitor`** | Absent pre-score component; `test_the_competitor_registry_was_not_wired_before_p15` still fails if wired early | **P15** |
| **`subreddit_fit`** | Absent pre-score component. `projects` exists and is **empty** | **P16**, which writes the first row |
| **T3 above** | The `vec0` DDL is unexecuted | **P15** |
| **DI26** | `keywords.normalise` tears decomposed Unicode apart | **P15** |
| **DI14** | `_extract_search_post` does not normalise its host | Unchanged |
| **DI15** | An eighth job type shipped unreconciled. **P12 added none** | Unchanged |
| **DI16 / T1 (P8)** | `leads.confidence_score` exists, not populated | **P21** |
| **DI17** | Nothing enqueues `maintenance` | **P17** |
| **DI29** | **New.** The literal `grep` form of fences 2 and 3 in [35 §2.1](35-testing-strategy.md) returns 6 and 2 matches — **all docstrings and comments, no import statements**. The AST-based `tests/test_boundaries.py` is the shipped enforcement and passes | *Someone runs the documented command and reads its output as a fence breach* |
| **DI20 · DI22 · DI27** | Triggers not satisfied across this phase | *A further occurrence* |
| **L4 (P7)** | Notification retry — **still nobody's** | Open since P7 |
| **O2** | `mypy`, deferred by D6 in P8. P12's new code ships clean under it | Its own scoped task |

**No Deferred Improvement was closed. One was opened — [DI29](DEFERRED-IMPROVEMENTS.md).** DI28 was
considered and declined with its reasoning recorded, which is what its trigger asked for.

---

## 6. Things a later phase must delete on purpose

| Phase | Test | Why it is there |
|---|---|---|
| **P14** | `test_the_three_absent_pre_score_components_are_still_absent` | It asserts exactly three absences **and that none names P12**. When P14 writes `pain_points.phrases_json`, `pain_phrase` becomes computable and **this test must be updated in the same change** — with `WEIGHTS` and `prescore()`. [PHASE-11-HANDOVER §4](PHASE-11-HANDOVER.md) T2 still applies: a seventh weight **rescales every stored `total`**, so re-measure the distribution before trusting the admission floor of 35 |
| **P14** | `test_p12_wrote_no_row` | Asserts all twelve tables are empty. P14 writes `bkb`, `bkb_sections`, `personas`, `pain_points`, `intent_signals` — **narrow this test to the tables P14 does not write**, do not delete it, or nothing will notice a migration that starts seeding rows |
| **P15** | `test_the_competitor_registry_was_not_wired_before_p15` | *(P9's)* Unchanged — P12 did not wire it |
| **P17** | `test_the_chain_is_still_ten_revisions_or_fewer` | Asserts **seven** revisions and that the last is `0007`. `0008_targeting` makes it eight; update the count, and keep the ten-revision ceiling ([freeze §4.1](ARCHITECTURE_FREEZE.md): *"No eleventh without an amendment"*) |
| **P17** | `test_leads_has_no_run_id` | P12's DI28 decision, pinned. If P17 carries the column in `0008`, **this test must go in the same change** — and DI28 moves to §3 of that phase's handover |
| **P21** | *(none yet)* | `src/scoring/` will hold `ConfidenceScorer`, and **R6 is "categoricals in, arithmetic out"** — `intent_signals.weight` is a **stored row**, never a call |

---

## 7. Verification snapshot at handover

| | |
|---|---|
| Full suite | **1903 passed, 2 skipped** in 388.07 s (P11: 1871 / 2) |
| New tests | **+32** |
| Coverage, whole tree | **89.20%** (P11: 87%) · `src/{ai,net,scoring}` **90%**, against the ≥85% floor |
| `ruff check` / `format --check` | Clean · 175 files |
| `alembic heads` | `0007_projects_and_knowledge_base` — one head; seven revisions of ten |
| `check_schema.py` | **74/74** on a fresh `0007` · **51/51** on the live `0006` with `--skip-p12` · **76/76** on an upgraded copy of the live database |
| Boundary / fence tests | **81 passed** (AST-based) |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns · `GET /` 200 |
| Mutation testing | **18 designed · 17 detected · 1 survived · 0 not applied.** The survivor is the deliberate control. **Two real defects found**, both in P12's own tests |
| Grep fences | Fence 2 covers **4 of 6** — unchanged; `src/knowledge/` is P15's. ⚠️ The *literal* grep form of fences 2 and 3 now returns 6 and 2 prose matches — [DI29](DEFERRED-IMPROVEMENTS.md) |
| Tables created | **12** · conditional pair **skipped** (`sqlite-vec` absent, measured) |
| Foreign keys closed | **6** |
| Migration duration | **0.120 s** upgrade · **0.165 s** downgrade, against a 5 s budget |
| AI calls | **0** |
| Rollback | **Executed** — up/down/up on a copy of the live database, fingerprint `9327a13dd9ef4185` identical at all four stages |

---

## 8. Blockers carried into P13

| ID | Blocker | Blocks P13? |
|---|---|---|
| **D1/O3** | **P00–P07, P09, P10, P11 manual sign-off tables unsigned.** P8's was signed 2026-08-14 | **No, but no tag.** P12's guide is unsigned until the operator runs it |
| **⚠️ live DB** | **`data/leads.db` is still at `0006`.** P12 did **not** upgrade it — that is the operator's action, and it is step T3 of the manual guide, with the M7 backup | **No.** The suite runs on copies; `--skip-p12` verifies the live file meanwhile |
| **T3 (§4)** | The `vec0` branch has never executed | **No.** P13 does not touch the semantic layer |
| **O2** | `mypy` not in the gate | **No.** Deferred by D6 in P8 |
| **L4 (P7)** | Notification retry undelivered | **No**, still an open P7 obligation |

---

## 9. Entry conditions for P13

- [ ] `docs/testing/P12-testing.md` sign-off table signed — **T3, T5 and T7 especially**
- [ ] **[§3 read]** — `website_snapshots` is yours; `projects` is empty and P16 is its writer
- [ ] **[§4 T1 read]** — `runs.project_id` is nullable permanently; do not re-attempt `NOT NULL`
- [ ] **[§4 T2 read]** — `create_all()` and `upgrade head` differ by two tables, deliberately
- [ ] **[§4 T3 read]** — the `vec0` DDL is unexecuted and is **P15's** to discover
- [ ] **[§6 read]** — `test_p12_wrote_no_row` is **P14's** to narrow, not to delete
- [ ] [34 §P13](34-implementation-plan.md) read — all thirteen fields, including **direct egress**
      (`request_class="website"`, AD-25) and the **`file://` → 422** validation
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] The full suite recorded green before the first change — **1903 passed, 2 skipped**
- [ ] `git status` clean · `alembic heads` = one `0007`
- [ ] ⚠️ **`check_schema.py` now expects `0007`.** Against the live database, which is still at
      `0006`, use `--skip-p12` — or run the guide's upgrade first
- [ ] `gh run list` checked: P12 green on `origin/main`
- [ ] ⚠️ **`config.yaml` checked for uncommitted local values** — it carried a real chat id at the
      start of both P8 and P9. **P12 added no config key**; the file should be untouched since P11
- [ ] ⚠️ **P13 adds `trafilatura` to `requirements.txt`** — the first new dependency since P2. It is
      named in [freeze §5](ARCHITECTURE_FREEZE.md) as the text-extraction choice, so it needs no
      amendment; adding anything *beside* it does
