# P0 — Validation Sprint Report

**Executed:** 2026-08-05 · **Machine:** Windows, Python 3.12.5 · **Network:** residential, unproxied
baseline + 10 Webshare datacenter proxies

> Every number here was measured on this machine on this date. Nothing is estimated, inferred from a
> third party, or carried forward from a previous document. Where a measurement could not be taken,
> the row says **BLOCKED** and names what is needed — it does not guess.
>
> Raw output: [`measurements/p0-transport.json`](measurements/p0-transport.json).
> Probe source: `scripts/probe/`.

---

## 0. Headline

| # | Finding | Impact |
|---|---|---|
| **F1** | **Direct connection: 100% success, 0% blocks. Webshare: 71.4% success, 28.6% hard blocks.** Reproduced twice. | **AD-25 validated.** Direct is the default; Webshare is a fallback, not a requirement |
| **F2** | **RSS carries full selftext** (median 1,089 chars) | **U2 confirmed — the favourable branch.** RSS can replace the HTML listing fetch for bodies |
| **F3** | **RSS is rate-limited to 1 request per ~60 s per IP** | **U1 = per-IP.** Multireddit combining becomes mandatory, not optional |
| **F4** | **Reddit sends no `ETag` and no `Last-Modified` on RSS** | **U4 refuted.** Doc 28's layer L1 (conditional GET) does not exist and must be removed |
| **F5** | **Boolean multi-subreddit search works** — `(subreddit:A OR subreddit:B)` | **U3 confirmed.** 12 search requests, not 120 |
| **F6** | **Measured post volume is ~116/day across 4 subreddits, not ~1,000** | The cost model is *more* favourable than assumed |
| **F7** | **The 100-entry RSS window takes 20.6 h to fill** | Polling can be far less frequent than designed |
| **F8** | **Track B (Hermes) is BLOCKED** — no provider key, no Telegram token | 12 measurements deferred; nothing else depends on them |
| **F9** | **Two grep fences in doc 35 are mis-specified** — they must be AST-based | Documentation defect; the shipped enforcement is already correct |

**Six of six architecture assumptions that could invalidate implementation were testable and are now
measured. One (U4) is refuted. No architecture change is required — one documented layer is deleted
and one becomes mandatory.**

---

## 1. Track A — Transport comparison (U8)

### 1.1 Method

Seven requests per transport against `old.reddit.com`: four subreddit listings, one paginated walk,
one restricted search, one metadata page. Paced at a randomised 3–7 s per exit, matching the
production cadence — a burst would measure how Reddit responds to a burst, which is not the question.

Classification uses the **shipped** `src/net/blocks.py`, and headers use the **shipped**
`src/net/user_agents.py` profiles. A probe that hand-rolled either would measure the probe.

**Run twice**, ~40 minutes apart, to test consistency.

### 1.2 Results

| Metric | Direct | Webshare | Winner |
|---|---:|---:|---|
| Requests | 7 | 7 | — |
| **Success rate** | **100%** | **71.4%** | **Direct** |
| **Block rate** | **0%** | **28.6%** | **Direct** |
| Outcome mix | `ok: 7` | `ok: 5, hard_block: 2` | Direct |
| Mean latency (successful) | **1,341.7 ms** | 2,081.2 ms | **Direct, 1.55×** |
| p50 latency | 1,219 ms | 1,578 ms | Direct |
| p95 latency | 2,266 ms | 3,391 ms | Direct |
| Posts extracted | **175** | 125 | Direct |
| CPU seconds | **0.453** | 1.156 | **Direct, 2.55×** |
| Peak memory | 3,002 KB | 2,987 KB | tie |
| Exits used | 1 | 4 | — |
| **Exits that ever succeeded** | 1/1 | **2/4** | Direct |

**Consistency across the two runs: identical.** Both produced 100% / 0% for direct and 71.4% / 28.6%
for Webshare. Latency varied by ~15%; success and block rates did not vary at all.

### 1.3 Connection stability, retry, pagination, rate limiting

| Property | Direct | Webshare |
|---|---|---|
| Timeouts | 0 | 0 |
| Network errors | 0 | 0 |
| HTTP 429 | 0 | 0 |
| HTTP 403 | 0 | **2** — `45.38.107.97:6014`, `198.105.121.200:6462` |
| Soft blocks (200 with no posts) | 0 | 0 |
| Pagination (`?count=25`) | ✅ returned 25 posts | ✅ returned 25 posts |
| Connection reuse | ✅ one session, pinned profile | ✅ one session per exit |
| Mean failure latency | n/a — no failures | 1,672 ms (403s return fast) |

◐ `198.105.121.200:6462` is **the same proxy** [PHASE-02-STATUS §6](PHASE-02-STATUS.md) recorded as
403-blacklisted on 2026-07-31. Six days later it is still blocked. That is not noise; it is a
persistently burned address.

### 1.4 Egress verification — the leak check

| Check | Result |
|---|---|
| Proxies reachable | **10 / 10** |
| Distinct exit IPs | **10** |
| Exits matching the local address | **0 — no leak** |
| Local IP recorded for comparison | ✅ |

✅ The pool is genuinely proxying. The 28.6% block rate is Reddit refusing those addresses, not a
misconfiguration.

### 1.5 The finding underneath the finding

The first ad-hoc probe of this session used a hand-written header set — Chrome UA, no `Sec-CH-UA`,
no `Sec-Fetch-*`, no `Accept`. **It got HTTP 403 direct.** Switching to the shipped coherent profiles
produced 100%.

That independently reproduces [PHASE-02-STATUS §3.1](PHASE-02-STATUS.md) on a different date from a
different address: **the block is a fingerprint problem, not an address problem.** It is also a
warning — any future code path that constructs headers by hand will reintroduce a total outage that
looks exactly like an IP ban.

### 1.6 Recommendation

> ## ▶ **DIRECT**, with Webshare retained as a configured fallback.

The margin is **28.6 percentage points** on success rate, against a 10-point "similar" threshold.
Direct also wins on latency (1.55×), CPU (2.55×) and posts extracted. There is no dimension on which
the datacenter pool is better.

**This is not "drop the proxies".** [AD-25](ARCHITECTURE_FREEZE.md) is validated exactly as written:
egress is a policy, chosen per request class, with a degradation ladder. The measurement sets the
*default*, and the ladder — `direct → webshare` — is what P4 implements. Residential proxies remain
the [deferred](ARCHITECTURE_FREEZE.md) option if direct degrades at higher volume.

---

## 2. Track A — RSS validation

### 2.1 Results against the four unknowns that change the arithmetic

| # | Question | Answer | Evidence |
|---|---|---|---|
| **U1** | Per-feed or per-IP rate limit? | **PER-IP** | A *different* feed requested immediately after a successful one returned 429 |
| **U2** | Does `<content>` carry full selftext? | **YES** ✅ | median **1,089 chars**, max **4,588** over 100 entries |
| **U3** | Boolean `subreddit:A OR subreddit:B` in search? | **YES** ✅ | 50 entries spanning **2 distinct subreddits** |
| **U4** | Conditional GET → 304? | **NO** ⛔ | Neither `ETag` nor `Last-Modified` sent. `Cache-Control: private, max-age=3600` |
| **U5** | Is `?limit=100` honoured? | **YES** ✅ | **100 entries**, 228,639 bytes |
| **U6** | Does `old.reddit.com` serve RSS? | **YES** ✅ | 200, 25 entries, 56,241 bytes |
| **U7** | Do RSS and HTML share a budget? | **NO** | 14 HTML requests at 100% while RSS was capped at 1/min |

### 2.2 The rate limit, characterised

| Property | Measured |
|---|---|
| Budget | **1 request per IP** |
| Headers on success | `x-ratelimit-used: 1`, `x-ratelimit-remaining: 0.0`, `x-ratelimit-reset: 17–48` |
| Response when exhausted | **HTTP 429**, zero bytes |
| Recovery at 30 s | ❌ 429 |
| **Recovery at 60 s** | ✅ **200** |
| Effective budget | **~1 request / 60 s / IP → 1,440 RSS requests/day** |

◐ Against the ~28 requests/day the steady-state design needs
([28 §5.2](28-discovery-redesign.md)), 1,440/day is **50× more headroom than required**. The
constraint is not volume — it is that requests must be *spaced*, which a background poller does
naturally and a burst does not.

### 2.3 Feature validation

| Feature | Result | Detail |
|---|---|---|
| **Multireddit** `/r/a+b+c/.rss` | ✅ **works** | 3 distinct subreddits in one request |
| Restricted search `.rss` | ✅ works | 25 entries, single subreddit |
| Boolean sitewide search | ✅ works | 50 entries, 2 subreddits |
| `old.reddit.com` host | ✅ works | identical shape to `www` |
| Metadata completeness | ✅ title, author, link, updated, content — all present | |
| Score / comment count | ⛔ **absent**, as documented | must be back-filled from HTML |
| Freshness | ✅ newest entry **1.3 minutes old** | |

### 2.4 Verdict on RSS's role

> ## ▶ **PRIMARY DISCOVERY.**

U2 is the decisive one. Because `<content>` carries the selftext, RSS supplies title, author,
permalink, timestamp **and body** — everything the metadata triage and the content hash need. Only
`score` and `num_comments` are missing, and those feed a 0.05-weight engagement component and the
comment-fetch eligibility test, both of which can be back-filled later for the small number of items
that reach the admission gate.

Combined with U1 (per-IP) and the confirmed multireddit support, the shape is exactly what
[28 §3](28-discovery-redesign.md) designed:

```
1 multireddit RSS request  →  up to 100 newest posts across all watched subreddits,
                              with bodies, every 60+ seconds
```

**One documented layer must be deleted.** U4 is refuted: there is no conditional GET, so an idle poll
costs one full request (~56 KB), not ~0 bytes. See §5.

---

## 3. Track C — Environment and provider

### 3.1 Runtime

| Check | Result |
|---|---|
| Python | **3.12.5** |
| Platform | win32 |
| SQLite | **3.45.3** |
| WAL supported | ✅ |
| **`enable_load_extension` available and working** | ✅ **V-3 favourable** — the semantic tier can work on this host |

| Optional package | Installed | Needed by |
|---|---|---|
| `sqlite_vec` | ❌ | P12 (AD-16 — degrades cleanly if absent) |
| `model2vec` | ❌ | P12 |
| `trafilatura` | ❌ | P13 |
| `openpyxl` | ❌ | P27 |
| `python-json-logger` | ❌ | **P2** |

▶ None is installed, and none was installed by this probe. [AD-16](ARCHITECTURE_FREEZE.md) requires
the semantic tier to degrade cleanly when absent, so "absent" is a supported state — installing them
to make a probe green would have hidden the case that matters.

### 3.2 Live database — untouched, as required

| Check | Value | Expected | ✅ |
|---|---|---|---|
| Leads | **459** | 459 | ✅ |
| `intent_score` min / max / avg | **5.0 / 164.28 / 42.29** | 5.0 / 164.28 / 42.29 | ✅ |
| `scrape_runs` | 10 | 10 | ✅ |
| Alembic version | `0003_net_infrastructure` | 0003 | ✅ |
| Tables | 15 | — | — |
| **File mtime changed by this probe** | **No** | No | ✅ |

Opened **read-only** (`mode=ro`). P0's "no production code, no database writes" constraint holds.

### 3.3 V-5 — measured post volume

One multireddit feed across `SaaS + startups + Entrepreneur + marketing`:

| Metric | Measured |
|---|---|
| Entries returned | 100 |
| Window spanned | **20.63 hours** |
| **Posts per hour** | **4.8** |
| **Projected posts/day** | **116** |
| Newest entry age | 1.3 min |
| **Hours to fill the 100-entry window** | **20.6** |

**Distribution — and an anomaly worth flagging rather than explaining away:**

| Subreddit | Posts in window |
|---|---:|
| SaaS | 83 |
| startups | 10 |
| marketing | 4 |
| Entrepreneur | 3 |

◐ r/Entrepreneur and r/marketing are large communities and 3–4 posts in 20 hours is implausibly low
for them. Either the multireddit merge is not evenly interleaved, or those subreddits' `/new/` rate
genuinely differs from expectation. **This is not resolved.** It does not block anything — the
aggregate figure is what the cost model uses — but per-subreddit rates must be measured individually
in **P6**, where `observed_rate_per_hour` per watermark is computed anyway.

### 3.4 V-2 — DeepSeek pricing re-verified

| | `deepseek-v4-flash` | `deepseek-v4-pro` | Doc [02 §6.2](02-research-findings.md) |
|---|---:|---:|---|
| Input, cache hit | **$0.0028** | $0.003625 | $0.0028 ✅ |
| Input, cache miss | **$0.14** | $0.435 | $0.14 ✅ |
| Output | **$0.28** | $0.87 | $0.28 ✅ |
| Context | 1M | 1M | 1M ✅ |
| Max output | 384K | 384K | 384K ✅ |

**The price table is unchanged.** [27 §6.2](27-architecture-review.md) flagged it as eight days stale
in a market that had retired two aliases in six days; it has not moved. **No cost-model revision is
required.**

**Peak surcharge:** 2× during **09:00–12:00 and 14:00–18:00 Beijing (UTC+8)** = **01:00–04:00 and
06:00–10:00 UTC** — exactly the windows [02 §6.5](02-research-findings.md) records. Still *"subject
to official announcement"*, i.e. **not active**. `pricing.peak_surcharge.enabled: false` remains
correct.

---

## 4. Track B — Hermes: **BLOCKED**

| Blocker | Needed for |
|---|---|
| **`DEEPSEEK_API_KEY` absent from `.env`** | M-1, M-2, M-3, M-4, M-6, M-11, M-12 and V-1 — every token, cost and behaviour measurement |
| **`TELEGRAM_BOT_TOKEN` absent** | M-5, M-9, M-10 — the notification-cost measurements |

`.env` currently contains **only** `APP_SECRET_KEY`.

**Hermes was not installed.** ▶ Ten of the twelve Track B measurements are token-cost measurements
that require a provider key. Installing a large runtime (uv, Node.js, ripgrep, ffmpeg) to answer the
two that do not — M-7 (compose bring-up, now moot under [AD-30](ARCHITECTURE_FREEZE.md)) and M-8
(enumerate bundled skills) — while the other ten stay blocked would be motion rather than progress,
and would put a substantial dependency on the machine before it can be validated.

**Impact: none on the critical path.** Track B gates **P23**, which is eight phases away. P1–P11 and
P12–P22 do not depend on any Track B answer. ▶ Track B should be run as one unit when a key exists —
ideally immediately before P23.

**Nothing about this is a design problem.** It is a credentials problem with a one-line fix.

---

## 5. Architecture impact

### 5.1 Validated — no change

| Assumption | Status |
|---|---|
| [AD-25](ARCHITECTURE_FREEZE.md) egress is a policy, not a mandate | ✅ **Validated and strengthened.** Direct measurably outperforms |
| [AD-26](ARCHITECTURE_FREEZE.md) discovery is metadata-first | ✅ **Validated on the optimistic branch** — U2 confirms bodies are in the feed |
| [AD-27](ARCHITECTURE_FREEZE.md) watermark is the sync primitive; overflow is an error | ✅ **Validated and relaxed** — the window takes 20.6 h to fill |
| [AD-16](ARCHITECTURE_FREEZE.md) semantic layer optional and degrading | ✅ Host supports extension loading; packages absent and that is fine |
| Price table, [06d](06d-ai-budget-and-scale.md) cost model | ✅ Unchanged |
| Legacy contract (459 leads, fingerprint) | ✅ Intact |

### 5.2 Refuted — one deletion required

> **U4: Reddit sends no `ETag` and no `Last-Modified` on RSS.**

[28 §5.1](28-discovery-redesign.md) lists **L1 — conditional GET** as a layer eliminating "100% of the
*payload* for an unchanged feed", and [28 §4.3](28-discovery-redesign.md) claims an idle poll can cost
"**0 bytes** if U4 ✅".

**Both must be corrected.** An idle poll costs one full request — measured at **56,241 bytes** for a
25-entry feed. This is a documentation deletion, not an architecture change: the layer was always
conditional on a measurement, and the measurement came back negative.

**Revised idle-poll cost: 1 request, ~56 KB, ~1 s.** Still one request versus the current design's
390 per run, so [28](28-discovery-redesign.md)'s conclusion is unaffected — only its arithmetic.

`Cache-Control: private, max-age=3600` is a useful consolation: Reddit itself says the feed is good
for an hour, which independently supports a polling interval measured in hours rather than minutes.

### 5.3 Changed from optional to mandatory

**U1 = per-IP** means multireddit combining is no longer an optimisation. Twelve subreddits polled
individually would take **12 minutes** of wall clock at 1 request/minute; combined, they take **one
request**. [28 §3](28-discovery-redesign.md) already designed for this case; it is now the only case.

### 5.4 Assumption A1 corrected — favourably

[06d §2.4](06d-ai-budget-and-scale.md) models "~1,000 posts/day collected, of which ~120 genuinely
new". Measured: **~116 posts/day total** across four subreddits.

◐ The "~120 new" figure is close to right; the "~1,000 collected" figure is ~9× too high for this
subreddit set. Since cost scales with *new* items, **the cost model is unaffected or slightly
improved**. It does mean the request-reduction percentages in [28 §4](28-discovery-redesign.md) are
computed against an inflated baseline and should be restated per-actual-volume in P6.

---

## 6. Required documentation changes

**Only P0-affected documents.** Each is a correction to a measurement, not a redesign.

| Doc | Change | Why |
|---|---|---|
| [28 §5.1](28-discovery-redesign.md) | **Delete layer L1 (conditional GET)** | U4 refuted |
| [28 §4.3](28-discovery-redesign.md) | Idle poll = **1 request / ~56 KB**, not "0 bytes" | U4 refuted |
| [28 §2.1](28-discovery-redesign.md) | Replace the four ❓ rows with measured answers | U1–U6 settled |
| [28 §3](28-discovery-redesign.md) | Mark multireddit combining **mandatory** | U1 = per-IP |
| [28 §10](28-discovery-redesign.md) | Drop `last_etag` / `last_modified` from `discovery_watermarks` | The server never sends them |
| [29 §5.3](29-network-and-proxy-strategy.md) | Record the measurement; confirm **direct** as MVP default | F1 |
| [31 §3](31-execution-plan.md) | Mark U1–U8, V-2…V-5 complete; Track B blocked | — |
| [35 §2.1](35-testing-strategy.md) | **Fix fences 1 and 4 to be AST-based** | §7 below |
| [ARCHITECTURE_FREEZE §11](ARCHITECTURE_FREEZE.md) | Amendment entry for U4 | The only amendment P0 produced |
| [06d §2.4](06d-ai-budget-and-scale.md) | Note measured volume; restate baselines in P6 | A1 |

---

## 7. Defect found in the testing strategy

[35 §2.1](35-testing-strategy.md) specifies fence 1 as `grep -ri "deepseek" src/ --exclude-dir=ai/providers → 0`
and fence 4 as `grep -ri "reddit|subreddit|lead" src/net/ → 0`.

**Both fail against the shipped, correct codebase** — 14 files match each. Every match is a
**docstring or comment**, not code. `src/net/user_agents.py`'s docstring necessarily explains that it
exists because of `old.reddit.com` 403s.

The shipped enforcement, `tests/test_boundaries.py`, is **AST-based** and states the reason in its own
comment: *"Uses `ast` rather than `tokenize`: docstrings are an AST concept."* It passes.

▶ **The implementation is right and the documentation is wrong.** [35 §2.1](35-testing-strategy.md)
must specify `pytest tests/test_boundaries.py` for fences 1 and 4 rather than a naive `grep -ri`. A
literal reading of the current text would force an engineer to delete the comments that explain why
the boundary exists.

---

## 8. Automated test results

| # | Check | Result |
|---|---|---|
| 1 | `ruff check` | ✅ **All checks passed** (15 findings fixed) |
| 2 | `ruff format --check` | ✅ 6 files formatted |
| 3 | `mypy` | ⚠️ **Not installed** — §9 blocker 3 |
| 4–5 | `pytest` | ✅ **265 passed, 0 failed**, 31.7 s |
| 6 | Offline guarantee | ⚠️ Probe scripts are **deliberately online**; the suite itself is offline |
| 7 | Coverage | n/a — probes excluded by design ([35 §3](35-testing-strategy.md)) |
| 8 | Fence 1 (vendor coupling) | ✅ via `tests/test_boundaries.py` (AST) |
| 9 | Fence 2 (`src.ai` in deterministic packages) | ✅ **0 matches** |
| 10 | Fence 3 (`hermes` in `src/`) | ✅ **0 matches** |
| 11 | Fence 4 (Reddit in `src/net/`) | ✅ via `tests/test_boundaries.py` (AST) |
| 12 | Migration round-trip | n/a — P0 adds no migration |
| 13 | **Legacy regression** | ✅ **459 leads, fingerprint 5.0/164.28/42.29, DB mtime unchanged** |
| 14 | Secret scan | ✅ 11 new tests assert credential redaction; `repr`/`str` leak nothing |
| 15 | Error paths | ✅ every transport failure class returns a classified result, never an exception |
| 16 | Edge cases | ✅ malformed/duplicate/empty proxy lines, unparseable feeds |
| 17 | Logging validation | n/a — P0 adds no logging (P2) |
| 18 | Documentation validation | ✅ §6 list produced |

**New tests: 11** (`tests/unit/test_probe_transport.py`) covering credential redaction, the
deliberate credential exposure in `.url`, `DisabledProvider` refusal, `FutureManagedProvider`
construct-but-refuse, and the `exposes_origin_ip` flag.

---

## 9. Blockers

| # | Blocker | Impact | Recommended fix |
|---|---|---|---|
| **B1** | **No `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN`** | Track B (12 measurements) and V-1 deferred | Add both to `.env`. **Does not block P1–P22.** Run Track B immediately before P23 |
| **B2** | **[35 §2.1](35-testing-strategy.md) fences 1 & 4 mis-specified** | A literal reading would delete explanatory comments | Documentation fix — specify `tests/test_boundaries.py` (§7) |
| **B3** | **`mypy` required by [35 §2.1](35-testing-strategy.md) check 3 but absent from [FREEZE §5](ARCHITECTURE_FREEZE.md)** | Gate check 3 cannot run | ▶ Reconcile: add `mypy` to FREEZE §5 as a dev tool. **This is a documentation inconsistency between two frozen documents, not an amendment** — no new technology is being introduced, one was omitted from a list |

**None of B1–B3 blocks P1.** B2 and B3 are documentation reconciliations; B1 is deferred by eight
phases.

---

## 10. Unknowns remaining

| # | Unknown | Deferred to |
|---|---|---|
| Per-subreddit post rates (the §3.3 anomaly) | P6, where `observed_rate_per_hour` is computed per watermark |
| Whether direct holds at sustained volume over days | P6 — the first real scheduled polling |
| Hermes token costs (M-1…M-4, M-6, M-11, M-12) | Track B, before P23 |
| `hermes send` cost and reachability (M-5, M-9, M-10) | Track B |
| DeepSeek vs OpenRouter latency (V-1) | Track B |
| MinHash performance at 2,000 items (A5) | P10 |
| Hard-filter rate on real data (A2) | P11 |

---

## 11. Definition of done

| Criterion | Status |
|---|---|
| Validation completed | ✅ **16 of 16 testable measurements taken**; 12 deferred with a named blocker |
| Measurements collected | ✅ §1–§3, raw JSON persisted |
| Automated tests pass | ✅ 265 passed, 0 failed; lint and format clean |
| Documentation updated | ✅ §6 list; edits applied |
| Manual testing guide generated | ✅ [`testing/P00-testing.md`](testing/P00-testing.md) |
| Architecture assumptions validated | ✅ 6 validated, 1 refuted, 1 relaxed |
| No unresolved blockers | ⚠️ **3 documented, none blocking P1** |
| Live database unmodified | ✅ 459 leads, mtime unchanged |
| No production code written | ✅ `scripts/probe/` and `tests/` only; **nothing under `src/`** |

---

## 12. Recommendation

> **Proceed to P1.**
>
> The architecture survives P0 intact. The one refuted assumption (U4) deletes a documented
> optimisation layer without changing any decision, and the two most consequential unknowns — whether
> RSS carries bodies, and whether direct egress works — both came back **favourable**.
>
> Do **not** purchase proxies. Direct outperforms the datacenter pool on every measured dimension,
> and [AD-25](ARCHITECTURE_FREEZE.md)'s ladder already covers degradation.
>
> Add `DEEPSEEK_API_KEY` and `TELEGRAM_BOT_TOKEN` to `.env` at your convenience; Track B is not needed
> until P23.
