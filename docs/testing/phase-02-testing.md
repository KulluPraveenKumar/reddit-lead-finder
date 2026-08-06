# Phase 02 — Testing: Proxy Service & Hardened Scraping Transport

---

# PART A — Claude Verification

Claude verifies each item by reading code, running tools, and inspecting output. Every box must be
ticked before Part B begins.

## A1. Architecture

- [ ] `src/net/` contains **zero** Reddit-specific identifiers — `grep -ri "reddit\|subreddit\|lead" src/net/` returns nothing
- [ ] `ProxyManager` has no import from `src/scrapers/`, `src/db/`, or `src/dashboard/`
- [ ] `ProxiedHTTPClient` depends only on `ProxyManager`, `HTTPCache`, `RetryPolicy`, `Metrics`
- [ ] `RedditClient` holds a `ProxiedHTTPClient` and makes **no** direct `requests` call — `grep -n "requests\." src/reddit_client.py` shows only the import of exception types
- [ ] The six public `RedditClient` methods have unchanged signatures (verified by `inspect.signature` in a test)
- [ ] Dependency direction respected: nothing in `src/net/` imports upward

## A2. Compilation and imports

- [ ] `python -c "import src.net, src.reddit_client, src.scoring, src.dashboard.app"` succeeds
- [ ] `python main.py --help` renders the help panel
- [ ] No circular imports (`python -X importtime -c "import src.dashboard.app"` completes)
- [ ] All new modules have `__all__` or explicit exports
- [ ] No unused imports (`ruff check --select F401`)

## A3. Lint and formatting

- [ ] `ruff check .` — zero findings
- [ ] `ruff format --check .` — clean
- [ ] Line length ≤ 100 enforced by config
- [ ] No `print()` in `src/` (logging only) — `ruff check --select T20`

## A4. Typing

- [ ] Every public function in `src/net/` has parameter and return annotations
- [ ] `ProxyEndpoint`, `ProxyLease`, `ProxyStats` are dataclasses with typed fields
- [ ] `Outcome` is an `Enum`, not string literals
- [ ] Optional returns annotated `X | None`, never bare `X`
- [ ] Timeouts typed as `tuple[float, float]`

## A5. Edge cases

- [ ] Proxy file: missing → `ProxyConfigError` naming the path
- [ ] Proxy file: empty → `ProxyConfigError`
- [ ] Proxy file: all lines malformed → `ProxyConfigError`
- [ ] Proxy file: some lines malformed → parsed subset, warnings logged **without line content**
- [ ] Proxy file: duplicate `host:port` → deduped
- [ ] Proxy file: port `0`, `65536`, `abc` → skipped
- [ ] Password containing `@`, `:`, `/` → URL-quoted correctly
- [ ] All proxies blacklisted → `ProxyExhaustedError` naming seconds-to-next-available
- [ ] Single-proxy pool → rotation degenerates gracefully, no divide-by-zero
- [ ] Empty HTML response → parser returns `[]`, not a crash
- [ ] Listing page with zero posts → loop terminates
- [ ] Listing page with no next link → loop terminates
- [ ] `next_url == current_url` → loop terminates
- [ ] `max_pages` reached → loop terminates
- [ ] Malformed `data-timestamp` → `created_utc = None`, post still extracted
- [ ] Negative `data-score` → parsed correctly (`-5`)
- [ ] Missing `data-fullname` → post skipped, page continues
- [ ] Query with space, `&`, `#`, `+`, `?` → encoded correctly
- [ ] Unicode query → encoded correctly
- [ ] `Retry-After` non-numeric → falls back to default
- [ ] `Retry-After: 99999` → capped at 600

## A6. Error handling

- [ ] Every exception in the hierarchy is raised somewhere and caught somewhere
- [ ] `_get()` returns `None` on `ScraperError` — the existing caller contract
- [ ] `ProxyExhaustedError` propagates out of `_get()` (fatal, not swallowed)
- [ ] `ProxyLeakError` is fatal and never caught broadly
- [ ] No bare `except:` — `ruff check --select E722`
- [ ] No `except Exception: pass` anywhere in `src/net/`
- [ ] Each exception message includes actionable context (URL, proxy key, attempt count)

## A7. Security

- [ ] `ProxyEndpoint.username` / `.password` declared `field(repr=False)`
- [ ] `repr(endpoint)` and `str(endpoint)` contain neither credential (unit-tested)
- [ ] No credential in any log line — full-run log capture grepped
- [ ] No credential in any template or API response
- [ ] `.env` and `*proxies*.txt` in `.gitignore`
- [ ] `git status` shows no credential file as untracked-but-present in the repo
- [ ] `RedactingFilter` registered on the root logger
- [ ] Proxy file read with an explicit encoding; not written back

## A8. Performance

- [ ] Per-proxy throttle, not global — 10 requests across 10 proxies do **not** take 10 × delay
- [ ] `HTTPAdapter(pool_connections=2, pool_maxsize=4)` per proxy session
- [ ] Adapter `max_retries=0` (retry owned by the client)
- [ ] Cache lookup is O(1)
- [ ] Cache bounded; LRU eviction verified
- [ ] Metrics use bounded `deque`, not unbounded lists
- [ ] Health checks run on a background thread, not in the request path

## A9. Scalability

- [ ] `ProxyManager` handles a 100-endpoint file without behaviour change
- [ ] Sticky-session map is bounded by TTL eviction
- [ ] `tried` set is per-request, not global
- [ ] Cache memory bounded by an explicit byte cap
- [ ] No unbounded growth over a 1,000-request soak (memory sampled)

## A10. Logging

- [ ] Every request logs URL (redacted), proxy key, outcome, latency, attempt
- [ ] State transitions logged with the reason
- [ ] Blacklisting logs proxy key, cause, duration
- [ ] Circuit open/close logged at WARNING/INFO
- [ ] Health-check summary logged at startup
- [ ] `ProxyLeakError` logged at ERROR with the offending proxy key
- [ ] Log levels appropriate (per-request at DEBUG, not INFO)

## A11. Retries

- [ ] Max 4 attempts per URL, configurable
- [ ] Each attempt uses a **different** proxy while one is available (`exclude=tried`)
- [ ] Backoff is exponential with jitter
- [ ] `Retry-After` honoured on 429
- [ ] 404 never retried
- [ ] 403 blacklists and retries elsewhere
- [ ] Soft block blacklists and retries elsewhere
- [ ] Timeout/connection error retried
- [ ] Exhaustion raises with full context

## A12. AI-independence & efficiency

- [ ] `src/net/` contains no AI identifiers (grep `deepseek`, `ai_`, `llm`) → 0
- [ ] Nothing in this phase calls `AIService`
- [ ] The Phase-1 AI suite still passes unchanged
- [ ] `/settings/ai` and `/health/ai` still render
- [ ] A stored API key survives the `0003` migration and still validates
- [ ] **`ai_calls` count is unchanged by a full scrape** — this phase makes zero AI calls
- [ ] HTTP response cache prevents duplicate fetches (distinct from the AI cache)

## A13. Regression — existing features

- [ ] `python main.py scrape --scraper subreddit` completes
- [ ] `python main.py scrape --scraper keyword` completes
- [ ] `python main.py scrape --scraper user` completes (0 tracked users → clean exit)
- [ ] `python main.py dashboard` starts and serves `/`
- [ ] `python main.py add-user testuser` inserts a row
- [ ] `GET /` renders with 459 leads
- [ ] All 3 charts render
- [ ] Filter, sort, search, pagination all work
- [ ] Status change and delete work
- [ ] All 12 sidebar CRUD endpoints work
- [ ] `GET /api/leads/export` returns 13 columns
- [ ] `POST /api/scrape` returns `{"ok": true, "message": ...}`
- [ ] Contract test replaying all 17 endpoints passes

## A14. Test suite

- [ ] `pytest` passes
- [ ] Coverage ≥ 85% on `src/net/`
- [ ] 10 golden HTML fixtures present with `.expected.json` companions
- [ ] Parser tests assert **field values**, not just "no exception"
- [ ] No test makes a live network call
- [ ] Regression test: re-scoring all 459 leads yields identical `intent_score`

---

# PART B — Manual Testing

Execute in order. Record actual results and any deviation.

---

## Test 1 — Proxy pool loads and health-checks at startup

**Preconditions**
- `.env` contains `PROXY_FILE=%USERPROFILE%\Downloads\Webshare 10 proxies.txt`
- `config.yaml` has `proxy.enabled: true`
- Internet reachable

**Steps**
1. `python main.py dashboard`
2. Read the console output.
3. Open `http://127.0.0.1:5000/health/proxies`.

**Expected**
- Console prints a panel: `Proxy pool: 10 loaded · N healthy`
- Console prints `Egress verified: N distinct exit IPs, none matching local address`
- Startup completes in under 30 seconds
- The health page lists 10 rows
- Every row shows `ip:port` only — **no username, no password anywhere on the page**
- Each healthy row shows a latency figure

**Failure behaviour**
- 0 healthy + `fail_closed: true` → process exits with `No healthy proxies and fail_closed=true`
- Missing file → `ProxyConfigError` naming the path
- Malformed file → parsed subset, warnings that contain no credential

**Edge cases**
- Set `PROXY_FILE` to a non-existent path → clear error, no traceback spam
- Blank the file → `ProxyConfigError`
- Corrupt one line → 9 proxies load, 1 warning
- Disconnect the network → all fail health check, `fail_closed` triggers

**Success criteria**
- ≥ 8 of 10 proxies healthy
- Zero credentials visible anywhere
- Startup < 30 s

---

## Test 2 — Egress actually goes through the proxies

**Preconditions** Dashboard running with proxies enabled.

**Steps**
1. Note your real public IP (visit `https://api.ipify.org` in a browser).
2. `python -c "from src.net import build_client; c=build_client(); print(c.get('https://api.ipify.org?format=json').text)"` — run it 5 times.
3. Compare each printed IP against your real IP and against the pool.

**Expected**
- Each printed IP is one of the 10 pool IPs
- **No printed IP equals your real IP**
- Successive calls show different IPs (rotation)

**Failure behaviour**
- Real IP printed → `ProxyLeakError` should have fired; if it did not, this is a **blocking defect**
- All calls same IP → rotation broken

**Edge cases**
- With `--no-proxy` → your real IP is printed and a warning is shown (expected)
- With one proxy blacklisted → the other 9 rotate

**Success criteria**
- 5/5 calls exit from pool IPs, ≥ 3 distinct

---

## Test 3 — Search pagination returns more than 25 results *(the Phase-1 bug fix)*

**Preconditions** Proxies healthy.

**Steps**
1. Record the pre-fix baseline: with the old code, `search_posts("startup", "startups", limit=50)` returned ≤ 25.
2. Run: `python -c "from src.reddit_client import RedditClient; print(len(RedditClient().search_posts('startup', subreddit='startups', limit=50)))"`
3. Repeat with `limit=100`.

**Expected**
- `limit=50` → **more than 25** results (typically 50)
- `limit=100` → up to 100
- Console shows multiple requests, not one

**Failure behaviour**
- Exactly 25 → the `span.nextprev` selector fix did not land
- 0 results → check the query and proxy health
- Duplicates in the list → the in-loop `seen` guard failed

**Edge cases**
- A query with genuinely < 25 results → returns what exists, terminates cleanly
- A nonsense query → 0 results, no crash
- `limit=10` → stops at 10 without fetching page 2

**Success criteria**
- \> 25 results for a broad query, all unique

---

## Test 4 — Query encoding

**Preconditions** Proxies healthy.

**Steps**
1. Search for `looking for` (with a space).
2. Search for `SaaS & tools`.
3. Search for `C# developers`.
4. Enable DEBUG logging and inspect the constructed URLs.

**Expected**
- Space → `+` or `%20`
- `&` → `%26` (not a parameter separator)
- `#` → `%23` (not a fragment)
- All three return results

**Failure behaviour**
- Raw space in the URL → encoding fix missing
- `&`-query silently returns unrelated results → the query was truncated at the `&`

**Edge cases**
- Empty query → rejected before the request
- 300-character query → truncated or rejected with a clear message
- Emoji in the query → encoded, no crash

**Success criteria**
- All three URLs correctly percent-encoded; all return results

---

## Test 5 — Retry on failure with proxy switching

**Preconditions** Ability to edit config; a temporary bad proxy line.

**Steps**
1. Add a deliberately dead entry (`1.2.3.4:9999:x:y`) to a **copy** of the proxy file; point `PROXY_FILE` at the copy.
2. Restart; observe the health check marking it unhealthy.
3. Run a scrape.
4. Inspect logs for retry lines.

**Expected**
- The dead proxy is marked unhealthy at startup
- It is not selected for requests
- If selected before health check, the request retries on a **different** proxy
- The scrape completes successfully

**Failure behaviour**
- Retries against the same dead proxy → `exclude=tried` broken
- Scrape aborts → the run should survive a single dead proxy

**Edge cases**
- 5 of 10 dead → scrape completes, slower
- 10 of 10 dead → `ProxyExhaustedError`, clean failure message
- A proxy that dies mid-run → blacklisted, run continues

**Success criteria**
- Scrape completes with one dead proxy; logs show retries on different IPs

---

## Test 6 — Rate limit handling

**Preconditions** Ability to run a burst.

**Steps**
1. Temporarily set `min_delay_s: 0.1`, `max_delay_s: 0.2`.
2. Run a large keyword scrape to provoke 429s.
3. Watch the logs and `/health/proxies`.
4. **Restore the delays afterward.**

**Expected**
- 429 logged with the `Retry-After` value
- That proxy is blacklisted for the stated duration
- The request retries on a different proxy
- The blacklist countdown is visible on the health page
- No unhandled exception

**Failure behaviour**
- Run aborts on the first 429 → retry policy not wired
- Hammering after a 429 → `Retry-After` ignored

**Edge cases**
- All proxies rate-limited → `ProxyExhaustedError` with seconds-to-next
- 429 with no `Retry-After` → default 60 s used

**Success criteria**
- 429s are absorbed; the run completes; delays are restored

---

## Test 7 — Block-page detection

**Preconditions** A fixture harness that can inject a response.

**Steps**
1. Point the client at a local server returning HTTP 200 with body `<html>Just a moment...</html>`.
2. Issue a request.
3. Inspect the cache table/dict.
4. Inspect proxy state.

**Expected**
- Response classified `SOFT_BLOCK`, not `OK`
- **Not cached**
- Proxy blacklisted 15 minutes
- Retried on a different proxy
- Parser never sees the block page

**Failure behaviour**
- Block page cached → **blocking defect**; a run would silently return zero for 15 minutes
- Parsed as a real page → 0 posts extracted, silently

**Edge cases**
- 200 with a 300-byte body → treated as a block (length heuristic)
- 200 with "you've been blocked" → detected
- Legitimate short page (e.g. an empty search) → **must not** be misclassified — verify with the `search_empty.html` fixture

**Success criteria**
- Block page never cached, never parsed; empty-results page correctly treated as OK

---

## Test 8 — Sticky sessions

**Preconditions** Proxies healthy; DEBUG logging.

**Steps**
1. Scrape one subreddit with `limit=100` (4 pages).
2. Grep logs for the proxy key used on each of the 4 requests.
3. Scrape a second subreddit; compare.

**Expected**
- All 4 pages of subreddit A use the **same** proxy
- Subreddit B likely uses a different one
- If A's proxy is blacklisted mid-walk, a new one is pinned and logged

**Failure behaviour**
- Rotation within one walk → sticky not applied
- Every subreddit on one proxy → over-sticky; check TTL and rotation

**Edge cases**
- Pinned proxy blacklisted → re-pin, walk continues
- `sticky_sessions: false` → rotation every request
- 15 subreddits, 10 proxies → reuse expected, distribution roughly even

**Success criteria**
- Intra-walk stickiness holds; inter-subreddit distribution is spread

---

## Test 9 — Response cache

**Preconditions** Cache enabled, TTL 900 s.

**Steps**
1. Fetch `https://old.reddit.com/r/SaaS/` and time it.
2. Fetch the same URL again immediately; time it.
3. Check `http.cache_hit` in metrics.
4. Wait past the TTL (or force-expire) and refetch.

**Expected**
- First fetch: normal latency + throttle delay
- Second fetch: near-instant, no proxy used, cache-hit counter increments
- After expiry: full fetch again

**Failure behaviour**
- Second fetch also slow → cache not consulted
- Stale data after expiry → TTL not enforced

**Edge cases**
- 404 → not cached (verify by refetching and seeing a second request)
- Cache size cap exceeded → oldest evicted, no unbounded growth
- `use_cache=False` → always fetches

**Success criteria**
- Cache hit under 10 ms; expiry respected; non-200 never cached

---

## Test 10 — Circuit breaker

**Preconditions** Ability to force pool-wide failure.

**Steps**
1. Block outbound traffic to all proxy IPs (firewall rule) **or** point the pool at unreachable hosts.
2. Start a scrape.
3. Observe the log and `/health/proxies`.
4. Restore connectivity and wait for the probe.

**Expected**
- Failures accumulate; after the threshold within the window, the circuit **opens**
- Subsequent calls raise `CircuitOpenError` immediately (no network attempt)
- Health page shows `Circuit: OPEN`
- After `open_duration_s`, a single probe is attempted
- On success the circuit closes and the run resumes

**Failure behaviour**
- Hundreds of failing requests with no circuit → breaker not wired
- Circuit never closes → half-open logic broken

**Edge cases**
- Failures spread below the threshold → circuit stays closed
- Probe fails → reopens with a doubled duration

**Success criteria**
- Circuit opens within ~30 failing requests, closes after recovery

---

## Test 11 — Existing scrapers unchanged

**Preconditions** Live database backed up.

**Steps**
1. Record `SELECT COUNT(*) FROM leads` (expect 459).
2. `python main.py scrape --scraper subreddit`
3. `python main.py scrape --scraper keyword`
4. Recount leads; inspect new rows.
5. `python main.py dashboard`; open `/`.

**Expected**
- Both scrapers complete without error
- New leads have the same column shape as existing ones
- `search`-sourced leads have `score = NULL`
- Existing 459 rows unchanged (`intent_score` identical)
- Dashboard renders, charts render, filters work

**Failure behaviour**
- A scraper raises → the `RedditClient` API changed
- Existing scores changed → the `LeadScorer` change was not backward compatible

**Edge cases**
- Run with proxies disabled → still works
- Run twice → second run inserts near-zero (dedup)

**Success criteria**
- Both scrapers work unmodified; 459 existing rows byte-identical

---

## Test 12 — No credential leakage

**Preconditions** A full run's logs captured to file.

**Steps**
1. `python main.py scrape > run.log 2>&1`
2. `grep -i "sff3dv6jimdr" run.log` (the password from the fixture)
3. `grep -i "wvwefhhu" run.log` (the username)
4. Inspect `data/leads.db` for credentials: `SELECT * FROM proxies` (Phase 2) — this phase, confirm no DB writes.
5. View source of `/health/proxies`.
6. `git status` and `git check-ignore .env`

**Expected**
- Both greps return **zero** matches
- No credential in any HTML source
- `.env` is gitignored
- The proxy file is not in the repo

**Failure behaviour**
- **Any** match is a blocking defect. Do not proceed to Phase 2.

**Edge cases**
- Force an error path (bad proxy) → the error message contains `ip:port` only
- Enable DEBUG logging → still no credential

**Success criteria**
- Zero matches across logs, HTML, database, and repo

---

## Test 13 — Golden-fixture parser regression

**Preconditions** Fixtures present.

**Steps**
1. `pytest tests/unit/test_parsers.py -v`
2. Manually corrupt one fixture (rename `data-fullname` to `data-fullnam`).
3. Re-run.
4. Restore the fixture.

**Expected**
- All parser tests pass initially
- The corrupted fixture causes a **specific field assertion failure**, not a crash
- After restore, all pass

**Failure behaviour**
- Tests pass with a corrupted fixture → assertions are too weak (checking only "not empty")

**Edge cases**
- Empty fixture → parser returns `[]`
- Block-page fixture → classified as a block, not parsed

**Success criteria**
- Field-level assertions catch corruption

---

## Test 14 — Throughput

**Preconditions** Proxies healthy, default delays (3–7 s).

**Steps**
1. Time a scrape of 3 subreddits at `limit=100`.
2. Count total requests from metrics.
3. Compute requests/minute.
4. Repeat with `proxy.enabled: false` and 1 IP.

**Expected**
- With 10 proxies: substantially higher throughput than with 1
- Per-proxy rate ≈ 12 req/min (5 s mean delay)
- Aggregate ≈ 60–120 req/min
- No 429s at this rate

**Failure behaviour**
- Same throughput as single-IP → the throttle is global, not per-proxy — a design defect
- 429s at this rate → delays too aggressive; increase

**Edge cases**
- 2 proxies → roughly 2× single-IP
- Delays set to 1 s → faster, but watch for 429s

**Success criteria**
- ≥ 3× the single-IP throughput; zero 429s at default settings

---

---

## Test 15 — Dedup query count

**Preconditions** Migrated DB.

**Steps**
1. Enable SQLAlchemy statement logging (or attach the test's statement counter).
2. Run `python main.py scrape --scraper subreddit` for one subreddit.
3. Count `SELECT ... FROM leads WHERE leads.reddit_id IN` statements.
4. Count total posts processed.

**Expected**
- One `IN` query per page of 25, not one per post
- For 100 posts: ~4 dedup queries, not 100

**Failure behaviour**
- 100 queries → `filter_new` not adopted by the scraper
- 0 queries → dedup skipped entirely (would create duplicates)

**Edge cases**
- Page of 0 posts → 0 queries
- Page of 1,000 ids → chunked into multiple queries under the 999-variable limit

**Success criteria**
- Query count scales with pages, not posts

---

---

## Test 16 — Dashboard unchanged

**Preconditions** Migrated DB; a pre-migration HTML snapshot of `/`.

**Steps**
1. Open `/` and save the HTML source.
2. Diff against the pre-migration snapshot (ignoring only timestamp-bearing lines).
3. Click through: each filter, each sort option, pagination pages 1–3.
4. Change one lead's status; delete a test lead; re-add nothing.
5. Export CSV; open it.
6. Exercise all six sidebar cards.

**Expected**
- HTML diff is empty apart from timestamps
- All filters, sorts, and pagination behave identically
- Status change and delete work
- CSV has exactly 13 columns and the same header text
- All sidebar CRUD works

**Failure behaviour**
- Any diff beyond timestamps → the repository refactor changed the query or ordering
- CSV column count ≠ 13 → export changed prematurely

**Edge cases**
- Filter combination producing 0 results → empty state, not an error
- Page beyond the last → clean handling

**Success criteria**
- Byte-identical rendering; all interactions unchanged

---

---

## Test 17 — Proxy state persistence

**Preconditions** Phase 1 complete; Phase 2 migrated.

**Steps**
1. Start the dashboard; let health checks run.
2. `SELECT host, port, state, total_requests FROM proxies;`
3. Run a scrape.
4. Re-query — counters should have advanced.
5. Restart the app; re-query.

**Expected**
- 10 rows, one per proxy
- **No username or password columns exist**
- Counters persist across restart
- Blacklist state persists

**Failure behaviour**
- Credentials present in the table → **blocking security defect**
- Counters reset → persistence not wired

**Edge cases**
- Proxy file changed between runs → removed proxies remain as historical rows; new ones added
- Blacklist expiring across a restart → handled by timestamp comparison

**Success criteria**
- State persists; zero credentials stored

---

---

## Test 18 — `get_scoring_settings` equivalence

**Preconditions** Live DB with 6 settings rows.

**Steps**
1. In a Python shell, call the **new** `get_scoring_settings(config, session)`.
2. Compare against the known live values: `keyword_weight=4, upvote_weight=2, comment_weight=2, recency_weight=1.5, high_intent_multiplier=2`.
3. Delete one settings row temporarily; re-call.
4. Restore the row.

**Expected**
- Returns exactly those five floats
- With a row missing → falls back to the YAML default for that key only
- One query issued, not ten

**Failure behaviour**
- Different values → the refactor changed precedence
- Exception on missing row → fallback broken

**Edge cases**
- All settings rows deleted → all YAML defaults
- A settings value of `"abc"` → clear error naming the key

**Success criteria**
- Output identical to the old implementation; one query

---

---

## Sign-off

| Test | Result | Notes |
|---|---|---|
| 1 Startup & health | ☐ Pass ☐ Fail | |
| 2 Egress verification | ☐ Pass ☐ Fail | |
| 3 Search pagination fix | ☐ Pass ☐ Fail | |
| 4 Query encoding | ☐ Pass ☐ Fail | |
| 5 Retry & switching | ☐ Pass ☐ Fail | |
| 6 Rate limiting | ☐ Pass ☐ Fail | |
| 7 Block-page detection | ☐ Pass ☐ Fail | |
| 8 Sticky sessions | ☐ Pass ☐ Fail | |
| 9 Response cache | ☐ Pass ☐ Fail | |
| 10 Circuit breaker | ☐ Pass ☐ Fail | |
| 11 Existing scrapers | ☐ Pass ☐ Fail | |
| 12 **Credential leakage** | ☐ Pass ☐ Fail | **Blocking** |
| 13 Golden fixtures | ☐ Pass ☐ Fail | |
| 14 Throughput | ☐ Pass ☐ Fail | |
| 15 Dedup query count | ☐ Pass ☐ Fail | |
| 16 Dashboard unchanged | ☐ Pass ☐ Fail | |
| 17 Proxy state persistence | ☐ Pass ☐ Fail | |
| 18 Scoring settings equivalence | ☐ Pass ☐ Fail | |

**Phase 2 complete when Part A is fully ticked and all 18 Part B tests pass.**
