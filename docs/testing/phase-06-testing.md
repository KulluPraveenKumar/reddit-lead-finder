# Phase 06 — Testing: Scrape Execution & Comment Extraction

> **This phase migrates the `leads` table. Verify the backup before starting.**

---

# PART A — Claude Verification

## A1. Architecture

- [ ] `BaseScraper` is abstract; all four scrapers extend it
- [ ] No scraper knows about jobs or runs beyond `ScrapeContext`
- [ ] `CommentScraper` reuses `RedditClient._parse_comments` rather than reimplementing it
- [ ] `SCRAPER_ORDER` defined once and imported by both `main.py` and the handler
- [ ] Score back-fill lives in `CommentScraper`, not in the parser
- [ ] Project scoping applied via `LeadRepository`, not inline in scrapers

## A2. Compilation and imports

- [ ] `python -c "import src.scrapers"` succeeds
- [ ] All four scrapers instantiate with the same constructor signature
- [ ] `Comment` model imports and maps cleanly

## A3. Lint / A4. Typing

- [ ] `ruff` clean
- [ ] `ScrapeContext` and `ScrapeReport` are typed dataclasses
- [ ] `collect()` annotated as an `Iterator`
- [ ] `Lead.score` typed `int | None`

## A5. Edge cases

- [ ] Subreddit with 0 posts → report with zeros, no error
- [ ] Subreddit that 404s mid-run → job fails as non-fatal, run continues
- [ ] Post with 0 comments → comment fetch skipped by the `min_post_comments` filter
- [ ] Post with 500 comments → capped at `max_comments_per_post`
- [ ] Comment with an empty body → skipped
- [ ] Comment from `[deleted]` → skipped by the pre-filter
- [ ] Deeply nested comment (depth 8) → excluded by `max_depth=4`
- [ ] Identical comment text on two different posts → **both stored** (hash includes `lead_id`)
- [ ] Identical comment re-scraped on the same post → deduped
- [ ] Lead already having a score → back-fill skipped
- [ ] Lead budget of 0 → no leads created, `truncated` set
- [ ] All keywords `low` tier → higher threshold applied consistently
- [ ] `time_window` of `all` → `t` parameter omitted or set to `all`

## A6. Error handling

- [ ] Permalink fetch failure → that lead's comments skipped, others continue
- [ ] `IntegrityError` on `body_hash` → caught via `begin_nested`, batch not rolled back
- [ ] Parse error on one comment → `continue`, others processed
- [ ] Rescore failure after back-fill → logged, score still saved

## A7. Security

- [ ] Comment bodies escaped in the UI (autoescaping; no `|safe`)
- [ ] Reddit usernames escaped
- [ ] Permalink URLs validated as `old.reddit.com` / `www.reddit.com` before fetching
- [ ] No credential in `ScrapeContext` or in any job payload

## A8. Performance

- [ ] One dedup query per page, not per post (statement counter)
- [ ] Comment insert batched per lead, committed once per lead
- [ ] `ix_leads_project_conf` used by the project lead query
- [ ] `ix_comments_lead` used by the comment query
- [ ] Per-page commit does not dominate wall time (network delay does)

## A9. Scalability

- [ ] Lead budget enforced and reported
- [ ] `max_comment_posts` caps the most expensive step
- [ ] `filter_new` chunks id lists under SQLite's variable limit
- [ ] Comment table growth bounded per run and cascades on lead delete

## A10. Logging

- [ ] Per-page: subreddit, page number, items, new
- [ ] Per-subreddit summary: posts seen, leads, duration
- [ ] Comment run: posts visited, comments stored, scores back-filled
- [ ] Truncation logged with the reason and limit

## A11. Retries

- [ ] Scrape job retryable up to 5 attempts
- [ ] Retry does not duplicate leads (dedup + unique index)
- [ ] Comment job retryable; `body_hash` prevents duplicates

## A12. AI verification & local-pipeline efficiency

- [ ] **This phase makes ZERO AI calls** — `ai_calls` count unchanged by a scrape-only run
- [ ] `src/rules/`, `src/dedupe/`, `src/scoring/` do **not** import `src.ai` (grep-enforced)
- [ ] Exact content-hash dedup collapses crossposts
- [ ] MinHash + LSH groups near-duplicates at Jaccard ≥ 0.85
- [ ] MinHash indexing of 2,000 items completes in < 2 s on CPU
- [ ] `prescores` written for **every** collected item, admitted or not
- [ ] Pre-score is deterministic: same inputs → identical score
- [ ] Competitor detection is dictionary-based, **not** an AI call
- [ ] `comments.body_hash` computed and stored — Phase 7's dedup depends on it
- [ ] `finalize_run` → `ANALYZING` when AI is configured, `COMPLETE` when not
- [ ] A scrape completes normally with **no** API key configured
- [ ] A stored API key survives the `0007` migration

## A13. Regression

- [ ] 459 legacy leads have `project_id IS NULL`
- [ ] Legacy `intent_score` values unchanged
- [ ] `GET /` with no `project_id` shows all leads
- [ ] CSV export: 13 columns
- [ ] All 17 legacy endpoints unchanged
- [ ] Phases 1–5 suites pass

## A14. Test suite

- [ ] Migration test on a copy of the live DB
- [ ] Comment parser golden-fixture tests including depth
- [ ] Back-fill test using a permalink fixture
- [ ] Statement-count test for dedup
- [ ] Idempotency test: run the same scrape job twice, assert no duplicates

---

# PART B — Manual Testing

---

## Test 1 — Migration of the `leads` table

**Preconditions** Verified backup; live DB at revision `0006`.

**Steps**
1. `cp data/leads.db data/leads.db.pre06`
2. `python main.py migrate`
3. Verify:
   ```sql
   SELECT COUNT(*) FROM leads;                                  -- 459
   SELECT COUNT(*) FROM leads WHERE project_id IS NULL;         -- 459
   SELECT COUNT(*) FROM leads WHERE confidence_score IS NULL;   -- 459
   SELECT COUNT(*) FROM leads WHERE analysis_status='not_analyzed'; -- 459
   SELECT MIN(intent_score), MAX(intent_score), ROUND(AVG(intent_score),2) FROM leads;
   PRAGMA table_info(comments);
   ```
4. Open `/`; confirm 459 leads render.
5. Export CSV; confirm 13 columns.

**Expected**
- Exactly 459 leads, all with NULL project/confidence and `not_analyzed`
- Scores unchanged: 5.0 / 164.28 / 42.29
- `comments` table exists with the documented columns
- Dashboard and export unchanged

**Failure behaviour**
- Row count changed → **restore immediately** from `leads.db.pre06`
- Scores changed → restore; the migration touched data it should not have

**Edge cases**
- Downgrade `0007` → the three columns and `comments` are dropped; 459 leads remain
- Re-upgrade → columns return with the same defaults

**Success criteria**
- Columns added, zero data changed

---

## Test 2 — Full run: URL to leads

**Preconditions** Phases 4–5 complete; a project through both gates.

**Steps**
1. On `/runs/<id>/options`, set: past month, newest, 100/keyword, comments **on**.
2. Note the estimate.
3. Click **Start scraping**.
4. Watch the progress page for the whole run.
5. When complete, open `/runs/<id>/leads`.
6. Query: `SELECT COUNT(*) FROM leads WHERE project_id=?;` and `SELECT COUNT(*) FROM comments WHERE project_id=?;`

**Expected**
- One `scrape_subreddit` job per approved subreddit, executing in sequence
- Progress bar advances per completed job
- Activity feed shows per-page entries with new-item counts
- Comment jobs run after scraping
- Run reaches `complete` (or `analyzing` if AI is enabled)
- Leads have the correct `project_id`
- Comments exist and are linked to leads

**Failure behaviour**
- 0 leads → check keyword quality and thresholds; check the search-pagination fix
- Run fails → read the failed job's error
- Duration far exceeding the estimate → check proxy health and rate limiting

**Edge cases**
- One subreddit 404s mid-run → that job fails, run completes
- Proxy pool degrades mid-run → run slows, completes
- Kill mid-run and restart → resumes (Phase 3 behaviour, re-verify here)

**Success criteria**
- End-to-end run produces project-scoped leads and comments

---

## Test 3 — Search pagination fix, verified end to end

**Preconditions** A run with a broad keyword.

**Steps**
1. Pick a keyword expected to have many results (e.g. `"looking for"` in `r/SaaS`).
2. Set `limit_per_query=100`.
3. Run.
4. In the activity feed, count pages fetched for that keyword.
5. Count leads attributable to it.

**Expected**
- ≥ 4 pages fetched for that keyword (25/page)
- More than 25 unique posts seen
- No duplicate `reddit_id` values

**Failure behaviour**
- Exactly 1 page → the Phase-1 selector fix regressed
- Duplicates → the in-loop `seen` guard failed

**Edge cases**
- Keyword with < 25 results → 1 page, clean termination
- `limit_per_query=10` → stops after page 1

**Success criteria**
- Multi-page search confirmed in a real run

---

## Test 4 — Comment extraction

**Preconditions** A run with comments enabled.

**Steps**
1. After the run, pick a lead with `num_comments >= 10`.
2. `SELECT author, depth, LENGTH(body), score FROM comments WHERE lead_id=? ORDER BY depth, id;`
3. Open the post on Reddit and compare the first 5 comments.
4. Open the lead in the UI and expand comments.

**Expected**
- Comments stored, ordered, with `depth` values 0–4
- Text matches Reddit (allowing for markdown-to-text conversion)
- Authors match
- `[deleted]` and AutoModerator comments filtered out
- UI indents by depth

**Failure behaviour**
- 0 comments for a post with 20 → selector or candidate-selection issue
- All depth 0 → depth extraction not implemented
- Garbled text → parser encoding issue

**Edge cases**
- Post with only deleted comments → 0 stored, no error
- Post with a comment containing code blocks → stored as text
- Post with 500 comments → capped at 30

**Success criteria**
- Comments accurate, depth-tagged, filtered

---

## Test 5 — Comment deduplication

**Preconditions** Test 4 completed.

**Steps**
1. Record `SELECT COUNT(*) FROM comments WHERE project_id=?;`
2. Re-run **only** the comment job for the same run (re-enqueue it manually).
3. Recount.
4. Check for duplicate `body_hash` values.

**Expected**
- Count unchanged (or increased only by genuinely new comments posted since)
- Zero duplicate `body_hash`
- The re-run completes without `IntegrityError` bubbling up

**Failure behaviour**
- Count doubles → `body_hash` dedup not applied
- Job crashes on `IntegrityError` → `begin_nested` handling missing

**Edge cases**
- A comment edited on Reddit → new hash, stored as new (documented, acceptable)
- Same comment text on a different post → both stored (hash includes `lead_id`)

**Success criteria**
- Re-run is idempotent

---

## Test 6 — Score back-fill

**Preconditions** A run whose leads came from keyword search (score NULL).

**Steps**
1. Before comment fetching: `SELECT COUNT(*) FROM leads WHERE project_id=? AND score IS NULL;`
2. Run comment extraction.
3. Re-query.
4. Pick a back-filled lead; compare its `score` to the live Reddit post.
5. Check `run_events` for `comments.score_backfilled`.

**Expected**
- The NULL count drops for leads that had comments fetched
- Back-filled scores match Reddit (within vote fuzzing)
- `intent_score` recalculated for those leads
- Events emitted

**Failure behaviour**
- No back-fill → `_backfill_score` not called or the selector is wrong
- Scores wildly wrong → parsing the wrong element
- Leads with an existing score changed → back-fill should skip them

**Edge cases**
- Lead whose post was deleted → fetch fails, score stays NULL
- Lead already scored → untouched (verify explicitly)

**Success criteria**
- NULL scores back-filled accurately; existing scores untouched

---

## Test 7 — Per-tier thresholds

**Preconditions** Keywords of all three tiers approved.

**Steps**
1. Identify a `high`-tier and a `low`-tier keyword.
2. Run.
3. For leads matched by each, inspect `intent_score` distribution.
4. Confirm the minimum score among `high`-sourced leads is lower than among `low`-sourced.

**Expected**
- `high` keywords qualify leads at ≥ 3.0
- `medium` at ≥ 5.0
- `low` at ≥ 8.0
- Distributions reflect this

**Failure behaviour**
- All leads at the same threshold → tiers not applied
- No `low`-tier leads at all → threshold too high for that tier; note and consider tuning

**Edge cases**
- A lead matched by both a high and a low keyword → the lower threshold wins (first qualification stores it)
- Custom user keyword with no tier → defaults to medium

**Success criteria**
- Threshold varies by tier as specified

---

## Test 8 — Lead budget truncation

**Preconditions** Set `limits.max_leads_per_run: 20`.

**Steps**
1. Run against subreddits likely to yield more than 20 leads.
2. Watch the run.
3. Check the lead count and the run page.

**Expected**
- Exactly 20 leads (or the last page's boundary)
- `truncated` flag set on the run
- Banner: *"Stopped at 20 leads (your limit)…"*
- `run_events` contains `scrape.truncated`
- Remaining scrape jobs are skipped or complete immediately

**Failure behaviour**
- More than 20 leads → budget not enforced
- Silent truncation → the user thinks they got everything

**Edge cases**
- Budget of 0 → 0 leads, immediate truncation
- Budget higher than available → no truncation, flag unset

**Success criteria**
- Budget enforced and clearly communicated

---

## Test 9 — Legacy dashboard with project leads present

**Preconditions** Both legacy leads (459) and new project leads exist.

**Steps**
1. Open `/` with no filters.
2. Note the total count.
3. Verify it equals 459 + new leads.
4. Use the new project filter dropdown: select the project, then "Legacy (no project)", then "All".
5. Export CSV with no filter.

**Expected**
- Default view shows **everything** — 459 + new — exactly as before the phase
- Project filter narrows to that project's leads
- "Legacy" filter shows exactly 459
- CSV with no filter: 13 columns, all rows

**Failure behaviour**
- Default view shows only legacy leads → an unintended `project_id IS NULL` filter crept in
- Default view shows only project leads → inverse problem
- CSV column count changed → export changed prematurely

**Edge cases**
- Filter to a project with 0 leads → empty state
- Sort by intent score across mixed sources → works

**Success criteria**
- Default behaviour unchanged; filtering is additive

---

## Test 10 — Scraper ordering determinism

**Preconditions** Two identical fresh databases.

**Steps**
1. On DB A: `python main.py scrape` (CLI path).
2. On DB B: trigger a scrape from the dashboard.
3. Use the same `config.yaml` and the same moment in time as closely as possible.
4. Compare the set of `reddit_id` values created.

**Expected**
- The same scraper order is used in both (`subreddit → keyword → user`)
- Lead sets are near-identical (differences only from new posts appearing between runs)
- No lead qualifies in one path and not the other due to ordering

**Failure behaviour**
- Materially different lead sets → `SCRAPER_ORDER` not adopted by both entry points

**Edge cases**
- Run both against the same DB sequentially → second run adds near-zero (dedup)

**Success criteria**
- Both entry points use the same order and produce equivalent results

---

## Test 11 — Mid-run restart with comments

**Preconditions** A run with several subreddits and comments enabled.

**Steps**
1. Start the run.
2. Kill the process during comment extraction.
3. Note the comment count.
4. Restart.
5. Wait for completion.
6. Recount comments and check for duplicates.

**Expected**
- Comment job reclaimed and re-run
- Already-stored comments not duplicated (`body_hash`)
- Run completes
- Final comment count ≥ the pre-kill count

**Failure behaviour**
- Duplicates → dedup not applied on re-run
- Run stuck → reclamation not working for this job type

**Edge cases**
- Kill during the very first comment fetch → clean restart
- Kill twice → still recovers

**Success criteria**
- Idempotent recovery with no duplicate comments

---

---

## Test 12 — Exact and near-duplicate detection

**Preconditions** A completed scrape with ≥ 300 items.

**Steps**
1. `SELECT COUNT(*) FROM dedup_groups WHERE run_id=?;` and `SELECT SUM(member_count) ...`
2. Pick a `minhash` group with ≥ 3 members; read all member texts side by side.
3. Judge: are they genuinely the same discussion?
4. Pick two items you know are *different* but topically close; confirm they were **not** grouped.
5. Time the MinHash indexing step from the logs.

**Expected**
- Exact groups collapse true crossposts and reposts
- MinHash groups contain genuinely near-identical discussions
- Topically-related-but-distinct items are **not** grouped at Jaccard ≥ 0.85
- Collapse rate > 8% of collected items
- Indexing 2,000 items completes in < 2 s

**Failure behaviour**
- Distinct discussions merged → threshold too low; **this loses leads silently**, so it is the
  more dangerous direction. Raise the threshold and re-run.
- Nothing grouped → shingle size or banding is wrong; check `num_perm` and band count
- Indexing takes minutes → LSH banding is not being used (O(n²) comparison)

**Edge cases**
- Two items differing only in trailing whitespace/case → grouped (normalisation working)
- A 30-character post → too short to shingle meaningfully; must not group spuriously
- Same text in two different subreddits → grouped for analysis, scored separately

**Success criteria** Groups are genuinely near-identical; no false merges in the sample.

---

## Test 13 — Deterministic pre-score

**Steps**
1. `SELECT total, components_json FROM prescores WHERE run_id=? ORDER BY total DESC LIMIT 5;`
2. Hand-compute the top item's score from its components and the configured weights.
3. Re-run the pre-score step on the same run.
4. Compare every score before and after.
5. Confirm a `prescores` row exists for **every** collected item, not only admitted ones.

**Expected**
- Hand computation matches to 2 decimals
- Re-running produces **byte-identical** scores — it is deterministic
- Row count in `prescores` == items collected
- Zero AI calls made by this step

**Failure behaviour**
- Scores change between runs → non-determinism (dict ordering, `now()` in a component)
- Rows only for admitted items → the funnel becomes unauditable and the gate untunable

**Edge cases**
- Item matching no keyword → low but non-zero score
- Item with NULL upvote score (search-sourced) → engagement component handles None

**Success criteria** Deterministic, complete, hand-verifiable, zero AI.

---

## Test 14 — Zero AI calls in this phase

**Steps**
1. `SELECT COUNT(*) FROM ai_calls;` — record.
2. Run a full scrape with comments, dedup, rules, and pre-score.
3. Re-query.

**Expected** The count is **identical**. This phase's entire pipeline is deterministic.

**Failure behaviour** Any increase means AI leaked into the local pipeline — find it and remove it.

**Success criteria** Delta of exactly zero.

---

## Test 15 — The three-tier dedup cascade

**Test case** Each tier catches what the previous cannot, and the semantic tier never loses a lead.

**Preconditions** A fixture containing: exact reposts, reworded near-duplicates sharing 5-grams, and
**paraphrase pairs sharing almost no character 5-grams** ("Which CRM should I use?" /
"Looking for recommendations on customer management software").

**Steps**
1. Run with all three tiers. Record which tier grouped each pair.
2. Disable tier 3; re-run on the same fixture.
3. Compare the **lead sets** (not the group counts) between the two runs.
4. Inspect the pre-scores within one multi-member group.

**Expected**
- Tier 1 catches exact reposts; tier 2 the rewordings; **tier 3 and only tier 3** the paraphrases
- With tier 3 off: fewer groups, **identical lead membership** — no lead is lost
- Within any group, the N members have **N distinct pre-scores**

**Failure behaviour**
- Tier 3 grouping unrelated posts → the cosine threshold is too loose; both are "frustrated software
  pricing questions" and neither is a duplicate
- A lead disappearing when tier 3 is enabled → embeddings are rejecting, which they must never do
- Identical scores across a group → "group for analysis, score individually" is not implemented, and
  N different-value leads are being shown one number

**Edge cases**
- Semantic layer unavailable → tier 3 is a silent no-op; tiers 1–2 unaffected
- A group whose representative is deleted → a new representative is selected, analysis re-linked

**Success criteria**
- Each tier demonstrably adds recall; membership is never reduced; scores stay individual

---

## Sign-off

| Test | Result | Notes |
|---|---|---|
| 1 **`leads` migration** | ☐ Pass ☐ Fail | **Blocking** |
| 2 Full run | ☐ Pass ☐ Fail | |
| 3 Search pagination E2E | ☐ Pass ☐ Fail | |
| 4 Comment extraction | ☐ Pass ☐ Fail | |
| 5 Comment dedup | ☐ Pass ☐ Fail | |
| 6 Score back-fill | ☐ Pass ☐ Fail | |
| 7 Per-tier thresholds | ☐ Pass ☐ Fail | |
| 8 Budget truncation | ☐ Pass ☐ Fail | |
| 9 Legacy dashboard | ☐ Pass ☐ Fail | |
| 10 Ordering determinism | ☐ Pass ☐ Fail | |
| 11 Restart with comments | ☐ Pass ☐ Fail | |

| 12 Dedup detection | ☐ Pass ☐ Fail | |
| 13 Deterministic pre-score | ☐ Pass ☐ Fail | |
| 14 **Zero AI calls** | ☐ Pass ☐ Fail | |
| 15 **Three-tier dedup cascade** | ☐ Pass ☐ Fail | |

**Phase 6 complete when Part A is fully ticked and all 15 Part B tests pass.**
