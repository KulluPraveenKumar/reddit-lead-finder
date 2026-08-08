# 28 — Discovery Pipeline Redesign

> **Parts 3, 4 and 7.** How to reduce Reddit requests dramatically *before* introducing AI or
> proxies, the layered request-reduction strategy, and whether the Discovery Agent should become
> smarter.
>
> Evidence labels as defined in [27](27-architecture-review.md): ✅ Verified · ◐ Inferred ·
> ▶ Recommendation · ❓ Unknown.

---

## 1. The baseline being replaced

[07 §5](07-scraping-pipeline.md) budgets a run with 10 approved subreddits and 12 approved keywords:

| Step | Requests |
|---|---:|
| Listing walk — 10 subs × 4 pages | 40 |
| **Search walks — 10 subs × 12 kw × ~2 pages** | **240** |
| Subreddit metadata | 10 |
| Comment fetches (capped) | 100 |
| **Total** | **≈ 390** |

At the specified cadence (12 req/min/proxy, 3–7 s jitter) this is **≈ 33 minutes** of wall clock, and
[06b §6](06b-deepseek-optimization.md) concedes the point directly: *"Scraping dominates the wall
clock, not AI."*

**Two observations the plan never acts on.**

1. **62% of the budget is the search path.** Every optimisation aimed at listing pagination is
   optimising the smaller half.
2. ✅ **The request budget assumes every page is fetched successfully.**
   [PHASE-02-STATUS §4.1](PHASE-02-STATUS.md) measured 12 successes in 36 attempts. The real budget
   is therefore ~3× the nominal one, or the run truncates — which is what happened on 3 of 4
   subreddits.

---

## 2. What RSS changes

### 2.1 The verified facts ✅

Sources and full quotations in [27 §3](27-architecture-review.md).

| Property | Value |
|---|---|
| Endpoint | `.rss` appended to any subreddit, user, search or multireddit URL |
| Format | **Atom 1.0** — a versioned, stable schema |
| Items per request | Default 25, **`?limit=` up to 100** |
| Multireddit | `/r/a+b+c/.rss` returns a merged feed |
| Search | `/r/{sub}/search.rss?q=…&restrict_sr=1&sort=new` |
| Sorts | Same as the site: `new`, `hot`, `top?t=`, `rising` |
| Rate limit | **~1 req/min** since 2025-06-11, HTTP 429 with `x-ratelimit-used/remaining/reset` |
| Auth workaround | `user=` + `feed=` from a logged-in account — **rejected**, violates [D1](02-research-findings.md) |

✅ **All four unknowns were measured in P0 on 2026-08-05.** Full evidence in
[SPRINT-0-MEASUREMENTS §2](SPRINT-0-MEASUREMENTS.md).

| # | Question | **Measured answer** | Consequence |
|---|---|---|---|
| **U1** | Per feed or per IP? | ✅ **PER IP.** A different feed immediately after a successful one → 429. Recovery at 60 s (30 s still 429). Budget ≈ **1 req/60 s/IP = 1,440/day** | **Multireddit combining is mandatory**, not optional. 1,440/day is still ~50× the ~28/day the steady state needs |
| **U2** | Does `<content>` carry full selftext? | ✅ **YES** — median **1,089 chars**, max 4,588 over 100 entries | **The favourable branch.** RSS supplies bodies; no HTML listing fetch is needed for them |
| **U3** | Boolean `subreddit:a OR subreddit:b`? | ✅ **YES** — 50 entries spanning 2 subreddits | **12 search requests, not 120** |
| **U4** | Conditional GET → 304? | ⛔ **NO.** Neither `ETag` nor `Last-Modified` is sent; only `Cache-Control: private, max-age=3600` | **Layer L1 is deleted** (§5.1). An idle poll costs one full request, ~56 KB — not 0 bytes |
| U5 | Is `?limit=100` honoured? | ✅ **YES** — 100 entries, 228,639 bytes | The density claim holds |
| U6 | Does `old.reddit.com` serve RSS? | ✅ **YES** — identical shape to `www` | Either host works |
| U7 | Do RSS and HTML share a budget? | ✅ **NO** — 14 HTML requests at 100% while RSS was capped | The two paths run independently |

▶ **Net: three of four favourable, one refuted.** The refutation deletes a documented optimisation
without changing a decision — an idle poll is still *one* request against the current design's 390.

### 2.2 The honest comparison

| | HTML listing page | RSS feed |
|---|---|---|
| Items per request | 25 | **100** |
| Subreddits per request | 1 | **many** |
| Response size ◐ | ~190 KB ✅ *(measured, [00 §3](00-current-state.md))* | ~20–40 KB |
| Title, author, permalink, timestamp | ✅ | ✅ *(permalink: the feed always gives the post; a listing title links to the **destination** for link/media posts — [freeze §11](ARCHITECTURE_FREEZE.md), 2026-08-08)* |
| **Selftext body** | ⛔ **NO** — corrected 2026-08-08 | ✅ **measured: median 1,089 chars** (U2) |
| **Score** | ✅ `data-score` | ❌ |
| **Comment count** | ✅ | ❌ |
| Parse stability | ❌ CSS classes — [R1](10-implementation-roadmap.md), rated Critical | ✅ **stable schema** |
| ToS posture | Scraping a rendered page | **Consuming a published feed** |

> ⛔ **CORRECTED 2026-08-08 (P5) — this section's conclusion rested on a false premise.**
> The paragraph below originally read: *"An HTML listing page carries 25 posts **with body and
> score**… If full data is needed for more than ~25% of discovered posts, HTML listing is the cheaper
> source."* **A listing page carries no body at all.** Old Reddit renders the expando as
> `<span class="error">loading...</span>` and fetches the text over AJAX, so `div.expando .md`
> matches zero elements. Measured three ways; see [freeze §11](ARCHITECTURE_FREEZE.md).
> HTML **search** is unaffected — it renders bodies inline in `div.search-result-body .md`.

▶ **The instinct to replace HTML with RSS outright is wrong, and worth stating because it is the
obvious move** — but for a narrower reason than this section first gave. An HTML listing page carries
25 posts with **score and comment count**, which the feed does not; a feed carries 100 posts with
**bodies**, which the listing does not. Neither is a superset. RSS wins on **change detection,
keyword search, incremental sync and any body-bearing collection**; HTML listing remains the only
source of engagement figures, and the permalink page remains the only source of comments.

⚠️ **This changes [§3](#3-the-redesigned-discovery-pipeline) stage 4 and
[34 §P6](34-implementation-plan.md) task 5.** The density-adaptive body fetch — *listing ≥25%,
permalink <25%* — assumed a listing page could supply bodies in bulk. It cannot, at any density.
**P6 owns the redesign**; P5 deliberately did not attempt it. See
[PHASE-05-HANDOVER.md](PHASE-05-HANDOVER.md).

The redesign below uses each for what it is good at.

---

## 3. The redesigned discovery pipeline

```
                        ┌──────────────────────────────────────┐
                        │  SCHEDULER (deterministic, §8)       │
                        │  per-subreddit interval from         │
                        │  observed post rate + historical     │
                        │  yield. Zero AI.                     │
                        └───────────────┬──────────────────────┘
                                        ▼
 ╔═══════════════════════════════════════════════════════════════════════╗
 ║ STAGE 1 — CHANGE DETECTION                     1 request per poll     ║
 ║ GET /r/a+b+c+…/new/.rss?limit=100       MULTIREDDIT MANDATORY (U1)      ║
 ║   no conditional GET — U4 refuted, so this always transfers ~56 KB   ║
 ║   → 200: newest ≤100 IDs across every watched subreddit               ║
 ╚═══════════════════════════════╤═══════════════════════════════════════╝
                                 ▼
 ╔═══════════════════════════════════════════════════════════════════════╗
 ║ STAGE 2 — WATERMARK DIFF                        0 requests, SQL only  ║
 ║ per subreddit: last_seen_fullname, last_seen_utc                      ║
 ║ new = feed_ids − known_ids   (single IN-clause query)                 ║
 ║ if new = ∅  ─────────────────────────────────►  STOP.                 ║
 ╚═══════════════════════════════╤═══════════════════════════════════════╝
                                 ▼
 ╔═══════════════════════════════════════════════════════════════════════╗
 ║ STAGE 3 — METADATA TRIAGE                       0 requests            ║
 ║ against TITLE + SNIPPET only:                                         ║
 ║   structural regex · negative terms · bot/deleted authors             ║
 ║   · time window · keyword tier · competitor aliases                   ║
 ║ → provisional pre-score, components stored                            ║
 ╚═══════════════════════════════╤═══════════════════════════════════════╝
                                 ▼
 ╔═══════════════════════════════════════════════════════════════════════╗
 ║ STAGE 4 — ADAPTIVE BODY FETCH        the ONLY bulk HTML in the design ║
 ║                                                                       ║
 ║  U2 CONFIRMED — RSS carries selftext, so normally:                     ║
 ║      0 requests — bodies already present                              ║
 ║                                                                       ║
 ║  fallback (link posts, or score needed), choose by density:           ║
 ║      survivors ÷ discovered ≥ 25%  →  HTML LISTING walk (25/req,      ║
 ║                                        full data, cursor-paginated)   ║
 ║      survivors ÷ discovered <  25%  →  per-post permalink fetch       ║
 ║                                                                       ║
 ║  Score and comment-count arrive here, not before.                     ║
 ╚═══════════════════════════════╤═══════════════════════════════════════╝
                                 ▼
 ╔═══════════════════════════════════════════════════════════════════════╗
 ║ STAGE 5 — KEYWORD SEARCH                       12 or 120 requests     ║
 ║ if U3 ✅:  /search.rss?q=(subreddit:a OR subreddit:b) AND "<kw>"      ║
 ║           &sort=new&limit=100          →  1 request per keyword       ║
 ║ else:     /r/{sub}/search.rss?q=…&restrict_sr=1&limit=100             ║
 ║                                        →  1 per (sub × keyword)       ║
 ║ Same watermark + triage as Stages 2–3.                                ║
 ╚═══════════════════════════════╤═══════════════════════════════════════╝
                                 ▼
 ╔═══════════════════════════════════════════════════════════════════════╗
 ║ STAGE 6 — COMMENT EXPANSION             ≤ cap, ordered by pre-score   ║
 ║ only posts that (a) clear the admission floor AND (b) num_comments≥N  ║
 ║ one permalink fetch each; back-fills score for search-sourced leads    ║
 ╚═══════════════════════════════╤═══════════════════════════════════════╝
                                 ▼
              local dedup → full pre-score → adaptive gate → AI
                        (unchanged, [06c](06c-local-first-pipeline.md))
```

### 3.1 The three decisions that make this work

**1. Metadata-only discovery, enrichment on demand.** Stages 1–3 make every rejection decision from
a title, a snippet, an author and a timestamp. ◐ The majority of what the funnel discards — hiring
posts, giveaways, megathreads, bot authors, out-of-window items, and everything matching a negative
term — is identifiable from a title. Paying 190 KB to download a post's body before deciding it is a
job advert is the current design's central inefficiency.

**2. Density-adaptive body fetching (Stage 4).** The crossover is arithmetic, not preference. A
listing page yields 25 full posts per request; a permalink yields 1. If more than 25% of a page's
posts are wanted, refetching the page is cheaper than fetching the survivors individually. The
threshold is exactly `1/25`, computed per subreddit per poll from Stage 3's own output.

**3. The watermark is the incremental-sync primitive.** One row per (subreddit, sort):

```sql
CREATE TABLE discovery_watermarks (
    id                INTEGER PRIMARY KEY,
    subreddit         VARCHAR(100) NOT NULL,
    channel           VARCHAR(20)  NOT NULL,   -- listing | search
    query             VARCHAR(300) NULL,       -- NULL for listing
    last_seen_fullname VARCHAR(20) NULL,       -- t3_…
    last_seen_utc     DATETIME NULL,
    last_polled_at    DATETIME NULL,
    -- last_etag / last_modified REMOVED: U4 refuted in P0. Reddit sends
    -- neither header on .rss, so there is nothing to store or replay.
    consecutive_empty INTEGER NOT NULL DEFAULT 0,
    observed_rate_per_hour REAL NULL,          -- feeds the scheduler, §8
    next_poll_at      DATETIME NULL
);
CREATE UNIQUE INDEX ux_watermarks ON discovery_watermarks (subreddit, channel, query);
```

▶ This table is the single largest structural addition in the redesign, and it is what turns
*"scrape the last 4 pages every time"* into *"fetch what changed."* `consecutive_empty` and
`observed_rate_per_hour` are what make §8's adaptive polling possible without a model.

---

## 4. Request arithmetic

Ten subreddits, twelve keywords, matching [07 §5](07-scraping-pipeline.md)'s scenario exactly.

### 4.1 Cold start — first run on a new project

| Path | Current | Redesign (U2/U3 ❌ — pessimistic) | Redesign (U2/U3 ✅ — optimistic) |
|---|---:|---:|---:|
| Listing discovery | 40 | **10** (RSS, limit=100) | **10** |
| Listing bodies | *(included)* | **40** (HTML listing, density ≥25%) | **0** (selftext in feed) |
| Keyword search | 240 | **120** (RSS per sub×kw, limit=100) | **12** (boolean multireddit) |
| Subreddit metadata | 10 | 10 | 10 |
| Comments | 100 | 100 | 100 |
| **Total** | **390** | **280** | **132** |
| **Reduction** | — | **−28%** | **−66%** |

◐ Cold start improves modestly in the pessimistic branch. That is expected and worth being plain
about: **a cold corpus has to be downloaded once, and RSS does not change that.** The gains
concentrate where the platform actually spends its life.

### 4.2 Steady state — the mode that runs 29 days out of 30

[06d §2.4](06d-ai-budget-and-scale.md): daily monitoring, ~1,000 posts seen, ~120 genuinely new.

| Path | Current | Redesign (pessimistic) | Redesign (optimistic) |
|---|---:|---:|---:|
| Change detection | — | **1** (multireddit RSS) | **1** |
| Listing discovery | 40 | 0 *(covered by the above)* | 0 |
| Listing bodies | *(included)* | **5** (120 new ÷ 25/page) | **0** |
| Keyword search | 240 | **120** | **12** |
| Subreddit metadata | 10 | **0** (cached 7 d) | **0** |
| Comments | 100 | **15** (admitted ∩ comments≥3) | **15** |
| **Total** | **390** | **141** | **28** |
| **Reduction** | — | **−64%** | **−93%** |

### 4.3 Idle poll — nothing new

| | Current | Redesign |
|---|---:|---:|
| Requests | 390 *(the design has no idle path)* | **1** — ~56 KB, ~1 s *(measured; U4 refuted)* |

◐ **This is the largest single win and the current design has no equivalent.** A scheduled run today
performs the full 390-request walk regardless of whether anything changed. Under adaptive polling
(§8), most polls of a low-activity subreddit are idle, and an idle poll must cost one request.

### 4.4 Monthly totals

Daily monitoring, 30 days, one project:

| | Current | Pessimistic | Optimistic |
|---|---:|---:|---:|
| Requests/month | **11,700** | 390 + 29×141 = **4,479** | 132 + 29×28 = **944** |
| **Reduction** | — | **−62%** | **−92%** |
| ◐ HTML downloaded | ~2.2 GB | ~0.55 GB | ~0.10 GB |
| Wall clock/run ◐ | ~33 min | ~12 min | **~2.5 min** |
| Browser launches | **0** | **0** | **0** |
| AI requests | 140 | 140 | 140 |
| ◐ Residential proxy cost @ $3/GB | $6.60/mo | $1.65/mo | **$0.30/mo** |

**Two rows deserve comment.**

**Browser launches are zero in every column** and always have been. [10 §9](10-implementation-roadmap.md)
lists a headless browser as a *future* enhancement for JS-only sites, and
[06 §2.3](06-ai-pipeline.md) explicitly routes SPA sites to the `thin_content` path instead. There is
no browser to reduce. ▶ Recorded because the brief asks for the measurement, and reporting a
reduction on a component that does not exist would be dishonest.

**AI requests do not change.** Discovery optimisation reduces *collection* cost, not *enrichment*
cost — those are separate funnels ([06c §1](06c-local-first-pipeline.md)). ◐ A second-order effect
does exist and is small: fewer wasted collections means marginally fewer items entering the local
funnel, but the adaptive gate admits on *pre-score rank*, so the admitted count is governed by
distribution shape rather than by corpus size. Claiming an AI saving here would be
[C1](24-cost-optimization.md)'s failure mode in reverse.

---

## 5. Part 4 — The layered request-reduction strategy

The brief proposes an ordering. ▶ It is close but has two layers in the wrong place, and the
correction matters.

| Brief's order | Verdict |
|---|---|
| L1 Local cache | ✅ Correct first |
| L2 Deduplication | ⚠️ **Split.** ID-dedup is free and belongs at L2; *content* dedup requires the body and cannot run until L5 |
| L3 Incremental sync | ⚠️ **Move to L2.** Incremental sync is what *prevents the request*; ID-dedup only avoids re-storing |
| L4 Keyword filters | ✅ |
| L5 Business rules | ✅ |
| L6 AI qualification | ✅ Correct last |

### 5.1 The corrected ordering

Ordered by **cost of evaluation**, cheapest first — which is the only ordering that makes sense when
each layer's job is to prevent the next layer's work.

| # | Layer | Costs | Eliminates | Cumulative |
|---:|---|---|---|---:|
| **L0** | **Scheduler** — is this subreddit due? | 0 | **~60% of polls** on low-activity subreddits (§8) | 60% |
| ~~L1~~ | ~~**Conditional GET** — 304 Not Modified~~ | — | **DELETED — U4 refuted in P0.** Reddit sends no `ETag` and no `Last-Modified`. An idle poll costs one full request (~56 KB measured), not 0 bytes | 60% |
| **L2** | **Watermark / incremental sync** | 0 (SQL) | **~88%** of discovered items in steady state (1,000 seen → 120 new) | 95% |
| **L3** | **ID dedup** — `reddit_id IN (…)`, one query per page | 0 | 3–8% residual overlap | 95% |
| **L4** | **Metadata triage** — structural regex, negatives, bots, window, on title+snippet | 0 | **~55%** of new items, *before any body is fetched* | 98% |
| **L5** | **Body fetch, density-adaptive** | 1 req per 25 (listing) or per 1 (permalink) | — *(this layer spends, it does not save)* | — |
| **L6** | **Content dedup** — exact hash → MinHash → semantic | 0 | 13–33% of remaining | 98.5% |
| **L7** | **Business rules + full pre-score** | 0 | scores; rejects `below_prescore` | — |
| **L8** | **Adaptive admission gate** | 0 | the tunable dial — **not a cost target** ([C1](24-cost-optimization.md)) | — |
| **L9** | **Comment expansion** — admitted ∩ `num_comments ≥ N` | 1 req per post | — *(spends)* | — |
| **L10** | **AI enrichment** | 1 call per 8 admitted | — | — |

**The two structural changes from the brief's ordering:**

1. **L0 and L1 are new.** Neither the brief nor the existing plan has a layer that prevents a *poll*.
   Everything in [06c](06c-local-first-pipeline.md) begins after collection has happened. ▶ The
   cheapest request is the one not scheduled, and that layer did not exist.
2. **Deduplication splits across L2/L3 and L6.** ID-based dedup is free and runs before any fetch;
   content-based dedup needs the body and runs after L5. Collapsing them into one "deduplication"
   layer, as the brief does, forces the expensive half to run early or the cheap half to run late.

### 5.2 Cumulative saving

Steady-state daily poll, pessimistic branch:

```
  10 subreddits × 6 potential polls/day        = 60 potential polls
  L0 scheduler                                 → 24 actual polls      (−60%)
  L1 conditional GET (❓U4)                    → 24 requests, 9 with payload
  L2 watermark: 1,000 items seen               → 120 new              (−88%)
  L3 ID dedup                                  → 114                  (−5%)
  L4 metadata triage (title only)              → 51                   (−55%)
  L5 body fetch: 51 ÷ 25 = 3 listing pages     → 3 requests
  L6 content dedup                             → 40                   (−22%)
  L7 pre-score                                 → 40 candidates
  L8 adaptive gate                             → ~26 admitted
  L9 comments: admitted ∩ comments≥3           → 15 requests
  L10 AI: 26 ÷ 8                               → 4 calls
  ─────────────────────────────────────────────────────────────────
  HTTP requests/day    24 + 120(search RSS)/6 + 3 + 15  ≈  62
  vs. current design                                       390
                                                        −84%
```

The keyword-search path is amortised across polls: 120 search-RSS requests are not run 6× daily —
▶ search is polled on its own, slower cadence (§8.3), because a keyword query's result set changes
more slowly than a subreddit's front page.

---

## 6. The techniques the brief lists, adjudicated

| Technique | Verdict | Where |
|---|---|---|
| **Incremental synchronization** | ✅ **Adopt** — the single highest-value technique; −88% in steady state | L2, `discovery_watermarks` |
| **Cursor-based crawling** | ✅ **Already correct.** [07 §3.2](07-scraping-pipeline.md) follows the `href` directly, preserving `count=`, with a `seen` set and a `next_url == url` loop guard. **Keep unchanged** | Stage 4 |
| **RSS feeds** | ✅ **Adopt** for change detection, search, and incremental sync | Stages 1, 5 |
| **Search result caching** | ⚠️ **Adopt with a fix.** `http_cache` TTL is 15 min ([07 §8](07-scraping-pipeline.md)); search results change slowly. ▶ Raise the search-path TTL to **60 min** and reconcile it with the poll interval, or the cache silently blocks the watermark from advancing | `net/cache.py` |
| **Subreddit prioritization** | ✅ **Adopt** — deterministic, from historical yield | §8.2 |
| **Keyword prioritization** | ✅ **Adopt** — deterministic, from hit density | §8.3 |
| **Historical activity scoring** | ✅ **Adopt** — `observed_rate_per_hour` drives the interval | §8.1 |
| **Adaptive polling** | ✅ **Adopt** — the mechanism behind L0's −60% | §8.1 |
| **Time-window optimization** | ⚠️ **Adopt, narrowly.** `t=` is already a `search_posts` parameter ([04 §5.2](04-system-design.md)). ▶ Its real value is *shrinking* on repeat polls: after the first sync, `t=day` is sufficient and returns far fewer results than `t=month` | Stage 5 |
| **Duplicate prevention** | ✅ **Already four layers** ([07 §7](07-scraping-pipeline.md)). Redesign adds the watermark *above* them | L2/L3/L6 |
| **Request batching** | ✅ **Adopt via multireddit** — `r/a+b+c/.rss` is the only true batching Reddit offers. There is no bulk endpoint | Stage 1 |
| **Conditional fetching** | ⛔ **Rejected — U4 refuted in P0.** Reddit sends no `ETag`/`Last-Modified` on `.rss` | — |
| **Metadata-only discovery** | ✅ **Adopt** — the core of the redesign | Stages 1–3 |
| **Post enrichment only when necessary** | ✅ **Adopt** — density-adaptive Stage 4 | L5 |
| **Comment expansion only when necessary** | ⚠️ **Already capped**, but ordered by `intent_score`. ▶ Reorder by **pre-score** and skip anything below the admission floor ([24 §4.4](24-cost-optimization.md)) | L9 |
| **Cold start strategy** | ✅ §7.1 |
| **Warm cache strategy** | ✅ §7.2 |
| **Steady state strategy** | ✅ §7.3 |

---

## 7. The three operating modes

### 7.1 Cold start — a new project, no history

▶ **Bounded backfill, not exhaustive backfill.** RSS returns the newest 100 and does not paginate
meaningfully; HTML paginates but costs 25/request.

| Decision | Value |
|---|---|
| Backfill depth | **`t=month`**, capped at `max_pages_per_query: 8` (200 items) per subreddit |
| Order | RSS first (100 newest, free of pagination), then HTML *only* to reach the depth target |
| Watermark | Set to the **oldest** fetched item, so subsequent polls fill forward |
| Comments | Deferred entirely to the second run — a cold project has no pre-score history and would spend its comment budget badly |

The last row is a real behaviour change. ◐ On a cold run the pre-score is uncalibrated, so ordering
100 comment fetches by it is close to random. Deferring costs one day of comment coverage and saves
100 requests on the least informative run the project will ever have.

### 7.2 Warm cache — a re-run within the TTL window

| Layer | Behaviour |
|---|---|
| `http_cache` (15 min, 60 min for search) | ⛔ **Corrected 2026-08-08 (P5): discovery bypasses it.** [§11 D5](#11-risks) is the governing rule and names the reason — a 15-minute TTL serving a stale feed to a 15-minute poll leaves the watermark permanently unadvanced. `get_feed` passes `allow_cache=False` |
| Watermark | Unchanged; no new items |
| `ai_cache` | `already_analyzed` on every item |
| **Cost** | **1 request, $0.00.** Not zero: the feed is fetched, and with no conditional GET (U4) it transfers in full. The $0.00 half stands — [06c §5](06c-local-first-pipeline.md)'s guarantee is about AI spend, and no model is called |

### 7.3 Steady state — the design target

| Property | Value |
|---|---|
| Poll cadence | Per subreddit, from `observed_rate_per_hour` (§8.1) |
| Change detection | 1 multireddit RSS request |
| Typical day | ≈ 62 requests ([§5.2](#52-cumulative-saving)) |
| Idle poll | **1 request, ~56 KB** (measured) |
| AI | ~4 calls/day, unchanged |

---

## 8. Part 7 — Should the Discovery Agent become smarter?

**▶ Yes — and none of the intelligence should be a model call.**

Every optimisation the brief asks about is a function of data the platform already stores.
Delegating them to Hermes would cost tokens to compute arithmetic, which is
[AD-10a](03-architecture.md) inverted.

| Capability | Deterministic mechanism | AI cost |
|---|---|---|
| **Polling frequency** | §8.1 — post rate + yield | **$0.00** |
| **Subreddit priority** | §8.2 — leads per 100 collected | **$0.00** |
| **Keyword priority** | §8.3 — hit density and lead conversion | **$0.00** |
| **Request scheduling** | §8.4 — a due-queue ordered by priority | **$0.00** |
| **Idle detection** | `consecutive_empty` on the watermark | **$0.00** |
| **Adaptive crawling** | The composition of the above | **$0.00** |

### 8.1 Adaptive polling interval

```python
# scoring/discovery_policy.py — deterministic, no imports from src.ai
def next_interval(w: Watermark, cfg: Policy) -> timedelta:
    """Poll often enough that the newest-100 window never overflows,
       and no more often than that."""
    rate = w.observed_rate_per_hour or cfg.default_rate      # EWMA of new posts/hour
    if rate <= 0:
        return cfg.max_interval                              # dead subreddit → daily
    # time for `window_target` (default 60) new posts to appear —
    # comfortably inside RSS's 100-item ceiling
    hours = cfg.window_target / rate
    interval = timedelta(hours=hours)
    # slow down where nothing has been found for a while
    interval *= (1 + cfg.empty_backoff * min(w.consecutive_empty, cfg.empty_cap))
    # speed up where leads actually come from
    interval /= (1 + cfg.yield_boost * subreddit_yield(w.subreddit))
    return clamp(interval, cfg.min_interval, cfg.max_interval)
```

**The governing constraint is stated in the docstring and is the whole reason this works:** RSS
returns at most 100 items, so a subreddit producing 20 posts/hour must be polled at least every 5
hours or the window overflows and posts are missed silently. ◐ **Overflow is the failure mode of any
watermark design**, and it is invisible — you simply stop seeing older new posts. The `window_target`
of 60 is a 40% safety margin against a burst.

Defaults ▶: `min_interval` 15 min, `max_interval` 24 h, `window_target` 60, `empty_backoff` 0.5,
`empty_cap` 6, `yield_boost` 1.0.

### 8.2 Subreddit prioritisation

```sql
-- nightly, zero AI, alongside the existing patterns rollup
SELECT subreddit,
       COUNT(*)                                         AS collected,
       SUM(CASE WHEN confidence_score >= 70 THEN 1 END) AS good_leads,
       1.0 * SUM(CASE WHEN confidence_score >= 70 THEN 1 END) / COUNT(*) AS yield
  FROM leads
 WHERE project_id = :p AND created_at > :since
 GROUP BY subreddit;
```

`yield` feeds §8.1's `yield_boost` and orders the due-queue. ◐ A subreddit that has produced no
qualifying lead in 30 days over 500 collected posts is a candidate for removal — surfaced to the
operator as a **suggestion**, never applied, exactly as [06h §4.3](06h-knowledge-lifecycle.md)
governs knowledge suggestions.

### 8.3 Keyword prioritisation

Two signals, both already collected:

| Signal | Source |
|---|---|
| **Hit density** — results returned per search | `project_keywords.est_volume` ([05 §5.2](05-database-plan.md)) |
| **Lead conversion** — leads ≥70 per 100 results | `leads.matched_keywords` |

▶ Tier the polling rather than the keyword: `high` tier searched every poll, `medium` every third,
`low` daily. A `low`-tier keyword that has produced nothing in 30 days is proposed for demotion.

**This is where the 120-request search path is actually reduced in the pessimistic branch** — not
every keyword is searched on every poll. ◐ Effective search requests fall to roughly a third.

### 8.4 Where Hermes fits

The scheduler decides. **Hermes explains, proposes, and takes instruction** — a read-and-narrate
role, identical to the one [22 §4.4](22-hermes-skills.md) gives `patterns-analyst`:

```
Operator: "why are we barely polling r/PPC?"

discovery-policy skill  →  GET /api/agent/discovery/policy?subreddit=PPC
                        →  { interval_h: 24, rate_per_hour: 0.4,
                             consecutive_empty: 5, yield_30d: 0.004,
                             clamped_by: "max_interval" }

"r/PPC produces about one post every 2.5 hours and has yielded 2 qualifying
 leads from 500 collected in 30 days (0.4%). The policy backed off to the
 24-hour maximum after 5 empty polls. Three subreddits are outperforming it
 by more than 10×. Want me to propose removing it at the next gate?"
```

▶ **Two rules keep this honest**, and both mirror decisions the platform already made:

1. **The agent never computes the interval.** It reads the policy output. If a number appears in a
   reply that is not in a tool result, that is a defect — [23 §4.4](23-hermes-memory-and-knowledge.md)'s
   `SOUL.md` rule.
2. **The agent never changes the policy silently.** It proposes; the operator approves at a gate or
   in Settings. Same posture as `bkb_suggestions`.

**Marginal AI cost of a "smarter" discovery agent: $0.00 for the intelligence, ~1 turn when the
operator asks about it.**

---

## 9. Failure modes introduced by this redesign

▶ Every one of these is new surface that the current design does not have. Listing them is the price
of proposing the change.

| # | Failure | Detection | Mitigation |
|---|---|---|---|
| D1 | **Watermark overflow** — more than 100 new posts between polls; older ones never seen | Feed's oldest item is newer than `last_seen_utc` | Explicit check on every poll; on overflow, fall back to an HTML listing walk **and** shorten the interval. This must be an error, not a silent gap |
| D2 | **Watermark poisoning** — a bad ID stored; the subreddit appears permanently empty | `consecutive_empty` exceeds a threshold while `rate_per_hour` is non-zero | Alert; `POST /api/agent/discovery/reset?subreddit=` clears it |
| D3 | **RSS silently deprecated by Reddit** | Feed returns non-Atom, or 404 | The canary parses one feed daily; on failure, fall back to HTML listing automatically. **The HTML path is retained, not deleted** |
| D4 | **RSS 429 under multi-proxy rotation** | `x-ratelimit-remaining: 0` | Respect `x-ratelimit-reset`; treat the RSS budget as *per-IP* until U1 says otherwise |
| D5 | **Cached feed blocks the watermark** — the 15-min `http_cache` serves a stale feed on a 15-min poll | Watermark does not advance while `rate_per_hour` is high | **Discovery requests bypass `http_cache` entirely.** The watermark *is* the cache |
| D6 | **Title-only triage rejects a good lead** whose title is bland but whose body is strong | The holdout audit already samples rejects | ▶ **Extend the holdout audit to Stage 3.** 2% of metadata-triage rejects get their body fetched and scored. Without this, the redesign moves a rejection decision earlier and *removes it from measurement* — which is exactly [AD-10b](03-architecture.md)'s prohibition |
| D7 | **Density heuristic thrashes** at the 25% boundary | Requests per collected item rises | Hysteresis: switch to listing at ≥30%, back to permalink at ≤20% |

**D6 is the most important row in this document.** The redesign's central move is deciding earlier,
on less information. [AD-10b](03-architecture.md) states that *"a gate that silently discards a good
lead is worse than no gate"* and that aggressive filtering demands continuous measurement. Stage 3 is
a new gate; it inherits the obligation.

---

## 10. Schema and code changes

**Additive. No existing table is altered.** Lands in the collection revision
([31 §5](31-execution-plan.md)).

```sql
CREATE TABLE discovery_watermarks (…);          -- §3.1
CREATE INDEX ix_watermarks_due ON discovery_watermarks (next_poll_at);

-- provisional (metadata-only) pre-score, so Stage 3 rejections are auditable
ALTER TABLE prescores ADD COLUMN stage VARCHAR(20) NOT NULL DEFAULT 'full';
                                                -- metadata | full
```

| Module | Change |
|---|---|
| `src/net/http_client.py` | ~~`if_none_match` / `if_modified_since`; treat **304 as success with no body**~~ ⛔ **DELETED — U4 refuted in P0** ([freeze §11](ARCHITECTURE_FREEZE.md)). Reddit sends neither header, so the branch could never be taken. What P5 actually added here is **`x-ratelimit-reset`** handling, in seconds-remaining, clamped |
| `src/reddit_client.py` | `+ get_feed(subreddits, sort, limit, query)` — Atom parse. **Public API otherwise frozen** ([AD-2](03-architecture.md)). *(`since` was never a parameter: with no conditional GET there is nothing to send it in, and the watermark diff is P6's, done on the returned ids)* |
| `src/discovery/feed_parser.py` | **New.** Atom → the same post dict shape `_extract_post` returns, with `score=None`, `num_comments=None` |
| `src/discovery/watermarks.py` | **New.** Read, diff, advance, overflow detection |
| `src/discovery/policy.py` | **New.** §8 — deterministic, grep-fenced from `src.ai` |
| `src/scrapers/base.py` | Stage 4's density decision |
| `src/db/repositories/discovery.py` | **New.** Watermark and due-queue queries |

▶ `feed_parser.py` returning the **same dict shape** as the HTML extractor is the design choice that
makes the fallback in D3 free: every downstream stage is source-agnostic, and switching between RSS
and HTML is a strategy swap rather than a second pipeline.

---

## 11. Acceptance criteria

- [ ] **D-AC1** — A poll with no new posts issues **exactly one** request and creates zero rows
- [x] ~~**D-AC2** — With U4 supported, an unchanged feed returns **304** and transfers no body~~
      ⛔ **VOID BY ITS OWN PRECONDITION.** U4 was *not* supported: Reddit sends neither `ETag` nor
      `Last-Modified` on `.rss` (P0, re-observed 2026-08-08). There is no 304 to test. An unchanged
      feed costs one full request, ~56 KB — which is what [§4.3](#43-request-arithmetic) now says
- [ ] **D-AC3** — Watermark overflow is **detected and logged as an error**, and triggers an HTML fallback walk (fixture: 150 new posts between polls)
- [ ] **D-AC4** — Steady-state daily requests ≤ **80** for the 10-subreddit / 12-keyword scenario
- [ ] **D-AC5** — Cold start collects ≥ 95% of the posts the current HTML design collects, from the same subreddits and window
- [ ] **D-AC6** — RSS-sourced and HTML-sourced posts produce **identical `Lead` rows** for the same `reddit_id`, except `score`/`num_comments` which are NULL until back-filled
- [ ] **D-AC7** — With RSS disabled by config, the pipeline runs entirely on the HTML path and passes every Phase 6 acceptance criterion
- [ ] **D-AC8** — **Stage-3 holdout audit** runs at 2% and publishes a metadata-triage miss rate below 5% (D6)
- [ ] **D-AC9** — The scheduler makes **zero** AI calls; `discovery/policy.py` does not import `src.ai`
- [ ] **D-AC10** — Discovery requests bypass `http_cache` (D5), asserted by a statement counter
- [ ] **D-AC11** — Comment expansion is ordered by pre-score and skips items below the admission floor
- [ ] **D-AC12** — 459 legacy leads intact; all 17 legacy endpoints unchanged

---

## 12. Summary

| Metric | Current | Redesign (pessimistic) | Redesign (optimistic) |
|---|---:|---:|---:|
| Requests, cold start | 390 | 280 (−28%) | 132 (**−66%**) |
| Requests, steady state | 390 | 141 (−64%) | 28 (**−93%**) |
| Requests, idle poll | 390 | 1 | **1** (~56 KB, measured) |
| Requests/month | 11,700 | 4,479 (−62%) | 944 (**−92%**) |
| ◐ HTML downloaded/month | ~2.2 GB | ~0.55 GB | ~0.10 GB |
| ◐ Wall clock/run | ~33 min | ~12 min | ~2.5 min |
| Browser launches | 0 | 0 | 0 |
| AI requests | 140/mo | 140/mo | 140/mo |
| ◐ Proxy bandwidth cost @ $3/GB | $6.60/mo | $1.65/mo | $0.30/mo |
| Parser fragility on the hot path | HTML/CSS | **Atom** | **Atom** |

**Which branch we land in is decided by four measurements, not by argument.** U1–U4 are the first
tasks in Sprint 0 ([31 §3](31-execution-plan.md)), each costs under an hour, and together they
determine whether steady-state collection costs 28 requests a day or 141. Both are large improvements
on 390; the difference between them is worth an afternoon of probing before any code is written.
