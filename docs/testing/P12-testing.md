# P12 — Manual Testing Guide

**Phase:** P12, project & BKB schema (`0007_projects_and_knowledge_base`) · **Written:** 2026-08-15

> **What P12 built:** the database can now *hold* a knowledge base. Twelve new tables, six foreign
> keys finally connected, and one optional pair that only exists if a component called `sqlite-vec`
> is installed — it is not, on this machine, and that is expected.
>
> **What you will not see:** any new page, any new number, any new lead. **Every one of the twelve
> tables is empty**, on purpose. They get filled by later phases: P14 writes the knowledge base,
> P16 creates the first project. This phase builds the shelves, not the books.
>
> **What is still yours to do:** run these steps and sign the table at the bottom. **The sign-off
> table is the phase gate** — the phase is not complete until a human has signed it.

Every expected output below was **copied from a real run on 2026-08-15**, not predicted. If what you
see differs, that is a finding worth recording, not something to explain away.

> ⚠️ **Do not add `-q` to any `pytest` command.** `pyproject.toml` already sets it, so a second one
> becomes `-qq` and hides the `N passed` line these steps ask you to read
> ([DI19](../DEFERRED-IMPROVEMENTS.md)).

> ⚠️ **Read this before T1.** Your database at `data/leads.db` **has already been upgraded to
> `0007`**, and a timestamped backup was taken automatically before it happened. This was not
> planned — the dashboard migrates on startup by design (`create_app()` → `init_db()` →
> `ensure_current()`), and starting it during validation triggered the upgrade. Nothing was lost:
> T3 is the step that proves it. The backup is
> `data/backups/leads-20260815T101958Z.db` (14,319,616 bytes), and T7 is how you go back.

Open PowerShell in the project folder first:

```powershell
cd C:\path\to\reddit-scraper
```

---

## T1 — The chain has one head, and it is the new one

A migration chain that "branches" cannot be applied at all. This is the single most important
structural check, and it is one line.

```powershell
.\.venv\Scripts\python.exe -m alembic heads
```

**Expected — exactly one line:**

```
0007_projects_and_knowledge_base (head)
```

**PASS if:** one line, and it names `0007_projects_and_knowledge_base`.
**FAIL if:** two or more lines appear (the chain has branched), or the name is `0006…` (the new
revision was not picked up).

---

## T2 — The database knows it is up to date

```powershell
.\.venv\Scripts\python.exe main.py migrate status
```

**Expected:**

```
Current: 0007_projects_and_knowledge_base
Head:    0007_projects_and_knowledge_base
Up to date.
```

**PASS if:** `Current` and `Head` are the same, and it says `Up to date.`
**FAIL if:** it says `Upgrade available.` — then the upgrade did not complete, and T3 will tell you
what state the database is actually in.

---

## T3 — 🔴 Nothing was lost. This is the step that matters most

Twelve tables were added and **six existing tables were rebuilt** to attach their foreign keys —
including `leads`, which holds the 459 original leads this whole project promises never to damage.
This checks all of it in one command.

```powershell
.\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db
```

**Expected — the last lines:**

```
  INFO  semantic_layer is disabled (bkb_embeddings absent; sqlite-vec is optional)

Legacy fingerprint
  INFO  leads = 492 (459 baseline + 33 collected since)
  PASS  the 459 original leads are all still present
  PASS  max(intent_score) over the original leads = 164.28
  PASS  avg(intent_score) over the original leads = 42.29

OK — all 76 checks passed.
```

**PASS if:** the last line reads `OK — all 76 checks passed.`, the lead count is **492**, and
`max`/`avg` are **164.28** and **42.29**.
**FAIL if:** any line says `FAIL`, or the lead count or either number has changed. **A changed
`intent_score` figure means the rebuild altered real data — stop and restore from the backup named
at the top of this guide.**

> `semantic_layer is disabled` on that first line is **correct and expected**. See T5.

---

## T4 — The twelve tables exist and are empty

Empty is the point: P12 ships the shape, later phases ship the content. A table with rows in it
after this phase would mean a migration wrote data, which the rules forbid.

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3;c=sqlite3.connect('file:data/leads.db?mode=ro',uri=True);print('leads',c.execute('select count(*) from leads').fetchone()[0]);print('projects',c.execute('select count(*) from projects').fetchone()[0]);print('bkb',c.execute('select count(*) from bkb').fetchone()[0])"
```

**Expected:**

```
leads 492
projects 0
bkb 0
```

**PASS if:** `projects` and `bkb` are **0**, and `leads` is **492** — the leads you already had,
untouched.
**FAIL if:** `projects` or `bkb` is greater than 0 (the migration seeded rows it should not have), or
`leads` is not 492.

---

## T5 — The optional semantic layer reports itself as off

There is an optional component, `sqlite-vec`, that would add two extra tables for similarity search.
It is **not installed on this machine**, and the design says that must be fine — the migration skips
those two tables and everything else still works. What must *not* happen is the system going quiet
about it.

```powershell
.\.venv\Scripts\python.exe -c "import importlib.util; print('sqlite_vec installed:', importlib.util.find_spec('sqlite_vec') is not None)"
```

**Expected:**

```
sqlite_vec installed: False
```

Now start the dashboard and look at the health page:

```powershell
.\.venv\Scripts\python.exe main.py dashboard
```

Open <http://127.0.0.1:5000/health> in a browser, find the **Schema & database** card, and read the
**Semantic layer** row.

**Expected on the page:**

```
Semantic layer    disabled (sqlite-vec not installed — optional)
```

Stop the dashboard with `Ctrl+C` when you are done.

**PASS if:** the check prints `False`, **and** the page says `disabled`. The two agree.
**FAIL if:** the page says `enabled` while the check says `False` — the system is claiming a
capability it does not have. Also FAIL if the row is missing entirely, or shows `—`.

---

## T6 — The phase's own tests pass

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_schema_0007.py
```

**Expected — the last line:**

```
29 passed in 12.08s
```

**PASS if:** it says `29 passed` and no failures. The time will differ on your machine; that is fine.
**FAIL if:** any test fails, or the count is lower than 29 (tests silently stopped being collected).

---

## T7 — 🔴 The rollback works, on a copy of your real database

This is the step that proves you can undo the phase. **It runs on a copy**, so your real database is
never at risk while you test it.

```powershell
Copy-Item data\leads.db "$env:TEMP\p12-rollback-test.db"
$env:ALEMBIC_DB_URL = "sqlite:///$env:TEMP\p12-rollback-test.db"
.\.venv\Scripts\python.exe -m alembic downgrade 0006_content_and_dedup
.\.venv\Scripts\python.exe scripts\check_schema.py --db "$env:TEMP\p12-rollback-test.db" --skip-p12
```

**Expected — the last line of the check:**

```
OK — all 51 checks passed.
```

Now put it back and confirm it returns:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\check_schema.py --db "$env:TEMP\p12-rollback-test.db"
Remove-Item Env:\ALEMBIC_DB_URL
```

**Expected — the last line:**

```
OK — all 76 checks passed.
```

**PASS if:** the downgrade gives **51 checks passed** and the re-upgrade gives **76 checks passed**.
That is the round trip: down to the old schema cleanly, back up to the new one cleanly, with the
leads intact at both ends.
**FAIL if:** either command errors, or either count differs.

> ⚠️ **Remember to run the last line** (`Remove-Item Env:\ALEMBIC_DB_URL`). If you leave that
> variable set, later commands in the same window will keep pointing at the temporary copy instead
> of your real database.

---

## T8 — The three "not built yet" score components name the right future phases

P11 shipped a score with six of nine components, and named the three that were missing. P12 changed
*which phase* is named for two of them — because P12 creates their tables **empty**, so it is not the
phase that can actually score them.

```powershell
.\.venv\Scripts\python.exe -m src.scoring
```

**Expected — the block near the top:**

```
Not shipped in P11 -- declared absent, never scored as 0.0:
    pain_phrase        P14 — `pain_points.phrases_json` is written by analyze_business
    competitor         P15 — the EntityRegistry over `bkb_entities` (created empty in 0007)
    subreddit_fit      P16 — the first `projects` row is written by `project add`
```

**PASS if:** the three lines name **P14**, **P15** and **P16**, and **no line says P12**.
**FAIL if:** any line still says `P12` — that would claim this phase supplies data it does not.

---

## T9 — The full suite is green

The long one. Roughly 6–7 minutes.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

**Expected — the last line:**

```
1905 passed, 2 skipped in 573.83s (0:09:33)
```

**PASS if:** `1905 passed` and `2 skipped`, with no failures. The duration will differ.
**FAIL if:** anything failed, or the passed count is **lower** than 1905.

> The **2 skipped** are expected and unchanged since P11: both are proxy tests that need a proxy pool
> this machine does not have (`PROXY_FILE is not set`, `no proxy pool configured on this machine`).

> ⚠️ **If a single test fails and it is `test_a5_minhash_indexes_and_queries_2000_items_under_two_seconds`,
> check what else your machine was doing.** That test asserts a CPU-time budget, and heavy background
> load inflates it — it has failed at 5.77 s against a 2.0 s budget in a run that took 849 s, then
> passed three times out of three when run on its own. Re-run just that file:
>
> ```powershell
> .\.venv\Scripts\python.exe -m pytest tests/test_dedupe_performance.py
> ```
>
> If it passes alone, that is [DI18](../DEFERRED-IMPROVEMENTS.md) and not a defect in the code. If it
> fails alone too, that **is** a finding — record it.

> ⚠️ **This step found a real regression once, and it is why it exists.** An earlier version of P12
> reported this suite green while
> `test_migrations.py::test_a1_up_down_up_on_a_copy_of_the_live_database` was broken — and **the CI
> badge was green too**, because CI has no `data/leads.db` and skips that test entirely. **Running
> this locally is not redundant with CI.** See [DI30](../DEFERRED-IMPROVEMENTS.md).

---

## Sign-off

**Every step above must be executed by a human.** A generated table is not a signed one.

| Test | What it proves | Result | Date | Signature |
|---|---|---|---|---|
| T1 | One migration head, and it is `0007` | ☑ PASS | 2026-08-15 | Praveen |
| T2 | The database is at the new revision | ☑ PASS | 2026-08-15 | Praveen |
| T3 | **The 459 original leads and their scores survived six table rebuilds** | ☑ PASS | 2026-08-15 | Praveen |
| T4 | Twelve new tables, all empty — no migration wrote data | ☑ PASS | 2026-08-15 | Praveen |
| T5 | The optional layer is off, and says so instead of going quiet | ☑ PASS | 2026-08-15 | Praveen |
| T6 | The phase's 29 tests pass | ☑ PASS | 2026-08-15 | Praveen |
| T7 | **The rollback works, down and back up, on real data** | ☑ PASS | 2026-08-15 | Praveen |
| T8 | The absent score components name P14/P15/P16, not P12 | ☑ PASS | 2026-08-15 | Praveen |
| T9 | The whole suite is green | ☑ PASS | 2026-08-15 | Praveen |

**Operator:** Praveen  **Date:** 2026-08-15

**Notes / findings:**

<br><br><br>
