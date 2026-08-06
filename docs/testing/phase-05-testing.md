# Phase 05 — Testing: Subreddit Discovery, Keywords & Review Gates

---

# PART A — Claude Verification

## A1. Architecture

- [ ] `src/discovery/` depends on `RedditClient` and `AIService`, nothing above
- [ ] The three channels are separate methods with independent failure handling
- [ ] `Validator` is the only place a candidate can be rejected
- [ ] `Ranker` is pure — same inputs, same score, no I/O
- [ ] Gate approval flows through `RunService`, never by writing `runs.state` directly
- [ ] `KeywordGenerator` is in `src/ai/`, not `src/discovery/`

## A2. Compilation and imports

- [ ] `python -c "import src.discovery, src.ai.keyword_generator"` succeeds
- [ ] `RedditClient.get_related_subreddits` added without changing existing signatures
- [ ] Gate blueprints registered

## A3. Lint / A4. Typing

- [ ] `ruff` clean
- [ ] `SubredditCandidate` is a typed dataclass with a `channels: set[str]`
- [ ] Rank components typed `dict[str, float]`
- [ ] `RunOptions` fully typed with defaults

## A5. Edge cases

- [ ] LLM proposes 0 subreddits → channels 2 and 3 still run
- [ ] All LLM proposals invalid → rejected list shows all; user can still add manually
- [ ] Channel 2 returns 0 results → no crash; hit density all zero
- [ ] Sidebar has no related links → channel 3 contributes nothing, no error
- [ ] Candidate name with mixed case → normalised to lowercase for dedup
- [ ] Candidate name with `r/` prefix or trailing `/` → stripped
- [ ] Candidate name with invalid characters → rejected before the request
- [ ] Subreddit with exactly `MIN_SUBS` members → boundary defined and consistent
- [ ] Private subreddit → `inaccessible`, not `not_found`
- [ ] Banned subreddit → `inaccessible`
- [ ] Zero approved subreddits → approval returns 422
- [ ] Zero approved keywords → approval returns 422
- [ ] Duplicate keyword for the same subreddit → 409 on add
- [ ] Keyword exceeding 300 chars → rejected
- [ ] Negative term added as a positive keyword by mistake → tier is explicit, no ambiguity
- [ ] `log10(0)` guard in the size component (subscribers clamped to ≥10)
- [ ] Estimate with 0 subreddits → 0, no divide-by-zero

## A6. Error handling

- [ ] One channel raising does not abort discovery — the others still contribute
- [ ] Validation request failure → candidate marked `unknown`, retried once, then rejected
- [ ] Keyword generation failing for one subreddit → others still generated
- [ ] Approval with stale ids (deleted rows) → 422, not 500

## A7. Security

- [ ] Manually added subreddit names sanitised before URL construction (no path traversal)
- [ ] Keyword text escaped in the UI (autoescaping; no `|safe`)
- [ ] LLM-generated subreddit names never used in a URL without pattern validation
- [ ] No credential in the estimate or gate responses

## A8. Performance

- [ ] Validation is bounded: max candidates × 2 requests, capped by `limits.max_subreddits_per_run` × 3
- [ ] Channel 2 bounded to 12 terms
- [ ] Channel 3 one hop only
- [ ] Gate pages render < 300 ms with 30 candidates
- [ ] `/api/runs/<id>/estimate` < 100 ms (debounced client-side)

## A9. Scalability

- [ ] `project_subreddits` and `project_keywords` unique constraints prevent unbounded duplicates
- [ ] Rank components stored as JSON, not as 5 columns (schema stays stable as the formula evolves)
- [ ] Estimate uses observed latency from `metrics`, not a hardcoded constant

## A10. Logging

- [ ] Each channel logs its candidate count
- [ ] Each rejection logs name + reason
- [ ] Hallucination rate logged: proposed vs. validated
- [ ] Keyword generation logs count per subreddit
- [ ] Gate approvals logged with the id list

## A11. Retries

- [ ] Discovery job retryable up to 3 attempts
- [ ] Validation request retried by `ProxiedHTTPClient`
- [ ] Keyword generation retried on schema failure

## A12. AI verification & efficiency

- [ ] **This phase makes ZERO AI calls.** Subreddit and keyword recommendations were produced by
      Phase 4's single consolidated call; this phase only validates, ranks, and gates them.
- [ ] `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` is **unchanged** across discovery + keyword review
- [ ] Subreddit validation is a live HTTP fetch, not an AI call
- [ ] Ranking is deterministic — same inputs, same order, no provider involved
- [ ] Per-subreddit keyword specialisation is a **set intersection**, not a call
- [ ] `grep -ri "deepseek" src/discovery/` → **0**
- [ ] `src/discovery/` does not import `src.ai.service`
- [ ] Regenerating recommendations uses `regenerate_artifact()` — **one** targeted call, not 19

## A13. Regression

- [ ] Phases 1–4 suites pass
- [ ] 459 leads intact
- [ ] All 17 legacy endpoints unchanged
- [ ] `python main.py scrape` still uses `config.yaml` subreddits (project targeting is additive)

## A14. Test suite

- [ ] Recorded LLM fixtures for `subreddit_proposal` and `keyword_generation`
- [ ] HTML fixtures for a valid, private, and banned subreddit page
- [ ] Ranker unit tests with hand-computed expected scores
- [ ] A test asserting a hallucinated name is rejected

---

# PART B — Manual Testing

---

## Test 1 — Discovery produces validated candidates

**Preconditions** A completed Phase-4 project with a good ICP; proxies healthy.

**Steps**
1. From `/projects/<id>`, click **New run**.
2. Watch the run reach `discovering`, then `awaiting_subreddit_review`.
3. Open `/runs/<id>/subreddits`.
4. Count validated candidates and rejected ones.
5. Expand the rejected list.

**Expected**
- ≥ 10 validated candidates
- Each row shows subscribers, description, rank score, and `found by:` channels
- Rejected list is collapsed by default and expands to show names with reasons
- Reasons are one of: not found, too small, inaccessible
- Discovery takes 3–8 minutes (validation is request-bound)

**Failure behaviour**
- 0 candidates → check LLM output and the vocabulary; check proxy health
- All candidates rejected → `MIN_SUBS` may be set too high
- Run stuck in `discovering` → check the worker and the job's error

**Edge cases**
- A very niche ICP → fewer candidates; channel 2 should still find something
- A very broad ICP → capped at `max_subreddits_per_run`
- Vocabulary with only 2 core terms → channel 2 weaker; note it

**Success criteria**
- ≥ 10 validated candidates with visible provenance and reasons

---

## Test 2 — Hallucination rate

**Preconditions** Test 1 completed.

**Steps**
1. Count candidates whose `found by:` includes `AI`.
2. Count how many of those were validated vs. rejected as `not_found`.
3. Compute: validated ÷ AI-proposed.
4. For 3 rejected AI proposals, manually visit `https://old.reddit.com/r/<name>/` to confirm they really don't exist.

**Expected**
- ≥ 70% of AI proposals survive validation
- Every `not_found` rejection is genuinely a 404 when checked manually
- The rejected list is honest — nothing valid was wrongly rejected

**Failure behaviour**
- < 50% survival → the proposal prompt is not precision-biased enough
- A rejected subreddit that actually exists → **false rejection**; check the validator's parsing of the sidebar/404 page

**Edge cases**
- A subreddit that exists but is empty → validated (correct) but should rank low on activity
- A recently banned subreddit → `inaccessible`

**Success criteria**
- ≥ 70% AI survival rate; zero false rejections in the sample of 3

---

## Test 3 — Ranking explainability

**Preconditions** Test 1 completed.

**Steps**
1. On the top-ranked candidate, click `[why? ▾]`.
2. Note all five component values.
3. Manually compute `0.30·hit_density + 0.25·llm_relevance + 0.20·size + 0.15·activity + 0.10·agreement`.
4. Compare to the displayed score.
5. Repeat for the lowest-ranked candidate.
6. Compare a 1M-member general subreddit against a 50K-member niche one.

**Expected**
- Manual computation matches the displayed score (within rounding)
- All five components are shown with values
- **The niche subreddit is not automatically outranked by the huge one** — the log scale should keep them comparable when relevance differs

**Failure behaviour**
- Numbers don't add up → components not stored, or the formula in the UI differs from the backend
- Every large subreddit ranks first → the size component is linear, not log

**Edge cases**
- Candidate found by all 3 channels → `agreement = 1.0`
- Candidate found by 1 channel → `agreement = 0.33`
- Subreddit with no recent posts → low `activity`

**Success criteria**
- Score reproducible by hand; log scaling verifiably working

---

## Test 4 — Gate 1 interaction

**Preconditions** Run at `awaiting_subreddit_review`.

**Steps**
1. Click **Select none** → confirm 0 selected and **Continue disabled**.
2. Click **Select top 10** → confirm 10 selected.
3. Manually untick two; tick one from lower down.
4. Add a valid subreddit manually (e.g. `r/Entrepreneur`).
5. Add an invalid one (`r/thisdoesnotexist99999`).
6. Click **Continue to keywords**.

**Expected**
- Continue disabled at 0 with an inline explanation
- Select-top-10 selects exactly 10 by rank
- Manual add of a valid name → validated live, row appears with `user_added`
- Manual add of an invalid name → **422 with a readable reason**, inline, no row created
- Continue transitions the run to `generating_keywords`

**Failure behaviour**
- Invalid name accepted → validation not applied to manual adds; it will fail during scraping instead
- Continue enabled at 0 → guard missing
- Selections lost on reload → not persisted

**Edge cases**
- Add a name already in the list → 409 or a no-op with a message
- Add with `r/` prefix, trailing slash, or mixed case → normalised
- Reload the page mid-selection → selections persisted (status is stored per row)

**Success criteria**
- All interactions work; invalid additions rejected immediately

---

## Test 5 — Gate persistence across restart

**Preconditions** Run at `awaiting_subreddit_review`.

**Steps**
1. Select 8 subreddits but do **not** approve.
2. Kill the process.
3. Wait 2 minutes.
4. Restart.
5. Open `/runs/<id>/subreddits`.
6. Check `jobs` for anything stuck `running`.

**Expected**
- Run still at `awaiting_subreddit_review`
- The 8 selections are still shown
- **No job is `running`** — the worker holds no lease at a gate
- Approving now proceeds normally

**Failure behaviour**
- Run advanced on its own → a timeout or auto-approve exists; there must not be one
- Selections lost → status not persisted per row
- A stuck `running` job → the worker held a lease across the gate, which will expire and re-run discovery

**Edge cases**
- Restart twice → still fine
- Leave the gate for 24 hours → still fine

**Success criteria**
- Gate state survives restart indefinitely with no lease held

---

## Test 6 — Keyword generation

**Preconditions** Subreddits approved.

**Steps**
1. Wait for `awaiting_keyword_review`.
2. Open `/runs/<id>/keywords`.
3. Inspect the global group, the per-subreddit groups, and the negative panel.
4. Read 10 keywords and judge whether a real person would type them.

**Expected**
- A global group of 5–10 keywords
- A per-subreddit group for each approved subreddit
- Keywords tiered high / medium / low with distinct badges
- Negative panel pre-populated from the vocabulary plus structural terms (hiring, giveaway, weekly thread)
- Keywords read like things people type, not marketing copy
- No duplicates across groups
- Live estimate line present and plausible

**Failure behaviour**
- Marketing-speak keywords → prompt not enforcing colloquial language
- Duplicates → cross-subreddit dedup missing
- No negative terms → vocabulary negatives not materialised

**Edge cases**
- Subreddit with a very short description → fewer, more generic keywords
- 15 subreddits → generation takes longer; watch for a cost spike
- A keyword containing quotes → renders and stores correctly

**Success criteria**
- Tiered, deduplicated, colloquial keywords with negatives, per subreddit

---

## Test 7 — Gate 2 interaction

**Preconditions** Run at `awaiting_keyword_review`.

**Steps**
1. Untick 5 keywords; watch the estimate line change.
2. Add a custom high-tier keyword.
3. Add a custom negative term.
4. Delete one AI-generated keyword.
5. Click **Continue to options**.

**Expected**
- Estimate updates within ~500 ms of each change (debounced)
- Custom additions persist and appear in the correct group
- Deletion persists
- Continue transitions to `awaiting_options`

**Failure behaviour**
- Estimate static → not wired to the endpoint
- Additions lost on reload → not persisted
- Continue with 0 keywords allowed → guard missing

**Edge cases**
- Untick everything → Continue disabled
- Add a 300-char keyword → rejected with a message
- Add a duplicate → 409

**Success criteria**
- Full edit control with a live, responsive estimate

---

## Test 8 — Estimate accuracy

**Preconditions** Run at `awaiting_options`.

**Steps**
1. Record the estimate: requests, minutes, items, cost.
2. Set options: past month, newest, 100/keyword, comments **on**.
3. Record the updated estimate.
4. **Proceed into Phase 6** and run the scrape.
5. Compare actual requests and duration to the estimate.

**Expected**
- Estimate changes when options change
- Actual requests within ±30% of the estimate
- Actual duration within ±30%
- The estimate is labelled as an estimate

**Failure behaviour**
- Estimate off by 5× → the formula's assumptions are wrong; recalibrate against observed data
- Estimate does not respond to the comments toggle → not all options are in the formula

**Edge cases**
- Comments off → estimate drops noticeably
- `limit_per_query=10` → estimate drops proportionally
- Time window "all" → more results, longer

**Success criteria**
- Within ±30% on both requests and duration

---

## Test 9 — Regenerate preserves user additions

**Preconditions** Gate 1 with a manually added subreddit.

**Steps**
1. Manually add `r/Entrepreneur`.
2. Click **Regenerate**.
3. Wait for re-discovery.
4. Check whether `r/Entrepreneur` is still present and still marked `user_added`.
5. Repeat on Gate 2 with a custom keyword.

**Expected**
- `user_added` rows survive regeneration
- AI-proposed rows are replaced
- Previously rejected AI rows may reappear (that is fine)
- Selections on user-added rows are preserved

**Failure behaviour**
- User additions wiped → regeneration deletes indiscriminately; user work destroyed

**Edge cases**
- Regenerate twice → still preserved
- Regenerate after approving → returns the run to the gate (legal backward transition)

**Success criteria**
- User-added targeting survives every regeneration

---

## Test 10 — Discovery cost

**Preconditions** A run through both gates.

**Steps**
1. `SELECT stage, SUM(cost_usd) FROM ai_calls WHERE run_id=? GROUP BY stage;`
2. Sum the total.
3. Compare against the ~$0.008 estimate for 12 subreddits.

**Expected**
- `subreddit_recommendation` ≈ $0.0008
- `keyword_generation` ≈ $0.0006 per subreddit
- Total for discovery + keywords **< $0.05**
- Cost visible on the run page

**Failure behaviour**
- \> $0.10 → check `max_tokens` and whether the ICP is being resent redundantly
- $0 → calls not recorded

**Edge cases**
- 20 subreddits → proportionally higher, still far under the $2.00 run cap
- Re-running with the same inputs → cache hits, near $0

**Success criteria**
- Under $0.05 for 12 subreddits; per-stage breakdown available

---

## Test 11 — Channel 4 (semantic discovery) and zero-AI targeting

**Test case** Semantic matching finds communities the lexical channels cannot, and this phase makes
no model calls.

**Preconditions** A completed BKB with ICP and persona vectors; the semantic layer enabled.

**Steps**
1. Run discovery with all four channels. Record which channel first surfaced each candidate.
2. Identify candidates surfaced **only** by channel 4; read their sidebar descriptions.
3. Disable channel 4; re-run. Compare candidate sets.
4. `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` for the whole phase.
5. Confirm generated keywords draw on BKB sections 14–16 and 20–22.
6. Disable the semantic layer entirely; re-run.

**Expected**
- Channel 4 surfaces at least one valid community whose description matches the ICP **without
  sharing its vocabulary** — the specific gap lexical channels have
- Every channel-4 candidate is still **live-validated** like any other; none bypasses validation
- Step 4: **zero** AI calls — everything needed already exists in the BKB
- Step 6: discovery completes on three channels, and the run reports that channel 4 was skipped

**Failure behaviour**
- Non-zero AI calls → Phase 5 has reintroduced generation the consolidated Phase-4 call already paid
  for, and the cost model's largest saving is undone
- Channel 4 candidates skipping validation → hallucinated or dead subreddits reach Gate 1, which is
  exactly what live validation exists to prevent
- Channel 4 adding nothing over three runs → the ICP vector is too generic to discriminate; record it
  rather than shipping a channel that does nothing

**Edge cases**
- Semantic layer disabled → three channels, explicitly reported, not silently degraded
- Channel 4 returning a private or banned subreddit → rejected at validation with a recorded reason
- Duplicate candidate across channels → one row, with all contributing channels recorded

**Success criteria**
- Channel 4 demonstrably adds candidates; every candidate is validated; the phase spends nothing

---

## Sign-off

| Test | Result | Notes |
|---|---|---|
| 1 Discovery | ☐ Pass ☐ Fail | |
| 2 Hallucination rate | ☐ Pass ☐ Fail | |
| 3 Ranking explainability | ☐ Pass ☐ Fail | |
| 4 Gate 1 interaction | ☐ Pass ☐ Fail | |
| 5 Gate persistence | ☐ Pass ☐ Fail | |
| 6 Keyword generation | ☐ Pass ☐ Fail | |
| 7 Gate 2 interaction | ☐ Pass ☐ Fail | |
| 8 Estimate accuracy | ☐ Pass ☐ Fail | |
| 9 Regenerate preserves | ☐ Pass ☐ Fail | |
| 10 Discovery cost | ☐ Pass ☐ Fail | |
| 11 **Channel 4 + zero AI** | ☐ Pass ☐ Fail | |

**Phase 5 complete when Part A is fully ticked and all 11 Part B tests pass.**
