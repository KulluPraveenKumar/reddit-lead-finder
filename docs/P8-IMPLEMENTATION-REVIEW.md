# P8 IMPLEMENTATION REVIEW — Content & dedup schema

**Written:** 2026-08-11 · **Phase:** P8 (frozen numbering) · **Revision:** `0006_content_and_dedup` · **Days / Risk:** 2 · Low
**Status:** review only. **No production code has been written.**

> ⚠️ **P8 is a schema-only migration phase.** It is **not** `docs/18-phase-08.md` ("Quality
> Measurement, Dashboard, Export & Production Readiness"), which belongs to the **superseded
> eight-phase numbering** ([lock §2.1](EXECUTION_MODE_LOCK.md)). That document maps to **P25–P27 and
> P30**, and to migration `0010`. `docs/testing/phase-08-testing.md` is its companion and is likewise
> historical: **read-only, never extended.**
>
> Reading either as P8's specification would build Stage I seventeen phases early, author the wrong
> migration, and create five tables the freeze does not place in `0006`.

**P8's actual content**, per [freeze §4.1](ARCHITECTURE_FREEZE.md) and [34 §P8](34-implementation-plan.md):
`comments`, `dedup_groups`, `dedup_members`, `minhash_bands`; four new `leads` columns; and closure
of the `prescores.comment_id` foreign key deferred by `0005`.

---

## 0. Verdict up front

**P8 must not be implemented as currently documented.** One finding is blocking and it is not a
documentation nit — it is a defect that the phase's own acceptance criteria, the universal gate, and
`scripts/check_schema.py` would **all report as passing**.

| | Finding | Severity |
|---|---|---|
| **F1** | A `REFERENCES projects(id)` clause written at `0006` makes **every `INSERT` into `leads` fail** — and every gate stays green | 🔴 **BLOCKING** |
| **F2** | [05 §7](05-database-plan.md) self-declares "authoritative" and contradicts [freeze §4.1](ARCHITECTURE_FREEZE.md) on the number, name and content of every revision from `0005` onward | 🔴 **BLOCKING** |
| **F3** | `leads.source` is asserted by P8's acceptance criteria and defined **nowhere in the frozen schema** | 🟠 Must resolve |
| **F4** | `dedup_groups.project_id` / `minhash_bands.project_id` are `NOT NULL` in [05 §5.4b](05-database-plan.md) but must be nullable at `0006`; **P12 never tightens them** | 🟠 Must resolve |
| **F5** | [05 §7.1a](05-database-plan.md)'s ordering block for `content_and_dedup` is stale in three ways | 🟡 P8 owns the fix |
| **F6** | P8's acceptance criteria say "459 rows"; the live database holds **478** | 🟡 Wording |
| **F7** | `dedup_members`' stated invariant — *"at most one group per run"* — is not expressible in its schema | 🟡 Record |
| **F8** | **DI20 does not exist.** The register runs DI1–DI19 | ℹ️ Reported |

Nothing below is worked around. F1 and F2 are analysed as decisions in
[P8-DECISION-ANALYSIS.md](P8-DECISION-ANALYSIS.md).

---

## 1. Authority ranking

When two documents disagree, the higher row wins.

| # | Authority | Scope | Why it ranks here |
|---|---|---|---|
| **1** | [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) | §4 migration rules **M1–M10**; **§4.1 the frozen chain**; §11 amendments; §11.1 reconciliations | Self-declared binding constraint set. §4.1 is the **only** table that matches what has actually shipped |
| **2** | [EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md) | §2.1 the two numberings; §3 workflow; §4 discipline; §5 hygiene; §8 deferral conditions | Governs *how* the phase executes |
| **3** | [34 §P8](34-implementation-plan.md) + [34 §1.2](34-implementation-plan.md) | Objective, Deliverables, Files, DB, Depends on, 4 Tasks, Acceptance, Metrics, Rollback, Docs | "The definitive execution guide" |
| **4** | [35](35-testing-strategy.md) | The gate | The named testing gate |
| **5** | [PHASE-07-HANDOVER.md](PHASE-07-HANDOVER.md) | Entry conditions, traps, blockers | Execution record of the immediate predecessor |
| **6** | [05 §4.1, §5.4, §5.4b](05-database-plan.md) | **Column-level DDL only** | Design detail. Its **§7 sequence table is stale** (F2) and is *not* binding |
| **⛔** | `18-phase-08.md`, `testing/phase-08-testing.md`, `16-phase-06.md`, `17-phase-07.md` | — | **Superseded / historical** ([lock §2.1](EXECUTION_MODE_LOCK.md)) |

> **Note the split on doc 05.** Its *column definitions* (§4.1, §5.4, §5.4b) remain the schema
> reference and P8 implements them. Its *migration sequence* (§7, §7.1, §7.1a) predates the
> [31](31-execution-plan.md) reorder and is wrong. P8's **Docs** field already makes P8 the owner of
> repairing it — which is the correct disposition, not a workaround.

---

## 2. Blocking findings

### 2.1 🔴 F1 — A deferred FK is not a formality here; omitting it breaks the shipped pipeline

[05 §4.1](05-database-plan.md) and [05 §5.4](05-database-plan.md)/[§5.4b](05-database-plan.md)
specify these columns with inline `REFERENCES projects(id)`:

| Table | Column | Created at | `projects` exists at |
|---|---|---|---|
| `leads` | `project_id` | `0006` | `0007` |
| `comments` | `project_id` | `0006` | `0007` |
| `dedup_groups` | `project_id` | `0006` | `0007` |
| `minhash_bands` | `project_id` | `0006` | `0007` |

Under doc 05's **original** ordering this was safe: `projects` was `0005` and `content_and_dedup`
was `0007`. The [31](31-execution-plan.md) reorder **inverted them**, and no document was updated.

`src/db/database.py:52` sets **`PRAGMA foreign_keys=ON` on every connection.** Measured this session
on SQLite 3.45.3:

```
ADD COLUMN w/ dangling REFERENCES: OK          <- the migration succeeds
SELECT after:                      (1,)        <- reads still work
INSERT after dangling FK FAILED:   OperationalError: no such table: main.projects
INSERT comments (NULL fk):         OperationalError: no such table: main.projects
PRAGMA foreign_key_check:          []          <- reports CLEAN
```

**The `INSERT` fails even when `project_id` is `NULL`.** SQLite resolves the parent table at
statement-prepare time, not at constraint-check time, so there is no value that avoids it.

#### Why this is the finding, and not merely a bug

Line the failure up against everything that is supposed to catch it:

| Gate | What it does at `0006` | Result |
|---|---|---|
| [34 §1.2](34-implementation-plan.md) universal AC — `upgrade head → downgrade -1 → upgrade head` | Pure DDL. No `INSERT` | ✅ **passes** |
| P8's own AC — *"459 rows get `project_id=NULL` … no row rewritten"* | A `SELECT` assertion | ✅ **passes** |
| `scripts/check_schema.py` — 31 checks | Row counts, index and constraint introspection — all `SELECT` | ✅ **passes** |
| `PRAGMA foreign_key_check` | Returns `[]` | ✅ **passes** |
| `tests/test_migrations.py` (8 tests) | Schema dumps and round-trips; no insert at an intermediate revision | ✅ **passes** |

> **P8 as specified can ship a migration that breaks every lead insert in the shipped scraper, and
> every single gate reports green.** That is the blocking property: not the defect, but that nothing
> in the project can currently see it.

**Root cause:** [freeze M8](ARCHITECTURE_FREEZE.md) already mandates the correct pattern — *"Forward
references use a bare column plus a deferred FK added later by `batch_alter_table`."* The rule is
frozen and correct. The failure is that **[05 §7.1](05-database-plan.md)'s deferred-FK table lists
three columns and none of them is one of these four**, and [34 §P8](34-implementation-plan.md)'s DB
row mentions deferral only for *"dedup tables"* — omitting `leads` and `comments`, of which `leads`
is the one that breaks a shipped code path.

**The fix, verified this session end to end:**

```
0006: ALTER TABLE leads ADD COLUMN project_id INTEGER NULL      -- bare, no REFERENCES
      INSERT INTO leads ...                                      -> OK
      legacy row defaults: (None, None, 'not_analyzed', 'scrape') -> all correct
0007: batch_alter_table('leads').create_foreign_key(...)
      PRAGMA foreign_key_check                                   -> []
      INSERT INTO leads ...                                      -> OK
      INSERT ... project_id=999                                  -> FOREIGN KEY constraint failed
```

The constraint is genuinely enforced after closure. This is the same mechanism `0004` already used
for `ai_calls.run_id` (`migrations/versions/0004_orchestration.py:107`), so P8 introduces no new
technique — it applies an existing one to four more columns.

**What P8 must add:** a test that inserts a lead **at revision `0006`**. No such test exists at any
revision. See [checklist](P8-IMPLEMENTATION-CHECKLIST.md) Stage 1.

> ### ✅ Independently reproduced — 2026-08-11, a second session
>
> F1 is the finding the whole phase turns on, so it was **re-derived from scratch** rather than
> re-read. A throwaway in-memory database, `PRAGMA foreign_keys=ON`, SQLite **3.45.3**:
>
> ```
> --- 0006 as specified: ADD COLUMN with an inline dangling REFERENCES ---
>   ADD COLUMN                       : OK   <- the migration succeeds
>   SELECT after                     : [(1, 'legacy row')]
>   PRAGMA foreign_key_check         : []   <- reports CLEAN
>   INSERT (project_id NULL)         : FAILED  OperationalError: no such table: main.projects
>   INSERT (project_id explicit NULL): FAILED  OperationalError: no such table: main.projects
>
> --- the proposed fix: bare column at 0006, FK closed at 0007 ---
>   INSERT at 0006 (bare column)     : OK
>   legacy row project_id default    : (None,)
> ```
>
> **Every claim holds, including the uncomfortable one:** `PRAGMA foreign_key_check` returns `[]`
> against a database whose every `leads` insert is broken. The premise was checked too —
> `src/db/database.py:52` does set `PRAGMA foreign_keys=ON` per connection, with the comment *"Off by
> default in SQLite. Must be set per connection."*
>
> **F1 is confirmed BLOCKING on independent evidence.**

**Carried cost, which belongs to P12 and must be in P8's handover:** closing four FKs by
`batch_alter_table` in `0007` means four create-copy-drop-rename rebuilds, one of them over the
`leads` table (478 rows today). Analysed as [D1](P8-DECISION-ANALYSIS.md).

---

### 2.2 🔴 F2 — Two documents both claim authority over the migration chain, and they disagree completely

[05 §7](05-database-plan.md) opens with **"This table is authoritative."**
[freeze §4.1](ARCHITECTURE_FREEZE.md) is "The frozen chain", governed by M1–M10, amendable only by a
failed measurement.

| Rev | [05 §7](05-database-plan.md) says | [freeze §4.1](ARCHITECTURE_FREEZE.md) says | **Shipped reality** |
|---|---|---|---|
| `0004` | `orchestration` | `orchestration` | ✅ `0004_orchestration` |
| `0005` | `projects_and_knowledge_base` | `discovery` | ✅ **`0005_discovery`** |
| `0006` | `targeting` | **`content_and_dedup` (P8)** | — |
| `0007` | `content_and_dedup` | `projects_and_knowledge_base` | — |
| `0008` | `enrichment` | `targeting` | — |
| `0009` | `monitoring_and_quality` | `enrichment` | — |
| `0010` | *"No tenth revision."* (stated twice) | `monitoring_and_quality` (P25) | — |

**Doc 05 §7 is stale, and demonstrably so:** it predicts `0005 = projects_and_knowledge_base`, and
`0005_discovery` is applied to the live database right now. It also insists twice that there is no
tenth revision, while freeze M4 says *"Revisions `0004`–`0010`"* and §4.1 lists `0010`. Its
supporting prose is stale in the same direction:

- *"The three `leads` columns land in `0007` (Phase 6)"* — four columns, `0006`, P8.
- *"`0007` is the only one that touches `leads`; its downgrade drops the three added columns"* —
  wrong revision **and** wrong count.

**Resolution: freeze §4.1 wins.** It is the higher authority, it matches what has shipped, and
`migrations/versions/0005_discovery.py:13` already records the precedent in its own docstring —
*"The freeze (§4.1) is the authority."*

This is a **[§11.1](ARCHITECTURE_FREEZE.md) documentation reconciliation, not an amendment**: no
technology, table or decision changes; one document transcribed a pre-reorder sequence. P8's **Docs**
field (*"[05](05-database-plan.md) §7 + §7.1a ordering"*) already assigns the repair to P8. See
[D2](P8-DECISION-ANALYSIS.md).

> ⚠️ P8 must **not** edit `05-database-plan.md` or the freeze during this review. Those edits are
> P8's implementation deliverables ([lock §3](EXECUTION_MODE_LOCK.md) step 11), executed after
> approval.

---

## 3. Non-blocking findings

### 3.1 🟠 F3 — `leads.source` is asserted but not defined in the frozen schema

P8's acceptance criteria state, in bold: *"459 rows get … `source='scrape'`."*
[freeze §4.1](ARCHITECTURE_FREEZE.md) says *"`leads` +4"*.

But [05 §4.1](05-database-plan.md) — the frozen schema's `leads` section — defines **three** columns
and four indexes, and never mentions `source`. It is specified only in:

| Where | What it says | Status |
|---|---|---|
| [16 §115](16-phase-06.md) | `ALTER TABLE leads ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'scrape';` | ⛔ **superseded numbering** |
| [06i §97, §321](06i-feedback-and-memory.md) | `scrape \| holdout_audit`; assigns it to old-`0007` | Design doc |
| [06c §327](06c-local-first-pipeline.md) | Holdout-audited items persist as `source='holdout_audit'` | Design doc; the *consumer*, in P11 |

So the column is real and its purpose is well-motivated ([R27](10-implementation-roadmap.md), the
degenerate-learning-loop fix), but **the only DDL for it lives in a read-only historical document.**

**Resolution:** adopt the [16 §115](16-phase-06.md) DDL verbatim into [05 §4.1](05-database-plan.md)
as part of P8's Docs deliverable. No new column, no new capability — a definition is being moved from
a superseded document into the frozen one that should always have carried it. See
[D3](P8-DECISION-ANALYSIS.md).

**No index on `source`.** [05 §4.1](05-database-plan.md) specifies four indexes for the *other* three
columns; [05 §7.1a](05-database-plan.md) says "3 columns + 4 indexes". P8 ships **4 columns and 4
indexes**. Stated explicitly so implementation does not invent a fifth.

---

### 3.2 🟠 F4 — Two `NOT NULL`s that cannot hold at `0006`, and that nothing later fixes

[05 §5.4b](05-database-plan.md):

```sql
CREATE TABLE dedup_groups  ( ... project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, ... );
CREATE TABLE minhash_bands ( ... project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, ... );
```

[34 §P8](34-implementation-plan.md) requires the opposite: *"`project_id` **nullable** on dedup tables
(FK deferred to `0007`)."* Both cannot hold, and `NOT NULL` is impossible at `0006` because there is
no `projects` row for any value to reference.

The deeper gap is at the other end. [34 §P12](34-implementation-plan.md) lists its FK closures as
*"`ai_calls.project_id`, `runs.project_id` (+ `NOT NULL`), `dedup_groups.project_id`,
`minhash_bands.project_id`"*. It **explicitly** tightens `runs.project_id` and **explicitly does not**
tighten the other two. So on the documents as written, the two columns are nullable at `0006` and
stay nullable forever — silently contradicting [05 §5.4b](05-database-plan.md).

**This is P12's decision, not P8's**, and P8 must not pre-empt it. P8's obligation is to create them
nullable and bare, and to **name the open question in the handover** so P12 decides deliberately
rather than inheriting an accident. See [D4](P8-DECISION-ANALYSIS.md).

---

### 3.3 🟡 F5 — The intra-revision ordering block is stale in three ways

[05 §7.1a](05-database-plan.md) is the only place that specifies statement order inside this
revision, and it is correct in spirit — *"table creation order within a single revision is a real
constraint, not a formality"* — but wrong in detail:

```
0007_content_and_dedup:                 <- (1) wrong revision number; it is 0006
  1. ALTER leads (3 columns + 4 indexes) <- (2) four columns, not three
  ...
  6. CREATE prescores                    <- (3) prescores SHIPPED IN 0005
```

`prescores` was moved into `0005` by [33 §2.4](33-final-review.md) and recorded there in
[freeze §4.1](ARCHITECTURE_FREEZE.md); `migrations/versions/0005_discovery.py:89` creates it. Step 6
therefore describes a `CREATE TABLE` that would fail with *"table prescores already exists"*.

Worse, the block **omits** the one operation `0006` genuinely owes `prescores`: closing the
`comment_id` FK that `0005` deliberately left bare
(`0005_discovery.py:16-19`; [freeze §11.1](ARCHITECTURE_FREEZE.md), 2026-08-08). That closure is
[34 §P8](34-implementation-plan.md) task 4 and is missing from doc 05 entirely.

**Corrected order** — P8's Docs deliverable, and the order the checklist implements:

```
0006_content_and_dedup:
  1. ALTER leads  +4 bare columns, +4 indexes     (project_id BARE — F1)
  2. CREATE comments                              (project_id BARE — F1)
  3. CREATE dedup_groups        -> leads, comments (project_id BARE, NULLABLE — F1/F4)
  4. CREATE dedup_members       -> dedup_groups, leads, comments
  5. CREATE minhash_bands       -> leads, comments (project_id BARE, NULLABLE — F1/F4)
  6. batch_alter_table('prescores'): close comment_id -> comments
downgrade(): exact reverse
```

---

### 3.4 🟡 F6 — "459 rows" is no longer the row count

P8's AC says *"**459 rows** get `project_id=NULL` …"*. Measured this session:

```
INFO  leads = 478 (459 baseline + 19 collected since)
PASS  the 459 original leads are all still present
```

The `ALTER` touches **478** rows. The 459 figure is the *legacy-contract* guarantee (those rows
present, `intent_score` fingerprint unchanged) and remains exactly right for that purpose — but as a
statement about what the migration affects it is stale, and a tester told to expect 459 will
correctly report a mismatch. The checklist and manual guide both use 478/459 with the distinction
spelled out.

---

### 3.5 🟡 F7 — `dedup_members`' stated invariant is not expressible in its schema

[05 §5.4b](05-database-plan.md) comments: *"A lead or comment belongs to at most one group **per
run**."* The enforcement shipped alongside it is:

```sql
CREATE UNIQUE INDEX ux_dedup_members_lead ON dedup_members (group_id, lead_id) WHERE lead_id IS NOT NULL;
```

That constrains *"at most once **within a group**"*, which is a different and much weaker statement.
`dedup_members` has **no `run_id` column**; the run is reachable only through `dedup_groups.run_id`,
and SQLite cannot express a uniqueness constraint across a join. Two `dedup_groups` rows from the same
run can each claim the same `lead_id` and both indexes stay satisfied.

**P8 should not fix this.** Adding `run_id` to `dedup_members` is a table the freeze does not
describe, for an invariant whose only writer is **P10**'s cascade. The honest disposition is: create
the table exactly as [05 §5.4b](05-database-plan.md) specifies, and record that the invariant is an
**application-level guarantee P10 must uphold and test**, not a schema-level one. Recorded as a
[DEFERRED-IMPROVEMENTS](DEFERRED-IMPROVEMENTS.md) candidate with P10 as its trigger, and named in the
handover.

---

### 3.6 ℹ️ F8 — DI20 does not exist

The review brief asks for attention to **DI20**. [DEFERRED-IMPROVEMENTS §1](DEFERRED-IMPROVEMENTS.md)
contains DI1–DI19 (tabled out of numeric order, with DI11 last). There is no DI20, in §1, §2 or §3.

Reported rather than guessed at. If an item was intended, it needs to be named before it can be
classified. DI17 and DI18 are real and classified in §7 below.

> **Resolved 2026-08-11 — the gap is now deliberate and documented.** The intended item was
> [PHASE-07-HANDOVER §8](PHASE-07-HANDOVER.md)'s *"**DI20** *(proposed)* —
> `test_does_not_write_to_the_database_it_checks`, WAL/mtime race"*, which was **proposed in the
> handover but never registered**, because it failed once and passed on re-run with identical code.
> That is why the register skipped it rather than contained it.
>
> **DI20 remains reserved for that item, and the register now says so in a note.** The register has
> since gained **DI21** (the late-drained `gate.reached` title — see the P7 live-verification work),
> so it now reads DI1–DI19 **and DI21**, with DI20 held open on purpose so the handover's reference
> does not silently retarget.
>
> **The WAL/mtime race is still real and still unregistered.** It fired again during P8's pre-flight
> — full suite, pristine config: `1 failed, 1130 passed, 2 skipped`, then `4 passed` on an immediate
> re-run of the same test with no code change. **That is now a third occurrence.** P8 should either
> register it properly as DI20 or fix it, rather than continue to describe it as *proposed*. It is
> listed in [the checklist](P8-IMPLEMENTATION-CHECKLIST.md) Stage 0 as a known re-run.

---

## 4. Dependency and predecessor verification

### 4.1 Phase dependencies

[34 §P8](34-implementation-plan.md) **Depends on: P6.** P6 and P7 are both complete and pushed, so
the stated dependency is satisfied with one phase to spare.

Unlike [P7's C1](P7-IMPLEMENTATION-REVIEW.md), **P8 depends on no Sprint-0 measurement.** Nothing in
this phase is contingent on an unmeasured value; it is DDL against a known schema. This is the
lowest-dependency phase since P1.

### 4.2 What P8 inherits from `0005`

| Inherited | Where | P8's obligation |
|---|---|---|
| `prescores.comment_id` left bare, FK deferred | `0005_discovery.py:16-19` | **Close it** — task 4 |
| `prescores` includes `stage`, created not altered | [freeze §11.1](ARCHITECTURE_FREEZE.md) 2026-08-08 | Do not re-create |
| `CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))` | `0005_discovery.py:107` | Unaffected by the FK closure — `batch_alter_table` must **preserve** it |
| Stage-3 funnel is `run_events` counters, no `prescores` rows | [freeze §11.1](ARCHITECTURE_FREEZE.md) 2026-08-08 | P8 writes no rows at all |

> ⚠️ **A `batch_alter_table` rebuild reconstructs the table from SQLAlchemy's reflection of it.**
> Named `CHECK` constraints are a known weak spot for reflection round-trips. Stage 1 of the
> checklist asserts `ck_prescores_one_target` still exists **after** the rebuild — it is not assumed.

### 4.3 Baseline — measured 2026-08-11, this session, on `main` @ `127da1c`

| Fact | Value |
|---|---|
| Working tree | clean |
| `HEAD` vs `origin/main` | identical (`127da1c`) |
| Latest CI run | **success** (`127da1c`, workflow `CI`) |
| `alembic heads` | `0005_discovery` — **one head** |
| Live DB revision | `0005_discovery` |
| `scripts/check_schema.py` | **OK — all 31 checks passed** |
| Tests collected | **1133** |
| `leads` rows | **478** (459 original + 19 collected) |
| Untracked / temporary files | none |

---

## 5. Acceptance criteria

### 5.1 P8-specific — [34 §P8](34-implementation-plan.md), as reconciled above

| # | Criterion | Reconciliation applied |
|---|---|---|
| **A1** | `upgrade → downgrade -1 → upgrade` on a **copy** of the live DB | — |
| **A2** | All **478** rows get `project_id=NULL`, `confidence_score=NULL`, `analysis_status='not_analyzed'`, `source='scrape'`; the **459** original rows and their `intent_score` fingerprint are unchanged | F6 |
| **A3** | No row rewritten | Holds at `0006` — all four `ALTER`s are metadata-only. **Does not hold at `0007`** (D1) |
| **A4** | One head | — |
| **A5** | `intent_score` fingerprint unchanged | — |
| **A6** | `ALTER` completes in < 1 s | ⚠️ wall-clock — see DI18, §7 |
| **A7 (new)** | **At revision `0006`, a lead can be inserted** | **F1 — added by this review** |
| **A8 (new)** | **At revision `0006`, a comment can be inserted** | **F1** |
| **A9 (new)** | `ck_prescores_one_target` survives the `prescores` rebuild | §4.2 |

A7 and A8 are additions. [lock §8](EXECUTION_MODE_LOCK.md) permits them: they relate directly to P8,
add no scope, redesign nothing, and cost minutes.

### 5.2 Universal — [34 §1.2](34-implementation-plan.md)

`ruff check` · `ruff format --check` · `pytest` offline · coverage ≥70% on new modules · **four grep
fences** · up/down/up on a live-DB copy · legacy contract (459 leads, fingerprint, `GET /`, 13 CSV
columns, 17 endpoints) · manual guide generated **and executed** · Docs landed.

> **Coverage is close to vacuous for P8.** The phase's only new code is a migration and four
> declarative model classes; migrations are not imported by the coverage run. The meaningful measure
> is the migration test set, not a percentage. Stated so a green coverage number is not mistaken for
> evidence.

---

## 6. Boundary verification

### 6.1 The four fences

| Fence | Enforced by | P8's exposure |
|---|---|---|
| R2 — no vendor coupling outside `providers/` | `test_no_vendor_coupling_outside_providers` | none |
| R3 — no `src.ai` in `rules`/`dedupe`/`scoring`/`knowledge` | `test_discovery_makes_no_ai_calls` + friends | none — **those packages do not exist yet** (P9/P10/P11) |
| R4 — notify imports no model | `test_notify_imports_no_model` | none |
| R5 — no `hermes` import in `src/` | `test_the_platform_never_imports_hermes` | none |

**P8 crosses no fence.** It adds no package, no import and no runtime code path. The honest statement
is that the fences are *unexercised* by this phase, not that they were *verified against* it.

### 6.2 The boundary P8 actually has

P8's boundary is **temporal, not modular**: *what may reference `projects` before `projects` exists.*
That is exactly what F1 is about, and it currently has **zero** enforcement. The new A7/A8 tests are
the first guard of this class in the repository.

Recommended, and specified in the checklist: a test that walks **every** revision from `0001` to
`head` and asserts that no table has a `REFERENCES` target which does not exist at that revision —
read straight from `PRAGMA foreign_key_list`, needing no fixture rows. That generalises A7/A8 into a
standing guard so **P12, P17, P19 and P25 cannot reintroduce the same class of defect** — each of
them also creates forward-referencing columns. See [D5](P8-DECISION-ANALYSIS.md).

---

## 7. Technical-debt review

Classified against [lock §8](EXECUTION_MODE_LOCK.md)'s four conditions — *relates to this phase ·
does not expand scope · does not redesign architecture · does not delay delivery.* An item must meet
**all four** to be done inside P8.

| # | Item | Classification | Reasoning |
|---|---|---|---|
| **DI17** | No periodic driver; nothing enqueues `handle_maintenance` | **2 — Safe to defer** | P8 enqueues nothing and runs no job. Trigger is *"the first phase that needs periodic background work"*; that is [34 §P17](34-implementation-plan.md)'s due-queue scheduler. Untouched by P8 |
| **DI18** | `test_parse_speed_stays_inside_the_budget` is a wall-clock assertion, fails under load | **2 — Safe to defer, but P8 must not repeat it** | Its trigger (*"fails in CI, or a third local occurrence"*) has **not** fired: CI is green on `127da1c`. **However**, P8's own **A6** (*"`ALTER` completes in < 1 s"*) is the same species. See recommendation R4 |
| **DI20** | — | **Does not exist** | F8 |
| Retry implementation | P7's transport retry budget; a failure past it is delivered on the next drain or not at all (DI17) | **4 — Future phase** | Notification-tier behaviour. P8 sends nothing |
| Unsigned sign-off tables | **O3** — P00/P01 manual sign-off unsigned | **1 — MUST BLOCK, but as a standing gate, not P8 work** | [lock §4](EXECUTION_MODE_LOCK.md) makes human sign-off a completion condition; [freeze §6.2](EXECUTION_MODE_LOCK.md) forbids tagging an unsigned phase. This is ~20 min of operator time and **no engineering**. It blocks *claiming* P8 complete, not *starting* it |
| `mypy` gate | **O2** — required by [35 §2](35-testing-strategy.md) check 3 and [freeze §5](ARCHITECTURE_FREEZE.md); not installed | **1 — Must block (cheaply)** | The gate cannot be *claimed in full* while a named check has never run. P8 is the **best possible phase to close it**: the phase adds ~4 model classes and one migration, so the first baseline error count is as small and as reviewable as it will ever be. Deferring past P8 means baselining against P9–P11's rule/dedup/scoring code instead. See recommendation R1 |
| Track-B items | M-1…M-12, V-1 — blocked on absent credentials | **2 — Safe to defer** | P0 recorded *"Track B is not needed until P23."* P8 makes no AI, network or agent call. **P8 is the phase least affected by Track B of any remaining phase** |
| **DI15** | Eighth job type `discover` shipped unreconciled | **3 — Documentation only; not triggered** | DI15 names *"most likely **P8** or P11"* as its trigger. **It does not fire: P8 adds no job type**, registers no handler, and touches no job registry. Reported explicitly because P8 was named as a candidate |
| **DI13 / DI14** | `num_comments = 0` vs `None`; permalink host split 444/27 | **4 — Future phase** | DI13's trigger is P11; DI14's is *"P10's dedup cascade is the first place that bites"*. **DI14 is one phase away** and P8 creates the tables it will bite in — named in the handover |
| **DI11** | `check_schema.py` crashes at revision `0003` | **2 — Safe to defer** | Trigger is *"a phase whose rollback **is** a downgrade needs the verifier to work at the earlier revision."* ⚠️ **P8's rollback *is* `alembic downgrade 0005`** — but the crash is at `0003`, and P8 downgrades to `0005`, where all 31 checks pass. Verified this session. **Close to firing; does not fire** |
| **DI6** | Handover says `0003`, DB was at `0004` | **3 — Documentation only** | Superseded by events; DB is at `0005` |
| **DI4 / DI7 / DI10** | `ruff format` legacy modules; R20 wording; Python 3.11 vs 3.12 | **3 — Documentation only** | None triggered by P8 |

**Nothing is moved between phases.** DI15 and DI11 were both candidates to fire in P8 and both were
checked against their own stated triggers rather than against convenience; neither fires.

---

## 8. Assumptions this review makes explicit

| # | Assumption | Basis | If wrong |
|---|---|---|---|
| **A-1** | freeze §4.1 outranks 05 §7 | [lock §2.1](EXECUTION_MODE_LOCK.md); `0005_discovery.py:13` precedent; §4.1 matches shipped reality | The whole numbering section is wrong. **Operator confirmation requested** ([D2](P8-DECISION-ANALYSIS.md)) |
| **A-2** | `leads.source` is `VARCHAR(20) NOT NULL DEFAULT 'scrape'`, values `scrape\|holdout_audit` | [16 §115](16-phase-06.md); [06i §97](06i-feedback-and-memory.md) | The column ships with a wrong type or domain |
| **A-3** | Deferring four FKs to `0007` is within M8 and needs no amendment | M8 states the pattern; `0004` set the precedent | It becomes a §11 amendment, needing a failed measurement |
| **A-4** | `batch_alter_table` preserves `ck_prescores_one_target` | Alembic reflects and re-emits CHECKs | Asserted, not assumed — A9 |
| **A-5** | The live DB copy used for A1 is a **copy** | [lock §3](EXECUTION_MODE_LOCK.md) step 3; M7, M9 | Data loss on the live database |
| **A-6** | P8 writes no rows to any new table | [34 §P8](34-implementation-plan.md) — schema only | Scope expansion into P9–P11 |

---

## 9. Risk assessment

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| **X1** | The dangling-FK defect ships because every gate is blind to it | **High if unfixed** | **Critical** | A7/A8, plus the all-revisions insert guard (§6.2) |
| **X2** | `batch_alter_table` on `prescores` silently drops the CHECK | Low | High | A9 asserts it explicitly |
| **X3** | Implementation follows `18-phase-08.md` | Low | **Critical** | The banner at the top of this document; [lock §2.1](EXECUTION_MODE_LOCK.md) |
| **X4** | Doc 05 §7 is edited to match, but §5.4b's `NOT NULL`s are left | Medium | Medium | F4 is a named Docs deliverable, not a side effect |
| **X5** | A6's wall-clock budget fails under machine load | Medium | Low | DI18's species; R4 makes it load-tolerant by construction |
| **X6** | Downgrade leaves an orphaned index | Low | Medium | Downgrade is exact-reverse and round-tripped on a live copy |
| **X7** | The 19 leads collected since P6 behave differently from the 459 | Low | Medium | A2 asserts defaults over all 478, not a sample |

---

## 10. Scope — what P8 does **not** do

Named because each is plausibly adjacent and all are out of scope:

- **No rule engine, no dedup cascade, no pre-scoring.** P9, P10, P11. P8 creates tables that stay
  **empty**.
- **No `projects` table, and no FK closure.** P12.
- **No `gate_audits`.** [05 §5.4b](05-database-plan.md) lists it beside the dedup tables, but
  [freeze §4.1](ARCHITECTURE_FREEZE.md) places it in **`0009_enrichment`** (P19). Adjacency in a
  design document is not membership in a revision.
- **No `comment_scraper.py`, no `repositories/comments.py`.** P11.
- **No notification kind for `leads.confidence_score`.** DI16 — the column exists at `0006`, but it
  is not *populated* until P21, and the trigger requires both.
- **No fix to DI13, DI14, DI15, DI17, DI18.** §7.
- **No edit to `05-database-plan.md` before approval.** A Docs deliverable of the implementation.

---

## 11. Verdict

**P8 is well-scoped, genuinely low-risk, and correctly placed — and it must not begin until F1 and
F2 are resolved.**

The phase itself is two days of declarative DDL with no runtime behaviour, no AI call, no network
call and no new package. That is as safe as a phase gets. The danger is entirely in the documents:
one of them ships a pipeline-breaking FK, and another disagrees with the freeze about which revision
this even is.

Both are resolvable **without an amendment**. F1 is an application of frozen rule M8 that two
documents failed to enumerate. F2 is a §11.1 reconciliation of a table that predates the reorder,
and P8's own Docs field already owns it.

**Required before implementation begins:**

1. Operator confirmation on [D1](P8-DECISION-ANALYSIS.md) — deferred FK vs permanently bare.
2. Operator confirmation on [D2](P8-DECISION-ANALYSIS.md) — freeze §4.1 wins; P8 executes the §11.1
   reconciliation.
3. A decision on [O2 `mypy`](DEFERRED-IMPROVEMENTS.md) — recommendation R1.
4. Acknowledgement that **DI20 does not exist** (F8).

The remaining findings (F3–F7) are resolved by the recommendations in
[P8-DECISION-ANALYSIS.md](P8-DECISION-ANALYSIS.md) and executed by
[P8-IMPLEMENTATION-CHECKLIST.md](P8-IMPLEMENTATION-CHECKLIST.md); none of them blocks a start once
D1 and D2 are settled.
