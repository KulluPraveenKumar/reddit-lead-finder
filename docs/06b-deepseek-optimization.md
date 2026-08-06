# 06b — DeepSeek Integration, Token & Cost Optimization

> How the AI Service Layer actually talks to DeepSeek V4 Flash, and every technique used to minimise
> API calls, latency, tokens, and cost. All figures derive from the pricing verified in
> [02 §6.2](02-research-findings.md) on 2026-07-30.

---

## 1. The economics that drive every decision

| Token class | $/1M | Relative |
|---|---:|---:|
| Input, **cache hit** | $0.0028 | **1×** |
| Input, cache miss | $0.14 | **50×** |
| Output | $0.28 | **100×** |

Two consequences dominate the design:

1. **A cache miss on the shared prefix costs 50× a hit.** Prefix stability is not an optimisation;
   it is the cost model. Everything else is rounding.
2. **Output is 2× input-miss and 100× input-hit.** Verbose schemas are the second-largest lever.
   Every field the model does not need to emit is worth 100 cached input tokens.

The corollary is counter-intuitive but important: **it is cheaper to send a large, stable context on
every call than a small, varying one.** A 3,000-token frozen prefix at cache-hit rates costs
$0.0000084 per call. The same 3,000 tokens rebuilt differently each time costs $0.00042 — fifty
times more, for identical information.

---

## 2. Wire format

DeepSeek is OpenAI-compatible. One endpoint, no SDK.

```http
POST https://api.deepseek.com/v1/chat/completions
Authorization: Bearer <key>
Content-Type: application/json

{
  "model": "deepseek-v4-flash",
  "messages": [
    {"role": "system",  "content": "<FROZEN — byte-identical across every call>"},
    {"role": "user",    "content": "<the only part that varies>"}
  ],
  "response_format": {"type": "json_object"},
  "max_tokens": 1536,
  "temperature": 0.2,
  "stream": false
}
```

Response `usage` carries the fields the cost model depends on:

```json
"usage": {
  "prompt_tokens": 3180,
  "completion_tokens": 240,
  "prompt_cache_hit_tokens": 3072,
  "prompt_cache_miss_tokens": 108,
  "total_tokens": 3420
}
```

`prompt_cache_hit_tokens` is the health metric for the entire cost model. A run where it stays at
zero is a run costing up to 50× its estimate.

**Parameter decisions:**

| Parameter | Value | Rationale |
|---|---|---|
| `temperature` | 0.2 (enrichment), 0.4 (generation) | Deterministic prompting: classification wants consistency, not creativity. Low temperature also shortens outputs. |
| `max_tokens` | Per stage, sized to the schema + 40% headroom | Too low truncates JSON mid-string (invalid); too high invites padding |
| `stream` | `false` | Responses are small and structured; streaming adds complexity with no user-visible benefit for a batch pipeline |
| `response_format` | `{"type": "json_object"}` | Required for JSON mode |
| `stop` | unset | JSON mode terminates naturally; a stop sequence risks truncating valid output |

---

## 3. Prompt structure for maximum cache hit

The message array is engineered so that the longest possible prefix is byte-identical between calls.

```
┌─────────────────────────────────────────────────────────────┐
│ SYSTEM MESSAGE — frozen, cached, ~2,000–3,500 tokens        │
│                                                             │
│  [A] Role + task + rules          ← identical per stage     │
│  [B] Rubric (enums + criteria)    ← identical per stage     │
│  [C] JSON shape example           ← identical per stage     │
│  [D] Project context              ← identical per project   │
│      business · icp · personas · pains · signals · vocab    │
│      json.dumps(sort_keys=True), padded to 64-token boundary│
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ USER MESSAGE — varies, ~200–800 tokens, never cached        │
│  <subreddit>…</subreddit><title>…</title><body>…</body>     │
└─────────────────────────────────────────────────────────────┘
```

Ordering rationale: A–C are constant for a stage across all projects, D is constant for a project
across all items. Placing D **last inside the system message** means that if a project's context
changes, A–C still cache. Placing anything variable before D would forfeit the entire prefix.

### Worked example — 500 posts, 3,000-token prefix, 500-token user, 250-token output

| Strategy | Input cost | Output cost | **Total** |
|---|---:|---:|---:|
| Context rebuilt per call (no prefix discipline) | $0.2450 | $0.0350 | **$0.2800** |
| Frozen prefix, cache hits from call 2 | $0.0396 | $0.0350 | **$0.0746** |
| Frozen prefix + response-cache on a 40% re-run | $0.0238 | $0.0210 | **$0.0448** |

**73% saved by prefix discipline alone.** 84% with the response cache. And in absolute terms: a
500-post enrichment costs about **7 cents**.

---

## 4. The optimisation techniques, ranked by what they actually save

**Ordered by dollars saved, not by novelty.** The first three are local and prevent the call
entirely; the rest make a call that is happening anyway cheaper.

| Rank | Technique | Mechanism | Cost saved | Calls saved |
|---:|---|---|---|---|
| **1** | **Candidate selection (`PreAIGate`)** | Deterministic pre-score; only admitted items reach AI | **~6×** | ~6× |
| **2** | **Incremental enrichment** | Only unseen `(content_hash, prompt_version)` | **∞ on re-runs** | ∞ |
| **3** | **Semantic dedup** | Exact hash + MinHash/LSH ≥ 0.85 → one analysis per group | **~1.3×** | ~1.3× |
| **4** | **Prefix caching** | Byte-identical frozen system message | **~50× on the prefix** | — |
| **5** | **Consolidation** | 6 generation calls + 12 keyword calls → **1** | ~2× on generation | **19×** |
| **6** | **Batching (B=8)** | 8 items per request | ~1.05× hot, **~3× cold** | **~8×** |
| 7 | **Response cache** | `sha256(provider, model, stage, version, system, user)` | 100% of repeats | 100% |
| 8 | **In-flight dedup guard** | Concurrent identical requests collapse | double-charge | — |
| 9 | **Context compression** | Site text → structured profile once | ~10× on generation | — |
| 10 | **Minimal context windows** | Each stage gets only what it needs | 30–50% of prefix | — |
| 11 | **Tight output schemas** | Slugs not prose; capped free text | output is the 100× class | — |
| 12 | **Chunk alignment** | Pad context to a 64-token boundary | recovers the tail chunk | — |
| 13 | **Local signal extraction** | Competitors, pricing, tech markers by regex/dictionary | removes work from the prompt | — |

**The ranking is the point.** Prefix caching is the most *discussed* optimisation and it is fourth.
Ranks 1–3 are deterministic local work that means the call never happens, and they dominate.
Optimising a call you should not be making is the expensive mistake.

### 4.6 in detail — batch size is measured, not guessed

Batch prompting degrades accuracy as batch size grows ([02 §6.8](02-research-findings.md)).
Published thresholds: quality holds to b < 16 for simple classification, b < 8 for multi-step
reasoning, and ~4 for heterogeneous unrelated items. The mechanism is **attention dilution** —
transformers concentrate attention on initial tokens, so the instruction block becomes the sink and
**middle items are starved**. Past the threshold, accuracy collapses rather than degrading
gracefully.

**Procedure, executed in Phase 7 and re-executed on any model change:**

```
for B in [1, 4, 8, 12, 16]:
    run the 40-item golden set at batch size B
    record precision, recall, F1 on is_lead
    record mean absolute error on buying_intent
    record mean output tokens per item
    record batch length-mismatch rate

ship the LARGEST B whose F1 is within 0.02 of B=1
```

Expected shape, to be replaced by measured values:

| B | Calls / 1,000 items | Expected F1 | Length-mismatch risk |
|---:|---:|---|---|
| 1 | 1,000 | baseline | none |
| 4 | 250 | ≈ baseline | very low |
| **8** | **125** | **≈ baseline — the default** | low |
| 12 | 84 | slight decline expected | moderate |
| 16 | 63 | decline expected | higher |

**Adaptive within the measured band.** Start at 8. On a length mismatch or a schema failure, halve
for that item set (8 → 4 → 2 → 1) so a difficult batch degrades toward the known-good B=1 rather
than failing. On a clean window, step back up. The ceiling never exceeds the measured maximum.

### 4.6a Why batching is worth doing even though it saves ~5%

| Scenario | Unbatched | Batched B=8 |
|---|---:|---:|
| Prefix cache **hot** | $0.000148/item | $0.000141/item (**−5%**) |
| Prefix cache **cold** | $0.000560/item | $0.000185/item (**−67%**) |
| Calls per 1,000 items | 1,000 | **125** |

DeepSeek's caching is explicitly **best-effort with no guaranteed hit rate**, entries clear within
"a few hours to a few days", and construction takes seconds. A daily monitoring run meets a cold
cache routinely.

**Batching is insurance.** It turns a cold-cache event from a 3.8× cost spike into a 1.2× one, and
it cuts call count 8×, which is what relieves rate-limit and latency pressure. Presenting it as the
primary *cost* lever would be wrong — that is ranks 1–3.

### 4.7 in detail — cache warm-up ordering

Firing 8 concurrent requests at a cold cache produces 8 simultaneous full-price prefixes, because
none can hit a cache the others are still building.

**→ The first batch of a run is issued alone.** Its `prompt_cache_miss_tokens` is recorded as
warm-up cost; only after it returns does the concurrency pool open. One serialised request buys a
warm cache for every subsequent one.

### 4.8 in detail — context compression

The website may yield 40 KB of text (~10,000 tokens). Sending that to every downstream stage would
cost 10,000 uncached tokens six times over.

```
raw site text (40 KB, ~10,000 tok)
      │  ONE call: website_analysis
      ▼
BusinessProfile (~600 tok structured)
      │  every downstream stage consumes THIS, never the raw text
      ├──► icp_generation
      ├──► pain_extraction
      ├──► buying_intent
      ├──► reddit_vocabulary
      ├──► subreddit_recommendation
      └──► keyword_generation
```

The raw text is read exactly once. This is a ~10× reduction on the generation pipeline and it also
improves quality — a structured profile is a cleaner input than boilerplate-laden HTML text.

### 4.9 in detail — minimal context per call

With consolidation there are only two prompt shapes, so "minimal context" means something sharper
than trimming a stage list.

| Call | Receives | Deliberately does **not** receive |
|---|---|---|
| `analyze_business` | Cleaned site text (≤40 KB) **+ locally extracted signals** (competitors, pricing, tech markers, schema.org) as *facts* | Raw HTML, nav chrome, cookie banners, boilerplate footers |
| `enrich_batch` | Frozen project context (cached) + 8 items, each title + truncated body + top-comment digest | Raw site text, full comment trees, the business profile prose, anything already in the frozen prefix |

**Per-item truncation inside a batch.** Body text is head+tail truncated at 1,200 characters with an
explicit `…[truncated]…` marker. Reddit posts have a long tail of 10,000-character essays; sending
one whole would cost more than the other seven items combined and rarely changes the judgement.

**Comment digest, not comment dump.** For a post with comments, the batch carries the top 3 comments
by score, truncated to 200 characters each — not the thread. The signal that matters ("same here, we
ripped out X in March") is almost always in the top-scored replies.

## 5. Complete cost model

Full budgets by scrape size in [06d](06d-ai-budget-and-scale.md). Summary:

### 5.1 Business Knowledge Base — one call per project

| Component | Tokens | Rate | Cost |
|---|---:|---|---:|
| Input (site text + local signals) | 12,000 | $0.14/M | $0.00168 |
| Output (**all 23 BKB sections**) | 7,000 | $0.28/M | $0.00196 |
| **Total** | | | **$0.0037** |

Against the previous six-call design at $0.0051 plus twelve per-subreddit keyword calls at $0.0069
— **19 calls and $0.012 become 1 call and $0.0037.**

`max_tokens` is set to **12,000**, well above the 7,000 expected, because a truncated response is
the one failure the repair ladder cannot recover from cheaply. Headroom costs nothing when unused —
output is billed on tokens produced, not on the limit.

### 5.2 Enrichment — per item, batched B=8, hot prefix cache

| Component | Tokens | Rate | Cost |
|---|---:|---|---:|
| Cached prefix (amortised over 8) | 3,000 / 8 | $0.0028/M | $0.0000011 |
| Uncached item text | 500 | $0.14/M | $0.0000700 |
| Output | 250 | $0.28/M | $0.0000700 |
| **Per item** | | | **$0.000141** |

### 5.3 Full runs, `balanced` mode

| Collected | Admitted (~15%) | Calls | **Total cost** | Re-run |
|---:|---:|---:|---:|---:|
| 100 | 17 | 4 | **$0.005** | $0.00 |
| 500 | 84 | 12 | **$0.014** | $0.00 |
| 1,000 | 167 | 22 | **$0.026** | $0.00 |
| 5,000 | 835 | 106 | **$0.120** | $0.00 |
| 10,000 | 1,670 | 210 | **$0.238** | $0.00 |

### 5.4 The budget caps

| Cap | Default | Rationale |
|---|---:|---|
| `max_cost_per_run_usd` | **$2.00** | Above the largest legitimate run (≈$0.24 at 10,000 posts, with headroom for `thorough` mode), ~80× a typical one |
| `max_cost_per_day_usd` | **$5.00** | Backstop against a stuck scheduler |
| `max_ai_calls_per_run` | **500** | **Independent** ceiling — cost and call count can diverge |
| `max_items_per_run` | **2,000** | Admission ceiling |

`max_ai_calls_per_run` is deliberately a second dial. A prompt-size regression raises cost without
raising calls; a batching regression raises calls without raising cost much. One dial would miss
one of them.

### 5.5 Peak-surcharge awareness

A 2× surcharge at 01:00–04:00 and 06:00–10:00 UTC is announced but **not active** (verified
2026-07-25). Config carries it disabled; when it activates, flipping `enabled` makes the estimator,
budget guard, and recorder surcharge-aware with no code change.

## 6. Latency

| Lever | Effect |
|---|---|
| Bounded concurrency (default 8) | ~8× wall-clock reduction on enrichment |
| Cache hits | Return in microseconds; no network |
| Prefix caching | Reduces prefill time as well as cost |
| `stream: false` | One round trip; no event handling |
| Connection pooling | Amortises TLS handshake across a run |
| Tight `max_tokens` | Generation time is dominated by output length |
| Pre-filter | The cheapest call is the one not made |

**Measured expectation for a typical run:** 1,200 items ÷ 8 concurrent × ~2.5 s ≈ **6 minutes** of
enrichment. Scraping dominates the wall clock, not AI.

The enrichment stage is deliberately **not** on the user's critical path — it runs after scraping,
and the dashboard is usable with partial results as they land.

---

## 7. Failure modes specific to DeepSeek

| Failure | Detection | Response | User sees |
|---|---|---|---|
| Empty content (documented) | `content == ""` | Retry with perturbed prompt, ≤2 | Nothing unless exhausted |
| JSON wrapped in ```` ```json ```` fences | Parse fails on the raw string | Strip fences, re-parse before retrying | Nothing |
| JSON truncated mid-string | `finish_reason == "length"` | Retry with `max_tokens × 1.5` | Nothing |
| Schema violation | Pydantic | Retry with the field error, ≤2 | "Analysis failed" on that item |
| 401 invalid key | HTTP | Mark key invalid; stop AI | **Settings: "API key rejected"** |
| **402 insufficient balance** | HTTP | Stop enrichment, preserve work | **"DeepSeek balance exhausted — add credit"** |
| 429 / 503 | HTTP | Backoff + halve concurrency | "Rate limited, slowing down" |
| Latency degradation under load | p95 rising | Halve concurrency | ETA extends |
| Prefix cache miss | `prompt_cache_hit_tokens == 0` after item 2 | **Loud warning**, run continues | "Cache not working — costs may be 50× estimate" |
| Model ID retired | 400/404 | Fail fast at Test Connection | **Settings: "Model not available"** |

The cache-miss warning matters disproportionately. Every other failure is visible; a silent cache
miss looks like a perfectly successful run and only shows up on the invoice.

---

## 8. Estimation, shown before the user commits

```python
def estimate(plan: WorkloadPlan) -> CostEstimate:
    prefix   = ctx_tokens                                  # measured, not guessed
    per_item = (prefix * P.input_cached                    # after the first call
                + plan.avg_item_tokens * P.input_uncached
                + plan.avg_output_tokens * P.output) / 1e6
    first    = (prefix * P.input_uncached) / 1e6           # first call pays full price
    total    = first + per_item * plan.eligible_items
    return CostEstimate(
        items=plan.eligible_items,
        usd=total * P.surcharge_multiplier(plan.starts_at),
        minutes=plan.eligible_items / plan.concurrency * plan.avg_latency_s / 60,
        cache_assumed=True,
        prices_verified_on=P.verified_on,
    )
```

Displayed on the options screen before scraping starts:

```
1,240 items collected → 612 eligible after filtering
Estimated AI cost   $0.09        (cap $2.00)
Estimated AI time   ~3 min       (8 concurrent)
Prices verified     2026-07-30 · no peak surcharge active
```

`prices_verified_on` is displayed deliberately. A cost estimate from a stale price table is worse
than none, and showing the date makes staleness visible without requiring anyone to remember.

---

## 9. Configuration

```yaml
ai:
  enabled: true
  provider: deepseek                     # PROVIDER_REGISTRY key

  models:
    default:              deepseek-v4-flash
    website_analysis:     deepseek-v4-flash     # ← per-stage override; v4-pro if evidence warrants
    post_analysis:        deepseek-v4-flash
    comment_analysis:     deepseek-v4-flash

  max_tokens:
    business_intelligence: 8000    # ~2x expected 4000 — truncation is the risk
    enrichment_batch:      6000    # 8 items x ~250 out, x3 headroom
    artifact_regen:        3000
    outreach_suggestion:   1024
    default:               2048

  temperature:
    generation: 0.4
    enrichment: 0.2

  batching:
    enabled: true
    size: 8                              # MEASURED ceiling — see §4.6
    min_size: 1
    max_size: 12
    adapt_on_length_mismatch: true       # halve on mismatch, step up on clean window
    warm_up_first_batch_alone: true      # §4.7

  gate:
    mode: balanced                       # thorough | balanced | frugal
    prescore_threshold: 35               # balanced
    max_items_per_run: 2000
    holdout_sample_rate: 0.02            # §06c §6
    gate_miss_rate_warn_at: 0.05

  dedup:
    exact_enabled: true
    minhash_enabled: true
    shingle_k: 5
    num_perm: 128
    jaccard_threshold: 0.85

  concurrency:
    initial: 8
    floor:   1
    ceiling: 16
    adapt_on_429: true
    adapt_on_latency_p95_ms: 8000

  rate_limit:
    requests_per_minute: 240
    tokens_per_minute:   2_000_000

  timeouts:
    connect_s: 10
    read_generation_s: 180        # the consolidated call is large
    read_enrichment_s: 120        # a batch of 8 takes longer than one item

  retries:
    max_attempts_transient: 5
    max_attempts_repair:    2
    backoff_cap_s:          60

  cache:
    responses_enabled: true
    content_dedup_enabled: true
    website_ttl_days: 7
    min_prefix_tokens_for_cache: 512
    chunk_tokens: 64

  budget:
    max_cost_per_run_usd: 2.00
    max_cost_per_day_usd: 5.00
    max_ai_calls_per_run: 500

  prefilter:
    min_chars: 80
    skip_deleted_authors: true
    skip_bot_authors: true

pricing:
  verified_on: "2026-07-30"
  deepseek-v4-flash:
    input_cached_per_m:   0.0028
    input_uncached_per_m: 0.14
    output_per_m:         0.28
  peak_surcharge:
    enabled: false
    multiplier: 2.0
    windows_utc: ["01:00-04:00", "06:00-10:00"]
```

**No API key appears here.** It is entered in Settings and stored encrypted — see
[06a §12](06a-ai-service-layer.md) and [09](09-dashboard-plan.md).

---

## 10. Optimisation acceptance criteria

Measurable, and each is a test.

| # | Criterion | Target |
|---|---|---:|
| 1 | **AI calls per 1,000 collected posts** (`balanced`) | **≤ 25** |
| 2 | Business intelligence: calls per project | **1** |
| 3 | Cost per 1,000 collected posts | ≤ $0.05 |
| 4 | Re-run of an unchanged project | **$0.00 and 0 calls** |
| 5 | Re-run after +50 new posts | ≤ 8 calls |
| 6 | Prefix cache hit ratio after warm-up | > 0.85 |
| 7 | Duplicate content analysed twice | **0 occurrences** |
| 8 | Near-duplicate collapse rate | > 8% |
| 9 | **Gate miss rate** (holdout audit) | **< 5%** |
| 10 | Batch length-mismatch rate | < 1% |
| 11 | Repair-ladder invocation rate | < 5% |
| 12 | Empty-content rate | < 2% |
| 13 | Enrichment wall clock, 1,000 collected | < 2 min |
| 14 | Cost estimate vs. actual | within ±25% |
| 15 | `PreAIGate` reduction | > 80% of collected items |
