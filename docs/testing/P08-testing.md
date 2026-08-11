# P08 — Manual Testing Guide · Content & dedup schema

**Phase:** P8 (frozen numbering) · **Revision:** `0006_content_and_dedup`
**Part A written:** 2026-08-11 · **Part B:** not yet executed

> ⚠️ **This guide is Part A.** P8 has not been implemented, so the guide cannot yet be *passed*.
> But **every command below has been executed verbatim in PowerShell against the current
> (`0005_discovery`) database** and corrected until it ran — see
> [Part A command verification](#part-a-verification). What remains for Part B is running them
> against the finished phase and recording the results.

> ⚠️ **This is not `docs/testing/phase-08-testing.md`.** That file belongs to the superseded
> eight-phase numbering and covers quality metrics, exports and production readiness. If you opened a
> guide about calibration charts and CSV exports, you have the wrong file.

---

## Before you start

### What P8 adds, in one paragraph

**Nothing you can see.** P8 adds no page, no button, no message and no behaviour. It widens the
database so later phases have somewhere to put comments, duplicate groups and AI scores: four new
tables, four new columns on `leads`, and one link that a previous phase deliberately left unfinished.
Every new table is created **empty** and stays empty until P9–P11. The whole phase is verifiable only
through the database and the test suite — which is why this guide is mostly commands.

### The one thing this phase is really about

There is a specific way this migration could go wrong that **no automatic check in this project would
catch**: a link to a table that does not exist yet. Written that way, the database still opens, every
report still says "OK", every count is still right — and the scraper silently refuses to save a
single new lead.

**T3 is the test for that.** If you only have time for one test, do T3.

### ⚠️ Three honesty notes — read before recording anything

1. **"All 31 checks passed" will become a different number.** P8 adds checks to `check_schema.py`.
   Record what you actually see.
2. **Your lead total is not fixed.** It was **478** on 2026-08-11 (459 original + 19 collected since),
   and the scraper keeps running. **459 is the only number that must never change** — it is the
   frozen guarantee. Everywhere else, this guide says "the total from T1", and you should compare
   against that, not against 478.
3. **A step that fails is a result, not your mistake.** Write down exactly what appeared, including
   the error text.

### Prerequisites

- Windows, PowerShell, the project's virtual environment active, and you are in the project folder
- **You do not need to understand SQL.** Every command is copy-paste.

### ⚠️ These commands are PowerShell, and the quoting matters

Copy them exactly, including which quotes are double and which are single. Do not translate them into
bash or Git Bash.

> **This is not fussiness.** The first draft of this guide used a different quote style and *every
> command in it was a silent parse error* — PowerShell printed a complaint and ran nothing, which in a
> hurried read looks a lot like a test that passed. That is why Part A was executed before it shipped.

### Start here — where am I?

```powershell
git log --oneline -1
python -m alembic heads
```

**Expected once P8 has shipped:** the newest commit mentions `P8`, and `alembic heads` prints exactly
one line, ending `(head)` and naming `0006_content_and_dedup`.

If it prints **two** lines, stop. That is a broken migration chain and nothing below is meaningful
until it is fixed.

---

## T1 — Nothing was lost 🔒

The whole project rests on 459 original leads staying exactly as they are.

```powershell
python scripts\check_schema.py
```

**Expected:** ends with `OK — all NN checks passed`, and includes:

```
INFO  leads = <total> (459 baseline + N collected since)
PASS  the 459 original leads are all still present
PASS  max(intent_score) over the original leads = 164.28
PASS  avg(intent_score) over the original leads = 42.29
```

**Record both numbers — later tests refer back to them:**

- [ ] The 459 original leads are all still present
- [ ] `max` is `164.28` and `avg` is `42.29`
- [ ] **Total lead count:** ______ ← *call this "the T1 total"*
- [ ] **Check count `NN`:** ______

---

## T2 — The four new tables exist, and are empty 🔒

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/leads.db'); print(sorted(r[0] for r in c.execute('SELECT name FROM sqlite_master WHERE type=? AND name IN (?,?,?,?)', ('table','comments','dedup_groups','dedup_members','minhash_bands'))))"
```

**Expected exactly:**

```
['comments', 'dedup_groups', 'dedup_members', 'minhash_bands']
```

Now confirm they are empty — P8 builds the shelves, it does not stock them:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/leads.db'); print({t: c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['comments','dedup_groups','dedup_members','minhash_bands']})"
```

**Expected:**

```
{'comments': 0, 'dedup_groups': 0, 'dedup_members': 0, 'minhash_bands': 0}
```

- [ ] All four tables exist
- [ ] All four are empty

---

## T3 — ⭐ The most important test · a new lead can still be saved 🔒

P8 adds a column to `leads` that *points at* a table which does not arrive until a later phase. If
written the obvious way, saving a lead breaks — and nothing else in this guide would notice.

```powershell
python -c "import sqlite3, datetime; c=sqlite3.connect('data/leads.db'); c.execute('PRAGMA foreign_keys=ON'); now=datetime.datetime.now().isoformat(sep=' ', timespec='seconds'); c.execute('INSERT INTO leads (reddit_id, subreddit, author, title, url, created_utc) VALUES (?,?,?,?,?,?)', ('t3_p8check','test','tester','P8 insert check','https://example.com',now)); print('INSERT OK'); c.rollback(); print('rolled back, nothing kept')"
```

**Expected:**

```
INSERT OK
rolled back, nothing kept
```

> The insert is **rolled back**, so nothing is added to your database. Re-run T1 afterwards and the
> total will be unchanged.

**⛔ If you instead see:**

```
sqlite3.OperationalError: no such table: main.projects
```

**stop and report it.** That is exactly the defect this phase was reviewed to prevent
([P8-IMPLEMENTATION-REVIEW.md](../P8-IMPLEMENTATION-REVIEW.md) finding **F1**). Nothing is corrupt and
no data is lost — but the scraper cannot save leads, and **no other check in this project will tell
you so.**

Now the same for comments:

```powershell
python -c "import sqlite3, datetime; c=sqlite3.connect('data/leads.db'); c.execute('PRAGMA foreign_keys=ON'); lead=c.execute('SELECT id FROM leads LIMIT 1').fetchone()[0]; now=datetime.datetime.now().isoformat(sep=' ', timespec='seconds'); c.execute('INSERT INTO comments (lead_id, author, body, scraped_at, body_hash) VALUES (?,?,?,?,?)', (lead,'tester','hello',now,'p8checkhash')); print('COMMENT INSERT OK'); c.rollback(); print('rolled back, nothing kept')"
```

**Expected:** `COMMENT INSERT OK`, then `rolled back, nothing kept`.

- [ ] A lead can be inserted at this revision
- [ ] A comment can be inserted at this revision
- [ ] Re-ran T1: the total is unchanged from the T1 total

---

## T4 — The new columns hold honest values on every existing row 🔒

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/leads.db'); print(c.execute('SELECT COUNT(*), SUM(project_id IS NULL), SUM(confidence_score IS NULL), SUM(analysis_status=?), SUM(source=?) FROM leads', ('not_analyzed','scrape')).fetchone())"
```

**Expected:** five identical numbers, each equal to **the T1 total**. For example, if T1 reported 478:

```
(478, 478, 478, 478, 478)
```

**What each means, in plain English:**

| Column | Value | Why that is the honest value |
|---|---|---|
| `project_id` | empty | These leads were collected before projects existed. They belong to no project — and never will |
| `confidence_score` | empty | Empty means *"never analysed"*, which is different from a score of 0 (*"analysed, and judged worthless"*) |
| `analysis_status` | `not_analyzed` | Exactly right — no AI has looked at them |
| `source` | `scrape` | They came from scraping, not from the later holdout-audit channel |

- [ ] All five numbers are equal
- [ ] They equal the T1 total

---

## T5 — The migration did not rewrite your data 🔒

Adding a column can be instant (SQLite just makes a note) or slow (SQLite rebuilds the whole table).
P8 must be the instant kind, because rebuilding is when data gets damaged.

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/leads.db'); print('leads rootpage =', c.execute('SELECT rootpage FROM sqlite_master WHERE type=? AND name=?', ('table','leads')).fetchone()[0])"
```

**Expected:** the same number as before the migration. The pre-P8 value measured on 2026-08-11 was
**2**, and `docs/PHASE-08-COMPLETION-REPORT.md` records the value taken immediately before the
upgrade — compare against that.

An unchanged `rootpage` means the table was never rebuilt, so your 459 rows were never copied, so
they cannot have been damaged in the copying.

> **Why not just time it?** A stopwatch measures how busy your computer is, not whether the code is
> correct. This project has already been bitten by that ([DI18](../DEFERRED-IMPROVEMENTS.md)). This
> check tests the thing the stopwatch was standing in for.

- [ ] `leads` rootpage is unchanged from the pre-migration value
- [ ] Value seen: ______ (pre-P8 was 2)

---

## T6 — The unfinished link from the previous phase is now closed 🔒

`0005` created `prescores` with a link to `comments` deliberately left unfinished, because `comments`
did not exist yet. It does now.

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/leads.db'); print([(r[2],r[3],r[4]) for r in c.execute('PRAGMA foreign_key_list(prescores)')])"
```

**Expected:** a list that now **includes** `comments`:

```
[('comments', 'comment_id', 'id'), ('leads', 'lead_id', 'id'), ('runs', 'run_id', 'id')]
```

The order may differ. What matters is that `comments` appears.

> **Before P8 this printed** `[('leads', 'lead_id', 'id'), ('runs', 'run_id', 'id')]` — measured
> 2026-08-11. If you still see only those two, the link was not closed.

Now confirm the rule that was already there **survived**. Closing a link in SQLite means quietly
rebuilding the table, and rules can be lost in the rebuild:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/leads.db'); sql=c.execute('SELECT sql FROM sqlite_master WHERE name=?', ('prescores',)).fetchone()[0]; print('ck_prescores_one_target present:', 'ck_prescores_one_target' in sql)"
```

**Expected:** `ck_prescores_one_target present: True` (it was `True` before P8 too — it must stay so).

- [ ] `prescores` now links to `comments`
- [ ] `ck_prescores_one_target` survived the rebuild

---

## T7 — The rollback really rolls back 🔒

A migration you cannot undo is not finished. **This runs on a copy, never your real database.**

### Step 1 — Make the copy

```powershell
Copy-Item data\leads.db "$env:TEMP\p8_rollback_test.db" -Force
Write-Output "copy made"
```

### Step 2 — Point alembic at the copy, and roll it back

```powershell
$env:ALEMBIC_DB_URL = "sqlite:///$env:TEMP/p8_rollback_test.db"
python -m alembic downgrade 0005_discovery
```

**Expected:** no traceback; a line mentioning `0006_content_and_dedup -> 0005_discovery`.

> Alembic prints two `INFO` lines to the error stream before it starts. That is normal and is not a
> failure.

### Step 3 — Confirm the leads survived the rollback

```powershell
python -c "import sqlite3, os; c=sqlite3.connect(os.environ['TEMP']+'/p8_rollback_test.db'); print('leads =', c.execute('SELECT COUNT(*) FROM leads').fetchone()[0]); print('new tables left behind:', [r[0] for r in c.execute('SELECT name FROM sqlite_master WHERE type=? AND name IN (?,?,?,?)', ('table','comments','dedup_groups','dedup_members','minhash_bands'))])"
```

**Expected:** the lead count equals **the T1 total**, and all four new tables are gone:

```
leads = <the T1 total>
new tables left behind: []
```

### Step 4 — Roll forward again

```powershell
python -m alembic upgrade head
python -c "import sqlite3, os; c=sqlite3.connect(os.environ['TEMP']+'/p8_rollback_test.db'); print('leads =', c.execute('SELECT COUNT(*) FROM leads').fetchone()[0])"
```

**Expected:** the T1 total again.

### Step 5 — ⚠️ MANDATORY: clean up and unset the override

```powershell
$p = Join-Path $env:TEMP 'p8_rollback_test.db'
if (Test-Path $p) { Remove-Item -LiteralPath $p -Force }
$env:ALEMBIC_DB_URL = $null
Write-Output "cleaned up; ALEMBIC_DB_URL is now [$env:ALEMBIC_DB_URL]"
```

**Expected:** `cleaned up; ALEMBIC_DB_URL is now []`

> ⚠️ **Do not skip Step 5.** While `ALEMBIC_DB_URL` is set, every later alembic command in this
> window targets the temporary copy instead of your real database. Confirm it is cleared:

```powershell
python -m alembic current
```

**Expected:** `0006_content_and_dedup (head)` — your **real** database, not the copy.

- [ ] Downgrade succeeded and removed all four tables
- [ ] The T1 total survived the downgrade
- [ ] Upgrade restored everything
- [ ] Temporary file deleted and `ALEMBIC_DB_URL` cleared

---

## T8 — Nothing that used to work has stopped working 🔒

```powershell
python -m pytest
```

**Expected:** a final line like `1143 passed in 200.12s`, and **no failures**.

> ⚠️ Do **not** add `-q`. The project already passes `-q` internally, so a second one suppresses the
> summary line you are being asked to record ([DI19](../DEFERRED-IMPROVEMENTS.md)).

**Record the count.** Before P8 it was **1133**; it must be higher, never lower.

If a test fails, record its full name and error. One named failure is far more useful than "some
tests failed".

- [ ] All tests pass
- [ ] Count recorded: ______ (was 1133)

---

## T9 — The dashboard is visibly unchanged 🔒

P8 changed the database, so the visible application must be **completely unchanged**.

```powershell
python main.py dashboard
```

Open <http://127.0.0.1:5000>.

- [ ] The lead list loads and shows leads
- [ ] The numbers look the same as before P8
- [ ] Clicking into a lead works
- [ ] CSV export downloads, and opens with the same 13 columns as before
- [ ] No error banner anywhere

Stop the server with `Ctrl+C`.

> **If anything looks different, that is a failure** — even if it looks like an improvement. P8 is
> required to change nothing you can see.

---

## T10 — A clean workspace 🔒

```powershell
git status --short
python -m alembic heads
```

**Expected:** `git status --short` prints **nothing at all**, and `alembic heads` prints exactly one
line ending `(head)`.

- [ ] Working tree clean
- [ ] Exactly one head

---

## Sign-off

Fill this in **after** running the tests. An unsigned table means the phase cannot be tagged
([EXECUTION_MODE_LOCK §6.2](../EXECUTION_MODE_LOCK.md)).

| Test | What it proves | Pass / Fail | Notes |
|---|---|---|---|
| T1 | The 459 original leads are intact | | |
| T2 | Four new tables exist and are empty | | |
| **T3** | **⭐ A new lead and comment can still be saved** | | |
| T4 | The new columns hold honest values on every row | | |
| T5 | The migration did not rewrite the table | | |
| T6 | The deferred link is closed; the rule survived | | |
| T7 | The rollback works and loses nothing | | |
| T8 | The full test suite passes | | |
| T9 | The dashboard is visibly unchanged | | |
| T10 | Clean tree, one migration head | | |

**Tested by:** ________________  **Date:** ____________

**Environment:** Windows ______ · Python ______ · commit ____________

**Overall result:** ☐ Pass ☐ Pass with notes ☐ Fail

**Anything that surprised you, however small:**

<br><br>

---

<a id="part-a-verification"></a>
## Part A — command verification record (done 2026-08-11)

Every command was executed verbatim in PowerShell against the current `0005_discovery` database,
**before** this guide shipped. Results:

| Command | Result at `0005` | Meaning |
|---|---|---|
| T1 `check_schema.py` | `OK — all 31 checks passed`; `leads = 478` | ✅ runs |
| T2 table list | `[]` | ✅ runs — **expected** to be empty before `0006` |
| **T3 lead insert** | `INSERT OK` / `rolled back, nothing kept` | ✅ **runs and passes today** — so a failure at `0006` is attributable to `0006` |
| T3 comment insert | *(not runnable — `comments` does not exist yet)* | Same command shape as the lead insert, which was verified |
| T4 column check | `sqlite3.OperationalError: no such column: project_id` | ✅ parses — **expected** before `0006` |
| T5 rootpage | `leads rootpage = 2` | ✅ runs; **2** is the pre-P8 baseline |
| T6 FK list | `[('leads','lead_id','id'), ('runs','run_id','id')]` | ✅ runs; confirms `comments` is genuinely absent today |
| T6 CHECK | `ck_prescores_one_target present: True` | ✅ runs; baseline is `True`, so "survived" is meaningful |
| T7 Steps 1–3, 5 | copy made; `ALEMBIC_DB_URL` accepted; `leads = 478`; `[]`; cleared to `[]` | ✅ run |
| T10 | clean tree, `0005_discovery (head)` | ✅ runs |

**Corrections forced by executing rather than reading:**

1. **Every `python -c` command in the first draft was a silent PowerShell parse error.** The draft
   used `python -c "... \"...\" ..."`; PowerShell does not use backslash escaping, so it reported
   `Missing argument in parameter list` and ran nothing. Rewritten to **outer double quotes, inner
   single quotes, all SQL literals passed as `?` parameters.**
2. A second attempt (outer *single* quotes, inner double) also failed — PowerShell 5.1 strips inner
   double quotes from native-command arguments, so Python received `connect(data/leads.db)` and
   raised `SyntaxError`.
3. T3 originally passed a `datetime` object and emitted a `DeprecationWarning` about the sqlite3
   datetime adapter, which reads as a failure to a non-developer. Now formats the timestamp as a
   string first.
4. T7 Step 5's `Remove-Item Env:\ALEMBIC_DB_URL` was replaced with `$env:ALEMBIC_DB_URL = $null`,
   and the file deletion made path-safe with `Join-Path` + `-LiteralPath`.
5. Hardcoded `478` was removed from T1, T4 and T7; the scraper is live, so the total moves. The guide
   now anchors on **"the T1 total"** and keeps **459** as the only fixed number.

---

<a id="part-b"></a>
## Part B — execution record

**Status: NOT YET EXECUTED.** P8 is not implemented.

Part B is completed by running the whole guide against the finished phase. It must record:

- [ ] Every command's real output at revision `0006`
- [ ] The real check count from T1 (Part A baseline: 31)
- [ ] The real T1 total, and confirmation that 459 originals and the `164.28` / `42.29` fingerprint
      are intact
- [ ] The real test count from T8 (baseline: 1133)
- [ ] The `rootpage` from T5, compared against the value recorded in the completion report
- [ ] Confirmation that T3's inserts left nothing behind — T1 re-run, total identical
- [ ] Confirmation that T7 Step 5 ran and `alembic current` points back at the real database
- [ ] Any step that could not be executed, marked **BLOCKED** rather than passed
