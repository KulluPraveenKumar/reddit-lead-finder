# Phase 07 — Testing: Lead Enrichment & Hybrid Confidence Engine

---

# PART A — Claude Verification

## A1. Architecture

- [ ] Enrichment emits **categoricals only**; the final score is never model-emitted
- [ ] `ConfidenceScorer` is pure Python — `grep -in "ai\|deepseek\|provider" src/scoring/confidence.py` returns nothing
- [ ] `ConfidenceScorer` writes only `confidence_score`; **never** `intent_score`
- [ ] Pre-filter is a separate module, callable independently, with no I/O beyond the session
- [ ] Enrichment calls `AIService.enrich_batch()`; **no provider name appears in `src/orchestration/`**
- [ ] Nothing calls `AIService` without passing `PreAIGate` first (grep + test)
- [ ] `grep -ri "deepseek" src/ --exclude-dir=ai/providers` → still **0**
- [ ] There is **no** `submit_batch` / `poll_batch` handler and no `llm_batches` table
- [ ] Single-item and bulk paths build the **identical** request payload

## A2. Compilation and imports

- [ ] `python -c "import src.ai.prefilter, src.scoring.confidence"` succeeds
- [ ] `from src.scoring import LeadScorer` still works (backward-compatible re-export)

## A3. Lint / A4. Typing

- [ ] `ruff` clean
- [ ] `LeadAnalysis` uses `Literal` for all six categorical fields and `ge/le` for `opportunity_score`
- [ ] `ConfidenceBreakdown` typed with `components: dict[str, float]`
- [ ] `ScoreWeights` typed and summing to 1.0 (validated)

## A5. Edge cases

- [ ] Zero eligible items after pre-filter → analysis completes immediately, run → `complete`
- [ ] One eligible item → pool of size 1, no error
- [ ] Concurrency ceiling of 1 → still correct, just serial
- [ ] 10,000 items → pool processes all; results streamed, memory bounded
- [ ] Item text of exactly `MIN_CHARS` → boundary defined and consistent
- [ ] Model returns an unknown pain slug → dropped with a warning, rest of the analysis kept
- [ ] Model returns an unknown persona slug → `persona_slug` nulled
- [ ] Model returns an empty `evidence_quote` → accepted (valid when there is no quotable span)
- [ ] Model returns a non-verbatim quote → blanked, flagged `hallucinated_quote`
- [ ] Lead with no analysis → still scored from non-AI components, never NULL after scoring
- [ ] All weights zero → score 0 for everything, no divide-by-zero
- [ ] Weights not summing to 1.0 → rejected at save with a message
- [ ] Futures complete in shuffled order → **correctly attached via `futures[fut]`**
- [ ] One item raising → that item marked failed; the other futures still complete
- [ ] `InsufficientBalanceError` mid-pool → pool drains, completed work preserved
- [ ] Re-analysis at the same `prompt_version` → no-op (unique index)
- [ ] Comment and lead both analysed → separate rows, CHECK constraint holds

## A6. Error handling

- [ ] `SchemaValidationError` → item `failed`, run continues
- [ ] `BudgetExceededError` → analysis stops, completed work preserved, run → `complete` with `partial_analysis`
- [ ] **`InsufficientBalanceError` (402)** → stops enrichment, preserves work, amber UI state
- [ ] `InvalidAPIKeyError` (401) mid-run → stops enrichment, key marked invalid, red UI state
- [ ] AI disabled → all items `skipped`, non-AI scoring still applied

## A7. Security

- [ ] Model output rendered with autoescaping; **no `|safe` on `evidence_quote`, `reasoning`, or `suggested_angle`**
- [ ] `raw_json` not exposed via any API without sanitisation
- [ ] No API key appears in any log line emitted during a 1,000-item run
- [ ] Request payloads contain only public Reddit content plus project context

## A8. Performance

- [ ] `prompt_cache_hit_tokens > 0` from the second item onward; ratio > 85%
- [ ] `prefix_hash` identical across every call in a run
- [ ] Content-hash dedup prevents a second call for identical text
- [ ] Pre-filter runs before any API call
- [ ] Rescore of 10,000 leads completes in < 2 s with **zero** API calls
- [ ] `ix_leads_project_conf` used for the ranked query
- [ ] Lead list with 5,000 rows renders in < 300 ms

## A9. Scalability

- [ ] Adaptive concurrency has hysteresis — no oscillation under intermittent 429s
- [ ] Results persisted as futures complete, not in one giant transaction
- [ ] `lead_analysis` growth bounded by `prompt_version` (one row per item per version)
- [ ] `ai_cache` keyed by hash, not full text

## A10. Logging

- [ ] Pre-filter counts logged per reason
- [ ] Each analysis logs item id, outcome, tokens, cost, cache status
- [ ] Pool start / adaptation / drain logged with the ceiling at each change
- [ ] **Loud warning if `prompt_cache_hit_tokens` stays 0 after item 2**
- [ ] Unknown-slug rate logged

## A11. Retries

- [ ] Schema failure: 2 retries with the error appended
- [ ] Transport retries: 429/503 halve concurrency; 500/timeout back off
- [ ] `enrich_leads` job retryable up to 3; a retry never re-charges an already-analysed item
- [ ] 402 and 401 are **never** retried

## A12. Regression

- [ ] All 459 legacy `intent_score` values unchanged (asserted)
- [ ] Legacy leads have `confidence_score` computed from non-AI components only, or remain NULL if never rescored — documented and consistent
- [ ] `GET /` unchanged with no new filters applied
- [ ] CSV default export: 13 columns
- [ ] All 17 legacy endpoints unchanged
- [ ] Phases 1–6 suites pass

## A13. Test suite

- [ ] **Shuffled-completion attribution test present and passing**
- [ ] Property test: score always in `[0, 100]`
- [ ] Test: cached prefix contains no timestamp/UUID/id (string inspection)
- [ ] Golden-set evaluation script runs and reports precision/recall/F1
- [ ] Test: rescore issues zero provider calls (mock asserts call count == 0)
- [ ] Whole enrichment suite runs on `FakeProvider` with zero network calls

---

# PART B — Manual Testing

---

## Test 1 — Enrichment runs end to end

**Preconditions** A completed Phase-6 run with 200+ leads and comments; a validated DeepSeek key.

**Steps**
1. Ensure `ai.enabled: true` and the key shows ● Connected.
2. Let the run transition to `analyzing` (or trigger `POST /api/runs/<id>/enrich`).
3. Watch the progress page and the enrichment stats panel.
4. When complete, open `/runs/<id>/leads`.
5. `SELECT COUNT(*) FROM lead_analysis WHERE run_id=?;`

**Expected**
- Pre-filter panel shows collected → eligible with per-reason counts
- Concurrency pool starts at 8; the panel shows the current ceiling
- Analyses persist **progressively** as futures complete — the lead list fills in, not all at once
- Every row has valid values for all six categorical fields
- Leads ranked by `confidence_score` descending, NULLs last
- Run → `complete`

**Failure behaviour**
- Stuck in `analyzing` → check the job's error and the pool's current ceiling
- 0 analyses → check the pre-filter; it may be excluding everything
- All items `failed` → schema mismatch; read the recorded repair errors

**Edge cases**
- 1 eligible item → pool of size 1, completes
- 0 eligible → completes immediately with a clear message
- Run with comments → comments enriched too, as separate rows with `comment_id` set

**Success criteria** Every eligible item enriched; leads ranked; results appear progressively.

---

## Test 2 — Concurrent result attribution *(CRITICAL)*

This replaces the batch-keying test. With a thread pool, mis-attribution is the same catastrophic
failure by a different mechanism.

**Steps**
1. `pytest tests/unit/test_enrichment_attribution.py -v` — the automated test submits N items whose
   futures complete in deliberately shuffled order and asserts each result lands on its own item.
2. Pick 5 enriched leads with distinctive titles.
3. For each, read `lead_analysis.evidence_quote`, `summary`, and `reasoning`.
4. Read the lead's actual title and body.
5. Confirm the analysis unmistakably describes **that** lead.
6. Confirm the evidence quote appears in **that** lead's text.

**Expected**
- The shuffled-order test passes
- 5/5 analyses correctly attributed
- Every evidence quote is found in its own lead's text

**Failure behaviour**
- An analysis describing a different post → **critical defect**: results attributed by position
  rather than through the `futures[fut]` map. Every ranking in the product is meaningless.
  **Stop and fix before anything else.**

**Edge cases**
- Two leads with identical titles → distinguished by the future map, not by text
- One item raising mid-pool → the others still land correctly
- Pool ceiling reduced mid-run by adaptation → attribution unaffected

**Success criteria** Perfect attribution under shuffled concurrent completion.

---

## Test 3 — Prefix caching is actually working

**Preconditions** A run with ≥ 20 eligible items.

**Steps**
1. Run enrichment.
2. `SELECT stage, input_tokens_uncached, input_tokens_cached, prefix_hash FROM ai_calls
    WHERE stage='post_analysis' ORDER BY id LIMIT 20;`
3. Compare row 1 against rows 2–20.
4. Compute the cache-hit ratio; compare with `/health/ai`.
5. Check `run_events` and the logs for a cache-miss warning.
6. Confirm every row shares the same `prefix_hash`.

**Expected**
- Row 1: `input_tokens_cached` ≈ 0, `input_tokens_uncached` large
- Rows 2+: `input_tokens_cached` large (≈ the context size), `input_tokens_uncached` small
- Cache-hit ratio > 85%; `/health/ai` shows it green
- **Identical `prefix_hash` on every row**
- No cache-miss warning

**Failure behaviour**
- `input_tokens_cached` stays 0 → **the input bill is up to 50× the estimate.** Inspect the system
  prefix for a timestamp, UUID, run id, item id, or non-deterministic JSON ordering.
- `prefix_hash` varies → `PrefixDriftError` should have fired; if it did not, that guard is broken
- Prefix under the minimum → caching correctly skipped, and a log line must say so

**Edge cases**
- Very small project context → caching skipped with an explicit log line
- Model changed mid-run → should be impossible; verify it is prevented

**Success criteria** Cache reads confirmed from item 2; ratio > 85%; prefix hash constant.

---

## Test 4 — Never analyse identical content twice

**Steps**
1. Find or create two leads with byte-identical body text (a crosspost is ideal).
2. Run enrichment.
3. `SELECT COUNT(*) FROM lead_analysis WHERE content_hash = ?;`
4. Confirm both leads display the same analysis.
5. Count `ai_calls` rows for the stage; confirm only one call was made for that content.

**Expected**
- **One** `lead_analysis` row for the shared content hash
- Both leads render that analysis
- Exactly one provider call for the pair
- The dedup is visible in the stats panel

**Failure behaviour**
- Two analyses → content dedup not applied; every crosspost is paid for twice
- Only one lead shows an analysis → the link step is missing

**Edge cases**
- Identical text, different subreddits → still deduped (content hash ignores subreddit)
- Text differing only by trailing whitespace → normalised, still deduped
- Same text, different `prompt_version` → new analysis, correctly

**Success criteria** One call, one analysis, both leads served.

---

## Test 5 — Incremental enrichment

**Steps**
1. Note the `ai_calls` count and cost after a completed run.
2. Re-trigger enrichment on the same run with no new data.
3. Recount.
4. Scrape again so ~50 new posts arrive; re-trigger.
5. Recount.

**Expected**
- Step 2: **zero** new provider calls, **$0.00** — everything already analysed at this version
- Step 4: at most 50 new calls, proportional cost
- The stats panel reports `already_analyzed` for the rest

**Failure behaviour**
- Full re-analysis on step 2 → the `already_analyzed` pre-filter rule or the version check is broken;
  every re-run costs full price

**Edge cases**
- Prompt version bumped → full re-analysis is correct, and the old rows are retained
- Half the items previously failed → only those are retried

**Success criteria** Re-runs cost near zero; only genuinely new items are charged.

---

## Test 6 — Confidence score and hybrid breakdown

**Steps**
1. Open `/runs/<id>/leads`; note the top lead's confidence.
2. Open its detail drawer.
3. Read all eleven components, grouped by class (AI / rules / metrics / recency).
4. Manually compute `100 × Σ(weight × value)`.
5. Compare with the displayed total.
6. Repeat for a mid-range and a low lead.
7. Find a lead with no analysis; confirm it still has a score and shows a "no AI" marker.

**Expected**
- Manual computation matches within rounding
- All eleven components shown with value, weight, and contribution
- Class subtotals visible (AI 0.75 / rules 0.13 / metrics 0.05 / recency 0.07)
- Any penalty multiplier shown explicitly
- Unanalysed leads score from the 0.25 non-AI weight and are marked

**Failure behaviour**
- Numbers do not reconcile → the UI recomputes instead of reading stored components
- Score above 100 or below 0 → clamping missing
- Unanalysed lead shows no score → the non-AI path is not running

**Edge cases**
- `ready_to_buy` + 3 pain matches → near the top of the range
- All AI components zero, strong keyword score → mid-low but non-zero

**Success criteria** Score fully reproducible from the displayed breakdown.

---

## Test 7 — Free re-scoring

**Steps**
1. Record `SELECT COUNT(*) FROM ai_calls;` and the run cost.
2. Open the score-weights editor; raise `intent` from 0.22 to 0.35 and reduce others to compensate.
3. Save; click **Rescore all**. Time it.
4. Watch the lead ordering change.
5. Recount `ai_calls` and recheck the cost.
6. Try saving weights that sum to 1.2.

**Expected**
- Rescore completes in < 2 s for 10,000 leads
- Ordering visibly changes
- **`ai_calls` count unchanged; cost unchanged**
- Weights not summing to 1.0 rejected with a message

**Failure behaviour**
- New `ai_calls` rows → rescore is re-running enrichment, defeating the entire design
- Ordering unchanged → weights not applied

**Edge cases**
- `intent` at 1.0, everything else 0 → ranking driven purely by buying-intent stage
- Rescore with 0 analysed leads → still works from non-AI components

**Success criteria** Re-ranking is instant and free.

---

## Test 8 — Verbatim evidence

**Steps**
1. Pick 5 leads with non-empty evidence quotes.
2. Copy each quote; search for it in the lead's stored body and on Reddit.
3. Check for any lead flagged `hallucinated_quote`.
4. Confirm flagged quotes render as "not verifiable", not as normal quotes.

**Expected**
- 5/5 quotes found verbatim
- Flagged rate < 5%
- Flagged quotes clearly marked in the UI

**Failure behaviour**
- A quote absent from the source **and not flagged** → the verbatim validator is not running

**Edge cases**
- Quote with different whitespace → normalised comparison still passes
- Quote from a comment attached to a comment analysis → validated against the comment text

**Success criteria** All displayed quotes verifiable; unverifiable ones marked.

---

## Test 9 — Cost cap and 402 balance

**Steps**
1. Set `ai.budget.max_cost_per_run_usd: 0.02`. Start enrichment on a large run.
2. Watch the cost counter approach the cap.
3. Observe behaviour at the cap; check the run state and leads.
4. Raise the cap; click "Continue analysis".
5. **Simulate a 402** (test harness or an exhausted account). Repeat 1–3.

**Expected — cost cap**
- Enrichment stops at the cap
- Run → `complete` with `partial_analysis` (**not** `failed`)
- Already-enriched leads keep their scores; the rest keep non-AI scores
- UI offers to raise the cap; continuing enriches only the remainder

**Expected — 402**
- Identical preservation semantics
- Message: *"DeepSeek balance exhausted — add credit"*
- `/settings/ai` turns **amber**, not red
- 402 is **not retried**

**Failure behaviour**
- Run marked `failed` → completed work is devalued
- Analyses discarded → data loss
- 402 retried with backoff → wastes minutes on an error that cannot self-resolve
- 402 shown as an invalid key → sends the operator to the wrong remedy

**Edge cases**
- Cap below the cost of one item → stops immediately with a clear message
- Credit added mid-run and Retest clicked → resumes without re-entering the key

**Success criteria** Both stop paths preserve work and give the correct remedy.

---

## Test 10 — Pre-filter effectiveness

**Steps**
1. Read the pre-filter panel on the run page.
2. Note counts per exclusion reason.
3. Sample 5 excluded items; verify each exclusion is correct.
4. Temporarily clear all negative terms; re-run on a copy; compare counts, cost, and result quality.

**Expected**
- Panel shows collected → eligible with every reason and count
- Each sampled exclusion is genuinely correct
- Without negatives: more eligible, higher cost, visibly more junk in the results

**Failure behaviour**
- All items eligible → pre-filter not running; cost far above plan
- Legitimate leads excluded → a negative term is too broad — the panel makes this visible, which is
  exactly its purpose

**Edge cases**
- Item exactly at `MIN_CHARS` → boundary consistent
- Item just outside the time window → excluded with the right reason

**Success criteria** Meaningful reduction with correct, inspectable reasons.

---

## Test 11 — Lead quality *(the product test)*

**Preconditions** A completed, enriched run for a product you understand.

**Steps**
1. Open `/runs/<id>/leads` sorted by confidence.
2. Read the **top 20**: title, evidence quote, buying intent, urgency.
3. For each, judge: *would I actually reach out to this person?*
4. Record the count of genuine leads.
5. Read the **bottom 20**; judge whether they are correctly ranked low.
6. Check that no obviously excellent lead is buried.

**Expected**
- ≥ 12 of the top 20 (60%) genuinely relevant
- `ready_to_buy` items really do show urgency
- Bottom-ranked items genuinely weak
- No obvious inversion

**Failure behaviour**
- < 40% relevance → the ICP, the pain phrasing, or the enrichment prompt is mis-targeted. Check the
  pain-point `how_people_phrase_it` first; it is the most common cause.
- Ranking looks random → weights or component values wrong; go back to Test 6

**Edge cases**
- Niche product → fewer leads, relevance should still hold
- All leads `problem_aware` → keywords may be too generic

**Success criteria** ≥ 60% of the top 20 actionable.

---

## Test 12 — Golden-set evaluation

**Steps**
1. `python scripts/eval_prompts.py --stage post_analysis --version 1`
2. Read precision, recall, F1 on `is_lead`.
3. Read mean absolute error on `buying_intent`.
4. Read hallucinated-quote rate, repair rate, and empty-content rate.

**Expected**
- Precision ≥ 0.70, recall ≥ 0.70
- Hallucinated-quote rate < 5%
- Repair rate < 5%; empty-content rate < 2%
- Mean intent error < 0.25 on the 0–1 mapping

**Failure behaviour**
- Recall < 0.5 → the prompt is too conservative
- Precision < 0.5 → the rubric is too loose
- Repair rate > 15% → the `# JSON Shape` section needs to be clearer

**Edge cases**
- Run against a v2 prompt → compare side by side before shipping

**Success criteria** All thresholds met on v1.

---

## Test 13 — Fallback without AI

**Steps**
1. Set `ai.enabled: false` (or clear the API key). Run a full scrape.
2. Observe the run at the enrichment stage.
3. Open the leads list; check `analysis_status`, `confidence_score`, and the "no AI" marker.
4. Re-enable AI and re-enrich.

**Expected**
- Run skips enrichment and goes to `complete`
- All items `analysis_status='skipped'`
- `confidence_score` computed from the non-AI components; **not NULL**
- `has_ai=false` surfaced in the UI
- `intent_score` unchanged
- Re-enabling and re-enriching upgrades the scores

**Failure behaviour**
- Run fails → AI must be optional
- All confidence NULL → the non-AI path is not applied
- `intent_score` altered → the frozen column was written

**Success criteria** Fully functional keyword-only mode with honest labelling.

---

## Test 14 — Idempotent re-enrichment

**Steps**
1. Record `SELECT COUNT(*) FROM lead_analysis;` and `SELECT COUNT(*) FROM ai_calls;`
2. Trigger `POST /api/runs/<id>/enrich` again. Recount both.
3. Bump `prompt_version` for `post_analysis` in settings. Re-enrich. Recount.
4. Query both versions for one lead.

**Expected**
- Same version: **zero** new `lead_analysis` rows, zero new provider calls
- After the bump: one new row per item; **old rows retained**
- Both versions queryable side by side

**Failure behaviour**
- Duplicate rows at the same version → the partial unique index is missing
- Old rows deleted on bump → history destroyed, comparison impossible

**Edge cases**
- Re-enrich a single lead via the UI → one row per version
- Version bump with a worse prompt → old results still intact for comparison

**Success criteria** Same version is a no-op; a new version is purely additive.

---

---

## Test 15 — AI call budget *(the headline efficiency test)*

**Preconditions** A run collecting ~1,000 items, `balanced` mode.

**Steps**
1. `SELECT COUNT(*) FROM ai_calls WHERE run_id=?;` before enrichment.
2. Run enrichment to completion.
3. Re-query. Compute calls per 1,000 collected posts.
4. Read the run's cost.
5. Compare against the naive baseline (1 call per collected post).
6. Repeat in `thorough` and `frugal` modes on copies.

**Expected**
- **≤ 25 calls per 1,000 collected posts** in `balanced`
- Cost ≤ $0.05 per 1,000 collected
- `thorough` roughly 4× the calls, `frugal` roughly ¼ — all three within their documented bands
- The run page reports calls, cost, and calls-per-1,000

**Failure behaviour**
- \> 100 calls per 1,000 → batching or the gate is not engaged; check `gate_decision` counts
- Calls ≈ collected count → the gate is admitting everything
- Cost ≫ estimate → check `prompt_cache_hit_tokens`; a cold cache inflates it

**Edge cases**
- All items unique and high-scoring → more calls, correctly; the budget cap engages
- Second run, nothing new → **0 calls**

**Success criteria** ≤ 25 calls per 1,000 collected, with the funnel counts explaining why.

---

## Test 16 — Batch integrity

**Steps**
1. Enable DEBUG logging; run enrichment.
2. Confirm requests carry 8 items and responses 8 results.
3. Via the harness, script a response with 7 results for an 8-item batch.
4. Script a response with an unknown `id`.
5. Script a response with a duplicated `id`.
6. Observe handling of each.
7. Verify every stored analysis matches its own item's `id`.

**Expected**
- Normal batches: 8 in, 8 out, every `id` echoed
- 7-of-8 → **batch-level failure**, split into two 4-item batches, both retried
- Unknown `id` → batch rejected and split
- Duplicated `id` → batch rejected and split
- After split-and-retry, all 8 items end up analysed
- No analysis is ever attributed to the wrong item

**Failure behaviour**
- 7 results silently accepted → **silent lead loss**; the most dangerous batching defect
- Batch failure loses all 8 items → split-and-retry not implemented
- Analysis attached to the wrong item → critical; stop and fix

**Edge cases**
- Split reaching B=1 → behaves exactly like the unbatched path
- Whole batch fails at B=1 → that single item marked failed, others unaffected

**Success criteria** Every anomaly detected; no silent partial success.

---

## Test 17 — Batch-size sweep

**Steps**
1. `python scripts/eval_batch_size.py --sizes 1,4,8,12,16`
2. Read precision, recall, F1, mean output tokens, and length-mismatch rate per B.
3. Identify the largest B within 0.02 F1 of B=1.
4. Confirm the shipped default matches it.

**Expected**
- F1 stable at low B, declining at high B
- A documented recommendation with numbers behind it
- The configured default equals the measured recommendation

**Failure behaviour**
- Default not equal to the measured value → the config is a guess; the brief explicitly forbids it
- F1 flat across all B → the golden set is too easy to discriminate; strengthen it

**Success criteria** The default batch size is justified by published measurements.

---

## Test 18 — Holdout audit and gate miss rate

**Steps**
1. After enrichment, read `SELECT * FROM gate_audits WHERE run_id=?;`
2. Note `sampled`, `would_have_qualified`, `gate_miss_rate`, `worst_reason`.
3. Manually inspect 3 rejects that the audit says *would* have qualified.
4. Judge whether they are genuinely leads.
5. Tighten the gate to `frugal`; re-run; observe the miss rate move.
6. Confirm the warning fires above threshold.

**Expected**
- ~2% of rejects sampled, deterministically (reproducible per run)
- `gate_miss_rate` computed and displayed on the run page and `/health/ai`
- `worst_reason` names the most over-aggressive rejection rule
- `frugal` shows a **higher** miss rate than `balanced` — the trade is visible
- Above threshold → explicit warning suggesting `thorough`
- `already_analyzed` / `duplicate_*` / `budget_exhausted` are **never** sampled

**Failure behaviour**
- No audit row → the only quality guarantee in the design is missing
- Miss rate always 0 with a tight gate → sampling is not actually re-admitting rejects
- Provably-correct rejections sampled → wasted calls proving arithmetic works

**Edge cases**
- Fewer than 50 rejects → sample everything, or report "insufficient sample"
- Miss rate 0% on a large sample → the gate is safe; consider tightening for cost

**Success criteria** A real, reproducible miss rate with an actionable `worst_reason`.

---

## Test 19 — Duplicate-group fan-out with distinct scores

**Steps**
1. Find a `dedup_group` with ≥ 3 members.
2. `SELECT COUNT(*) FROM lead_analysis WHERE ...` for those members.
3. `SELECT id, confidence_score FROM leads WHERE id IN (...);`
4. Compare the members' recency, upvotes, and subreddits.
5. Open one in the UI; confirm the "similar discussions (N)" affordance.

**Expected**
- **Exactly one** `lead_analysis` row for the group
- All members linked to it
- **Distinct `confidence_score` values** reflecting their own recency, engagement, subreddit fit
- The UI discloses the grouping rather than hiding it

**Failure behaviour**
- N analyses → dedup did not prevent the calls; the saving is not real
- N identical confidence scores → the score was collapsed with the analysis. **This is the subtle
  quality bug**: three genuinely different-value leads presented as identical, and the operator
  correctly stops trusting the ranking.
- Grouping invisible in the UI → the user cannot tell why a lead looks familiar

**Success criteria** One analysis, N leads, N distinct scores, visible grouping.

---

## Test 20 — Adaptive budget across five distributions

**Test case** The admission count is derived correctly, and every degenerate case is caught.

**Preconditions** The five pre-score fixtures from [06f §4](../06f-adaptive-budget.md), replayable
without scraping.

**Steps**
For each fixture, run the budget calculation in `balanced` mode and record `count` and `method`:

| Fixture | Expect count | Expect method |
|---|---:|---|
| A — strong, `n`=329, knee 214 | 214 | `knee` |
| B — flat, `n`=402, knee 310, floor allows 47 | 47 | `knee+floor` |
| C — small, `n`=31 | 22 | `fixed_threshold_small_n` |
| D — large, `n`=900, marginal allows 705 | 690 | `knee` |
| E — degenerate, `n`=250, knee 3 | 13 | `knee+clamped_min` |

6. For A, also record what the fixed ≥35 cut would admit (expect 180).
7. Confirm an `ai_budgets` row exists for each with all decision fields populated.

**Expected**
- Every count and method matches exactly
- Fixture A admits **more** than the fixed cut — the case a fixed threshold handles worst
- Fixture E is clamped up from 3 to 13, and the method **says so**

**Failure behaviour**
- E returning 3 → the min clamp is missing, and a nonsensical run would look like a cheap one
- C running knee detection → the small-`n` bypass is missing; Kneedle on 31 points is noise
- `method` not recorded → the number is unexplainable, which is the defect
  [06f](../06f-adaptive-budget.md) exists to prevent

**Edge cases**
- All pre-scores identical → `knee_index` returns `None`, method is `fixed_threshold_no_knee`
- `n` exactly 200 → adaptive runs (boundary is inclusive), documented and asserted
- Cost ceiling below the knee → `+clamped_max`, and the run page explains it

**Success criteria**
- All five fixtures produce their documented count and method; `ai_budgets` fully populated

---

## Test 21 — Explanations are faithful, grounded, and closed-set

**Test case** No lead can carry an explanation the computation does not support.

**Preconditions** An enriched run; a `FakeProvider` able to inject crafted responses.

**Steps**
1. Open a high-confidence lead. Confirm all ten explanation fields render.
2. Sum the components in `confidence_reasoning`; compare to `leads.confidence_score`.
3. Confirm the five locally-computed fields are populated, and that
   `SELECT COUNT(*) FROM ai_calls` did not increase when they were.
4. Inject a response naming a persona slug **not** in the BKB.
5. Inject an `evidence_quote` that is not a substring of the post.
6. Inject a `why_relevant` referencing a pain point not in `matched_pain_points`.
7. Click each `↗` and confirm it opens the defining BKB section.

**Expected**
- Step 2: reconciles within rounding — the breakdown *is* the arithmetic
- Step 4: validation fails, the repair ladder fires, the invented slug is **never persisted**
- Step 5: the span is dropped, the lead survives, `hallucinated_span_rate` increments
- Step 6: rejected by the constraint validator, or the reference stripped
- Step 7: every link resolves to a real section with its source evidence

**Failure behaviour**
- Breakdown not reconciling → the displayed explanation is decorative, not the computation, and the
  central explainability claim ([AD-15](../03-architecture.md)) is false
- An invented slug persisting → explanations become unjoinable and the BKB link chain breaks
- Local fields costing a call → the AI is doing work Python should do

**Edge cases**
- A lead with no competitor mention → the field is empty, not fabricated
- A lead scoring 0 on every AI component → `confidence_reasoning` still renders, all zeros
- A BKB regenerated after the lead was scored → links resolve to the **pinned** version, not a dangling ref

**Success criteria**
- Explanations reconcile exactly; every fabrication path is blocked and counted

---

## Test 22 — Knowledge suggestions are proposed, never applied

**Test case** Learned knowledge cannot modify the BKB without an operator.

**Preconditions** An enrichment run that encounters an unregistered competitor alias and a novel
high-confidence pain phrasing.

**Steps**
1. Run enrichment. Query `bkb_suggestions`.
2. Snapshot `bkb_entity_aliases` and the `pain_points` phrasings **before** and **after** the run.
3. Open the Knowledge Suggestions panel; confirm each proposal shows its evidence lead and span.
4. Accept one; reject one.
5. Re-check the alias table and section versions.

**Expected**
- After step 1: rows exist with `status='pending'`
- After step 2: the before/after snapshots are **identical** — the run changed nothing
- After step 4: the accepted proposal appears with `source='confirmed'` and bumps the section
  version; the rejected one is marked `rejected` and never applied

**Failure behaviour**
- Any BKB change during step 1 → self-modification is live, and one mis-scored lead can now poison
  the knowledge base permanently and silently (R24)
- Proposals without evidence → the operator cannot judge them and will accept blindly

**Edge cases**
- The same alias proposed twice → `occurrences` increments; one row, not two
- A proposal whose entity was deleted → the proposal is invalidated, not orphaned

**Success criteria**
- Zero BKB mutations from enrichment; acceptance is the only write path

---

## Test 23 — The exploration channel closes the learning loop

**Test case** Holdout-audited items become labellable leads, and the yield curve sees them.

**Preconditions** A run large enough for a real holdout sample (≥200 candidates).

**Steps**
1. Run enrichment. Query `leads WHERE source='holdout_audit'`.
2. Open the lead list; confirm audit leads appear with a badge.
3. Label two of them — one `interested`, one `not_relevant`.
4. Inspect the `YieldCurve` fit query.
5. Fit the curve; confirm the labelled audit leads are in its input set.
6. Correlate the hash sample against pre-score across a synthetic distribution.

**Expected**
- Audit items are persisted as real leads, scored normally, badged in the list
- Step 4: **the query has no predicate restricting it to admitted leads.** A test fails if one exists
- Step 5: audit labels contribute on equal footing with admitted-lead labels
- Step 6: sampling is uncorrelated with pre-score (|r| < 0.1)

**Failure behaviour**
- Audit items not appearing as leads → the audit produces a metric and **zero learning signal**; the
  yield curve is fitted only above the cut, learns the shape of its own gate, and narrows every
  cycle. Precision would never reveal it, because precision is also measured only above the cut.
  This is R27, and it is the defect the final research pass existed to find
- Sampling correlated with pre-score → it is not exploration, it is a second gate

**Edge cases**
- Zero rejects (tiny run) → no audit leads, curve unchanged, no error
- An audit lead scoring above the display threshold → shown normally; the badge explains its presence
- Fewer than 200 labels overall → the curve does not activate at all, as specified

**Success criteria**
- The loop is closed: exploration produces labels, and the labels reach the curve

---

## Test 24 — Version pinning and reproducibility

**Test case** A decision made today is reconstructible after the world moves on.

**Preconditions** A completed enriched run.

**Steps**
1. Note a lead's score, breakdown, and matched entity links.
2. Confirm its `lead_analysis` row pins `bkb_id`, `weights_version`, `ruleset_version`, `prompt_version`.
3. Re-score from stored components; diff the breakdown against step 1.
4. **Regenerate the BKB**, materially changing a pain-point definition.
5. Reopen the lead. Follow its entity links.
6. Score a new lead; compare its pinned `bkb_id` to the old one.

**Expected**
- Step 3: **byte-identical** breakdown
- Step 5: links resolve to the **pinned** BKB version — the definition as it was when the lead was
  scored — not to current knowledge
- Step 6: different `bkb_id`; both leads remain individually explainable

**Failure behaviour**
- Step 5 showing the *new* definition → the explanation confidently cites something that did not
  exist when the lead was scored. **Worse than a broken link**, because it looks correct (R30)
- Step 3 differing → scoring is not deterministic; something reads the wall clock or a mutable global

**Edge cases**
- A pinned BKB version deleted → the link degrades to "knowledge base version no longer available",
  never to silently-current
- `weights_version` bumped after scoring → old leads keep their old breakdown until re-scored

**Success criteria**
- Every analysis pins four versions; historical explanations stay historically accurate

---

## Test 25 — Tier 2 is additive and capped

**Test case** Deep analysis enriches presentation without disturbing ranking.

**Preconditions** A run with ≥20 leads scoring ≥80.

**Steps**
1. Record the full ranked list with scores.
2. Let Tier 2 run on qualifying leads.
3. Re-record the list; diff order and scores.
4. Set `max_tier2_items_per_run: 5` and re-run; count Tier 2 analyses.
5. Force a Tier 2 failure on one lead; open it.
6. Re-run the whole thing; count new Tier 2 API calls.

**Expected**
- Step 3: **scores and ordering identical.** Tier 2 adds fields, never numbers that feed the score
- Step 4: exactly 5 items deepened; the rest keep Tier 1 output
- Step 5: the lead shows its Tier 1 analysis normally, with a quiet note that deep analysis failed
- Step 6: **zero** new calls — Tier 2 output is cached on `(content_hash, prompt_version)`

**Failure behaviour**
- Any score or order change → two leads with identical evidence now rank differently depending on
  which tier happened to run, destroying comparability (R31)
- Cap not holding → a strong run escalates hundreds of items un-batched
- Tier 2 failure hiding the lead → an enhancement became a dependency

**Edge cases**
- Zero leads ≥80 → Tier 2 never runs, no error, no cost
- Operator requests Tier 2 on a lead scoring 40 → allowed, counted against the cap
- Cost cap reached mid-Tier-2 → stops cleanly, completed work preserved

**Success criteria**
- Tier 2 changes what is shown, never what is ranked; cap and cache both hold

---

## Sign-off

| Test | Result | Notes |
|---|---|---|
| 1 Enrichment E2E | ☐ Pass ☐ Fail | |
| 2 **Concurrent attribution** | ☐ Pass ☐ Fail | **Critical** |
| 3 **Prefix caching** | ☐ Pass ☐ Fail | **Cost-critical** |
| 4 Content dedup | ☐ Pass ☐ Fail | |
| 5 Incremental enrichment | ☐ Pass ☐ Fail | |
| 6 Hybrid breakdown | ☐ Pass ☐ Fail | |
| 7 Free re-scoring | ☐ Pass ☐ Fail | |
| 8 Verbatim evidence | ☐ Pass ☐ Fail | |
| 9 Cost cap & 402 | ☐ Pass ☐ Fail | |
| 10 Pre-filter | ☐ Pass ☐ Fail | |
| 11 **Lead quality** | ☐ Pass ☐ Fail | Product test |
| 12 Golden set | ☐ Pass ☐ Fail | |
| 13 No-AI fallback | ☐ Pass ☐ Fail | |
| 14 Idempotent re-enrichment | ☐ Pass ☐ Fail | |

| 15 **AI call budget** | ☐ Pass ☐ Fail | **Efficiency headline** |
| 16 **Batch integrity** | ☐ Pass ☐ Fail | **Critical** |
| 17 Batch-size sweep | ☐ Pass ☐ Fail | |
| 18 **Holdout audit** | ☐ Pass ☐ Fail | **Quality guarantee** |
| 19 Group fan-out | ☐ Pass ☐ Fail | |
| 20 **Adaptive budget, 5 distributions** | ☐ Pass ☐ Fail | **Blocking** |
| 21 **Faithful explanations** | ☐ Pass ☐ Fail | **Blocking** |
| 22 **Suggestions never auto-apply** | ☐ Pass ☐ Fail | **Blocking** |
| 23 **Exploration closes the loop** | ☐ Pass ☐ Fail | **Blocking** — R27 |
| 24 **Version pinning** | ☐ Pass ☐ Fail | **Blocking** — R30 |
| 25 **Tier 2 additive** | ☐ Pass ☐ Fail | |

**Phase 7 complete when Part A is fully ticked and all 25 Part B tests pass.**
