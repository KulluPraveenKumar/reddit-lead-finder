# Reddit Lead Finder — Current Features

> A factual description of everything implemented in this application as of the current codebase.
> Nothing in this document is aspirational — every feature listed below exists in code and, where
> noted, is verified against the live database at `data/leads.db` (459 leads, 10 scrape runs).

---

## 1. What the Application Is

A self-hosted **Reddit lead-generation tool**. It scrapes `old.reddit.com` HTML without any API key
or authentication, scores each post against a configurable keyword list to estimate buying intent,
stores qualifying posts as "leads" in a local SQLite database, and serves a single-page Flask
dashboard for filtering, triaging, exporting, and re-running scrapes.

**Stack:** Python 3.11/3.12 · `requests` · `BeautifulSoup4` + `lxml` · `SQLAlchemy 2.x` · `Flask 3.x` ·
`PyYAML` · `rich` · `schedule` · Chart.js 4.4.0 (CDN)

**Entry points:** `main.py` (CLI) and the Flask app created by `src/dashboard/app.py:create_app()`.

---

## 2. Command-Line Interface

Implemented in `main.py`. Arguments are parsed manually from `sys.argv` (no `argparse`).

| Command | Effect |
|---|---|
| `python main.py` / `-h` / `--help` / `help` | Prints the `rich`-formatted help panel |
| `python main.py scrape` | Runs all three scrapers in order: subreddit → keyword → user |
| `python main.py scrape --scraper keyword` | Runs only the keyword scraper (`keyword`, `subreddit`, or `user`) |
| `python main.py dashboard` | Starts the Flask dashboard on the configured host/port |
| `python main.py schedule` | Runs a scrape immediately, then repeats on the configured interval |
| `python main.py add-user USERNAME` | Inserts a row into `tracked_users` — the only way to populate that table |

Every command except `help` first loads and validates `config.yaml`. All commands that touch the
database call `init_db()`, which creates `data/leads.db` and all seven tables if absent.

---

## 3. Reddit Scraping Engine

**File:** `src/reddit_client.py` (378 lines)

### 3.1 Transport layer

- **Target host:** `https://old.reddit.com` for all requests. Post links are rewritten to
  `https://www.reddit.com` for display.
- **Session:** a single persistent `requests.Session` per scrape run, so cookies survive across
  requests within a run.
- **Headers:** one static set — a spoofed Chrome 120 / Windows desktop User-Agent, plus `Accept`
  and `Accept-Language`. Not rotated.
- **Rate limiting:** a fixed `time.sleep(2)` before *every* request (`REQUEST_DELAY = 2`).
- **Timeout:** 30 seconds per request.
- **Retry:** on HTTP 429 only. Reads the `Retry-After` header (default 60s), sleeps, and retries
  **once**. No retry on timeouts, connection errors, or 5xx.
- **Failure mode:** any `requests.RequestException` is caught, printed in red, and `None` is returned.

### 3.2 Endpoints used

| Reddit path | Client method | Used by |
|---|---|---|
| `/r/{sub}/new/` | `get_new_posts(sub, limit=100)` | Subreddit scraper |
| `/r/{sub}/hot/` | `get_hot_posts(sub, limit=50)` | *(implemented, not currently called)* |
| `/r/{sub}/search?q=…&restrict_sr=on&sort=new` | `search_posts(q, sub, limit=50)` | Keyword scraper |
| `/search?q=…&sort=new` | `search_posts(q, limit=50)` | *(sitewide branch — implemented)* |
| `/user/{name}/submitted/new/` | `get_user_posts(name, limit=50)` | User scraper |
| `/r/{sub}/` | `get_subreddit_info(sub)` | Subreddit scraper (metadata) |
| post permalink | `get_post_comments(url, limit=50)` | *(implemented, not currently called)* |

### 3.3 Pagination

Listing pages (`/new/`, `/hot/`, `/user/…/submitted/`) follow old.reddit's `?after=` cursor. The
client reads the "next" link out of `span.nextprev a[rel='nofollow next']`, extracts the `after`
token by regex, and loops until either `limit` posts are collected or no next link is present.
Verified working — the live `scrape_runs` table records passes of 300–400 posts across four
subreddits.

### 3.4 Extracted fields

**Posts (from `div.thing.link`):**

| Field | Source |
|---|---|
| `id` | `data-fullname` attribute (e.g. `t3_1v5vysj`) |
| `title` | `a.title` / `p.title a` text |
| `url` | title href, rewritten to absolute `www.reddit.com` |
| `author` | `data-author` attribute (falls back to `[deleted]`) |
| `subreddit` | `data-subreddit` attribute |
| `score` | `data-score` attribute, integer-safe (handles negatives) |
| `num_comments` | first integer found in `a.comments` text |
| `body` | `div.expando .md` text, truncated to 5,000 characters |
| `created_utc` | `data-timestamp` (ms → UTC datetime), with a `<time datetime>` fallback |

**Search results (from `div.search-result.search-result-link`):** the same field set, sourced from
search-specific selectors (`a.search-title`, `a.author`, `a.search-subreddit-link`,
`a.search-comments`, `div.search-result-body .md`).

**Subreddit metadata (from `/r/{sub}/`):** description (`div.titlebox .usertext-body .md`, capped at
500 chars) and subscriber count.

**Comments (from `div.comment`):** author, body (`div.usertext .md`), score, and timestamp. The
parser is complete; it is not currently invoked by any scraper and there is no comment table.

### 3.5 Resilience

Both `_extract_post` and `_extract_search_post` wrap extraction in a broad `try/except` and return
`None` on failure, so one malformed post cannot abort a page. `_parse_comments` uses `continue` for
the same reason. Missing elements degrade to sensible defaults (`""`, `0`, `[deleted]`) rather than
raising.

---

## 4. Scrapers

All three scrapers share a common shape: a constructor taking `(reddit_client, config)` and a
`run(session)` method that returns the number of leads created and writes one `ScrapeRun` audit row.

### 4.1 Subreddit Scraper — `src/scrapers/subreddit_scraper.py`

Pulls the newest posts from every configured subreddit and scores them.

```
get_all_subreddits(config + DB)
  → for each subreddit:
      client.get_new_posts(sub, limit=100)
      _update_subreddit_info(sub)          # upserts description + subscriber count
      for each post:
          skip if reddit_id already in DB
          LeadScorer.score_post(...)
          if is_lead(min_score=3): INSERT Lead
      commit
  → INSERT ScrapeRun(scraper_type="subreddit")
```

- Threshold: **`min_score = 3`**
- Commits once per subreddit, so a crash mid-run preserves completed subreddits
- Also maintains the `subreddits` table (`description`, `subscriber_count`, `last_scraped`)
- Live evidence: runs of 300–400 posts scanned per pass

### 4.2 Keyword Scraper — `src/scrapers/keyword_scraper.py`

Runs every configured keyword and every custom search query as a subreddit-restricted Reddit search.

```
queries = high_intent + medium_intent + custom search queries
  → for each subreddit:
      for each query:
          client.search_posts(query, subreddit=sub, limit=50)
          dedupe against an in-memory seen_ids set
          skip if reddit_id already in DB
          LeadScorer.score_post(...)
          if is_lead(min_score=5): INSERT Lead
      commit
  → INSERT ScrapeRun(scraper_type="keyword")
```

- Threshold: **`min_score = 5`** (deliberately stricter than the subreddit scraper)
- Two-layer deduplication: a per-subreddit in-memory `seen_ids` set, plus a per-post database lookup
  on the unique `reddit_id` index
- With the shipped config this is 11 keyword queries + any custom queries, per subreddit

### 4.3 User Scraper — `src/scrapers/user_scraper.py`

Follows the submission history of specific redditors listed in `tracked_users`.

```
tracked = SELECT * FROM tracked_users
  → for each user:
      client.get_user_posts(username, limit=30)
      skip posts whose subreddit isn't in the tracked subreddit list
      skip if reddit_id already in DB
      INSERT Lead (intent_score = 0, no keyword scoring)
      update last_seen / post_count / lead_count
  → INSERT ScrapeRun(scraper_type="user")
```

- Posts are captured **unconditionally** for tracked users — no keyword filter, no score threshold
- Exposes a static helper `UserScraper.add_user(session, username)` used by the CLI
- Exits early with a notice when `tracked_users` is empty (its current state)

---

## 5. Intent Scoring Engine

**File:** `src/scoring.py`

`LeadScorer` reads its five weights from the database `settings` table when a session is supplied,
falling back to `config.yaml` values, falling back to hardcoded defaults.

### Formula

```
text = (title + " " + body).lower()

keyword_score  = Σ  keyword_weight × high_intent_multiplier   for each high-intent phrase found
               + Σ  keyword_weight                            for each medium-intent phrase found

upvote_score   = min(upvotes, 100)   × upvote_weight
comment_score  = min(comments, 50)   × comment_weight
recency_score  = max(0, 100 − age_hours) × recency_weight / 100

total = keyword_score + upvote_score + comment_score + recency_score
```

### Qualification

```python
is_lead = total >= min_score AND len(matched_keywords) > 0
```

A post must match **at least one keyword** to become a lead, regardless of how high its raw score is.
(The user scraper is the one exception — it bypasses scoring entirely.)

### Output

`score_post()` returns a breakdown dict — `total`, `keyword_score`, `upvote_score`, `comment_score`,
`recency_score`, and `matched_keywords` — all rounded to 2 decimals. Matched phrases are tagged
`[HIGH]` or `[MED]` and joined into the `Lead.matched_keywords` column, which drives both the
keyword chips in the table and the keyword-breakdown doughnut chart.

### Default weights (`config.yaml`)

| Weight | Default | Live DB value |
|---|---|---|
| `keyword_weight` | 3 | 4 |
| `upvote_weight` | 1 | 2 |
| `comment_weight` | 2 | 2 |
| `recency_weight` | 1.5 | 1.5 |
| `high_intent_multiplier` | 2 | 2 |

Observed score distribution in the live database: **min 5.0, max 164.28, mean 42.29** across 459 leads.

---

## 6. Configuration System

### 6.1 `config.yaml`

Loaded and validated by `src/config.py`. Validation enforces three rules: the keys `subreddits`,
`keywords`, and `scoring` must exist; `subreddits` must be a non-empty list; and at least one of
`keywords.high_intent` / `keywords.medium_intent` must be present. Parsed with `yaml.safe_load`.

```yaml
subreddits:        # startups, SaaS, entrepreneur
keywords:
  high_intent:     # "looking for", "any recommendations", "what tool do you use",
                   # "best alternative to", "recommend me", "anyone know a good"
  medium_intent:   # "how do I", "struggling with", "need help with",
                   # "is there a way to", "frustrated with"
scoring:           # the five weights above
schedule:
  interval_minutes: 60
dashboard:
  host: "127.0.0.1"
  port: 5000
```

### 6.2 Config + database merge layer

**File:** `src/subreddit_loader.py`

Four helpers unify the YAML file with dashboard-managed database rows, so the UI can extend the
configuration without editing files:

| Function | Behaviour |
|---|---|
| `get_all_subreddits(config, session)` | Union of `config.subreddits` and `dashboard_subreddits`, lowercased, deduplicated, sorted |
| `get_all_keywords(config, session)` | Union of YAML keywords and `dashboard_keywords`, split by intent level; strips the stored `high:`/`medium:` prefix |
| `get_all_search_queries(session)` | All rows from `dashboard_search_queries` |
| `get_scoring_settings(config, session)` | Per-key lookup in `settings`, falling back to YAML, coerced to `float` |

The merge is **union-only** — the dashboard can add to the configuration but cannot remove entries
that came from `config.yaml`.

---

## 7. Database

**Engine:** SQLite at `data/leads.db`, created automatically. **ORM:** SQLAlchemy 2.x declarative.
Schema is materialized by `Base.metadata.create_all()` on every `init_db()` call.

### Tables

**`leads`** — the primary table
| Column | Type | Notes |
|---|---|---|
| `id` | Integer | PK |
| `reddit_id` | String(20) | **Unique**, indexed — the cross-run deduplication key |
| `subreddit` | String(100) | Indexed |
| `author` | String(100) | |
| `title` | Text | Not null |
| `body` | Text | Post selftext, capped at 5,000 chars |
| `url` | Text | Absolute `www.reddit.com` permalink |
| `post_type` | String(20) | Defaults to `"post"` |
| `score` | Integer | Reddit upvotes |
| `num_comments` | Integer | |
| `intent_score` | Float | Indexed — the ranking key |
| `matched_keywords` | Text | `", "`-joined, `[HIGH]`/`[MED]` tagged |
| `status` | String(20) | Indexed — `new` \| `contacted` \| `interested` \| `rejected` |
| `created_utc` | DateTime | Post creation time |
| `scraped_at` | DateTime | Indexed — ingestion time |

**`subreddits`** — scraper-discovered metadata: `name` (unique), `description`, `subscriber_count`, `last_scraped`
**`dashboard_subreddits`** — subreddits added through the UI: `name` (unique), `added_at`
**`dashboard_keywords`** — UI keywords: `keyword` (stored prefixed `high:`/`medium:`), `intent_level`, `added_at`
**`dashboard_search_queries`** — free-text search queries added through the UI: `query`, `added_at`
**`settings`** — key/value store: `key` (unique), `value`
**`tracked_users`** — `username` (unique, indexed), `post_count`, `lead_count`, `first_seen`, `last_seen`
**`scrape_runs`** — audit trail: `scraper_type`, `subreddit`, `posts_found`, `leads_found`, `run_at`

### Indexes

`leads.reddit_id` (unique) · `leads.subreddit` · `leads.status` · `leads.intent_score` ·
`leads.scraped_at` · `tracked_users.username` · plus unique auto-indexes on `subreddits.name`,
`dashboard_subreddits.name`, and `settings.key`.

### Session management

`src/db/database.py` holds module-level `ENGINE` and `SessionFactory` globals. `get_session()`
lazily calls `init_db()` if the factory is unset. Every Flask route acquires a session and closes it
in a `finally` block.

### Live contents

| Table | Rows |
|---|---|
| `leads` | 459 |
| `subreddits` | 4 (entrepreneur, saas, seo, startups) |
| `dashboard_subreddits` | 1 |
| `dashboard_keywords` | 1 |
| `dashboard_search_queries` | 1 |
| `settings` | 6 |
| `scrape_runs` | 10 |
| `tracked_users` | 0 |

---

## 8. Web Dashboard

**Files:** `src/dashboard/app.py`, `src/dashboard/routes.py` (505 lines),
`src/dashboard/templates/index.html` (584 lines)

Server-rendered Jinja2, one page, one Blueprint. No JavaScript build step — all CSS and JS is inline
in the template. Dark theme with Reddit-orange (`#ff4500`) accents.

### 8.1 Stat cards

Five counters computed on every page load: total leads, new leads, contacted, interested, and
average intent score.

### 8.2 Charts (Chart.js)

| Chart | Type | Data |
|---|---|---|
| Leads Over Time | Line | `COUNT(*)` grouped by `DATE(scraped_at)` |
| Top Subreddits | Horizontal bar | Top 10 subreddits by lead count |
| Keyword Breakdown | Doughnut | Top 10 keywords by match frequency, aggregated from `matched_keywords` |

### 8.3 Lead table

Nine columns — colour-coded score badge (green ≥20, amber ≥10, red below), truncated clickable
title, subreddit, author, upvotes, comments, keyword chips, an inline status dropdown, and a delete
button. Renders an explicit empty state when no leads match.

### 8.4 Filtering, sorting, search

A GET form supporting:

- Full-text search across `title` and `body` (`ILIKE %term%`)
- Subreddit dropdown
- Status filter (new / contacted / interested / rejected)
- Sort by intent score, upvotes, comments, newest, or recently scraped — always descending
- Minimum intent score threshold
- Offset/limit pagination, 25 per page by default, with numbered Prev/Next links that preserve all
  active filters

### 8.5 Sidebar managers

Six cards, each backed by AJAX endpoints, updating the DOM in place without a page reload:

1. **Subreddits** — add/remove chips; input is normalized (lowercased, `r/` and `/` stripped); Enter key submits
2. **Keywords** — separate high-intent and medium-intent inputs with independent chip lists
3. **Search Queries** — free-text custom queries fed to the keyword scraper
4. **Scoring Settings** — six numeric inputs (five weights + scrape interval) with a save button and inline confirmation
5. **Run Scraper** — a button that fires a background scrape
6. **Recent Scrape Runs** — the last five runs with type, lead count, and timestamp

### 8.6 Lead triage

Changing a lead's status dropdown issues a `PUT` and re-colours the control in place. The delete
button prompts for confirmation, issues a `DELETE`, and removes the table row from the DOM.

### 8.7 On-demand scraping

`POST /api/scrape` spawns a daemon thread that runs all three scrapers in sequence (subreddit →
keyword → user) and returns `200` immediately, so the request does not block.

---

## 9. HTTP API

Seventeen endpoints, all on a single Blueprint in `src/dashboard/routes.py`.

### Leads
| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Full dashboard render |
| `GET` | `/api/leads` | Paginated JSON list; supports `page`, `per_page`, `subreddit`; ordered by intent score |
| `PUT` | `/api/leads/<id>/status` | Updates status; **validated** against the four-value enum; 400 on invalid, 404 on missing |
| `DELETE` | `/api/leads/<id>` | Deletes a lead; 404 on missing |
| `GET` | `/api/leads/export` | CSV download honouring `subreddit`, `status`, and `search` filters |

### Subreddits
| Method | Route | Description |
|---|---|---|
| `GET` | `/api/subreddits` | Lists dashboard-managed subreddits |
| `POST` | `/api/subreddits` | Adds one; normalizes input; 409 on duplicate; 201 on success |
| `DELETE` | `/api/subreddits/<id>` | Removes one |

### Keywords
| Method | Route | Description |
|---|---|---|
| `GET` | `/api/keywords` | Lists all, ordered by intent level then keyword |
| `POST` | `/api/keywords` | Adds one; validates `intent_level` ∈ {high, medium}; 409 on duplicate |
| `DELETE` | `/api/keywords/<id>` | Removes one |

### Search queries
| Method | Route | Description |
|---|---|---|
| `GET` | `/api/queries` | Lists custom queries |
| `POST` | `/api/queries` | Adds one; 409 on duplicate |
| `DELETE` | `/api/queries/<id>` | Removes one |

### Settings, scraping, stats
| Method | Route | Description |
|---|---|---|
| `GET` | `/api/settings` | Returns the six known setting keys |
| `PUT` | `/api/settings` | Upserts submitted key/value pairs |
| `POST` | `/api/scrape` | Starts a background scrape thread |
| `GET` | `/api/stats` | Total leads, subreddits, and tracked users |

All endpoints acquire and close a database session per request. JSON endpoints return
`{"error": "..."}` with an appropriate status code on failure.

---

## 10. CSV Export

`GET /api/leads/export` produces a downloadable `leads_export.csv` with thirteen columns:

`ID, Reddit ID, Subreddit, Author, Title, URL, Score, Comments, Intent Score, Keywords, Status,
Created UTC, Scraped At`

The export respects the subreddit, status, and search filters passed as query parameters and is
sorted by intent score descending. The dashboard's "Export CSV" button forwards whatever filters are
currently active on the page.

---

## 11. Scheduling

`python main.py schedule` uses the `schedule` library to run a full scrape on a fixed interval read
from `config.yaml` (`schedule.interval_minutes`, default 60).

Behaviour:
- Executes one scrape immediately on start, then repeats on the interval
- Polls the scheduler once per minute
- Wraps each job in a `try/except` so a failed run is reported but does not stop the loop
- Handles `Ctrl+C` cleanly with a shutdown message

---

## 12. Deduplication

Three independent mechanisms prevent duplicate leads:

1. **Database uniqueness** — `leads.reddit_id` carries a unique constraint and index
2. **Pre-insert lookup** — every scraper queries for an existing `reddit_id` before inserting
3. **In-run set** — the keyword scraper keeps a per-subreddit `seen_ids` set, since the same post
   frequently matches multiple queries

The practical effect is visible in the audit trail: repeat runs scan hundreds of posts and correctly
insert zero new leads when nothing has changed.

---

## 13. Console Output

All CLI feedback uses `rich`:

- Bordered panels for the dashboard URL and scheduler startup
- Colour-coded progress per subreddit (`r/saas: 12 leads found`)
- Per-scraper summary lines on completion
- Yellow rate-limit notices, red request failures, dim parse warnings
- A formatted help panel with usage and examples

---

## 14. Feature Summary

| Feature | Status |
|---|---|
| old.reddit HTML scraping (no API key required) | ✅ Working |
| Subreddit `/new` listing scraper with cursor pagination | ✅ Working |
| Keyword search scraper with two-layer deduplication | ✅ Working |
| Tracked-user scraper | ✅ Implemented (table currently empty) |
| Subreddit metadata capture | ✅ Working |
| Comment parser | ⚙️ Implemented, not yet wired into a scraper |
| Hot-posts and sitewide-search fetchers | ⚙️ Implemented, not yet called |
| Weighted intent scoring with high/medium tiers | ✅ Working |
| Configurable scoring weights (YAML + database override) | ✅ Working |
| SQLite persistence, 7 tables, 6 indexes | ✅ Working |
| Cross-run deduplication | ✅ Working |
| Web dashboard with stat cards and 3 charts | ✅ Working |
| Filtering, search, sorting, pagination | ✅ Working |
| Lead status pipeline (new → contacted → interested → rejected) | ✅ Working |
| Lead deletion | ✅ Working |
| CSV export with filter passthrough | ✅ Working |
| Subreddit / keyword / query managers in the UI | ✅ Working |
| Settings editor | ✅ Working |
| One-click background scrape | ✅ Working |
| Scrape-run audit trail | ✅ Working |
| Interval scheduler | ✅ Working |
| Rate limiting (2s delay) and 429 retry | ✅ Working |
| CLI with four commands | ✅ Working |

---

## 15. Running the Application

```bash
pip install -r requirements.txt

python main.py scrape        # populate the database
python main.py dashboard     # browse results at http://127.0.0.1:5000
python main.py schedule      # keep scraping every 60 minutes
```

The database is created automatically at `data/leads.db` on first run. No API keys, no `.env` file,
and no external services are required.
