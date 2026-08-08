# PHASE-04 HANDOVER — Network provider abstraction → P5

**From:** P4 — Network provider abstraction (complete 2026-08-08)
**To:** P5 — RSS client & Atom parser
**Companion:** [PHASE-04-COMPLETION-REPORT.md](PHASE-04-COMPLETION-REPORT.md) · [testing/P04-testing.md](testing/P04-testing.md)
**Architecture status:** FROZEN. P4 produced **no amendment and no reconciliation**.

> ⚠️ **Not to be confused with the legacy "Phase 04."** [`14-phase-04.md`](14-phase-04.md) and
> [`testing/phase-04-testing.md`](testing/phase-04-testing.md) belong to the **old eight-phase
> numbering**, where "Phase 04" was the Business Knowledge Base — which maps to **P12–P16** here.
> The two schemes are unrelated. P4 cost half a day of reading to establish that; do not re-pay it.

This document exists so whoever picks up P5 does not have to re-derive P4's decisions from the diff.

---

## 1. What now exists

```
src/net/
├── providers/
│   ├── base.py             NetworkProvider ABC · Lease · Outcome · ProviderHealth ·
│   │                       Capacity · Rotation · ProviderUnavailable
│   ├── direct.py           DirectProvider      exposes_origin_ip=True, hourly governor
│   ├── managed_list.py     WebshareDatacenterProvider   adapts the shipped ProxyManager
│   ├── managed_gateway.py  ManagedProxyProvider         every managed vendor, one class
│   ├── null.py             NullProvider                 asserts "no network call here"
│   └── registry.py         build_provider() · ${ENV} resolution · readable errors
├── policy.py               NetworkPolicy · RequestClass · ALWAYS_DIRECT ·
│                           DegradationNotice · EgressExhausted · build_policy_from_config
├── egress.py               get_policy() / reset_policy()  — one policy per PROCESS
├── proxy_manager.py    ~   + target_ok/target_blocked/acceptance_rate, exclude=,
│                           effective_cooldown() with a floor, usable_count
├── blocks.py           ~   + BlockSignatures; generic markers here, target-specific injected
└── http_client.py      ~   one loop through the policy; request_class=; session_key=; bytes_in
```

### 1.1 The interfaces P5 will use

```python
from src.net import get_policy, RequestClass

client.get(url, request_class=RequestClass.RSS.value)   # -> always DIRECT (R18)
client.get(url, session_key="whatever")                 # sticky, where the provider supports it

policy = get_policy(config)          # the process-wide policy; same object as the dashboard's
policy.drain_notices()               # value objects; the caller writes them to run_events
policy.describe()                    # the /api/health/proxies payload
```

**`ProxiedHTTPClient.get()` gained two keyword arguments, both with defaults.** Everything that
called it before P4 still calls it correctly and gets `request_class="html"`.

---

## 2. Seven guarantees P5 must not break

### G1 — `src/net/` contains zero Reddit identifiers, and it is now enforced

Grep fence 4 exists for the first time (`tests/test_boundaries.py::test_the_network_layer_has_no_reddit_knowledge`),
AST-based, scoped to `src/net/`. Docstrings and comments are allowed and wanted; identifiers and
runtime strings are not. **P5 adds Atom parsing — put it in `src/discovery/`, not here.** If P5 needs
target-specific block or parse signatures, inject them the way `REDDIT_SIGNATURES` is injected.

### G2 — Nothing in `src/net/` holds a database session

This is what lets the network layer report degradation without taking SQLite's write lock across a
fetch. `NetworkPolicy` returns `DegradationNotice` **value objects**; the caller writes them. A
`session` parameter anywhere under `src/net/` is a defect, not a convenience.

### G3 — Degradation is drained **after** network work, never during

`handle_scrape_subreddit` calls `_record_egress_degradations(session, run_id)` *after*
`scraper.run()` returns. **P5/P6 add discovery handlers that make network calls; they need the same
three lines in the same position.** See §4 T1.

### G4 — One policy per process

`src/net/egress.get_policy()`. The hourly governor and the blacklist are budgets over a *machine*.
A handler that builds its own policy enforces a 120/hour cap N times per run. `build_scraper()`
resolves it; so does `dashboard/app.get_network_policy()`; they are the same object.

### G5 — R18's three classes are direct in code, not in configuration

`ALWAYS_DIRECT = {rss, health, website}` in `src/net/policy.py`. They are direct under every
`policy` value, whether or not `direct` appears in the ladder, and an attempt to remove one from
`network.direct.classes` is logged and ignored. **`rss` is P5's class and it is already routed.**

### G6 — `exclude=tried` is enforced, not emergent

Every attempt adds its label; the next acquire excludes them. When every reachable exit has been
tried the transport stops retrying rather than reusing one. If P5 adds a retry path, pass `exclude`.

### G7 — `build_scraper()` keeps its name and one-argument shape

P3's G3/T2, still true. Roughly a dozen tests patch it by name.

---

## 3. What P4 deliberately did NOT do

| Not done | Owner |
|---|---|
| **`RedditClient._get` raising instead of returning `None`** — see §4 T1 | **P5/P6** |
| Sticky sessions wired to pagination. `session_key` is implemented and plumbed; no caller passes one | P5/P6 |
| `get_feed()`, Atom parsing, conditional GET, `x-ratelimit-reset` | P5 |
| A `WebsiteFetcher`. The `website` class ships with no consumer, by design | P13 |
| Any migration. `alembic heads` is still one `0004` | — |
| A residential purchase. `managed_gateway` ships with no credentials | Deferred |
| `PoolCircuitBreaker`'s rolling window, `COOLDOWN` probation, per-cause blacklist durations | — |
| CI action version bumps (`checkout@v5`, `setup-python@v6`) | P30 |

---

## 4. Traps waiting in P5

**T0 — never hold the SQLite write lock across I/O. Still the most expensive trap in this codebase.**
P3 lost a sign-off to it; P4 added a write inside the same window and had to prove it did not
reopen it. `tests/test_handlers_scrape.py` asserts the session is clean at the moment a scrape
starts **and** during a scrape that degrades. **A P5 discovery handler that emits an event before its
fetch will reproduce the HTTP 500 exactly.**

**T1 — `RedditClient._get` still swallows every transport failure and returns `None`, and this now
costs something visible.** `on_pool_exhausted: pause_run` and `fail_run` are indistinguishable from
the run page because neither can reach the handler as an exception (completion report §7.1). P4
carries the answer correctly in `EgressExhausted.action` / `.retryable`; **P5 or P6 is where the
transport starts raising and `handlers/scrape.py` gains the mapping.** Note this was already true
pre-P4 — `fail_closed: true` never failed a job either.

**T2 — a mutation you have not run is a test you do not have.** Three of P4's seven mutations were
undetected on the first attempt (completion report §6), including the guard for the defect that
blocked P3. Two were tests that passed for the wrong reason; one was a measurement taken *after* the
autoflush it was trying to observe. **Run the mutation before believing the guard.**

**T3 — the P4 config block is optional, and the fallback path is real.** Delete `network:` and
`build_policy_from_config` reconstructs the pre-P4 arrangement from `proxy:`. If P5 adds config,
keep that path working — it is the documented second rollback level and it is tested.

**T4 — `reset_policy()` in any test that touches egress.** The policy is a process-wide singleton.
A test that leaves a degraded or governor-exhausted policy behind will fail the *next* test, in a
different file, for reasons that look unrelated. `tests/test_handlers_scrape.py::degrading_policy`
is the pattern.

**T5 — `rss` is routed but has no fixtures.** P5 is the first consumer of a request class that P4
shipped. The routing is asserted; the *feed* behaviour is entirely P5's, and P0 measured that Reddit
sends **no `ETag` and no `Last-Modified`** on `.rss` ([ARCHITECTURE_FREEZE §11](ARCHITECTURE_FREEZE.md)),
so do not build conditional GET.

**T6 — `x-ratelimit-reset` is not handled.** `_retry_after` reads `Retry-After` only. P0 measured RSS
at **1 request per ~60 s per IP** — and the direct provider is one IP, so P5's pacing is a real
constraint, not a formality.

---

## 5. Findings from P4 worth carrying forward

| # | Finding | Lesson |
|---|---|---|
| **F1** | Fence 4 was specified in three documents, ticked as delivered, and did not exist — and would have failed | **A documented check that was never written is worse than an absent one**: it is counted as coverage. Run the four fences and read what they actually assert |
| **F2** | R18 had a hole reachable only via `ladder: [dc]` — a frozen rule made optional *by omission* | Attack an invariant from the angle a config file can produce, not the angle the code suggests |
| **F3** | The clean-session guard passed under the mutation it existed to catch — measured after the autoflush, with nothing pending | **P3's F7, third occurrence.** Verify the *measurement point*, not just the double |
| **F4** | `exclude=tried` was implemented and had zero tests that noticed its removal | A test that counts distinct outcomes over N attempts passes on ordering luck. Assert the contract |
| **F5** | Deleting the block-signature wiring from `_default_client` broke nothing | Every transport test built its own client. **Test the production construction path at least once** |
| **F6** | A direct fetch with a `Referer` picked a random header profile, mixing two identities | The failure mode that caused two measured 100% block rates, latent for three phases because nothing exercised the path |
| **F7** | Notice dedup was per-drain; the requirement was per-run | When a layer is deliberately ignorant of a scope, the dedup for that scope cannot live in it |

---

## 6. Verification snapshot at handover

| | |
|---|---|
| Full suite | **695 passed, 2 skipped** · 312 s (P3 baseline: 583 / 2) |
| Under `-W error::DeprecationWarning` | **695 passed, 2 skipped** |
| New P4 tests | **+112** |
| `ruff check` / `ruff format --check` | All checks passed! / 101 files already formatted |
| Coverage, `src/net/` | **91%** (was 85% — exactly the gate floor) |
| `alembic heads` | `0004_orchestration (head)` — one head, no migration |
| `check_schema.py` | **OK — all 25 checks passed** |
| Legacy contract | 459 baseline leads · `GET /` byte-identical · 13 CSV columns · 17 endpoints |
| Mutation testing | 7 mutations, 7 detected (3 only after the gaps they exposed were fixed) |
| Grep fences | **4 of 4** — fence 4 for the first time |

---

## 7. Blockers carried into P5

| ID | Blocker | Blocks P5? |
|---|---|---|
| **D1** | P00–P04 manual sign-off tables are unsigned | **By the project's own rule, yes** — [lock §4](EXECUTION_MODE_LOCK.md). P4 was implemented on the operator's declaration that P3 is signed off; the tables in the repository are still blank |
| **C1** | ⚠️ **R20's migration half is never verified in CI.** `data/leads.db` is correctly gitignored, so three live-database tests skip on the runner (`test_live_database_preserved`, `test_live_database_migrates_with_leads_intact`, `test_downgrade_removes_everything_and_restores_scrape_runs`). **"CI is green" does not mean "the legacy contract is machine-verified."** It is verified locally and by the manual guides. **A standing property of the CI design that every future phase inherits** | **No**, but it must not be forgotten |
| **B3 / O2** | `mypy` required by [35 §2](35-testing-strategy.md) check 3, not installed | **No** — but the gate cannot be claimed in full |
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` | **No** — gates P23 |
| **N1** | Keyword and user leads are not collected by the button or the scheduler | **No** — P5/P17's scope |
| **N2** | **New in P4.** `pause_run` and `fail_run` are indistinguishable at run level | **No** — it is T1, and P5/P6 is where it closes |

---

## 8. Entry conditions for P5

- [ ] `docs/testing/P04-testing.md` sign-off table signed (and P00–P03, still outstanding)
- [ ] `docs/34-implementation-plan.md` P5 read in full — all thirteen fields
- [ ] [07 §2a](07-scraping-pipeline.md) and [28](28-discovery-redesign.md) read — P5's design is not in one document
- [ ] **[SPRINT-0 §2](SPRINT-0-MEASUREMENTS.md) re-read**: U1 (RSS is rate-limited **per IP**, ~60 s
      recovery), U2 (RSS carries full selftext), U4 (**no `ETag`, no `Last-Modified`** — conditional
      GET does not exist and must not be built), U6. Two of these are P5 acceptance criteria and one
      deletes a documented layer
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] **The full suite recorded green before the first change** — 695 passed, 2 skipped
- [ ] `gh run list` checked: P4 green on `origin/main`
