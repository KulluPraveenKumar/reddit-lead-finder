# Phase 01 — AI Foundation & DeepSeek V4 Flash Integration

**Completion after this phase: 14%**

## 1. Objective

Build the **AI Service Layer** — a provider-agnostic, production-grade AI platform with DeepSeek V4
Flash as its first provider — together with the migration foundation it needs and the Settings page
through which the operator configures it.

At the end of this phase the application can talk to DeepSeek safely, observably, and cheaply. It has
nothing to analyse yet; that arrives in Phase 4. What matters is that **the provider boundary is
correct from the first line of AI code**, so no DeepSeek specific ever leaks into business logic.

## 2. Scope

### 2.1 In scope

**Migration foundation** (the minimum the AI layer needs)
- Alembic setup, `MigrationRunner`, auto-detect / auto-stamp / auto-backup
- SQLite pragmas: WAL, `busy_timeout`, `synchronous=NORMAL`, `foreign_keys=ON`
- `session_scope()`; `check_same_thread=False`; `expire_on_commit=False`
- Revisions `0001_baseline` (stamped) and `0002_ai_infrastructure`

**AI Service Layer** (`src/ai/`)
- `AIService` with its **4 model-invoking methods** (stubs that Phase 4 and 7 fill)
- `PreAIGate` skeleton — the only path to the service; rules land in Phase 6
- `LLMProvider` ABC + `ChatRequest` / `ChatResponse` + capability flags
- `OpenAICompatibleProvider` base; `DeepSeekProvider`; `FakeProvider`
- `PromptManager` — versioned templates, rendering, content hashing
- `ContextBuilder` — the frozen, chunk-aligned prefix
- `ResponseRepairer` — the three-branch ladder
- `ResponseCache` + content-hash dedup + in-flight guard
- `ConcurrencyPool` — bounded, adaptive
- `RateLimiter`, `RetryPolicy`, `CostTracker`, `AIMetrics`
- `CredentialStore` — Fernet encryption, validation, fingerprints
- Full error hierarchy with **401 and 402 as distinct product states**
- **4 prompt templates** at `v1` with the six mandatory sections (+ Batch Contract)

**Settings & observability**
- `/settings/ai` — key entry, Test Connection, six status states, usage, caps, advanced config
- `/health/ai` — cost, tokens, cache-hit ratio, repair rate, latency, concurrency
- Structured logging with redaction

**Tooling**
- `ruff`, `pytest`, `python-dotenv`, `.env.example`, `.gitignore`, `pyproject.toml`

### 2.2 Out of scope

- Website crawling (Phase 4 — needs the proxied client from Phase 2)
- Any actual AI *content* generation — the stage methods exist and are tested against
  `FakeProvider`, but no prompt is exercised against real business data until Phase 4
- Proxy service (Phase 2), orchestration (Phase 3)
- `projects` / `runs` / `leads` schema changes

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  /settings/ai   ·   /health/ai        (Flask blueprints)             │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────┐
│  AIService — 4 model methods, ONE internal _call()                   │
│                                                                      │
│   _call(stage, context, variables, output_model, max_tokens)         │
│     ├─ PromptManager.render()      → system (FROZEN) + user (varies) │
│     ├─ ResponseCache.get(key)      → hit? return, $0.00              │
│     ├─ DedupeGuard.guard(key)      → collapse concurrent identicals   │
│     ├─ CostTracker.check_budget()  → BEFORE the call, never after    │
│     ├─ RateLimiter.acquire()                                         │
│     ├─ provider.chat()  ──┐                                          │
│     │    └─ transport retry: 429/500/503/timeout → backoff           │
│     │       401 → InvalidAPIKeyError    402 → InsufficientBalance     │
│     ├─ ResponseRepairer.evaluate()                                   │
│     │    ├─ empty content   → perturb prompt, retry ≤2               │
│     │    ├─ invalid JSON    → strip fences, append error, retry ≤2   │
│     │    └─ schema violation→ append field error, retry ≤2           │
│     ├─ post-validate: verbatim evidence · slug allow-list            │
│     ├─ ResponseCache.put()                                           │
│     └─ ai_calls row + AIMetrics                                      │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ LLMProvider (ABC)
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
  DeepSeekProvider   OpenAICompatible      FakeProvider
  ★ v4-flash         Provider (base)       (the whole suite runs on this)
```

Design detail in [06a](06a-ai-service-layer.md) and [06b](06b-deepseek-optimization.md).

## 4. Files affected

**New — migration foundation**

| File | Purpose |
|---|---|
| `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako` | Alembic |
| `migrations/versions/0001_baseline.py` | The 8 existing tables, hand-written |
| `migrations/versions/0002_ai_infrastructure.py` | `ai_calls`, `ai_cache`, `ai_provider_state` |
| `src/db/migrate.py` | `MigrationRunner` — detect, stamp, backup, upgrade |
| `src/settings.py` | Typed resolution: env → DB → YAML → default |

**New — AI Service Layer**

| File | Purpose |
|---|---|
| `src/ai/service.py` | `AIService` — the only public entry point |
| `src/ai/schemas.py` | Every Pydantic output model |
| `src/ai/context.py` | `ContextBuilder` — frozen prefix, chunk alignment |
| `src/ai/prompts.py` | `PromptManager` |
| `src/ai/prompts/*.v1.md` | 4 templates + `_shared/` (incl. `batch_contract.md`) |
| `src/ai/repair.py` | Three-branch ladder |
| `src/ai/cache.py` | Response cache · content dedup · in-flight guard |
| `src/ai/concurrency.py` | Bounded adaptive pool |
| `src/ai/cost.py` | `PriceTable`, `CostTracker`, budget guard, surcharge awareness |
| `src/ai/metrics.py` | Cache-hit ratio, repair rate, token/cost counters |
| `src/ai/errors.py` | Exception hierarchy |
| `src/ai/credentials.py` | `CredentialStore` — Fernet, validation, fingerprints |
| `src/ai/providers/base.py` | `LLMProvider` ABC, `ChatRequest`, `ChatResponse` |
| `src/ai/providers/openai_compatible.py` | Shared wire format |
| `src/ai/providers/deepseek.py` | ★ `DeepSeekProvider` |
| `src/ai/providers/fake.py` | Test double |
| `src/ai/providers/registry.py` | `PROVIDER_REGISTRY` + UI descriptors |
| `src/db/repositories/ai.py` | `AICallRepository`, `AICacheRepository`, `ProviderStateRepository` |
| `src/dashboard/routes_settings.py` | `/settings/ai` + API |
| `src/dashboard/routes_health.py` | `/health`, `/health/ai` |
| `src/dashboard/templates/settings_ai.html` | |
| `src/dashboard/templates/health_ai.html` | |
| `src/obs/logging.py` | Structured JSON + `RedactingFilter` |
| `.env.example`, `.gitignore`, `pyproject.toml` | |
| `tests/fixtures/ai/*.json` | Recorded provider responses |

**Modified**

| File | Change |
|---|---|
| `src/db/database.py` | Pragma listener, `session_scope()`, migration hook |
| `src/db/models.py` | +`AICall`, `AICache`, `AIProviderState`; existing 8 untouched |
| `src/config.py` | Loads `.env`; `${VAR}` interpolation; validates `ai:` and `pricing:` |
| `config.yaml` | New `ai:` and `pricing:` sections — **no API key** |
| `main.py` | `migrate` and `ai` subcommands; startup AI status line |
| `src/dashboard/app.py` | Registers settings + health blueprints |
| `requirements.txt` | `+alembic`, `+pydantic>=2`, `+cryptography`, `+python-dotenv`, `+pytest`, `+pytest-cov`, `+responses`, `+ruff` |

**Untouched:** all three scrapers, `reddit_client.py`, `scoring.py`, `routes.py`, `index.html`.

## 5. Database changes

**`0001_baseline`** — the 8 existing tables exactly as `create_all()` produces them.
**Stamped, not applied,** on the live database. A test asserts `0001`-on-empty produces DDL
identical to `create_all()`-on-empty.

**`0002_ai_infrastructure`** — `ai_calls`, `ai_cache`, `ai_provider_state`
([05 §5.4a](05-database-plan.md)). All new tables; no `ALTER`; the live 459 rows are untouched.

`ai_calls.run_id` and `.project_id` are created **without** a `REFERENCES` clause because `runs` and
`projects` do not exist yet; the FK is added in `0005` via `batch_alter_table`.

**The API key is not a schema change.** Its Fernet ciphertext goes into the pre-existing `settings`
table under `ai.provider.deepseek.api_key_enc`.

## 6. APIs

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/settings/ai` | Provider, status, masked fingerprint, model info, last validation, caps. **Never the key.** |
| `PUT` | `/api/settings/ai/key` | `{api_key}` — validate, then store encrypted; 422 with the specific reason |
| `DELETE` | `/api/settings/ai/key` | Clear; AI disabled |
| `POST` | `/api/settings/ai/test` | `{ok, model, context_window, latency_ms, validated_at, error?}` |
| `PUT` | `/api/settings/ai/config` | Model overrides, concurrency, timeouts, caps |
| `GET` | `/api/settings/ai/providers` | Registry descriptors |
| `GET` | `/api/ai/usage?period=today\|month` | Cost, tokens, calls, cache-hit ratio |
| `GET` | `/health` | +`schema_version`, `ai_status` |
| `GET` | `/health/ai` | Full AI metrics |

All 17 legacy endpoints unchanged.

## 7. UI changes

**`/settings/ai`** — designed in [09 §2a](09-dashboard-plan.md). Key entry with masked fingerprint,
Test Connection, all six status states, live usage, editable caps, advanced config.

**`/health/ai`** — cost today/month, cache-hit ratio with a target bar, repair rate, empty-content
rate, mean/p95 latency, current concurrency.

A **Settings** link is added to the existing header (one `<a>`; the rendered-output snapshot for
`/` is updated accordingly).

## 8. AI changes

This phase *is* the AI architecture. Concretely:

| Aspect | Decision |
|---|---|
| Provider | DeepSeek V4 Flash, `deepseek-v4-flash`, `https://api.deepseek.com/v1` |
| Transport | Raw `requests` — **no vendor SDK** |
| Structured output | `response_format={"type":"json_object"}` + client-side Pydantic |
| Repair | Three branches: empty content (perturb), invalid JSON (strip fences + error), schema (field error). ≤2 attempts each. |
| Caching | Implicit prefix caching — **guarantee byte-identical prefixes**; assert `prompt_cache_hit_tokens > 0` |
| Bulk | Bounded adaptive concurrency — **DeepSeek has no batch endpoint** |
| Cost | `$0.14` uncached in / `$0.0028` cached in / `$0.28` out per 1M; caps `$2.00`/run, `$5.00`/day |
| Errors | 400/401/402/422 non-retryable; 429/500/503 retryable with backoff + concurrency halving |
| 401 / 402 | **Distinct product states** with their own UI surfaces |
| Prompts | **4 templates** (one per model-invoking method), four mandatory sections incl. `# JSON Shape`; versioned; hash-locked |
| Testing | `FakeProvider` runs the entire suite. **Zero live API calls in CI.** |

**All 4 prompt templates are authored in this phase** even though only the connection test
exercises the provider. Writing them now forces the schemas, the context shape, and the cache
boundaries to be settled before any consumer depends on them.

*(This said "12" until implementation: a leftover from before the 12 domain methods were
consolidated into 4 in the DeepSeek re-evaluation. §2.1, §4 and AC10 already said 4.)*

## 9. Backend changes

### 9.1 Credential flow

```
User pastes key on /settings/ai
   └─► PUT /api/settings/ai/key
         ├─ strip whitespace; reject obviously malformed client-side
         ├─ CredentialStore.set_key(validate=True)
         │     ├─ provider.validate_credentials()  ← 1-token completion
         │     ├─ on success: Fernet(HKDF(APP_SECRET_KEY)).encrypt(key)
         │     │              → settings["ai.provider.deepseek.api_key_enc"]
         │     │              → ai_provider_state{status=valid, fingerprint,
         │     │                 key_sha256, model_id, last_validated_at, ms}
         │     └─ on 401 → 422 "DeepSeek rejected this key"     (key NOT stored)
         │        on 402 → stored, status=insufficient_balance  (the key is valid)
         │        on network → 422 "Could not reach api.deepseek.com"
         └─► UI shows the new status
```

A **402 stores the key** — it is a correct credential attached to an empty account, and forcing
re-entry after a top-up would be wrong.

### 9.2 Encryption

```python
def _data_key() -> bytes:
    secret = settings.get("APP_SECRET_KEY")
    if not secret:
        raise AIDisabled("APP_SECRET_KEY not set — AI features disabled")
    return base64.urlsafe_b64encode(
        HKDF(algorithm=SHA256(), length=32, salt=b"reddit-lead-finder/ai-key/v1",
             info=b"deepseek").derive(secret.encode())
    )
```

Documented honestly in the UI: on a single-tenant self-hosted install the data key lives on the same
machine, so this protects a **copied database file or a backup**, not an attacker with server
access. Claiming more would be dishonest.

### 9.3 Startup behaviour

```
Migrations      up to date (0002_ai_infrastructure)
AI provider     deepseek · deepseek-v4-flash · ● connected (validated 3h ago)
```

Missing `APP_SECRET_KEY`, missing key, or invalid key → AI disabled with a clear message.
**Scraping and the legacy dashboard remain fully functional** — the phases are independent.

### 9.4 The one internal call path

Everything routes through `AIService._call()` ([04 §6.3](04-system-design.md)), so caching, dedup,
budget, rate limiting, retry, repair, cost recording, and metrics are implemented exactly once and
inherited by all four model-invoking methods.

## 10. Frontend changes

- `settings_ai.html` — masked key field, Test Connection with inline result, six status renderings,
  usage panel, caps editor, advanced section
- `health_ai.html` — metric bars with targets; cache-hit ratio red below 85% with the explanation
- Shared `toast()` helper (the fix for the existing silent-AJAX-failure pattern)
- Header gains **Settings**

## 11. Risks

| Risk | Mitigation |
|---|---|
| **API key leaks** into logs, exports, or the repo | Fernet at rest; never returned by any API; redaction filter; grep tests over logs, DB, templates, repo |
| **Prefix cache never hits** → up to 50× cost | `prefix_hash` asserted constant; no volatile data in the prefix (test-enforced); `prompt_cache_hit_tokens > 0` asserted from call 2; red indicator on `/health/ai` |
| DeepSeek JSON mode returns unusable output | Three-branch ladder; `# JSON Shape` mandatory; `repair_rate` / `empty_content_rate` metrics |
| Vendor coupling leaks past the abstraction | Grep test: no `deepseek` outside `providers/`; whole suite on `FakeProvider` |
| Migration corrupts the live DB | SQLite backup API before every upgrade; tested downgrade; suite runs on a copy |
| `APP_SECRET_KEY` rotated → key undecryptable | Detected at startup; status `unconfigured` with "re-enter your API key"; never a crash |
| Building the AI layer with nothing to test it on | `FakeProvider` + recorded fixtures + the live Test Connection give real coverage without Phase 4 |
| Over-engineering the abstraction | Provider interface is 4 methods + 4 flags; `FakeProvider` proves it is sufficient |

## 12. Dependencies

**Upstream:** none. This phase can start immediately.

**New packages:** `alembic>=1.13`, `pydantic>=2`, `cryptography>=42`, `python-dotenv>=1.0`,
`pytest>=8`, `pytest-cov>=5`, `responses>=0.25`, `ruff>=0.5`.

**External:** a DeepSeek API key with credit, entered at runtime. `APP_SECRET_KEY` in `.env`.

## 13. Acceptance criteria

- [ ] AC1 — `python main.py migrate` on the **live** DB succeeds, prints a backup path, and leaves 459 leads with unchanged `intent_score`
- [ ] AC2 — `alembic heads` returns exactly one head
- [ ] AC3 — Pasting a valid key on `/settings/ai` validates and stores it; status shows Connected with model and latency
- [ ] AC4 — Test Connection returns in < 5 s and persists outcome, latency, model, timestamp
- [ ] AC5 — An invalid key returns 422 "DeepSeek rejected this key" and is **not** stored
- [ ] AC6 — A 402 stores the key and shows the amber "balance exhausted" state
- [ ] AC7 — No endpoint, template, or log ever contains the plaintext key
- [ ] AC8 — `grep -ri deepseek src/ --exclude-dir=ai/providers` returns **zero** matches
- [ ] AC9 — The entire AI test suite passes against `FakeProvider` with **zero** network calls
- [ ] AC10 — All 4 prompt templates exist at v1, each with a `# JSON Shape` section and the literal word "json"; batched prompts also carry a `# Batch Contract`
- [ ] AC11 — Two identical `_call()` invocations issue **one** provider request; the second is a cache hit at $0.00
- [ ] AC12 — Concurrent identical requests collapse to one via the in-flight guard
- [ ] AC13 — An empty-content response triggers a perturbed retry; invalid JSON triggers a fence-strip retry; a schema violation triggers a field-error retry
- [ ] AC14 — `prompt_cache_hit_tokens > 0` from the second call with an identical prefix
- [ ] AC15 — A budget cap is enforced **before** the call, not after
- [ ] AC16 — `ai_calls` records tokens, cached/uncached split, cost, latency, outcome for every call
- [ ] AC17 — Missing `APP_SECRET_KEY` or key disables AI cleanly; `python main.py scrape` still works
- [ ] AC18 — `GET /` renders identically; CSV export has 13 columns; all 17 legacy endpoints unchanged
- [ ] AC19 — `ruff` clean; coverage ≥ 85% on `src/ai/`

## 14. Completion checklist

- [ ] Alembic configured; `0001_baseline` DDL-verified against `create_all()`
- [ ] `0002_ai_infrastructure` with downgrade
- [ ] `MigrationRunner`: detect, auto-stamp, backup via SQLite backup API, upgrade
- [ ] Pragmas applied on every connect; `foreign_keys=1` verified on an app connection
- [ ] `session_scope()`
- [ ] `LLMProvider` ABC + `ChatRequest`/`ChatResponse` + 4 capability flags
- [ ] `OpenAICompatibleProvider` base class
- [ ] `DeepSeekProvider` with price table, error classification, `validate_credentials`
- [ ] `FakeProvider` replaying recorded fixtures
- [ ] `PROVIDER_REGISTRY` + Settings-UI descriptors
- [ ] `AIService` with its 4 model-invoking methods and the single `_call()`
- [ ] `PromptManager`: load, render, version, content-hash lock
- [ ] 4 prompt templates at v1, six sections each (+ Batch Contract where batched)
- [ ] Test: every prompt has `# JSON Shape`, a fenced example, and the word "json"
- [ ] Test: prompt file hash matches its recorded version hash
- [ ] `ContextBuilder`: sorted JSON, no volatile data, 64-token padding, `prefix_hash`
- [ ] `ResponseRepairer` — all three branches
- [ ] `ResponseCache` + content-hash dedup + in-flight guard
- [ ] `ConcurrencyPool` — bounded, adaptive, `futures[fut]` attribution
- [ ] `RateLimiter` (token bucket)
- [ ] `RetryPolicy` with the full error classification table
- [ ] `CostTracker` — price table, `verified_on`, surcharge-aware, run + day caps
- [ ] `AIMetrics` — cache-hit ratio, repair rate, empty rate, latency, cost
- [ ] `CredentialStore` — Fernet, HKDF, validate-before-store, fingerprints, `mark_invalid`
- [ ] `InvalidAPIKeyError` and `InsufficientBalanceError` as distinct classes
- [ ] `/settings/ai` with all six status states
- [ ] `/health/ai` with target bars
- [ ] Structured logging + `RedactingFilter`
- [ ] `.env.example` documents `APP_SECRET_KEY`; **no API key anywhere in config**
- [ ] `config.yaml` gains documented `ai:` and `pricing:` sections
- [ ] `README.md` documents the Settings-page key setup
- [ ] `docs/testing/phase-01-testing.md` Part A complete
- [ ] `docs/testing/phase-01-testing.md` Part B executed and recorded
