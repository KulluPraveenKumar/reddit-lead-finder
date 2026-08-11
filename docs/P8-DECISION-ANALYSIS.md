# P8 DECISION ANALYSIS — Content & dedup schema

**Written:** 2026-08-11 · **Companion to** [P8-IMPLEMENTATION-REVIEW.md](P8-IMPLEMENTATION-REVIEW.md)
**Status:** decisions proposed, **not executed.** No production code, no document edits.

Seven decisions. **D1 and D2 are blocking** — implementation cannot start correctly until the
operator settles them. D3–D5 have clear recommendations that need only assent. D6 and D7 are
recorded so they are made deliberately rather than by default.

| # | Decision | Status |
|---|---|---|
| [D1](#d1) | Deferred FK, or permanently bare `project_id` | 🔴 **BLOCKING** |
| [D2](#d2) | Which document governs the migration chain | 🔴 **BLOCKING** |
| [D3](#d3) | Where `leads.source` is defined | 🟠 Needs assent |
| [D4](#d4) | The two `NOT NULL`s on the dedup tables | 🟠 Needs assent |
| [D5](#d5) | How the F1 class of defect is prevented in future phases | 🟠 Needs assent |
| [D6](#d6) | Whether P8 closes the `mypy` gate (O2) | 🟡 Recommendation |
| [D7](#d7) | The unspecified details | 🟡 Recorded |

---

<a id="d1"></a>
## D1 — Four columns reference `projects`, which does not exist until `0007`

### 🔴 BLOCKING

Established in [review F1](P8-IMPLEMENTATION-REVIEW.md). `leads.project_id`, `comments.project_id`,
`dedup_groups.project_id` and `minhash_bands.project_id` are all specified in
[05](05-database-plan.md) with inline `REFERENCES projects(id)`. Under the pre-[31](31-execution-plan.md)
ordering `projects` came first; after the reorder it comes second, and no document was updated.

**Measured, this session, SQLite 3.45.3, with `PRAGMA foreign_keys=ON` as
`src/db/database.py:52` sets on every connection:**

```
ALTER TABLE leads ADD COLUMN project_id INTEGER NULL REFERENCES projects(id)  -> succeeds
SELECT ... FROM leads                                                          -> succeeds
INSERT INTO leads (title) VALUES ('after')  -> OperationalError: no such table: main.projects
PRAGMA foreign_key_check                                                       -> []   (clean)
```

The insert fails **with `project_id` unset**. There is no value that avoids it, because SQLite
resolves the parent table when the statement is prepared.

**The decision is forced in one direction and free in another.** It is forced that `0006` must not
emit a `REFERENCES` clause. It is free whether the constraint is ever added.

### What is actually at stake

Not correctness at `0006` — both options are correct there. The stake is **what `0007` costs**, and
whether the database ever enforces project ownership at all.

`batch_alter_table` is not an `ALTER`. SQLite cannot `ADD CONSTRAINT`, so Alembic performs
create-copy-drop-rename: a new table, a full row copy, a drop, a rename. Closing four FKs in `0007`
means four rebuilds, one of them over `leads` — **478 rows today, and every row P9–P11 adds between
now and then.**

That collides with [freeze M5](ARCHITECTURE_FREEZE.md): *"Additive only. No existing column is
dropped, renamed or retyped. **No migration rewrites a row.**"*

> **Precedent settles the M5 question.** `0004_orchestration.py:100-108` already ran
> `batch_alter_table` on `scrape_runs` (10 rows) and `ai_calls`, and shipped as M5-compliant. A
> rebuild **preserves every value**; M5 prohibits *changing* rows, not copying them through a
> rebuild. Recorded here because "no row rewritten" is P8's own acceptance criterion and a reader
> will otherwise hit this at `0007`.

### Options

| | Option | `0006` | `0007` | DB enforces ownership? |
|---|---|---|---|---|
| **A** | **Bare at `0006`, FK closed in `0007` by `batch_alter_table`** | 4 bare columns; metadata-only; no rebuild | 4 rebuilds, incl. `leads` | ✅ Yes, from `0007` |
| **B** | **Bare permanently; enforce in application code** | identical to A | nothing | ❌ No — ever |
| **C** | Reorder the chain so `projects` precedes `content_and_dedup` | — | — | ✅ Yes |
| **D** | Create a stub `projects` table in `0006` | — | — | ✅ Yes |

**C is not available.** [freeze M2](ARCHITECTURE_FREEZE.md): *"No revision inserted out of sequence
once shipped."* `0005` is applied to the live database. Reordering also re-opens the
[31](31-execution-plan.md) sprint ordering, which exists to put real data in the pipeline early — a
redesign, requiring a failed measurement, and there is none.

**D is not available.** [freeze §12](ARCHITECTURE_FREEZE.md): *"No phase may introduce a … table …
that is not named in this document."* A stub `projects` in `0006` is a table `0006` does not own, and
it would make `0007`'s real `CREATE TABLE projects` fail.

So the live choice is **A or B**.

### ✅ Recommendation — **Option A**

**Four reasons, in order:**

1. **M8 already decided it.** *"Forward references use a bare column plus a deferred FK added later
   by `batch_alter_table`."* This is a frozen rule that describes Option A exactly. Option B is a
   silent departure from a frozen rule — which needs an amendment, which needs a failed measurement,
   and there is none. **A requires no amendment; B does.**

2. **[05 §4.1](05-database-plan.md) specifies `ON DELETE SET NULL` on `leads.project_id` and
   `ON DELETE CASCADE` on the dedup tables.** Those are *database* behaviours. Under B they do not
   exist, and deleting a project would silently orphan every dedup group and leave stale
   `project_id`s on leads. Re-implementing cascade semantics in application code is strictly more
   code and strictly less reliable.

3. **The precedent is exact.** `ai_calls.run_id` was created bare in `0002` and closed in `0004`,
   and that path is shipped, tested and green. P8 adds four instances of a pattern the repository
   already runs.

4. **The rebuild cost is real but bounded and paid once.** 478 rows is a sub-second copy. Measured
   end to end this session:

   ```
   0006 bare-column INSERT: OK -> 2 rows
   0006 legacy row defaults: (None, None, 'not_analyzed', 'scrape')
   0007 fk_check: []
   0007 INSERT after FK closed: OK -> 3 rows
   0007 FK now enforced: FOREIGN KEY constraint failed
   ```

**What Option A obliges, and must not be left implicit:**

- `0006` emits **no `REFERENCES` clause** on those four columns. The `leads` `ALTER`s stay
  metadata-only and P8's "no row rewritten" AC holds **at `0006`**.
- **P8's handover must tell P12 it inherits four rebuilds**, one over `leads`, and that M7's backup
  precedes them. This is the single most important line in the handover.
- P8's Docs deliverable adds all four rows to [05 §7.1](05-database-plan.md)'s deferred-FK table,
  which currently lists three and none of these.

**Why not B, stated fairly:** B is genuinely simpler and avoids the rebuild entirely. If the operator
judges that project ownership will always be enforced by the service layer and that no `ON DELETE`
behaviour is wanted, B is coherent. But it must then be recorded as a **[§11](ARCHITECTURE_FREEZE.md)
amendment against M8**, and [05 §4.1](05-database-plan.md)/[§5.4b](05-database-plan.md) must have
their `REFERENCES` and `ON DELETE` clauses struck. **Do not take B by drift.**

---

<a id="d2"></a>
## D2 — Two documents claim authority over the migration chain

### 🔴 BLOCKING

[05 §7](05-database-plan.md) says **"This table is authoritative"** and places
`content_and_dedup` at `0007`. [freeze §4.1](ARCHITECTURE_FREEZE.md) — "The frozen chain" — places it
at **`0006`, P8**. They disagree on the number, name and content of every revision from `0005` on,
and doc 05 states twice that no tenth revision exists while the freeze lists one.

This is not academic: it determines the **filename P8 creates** and the `down_revision` it declares.
Getting it wrong produces a second head and breaks `upgrade head` — [freeze M1](ARCHITECTURE_FREEZE.md).

### The tie-breakers

| Test | Result |
|---|---|
| Which matches what has **shipped**? | freeze. `0005_discovery` is applied to the live DB; doc 05 §7 predicts `0005 = projects_and_knowledge_base` |
| Which is higher in the authority ranking? | freeze — self-declared binding, amendable only by failed measurement ([review §1](P8-IMPLEMENTATION-REVIEW.md)) |
| Is there a precedent? | **Yes.** `migrations/versions/0005_discovery.py:13`: *"The freeze (§4.1) is the authority and it says 0005 creates `prescores`… Recorded as a §11.1 reconciliation"* |
| Which reflects the [31](31-execution-plan.md) reorder? | freeze. Doc 05 §7 predates it |
| Does resolving it change any technology, table or decision? | **No.** Identical tables, identical columns, different ordinal |

### ✅ Recommendation — **freeze §4.1 wins; P8 executes a §11.1 reconciliation**

P8 creates `migrations/versions/0006_content_and_dedup.py` with
`down_revision = "0005_discovery"`.

**This is a [§11.1 documentation reconciliation, not a §11 amendment.** No technology, table or
decision changes; one document transcribed a pre-reorder sequence. That is precisely the category
§11.1 exists for, and P6 already used it for the same document
([freeze §11.1](ARCHITECTURE_FREEZE.md), 2026-08-08).

**The edits P8 owns** — its Docs field already says *"[05](05-database-plan.md) §7 + §7.1a ordering"*:

| Target | Change |
|---|---|
| [05 §7](05-database-plan.md) table | Renumber `0005`–`0009` to match freeze §4.1; add `0010` |
| [05 §7](05-database-plan.md) prose | Strike *"No tenth revision"* (twice); correct *"the three `leads` columns land in `0007` (Phase 6)"* → four columns, `0006`, P8; correct *"`0007` is the only one that touches `leads`… drops the three added columns"* |
| [05 §7.1](05-database-plan.md) | Add the four deferred FKs from [D1](#d1). It currently lists three, none of them these |
| [05 §7.1a](05-database-plan.md) | Retitle `0007_content_and_dedup` → `0006`; "3 columns" → 4; **delete step 6 `CREATE prescores`** (shipped in `0005`); **add** the `prescores.comment_id` FK closure |
| [05 §4.1](05-database-plan.md) | [D3](#d3) |
| [05 §5.4b](05-database-plan.md) | [D4](#d4) |
| [freeze §11.1](ARCHITECTURE_FREEZE.md) | One new row recording this reconciliation, dated, attributed to **P8** |

> ⚠️ **None of these edits happens during this review.** They are implementation deliverables
> executed at [lock §3](EXECUTION_MODE_LOCK.md) step 11, after approval. The review's job was to find
> them.

**A narrower alternative** — leave doc 05 §7 alone and rely on the freeze — is **rejected**. The
repository has already been bitten twice by frozen documents disagreeing
([lock §1](EXECUTION_MODE_LOCK.md)), and a table that says "This table is authoritative" while being
wrong is the most dangerous possible form of stale documentation. P12 reads this table next.

---

<a id="d3"></a>
## D3 — `leads.source` is asserted by P8's acceptance criteria and defined nowhere frozen

### 🟠 Needs assent

[34 §P8](34-implementation-plan.md) requires `source='scrape'` on every existing row.
[freeze §4.1](ARCHITECTURE_FREEZE.md) says *"`leads` +4"*. [05 §4.1](05-database-plan.md) — the
frozen schema's `leads` section — defines **three** columns and never mentions `source`.

The DDL exists only in [16 §115](16-phase-06.md), a **superseded, read-only** document, and the
semantics only in [06i](06i-feedback-and-memory.md) and [06c](06c-local-first-pipeline.md).

The column is well-motivated: it is the fix for **[R27](10-implementation-roadmap.md)**, the
degenerate-learning-loop risk — holdout-audited items must become real, labellable leads, or the
yield curve is fitted only on the gate's own admissions and recall collapses invisibly.

### Options

| | Option | Assessment |
|---|---|---|
| **A** | Adopt [16 §115](16-phase-06.md)'s DDL into [05 §4.1](05-database-plan.md) | Definition moves from a superseded doc into the frozen one |
| **B** | Ship `source` with no frozen definition | Leaves the next reader with an undefined column and a bold AC referencing it |
| **C** | Drop `source` from `0006` | Contradicts freeze §4.1 ("+4") **and** 34 §P8's AC. Would need an amendment |
| **D** | Invent a definition | Prohibited — [lock §2](EXECUTION_MODE_LOCK.md) |

### ✅ Recommendation — **Option A**

```sql
ALTER TABLE leads ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'scrape';
```

Domain `scrape | holdout_audit` ([06i §97](06i-feedback-and-memory.md)). Verbatim from
[16 §115](16-phase-06.md), which also already states the exact default-backfill semantics P8's AC
asserts: *"`source = 'scrape'` — all of which are semantically correct. No row is rewritten."*

**No new column, no new capability** — a definition is being moved into the document that should
always have carried it. Recorded in the same [§11.1](ARCHITECTURE_FREEZE.md) row as [D2](#d2).

**Two details, so implementation does not improvise:**

- **No index on `source`.** [05 §4.1](05-database-plan.md) specifies four indexes for the other three
  columns; [05 §7.1a](05-database-plan.md) says "4 indexes". P8 ships **4 columns, 4 indexes**. The
  only consumer is P11's holdout, which reads by run, not by source.
- **No `CHECK` on the domain.** [05](05-database-plan.md) uses bare `VARCHAR` for every other
  enumerated column (`analysis_status`, `gate_decision`, `method`). Adding a `CHECK` here alone would
  be an inconsistency, and P8 must match the surrounding idiom
  ([lock §7](EXECUTION_MODE_LOCK.md) priority 3).

---

<a id="d4"></a>
## D4 — `dedup_groups.project_id` and `minhash_bands.project_id` are `NOT NULL`, and cannot be

### 🟠 Needs assent

[05 §5.4b](05-database-plan.md) declares both `NOT NULL REFERENCES projects(id) ON DELETE CASCADE`.
[34 §P8](34-implementation-plan.md) requires *"`project_id` **nullable** on dedup tables (FK deferred
to `0007`)"*. `NOT NULL` is impossible at `0006`: there is no `projects` row for any value to
reference, so any insert before P12 would be unsatisfiable.

**The real gap is downstream.** [34 §P12](34-implementation-plan.md) lists its closures as
*"`ai_calls.project_id`, `runs.project_id` (+ `NOT NULL`), `dedup_groups.project_id`,
`minhash_bands.project_id`"*. It tightens `runs.project_id` **explicitly** and pointedly says nothing
about the other two. On the documents as written they are nullable at `0006` and nullable forever —
quietly contradicting [05 §5.4b](05-database-plan.md).

### ✅ Recommendation — **nullable and bare at `0006`; the tightening is P12's decision, named in P8's handover**

P8 has no choice about `0006`: nullable and bare is the only thing that works, and it is what
[34 §P8](34-implementation-plan.md) says.

P8 must **not** pre-empt P12. Whether these columns become `NOT NULL` depends on whether a dedup
group can legitimately exist outside a project — and the answer is genuinely unobvious, because
**the 478 existing leads all carry `project_id IS NULL`** and P10 will group leads, not projects.
[X4](31-execution-plan.md) explicitly anticipates project-less leads as normal.

**P8's obligations, all discharged in documentation:**

1. Create both columns nullable and bare.
2. Amend [05 §5.4b](05-database-plan.md) to `NULL` with a comment naming `0007` as where the FK
   closes and P12 as the owner of the nullability question.
3. **State the open question in `PHASE-08-HANDOVER.md`**, so P12 answers it deliberately.

> If P12 does tighten them, it needs a **fifth and sixth** rebuild on top of D1's four. That belongs
> in P8's handover as a cost estimate, not discovered by P12 mid-phase.

---

<a id="d5"></a>
## D5 — How the F1 class of defect is prevented from recurring

### 🟠 Needs assent

The sharpest fact in this review is not that a dangling FK breaks inserts. It is that
**every gate in the project reports green while it does**
([review §2.1](P8-IMPLEMENTATION-REVIEW.md)): the up/down/up round-trip is pure DDL,
`check_schema.py` only reads, `PRAGMA foreign_key_check` returns `[]`, and P8's own AC is a `SELECT`.

**P8 is not the last phase with this exposure.** `0007` (P12), `0008` (P17), `0009` (P19) and `0010`
(P25) each create forward-referencing columns. The same defect can be reintroduced four more times.

### Options

| | Option | Coverage | Cost |
|---|---|---|---|
| **A** | Two tests: insert a lead and a comment at `0006` | P8 only | ~20 lines |
| **B** | **A, plus a parametrised guard over every revision `0001..head` asserting no table has a `REFERENCES` target that does not exist at that revision** | **Every current and future revision** | ~40 lines, **no fixtures** |
| **B′** | As B, but by *inserting* into every table at every revision | same | **rejected — see below** |
| **C** | Add `PRAGMA foreign_key_check` to `check_schema.py` | **None** — measured to return `[]` with the defect present | — |
| **D** | Document the hazard in the handover | Advisory only | ~0 |

**C is worthless here, and worth stating explicitly** because it is the obvious instinct and it was
measured to fail: `foreign_key_check` validates *data* against constraints it can resolve. It says
nothing about a constraint whose parent table is missing.

**B′ is rejected on cost.** Inserting into *every* table at *every* revision needs a valid fixture
row for `jobs` (FK to `runs`), `run_events`, `prescores` (an FK **and** the
`(lead_id IS NOT NULL) <> (comment_id IS NOT NULL)` CHECK), `dedup_members`, and more — at six
revisions and growing. That is a fixture-maintenance burden that would stall Stage 1 and would itself
need maintaining by every later phase.

### ✅ Recommendation — **Option B**

The defect class is narrower than "inserts break": it is **a `REFERENCES` target that does not exist
at that revision.** `PRAGMA foreign_key_list(<table>)` names it directly, at every revision, with no
fixture rows at all — cross-check each referenced parent against `sqlite_master`.

**Verified this session** — the guard detects the defect and goes quiet once the parent arrives:

```
tables: ['comments', 'leads']
DANGLING DETECTED: [('leads', 'project_id', 'projects')]
after projects exists: []
```

The whole check is a nested loop over `sqlite_master` and `foreign_key_list`, and it correctly
ignores in-revision references (`comments.lead_id → leads` raised nothing).

The marginal cost over A is roughly twenty lines, and it converts a P8 bug-fix into a standing
architectural guard — the same move P6 made with `test_the_density_heuristic_was_not_reintroduced`
and P5 with `test_conditional_get_has_not_been_reintroduced`. This repository already prefers a test
that prevents a class of error over a note describing one.

It satisfies all four [lock §8](EXECUTION_MODE_LOCK.md) conditions: it relates directly to P8's
defect, adds no scope (a test, not a capability), redesigns nothing, and costs well under an hour.

**Keep A as well.** The two concrete inserts at `0006` are cheap and prove the failure mode end to
end rather than by proxy.

**Suggested names**, matching the existing idiom:
`tests/test_migrations.py::test_no_revision_leaves_a_dangling_foreign_key`, plus the A7/A8 inserts.

---

<a id="d6"></a>
## D6 — Whether P8 closes the `mypy` gate (O2)

### 🟡 Recommendation

`mypy` is required by [35 §2](35-testing-strategy.md) check 3 and
[freeze §5](ARCHITECTURE_FREEZE.md), and has never been installed — open as **O2** since 2026-08-06.
The full gate has therefore not been *claimable* for eight phases.

### ✅ Recommendation — **close it in P8, or explicitly re-defer it with a stated reason**

Not because P8 needs it, but because **P8 is the cheapest phase remaining in which to establish the
baseline.** P8 adds one migration and roughly four declarative model classes. The first
error-count baseline will never again be this small or this reviewable.

The alternative is baselining against P9's rule engine, P10's dedup cascade and P11's scoring — the
most logic-dense phases in Stage D, and precisely the code where type errors would matter most.

**Cost:** `python -m pip install mypy`, one run, record the count. Under thirty minutes.

**This is an operator decision, not an engineering one** — O2 is in
[DEFERRED-IMPROVEMENTS §2](DEFERRED-IMPROVEMENTS.md) ("choices only the operator can make"). Either
answer is legitimate; what is not legitimate is a ninth phase claiming a green gate that includes a
check which has never executed.

---

<a id="d7"></a>
## D7 — Details that are unspecified, and are being chosen rather than defaulted

### 🟡 Recorded, non-blocking

Each is a real gap in the documents. Each recommendation follows the surrounding idiom rather than
introducing anything.

| # | Unspecified | Recommendation | Basis |
|---|---|---|---|
| **d1** | Revision filename | `0006_content_and_dedup.py`, `down_revision = "0005_discovery"` | [freeze §4.1](ARCHITECTURE_FREEZE.md); matches `0005_discovery`'s own convention |
| **d2** | Whether `Comment` etc. get SQLAlchemy models | **Yes** for `Comment` ([34 §P8](34-implementation-plan.md) Deliverables names it). Dedup tables also get models — `test_post_baseline_columns_are_exactly_as_declared` reflects `Base.metadata` and will otherwise diverge | 34 §P8; `tests/test_migrations.py:124` |
| **d3** | `comments.scraped_at` default | Naive UTC via the existing `_utcnow`, never `datetime.utcnow` | `test_no_datetime_column_defaults_to_a_deprecated_or_local_clock` already enforces this |
| **d4** | Whether `ux_comments_hash` is global or per-lead | **Global**, exactly as [05 §5.4](05-database-plan.md) writes it. The hash is `sha256(lead_id\|author\|body)`, so `lead_id` is already inside the key | 05 §5.4 |
| **d5** | Does `downgrade()` drop `leads` columns individually or by rebuild? | `batch_alter_table` drop_column — SQLite ≥3.35 supports `DROP COLUMN`, but Alembic's batch path is what `0004` used | `0004_orchestration.py:117` |
| **d6** | Does P8 update `POST_BASELINE_COLUMNS`? | **Yes** — `leads` gains four entries, or `test_post_baseline_columns_are_exactly_as_declared` fails | `tests/test_migrations.py:124` |
| **d7** | Timing budget for A6 (*"`ALTER` < 1 s"*) | Assert **metadata-only** (row count and `rootpage` unchanged), not wall-clock | **DI18** — a wall-clock assertion tests machine load, not code |

> **d7 is the DI18 lesson applied prospectively.** DI18's trigger has not fired and P8 must not fire
> it: the property that matters is *"the `ALTER` did not rewrite the table"*, and asserting that
> directly is both stronger than a stopwatch and immune to a busy machine. This is not weakening an
> assertion ([lock §3](EXECUTION_MODE_LOCK.md) step 6) — it is replacing a proxy with the thing the
> proxy stood for.

---

## D8 — A flaky test now stands between every P8 stage and its own gate

### 🟠 Needs assent — *raised 2026-08-11, after this document was first written*

`tests/test_orchestration.py::TestSchemaCheckScript::test_does_not_write_to_the_database_it_checks`
is a WAL/mtime race. The history:

| # | When | Result |
|---|---|---|
| 1 | P7 CI | Failed once, **passed on re-run with identical code** |
| 2 | — | Recorded in [PHASE-07-HANDOVER §8](PHASE-07-HANDOVER.md) as **DI20 *(proposed)*** — never registered |
| 3 | **P8 pre-flight, 2026-08-11** | `1 failed, 1130 passed, 2 skipped`, pristine tree · re-run of that test alone: **`4 passed`** |

**Why this is a decision and not a footnote.** P8's own rule is *"green CI after every implementation
stage"*, and the checklist has **five** stages. A test that fails intermittently converts that rule
into a coin flip, and — worse — it trains the phase to treat a red suite as *"probably the flake"*.
That is precisely the reflex that lets a real regression through. **A re-run is not a pass.**

The reason P7 gave for deferring it — *"it is P5's test on a path P7 does not touch"* — **no longer
holds.** P8 is a migration phase, `check_schema.py` is one of its gates (Stage 0.6, and again after
every migration step), and this is the test that guards that script's read-only property.

### Options

| | Option | Pros | Cons |
|---|---|---|---|
| **A** | **Fix it now**, before Stage 1 | The gate means what it says for all five stages · same class and shape as the `TELEGRAM_BOT_TOKEN` fix already made this session — an ambient precondition made explicit · removes the "probably the flake" reflex | ~30 min on a test P8 did not plan to touch |
| **B** ▶ | **Register it as DI20 properly**, and re-run when it fires | Zero cost now · honest about what is known | Every stage's gate carries an asterisk · a third occurrence is a pattern, and registering a pattern is not the same as handling it |
| **C** | Raise the timing threshold | Fastest | ⛔ **Weakening an assertion** — [lock §3](EXECUTION_MODE_LOCK.md) step 6 forbids it. Listed to be ruled out |

### ✅ Recommendation — **A, and register DI20 either way**

**Fix it.** The precedent was set twice already this session: the same species of defect (a test whose
premise is ambient rather than stated) was found in `test_building_the_transport_is_lazy…` and fixed
in one line that *strengthened* the assertion. Doing the same here costs little and buys a gate that
can be trusted for five consecutive stages.

**If the operator prefers B**, then DI20 must be **registered**, not left *proposed* — a third
occurrence of an unregistered flake is how it becomes permanent. And Stage 0.7 must say out loud that
a re-run is a known, bounded exception rather than a general licence.

⚠️ **This is scope P8 did not plan for.** It is raised rather than absorbed, because the alternative
is a phase that quietly redefines "green".

---

## Summary — what is needed to start

| # | Needed from the operator | Blocking? |
|---|---|---|
| 1 | **D1** — confirm Option A (bare at `0006`, FK closed in `0007`), accepting four rebuilds in P12 | 🔴 Yes |
| 2 | **D2** — confirm freeze §4.1 wins and P8 executes the §11.1 reconciliation across seven document targets | 🔴 Yes |
| 3 | **D3** — assent to adopting [16 §115](16-phase-06.md)'s `source` DDL into [05 §4.1](05-database-plan.md) | 🟠 Effectively |
| 4 | **D4** — assent to nullable-and-bare, with the tightening question handed to P12 | 🟠 Effectively |
| 5 | **D5** — assent to the all-revisions insert guard (Option B) | 🟠 Recommended |
| 6 | **D6** — decide O2 (`mypy`): close it in P8, or re-defer with a reason | 🟡 Operator's call |
| 7 | **D7** — no action; recorded so nothing is defaulted silently | 🟡 No |
| 8 | **D8** — the WAL/mtime flake: fix it now (**A**, recommended), or register DI20 and re-run | 🟠 Recommended |
| 9 | Acknowledge **DI20 is reserved, not missing** ([review F8](P8-IMPLEMENTATION-REVIEW.md), resolved 2026-08-11) | ℹ️ No |

**With D1 and D2 settled, P8 is two days of low-risk declarative DDL.** Without them, it is a
migration that breaks the scraper while every gate reports success.

---

## Addendum — what changed after this document was first written

This analysis was drafted 2026-08-11 10:30. The following was established afterwards, in the same
session that closed P7's live verification:

| | Change | Effect on this document |
|---|---|---|
| **F1 independently reproduced** | Re-derived from scratch on SQLite 3.45.3: the dangling `REFERENCES` lets `ADD COLUMN` succeed, `SELECT` succeed and `PRAGMA foreign_key_check` return `[]`, while **every** `INSERT` into `leads` fails — including with `project_id` explicitly `NULL` | **D1 is unchanged and now rests on two independent reproductions.** Option A stands |
| **F6 re-checked** | `scripts/check_schema.py` defines `EXPECTED_LEADS = 459` and `BASELINE_MAX_LEAD_ID = 459`; the live table holds **478** | **F6 was already stated correctly** — it separates the legacy-contract baseline from the row count the `ALTER` touches. No change |
| **D8 added** | The WAL/mtime flake fired a third time, on P8's own pre-flight | **New row 8 above** |
| **P7's B1 closed** | Live Telegram delivery verified; the token now exists in `.env` | **No effect on P8** — P8 is a schema phase and never depended on B1. It did expose one test that depended on the token's *absence*, fixed in `06cdf11` |
