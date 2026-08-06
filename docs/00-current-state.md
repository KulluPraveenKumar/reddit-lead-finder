# 00 — Current State Analysis

> Audit of the existing `reddit-scraper` codebase as of 2026-07-29, performed by reading every
> source file plus `FEATURES.md`, and by probing `old.reddit.com` live. This document is the
> factual baseline that every later plan builds on. Nothing here is aspirational.

---

## 1. Repository inventory

```
reddit-scraper/
├── config.yaml                       # subreddits, keywords, scoring weights, schedule, dashboard
├── main.py                           # CLI: scrape | dashboard | schedule | add-user
├── requirements.txt                  # 8 runtime deps, no dev/test deps
├── FEATURES.md                       # existing feature documentation (accurate)
├── data/leads.db                     # live SQLite DB (459 leads, 10 scrape runs)
└── src/
    ├── config.py                     # YAML load + 3 validation rules
    ├── reddit_client.py              # 378 lines — HTTP transport + HTML parsing
    ├── scoring.py                    # LeadScorer — keyword/upvote/comment/recency weights
    ├── subreddit_loader.py           # merges config.yaml with dashboard-managed DB rows
    ├── db/
    │   ├── database.py               # module-level ENGINE / SessionFactory globals
    │   └── models.py                 # 8 declarative models, 7 tables + audit table
    ├── scrapers/
    │   ├── subreddit_scraper.py      # /r/<sub>/new listing scrape, min_score=3
    │   ├── keyword_scraper.py        # /r/<sub>/search per keyword, min_score=5
    │   └── user_scraper.py           # /user/<name>/submitted, no scoring
    └── dashboard/
        ├── app.py                    # create_app() — Flask factory
        ├── routes.py                 # 505 lines, 17 endpoints, one Blueprint
        └── templates/index.html      # 584 lines, inline CSS+JS, Chart.js via CDN
```

**Total application code: ~1,600 lines of Python + 584 lines of HTML/CSS/JS.**
There is no test directory, no `pyproject.toml`, no linter config, no CI, no `.env`, and no
migration tooling. The project is not a git repository.

---

## 2. What genuinely works today

These are load-bearing assets. **The plan must reuse, not replace, all of them.**

| Capability | Where | Notes |
|---|---|---|
| Unauthenticated `old.reddit.com` HTML scraping | `reddit_client.py` | No API key, no OAuth, no PRAW. Verified live. |
| Listing pagination via `?after=` cursor | `_parse_listing` | Selector `span.nextprev a[rel='nofollow next']` — **verified working** |
| Post extraction from `div.thing.link` | `_extract_post` | 9 fields; `data-fullname`, `data-timestamp`, `data-score` all present in live HTML |
| Search-result extraction from `div.search-result.search-result-link` | `_extract_search_post` | Verified present in live HTML |
| Comment parser for `div.comment` | `_parse_comments` | Complete but **never invoked** by any scraper |
| Subreddit metadata capture | `_parse_subreddit_about` | Description + subscriber count |
| Weighted intent scoring with high/med tiers | `scoring.py` | 5 tunable weights, DB-override-then-YAML fallback |
| Cross-run dedup on `leads.reddit_id` | unique index + pre-insert lookup + in-run set | Works; repeat runs insert 0 rows |
| Flask dashboard: filter/sort/search/paginate | `routes.py::index` | Server-rendered, 25/page, filters preserved across pages |
| Sidebar CRUD for subreddits/keywords/queries/settings | 12 AJAX endpoints | Union-merge with `config.yaml` |
| Lead status pipeline (new→contacted→interested→rejected) | `PUT /api/leads/<id>/status` | Validated against enum |
| CSV export with filter passthrough | `GET /api/leads/export` | 13 columns |
| Scrape-run audit trail | `scrape_runs` table | 10 rows live |
| Background scrape trigger | `POST /api/scrape` | Daemon thread, returns 200 immediately |
| Interval scheduler | `main.py::cmd_schedule` | `schedule` lib, survives job exceptions |

---

## 3. Live verification of the scraping premise

Executed 2026-07-29 from the development machine, no proxy:

| Request | Status | Bytes | `data-fullname` count | Pagination markup |
|---|---|---|---|---|
| `GET old.reddit.com/r/SaaS/new/` | **200** | 192,655 | 25 | `div.nav-buttons > span.nextprev > span.next-button > a[rel="nofollow next"]` |
| `GET old.reddit.com/r/SaaS/search?q=looking+for&restrict_sr=on&sort=new` | **200** | 110,484 | 25 | `div.nav-buttons > span.nextprev > a[rel="nofollow next"]` |

**Conclusions:**

1. `old.reddit.com` still serves the legacy HTML and the existing selectors are still correct.
   The whole architecture remains viable.
2. **Page size is 25, not 100.** The `limit=100` / `limit=50` arguments are client-side caps on
   an accumulated list, not a server page size. A `limit=100` listing scrape costs 4 HTTP round
   trips, not 1.
3. The `next` link is absolute (`https://old.reddit.com/...`) and carries **`count=25&after=...`**.
   The current code extracts only `after` and reconstructs the URL, dropping `count`. This works
   but is fragile; following the href directly is more robust.

---

## 4. Confirmed defects

These are real bugs visible in the source, not hypotheses. Each one justifies work in a later
phase, and each must be fixed **without changing observable behaviour for existing leads**.

### 4.1 Search pagination has never worked — `reddit_client.py:184`

```python
next_link = soup.select_one("nav-buttons a[rel='nofollow next']")
```

`nav-buttons` with no leading `.` is an **element-type selector**. There is no `<nav-buttons>`
element in Reddit's HTML — the real markup is `<div class="nav-buttons">`. `select_one` therefore
always returns `None`, `after` is always `None`, and `search_posts()` breaks out of its loop after
the first page.

**Impact:** every keyword query has only ever seen the **first 25 results**, never 50. The
`limit=50` in `keyword_scraper.py:32` is a fiction. Correct selector: `span.nextprev a[rel='nofollow next']`
(identical to the listing path — `span.nextprev` is present on both page types).

### 4.2 Search queries are not URL-encoded — `reddit_client.py:92,94`

```python
url = f"{BASE_URL}/r/{subreddit}/search?q={query}&restrict_sr=on&sort=new"
```

A configured keyword such as `"looking for"` is interpolated raw, producing a literal space in the
URL. `requests` papers over this today, but any query containing `&`, `#`, `+`, or `?` — all
plausible in AI-generated keywords — will silently produce a wrong query or a malformed URL.
Phrase queries also need explicit quoting (`q="looking for"`) to be treated as a phrase by Reddit's
search rather than an OR of two terms.

### 4.3 Search-sourced leads score on a different scale — `reddit_client.py:306`

`_extract_search_post` hardcodes `"score": 0` because the search-result markup does not expose
`data-score`. Meanwhile:

- `subreddit_scraper` uses `min_score=3` with a real upvote score.
- `keyword_scraper` uses `min_score=5` with a **guaranteed-zero** upvote score.

So the stricter threshold is applied to the weaker signal. With the live DB weights
(`upvote_weight=2`), a search-sourced post loses up to 200 points of headroom relative to a
listing-sourced post. The two scrapers are not comparable, and the same post can qualify or not
purely based on which scraper found it first.

### 4.4 Per-post N+1 database query

All three scrapers run `session.query(Lead).filter_by(reddit_id=post["id"]).first()` inside the
per-post loop. At today's volumes (a few hundred posts) this is invisible. Once comments are
ingested — the vision requires it — a single run can produce tens of thousands of dedup lookups.
The fix is a single `IN`-clause prefetch per page into a Python set.

### 4.5 Retry logic covers one failure mode out of five — `reddit_client.py:26-39`

`_get()` retries only on HTTP 429, only once, and returns `None` on every other
`RequestException`. There is no retry on connection reset, DNS failure, read timeout, 500, 502,
503, or 504 — precisely the errors a rotating-proxy pool produces constantly. A single flaky proxy
silently truncates a subreddit's results with a red console line and no persisted record.

### 4.6 `get_scoring_settings` issues 10 queries for 5 values — `subreddit_loader.py:39-43`

Each line calls `session.query(Settings).filter_by(...).first()` **twice** — once in the condition,
once in the value expression. Called once per scraper run today, so harmless; it becomes a hot path
if scoring moves per-lead.

### 4.7 Naive UTC datetimes throughout

`datetime.datetime.utcnow()` (deprecated in Python 3.12) is used everywhere, and
`datetime.utcfromtimestamp()` in `_extract_post`. All stored datetimes are naive. Recency scoring
compares a naive "now" against a naive parsed timestamp; this happens to work but breaks the moment
any timezone-aware value enters the system.

### 4.8 `session.query(Model).get(id)` is legacy in SQLAlchemy 2.x

Used in five routes (`routes.py:209, 221, 317, 369, 421`). Emits a `LegacyAPIWarning`; the 2.x
form is `session.get(Model, id)`.

### 4.9 `POST /api/scrape` has no concurrency guard

Each call spawns a fresh daemon thread. Clicking the button twice starts two full scrapes against
the same SQLite file. There is no run lock, no progress reporting, no cancellation, and no way for
the UI to know whether a scrape is running or finished.

### 4.10 `main.py` scraper ordering differs from `routes.py`

CLI runs keyword → subreddit → user; the dashboard runs subreddit → keyword → user. Because the
two scrapers use different thresholds and dedup on first-write, **the order changes which rows are
created**. This is a genuine nondeterminism in lead qualification.

---

## 5. Structural constraints that shape the plan

### 5.1 There is no migration system

`init_db()` calls `Base.metadata.create_all(ENGINE)`. That statement **creates missing tables and
never alters existing ones.** Adding a column to `leads` — which the vision requires — will not
happen automatically, and there is a live database with 459 leads and 10 audit rows to preserve.

**A versioned migration runner must land before any schema-touching phase.** This is
non-negotiable and is why it is Phase 2 rather than an afterthought.

### 5.2 SQLite + background worker = writer contention

Today a single daemon thread writes while Flask reads. Adding a persistent worker that writes
leads, comments, and AI analysis rows while the dashboard polls for progress will produce
`database is locked` errors under default SQLite settings. WAL journal mode, a `busy_timeout`, and
single-writer discipline are required, and they belong in the same phase as the migration runner.

### 5.3 The application is single-tenant and globally configured

`leads` has no owner column. Subreddits come from a global `config.yaml` list unioned with a
global `dashboard_subreddits` table. Keywords are global. The product vision is inherently
**project-scoped**: one website URL owns its own business profile, ICP, personas, subreddits,
keywords, and leads.

This is the single largest schema decision in the project and is treated explicitly in
[05-database-plan.md](05-database-plan.md).

### 5.4 The fire-and-forget thread cannot express the vision

The target flow has **human review gates in the middle of the pipeline** — the user approves
subreddits, then approves keywords, then scraping starts. A thread that runs to completion and
returns nothing cannot pause, persist, and resume. This requires a persisted run state machine, not
a thread.

### 5.5 No secrets handling

There is no `.env`, no `python-dotenv`, and no secrets loader. Both the LLM API key and the proxy
credentials need one, and neither may be committed.

---

## 6. Live database snapshot

| Table | Rows | Notes |
|---|---:|---|
| `leads` | 459 | intent_score min 5.0 / max 164.28 / mean 42.29 |
| `subreddits` | 4 | entrepreneur, saas, seo, startups |
| `dashboard_subreddits` | 1 | |
| `dashboard_keywords` | 1 | stored with a `high:` / `medium:` prefix inside `keyword` |
| `dashboard_search_queries` | 1 | |
| `settings` | 6 | keyword_weight=4, upvote_weight=2, comment_weight=2, recency_weight=1.5, high_intent_multiplier=2, interval_minutes |
| `tracked_users` | 0 | user scraper has never had input |
| `scrape_runs` | 10 | |

**Backward-compatibility bar:** after every phase, this database must still open, the dashboard
must still render all 459 leads, and CSV export must still produce the same 13 columns.

---

## 7. Dependency posture

```
requests · beautifulsoup4 · lxml · SQLAlchemy>=2.0 · Flask>=3.0 · PyYAML · rich · schedule
```

Notably absent and required by the plan:

| Need | Proposed dependency | Phase |
|---|---|---|
| LLM calls | `requests` (DeepSeek is OpenAI-compatible; **no vendor SDK**) | 1 |
| Secrets | `python-dotenv` + `cryptography` (Fernet) | 1 |
| Schema validation of LLM output | `pydantic>=2` | 4 |
| Migrations | `alembic` | 2 |
| Tests | `pytest`, `pytest-cov`, `responses` | 1 |
| Lint / format | `ruff` | 1 |
| Structured JSON logging | `python-json-logger` — **added in P2**; stdlib `logging` does the rest | P2 |
| HTML fetch for website analysis | `requests` (already present) + `trafilatura` or `readability-lxml` | 4 |

No async framework, no Redis, no Celery, no Postgres. The plan deliberately keeps the deployment a
**single Python process plus SQLite**, because that is what the current operator runs.

---

## 8. Reuse map — what each vision stage inherits

| Vision stage | Existing asset to extend | New work |
|---|---|---|
| Website → business profile / ICP / personas | — | All new (`src/ai/`) |
| Subreddit discovery | `RedditClient.get_subreddit_info`, `search_posts` sitewide branch | Discovery service + ranking |
| Keyword generation | `DashboardKeyword` table + `subreddit_loader` merge | AI generator writing into project-scoped keywords |
| Scrape Reddit via old.reddit | `RedditClient` **as-is, hardened** | Proxy transport, retry, comment wiring |
| Rotating proxies | — | All new (`src/net/`) |
| Extract posts | `_parse_listing` / `_extract_post` | Reuse verbatim |
| Extract comments | `_parse_comments` — **already written, never called** | Wire into a comment scraper + `comments` table |
| AI analysis / pain / intent | `LeadScorer` | New `AIAnalyzer`, composed with the existing keyword score |
| Confidence score & ranking | `Lead.intent_score` index | New `confidence_score` column + blended formula |
| Dashboard | `routes.py` + `index.html` | New project views, review gates, lead detail |
| Export | `api_leads_export` | Extend columns, add JSON/XLSX |

The honest summary: **roughly 40% of the target product already exists and works.** The plan's job
is to add the AI front-end, the proxy/reliability layer, the comment layer, and the orchestration
that ties them together — while leaving the working parts alone.
