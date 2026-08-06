# Phase 07 — Adaptive, Batched Enrichment & Explainable Confidence

**Completion after this phase: 90%**

> **Rescoped by the 2026-07-30 research phase** on two axes: the admission gate became **adaptive**
> rather than fixed-threshold ([06f](06f-adaptive-budget.md)), and explainability became **ten
> specified fields** rather than an implicit consequence of storing score components
> ([06g Part I](06g-explainability-and-quality.md)). See [10 §1.1](10-implementation-roadmap.md).

## 1. Objective

Enrich every collected post and comment with DeepSeek V4 Flash — summary, pain point, problem
category, urgency, buying intent, ICP match, persona match, competitor mention, sentiment,
opportunity, priority, and a suggested outreach angle — then combine those judgements with
rule-based signals, Reddit metrics, recency, and engagement into a **deterministic, explainable
0–100 confidence score**.

This phase delivers the product vision. After it, the operator gets ranked opportunities with
evidence.

## 2. Scope

### 2.1 In scope

- Revision `0008_enrichment` — `lead_analysis`, `gate_audits`, **`ai_budgets`**
- **`PreAIGate`** — 11 counted rejection reasons; the only path to `AIService`
- **`AdaptiveBudget`** — Kneedle knee detection, mode-derived quality floor, marginal-value cutoff,
  policy clamps, and the small-`n` fixed fallback ([06f §2](06f-adaptive-budget.md))
- **`YieldCurve`** — `P(is_lead | prescore)` fitted from `lead_labels`; **inactive below 200 labels**,
  so a first run is governed by knee + floor alone
- **`Budget.method` persistence and display** — every binding constraint, plus the fixed-cut
  counterfactual, on the options screen and the run page
- **The ten explanation fields** ([06g §2](06g-explainability-and-quality.md)) — five computed
  locally, four closed-set slug selections, one constrained prose field
- **Closed-set validation** — a persona, pain, or signal slug outside the BKB fails validation
- **Deterministic `confidence_reasoning`** rendered from stored components, never model-written
- **Knowledge suggestions** — widened to the full set: aliases, new competitors, pain phrasings,
  customer language, Reddit terminology, objections, intent-signal examples. Written to
  `bkb_suggestions` as **proposals only**, never auto-applied, and only when a pattern clears
  **≥3 occurrences across ≥2 distinct dedup groups** ([06h §4.2](06h-knowledge-lifecycle.md))
- **Holdout-audited items persisted as real leads** (`leads.source='holdout_audit'`), labellable
  like any other — the exploration channel that stops the yield curve degenerating
  ([06i §1](06i-feedback-and-memory.md))
- **Version pinning** — `lead_analysis.bkb_id`, `weights_version`, `ruleset_version`, `tier`
- **Tier 2 enrichment** — un-batched, full-context analysis for leads ≥80 or on request, separately
  capped, and **never altering the confidence score** ([06i §3](06i-feedback-and-memory.md))
- **Batched enrichment** via `AIService.enrich_batch()`, B=8 measured ceiling
- **Batch-size golden-set sweep** at B ∈ {1, 4, 8, 12, 16} — the measurement that sets the default
- **Holdout audit** — 2% of rejects enriched anyway → published gate miss rate
- Duplicate-group fan-out: one analysis, N leads, **N distinct confidence scores**
- Incremental enrichment — a re-run only analyses genuinely new items
- `ConfidenceScorer` — the hybrid engine, pure Python
- Verbatim evidence validation; slug reconciliation
- Free re-scoring on a weight change (zero API calls)
- Lead table with confidence, enrichment filters, detail drawer with the full breakdown
- Cost cap and **402 balance** handling with partial-completion semantics
- Lazy `opportunity_summary` / `outreach_suggestion` on demand

### 2.2 Out of scope

- Export formats beyond CSV (Phase 8)
- Calibration report (Phase 8)
- `deepseek-v4-pro` deep re-analysis of top-N (config flag exists; UI in Phase 8)

## 3. Architecture

```
run.state = SCRAPING → ANALYZING
   └─► enqueue("enrich_leads", {run_id})

Worker: handle_enrich_leads
   │
   ├─ collect: leads + comments where analysis_status='pending'
   │
   ├─ PRE-FILTER (deterministic, zero cost)
   │     already_analyzed · too_short · bot_or_deleted · negative_term
   │     · structural_noise · out_of_window · downvoted
   │     → counts emitted to run_events and shown in the UI
   │
   ├─ CONTENT DEDUP
   │     group by sha256(normalised text); identical content → ONE analysis,
   │     linked to every matching lead. Crossposts and reposts cost nothing.
   │
   ├─ ContextBuilder.build(project)  → FROZEN prefix (sorted JSON, chunk-padded)
   ├─ estimate_cost() vs. per-run and per-day caps        → shown before starting
   │
   ├─ ai.enrich_batch(items, ctx, on_result=persist)
   │     ThreadPoolExecutor(max_workers=adaptive, default 8)
   │     futures = {executor.submit(analyze, it): it for it in items}
   │     for fut in as_completed(futures):
   │         item = futures[fut]         ◄── ATTRIBUTION. Never by position.
   │         persist(item, fut.result())
   │     ├─ 429/503 or p95 latency breach → halve concurrency
   │     ├─ InsufficientBalanceError → drain pool, preserve completed work
   │     └─ BudgetExceededError      → drain pool, preserve completed work
   │
   ├─ per item: verbatim evidence check · slug reconciliation · persist lead_analysis
   │
   ├─ ConfidenceScorer.score() for EVERY item (analysed or not)
   │     → leads.confidence_score / comments.confidence_score
   │
   └─ run.state = ANALYZING → COMPLETE  [+ partial_analysis flag if stopped early]
```

**There is no batch-submit / poll cycle.** DeepSeek has no batch endpoint; this is a single job
running a bounded pool ([02 §6.3a](02-research-findings.md)).

## 4. Files affected

**New**

| File | Purpose |
|---|---|
| `migrations/versions/0008_enrichment.py` | `lead_analysis` + partial unique indexes |
| `src/ai/prefilter.py` | Deterministic rules with reason counting |
| `src/scoring/confidence.py` | `ConfidenceScorer`, `ScoreWeights`, `ConfidenceBreakdown` |
| `src/orchestration/handlers/enrich.py` | `enrich_leads` |
| `src/db/repositories/analysis.py` | Incl. `analysis_by_content_hash` and `link_analysis` |
| `src/dashboard/templates/lead_detail.html` | Drawer with the hybrid breakdown |
| `tests/fixtures/golden_leads.jsonl` | 40 hand-labelled items |

**Modified**

| File | Change |
|---|---|
| `src/db/models.py` | +`LeadAnalysis` |
| `src/ai/service.py` | `enrich_batch` and `suggest_outreach` move from stub to implemented |
| `src/scoring/__init__.py` | Re-exports `LeadScorer` and `ConfidenceScorer` |
| `src/dashboard/routes_leads.py` | Confidence sort, enrichment filters, detail, re-analyse, rescore |
| `src/dashboard/templates/run_leads.html` | Confidence column, evidence row, chips, filters |
| `src/orchestration/handlers/scrape.py` | `finalize_run` → `ANALYZING` when AI is enabled |
| `config.yaml` | `scoring.weights` block |

## 5. Database changes

**`0008_enrichment`** — `lead_analysis` ([05 §5.5](05-database-plan.md)).

Partial unique indexes provide idempotency; create them with Alembic's `sqlite_where`, not raw SQL:

```python
op.create_index("ux_lead_analysis_lead", "lead_analysis", ["lead_id", "prompt_version"],
                unique=True, sqlite_where=sa.text("lead_id IS NOT NULL"))
```

Re-running at the same `prompt_version` collides and is skipped. Bumping the version produces a new
row and **preserves the old judgement for comparison**. `CHECK ((lead_id IS NOT NULL) <> (comment_id
IS NOT NULL))` enforces exactly one target.

`content_hash` is indexed with `prompt_version` — this is what makes "never analyse identical
content twice" a single indexed lookup.

## 6. APIs

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/leads` (extended) | `+min_confidence`, `buying_intent`, `urgency`, `icp_match`, `pain_slug`, `persona_slug`, `sentiment`, `sort=confidence` |
| `GET` | `/api/leads/<id>/detail` | Lead + analysis + breakdown + comments |
| `POST` | `/api/leads/<id>/enrich` | Sync re-analysis of one item |
| `POST` | `/api/leads/<id>/outreach` | Lazy `suggest_outreach` |
| `POST` | `/api/runs/<id>/enrich` | Re-enrich a whole run (e.g. after a prompt bump) |
| `POST` | `/api/runs/<id>/rescore` | **Recompute confidence with zero API calls** |
| `GET` | `/api/runs/<id>/enrichment-stats` | Pre-filter counts, analysed, failed, cost, cache-hit ratio, repair rate |
| `GET`/`PUT` | `/api/settings/score-weights` | Editable weights; must sum to 1.0 |

`POST /api/runs/<id>/rescore` is the payoff for AD-11: changing a weight re-ranks an entire run in
milliseconds at zero cost.

## 7. UI changes

**Lead table** ([09 §3.7](09-dashboard-plan.md)):
- Confidence badge, colour-graded, sorted descending by default
- **Evidence quote on the row** — the fastest human triage signal available
- Pain-point, persona, and urgency chips
- Filters: buying intent, urgency, ICP match, min confidence, pain point, persona, sentiment
- **NULL confidence sorts last**, never first
- Rows scored without AI show a small "no AI" marker rather than implying enrichment

**Lead detail drawer** ([09 §3.8](09-dashboard-plan.md)):
- Full hybrid breakdown — every component grouped by class (AI / rules / metrics / recency), with
  raw value, weight, and contribution
- Enrichment: summary, pain point, category, urgency, intent, ICP match, persona, competitors,
  sentiment, opportunity, priority
- Evidence quote with a "verified verbatim" tick, or "not verifiable" if flagged
- Suggested outreach angle (generated lazily on first open)
- Comments with their own scores
- `Re-analyse` button

**Score weights editor**: eleven sliders grouped by signal class, summing to 1.0, with `Rescore all`.

## 8. AI changes

### 8.1 The enrichment contract

`enrich_batch` returns one `LeadAnalysis` per input item
([06 §4](06-ai-pipeline.md)) — **categoricals only**. The rubric is stated verbatim in the prompt:

| `buying_intent` | Criteria |
|---|---|
| `unaware` | Discusses the domain, describes no problem we solve |
| `problem_aware` | Describes the pain, is not looking for a solution |
| `solution_aware` | Knows solutions exist, asking how others handle it |
| `evaluating` | Comparing named options, or asking for a recommendation |
| `ready_to_buy` | Explicit budget, timeline, or an active decision to switch |

Plus `urgency` (5), `icp_match` (4), `sentiment` (4), and `recommended_priority` (4) — each anchored
to observable text rather than to a felt sense.

`opportunity_score` (0–10) is the model's coarse holistic read. **It is one weighted input at 0.05,
not the score.** Letting it dominate would reintroduce the black box this design exists to avoid.

### 8.2 Prefix caching — where it finally pays off

Generation stages each had their own prefix and cached poorly. Enrichment sends the **same frozen
project context** thousands of times, so the 50× cache-hit discount applies to nearly the whole
input.

| Invariant | Verification |
|---|---|
| `context_block` built with `sort_keys=True`, fixed separators | Unit test |
| No timestamp, UUID, run id, or item id in the prefix | String-inspection test |
| Padded to a 64-token chunk boundary | Unit test |
| `prefix_hash` constant for the run | `PrefixDriftError` if not |
| `prompt_cache_hit_tokens > 0` from item 2 | Asserted; loud `run_events` warning and a red `/health/ai` indicator if not |

A silent cache miss here is the single most expensive failure in the product — it multiplies the
input bill by up to 50 while the run looks perfectly healthy.

### 8.3 Never analyse identical content twice

```python
h = sha256(normalise(item.text))
if existing := repo.analysis_by_content_hash(project_id, h, prompt_version):
    repo.link_analysis(item, existing)      # zero calls, zero cost
    continue
```

Covers crossposts, reposts, and quoted replies. Combined with the `already_analyzed` pre-filter rule
it also gives **incremental enrichment**: a re-run over a subreddit that gained 12 posts costs 12
calls, not 400.

### 8.4 Cost

| | |
|---|---:|
| Per item (3,000-token cached prefix, 500-token item, 250-token output) | **$0.000148** |
| 1,000 items | **≈ $0.15** |
| Typical run (1,200 items) | **≈ $0.18** |
| Re-run, unchanged | **$0.00** |

## 9. Backend changes

### 9.1 The hybrid confidence engine

Full design in [04 §9](04-system-design.md). Five signal classes, eleven components, one
deterministic function.

```
RULE-BASED (0.13) + AI (0.75) + REDDIT METRICS (0.05) + RECENCY (0.07)
                              ▼
                   ConfidenceScorer (pure Python)
                              ▼
                    confidence_score 0–100
```

**Properties, all property-tested:**
- Output always in `[0, 100]`, for every input including all-None
- An item with no analysis still scores from the 0.25 of non-AI weight — never NULL after scoring
- Rescoring 10,000 leads takes < 2 s and issues **zero** API calls
- Every component persisted, so the UI breakdown is stored data
- `has_ai` records which mode produced the score; the UI never presents a degraded score as full
- Weights not summing to 1.0 are rejected at save

### 9.2 Fallback and partial-completion discipline

| Condition | Behaviour |
|---|---|
| AI disabled / no key | `analysis_status='skipped'`; non-AI confidence; `intent_score` untouched |
| One item fails after repairs | `analysis_status='failed'`; non-AI confidence; retryable from the UI |
| Budget cap hit | Pool drains; completed work kept; run → `complete` + `partial_analysis`; UI offers to raise the cap |
| **402 insufficient balance** | Identical to the cap path, but the message is *"DeepSeek balance exhausted — add credit"* and Settings turns amber |
| 401 invalid key mid-run | Stop enrichment; mark key invalid; Settings turns red |

**A failure never discards completed work.** This is AD-9 made concrete.

### 9.3 Pre-filter reporting

```
1,240 collected → 612 eligible
   318 already analysed   190 negative term   74 too short   46 out of window
```

Emitted to `run_events` and shown on the run page. This makes the cost figure credible and a
mis-tuned negative list *visible* rather than mysterious.

### 9.4 Slug reconciliation

Slugs returned by the model are checked against the project's actual `personas`, `pain_points`, and
`intent_signals`. Unknown slugs are **dropped with a warning**, never used to create rows. A high
unknown-slug rate is surfaced as a prompt-quality signal.

## 10. Frontend changes

- Confidence column with colour grading and correct NULL ordering
- Evidence quote row with a verified/not-verifiable indicator
- Seven enrichment filters wired to query params
- `lead_detail.html` drawer, deep-linkable, with the class-grouped breakdown
- Enrichment stats panel on the run page (pre-filter counts, cost, cache-hit ratio, repair rate)
- Score-weights editor grouped by signal class with `Rescore all`

## 11. Risks

| Risk | Mitigation |
|---|---|
| **Concurrent result mis-attribution** | `futures[fut] → item`, never positional. **Blocking test** with shuffled completion order. |
| **Prefix cache stops hitting** → up to 50× cost | Asserted from item 2; `prefix_hash` constant; loud warning; red `/health/ai` |
| Cost overrun | Pre-run estimate + confirmation; per-run and per-day caps checked pre-call; live cost on the run page |
| **402 mid-run** | Distinct exception; pool drains; work preserved; amber Settings banner with a billing link |
| Model marks everything `is_lead=false` | Post-run distribution check → *"0 of 612 scored as leads — review your ICP"* |
| Hallucinated evidence | Verbatim substring check; flagged and blanked |
| Repair ladder thrash | `repair_rate` and `empty_content_rate` metrics with targets; a rising rate means revise the prompt |
| Scores uncalibrated | Every component visible and editable; calibration report in Phase 8 |
| V4 Flash too weak for the rubric | Golden-set measurement first; documented escalation to `deepseek-v4-pro` per stage |
| Re-analysis duplicates rows | Partial unique index on `(target, prompt_version)` |
| Legacy `intent_score` overwritten | `ConfidenceScorer` writes only `confidence_score`; test asserts all 459 unchanged |
| Adaptive concurrency oscillates | Halve-on-error, step-up-after-clean-window with hysteresis; floor 1, ceiling 16 |

## 12. Dependencies

**Upstream:** Phases 1–6. Phase 4's `personas` / `pain_points` / `intent_signals` are the enrichment
vocabulary; Phase 6's leads and comments are the input.

**New packages:** none.

## 13. Acceptance criteria

- [ ] AC1 — Enrichment completes on a run with > 500 items
- [ ] AC2 — Every enriched item has a `lead_analysis` row with valid enum values across all six categoricals
- [ ] AC3 — Confidence scores are in `[0, 100]` and rank sensibly
- [ ] AC4 — The displayed breakdown reconciles (within rounding) to the displayed score
- [ ] AC5 — `POST /api/runs/<id>/rescore` re-ranks with **zero** API calls in < 2 s for 10,000 leads
- [ ] AC6 — `prompt_cache_hit_tokens > 0` from the second item; ratio > 85% overall
- [ ] AC7 — **Results are correctly attributed under shuffled concurrent completion** (blocking test)
- [ ] AC7b — **Every batch element echoes its input `id`**; a length mismatch splits and retries
- [ ] AC7c — **AI calls per 1,000 collected posts ≤ 30** in `balanced` mode on a typical distribution
- [ ] AC7d — **Gate miss rate measured and < 5%**; `worst_reason` reported
- [ ] **AC7g — Adaptive budget correctness.** Each of the five distributions in [06f §4](06f-adaptive-budget.md) is replayed as a fixture and produces the documented `count` and `method`: strong→`knee`, flat→`knee+floor`, small-`n`→`fixed_threshold_small_n`, large→`knee`, degenerate→`knee+clamped_min`
- [ ] **AC7h — `ai_budgets` row written for 100% of runs**, including `method`, `knee_rank`, `floor_allows`, both clamps, and `fixed_would_admit`
- [ ] **AC7i — Clamps are a guard, not a budget.** Over a 20-run `balanced` sample, a clamp binds on < 10% of runs. *(Not asserted for `thorough`, which is designed to hit `max_admission_fraction` — [06f §3](06f-adaptive-budget.md).)*
- [ ] **AC7j — Yield curve gating.** With < 200 labels the marginal-value stage does not run and `method` contains no `+marginal`; with ≥ 200 it does
- [ ] **AC7k — Adaptive beats fixed where it should.** On the strong fixture, adaptive admits strictly more than the fixed ≥35 cut, and the holdout miss rate does not rise
- [ ] AC7e — Batch-size sweep executed; the shipped default is the largest B within 0.02 F1 of B=1
- [ ] AC7f — A duplicate group of N leads produces **1** analysis and **N distinct** confidence scores
- [ ] AC8 — Two items with identical text produce **one** analysis, linked to both
- [ ] AC9 — A re-run with 50 new items issues ≤ 50 calls
- [ ] AC10 — Pre-filter reduces the eligible set and reports every reason with counts
- [ ] AC11 — Every `evidence_quote` is verbatim, or blanked and flagged
- [ ] AC12 — Cost cap stops enrichment cleanly and preserves completed work
- [ ] AC13 — A simulated 402 preserves work and shows the amber balance state
- [ ] AC14 — With AI disabled, leads still receive non-AI confidence and `has_ai=false`
- [ ] AC15 — Re-enrichment at the same `prompt_version` is a no-op; a version bump adds rows and keeps the old ones
- [ ] AC16 — All 459 legacy `intent_score` values unchanged
- [ ] AC17 — Golden set: precision ≥ 0.7, recall ≥ 0.7 on `is_lead`
- [ ] **AC21 — All ten explanation fields populated** on every enriched lead, each with its documented provenance
- [ ] **AC22 — Closed-set enforcement.** An injected response containing an invented persona slug fails validation and triggers the repair ladder; it is never persisted
- [ ] **AC23 — `confidence_reasoning` is not model-written.** Grep confirms it is rendered by `scoring/explain.py`; its component values reconcile exactly to `leads.confidence_score`
- [ ] **AC24 — Locally-computed fields cost nothing.** `matched_product_features`, `matched_customer_language`, `matched_keyword_cluster`, and `competitor_mentions` are populated with **zero** additional AI calls
- [ ] **AC25 — Competitor alias resolution end to end.** A post using only an alias surface form (e.g. `"segement"`) produces a `competitor_mentions` entry resolved to the canonical entity, with the surface form retained
- [ ] **AC27 — Audit leads are labellable.** Holdout-enriched items persist with `source='holdout_audit'`, appear in the lead list with a badge, and accept labels
- [ ] **AC28 — The yield curve sees both sides of the cut.** A test inspects the fit query and **fails if it filters to admitted leads**; hash sampling is asserted uncorrelated with pre-score
- [ ] **AC29 — Version pinning.** Every `lead_analysis` row pins `bkb_id`, `weights_version`, `ruleset_version`; re-scoring from stored components reproduces the breakdown byte-identically
- [ ] **AC30 — Tier 2 is additive.** Tier 2 leaves `confidence_score` unchanged; Tier 2 failure leaves the Tier 1 analysis intact and displayed; the per-run cap holds
- [ ] **AC31 — Suggestions need distinct groups.** A pattern occurring 3× inside one dedup group raises **no** suggestion; 3× across 2 groups raises exactly one
- [ ] **AC26 — Suggestions never auto-apply.** Enrichment writes `bkb_suggestions` rows with `status='pending'`; no BKB section or alias changes until a `POST /api/projects/<id>/bkb/suggestions/<sid>` accept
- [ ] AC18 — Enrichment cost for 1,000 items **< $0.30**
- [ ] AC19 — 1,000 items enriched in < 8 minutes at default concurrency
- [ ] AC20 — All 17 legacy endpoints unchanged

## 14. Completion checklist

- [ ] Revision `0008_enrichment` with `ai_budgets`, partial unique indexes via `sqlite_where`, and the CHECK constraint
- [ ] `LeadAnalysis` schema with all six categorical enums **plus the ten explanation fields**
- [ ] `post_analysis` / `comment_analysis` prompts with the full rubric and `# JSON Shape`
- [ ] `scoring/knee.py` — Kneedle, returning `None` on a curve with no knee
- [ ] `scoring/budget.py` — knee × mode bias → floor → marginal → clamps, with `method` accumulation
- [ ] `scoring/yield_curve.py` — fitted from `lead_labels`; inactive below the label threshold
- [ ] `scoring/explain.py` — renders `confidence_reasoning` from stored components only
- [ ] Closed-set slug validators for persona / pain / signal / competitor
- [ ] Local matchers for features, customer language, and keyword cluster
- [ ] `bkb_suggestions` writer: proposals with evidence, `status='pending'`, thresholded on `distinct_groups`
- [ ] `feedback/yield_curve.py` fitted over **all** labelled leads, monotonicity enforced
- [ ] Holdout items persisted as leads with `source='holdout_audit'`
- [ ] Tier 2 path: un-batched, retrieval-only BKB context, own cap, cached on `(content_hash, prompt_version)`
- [ ] The five budget fixtures from [06f §4](06f-adaptive-budget.md) as regression tests
- [ ] Deterministic pre-filter with all seven rules and reason counting
- [ ] Content-hash dedup with `analysis_by_content_hash` + `link_analysis`
- [ ] Incremental enrichment verified
- [ ] `enrich_batch` with two-level attribution (`futures[fut]` → batch, echoed `id` → item) and the shuffled-order test
- [ ] Adaptive concurrency: halve on 429/503 or latency, step up on a clean window
- [ ] `InsufficientBalanceError` and `BudgetExceededError` drain the pool and preserve work
- [ ] Verbatim evidence validation; slug reconciliation with unknown-slug warnings
- [ ] `ConfidenceScorer` — eleven components across four signal classes
- [ ] `has_ai` recorded and surfaced
- [ ] Default weights in `config.yaml`, overridable, sum validated
- [ ] `rescore` endpoint with zero API calls
- [ ] `enrich_leads` handler
- [ ] Lazy `opportunity_summary` / `outreach_suggestion`
- [ ] Lead table: confidence, evidence, chips, seven filters, NULL-last ordering
- [ ] `lead_detail.html` with the class-grouped breakdown
- [ ] Score-weights editor + `Rescore all`
- [ ] Enrichment stats panel
- [ ] 40-item golden set + evaluation script
- [ ] `docs/testing/phase-07-testing.md` Part A complete
- [ ] `docs/testing/phase-07-testing.md` Part B executed and recorded
