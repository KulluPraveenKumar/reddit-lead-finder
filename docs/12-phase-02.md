# Phase 02 — Proxy Service & Hardened Scraping Transport

**Completion after this phase: 24%**

## 1. Objective

Route every outbound HTTP request — Reddit scraping now, website crawling in Phase 4 — through a
rotating Webshare proxy pool with health checking, blacklisting, retries, exponential backoff,
caching, and metrics, and fix the confirmed transport and parser defects — **without changing the
behaviour, signature, or output of any existing scraper, route, or CLI command.**

Success is an operator running `python main.py scrape` exactly as today and getting *more* results,
from rotating IPs, with no configuration change beyond a `.env` entry.

## 2. Scope

### 2.1 In scope

- `src/net/`: `ProxyEndpoint`, `ProxyManager`, `ProxiedHTTPClient`, `RetryPolicy`, header profiles,
  HTTP response cache, in-process metrics, pool circuit breaker
- Proxy file parsing from `PROXY_FILE` with hard redaction guarantees
- Health checking against an IP-echo endpoint, including **exit-IP leak detection**
- `RedditClient` refactor: transport delegated to `ProxiedHTTPClient`, **public API frozen**
- **Bug fixes:** search pagination selector, URL encoding, search-score semantics, `href`-following
  pagination, loop guards
- New optional `sort` / `t` parameters on `search_posts`
- Golden HTML fixtures for every parser path
- `src/db/repositories/` — `LeadRepository.filter_new()` (the N+1 fix), `search()`,
  `keyword_breakdown()`
- Revision `0003_net_infrastructure` — `proxies`, `http_cache`, `metrics`
- `/health/proxies`

### 2.2 Out of scope

- Any AI change — `AIService` is complete from Phase 1 and untouched here
- Website crawling (Phase 4), though it will consume this client
- Orchestration (Phase 3)
- Concurrency beyond the per-proxy throttle

## 3. Architecture

```
  SubredditScraper ──┐
  KeywordScraper   ──┼──► RedditClient  (public API UNCHANGED)
  UserScraper      ──┘         │  _get() delegates transport
                               ▼
                    ┌──────────────────────────────┐
                    │     ProxiedHTTPClient        │
                    │  cache → acquire → throttle  │
                    │  → request → classify        │
                    │  → release → retry/backoff   │
                    └───┬──────────┬───────────┬───┘
                        │          │           │
                 ┌──────▼───┐ ┌────▼─────┐ ┌───▼──────┐
                 │ProxyMgr  │ │HTTPCache │ │ Metrics  │
                 │rotation  │ │TTL+bound │ │ counters │
                 │health    │ └──────────┘ └──────────┘
                 │blacklist │
                 │sticky    │        also consumed in Phase 4 by
                 │circuit   │        WebsiteFetcher — src/net/ is
                 └────┬─────┘        Reddit-agnostic by construction
                      │ one requests.Session per proxy
              ┌───────▼────────────────────────────┐
              │ 10 × ProxyRuntime                  │
              │ own cookie jar · own header profile│
              │ own connection pool                │
              └────────────────────────────────────┘
```

Detail in [08-proxy-service.md](08-proxy-service.md). `src/net/` contains **zero** Reddit
identifiers — grep-verified.

## 4. Files affected

**New**

| File | Purpose |
|---|---|
| `migrations/versions/0003_net_infrastructure.py` | `proxies`, `http_cache`, `metrics` |
| `src/net/proxy_models.py` | `ProxyEndpoint`, `ProxyState`, `ProxyRuntime`, `ProxyLease`, `ProxyStats` |
| `src/net/proxy_manager.py` | Pool, rotation, health, blacklist, sticky, circuit breaker |
| `src/net/http_client.py` | `ProxiedHTTPClient` |
| `src/net/retry.py` | `Outcome`, classifiers, `backoff`, `_is_block_page` |
| `src/net/user_agents.py` | 6 internally consistent header profiles |
| `src/net/cache.py` | TTL response cache with a size bound |
| `src/net/metrics.py` | Counters, latency windows |
| `src/net/errors.py` | Exception hierarchy |
| `src/db/repositories/{base,leads,proxies}.py` | Query objects |
| `src/dashboard/templates/health_proxies.html` | Proxy table |
| `scripts/refresh_fixtures.py` | Re-download golden HTML |
| `tests/fixtures/html/*` | 10 golden pages + `.expected.json` |

**Modified**

| File | Change |
|---|---|
| `src/reddit_client.py` | `_get` → `ProxiedHTTPClient`; `href` pagination; **search selector fixed**; query encoding; `score=None`; `sort`/`t`; loop guards |
| `src/scoring.py` | `upvotes is None` = unknown, not zero |
| `src/scrapers/*.py` | Dedup via `LeadRepository.filter_new()` — behaviour identical, 25 queries → 1 |
| `src/subreddit_loader.py` | `get_scoring_settings` — 10 queries → 1, output-identical |
| `src/dashboard/routes.py` | `index()` uses `LeadRepository.search()` — snapshot-identical output |
| `src/dashboard/routes_health.py` | +`/health/proxies` |
| `config.yaml` | New `proxy:` section |
| `.env.example` | `+PROXY_FILE` |
| `main.py` | Startup proxy health summary; `--no-proxy` debug flag |

## 5. Database changes

**`0003_net_infrastructure`** — `proxies`, `http_cache`, `metrics`
([05 §5.6](05-database-plan.md)).

`proxies` stores host, port, and health **only**. No username, no password — verified by
`PRAGMA table_info(proxies)` in Part A.

## 6. APIs

| Method | Route | Response |
|---|---|---|
| `GET` | `/health/proxies` | HTML table; JSON with `Accept: application/json` |
| `POST` | `/health/proxies/check` | Force a health check; returns the new snapshot |
| `GET` | `/health` | +`proxies_healthy`, `proxies_total`, `circuit` |

All 17 legacy endpoints unchanged.

## 7. UI changes

`/health/proxies` in the existing dark theme:

```
Pool: 10 total · 9 healthy · 0 cooldown · 1 blacklisted (12m 04s)
Circuit: CLOSED    Requests/min: 47    Success: 96.2%    [Re-check now]

 PROXY                  STATE        REQS  FAIL  P50    P95   LAST ERROR
 31.59.20.176:6754      healthy       412     3  840ms  2.1s  —
 198.105.121.200:6462   blacklisted   201    41  1.4s   5.8s  HTTP 403 (3m ago)
```

**No credential appears anywhere on this page.** A "Proxies" link is added under Health.

## 8. AI changes

**None.** `AIService` is complete and untouched.

One forward-looking note: because `src/net/` is Reddit-agnostic, Phase 4's `WebsiteFetcher` will
consume `ProxiedHTTPClient` unchanged and inherit rotation, retries, caching, and metrics for free.
That is the payoff for building it as infrastructure rather than as part of the scraper.

## 9. Backend changes

### 9.1 `RedditClient` — every change

| Change | Before | After |
|---|---|---|
| Transport | `self.session.get(url, timeout=30)` | `self.http.get(url, session_key=...)` |
| Retry | 429 only, once | Full policy in `ProxiedHTTPClient` |
| Delay | fixed 2.0 s, global | random 3–7 s, **per proxy** |
| Listing pagination | regex `after=`, rebuild URL | Follow `href` directly |
| **Search pagination** | `select_one("nav-buttons a[…]")` — **always `None`** | `select_one("span.nextprev a[rel='nofollow next']")` |
| Query encoding | f-string interpolation | `urlencode(..., quote_via=quote_plus)` |
| Search score | `0` | `None` |
| Loop safety | none | `max_pages=20`, in-loop `seen`, `next_url == url` guard |
| `sort` / `t` | absent | keyword-only, defaults preserve today's behaviour |

The search selector was an **element**-type selector for a tag that does not exist
([00 §4.1](00-current-state.md)); search has therefore never advanced past page 1.

### 9.2 `LeadScorer`

```python
if upvotes is None:
    upvote_score = 0.0
    self._unknown_upvotes = True        # recorded in the breakdown
else:
    upvote_score = min(upvotes, 100) * self.upvote_weight
```

**No existing score changes** — a regression test re-scores all 459 leads and asserts
byte-identical `intent_score`.

### 9.3 Batched dedup

```python
def filter_new(self, session, posts: list[dict]) -> list[dict]:
    ids = [p["id"] for p in posts]
    existing = set(session.execute(
        select(Lead.reddit_id).where(Lead.reddit_id.in_(ids))).scalars())
    return [p for p in posts if p["id"] not in existing]
```

One query per page of 25 instead of 25 queries. Chunked under SQLite's 999-variable limit.

### 9.4 Session-key convention

| Caller | `session_key` | Reason |
|---|---|---|
| Subreddit listing / keyword search / metadata | `f"sub:{subreddit}"` | Whole cursor walk on one IP |
| User submissions | `f"user:{username}"` | |
| Health check | `None` | Never sticky |

## 10. Frontend changes

- `health_proxies.html`, auto-refreshing every 10 s and pausing when the tab is hidden
- Header link under Health

## 11. Risks

| Risk | Mitigation |
|---|---|
| A proxy silently fails open, leaking the operator's real IP | Exit-IP comparison on every health check; `ProxyLeakError` is fatal |
| Block page cached → run silently returns zero | `_is_block_page` runs **before** the cache write; test asserts a 200 block page is never cached |
| Proxies degrade throughput below usable | Per-proxy throttle means 10 proxies ≈ 10× a single IP; measured in Part B |
| Fixing search pagination floods the DB | Expected and desirable — Part B measures the delta explicitly |
| A `RedditClient` signature change breaks a scraper | Signature freeze verified by introspection test |
| Webshare credentials leak into a log | `repr=False`; `RedactingFilter`; full-log grep test |
| Repository refactor changes `GET /` output | Rendered-HTML snapshot diff |
| Sticky sessions ossify onto one proxy | `sticky_ttl_s=1800`; re-pin on failure; distribution asserted |

## 12. Dependencies

**Upstream:** Phase 1 (Alembic, pragmas, `session_scope`, logging, settings resolution).

**New packages:** none.

**External:** `PROXY_FILE` pointing at a readable Webshare file; outbound HTTPS to the proxies and
to `api.ipify.org`.

## 13. Acceptance criteria

Verified 2026-07-31. "live" = run against the real proxy pool and `old.reddit.com`;
"test" = offline, in the suite. Evidence for each is in `docs/PHASE-02-STATUS.md` §3.

- [x] AC1 — `python main.py scrape` completes with proxies enabled — **live**: 200 posts
      scanned, 7 new leads, no exception. See the caveat on block rate in AC-notes below.
- [x] AC2 — Every Reddit request exits from a proxy IP; **zero** from the local IP — **live**:
      10/10 proxies returned distinct exit IPs, none equal to this machine's; plus a test
      asserting every outbound call carries a proxy.
- [x] AC3 — Blacklisting one proxy mid-run does not fail the run — **test** + **live** (8 of 10
      proxies blacklisted during the AC1 run; the run still completed).
- [x] AC4 — Search pagination returns **more than 25** results where more exist — **live**: 47
      unique posts. This was the headline bug; see AC-notes.
- [x] AC5 — A query containing a space, `&`, and `#` is correctly encoded and returns results —
      **live** + **test**.
- [x] AC6 — Search-sourced leads store `score = NULL`, not `0` — **live** + **test**.
- [x] AC7 — Re-scoring the 459 existing leads yields identical `intent_score` — **live**: the
      `upvotes or 0` coercion changed **0 of 459** scores.
- [x] AC8 — HTTP 429 with `Retry-After: 30` waits ≈30 s and retries on a **different** proxy —
      **test** (scripted 429; the slept duration and the proxy switch are both asserted).
- [x] AC9 — A 200 containing "Just a moment" is neither cached nor parsed — **test**.
- [x] AC10 — `/health/proxies` renders all 10 with **no credentials visible** — **live** against a
      real HTTP server: 10 rows, 0 credential tokens across 11 responses.
- [x] AC11 — A full log capture contains neither the proxy username nor password — **test**.
- [x] AC12 — Zero healthy proxies + `fail_closed: true` → clean exit with a clear message —
      **test**: raises `ProxyExhaustedError`, never falls back to the local IP.
- [x] AC13 — One dedup query per page, not 25 (statement counter) — **test**: 100 posts → 1
      `SELECT`, counted at the driver.
- [x] AC14 — `GET /` renders byte-identically; all 17 legacy endpoints unchanged — **live**: all
      pages 200 from a real server; the frozen API-contract test still passes.
- [x] AC15 — 459 leads intact — **live**: unchanged, and the baseline fingerprint test passes.
- [x] AC16 — `ruff` clean; coverage ≥ 85% on `src/net/` — **87%**, ruff clean, 248 tests passing.

### AC-notes (things a tick mark hides)

**AC1 block rate.** The run completed, but 24 of 36 requests were blocked and 8 of 10 proxies
ended blacklisted; pagination stopped early on 3 of 4 subreddits. `old.reddit.com` blocks these
datacenter proxies aggressively. The transport degrades exactly as designed — retry, rotate,
blacklist, keep going — but throughput is materially below what a clean pool would give.
Residential proxies would change this; nothing in the code will.

**AC4 was a two-`.nav-buttons` bug.** The search page carries two pagination groups: the first
pages the *subreddit* sidebar (`after=t5_`, zero post links), the second pages the posts
(`after=t3_`). The old code followed the first, so it paginated forever and returned nothing
past the first page — the 25-result ceiling. A test pins `after=t3_`.

**AC7's two apparent mismatches are not regressions.** Re-scoring flags 2 of 459 leads as
gaining `[HIGH]ai seo`. That keyword was added through the dashboard *after* those leads were
scored; it is a config change, not a scoring change. Keyword *ordering* differs on 14 more for
the same reason. `intent_score` itself moved on none.

## 14. Completion checklist

Done:

- [x] Revision `0003_net_infrastructure` with downgrade; still exactly one Alembic head
- [x] `src/net/` with no Reddit identifiers (grep test)
- [x] Proxy file parser: valid, malformed, duplicate, empty; **log lines carry no credential**
- [x] `ProxyEndpoint.__repr__`/`__str__` redact
- [x] Health checks: startup + on-demand + **exit-IP leak detection**
- [x] Circuit breaker: opens when nothing is usable, closes as proxies return from cooldown
- [x] `ProxiedHTTPClient` request algorithm: rotate, backoff, fatal, soft-block
- [x] `Retry-After` honoured, capped (at `RetryPolicy.max_delay`)
- [x] Soft-block detection **before** caching
- [x] Timeouts always `(connect, read)`
- [x] HTTP cache with TTL, size bound, non-OK exclusion
- [x] `RedditClient` public API unchanged (introspection test)
- [x] Search pagination selector fixed; `href`-following; loop guards
- [x] Query encoding; `sort`/`t` added
- [x] Search score `None`; `LeadScorer` treats it as unknown
- [x] `LeadRepository.filter_new/search/keyword_breakdown`
- [x] `get_scoring_settings` → one query, output-identical (was ten queries)
- [x] `/health/proxies` + `POST /api/health/proxies/check`, reachable from the nav
- [x] `config.yaml` gains a documented `proxy:` section

**Deliberately not built.** Each is a design item from the plan that the implementation did not
need; none is a silent omission, and each is cheap to add later if a real symptom appears.

- [ ] **Three rotation strategies** — one is implemented (least-recently-used with per-proxy
      pacing). Two more would be configuration surface with no evidence for choosing between
      them; LRU already spreads load evenly across the pool.
- [ ] **Sticky sessions with TTL and re-pin-on-failure** — a session (and therefore a cookie
      jar) is pinned per proxy for the process lifetime, which is what prevents cookie
      correlation across exit IPs. TTL and re-pin add expiry machinery with no observed failure
      to justify it.
- [ ] **Blacklist with per-cause durations and doubling; `COOLDOWN` probation** — a single
      cooldown is implemented. Per-cause doubling is tuning, and the AC1 run gave no signal
      about what the right per-cause values would be.
- [ ] **Half-open probe** — a blacklisted proxy simply re-enters rotation when its cooldown
      expires, and its next real request is the probe. A dedicated probe would spend an extra
      request per proxy to learn the same thing.
- [x] **`exclude=tried` guaranteeing a different proxy** — ✅ **DELIVERED IN P4.**
      `ProxyManager.acquire(exclude=…)` now filters explicitly and raises when every usable exit has
      already been tried for this request. The reasoning below was right that LRU *usually* produces
      the same outcome, and wrong that this makes enforcement unnecessary: the case it misses is a
      paced pool where the excluded exit is the only one ready, and there ordering hands back the IP
      that just failed. [29 §4.2](29-network-and-proxy-strategy.md) called this "the classic
      rotating-proxy bug"; mutation testing in P4 confirmed that removing the filter breaks four
      tests and that *no* pre-P4 test noticed. The original note is kept below.
- [ ] ~~**`exclude=tried` guaranteeing a different proxy**~~ — LRU ordering already yields a
      different proxy on retry (asserted in the AC8 test), but it is an emergent property, not
      an enforced one. Worth making explicit if a single-proxy pool ever misbehaves.
- [ ] **Adapter `max_retries=0`** — not set explicitly; `requests`' default already performs no
      retry for these calls, so the retry ladder is the only thing retrying.
- [ ] **10 golden HTML fixtures + `.expected.json`; `refresh_fixtures.py`** — three fixtures are
      captured (search page, listing page, soft-block interstitial) and asserted against
      inline expectations. The remaining seven and the refresh tooling are not built.
- [ ] `docs/testing/phase-02-testing.md` — superseded by `docs/PHASE-02-STATUS.md` §5, which
      carries the manual test script in the per-step format Phase 1 established.
