# Phase 2 — Proxy Service & Scraping Transport: Status

**Date:** 2026-07-31 · **Status:** complete · **Tests:** 251 passing · **Coverage:** 87 % on `src/net/`

---

## 1. What Phase 2 was for

Phase 1 gave the project an AI layer. It could not yet reliably *get* anything to reason about:
every Reddit request left from this machine's own address, and the search path silently returned
at most 25 results no matter how many existed.

Phase 2 puts a proxy pool and a real transport under the scraper, and fixes the parser bugs that
the transport work exposed.

**Nothing about this is a rewrite.** `RedditClient`'s public API is unchanged — the same method
names, the same arguments, the same return shapes — and all 17 legacy dashboard endpoints still
respond exactly as before. The new code sits underneath.

---

## 2. What was built

### `src/net/` — a Reddit-agnostic network layer

Nothing in this package knows what a subreddit is. Phase 4's website fetcher is meant to reuse
it unchanged, and a grep test enforces the separation rather than trusting it.

| Module | Responsibility |
|---|---|
| `proxy_models.py` | `ProxyEndpoint`, file parsing. Credentials are private by construction. |
| `proxy_manager.py` | The pool: LRU rotation, pacing, blacklisting, cooldown, circuit breaker, health checks, exit-IP leak detection. |
| `http_client.py` | `ProxiedHTTPClient`: the retry/rotate/backoff ladder and block handling. |
| `blocks.py` | Classifies a response as `NONE` / `HARD` / `SOFT` / `EMPTY`. |
| `retry.py` | Maps a status or exception to `ROTATE` / `BACKOFF` / `FATAL` / `NONE`. |
| `user_agents.py` | Five coherent browser header profiles, pinned per proxy. |
| `cache.py` | Two-layer HTTP cache (memory + database) with TTL. |
| `metrics.py` | Request counters and latency percentiles, flushed to the `metrics` table. |

### Elsewhere

- **Migration `0003_net_infrastructure`** — adds `proxies`, `http_cache`, `metrics`. Alters
  nothing existing, so live rows are untouched.
- **`src/db/repositories/leads.py`** — `LeadRepository`, replacing per-post dedup queries.
- **`src/reddit_client.py`** — rewritten internals behind a frozen public API; six bug fixes.
- **`/health/proxies`** — a new page, reachable from the navigation, plus
  `POST /api/health/proxies/check` for an on-demand live test.

---

## 3. The three findings that mattered

### 3.1 The 403s were a fingerprint problem, not an IP problem

Every one of the 10 proxies got HTTP 403 from `old.reddit.com` — **and so did the local IP**.
That ruled out the proxies immediately: ten unrelated datacenter addresses and a residential one
do not all get blocked at the same instant for being the wrong address.

The cause was header incoherence. The legacy header set paired a **Chrome** `User-Agent` with
**Firefox's** `Accept-Language: en-US,en;q=0.5`, and sent no `Sec-CH-UA` or `Sec-Fetch-*` at all
— a combination no real browser produces. Swapping in a coherent Chrome profile returned **200
through the same proxy seconds later**.

This is why `user_agents.py` builds whole profiles rather than picking a random UA string, and
why the tests assert that Chrome profiles carry client hints and Firefox profiles do not.

### 3.2 Search pagination followed the wrong pager

`old.reddit.com/search` renders **two** `.nav-buttons` groups:

| Group | Paginates | `after=` prefix | Post links |
|---|---|---|---|
| 1 | the subreddit sidebar | `t5_` | 0 |
| 2 | the posts | `t3_` | 25 |

The old code selected the first one. Following it paginates through *subreddits* forever while
returning zero posts — which is exactly the "search never returns more than 25 results" symptom.

Worth noting because the obvious fix is also wrong: the bare tag selector `nav-buttons` matches
**0** elements, so a naive "the selector is broken, use the class" fix lands on group 1 and
changes nothing observable. The parser now selects the group containing `div.search-result-link`
and falls back to requiring `after=t3_`.

Verified live: **47 unique posts** for a query that previously capped at 25.

### 3.3 A block can arrive as HTTP 200

One captured response was 200 OK, 311 KB of valid HTML, with `<title>Welcome to Reddit</title>`,
`shreddit`/`faceplate` markers, and **zero** `div.thing` elements.

Left undetected this is worse than a 403: the scraper reports "no posts found", caches the
interstitial, and keeps reporting it for the whole TTL. `blocks.py` classifies it as `SOFT`, and
a block is never cacheable.

---

## 4. Verification — what was actually run

All 16 acceptance criteria pass. The checklist with per-AC evidence is in
`docs/12-phase-02.md` §13. Highlights:

| Check | Result |
|---|---|
| Subreddit scrape with proxies enabled | 200 posts scanned, 7 new leads, no exception |
| Keyword scrape (narrowed scope) | 10 leads, no exception |
| User scrape (against a real tracked author) | 2 leads, no exception |
| Duplicate `reddit_id` rows after all three | **none** |
| Proxy pool live check | 10/10 reachable, 10 distinct exit IPs |
| IP leak | **none** — no proxy exits from this machine's address |
| Search pagination | 47 unique posts (previously capped at 25) |
| Existing 459 leads re-scored | **0** score changes |
| Live database after all testing | still 459 rows; baseline fingerprint test passes |
| Credentials in any HTTP response | **0** across 11 endpoints |
| Dedup queries per 100-post page | **1** (was 100) |
| `ruff` | clean |
| Tests / coverage | 251 passing, 87 % on `src/net/` |

All scrape verification ran against a **copy** of the database, so the live 459-row baseline that
`test_live_database_preserved` fingerprints was not altered by testing.

`main.py scrape` drives all three scrapers, and all three had their dedup loops rewritten, so
each was executed separately rather than inferring the other two from the first. This mattered:
the user scraper returns early when no users are tracked, so the first attempt exercised none of
its changed code. It was re-run against a real tracked author to actually reach the loop.

### 4.1 The number the tick marks hide

The AC1 scrape completed — but the transport counters from that run were:

```
requests=36  ok=12  failed=24  blocked=24  cache_hits=0  p95=3182ms
pool: healthy=2  degraded=0  blacklisted=8  untested=0 / 10
```

**Two thirds of requests were blocked, and 8 of 10 proxies ended blacklisted.** Pagination
stopped early on 3 of the 4 subreddits; only r/startups paged fully.

This is the retry ladder working as designed — it rotated, backed off, blacklisted, and kept
going rather than failing the run — but an operator reading only "7 leads collected" would not
expect that. `old.reddit.com` blocks these datacenter proxies aggressively. Residential proxies
would change the number; nothing in this codebase will.

A blacklisted proxy is **not** dead. It returns to rotation when its cooldown expires (15 minutes
by default). A run that ends with most of the pool blacklisted and some leads collected has
behaved correctly.

---

## 5. Manual testing — `/health/proxies`

Phase 1 shipped a step-by-step guide with an expected result after every step. Phase 2 adds one
page and one button that sends real outbound traffic, so it gets the same treatment.

**Before you start:** run `python dev.py`, then open <http://127.0.0.1:5000>.

> ⚠️ If a page 404s on a route you expect to exist, a **stale server** is almost certainly still
> holding port 5000 — this bit us twice during development. On Windows, `pkill` from Git Bash
> does *not* kill Python. Use PowerShell:
> `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'main\.py|dev\.py' } | Stop-Process -Force`

| # | Step | Expected result |
|---|---|---|
| 1 | Look at the top navigation on any page. | A **Proxies** item appears between "AI Health" and "About". You never have to type a URL. |
| 2 | Click **Proxies**. | The Proxy Health page loads. Title "Proxy Health". No error banner. |
| 3 | Read the **Pool** card. | "Proxying" shows a green `enabled` pill. "Healthy" shows `N / 10`. "On exhaustion" reads **"stop the run (fail closed)"**. |
| 4 | Read the **Circuit** row. | Green `closed — proxies available`. If it is red `open`, no proxy is currently usable and scraping will stop rather than use your own IP. |
| 5 | Look at the **Proxies** table. | Exactly **10** rows. The first column shows `host:port` only — e.g. `31.59.20.176:6754`. |
| 6 | Look for a username or password anywhere on the page. | **There is none.** Credentials live only in the proxy file. This is deliberate and is enforced by a test. |
| 7 | Check the **Exit IP** column before running a check. | Every row reads *not checked* in italics. Loading the page sends no outbound traffic. |
| 8 | Click **Check all proxies**. | The button greys out and the line beside it reads "Checking… one request per proxy, this takes a few seconds." |
| 9 | Wait for it to finish (roughly 5–20 s). | The result line reads **"10 of 10 proxies reachable. No proxy exits from this machine's address."** |
| 9b | If instead you see an amber **LEAK CHECK DID NOT RUN** pill. | This machine's own address could not be determined, so no exit IP was compared against it. This is **not** a clean result — nothing was checked. Re-run when the network settles. |
| 10 | Look at the **Exit IP** column now. | Each row shows a distinct public IP. **None** of them is your own address. |
| 11 | If you ever see a red **IP LEAK** pill. | One or more proxies are not proxying — your real address is reaching Reddit through them. Stop scraping and check the proxy account. This is the single failure the pool exists to prevent. |
| 12 | Open <http://127.0.0.1:5000/api/health>. | The JSON contains a `proxies` block with `enabled`, `healthy`, `total`, `circuit_open`. This is what a monitor would alert on. |
| 13 | Open <http://127.0.0.1:5000/api/health/proxies>. | Full per-proxy JSON. Search it for your proxy password — **it is not there**. |
| 14 | Try to load `/api/health/proxies/check` in the browser address bar. | **405 Method Not Allowed.** The live check is POST-only, so a link, a prefetch or a browser refresh cannot fire ten outbound requests. |
| 15 | Run a scrape, then reload the Proxies page. | "Requests", "Failures", "Fail rate" and "Blocked" are now non-zero. Some proxies may show `degraded` or `blacklisted`. **This is expected** — see §4.1. |
| 16 | Note a proxy showing `blacklisted`, then wait 15 minutes and reload. | It has returned to rotation. Blacklisting is temporary by design. |

---

## 6. Security posture

The user's constraint was that proxy credentials must not reach the database, the logs, or the
UI. That is enforced in four independent places, so no single mistake exposes them:

1. **`ProxyEndpoint`** stores the username and password in fields marked `repr=False`, and
   overrides `__repr__`/`__str__` to emit `host:port`. Interpolating an endpoint into a log line
   cannot leak.
2. **The `proxies` table has no credential column at all.** A copied `leads.db` cannot become a
   compromised proxy account. A test asserts the column list, which is what keeps this true
   rather than merely intended today.
3. **`parse_proxy_line` does not echo the offending line** in its error message. A malformed
   line is usually a correct line with a typo — it still contains a real password, and error
   messages end up in tickets.
4. **`ProxyManager.snapshot()` emits labels only**, and it is the sole source for the health page
   and the JSON API.

Tests cover all four, including one that drives the pool through failures with log capture on and
asserts the username and password appear nowhere. Verified live against a running server: **zero**
credential tokens across 11 endpoint responses.

The one method that *does* expose credentials — `ProxyEndpoint.url()`, which must, or the proxy
would not authenticate — has a test pinning that it does. Without it, a suite asserting "no
credentials anywhere" would pass just as happily against a pool that could not connect.

---

## 7. Testing approach

251 tests, all offline. The suite gives the same answer whether or not Reddit is reachable.

The transport is tested through a **fake session** injected at `ProxyManager.session_for`, which
is the same seam the real client uses. That covers the whole retry ladder — rotation on 403,
backoff on 429 with `Retry-After`, fatal on 404, soft-block rejection, response size capping,
and cache write-through — without a network call.

**Every significant assertion was mutation-tested**: the guarantee was deliberately broken in the
source, the test was confirmed to fail, and the source was restored. This caught two tests that
passed for the wrong reason:

- The soft-block fixture test passed even with the marker list emptied, because the captured
  interstitial trips **two** independent detection paths. Each path now has its own minimal case.
- A cache test asserted the `verdict.cacheable` gate but was actually exercising the outer
  `not verdict.blocked` guard. It was replaced with the case `cacheable` genuinely
  discriminates: an `EMPTY` 200, which is returned to the caller but must not be cached.

A late review pass caught a third, in the code rather than a test: `health_check_all` computes
`local_ip_known`, but the endpoint dropped it from its response. If the local address could not
be determined, `leaking` is empty because **nothing was compared** — and the page said "No proxy
exits from this machine's address." A false negative, on the one check §6 calls the single
failure the pool exists to prevent. The field is now passed through and the page reports
"leak check did not run" as a distinct, amber outcome. Three tests pin the three states.

Two Phase 1 tests were also corrected. Both pinned a *value* that Phase 2 legitimately changes
rather than the property they were named for: one hardcoded the current Alembic head (it now
asserts the history has not branched), and one filtered baseline tables by an `ai_` name prefix,
which silently swept in every later phase's tables (it now uses an explicit frozen list).

---

## 8. Known limitations

1. **Block rate against `old.reddit.com` is high** — see §4.1. This is the main practical
   constraint on throughput and it is not fixable in code.
2. **`proxy_manager.py` coverage is 73 %**, below the rest of `src/net/`. The uncovered region is
   `health_check` / `direct_ip`, which make real outbound calls; the suite is offline by
   contract. They are verified live instead (§4).
3. **Three golden fixtures, not ten**, and no `refresh_fixtures.py`. Enough to pin the parsers
   that changed; not the full corpus the plan described.
4. **Several pool refinements were deliberately not built** — additional rotation strategies,
   sticky-session TTL, per-cause blacklist doubling, an explicit half-open probe. Each is listed
   with its reasoning in `docs/12-phase-02.md` §14. None is load-bearing today.
5. **`config.yaml` must single-quote the proxy file path.** In a double-quoted YAML scalar a
   backslash begins an escape, so `"C:\Users\..."` is a parse error. The file documents this
   inline; it cost real debugging time.

---

## 9. What Phase 3 inherits

- A transport that any fetcher can use, with no Reddit knowledge in it.
- A block classifier that distinguishes "blocked" from "genuinely empty" — the distinction that
  decides whether a scraper should retry or move on.
- A lead repository that batches dedup, so scraping more does not mean querying more.
- A health page pattern that reports state without exposing secrets.
