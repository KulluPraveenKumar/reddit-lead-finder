# PHASE-04 COMPLETION REPORT — Network provider abstraction

**Phase:** P4 of the frozen P0–P30 plan ([34 §P4](34-implementation-plan.md))
**Delivered:** 2026-08-08 · **Architecture status:** FROZEN, **no amendment, no reconciliation**
**Companions:** [PHASE-04-HANDOVER.md](PHASE-04-HANDOVER.md) · [testing/P04-testing.md](testing/P04-testing.md) ·
[P4-IMPLEMENTATION-REVIEW.md](P4-IMPLEMENTATION-REVIEW.md) · [P4-DECISION-ANALYSIS.md](P4-DECISION-ANALYSIS.md)

> ⚠️ **Not `docs/14-phase-04.md`.** That is "Phase 04 — The Business Knowledge Base" from the legacy
> eight-phase numbering and maps to **P12–P16**. This report is about **P4** in the frozen plan.

---

## 1. Objective

> *Egress is a policy chosen per request class, with a degradation ladder — not a mandate.*

Met. Before this phase every request went through the proxy pool and a dead pool stopped the run.
Now the request's **class** chooses the path, a configured **ladder** decides the order, and an
exhausted ladder degrades — visibly, and under a hard cap on the operator's own address.

**The measurement this phase was waiting for.** P4's stated dependency was P0's U8 result:
**direct 100% success / 0% blocks / 1,342 ms; Webshare datacenter 71.4% / 28.6% / 2,081 ms**,
reproduced twice, with direct also winning on CPU (2.55×) and posts extracted
([SPRINT-0 §1.2](SPRINT-0-MEASUREMENTS.md)). The shipped ladder is therefore `[direct, dc]`. Nothing
was purchased, exactly as [29 §5.3](29-network-and-proxy-strategy.md) concluded.

---

## 2. Verification

| Check | Result |
|---|---|
| `pytest` | **695 passed, 2 skipped** · 312 s (baseline before P4: 583 passed, 2 skipped) |
| `pytest -W error::DeprecationWarning` | **695 passed, 2 skipped** |
| `ruff check .` | All checks passed! |
| `ruff format --check .` | 101 files already formatted |
| `scripts/check_schema.py` | **OK — all 25 checks passed** (the same 25; P4 adds no table) |
| `alembic heads` | `0004_orchestration (head)` — **one head, no migration added** |
| Coverage, `src/net/` | **91%** (was 85% — the gate floor) |
| New tests | **+112** (`test_network_policy.py` 47, `test_net_providers.py` 38, plus 27 across three existing files) |
| The two skips | Both in `tests/test_net.py`, environment-gated on `PROXY_FILE`. Unchanged from P3 |
| Offline | No new live call. Every provider is exercised against unreachable endpoints or a fake session |
| Legacy contract | 459 baseline leads intact · `GET /` byte-identical · 13 CSV columns · 17 endpoints identical |
| Mutation testing | **7 mutations, 7 detected** — after two were found undetected and fixed (§6) |

### 2.1 Per-module coverage, `src/net/`

| Module | Before | After |
|---|---:|---:|
| `blocks.py` | 100% | 100% |
| `http_client.py` | 90% | **95%** |
| `proxy_manager.py` | 74% | **80%** |
| `policy.py` | — | **93%** |
| `providers/base.py` | — | **100%** |
| `providers/direct.py` | — | **96%** |
| `providers/managed_gateway.py` | — | **95%** |
| `providers/managed_list.py` | — | **97%** |
| `providers/registry.py` | — | **91%** |
| `egress.py` | — | **100%** |
| **Total** | **85%** | **91%** |

---

## 3. The three decisions taken before implementation

Analysed in [P4-DECISION-ANALYSIS.md](P4-DECISION-ANALYSIS.md) and approved by the operator before
any code was written.

### 3.1 D-A → A1 — the ladder is the ordering authority

`policy` decides which providers are **eligible** (`direct_only` | `prefer_proxy` | `proxy_only`);
`ladder` decides the **order**. Two axes, because the measurement that sets the order is independent
of the rule that sets eligibility — so re-measuring is one config line, not a code change. Ships as
`policy: prefer_proxy`, `ladder: [direct, dc]`.

The alternative (a fourth enum value, `prefer_direct`) would have read more honestly but required a
[§11.1](ARCHITECTURE_FREEZE.md) reconciliation against [29 §2.2](29-network-and-proxy-strategy.md),
which enumerates exactly three. **No frozen document changed.**

### 3.2 D-B → B1 — block signatures are injected by the caller

`src/net/blocks.py` keeps the target-agnostic challenge markers (Cloudflare, "checking your
browser", bad-title heuristics). The Reddit-specific set moved to `src/reddit_client.py` as
`REDDIT_SIGNATURES` and is passed in at construction.

### 3.3 D-C → C1 — degradation notices are buffered, drained after the scrape

`NetworkPolicy` accumulates `DegradationNotice` value objects. `handle_scrape_subreddit` drains them
into `run_events` **after** `scraper.run()` returns. Nothing in `src/net/` holds a database session,
so no write can occur inside the window that produced P3's HTTP 500.

---

## 4. What was built

```
src/net/
├── providers/
│   ├── base.py             NetworkProvider ABC, Lease, Outcome, ProviderHealth,
│   │                       Capacity, Rotation, ProviderUnavailable
│   ├── direct.py           DirectProvider — pinned profile, rolling hourly governor
│   ├── managed_list.py     WebshareDatacenterProvider — adapts the shipped pool
│   ├── managed_gateway.py  ManagedProxyProvider — every managed vendor, one class
│   ├── null.py             NullProvider — asserts a path made no network call
│   └── registry.py         type -> class, ${ENV} resolution, readable config errors
├── policy.py               NetworkPolicy, RequestClass, ALWAYS_DIRECT, the ladder,
│                           DegradationNotice, EgressExhausted, config builders
├── egress.py               the process-wide policy (one per machine, not per job)
├── proxy_manager.py    ~   target acceptance, exclude=, pressure-scaled cooldown
├── blocks.py           ~   BlockSignatures — generic here, target-specific injected
└── http_client.py      ~   one loop, through the policy; request_class; bytes_in
```

**Six request classes** (`rss`, `health`, `website`, `html`, `comments`, `validation`), of which
**three are direct under every policy** ([R18](ARCHITECTURE_FREEZE.md)) — enforced in code, not by
configuration.

### 4.1 Deliberately not built

| Not done | Why |
|---|---|
| `RedditClient` raising instead of returning `None` (T5) | [34 §P4](34-implementation-plan.md) authorises none of it and AD-2 freezes the client's API. It is P5/P6's, and §7 records what it costs today |
| Sticky sessions wired to pagination | `session_key` is implemented and plumbed; **no caller passes one**. `ManagedProxyProvider` needs it for `-session-{key}`; the first *caller* is P5/P6 |
| `WebshareResidentialProvider` as a class | It is `managed_gateway` with different config. Writing a class per vendor would contradict the economy the design names as its main win |
| `PoolCircuitBreaker` rolling-window rewrite | [29 §4.4](29-network-and-proxy-strategy.md) says the breaker is unchanged plus an acceptance trigger, which is what shipped |
| `COOLDOWN` probation, per-cause blacklist durations | [12 §14](12-phase-02.md) deliberately-not-built; not in P4's task list |
| Any residential purchase | Deferred; P0 measured the opposite of its trigger |

---

## 5. Defects found and fixed during the phase

### 5.1 ⚠️ Fence 4 did not exist, and writing it failed — **pre-existing, from P2**

[35 §2.1](35-testing-strategy.md) lists *"Fence 4 — no Reddit knowledge in `src/net/`"* among the
**four checks it calls non-negotiable**. [12 §14](12-phase-02.md) ticked it as delivered. **No such
test existed.**

Writing it as specified found **seven** Reddit identifiers in executable code in `src/net/blocks.py`:
`_NEW_REDDIT_MARKERS`, `"shreddit-app"`, `"shreddit-async-loader"`, `"welcome to reddit"`,
`"Reddit rate-limit interstitial"`, `"served the new Reddit app instead of old HTML"`.

**Root cause, not spelling.** [08](08-proxy-service.md)'s opening line is *"`src/net/` knows nothing
about subreddits, leads, or Reddit markup"*, and the stated payoff is that the website fetcher
inherits the whole layer. A detector hard-coding one site's markup **is** that knowledge — and it is
actively wrong for P13, which fetches a customer's own website through the same client and must not
have Reddit's "you were bounced to the wrong app" heuristic applied to it.

**Fixed** by injection (§3.2). Signatures were **moved, not deleted**; every existing detection
fixture still classifies identically. Two tests in `TestBlockClassification` now construct with the
Reddit set — justified under P4's acceptance, which permits a changed test if the change is
justified.

### 5.2 ⚠️ R18 had a hole: a ladder without `direct` left the frozen classes unrouted — **introduced, caught by its own test**

`eligible()` filtered providers from the **ladder**, then applied the always-direct rule. With
`ladder: [dc]` the direct provider was never a candidate, so `website` — the customer's own site —
resolved to nothing.

Caught by `test_they_are_direct_even_when_direct_is_absent_from_the_ladder`, written specifically to
attack R18 from the hardest angle, and failing on its first run.

**Fixed at the root:** the always-direct classes search **every configured provider**, not the
ladder. The ladder is a degradation order for the classes that consult one; these do not. Leaving it
ladder-scoped would have turned a frozen rule into a config option *by omission* — the subtler half
of the same mistake as deleting an entry from `direct.classes`.

### 5.3 ⚠️ The clean-session guard did not detect its own mutation — **introduced, caught by mutation testing**

The new RK-1 regression test asserted the handler's session is clean during a degrading scrape. It
passed. Moving the drain **before** `scraper.run()` — the exact defect it exists to catch — **also**
passed. Two independent reasons:

1. **It measured after the autoflush.** The fake read `session.dirty or session.new` *after* issuing
   its query, and the query is itself the flush point, so it cleared `.new` on the way through. The
   assertion reported a clean session precisely in the case where the lock had just been taken.
2. **Nothing was pending to drain.** The degradation is caused *by* the scrape, so with the drain
   moved earlier there was nothing to write yet.

**Fixed** by reading the session state *before* the query, and by leaving a notice pending on entry —
modelling the real shape, which is the second subreddit of a run whose first one already degraded.
The mutation now fails two tests.

> This is P3's **F7 lesson a third time**: a guard that has not been seen to fail is not a guard. The
> first two occurrences were fakes that were easier than reality; this one was a *measurement point*
> that was easier than reality. Same family.

### 5.4 ⚠️ `exclude=tried` was enforced but untested — **introduced, caught by mutation testing**

Deleting the exclusion filter from `ProxyManager.acquire` broke **zero** tests. The test intended to
cover it (`test_every_request_exits_through_a_proxy`) counts distinct exits over three attempts and
passes on LRU ordering alone.

**Fixed** with four tests that assert the contract directly, including the case LRU cannot cover: a
paced pool where the *excluded* exit is the only one ready, so ordering alone would hand back the IP
that just failed. Removing the filter now fails all four.

### 5.5 ⚠️ The production block-signature wiring was untested — **introduced, caught by mutation testing**

Deleting `block_signatures=REDDIT_SIGNATURES` from `_default_client` broke **zero** tests: every
transport test builds its client through `_client_with`, which passes them explicitly. The product
would have silently lost soft-block detection — whose module docstring says a false negative
*"poisons the cache and the lead table"* — with a green suite.

**Fixed** with a test that constructs the client the production way and asserts both the wiring and
the resulting behaviour on the real 311 KB interstitial fixture.

### 5.6 A `Referer` request from the direct connection picked a **random** header profile — **pre-existing, from P2**

`headers_for(None, referer=...)` falls through to `pick_profile(None)`, which is
`random.choice(PROFILES)`. The direct session is built with `DEFAULT_PROFILE`, so any direct fetch
carrying a `Referer` presented a Chrome UA from one profile beside a Firefox `Accept-Language` from
another.

**That is the exact incoherence that produced a measured 100% block rate, twice** — 2026-07-31
([PHASE-02-STATUS §3.1](PHASE-02-STATUS.md)) and again 2026-08-05
([SPRINT-0 §1.5](SPRINT-0-MEASUREMENTS.md)). It was latent because nothing passed a `Referer` on the
direct path before P4 made direct the first rung.

**Fixed at the root:** a `Lease` carries the profile its session was built with, and
`headers_for_profile()` extends *that* identity. `headers_for()` remains for callers that want a
seeded pick.

### 5.7 Notice dedup was per-drain, not per-run — **introduced, caught by its own test**

`NetworkPolicy` dedups notices on `(from, to)`, but `drain_notices()` clears. A twelve-subreddit run
is twelve drains, so the timeline got twelve identical warnings instead of one.

**Fixed in the handler, not the policy.** The policy deliberately knows nothing about runs — that is
what lets it report degradation without a session — so it *cannot* dedup per run. The run's own
timeline is where "this run" is known, so the check belongs there. Matching on the rendered message
rather than on `(from, to)` is deliberate: the same step failing for a different reason is a
different fact and earns its own entry.

---

## 6. Mutation testing

[35 §2.4](35-testing-strategy.md): *"for every acceptance criterion, deliberately break the guarantee
in the source, confirm the test fails."*

| # | Mutation | Detected | By |
|---|---|---|---|
| 1 | Plant `REDDIT_MARKER = "reddit"` in `src/net/metrics.py` | ✅ | fence 4 |
| 2 | `COOLDOWN_FLOOR_SECONDS = 0.0` | ✅ **18 tests** | exhaustion, fail-closed, ladder |
| 3 | `candidates = list(usable)` (ignore `exclude`) | ✅ 4 tests | §5.4's new tests — **0 before them** |
| 4 | Make the always-direct branch unreachable | ✅ 4 tests | R18 suite |
| 5 | Move the degradation drain before `scraper.run()` | ✅ 2 tests | §5.3's corrected guard — **1 before it** |
| 6 | Delete `block_signatures=REDDIT_SIGNATURES` from `_default_client` | ✅ | §5.5's new test — **0 before it** |
| 7 | Build the policy per call instead of once | ✅ | the shared-governor tests |

**Three of seven were undetected on the first attempt.** Each gap is a defect in §5, and each is now
covered by a test that has been *observed* to fail.

---

## 7. Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| A1 | RSS, health, website go **direct** under `prefer_proxy` | ✅ and under all three policies, and with `direct` absent from the ladder |
| A2 | Bulk HTML uses a proxy when healthy; degrades per policy | ✅ |
| A3 | Degradation emits a **visible `run_events` warning**, hourly cap respected | ✅ |
| A4 | `ProxyLeakError` still fatal | ✅ the ladder steps on `ProviderUnavailable` **only**; anything else propagates |
| A5 | Healthy-on-ipify but soft-blocked on target → **degraded** | ✅ acceptance is a separate signal; the probe does not count toward it |
| A6 | All existing `src/net/` tests pass, or the change is justified | ✅ 3 changed, all justified (§5.1, and one fixture given a third exit — §5.4) |
| A7 | Vendor swap is config-only | ✅ 5 config blocks across 4 classes, no code change |
| A8 | Retries use a **different** exit, enforced | ✅ §5.4 |
| A9 | Credentials in no log/DB/response/UI | ✅ extended to the new gateway credential path |
| A10 | `src/net/` has **zero** Reddit identifiers | ✅ fence 4 now exists (§5.1) |
| A11 | Metered provider below its floor reports unhealthy, policy degrades | ✅ |

### 7.1 Honest limitations

**`pause_run` and `fail_run` are not distinguishable from the run page.** Both end with the
subreddit yielding no pages and the job completing with zero leads, because `RedditClient._get`
catches every transport failure and returns `None` (P2's decision, [T5](PHASE-03-HANDOVER.md)). P4
carries the operator's choice correctly — `EgressExhausted.action` and `.retryable` — and it is
asserted at the policy level, but the *run* cannot respond to it until the transport raises.

**This was already true before P4**: `fail_closed: true` did not fail a job either, despite
[08 §7](08-proxy-service.md) implying it would. P4 did not introduce the gap; it is the first phase
in a position to see it. [testing/P04-testing.md](testing/P04-testing.md) T8 was rewritten to test
what is actually observable rather than what the design document claimed.

**The direct governor is in-process and resets on restart.** A persistent counter needs a table, and
P4 owns no migration.

**Bandwidth accounting is decompressed length.** `http_client` reads with `decode_content=True`, so
`bytes_in` over-states what a vendor bills — a conservative floor for the guard, not an invoice.

**R20's migration half is still not machine-verified in CI.** Carried from P3 and unchanged; see the
handover.

---

## 8. Behaviour changes an operator will notice

Three, all intended, all documented, all reversible by config.

| # | Change | Why |
|---|---|---|
| 1 | **Bulk HTML now prefers the direct connection** over the datacenter pool | P0's measurement (§1). Reverse with `ladder: [dc, direct]` |
| 2 | **An exhausted pool no longer stops the run** — it degrades, under a 120/hour cap, with a warning | The phase's objective. Revert with `policy: proxy_only` + `on_pool_exhausted: fail_run` |
| 3 | **`/health/proxies` now reflects scraper traffic** | It never did before: `dashboard/app.py` built one pool and every scrape job built another, so the page reported a pool that had never served a request. Both now resolve the same process-wide policy — which is also what makes the hourly cap a real cap |

---

## 9. Documentation landed

- [08 §3a](08-proxy-service.md) — **new**: target acceptance as the third health signal
- [08 §3.1](08-proxy-service.md) — LRU recorded as shipped; `exclude=tried` now enforced; cooldown floor
- [08 §7](08-proxy-service.md) — `fail_closed` → `on_pool_exhausted`, **original reasoning retained**
- [08 §10](08-proxy-service.md) — `WebsiteFetcher` moved off the pool, with the error named
- [07 §1](07-scraping-pipeline.md) — "all traffic via rotating proxy" → per request class
- [03 §6](03-architecture.md) — **AD-25 transcribed** into the decision register
- [03 §8](03-architecture.md) — **network provider** row in the technology table
- [12 §14](12-phase-02.md) — `exclude=tried` moved to delivered, with why the original reasoning was half right
- [34 §P4](34-implementation-plan.md) — DELIVERED marker
- [CHANGELOG.md](../CHANGELOG.md) · [testing/P04-testing.md](testing/P04-testing.md) ·
  [PHASE-04-HANDOVER.md](PHASE-04-HANDOVER.md) · [progress/P04-COMPLETE.md](progress/P04-COMPLETE.md)

**No amendment and no §11.1 reconciliation.** No technology, table, migration, dependency or
capability was added that [ARCHITECTURE_FREEZE](ARCHITECTURE_FREEZE.md) does not name.
