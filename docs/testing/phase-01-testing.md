# Phase 01 — Testing: AI Foundation & DeepSeek V4 Flash Integration

> **Two blocking gates in this phase.** Test 1 (backup/restore) must pass before any migration runs.
> Test 12 (credential leakage) must pass before the phase is signed off.

---

# PART A — Claude Verification

## A1. Architecture

- [ ] `AIService` is the **only** entry point to any model — `grep -rn "chat/completions" src/ --exclude-dir=ai/providers` → 0
- [ ] `grep -ri "deepseek\|api.deepseek.com" src/ --exclude-dir=ai/providers` → **0 matches**
- [ ] `grep -rn "response_format\|max_tokens\|temperature" src/ --exclude-dir=ai` → 0
- [ ] `src/ai/providers/` imports nothing from `src/ai/` above it (no circular dependency)
- [ ] `src/ai/` imports only from `src/net/`, `src/db/`, `src/obs/`, `src/settings.py`
- [ ] `LLMProvider` is an ABC with 4 abstract methods and 4 capability properties
- [ ] `DeepSeekProvider` derives from `OpenAICompatibleProvider`
- [ ] `FakeProvider` implements the identical interface with no DeepSeek-specific code
- [ ] All 4 model-invoking methods funnel through a single `_call()` — caching, dedup, budget, retry, repair, cost, metrics implemented exactly once
- [ ] `MigrationRunner` lives in `src/db/`, not in a route or `main.py`

## A2. Compilation and imports

- [ ] `python -c "import src.ai, src.ai.providers.deepseek, src.db.migrate"` succeeds **without** an API key set
- [ ] Missing key raises only at first call, never at import
- [ ] `alembic heads` returns exactly one head
- [ ] `alembic history` shows `0001 → 0002` linearly
- [ ] `python main.py migrate status` runs
- [ ] All 8 existing model classes still importable under their original names

## A3. Lint / A4. Typing

- [ ] `ruff check .` and `ruff format --check .` clean
- [ ] No `print()` in `src/` (`ruff --select T20`)
- [ ] `ChatRequest` / `ChatResponse` / `ConnectionResult` / `CostEstimate` are typed dataclasses
- [ ] Every Pydantic model uses `Literal` for enums and `Field(...)` constraints
- [ ] `slug` fields carry the `pattern` constraint
- [ ] Timeouts typed `tuple[float, float]`
- [ ] `AIErrorClass` is an `Enum`, not string literals

## A5. Edge cases

**Credentials**
- [ ] No key configured → AI disabled, clear message, scraping unaffected
- [ ] Key with leading/trailing whitespace → stripped before use
- [ ] Obviously malformed key → rejected client-side, no network call
- [ ] `APP_SECRET_KEY` missing → AI disabled with a clear message, **not a crash**
- [ ] `APP_SECRET_KEY` rotated → stored key undecryptable → status `unconfigured` + "re-enter your key"
- [ ] Key valid but account empty (402) → key **is** stored, status `insufficient_balance`
- [ ] Key rejected (401) → key **not** stored

**Provider / JSON**
- [ ] Empty content response → perturbed retry, ≤2 attempts
- [ ] Response wrapped in ```` ```json ```` fences → fences stripped, then parsed
- [ ] Truncated JSON (`finish_reason == "length"`) → retry with larger `max_tokens`
- [ ] Valid JSON, missing required field → field-specific repair retry
- [ ] Valid JSON, `personas` has 7 items (max 5) → repair retry with the constraint named
- [ ] Repair exhausted → `SchemaValidationError`, item marked failed
- [ ] Response with unknown extra keys → ignored, not an error

**Cache / dedup**
- [ ] Two identical `_call()`s → 1 provider request, 1 cache hit
- [ ] Concurrent identical `_call()`s → in-flight guard collapses to 1
- [ ] `prompt_version` bump → cache miss (new namespace)
- [ ] Prefix shorter than `min_prefix_tokens_for_cache` → caching skipped **and logged**, not silently ineffective
- [ ] Context block containing a timestamp → caught by the prefix-purity test

**Cost / limits**
- [ ] Budget checked **before** the call
- [ ] Run cap and day cap enforced independently
- [ ] Peak-surcharge window with `enabled: false` → multiplier 1.0
- [ ] Zero-token response → cost 0.0, no divide-by-zero

**Migrations**
- [ ] Empty DB → creates everything from `0001`
- [ ] Live DB → stamps `0001`, applies `0002`
- [ ] Already current → no-op, no backup created
- [ ] `data/` not writable → clear error **before** any schema change
- [ ] Downgrade below `0001` → refused

## A6. Error handling

- [ ] Error classification covers 400/401/402/422/429/500/503 + timeout + connection
- [ ] **401 and 402 are distinct exception classes**, not folded into a generic API error
- [ ] 400/401/402/422 are **never** retried
- [ ] 429/500/503 retried with jittered backoff and concurrency halving
- [ ] No bare `except:` (`ruff --select E722`); no `except Exception: pass` in `src/ai/`
- [ ] Every exception message includes actionable context (stage, attempt, status)
- [ ] Failed migration exits non-zero, prints the backup path, leaves no half-applied revision

## A7. Security

- [ ] `settings` stores only ciphertext under `ai.provider.deepseek.api_key_enc`
- [ ] `ai_provider_state` has **no** key column — verify with `PRAGMA table_info(ai_provider_state)`
- [ ] No endpoint returns the plaintext key — inspect every response shape
- [ ] `CredentialStore.__repr__` and any dataclass holding the key use `repr=False`
- [ ] `RedactingFilter` registered on the root logger and unit-tested
- [ ] Full-run log capture grepped for the key → 0 matches
- [ ] `.env`, `*.db`, `data/backups/` in `.gitignore`
- [ ] `config.yaml` contains **no** `api_key` field
- [ ] Fernet key derived via HKDF with a fixed salt and info string
- [ ] `ai_calls.error` and `run_events.data_json` pass through redaction

## A8. Performance

- [ ] Cache lookup is a single indexed query
- [ ] `ai_cache` keyed by hash, not by full prompt text
- [ ] Content-dedup lookup uses `ix_ai_cache_content`
- [ ] `ContextBuilder.build()` result memoised per `(project, stage)` within a run
- [ ] `prefix_hash` computed once, not per call
- [ ] Pragmas applied on every connect (event listener), not once
- [ ] `PRAGMA journal_mode` = `wal`, `busy_timeout` = 10000, `foreign_keys` = 1 on an **application** connection

## A9. Scalability

- [ ] `ConcurrencyPool` ceiling configurable; adaptation has hysteresis (no oscillation)
- [ ] `RateLimiter` is a bounded token bucket, not an unbounded queue
- [ ] `AIMetrics` uses bounded `deque`, not unbounded lists
- [ ] `ai_calls` growth bounded by the documented retention purge
- [ ] In-flight guard map is cleared on completion (no leak)

## A10. Logging

- [ ] Every call logs stage, provider, model, prompt version, tokens (cached/uncached), cost, latency, outcome, attempt
- [ ] Cache hit / miss logged at DEBUG; **cache-miss-after-warmup at WARNING**
- [ ] Repair attempts logged with the branch taken and the reason
- [ ] Credential validation logged **without** the key
- [ ] 402 logged at ERROR with the "add credit" remedy
- [ ] Migration start/end and backup path logged

## A11. Retries

- [ ] Two distinct loops: transport retry (network/HTTP) and repair retry (content)
- [ ] Transport: max 5 for 429/503, 4 for 500/timeout
- [ ] Repair: max 2 per branch
- [ ] `Retry-After` honoured when present, capped
- [ ] Backoff exponential with jitter, capped at 60 s
- [ ] Non-retryable classes short-circuit immediately
- [ ] A retried call that succeeds is **not** double-charged (dedup guard)

## A12. AI-specific verification

- [ ] **DeepSeek connection** — `test_connection()` returns model, context window, latency; persists to `ai_provider_state`
- [ ] **Prompt validation** — every one of the 12 files has all six sections
- [ ] Every prompt contains the literal token `json` (case-insensitive) and a fenced example
- [ ] Prompt content hash matches the recorded hash for its version
- [ ] **JSON validation** — all three repair branches unit-tested with recorded fixtures
- [ ] **Retry behaviour** — 429 → backoff + concurrency halved; verified with a mocked provider
- [ ] **Timeout behaviour** — `(connect, read)` tuple always; read timeout retried
- [ ] **Cache behaviour** — second identical call returns `from_cache=True` at $0.00
- [ ] **Duplicate request prevention** — in-flight guard test with two threads
- [ ] **Token usage** — `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` parsed into the right columns
- [ ] **Cost estimation** — computed cost matches a hand calculation to 6 decimals
- [ ] **Fallback behaviour** — provider unavailable → AI disabled cleanly; scraping unaffected
- [ ] Whole AI suite passes against `FakeProvider` with **zero** network calls

## A13. Regression

- [ ] `SELECT COUNT(*) FROM leads` = 459
- [ ] `MIN/MAX/AVG(intent_score)` = 5.0 / 164.28 / 42.29 (±0.01)
- [ ] `scrape_runs` = 10, `settings` ≥ 6, `subreddits` = 4
- [ ] `GET /` renders; HTML diff limited to the new Settings nav link
- [ ] All 3 charts render; filters, sorts, pagination unchanged
- [ ] CSV export: 13 columns, same rows
- [ ] All 17 legacy endpoints byte-identical (contract test)
- [ ] All three scrapers still run

---

# PART B — Manual Testing

---

## Test 1 — Backup and restore *(BLOCKING — do this first)*

**Preconditions** Live `data/leads.db` with 459 leads.

**Steps**
1. `cp data/leads.db data/leads.db.manual-backup`
2. `python main.py migrate`
3. Note the printed backup path; verify the file exists and its size is plausible.
4. `sqlite3 <backup> "SELECT COUNT(*) FROM leads;"`
5. Restore test: `cp <backup> data/leads.db`, reopen the dashboard.

**Expected**
- Backup written to `data/backups/leads-<UTC>.db` **before** any schema change
- Backup contains 459 leads and is restorable
- Backup path printed in green

**Failure behaviour**
- No backup → **stop; do not proceed**
- Restore produces a corrupt file → the backup used `shutil.copy` instead of the SQLite backup API

**Edge cases**
- `data/` read-only → migration refuses to start
- Run `migrate` twice → second creates no backup (already at head)

**Success criteria** A valid, restorable backup exists before any schema change.

---

## Test 2 — Migration of the live database

**Preconditions** Test 1 passed.

**Steps**
1. `python main.py migrate status`
2. `python main.py migrate`
3. Verify:
   ```sql
   SELECT COUNT(*) FROM leads;                                   -- 459
   SELECT MIN(intent_score), MAX(intent_score), ROUND(AVG(intent_score),2) FROM leads;
   SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;
   PRAGMA table_info(ai_provider_state);
   ```

**Expected**
- Stamps `0001`, applies `0002`
- 459 leads; scores 5.0 / 164.28 / 42.29
- New tables: `ai_calls`, `ai_cache`, `ai_provider_state`
- All 8 original tables present
- **`ai_provider_state` has no column containing a key**

**Failure behaviour** Any count or score change → restore from backup immediately.

**Edge cases**
- Ctrl-C mid-migration → each revision is a transaction; DB lands on a clean revision
- Fresh DB → creates everything from `0001`

**Success criteria** Head reached, zero data changed.

---

## Test 3 — Entering a valid API key

**Preconditions** A DeepSeek key with credit; `APP_SECRET_KEY` in `.env`; dashboard running.

**Steps**
1. Open `/settings/ai`. Note the initial state.
2. Paste the key. Click **Save**.
3. Observe validation.
4. Reload the page.
5. `SELECT key FROM settings WHERE key LIKE 'ai.provider%';` and `SELECT * FROM ai_provider_state;`

**Expected**
- Initial state: ○ grey, "No API key configured. AI features are disabled; scraping still works."
- On save: validates within ~2 s, then ● green Connected
- Shows `deepseek-v4-flash`, context window, latency, "Last validated <timestamp>"
- After reload: masked fingerprint `sk-••••a3f9`, status persists
- `settings` holds **ciphertext**, not the key
- `ai_provider_state` holds fingerprint, sha256, model, timestamp — **no key**

**Failure behaviour**
- Plaintext key visible in `settings` → **blocking security defect**
- Status not persisted → `ai_provider_state` not written
- Key echoed back in the form field → **blocking**

**Edge cases**
- Paste with trailing newline/space → stripped, still validates
- Paste a key with an obviously wrong shape → rejected client-side before any network call
- Save without validating (explicit tick) → stored, status `unconfigured`

**Success criteria** Key validates, stores encrypted, status persists, plaintext never visible.

---

## Test 4 — Test Connection

**Preconditions** Valid key stored.

**Steps**
1. Click **Test Connection**. Time it.
2. Read the inline result.
3. `SELECT last_validated_at, last_validation_ms, model_id, status FROM ai_provider_state;`
4. `SELECT stage, outcome, cost_usd FROM ai_calls ORDER BY id DESC LIMIT 1;`

**Expected**
- Returns in < 5 s
- `✓ Connected in NNN ms · deepseek-v4-flash · validated <timestamp>`
- All four state columns updated
- An `ai_calls` row with `stage='connection_test'` and a cost near $0.0000005

**Failure behaviour**
- No `ai_calls` row → the test bypasses the instrumented path and proves less than it appears to
- Raw traceback shown → error mapping missing

**Edge cases**
- Test twice rapidly → both succeed; no in-flight-guard deadlock
- Test with the network down → "Could not reach api.deepseek.com", amber, scraping unaffected

**Success criteria** Fast, persisted, instrumented.

---

## Test 5 — Invalid, missing, and expired keys

**Steps**
1. Replace the key with `sk-thisisnotavalidkey000000000000`. Save.
2. Observe.
3. Verify the **previous working key** is still in effect (reload; check status).
4. Delete the key entirely (`DELETE /api/settings/ai/key`). Reload.
5. Restore the valid key.
6. Try to start a project (Phase 4 feature — expect a clear message if unavailable).

**Expected**
- Invalid key → **422** with "DeepSeek rejected this key. Check it was copied completely."
- The bad key is **not stored**; the previous key still works
- After deletion: ○ grey "No API key configured"; AI features disabled
- With no key: `python main.py scrape` **still works**; `GET /` still renders
- Restoring the valid key returns to ● green

**Failure behaviour**
- Bad key overwrites the good one → **data-loss-grade defect**
- App refuses to start without a key → AI must be optional
- Generic "Error" with no remedy → error mapping missing

**Edge cases**
- Key valid yesterday, revoked today → next call returns 401 → status flips to red automatically, without needing a manual test
- Empty string submitted → 422, nothing changes

**Success criteria** Each of the three states is distinct, actionable, and non-destructive.

---

## Test 6 — Insufficient balance (402)

**Preconditions** A key on an account with zero credit, **or** a mocked 402 via the test harness.

**Steps**
1. Configure the zero-balance key.
2. Click Test Connection.
3. Observe the status colour and message.
4. Check `/health/ai`.
5. Confirm the key **was** stored.

**Expected**
- Status: **● amber**, not red
- Message: "DeepSeek balance exhausted. Add credit to resume AI features."
- A link to DeepSeek billing and a Retest button
- The key **is** stored — it is valid, the account is empty
- `/health/ai` shows the same state
- Scraping unaffected

**Failure behaviour**
- Shown as red/invalid-key → sends the operator to debug the wrong thing
- Key discarded → they would have to re-enter it after topping up
- 402 retried with backoff → wastes time on an error that cannot resolve itself

**Edge cases**
- Balance exhausted **mid-run** (Phase 7) → run preserves completed work; verify the semantics are documented consistently here
- Credit added, Retest clicked → returns to green with no re-entry

**Success criteria** 402 is a distinct, correctly-coloured, non-destructive product state.

---

## Test 7 — Prompt framework

**Steps**
1. `pytest tests/unit/test_prompts.py -v`
2. Open three prompt files; confirm all six sections.
3. Delete the `# JSON Shape` section from one; re-run the test.
4. Change one word in a prompt without bumping the version; re-run.
5. Restore both.

**Expected**
- All 12 files present at v1 with six sections each
- Removing `# JSON Shape` → **specific** failure naming that file
- Editing without a version bump → hash-mismatch failure naming the file
- Every file contains the literal token `json` and a fenced example

**Failure behaviour**
- Tests pass with a missing section → assertions too weak
- No hash lock → prompt edits silently serve stale cached results forever

**Edge cases**
- A v2 file added alongside v1 → both loadable; active version comes from settings
- Prompt referencing a variable not supplied → clear render-time error

**Success criteria** The framework catches both structural and silent-drift errors.

---

## Test 8 — The three-branch repair ladder

**Preconditions** Test harness able to script provider responses.

**Steps**
1. Script an **empty content** response, then a valid one. Call a stage.
2. Script **invalid JSON** (`{"a": `), then valid.
3. Script JSON wrapped in ```` ```json ```` fences.
4. Script valid JSON that violates a constraint (6 personas), then valid.
5. Script three consecutive failures.
6. Inspect `ai_calls` rows for each.

**Expected**
- Empty → retry with a **perturbed** prompt (verify the second request differs), then succeeds
- Invalid JSON → retry with the parser error appended
- Fenced → fences stripped and parsed **without** a retry
- Constraint violation → retry with the field error naming `personas`
- Three failures → `SchemaValidationError`, item failed, run continues
- Each attempt writes an `ai_calls` row with the right `outcome`

**Failure behaviour**
- Empty content resent byte-identically → the vendor's documented workaround is prompt modification; an identical resend likely repeats the failure
- Fenced JSON causing a retry → wasteful; strip first
- Repair loop unbounded → cost risk

**Edge cases**
- Empty content on the final allowed attempt → clean failure, not a crash
- JSON valid but semantically absurd (all fields null) → passes schema; caught downstream by the slug/evidence checks

**Success criteria** All three branches behave distinctly and terminate.

---

## Test 9 — Caching and duplicate prevention

**Steps**
1. Call the same stage with identical inputs twice. Time both.
2. `SELECT COUNT(*) FROM ai_calls WHERE stage=?;` and `SELECT hits FROM ai_cache;`
3. From two threads, issue the same call simultaneously.
4. Bump `prompt_version` in settings; repeat call 1.
5. Inspect `prompt_cache_hit_tokens` on the second of two calls sharing a prefix.

**Expected**
- First call: normal latency, cost recorded
- Second call: near-instant, `outcome='cached'`, **cost 0.00**, `ai_cache.hits` incremented
- Concurrent identical calls → **one** provider request
- After a version bump → cache miss, full cost
- With a shared prefix, call 2 shows `prompt_cache_hit_tokens > 0`

**Failure behaviour**
- Second call costs the same → cache key includes something volatile; inspect it
- `prompt_cache_hit_tokens` always 0 → **the prefix is not stable; costs are up to 50× the estimate**
- Concurrent calls both hit the API → in-flight guard not wired

**Edge cases**
- Prefix under the minimum → caching skipped **and a log line says so**
- Cache entry for a retired prompt version → purgeable by version

**Success criteria** Cache hits are free; prefix caching demonstrably active.

---

## Test 10 — Cost tracking and caps

**Steps**
1. Note `/health/ai` cost figures.
2. Make 10 calls via the harness.
3. Recheck; verify cost increased by the expected amount.
4. Hand-calculate one call's cost from its `ai_calls` row and the price table; compare.
5. Set `max_cost_per_run_usd: 0.0001`; attempt a run of calls.
6. Set `max_cost_per_day_usd` below today's spend; attempt a call.
7. Restore both.

**Expected**
- Cost accumulates per call, per day, per month
- Hand calculation matches to 6 decimals
- Run cap → `BudgetExceededError` **before** the call
- Day cap → same, independently
- Both caps are visible and editable on `/settings/ai`

**Failure behaviour**
- Cost computed after the call → the cap cannot prevent overspend, only report it
- Cached calls counted as cost → double counting
- Caps not independent → a day cap that only fires within one run is useless against a stuck scheduler

**Edge cases**
- Peak surcharge enabled in config → multiplier applied and shown
- Zero-cost cached call → does not advance the caps

**Success criteria** Costs accurate and caps enforced pre-call.

---

## Test 11 — Provider abstraction *(the extensibility proof)*

**Steps**
1. `pytest tests/ -k ai -v` — confirm the whole AI suite runs on `FakeProvider`.
2. Disconnect the network entirely; re-run.
3. `grep -ri "deepseek" src/ --exclude-dir=ai/providers`
4. Read `src/ai/service.py` for any vendor-specific branch.
5. Inspect `PROVIDER_REGISTRY` and the Settings dropdown.

**Expected**
- Entire AI suite passes offline
- Grep returns **zero** matches
- No `if provider.name == "deepseek"` anywhere — behaviour selected by capability flags only
- Registry drives the dropdown as data

**Failure behaviour**
- Any match outside `providers/` → the abstraction is already leaking, on day one
- Vendor-name branching → adding a provider will require editing `AIService`
- Suite requires network → CI will be flaky and slow

**Edge cases**
- Add a trivial `EchoProvider` in a test and swap it in → all domain methods still work
- Capability flags flipped on `FakeProvider` → `enrich_batch` takes the other path

**Success criteria** Zero vendor leakage; suite fully offline.

---

## Test 12 — Credential leakage *(BLOCKING)*

**Steps**
1. `python main.py dashboard > run.log 2>&1`, exercise Settings, run a Test Connection, then stop.
2. `grep -i "<your actual key>" run.log` — and grep for its last 20 characters.
3. Dump every TEXT column: `sqlite3 data/leads.db ".dump"` and grep for the key.
4. View source on `/settings/ai` and `/health/ai`.
5. `curl -s localhost:5000/api/settings/ai | grep -i sk-`
6. `git status`; `git check-ignore -v .env`
7. Repeat with logging at DEBUG.

**Expected**
- **Zero** matches in logs, at every log level
- **Zero** matches in the database dump except the Fernet ciphertext (which is not the key)
- No key in any HTML source
- API returns only the masked fingerprint
- `.env` gitignored

**Failure behaviour**
- **Any** plaintext match is a blocking defect. Do not proceed to Phase 2.

**Edge cases**
- Force a 401 → the error message contains no key material
- Force an exception with a traceback → no key in the traceback

**Success criteria** Zero matches everywhere, including at DEBUG.

---

## Test 13 — Degradation without AI

**Steps**
1. Remove `APP_SECRET_KEY` from `.env`. Restart.
2. Observe startup output and `/settings/ai`.
3. Run `python main.py scrape`.
4. Open `/`.
5. Restore `APP_SECRET_KEY` but delete the API key. Restart. Repeat 3–4.

**Expected**
- Missing `APP_SECRET_KEY` → clear startup message; AI disabled; **no crash**
- `/settings/ai` explains the missing prerequisite
- **`python main.py scrape` works normally in both cases**
- Legacy dashboard fully functional
- `/health` shows AI as unconfigured without erroring

**Failure behaviour**
- App refuses to start → AI must be optional
- Scraping broken → the phases are not independent
- `/health` 500s → the health page must be the most robust page in the app

**Edge cases**
- `APP_SECRET_KEY` changed after a key was stored → status `unconfigured` with "re-enter your API key", not a decryption traceback

**Success criteria** The product degrades to a working scraper.

---

## Test 14 — Concurrency and rate limiting

**Steps**
1. Via the harness, submit 50 items through `enrich_batch` against `FakeProvider` with simulated latency.
2. Observe wall clock vs. sequential.
3. Script sustained 429s; watch the concurrency ceiling.
4. Stop the 429s; watch it recover.
5. Verify every result is attributed to the correct input.

**Expected**
- ~8× faster than sequential at default concurrency
- On sustained 429 → ceiling halves (8 → 4 → 2 → 1), logged each time
- After a clean window → steps back up
- **All 50 results correctly attributed** (this is rehearsal for the Phase 7 blocking test)

**Failure behaviour**
- No adaptation → a rate-limited account will thrash
- Oscillation → hysteresis missing
- Any mis-attribution → **critical**; fix before Phase 7 depends on it

**Edge cases**
- Ceiling 1 → still functions, just serial
- All 50 fail → `BatchReport` reports 50 failures without raising

**Success criteria** Speed-up achieved, adaptation works, attribution exact.

---

## Sign-off

| Test | Result | Notes |
|---|---|---|
| 1 **Backup & restore** | ☐ Pass ☐ Fail | **Blocking** |
| 2 Live migration | ☐ Pass ☐ Fail | |
| 3 Valid key entry | ☐ Pass ☐ Fail | |
| 4 Test Connection | ☐ Pass ☐ Fail | |
| 5 Invalid / missing key | ☐ Pass ☐ Fail | |
| 6 402 balance state | ☐ Pass ☐ Fail | |
| 7 Prompt framework | ☐ Pass ☐ Fail | |
| 8 Repair ladder | ☐ Pass ☐ Fail | |
| 9 Cache & dedup | ☐ Pass ☐ Fail | |
| 10 Cost & caps | ☐ Pass ☐ Fail | |
| 11 Provider abstraction | ☐ Pass ☐ Fail | |
| 12 **Credential leakage** | ☐ Pass ☐ Fail | **Blocking** |
| 13 Degradation without AI | ☐ Pass ☐ Fail | |
| 14 Concurrency | ☐ Pass ☐ Fail | |

**Phase 1 complete when Part A is fully ticked and all 14 Part B tests pass.**
