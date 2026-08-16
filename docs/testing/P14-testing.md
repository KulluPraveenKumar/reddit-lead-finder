# Manual Testing — Phase 14

**`analyze_business` — a website becomes 23 sections of business knowledge, in one AI call.**

| | |
|---|---|
| **Time** | ~35 minutes (~20 without an API key) |
| **You need** | A terminal, this project folder, and a website URL you know well |
| **Destructive?** | **No.** One step (R2) touches the database and is reversed in the same step, with a backup taken first |
| **Needs an API key?** | **T5, T6, T7 and T8 do.** Every other step runs without one, and the guide says so at each step |

> ⚠️ **About the API key.** The application takes it **through the Settings page**
> (`/settings/ai`), where it is validated against the provider and then encrypted at rest (AD-12) —
> not from a file. **T5 step 5a is where you enter it**, and no key is needed before that point.
>
> The steps that need one are marked **`[needs key]`**. If you skip them, say so in the sign-off
> notes and record that **the cost and one-call criteria went unverified against a live provider**:
> the automated suite verifies them against a *fake* provider, which proves the accounting and the
> control flow but **not** that a real DeepSeek response validates on the first attempt, and **not**
> a real invoice. Running T5–T8 with a real key is also what closes
> [V-1](../P14-DECISION-ANALYSIS.md)'s outstanding measurement.

---

## Before you start

### 1. Open a terminal in the project folder

```powershell
cd C:\path\to\reddit-scraper
```

Everything below is run from there. If a command says *"no such file or directory"*, you are in the
wrong folder — run the `cd` again.

### 2. Kill any stale server

A server left running from an earlier session serves **old code**, which looks exactly like a broken
change.

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

No output means nothing was running. That is fine.

### 3. Install dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Expected:** ends with `Successfully installed …` or `Requirement already satisfied` for every line.

**Possible failure:** `No package.json found` → you ran `npm`. This is a Python project; use the
command exactly as written.

### 4. Confirm you are on the right commit

```powershell
git log --oneline -1
```

**Expected:** a line beginning `feat(P14):`.

---

## T1 — The 23 sections exist, and are the 23 the database expects

**No key needed.** This proves the schema and the section registry agree before anything is fetched.

```powershell
.\.venv\Scripts\python.exe -c "from src.knowledge import SECTION_SPECS; from src.db.models import BKB_SECTION_KEYS; print(len(SECTION_SPECS)); print(tuple(SECTION_SPECS) == BKB_SECTION_KEYS)"
```

**Expected — exactly this:**

```
23
True
```

**Possible failure:** `22` or `False` → the section registry and `BKB_SECTION_KEYS` have drifted
apart. A section the registry does not know about is a section that will never be written.

**Troubleshooting:** none — this is a hard failure; stop and report it.

- **Screenshot expected:** none
- **Logs to verify:** none
- **Database values:** none
- **API response:** none
- **Acceptance:** *all 23 sections persist* (the registry half)

---

## T2 — Reading a real website, without spending anything

**No key needed. This makes real HTTP requests to the site you name.**

Pick a small company website you can look at in a browser. Use its homepage.

```powershell
.\.venv\Scripts\python.exe -m src.orchestration.handlers.website --dry-run --url https://example.com
```

Replace `https://example.com` with your chosen site.

**Expected — this shape (your numbers will differ):**

```
URL              https://example.com
MODE             dry run — nothing was sent to a model, nothing was written
pages fetched    1
characters       285
thin content     True
markup observed  True

Local signals that would be sent as FACTS:
{
  "competitors": [],
  "pricing": {
    "amounts": [],
    ...
  },
  ...
}
```

**Possible failures:**

| You see | It means |
|---|---|
| `WebsiteUnreachable` | The site refused the request or is down. Try a different site |
| `InvalidWebsiteURL` | You typed something that is not `http://` or `https://` |
| `pages fetched 0` | Nothing was read. Check the URL in a browser first |
| It hangs over 2 minutes | Your network is blocking it. Ctrl+C and try another site |

**Troubleshooting:** if `characters` is under 500, `thin content` will say `True`. That is correct
behaviour for a small page, not a failure.

- **Screenshot expected:** yes — paste the whole block into the notes
- **Logs to verify:** none
- **Database values:** none — **this step writes nothing**
- **API response:** none
- **Acceptance:** *zero AI calls*; the fetch and local-signal path

---

## T3 — A second read of the same site costs zero requests

**No key needed.** This is P13's cache, confirmed still working underneath P14.

Run **exactly the same command as T2 again**, immediately.

```powershell
.\.venv\Scripts\python.exe -m src.orchestration.handlers.website --dry-run --url https://example.com
```

**Expected:** the same output as T2.

> ℹ️ The dry run does not use the project cache (it has no project), so `pages fetched` will be the
> same number again rather than 0. **The zero-fetch behaviour is verified in T7**, which uses a real
> project. This step only confirms the command is repeatable and gives a stable answer.

**Possible failure:** a *different* number of characters on the second run → the site is serving
different content each time (an A/B test or a rotating banner). Note it and continue; it does not
fail the phase.

- **Screenshot expected:** no
- **Logs to verify:** none
- **Database values:** none
- **API response:** none
- **Acceptance:** determinism of the input path

---

## T4 — An unobserved signal is never reported as an absent one

**No key needed.** This is [DI33](../DEFERRED-IMPROVEMENTS.md), and it is the one step here that is
about *honesty* rather than function.

The four signals `tech_markers`, `structured_data`, `social_links` and `nav_taxonomy` need the page
source. When the page source is not available, they must be **omitted with a flag** — never sent as
four empty lists, which would read to the model as *"this company uses none of these"*.

Look at your T2 output.

**If it said `markup observed  True`:** the four keys appear in the signals block. Confirm you can
see at least `"nav_taxonomy"` in it.

**Expected:** the words `nav_taxonomy` appear in the JSON block.

**If it said `markup observed  False`:** you should instead see this note at the bottom:

```
NOTE  markup_not_observed is set, so tech_markers, structured_data,
      social_links and nav_taxonomy are OMITTED rather than sent empty.
      An omitted signal is unobserved, never absent (DI33).
```

**Expected:** that note is present, **and** the four key names do **not** appear in the JSON block.

**Possible failure:** `markup observed  False` **and** you can see `"tech_markers": []` in the JSON
→ this is the exact defect DI33 exists to prevent. Fail this step and report it.

- **Screenshot expected:** yes
- **Logs to verify:** none
- **Database values:** none
- **API response:** none
- **Acceptance:** DI33 resolved

---

## T5 — One website becomes one BKB, in exactly one AI call **`[needs key]`**

⚠️ **This step spends money** — expected to be well under one US cent.

### 5a. Enter your key on the Settings page

**The application takes the key through the UI, not a file.** `src/ai/credentials.py` says so in as
many words — *"the Settings page remains the intended path"* — and the key is **validated against the
provider before it is stored**, then encrypted at rest (AD-12). An environment variable exists only
as a local-development fallback and is not the route this guide uses.

Start the app:

```powershell
.\.venv\Scripts\python.exe main.py
```

Leave it running. In a browser, open:

```
http://localhost:5000/settings/ai
```

Under **API key**:

1. Click into the field labelled **"Paste your API key"** (it shows `sk-...` as a placeholder).
2. Paste your real DeepSeek key.
3. Click **"Validate & save"**.

**Expected:** a green toast, and the status line changes to **Valid**.

**Possible failures:**

| You see | It means |
|---|---|
| `Key rejected` / status **`invalid_key`** | The provider refused the key. **It was not stored** — validation happens before storage on purpose. Re-copy it |
| `Insufficient balance` | The key is **correct** and the account needs credit. It **is** stored; top up and continue |
| `unreachable` | The provider could not be reached. Check your network |
| `The stored key could not be decrypted` | `APP_SECRET_KEY` changed since a key was last saved. Re-enter the key |

### 5b. Confirm the key reaches the real provider

Still on `/settings/ai`, click **"Test connection"**.

**Expected:** a toast reading `Connected in <N> ms · <model name>` — for example
`Connected in 412 ms · deepseek-v4-flash`.

**This is the step that proves the response came from the real provider** rather than from a fixture:
the model name and the latency both come back from the provider's own reply.

**Possible failure:** `Test failed` with any message → do not continue to T5c/T5d. The remaining live
steps will not be meaningful.

> ℹ️ Leave the server running for the rest of T5–T8. The CLI and the dashboard read the **same**
> encrypted key from the **same** database, so you do not need to re-enter it anywhere.

### 5c. Create a project to analyse

⚠️ **This writes one row.** It is reversed in R2.

`projects` has no user-facing creator yet — that is **P16's** job — so for now you add the row by
hand. **Copy this as one line:**

```powershell
.\.venv\Scripts\python.exe -c "from src.db.database import get_session; from src.db.models import Project; s=get_session(); u='https://example.com'; p=Project(name='Manual P14 test', website_url=u, normalized_url=u); s.add(p); s.commit(); print('project id:', p.id)"
```

Replace `https://example.com` with your chosen site — **scheme and host only**, no path and no
trailing slash (`https://acme.com`, not `https://acme.com/en/`).

**Expected:**

```
project id: 1
```

**Write the number down.** Every step below uses it.

**Possible failure:** `UNIQUE constraint failed: projects.normalized_url` → you already created this
project. Run this to find its id:

```powershell
.\.venv\Scripts\python.exe -c "from src.db.database import get_session; from src.db.models import Project; s=get_session(); print([(p.id,p.name) for p in s.query(Project).all()])"
```

### 5d. Build the knowledge base

```powershell
.\.venv\Scripts\python.exe -m src.orchestration.handlers.website --project-id 1
```

Use your own project id.

**Expected — this shape:**

```
URL              https://example.com
BKB              v1  (id 1)
sections         23/23 complete
incomplete       none
AI calls         1
cost             $0.0012
http requests    3
markup observed  True
reused           False
```

**The two numbers that matter:** `AI calls` must be **1**, and `cost` must be **under $0.0500**.

**Possible failures:**

| You see | It means |
|---|---|
| `AIDisabledError` / `no API key is configured` | 5a did not take effect. Go back to `/settings/ai` and confirm the status line reads **Valid**. The CLI reads the same stored key the dashboard wrote |
| `AI calls         2` or more | **Fail this step.** The repair ladder ran, which the phase is built to avoid |
| `cost             $0.06` | Over budget. Fail and record the number |
| `sections        19/23 complete` | Not a failure by itself — see T6 |
| `no project 1` | Wrong id. Re-run the listing command in 5b |

- **Screenshot expected:** yes — the whole block
- **Logs to verify:** none
- **Database values:** verified in T6
- **API response:** none
- **Acceptance:** **exactly one `ai_calls` row**; **cost < $0.05 and displayed**

---

## T6 — All 23 sections are stored, and any incomplete one says which **`[needs key]`**

```powershell
.\.venv\Scripts\python.exe -m src.orchestration.handlers.website --show --project-id 1
```

Use your project id. **`--show` is read-only** — it fetches nothing and calls nothing.

**Expected:**

```
BKB version      v1  (id 1)   status: complete
sections         23/23 complete
incomplete       none
personas         3   (expected 1-5)
pain points      6   (expected 3-12)
buying signals   5   (expected 3-12)
ai_calls rows    1   (expected exactly 1)
total cost       $0.001234   (budget $0.05)
  - project=1 outcome=ok attempt=1 cost=$0.001234
```

**The five things to check** — each line prints the expected range beside it:

1. `sections` reads **23/23** — never 22, never 24.
2. `personas` is between **1 and 5**.
3. `pain points` is between **3 and 12**.
4. `buying signals` is between **3 and 12**.
5. `ai_calls rows` is **exactly 1**, and its line shows `project=1` (not `project=None`).

**Possible failures:**

| You see | It means |
|---|---|
| `sections 22/23` and `incomplete  pain_points` | The model returned something malformed in that section. **This is the phase working**: the other 22 persisted. Record which section and continue |
| `sections 19/19` | **Fail.** Sections were lost, which is the failure isolation is meant to prevent |
| `personas   0` | Fail — the bound is 1–5 |
| `ai_calls rows   2` | **Fail** — the repair ladder ran |
| `project=None` on the call line | **Fail** — the call was not attributed to the project |
| `project 1 has no BKB yet` | T5 did not complete. Re-run it |

- **Screenshot expected:** yes
- **Logs to verify:** none
- **Database values:** as above — this step *is* the database check
- **API response:** none
- **Acceptance:** **all 23 sections persist**; **1–5 personas, 3–12 pains, 3–12 signals**;
  per-section failure isolation

---

## T7 — Re-analysing an unchanged site makes **zero** AI calls **`[needs key]`**

This is the criterion that keeps a re-run free.

First, note the current call count:

```powershell
.\.venv\Scripts\python.exe -c "from src.db.database import get_session; from src.db.models import AICall; s=get_session(); print('ai_calls rows:', s.query(AICall).filter(AICall.stage=='business_intelligence').count())"
```

**Expected:** `ai_calls rows: 1`

Now run **exactly the same command as T5c again**:

```powershell
.\.venv\Scripts\python.exe -m src.orchestration.handlers.website --project-id 1
```

**Expected:**

```
BKB              v1  (id 1)
AI calls         0
cost             $0.0000
http requests    0
reused           True
```

Then re-count:

```powershell
.\.venv\Scripts\python.exe -c "from src.db.database import get_session; from src.db.models import AICall; s=get_session(); print('ai_calls rows:', s.query(AICall).filter(AICall.stage=='business_intelligence').count())"
```

**Expected:** `ai_calls rows: 1` — **still one.**

**The three things to check:** `AI calls` is `0`, `reused` is `True`, `BKB` is still **v1** (a reuse
must not burn a version number), and the row count did not move.

**Possible failures:**

| You see | It means |
|---|---|
| `AI calls         1` and `ai_calls rows: 2` | **Fail.** The cache did not hit; every re-run would cost money |
| `BKB              v2` | **Fail.** A reuse superseded the BKB it reused |
| `http requests    3` | P13's L1 website cache expired (7-day TTL) or missed. Note it; if `AI calls` is still 0 the P14 criterion passed |

- **Screenshot expected:** yes — both counts and the run output
- **Logs to verify:** none
- **Database values:** `ai_calls` count unchanged
- **API response:** none
- **Acceptance:** **re-analysis of an unchanged fingerprint makes zero calls**

---

## T8 — A cost you can see, attributed to the project **`[needs key]`**

```powershell
.\.venv\Scripts\python.exe -m src.orchestration.handlers.website --show --project-id 1
```

Look at the **last three lines** of the output.

**Expected:**

```
ai_calls rows    1   (expected exactly 1)
total cost       $0.001234   (budget $0.05)
  - project=1 outcome=ok attempt=1 cost=$0.001234
```

**The four things to check:** `ai_calls rows` is `1`; `total cost` is under `$0.05`; the detail line
says `project=1` and not `project=None`; and `attempt=1`.

**Possible failures:**

| You see | It means |
|---|---|
| `project=None` | The call was not attributed. Fail and report |
| More than one `  - ` line | Fail — this is the same defect T5 checks, seen from the database |
| `outcome=schema_invalid` | The repair ladder ran. Report how many `  - ` lines there are |
| `total cost       $0.0612` | Over budget. Fail and record the number |

- **Screenshot expected:** yes
- **Logs to verify:** none
- **Database values:** `ai_calls` — one row, attributed, one attempt
- **API response:** none
- **Acceptance:** **exactly one `ai_calls` row**; **cost < $0.05 and displayed**

---

## T9 — No secret reached the repository

**Run this after T5–T8 if you entered a key.** Your key now lives **encrypted in the database**
(AD-12), not in a file — so this step checks three different places it must never appear: the
repository, the stored knowledge, and the API.

```powershell
git status --short
git check-ignore -v .env data/leads.db
```

**Expected from the first command:** `.env` does **not** appear in the list.

**Expected from the second — two lines naming the rule that ignores each:**

```
.gitignore:2:.env        .env
.gitignore:11:data/*.db  data/leads.db
```

**Possible failure:** `.env` appears in `git status` → **stop immediately.** Do not commit. The key
would become public. Run `git rm --cached .env` and check `.gitignore` contains `.env`.

Then scan the database and the logs:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3,re; c=sqlite3.connect('data/leads.db'); rows=c.execute(\"SELECT payload_json FROM bkb_sections WHERE payload_json IS NOT NULL\").fetchall(); hits=[r for r in rows if re.search(r'sk-[A-Za-z0-9]{10}', r[0] or '')]; print('secret-shaped strings in stored sections:', len(hits))"
```

**Expected:** `secret-shaped strings in stored sections: 0`

Then confirm the key is **stored encrypted, not in the clear** — with the server still running from
T5, in a second terminal:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3,re; c=sqlite3.connect('data/leads.db'); rows=c.execute('SELECT key, value FROM settings').fetchall(); clear=[k for k,v in rows if v and re.match(r'^sk-[A-Za-z0-9]{8}', str(v))]; print('API keys stored in cleartext:', len(clear))"
```

**Expected:** `API keys stored in cleartext: 0`

**Possible failure:** any number above 0 → **fail immediately and rotate the key.** It means the
Fernet encryption at rest did not apply.

Finally, confirm the API never hands the key back:

```powershell
.\.venv\Scripts\python.exe -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://localhost:5000/api/settings/ai')); s=json.dumps(d); import re; print('key returned by the API:', bool(re.search(r'sk-[A-Za-z0-9]{8}', s)))"
```

**Expected:** `key returned by the API: False`

**Possible failure:** `True` → **fail and rotate the key.** R15 forbids a secret reaching an API
response, and the Settings page is meant to show a *status*, never the value.

- **Screenshot expected:** no
- **Logs to verify:** none
- **Database values:** zero secret-shaped strings in `bkb_sections`; zero cleartext keys in `settings`
- **API response:** `/api/settings/ai` contains no key
- **Acceptance:** **R15** — secrets never enter the database, an API response, or the repository;
  **AD-12** — encrypted at rest

---

## T10 — The database did not move, and the 459 leads are intact

**No key needed.** Every phase ends here.

```powershell
.\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db
```

**Expected:** the last line reads:

```
OK — all 76 checks passed.
```

**Possible failure:** any `FAIL` line → report the exact line. P14 opens no migration, so a schema
change here would be unexpected.

Then the migration head:

```powershell
.\.venv\Scripts\python.exe -m alembic heads
```

**Expected — one line, exactly:**

```
0007_projects_and_knowledge_base (head)
```

**Possible failure:** two lines → two heads, which violates **M1**. Stop and report.

- **Screenshot expected:** no
- **Logs to verify:** none
- **Database values:** 76/76; head `0007`; 459 original leads confirmed by the script
- **API response:** none
- **Acceptance:** legacy contract; **P14 adds no revision**

---

## T11 — The dashboard still renders

**No key needed.**

```powershell
.\.venv\Scripts\python.exe main.py
```

Leave it running. Open **http://localhost:5000** in a browser.

**Expected:** the leads page renders, showing the lead table.

Then, in a **second** terminal:

```powershell
cd C:\path\to\reddit-scraper
.\.venv\Scripts\python.exe -c "import urllib.request; print(urllib.request.urlopen('http://localhost:5000/api/leads').status)"
```

**Expected:** `200`

Stop the server with **Ctrl+C** in the first terminal.

**Possible failure:** `Address already in use` → a stale server. Go back to *Before you start*, step 2.

- **Screenshot expected:** yes — the dashboard
- **Logs to verify:** the terminal shows no traceback
- **Database values:** none
- **API response:** `200` from `/api/leads`
- **Acceptance:** legacy contract — 17 endpoints unchanged

---

## Rollback verification

**Every phase tests its rollback. A rollback plan nobody has run is a guess.**

[34 §P14](../34-implementation-plan.md)'s Rollback row is: *"`ai.enabled: false`; BKB tables sit
empty and nothing downstream exists yet"*.

### R1 — Turning the AI off stops the phase cleanly

⚠️ **This edits `config.yaml`.** You will undo it in the same step.

Open `config.yaml`. Find the line `  provider: deepseek` inside the `ai:` block. **Above** it, add:

```yaml
  enabled: false
```

Save. Then:

```powershell
.\.venv\Scripts\python.exe -m src.orchestration.handlers.website --project-id 1
```

**Expected:** it fails with a readable sentence, **not** a traceback ending in a random error:

```
AI features are disabled: no API key is configured. Add one on the Settings page.
Scraping is unaffected.
```

**Now undo it:** delete the `  enabled: false` line you added and save.

**Confirm the undo:**

```powershell
.\.venv\Scripts\python.exe -c "import yaml; c=yaml.safe_load(open('config.yaml',encoding='utf-8')); print('max_tokens key:', c['ai']['max_tokens']['business_intelligence'])"
```

**Expected:** `max_tokens key: 12000`

**Possible failure:** `KeyError` → you deleted more than the one line you added. Restore with
`git checkout config.yaml`.

### R2 — Removing the test project leaves nothing behind

⚠️ **This deletes the project row you created in T5b, and everything hanging off it.** That is the
point of the step, and it is what a rollback means here.

**Take a backup first:**

```powershell
Copy-Item data\leads.db data\leads.db.p14-manual-backup
```

Then:

**Copy this as one line** (it prints the counts, deletes the project, then prints them again):

```powershell
.\.venv\Scripts\python.exe -c "from src.db.database import get_session; from src.db.models import BKB, BKBSection, IntentSignal, PainPoint, Persona, Project; s=get_session(); c=lambda: (s.query(BKB).count(), s.query(BKBSection).count(), s.query(Persona).count(), s.query(PainPoint).count(), s.query(IntentSignal).count()); print('before (bkb, sections, personas, pains, signals):', c()); s.delete(s.get(Project, 1)); s.commit(); print('after  (bkb, sections, personas, pains, signals):', c())"
```

Change `Project, 1` to your project id.

**Expected:**

```
before (bkb, sections, personas, pains, signals): (1, 23, 3, 6, 5)
after  (bkb, sections, personas, pains, signals): (0, 0, 0, 0, 0)
```

Then confirm the leads are untouched:

```powershell
.\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db
```

**Expected:** `OK — all 76 checks passed.` — including the 459-lead fingerprint.

Everything cascaded away with the project, leaving no orphans.

**Possible failure:** any non-zero number on the `after` line → the cascade did not fire. Restore the
backup:

```powershell
Copy-Item data\leads.db.p14-manual-backup data\leads.db -Force
```

**When you are done and everything passed**, remove the backup:

```powershell
Remove-Item data\leads.db.p14-manual-backup
```

---

## T12 — The whole suite is green

```powershell
.\.venv\Scripts\python.exe -m pytest
```

This takes about **10 minutes**. Do not pass `-q` — the addopts already include it, and a second one
hides the summary line you need.

**Expected — the last line:**

```
2143 passed, 2 skipped in 600.00s
```

The exact count may differ by a few if you are on a later commit; **`0 failed` is what matters**.

**Possible failure:** anything other than `0 failed` → paste the failing test names into the notes.

- **Acceptance:** the full gate

---

## Coverage of the acceptance criteria

Every criterion in [34 §P14](../34-implementation-plan.md) maps to at least one step.

| Acceptance criterion | Step |
|---|---|
| **Exactly one `ai_calls` row with `stage='business_intelligence'` per analysis** | **T5**, **T8** |
| All 23 sections persist | **T1**, **T6** |
| Total cost **< $0.05** and displayed | **T5**, **T8** |
| **Re-analysis of an unchanged fingerprint makes zero calls** | **T7** |
| A forced schema failure in one section leaves the other 22 persisted | **T6** (the `incomplete` row) |
| 1–5 personas, 3–12 pains, 3–12 signals | **T6** |
| Golden-set comparison | **Not applicable — P20's.** See [P14-DECISION-ANALYSIS §D1](../P14-DECISION-ANALYSIS.md) |
| Per-section validation isolates a failure | **T6** |
| Zero AI in the fetch/signal path | **T2** |
| DI33 — an unobserved signal is not an absent one | **T4** |
| Secrets never reach the database or the repo (R15) | **T9** |
| No migration; head still `0007` | **T10** |
| Legacy contract — 459 leads, 17 endpoints | **T10**, **T11** |
| Rollback executed | **R1**, **R2** |
| Whole suite | **T12** |

---

## Sign-off

**Every step above must be executed by a human.** A generated table is not a signed one.

| Test | What it proves | Result | Date | Signature |
|---|---|---|---|---|
| T1 | The 23 sections the code knows are the 23 the database expects | ☐ PASS ☐ FAIL | | |
| T2 | A real website is read, and **nothing is sent to a model** | ☐ PASS ☐ FAIL | | |
| T3 | The same site gives the same answer twice | ☐ PASS ☐ FAIL | | |
| T4 | **An unobserved signal is never reported as an absent one** | ☐ PASS ☐ FAIL | | |
| T5 | **One website becomes one knowledge base, in exactly one AI call** `[needs key]` | ☐ PASS ☐ FAIL ☐ SKIPPED | | |
| T6 | **All 23 sections are stored, and an incomplete one names itself** `[needs key]` | ☐ PASS ☐ FAIL ☐ SKIPPED | | |
| T7 | **Reading the same site again costs nothing** `[needs key]` | ☐ PASS ☐ FAIL ☐ SKIPPED | | |
| T8 | **The cost is a real number you can see, charged to the right project** `[needs key]` | ☐ PASS ☐ FAIL ☐ SKIPPED | | |
| T9 | **No key and no secret reached the repository or the database** | ☐ PASS ☐ FAIL | | |
| T10 | The database did not move, and the 459 leads are intact | ☐ PASS ☐ FAIL | | |
| T11 | The dashboard still renders and the API still answers | ☐ PASS ☐ FAIL | | |
| R1 | Turning the AI off fails with a sentence, not a crash | ☐ PASS ☐ FAIL | | |
| R2 | **Deleting the project removes everything it owned, and no leads** | ☐ PASS ☐ FAIL | | |
| T12 | The whole suite is green | ☐ PASS ☐ FAIL | | |

**Operator:** ______________________  **Date:** ______________

**Did you enter a DeepSeek API key on the Settings page?**  ☐ Yes  ☐ No — T5–T8 skipped

> If **No**: record here that the *live* verification of the one-call and cost criteria did not
> happen. They are covered by the automated suite against the fake provider and the shipped price
> tables, which proves the accounting and not the invoice. **V-1 stays deferred** under
> [SPRINT-0 B1](../SPRINT-0-MEASUREMENTS.md).

**Notes / findings:**

<br><br><br>
