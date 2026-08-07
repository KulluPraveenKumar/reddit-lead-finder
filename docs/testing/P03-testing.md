# Manual Testing Guide — P3: Run service, API, run pages

> ⚠️ **This is P3 of the frozen P0–P30 plan ([34](../34-implementation-plan.md)) — NOT the legacy
> "Phase 03."** [`testing/phase-03-testing.md`](phase-03-testing.md) belongs to the **old eight-phase
> numbering** and is a historical record. The two schemes are unrelated.

Written so a **non-developer can validate this phase without guessing**. Every step states what you
should see. If what you see differs, that step's *Possible failure* section tells you what it means.

- **Time:** ~40 minutes for the full suite, ~10 minutes for the smoke path (T1–T3).
- **You need:** a terminal and a web browser. **No API key and no internet** except for T7, which is
  the only test that scrapes Reddit for real and is clearly marked.
- **Destructive steps:** T7 only, and it writes leads to `data\leads.db` exactly as pressing the
  scrape button has always done. Everything else uses a temporary database that is deleted after.

Throughout, `>` marks a command to run and `→` marks what you should see.

---

## Before you start

> cd <the folder containing pyproject.toml>

**If the app is already running**, stop it — a stale process keeps port 5000 and serves you *old
code*, which looks exactly like a broken change:

> powershell "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*dashboard*' } | Stop-Process -Force"

**Record the state of the live database, so you can prove it afterwards:**

> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db

→ Ends with `OK — all 25 checks passed.`

---

# T1 — The suite is green and the code is clean

**Purpose:** prove the phase ships without lint errors, formatting drift, or failing tests.
**Preconditions:** none.

### Step 1 — Lint

> .\.venv\Scripts\python.exe -m ruff check .

→ **Expected:** `All checks passed!`

### Step 2 — Formatting

> .\.venv\Scripts\python.exe -m ruff format --check .

→ **Expected:** `90 files already formatted`

### Step 3 — The full suite

> .\.venv\Scripts\python.exe -m pytest

→ **Expected:** `581 passed, 2 skipped` in roughly 3 minutes.

The two skips are both in `tests/test_net.py` and need a proxy list this machine does not have
(`PROXY_FILE is not set`). They are skipped by design, not broken. To see for yourself which two:

> .\.venv\Scripts\python.exe -m pytest -q -rs

→ Two `SKIPPED` lines, both mentioning proxies.

### Step 4 — No deprecation warnings

> .\.venv\Scripts\python.exe -m pytest -W error::DeprecationWarning

→ **Expected:** the same counts. This run turns every deprecation warning into a failure.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `N files would be reformatted` | A file was edited after formatting | Run `ruff format .` and re-run |
| A test named `..._p95_...` fails | The machine was busy during a timing test | Close other applications and re-run that one test |
| `ModuleNotFoundError` | Dependencies are missing | `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` |

---

# T2 — The scrape button now takes you somewhere

**Purpose:** the phase's headline change. The button used to show "Scrape complete!" after five
seconds whether or not anything happened.
**Preconditions:** T1 passed.

### Step 1 — Start the dashboard

> .\.venv\Scripts\python.exe main.py dashboard

→ A panel saying `Dashboard running at http://127.0.0.1:5000`.

### Step 2 — Open it

Open **http://127.0.0.1:5000** in your browser.

→ The dashboard loads. In the top navigation there is now a **Runs** link, between *Dashboard* and
*Configuration*.

### Step 3 — Check what will be scraped

Click **Configuration**.

→ You see your subreddit list. **Write down how many subreddits are listed** — call it **N**. If the
list is empty, add two (for example `SaaS` and `startups`) before continuing.

### Step 4 — Press the button

Go back to the **Dashboard** and click **Run Scrape Now** in the right-hand sidebar.

→ The button says `Starting...` and then **the browser navigates to a new page**, `/runs/<number>`.

> ⚠️ **This starts a real scrape against Reddit.** If you do not want that right now, skip to T3 and
> come back. Nothing breaks either way.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| The old "Scrape complete!" message | The page was cached | Hard-refresh with Ctrl+F5 |
| Stays on the dashboard, says "running in the background" | `orchestration.enabled` is `false` in `config.yaml` | That is the rollback setting. Set it to `true` for this test |
| "Could not start the run" | The dashboard stopped | Check the terminal you started it in |

---

# T3 — The run page shows what is actually happening

**Purpose:** AC2 and AC10 — real progress, and a live activity feed.
**Preconditions:** you are on a `/runs/<number>` page from T2.

### Step 1 — Read the page

→ You should see:
- **Run #<number>** as the heading
- a **state** label — `scraping` while it works, `complete` when done
- a **progress bar** that is not stuck at 0%
- **Leads found**, **Jobs done** (`x / N`, where N is your subreddit count from T2), **Failed**
- an **Activity** panel with lines of text

### Step 2 — Read the activity feed

→ The newest line is at the top. Near the bottom you should find lines like:

```
Subreddit review already satisfied: you chose these subreddits yourself.
Keyword review already satisfied: scoring uses the keywords you configured.
Scraping started — working through the configured subreddits one at a time.
```

**This is expected and important.** The system has review steps built in for a later phase. A scrape
you start yourself has already answered the questions those steps ask, so the run passes through
them and says so, rather than stopping to ask you again.

### Step 3 — Watch it move

Leave the page open for a minute.

→ **Jobs done** increases, the progress bar grows, and new activity lines appear at the top **without
you refreshing**. Each finished subreddit adds a line like `r/SaaS done — 3 lead(s).`

### Step 4 — Let it finish

→ When every subreddit is done, the state becomes **complete**, the bar reaches 100% and turns green,
the word `live` next to *Activity* changes to `complete`, and the **Cancel run** button greys out.

### Step 5 — Confirm the polling stopped

Leave the finished page open for two minutes, then look at the terminal running the dashboard.

→ **No new lines appear** for this run. A finished page must stop asking the server for updates.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| Progress bar stuck at 0%, jobs `0 / 0` | No subreddits are configured | Add some on Configuration and start a new run |
| Jobs done climbs but Leads found stays 0 | Normal — nothing new since the last scrape | Not a fault. Reddit had no new matching posts |
| State goes to `complete` with **Failed** above 0 | Some subreddits could not be reached | Expected behaviour: the run keeps what it collected. An amber line explains it |
| Terminal keeps logging after completion | Polling did not stop | A real defect — report it |

---

# T4 — Cancelling a run

**Purpose:** AC6. Cancel stops the queued work; the subreddit in progress finishes first.
**Preconditions:** at least **three** subreddits configured.

### Step 1 — Start a run and cancel it immediately

Press **Run Scrape Now**, and as soon as the run page appears click **Cancel run** and confirm.

### Step 2 — Read the result

→ A message appears: *"Run cancelled. The subreddit in progress will finish first."* The state
becomes **cancelled** and the Cancel button greys out.

### Step 3 — Check the activity feed

→ There is an amber line naming how many jobs were cancelled, for example
`Cancelled by the operator. 2 queued job(s) cancelled.`

You may also see one line like `Skipped r/startups — the run was cancelled.` That is the subreddit
that had already started: it is allowed to finish its current work rather than being killed halfway
through writing to the database.

### Step 4 — Try to cancel it again

Reload the page and click **Cancel run**.

→ The button is greyed out and cannot be clicked. Cancelling is final — it does not mean "pause".

---

# T5 — You cannot start two runs at once

**Purpose:** AC7. The double-click problem, solved so it cannot happen.
**Preconditions:** the dashboard is running.

### Step 1 — Start a run

Press **Run Scrape Now**. Note the run number in the URL.

### Step 2 — Open the dashboard in a second browser tab and press it again

→ You land on **the same run page, with the same number**. No second run is created.

### Step 3 — Confirm on the Runs page

Click **Runs** in the navigation.

→ Exactly **one** run is listed as `scraping`. Not two.

**Possible failure**

| You see | Meaning |
|---|---|
| Two runs both `scraping` | A real defect — the guard is not working. Report it |
| An error page | A real defect. The second press must be handled, not error |

---

# T6 — The Runs page

**Purpose:** the run history is browsable.
**Preconditions:** you have run T2–T5, so several runs exist.

### Step 1 — Open it

Click **Runs**.

→ A table with one row per run, **newest first**, showing: run number, state, leads, jobs (`done /
total`), duration and start time.

### Step 2 — Check the states read as words

→ States are spelled out — `complete`, `cancelled`, `scraping` — not shown only as a colour. Colour
is a hint, never the only signal.

### Step 3 — Open an old run

Click any run number.

→ Its page loads with the final numbers, and the state is not `live`.

### Step 4 — Try a run that does not exist

Put `/runs/999999` in the address bar.

→ A page saying **Run #999999 not found**, explaining that old runs are purged after 90 days, with a
link back. **Not** a stack trace or a blank error page.

---

# T7 — Restart recovery *(the one that proves durability)*

**Purpose:** AC3. Killing the dashboard mid-run does not lose the run.
**Preconditions:** at least **four** subreddits configured, so the run takes long enough to interrupt.

### Step 1 — Start a run and note its number

Press **Run Scrape Now**. Note the run number.

### Step 2 — Kill the dashboard while it is working

While **Jobs done** still shows fewer than the total, go to the terminal running the dashboard and
press **Ctrl+C**. If it does not stop within 30 seconds, press Ctrl+C again.

→ The terminal returns to a prompt.

### Step 3 — Confirm the browser can no longer reach it

Reload the run page.

→ The browser shows a connection error, and after a few seconds a red notice appears if the page was
still open: *"Lost contact with the server — retrying every 10 s."*

### Step 4 — Start it again

> .\.venv\Scripts\python.exe main.py dashboard

Open **http://127.0.0.1:5000/runs/<your run number>**.

### Step 5 — Watch it resume

→ Within about fifteen minutes the remaining subreddits are scraped and the run reaches **complete**.

> ⏱ **Why up to fifteen minutes.** When a process dies, the job it was working on is still marked as
> taken, held by a worker that no longer exists. The system waits out that claim — fifteen minutes —
> before handing the job to someone else. That is deliberate: taking work back sooner risks two
> workers doing the same job at once. Nothing is lost while you wait.

### Step 6 — Confirm no duplicate leads

> .\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/leads.db'); print('leads:', c.execute('select count(*) from leads').fetchone()[0]); print('duplicate reddit_ids:', c.execute('select count(*) from (select reddit_id from leads group by reddit_id having count(*)>1)').fetchone()[0])"

→ **Expected:** `duplicate reddit_ids: 0`. The interrupted subreddit was scraped twice and stored
once.

---

# T8 — The old scrape response is unchanged

**Purpose:** R20. Anything that already talked to this system keeps working.
**Preconditions:** the dashboard is running.

### Step 1 — Call the endpoint directly

> .\.venv\Scripts\python.exe -c "import urllib.request,json; r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:5000/api/scrape', method='POST')); print(r.status, json.load(r))"

→ **Expected:** `200 {'ok': True, 'message': 'Scrape started in background', 'run_id': <number>}`

The two original fields — `ok` and `message` — are **exactly** as they were. `run_id` is new, and
adding a field is safe for anything already reading the old two.

### Step 2 — Confirm the status code never changed either

Run the same command again straight away, while that run is still going.

→ **Still `200`**, with the **same** `run_id`. It does not become an error just because a run is
already going — it points you at the one that is.

---

# T9 — The rollback switch

**Purpose:** prove the phase can be turned off without touching code.
**Preconditions:** the dashboard is stopped.

### Step 1 — Turn it off

Open `config.yaml`, find the `orchestration:` section near the bottom, and change:

```yaml
orchestration:
  enabled: false
```

### Step 2 — Start the dashboard and scrape

> .\.venv\Scripts\python.exe main.py dashboard

Press **Run Scrape Now**.

→ The page **stays on the dashboard** and says *"Scrape running in the background. Refresh in a few
minutes."* You are **not** taken to a run page, and no new run appears under **Runs**.

This is the pre-P3 behaviour, restored exactly.

### Step 3 — Note what comes back

→ With the switch **off**, the scrape also collects **keyword** and **user** leads again.
With it **on**, it collects **subreddit** leads only.

> ℹ️ **This is expected, and it is the one behaviour this phase deliberately changed.** The job
> system only knows how to run the subreddit scraper so far; keyword and user collection return in
> later phases. If you need all three today, either leave this switch off, or run
> `python main.py scrape` from a terminal — that command still runs all three and always will.

### Step 4 — Turn it back on

Set `enabled: true` again and restart the dashboard. Confirm the button takes you to a run page.

> ⚠️ **Do not leave it set to `false` and then re-run T1.** One test asserts that the *shipped*
> configuration has the switch on, so the suite reports one failure for as long as the file says
> `false`. That is the test doing its job — rolling back is something you do to a running
> installation, not something you commit — but it looks like a broken build if you are not expecting
> it. Set it back to `true` before re-running the suite.

---

# T10 — System health

**Purpose:** the queue is visible to an operator.
**Preconditions:** the dashboard is running.

### Step 1 — Look at health

> .\.venv\Scripts\python.exe -c "import urllib.request,json; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health'))['queue'], indent=2))"

→ Something like:

```json
{
  "queued": 0,
  "running": 0,
  "failed": 0,
  "oldest_queued_at": null,
  "inprocess_worker": true,
  "worker_id": "yourpc-12345-a1b2c3"
}
```

### Step 2 — Understand the two important fields

- **`inprocess_worker: true`** — this dashboard is executing jobs itself.
- **`oldest_queued_at`** — when the longest-waiting job was queued. `null` means nothing is waiting.
  **If this is more than an hour old while `queued` is above 0, work is stuck** and nothing is
  processing it. That is the field to watch.

### Step 3 — Confirm the live database is still intact

> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db

→ `OK — all 25 checks passed.` — the same as before you started.

---

# Sign-off

Complete this table. **A phase is not done until a human has run this guide** — see
[EXECUTION_MODE_LOCK §4](../EXECUTION_MODE_LOCK.md).

| Test | What it proves | Pass / Fail | Tester | Date | Notes |
|---|---|---|---|---|---|
| T1 | Suite green, no lint or deprecation issues | | | | |
| T2 | The scrape button opens a run page | | | | |
| T3 | Progress and the live activity feed are real | | | | |
| T4 | Cancel stops queued work | | | | |
| T5 | Two runs cannot start at once | | | | |
| T6 | The run history is browsable | | | | |
| T7 | A killed process resumes with no duplicates | | | | |
| T8 | The old scrape response is unchanged | | | | |
| T9 | The rollback switch works | | | | |
| T10 | Queue health is visible; the database is intact | | | | |

**Signed:** ______________________  **Date:** ______________
