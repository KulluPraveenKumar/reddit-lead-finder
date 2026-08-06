# 24 — API Cost Optimization

> **Step 10, the brief's highest priority.** The target: 95%+ of Reddit posts must never invoke an
> LLM. This document states which definition of that target is being measured, shows the arithmetic,
> specifies the filtering layers, and — because Hermes is a *new* cost — specifies how the agent tier
> is bounded so that adding a conversational surface does not quietly undo the pipeline's economics.
>
> Basis: [06b](06b-deepseek-optimization.md), [06c](06c-local-first-pipeline.md),
> [06d](06d-ai-budget-and-scale.md), [06f](06f-adaptive-budget.md),
> [21 §6.5, §9](21-hermes-architecture.md).

---

## 1. The one thing this document must not do

There are two ways to make the headline number go up, and only one of them is legitimate.

| Approach | Effect on the metric | Effect on the product |
|---|---|---|
| **Add deterministic filtering before the gate** | Fewer candidates reach AI | Neutral or positive — the removed items were provably not leads |
| **Lower the admission threshold** | Fewer candidates reach AI | **Loses real leads on the steep part of the score curve** |

[06f §1](06f-adaptive-budget.md) is unambiguous that the second approach was tried, measured, and
reversed: the fixed ≥35 cut was cheaper *because it was discarding leads*, and adaptive budgeting
deliberately made a 1,000-post run **more** expensive ($0.030 vs $0.026) to stop it.
[09 §4.2](09-dashboard-plan.md) goes further and labels gate reduction *"informational — NOT a
target"*, precisely so that a dashboard cannot push an operator to re-introduce the fixed cut.

> **Constraint C1 — Nothing in this document may raise the metric by admitting fewer high-scoring
> candidates. Every layer added is a deterministic pre-gate filter, and the holdout audit's gate miss
> rate is the acceptance test for all of them.**

The goal is *the fewest calls that do not lose real leads*, not the fewest calls.

---

## 2. Defining the target precisely

"95% of posts never invoke an LLM" admits two readings, and they differ by an order of magnitude.
Both are reported.

| Definition | Meaning | Why it matters |
|---|---|---|
| **D-A — Enrichment rate** | Share of collected posts that are **never sent to a model at all** | The plain reading of the brief |
| **D-B — Call reduction** | `1 − (actual calls ÷ naive one-call-per-post)` | What actually determines the invoice, because batching means 8 posts share one call |

### 2.1 Where the design stands today

**First run on a new project, 1,000 collected posts, `balanced`** ([06d §2](06d-ai-budget-and-scale.md)):

```
1,000 collected
 −730  removed by hard filters (dedup, negatives, structural noise, too short, bots, window)
 ─────
  270  candidates (n)
  −94  below the adaptive admission cut
 ─────
  176  admitted to AI   +2 holdout audit  =  178 items enriched
        ÷ 8 per batch   =  23 calls  +1 website call  =  24 calls
```

| | Value |
|---|---|
| **D-A — never enriched** | 822 / 1,000 = **82.2%** |
| **D-B — call reduction** | 1 − 24/1,000 = **97.6%** |

### 2.2 Steady state is the mode that actually runs

The platform's operating mode is scheduled monitoring, not repeated cold starts. From
[06d §2.4](06d-ai-budget-and-scale.md): one project, 12 subreddits, daily, ~1,000 posts collected
per day of which **~120 are genuinely new after dedup**, producing ~4 calls/day.

```
Day 2–30, per day:
1,000 collected
 −880  already analysed at this prompt version  ← incremental enrichment, $0.00
 ─────
  120  new after dedup
  −88  hard filters + below the cut
 ─────
   32  admitted   ÷8  =  4 calls
```

| | Value |
|---|---|
| **D-A — never enriched** | 968 / 1,000 = **96.8%** |
| **D-B — call reduction** | 1 − 4/1,000 = **99.6%** |

### 2.3 The number to quote: a full month

| | Month total |
|---|---:|
| Posts collected | 30,000 |
| Posts enriched | 176 + (29 × 32) = **1,104** |
| **D-A — never invoke an LLM** | **96.3%** ✅ |
| Pipeline calls | 24 + (29 × 4) = **140** |
| **D-B — call reduction vs. naive** | **99.5%** ✅ |
| Calls per 1,000 collected | **4.7** |
| Posts per call | **214** |

> **The 95% target is met on both definitions over a monthly window, and on D-B on every window.
> D-A is met from day two onward; the first run of a new project sits at 82% and that is correct** —
> a cold project has nothing cached and no history, and tightening the gate to reach 95% on day one
> would violate C1.

§4 adds four deterministic layers that raise the first-run figure without touching the admission
threshold.

---

## 3. The filtering layers

The brief lists the layers it expects. All of them exist; this table states where each lives, what it
removes, and — the column that matters — that none of them costs a token.

```
                    1,000 collected posts
                              │
  ┌───────────────────────────▼───────────────────────────┐
  │  L0  CACHED DECISIONS      already analysed at this    │   0–88%   $0.00
  │      (content_hash, prompt_version)                    │
  ├────────────────────────────────────────────────────────┤
  │  L1  EXACT DEDUP           sha256(normalised text)      │   3–8%    $0.00
  ├────────────────────────────────────────────────────────┤
  │  L2  NEAR DEDUP            MinHash+LSH, Jaccard ≥ 0.85  │   8–20%   $0.00
  ├────────────────────────────────────────────────────────┤
  │  L3  SEMANTIC DEDUP        Model2Vec + sqlite-vec ≥0.88 │   2–5%    $0.00
  ├────────────────────────────────────────────────────────┤
  │  L4  REGEX / STRUCTURAL    hiring · giveaway · AMA ·    │   5–12%   $0.00
  │                            megathread · promo           │
  ├────────────────────────────────────────────────────────┤
  │  L5  KEYWORD + NEGATIVES   set membership, compiled re  │  10–20%   $0.00
  ├────────────────────────────────────────────────────────┤
  │  L6  AUTHOR / USER FILTERS [deleted] · AutoModerator ·  │   2–5%    $0.00
  │                            *Bot · vendor allowlist      │
  ├────────────────────────────────────────────────────────┤
  │  L7  SUBREDDIT RULES       fit floor · relative         │   1–4%    $0.00
  │                            engagement · window          │
  ├────────────────────────────────────────────────────────┤
  │  L8  BUSINESS RULES        competitor dictionary (alias-│    —      $0.00
  │                            resolved) · pain phrasing ·  │  (scores, │
  │                            customer language            │  doesn't  │
  │                                                         │  reject)  │
  ├────────────────────────────────────────────────────────┤
  │  L9  HISTORICAL SCORING    deterministic pre-score 0–100│    —      $0.00
  │                            + yield curve P(is_lead|s)   │
  ├────────────────────────────────────────────────────────┤
  │  L10 ADAPTIVE ADMISSION    knee + floor + marginal +    │  the only │
  │      ★ NOT A COST DIAL     clamps. Derived per run      │  tunable  │
  └───────────────────────────┬────────────────────────────┘
                              │  ~176 admitted (first run) / ~32 (steady)
                              ▼
                    ╔═════════════════════╗
                    ║  AIService          ║   batched B=8
                    ║  enrich_batch()     ║   frozen 3.5k prefix
                    ╚══════════┬══════════╝   4 pre-call ceilings
                               ▼
                    +2% of REJECTS re-admitted → HOLDOUT AUDIT
                       → gate miss rate, published every run
```

| Layer | Mechanism | Module | AI? |
|---|---|---|---|
| L0 | `(content_hash, prompt_version)` lookup | `ai/cache.py`, `PreAIGate` | ✗ |
| L1 | `sha256(normalise(title + body))` | `dedupe/exact.py` | ✗ |
| L2 | MinHash 128 perms, char 5-grams, LSH bands | `dedupe/minhash.py` | ✗ |
| L3 | Model2Vec (~30 MB, CPU) + `sqlite-vec`, degrades to no-op | `dedupe/semantic.py` | ✗ |
| L4 | Compiled regex | `rules/structural.py` | ✗ |
| L5 | Set membership + tiered keyword match | `rules/keywords.py` | ✗ |
| L6 | Regex + allowlist | `rules/authors.py` | ✗ |
| L7 | Arithmetic + `project.subreddit_fit()` | `scoring/features.py` | ✗ |
| L8 | 4-tier `EntityRegistry.resolve()` | `rules/competitors.py` | ✗ |
| L9 | Weighted arithmetic; `YieldCurve` fitted from labels | `scoring/prescore.py`, `feedback/yield_curve.py` | ✗ |
| L10 | Kneedle + floor + marginal + clamps | `scoring/budget.py` | ✗ |

**Every layer is grep-fenced from `src.ai`, and the fence now also forbids reaching them through
Hermes** ([21 §8.4](21-hermes-architecture.md)). If any of these ever needs a model call, the cost
argument has broken and the test says so.

---

## 4. New deterministic layers — raising D-A without violating C1

Four additions, in descending order of expected yield. Each removes items the platform can *prove*
are not leads, so each is C1-safe by construction; each is validated by the gate miss rate not
rising.

### 4.1 Label-reason → negative-rule promotion

[06i §2.2](06i-feedback-and-memory.md) already collects a `reason` on every `not_relevant` label.
Today the reason routes to a knowledge *suggestion*. It should also route to a **deterministic rule
proposal**, under the same operator gate:

| Recurring reason | Proposed deterministic rule |
|---|---|
| `competitor_staff` ×3 across ≥2 groups | Author allowlist entry (L6) |
| `not_a_buyer` ×3 with a shared phrase | Negative term (L5) |
| `too_old` clustering in one subreddit | Per-subreddit time-window override (L7) |
| `wrong_persona` ×5 for one persona | **Not a filter** — routes to the persona definition, as today |

The fourth row is the guard: a knowledge problem must not be solved by adding a filter, because a
filter hides the symptom and the wrong persona keeps mis-matching everywhere else.

**Expected effect:** 2–5% additional L5/L6 removal after ~8 weeks of labelling.
**Risk:** an over-broad learned negative silently over-rejects. **Mitigation:** every learned rule is
attributed in `prescores.gate_reason`, so the holdout audit's `worst_reason` names it directly.

### 4.2 Cross-project cached decisions

`ai_cache` is keyed on `(content_hash, stage, prompt_version)` and is **already project-agnostic**
([05 §5.4a](05-database-plan.md)). The index exists; the lookup in `PreAIGate` is currently
project-scoped.

Widening it means a post appearing in two projects' subreddit overlap is analysed once. **But the
analysis is only reusable if the enrichment prefix is the same**, and the prefix is per-project by
construction ([06e §6](06e-business-knowledge-base.md)).

**→ Decision: widen the lookup only for `is_lead=false` outcomes with no matched slugs.** A post
judged irrelevant to *any* business under *any* prefix is very likely irrelevant to the next one, and
a false reuse there costs a rejected non-lead. A positive judgement is prefix-dependent and is never
shared.

**Expected effect:** 0% for one project; 3–8% with two or more projects sharing subreddits.
**Guard:** shared-reuse decisions are flagged in `prescores` and sampled by the holdout audit at
double rate for the first 200 occurrences.

#### The version-pinning rule this requires

[AD-19](03-architecture.md) and Phase 7 **AC29** require every `lead_analysis` row to pin `bkb_id`,
`weights_version` and `ruleset_version`, so that any historical decision is reconstructible. A row
reused across projects would pin a *foreign* project's BKB, and AC29 would fail on a case nobody
anticipated.

**→ Rule: a cross-project reused analysis is written with `bkb_id = NULL` and
`reused_cross_project = 1`.**

The `NULL` is correct rather than a workaround: a row with `is_lead=false` and no matched slugs makes
**no claim that references a knowledge base**, so there is no version to pin. There is nothing to
explain and therefore nothing to reconstruct.

Three consequences, each asserted:

- **AC29 is amended** to read *"every `lead_analysis` row pins `bkb_id` unless
  `reused_cross_project = 1`, in which case `bkb_id IS NULL` and `matched_*_slugs` are empty."*
- **A reused row can never become a positive judgement.** A test asserts
  `reused_cross_project = 1 ⟹ is_lead = 0 AND matched_pain_slugs = '' AND persona_slug IS NULL`.
- **Re-enrichment is available.** If such a lead is later labelled `interested` by the operator — the
  case where the reuse was wrong — the flag makes it findable, and re-enrichment under the correct
  prefix produces a properly pinned row.

`reused_cross_project` is a `BOOLEAN NOT NULL DEFAULT 0` on `lead_analysis`, added inside revision
`0009_enrichment` (Phase 7, unshipped), so no new migration is introduced.

### 4.3 Subreddit-relative engagement floor

[02b §19](02b-research-2026-07.md) established that 30 upvotes is exceptional in a niche subreddit
and unremarkable in a large one, and that engagement should be normalised against the subreddit's own
baseline. That normalisation feeds the pre-score today, but there is no **hard floor**.

A post in the bottom decile of its own subreddit's engagement distribution, with no keyword hit and
no competitor mention, is not a lead. That is three independent negative signals, and rejecting it is
a hard filter (L7) rather than a threshold move.

**Expected effect:** 1–4%.
**Guard:** requires all three conditions. Any one of them alone is not sufficient, because a
zero-upvote post asking *"has anyone replaced Segment?"* is exactly the lead we exist to find.

### 4.4 Comment-budget targeting

Comment fetching is *"the most expensive collection step — one request per post with no pagination
reuse"* ([16 §9.2](16-phase-06.md)), and comments enter the enrichment funnel like any other item.
Candidates are currently ordered by `intent_score` and capped at 100 posts.

Ordering by **pre-score** instead, and skipping posts whose pre-score is already below the run's
admission floor, removes comments that would be gated out anyway — saving proxy requests *and*
candidates.

**Expected effect:** 5–15% fewer collected comments, with no change to admitted items.
**Note:** this is the only layer here that also saves *scraping* cost, which is the platform's real
wall-clock bottleneck (~33 min per run vs ~1 min of AI).

### 4.5 Combined effect on the first run

| | Before | After |
|---|---|---:|
| Collected | 1,000 | 1,000 |
| Candidates after hard filters | 270 | **~215** |
| Admitted (adaptive, unchanged rules) | 176 | ~145 |
| **D-A — never enriched** | 82.2% | **85.5%** |
| Calls | 24 | **20** |

**The first run still does not reach 95% on D-A, and no legitimate change will make it.** A cold
project has no cache, no labels, and no history — the three things that produce the steady-state
figure. Presenting a first-run 95% would require gate tightening, which C1 forbids. The honest
statement is: **82% → 86% on day one, 97% from day two, 96%+ over any month.**

---

## 5. The Hermes tier — where the new cost is

This is the section the brief's target does not anticipate, and it is the one that decides whether
the redesign is a net win.

### 5.1 Hermes adds cost. Stated plainly.

| | Monthly |
|---|---:|
| Pipeline, one monitored project ([06d §2.4](06d-ai-budget-and-scale.md)) | **$0.16** |
| Agent tier ([21 §6.5](21-hermes-architecture.md)) | **$0.43** |
| **Total** | **$0.59** |

**Adding Hermes multiplies platform AI spend by roughly 3.7×.** No amount of prefix engineering
changes that, because the agent tier is a genuinely new capability that did not previously consume
tokens. Any document claiming Hermes *reduces* cost would be wrong.

What can be said truthfully is that the increase is **small in absolute terms, bounded by a hard
cap, and separable on the invoice** — and that the alternative to a $0.43/month conversational
surface is not $0.00, it is the operator's time.

### 5.2 The eight agent-tier optimisations

| # | Optimisation | Mechanism | Saving |
|---|---|---|---|
| **1** | **Notifications never invoke a model** | `hermes send` runs *"without spinning up an agent or gateway loop"* ([19 §14.1](19-hermes-research.md)). Bodies rendered from SQL | **~30 turns/month → $0.00.** The single largest agent-tier saving |
| **2** | **Toolset pruning** | `agent.disabled_toolsets`: terminal, file, browser, code, web, media, x_search, image, tts | Tool schemas are a per-turn tax ([19 §3](19-hermes-research.md), L7). Est. **30–60% of system-prompt tokens** |
| **3** | **`--no-skills` profile** | No bundled skills; 13 authored skills only | Level-0 is ~3k tokens for a *default* install. Ours is measured and capped in H1 |
| **4** | **≤12-word descriptions** | [22 §2](22-hermes-skills.md) SR2 | Level-0 is paid every turn; bodies are not |
| **5** | **Deterministic notify policy** | 95% of events classified by a table, not a model | ~380 events/month → ~20 model classifications |
| **6** | **Reports pass numbers in** | The agent narrates; SQL computes | Removes tool round-trips *and* removes a class of wrong numbers |
| **7** | **Micro-compaction off** | Default; *"invalidates cached prefix tokens every turn"* | Preserves what prefix caching is available |
| **8** | **v4-flash, not v4-pro** | S3 recommends `deepseek-v4-pro` for Hermes; we pin `deepseek-v4-flash` per [D30](02-research-findings.md) | Pro is the more expensive sibling; escalation requires golden-set evidence, not intuition |

### 5.3 What is deliberately *not* attempted

**Prefix caching for the agent tier.** [19 §26.4](19-hermes-research.md) establishes that a Hermes
turn cannot be made byte-stable: the volatile prompt tier carries a timestamp, and the message array
grows with every tool call. Every figure in §5.1 therefore assumes **zero cache credit** for the
agent tier.

Pretending otherwise would understate agent cost by up to 50× on DeepSeek direct — the exact failure
mode [R2](10-implementation-roadmap.md) rates Critical for the pipeline. Budgeting for a discount you
cannot verify is how a cost model stops being a cost model.

---

## 6. The five ceilings

Four exist. Hermes needs a fifth, because it ships with none ([19 §40](19-hermes-research.md)).

| # | Ceiling | Default | Scope | Checked |
|---|---|---:|---|---|
| 1 | `max_cost_per_run_usd` | $2.00 | Pipeline | Pre-call |
| 2 | `max_cost_per_day_usd` | $5.00 | Pipeline | Pre-call, seeded from `ai_calls` on restart |
| 3 | `max_ai_calls_per_run` | 500 | Pipeline | Pre-call |
| 4 | `max_items_per_run` | 2,000 | Pipeline | At admission |
| **5** | **`agent.max_cost_per_day_usd`** | **$1.00** | **Agent tier** | **`pre_llm_call` hook, per turn** |

Ceiling 5 is implemented as the governor in [21 §9](21-hermes-architecture.md). Three properties make
it trustworthy:

- **It is checked before the tool-calling loop begins**, on the only hook Hermes documents as having
  a used return value — so a blocked turn issues **zero** provider calls.
- **It cannot silence alerts.** `hermes send` never enters an agent loop, so notifications continue
  at full function while conversation is capped. A control that blinds the operator when it fires
  gets switched off.
- **It is separately funded.** Two provider keys (AD-22) mean the agent cannot consume the pipeline's
  balance, and a runaway loop is visible as one account's spend rather than as a mystery.

---

## 7. Expected monthly cost

### 7.1 One monitored project, 30,000 posts/month

| Design | Calls/month | Cost/month | vs. naive-cold |
|---|---:|---:|---:|
| **Naive A** — one call per post, cold cache | 30,000 | **$16.80** | baseline |
| **Naive B** — one call per post, cache working | 30,000 | **$4.44** | −74% |
| \+ hard filters and dedup | 8,100 | $1.20 | −93% |
| \+ adaptive admission gate | 5,280 | $0.78 | −95% |
| \+ batching B=8 | 660 | $0.75 | −96% |
| \+ **incremental enrichment** (the dominant lever) | **140** | **$0.16** | **−99.0%** |
| \+ **Hermes agent tier** | 428 | **$0.59** | **−96.5%** |

**Read the last two rows together, because they are the honest summary of this redesign.** The
pipeline reaches $0.16/month. Hermes takes it to $0.59. Against the "no engineering at all" baseline
the platform is still **96.5% cheaper**; against a naive design that gets caching for free it is
**87% cheaper** — while additionally providing a conversational operator surface that neither
baseline has.

### 7.2 Sensitivity

| Scenario | Monthly | Note |
|---|---:|---|
| Steady state, one project (§7.1) | **$0.59** | The expected case |
| Three projects, shared subreddits | **$1.10** | Pipeline scales sub-linearly (§4.2); agent tier barely moves |
| Cold cache every day (worst realistic) | **$0.78** | Batching contains it; [06d §2.3](06d-ai-budget-and-scale.md) |
| **OpenRouter instead of DeepSeek direct** | **$0.71** | Cached input is 10× dearer ($0.028 vs $0.0028/M) — a **5×** differential, not 50× ([PHASE-01-STATUS](PHASE-01-STATUS.md)) |
| Heavy conversational month (3× agent use) | **$1.45** | Governor caps the day at $1.00, so the ceiling is $30/month |
| **Hard ceiling, both tiers** | **$180.00** | $5.00 + $1.00 per day. Never approached; it exists so a runaway loop has a bound |

**The last row is the number that matters for risk, not for budgeting.** The expected figure is
$0.59; the guaranteed maximum is $180. A design whose worst case is unbounded is not a cost model
regardless of its expected case.

---

## 8. Acceptance targets

Existing targets from [06d §5](06d-ai-budget-and-scale.md) are unchanged. These are added.

| # | Target | Value |
|---|---|---:|
| C1 | **D-A over a 30-day window** — posts never sent to a model | **≥ 95%** |
| C2 | **D-B, every run** — call reduction vs. one-call-per-post | **≥ 95%** |
| C3 | Pipeline calls per 1,000 collected, steady state | ≤ 6 |
| C4 | Pipeline cost, one monitored project | ≤ $0.30 / month |
| C5 | **Agent-tier cost** | ≤ **$1.00 / month expected**, hard cap $1.00 / day |
| C6 | **Agent turns per month** | ≤ **350** |
| C7 | **Notifications invoking a model** | **0** |
| C8 | Governor blocks a turn with zero provider calls | asserted |
| C9 | **Gate miss rate after adding §4's layers** | **< 5%**, unchanged |
| C10 | Any new deterministic layer raising `worst_reason` share | triggers review |
| C11 | Level-0 skill metadata tokens | ≤ measured H1 ceiling |
| C12 | Agent system-prompt tokens after toolset pruning | ≤ 60% of an unpruned baseline |
| C13 | Estimate vs. actual, both tiers | within ±25% |

**C6 is an absolute, not a share, and that is deliberate.** A ratio target ("agent spend ≤ 80% of
total") gets *easier* to satisfy as the pipeline grows, so it would stop constraining agent drift
exactly when drift became expensive. 350 turns/month is ~20% headroom over the
[21 §6.5](21-hermes-architecture.md) estimate of 288 and does not move when the pipeline does.

**C9 is the one that governs all the others.** Every layer in §4 removes candidates, and every
candidate removed is a lead that might have been. The gate miss rate is the only evidence that the
optimisation was free rather than merely cheap — and if it rises, the layer is reverted regardless of
what it did to C1.

---

## 9. Measurement, and what would falsify this

| Claim | How it is measured | What falsifies it |
|---|---|---|
| D-A ≥ 95% monthly | `SELECT` over `prescores.gate_decision` per 30 days | A month below 95% with the gate miss rate healthy → §4's layers are under-performing |
| Agent tier ≤ $1/month | `agent_events` aggregate on `/health/ai` | Sustained overage → the deterministic notify table is too narrow, or conversation is doing work a tool should |
| Notifications cost nothing | `agent_events` rows correlated to `notification_log` | Any non-zero token count → a notification path is going through the agent loop |
| Layers are C1-safe | `gate_audits.gate_miss_rate` before/after each layer | A rise on layer introduction → revert that layer |
| Toolset pruning works | H1 measurement of system-prompt tokens, pruned vs. unpruned | < 30% reduction → the tool schemas were not the dominant term and §5.2/2 is over-claimed |

The last row is a genuine open question rather than a rhetorical one: [19 §3](19-hermes-research.md)
records that Hermes does not publish tool-schema token costs, so the 30–60% figure in §5.2 is an
inference. **Phase H1 measures it, and this document is corrected from the measurement rather than
defended.**
