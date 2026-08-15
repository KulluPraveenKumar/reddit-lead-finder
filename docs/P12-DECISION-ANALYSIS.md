# P12 — Decision Analysis

**Phase:** P12, project & BKB schema · **Written:** 2026-08-15
**Companion to:** [PHASE-12-COMPLETION-REPORT.md](PHASE-12-COMPLETION-REPORT.md) ·
[PHASE-12-HANDOVER.md](PHASE-12-HANDOVER.md)

> The reasoning behind the three [freeze §11.1](ARCHITECTURE_FREEZE.md) reconciliations P12 filed,
> and the two things it deliberately did not build. Same role as
> [P11-DECISION-ANALYSIS.md](P11-DECISION-ANALYSIS.md): the completion report says *what*, this says
> *why*, and the freeze carries the one-line record.
>
> **Every one of these was measured before code was written**, not after. That ordering matters:
> D1 and D2 change what the revision contains, and discovering them during validation would have
> meant rewriting a shipped migration rather than authoring the right one.

---

## D1 — `runs.project_id` is not tightened to `NOT NULL`

**Operator decision, taken 2026-08-15 before `0007` was authored.**

### What the documents ask for

[34 §P12](34-implementation-plan.md)'s DB row: *"Closes FKs on … `runs.project_id` (**+ `NOT NULL`**)"*.
[05 §7.1a](05-database-plan.md): *"`runs.project_id` stays nullable until `0005` and **is tightened to
`NOT NULL` in the same rebuild**"*.

### The measurement

Taken on a read-only handle to `data/leads.db`, 2026-08-15:

```
runs total/null: (11, 11)
leads null pid : (492, 492)
ai_calls       : (3, 3)
```

**Every run that has ever existed on this installation has `project_id IS NULL`.**

### Why it cannot be built

Three walls, any one of which is sufficient:

1. **Mechanically.** SQLite has no `ALTER COLUMN`. `batch_alter_table` +
   `alter_column(nullable=False)` emits `CREATE _alembic_tmp_runs (… project_id INTEGER NOT NULL …)`
   then `INSERT INTO _alembic_tmp_runs SELECT … FROM runs`. That `INSERT` **fails** on 11 NULL rows.
2. **M5.** The only way to make it pass is to invent a placeholder `projects` row and backfill the
   11 runs to point at it. [Freeze §4](ARCHITECTURE_FREEZE.md) **M5**: *"Additive only … **No
   migration rewrites a row**."* And **M9** requires the up/down/up round-trip against a copy of the
   live database, so testing on a fresh one would not have hidden it — it would only have delayed
   the discovery to the operator's machine.
3. **AD-5, and the shipped code.** [Freeze §3](ARCHITECTURE_FREEZE.md) freezes AD-5 as *"Project
   scoping is additive **and nullable**"*. `RunService.create(project_id: int | None, options)` is
   the shipped signature; the dashboard passes `None`, `tests/test_schedule_and_health.py` passes
   `None`, and nothing creates a `projects` row until **P16**'s `project add`. A `NOT NULL` column
   would break run creation from P1 onward — the pipeline, not a test.

### Why this is a reconciliation and not a §11 amendment

Nothing frozen moves. The column keeps exactly the nullability it has had since `0004`; *not*
tightening it is what **preserves** M5 and AD-5 rather than what bends them. No technology, table,
decision or dependency changes, and the chain stays at ten revisions.

[05 §7.1a](05-database-plan.md) in fact **argues P12's side one sentence before it asks for the
opposite**: *"a run created before Phase 4 has no project to belong to"* — which is the reason the
constraint was deferred and is equally the reason the column stays nullable. The document contradicts
itself inside one paragraph; the half that agrees with a frozen AD wins.

### What shipped instead

The **foreign key is created** — that half was always buildable and is what M8 deferred. Two tests
pin the outcome in both directions, because a later phase re-reading the plan's parenthetical will
be tempted to "finish the job":

* `test_runs_project_id_is_still_nullable` — the schema fact, with the measurement in its message.
* `test_a_run_can_still_be_created_without_a_project` — the behaviour, which is what would actually
  break.

### Alternatives considered

| Option | Rejected because |
|---|---|
| Backfill a `projects` row named e.g. *"legacy"* and tighten | M5, in as many words. And it invents a project the operator never created, which then appears in every project list P16 renders |
| Tighten for new rows only (a `CHECK` with an id floor) | Not expressible without pinning a row id into the schema, and it would still break `RunService.create(None, …)` |
| File a §11 amendment | An amendment needs a failed measurement **that overturns a frozen decision**. The measurement here *confirms* AD-5. Filing one would consume the amendment path to ratify the status quo |

---

## D2 — six deferred foreign keys close, not four

### The disagreement

Four documents, four counts, for one set of columns:

| Source | Says |
|---|---|
| [34 §P12](34-implementation-plan.md) DB row | **four** — `ai_calls`, `runs`, `dedup_groups`, `minhash_bands` |
| [34 §P12](34-implementation-plan.md) Acceptance | *"reports all **four** constraints"* |
| [35 §6](35-testing-strategy.md) P12 row | *"**4** FKs"* |
| [05 §7.1](05-database-plan.md) table | **six** — the four above plus `leads.project_id`, `comments.project_id` |
| [05 §7.1a](05-database-plan.md) closing prose | *"all **three** constraints"* |

And `scripts/check_schema.py`, shipped since P8 and run from the manual guide, asserts in **four**
separate checks that `leads`, `comments`, `dedup_groups` and `minhash_bands` are each *"BARE — the FK
is **deferred to 0007** (M8)"*.

### Why six

Two of those four `check_schema.py` assertions describe a deferral that, on the count of four, would
**never be honoured**. M8's text is *"forward references use a bare column plus a **deferred FK added
later** by `batch_alter_table`"* — a bare column whose parent now exists and that nothing is going to
constrain is not a deferral, it is an unconstrained column with a comment. `0007` is the last
revision that creates `projects`; there is no later one that would "finish" `leads` and `comments`
without a reason of its own.

Six is also the **union** of every list, so it satisfies the four-count readings as well: a test
asserting those four constraints exist passes against six.

### The risk, measured before the revision was written

The objection to six is real and is entirely about `leads`: closing its FK means `batch_alter_table`
performs a create-copy-drop-rename on the table [R20](ARCHITECTURE_FREEZE.md) pins, carrying 492
rows, a fingerprint, nine indexes and inbound foreign keys from four other tables. So it was probed
on a copy of the live database **before** `0007` existed, rather than argued:

```
BEFORE 492 rows  fp=9327a13dd9ef4185  9 indexes
AFTER  492 rows  fp=9327a13dd9ef4185  9 indexes  fk=[(projects, project_id, id)]
ix_leads_reddit_id UNIQUE preserved (index_list unique flag 1 → 1)
child FKs: comments->leads intact · dedup_members->{comments,leads,dedup_groups} intact
PRAGMA foreign_key_check [] · integrity_check ok
VERDICT: SURVIVES
```

Had that come back BROKEN, the answer would have been four with `leads`/`comments` filed as a
Deferred Improvement. It did not, so the documented deferral is honoured.

### The ON DELETE actions are not uniform, deliberately

No document states them for these four columns, so P12 chose. The choice is asymmetric and the
asymmetry is the content:

| Column | Action | Why |
|---|---|---|
| `ai_calls.project_id` | `SET NULL` | Given literally in [05 §7.1](05-database-plan.md) |
| `runs.project_id` | `CASCADE` | Given literally in [05 §7.1](05-database-plan.md) |
| `leads.project_id` | **`SET NULL`** | [Freeze §8](ARCHITECTURE_FREEZE.md) makes *expiring leads* a permanent non-goal: *"a lead is a historical fact"*. Cascading a project deletion into the collected corpus would delete real research |
| `comments.project_id` | **`SET NULL`** | Same, and a comment's lifetime is already tied to its lead, which cascades |
| `dedup_groups.project_id` | **`CASCADE`** | A derived per-run artefact, rebuilt from scratch, already cascading from `runs` |
| `minhash_bands.project_id` | **`CASCADE`** | Same |

`test_the_deletion_actions_are_not_uniform` asserts the split survives, because collapsing it in
either direction is a one-line edit that no other test would notice.

---

## D3 — `bkb_sections.payload_json` ships nullable, with a `CHECK`

### The contradiction

[05 §5.1](05-database-plan.md)'s DDL: `payload_json TEXT NOT NULL`.
[05 §5.1b](05-database-plan.md), added later by the architecture review: for `buyer_personas`,
`pain_points` and `buying_signals`, *"the typed table is authoritative for content … **`payload_json`
is `NULL`**"*.

Both cannot hold. [34 §P12](34-implementation-plan.md)'s acceptance criterion encodes §5.1b
explicitly — *"`payload_json IS NULL` for exactly `buyer_personas`/`pain_points`/`buying_signals`"* —
so the phase could not have been accepted under §5.1's reading either.

### Why §5.1b wins

It is the later statement, the more specific one, and the only one that carries its reasoning:
one source of truth for a persona's text, and evidence that cascades correctly with the BKB version
it belongs to. §5.1's `NOT NULL` is a column attribute written before the typed-table rule existed.

### Why a `CHECK` rather than a convention

§5.1b says *"a test asserts both directions"*. P12 ships the test **and** the constraint, because a
rule enforced only by a test is one the next writer breaks inside a transaction no test observes —
and this schema already enforces exactly this shape twice, in `ck_prescores_one_target` and
`ck_dedup_members_one_target`. Writing it as a biconditional rather than two rules is what makes the
second half assertable at all:

```sql
CHECK ((section_key IN ('buyer_personas','pain_points','buying_signals')) = (payload_json IS NULL))
```

**`ideal_customer_profiles` is not exempt**, which is the specific mistake §5.1b flags by name. An
ICP feels structurally like a persona, so a reader assumes an `icps` table behind it. There is none —
`payload_json` is the only copy of an ICP that exists, and exempting the section would lose it
entirely while every other test still passed. `test_ideal_customer_profiles_is_not_exempt` exists for
that one line.

The keys are spelled **twice** — literally in the migration (a revision is a snapshot and must not
import a constant a later phase may edit) and in `src.db.models.BKB_TYPED_SECTION_KEYS`. Two
spellings of one rule is how they drift, so
`test_the_migrations_check_and_the_models_constant_agree` asserts the agreement — the pairing
`tests/test_rules_vocabulary.py` established in P9.

---

## D4 — DI28 (`leads.run_id`) declined

[PHASE-11-HANDOVER §3](PHASE-11-HANDOVER.md) named `0007` *"the cheap moment"*, and it was: the
revision already ran `batch_alter_table` over `leads`, so the marginal cost was one line.

Declined on **DI28's own trigger text**: *"there is **no failed measurement**, because the window is
exact today."* [Lock §8](EXECUTION_MODE_LOCK.md) admits a mid-phase improvement only when it
*"directly relates to the current phase"* — P12's Objective is the knowledge-base schema, and no P12
deliverable, task or acceptance criterion reads `leads` by run. The register is explicit that it *"is
not a backlog to be worked through; it is where an idea waits for evidence"*, and the evidence DI28
names — a second concurrent run, or a backfill writing historical leads with a current `scraped_at` —
has not arrived.

It would also have meant a **second** rebuild of the legacy table, doubling the one genuinely risky
operation in the revision for a column nothing reads.

`test_leads_has_no_run_id` pins the decision so the next reader sees a choice. The entry stays open
with its trigger unchanged, now naming **P17**'s `0008_targeting` as the next revision that could
carry it.

---

## D5 — the three absent pre-score components stay absent

[PHASE-11-HANDOVER §3](PHASE-11-HANDOVER.md) assigns `pain_phrase` and `subreddit_fit` to P12:
*"`0007` creates `projects`, `pain_points` and `bkb_entities`, which is what they need."*

**It is not what they need.** `0007` creates those tables **empty**. The rows arrive later:
`pain_points.phrases_json` is written by **P14**'s `analyze_business`; the first `projects` row by
**P16**'s `project add`; `bkb_entities` by **P15**'s registry — and
`test_the_competitor_registry_was_not_wired_before_p15` already fails if that one is wired early.

A component reading an empty table returns `0.0` for every item. That is
[DI24](DEFERRED-IMPROVEMENTS.md) verbatim — *a score nobody noticed was always zero* — inside the
constant that exists to prevent it, and it is the reasoning by which P11 declined to ship the three
at `0.0` in the first place. [PHASE-11-HANDOVER §4](PHASE-11-HANDOVER.md) **T2** adds the second
cost: the weights are normalised by their own sum, so adding a seventh **rescales every stored
`total`** and invalidates the admission floor of 35 measured against the six-component distribution.
Rescaling every score in the database, to add components that can only be zero, is strictly worse
than waiting.

**What P12 did change is the labels.** `ABSENT_COMPONENTS` named *"P12 — `pain_points` arrives in
revision 0007"*, which was true about the column and wrong about the phase. Each entry now names the
phase that supplies the **data**: `pain_phrase` → P14, `competitor` → P15, `subreddit_fit` → P16.
Leaving them would have reproduced [PHASE-11-HANDOVER §6](PHASE-11-HANDOVER.md)'s exact warning — a
constant that keeps passing while asserting a lie.

`test_the_three_absent_pre_score_components_are_still_absent` carries the reasoning and asserts that
**no** entry names P12, so the correction cannot be silently reverted.

---

## D6 — `/health` reads the schema, not an import

[34 §P12](34-implementation-plan.md): *"`/health` reports `semantic_layer: disabled`"*. Two ways to
answer that, and they are different questions:

| Probe | Answers |
|---|---|
| `import sqlite_vec` | *Could this process load the extension right now?* |
| `SELECT … WHERE name='bkb_embeddings'` | *Did the migration create the tables?* |

The second is the question. The difference bites in one specific direction: install the extension on
a database that was migrated without it, and the import probe reports `enabled` for **two tables that
do not exist**. The migration is where the decision was taken, and the schema is where that decision
is recorded. `test_health_reads_the_schema_rather_than_importing_sqlite_vec` injects a perfectly
importable `sqlite_vec` and asserts the report stays `disabled`.

---

## D7 — what could not be tested, stated rather than faked

`sqlite_vec` is not installed on this host — P0's finding
([SPRINT-0-MEASUREMENTS §3.1](SPRINT-0-MEASUREMENTS.md)), re-measured 2026-08-15 — so
`CREATE VIRTUAL TABLE bkb_embeddings USING vec0(embedding FLOAT[256])` **never executes**, in the
suite or in the drill. There is no honest way to fake it: `vec0` is a C extension module, and a stub
that let the branch proceed would fail at the DDL with `no such module: vec0`.

So the branch is covered from every side except the one statement:

* the loader failing is **forced**, by injecting a `sqlite_vec` whose `load()` raises — not left to
  the host's genuine absence, which would pass vacuously and start failing the day someone installed
  it;
* both tables are asserted absent **together**, because meta without vectors is a table of pointers
  into nothing;
* the warning is asserted to name its cause and what was skipped;
* the DDL string itself is pinned, which catches a hand-edited dimension and nothing more;
* the downgrade is asserted clean on a host where the pair was never created.

The residue — *does `vec0` accept this column spec?* — is untested and is recorded as such in
[PHASE-12-COMPLETION-REPORT](PHASE-12-COMPLETION-REPORT.md) and as a trap in
[PHASE-12-HANDOVER](PHASE-12-HANDOVER.md), rather than covered by a test that would pass without
proving it. It is P15's to discover, being the first phase with a reason to install the extension.

---

## D8 — `check_schema.py`'s four assertions invert

`check_schema.py` is outside [34 §P12](34-implementation-plan.md)'s Files row, and it had to change:
its four *"`{table}.project_id` is BARE — the FK is deferred to 0007"* checks are **correct at `0006`
and false at `0007`**, and the same is true of *"runs has no foreign keys yet"*.

Both directions are real failures and they are exact opposites:

* before `0007`, a `REFERENCES projects` clause breaks **every** `INSERT` into that table, silently;
* after `0007`, its absence means M8 deferred a constraint to nowhere.

So the checks take a flag rather than becoming constants, and `--skip-p12` continues the
`--skip-p1`/`--skip-p6`/`--skip-p8` idiom for verifying a database that has not been upgraded yet —
which the operator's live database has not, and will not be until they run the manual guide
themselves. `--skip-p8` implies `--skip-p12`, because a database without `comments` cannot have had
`0007` applied.

The alternative — auto-detecting the revision — was rejected: it would pass silently on a database
that is missing all twelve tables for the wrong reason.
