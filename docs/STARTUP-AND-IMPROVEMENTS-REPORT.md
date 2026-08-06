# Startup Audit & Improvement Pass — 2026-07-31

---

## 1. Root cause of the startup failure

**There is no startup failure in the application.** `pnpm run dev` and
`npm run dev` fail because **this project has no Node.js layer** — and never has.

### Evidence

Exhaustive check of the repository tree:

| Artefact | Present? |
|---|---|
| `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `yarn.lock`, `bun.lockb` | ❌ none |
| `tsconfig*.json`, `jsconfig.json` | ❌ none |
| `vite.config.*`, `next.config.js`, `webpack.config.js`, `rollup.config.js` | ❌ none |
| `.npmrc`, `.nvmrc`, `turbo.json`, `nx.json` | ❌ none |
| `node_modules/` anywhere | ❌ none |
| Any `.ts`, `.tsx`, `.jsx`, `.vue`, `.svelte` file anywhere | ❌ none |

Node, npm and pnpm *are* installed on this machine (v24.11.1 / 11.4.2 / 11.1.3),
so the tools ran and reported honestly:

```
$ pnpm run dev
[ERR_PNPM_NO_PKG_MANIFEST] No package.json found in <project root>

$ npm run dev
npm error code ENOENT
npm error path <project root>\package.json
npm error enoent Could not read package.json
```

**This is a category error, not a defect.** The project is Python 3.12 + Flask +
SQLAlchemy + Alembic. The dashboard is server-rendered Jinja with inline CSS/JS
and Chart.js from a CDN — a deliberate decision recorded in
[09 §1](09-dashboard-plan.md) before any code was written:

> **No build step.** Server-rendered Jinja, inline CSS/JS, Chart.js from CDN.
> Adding npm/webpack would cost more than it returns for a single-operator tool.

Every item on the requested audit list was checked. The Python-side equivalents
(`config.yaml`, environment loading, imports, entry points, database
initialisation, provider initialisation, settings resolution, AI service
startup, routing, dev-server configuration) were all verified working — see §3.

## 2. How it was fixed

Nothing in the application needed fixing. Three things were added so the next
person does not lose the same hour:

1. **`README.md` rewritten**, opening with the exact two error messages and the
   commands that actually work. It states plainly that **npm and pnpm are not
   supported and are not intended to be**, with the reason and a link to the
   decision.
2. **`dev.py`** — `python dev.py` is now an alias for `python main.py dashboard`,
   with a preflight that turns the common setup mistakes into sentences:
   wrong Python version, missing dependencies (named individually), missing
   `config.yaml`, missing `.env` (a warning, not a failure — everything except
   AI works without it).
3. **No `package.json` shim was added.** A manifest whose only job is to shell
   out to Python would put a Node dependency, a lockfile and a `node_modules`
   directory into a Python project to serve a habit rather than a requirement,
   and would contradict a documented architectural decision.

### Command mapping

| Habit | This project |
|---|---|
| `pnpm install` / `npm install` | `python -m pip install -r requirements.txt` |
| `pnpm run dev` / `npm run dev` | `python main.py dashboard` (or `python dev.py`) |
| `npm run build` | *n/a — there is no build step* |
| `npm test` | `python -m pytest tests/ -q` |
| `npm run lint` | `python -m ruff check .` |

## 3. Startup verification

Verified against a **real HTTP server** on port 5000, not the Flask test client.

```
+-----------------------------------------------------------------------------+
| Dashboard running at http://127.0.0.1:5000                                  |
+-----------------------------------------------------------------------------+
Migrations      up to date (0002_ai_infrastructure)
AI provider     openrouter - deepseek/deepseek-v4-flash - valid
 * Serving Flask app 'src.dashboard.app'
```

| Check | Result |
|---|---|
| Application boots | ✅ no exceptions in the startup log (grep count: 0) |
| Dashboard loads | ✅ `GET /` 200, **byte-identical** to the pre-Phase-1 baseline |
| Settings page | ✅ `GET /settings/ai` 200; six status states render |
| Database initialises | ✅ 459 leads, `intent_score` SHA-256 unchanged |
| Migrations | ✅ `0002_ai_infrastructure`, single head, up to date |
| AI provider initialises | ✅ `openrouter` / `deepseek-v4-flash` / `valid` |
| Live connection test | ✅ `POST /api/settings/ai/test` → ok, 2,442 ms |
| Routing | ✅ **13/13 endpoints 200** (list below) |
| Health endpoints | ✅ `/health`, `/health/ai`, `/api/health`, `/api/health/ai`, `/api/health/providers` |
| CLI entry points | ✅ `--help`, `migrate status`, `ai status`, `ai test` |
| Scraper imports | ✅ all three scrapers + `RedditClient` |
| Ruff | ✅ clean |
| Tests | ✅ **109 passed**, 87% coverage on `src/ai` |
| CSV export | ✅ 13 columns, unchanged |

Endpoints verified: `/`, `/settings/ai`, `/health`, `/health/ai`, `/api/health`,
`/api/health/ai`, `/api/health/providers`, `/api/settings/ai`,
`/api/settings/ai/providers`, `/api/ai/usage`, `/api/leads`,
`/api/leads/export`, `/api/stats`.

**Background workers:** none exist yet. The worker and job queue are Phase 3
([13-phase-03.md](13-phase-03.md)). **Proxy service:** none yet — Phase 2. Both
are correctly absent, not silently broken.

### One real defect found during verification

`/api/health/providers` returned 404 on a running server while returning 200 in
the test client. Cause: a stale `python main.py dashboard` process still bound to
port 5000. `pkill` does not reach Windows Python processes from Git Bash; the
process had to be killed via `Stop-Process`. Worth knowing — an apparently
"unregistered route" on Windows is usually a zombie server, and chasing it as a
routing bug would waste time.

---

## 4. Research findings

### Provider management

Sources converge on four points, and the existing abstraction already satisfied
the first:

1. **Never branch on provider names.** *"Your application shouldn't branch on
   provider names — every new provider becomes a refactor. Adding a provider
   should require touching only the model string."* Already enforced by an
   AST-level test (`test_no_vendor_coupling_outside_providers`).
2. **Circuit breaking per provider**, with a half-open probe state.
3. **Fallback chains**, not load balancing, for failure.
4. **Track cost and latency per provider in real time.**

Circuit-breaker specifics: `CLOSED → OPEN` on N consecutive failures, cooldown,
then `HALF_OPEN` admitting limited probes; a failed probe re-opens immediately.

### What the research did *not* justify

- **Load balancing across providers.** Spreading traffic destroys prefix-cache
  locality, which is the largest cost lever in this system. Failover only.
- **A gateway/proxy layer (LiteLLM etc.).** We already have the abstraction it
  would provide, and OpenRouter *is* a gateway — adding another would mean two.

Sources: [Multi-provider LLM orchestration 2026](https://dev.to/ash_dubai/multi-provider-llm-orchestration-in-production-a-2026-guide-1g10),
[Kong — switching providers without downtime](https://konghq.com/blog/enterprise/how-to-switch-llm-providers-without-downtime),
[LLM fallback strategies](https://www.buildmvpfast.com/blog/llm-fallback-strategies-primary-model-secondary-model-2026),
[pybreaker](https://github.com/danielfm/pybreaker),
[Circuit breakers in Python](https://oneuptime.com/blog/post/2026-01-23-python-circuit-breakers/view).

---

## 5. Implemented improvements

### ✅ Improvement 1 — Provider management (complete)

| Capability | Implementation |
|---|---|
| DeepSeek provider | ✅ existing |
| OpenRouter provider | ✅ added (previous session), live-verified |
| OpenAI provider | ✅ added — genuine ~30-line subclass |
| Anthropic / Gemini | ⛔ **deliberately not written** — see trade-offs |
| Provider selection from Settings | ✅ `ai.provider` now read at service construction |
| Provider health status | ✅ `ProviderHealth` — circuit state, failure rate, latency |
| Connection testing | ✅ existing, live-verified |
| Provider capabilities | ✅ four flags per provider, surfaced in the comparison |
| Latency metrics | ✅ mean + p95 per provider |
| Estimated cost | ✅ `/api/health/providers` prices the same workload on each |
| Graceful fallback | ✅ `ProviderRouter` with an ordered chain |

**New files:** `providers/health.py`, `providers/router.py`, `providers/openai.py`.
**New endpoint:** `GET /api/health/providers`.
**New tests:** 22, all passing.

The failover rule is the part worth stating: **only faults that a different
provider could plausibly fix trigger failover** — timeouts, 5xx, connection
errors. A 401, 402 or schema violation reproduces everywhere, so failing over on
one would burn every configured key in sequence against the same bad request.
Tested explicitly.

Live cost comparison for 1,000 items:

```
  deepseek     $0.1498 warm   $0.6300 cold   cache=50x  schema=False  verified 2026-07-30
* openrouter   $0.2380 warm   $0.6300 cold   cache=5x   schema=False  verified 2026-07-31
  openai       $0.4875 warm   $0.7500 cold   cache=2x   schema=True   verified UNVERIFIED
```

### ⚠️ Improvement 4 — Quality monitoring (Phase-1 half done)

| Metric | Status |
|---|---|
| Provider latency (mean, p95) | ✅ per provider |
| Provider failures + failure rate | ✅ per provider |
| Provider health / circuit state | ✅ |
| Token usage | ✅ cached/uncached split |
| Estimated cost | ✅ + provider-reported actual |
| Cache hit ratio | ✅ (0% on OpenRouter — telemetry gap, documented) |
| Batch efficiency | ✅ calls, repairs, truncation |
| Precision · false positives · false negatives | ⛔ needs labelled leads — Phase 8 |
| Holdout audit | ⛔ needs the gate and enrichment — Phase 7 |
| Confidence calibration | ⛔ needs scored leads — Phase 8 |

### ✅ Improvement 6 — Project architecture (research: already correct)

**No change needed. The design is already project-centric**, and was decided
deliberately — [05 §2](05-database-plan.md) is titled *"The single biggest
decision: project scoping"*:

> One website URL owns one project, and a project owns its own profile, ICP,
> personas, subreddits, keywords, runs, leads, and comments.

The planned hierarchy already matches the one proposed, with **one difference**:

| Proposed | Planned | Assessment |
|---|---|---|
| Project → …→ **Websites** (plural) | Project ↔ **one** website | Deliberate. One project = one business. Multiple websites per project only helps an agency managing several clients under one account, which is explicitly a non-goal for an internal tool. Changing it would make `bkb.project_id` ambiguous — which site's facts win? |

Everything else in the proposal — Business Knowledge, Keywords, Subreddits,
Monitoring, Leads, History, Learning, Settings — is already project-scoped in the
schema plan. **Recommendation: no change.** Revisit only if this becomes a
multi-tenant product, which is currently a stated non-goal.

### ⛔ Improvements 2, 3, 5 — designed, blocked on earlier phases

These operate on tables that do not exist yet. They are fully designed; nothing
is missing but the substrate.

| # | Improvement | Blocked on | Design |
|---|---|---|---|
| 2 | Knowledge-Base evolution | **Phase 4** — no `bkb` table exists | [06h §4](06h-knowledge-lifecycle.md) — aggregate-only (≥3 occurrences, ≥2 dedup groups), operator-gated, `origin` guard so website facts are never overwritten |
| 3 | Learning layer | **Phase 7/8** — no `lead_analysis` or `lead_labels` | [06i §2](06i-feedback-and-memory.md) — labels + reasons → ranking weights, calibration, knowledge suggestions. **No online training**, and the arithmetic for why is recorded |
| 5 | Explainability | **Phase 7** — no analyses to explain | [06g Part I](06g-explainability-and-quality.md) — ten fields incl. matched ICP/persona/pain/feature/competitor/terminology, evidence, and pinned BKB version |

Every question the improvement brief asks — *"Do NOT overwrite website facts"*,
*"Do NOT implement online model training"*, *"Which Business Knowledge version
was used"* — is already answered in those designs, by the `origin` write-path
guard, the deterministic-weights decision, and `lead_analysis.bkb_id`
respectively.

**Implementing them now would mean writing code against tables that do not
exist.** The honest sequencing is Phase 2 → 3 → 4, at which point Improvement 2
becomes buildable; Phase 7 unblocks 3 and 5.

---

## 6. Trade-offs

**No `package.json` shim.** Rejected: it would add a Node dependency to a Python
project purely for muscle memory, and contradict a documented decision. The cost
is that `npm run dev` still fails — now with a README that explains why in its
first paragraph.

**Anthropic and Gemini providers not written.** Both use a different request and
response shape, so each is a genuine implementation of `LLMProvider`, not a
subclass of `OpenAICompatibleProvider`. Writing them with no key to test against
would produce code that looks finished and has never executed. The abstraction
supports them; that is a different claim from having them, and conflating the two
is how a provider list becomes a list of things that break on first use.

**OpenAI pricing is unverified.** No OpenAI key was available. The figures are
published rates entered by hand, and the registry carries
`pricing_verified_on: "unverified"` so the Settings page and the cost comparison
both show it as unconfirmed rather than presenting a guess as a measurement.

**Failover retries the whole batch, not the failed half.** Two providers'
categorical judgements are not calibrated against each other; mixing them within
one batch would make confidence scores incomparable between leads in the same
run. Costs a little duplicated work on a rare path, protects the property the
whole scoring model rests on.

**The circuit breaker is per-process.** It resets on restart. Persisting it would
mean a provider that failed overnight starts the morning still open, which is
usually wrong. Accepted deliberately.

---

## 7. Remaining technical debt

| Item | Impact | When |
|---|---|---|
| **AC14 cache telemetry is 0% on OpenRouter** | `/health/ai` shows a misleading 0% cache ratio. Cost figures are correct (provider-reported), but the *cache health signal* is blind. | Fixed by switching to DeepSeek direct, or by OpenRouter populating `cached_tokens` |
| **OpenAI pricing unverified** | Cost comparison may be wrong for OpenAI | Needs an OpenAI key |
| **Latency ~12.8 s/call via OpenRouter** | Phase-7 target (1,000 items < 2 min) unreachable without more concurrency | Measure DeepSeek direct before treating as real |
| **AC9 not machine-enforced** | Suite is offline today, but a live call added later would still pass | ~10-line socket-blocking autouse fixture |
| **33 ruff findings in pre-Phase-1 modules** | Suppressed via `per-file-ignores`, each with the phase that removes it | Phases 2 and 6 |
| **No worker / proxy service** | Not debt — Phases 2 and 3 | As planned |

---

## 8. Production readiness

**Ready for continued development. Not ready for production use** — which is
correct at 14% of the roadmap.

| Dimension | State |
|---|---|
| Starts reliably | ✅ verified against a real server |
| Schema safety | ✅ auto-backup, tested downgrade, single head, 459 rows preserved across every run |
| Secrets | ✅ encrypted at rest, never returned by any endpoint, redaction filter, grep-tested |
| Provider resilience | ✅ circuit breaker, failover, health surfaced |
| Cost controls | ✅ per-run/day/call ceilings, checked pre-call, daily spend survives restart |
| Observability | ✅ `ai_calls` ledger, `/health/ai`, `/health/providers` |
| Test coverage | ✅ 109 tests, 87% on `src/ai`, fully offline |
| Functional completeness | ⚠️ **Phase 1 of 8.** No website analysis, discovery, scraping pipeline, enrichment or scoring yet |

---

## 9. Recommendations before Phase 2

1. **Rotate the OpenRouter key.** It was pasted into a chat transcript. It is
   valid and has spend attached.
2. **Decide DeepSeek direct vs OpenRouter, and record it.** Direct is ~37%
   cheaper on a warm cache (10× cheaper cached input), has working cache
   telemetry, and is likely lower latency. OpenRouter buys model breadth and a
   single key. This changes the cost model in [06d](06d-ai-budget-and-scale.md),
   which is written against DeepSeek direct.
3. **Measure DeepSeek-direct latency before Phase 7.** If 12.8 s is the gateway
   rather than the model, the throughput targets stand; if not, they need
   revising while it is still cheap to revise them.
4. **Take Phase 2 next, as planned.** The proxy service is the only thing
   blocking real scraping, and Phase 4's website fetcher depends on it.
5. **Add the socket-blocking fixture** if the offline-test guarantee matters
   going forward. Ten lines, closes AC9 permanently.
