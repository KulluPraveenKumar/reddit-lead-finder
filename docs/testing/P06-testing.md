# P06 — Manual Testing Guide · Watermarks & incremental discovery

**Phase:** P6 — Watermarks & incremental discovery · [34 §P6](../34-implementation-plan.md)
**Written:** 2026-08-08 · **Companion:** [P6-IMPLEMENTATION-REVIEW.md](../P6-IMPLEMENTATION-REVIEW.md)

> **Who this is for.** Someone who can copy a command into a terminal and read what comes back. You
> do **not** need to know Python, SQL or Reddit. Every step says what you should see; if you see
> something else, the step says what that means.

---

## Before you start

### What P6 added, in one paragraph

Until now the collector re-read the same pages every time it ran. P6 gives it a **memory**: a
"watermark" per subreddit that records how far it has already read. A poll now asks Reddit one
question — *"what is new?"* — and when the answer is *"nothing"*, it costs **one request and writes
no data**. P6 also adds the thing that makes this safe: if more posts appeared than a single request
can carry, the gap is reported as an **error**, never quietly ignored. A post that was never seen is
a lead that never existed, and that is the failure this phase exists to prevent.

### One thing that is deliberately **not** here

**There is no "density" test.** The plan for this phase described choosing between two ways of
downloading post text depending on how many posts needed it. Phase 5 measured that one of those two
ways — the ordinary Reddit listing page — **contains no post text at all**. The feed already carries
the text, so the choice had nothing to choose between and was removed. If a step seems to be
missing, this is why. See [P6-IMPLEMENTATION-REVIEW §2.3](../P6-IMPLEMENTATION-REVIEW.md).

### ⚠️ Mutations and rollback

This guide **never edits a tracked project file.** Where a test needs different settings it writes a
**temporary** file in a scratch folder outside the project. **T10** proves the project was left
clean.

### Prerequisites

Open PowerShell in the project folder. Every command below is PowerShell.

```powershell
cd $HOME\Downloads\reddit-scraper
.\.venv\Scripts\python.exe --version
```

**Expected:** `Python 3.12.x` (any 3.11+ is fine).

```powershell
git status --short
```

**Expected:** no output. If anything is listed, stop — the tree is dirty and results will not be
trustworthy.

---

## T1 — The database gained its two new tables 🔒

```powershell
.\.venv\Scripts\python.exe scripts\check_schema.py
```

**Expected:** the last line reads `OK — all 31 checks passed.`

Scroll up to the block headed **`Discovery (0005)`**. All six lines must say `PASS`. The most
important is:

```
PASS  ux_watermarks_listing exists — listing rows are actually unique
```

**Why this one matters.** SQLite has a quirk: an "everything must be unique" rule *ignores* rows
with a blank field. The watermark's search-term field is blank for ordinary subreddit polls, so the
obvious rule would not have protected them, and the collector could have ended up with two memories
of the same subreddit — each hiding posts from the other. This line proves the working rule shipped.

**If it says FAIL:** the migration did not apply. Run `.\.venv\Scripts\python.exe -m alembic upgrade head`.

---

## T2 — The original 459 leads are untouched 🔒

```powershell
.\.venv\Scripts\python.exe scripts\check_schema.py | Select-String -Pattern "459|intent_score"
```

**Expected:** three lines, all `PASS`, including `the 459 original leads are all still present`.

**Why:** every phase must prove it did not disturb the data that was there before. A migration that
quietly dropped a row would be caught here and nowhere else.

---

## T3 — A poll that finds nothing costs one request and writes nothing 🔒

This is the phase's whole objective.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_discovery_handler.py -k "idle_poll" -v
```

**Expected:** `1 passed`. The test name is
`test_an_idle_poll_issues_one_request_and_creates_no_rows`.

**Read the count, not the colour.** If it says `no tests ran` or `0 selected`, that is a **failure**,
not a pass — a filter that matches nothing still exits successfully. This exact defect was found in
P4 and again in P5.

---

## T4 — Losing posts is reported as an error 🔒

The dangerous failure: more posts appear between two polls than one request can carry, so the older
ones scroll out of reach and are never collected.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_watermarks.py tests\test_discovery_handler.py -k "overflow" -v
```

**Expected:** **12 passed** — and read that number. Most of them are the cases that must **not**
raise the alarm (a first-ever poll, a memory that has never advanced, an empty subreddit, an ordinary
poll). The rest prove the alarm fires, that the recovery walk actually runs, and that the next poll
happens sooner.

**Why so many negatives.** An alarm that goes off constantly is an alarm nobody reads. Proving it
stays quiet is as important as proving it fires.

---

## T5 — The collector never mistakes a failure for silence 🔒

If Reddit blocks a request and the collector reads that as *"this subreddit has nothing new"*, it
will believe the subreddit is dead forever.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_discovery_handler.py -k "transport or empty_subreddit" -v
```

**Expected:** **3 passed.**

---

## T6 — The polling schedule is sane and costs less than the daily budget

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_discovery_policy.py tests\test_discovery_triage.py -v
```

**Expected:** **33 passed.**

Two are worth knowing by name:

- `test_steady_state_stays_within_eighty_requests_a_day` — the budget this phase promised.
- `test_the_policy_computes_an_interval_in_under_a_millisecond` — the speed budget.

---

## T7 — The off switch still works 🔒

`rss_enabled: false` is the rollback: it puts the collector back on the old page-reading path.
**This writes a temporary settings file outside the project — it does not touch `config.yaml`.**

```powershell
$scratch = Join-Path $env:TEMP "p06-rollback"
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
@'
discovery:
  rss_enabled: false
'@ | Out-File -FilePath (Join-Path $scratch "config.yaml") -Encoding utf8
Get-Content (Join-Path $scratch "config.yaml")
```

**Expected:** the two lines you just wrote.

Now prove the code path is exercised:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_discovery_handler.py -k "rss_disabled or html_sourced" -v
```

**Expected:** **2 passed.**

Clean up:

```powershell
Remove-Item -Recurse -Force $scratch
git status --short
```

**Expected:** no output from `git status`. Nothing tracked was edited.

---

## T8 — The rollback actually rolls back 🔒

[Lock §4](../EXECUTION_MODE_LOCK.md) requires the rollback to be **executed**, not just described.
This works on a **copy**, never the real database.

```powershell
$scratch = Join-Path $env:TEMP "p06-downgrade"
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
.\.venv\Scripts\python.exe -c "import sqlite3,sys; s=sqlite3.connect('data/leads.db'); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close(); s.close()" "$scratch\leads.db"
$env:ALEMBIC_DB_URL = "sqlite:///$scratch/leads.db"
.\.venv\Scripts\python.exe -m alembic downgrade 0004_orchestration
.\.venv\Scripts\python.exe -m alembic current
```

⚠️ **The copy uses SQLite's backup API, not `Copy-Item`, and that is not fussiness.** The database
runs in WAL mode, which means recent changes may live in a separate `-wal` file. Copying only
`leads.db` can produce a stale snapshot — so the test would pass against a database that is not the
one you have. `tests/test_migrations.py::test_backup_uses_sqlite_api` exists for the same reason.

**Expected:** the last line reads `0004_orchestration`. The two new tables are gone.

Now put it back, which is the half that proves the rollback is not one-way:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
$env:ALEMBIC_DB_URL = $null
Remove-Item -Recurse -Force $scratch
```

**Expected:** `0005_discovery (head)`, then no errors.

⚠️ **`$env:ALEMBIC_DB_URL = $null` is not optional.** Leaving it set would point every later command
at a deleted file.

---

## T9 — Boundaries hold 🔒

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_boundaries.py -v
```

**Expected:** **29 passed.** Three by name:

- `test_discovery_makes_no_ai_calls` — the scheduler must cost nothing to run.
- `test_the_density_heuristic_was_not_reintroduced` — the removed feature stays removed.
- `test_conditional_get_has_not_been_reintroduced` — same, from P5.

---

## T10 — The full suite, and a clean tree 🔒

```powershell
.\.venv\Scripts\python.exe -m pytest
```

**Expected:** `887 passed, 2 skipped`. (P5's baseline was 803 passed, 2 skipped.)

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
git status --short
```

**Expected:** `All checks passed!`, then `NNN files already formatted`, then **no output** from
`git status`.

---

## T11 *(optional — this is the only step that goes online)*

The one check that notices Reddit changing. It costs two requests and roughly a minute.

```powershell
.\.venv\Scripts\python.exe scripts\validate_feed_parity.py --subreddit startups
```

**Expected:** the last line reads `OK — 25 posts agree on all 7 compared fields.`

You will also see a block headed **Tolerated differences**, listing every post with a `body`
difference. **That is expected and is the P5 finding**: the ordinary Reddit page carries no post
text, the feed does. It is a difference between two Reddit endpoints, not a fault in this project.

**If this step fails**, do not treat it as a P6 defect until you have read what it printed — it is
designed to detect Reddit changing its markup, which is outside this project's control.

---

## Sign-off

**Blocking tests.** **T1, T3, T4, T5, T7, T8, T9 and T10 are not optional.** T3 and T4 are the
phase's central claims; T5 protects against believing a failure; T7 and T8 protect the ability to
undo; T9 protects frozen architecture; T10 is the gate. A guide signed with any of these unrun
records a verification that did not happen.

**T11 is optional** and is the only step that contacts Reddit.

| Test | What it proves | Pass | Fail | Notes | Tester |
|---|---|---|---|---|---|
| **T1** 🔒 | **The two new tables exist, with the constraint that actually holds** | | | | |
| **T2** 🔒 | **The 459 original leads are untouched** | | | | |
| **T3** 🔒 | **An idle poll costs one request and writes nothing** | | | | |
| **T4** 🔒 | **A lost-post gap is an error — and ordinary polls stay quiet** | | | | |
| **T5** 🔒 | **A blocked request is never read as an empty subreddit** | | | | |
| T6 | The schedule is sane and inside the 80-request daily budget | | | | |
| **T7** 🔒 | **`rss_enabled: false` switches feeds off; nothing tracked was edited** | | | | |
| **T8** 🔒 | **The migration rolls back and forward again, on a copy** | | | | |
| **T9** 🔒 | **Boundaries hold; the removed feature stayed removed** | | | | |
| **T10** 🔒 | **The full suite passes and the tree is clean** | | | | |
| T11 *(optional)* | Reddit has not changed its markup | | | | |

**Signed:** ______________________  **Date:** ______________

---

## Command verification record

[Lock §3 step 8](../EXECUTION_MODE_LOCK.md) requires every command in this guide to have been
**executed as written** before the guide is finalised.

| When | Which commands | Status |
|---|---|---|
| 2026-08-08, post-implementation | Prerequisites · T1 · T2 · T3 · T4 · T5 · T6 · T9 · T10 | ✅ Executed and verified as written |
| 2026-08-08, **second pass** | **T7 and T8** — the two whose *shell* commands had not been executed | ✅ Executed verbatim, including cleanup and the `$env:ALEMBIC_DB_URL = $null` reset |
| 2026-08-08 | **T11** | ✅ Executed against `r/startups`, exit 0 |

⚠️ **T7 and T8 were marked verified before their commands had been run.** Only their `pytest` lines
had been executed; the scratch-file mechanics of T7 and the whole copy/downgrade/upgrade sequence of
T8 had not. That is the defect [P5-IMPLEMENTATION-REVIEW §3.3](../P5-IMPLEMENTATION-REVIEW.md) names
in as many words — *a documented check that was never executed is worse than an absent one, because
it is counted as coverage* — and it was caught in review rather than by the guide. Both have since
been executed end to end, and executing T8 is what found the WAL bug below.

**Every `-k` filter in this guide asserts a count**, following P5's **F5**: a filter that matches
nothing exits successfully, so "it went green" proves nothing on its own.

**Four expected counts were corrected by executing them**, which is the entire reason this record
exists — every one had been written from an estimate:

| Step | Written | Actual |
|---|---|---|
| **T4** | 8 passed | **12 passed** |
| **T5** | 4 passed | **3 passed** |
| **T6** | 52 passed | **33 passed** |
| **T9** | "all pass" — not a number | **29 passed** |

**And T8 was WAL-unsafe as first written.** It used `Copy-Item data\leads.db`, which copies the
database file but not its `-wal` sidecar — so the rollback could have been proved against a stale
snapshot. It now uses SQLite's backup API. Found by executing the step.

**And the F5 defect reproduced during verification.** Two filters were first run with the `-k`
expression unquoted; PowerShell split it on spaces and pytest selected **nothing**, reporting
`no tests ran` — which exits successfully. The commands in this guide quote every `-k` expression,
and that quoting is load-bearing rather than stylistic.
