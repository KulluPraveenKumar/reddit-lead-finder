# 06d — AI Call Budget, Cost at Scale & Why This Beats One-Call-Per-Post

> Concrete API-call and dollar budgets for 100 → 10,000 scraped posts, the assumptions behind them,
> and a decomposed comparison against the naive design. Prices verified 2026-07-30
> ([02 §6.2](02-research-findings.md)); batch and gate behaviour from
> [06b](06b-deepseek-optimization.md) and [06c](06c-local-first-pipeline.md).

---

## 1. Model assumptions

| Parameter | Value | Source |
|---|---|---|
| Cached input | $0.0028 / 1M | verified |
| Uncached input | $0.14 / 1M | verified |
| Output | $0.28 / 1M | verified |
| Frozen prefix | ~3,500 tok | BKB matching surface, budget 4,000 ([06e §6](06e-business-knowledge-base.md)) |
| Per-item text | ~500 tok | typical Reddit post + top comments |
| Per-item output | ~250 tok | `LeadAnalysis` schema |
| Batch size | 8 | measured ceiling ([06b](06b-deepseek-optimization.md)) |
| Hard-filter pass rate | ~27% | [06c §8](06c-local-first-pipeline.md) |
| Adaptive admission (`balanced`) | ~65% of candidates | **derived per run**, not configured ([06f](06f-adaptive-budget.md)) |
| **Net AI admission rate** | **~18% of collected** | product of the above, on a *typical* distribution |
| Holdout audit | 2% of rejects | [06c §6](06c-local-first-pipeline.md) |

Per-item enrichment cost, batched at B=8 with a hot prefix cache:

```
per call = 3,500 × $0.0028/M  +  8 × 500 × $0.14/M  +  8 × 250 × $0.28/M
         = $0.0000098 + $0.00056 + $0.00056  =  $0.00113
per item = $0.000141
```

---

## 2. Call budget by scrape size

`balanced` mode, first run on a new project (no cache reuse), including the one consolidated
website-intelligence call and the holdout audit.

> **These figures are representative, not fixed.** Since [06f](06f-adaptive-budget.md) replaced the
> fixed threshold with an adaptive budget, the admitted count is **derived from each run's pre-score
> distribution** and will vary — see the five distributions in [06f §4](06f-adaptive-budget.md),
> which span 13 to 690 admitted. The table below models a *typical* distribution: ~27% of collected
> items survive the hard filters, and the adaptive cut admits ~65% of those (~55% via the
> small-`n` fixed fallback below 200 candidates). The **ceilings in §4 are the hard guarantees**;
> this table is the expected case.

| Collected | Candidates (`n`) | Admitted | Path | Holdout | **Enrichment calls** | Website | **Total calls** |
|---:|---:|---:|---|---:|---:|---:|---:|
| 100 | 27 | 15 | fixed (`n` < 200) | 1 | 3 | 1 | **4** |
| 500 | 135 | 74 | fixed (`n` < 200) | 2 | 11 | 1 | **12** |
| 1,000 | 270 | 176 | adaptive | 2 | 23 | 1 | **24** |
| 5,000 | 1,350 | 878 | adaptive | 10 | 112 | 1 | **113** |
| 10,000 | 2,700 | 1,755 | adaptive | 19 | 223 | 1 | **224** |

**Calls scale with unique high-value candidates, not with posts scraped.** Ten thousand collected
posts produce 224 requests — a ratio of **1 call per 45 posts**.

The count rose from the 210 quoted under the fixed threshold, because adaptive budgeting admits
*more* on a healthy distribution (~18% of collected rather than 15%). That is the intended
direction: the earlier figure was lower because it was discarding candidates on the steep part of
the curve. **Cheaper was not better there, and the holdout audit is what proves it.**

### 2.1 Cost by scrape size

| Collected | Enrichment | Website¹ | **Total (first run)** | **Re-run, no new posts** | Naive² |
|---:|---:|---:|---:|---:|---:|
| 100 | $0.0034 | $0.0037 | **$0.007** | $0.00 | $0.015 |
| 500 | $0.0123 | $0.0037 | **$0.016** | $0.00 | $0.074 |
| 1,000 | $0.0258 | $0.0037 | **$0.030** | $0.00 | $0.148 |
| 5,000 | $0.1254 | $0.0037 | **$0.129** | $0.00 | $0.740 |
| 10,000 | $0.2498 | $0.0037 | **$0.254** | $0.00 | $1.480 |

¹ The website call rose from $0.0025 to $0.0037 because it now produces the full 23-section
Business Knowledge Base rather than four artefacts ([06e §8](06e-business-knowledge-base.md)).
**One eighth of one cent** for a substantially richer, reusable knowledge model — and it is paid
once per website version, not once per run.

² **Naive = one call per collected post with the prefix cache working.** The same design with a
cold cache costs 3.8× more ($0.560 per 1,000). Both baselines appear in §3.1; percentage claims
always name which one they are measured against.

### 2.2 Mode comparison at 5,000 posts (`n` = 1,350 candidates)

Under adaptive budgeting the modes shift the knee rather than setting a fixed cut, so the admitted
counts below are what a *typical* distribution yields at each appetite:

| Mode | Admitted | ≈ share of `n` | Calls | Cost | Gate miss rate (target) |
|---|---:|---:|---:|---:|---|
| `thorough` | 1,215 | 90% (max clamp binds) | 154 | $0.175 | < 2% |
| `balanced` | 878 | 65% | 113 | $0.129 | < 5% |
| `frugal` | 405 | 30% | 55 | $0.064 | < 12% |

The spread is narrower than under fixed thresholds (previously $0.03–$0.44) because **the hard
filters have already removed the items no mode would want**, and the adaptive floor prevents
`frugal` from cutting into the steep part of the curve. A narrower spread is the correct outcome:
it means the mode selector is choosing between defensible options rather than between a good run and
a crippled one.

The miss-rate column is the honest cost of frugality — and because it is **measured** by the
holdout audit rather than assumed, the operator can choose with evidence.

### 2.3 Cold-cache sensitivity

Caching is best-effort with hours-to-days TTL ([02 §6.9](02-research-findings.md)). A monitoring
run firing daily will meet a cold cache.

| Scenario | 1,000-post run |
|---|---:|
| Hot cache, batched B=8 | $0.030 |
| **Cold cache, batched B=8** | $0.039 (+31%) |
| Cold cache, **unbatched** | $0.110 (+269%) |

**Batching is what keeps a cold cache from tripling the bill.** The estimator therefore quotes a
range, not a point.

### 2.4 Monthly cost, continuous monitoring

One project, 12 subreddits, daily monitoring, ~1,000 posts/day of which ~120 are genuinely new
after dedup:

| | Calls/day | Cost/day | **Cost/month** |
|---|---:|---:|---:|
| First day (full) | 24 | $0.030 | — |
| Subsequent days (incremental, ~120 new items) | ~4 | $0.0045 | **≈ $0.13** |
| Naive one-call-per-post (cache working) | 1,000 | $0.148 | **≈ $4.44** |

Month total for this design: $0.030 (first day) + 29 × $0.0045 = **≈ $0.16**.

**≈ 28× cheaper over a month**, and the gap widens as the corpus accumulates, because incremental
processing means the marginal cost tracks new content rather than total content. Note the daily
incremental run has only ~32 candidates, so it takes the small-`n` fixed path — adaptive budgeting
correctly declines to infer a knee from 32 points.

---

## 3. Why this beats one-call-per-post

### 3.1 Decomposed, at 1,000 posts

All percentages below are against the **cold-cache naive baseline** ($0.560), which is the true
"no engineering at all" starting point. Against the **hot-cache naive baseline** ($0.148) — i.e.
crediting the naive design with caching it would get for free — the final figure is **−80% cost**.

| Design | Calls | Cost | vs. cold-cache naive |
|---|---:|---:|---|
| **Naive A**: one call per post, cold cache, no filter | 1,000 | $0.560 | baseline |
| **Naive B**: one call per post, cache working | 1,000 | $0.148 | −74% |
| \+ pre-filter & dedup (hard rules only) | 270 | $0.040 | −93% |
| \+ adaptive admission gate (`balanced`, knee at 176) | 176 | $0.026 | −95% |
| \+ batching B=8 | **22** | $0.025 | −96% cost, **−98% calls** |
| \+ holdout audit (quality insurance) | 23 | $0.026 | −95% |
| \+ website BKB call (once per site version) | **24** | **$0.030** | **−95%** (−80% vs Naive B) |

**Read the middle rows together.** Batching moves the *call count* from 176 to 22 while barely
moving cost; the gate and cache moved the *cost*. Both matter, for different reasons — conflating
them would send optimisation effort to the wrong place.

**And read the gate row against [06f](06f-adaptive-budget.md).** 176 is not a configured 15% — it is
where this distribution's knee fell. On a flat distribution the same mechanism admits far fewer
([06f §4B](06f-adaptive-budget.md): 47 of 402); on a steep one it admits more. The saving is a
*consequence* of the data, which is why it can be aggressive without being reckless.

### 3.2 The seven structural advantages

1. **Cost scales with unique high-value candidates, not scraped volume.** Naive cost is linear in
   posts. Here it is linear in *novel, plausible* discussions, which grows far more slowly — most
   scraping re-encounters known content.

2. **Re-runs are free.** Naive design re-pays for every post on every run. Incremental enrichment
   makes an unchanged re-run $0.00, which is what makes scheduled monitoring viable at all.

3. **Near-duplicates are paid for once.** Forty variants of "which CRM should I use" cost one
   analysis, not forty — while each lead keeps its own confidence score.

4. **Batching insures against cold caches.** The naive design's cost triples when the cache is cold.
   Batched, the same event costs +31%.

5. **Deterministic work stays deterministic.** Competitor detection, keyword matching, recency, and
   engagement are arithmetic and dictionary lookups. The naive design pays a model to do them
   inside every call; here they never reach the API.

6. **Fewer calls means fewer failure surfaces.** 21 requests have 21 chances to hit a 429, a
   timeout, or a malformed response. 1,000 requests have 1,000. Reliability improves for the same
   reason cost does.

7. **The filtering is measured.** This is the decisive one. The naive design has no gate, so it has
   nothing to measure and no way to know what it missed. This design gates aggressively **and
   continuously audits the gate**, publishing a gate miss rate. It can prove it is not trading
   quality for money — the naive design can only assert it.

### 3.3 What the naive design does better, stated fairly

| | Naive | This design |
|---|---|---|
| Implementation complexity | Trivial | Rule engine, MinHash, gate, batching, audit |
| Per-item attention | Full — one item per call | Shared across 8 items |
| Failure blast radius | One item | One batch (mitigated by split-and-retry) |
| Coverage | 100% of collected | ~18% admitted (adaptive) + a measured audit of the remainder |

The middle two are genuine and are why batch size is capped at a **measured** ceiling rather than
50 or 100, and why a length-mismatched batch response is treated as a failure rather than a partial
success. The last one is the real trade, and the holdout audit exists precisely so it is a
quantified trade rather than a hopeful one.

---

## 4. Budget enforcement

| Control | Default | Behaviour on breach |
|---|---|---|
| `max_cost_per_run_usd` | $2.00 | Enrichment stops; completed work preserved; run → `complete` + `partial_analysis` |
| `max_cost_per_day_usd` | $5.00 | Same, across all runs |
| `max_ai_calls_per_run` | 500 | Hard call ceiling independent of cost |
| `max_items_per_run` | 2,000 | Admission ceiling; excess rejected as `budget_exhausted` |

`max_ai_calls_per_run` exists as a **second, independent ceiling** because cost and call count can
diverge — a prompt-size regression could raise cost without raising calls, and a batching regression
could raise calls without raising cost much. Two dials catch both.

All four are checked **before** each call and shown live on the run page.

### 4.1 Pre-run estimate

```
1,200 collected → 329 candidates → 214 admitted + 3 audit = 217 items
Decided by          knee detection      (fixed ≥35 would admit 180)
Batches of 8                            28 DeepSeek calls
Estimated cost      $0.031 – $0.040     (hot – cold cache)   cap $2.00
Estimated AI time   ~50 s               (8 concurrent)
Prices verified     2026-07-30 · no peak surcharge active

  [ thorough  296 · $0.043 ]  [ balanced  214 · $0.031 ]  [ frugal  128 · $0.019 ]
```

The three modes are priced side by side at the moment of choosing, so the cost/coverage trade is
made with numbers rather than adjectives — and because each mode's count is now computed from this
run's actual distribution rather than from a stored percentage, the three numbers shown are what
those modes would really do on *this* data. The fixed-cut counterfactual is displayed alongside so
the adaptive mechanism stays reviewable rather than merely automatic.

---

## 5. Acceptance targets

| # | Target | Value |
|---|---|---:|
| 1 | AI calls per 1,000 collected posts (`balanced`, typical distribution) | ≤ 30 |
| 2 | Cost per 1,000 collected posts | ≤ $0.05 |
| 3 | Cost of an unchanged re-run | **$0.00** |
| 4 | Prefix cache-hit ratio after warm-up | > 85% |
| 5 | Items analysed more than once at one prompt version | **0** |
| 6 | Near-duplicate collapse rate | > 8% |
| 7 | **Gate miss rate** | **< 5%** |
| 8 | Batch length-mismatch rate | < 1% |
| 9 | Repair-ladder invocation rate | < 5% |
| 10 | Enrichment wall clock, 1,000 collected | < 2 min |
| 11 | Estimate vs. actual cost | within ±25% |
| 12 | Monthly cost, one monitored project | < $0.50 |
| 13 | Adaptive budget: **`balanced`** runs where a clamp bound the result | < 10% |
| 14 | Adaptive budget: `Budget.method` persisted for every run | **100%** |

Targets 1 and 2 are stated against a *typical* distribution because adaptive budgeting makes the
admitted count data-dependent. **The unconditional guarantees are the §4 ceilings**, which hold on
every run regardless of distribution. Target 13 is the check that the clamps remain what they were
designed to be — a guard against nonsense, not a routine budget: if they bind often, the knee
detector or the pre-score needs attention, not the clamp. It is scoped to `balanced` because
**`thorough` is designed to hit the ceiling** ([06f §3](06f-adaptive-budget.md)), so counting its
clamps would drown the signal it exists to carry.
