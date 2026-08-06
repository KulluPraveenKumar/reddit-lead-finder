# Phase 01 — Implementation Status

Recorded 2026-07-30 at the end of the first implementation pass.
Plan: [11-phase-01.md](11-phase-01.md).

---

## Verified

| AC | What | Evidence |
|---|---|---|
| AC1 | Live DB migrates, backup printed, 459 leads with unchanged `intent_score` | `test_live_database_preserved`; SHA-256 of `(id, intent_score)` matches the pre-change baseline |
| AC2 | Exactly one Alembic head | `test_single_head` |
| AC7 | No endpoint, template or log contains the plaintext key | `test_key_never_returned_by_any_settings_route`, `test_redaction_catches_credential_shapes` |
| AC8 | No vendor coupling outside `providers/` | `test_no_vendor_coupling_outside_providers` (AST-based, so docstrings are allowed and defaults are not) |
| AC9 | Whole AI suite passes offline | 79 tests. Every HTTP test uses `responses`; everything else uses `FakeProvider`. **Not machine-enforced** — a live call added later would still pass. A socket-blocking autouse fixture would close that. |
| AC10 | 4 templates at v1, each with `# JSON Shape` and the word "json"; batched one has `# Batch Contract` | `test_every_prompt_has_the_required_sections` |
| AC11 | Two identical calls issue one request | `test_identical_calls_issue_one_request` |
| AC12 | Concurrent identical requests collapse to one | `test_concurrent_identical_calls_collapse` (6 threads, 1 provider call) |
| AC13 | All three repair branches | `test_empty_content_…`, `test_fenced_json_…`, `test_schema_violation_…` |
| AC15 | Budget enforced **before** the call | `test_budget_checked_before_the_call` asserts zero provider calls |
| AC16 | `ai_calls` records tokens, split, cost, latency, outcome | `test_every_call_is_recorded` |
| AC17 | No key / no `APP_SECRET_KEY` disables AI cleanly; scraping unaffected | `test_disabled_without_key`, `test_rotated_app_secret_key_is_a_distinct_state`; `python main.py ai status` |
| AC18 | `GET /` byte-identical; CSV 13 columns; legacy endpoints unchanged | Diffed against a baseline captured before any change |
| AC19 | `ruff` clean; coverage on `src/ai` | `ruff check .` passes; **87%** (target 85%) |

Also verified beyond the ACs: `0001_baseline` produces **byte-identical DDL** to
`create_all()`; downgrade/re-upgrade round-trips; pragmas (`WAL`, `busy_timeout`,
`foreign_keys=ON`) are applied on every pooled connection; batch results are matched
by echoed `id` rather than position.

---

## Live verification, 2026-07-31

A key was supplied and the AI path was exercised end to end against a real provider.

**The key is an OpenRouter key (`sk-or-v1-…`), not a DeepSeek key.** DeepSeek rejects it
with a 401 — confirmed directly. OpenRouter is OpenAI-compatible and serves
`deepseek/deepseek-v4-flash` at 1M context, so a 90-line `OpenRouterProvider` subclass was
added and the platform now runs on it. **Nothing outside `src/ai/providers/` changed** to
support a second provider, which is the provider abstraction doing the job it was built for.

| AC | Result |
|---|---|
| AC3 | ✅ Key validated and stored; status `valid`, fingerprint `sk-…d115` |
| AC4 | ⚠️ Test Connection succeeds but takes **3–10 s**, not < 5 s. Gateway routing latency; see below |
| AC5 | ✅ Verified against DeepSeek direct, which returns a real 401 for this key |
| AC6 | ⛔ Not verifiable — the account has credit, so no 402 can be produced |
| **AC14** | ⚠️ **Cache works; telemetry does not.** See below |

### AC14 in detail — the finding that mattered most

Two calls with a **byte-identical 2,014-token prefix** both reported
`prompt_tokens_details.cached_tokens: 0`, while the reported prompt cost fell
**0.000282 → 0.000186, a 34% drop**. The upstream cache *is* working and the discount *is*
passed through; OpenRouter simply does not populate the cached-token field for DeepSeek.

Consequence: computing cost from tokens overstates it on every cached call. `ChatResponse`
now carries `reported_cost_usd`, and `CostTracker.record()` prefers the provider's own
figure. **`/health/ai` will show a 0% prefix-cache ratio on OpenRouter — that is a
telemetry gap, not a broken cache**, and the cost figures remain accurate because they no
longer depend on the missing field.

### Pricing differs from DeepSeek direct

| | Uncached in | Cached in | Out | Differential |
|---|---:|---:|---:|---:|
| DeepSeek direct | $0.14/M | $0.0028/M | $0.28/M | **50×** |
| OpenRouter | $0.14/M | $0.028/M | $0.28/M | **5×** |

Cached input costs 10× more through the gateway, so the prefix cache is worth ~5×, not
~50×. It is still worth engineering for, but it stops being the dominant cost lever, and
the gate, dedup and incremental savings become proportionally more important. The cost
model in [06d](06d-ai-budget-and-scale.md) is written against DeepSeek direct and would
need re-deriving if OpenRouter becomes permanent.

### Latency

Mean **12.8 s** per enrichment call through the gateway, against a design assumption of
~2 s. Acceptable for batched background work; it would make the Phase-7 wall-clock target
(1,000 collected in under 2 minutes) unreachable without more concurrency. Worth measuring
again against DeepSeek direct before treating it as the real number.

### Classification quality, unprompted spot check

Three realistic Reddit posts, one deliberately irrelevant:

| Post | Verdict |
|---|---|
| "Actively looking to replace Segment this quarter" | `is_lead`, `evaluating`, matched `attribution-gap`, competitor `segment` |
| "Complete beginner, learn Python for data?" | **correctly rejected** — `unaware`, no matches |
| "Dreamdata vs Segment, budget approved" | `is_lead`, `ready_to_buy`, competitors `dreamdata` + `segment` |

Closed-set slug selection held: no invented slugs across any run.

---

## Deviations from the plan, and why

**`ruff` scoped away from pre-Phase-1 modules.** `routes.py`, the scrapers,
`reddit_client.py`, `scoring.py`, `config.py` and `subreddit_loader.py` are listed under
`per-file-ignores`. Reformatting them would risk the byte-identical `GET /` guarantee
(AC18) to fix lint findings in code that Phases 2 and 6 rewrite anyway. Each entry has a
note naming the phase that removes it.

**`create_all()` removed from `init_db()`.** The plan implied this; it needed stating.
Leaving it in meant that importing the app would create whatever was in `models.py` and
then collide with the migration meant to create it, with no clean recovery.

**`AIStatus.UNDECRYPTABLE` added as a sixth state.** The plan lists five UI states plus a
rotated-`APP_SECRET_KEY` risk. That risk *is* a state, and it needs different wording from
"unconfigured" — "re-enter your key", not "enter a key".

---

## Six bugs found

Three by the offline tests, three only by running against a real provider. All six were
silent.

**1. In-flight guard dropped results for slow followers.** The leader's `release()` cleared
the published result while other threads were still waiting on the event, so they woke to
`None` and crashed on validation. Fixed with a waiter refcount plus a cache fallback. Only
reproducible under real concurrency — `test_concurrent_identical_calls_collapse` catches it.

**2. The daily cost cap reset on every process restart.** `CostTracker.load_day_spend()`
existed and was never called, so `max_cost_per_day_usd` was a *per-process* limit — restart
the dashboard and the cap was fresh. Now seeded lazily from `ai_calls` before the first
budget check. Two tests cover it, and both were confirmed to fail with the fix removed.

The first attempt at that test passed for the wrong reason: the cap was small enough that a
single call's (deliberately conservative) pre-flight estimate tripped it on its own, whether
or not seeding worked. The test now computes the discriminating window and asserts the cap
sits inside it.

**3. Bare `ConnectionError` escaped classification.** `requests` usually wraps socket
failures in `RequestException`, but not always. An unwrapped one would propagate
unclassified and the retry policy would decline to retry a transient network blip. The
transport now catches `OSError` too.

### Found only against a live provider

**4. The enrichment output budget was far too small, and reasoning tokens were the reason.**
`max_tokens = 400·n + 500` gave a 1-item batch 900 tokens. `deepseek-v4-flash` is a
reasoning model that spends output budget on reasoning *before* emitting content — a probe
with `max_tokens=30` returned `reasoning_tokens: 30` and empty content. In the first live
run, **3 batches cost 7 provider calls**: 2 empty-content failures and 1 truncated
("unterminated string") response, each burning repair attempts on a fault no rewording can
fix. Budget raised to `1200·n + 1500`, and budget starvation now **escalates the budget**
rather than entering the repair ladder, bounded by `MAX_OUTPUT_CEILING`. After the fix:
**3 batches → 3 calls, 0 repairs.**

**5. Cost was computed from a cache split the gateway does not report.** Every cached call
would have been overstated. `reported_cost_usd` now wins when the provider supplies it.

**6. `ai_calls` recorded two rows per call whenever a repair fired.** The row was written
once on send and again on outcome, so every calls-per-1,000-posts figure would have been
inflated by the repair rate — the exact metric the cost argument rests on. Now one row per
provider call, and a failed attempt records the cost it actually incurred.

---

## Not started

Phases 2–8. Nothing in this phase depends on them, and nothing in them is blocked:
`AIService`'s four domain methods exist and are exercised against `FakeProvider`; Phase 4
fills in `analyze_business`, Phase 7 fills in `enrich_batch`.

`PreAIGate` ships as a boundary with its eleven counted rejection reasons; the rules
themselves land in Phase 6, as planned.
