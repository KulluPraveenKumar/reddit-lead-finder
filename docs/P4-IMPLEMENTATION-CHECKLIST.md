# P4 IMPLEMENTATION CHECKLIST — Network provider abstraction

**Status:** awaiting approval. **No source file has been modified.**
**Companions:** [P4-IMPLEMENTATION-REVIEW.md](P4-IMPLEMENTATION-REVIEW.md) ·
[P4-DECISION-ANALYSIS.md](P4-DECISION-ANALYSIS.md) · [testing/P04-testing.md](testing/P04-testing.md)

This document is the **execution checklist**: it is ticked during implementation, and it is the
record of what was actually done. Sections 0, 3, 4 and 5 answer Parts 0, 3, 4 and 5 of the P4
pre-implementation brief.

**P4 baseline commit:** `8a74b53af585d94c2d2402325610b8db6048b67a` — every `git diff` below is
against this. Referred to as `$P3` throughout.

---

# 0. P3 validation — CLOSED ✅

## 0.1 What was wrong

[PHASE-03-HANDOVER §7](PHASE-03-HANDOVER.md) carries blocker **R7**: *"GitHub CI runs for recent
commits — external; check `gh run list` at the start of P4."* Checked, and it was open:

```
main...origin/main [ahead 11]
last CI run:  31178009702  success  2026-08-07T12:23Z  "fix(P2): use timezone-aware UTC …"
local HEAD:   8a74b53                2026-08-07T16:56Z  "fix(P3): check_schema must pass …"
```

**All eleven P3 commits were unpushed.** The green run belonged to a **P2** commit. No P3 code had
ever executed in GitHub Actions.

## 0.2 Action taken

> git push origin main   →   `8c12367..8a74b53  main -> main`

## 0.3 Result

| Field | Value |
|---|---|
| **Run URL** | https://github.com/KulluPraveenKumar/reddit-lead-finder/actions/runs/31204648730 |
| **Job URL** | https://github.com/KulluPraveenKumar/reddit-lead-finder/actions/runs/31204648730/job/92952603526 |
| **Commit tested** | `8a74b53af585d94c2d2402325610b8db6048b67a` — *"fix(P3): check_schema must pass on a database that has been used"* |
| **Workflow** | `CI` — the only workflow in the repository (`.github/workflows/ci.yml`), one job named `gate` |
| **Trigger** | `push` to `main` |
| **Started / finished** | 2026-08-07 17:56:41Z → 17:58:29Z |
| **Duration** | **1 m 48 s** (job `gate`: 1 m 37 s; `pytest` step: 1 m 16 s) |
| **Final status** | **completed · success** |

### Every step, individually

| # | Step | Result |
|---:|---|---|
| 1 | Set up job | ✅ success |
| 2 | `actions/checkout@v4` | ✅ success |
| 3 | `actions/setup-python@v5` (Python 3.12.13, pip cache) | ✅ success |
| 4 | `pip install -r requirements.txt` | ✅ success (10 s — warm cache) |
| 5 | `ruff check .` | ✅ success — `All checks passed!` |
| 6 | `ruff format --check .` | ✅ success |
| 7 | `pytest` | ✅ success — **`580 passed, 5 skipped in 75.02s`** |
| 13–15 | Post-steps, complete job | ✅ success |

**Zero failures. Zero errors. Zero jobs skipped.** One job exists and it ran.

## 0.4 The five skips — identified, not waved through

Locally the suite reports `583 passed, 2 skipped`; CI reports `580 passed, 5 skipped`. **Same total
(585).** Three tests that pass locally are skipped on CI. Traced to source:

| # | Test | Skip reason | Why it fires on CI |
|---|---|---|---|
| 1–2 | Two in `tests/test_net.py` (`test_net.py:140/143`) | `PROXY_FILE is not set` | No proxy file on the runner, and none locally either — **these two skip in both places** |
| 3 | `tests/test_migrations.py::test_live_database_preserved` | `no live database present` (`conftest.py:91`) | `data/leads.db` is **gitignored**, so it is not in a fresh checkout |
| 4 | `tests/test_orchestration.py::test_live_database_migrates_with_leads_intact` | same | same |
| 5 | `tests/test_orchestration.py::test_downgrade_removes_everything_and_restores_scrape_runs` | same | same |

Both causes are **deliberate environment gates**, not flakiness: each is a `pytest.skip()` with an
explicit condition, and each skips for a stated, checkable reason. No test is `@pytest.mark.skip`,
no test is xfail, and nothing was disabled to make the run pass.

> ⚠️ **Honest limitation, and it is a real one — carry this into [PHASE-04-HANDOVER.md](PHASE-04-HANDOVER.md).**
> It is a standing property of the CI design that **every future phase inherits**, and it is
> currently recorded nowhere but this working document.
>
> The three live-database skips mean **R20's legacy-contract half — "the 459 baseline leads survive
> a migration round-trip" — is verified locally only, never in CI.** The runner cannot verify it because the database is correctly not in
> the repository. This is a pre-existing property of the CI design, not something P3 or P4
> introduced, and it is why [35 §2.1](35-testing-strategy.md) check 12 and the manual guides both
> run it against a copy of the live file. **It is recorded here so nobody reads "CI is green" as
> "the legacy contract is machine-verified."** It is verified by T1 Step 6 and T12 Step 4 of
> [P04-testing.md](testing/P04-testing.md), by hand, on the real database.

## 0.5 Warnings — reviewed

The log contains warnings. Each was read and classified:

| Warning | Source | Requires action? |
|---|---|---|
| `Node.js 20 is deprecated … actions/checkout@v4, actions/setup-python@v5 are being forced to run on Node.js 24` | GitHub runner infrastructure | **No, not now.** The actions still run, on Node 24, successfully. Bumping to `checkout@v5` / `setup-python@v6` is a CI-hygiene change owned by **P30** ([34 §P30](34-implementation-plan.md) — *Security review & CI*). Doing it inside P4 would be opportunistic scope. **Logged as a carried item — see §4.4** |
| `DeprecationWarning: the punycode module is deprecated` ×2 | Node internals inside the setup actions | No. Not our code; not reachable from Python |
| `DeprecationWarning: url.parse() behavior is not standardized` | Node internals inside `setup-python` | No. Same |
| `hint: to use in all of your new repositories…` | `git` init hint during checkout | No. Informational |

**No warning originates from this repository's Python code.** `pytest` produced no warning summary,
and the local `pytest -W error::DeprecationWarning` run (which turns every Python deprecation into a
failure) passes.

## 0.6 Flakiness

The run completed in 75 s of test time with no retries, no reruns, and no timing-sensitive failure.
P3's completion report notes the progress-budget test is timing-sensitive on a busy machine; it
passed on the runner. **No evidence of flakiness. No test was retried to obtain this result.**

## 0.7 Verdict

> ### ▶ **P3 is validated in GitHub Actions. R7 is closed. P4 is unblocked on this axis.**

Remaining P3 blockers, unchanged and **not** resolved by this run:

| ID | Blocker | Blocks P4? |
|---|---|---|
| **D1** | P00–P03 manual sign-off tables are unsigned | **By the project's own rule, yes** — [EXECUTION_MODE_LOCK §4](EXECUTION_MODE_LOCK.md). Carried forward from the P3 handover; your call, as it was for P3 |
| **B3 / O2** | `mypy` not installed — [35 §2.1](35-testing-strategy.md) check 3 | No, but the gate cannot be claimed in full |
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` | No — gates P23 |
| **N1** | Keyword/user leads no longer collected by the button | No — P5/P17 scope |

---

# 3. Expanded implementation stages

Eleven stages. Each ends green — `pytest`, `ruff check`, `ruff format --check` — so there is **no
broken intermediate commit** and every stage boundary is a valid rollback point.

**Stages 1–6 touch no existing consumer**, so the suite cannot regress before stage 7. Stage 7 is
the single riskiest commit and is deliberately isolated.

Total estimated new/changed production LOC: **~640**. Test LOC: **~700**.

---

## Stage 1 — The provider ABC

| Field | Value |
|---|---|
| **Purpose** | Define the contract every egress path implements, so the policy layer reasons about capabilities rather than branching on provider names |
| **Files** | `src/net/providers/__init__.py` +, `src/net/providers/base.py` +, `src/net/providers/null.py` +, `tests/test_net_providers.py` + |
| **Est. LOC** | ~120 production, ~90 test |
| **Interfaces affected** | **None existing.** Adds `NetworkProvider`, `Lease`, `Outcome`, `ProviderHealth`, `Capacity`, `NullProvider`, `PROVIDER_TYPES` registry |
| **Expected tests** | ABC cannot be instantiated; every concrete subclass implements all four abstract methods; capability flags default safely (`exposes_origin_ip=False`, `is_metered=False`); `NullProvider.acquire()` raises with a message naming the caller's intent; registry maps the four `type` strings — **`direct`, `managed_list`, `managed_gateway`, `null_provider`** (not bare `null`, which YAML parses as `None`) — to classes and rejects an unknown type with a readable error |
| **Coverage impact** | New module at ~95%. `src/net/` total: 85% → **~86%** |
| **Risks** | Getting the ABC shape wrong forces churn in stages 3–6. Mitigated by writing `null.py` in the same stage — implementing the ABC once immediately proves it is implementable |
| **Rollback point** | Delete `src/net/providers/`. Nothing imports it |
| **Validation** | `pytest tests/test_net_providers.py -v` · `pytest` · `ruff check .` · `ruff format --check .` |
| **AC satisfied** | Groundwork for A1, A2, A7, A11. **A7 partially** — the registry is the mechanism that makes vendor swap config-only |

---

## Stage 2 — Pool upgrades on `ProxyManager` (additive only)

| Field | Value |
|---|---|
| **Purpose** | Add the three behaviours [34 §P4](34-implementation-plan.md) tasks 6–8 require — target acceptance, explicit `exclude`, pressure-scaled cooldown — **without changing any existing behaviour** |
| **Files** | `src/net/proxy_manager.py` ~, `tests/test_net.py` ~ (additions only) |
| **Est. LOC** | ~70 production, ~120 test |
| **Interfaces affected** | `ProxyStats` +3 fields (`target_ok`, `target_blocked`, `acceptance_rate`); `acquire(*, wait, timeout, exclude=None, session_key=None)`; `PoolSnapshot.proxies[]` rows gain `acceptance_rate`. **All additive** |
| **Expected tests** | `exclude=tried` → three failures use three distinct exits (**A8**); acceptance is neutral below the sample floor and a warm mixed-rate pool still spreads (**P-3**); `record_failure(blocked=True)` decrements acceptance while `record_failure(blocked=False)` does not; cooldown scales with pressure **and respects its floor**; **at 0 healthy, `acquire()` still raises `ProxyExhaustedError`** (**P-1**) |
| **Coverage impact** | `proxy_manager.py` 74% → **~88%**. `src/net/` total → **~88%** |
| **Risks** | **RK-9 (Critical)** — a cooldown of zero at 0 healthy makes `ProxyExhaustedError` unreachable, silently disabling the entire ladder. **RK-11 (High)** — acceptance-ordered selection collapsing the pool onto one exit |
| **Mutation required** | Set the cooldown floor to 0 → the exhaustion **and** `TestFailClosed` tests must fail. Make acceptance influence selection at n=0 → the LRU-spread test must fail |
| **Rollback point** | `git revert` this commit; `ProxyManager` returns to its P3 shape and every consumer is unaffected because nothing yet passes the new arguments |
| **Validation** | `pytest tests/test_net.py -v` — **all 112 pre-existing tests must pass unchanged**, including `TestProxyManager` and `TestFailClosed` · `pytest` · `pytest --cov=src/net` |
| **AC satisfied** | **A8** (retries use a different exit), **A5** groundwork (acceptance is the signal) |

---

## Stage 3 — `WebshareDatacenterProvider` (`managed_list`)

| Field | Value |
|---|---|
| **Purpose** | Put today's pool behind the ABC, **behaviour unchanged** — [34 §P4](34-implementation-plan.md) task 2 |
| **Files** | `src/net/providers/managed_list.py` +, `tests/test_net_providers.py` ~ |
| **Est. LOC** | ~90 production, ~80 test |
| **Interfaces affected** | New class only. It **adapts** to `ProxyManager` rather than replacing it — resolving [P4-IMPLEMENTATION-REVIEW §6 R-2](P4-IMPLEMENTATION-REVIEW.md) |
| **Expected tests** | `acquire()` returns a `Lease` wrapping a `ProxyEndpoint`; `release(outcome=OK)` calls `record_success`, `release(outcome=BLOCKED)` calls `record_failure(blocked=True)`; `health()` reflects `healthy_count` and `circuit_open`; `capacity()` reports usable exits; `exposes_origin_ip is False`; the fake-session seam (`session_for`) still works through the adapter |
| **Coverage impact** | New module ~92%. `src/net/` total → **~88%** |
| **Risks** | **RK-2 (High)** — the adapter changing pool semantics by accident (e.g. counting a lease twice, or losing the pacing sleep) |
| **Mutation required** | Make `release()` a no-op → the blacklist-after-N-failures test must fail |
| **Rollback point** | Delete the file. `ProxyManager` is still used directly by `http_client` at this stage |
| **Validation** | `pytest tests/test_net.py tests/test_net_providers.py -v` · `pytest` |
| **AC satisfied** | **A6** (existing pool tests unchanged), groundwork for A2 |

---

## Stage 4 — `DirectProvider`

| Field | Value |
|---|---|
| **Purpose** | Make the direct connection a first-class provider with a pinned header profile and an hourly governor — [34 §P4](34-implementation-plan.md) task 3 |
| **Files** | `src/net/providers/direct.py` +, `tests/test_net_providers.py` ~ |
| **Est. LOC** | ~85 production, ~90 test |
| **Interfaces affected** | New class. `exposes_origin_ip = True` — **the only provider for which this is true** |
| **Expected tests** | The governor permits N and refuses N+1 within the hour, and the window rolls; the counter is **shared, not per-instance** (**P-2**); `headers` is a **whole** `HeaderProfile`, never a partial dict (**AS-5** — a hand-built header set is what caused a 100%-block outage twice, [SPRINT-0 §1.5](SPRINT-0-MEASUREMENTS.md)); `health()` is unhealthy once the governor is spent; `is_metered is False` |
| **Coverage impact** | New module ~93%. `src/net/` total → **~89%** |
| **Risks** | **RK-5 (Medium)** — the governor throttling a legitimate run. 120/h against a measured steady state of ≤80/**day** leaves ample headroom, and reaching it emits its own warning. **AS-5 (High if wrong)** — a partial header profile reintroduces a total outage that looks exactly like an IP ban |
| **Mutation required** | Remove the governor check → the cap test must fail. Return a partial header dict → the atomicity test must fail |
| **Rollback point** | Delete the file |
| **Validation** | `pytest tests/test_net_providers.py -v` · `pytest` |
| **AC satisfied** | **A3** (the hourly cap half), groundwork for **A1** |

---

## Stage 5 — `ManagedProxyProvider` (`managed_gateway`)

| Field | Value |
|---|---|
| **Purpose** | One generic gateway class covering every residential vendor — [29 §3.1](29-network-and-proxy-strategy.md) calls this "the design's main economy" |
| **Files** | `src/net/providers/managed_gateway.py` +, `tests/test_net_providers.py` ~ |
| **Est. LOC** | ~110 production, ~110 test |
| **Interfaces affected** | New class. Takes `gateway`, `username`, `password`, `session_param`, `metered`, `bandwidth_budget_gb`, `bandwidth_floor_gb` |
| **Expected tests** | `session_param: "-session-{key}"` renders into the username for a given `session_key`, and the **same key yields the same exit identity**; `repr`/`str`/`to_dict` expose **host:port only**, never credentials (**RK-7**); `bytes_in` accumulates through `release()`; below `bandwidth_floor_gb`, `health()` reports unhealthy (**A11**); `capacity()` reports remaining budget; four different vendor configs construct identically with no code change (**A7**) |
| **Coverage impact** | New module ~90%. `src/net/` total → **~89%** |
| **Risks** | **RK-7 (High)** — this is a **new credential path**. Gateway credentials come from config/env, not the proxy file the existing four guarantees were built around, so `RedactingFilter`, `ProxyEndpoint.__repr__` and the health-payload label rule must all be re-proven for it |
| **Mutation required** | Return the credentialled URL from `to_dict()` → the credential-scan test must fail |
| **Rollback point** | Delete the file |
| **Validation** | `pytest tests/test_net_providers.py -v` · `pytest -k credential -v` · `pytest` |
| **AC satisfied** | **A7** (vendor swap is config-only), **A9** (credentials never leak), **A11** (bandwidth floor) |

---

## Stage 6 — `NetworkPolicy`

| Field | Value |
|---|---|
| **Purpose** | The component the phase is named for: choose a provider per request class, walk the ladder on failure, apply `on_pool_exhausted`, and record degradation |
| **Files** | `src/net/policy.py` +, `tests/test_network_policy.py` + |
| **Est. LOC** | ~150 production, ~200 test |
| **Interfaces affected** | New: `NetworkPolicy`, `RequestClass`, `DegradationNotice`, `build_policy_from_config`, `build_policy_from_settings` |
| **Expected tests** | Every request class × every policy value resolves as specified (**A1**); `rss`/`health`/`website` resolve to `direct` **even under `proxy_only` with `direct` absent from the ladder** (**R18**, the central test); the ladder steps on provider failure and stops at the end (**A2**); all three `on_pool_exhausted` values behave differently (**A2**); notices accumulate and dedup on `(from, to)` (**AS-7**); `ProxyLeakError` propagates rather than degrading (**RK-6**); a metered provider under its floor is skipped (**A11**); every configured block constructs (**A7**); with no `network:` block, the legacy `proxy:` block yields the P3 configuration byte-for-byte (**AS-6**) |
| **Coverage impact** | New module ~93%. `src/net/` total → **~90%** |
| **Risks** | **RK-6 (Critical)** — the ladder swallowing `ProxyLeakError` and degrading past a leak instead of failing on it. The leak check is the one guarantee the pool exists to provide |
| **Mutation required** | Catch `ProxyLeakError` in the ladder walk → the leak test must fail. Make `direct.classes` a ladder preference rather than a rule → the R18 test must fail |
| **Rollback point** | Delete the file. Still nothing imports it |
| **Validation** | `pytest tests/test_network_policy.py -v` · `pytest` · `pytest --cov=src/net` |
| **AC satisfied** | **A1, A2, A4, A11**, and **A7** completely |

---

## Stage 7 — Transport wiring ⚠️ the riskiest commit

| Field | Value |
|---|---|
| **Purpose** | Make the shipped transport use the policy, and resolve the policy **process-wide** rather than per job |
| **Files** | `src/net/http_client.py` ~, `src/net/__init__.py` ~, `src/reddit_client.py` ~, `src/dashboard/app.py` ~, `src/orchestration/handlers/scrape.py` ~ (construction only — the drain is stage 9), `tests/test_net.py` ~ |
| **Est. LOC** | ~90 production, ~60 test |
| **Interfaces affected** | `ProxiedHTTPClient.__init__(egress=…)` accepting a `NetworkPolicy` **or** a `ProxyManager`; `get(..., request_class="html", session_key=None)`; `bytes_in` reported to `release()`; `get_network_policy()` beside `get_proxy_manager()`. **All additive — `build_scraper`'s name and one-argument shape are unchanged (P3 T2/G3)** |
| **Expected tests** | Every pre-existing `test_net.py` test passes; a client built from a bare `ProxyManager` still works (back-compat); **two `build_scraper()` calls share one governor and one blacklist** (**P-2**); `request_class` defaults to `html`; `bytes_in` is reported and is the decompressed length (**AS-3**) |
| **Coverage impact** | `http_client.py` 90% → **~92%**. `src/net/` total → **~90%** |
| **Risks** | **RK-2 (High)** — this is where a silent behaviour change would land. **P-2 (High)** — per-job construction would enforce the frozen 120/h budget at N×, and would reset the blacklist and acceptance window every subreddit. **T2 (P3)** — roughly a dozen tests across four files patch `build_scraper` by name |
| **Mutation required** | Build the policy per call rather than once → the shared-governor test must fail |
| **Rollback point** | **The critical one.** Reverting this single commit restores the shipped transport while leaving stages 1–6 in place, unused and harmless |
| **Validation** | `pytest tests/test_net.py -v` **compared line-by-line against the §0 baseline** · `pytest` · `pytest --cov=src/net` · `pytest -W error::DeprecationWarning` |
| **AC satisfied** | **A6** (the whole existing suite still passes) |

---

## Stage 8 — Configuration and the health surface

| Field | Value |
|---|---|
| **Purpose** | Give the operator a way to configure the policy and to see which egress path is in use |
| **Files** | `config.yaml` ~, `src/dashboard/routes_health.py` ~, `src/dashboard/templates/health_proxies.html` ~, `tests/test_net.py` ~ |
| **Est. LOC** | ~70 production + ~60 YAML, ~50 test |
| **Interfaces affected** | `GET /api/health/proxies` gains `policy`, `ladder`, `on_pool_exhausted`, `providers[]`, `direct_requests_this_hour`, `direct_max_requests_per_hour`; **`fail_closed` retained as a derived alias** (D-D). Not one of the 17 legacy endpoints — verified against `LEGACY_ROUTES` |
| **Expected tests** | The payload is **additive** — every pre-P4 key still present with the same type; `fail_closed` tracks `on_pool_exhausted == "fail_run"`; no credential in the payload for a **gateway** provider (**RK-7**); the page renders every new field; every nav URL still resolves |
| **Coverage impact** | Dashboard coverage unchanged; `src/net/` unaffected |
| **Risks** | **RK-10 (Medium)** — the health page and the scraper have **never** shared a pool (`app.py` holds its own singleton). After stage 7 they do, so request counts will appear on a page that has always shown zeros. An improvement, but it must be stated in the completion report and the manual guide so it does not read as a defect |
| **Rollback point** | Revert; the payload returns to its P3 shape |
| **Validation** | `pytest tests/test_net.py -k health -v` · `pytest tests/test_boundaries.py -v` (17 endpoints, `GET /` byte-identical) · `pytest` |
| **AC satisfied** | **A9** (no credential in any response), operator visibility for **A3** |

---

## Stage 9 — The degradation `run_events` warning (D-C / C1)

| Field | Value |
|---|---|
| **Purpose** | Make degradation **visible**, which is what makes bounded degradation acceptable at all — [29 §2.2](29-network-and-proxy-strategy.md) |
| **Files** | `src/orchestration/handlers/scrape.py` ~, `tests/test_handlers_scrape.py` ~ |
| **Est. LOC** | ~10 production, ~90 test |
| **Interfaces affected** | None. The handler drains `NetworkPolicy.drain_notices()` **after** `scraper.run()` returns |
| **Expected tests** | Exactly one `run_events` row at `warning`, naming the provider degraded **from** and **to**; a second degradation to the same rung adds no row; **the session is clean after a degrading scrape**; **cancel during a degrading scrape returns 200, not 500** |
| **Coverage impact** | `handlers/scrape.py` stays ≥97% |
| **Risks** | **RK-1 (Critical)** — recreating P3's F7. See §5.1 for the full analysis |
| **Doubles (mandatory shape)** | The fake scraper **must query the database** during `run()` so autoflush takes the write lock exactly as `LeadScorer` does, **and must cause a degradation** while running. A fake that does neither is how F7 passed 583 tests and failed in manual testing |
| **Mutation required** | Move the drain loop to **before** `scraper.run()` → the clean-session test **and** the cancel test must both fail. If they pass, the doubles are easier than reality and the guard is worthless |
| **Rollback point** | Delete four lines. The transport is unaffected; the log warning remains |
| **Validation** | `pytest tests/test_handlers_scrape.py -v` · `pytest tests/test_run_service.py tests/test_run_api.py -v` · `pytest` |
| **AC satisfied** | **A3** (visible `run_events` warning) |

---

## Stage 10 — Fence 4 (D-B / B1)

| Field | Value |
|---|---|
| **Purpose** | Make [35 §2.1](35-testing-strategy.md)'s non-negotiable check 11 exist and pass honestly |
| **Files** | `src/net/blocks.py` ~, `src/net/http_client.py` ~, `src/net/__init__.py` ~, `src/reddit_client.py` ~, `tests/test_boundaries.py` ~, `tests/test_net.py` ~ |
| **Est. LOC** | ~65 production, ~40 test |
| **Interfaces affected** | `blocks.classify(..., signatures=DEFAULT_SIGNATURES)` — additive; new `BlockSignatures`; `ProxiedHTTPClient(..., block_signatures=None)` |
| **Expected tests** | The fence passes on `src/net/`; **the fence fails when a Reddit token is injected** (mutation, and it is in the manual guide as T12 Step 2); every existing soft-block fixture classifies **identically** on the same fixtures; a Cloudflare challenge is detected with **no** signatures injected (the P13 case) |
| **Coverage impact** | `blocks.py` stays at 100% |
| **Risks** | **RK-3 (High)** — breaking soft-block detection, whose own docstring says a false negative *"poisons the cache and the lead table"* |
| **Mutation required** | Remove the signature injection from `RedditClient` → the Reddit-interstitial tests must fail. **This is the test that proves B1 was done correctly rather than merely done.** Also: [35 §2.4](35-testing-strategy.md) records that a past fixture in this module tripped two detection paths at once — any new fixture must trip exactly one |
| **Justified test changes** | ~2 in `TestBlockClassification` now construct with the Reddit signature set. Recorded in the completion report under **A6** |
| **Rollback point** | Revert; signatures return to `blocks.py` and the fence disappears |
| **Validation** | `pytest tests/test_boundaries.py -v` · `pytest tests/test_net.py -k block -v` · `pytest` |
| **AC satisfied** | **A10** (`src/net/` has zero Reddit identifiers) |

---

## Stage 11 — Documentation and reports

| Field | Value |
|---|---|
| **Purpose** | [35 §2.1](35-testing-strategy.md) check 18 — every documentation edit this phase owns has landed |
| **Files** | [08 §3a/§3.1/§3.4/§7/§10](08-proxy-service.md) ~, [07 §1](07-scraping-pipeline.md) ~, [03 §6 (AD-25) + §8](03-architecture.md) ~, [12 §14](12-phase-02.md) ~, [34 §P4](34-implementation-plan.md) ~ (DELIVERED marker), `CHANGELOG.md` ~, `PHASE-04-COMPLETION-REPORT.md` +, `PHASE-04-HANDOVER.md` +, `progress/P04-COMPLETE.md` +, `testing/P04-testing.md` ~ (corrections if any interface moved) |
| **Est. LOC** | Documentation only |
| **Interfaces affected** | None |
| **Expected tests** | No broken internal link; the completion report states the **measured** baseline and justifies every changed test |
| **Coverage impact** | None |
| **Risks** | Low. The main one is claiming an unverified number — §0 exists to prevent that |
| **Rollback point** | N/A |
| **Validation** | The full gate (§3.1 below) · [P04-testing.md](testing/P04-testing.md) T16 |
| **AC satisfied** | Universal criterion — *documentation edits landed* |

---

## 3.1 The full gate, run at the end of every stage from 7 onward

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest -W error::DeprecationWarning
.\.venv\Scripts\python.exe -m pytest --cov=src/net --cov-report=term      # >= 85%
.\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db     # 25 checks
.\.venv\Scripts\python.exe -m alembic heads                               # exactly one
git diff --stat 8a74b53..HEAD                                             # boundary check, §4
```

Plus, before declaring P4 complete: the migration round-trip on a live-DB copy, GitHub Actions green
on the pushed branch, and [P04-testing.md](testing/P04-testing.md) executed and signed.

---

# 4. Boundary verification

## 4.1 Nothing from P5 is included

| P5 deliverable ([34 §P5](34-implementation-plan.md)) | In P4? | Guard |
|---|---|---|
| `RedditClient.get_feed()` | ❌ | `RedditClient`'s six frozen methods asserted unchanged by introspection ([P04-testing.md](testing/P04-testing.md) T12 Step 6) |
| `src/discovery/feed_parser.py`, `src/discovery/__init__.py` | ❌ | No file under `src/discovery/` is created |
| `if_none_match` / `if_modified_since` / 304 handling on `http_client` | ❌ | **Deliberately excluded.** P4 touches `http_client` in stage 7, which is where this would be tempting. It is P5's, and P0's U4 measurement refuted conditional GET on `.rss` anyway |
| `tests/fixtures/atom/*.xml` | ❌ | No Atom fixture added |
| `discovery.rss_*` config keys | ❌ | Not added to `config.yaml` |
| `x-ratelimit-reset` handling on 429 | ❌ | The existing `Retry-After` handling is untouched |

> ⚠️ **The one thing that could leak.** `rss` is a **request class** in P4's routing table
> ([29 §2.1](29-network-and-proxy-strategy.md)) — a routing label with no consumer until P5. That is
> intended and is required by R18. It must remain a *label*: no feed URL construction, no Atom
> parsing, no rate-limit special-casing may attach to it in P4.

## 4.2 Nothing from P6 is included

| P6 deliverable | In P4? |
|---|---|
| `migrations/versions/0005_discovery.py` | ❌ — **P4 owns no migration.** `alembic heads` stays at one `0004` |
| `discovery_watermarks`, `prescores` | ❌ |
| `src/discovery/{watermarks,policy}.py` | ❌ |
| `src/orchestration/handlers/discover.py` | ❌ |
| Overflow detection, adaptive polling | ❌ |
| Discovery bypassing `http_cache` (D5) | ❌ — `http_cache` behaviour is unchanged in P4 |

## 4.3 Nothing beyond P4 is included

| Later work | In P4? | Note |
|---|---|---|
| `WebsiteFetcher` (P13) | ❌ | The `website` request class ships with **no consumer**. Justified: it is required by R18 and is directly tested from config, so it is config-driven behaviour rather than dead code — and P13 adds a caller, not a routing decision |
| `projects`, `bkb_*`, anything from the legacy "Phase 04" doc | ❌ | Wrong document — see the review's header warning |
| Residential proxy purchase | ❌ | Deferred ([ARCHITECTURE_FREEZE §9](ARCHITECTURE_FREEZE.md)); P0 measured the opposite of its trigger. `managed_gateway` ships with **no live credentials** |
| `PoolCircuitBreaker` rolling-window rewrite ([08 §5](08-proxy-service.md)) | ❌ | [29 §4.4](29-network-and-proxy-strategy.md) says the breaker is unchanged plus an acceptance trigger |
| `COOLDOWN` probation state, per-cause blacklist durations, half-open probe | ❌ | [12 §14](12-phase-02.md) deliberately-not-built; not in P4's task list |
| `RedditClient._get` raising instead of returning `None` (**T5**) | ❌ | The P3 handover says *"P4 is where that changes"*, but [34 §P4](34-implementation-plan.md) authorises none of it and AD-2 freezes the API. **Recorded as a conflict and deferred to P5/P6** |
| Sticky sessions wired to pagination | ❌ | D-F. `session_key` is implemented and plumbed; **no caller passes one** |
| Keyword/user scraping through the queue (**N1**) | ❌ | P3 T1 — explicitly not "fixed" here |
| CI action version bumps (`checkout@v5`, `setup-python@v6`) | ❌ | §0.5 — owned by **P30**. Doing it in P4 is opportunistic scope |
| `mypy` installation / baseline | ❌ | Carried blocker B3/O2 |

## 4.4 Frozen architecture — unchanged

| Item | Status after P4 |
|---|---|
| **Frozen rules R1–R20** | All hold. **R18 is *implemented* for the first time** — P4 is the phase that makes it real rather than aspirational. **R5 is enforced for the first time** (fence 4). No rule is weakened |
| **Decisions AD-1 … AD-31** | Unchanged. **AD-25 is transcribed** into [03 §6](03-architecture.md) from [32 §4](32-documentation-consistency.md) — a transcription, not a new decision (D-E) |
| **Migration chain** | Unchanged. Ten revisions, one head, `0004`. P4 adds none |
| **Technology set ([ARCHITECTURE_FREEZE §5](ARCHITECTURE_FREEZE.md))** | Unchanged. **No package added** — `requirements.txt` must show an empty diff. `requests` already covers the gateway shape |
| **Budgets ([ARCHITECTURE_FREEZE §6](ARCHITECTURE_FREEZE.md))** | Unchanged, and `network.direct.max_requests_per_hour: 120` is now **enforced** rather than merely stated (P-2) |
| **Scope limits ([ARCHITECTURE_FREEZE §7](ARCHITECTURE_FREEZE.md))** | Untouched — no Hermes tool, skill or notification kind |
| **Non-goals ([ARCHITECTURE_FREEZE §8](ARCHITECTURE_FREEZE.md))** | Untouched |
| **Amendment log §11** | **No amendment.** Under D-A option **A1**, not even a §11.1 reconciliation. Under **A2** (a fourth enum value), one §11.1 entry — a documentation inconsistency, not an amendment, since no technology, table or decision changes |

## 4.5 No schema changes · no migrations

- No file under `migrations/` is created or edited.
- `alembic heads` returns exactly one, `0004_orchestration`, before and after.
- `scripts/check_schema.py` reports the **same 25 checks** before and after.
- No SQLAlchemy model gains, loses or retypes a column. `src/db/models.py` is **not in P4's file list**.
- No row is written by the phase itself. `run_events` rows are produced by *running* the tool, exactly as in P3.

## 4.6 No API-breaking changes

| Surface | Change | Breaking? |
|---|---|---|
| The **17 legacy endpoints** | None | ❌ — asserted by `test_the_seventeen_legacy_endpoints_are_all_still_there` and the recorded replay |
| `POST /api/scrape` | None | ❌ — P3's G5 contract replay unchanged |
| `GET /` | None | ❌ — byte-identical assertion |
| CSV export | None | ❌ — 13 columns |
| `GET /api/health/proxies` | **Additive only**; `fail_closed` retained as a derived alias | ❌ — and it is not one of the 17 |
| `GET /api/health` | `proxies` summary unchanged in shape | ❌ |
| `RedditClient` public API | None | ❌ — AD-2; introspection test |
| `ProxiedHTTPClient.get` | Two keyword arguments **with defaults** | ❌ |
| `ProxyManager.acquire` | Two keyword arguments **with defaults** | ❌ |
| `build_scraper(config)` | None | ❌ — P3 G3/T2; ~12 tests patch it by name |
| `blocks.classify` | One keyword argument **with a default** | ❌ |

## 4.7 No unintended behaviour changes

Three behaviour changes are **intended** and each is documented, defaulted and reversible:

| # | Change | Intended? | Where it is recorded |
|---|---|---|---|
| 1 | Bulk HTML now prefers **direct** over the datacenter pool | ✅ Yes — P0's measured result, D-A | `config.yaml` comment, [08 §7](08-proxy-service.md), completion report, T5/T6 |
| 2 | An exhausted pool **degrades** instead of stopping | ✅ Yes — the phase's objective | Warning on `/runs/<id>`, `config.yaml`, T7/T8 |
| 3 | The health page now reflects **scraper** traffic, because the page and the scraper finally share a pool (RK-10) | ✅ Yes — a side effect of P-2, and an improvement | Completion report + T11 |

Everything else must be behaviour-identical. The guard is `pytest tests/test_net.py` compared
line-by-line against the §0 baseline at stage 7, plus the legacy contract at every stage.

---

# 5. Risk review — P3's critical risks, re-verified against P4

## 5.1 Long-running SQLite write locks · dirty sessions across network I/O

**The risk.** P3's **F7**: `handle_scrape_subreddit` left its session dirty and handed it to a scrape
that spends minutes on the network; the scraper's first query autoflushed, taking SQLite's single
write lock, and every other writer waited out `busy_timeout` and failed. Cancelling a run returned
HTTP 500. **P4 adds a new write inside that same window.**

**Why it cannot happen.**

1. **Structurally, by choice of design.** Under D-C option **C1**, the degradation write happens
   **after `scraper.run()` returns** — outside the network window entirely. There is no new write
   inside the window at all. This is C1's principal advantage over C2 and the reason it is
   recommended.
2. **The existing fix is untouched.** The `session.commit()` before `build_scraper()`, and the
   comment block explaining it, are not modified by any stage. Stage 7 changes only what
   `build_scraper` constructs, which is P3's G3 seam and its documented purpose.
3. **`src/net/` holds no session.** `NetworkPolicy` returns `DegradationNotice` value objects. The
   network layer cannot take a database lock because it cannot reach the database.

**The regression tests that guarantee it.**

| Test | Asserts | Mutation that must break it |
|---|---|---|
| `test_handlers_scrape.py` (existing) | The session is clean at the moment the scrape starts | Remove the pre-scrape commit |
| `test_handlers_scrape.py` (**new**, stage 9) | The session is clean **after a scrape that degraded** | Move the drain loop before `scraper.run()` |
| Cancel-during-degrading-scrape (**new**, stage 9) | Cancel returns 200 while a second connection holds a query | Same |
| [P04-testing.md](testing/P04-testing.md) **T14** | Manual cancel at three moments, including as the warning appears | — |

**The double is specified, not left to judgement** (P3's F4/F7 lesson, learned twice): the fake
scraper must **query the database** so autoflush fires, **and** must cause a degradation while it
runs. A fake that does neither passes trivially and proves nothing — which is precisely how F7
survived 583 green tests.

## 5.2 Concurrency regressions

**The risk.** P2's claim-under-contention guarantee (`BEGIN IMMEDIATE` + `AND state='queued'`), the
10-minute soak with zero `database is locked`, and the lease/heartbeat machinery.

**Why it cannot happen.** P4 touches **no** file under `src/orchestration/` except
`handlers/scrape.py`, and there only the construction line and a post-scrape drain loop. `JobQueue`,
`Worker`, `RunService` and `states.py` are not in P4's file list. No new thread is created: providers
are constructed on the calling thread, and the only shared mutable state P4 adds is the
process-wide policy — which reuses `ProxyManager`'s existing `threading.RLock` discipline.

**Guaranteed by.** `pytest tests/test_job_queue.py tests/test_worker.py tests/test_concurrency_soak.py`
green at every stage; the 20-second soak in the suite, and `SOAK_SECONDS=600` before sign-off. New
shared state (the governor counter, the acceptance window) is guarded by the same lock as the pool
statistics it sits beside, and a test exercises concurrent `acquire()` across threads.

## 5.3 Duplicate work

**The risk.** P3's **F1** — `retry()` enqueued a fresh set of jobs beside ones still queued, doubling
the work. Found by the first run of a new test file, not by review.

**Why it cannot happen.** P4 adds no enqueue path, no retry path and no job type. `_is_last_scrape_job`
and the finalise-enqueue logic are untouched. The one new loop (draining notices) writes `run_events`
rows, which are append-only telemetry with no scheduling effect.

**Guaranteed by.** `tests/test_run_service.py` (retry paths) and `tests/test_job_queue.py` green at
every stage. R9 idempotence is unaffected: a re-run scrape still writes no duplicate lead, and a
re-run that degrades again re-emits its notice, which is correct — the second attempt genuinely did
degrade.

## 5.4 Transaction leaks

**The risk.** A session opened and not closed, or a transaction left open across a stage boundary.

**Why it cannot happen.** Under **C1**, P4 opens **no session anywhere**. The handler's session is
the one P3 already gave it; the drain loop calls `emit_event`, which *adds* rows and lets the caller
commit — G1 preserved exactly. `src/net/` has no ORM import at all.

> This is the concrete reason C1 was preferred over C2 on this axis: C2 introduces a session factory
> into the seam and a second short-lived transaction during the scrape. Both are manageable, but
> "no new session" is a stronger guarantee than "a new session we believe is short."

**Guaranteed by.** The clean-session assertions in §5.1; a boundary test that no module under
`src/net/` imports `src.db`; and the existing `session_scope` discipline, unchanged.

## 5.5 Credential leakage

**The risk.** R15 — *secrets never enter the database, a log, an API response, a template, or the
repository.* **P4 opens a new credential path**: `managed_gateway` takes its username and password
from configuration and environment, not from the proxy file around which the four existing
guarantees were built. P3's **F3** is the standing lesson here — redaction is a property of *every
write to an operator-visible sink*, and the third such sink was found one phase after the second.

**How it is prevented.**

| Sink | Mechanism |
|---|---|
| Logs | `RedactingFilter` (P2), extended with the gateway credential shape; full-log grep across a representative workload |
| Database | No P4 code writes a credential anywhere. `run_events` messages carry **provider labels** (`host:port` / provider name), and `emit_event` redacts on write |
| API responses | Provider `to_dict()` returns label and type only; the credential scan is extended to `/api/health/proxies` with a gateway configured |
| Templates | The health page renders the same label-only rows; view-source check in T10 Step 4 |
| Repository | `git grep` for both fixture secrets; gateway credentials live in `${ENV}` interpolation, never literal YAML |

**Guaranteed by.** `TestCredentialsNeverLeak` extended with a gateway fixture carrying a known
password; the stage-5 mutation (return the credentialled URL from `to_dict()` → the scan must fail);
and [P04-testing.md](testing/P04-testing.md) **T10**, which searches six surfaces for two distinct
planted secrets and is a blocking sign-off test.

## 5.6 Provider state inconsistencies

**The risk, and it is P4's own.** Four sources of provider state that could disagree: the pool's
per-proxy statistics, the acceptance window, the hourly governor, and the bandwidth counter. If any
two are computed from different objects, the health page tells the operator one thing while the
scraper does another.

**How it is prevented.**

1. **One policy per process (P-2).** This is the structural fix. Today `dashboard/app.py` holds a
   `_proxy_manager` singleton and each scrape job builds its *own* `ProxyManager` — so the health
   page has never reflected scraper traffic. Stage 7 makes both resolve the same policy. RK-10
   records the visible consequence.
2. **One writer per counter.** Acceptance and pool statistics are written only by
   `record_success`/`record_failure` under `ProxyManager`'s existing `RLock`. The governor and the
   bandwidth counter are written only by `DirectProvider.release` and
   `ManagedProxyProvider.release`, each under its own lock.
3. **`health()` is derived, never cached.** A provider computes health from its counters at call
   time, so there is no second copy to fall out of date.
4. **Neutral-at-zero acceptance (P-3).** A rate of `0.0` at zero samples would make one success pin
   the pool to one exit; acceptance is neutral below a sample floor.
5. **Cooldown floor (P-1).** Without it, at 0 healthy the cooldown collapses to zero, every
   blacklisted proxy is instantly usable, `ProxyExhaustedError` becomes unreachable and the ladder
   silently never fires — the state the page would report as "pool fine" while nothing works.

**Guaranteed by.** The stage-2 mutations (floor → 0, and acceptance influencing selection at n=0);
the stage-7 shared-governor test; T9 Step 5 in the manual guide (the counter is shared across the
whole run, not reset per subreddit); and T11 Step 3 (the page shows acceptance for real traffic).

## 5.7 Risk summary

| Risk | Verdict |
|---|---|
| Long-running SQLite write locks | **Cannot happen** — no write inside the network window (C1) |
| Dirty session across network I/O | **Cannot happen** — the pre-scrape commit is untouched; the drain is after the return |
| Concurrency regression | **Prevented** — no orchestration file touched; new shared state under the existing lock |
| Duplicate work | **Cannot happen** — no enqueue, retry or job-type path added |
| Transaction leak | **Cannot happen** — P4 opens no session; `src/net/` has no ORM import |
| Credential leakage | **Prevented** — new gateway path explicitly covered by test, mutation and manual scan |
| Provider state inconsistency | **Prevented** — one policy per process, one writer per counter, derived health, plus the P-1/P-3 corrections |

---

# 6. Sign-off — before stage 1

| # | Gate | Status |
|---|---|---|
| 1 | P3 GitHub Actions green on the P3 tip | ✅ §0 — run 31204648730, `8a74b53`, success |
| 2 | `docs/testing/P04-testing.md` written before implementation | ✅ |
| 3 | Decision analysis for D-A, D-B, D-C | ✅ [P4-DECISION-ANALYSIS.md](P4-DECISION-ANALYSIS.md) |
| 4 | Implementation stages expanded | ✅ §3 |
| 5 | Boundary verification | ✅ §4 |
| 6 | Risk review against P3's critical defects | ✅ §5 |
| 7 | **D-A answered** | ⬜ awaiting |
| 8 | **D-B answered** | ⬜ awaiting |
| 9 | **D-C answered** | ⬜ awaiting |
| 10 | D-D, D-E, D-F confirmed or overridden | ⬜ awaiting |
| 11 | **Explicit approval to write production code** | ⬜ awaiting |

**No file under `src/` will be modified until items 7–11 are ticked.**
