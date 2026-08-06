# Manual Testing Guide — Phase 1

Written so a **non-developer can validate the application without guessing**.
Every step states what you should see. If what you see differs, that step's
*Failure symptoms* section tells you what it means.

- **Time:** ~30 minutes for the full suite, ~8 minutes for the smoke path (T1–T6).
- **You need:** a terminal, a browser. An AI provider key only for T10–T14.
- **Nothing here is destructive** except T13, which is reversible.

Throughout, `>` marks a command to run and `→` marks what you should see.

---

## Before you start

```
> cd <the folder containing pyproject.toml>
> python -m pip install -r requirements.txt
```
→ Finishes without errors. `Requirement already satisfied` lines are normal.

**If the app is already running**, stop it first — a stale process keeps port
5000 and will serve you *old code*, which looks exactly like a broken change:

```
> powershell "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*dashboard*' } | Stop-Process -Force"
```

---

# T1 — Start the application

**Purpose:** Confirm the app boots, migrates, and reports provider status.
**Preconditions:** None.

### Step 1
```
> python main.py dashboard
```
→ Four lines, in this order:
```
+------------------------------------------------------+
| Dashboard running at http://127.0.0.1:5000           |
+------------------------------------------------------+
Migrations      up to date (0002_ai_infrastructure)
AI provider     <provider> · <model> · valid
 * Serving Flask app 'src.dashboard.app'
```
→ The terminal **stays open**. That is correct — it is the server. Leave it.

### Step 2
Read the `Migrations` line.
→ Says `up to date`. If it shows `0001_baseline -> 0002_...`, the schema is
mid-upgrade; run `python main.py migrate` and repeat T1.

### Step 3
Read the `AI provider` line.
→ Ends in `valid` if a key is configured, or `unconfigured` if not.
**`unconfigured` is not an error** — the app is fully usable without AI.

**Expected final result:** Server running, schema current, provider status shown.

**Failure symptoms**
| You see | Meaning |
|---|---|
| `ModuleNotFoundError` | Dependencies missing → re-run the `pip install` above |
| `Address already in use` | A previous server is still running → see "Before you start" |
| `No package.json found` | You ran `pnpm`/`npm`. This is a **Python** project. Use `python main.py dashboard` |
| Any traceback | Copy the full text — this is a real bug |

**How to verify success:** `python main.py migrate status` in a *second*
terminal prints `Up to date.`

---

# T2 — Open the dashboard

**Purpose:** The main page loads with its data intact.
**Preconditions:** T1 running.

### Step 1
Open <http://127.0.0.1:5000> in a browser.
→ Page loads in under a second. Dark theme, orange accents.

### Step 2
Look at the very top.
→ A **navigation bar**: `Reddit Lead Finder` · Dashboard · Configuration │
AI Provider · AI Health · About, and on the right a coloured status pill
(e.g. green **AI ready**) plus `PHASE 1 / 8`.
→ **Dashboard** is highlighted.

### Step 3
Below the heading, count the stat cards.
→ **Five**: Total Leads, New Leads, Contacted, Interested, Avg Intent Score.
→ Total Leads shows a real number (**459** on the reference database).

### Step 4
Look below the stat cards.
→ An **AI status strip** with a coloured dot, provider name, and six metrics:
Model, Last validated, Latency, Cost today, Circuit, Calls today.

### Step 5
Scroll to the charts.
→ **Three** charts render: Leads Over Time, Top Subreddits, Keyword Breakdown.

### Step 6
Scroll to the leads table.
→ Rows of leads with Title, Subreddit, Score, Status. Each row has a status
dropdown and a delete button.

### Step 7
Look at the right-hand sidebar.
→ **Three** cards only: Configuration (with a button), Run Scraper, Recent
Scrape Runs.
→ Subreddits/Keywords/Search Queries/Scoring are **deliberately not here** —
they moved to Configuration.

**Expected final result:** Dashboard shows lead metrics, charts, AI status and
operational controls — no configuration forms.

**Failure symptoms**
| You see | Meaning |
|---|---|
| No navigation bar | You are on a cached old page → hard-refresh (Ctrl+F5) |
| Charts blank | Chart.js CDN blocked. Charts need internet; everything else does not |
| `Total Leads 0` | You are pointed at an empty database, not `data/leads.db` |
| Sidebar still shows keyword boxes | Stale server → stop it and restart (T1) |

**How to verify success:** Press **F12 → Console**. → **No red errors.**

---

# T3 — Navigation reaches every page

**Purpose:** Every Phase 1 feature is reachable by clicking. This is the
specific problem this release fixed.
**Preconditions:** T2 done.

### Step 1
Click **Configuration**.
→ URL becomes `/configuration`. Heading reads *Configuration*. **Configuration**
is highlighted in the nav.

### Step 2
Click **AI Provider**.
→ URL `/settings/ai`. Heading *AI Provider*. Nav highlight moves.

### Step 3
Click **AI Health**.
→ URL `/health/ai`. Heading *AI Health*.

### Step 4
Click **About**.
→ URL `/about`. Heading *About*.

### Step 5
Click **Dashboard**.
→ Back at `/`.

### Step 6
Click the brand text **Reddit Lead Finder** (top-left).
→ Also returns to `/`.

### Step 7
On the Dashboard, click the coloured **AI pill** in the top right.
→ Opens AI Health.

**Expected final result:** All five pages reachable, none typed by hand, every
one highlights correctly.

**Failure symptoms**
| You see | Meaning |
|---|---|
| Any **404** | A nav link points at an unbuilt page — a real bug |
| Highlight stuck on Dashboard | The page is not passing `nav_active` |
| A link to Projects / Runs / Quality | Those are **future phases** and must not appear |

**How to verify success:** You never typed a URL after Step 1 of T2.

---

# T4 — Configuration page

**Purpose:** Scraper settings work from their new home.
**Preconditions:** T1 running.

### Step 1
Open **Configuration**.
→ Four cards: Subreddits, Keywords, Search queries, Scoring weights.

### Step 2
In **Subreddits**, type `testsubreddit` and press **Enter**.
→ A chip `r/testsubreddit` appears immediately.
→ Bottom-right toast: *Added r/testsubreddit*.
→ The input clears.

### Step 3
Reload the page (F5).
→ The chip is **still there** — it was saved, not just drawn.

### Step 4
Click the **×** on that chip.
→ Chip disappears. Toast: *Removed*.

### Step 5
Reload again.
→ Still gone.

### Step 6
Under **Keywords → High intent**, type `looking for a tool` and press Enter.
→ Chip appears under High intent, not under Medium.

### Step 7
In **Scoring weights**, change *Keyword weight* to `4`, click **Save weights**.
→ Toast: *Scoring weights saved. Applies to newly scraped leads.*

### Step 8
Reload.
→ Keyword weight still shows `4`.

### Step 9
Set it back to `3` and save.
→ Saved. (Leaves the system as you found it.)

**Expected final result:** Every control adds, removes and persists.

**Failure symptoms**
| You see | Meaning |
|---|---|
| Chip appears then vanishes on reload | The save failed — check the terminal for a traceback |
| Red toast | The API rejected it; the toast text names the reason |
| Nothing happens on Enter | JS error → F12 → Console |

**How to verify success:** Values survive a reload. Empty lists show italic
*"No subreddits yet…"* rather than a blank space.

---

# T5 — Dashboard is not cluttered

**Purpose:** Confirm configuration genuinely moved rather than being duplicated.
**Preconditions:** T4 done.

### Step 1
Go to **Dashboard**. Look at the sidebar.
→ *Configuration* card with an **Open Configuration** button.
→ No keyword boxes, no subreddit input, no scoring number fields.

### Step 2
Click **Open Configuration**.
→ Goes to `/configuration`.

### Step 3
Go back. Confirm **Run Scraper** and **Recent Scrape Runs** are still on the
Dashboard.
→ Both present. These are operational, not configuration, so they stay.

**Expected final result:** One home for configuration, one for operations.

**How to verify success:** Ctrl+F on the Dashboard for "High Intent" → **no match**.

---

# T6 — Health page

**Purpose:** Diagnostics render and refresh.
**Preconditions:** T1 running.

### Step 1
Open **AI Health**.
→ Sections: Provider, Efficiency, Quality, Throughput, **Providers & circuit
breakers**, **Cost if the same workload ran on each provider**, Schema & database.

### Step 2
Look at *Providers & circuit breakers*.
→ A table, one row per provider, with Circuit showing a green **closed** pill.
→ Your active provider shows `configured`; others show `no key`.

### Step 3
Look at the cost comparison table.
→ One row per provider with warm/cold cost, a cache multiplier, and a
verification date.
→ The active provider's row is tinted and tagged **active**.
→ Any row whose prices were never confirmed shows an amber **unverified** pill.

### Step 4
Look at *Schema & database*.
→ Migration `0002_ai_infrastructure (up to date)`; Leads shows your lead count.

### Step 5
Wait ~15 seconds without touching anything.
→ Values refresh silently. No flicker, no error.

**Expected final result:** Every panel populated; nothing reads `undefined`
or `NaN`.

**Failure symptoms**
| You see | Meaning |
|---|---|
| `undefined` / `NaN` | An API returned an unexpected shape — a real bug |
| Tables stuck on *Loading…* | `/api/health/providers` failed → open it directly |
| Amber cache banner | Expected on OpenRouter — see the note in T11 |

---

# T7 — Health APIs directly

**Purpose:** The JSON behind the pages is well-formed.
**Preconditions:** T1 running.

### Step 1
Open <http://127.0.0.1:5000/api/health>.
→ JSON with `status: "ok"`, `database.leads`, `schema.up_to_date: true`, `ai`.

### Step 2
Open `/api/health/ai`.
→ JSON with `provider`, `cost`, `efficiency`, `quality`, `throughput`, `routing`.

### Step 3
Open `/api/health/providers`.
→ JSON with `routing.providers[]` and `comparison[]`.

### Step 4
Open `/api/ai/usage?period=today`.
→ JSON with `calls`, `cost_usd`, token counts.

**Expected final result:** Four valid JSON documents, no HTML error pages.

**How to verify success:** Each renders as JSON, not a stack trace.

---

# T8 — Empty states

**Purpose:** Nothing looks broken when there is no data.
**Preconditions:** T1 running.

### Step 1
On **Configuration**, remove every subreddit chip.
→ Italic grey line: *"No subreddits yet. The scraper has nothing to walk until
you add one."*

### Step 2
Reload.
→ Same message, not a blank area.

### Step 3
Re-add one so later tests behave.

**Expected final result:** Empty lists explain themselves.

---

# T9 — Responsive layout

**Purpose:** Usable on a narrow window.
**Preconditions:** T1 running.

### Step 1
Narrow the browser to roughly half-width.
→ Nav wraps; links stay readable and clickable.

### Step 2
Narrow further, to phone width.
→ The status pill drops onto its own line. **No horizontal scrollbar on the
page body.**

### Step 3
On AI Health at that width, look at the provider table.
→ The **table** scrolls sideways inside its card; the page itself does not.

### Step 4
Restore full width.
→ Layout returns to normal.

---

# T10 — Configure an AI provider

**Purpose:** Key entry, validation and storage.
**Preconditions:** T1 running; a provider API key.

### Step 1
Open **AI Provider**.
→ *Provider* dropdown listing DeepSeek, OpenRouter, OpenAI.

### Step 2
If a key is already stored, note the masked fingerprint (e.g. `sk-…d115`) and
click **Replace key**.
→ An entry field appears. **The full key is never shown** — by design.

### Step 3
Paste your key. Click **Validate & save**.
→ Button reads *Validating…*; status shows *Validating…*.

### Step 4
Wait up to ~10 seconds.
→ Green toast: *Key validated and stored.*
→ Status becomes ● **Connected**, with Model, Context window, Last validated.

### Step 5
Reload.
→ Still Connected. Fingerprint shown, not the key.

### Step 6
Go to **Dashboard**.
→ The AI strip shows a green dot and your provider.
→ The nav pill reads **AI ready**.

**Expected final result:** Key stored encrypted, status Connected everywhere.

**Failure symptoms**
| You see | Meaning |
|---|---|
| *"rejected this key"* | Wrong key, or wrong provider selected for that key |
| *"Could not reach…"* | Network/firewall. Scraping is unaffected |
| *"balance exhausted"* (amber) | Key is **valid**; the account needs credit. Nothing is broken |
| *APP_SECRET_KEY is not set* | Create `.env` — see README |

**How to verify success:** `python main.py ai status` in another terminal shows
`Status: valid`.

---

# T11 — Test connection & latency

**Preconditions:** T10 done.

### Step 1
On **AI Provider**, click **Test connection**.
→ Button reads *Testing…*.

### Step 2
Wait.
→ Green toast: *Connected in NNNN ms · <model>*.
→ *Last validated* updates to now.

### Step 3
Note the latency.
→ DeepSeek direct: typically **under 3,000 ms**.
→ OpenRouter: **3,000–12,000 ms** is normal — it is a gateway, with an extra hop.

### Step 4
Open **AI Health** and click its **Test connection** button.
→ Same behaviour; the provider table's call count increments.

**Failure symptoms:** A red toast names the reason. A timeout beyond ~20 s
suggests a network block rather than a bad key.

---

# T12 — Cost tracking

**Preconditions:** T11 done (a real call has been made).

### Step 1
Open **AI Health** → *Provider*.
→ **Cost today** shows a small dollar figure (often `$0.0000` — a connection
test is nearly free).

### Step 2
Check **Caps**.
→ `$2.0000 / run · $5.0000 / day · 500 calls`.

### Step 3
Open **Dashboard**.
→ The AI strip's *Cost today* matches Health.

### Step 4
Stop the server (Ctrl+C) and restart it (T1). Reopen AI Health.
→ **Cost today is unchanged** — it is read from the database, not memory.
This is the fix for a bug where the daily cap reset on restart.

**How to verify success:** Cost survives a restart.

---

# T13 — Invalid and missing key *(reversible)*

**Purpose:** Failure states are clear and non-destructive.
**Preconditions:** T10 done. **Note your real key first — you will re-enter it.**

### Step 1
**AI Provider** → **Replace key** → type `sk-thisisdefinitelynotarealkey123` →
**Validate & save**.
→ Red toast naming the rejection.
→ Status ● **Invalid key** (red), with an explanation.

### Step 2
Reload.
→ Still shows the *previous* stored key's fingerprint.
→ **The bad key was not stored.** That is the intended behaviour.

### Step 3
Click **Remove key** → confirm.
→ Status ○ **Not configured**.

### Step 4
Go to **Dashboard**.
→ AI strip is grey; note reads *"No API key yet. AI features are disabled;
scraping is unaffected."*
→ Nav pill reads **AI not configured**.

### Step 5
Confirm the app still works: reload, use filters, open Configuration.
→ Everything works. **AI being unconfigured degrades nothing else.**

### Step 6
Re-enter your real key (T10).
→ Back to Connected.

**Expected final result:** A bad key is rejected and never stored; no key
disables only AI.

---

# T14 — Circuit breaker

**Purpose:** Understand the health signal. **Read-only.**
**Preconditions:** T10 done.

### Step 1
**AI Health** → *Providers & circuit breakers*.
→ Active provider: **closed** (green), Failures `0`.

### Step 2
Read the note under the table.
→ Explains that only **transport** failures (timeouts, 5xx, connection errors)
open the circuit — never a rejected key or empty balance, which would fail
identically on any provider.

### Step 3
Disconnect your network. Click **Test connection**. Reconnect.
→ Red toast about reachability.
→ Failures increments. After 3 consecutive failures the circuit shows **open**
with a countdown, then **half_open** while it probes.

**Expected final result:** Circuit reflects reality and recovers on its own.

---

# T15 — Restart & persistence

### Step 1
Note: lead count, cost today, provider fingerprint, one Configuration chip.

### Step 2
Stop the server (Ctrl+C).
→ Terminal returns to a prompt. No traceback.

### Step 3
Restart (T1). Reopen the dashboard.
→ All four values identical to Step 1.

---

# T16 — Regression: nothing existing broke

**Purpose:** The pre-Phase-1 product still works exactly as before.

### Step 1
On the Dashboard, type a word into **Search leads** and submit.
→ The table filters. The URL gains `?search=…`.

### Step 2
Change a lead's **status** dropdown.
→ It saves. Reload → the new status persists.

### Step 3
Click a page number in the pager.
→ Page changes; filters are preserved.

### Step 4
Open <http://127.0.0.1:5000/api/leads/export>.
→ A CSV downloads. Open it: the header is exactly
```
ID,Reddit ID,Subreddit,Author,Title,URL,Score,Comments,Intent Score,Keywords,Status,Created UTC,Scraped At
```
→ **13 columns, unchanged.** External importers depend on this.

### Step 5
Click **Run Scrape Now**.
→ Status text appears. (It will contact Reddit — this is the pre-existing
scraper and may take a while, or fail without network. Either is fine here.)

**Expected final result:** Every pre-existing behaviour intact.

---

# T17 — Automated checks

Run in a second terminal.

### Step 1
```
> python -m pytest tests/ -q
```
→ Ends with all dots and no `FAILED`. **141 passed.** Takes ~2 minutes.
→ No network is used.

### Step 2
```
> python -m ruff check .
```
→ `All checks passed!`

### Step 3
```
> python main.py migrate status
```
→ `Current: 0002_ai_infrastructure`, `Head: 0002_ai_infrastructure`, `Up to date.`

### Step 4
```
> python main.py ai status
```
→ Provider, status, masked key, model, last validated.

**Failure symptoms:** Any `FAILED` line names the test. Copy the whole block —
that is a real bug.

---

# T18 — The pnpm question

**Purpose:** Confirm the expected failure is expected.

### Step 1
```
> pnpm run dev
```
→ `ERR_PNPM_NO_PKG_MANIFEST: No package.json found`

### Step 2
```
> npm run dev
```
→ `ENOENT: no such file or directory, open 'package.json'`

### Step 3
Open **About**.
→ Explains that this is a Python project with no Node layer, and that
`python main.py dashboard` is the command.

**Expected final result:** Both fail; both are supposed to. **This is not a
bug** — there is no JavaScript build in this project by design.

---

## Sign-off

| # | Test | Result |
|---|---|---|
| T1 | Start the application | ☐ Pass ☐ Fail |
| T2 | Open the dashboard | ☐ Pass ☐ Fail |
| T3 | Navigation reaches every page | ☐ Pass ☐ Fail |
| T4 | Configuration page | ☐ Pass ☐ Fail |
| T5 | Dashboard is not cluttered | ☐ Pass ☐ Fail |
| T6 | Health page | ☐ Pass ☐ Fail |
| T7 | Health APIs | ☐ Pass ☐ Fail |
| T8 | Empty states | ☐ Pass ☐ Fail |
| T9 | Responsive layout | ☐ Pass ☐ Fail |
| T10 | Configure an AI provider | ☐ Pass ☐ Fail ☐ N/A (no key) |
| T11 | Test connection & latency | ☐ Pass ☐ Fail ☐ N/A |
| T12 | Cost tracking | ☐ Pass ☐ Fail ☐ N/A |
| T13 | Invalid / missing key | ☐ Pass ☐ Fail ☐ N/A |
| T14 | Circuit breaker | ☐ Pass ☐ Fail ☐ N/A |
| T15 | Restart & persistence | ☐ Pass ☐ Fail |
| T16 | Regression | ☐ Pass ☐ Fail |
| T17 | Automated checks | ☐ Pass ☐ Fail |
| T18 | The pnpm question | ☐ Pass ☐ Fail |

**Phase 1 is validated when T1–T9 and T15–T18 pass.** T10–T14 need a provider
key; without one, mark them N/A — the application is still correct.
