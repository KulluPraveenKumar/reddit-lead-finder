# Phase 08 — Testing: Dashboard Polish, Export & Production Readiness

> This is the final gate. In addition to its own tests, **every prior phase's Part B suite is
> re-executed** against a copy of the live database.

---

# PART A — Claude Verification

## A1. Architecture

- [ ] Export logic lives in `src/export/`, not in `routes.py`
- [ ] `src/analytics/` depends only on repositories
- [ ] Scheduler enqueues; it never executes work inline
- [ ] Maintenance is a job type, not a cron script outside the system
- [ ] No layer-violating imports anywhere (import-graph test passes)

## A2. Compilation and imports

- [ ] `python -c "import src.export, src.analytics"` succeeds
- [ ] `openpyxl` imports; XLSX export degrades with a clear message if absent
- [ ] All CLI subcommands run

## A3. Lint / A4. Typing

- [ ] `ruff check .` / `ruff format --check .` clean across the **entire** codebase
- [ ] Export functions annotated with their return types (generators typed)
- [ ] `CalibrationReport` typed

## A5. Edge cases

- [ ] Export with 0 leads → valid file with headers only
- [ ] Export with 50,000 leads → streams, does not exhaust memory
- [ ] Export with a filter matching nothing → headers only
- [ ] CSV containing a lead whose title has commas, quotes, and newlines → correctly quoted
- [ ] CSV with non-ASCII → UTF-8 with BOM (so Excel opens it correctly)
- [ ] XLSX with a cell over 32,767 chars → truncated with an ellipsis, not an exception
- [ ] JSON export of a lead with no analysis → nulls, not missing keys
- [ ] Calibration with < 30 triaged leads → "not enough data" state
- [ ] Calibration with all leads in one decile → renders without a misleading trend claim
- [ ] Monitoring with `interval_hours=0` → rejected
- [ ] Monitoring when a run is already active → skipped, logged
- [ ] Maintenance on empty tables → no error

## A6. Error handling

- [ ] Export failure mid-stream → a partial file is not presented as complete (error surfaced)
- [ ] Every AJAX endpoint failure produces a toast — **verified endpoint by endpoint**
- [ ] Every page has a rendered error state, not a raw traceback
- [ ] 404 and 500 pages styled

## A7. Security *(full review)*

- [ ] `git grep -i "sff3dv6jimdr"` → zero
- [ ] `git grep -i "wvwefhhu"` → zero
- [ ] `git grep` for the DeepSeek API key → zero
- [ ] `git grep -i "api_key"` in `config.yaml` → zero
- [ ] No credential in any DB column (schema review + a scan of all TEXT columns)
- [ ] Full-run log capture grepped for all known secrets → zero
- [ ] `.env`, `data/*.db`, `data/backups/`, proxy `.txt` all gitignored
- [ ] Flask `debug=False` asserted at startup
- [ ] `SECRET_KEY` from env with **no** hardcoded fallback
- [ ] `grep -rn "|safe" src/dashboard/templates/` → zero on user or model content
- [ ] Jinja autoescaping confirmed on
- [ ] No f-string SQL — `grep -rn "execute(f\"" src/` → zero
- [ ] `pip-audit` clean, or every finding triaged and recorded
- [ ] No `oauth`, `praw`, or `client_secret` anywhere — grep-verified
- [ ] URL validation blocks `file://`, `javascript:`; SSRF posture for private IPs documented

## A8. Performance

- [ ] Lead list < 200 ms at 10,000 rows
- [ ] `/api/runs/<id>/progress` < 50 ms at 5,000 jobs
- [ ] `/health` < 100 ms
- [ ] Calibration < 500 ms at 10,000 leads
- [ ] CSV export of 10,000 rows begins streaming in < 1 s
- [ ] `EXPLAIN QUERY PLAN` verified for the ten most frequent queries; all index-backed
- [ ] `keyword_breakdown` bounded by `LIMIT`

## A9. Scalability

- [ ] All exports stream via generators
- [ ] XLSX uses write-only mode
- [ ] Retention purges scheduled and verified
- [ ] DB file size growth measured over a 10-run soak and is bounded

## A10. Logging

- [ ] Export requests logged with row counts
- [ ] Monitoring runs logged with project and trigger
- [ ] Maintenance logs per-category delete counts
- [ ] No secret in any log at any level, including DEBUG

## A11. Retries

- [ ] Monitoring run failure does not disable monitoring permanently
- [ ] Maintenance failure retried next cycle
- [ ] All prior phases' retry behaviour still intact

## A12. AI verification & cost reporting

- [ ] Exports include enrichment fields and never any credential
- [ ] Calibration and all quality rollups read stored rows only — **zero** provider calls
- [ ] Monitoring runs respect per-run, per-day **and per-call-count** caps
- [ ] A monitoring run on an unchanged project makes **zero** AI calls
- [ ] A 402 during a monitoring run pauses cleanly and surfaces the amber state
- [ ] `/health/ai` accurate under every provider state
- [ ] Cache-hit ratio below target renders red with the 50×-cost explanation
- [ ] **Gate miss rate** shown per run and trended over time
- [ ] **Calls-per-1,000-posts** reported and within the ≤ 30 target
- [ ] `ai_calls` retention purge aggregates monthly cost before deleting rows
- [ ] `grep -ri "deepseek" src/ --exclude-dir=ai/providers` → **0** at project end
- [ ] Whole AI suite still runs on `FakeProvider`, offline

## A13. Regression — full system

- [ ] **Phase 1 Part B re-executed** — 14 tests (AI foundation)
- [ ] **Phase 2 Part B re-executed** — 18 tests (proxy + transport)
- [ ] **Phase 3 Part B re-executed** — 11 tests
- [ ] **Phase 4 Part B re-executed** — 17 tests (incl. BKB, entity resolution, origin guard, evidence)
- [ ] **Phase 5 Part B re-executed** — 11 tests (incl. channel 4, zero-AI)
- [ ] **Phase 6 Part B re-executed** — 15 tests (incl. local pipeline, 3-tier dedup)
- [ ] **Phase 7 Part B re-executed** — 25 tests (incl. adaptive budget, explainability, exploration loop, pinning)
- [ ] 459 legacy leads intact with unchanged `intent_score`
- [ ] All 17 legacy endpoints unchanged
- [ ] Default CSV export byte-identical to Phase 0 for legacy leads

## A14. Test suite

- [ ] `pytest` passes; coverage ≥ 70% overall, ≥ 85% on `src/net/`, `src/scoring/`, `src/knowledge/`, `src/quality/`, `src/feedback/`
- [ ] CSV header-order snapshot test
- [ ] Export tests for all three formats
- [ ] Calibration test with insufficient and sufficient data
- [ ] Performance assertions present as tests, not just manual checks

---

# PART B — Manual Testing

---

## Test 1 — CSV export backward compatibility

**Preconditions** A pre-Phase-1 CSV export saved for comparison.

**Steps**
1. `GET /api/leads/export` with no parameters.
2. Open the file; inspect the header row.
3. Compare the first 13 columns against the original export.
4. Filter to legacy leads only; export; diff against the original file.
5. Export with a project filter; inspect the AI columns.

**Expected**
- First 13 columns identical in name and order: `ID, Reddit ID, Subreddit, Author, Title, URL, Score, Comments, Intent Score, Keywords, Status, Created UTC, Scraped At`
- 8 new columns appended after them
- Legacy-only export diffs cleanly against the original for the first 13 columns
- AI columns are empty for legacy leads, populated for analysed ones

**Failure behaviour**
- Column reordered or renamed → **breaks every existing importer**; blocking
- New columns inserted in the middle → same problem

**Edge cases**
- Lead with a comma in the title → quoted correctly
- Lead with a newline in the body → quoted correctly
- Non-ASCII characters → open in Excel; confirm no mojibake (BOM present)

**Success criteria**
- First 13 columns byte-identical; new columns strictly appended

---

## Test 2 — JSON export

**Steps**
1. `GET /api/leads/export?format=json&project_id=<id>`
2. Validate with `python -m json.tool`.
3. Inspect a lead object's structure.
4. Confirm nested analysis, breakdown, and comments.

**Expected**
- Valid JSON
- Each lead: base fields + `analysis` object + `confidence_breakdown` + `comments` array
- Leads without analysis have `"analysis": null`, not a missing key
- Run and project metadata at the top level

**Failure behaviour**
- Invalid JSON → serialisation bug (likely datetime or Decimal)
- Missing keys → inconsistent shape breaks consumers

**Edge cases**
- 10,000 leads → streams, file completes
- Lead with 200 comments → all included

**Success criteria**
- Valid, consistently shaped, complete

---

## Test 3 — XLSX export

**Steps**
1. `GET /api/leads/export?format=xlsx&project_id=<id>`
2. Open in Excel **and** LibreOffice.
3. Check both sheets.
4. Verify conditional colouring on confidence.
5. Test autofilter and the frozen header.

**Expected**
- Opens without a repair prompt in both applications
- `Leads` sheet: frozen header, autofilter, colour-graded confidence
- `Summary` sheet: run parameters, counts, cost, pre-filter stats
- Numbers are numeric, not text
- Dates are date-typed

**Failure behaviour**
- Repair prompt → malformed file
- Everything as text → cell types not set

**Edge cases**
- 50,000 rows → completes without exhausting memory
- A cell over 32,767 chars → truncated, no exception
- Zero leads → valid file with headers

**Success criteria**
- Opens cleanly in both applications with correct formatting

---

## Test 4 — Calibration report

**Preconditions** ≥ 30 leads triaged to `contacted` or `interested`.

**Steps**
1. Triage 30–50 leads across the confidence range: mark genuinely good ones `interested`, poor ones `rejected`.
2. Open `/analytics/calibration`.
3. Read the decile table.
4. Assess whether the interested-rate decreases as confidence decreases.
5. Test the insufficient-data path with a fresh project.

**Expected**
- Deciles from 90–100 down to 0–9
- Counts and rates per decile
- A monotonic-decrease verdict shown explicitly
- With < 30 triaged: "not enough data yet", **no chart drawn**

**Failure behaviour**
- Chart drawn on 6 data points → misleading; the sufficiency gate is missing
- Flat curve → the scorer carries no signal; the page should say so, and the operator should retune weights
- Inverted curve → weights are actively wrong

**Edge cases**
- All leads in one decile → renders without claiming a trend
- All leads `new` (untriaged) → insufficient-data state

**Success criteria**
- Honest report with a sufficiency gate

---

## Test 5 — Scheduled monitoring

**Preconditions** A project through both gates with approved targets.

**Steps**
1. Enable monitoring with `interval_hours=1`.
2. Set `last_monitored_at` to 2 hours ago in the DB.
3. Wait for the scheduler tick (or trigger it).
4. Observe: does a run start? Does it show the gates?
5. Start a manual run, then wait for the next monitoring tick.

**Expected**
- A run is created automatically
- **Both gates are skipped** — the run goes straight to `scraping`
- Existing approved subreddits and keywords are reused
- `last_monitored_at` updated
- With an active run present, the monitoring tick **skips** and logs why

**Failure behaviour**
- Run stops at a gate → monitoring is unusable; nobody will approve targets nightly
- Runs stack up → the active-run guard is missing
- Monitoring never fires → scheduler not wired

**Edge cases**
- Monitoring on a project with no approved targets → skipped with a clear log line
- Monitoring disabled mid-run → the current run finishes
- `interval_hours=0` → rejected at save

**Success criteria**
- Autonomous re-runs that reuse approved targeting and never stack

---

## Test 6 — Maintenance purge

**Preconditions** Ability to insert dated rows.

**Steps**
1. Insert: a `done` job finished 40 days ago; `run_events` for a run finished 100 days ago; an `http_cache` row expired yesterday; a `metrics` row 20 days old.
2. Insert recent equivalents of each.
3. Run maintenance in **dry-run** mode; read the reported counts.
4. Run for real.
5. Verify old rows gone, recent rows present.
6. Check the DB file size before and after.

**Expected**
- Dry run reports counts without deleting
- Real run deletes exactly the old rows
- Recent rows untouched
- Counts logged per category
- File size reduced if `VACUUM` ran

**Failure behaviour**
- Recent rows deleted → **data loss**; check window boundaries immediately
- Nothing deleted → not wired
- DB locked for minutes → purge not chunked

**Edge cases**
- Empty tables → no error
- 1,000,000 cache rows → completes without a long lock

**Success criteria**
- Correct rows purged; dry-run accurate; recent data safe

---

## Test 7 — Health page

**Steps**
1. Open `/health` with everything running.
2. Stop the worker; refresh.
3. Blacklist a proxy; refresh.
4. Make the DB read-only; refresh.
5. Restore everything.

**Expected**
- All-green state when healthy: worker alive, queue depth, proxies N/M, DB writable, schema at head
- Worker stopped → worker status shows stale/dead with the last heartbeat time
- Blacklisted proxy → count reflects it
- Read-only DB → `db_writable: false` shown clearly, not a 500
- Recent errors listed
- LLM spend today shown

**Failure behaviour**
- Health page 500s when a subsystem is down → the page must be the **most** robust page in the app
- Shows healthy while the worker is dead → the check is not real

**Edge cases**
- Fresh install, nothing run → renders with zeros
- All proxies blacklisted → red, with the time to next availability

**Success criteria**
- Accurate under every failure mode; never crashes

---

## Test 8 — Empty and error states

**Steps**
1. Fresh database: open `/projects`, `/runs`, `/`, `/health/proxies`, `/analytics/calibration`.
2. On a lead list, apply a filter matching nothing.
3. Disconnect the network; click an AJAX action.
4. Stop the worker; try to start a run.

**Expected**
- Every empty page shows a designed empty state with a next action, not a blank table
- Zero-result filter shows "No leads match these filters" with a clear-filters link
- AJAX failure shows a **toast**, not silence
- Starting a run with no worker shows a warning that jobs will queue

**Failure behaviour**
- Blank page → looks broken
- Silent AJAX failure → **the existing defect this phase is meant to fix**; must not remain

**Edge cases**
- Very slow response → loading state shown, not a frozen UI
- 500 from an endpoint → toast with a readable message

**Success criteria**
- No blank pages; no silent failures anywhere

---

## Test 9 — Performance at scale

**Preconditions** Seed 10,000 leads, 30,000 comments, 5,000 jobs.

**Steps**
1. Time `/runs/<id>/leads` page load.
2. Time `/api/runs/<id>/progress` (10 samples).
3. Time `/health`.
4. Time a 10,000-row CSV export to first byte.
5. Time the calibration report.
6. Scroll a 200-row table; check smoothness.

**Expected**
- Lead list < 200 ms server-side
- Progress < 50 ms
- Health < 100 ms
- CSV first byte < 1 s
- Calibration < 500 ms
- Scrolling smooth (`content-visibility` doing its job)

**Failure behaviour**
- Any target exceeded by > 2× → profile with `EXPLAIN QUERY PLAN` and fix the index
- Export loads everything into memory → not streaming

**Edge cases**
- 100,000 leads → degrades gracefully; note the numbers
- Concurrent export + scrape → no lock errors

**Success criteria**
- All five targets met

---

## Test 10 — Security review

**Steps**
1. Run every grep from Part A §A7.
2. Capture a full run's logs at DEBUG; grep for all known secrets.
3. Dump every TEXT column in the DB; scan for credential patterns.
4. View source on `/health/proxies` and `/projects/<id>`.
5. `git status`; `git check-ignore -v .env data/leads.db`
6. `pip-audit`
7. Attempt XSS: create a project whose name is `<script>alert(1)</script>`; view it.
8. Attempt SSRF: create a project with `http://169.254.169.254/`.

**Expected**
- Every grep returns zero
- No secret in logs, DB, HTML, or repo
- `.env` and DB files ignored
- `pip-audit` clean or fully triaged
- XSS payload rendered as **text**, not executed
- SSRF target either blocked or the behaviour is documented and deliberate

**Failure behaviour**
- **Any** secret found → blocking
- XSS executes → blocking
- SSRF reaches a metadata endpoint → blocking

**Edge cases**
- Lead title containing HTML → escaped
- LLM output containing markdown/HTML → escaped

**Success criteria**
- Zero findings on all eight checks

---

## Test 11 — Full-system regression

**Preconditions** A copy of the live database at head.

**Steps**
1. Re-execute **every** Part B test from Phases 1–7, in order (96 tests).
2. Record results in each phase's sign-off table.
3. Investigate any regression before proceeding.

**Expected**
- All 96 prior manual tests pass
- 459 legacy leads intact with unchanged scores
- Legacy dashboard, CLI, and export all unchanged

**Failure behaviour**
- Any regression → fix before declaring the project complete

**Success criteria**
- 96/96 prior tests pass alongside this phase's 12

---

## Test 12 — Fresh-install operator walkthrough

**Preconditions** A clean machine or a fresh clone with no database.

**Steps**
1. Follow `README.md` exactly, without prior knowledge.
2. Install dependencies.
3. Configure `.env` (`APP_SECRET_KEY`, `PROXY_FILE`) — **no AI key here**.
4. Run migrations.
5. Start the dashboard.
6. **Enter the DeepSeek key on `/settings/ai` and Test Connection.**
7. Create a project from a URL.
7. Complete both gates.
8. Run a scrape with analysis.
9. Export the results.
10. Note every point where the README was unclear or wrong.

**Expected**
- README is sufficient with no outside knowledge
- Every command in it works as written
- Errors along the way are actionable
- The full flow completes in under 45 minutes including scrape time

**Failure behaviour**
- A missing step → fix the README
- A command that fails → fix the code or the docs
- The operator gets stuck → the onboarding is not ready

**Edge cases**
- No proxy file → clear message with instructions
- No DeepSeek key → scraping still works; AI disabled with an explanation and a link to Settings
- DeepSeek account with zero balance → amber state, clear remedy
- Python 3.11 vs 3.12 → both work, or the requirement is stated

**Success criteria**
- A new operator reaches exported leads using only the README

---

## Test 13 — The golden set blocks a bad prompt

**Test case** A prompt version that degrades quality cannot ship.

**Preconditions** 100 hand-labelled golden items; a reference `golden_runs` row for the current
prompt version.

**Steps**
1. Run the golden set on the current version; record F1 and confirm `passed=1`.
2. Deliberately degrade the prompt (remove the rubric, or invert an instruction).
3. Attempt to activate the degraded version.
4. Check `golden_runs` and which version is active.
5. Restore the prompt and re-activate.

**Expected**
- Step 3 is **refused**, with the F1 delta and the 0.02 threshold both reported
- The previous version stays active; no lead is re-scored with the degraded prompt
- Both attempts are recorded in `golden_runs`, pass and fail

**Failure behaviour**
- The degraded version activating → the gate is advisory, not blocking, and the one mechanism that
  catches prompt regressions is decorative
- A pass with a large delta → the comparison is against the wrong baseline, or F1 is miscomputed

**Edge cases**
- A version that *improves* F1 → activates, and becomes the new reference
- Fewer than 100 golden items → the gate refuses to run rather than passing on thin evidence
- A model change with no prompt change → also triggers the gate

**Success criteria**
- Quality regressions are blocked automatically, with the number that justified the block

---

## Test 14 — Calibration corrects meaning without touching ranking

**Test case** Recalibration is not a re-ranking.

**Preconditions** ≥ 200 `lead_labels`; a deliberately overconfident score distribution.

**Steps**
1. Open `/health/quality`; record ECE, Brier, and the reliability diagram.
2. Export the current lead list ordering (ids in rank order).
3. Fit and activate a `calibration_map`.
4. Re-export the ordering; diff against step 2.
5. Compare displayed confidences before and after.
6. `SELECT confidence_score FROM leads` — compare to before.
7. Reduce the label count below 100 and reload the page.

**Expected**
- Step 4: the ordering diff is **empty** — isotonic regression is monotonic and preserves rank
- Step 5: displayed values change; ECE drops below 0.10
- Step 6: stored raw scores are **unchanged**
- Step 7: ECE and Brier report `insufficient data`, not a number

**Failure behaviour**
- Any ordering change → recalibration has become a reweighting, which is precisely the confusion
  [06g §7](../06g-explainability-and-quality.md) warns against (R26)
- Stored scores rewritten → history is destroyed and the reliability diagram can never be recomputed
- A number displayed on 40 labels → a metric that lies when under-powered is worse than a missing one

**Edge cases**
- Perfectly calibrated already → the fitted map is near-identity, ECE barely moves
- All labels one class → the fit is refused with a clear reason

**Success criteria**
- Meaning corrected, ranking untouched, raw data preserved, under-powered metrics honest

---

## Test 15 — Drift monitors fire, and measurement is free

**Test case** The unlabelled drift signals detect a shift, and the quality suite costs nothing.

**Preconditions** 30 days of `quality_snapshots`; the ability to inject a shifted score distribution
and a non-substring evidence span.

**Steps**
1. Record `SELECT COUNT(*) FROM ai_calls`.
2. Run the nightly and weekly rollups.
3. Re-record the count.
4. Inject a run whose score histogram is materially shifted; run the nightly job.
5. Inject an analysis whose `evidence_quote` is not a substring of the post.
6. Force a repair-ladder storm; check the repair rate.
7. Open `/health/quality` and confirm each red value shows its documented action.

**Expected**
- Steps 1–3: the count is **identical** — rollups are pure SQL, zero API calls
- Step 4: PSI > 0.2, flagged, and a golden-set run is triggered
- Step 5: the span is dropped, the lead survives, `hallucinated_span_rate` increments
- Step 7: the ECE action reads **recalibrate**, never "reweight"

**Failure behaviour**
- Any AI call from a rollup → the measurement budget claim in
  [06g §8](../06g-explainability-and-quality.md) is wrong, and the suite will be turned off for cost
- PSI not firing → drift is invisible until precision collapses, by which time weeks of leads are suspect
- A red metric with no stated action → the metric will be noticed, discussed, and ignored

**Edge cases**
- A legitimately different but healthy run → PSI flags it, the golden set passes, no action taken.
  This is the intended outcome: the triggers are cheap, and the golden set arbitrates
- No labels at all → the accuracy band reports `insufficient data`; the drift band still works,
  because it needs no labels

**Success criteria**
- All drift signals fire on injected faults; rollups make zero AI calls; every red value states its action

---

## Test 16 — Cache is not state

**Test case** The disposable memory class is genuinely disposable.

**Preconditions** A project with enriched, scored leads and a warm `ai_cache` / `http_cache`.

**Steps**
1. `SELECT id, confidence_score FROM leads ORDER BY id` — save as the baseline.
2. Record row counts in both cache tables.
3. `DELETE FROM ai_cache; DELETE FROM http_cache;`
4. Re-score every lead from stored components.
5. Diff against the baseline.
6. Re-run enrichment on the same content and count new API calls.

**Expected**
- Step 5: **every score identical.** No lead changes by any amount
- Step 6: calls are made again (the cache is cold) but produce the same analyses — cache affects
  cost and latency, never results

**Failure behaviour**
- Any score changing → the cache has become **state**. Something is reading a value that exists
  nowhere else, and the caches can never safely be cleared again — which is how a cache turns into an
  undocumented database nobody dares touch ([AD-18](../03-architecture.md))
- A lead becoming unscoreable → an analysis was reachable only via cache and was never persisted

**Edge cases**
- Deleting cache mid-run → the run continues, paying full price for the remainder
- A lead whose only analysis was cached → must not exist; `lead_analysis` is the durable record

**Success criteria**
- Both caches can be emptied at any moment with zero effect on any result

---

## Test 17 — Pattern discovery counts groups, costs nothing

**Test case** Patterns reflect distinct discussions, not repost volume, and use no AI.

**Preconditions** A project with ≥90 days of leads, including one thread with many near-duplicates.

**Steps**
1. `SELECT COUNT(*) FROM ai_calls` — record.
2. Run the nightly pattern aggregation.
3. Re-record the call count.
4. Open `/projects/<id>/patterns`.
5. Find a pain carried by a heavily-reposted thread; compare `occurrences` to `distinct_groups`.
6. Find a below-threshold row; try to promote it.
7. Find a `known` row; check it shows a trend rather than a promote control.

**Expected**
- Step 3: **identical count.** Zero AI calls — it is a `GROUP BY`
- Step 5: `occurrences` high, `distinct_groups` **1**. The threshold tests the second
- Step 6: greyed, **no promote control** — a single observation cannot become permanent knowledge
- Step 7: `known` rows show trend over time; they are market signal, not discovery

**Failure behaviour**
- Any AI call → someone reached for clustering on data that is already labelled, and the nightly job
  now costs money forever
- Thresholding on `occurrences` → one viral thread manufactures a pattern and can rewrite the
  knowledge base (R29)
- A promote control on a below-threshold row → the aggregate-only rule is defeated by the UI

**Edge cases**
- A project with 40 leads → nothing clears the threshold; the page says so rather than looking broken
- A pattern that later drops below threshold → stays visible with its history, not deleted
- Recomputing from scratch → identical output; `patterns` is a rebuildable projection

**Success criteria**
- Group-counted, free, and incapable of promoting a single observation

---

## Test 18 — Researcher view

**Test case** Richer metadata is available without degrading the default view.

**Steps**
1. Open a lead detail as a normal user. Confirm the default is the ten explanation fields and the
   score breakdown — nothing more.
2. Enable **Researcher view**.
3. Confirm each item in [06i §6](../06i-feedback-and-memory.md) renders: full evidence chain,
   component weights, confidence history, pattern history, pinned versions, tier and cost.
4. Reload; confirm the toggle persisted.
5. Turn it off; compare the rendered default against step 1.
6. Compare query counts on the default view before and after the feature exists.

**Expected**
- Default view unchanged, byte-for-byte, with the toggle off
- Every researcher field resolves to real stored data — nothing is computed on demand
- Step 6: **no additional queries** on the default path

**Failure behaviour**
- The default view gaining fields → the curated view has become a debug dump, and the screen now
  answers neither "should I act on this?" nor "is the system right?"
- Researcher fields triggering queries on the default path → an off-by-default feature is costing
  everyone latency

**Edge cases**
- A lead whose pinned BKB version was deleted → shows "version no longer available", never current
- A lead with no Tier 2 analysis → the tier row reads `1`, no empty section

**Success criteria**
- Off by default, persisted, additive only, and free when off

---

## Sign-off

| Test | Result | Notes |
|---|---|---|
| 1 CSV compatibility | ☐ Pass ☐ Fail | |
| 2 JSON export | ☐ Pass ☐ Fail | |
| 3 XLSX export | ☐ Pass ☐ Fail | |
| 4 Calibration | ☐ Pass ☐ Fail | |
| 5 Monitoring | ☐ Pass ☐ Fail | |
| 6 Maintenance | ☐ Pass ☐ Fail | |
| 7 Health page | ☐ Pass ☐ Fail | |
| 8 Empty/error states | ☐ Pass ☐ Fail | |
| 9 Performance | ☐ Pass ☐ Fail | |
| 10 **Security review** | ☐ Pass ☐ Fail | **Blocking** |
| 11 **Full regression** | ☐ Pass ☐ Fail | **Blocking** |
| 12 Fresh install | ☐ Pass ☐ Fail | |
| 13 **Golden set blocks** | ☐ Pass ☐ Fail | **Blocking** |
| 14 **Calibration ≠ re-ranking** | ☐ Pass ☐ Fail | **Blocking** |
| 15 **Drift fires, rollups free** | ☐ Pass ☐ Fail | |
| 16 **Cache is not state** | ☐ Pass ☐ Fail | **Blocking** |
| 17 **Patterns: groups, free** | ☐ Pass ☐ Fail | |
| 18 **Researcher view** | ☐ Pass ☐ Fail | |

---

## Final production sign-off

- [ ] All 8 phases' Part A checklists complete
- [ ] All 129 Part B manual tests passed
- [ ] Production readiness checklist in [10 §10](../10-implementation-roadmap.md) fully ticked
- [ ] `README.md` and `docs/RUNBOOK.md` complete and verified
- [ ] Live database backed up and verified restorable

**Project complete: 100%**
