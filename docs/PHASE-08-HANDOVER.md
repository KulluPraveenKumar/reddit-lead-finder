# Phase 08 — Handover

**From:** P8, content & dedup schema (`0006_content_and_dedup`) · **Written:** 2026-08-13
**To:** P9 and, for the schema debts, **P10**, **P11** and **P12**

> Evidence lives in [PHASE-08-COMPLETION-REPORT.md](PHASE-08-COMPLETION-REPORT.md).
> Where the next session resumes lives in [progress/P08-COMPLETE.md](progress/P08-COMPLETE.md).

---

## 1. What now exists

Four empty tables — `comments`, `dedup_groups`, `dedup_members`, `minhash_bands` — four new `leads`
columns with four indexes, and one closed foreign key. **Nothing writes to any of it yet.** P8 built
shelves; P9–P11 stock them.

---

## 2. Guarantees P9 must not break

| | Guarantee | Enforced by |
|---|---|---|
| **G1** | **The 459 original leads and their `intent_score` fingerprint never change** | `check_schema.py`, `test_a5_…`, `tests/baseline/db_fingerprint.json` |
| **G2** | **No revision leaves a foreign key pointing at a table that does not exist yet** | `test_no_revision_leaves_a_dangling_foreign_key`, over every revision `0001..head` |
| **G3** | **A downgrade leaves a valid, writable schema** | `test_a1_up_down_up_on_a_copy_of_the_live_database` |
| **G4** | **`ck_prescores_one_target` survives any further `prescores` rebuild** | Two tests: present, and enforced |
| **G5** | One head, always | `test_single_head` |

---

## 3. ⚠️ Four debts P12 inherits, and one decision it must make

**P12 owns `0007_projects_and_knowledge_base`, which creates `projects`.**

1. **Four `batch_alter_table` rebuilds**, closing `leads.project_id`, `comments.project_id`,
   `dedup_groups.project_id` and `minhash_bands.project_id`. One is over `leads`. **Take an M7 backup
   first.**

2. **⚠️ A rebuild here is real, unlike the one P8 measured.** `batch_alter_table` does **not** rebuild
   when its only operation is `add_column` — alembic emits a plain `ALTER`, measured `rootpage 2 → 2`.
   It **does** rebuild when it changes constraints, which is exactly what `0007` does. **Do not carry
   P8's "it was metadata-only" result across; it will not hold.**

3. **P12 must decide whether `dedup_groups.project_id` and `minhash_bands.project_id` become
   `NOT NULL`.** [05 §5.4b](05-database-plan.md) declares them `NOT NULL`; that is unsatisfiable at
   `0006` and P8 shipped them nullable. **[34 §P12](34-implementation-plan.md) tightens only
   `runs.project_id` and says nothing about these two**, so on the documents as written they are
   nullable forever. Tightening them costs a **fifth and sixth** rebuild on top of the four above.
   P8 did not pre-empt the choice; make it deliberately.

4. The answer is genuinely unobvious: **all 478 existing leads carry `project_id IS NULL`**, P10
   groups leads rather than projects, and [X4](31-execution-plan.md) anticipates project-less leads as
   normal.

---

## 4. Traps waiting in P9–P12

**T1 — `leads.confidence_score` now exists, and that does NOT unblock the deferred kind.**
[DI16](DEFERRED-IMPROVEMENTS.md)'s `lead.high_confidence` trigger is *"the column exists **and** is
populated (P21)"*. The column alone is not the trigger. `tests/test_boundaries.py::test_min_confidence_alert_was_not_shipped`
still fences `notify.min_confidence_alert` — delete that fence deliberately when P21 ships the kind,
do not discover it failing.

**T2 — the `dedup_members` invariant is yours, P10.** *"At most one group per run"* is **not**
expressible in this schema: there is no `run_id`, the run is reachable only through `dedup_groups`,
and SQLite cannot constrain uniqueness across a join. P8 shipped **no test that appears to check it**,
on purpose. Registered as **DI22**. Uphold it in the cascade and test it there.

**T3 — DI14 fires in P10.** The 444/27 `old.reddit.com` vs `www.reddit.com` permalink split is a
dedup-keying hazard, in tables P8 has now created. If the cascade keys on `url`, the same post
appears twice.

**T4 — DI13 fires in P11.** `_extract_post` reports `num_comments = 0` where the honest value is
`None`. P11's comment-fetch eligibility test is the first decision that hangs off the difference.

**T5 — a mutation you have not run is a test you do not have.** P8 ran **14**. Three survived a first
pass and **every one was informative**: one was a masked assertion (a real test defect), and two were
equivalences that had to be *proven* rather than assumed. Not one was noise.

**T6 — a re-run is not a pass.** Two flaky tests cost this phase five extra full-suite runs. Do not
let "probably the flake" become the reflex — see §8.

**T7 — `check_schema.py` has two skip-flags now.** `--skip-p6` and `--skip-p8`, plus a pinned count in
`tests/test_orchestration.py`. A revision that forgets to update them fails in a way that looks like a
schema defect and is not.

---

## 5. Findings carried forward, not resolved

| | Finding | Owner |
|---|---|---|
| **F-1** | **The Stage 3 checklist never mentions `Prescore`.** Its `comment_id` was still bare after Stage 2 closed the FK, so `create_all()` and `alembic upgrade head` disagreed. Fixed in P8; recorded because the *checklist* is still wrong | Whoever revises the P8 checklist |
| **F-2** | **`POST_BASELINE_COLUMNS` alone was insufficient**, because `_dump_schema` skips by index name rather than table name. `POST_BASELINE_INDEXES` was added. Any future revision adding an index to a **baseline** table must update it | P12 (`0007` alters `leads`) |
| **F-3** | **Checklist step 2.9 states the wrong reason** for the downgrade drop order. Its instruction is right; its justification is not — SQLite permits dropping a referenced parent in every configuration. The hazard is the reference left behind | Whoever revises the P8 checklist |
| **F-4** | **`docs/05 §7`'s "deferral is cheap" claim was factually wrong** and is struck. Recorded in [freeze §11.1](ARCHITECTURE_FREEZE.md) | Closed |
| **DI15** | **Did not fire in P8** — no job type was added. The trigger passes to **P11** | P11 |

---

## 6. Verification snapshot at handover

| | |
|---|---|
| Full suite | **1148 passed, 2 skipped** (P7: 1131 / 2) |
| Under `-W error::DeprecationWarning` | **1148 passed, 2 skipped** |
| New P8 tests | **+17** |
| `ruff check` / `format --check` | All checks passed / 127 files |
| `alembic heads` | `0006_content_and_dedup` — one head |
| `check_schema.py` | **51** plain · **52** with `--revision 0006` · **31** at `0005` with `--skip-p8` |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · sha256 `52b2ebb2…` · 13 CSV columns |
| `leads` rootpage | **2 → 2** — no row rewritten |
| Live DB | upgraded 2026-08-13; M7 backup `data/backups/leads-20260813T131507Z.db` |
| Mutation testing | **14 designed · 12 detected · 2 proven equivalent** |
| Grep fences | 4 of 4, unchanged |
| Rollback | **Executed**, twice, on a copy |

---

## 7. Blockers carried into P9

| ID | Blocker | Blocks P9? |
|---|---|---|
| **D1/O3** | P00–P08 manual sign-off tables unsigned | **By the project's own rule, yes** ([lock §4](EXECUTION_MODE_LOCK.md)). **No tag.** The operator explicitly approved proceeding past this for P8 |
| **O2** | `mypy` installed but not in the gate — **193 errors in 23 files** | **No.** Deferred by decision D6, with the measurement recorded |
| **D8** | The flaky-test decision — fix or register | **No**, but it costs a re-run per stage |
| **DI17** | Nothing enqueues `maintenance` | **No** — P17's |
| **DI22** | `dedup_members` invariant unenforced | **No** — P10's |
| **L4 (P7)** | Notification retry is undelivered | **No**, but it is still an open P7 obligation |

---

## 8. ⚠️ The flaky tests, and why this is now a pattern

**Five occurrences in one phase**, on unchanged code:

| Test | Times | Register |
|---|---|---|
| `test_parse_speed_stays_inside_the_budget` | **2** | [DI18](DEFERRED-IMPROVEMENTS.md) |
| `test_does_not_write_to_the_database_it_checks` | **2** | proposed DI20 — **still unregistered** |
| `test_the_heartbeat_thread_extends_a_lease_while_a_handler_runs` | **1** | **unregistered** |

All three are wall-clock or filesystem-timing assertions. All three pass in isolation. **Two
consecutive gate runs in Stage 5 failed on two *different* ones.**

The cost is not the re-runs. It is that a phase with a *"green after every stage"* rule is being
trained to read a red suite as *"probably the flake"* — which is exactly the reflex that lets a real
regression through. **D8 remains open by operator decision**, and the third test above is not
registered anywhere; P9 should either register all three or fix them.

---

## 9. Entry conditions for P9

- [ ] `docs/testing/P08-testing.md` sign-off table signed — **T9's four visual checks especially**
- [ ] **[§3 read]** — the four rebuilds and the `NOT NULL` decision P12 must make
- [ ] **[§4 T1 read]** — `confidence_score` existing does **not** unblock `lead.high_confidence`
- [ ] **[§4 T2 read]** — the `dedup_members` invariant is P10's, and no schema enforces it
- [ ] [34 §P9](34-implementation-plan.md) read — all thirteen fields
- [ ] [freeze §4.1](ARCHITECTURE_FREEZE.md) read — `0007` is `projects_and_knowledge_base`
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] The full suite recorded green before the first change — **1148 passed, 2 skipped**
- [ ] `git status` clean · `alembic heads` = one `0006` · `check_schema.py` 51/51
- [ ] `gh run list` checked: P8 green on `origin/main`
- [ ] A timestamped backup of `data/leads.db` before any `alembic upgrade` (**M7**)
