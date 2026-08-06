# Manual Testing Guide — P1: Run & Job Schema

Written so a **non-developer can verify this phase without guessing**. Every step states what you
should see. If what you see differs, that step's *Possible failure* table tells you what it means.

- **Time:** ~20 minutes for the full suite; ~5 minutes for the smoke path (T1–T3).
- **You need:** a terminal and the project's Python interpreter. No browser is needed until T7. No
  API key, no Telegram account, no internet connection. **You do not need the `sqlite3` command-line
  tool** — nothing in this guide uses it, which is why the guide runs unchanged on Windows.
- **Destructive steps:** **none, if you follow the guide.** T4, T5 and the Rollback section all run
  against a **copy** of the database (`data\p1-test.db`), never `data\leads.db`. Steps that create or
  delete that copy are marked ⚠️ and every one of them names its reversal.
- **What this phase added:** three new database tables (`runs`, `jobs`, `run_events`), one new nullable
  column on an existing table (`scrape_runs.run_id`), two foreign keys onto existing tables, and a
  Python state machine. **Nothing runs yet** — there is no worker, no API and no page. That arrives in
  P2 and P3. This guide therefore verifies *shape and safety*, not behaviour.

> ⚠️ **Not the same as `docs/MANUAL-TESTING-PHASE-01.md`.** That guide belongs to the old eight-phase
> numbering and was completed 2026-07-30. This guide covers **P1** of the frozen P0–P30 plan.

Throughout, `>` marks a command to run and `→` marks what you should see.

---

## Before you start

**Use PowerShell.** Open *Windows PowerShell* (or *Windows Terminal*), not `cmd.exe` and not Git
Bash. T4 Step 2 sets an environment variable with PowerShell syntax (`$env:NAME = "value"`); in
`cmd.exe` that line does nothing and prints no error, and the next command would migrate your **live**
database. T4 Step 3 exists to catch that, but starting in the right shell avoids it entirely.

**Start in the project root.** Every command below is relative to it, so nothing in this guide
contains a machine-specific path:
```
> cd <the folder containing pyproject.toml>
```

**If the dashboard is running, stop it.** A stale process holds port 5000 and serves *old code*,
which looks exactly like a broken change:

```
> powershell "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*dashboard*' } | Stop-Process -Force"
```
→ No output, or an error saying no process matched. Both are fine.

**Confirm the interpreter:**
```
> .\.venv\Scripts\python.exe --version
```
→ `Python 3.12.5`

**Confirm the live database is intact.** This is the single most important precondition in this
guide — every later step compares against it:
```
> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db
```
→ **Expected:** every line reads `PASS`, and the last line begins `OK —`.
→ The **number** of checks depends on which revision your live database is at, and both answers are
fine: `all 26 checks passed` at `0004_orchestration`, or — after adding `--skip-p1`, which you must
at `0003` — `all 5 checks passed`. Read the table below before deciding anything is wrong.
→ The `INFO  alembic_version is ...` line reports the version without judging it.

> **What `check_schema.py` is.** One command that replaces the long
> `python -c "import sqlite3; ..."` one-liners this guide used to carry. It is stdlib-only, opens the
> database **read-only**, and prints one `PASS`/`FAIL` line per check with the reason. `--help` lists
> its options. It needs Python and nothing else — in particular **not** the `sqlite3` command-line
> tool, which a default Windows install does not have.

### Which revision should the live database be at?

Either answer can be correct, and the guide works from both:

| `alembic_version` | Meaning | What changes |
|---|---|---|
| `0003_net_infrastructure` | P1 shipped the migration and you have not applied it to your live database | Nothing. This is the state P1 delivers |
| `0004_orchestration` | The migration has been applied to the live database — a deliberate operator action, or an accidental one during T4 | Nothing in P1 or P2 breaks. The three new tables are empty and unused until P2 |

**Neither is a defect, and 26 passing checks confirm the data is intact either way.** What *would* be
a defect is the lead count or the `intent_score` fingerprint moving, and those are checked above.
If you are at `0004` and want to return to the delivered state, run
`.\.venv\Scripts\python.exe -m alembic downgrade 0003` — but read T4 first, and take a backup.

---

# T1 — The P1 code is clean

**Objective:** the six files P1 created or changed pass lint and formatting.
**Preconditions:** none.

### Step 1
```
> .\.venv\Scripts\python.exe -m ruff check src/orchestration migrations/versions/0004_orchestration.py tests/test_orchestration.py tests/test_migrations.py src/db/models.py scripts/check_schema.py
```
→ **Expected:**
```
All checks passed!
```

### Step 2
```
> .\.venv\Scripts\python.exe -m ruff format --check src/orchestration migrations/versions/0004_orchestration.py tests/test_orchestration.py tests/test_migrations.py src/db/models.py scripts/check_schema.py
```
→ **Expected:**
```
7 files already formatted
```

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `Found N errors` | Lint regressions were introduced | Re-run Step 1 with `--fix`, then re-run Step 1 |
| `N files would be reformatted` | Formatting drifted | Run the Step 2 command **without** `--check`, then re-run Step 2 |
| `No module named ruff` | Wrong interpreter | Use `.\.venv\Scripts\python.exe`, not a global `python` |
| A `SyntaxError` mentioning `def _coerce[` | Python 3.11 generics syntax crept back in | The project floor is 3.11; `TypeVar` must be used instead |

**Screenshot expected:** none.
**Logs to verify:** none.
**Database values to verify:** none.
**API response to verify:** none.

**Acceptance:** ✅ Both commands report clean.

---

# T2 — The whole test suite passes

**Objective:** P1 broke nothing that already worked, and the new orchestration tests pass.
**Preconditions:** T1 passed.

### Step 1
```
> .\.venv\Scripts\python.exe -m pytest
```
→ **Expected**, on the last line:
```
310 passed, 9 warnings
```
→ The count must be **310 or more**, and the word **`failed` must not appear**. The line also reports
an elapsed time; it varies between 40 s and 2 minutes and does not matter.

### Step 2
Confirm the new orchestration tests ran:
```
> .\.venv\Scripts\python.exe -m pytest tests/test_orchestration.py
```
→ **Expected**, on the last line:
```
44 passed
```
→ These 44 include the exhaustive transition tests — every one of the 144 run-state pairs and all 25
job-state pairs is checked, not a sample — and four tests covering `scripts/check_schema.py` itself,
one of which deliberately breaks an index to prove the checker reports `FAIL`.
→ Followed by an elapsed time, which varies and does not matter.

### Step 3
Confirm the four architecture boundary fences still hold:
```
> .\.venv\Scripts\python.exe -m pytest tests/test_boundaries.py
```
→ **Expected**, on the last line:
```
18 passed
```
→ These 18 include `test_no_vendor_coupling_outside_providers` (fence 1) and
`test_csv_export_still_thirteen_columns` (the legacy export contract).

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `N failed` | A real regression | Read the failure. Do **not** edit the assertion to make it pass |
| `266 passed` | The new test file is missing | Confirm `tests/test_orchestration.py` exists |
| `no tests ran` | Wrong directory | `cd` to the project root first |
| `test_baseline_matches_create_all` failed | The database baseline guard tripped | Expected only if a table other than `scrape_runs` changed. See T5 Step 5 |

**Screenshot expected:** none.
**Logs to verify:** the 9 warnings are pre-existing `datetime.utcnow()` deprecations inside
SQLAlchemy. They existed before P1 and are not caused by it.
**Database values to verify:** none — the suite uses temporary databases.
**API response to verify:** none.

**Acceptance:** ✅ 310+ passed, 0 failed; 44 orchestration tests present; fences green.

---

# T3 — The migration chain has exactly one head

**Objective:** the new migration extends the chain rather than forking it. A forked chain is the
failure mode that silently produces two different database shapes on two different machines.
**Preconditions:** none.

### Step 1
```
> .\.venv\Scripts\python.exe -m alembic heads
```
→ **Expected — exactly one line:**
```
0004_orchestration (head)
```

### Step 2
```
> .\.venv\Scripts\python.exe -m alembic history
```
→ **Expected — exactly four lines**, newest first:
```
0003_net_infrastructure -> 0004_orchestration (head), orchestration - runs, jobs, run_events
0002_ai_infrastructure -> 0003_net_infrastructure, net_infrastructure - proxies, http_cache, metrics
0001_baseline -> 0002_ai_infrastructure, ai_infrastructure - ai_calls, ai_cache, ai_provider_state
<base> -> 0001_baseline, baseline - the 8 tables that already exist
```
→ Every revision has exactly one arrow into it, and only the last line says `(head)`.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| Two lines from `heads` | The chain forked — two revisions claim the same parent | **Stop.** This must be fixed before P2. Do not renumber an existing migration (rule M2) |
| `Can't locate revision` | A revision file was deleted or renamed | Restore it from version control |
| `No such file or directory: alembic.ini` | Wrong directory | `cd` to the project root |

**Screenshot expected:** none.
**Logs to verify:** none.
**Database values to verify:** none — `heads` reads the migration files, not the database.
**API response to verify:** none.

**Acceptance:** ✅ Exactly one head, and it is `0004_orchestration`.

---

# T4 — The migration applies, reverses, and re-applies on real data

**Objective:** prove the migration is reversible against a copy of the **live** database, with its
459 real leads — not against an empty test fixture.
**Preconditions:** T3 passed. The *Before you start* check reported 459 leads.

### Step 1 ⚠️
Make the working copy. **This writes one new file and touches nothing else:**
```
> powershell "Copy-Item data\leads.db data\p1-test.db -Force"
```
→ No output.
**Reversal:** delete `data\p1-test.db`. It is done for you in Step 8.

### Step 2
Point Alembic at the copy. **Every remaining step in T4 and T5 depends on this variable being set.**
If you open a new terminal, set it again:
```
> $env:ALEMBIC_DB_URL = "sqlite:///data/p1-test.db"
```
→ No output.
→ The path is **relative to the project root** and uses **forward slashes** — this is a URL, not a
Windows path. Because it is relative, this line is identical on Windows, macOS and Linux, and it
contains no machine-specific folder. It is also why *Before you start* insists you `cd` to the
project root: the URL is resolved against your current directory.

> On macOS or Linux the equivalent is `export ALEMBIC_DB_URL="sqlite:///data/p1-test.db"`, and the
> interpreter is `.venv/bin/python` rather than `.\.venv\Scripts\python.exe`. Nothing else differs.

### Step 3
Confirm the variable took effect before you migrate anything:
```
> echo $env:ALEMBIC_DB_URL
```
→ **Expected:** `sqlite:///data/p1-test.db`
→ If this prints an empty line, **stop** — the next step would migrate your live database.

### Step 4 — Upgrade
```
> .\.venv\Scripts\python.exe -m alembic upgrade head
```
→ **Expected:**
```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 0003_net_infrastructure -> 0004_orchestration, orchestration - runs, jobs, run_events
```

### Step 5 — Confirm the data survived
```
> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\p1-test.db --revision 0004
```
→ **Expected:** every line `PASS`, ending in `OK — all 26 checks passed.`
→ This one command checks the migration version, all 18 tables, the index column orders, the foreign
keys, the constraints **and** that all 459 leads survived with their scores unchanged.

### Step 6 — Downgrade
```
> .\.venv\Scripts\python.exe -m alembic downgrade 0003
```
→ **Expected:**
```
INFO  [alembic.runtime.migration] Running downgrade 0004_orchestration -> 0003_net_infrastructure, orchestration - runs, jobs, run_events
```
Then confirm the reversal was complete:
```
> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\p1-test.db --revision 0003 --skip-p1
```
→ **Expected:** every line `PASS`, ending in `OK — all 6 checks passed.`
→ `--skip-p1` is what makes this the *reversal* check: it tells the script the 0004 tables should
**not** be there, so it verifies only integrity, the revision and the 459 leads. Running it without
`--skip-p1` here would correctly fail, because `runs`, `jobs` and `run_events` are gone — which is
the point of a downgrade.

Then confirm the added **column** went too, which is the half a table-level check would miss:
```
> .\.venv\Scripts\python.exe -m pytest tests/test_orchestration.py -k downgrade
```
→ **Expected:** `1 passed`.
→ `test_downgrade_removes_everything_and_restores_scrape_runs` asserts the three tables are gone,
**`scrape_runs.run_id` is gone**, the `ai_calls` foreign key is gone, and 459 leads remain. A
downgrade that left `run_id` behind would be a partial rollback — worse than none.

### Step 7 — Re-upgrade
```
> .\.venv\Scripts\python.exe -m alembic upgrade head
```
→ **Expected:** the same three `INFO` lines as Step 4, with no error.
→ This is the step that catches a migration which can only ever run once.

### Step 8 ⚠️ — Clean up
Leave the copy in place if you are going on to T5; otherwise remove it:
```
> powershell "Remove-Item data\p1-test.db* -Force"
```
**Reversal:** re-run Step 1. The copy holds no unique data.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `no such table: leads` | The copy was not made, or Alembic hit a different file | Re-run Steps 1–3 and check the URL in Step 3 |
| `Running upgrade` naming `leads.db` | ⚠️ `ALEMBIC_DB_URL` was not set — **your live database was migrated** | Run `alembic downgrade 0003` immediately, then verify 459 leads |
| `table runs already exists` on Step 7 | The downgrade did not drop the tables | The `downgrade()` is incomplete. This blocks P2 |
| `run_id` still listed after Step 6 | The downgrade dropped the constraint but not the column | Same as above — blocks P2 |
| `leads` is not 459 at any point | The migration destroyed data | **Stop.** Restore `data\leads.db` from `data\backups\` |
| `database is locked` | The dashboard is still running | Re-run the stop command in *Before you start* |

**Screenshot expected:** none.
**Logs to verify:** exactly three `INFO` lines per upgrade, and one `Running downgrade` line. Any
`WARNING` or `ERROR` line is a failure.
**Database values to verify:** `leads` = **459** after every one of Steps 5, 6 and 7.
**API response to verify:** none.

**Acceptance:** ✅ upgrade → downgrade → upgrade completes with 459 leads intact at every stage, and
the downgrade removes the column as well as the tables.

---

# T5 — The schema is exactly what was specified

**Objective:** the tables, indexes and foreign keys match `docs/05-database-plan.md`. An index whose
columns are in the wrong order still "exists" but does not do its job, so column **order** is checked,
not just presence.
**Preconditions:** T4 completed through Step 7, and `data\p1-test.db` is at `0004_orchestration`.
If you deleted it in T4 Step 8, re-run T4 Steps 1–4 first.

### Step 1 — Run the schema checker
```
> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\p1-test.db --revision 0004 --verbose
```
→ **Expected:** 26 `PASS` lines under eight headings, ending in `OK — all 26 checks passed.`

Read the headings rather than every line. Each one answers a different question, and a `FAIL`
prints the value it actually found next to the value it wanted:

| Heading | Checks | Why it matters |
|---|---|---|
| **Database integrity** | 2 | `PRAGMA integrity_check` and `foreign_key_check`. If the file itself is damaged, nothing below is meaningful |
| **Migration version** | 1 | The copy is at `0004_orchestration` |
| **Tables** | 2 | All 18 expected tables present, **and no unexpected ones** — a migration that creates a table nobody specified is as much a defect as one that misses it |
| **Indexes** | 5 | Column **order**, not just presence. `ix_jobs_claim` must be `state, available_at, priority, id` — this is the index the P2 worker claims work with, and any other order silently turns a seek into a table scan |
| **Foreign keys** | 5 | The `ON DELETE` action. `ai_calls` and `scrape_runs` are `SET NULL`; `jobs` and `run_events` are `CASCADE` |
| **Constraints** | 5 | `runs` columns exact and in order, **no expiry column**, and the nullability of `runs.project_id`, `jobs.run_id`, `run_events.run_id` |
| **Row counts** | 3 | `runs`, `jobs` and `run_events` are empty — P1 ships shape, not behaviour |
| **Legacy fingerprint** | 3 | 459 leads, `max(intent_score)` 164.28, `avg` 42.29 |

**The two things most worth understanding:**

- **`SET NULL` vs `CASCADE` is deliberate.** `SET NULL` on `ai_calls` and `scrape_runs` means
  deleting a run never deletes its cost history or its legacy scrape record. `CASCADE` on `jobs` and
  `run_events` means deleting a run *does* clean up its own work items. If these two ever match each
  other, one of them is wrong.
- **The absent expiry column is a feature.** `runs` has no `expires_at`, `timeout_at`, `deadline` or
  `ttl`. This is the **schema** half of the "gates never time out" guarantee (AD-6); **T6 Step 5** is
  the **model** half. Both are needed — during P1 a deliberately introduced fault in the model was
  found to slip past a guard that only read the schema.

### Step 2 — Existing tables were not disturbed
```
> .\.venv\Scripts\python.exe -m pytest tests/test_migrations.py
```
→ **Expected**, on the last line:
```
9 passed
```
→ One of those 9 is `test_post_baseline_columns_are_exactly_as_declared`. It asserts the only column
P1 added to a pre-existing table is `scrape_runs.run_id`. It fails if *any* other existing table
changed. This stays a separate step because it compares against the **declared model**, which the
schema checker deliberately does not read — see the note at the top of `scripts/check_schema.py`.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `FAIL  ix_jobs_claim` | The index is mis-specified — the line prints the order it found | Fix `0004`, downgrade the copy, re-upgrade. This blocks P2 |
| `FAIL  jobs -> runs.run_id ON DELETE CASCADE` showing `SET NULL` | Orphan jobs will accumulate after a run is deleted | Fix `0004` |
| `FAIL  ai_calls -> runs.run_id ON DELETE SET NULL` showing `CASCADE` | ⚠️ Deleting a run would erase its spend history | Fix `0004`. This is a data-loss defect |
| `FAIL  ... no unexpected tables` | The migration created something nobody specified | Read the names it lists. This blocks P2 |
| `FAIL  runs has no expiry column` | Gates could time out and lose an operator's work | Remove it. This contradicts AD-6 |
| `FAIL  integrity_check` | The database file is damaged | **Stop.** Restore from `data\backups\` |
| `FAIL  leads = 459` | The migration destroyed data | **Stop.** Restore from `data\backups\` |
| `test_post_baseline_columns_are_exactly_as_declared` failed | An existing table changed beyond `scrape_runs.run_id` | Read the diff it prints; P1 is not allowed to touch other tables |
| `ERROR: no such database` | `data\p1-test.db` was deleted in T4 Step 8 | Re-run T4 Steps 1–4 to recreate it |

**Screenshot expected:** none.
**Logs to verify:** none.
**Database values to verify:** all 26 checks `PASS`. `--verbose` prints the actual value beside each
one if you want to read them rather than trust them.
**API response to verify:** none.

**Acceptance:** ✅ `OK — all 26 checks passed`, and `tests/test_migrations.py` reports 9 passed.

---

# T6 — The state machine refuses illegal transitions

**Objective:** an impossible run transition fails loudly and **names both states**, so a future bug
report says what actually happened rather than "the run got stuck".
**Preconditions:** T2 passed. **No database needed** — every step here runs against Python code only,
so it works whether or not `data\p1-test.db` still exists.

### Step 1 — There are twelve run states
```
> .\.venv\Scripts\python.exe -c "from src.orchestration import RunState; print(len(list(RunState))); print([s.value for s in RunState])"
```
→ **Expected:**
```
12
['pending', 'profiling', 'discovering', 'awaiting_subreddit_review', 'generating_keywords', 'awaiting_keyword_review', 'awaiting_options', 'scraping', 'analyzing', 'complete', 'failed', 'cancelled']
```
→ Twelve, in this order. `docs/34-implementation-plan.md` originally said eleven; that was a
documentation error, corrected during P1. The specification is `docs/04-system-design.md` §1.1.

### Step 2 — A legal transition is silent
```
> .\.venv\Scripts\python.exe -c "from src.orchestration import RunState, assert_transition; assert_transition(RunState.PENDING, RunState.PROFILING); print('ok')"
```
→ **Expected:**
```
ok
```

### Step 3 — An illegal transition raises, naming both states
```
> .\.venv\Scripts\python.exe -c "from src.orchestration import RunState, assert_transition; assert_transition(RunState.PENDING, RunState.COMPLETE)"
```
→ **Expected**, on the last line:
```
src.orchestration.states.IllegalTransition: illegal run transition pending -> complete; allowed from pending: cancelled, failed, profiling
```
→ A traceback here is the **correct** outcome. The message must contain **both** `pending` and
`complete`, and must list what *was* allowed.

### Step 4 — The two human gates have no timeout
```
> .\.venv\Scripts\python.exe -c "from src.orchestration import GATE_STATES, TERMINAL_STATES; print(sorted(s.value for s in GATE_STATES)); print(sorted(s.value for s in TERMINAL_STATES))"
```
→ **Expected:**
```
['awaiting_keyword_review', 'awaiting_subreddit_review']
['cancelled', 'complete', 'failed']
```

### Step 5 — Nothing can expire a run while it waits at a gate
```
> .\.venv\Scripts\python.exe -c "from src.db.models import Run; print([c.name for c in Run.__table__.columns])"
```
→ **Expected:**
```
['id', 'project_id', 'state', 'options_json', 'stats_json', 'llm_cost_usd', 'error', 'started_at', 'updated_at', 'finished_at']
```
→ There is **no** `expires_at`, `timeout_at`, `deadline` or `ttl` column. A run parked at Gate 1
waits for a human indefinitely — including across a restart. That is the design (AD-6), and the
absence of these columns is how it is enforced.

> The matching **schema-side** check — that the `runs` *table* also has no expiry column — is
> **T5 Step 1**, because it needs the database copy. Both halves are required: the model and the
> table are separate artefacts, and during P1 a mutation to one was found to slip past a guard on
> the other.

### Step 6 — Every transition, not just the ones spot-checked above
Steps 2 and 3 check one legal edge and one illegal one. This checks all of them:
```
> .\.venv\Scripts\python.exe -m pytest tests/test_orchestration.py -k "unspecified or specification"
```
→ **Expected**, on the last line:
```
4 passed
```
→ These four assert the **whole** transition table against an independently transcribed copy of
`docs/04-system-design.md` §1.2 — all 144 run-state pairs and all 25 job-state pairs. The exhaustive
form matters because an *extra* edge added by mistake passes every hand-picked check: nothing you
would think to try is the thing that broke.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `11` in Step 1 | A state is missing | Compare against `docs/04-system-design.md` §1.1 |
| Step 2 raises | The transition table is wrong | `tests/test_orchestration.py` holds an independent copy of the spec — run it |
| Step 3 prints `ok` | Illegal transitions are being accepted — the guard is not wired in | This blocks P2 entirely |
| Step 3's message omits a state name | The error is unusable in a bug report | Fix the message in `assert_transition` |
| An expiry-looking column appears in Step 5 | Gates could time out and lose an operator's work | Remove it. This contradicts AD-6 |
| Step 6 reports a failure | An edge was added or removed without updating the specification | Read which pair it names. Do **not** edit the transcribed copy to match the code — that is the whole point of it being a separate copy |
| `ModuleNotFoundError: No module named 'src'` | Wrong directory | `cd` to the project root — `python -c` resolves `src` from the current folder |

**Screenshot expected:** none.
**Logs to verify:** none.
**Database values to verify:** none — every step in T6 runs against Python code, not a database.
**API response to verify:** none.

**Acceptance:** ✅ 12 states; legal passes; illegal raises naming both states; gates and terminals as
listed; no expiry column on the `Run` model; all 144 run-state and 25 job-state pairs verified.

---

# T7 — The legacy contract is intact

**Objective:** everything that worked before P1 still works, and the live data is unchanged.
**Preconditions:** none.

### Step 1 — Live data unchanged
```
> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db
```
→ **Expected:** every line `PASS` (`all 26 checks passed` at `0004`; add `--skip-p1` and expect
`all 5 checks passed` at `0003`).
→ The three figures that constitute the legacy fingerprint — **459 leads, `max` 164.28, `avg`
42.29** — appear under *Legacy fingerprint*. **These are what must not move.**

→ The `INFO  alembic_version is ...` line reports either `0003_net_infrastructure` or
`0004_orchestration`. **Both are acceptable** — see *Which revision should the live database be at?*
in *Before you start*. If it reads `0003`, add `--skip-p1` or the 0004 shape checks will correctly
fail on tables that have not been created yet.

### Step 2 — The new tables are empty
The migration having been applied is harmless; the migration having been *used* would be scope creep,
because P1 ships no worker and no API.
```
> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db --verbose
```
→ **Expected**, under *Row counts*: `runs`, `jobs` and `run_events` each `PASS` as empty.
→ If the database is still at `0003` these tables do not exist; use `--skip-p1` and this step is
vacuously satisfied.

> If `p1-test.db` or `p1-rollback.db` still exist, that is fine — they are the T4 and Rollback
> copies. Remove them with `powershell "Remove-Item data\p1-test.db*, data\p1-rollback.db* -Force"`.

### Step 3 — The CSV export still has 13 columns
```
> powershell "Get-Content tests\baseline\export_baseline.csv -TotalCount 1"
```
→ **Expected:**
```
ID,Reddit ID,Subreddit,Author,Title,URL,Score,Comments,Intent Score,Keywords,Status,Created UTC,Scraped At
```

### Step 4 — Every page and endpoint still responds
```
> .\.venv\Scripts\python.exe -m pytest tests/test_navigation_and_pages.py
```
→ **Expected**, on the last line:
```
31 passed
```

### Step 5 — The dashboard renders
```
> .\.venv\Scripts\python.exe main.py dashboard
```
Open `http://127.0.0.1:5000/` in a browser.
→ **Expected:** the leads dashboard, showing **459 leads**, visually identical to before P1.
→ There is **no** "Runs" link in the navigation. That is correct — the run pages arrive in P3.
Stop the server with `Ctrl+C`.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `FAIL  leads = 459` | The live database lost or gained rows | **Stop.** Restore from `data\backups\` |
| `alembic_version` is `0004_orchestration` and you expected `0003` | The live database was migrated — deliberately, or by T4 with `ALEMBIC_DB_URL` unset | **Not a defect, and not urgent.** The new tables are empty and unused until P2. To return to the delivered state: clear `ALEMBIC_DB_URL`, take a backup, then `alembic downgrade 0003` |
| `FAIL  max(intent_score)` or `FAIL  avg(intent_score)` | Lead scores were recomputed | This must not happen in P1. Investigate before P2 |
| `FAIL  runs is empty` | Something wrote to the orchestration tables | P1 ships no writer. Investigate before P2 |
| The CSV header has 12 or 14 fields | The export contract broke | `tests/test_boundaries.py::test_csv_export_still_thirteen_columns` should have caught this — re-run T2 Step 3 |
| A "Runs" link appears | Scope crept into P1 | P1 ships schema only |
| The page will not load | A stale process holds the port | Re-run the stop command in *Before you start* |

**Screenshot expected:** the dashboard at `http://127.0.0.1:5000/`, showing 459 leads.
**Logs to verify:** the Flask startup line names port 5000 and no error follows it.
**Database values to verify:** 459 leads · `intent_score` max 164.28 · avg 42.29 · the three
orchestration tables empty.
**API response to verify:** covered by Step 4 — all 17 endpoints answer with their frozen shapes.

**Acceptance:** ✅ 459 leads, fingerprint unchanged, orchestration tables empty, 13 CSV columns,
31 navigation tests pass, dashboard renders unchanged.

---

## Rollback verification

**Purpose:** prove P1 can be undone. A rollback plan nobody has run is a guess.

**Rollback command (from `docs/34-implementation-plan.md` P1):** `alembic downgrade 0003`

### Step 1 — Prepare a copy ⚠️
```
> powershell "Copy-Item data\leads.db data\p1-rollback.db -Force"
> $env:ALEMBIC_DB_URL = "sqlite:///data/p1-rollback.db"
> echo $env:ALEMBIC_DB_URL
```
→ The `echo` must print `sqlite:///data/p1-rollback.db`. If it prints nothing, **stop.**
**Reversal:** delete `data\p1-rollback.db` (Step 5).

### Step 2 — Apply, then roll back
```
> .\.venv\Scripts\python.exe -m alembic upgrade head
> .\.venv\Scripts\python.exe -m alembic downgrade 0003
```
→ **Expected:** one `Running upgrade` line, then one `Running downgrade` line. No errors.

### Step 3 — Confirm the rollback was complete
```
> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\p1-rollback.db --revision 0003 --skip-p1
```
→ **Expected:** `OK — all 6 checks passed.` — integrity, the revision back at
`0003_net_infrastructure`, and 459 leads with their fingerprint intact.
→ `--skip-p1` asserts nothing about the 0004 tables, which is correct here: the downgrade removed
them.

### Step 4 — Confirm the application still runs after a rollback
```
> .\.venv\Scripts\python.exe -m pytest tests/test_navigation_and_pages.py
```
→ **Expected:** `31 passed`.
→ Nothing in the application reads `runs`, `jobs` or `run_events` yet, so removing them cannot break
it. That is why P1 is a low-risk phase.

### Step 5 — Clean up ⚠️
```
> powershell "Remove-Item data\p1-rollback.db*, data\p1-test.db* -Force -ErrorAction SilentlyContinue"
> $env:ALEMBIC_DB_URL = $null
```
→ **Clearing the variable matters.** Leaving it set means the next `alembic` command you run in this
terminal silently targets a file that no longer exists.

**Acceptance:** ✅ The downgrade removes all three tables and the added column, leaves 459 leads,
returns the version to `0003`, and the application still passes its navigation tests.

---

## Coverage — every acceptance criterion maps to a step

| P1 acceptance criterion (doc 34) | Verified by |
|---|---|
| Upgrade / downgrade / upgrade on a live-DB copy | **T4** Steps 4–7 |
| `alembic heads` = 1 | **T3** Step 1 |
| Illegal transition raises naming both states | **T6** Step 3; exhaustively **T6** Step 6 |
| The two `AWAITING_*_REVIEW` states have **no timeout** | **T6** Steps 4–5 (model) + **T5** Step 1, *Constraints* (schema) |
| `PRAGMA foreign_key_list(ai_calls)` reports the run FK | **T5** Step 1, *Foreign keys* |
| Legacy contract | **T7** Steps 1–5 |
| *Metric:* 459 leads intact | **T4** Steps 5–7, **T7** Step 1 |
| *Metric:* 1 head | **T3** Step 1 |
| *Metric:* 0 changes to existing tables beyond `scrape_runs.run_id` | **T5** Step 2 |
| *Deliverable:* 12 `RunState` values | **T6** Step 1 |
| *Deliverable:* `JobState`, transition table | **T6** Step 6; **T2** Step 2 (44 tests) |
| *DB:* the five named indexes, column order included | **T5** Step 1, *Indexes* |
| *DB:* integrity and no unexpected tables | **T5** Step 1, *Database integrity* / *Tables* |
| *Rollback:* `alembic downgrade 0003` | **Rollback verification** |

---

## Sign-off

| Check | Pass |
|---|---|
| T1 — lint and format clean | ☐ |
| T2 — 310+ tests pass, 0 failed | ☐ |
| T3 — exactly one migration head | ☐ |
| T4 — upgrade/downgrade/upgrade on a live-DB copy, 459 leads intact | ☐ |
| T5 — all 26 schema checks pass; `test_migrations.py` 9 passed | ☐ |
| T6 — 12 states; illegal transition raises; gates have no timeout; all pairs exhaustive | ☐ |
| T7 — legacy fingerprint intact, orchestration tables empty | ☐ |
| Rollback executed and verified | ☐ |
| `data\p1-test.db` and `data\p1-rollback.db` removed; `ALEMBIC_DB_URL` cleared | ☐ |
| No unexpected errors in any output | ☐ |

**Tester:** ______________________  **Date:** ______________  **Result:** ☐ Pass ☐ Fail
