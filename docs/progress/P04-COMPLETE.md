# P04 — COMPLETE

**Phase name:** P4 — Network provider abstraction (Stage C — Collection)
**Plan:** [34-implementation-plan.md §P4](../34-implementation-plan.md)
**Completion date:** 2026-08-08
**Companions:** [PHASE-04-COMPLETION-REPORT.md](../PHASE-04-COMPLETION-REPORT.md) ·
[PHASE-04-HANDOVER.md](../PHASE-04-HANDOVER.md) · [testing/P04-testing.md](../testing/P04-testing.md)

> ⚠️ **P4 of the frozen P0–P30 plan — NOT the legacy "Phase 04."**
> [`14-phase-04.md`](../14-phase-04.md) is the Business Knowledge Base and maps to **P12–P16**.
> The two schemes are unrelated.

---

## Objective

> *"Egress is a policy chosen per request class, with a degradation ladder — not a mandate."*

**Met.** Stage C opens. Before P4, every request went through the proxy pool and a dead pool stopped
the run. Now the request's **class** chooses the path, a configured **ladder** decides the order, and
an exhausted ladder degrades — visibly, and under a hard cap on the operator's own address.

This is the first phase to act on a P0 measurement: direct **100% success / 0% blocks** against the
datacenter pool's **71.4% / 28.6%**, reproduced twice. Nothing was purchased.

---

## Files changed

**Twenty-nine files outside the P4 planning documents: ten new, nineteen modified.**
Verified with `git diff --name-status 8a74b53..HEAD`.

### New — source (8)

| File | Purpose |
|---|---|
| `src/net/providers/__init__.py` | Package exports |
| `src/net/providers/base.py` | `NetworkProvider` ABC, `Lease`, `Outcome`, `ProviderHealth`, `Capacity`, `Rotation`, `ProviderUnavailable` |
| `src/net/providers/direct.py` | `DirectProvider` — pinned header profile, rolling hourly governor |
| `src/net/providers/managed_list.py` | `WebshareDatacenterProvider` — adapts the shipped `ProxyManager` |
| `src/net/providers/managed_gateway.py` | `ManagedProxyProvider` — one class for every managed vendor |
| `src/net/providers/null.py` | `NullProvider` |
| `src/net/providers/registry.py` | `build_provider()`, `${ENV}` resolution, readable config errors |
| `src/net/policy.py` | `NetworkPolicy`, `RequestClass`, `ALWAYS_DIRECT`, `DegradationNotice`, `EgressExhausted`, config builders |
| `src/net/egress.py` | The process-wide policy |

### New — tests (2)

`tests/test_network_policy.py` (47 tests) · `tests/test_net_providers.py` (38 tests)

### Modified — source and configuration (9)

| File | Change |
|---|---|
| `src/net/http_client.py` | One loop, through the policy; `request_class=`, `session_key=`; `bytes_in` reported; `block_signatures` |
| `src/net/proxy_manager.py` | Target acceptance; `exclude=`; pressure-scaled cooldown **with a floor**; `usable_count`; acceptance circuit trigger |
| `src/net/blocks.py` | `BlockSignatures` — generic markers stay, target-specific are injected |
| `src/net/user_agents.py` | `headers_for_profile()` — extends a *known* profile rather than picking a random one |
| `src/net/__init__.py` | Exports the P4 surface |
| `src/reddit_client.py` | `REDDIT_SIGNATURES`; transport built from the process-wide policy. **Public API unchanged** |
| `src/dashboard/app.py` | `get_network_policy()`; `get_proxy_manager()` is now a view onto it |
| `src/dashboard/routes_health.py` | `/api/health/proxies` gains policy, ladder, providers, routing, direct counter; `fail_closed` derived |
| `src/dashboard/templates/health_proxies.html` | Egress policy card, provider table, routing table, acceptance column |
| `src/orchestration/handlers/scrape.py` | Drains degradation notices **after** the scrape; run-scoped dedup |
| `config.yaml` | `network:` block, fully commented; `proxy:` retained as the fallback |

### Modified — tests (3)

`tests/test_boundaries.py` (fence 4) · `tests/test_net.py` (acceptance, exclusion, cooldown floor,
signature wiring) · `tests/test_handlers_scrape.py` (degradation, F7 guards)

### Modified — documentation (5)

`docs/03-architecture.md` (AD-25, technology row) · `docs/07-scraping-pipeline.md` §1 ·
`docs/08-proxy-service.md` §3a/§3.1/§7/§10 · `docs/12-phase-02.md` §14 · `CHANGELOG.md`

**No migration. No schema change. No new dependency.**

---

## Verification

| Check | Result |
|---|---|
| `pytest` | **695 passed, 2 skipped** (baseline 583 / 2) |
| `pytest -W error::DeprecationWarning` | **695 passed, 2 skipped** |
| `ruff check .` / `ruff format --check .` | All checks passed! / 101 files already formatted |
| `scripts/check_schema.py` | OK — all 25 checks passed |
| `alembic heads` | One — `0004_orchestration` |
| Coverage, `src/net/` | **91%** (was 85%) |
| Grep fences | 4 of 4 — **fence 4 for the first time** |
| Mutation testing | 7 mutations, 7 detected |
| Legacy contract | 459 baseline leads · `GET /` byte-identical · 13 CSV columns · 17 endpoints |

---

## Defects found

Seven, in [PHASE-04-COMPLETION-REPORT §5](../PHASE-04-COMPLETION-REPORT.md). Three were **pre-existing**
(fence 4 absent; the random-profile `Referer` bug; `exclude=tried` untested) and four were introduced
and caught during the phase. Three of the seven mutations were **undetected on the first attempt** —
each gap became a test that has been observed to fail.

---

## Resume point

**P4 is code-complete and documented. It is NOT signed off.**

The next action is **manual testing**: execute [testing/P04-testing.md](../testing/P04-testing.md)
and sign its table. Sixteen tests, ~75 minutes; six are marked blocking (**T5** R18, **T7**
degradation visible, **T10** credentials, **T12** fences and contract, **T13** rollback, **T14**
cancel-during-scrape must not return HTTP 500).

Until that table is signed:

- **do not tag** — [EXECUTION_MODE_LOCK §6.2](../EXECUTION_MODE_LOCK.md) forbids tagging a phase
  whose sign-off table is blank;
- **do not start P5** — the gate between phases is the quality mechanism.

**If this session was interrupted before commit:** the working tree holds the whole phase; run
`git status --short` against the file list above. The last verified state is the table in
*Verification*, reproducible with `ruff check . && ruff format --check . && pytest`.

**When P5 begins:** read [PHASE-04-HANDOVER.md](../PHASE-04-HANDOVER.md) first — seven guarantees,
six traps, and seven findings, of which **T0** (never hold the SQLite write lock across I/O) and
**T1** (`RedditClient._get` still swallows, and it now costs something visible) are the two that
will bite.
