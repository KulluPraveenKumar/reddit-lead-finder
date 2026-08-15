# P13 — Manual Testing Guide

**Phase:** P13, website fetch & local signals · **Written:** 2026-08-15
**Time:** about 25 minutes, most of it waiting for step T9 · **Destructive:** no

> **What P13 built:** the thing that turns a web address into readable text. Give it a company's
> website and it reads the front page plus up to six useful internal pages — pricing, product,
> about — strips away the menus and the code, and hands back the words a human would actually read.
> Then it picks out facts it can find without guessing: who the company compares itself to, what it
> charges, which tools its site uses.
>
> **No artificial intelligence is involved.** Not "a small amount" — none. Every number and every
> name in this phase comes from pattern-matching, and step T7 checks that against the database
> rather than taking anyone's word for it. The first AI call in this project is **P14**'s.
>
> **What you will not see:** a new page on the dashboard, a new lead, or a new number on any screen.
> P13 is a component, not a screen. The screen that shows all this is **P16**. So the steps below are
> run from a command window, and that is expected rather than a shortcut.
>
> **What is still yours to do:** run these steps and sign the table at the bottom. **The sign-off
> table is the phase gate** — the phase is not complete until a human has signed it.

Every expected output below was **copied from a real run on 2026-08-15**, not predicted. If what you
see differs, that is a finding worth recording, not something to explain away.

> ⚠️ **Do not add `-q` to any `pytest` command.** `pyproject.toml` already sets it, so a second one
> becomes `-qq` and hides the `N passed` line these steps ask you to read
> ([DI19](../DEFERRED-IMPROVEMENTS.md)).

> ⚠️ **This phase adds no migration.** Your database is untouched by P13 and stays at `0007`. The
> table this phase writes, `website_snapshots`, was created by P12. T8 confirms nothing moved.

---

## Before you start

**1. Install the new dependency.** P13 adds `trafilatura`, the library that pulls readable text out
of a web page. It is the first new dependency since P2 and nothing below works without it.

```powershell
cd C:\path\to\reddit-scraper
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Expected — among the last lines:**

```
Successfully installed babel-2.18.0 courlan-1.4.0 dateparser-1.4.2 htmldate-1.10.0 justext-3.0.2
lxml_html_clean-0.4.5 python-dateutil-2.9.0.post0 pytz-2026.3.post1 regex-2026.7.19 six-1.17.0
tld-0.13.2 trafilatura-2.2.0 tzdata-2026.3 tzlocal-5.4.4
```

If it instead says `Requirement already satisfied` for all of them, it is already installed and you
can continue.

**Possible failure:** `No module named pip` → you are using the system Python rather than the
project's. The `.\.venv\Scripts\python.exe` prefix is not optional.

**2. Kill any stale dashboard.** Not needed for these steps, but a server left running from an
earlier session serves the old code and that looks exactly like a broken change.

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

**3. These steps use the internet.** T1, T2 and T4 fetch real websites. This is the one part of this
project that is *supposed* to reach the outside world, and T3 is the step that checks it does so
from your own connection rather than through a proxy.

| Field | Value |
|---|---|
| Screenshot expected | none — every step is text output |
| Destructive steps | none. T9 writes nothing; T8's rollback runs on a **copy** |

---

## T1 — A real website becomes readable text

The whole phase in one command. `example.com` is used because it is a real site that exists for this
purpose and never changes.

```powershell
.\.venv\Scripts\python.exe -m src.ai.website_fetcher https://example.com
```

**Expected:**

```
website https://example.com/ yielded 285 characters (< 500): thin content, the knowledge built from it will be flagged
URL              https://example.com/
Requests made    1
Pages read       1
Characters       285
Thin content     YES — under 500 characters
Content hash     01d96b8d4067ef0fef8a52fb6beff911cea8e1e8ed8758425b51ea30d8f0e862
From cache       no

Pages:
  /                        285 chars

Local signals (no AI call was made):
  Competitors      (none found)
  Pricing          (no amounts)
  Posture          (none)
  Tech markers     (none found)
  Structured data  0 schema.org block(s)
  Social links     (none)
  Nav taxonomy     (none found)
```

**PASS if:** `Requests made` is `1`, `Characters` is `285`, and the `Content hash` matches the line
above character for character.

**FAIL if:**
- `Requests made` is more than 1 — `example.com` has no internal links, so anything above 1 means
  the crawler is following links it should not.
- The content hash differs — either `example.com` changed (check the character count first) or the
  text extraction is producing something different from what was recorded.

| Field | Value |
|---|---|
| Possible failure | `ModuleNotFoundError: No module named 'trafilatura'` |
| Troubleshooting | You skipped **Before you start** step 1 |
| Logs to verify | the `thin content` warning line, which is the log, printed first |
| Database values | none — this command writes nothing to the database, by design |
| API response | none — P13 has no API. That is **P16** |
| Acceptance | *"a URL becomes clean text"*, and *"`thin_content` when < 500 chars"* |

> **On `Thin content YES`:** that is the correct answer, not a failure. `example.com` really is 285
> characters long. This is the same flag a JavaScript-only site raises, and it exists so that P14
> knows to distrust what it built from such a page rather than presenting it confidently.

---

## T2 — A dangerous address is refused before anything is fetched

A web address does not have to point at a website. `file://` points at your own hard disk. Typing one
into a "paste your website" box must not read your files back to you.

```powershell
.\.venv\Scripts\python.exe -m src.ai.website_fetcher file:///etc/passwd
```

**Expected — one line, and no traceback:**

```
FAILED: file: URLs are not fetchable; a website URL must be http or https (got 'file:///etc/passwd')
```

**PASS if:** exactly that message, and **no** file contents are printed.
**FAIL if:** anything resembling file content appears, or a multi-line `Traceback` appears instead of
the sentence above.

Now confirm it is a genuine rule and not two special cases. Each of these must be refused too:

```powershell
.\.venv\Scripts\python.exe -m src.ai.website_fetcher javascript:alert(1)
.\.venv\Scripts\python.exe -m src.ai.website_fetcher ftp://example.com
```

**Expected — the same shape, naming the scheme:**

```
FAILED: javascript: URLs are not fetchable; a website URL must be http or https (got 'javascript:alert(1)')
FAILED: ftp: URLs are not fetchable; a website URL must be http or https (got 'ftp://example.com')
```

**PASS if:** all three are refused.
**FAIL if:** `ftp://` is accepted — that would mean only the two addresses named in the plan were
blocked, and anything else would get through.

| Field | Value |
|---|---|
| Possible failure | `ftp://` is accepted and the command hangs |
| Troubleshooting | Press Ctrl+C. This is a real finding — record it |
| Logs to verify | none |
| Database values | none |
| API response | none. When P16 adds the web form, this same refusal becomes an **HTTP 422** |
| Acceptance | *"URL scheme allowlist; `file://`/`javascript:` → 422"* |

---

## T3 — A page that does not exist fails in a sentence you can read

```powershell
.\.venv\Scripts\python.exe -m src.ai.website_fetcher https://example.com/definitely-not-a-real-page
```

**Expected:**

```
FAILED: https://example.com/definitely-not-a-real-page answered HTTP 404. Check the URL — a project needs a page that loads.
```

**PASS if:** the message names the address, names `404`, and tells you what to do about it.
**FAIL if:** a `Traceback` appears, or the message contains a proxy address or a server name — a
failure report about the customer's website should not be about our plumbing.

| Field | Value |
|---|---|
| Possible failure | the command succeeds and reports a page |
| Troubleshooting | Some hosts serve a "friendly" 200 page for missing URLs. Try a different site |
| Logs to verify | none |
| Database values | none |
| API response | none |
| Acceptance | *"a 404 fails with a readable message"* |

---

## T4 — Your own website, read properly

T1 used a deliberately empty page. This one uses a real business site so you can judge whether what
came back is *right*, which is the only part of this phase a person can check and a test cannot.

**Use a website you own or have permission to read.** It makes at most 7 requests, which is polite,
but it is still someone's server.

```powershell
.\.venv\Scripts\python.exe -m src.ai.website_fetcher https://your-company-website.example
```

**Expected — the shape, with your own values:**

```
URL              https://your-company-website.example/
Requests made    5
Pages read       5
Characters       18432
Thin content     no
Content hash     3f9a...
From cache       no

Pages:
  /                       6210 chars
  /pricing                4980 chars
  /about                  3122 chars
  ...

Local signals (no AI call was made):
  Competitors      ...
  Pricing          $49, $199  month/year
  ...
```

**PASS if all four hold:**
1. `Requests made` is **7 or fewer**. Seven is the hard budget: the front page plus six.
2. `Pages read` lists paths that are actually on your site, and **none from another website**.
3. `Characters` is **40000 or less**.
4. The signals are recognisably about your business — if it lists a "competitor" you have never heard
   of, read the sentence on your site that produced it before recording a failure.

**FAIL if:** `Requests made` is 8 or more, or any page listed belongs to a different domain.

| Field | Value |
|---|---|
| Possible failure | `Thin content YES` on a site that clearly has text |
| Troubleshooting | Your site probably renders with JavaScript. That is a **known limit**, not a bug — this project ships no browser. Record it and continue |
| Logs to verify | any `skipping …` lines: an internal page that failed is skipped, and the run continues |
| Database values | none |
| API response | none |
| Acceptance | *"landing + ≤6 priority paths, ≤40 KB"*, and *"≤7 requests per project version"* |

---

## T5 — The pricing and competitor reading, checked against a page you can see

Open your own `/pricing` page in a browser, then run:

```powershell
.\.venv\Scripts\python.exe -m src.ai.website_fetcher https://your-company-website.example --max-pages 2
```

**PASS if:** the `Pricing` line names amounts that appear on the page in front of you, and the
`Posture` line says `contact_sales` if and only if your page offers to talk to sales.
**FAIL if:** it reports an amount that is not on any page it read. That would mean it invented a
number, which is the one thing this phase must never do.

| Field | Value |
|---|---|
| Possible failure | `(no amounts)` on a page with visible prices |
| Troubleshooting | Prices drawn as images, or loaded by JavaScript, cannot be read as text. Check whether you can select the price with your mouse — if you cannot, neither can we |
| Logs to verify | none |
| Database values | none |
| API response | none |
| Acceptance | *"Local signals: competitor regex, pricing regex, tech markers, schema.org JSON-LD, social links, nav taxonomy"* |

---

## T6 — The fetch goes out from your own connection, not through the proxy pool

This is the phase's most important architectural rule and it is invisible from the outside, so it is
checked by the tests that were built to prove it. A customer's own website must be read from one
steady address: arriving from ten rotating proxy addresses looks like an attack, and the customer is
the last person we want to alarm.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_website_fetcher.py -k DirectEgress
```

**Expected — the last line:**

```
6 passed, 73 deselected in 1.96s
```

**PASS if:** `6 passed` and **0 failed**.
**FAIL if:** any test fails — in particular
`test_the_fetcher_end_to_end_never_touches_the_pool`, which sets the system to *"use proxies for
everything"* and confirms the website fetch still goes direct anyway.

| Field | Value |
|---|---|
| Possible failure | `no tests ran` |
| Troubleshooting | Check you are in the project folder and spelled `-k DirectEgress` exactly |
| Logs to verify | none |
| Database values | none |
| API response | none |
| Acceptance | *"Fetch goes **direct**, not through the proxy pool"* |

---

## T7 — Reading a site twice costs nothing the second time, and no AI was used

Two guarantees, one command. The first is that re-analysing a website inside a week makes **zero**
network requests. The second is that this entire phase made **zero** AI calls, counted in the
database rather than assumed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_website_fetcher.py -k "L1Cache or ZeroAI"
```

**Expected — the last line:**

```
10 passed, 69 deselected in 9.87s
```

**PASS if:** `10 passed` and **0 failed**.
**FAIL if:** `test_a_second_analysis_inside_the_window_makes_zero_fetches` fails — that is the
zero-request guarantee, and it counts requests rather than timing them.

> **Why this is a test and not a click.** The "paste it again and watch nothing happen" version of
> this step needs a saved project to paste against, and **no project can exist yet** — the first one
> is created by P16's `project add`. P13 was explicitly forbidden from adding a second way to create
> one. So the guarantee is proved where it can be proved today, and P16's guide is where you will
> click it.

| Field | Value |
|---|---|
| Possible failure | `9 passed, 1 failed` |
| Troubleshooting | Read which test failed; the name says which of the two guarantees broke |
| Logs to verify | none |
| Database values | the test itself asserts `SELECT COUNT(*) FROM ai_calls` is `0` |
| API response | none |
| Acceptance | *"unchanged fingerprint within 7 days makes **zero** fetches"* · *"**zero AI calls in this phase**"* |

---

## T8 — Your database did not move

P13 adds no migration. This confirms it.

```powershell
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db
```

**Expected:**

```
0007_projects_and_knowledge_base (head)
```

and, as the last lines of the second command:

```
  INFO  leads = 492 (459 baseline + 33 collected since)
  PASS  the 459 original leads are all still present
  PASS  max(intent_score) over the original leads = 164.28
  PASS  avg(intent_score) over the original leads = 42.29

OK — all 76 checks passed.
```

**PASS if:** one head, still `0007`, and **76 checks passed** with the 459 leads present.
**FAIL if:** the head is anything else, or the count is not 76 — either would mean this phase changed
the schema, which it must not.

| Field | Value |
|---|---|
| Possible failure | `0008…` appears |
| Troubleshooting | A migration was added. That is a phase-scope failure — record it and stop |
| Logs to verify | none |
| Database values | 459 baseline leads · max `164.28` · avg `42.29` |
| API response | none |
| Acceptance | the legacy contract, checked every phase |

---

## Rollback verification

**Both of P13's rollback paths, executed. Neither touches your real database.**

### R1 — Delete the configuration block; the behaviour is identical

P13 adds a `website:` block to `config.yaml`. Deleting it must reproduce the shipped defaults exactly,
so that "undo the configuration" and "undo the phase" cannot disagree.

Open `config.yaml` in Notepad, put a `#` at the start of every line of the `website:` block (it runs
from `website:` down to the blank line before `# Network policy (P4)`), save, then:

```powershell
.\.venv\Scripts\python.exe -m src.ai.website_fetcher https://example.com
```

**Expected:** byte-for-byte the same output as **T1**, including `Requests made 1`, `Characters 285`
and the same content hash.

**PASS if:** identical to T1.
**FAIL if:** anything differs — the defaults in code and the values in the file have drifted apart.

⚠️ **Now remove the `#` characters and save again.** Verified on 2026-08-15 as identical:

```
  with the website: block     WebsiteSettings(max_pages=7, max_depth=2, max_total_chars=40000, per_page_timeout=15.0, cache_ttl_days=7)
  with the block DELETED      WebsiteSettings(max_pages=7, max_depth=2, max_total_chars=40000, per_page_timeout=15.0, cache_ttl_days=7)
```

### R2 — The schema rollback still works

P13 adds no migration, so the rollback it inherits is P12's. This confirms P13 did not break it.
**It runs on a copy**, so your real database is never at risk.

```powershell
Copy-Item data\leads.db "$env:TEMP\p13-rollback-test.db"
$env:ALEMBIC_DB_URL = "sqlite:///$env:TEMP\p13-rollback-test.db"
.\.venv\Scripts\python.exe -m alembic downgrade 0006_content_and_dedup
.\.venv\Scripts\python.exe scripts\check_schema.py --db "$env:TEMP\p13-rollback-test.db" --skip-p12
```

**Expected — the last line:**

```
OK — all 51 checks passed.
```

Now put it back:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\check_schema.py --db "$env:TEMP\p13-rollback-test.db"
Remove-Item Env:\ALEMBIC_DB_URL
```

**Expected — the last line:**

```
OK — all 76 checks passed.
```

**PASS if:** **51** down and **76** back up.
**FAIL if:** either command errors or either count differs.

> ⚠️ **Remember to run the last line** (`Remove-Item Env:\ALEMBIC_DB_URL`). If you leave that
> variable set, later commands in the same window keep pointing at the temporary copy instead of your
> real database.

---

## T9 — The full suite is green

The long one. Roughly 17 minutes; leave it running.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

**Expected — the last line:**

```
1984 passed, 2 skipped in 1014.79s (0:16:54)
```

**PASS if:** `1984 passed` and `2 skipped`, with **0 failed**.
**FAIL if:** any failure. Record the test name; it is more useful than the count.

> ⚠️ **Run this locally, not from the CI badge.** Ten tests use your real database, which is not in
> the repository, so CI **skips** them and reports green without ever running the migration
> round-trip. This is [DI30](../DEFERRED-IMPROVEMENTS.md), and it is why your local run of this step
> is not redundant with CI.

| Field | Value |
|---|---|
| Possible failure | `12 skipped` instead of `2` |
| Troubleshooting | Your `data/leads.db` is missing. The live-database tests skip without it |
| Logs to verify | none |
| Database values | none — the suite uses temporary databases throughout |
| API response | none |
| Acceptance | the whole gate |

---

## Coverage — every acceptance criterion maps to a step

| Acceptance criterion ([34 §P13](../34-implementation-plan.md)) | Step |
|---|---|
| Fetch goes **direct**, not through the proxy pool | **T6** |
| Unchanged fingerprint within 7 days makes **zero** fetches | **T7** |
| SPA shell sets `thin` and the run still completes | **T1** (and T4's troubleshooting note) |
| A 404 fails with a readable message | **T3** |
| `file://` rejected at validation | **T2** |
| **Zero AI calls in this phase** | **T7** |
| Bounded crawl: landing + ≤6 priority paths, ≤40 KB | **T4** |
| Local signals: competitors, pricing, tech, schema.org, social, nav | **T1**, **T5** |
| `thin_content` when < 500 chars | **T1** |
| ≤7 requests per project version | **T4** |
| Rollback | **R1**, **R2** |
| Legacy contract — 459 leads, schema unmoved | **T8** |
| Whole suite | **T9** |

---

## Sign-off

**Every step above must be executed by a human.** A generated table is not a signed one.

| Test | What it proves | Result | Date | Signature |
|---|---|---|---|---|
| T1 | A real website becomes readable text, and a thin one says so | ☐ PASS ☐ FAIL | | |
| T2 | **`file://` and every other non-web address is refused before any fetch** | ☐ PASS ☐ FAIL | | |
| T3 | A 404 fails with a sentence a person can act on | ☐ PASS ☐ FAIL | | |
| T4 | **Your own site is read within the 7-page, 40 KB budget, and nothing off-site** | ☐ PASS ☐ FAIL | | |
| T5 | The pricing and competitor readings match a page you can see | ☐ PASS ☐ FAIL | | |
| T6 | **The customer's site is read from your own address, never the proxy pool** | ☐ PASS ☐ FAIL | | |
| T7 | **A second read costs zero requests, and zero AI calls were made** | ☐ PASS ☐ FAIL | | |
| T8 | The database did not move, and the 459 leads are intact | ☐ PASS ☐ FAIL | | |
| R1 | Deleting the config block changes nothing | ☐ PASS ☐ FAIL | | |
| R2 | **The rollback works, down and back up, on real data** | ☐ PASS ☐ FAIL | | |
| T9 | The whole suite is green | ☐ PASS ☐ FAIL | | |

**Operator:** ______________________  **Date:** ______________

**Notes / findings:**

<br><br><br>
