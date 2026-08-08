# 07 — Scraping Pipeline

## 1. Hard requirements

| Requirement | Enforcement |
|---|---|
| `old.reddit.com` only | `BASE_URL` constant; a test asserts no `oauth.reddit.com` / `api.reddit.com` / `praw` anywhere in the tree |
| No Reddit API | dependency audit in CI: `praw`, `asyncpraw`, `redditwarp` are banned imports |
| No OAuth, no login | no credential handling, no `Authorization` header, no account cookies |
| **All traffic via the network policy; egress is chosen per request class** | `RedditClient` has no direct `requests` access; only `ProxiedHTTPClient`. **Changed in P4** ([29 §6](29-network-and-proxy-strategy.md), [AD-25](ARCHITECTURE_FREEZE.md)): the *enforcement* is unchanged — no bare `requests.get` in `RedditClient` — but the destination is `NetworkPolicy`, not a mandated proxy. RSS, health checks and the customer's own website are always direct ([R18](ARCHITECTURE_FREEZE.md)); bulk HTML follows the configured ladder |

Reference: [02 §1.1](02-research-findings.md) — the market leader in this category was terminated by
a Reddit Data API licensing decision. The constraint is strategic, not incidental.

---

## 2. Endpoint surface

| Purpose | URL | Container | Paginates | Score? |
|---|---|---|---|---|
| Fresh posts | `/r/{sub}/new/` | `div.thing.link` | ✅ 25/page | ✅ |
| Popular posts | `/r/{sub}/hot/` | `div.thing.link` | ✅ | ✅ |
| Sub-restricted search | `/r/{sub}/search?q=&restrict_sr=on&sort=&t=` | `div.search-result.search-result-link` | ✅ 25/page | ❌ |
| Sitewide search | `/search?q=&sort=&t=` | same | ✅ | ❌ |
| Post + comments | post permalink | `div.comment` | ⚠️ "load more" not followed | ✅ (on the page) |
| User submissions | `/user/{name}/submitted/new/` | `div.thing.link` | ✅ | ✅ |
| Subreddit about | `/r/{sub}/` | `div.titlebox` | n/a | n/a |

All seven already exist as methods on `RedditClient`; three of them
(`get_hot_posts`, `get_post_comments`, sitewide `search_posts`) have **never been called**. The plan
activates all three rather than writing new transport code.

`sort` accepts `relevance | new | top | comments`; `t` accepts `hour | day | week | month | year |
all`. Both are added as keyword-only parameters with today's defaults, so existing callers are
unaffected.

---

## 3. Pagination — corrected

### 3.1 Verified markup

```html
<!-- listing -->
<div class="nav-buttons"><span class="nextprev">view more:
  <span class="next-button">
    <a href="https://old.reddit.com/r/SaaS/new/?count=25&amp;after=t3_1v9w4q5" rel="nofollow next">next ›</a>
  </span>
</span></div>

<!-- search — note: NO span.next-button wrapper -->
<div class="nav-buttons"><span class="nextprev">view more:
  <a href="https://old.reddit.com/r/SaaS/search?q=looking+for&amp;restrict_sr=on&amp;sort=new&amp;count=25&amp;after=t3_1v96bcr" rel="nofollow next">next ›</a>
</span></div>
```

`span.nextprev a[rel='nofollow next']` matches **both**. This single selector replaces the working
listing selector and the broken `nav-buttons` search selector from
[00 §4.1](00-current-state.md).

### 3.2 Loop contract

```python
def _paginate(self, first_url: str, parser, limit: int,
              session_key: str | None, max_pages: int = 20) -> list[dict]:
    out, url, pages, seen = [], first_url, 0, set()
    while url and len(out) < limit and pages < max_pages:
        html = self._get(url, session_key=session_key)
        if not html:
            break                                    # transport already retried and gave up
        items, next_url = parser(html)
        if not items:
            break                                    # empty page = end of results
        for it in items:
            if it["id"] not in seen:                 # guards against a cursor loop
                seen.add(it["id"]); out.append(it)
        if next_url == url:                          # defensive: identical next = loop
            break
        url, pages = next_url, pages + 1
    return out[:limit]
```

**Guards, and why each exists:**
- `max_pages=20` — 500 items per query is far more than any single keyword warrants; without it a
  malformed cursor is an infinite request loop against a proxied target.
- In-loop `seen` set — Reddit occasionally serves an overlapping page; without this, `limit` is
  reached with duplicates and real results are lost.
- `next_url == url` — the specific failure that a naive `?after=` reconstruction produces.
- Following the absolute `href` preserves `count=`, which Reddit uses for its own paging offset.

---

## 4. Extraction

### 4.1 Posts

Field mapping is unchanged from the working implementation. The one behavioural change:

```python
# _extract_search_post
"score": None,     # was: 0   ← [00 §4.3]
```

`None` means "unknown", `0` means "zero upvotes". They are different facts and the scorer must
treat them differently:

```python
# LeadScorer.score_post
if upvotes is None:
    upvote_score = 0.0
    max_possible -= 100 * self.upvote_weight     # threshold scales down proportionally
else:
    upvote_score = min(upvotes, 100) * self.upvote_weight
```

This removes the scale mismatch without changing a single existing listing-sourced score. A
regression test asserts that re-scoring all 459 existing leads produces byte-identical
`intent_score` values.

### 4.2 Comments

The parser exists (`_parse_comments`) and is correct. What it needs:

```python
def _parse_comments(self, html, *, max_depth: int = 4):
    for el in soup.select("div.comment"):
        depth = len(el.find_parents("div.child"))       # NEW: nesting depth
        if depth > max_depth: continue
        ...
        yield {..., "depth": depth,
               "body_hash": sha256(f"{author}|{body}".encode()).hexdigest()}
```

Additions: `depth` (so the UI can indent and the scorer can weight top-level comments higher) and
`body_hash` (the dedup key from [05 §5.4](05-database-plan.md)). Everything else is untouched.

**Not implemented, deliberately:** following `a.morecomments` ("load more comments") links. Each
one is an extra request against a proxied target for progressively lower-value content. The top ~30
comments on a post carry the signal. Documented as a future enhancement.

### 4.3 Score back-fill

Search-sourced leads have `score = NULL`. When the comment scraper visits the post permalink, the
full post markup **is** present on that page with `data-score`:

```python
def _backfill_score(self, session, lead, html):
    if lead.score is not None:
        return
    thing = BeautifulSoup(html, "lxml").select_one("div.thing.link[data-fullname]")
    if thing and (s := thing.get("data-score", "")).lstrip("-").isdigit():
        lead.score = int(s)
        lead.intent_score = rescore(lead)      # cheap, deterministic, no LLM
```

Free accuracy: one request already being made yields the missing field for every search-sourced
lead that gets comments fetched.

---

## 5. Collection strategy per run

```python
@dataclass
class RunOptions:
    mode: Literal["listing", "search", "both"] = "both"
    time_window: str = "month"              # old.reddit `t`
    sort: str = "new"
    limit_per_query: int = 100
    max_pages_per_query: int = 8
    fetch_comments: bool = True
    max_comments_per_post: int = 30
    max_comment_posts: int = 100
    min_post_comments_for_comment_fetch: int = 3
    min_score_threshold: float = 3.0
    max_total_leads: int = 2000
```

Job fan-out for a run with 10 approved subreddits and 12 approved keywords:

```
approve_keywords
  └─► 10 × scrape_subreddit jobs        (each: 1 listing walk + 12 search walks)
        └─► on completion, if fetch_comments:
              1 × scrape_comments job per subreddit, bounded by max_comment_posts
                └─► when all done: 1 × analyze_leads job
```

**Request budget for that run:**

| Step | Requests |
|---|---:|
| Listing walk, 10 subs × 4 pages | 40 |
| Search walks, 10 subs × 12 kw × ~2 pages | 240 |
| Subreddit metadata, 10 subs | 10 |
| Comment fetches, capped | 100 |
| **Total** | **≈ 390** |

At 12 req/min/proxy sequential over 10 proxies with a 5 s mean delay, that is **≈ 33 minutes**.
Acceptable for a batch tool, and the number the UI's ETA is computed from.

---

## 6. Rate limiting and anti-blocking

### 6.1 Cadence

| Control | Current | Target | Why |
|---|---|---|---|
| Delay | fixed 2.0 s, global | random 3.0–7.0 s, **per proxy** | Removes the fixed-interval fingerprint; per-proxy means the pool's aggregate rate scales with pool size |
| Concurrency | 1 | 1 (default), max 3 | [02 §2.1](02-research-findings.md) — reported floor is 10–30 rpm; stay well under |
| Effective rate | ~30 rpm from 1 IP | ~12 rpm per IP | Comfortably inside the reported floor |

### 6.2 Header profiles

Today: one static Chrome-120 UA for every request. Under proxy rotation, ten residential IPs
presenting a byte-identical header set is *more* anomalous than one IP would be.

```python
PROFILES = [
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
     "sec_ch_ua": '"Chromium";v="126", "Not;A=Brand";v="24", "Google Chrome";v="126"',
     "platform": '"Windows"', "accept_language": "en-US,en;q=0.9"},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ... Chrome/126.0.0.0 Safari/537.36",
     "sec_ch_ua": '"Chromium";v="126", ...', "platform": '"macOS"', "accept_language": "en-GB,en;q=0.9"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
     "sec_ch_ua": None, "platform": None, "accept_language": "en-US,en;q=0.5"},
    # ... 6 profiles total
]
```

**Rules:** a profile is **pinned to a proxy** for the life of that proxy's session (rotating headers
on a fixed IP is itself a signal); Firefox profiles omit `Sec-CH-UA` entirely because Firefox does
not send it, and sending it would be a giveaway; `Accept` and `Accept-Encoding` match the claimed
browser.

### 6.3 Cookie isolation

Each proxy gets its own `requests.Session` and therefore its own cookie jar. One Reddit session
cookie observed from ten different IPs is exactly the correlation signal we are paying for proxies
to avoid.

### 6.4 Response classification

```python
def classify(resp_or_exc) -> Outcome:
    if isinstance(exc, (ConnectTimeout, ProxyError, SSLError)):   return PROXY_FAILURE
    if isinstance(exc, ReadTimeout):                              return TIMEOUT
    if isinstance(exc, ConnectionError):                          return NETWORK
    code = resp.status_code
    if code == 200 and _is_block_page(resp.text):                 return SOFT_BLOCK
    if code == 200:                                               return OK
    if code == 404:                                               return NOT_FOUND       # no retry
    if code == 403:                                               return FORBIDDEN       # blacklist proxy
    if code == 429:                                               return RATE_LIMITED    # honour Retry-After
    if code in (500, 502, 503, 504):                              return SERVER_ERROR    # retry, new proxy
    return UNKNOWN
```

**Soft-block detection matters more than the status codes.** Reddit and Cloudflare both return
HTTP 200 with an interstitial. Heuristics:

```python
def _is_block_page(html: str) -> bool:
    if len(html) < 2000:                                    return True   # real pages are ~100 KB+
    low = html.lower()
    if "just a moment" in low or "cf-browser-verification" in low:  return True
    if "you've been blocked" in low or "whoa there, pardner" in low: return True
    if "our cdn was unable to reach our servers" in low:    return True
    return False
```

**A 200 that fails `_is_block_page` must never be cached and never parsed** — caching a block page
poisons the cache for 15 minutes and produces a run with silently zero results. This is the most
insidious failure mode in the whole pipeline.

### 6.5 Per-outcome response

| Outcome | Retry? | Proxy action | Backoff |
|---|---|---|---|
| `OK` | — | mark success | — |
| `NOT_FOUND` | ❌ | none | — |
| `FORBIDDEN` | ✅ new proxy | blacklist 30 min | immediate |
| `RATE_LIMITED` | ✅ new proxy | blacklist for `Retry-After` (cap 600 s) | honour header |
| `SOFT_BLOCK` | ✅ new proxy | blacklist 15 min | exponential |
| `SERVER_ERROR` | ✅ new proxy | +1 consecutive failure | exponential |
| `TIMEOUT` / `NETWORK` / `PROXY_FAILURE` | ✅ new proxy | +1 consecutive failure | exponential |

Max 4 attempts per URL, each on a **different** proxy where one is available. After exhaustion the
client raises `ScraperError`; `RedditClient._get` catches it and returns `None`, preserving the
existing caller contract exactly.

### 6.6 robots.txt

`old.reddit.com/robots.txt` disallows several paths. This tool operates as an assistive research
agent at human-scale rates against publicly readable pages, which is the same posture as every
product in the category. The mitigations that make that defensible are: rate limiting well below
the reported floor, no authentication, no content republication, no automated engagement, and no
personal-data enrichment. **Documented explicitly so the operator understands what they are
running**, and configurable — `scraping.respect_robots: false` is the default, and setting it to
`true` makes the client honour disallow rules (and collect substantially less).

---

## 7. Deduplication

Four layers, each catching what the previous one cannot:

| Layer | Scope | Mechanism | Catches |
|---|---|---|---|
| 1 | Within one pagination walk | in-loop `seen` set | Overlapping pages from a repeated cursor |
| 2 | Within one scrape job | per-job `seen_ids` set (exists today) | Same post matching multiple keywords |
| 3 | Across runs | batched `SELECT reddit_id WHERE IN (...)` | Everything previously collected |
| 4 | Database | `UNIQUE(leads.reddit_id)` | Concurrent-writer races |

Layer 3 is the [00 §4.4](00-current-state.md) N+1 fix: one query per page of 25, not 25 queries.

Comments dedup on `UNIQUE(comments.body_hash)` where the hash covers `lead_id|author|body`. Layer 4
must be handled with `INSERT OR IGNORE` semantics (SQLAlchemy: catch `IntegrityError` on flush and
skip) rather than assuming layer 3 caught everything, because a lease-expiry re-run of a job is a
legitimate concurrent writer.

---

## 8. HTTP response cache

```python
class HTTPCache:
    def get(self, url: str) -> CachedResponse | None: ...
    def put(self, url: str, resp: Response, ttl_s: int) -> None: ...
    def purge_expired(self) -> int: ...
```

| Rule | Value |
|---|---|
| Key | `sha256(url)` — the URL after normalisation |
| Default TTL | 900 s (15 min) |
| Cached | 200 responses that pass `_is_block_page` |
| **Never cached** | non-200, block pages, comment permalinks (they change fast and are one-shot) |
| Bypass | `use_cache=False`, e.g. subreddit validation which must be live |
| Bound | 500 MB; LRU eviction by `fetched_at` |

The cache pays for itself immediately: with 12 keywords per subreddit, the same popular post appears
in many result sets, and subreddit metadata is fetched once per subreddit per run regardless of how
many jobs touch it.

---

## 9. HTML fixtures and regression protection

**Reddit's markup is the single largest uncontrolled dependency in this system.** A CSS class rename
silently reduces every run to zero results with no error anywhere.

```
tests/fixtures/html/
├── listing_new_saas.html            # /r/SaaS/new/ — 25 posts + next link
├── listing_last_page.html           # no next link
├── search_results_saas.html         # search — 25 results + next link
├── search_empty.html                # "no results found"
├── comments_thread.html             # nested comments, several depths
├── subreddit_about.html             # sidebar with description + subscriber count
├── subreddit_private.html           # private sub interstitial
├── subreddit_banned.html            # banned sub page
├── block_cloudflare.html            # "Just a moment..."
└── block_reddit_ratelimit.html      # "Whoa there, pardner"
```

Each fixture has a companion `.expected.json` with the exact field values the parser must produce.
Tests assert field-by-field, not "did not crash".

**A `refresh_fixtures.py` script** re-downloads them on demand and prints a diff, so drift is
detected deliberately rather than discovered in production. A weekly canary job fetches one live
page, runs the parser, and alerts if the extracted item count is zero — the early-warning system for
a markup change.

---

## 10. Scraper implementations

### 10.1 `BaseScraper`

```python
class BaseScraper(ABC):
    def __init__(self, client: RedditClient, config: dict, repo: LeadRepository): ...

    @abstractmethod
    def collect(self, ctx: ScrapeContext) -> Iterator[list[dict]]:
        """Yield pages of raw post dicts."""

    def run(self, session, ctx: ScrapeContext) -> ScrapeReport:
        scorer = LeadScorer(self.config, session)
        report = ScrapeReport(subreddit=ctx.subreddit)
        for page in self.collect(ctx):
            report.posts_seen += len(page)
            for post in self.repo.filter_new(session, page):        # batched dedup
                res = scorer.score_post(post["title"], post["body"] or "",
                                        post["score"], post["num_comments"],
                                        post["created_utc"])
                if scorer.is_lead(res, min_score=ctx.min_score):
                    session.add(self._to_lead(post, res, ctx))
                    report.leads_created += 1
            session.commit()                                        # per page, crash-safe
            if report.leads_created >= ctx.remaining_lead_budget:
                report.truncated = True
                break
        self._record_scrape_run(session, ctx, report)
        return report
```

The per-page commit preserves today's "a crash mid-run keeps completed work" property, at finer
granularity than the current per-subreddit commit.

### 10.2 Subclasses

| Class | `collect()` | Change from today |
|---|---|---|
| `SubredditScraper` | `_paginate(/r/{sub}/new/)` | Project-aware, batched dedup, `session_key=f"sub:{sub}"` |
| `KeywordScraper` | one `_paginate` per query, encoded, tiered thresholds | Encoding fix, pagination fix, per-tier `min_score` |
| `CommentScraper` | per-lead permalink fetch | **New** — wires up the never-called parser |
| `UserScraper` | `_paginate(/user/{n}/submitted/new/)` | Behaviour identical; base-class refactor only |

`KeywordScraper` gains per-tier thresholds so that a `high` keyword can qualify at a lower total
score than a `low` one — the keyword's own tier is evidence:

```python
TIER_MIN_SCORE = {"high": 3.0, "medium": 5.0, "low": 8.0}
```

### 10.3 Ordering determinism

`SCRAPER_ORDER = ("subreddit", "keyword", "user")` is defined once in `src/scrapers/__init__.py` and
imported by both `main.py` and the dashboard route, fixing the divergence in
[00 §4.10](00-current-state.md).

---

## 11. Progress and observability

Emitted to `run_events` as the run proceeds:

```
scrape.subreddit.start      {subreddit, queries: 12, mode: "both"}
scrape.page                 {subreddit, page: 3, items: 25, new: 7}
scrape.rate_limited         {proxy: "45.38.107.97:6014", retry_after: 60}
scrape.proxy_blacklisted    {proxy: "…:6462", reason: "403", seconds: 1800}
scrape.subreddit.done       {subreddit, posts_seen: 187, leads: 23, duration_s: 214}
scrape.truncated            {reason: "max_total_leads", limit: 2000}
comments.start              {posts: 100}
comments.done               {comments: 2140, backfilled_scores: 63}
```

Live progress is derived from `jobs` grouped by state, so the progress bar reflects real completion
rather than an estimate. ETA uses observed mean request latency × remaining request budget.
