# P4 IMPLEMENTATION REVIEW — Network provider abstraction

**Status:** awaiting approval. **No source file has been modified.**
**Phase:** P4 of the frozen P0–P30 plan ([34 §P4](34-implementation-plan.md)).
**Design docs:** [29](29-network-and-proxy-strategy.md) (primary), [08](08-proxy-service.md) §3/§3.4/§7/§10,
[SPRINT-0-MEASUREMENTS §1](SPRINT-0-MEASUREMENTS.md) (the U8 dependency), [AD-25](32-documentation-consistency.md).
**Predecessor:** [PHASE-03-HANDOVER.md](PHASE-03-HANDOVER.md) · [PHASE-03-COMPLETION-REPORT.md](PHASE-03-COMPLETION-REPORT.md)

Documents read in full for this pass: [34 §1–2, §P0–P6](34-implementation-plan.md),
[29](29-network-and-proxy-strategy.md) (all eight sections), [08](08-proxy-service.md) (all ten),
[ARCHITECTURE_FREEZE](ARCHITECTURE_FREEZE.md), [PHASE-03-HANDOVER](PHASE-03-HANDOVER.md),
[SPRINT-0-MEASUREMENTS §0–§1](SPRINT-0-MEASUREMENTS.md), [35 §2](35-testing-strategy.md),
[32 §4](32-documentation-consistency.md), [12 §14](12-phase-02.md), [03 §8](03-architecture.md),
[07 §1](07-scraping-pipeline.md).
Source read: all of `src/net/`, `src/reddit_client.py`, `src/orchestration/handlers/scrape.py`,
`src/obs/events.py`, `src/dashboard/{app,routes_health}.py`, `tests/test_net.py`,
`tests/test_boundaries.py`, `config.yaml`.

> ⚠️ **`docs/14-phase-04.md` is NOT this phase.** It is "Phase 04 — The Business Knowledge Base"
> from the **legacy eight-phase numbering**, and maps to **P12–P16** in the frozen plan. P4 in the
> [34](34-implementation-plan.md) plan is *Network provider abstraction*. Nothing in `14-phase-04.md`
> is implemented here. The same trap the P3 handover warned about for `phase-03-testing.md`.

---

## 0. Baseline recorded before any edit

Entry condition: *"All 251 `src/net/` tests recorded green before the refactor begins."*

| Measurement | Value | Command |
|---|---|---|
| `tests/test_net.py` | **112 passed, 2 skipped** (114 collected) | `pytest tests/test_net.py` |
| `src/net/` coverage | **85%** (681 statements, 99 missed) | `pytest tests --cov=src/net` |
| Per module | `blocks` 100 · `metrics` 100 · `__init__` 100 · `user_agents` 96 · `cache` 90 · `http_client` 90 · `retry` 84 · `proxy_manager` 74 · `proxy_models` 71 | |
| `alembic heads` | one — `0004_orchestration` | |
| The 2 skips | environment-gated on `PROXY_FILE`; neither is a contract or boundary test | |

**The "251 tests" figure in [34 §P4](34-implementation-plan.md) and [29 §7 N-AC10](29-network-and-proxy-strategy.md)
is not reproducible.** The only test file importing `src.net` is `tests/test_net.py`, which collects
**114** — and roughly a third of those cover `RedditClient` parsers, `LeadRepository` and scoring,
not `src/net/` at all. I will hold the measured figure (**112 passed / 2 skipped**) as the baseline
and report against it. Flagged as a documentation defect, not silently rounded.

Coverage note: `src/net/` sits at **exactly the 85% gate floor** ([35 §2.1](35-testing-strategy.md)
check 7). Every new module must land above 85% or the gate falls below it.

### 0.1 Blocker R7 — found open, now closed

[PHASE-03-HANDOVER §7](PHASE-03-HANDOVER.md) says to check `gh run list` at the start of P4. On first
check, `main` was **11 commits ahead of `origin/main`**: the last green run was a *P2* commit, and no
P3 code had ever executed in GitHub Actions.

`main` was pushed (`8c12367..8a74b53`) and the run confirmed green. **Full record in
[P4-IMPLEMENTATION-CHECKLIST §0](P4-IMPLEMENTATION-CHECKLIST.md).** R7 is closed.

---

## 1. Acceptance criteria

### 1.1 From [34 §P4](34-implementation-plan.md) — the Acceptance row

| # | Criterion | How it will be proven |
|---|---|---|
| **A1** | RSS, health and website classes go **direct** under `prefer_proxy` | `NetworkPolicy.acquire()` unit test per class; asserts a `DirectProvider` lease even with a healthy proxy pool present |
| **A2** | Bulk HTML uses a proxy when healthy and degrades per policy | Fake pool healthy → proxy lease; pool exhausted → ladder step, per `on_pool_exhausted` |
| **A3** | Degradation emits a **visible `run_events` warning** and respects the hourly cap | Handler-level test asserting the row; governor test asserting request 121 in an hour is refused. **See D-C — this is the P3-F7 trap** |
| **A4** | `ProxyLeakError` still fatal | Existing leak test retained; new test that the policy does not swallow it |
| **A5** | A proxy healthy on ipify but soft-blocked on target reports **degraded** | Feed real outcomes into `record_failure(blocked=True)`; assert `acceptance_rate` drops and the health payload says `degraded` while `exit_ip` is set and reachable |
| **A6** | **All `src/net/` tests pass or their change is justified** | Baseline §0; every changed test justified in the completion report. **Two are expected to change — see D-B** |
| **A7** | Vendor swap is config-only | One test constructs every configured provider block from YAML and issues the same request against a fake session |
| **A8** | Retries use a different exit, enforced | `exclude=tried` test: three failures → three distinct labels, asserted against a pool of ≥3 |
| **A9** | Credentials in no log/DB/response/UI | Existing `TestCredentialsNeverLeak` extended to `managed_gateway` (whose credentials live in config/env, not a file) |
| **A10** | `src/net/` has **zero Reddit identifiers** | New AST fence test. **It fails today — see D-B** |

### 1.2 From [29 §7](29-network-and-proxy-strategy.md) — N-AC1…N-AC11

N-AC1–N-AC4 map to A1–A4. N-AC5 → A5. N-AC6 → A7. N-AC8 → A8. N-AC9 → A9. N-AC10 → A6.
N-AC11 → A10. **N-AC7 is not covered by the [34](34-implementation-plan.md) row and is added:**

| # | Criterion | How it will be proven |
|---|---|---|
| **A11** (N-AC7) | A metered provider below its bandwidth floor reports unhealthy and the policy degrades | `ManagedProxyProvider` with `bandwidth_budget_gb` / `bandwidth_floor_gb`; drive `bytes_in` through `release()` past the floor; assert `health()` unhealthy and the ladder steps |

### 1.3 Metrics row

| Metric | Target | Note |
|---|---|---|
| `src/net/` tests | 112 passed / 2 skipped, plus new | Not "251/251" — see §0 |
| Credential tokens across all endpoint responses | 0 | Extends the existing scan to `/api/health/proxies` new fields |
| Provider construction from config | **5 config blocks across 4 classes** | See §6 R-3 |

### 1.4 Universal criteria ([34 §1.2](34-implementation-plan.md))

`ruff check` · `ruff format --check` · `pytest` offline · coverage ≥85% on `src/net/` ·
four fences (**fence 4 is new work — D-B**) · migration round-trip (no migration added; round-trip
still run) · legacy contract (459 baseline leads, `GET /` byte-identical, 13 CSV columns, 17
endpoints) · manual guide generated and executed · documentation edits landed.

---

## 2. Files created

| File | Contents |
|---|---|
| `src/net/providers/__init__.py` | Re-exports; registry mapping config `type` → class |
| `src/net/providers/base.py` | `NetworkProvider` ABC, capability flags, `Lease`, `Outcome`, `ProviderHealth`, `Capacity` |
| `src/net/providers/direct.py` | `DirectProvider` — pinned header profile, hourly governor |
| `src/net/providers/managed_list.py` | `WebshareDatacenterProvider` — wraps the shipped `ProxyManager` |
| `src/net/providers/managed_gateway.py` | `ManagedProxyProvider` — one generic gateway class ([29 §3.1](29-network-and-proxy-strategy.md)) |
| `src/net/providers/null.py` | `NullProvider` — raises on use; asserts a path made no network call |
| `src/net/policy.py` | `NetworkPolicy`, `RequestClass`, ladder degradation, degradation notices, config builder |
| `tests/test_network_policy.py` | Policy, ladder, governor, degradation, bandwidth floor, config construction |
| `tests/test_net_providers.py` | The four provider classes against the fake-session seam |

**No migration.** P4 owns no revision; `alembic heads` stays at one `0004`.

## 3. Files modified

| File | Change |
|---|---|
| `src/net/proxy_manager.py` | `ProxyStats` gains `target_ok`/`target_blocked`/`acceptance_rate`; selection orders by acceptance then LRU; `acquire(exclude=…)`; cooldown scaled by pool pressure. **Public API additive** |
| `src/net/http_client.py` | Accepts a `NetworkPolicy` (or a bare `ProxyManager`, as today); `get(..., request_class="html", session_key=None)`; `bytes_in` reported to `release()`; degradation notices recorded |
| `src/net/blocks.py` | Reddit-specific soft-block signatures moved out — **D-B** |
| `src/net/__init__.py` | Exports the new public names |
| `src/reddit_client.py` | `_default_client` builds a `NetworkPolicy`; owns the Reddit block signatures it passes in. **`RedditClient`'s public API unchanged (AD-2)** |
| `src/dashboard/app.py` | `get_network_policy()` beside the existing `get_proxy_manager()` |
| `src/dashboard/routes_health.py` | `/api/health/proxies` gains `policy`, `on_pool_exhausted`, `ladder`, `providers[]`, `direct_requests_this_hour`. `fail_closed` **retained as a derived alias** — D-D |
| `src/dashboard/templates/health_proxies.html` | Renders the new fields |
| `src/orchestration/handlers/scrape.py` | Drains degradation notices into `run_events` **after** the scrape returns — D-C |
| `config.yaml` | New `network:` block; existing `proxy:` block retained and honoured |
| `tests/test_boundaries.py` | **New fence-4 test** ([35 §2.1](35-testing-strategy.md) check 11) |
| `tests/test_net.py` | Block-classification tests updated for the signature move — D-B |
| `tests/test_handlers_scrape.py` | New assertion: the session is still clean after a degrading scrape |

### Documentation modified (P4 owns these — [34 §P4](34-implementation-plan.md) Docs row + [29 §6](29-network-and-proxy-strategy.md))

| Doc | Edit |
|---|---|
| [08 §3.4](08-proxy-service.md) | New **§3a** — target-acceptance as the third health signal |
| [08 §7](08-proxy-service.md) | `fail_closed: true` → the three-value `on_pool_exhausted`, original reasoning retained |
| [08 §10](08-proxy-service.md) | `WebsiteFetcher` moves off the pool — the customer's own site is direct |
| [08 §3.1](08-proxy-service.md) | Record LRU as the shipped strategy; `exclude=tried` now explicit |
| [07 §1](07-scraping-pipeline.md) | *"All traffic via rotating proxy"* → *"via the network policy; egress is chosen per request class"* |
| [03 §6](03-architecture.md) | **Land AD-25** — it exists in [32 §4](32-documentation-consistency.md) but has never been written into the `AD-NN` register [32](32-documentation-consistency.md) §4 says is the single home. See D-E |
| [03 §8](03-architecture.md) | Technology table gains the **network provider** row |
| [12 §14](12-phase-02.md) | Move `exclude=tried` from "deliberately not built" to delivered, naming P4 |
| `CHANGELOG.md` | P4 entry |
| `docs/testing/P04-testing.md`, `PHASE-04-COMPLETION-REPORT.md`, `PHASE-04-HANDOVER.md`, `docs/progress/P04-COMPLETE.md` | The P2/P3 standard |

---

## 4. Interfaces that change

| Interface | Today | After P4 | Compatibility |
|---|---|---|---|
| `ProxiedHTTPClient.__init__` | `(proxy_manager=None, *, cache, metrics, retry_policy, timeout, max_bytes)` | `(egress=None, …)` accepting a `NetworkPolicy` **or** a `ProxyManager` | Positional shape preserved; existing tests construct with a `ProxyManager` and keep working |
| `ProxiedHTTPClient.get` | `(url, *, expect_selector, cache_ttl, referer, allow_cache)` | `+ request_class: str = "html"`, `+ session_key: str \| None = None` | **Additive.** The default is what makes A6 achievable |
| `ProxyManager.acquire` | `(*, wait, timeout)` | `+ exclude: set[str] \| None`, `+ session_key: str \| None` | Additive |
| `ProxyStats` | 11 fields | `+ target_ok`, `+ target_blocked`, `+ acceptance_rate` | Additive |
| `ProxyManager.record_failure` | `(endpoint, error, *, blocked=False)` | unchanged signature; `blocked=True` now also decrements acceptance | Behaviour extension |
| `GET /api/health/proxies` | 9 keys incl. `fail_closed` | + `policy`, `on_pool_exhausted`, `ladder`, `providers`, `direct_requests_this_hour`; `fail_closed` derived | **Additive only.** Not one of the 17 legacy endpoints (verified against `LEGACY_ROUTES` in `tests/test_boundaries.py`) |
| `blocks.classify` | `(status_code, html, *, expect_selector_hits)` | `+ signatures: BlockSignatures \| None` | D-B |
| `build_from_settings` | returns `ProxyManager` | retained; **new** `build_policy_from_settings` / `build_policy_from_config` | Additive |
| `RedditClient` public API | 6 frozen methods | **unchanged** (AD-2) | — |
| `build_scraper(config)` | one argument | **unchanged** (P3 G3/T2) | — |

---

## 5. Dependencies on P3

| P3 guarantee | P4's obligation |
|---|---|
| **G1** — `RunService` takes a session; the caller commits | P4 adds no service that opens its own session |
| **G3** — `build_scraper()` is the only line in the orchestrated path that opens a network client | The `NetworkPolicy` is constructed there and nowhere else in `src/orchestration/`. Name and one-argument shape unchanged (**T2**) |
| **G4** — no migration; cancel flag lives in `stats_json` | P4 owns no migration |
| **G5** — `POST /api/scrape` may only gain fields | Untouched |
| **T0 / F7** — **never hold the SQLite write lock across I/O** | The single highest risk in this phase. See **D-C** |
| **T1** — a scrape collects less than pre-P3, deliberately | Not "fixed" here |
| **T4** — the handler's transaction is not the scraper's | Degradation notices drain into the handler's post-scrape transaction; a rollback loses the notice, not the leads |
| **T5** — `RedditClient._get` swallows transport failures | **Explicitly NOT changed in P4.** See §10 |
| **T6** — `run_events.message` renders into HTML | Degradation messages carry a provider **label** (`host:port`), never a credential; `emit_event` redacts |
| **F4 / F7** — a fake that is easier than reality tests the fake | Every new double is specified in §12 to reproduce the property under test |

New network dependencies: **none.** No package is added; `requests` already covers the gateway shape.

---

## 6. Documentation conflicts

| # | Conflict | Proposed resolution |
|---|---|---|
| **R-1** | **The shipped default.** [29 §2.2/§5.4](29-network-and-proxy-strategy.md) ships `policy: prefer_proxy` with `ladder: [resi, dc, direct]`. [SPRINT-0 §1.6](SPRINT-0-MEASUREMENTS.md) measured direct at 100%/0% against Webshare at 71.4%/28.6% and states the ladder P4 implements is **`direct → webshare`**. The three-value enum has no way to say "direct first, proxy as fallback" | **D-A — needs your decision** |
| **R-2** | **The ABC does not match shipped code.** [29 §3.1](29-network-and-proxy-strategy.md) and [08 §3](08-proxy-service.md) specify `acquire(session_key=, exclude=) → Lease` + `release(lease, outcome=…)`. The shipped `ProxyManager` has `acquire(wait=, timeout=)` + `record_success` / `record_failure`. [34 §P4](34-implementation-plan.md) task 2 says "refactor behind the interface — **behaviour unchanged**" | **The ABC moves to the documented shape; `ProxyManager` keeps its own.** `WebshareDatacenterProvider` is the adapter: it implements `acquire`/`release`/`health`/`capacity` and translates to the shipped calls. `ProxyManager`'s API stays additive-only, so its 30-odd existing tests are untouched. This is the only reading under which "behaviour unchanged" and "the ABC" can both hold |
| **R-3** | **Provider count.** Deliverables name 4 classes (`direct`, `managed_list`, `managed_gateway`, `null`); Metrics says "all 5 types"; [29 §3.1](29-network-and-proxy-strategy.md) diagrams 5 with `WebshareResidentialProvider` separate; §3.1's own table then says `ManagedProxyProvider` covers every vendor "**without a per-vendor class**" | **4 classes, 5 config blocks.** Residential is `managed_gateway` with a different gateway/credentials. A5's construction test exercises 5 blocks. No `WebshareResidentialProvider` class is written — writing one would contradict the economy the design names as its main win. **The four config `type` strings are `direct`, `managed_list`, `managed_gateway`, `null_provider`** — the module is `null.py`, but the YAML literal is `null_provider` because bare `null` is a YAML keyword that parses as `None` |
| **R-4** | **`ProxyRuntime` does not exist.** [29 §4.1](29-network-and-proxy-strategy.md) says "`ProxyRuntime` gains `target_ok`…"; the shipped class is `ProxyStats` | Fields land on `ProxyStats`. Naming difference only |
| **R-5** | **"Keep per-subreddit pinning."** [29 §4.2](29-network-and-proxy-strategy.md) says keep it; [12 §14](12-phase-02.md) records sticky sessions as **deliberately not built**. There is nothing to keep | `session_key` is implemented in the ABC and the providers (`managed_gateway` genuinely needs it for `-session-{key}`), and plumbed through `ProxiedHTTPClient.get`. **No caller passes one in P4** — pagination pinning is P5/P6's. Directly unit-tested, so it is config-driven behaviour, not dead code. **D-F if you want it wired to the scraper now** |
| **R-6** | **`ProxiedHTTPClient`'s "unchanged public contract."** [29 §3.2](29-network-and-proxy-strategy.md) writes it as `get(url, session_key=, timeout=, use_cache=, max_attempts=)`. The shipped signature is `get(url, *, expect_selector=, cache_ttl=, referer=, allow_cache=)` — different in four of five parameters | The **shipped** signature is authoritative; P4 extends it additively (§4). Doc 29 §3.2's snippet is aspirational, written before P2 shipped |
| **R-7** | **ADR-02.** [29 §6](29-network-and-proxy-strategy.md) asks for a "New ADR: ADR-02"; [32 §4](32-documentation-consistency.md) explicitly **rejects** a separate ADR directory and writes the same decision as **AD-25** | No ADR-02. AD-25 is the decision; P4 lands it in [03 §6](03-architecture.md), which [32 §4](32-documentation-consistency.md) names as its single home. **D-E** |
| **R-8** | **`fail_closed` vs `on_pool_exhausted`.** [08 §7](08-proxy-service.md) is a boolean; [29 §2.2](29-network-and-proxy-strategy.md) replaces it with a three-value key. `fail_closed` is live in `ProxyManager`, `config.yaml`, `_default_client`, and the `/api/health/proxies` JSON | Both retained. `on_pool_exhausted` is authoritative; `fail_closed` becomes a derived alias (`== "fail_run"`) on the payload and a still-honoured legacy config key. **D-D** |
| **R-9** | **The "251 tests" figure** | Replaced with the measured baseline (§0), recorded in the completion report |
| **R-10** | **Fence 4 is specified but not implemented, and would fail.** [35 §2.1](35-testing-strategy.md) lists it as non-negotiable check 11; [12 §14](12-phase-02.md) ticks it as done. There is **no such test** in `tests/test_boundaries.py`, and an AST scan of `src/net/` finds seven Reddit identifiers in executable code in `blocks.py` | **D-B — needs your decision** |
| **R-11** | **`PoolCircuitBreaker`.** [08 §5](08-proxy-service.md) specifies a rolling-window breaker with `min_samples`/`failure_threshold`/`open_duration_s`; the shipped `circuit_open` is simply "nothing usable" | Out of scope. [29 §4.4](29-network-and-proxy-strategy.md) says the breaker is "**unchanged** — plus acceptance-rate as a second trigger", which is what P4 implements. The [08 §5](08-proxy-service.md) rewrite is not in P4's task list |

---

## 7. Assumptions

| # | Assumption | If wrong |
|---|---|---|
| **AS-1** | No residential proxy has been purchased; `managed_gateway` ships with no live credentials | Only the manual test plan changes — Part B gains a live gateway run |
| **AS-2** | `network.direct.max_requests_per_hour: 120` is a **process-wide**, in-memory governor (see P-1/P-2 in §7.1 — per-job construction would enforce it at 12×). There is no table for it and P4 owns no migration | A restart resets the counter. Documented, not hidden. A persistent counter needs a migration and is out of scope |
| **AS-3** | Bandwidth accounting is in-process, from `bytes_in` measured on the response body. No vendor billing API is called | `capacity()` reports what this process spent, not the account balance. Stated in the health payload as `bytes_this_process` |
| **AS-4** | `request_class` vocabulary is `rss` · `health` · `website` · `html` · `comments` · `validation` ([29 §2.1](29-network-and-proxy-strategy.md)). All six are generic — none is a Reddit identifier | — |
| **AS-5** | `DirectProvider` uses `DEFAULT_PROFILE` pinned for the process, matching what `_direct()` does today and what [SPRINT-0 §1.5](SPRINT-0-MEASUREMENTS.md) measured at 100% | A hand-built header set reintroduces a total outage that looks like an IP ban ([SPRINT-0 §1.5](SPRINT-0-MEASUREMENTS.md)). A test asserts `DirectProvider` sends a whole profile, never a partial one |
| **AS-6** | The legacy `proxy:` config block keeps working unchanged, so a machine that never gains a `network:` block behaves as it does today | — |
| **AS-7** | Degradation is reported once per run per ladder step, not once per request | A run that degrades 400 times writes 1 event, not 400 |

### 7.1 Four mechanism-level design points — recommendations, not questions

Each is a place where the design text, traced against shipped code, produces a mechanism that does
not work. Recorded here with the resolution I intend to implement.

**P-1 — Pressure-scaled cooldown must have a floor, or pool exhaustion becomes unreachable.**
[29 §4.3](29-network-and-proxy-strategy.md) gives `effective_cooldown = base × (healthy_count / pool_size)`
and only works the 2/10 case. Traced against `proxy_manager.py`: `_usable()` returns a blacklisted
proxy to rotation once `now - blacklisted_at >= cooldown`; `acquire()` raises `ProxyExhaustedError`
**only** when `_usable()` is empty; `circuit_open` is `not _usable(...)`. At 0/10 healthy the formula
yields a cooldown of **zero**, every blacklisted proxy is instantly usable, and exhaustion can never
latch — which would make `on_pool_exhausted`, the ladder, A2 and RK-6 unreachable, and break
`TestFailClosed`. **Resolution:** `effective_cooldown = max(base × pressure, cooldown_floor)` with a
non-zero floor, so exhaustion still latches at 0 healthy. Mutation test: set the floor to 0 → the
exhaustion and fail-closed tests must fail.

**P-2 — The hourly governor and the acceptance window must be process-wide, not per job.**
`handle_scrape_subreddit` calls `build_scraper(load_config())` **once per job**, so each subreddit
gets a fresh `RedditClient` → fresh `ProxyManager` → (after P4) a fresh `NetworkPolicy`. Twelve
subreddits would mean twelve independent counters, and `max_requests_per_hour: 120` — a **frozen
budget** ([ARCHITECTURE_FREEZE §6](ARCHITECTURE_FREEZE.md)) — would be enforced at 12×. The
blacklist and acceptance windows would reset per job too. **Resolution:** the policy is resolved
process-wide and handed to the client at the `build_scraper` seam, which keeps G3 and T2's
one-argument shape intact. Side effect worth stating: `/api/health/proxies` and the scraper then
observe **the same** pool — today `dashboard/app.py`'s `_proxy_manager` singleton and the scraper's
per-job manager are different objects, so the health page has never reflected scraper traffic.
AS-2 is amended accordingly.

**P-3 — `acceptance_rate` must be neutral at zero samples.** Shipped selection is pure LRU
(`min(ready, key=last_used_at)`). Ordering by acceptance first passes today's tests only because a
fresh pool has equal rates, and diverges under real traffic — F7's shape exactly. If
`acceptance_rate = ok/(ok+blocked)` is `0.0` at n=0, the first success pins the whole pool to one
exit and the LRU-spread guarantee dies. **Resolution:** acceptance is neutral (treated as equal)
below a minimum sample count; below that, ordering is unchanged LRU. An explicit test asserts a warm
pool with mixed rates still spreads across exits.

**P-4 — Two egress paths never reach the policy.** `ProxyManager.health_check` and
`ProxyManager.direct_ip` call `requests.get` directly. R18's enforcement is "policy test", and a
policy test cannot cover a call that bypasses the policy. **Resolution:** they stay as they are —
`direct_ip` *must* be unproxied (it is the reference value the leak check compares against, and
routing it through the pool would compare the pool with itself), and `health_check` is a synthetic
probe against `api.ipify.org`, not target traffic. Both are recorded here as **documented
out-of-band probes**, and A1's claim is scoped to policy-routed traffic rather than "every socket in
the process".

**Correction to AS-3:** `http_client` reads the body with `decode_content=True`, so `bytes_in` is
the **decompressed** length. It over-estimates billed bandwidth (vendors bill the wire) and is
therefore a conservative floor for the bandwidth guard, not a billing figure. Reported as
`bytes_this_process_decompressed`.

---

## 8. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **RK-1** | **Emitting the degradation warning re-creates P3's F7 lock bug.** `emit_event` adds to the caller's session; a dirty session inside `scraper.run()` takes SQLite's write lock across a multi-minute network call | **Critical** | **D-C.** Plus: `tests/test_handlers_scrape.py` already asserts the session is clean when the scrape starts; a new assertion covers *after a degrading scrape*, and the double must actually query (F7's lesson) |
| **RK-2** | The refactor changes proxy behaviour silently | High | `WebshareDatacenterProvider` is a thin adapter; `ProxyManager` internals are extended additively only; the 30-odd existing pool tests run unchanged |
| **RK-3** | Moving Reddit block signatures out of `src/net/` breaks soft-block detection — the failure that "poisons the cache and the lead table" | High | Signatures are injected by `RedditClient`, not deleted. Tests move with them; a mutation test (drop the injection) must fail the detection tests |
| **RK-4** | Coverage falls below the 85% floor because five new modules land at once | Medium | Each stage lands with its tests; coverage measured per stage, not at the end |
| **RK-5** | The direct governor throttles a legitimate run to a halt | Medium | 120/h against a measured steady state of ≤80/day ([ARCHITECTURE_FREEZE §6](ARCHITECTURE_FREEZE.md)); exceeding it is itself a `run_events` warning, not a silent stall |
| **RK-6** | `ProxyLeakError` is swallowed by the ladder — degrading past a leak instead of failing on it | **Critical** | The leak check is fatal *before* the ladder is consulted; an explicit test asserts the policy re-raises rather than degrading |
| **RK-7** | A credential reaches the health payload via the new `providers[]` array — `managed_gateway` credentials come from config/env, a path the file-based redaction never covered | High | Provider `__repr__`/`to_dict` return label only; `TestCredentialsNeverLeak` extended with a gateway fixture carrying a known password, grepped from every endpoint response and the full log capture |
| **RK-8** | Fence 4, once written, becomes a standing obstacle for P5/P6 (RSS work lives near the transport) | Low | The fence tests `src/net/` only; `src/discovery/` is unaffected |
| **RK-9** | Pressure-scaled cooldown makes `ProxyExhaustedError` unreachable, silently disabling the ladder P4 exists to build | **Critical** | §7.1 **P-1** — cooldown floor, plus a mutation test that removing it breaks the exhaustion and fail-closed tests |
| **RK-10** | A process-wide policy changes what `/api/health/proxies` reports, because the health page and the scraper have never shared a pool | Medium | §7.1 **P-2** — stated as an intended improvement in the completion report and the manual guide, with a before/after note so the operator is not surprised by non-zero request counts appearing on the page |
| **RK-11** | Acceptance-ordered selection collapses the pool onto one exit | High | §7.1 **P-3** — neutral below a minimum sample count; explicit spread test on a warm mixed-rate pool |

---

## 9. Ambiguities — six decisions I need from you

### D-A — The shipped default policy and ladder ⟵ **blocking**

[29 §2.2](29-network-and-proxy-strategy.md) gives three policy values and ships `prefer_proxy` with
`ladder: [resi, dc, direct]`. [SPRINT-0 §1.6](SPRINT-0-MEASUREMENTS.md) — P4's own stated dependency —
measured direct as better on **every** dimension and states the ladder P4 implements is
`direct → webshare`. The enum cannot express "direct first, proxy as fallback".

| Option | Config shipped | Cost |
|---|---|---|
| **A1 (recommended)** | Keep the three-value enum; make **`ladder` the sole ordering authority**. Ship `policy: prefer_proxy`, `ladder: [direct, dc]` | The name `prefer_proxy` reads oddly against a direct-first ladder. Zero doc conflict, zero enum change |
| **A2** | Add a fourth value `prefer_direct` and ship it | Names things honestly; adds an enum value [29 §2.2](29-network-and-proxy-strategy.md) does not list → a §11.1 documentation reconciliation |
| **A3** | Ship `policy: direct_only` | Matches "buy nothing" most literally, but the Webshare pool is then configured and never used — there is no fallback at all when the direct governor is spent |

Either way `network.direct.classes: [rss, health, website]` is unconditional (R18), and the
**Rollback** row stays exactly true: `policy: proxy_only` + `on_pool_exhausted: fail_run` reproduces
pre-P4 behaviour.

### D-B — Fence 4 fails today ⟵ **blocking**

[35 §2.1](35-testing-strategy.md) check 11 is *non-negotiable*; [12 §14](12-phase-02.md) ticks it as
delivered; **the test does not exist**. Writing it as specified (AST-based, executable tokens only)
finds seven hits in `src/net/blocks.py`:

```
_NEW_REDDIT_MARKERS, "shreddit-app", "shreddit-async-loader", "welcome to reddit",
"Reddit rate-limit interstitial", "served the new Reddit app instead of old HTML"
```

| Option | What happens | Cost |
|---|---|---|
| **B1 (recommended)** | Root-cause fix: `blocks.py` keeps the **generic** challenge markers (Cloudflare, "checking your browser", bad-title heuristic). The Reddit-specific set moves to `src/reddit_client.py` and is injected via `ProxiedHTTPClient(block_signatures=…)`. Fence 4 then passes honestly | ~2 tests in `TestBlockClassification` change to inject the Reddit set — justified under A6. Touches shipped, working block detection (RK-3) |
| **B2** | Ship the fence with `blocks.py` on an allowlist | The fence stops meaning what it says on the one file most likely to break it |
| **B3** | Defer fence 4 to a later phase | P4's own Acceptance row states *"`src/net/` has zero Reddit identifiers"*. Deferring means P4 cannot claim its acceptance |

### D-C — Where the degradation `run_events` warning is written ⟵ **blocking**

Degradation happens inside `src/net/`, which has no session and no `run_id`. The only orchestrated
caller is `handlers/scrape.py` — the handler P3's F7 proved must keep a **clean session across the
network call**.

| Option | Mechanism | Assessment |
|---|---|---|
| **C1 (recommended)** | `NetworkPolicy` accumulates degradation notices in memory; the handler drains them into `run_events` **after** `scraper.run()` returns, in the transaction it already commits | Provably keeps the clean-session assertion green. Adds no write path during the scrape. Cost: the warning appears on `/runs/<id>` when the subreddit finishes, not the instant it degrades |
| **C2** | An injected callback that opens its **own** short-lived session and commits immediately | Real-time visibility; a short transaction does not hold the lock across I/O. Cost: a second write path during the scrape, and a new session-factory dependency in the handler |

Under either option the test double **must actually take the write lock** — an easy fake is what let
F7 through 583 green tests.

### D-D — `fail_closed` on `/api/health/proxies`

`fail_closed` is currently in the JSON payload and rendered on `/health/proxies`. Recommended: keep
it as a **derived alias** of `on_pool_exhausted == "fail_run"` and add the new fields alongside, so
the change is purely additive. Alternative: remove it and update the template and tests. The endpoint
is **not** one of the 17 legacy endpoints, so either is permitted.

### D-E — Land AD-25 in [03 §6](03-architecture.md)

AD-25 is listed as ✅ Frozen in [ARCHITECTURE_FREEZE §3](ARCHITECTURE_FREEZE.md) and written out in
[32 §4](32-documentation-consistency.md), but has never been added to the `AD-NN` register in
[03 §6](03-architecture.md) — which [32 §4](32-documentation-consistency.md) names as the single home
for decisions. Recommended: P4 lands AD-25's text there (a transcription, not a new decision) and
adds the [03 §8](03-architecture.md) technology row. Confirm you want P4 to touch [03](03-architecture.md).

### D-F — Does `session_key` get wired to the scraper in P4?

Recommended **no**: implement it in the ABC and providers (`managed_gateway` needs it), plumb it
through `ProxiedHTTPClient.get`, but let P5/P6 be the first caller. Wiring it to
`RedditClient._paginate` now would change live pagination behaviour inside a phase whose acceptance
is "behaviour unchanged", and [12 §14](12-phase-02.md) records sticky sessions as deliberately not built.

---

## 10. Belongs to later phases — NOT implemented in P4

| Item | Owner | Why not here |
|---|---|---|
| **`RedditClient._get` raising instead of returning `None`** (T5) | P5/P6 | The handover says "P4 is where that changes", but [34 §P4](34-implementation-plan.md) authorises nothing of the sort and AD-2 freezes the client's API. **Recorded as a conflict; deferred.** The `except BlockedError: raise RetryableError` mapping in `handlers/scrape.py` stays absent, as it cannot execute |
| `WebsiteFetcher` and the `website` request class having a consumer | P13 | The class ships and is directly tested from config; its first caller is P13 |
| `RedditClient.get_feed()` / Atom parsing / `if_none_match` | P5 | [34 §P5](34-implementation-plan.md) |
| `discovery_watermarks`, conditional GET, adaptive polling | P6 | |
| Residential proxy purchase | Deferred ([ARCHITECTURE_FREEZE §9](ARCHITECTURE_FREEZE.md)) | Trigger is a measured block rate; P0 measured the opposite |
| `PoolCircuitBreaker` rolling-window rewrite ([08 §5](08-proxy-service.md)) | — | [29 §4.4](29-network-and-proxy-strategy.md) says unchanged; R-11 |
| `COOLDOWN` probation state, per-cause blacklist durations, half-open probe | — | [12 §14](12-phase-02.md) deliberately-not-built; not in P4's task list |
| Sticky-session TTL and re-pin-on-failure | P5/P6 | D-F |
| Keyword / user scraping through the queue (N1) | P5/P17 | P3 T1 — explicitly not "fixed" here |
| Any migration, any schema change | — | P4 owns none |
| `mypy` baseline (B3/O2) | — | Not installed; the gate cannot be claimed in full. Carried, not resolved |

---

## 11. Proposed implementation order

Each stage ends green: `pytest`, `ruff check`, `ruff format --check`. No broken intermediate commit.

| # | Stage | Contents | Gate |
|---:|---|---|---|
| **0** | Baseline | §0 recorded; `gh run list` checked (R7) | Committed as part of this document |
| **1** | The ABC | `providers/base.py` + `null.py`: flags, `Lease`, `Outcome`, `ProviderHealth`, `Capacity`. No consumer yet | New tests only; nothing existing can regress |
| **2** | Pool upgrades | `ProxyStats` acceptance fields, `exclude=`, acceptance-ordered selection (**P-3**), pressure-scaled cooldown with a floor (**P-1**) — all additive on `ProxyManager` | **All existing pool tests unchanged and green**, incl. `TestFailClosed` and the LRU-spread test |
| **3** | `managed_list` | `WebshareDatacenterProvider` adapts `ProxyManager` to the ABC. Behaviour unchanged | Adapter tests + existing pool tests |
| **4** | `direct` | `DirectProvider`: pinned profile, hourly governor | AS-5 profile-atomicity test; governor boundary test |
| **5** | `managed_gateway` | Generic gateway, session suffix, metering, bandwidth floor | A11; RK-7 credential scan |
| **6** | `policy.py` | Class→provider, ladder, degradation notices, leak passthrough, config builder | A1, A2, A7, A11, RK-6 |
| **7** | Transport wiring | `http_client` takes the policy; `request_class`/`session_key`; `bytes_in`; both construction sites; **process-wide resolution at the `build_scraper` seam (P-2)** | **The whole existing `test_net.py` re-run against the baseline**; a test that two `build_scraper` calls share one governor |
| **8** | Config + surfaces | `config.yaml` `network:` block; `/api/health/proxies` additive fields; template | Legacy contract; credential scan |
| **9** | The `run_events` warning | Handler drains notices (D-C) | A3 + the clean-session assertion (RK-1) |
| **10** | Fence 4 | D-B: signature move + the boundary test | Fence 4 green; block detection mutation-tested |
| **11** | Docs + reports | §3 documentation table; `P04-testing.md`, completion report, handover, `P04-COMPLETE.md`, `CHANGELOG.md` | Doc-link check; manual guide executed |

Stages 1–6 touch no existing consumer, so the suite cannot regress before stage 7. Stage 7 is the
single riskiest commit and is deliberately isolated.

---

## 12. Testing strategy

**Offline, always.** No stage introduces a live call. The `session_for` fake-session seam
([29 §3.2](29-network-and-proxy-strategy.md)) is retained and extended: every provider exposes a
session the test replaces, so `_FakeSession` in `tests/test_net.py` keeps working.

### 12.1 Doubles that reproduce the property under test (P3's F4/F7 lesson)

| Double | Must reproduce | Why the easy version is useless |
|---|---|---|
| Degrading scraper (RK-1) | **Queries the DB** so autoflush takes the write lock, and degrades mid-scrape | An in-memory fake never flushes — exactly how F7 passed 583 tests and failed in production |
| Exhausted pool | Real `ProxyExhaustedError` from the real `ProxyManager` with all endpoints blacklisted | A stubbed `acquire` skips `_usable()`, where the cooldown logic lives |
| Soft-blocked proxy (A5) | 200 + a real interstitial fixture through the fake session, so `blocks.classify` runs | Calling `record_failure(blocked=True)` directly proves the counter, not the detection |
| Metered gateway (A11) | Real `bytes_in` from a body of known length via `release()` | Setting `bytes_used` directly skips the accounting path |
| Leak (RK-6) | Exit IP equal to the local IP through `health_check_all` | — |

### 12.2 New test coverage

`tests/test_network_policy.py` — class routing (6 classes × 3 policies), ladder degradation,
`on_pool_exhausted` × 3, hourly governor boundary, degradation notice accumulation and dedup,
bandwidth floor, leak passthrough, config construction of all 5 blocks with no code change (A7).

`tests/test_net_providers.py` — each of the 4 classes: capability flags, `acquire`/`release`/
`health`/`capacity`, `NullProvider` raising, `exclude=tried` producing distinct exits (A8),
`DirectProvider` header atomicity (AS-5), gateway session-suffix rendering, credential redaction (A9/RK-7).

`tests/test_boundaries.py` — fence 4 (A10).

`tests/test_handlers_scrape.py` — the degradation event lands (A3) **and** the session is clean
throughout (RK-1).

### 12.3 Conditional gates ([35 §2.2](35-testing-strategy.md))

**Retry** applies to P4: backoff growth, max attempts, non-retryable classes — existing tests
retained, plus `exclude=tried`. **API contract**: `/api/health/proxies` replayed for additive-only
change. **Secret scan**: extended to gateway credentials.

### 12.4 Mutation discipline ([35 §2.4](35-testing-strategy.md))

One deliberate break per acceptance criterion. At minimum: remove `exclude=tried` (A8 must fail);
make `website` proxy-eligible (A1 must fail); drop the block-signature injection (RK-3 must fail);
remove the pre-scrape `session.commit()` (RK-1 must fail); return `healthy` regardless of acceptance
(A5 must fail).

### 12.5 Full gate before sign-off

`pytest` · `pytest -W error::DeprecationWarning` · `ruff check .` · `ruff format --check .` ·
`python scripts/check_schema.py` · `alembic heads` (one) · migration round-trip on a live-DB copy ·
coverage ≥85% on `src/net/` · four fences · legacy contract · GitHub Actions green.

---

## 13. Rollback strategy

| Level | Action | Result |
|---|---|---|
| **Config (stated in [34 §P4](34-implementation-plan.md))** | `network.policy: proxy_only` + `network.on_pool_exhausted: fail_run` | Exact pre-P4 behaviour: every non-`direct.classes` request goes through the pool, and an exhausted pool stops the job |
| **Config, stronger** | Delete the `network:` block entirely | `build_policy_from_config` falls back to the legacy `proxy:` block and constructs a single `managed_list` provider — byte-for-byte today's construction (AS-6) |
| **Code** | `git revert` the P4 range | No migration, no schema change, no data written by this phase — the revert is complete and leaves nothing behind |
| **Partial** | Stages 1–6 are inert until stage 7 | Reverting stage 7 alone restores the shipped transport while keeping the new modules unused |

**Nothing in P4 is one-way.** No migration, no row written, no external purchase, no dependency added.

---

## 14. Approval

Implementation does not begin until **D-A, D-B and D-C** are answered (D-D, D-E, D-F have
recommendations that I will follow unless you say otherwise).

- [ ] D-A — default policy and ladder (**A1** recommended)
- [ ] D-B — fence 4 (**B1** recommended)
- [ ] D-C — degradation event plumbing (**C1** recommended)
- [ ] D-D — `fail_closed` retained as a derived alias (recommended)
- [ ] D-E — P4 may edit [03 §6](03-architecture.md) to land AD-25 (recommended)
- [ ] D-F — `session_key` implemented but not wired to the scraper (recommended)
- [ ] Approval to begin stage 1
