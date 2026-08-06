# Phase 04 — Testing: The Business Knowledge Base

---

# PART A — Claude Verification

## A1. Architecture

- [ ] Handlers call `AIService` **domain methods only** — no prompt, model, or token appears outside `src/ai/`
- [ ] `grep -ri "deepseek" src/ --exclude-dir=ai/providers` → still **0**
- [ ] `WebsiteFetcher` uses `ProxiedHTTPClient`, not `requests` directly
- [ ] No AI *infrastructure* is written in this phase — only domain code
- [ ] Prompts are files, not string literals — `grep -rn 'You are a' src/ --include=*.py` returns nothing
- [ ] BKB persistence is in a repository, not in the handler
- [ ] Context compression verified: **only** `analyze_business` receives raw site text
- [ ] The `origin` guard lives in the repository write path, **not** in the route or the template
- [ ] `src/knowledge/` does not import `src.ai` (grep)

## A2. Compilation and imports

- [ ] `python -c "import src.ai"` succeeds without a key configured
- [ ] A missing key does not raise at import time (only at first call)
- [ ] All Pydantic models import cleanly
- [ ] `trafilatura` import has a guarded fallback

## A3. Lint / A4. Typing

- [ ] `ruff check .` / `ruff format --check .` clean
- [ ] Every Pydantic model has typed fields with `Field(...)` constraints
- [ ] `Literal` used for every enum-like field, never bare `str`
- [ ] `slug` fields carry the `pattern` constraint
- [ ] `analyze_business` and `regenerate_section` are fully annotated with typed return models
- [ ] All 23 section payload models are typed; `origin` and `source_type` are `Literal`, never bare `str`

## A5. Edge cases

- [ ] URL with no scheme → `https://` prepended
- [ ] URL with a trailing slash / fragment / query → normalised consistently
- [ ] URL that 404s → run fails with a readable message
- [ ] URL that redirects cross-domain → followed once, logged
- [ ] Site with a `robots.txt` disallow → behaviour matches the configured `respect_robots`
- [ ] Site returning 200 with an empty body → `thin_content`
- [ ] JS-only SPA (near-zero text) → `thin_content`, not a crash
- [ ] Site with 500 internal links → only 6 fetched, budget respected
- [ ] A single internal page timing out → skipped, others continue
- [ ] Extracted text exceeding 40 KB → truncated at a character boundary
- [ ] Non-UTF-8 page → decoded with a fallback, no `UnicodeDecodeError`
- [ ] Model returns 4 personas → accepted; 6 → schema rejects, retry
- [ ] Model returns an invalid slug (`Persona One`) → schema rejects, retry
- [ ] Model returns `confidence: 1.5` → schema rejects
- [ ] Duplicate slugs in one response → deduped or rejected (documented)
- [ ] Regenerating a section with `edited_by_user=1` → 409 unless forced
- [ ] Regenerating a section containing only `reddit_learned` rows → succeeds, deletes nothing
- [ ] A claim submitted with zero evidence rows → rejected
- [ ] An `ai_inference` evidence row carrying a quote → rejected
- [ ] `staleness_days IS NULL` → never stales at any age
- [ ] A section exactly at its staleness threshold → `stale` (boundary inclusive)
- [ ] Creating a project with an existing `normalized_url` → 409

## A6. Error handling

- [ ] Error classification inherited from Phase 1; no new try/except around provider calls in this phase
- [ ] `SchemaValidationError` surfaced after the repair ladder, not silently swallowed
- [ ] `BudgetExceededError` raised **before** the call, not after
- [ ] `InsufficientBalanceError` (402) surfaces as the amber product state, not a generic failure
- [ ] Missing API key → clear message, AI disabled, scraping unaffected
- [ ] A section failing validation preserves the other 22 (per-section isolation)
- [ ] A regeneration failing mid-way is transactional — no partial deletion of `website` rows

## A7. Security

- [ ] The API key is read only through `CredentialStore`, never `os.environ` directly
- [ ] Key never logged, never in `ai_calls`, never in a template
- [ ] Full-run log capture grepped for the DeepSeek key → zero matches
- [ ] Model output rendered through Jinja autoescaping; **no `|safe` on any model-generated content**
- [ ] Fetched website HTML never rendered raw into the UI
- [ ] Project URL validated (scheme allowlist `http`/`https`; no `file://`, no `javascript:`)

## A8. Performance

- [ ] Website fetch bounded: ≤ 7 pages, ≤ 40 KB, 15 s per page
- [ ] Snapshot reuse on content-hash match within 7 days → zero fetches
- [ ] Response-cache hit → zero API calls, zero cost
- [ ] **Context compression**: section regeneration receives persisted BKB context, not the ~12,000-token site text
- [ ] Generation completes in under 3 minutes for a typical site
- [ ] `/projects/<id>` renders in < 300 ms

## A9. Scalability

- [ ] `bkb_sections` supersede rather than accumulate unbounded current rows
- [ ] Entity upsert on `(project_id, slug)` — no orphan accumulation across regenerations
- [ ] `ai_cache` keyed on a hash, not on full prompt text
- [ ] `ai_calls` growth bounded by the maintenance purge

## A10. Logging

- [ ] Each AI call logs stage, model, prompt version, tokens (cached/uncached), cost, latency, cache status
- [ ] Website fetch logs each page: URL, status, extracted chars
- [ ] `thin_content` logged at WARNING
- [ ] Repair-ladder branch and reason logged per attempt
- [ ] `project_id` on every line

## A11. Retries

- [ ] Repair retries (empty / invalid JSON / schema) inherited from Phase 1, ≤2 each
- [ ] Transport retries (429/500/503/timeout) inherited from Phase 1
- [ ] Job-level retry (max 3) wraps the whole stage
- [ ] Website page fetch retried by `ProxiedHTTPClient`

## A12. Regression

- [ ] `GET /` renders **byte-identically** after the `base.html` extraction (snapshot diff)
- [ ] 459 leads intact
- [ ] CSV export 13 columns
- [ ] All 17 legacy endpoints unchanged
- [ ] `python main.py scrape` works with **no** API key configured
- [ ] Phase 1–3 test suites still pass

## A13. Test suite

- [ ] `pytest` passes; **no live AI calls in CI** — the BKB build runs on `FakeProvider`
- [ ] Recorded provider fixtures covering a full 23-section response and a per-section failure
- [ ] A test asserts each prompt file's content hash matches its recorded version hash
- [ ] Site fixtures include an SPA shell and a 404
- [ ] A test asserts every `website` / `reddit_*` evidence quote is a substring of its source
- [ ] A test seeds all three origins and asserts a double regeneration loses none

---

# PART B — Manual Testing

---

## Test 1 — Website analysis end to end

**Preconditions** A validated DeepSeek key in `/settings/ai`; worker running; proxies healthy.

**Steps**
1. Open `/projects`.
2. Enter a real B2B SaaS URL (e.g. `https://www.notion.so` or your own product).
3. Click **Analyse**.
4. Watch the run progress.
5. When complete, open `/projects/<id>`.
6. Click through all four BKB bands.

**Expected**
- Project created; run enters `profiling`
- Progress shows website fetch, then each generation stage
- Completes in under 3 minutes
- **Profile tab**: one-liner accurately describes the company; category correct; competitors listed if named on the site; confidence shown
- **ICP tab**: industries, sizes, stages, trigger events, disqualifiers — all plausible
- **Personas tab**: 1–5 personas, each with a title, seniority, responsibilities, tools, likely subreddits
- **Pain Points tab**: 3–12, each with severity/frequency and "how people phrase it" in colloquial language
- **Buying Intent tab**: 3–12 signals with tiers and example phrases
- **Vocabulary tab**: ≥5 core terms, ≥3 negative terms, negatives visually distinct
- Cost chip shows a figure under $0.05

**Failure behaviour**
- Run fails → read `runs.error`; likely the URL is unreachable or the key is invalid
- Empty tabs → generation succeeded but persistence failed
- Nonsense profile → check the Evidence panel; if evidence is nav text, the site is JS-only

**Edge cases**
- Very small site (one page) → fewer pages fetched, lower confidence
- Very large site → page budget caps at 7
- Non-English site → works or degrades; note the outcome
- URL with a redirect → followed, final URL recorded

**Success criteria**
- All six artefacts generated, plausible, and under $0.05

---

## Test 2 — Evidence is verbatim *(the hallucination check)*

**Preconditions** Test 1 completed.

**Steps**
1. Open the Profile tab; note the evidence quotes.
2. Open the analysed website in a browser.
3. Use Ctrl-F to search for each evidence quote **exactly**.
4. Repeat for 3 quotes.

**Expected**
- Every quote is found verbatim on the site
- No paraphrases, no invented marketing copy

**Failure behaviour**
- A quote is not on the site → the verbatim validator is not running, or is not enforced. **This is a blocking defect** — the evidence panel is the trust mechanism.

**Edge cases**
- Quote spans two elements → whitespace-normalised comparison should still pass
- Quote from a page other than the landing page → still valid (all fetched pages count)
- Empty evidence array → acceptable if the site is thin; flag it

**Success criteria**
- 3/3 quotes verifiable on the source site

---

## Test 3 — Thin-content detection

**Preconditions** A JS-only SPA URL, or a local server serving `<html><body><div id="root"></div></body></html>`.

**Steps**
1. Create a project with the SPA URL.
2. Wait for completion.
3. Open `/projects/<id>`.
4. Inspect the banner and the confidence values.

**Expected**
- Run **completes** (does not fail)
- Amber banner: *"We only found N characters of text on this site…"*
- Confidence values are low (< 0.5)
- Artefacts still generated, clearly marked as low confidence
- User can edit every field

**Failure behaviour**
- Run fails hard → thin content should degrade, not abort
- Confident-looking profile with no warning → **the worst failure mode**; everything downstream inherits garbage silently

**Edge cases**
- Exactly 500 chars → boundary; confirm which side it falls on and that the behaviour is consistent
- 0 chars → banner plus a suggestion to enter the profile manually

**Success criteria**
- Detected, warned, degraded gracefully, still editable

---

## Test 4 — Cost tracking and caching

**Preconditions** A completed project.

**Steps**
1. Note the cost chip on `/projects/<id>`.
2. `SELECT stage, model, input_tokens_uncached, input_tokens_cached, output_tokens, cost_usd, outcome FROM ai_calls WHERE project_id=?;`
3. Delete the project's artefacts (or create a **second** project with the same URL).
4. Re-run analysis.
5. Compare cost and `outcome` values.

**Expected**
- First run: 6 `ai_calls` rows, `outcome='ok'`, **total < $0.05**
- Second run on the same URL within 7 days: website snapshot **reused** (zero fetches), LLM cache hit, `outcome='cached'`, **cost $0.00**
- Cost chip shows `$0.00 · 0 calls · 6 cached`

**Failure behaviour**
- Second run costs the same → cache key includes something volatile; inspect it
- Cost figures implausible (e.g. $50) → price table wrong or `max_tokens` runaway

**Edge cases**
- Change a prompt version → cache miss, full cost (correct — this is the point of `prompt_version` in the key)
- 8 days later → snapshot expires, refetched

**Success criteria**
- First run < $0.05; identical re-run $0.00

---

## Test 5 — Cost cap enforcement

**Preconditions** Set `ai.budget.max_cost_per_run_usd: 0.002`.

**Steps**
1. Create a project with a content-heavy URL.
2. Watch the run.
3. Inspect the run state and error.
4. Raise the cap to $2.00 and retry.

**Expected**
- The run stops when the projected cost would exceed $0.002
- Partial artefacts (whatever completed) are preserved
- Clear message naming the cap and the spend
- On retry with a higher cap, it completes

**Failure behaviour**
- Cap ignored → budget check is after the call, not before
- All work discarded → partial preservation not implemented

**Edge cases**
- Cap set below the cost of a single call → fails on stage 1 with a clear message
- Cap of 0 → AI effectively disabled with a clear message

**Success criteria**
- Cap enforced pre-call; partial work preserved; retry works

---

## Test 6 — Editing artefacts

**Preconditions** A completed project.

**Steps**
1. On the Profile tab, click the one-liner; edit it; press Enter.
2. Reload the page.
3. On the Personas tab, change a job title.
4. On the Buying Intent tab, drag a weight slider.
5. `SELECT kind, edited_by_user FROM ai_artifacts WHERE project_id=? AND superseded_at IS NULL;`

**Expected**
- Each edit persists across reload
- A success toast appears
- `edited_by_user = 1` for edited artefacts
- Weight changes persist to `intent_signals.weight`

**Failure behaviour**
- Edit lost on reload → PUT not wired or not committed
- Silent failure → **the existing silent-AJAX-failure pattern**; must show a toast

**Edge cases**
- Empty value → validation error, edit rejected with a message
- 10,000-character value → truncated or rejected with a message
- Concurrent edit in two tabs → last write wins (acceptable; document it)

**Success criteria**
- Edits persist; `edited_by_user` set; failures visible

---

## Test 7 — Regenerate a single artefact

**Preconditions** A completed project with an **edited** ICP.

**Steps**
1. On the Personas tab, click **Regenerate**.
2. Observe: does it warn about the edit?
3. Confirm.
4. Verify only the Personas tab changed.
5. Try regenerating the edited ICP.

**Expected**
- Regenerating a non-edited artefact proceeds directly
- Regenerating an **edited** artefact shows a confirmation first
- Only the targeted artefact changes; others are untouched
- The old version is retained with `superseded_at` set
- Cost increases by one stage only

**Failure behaviour**
- Regenerate wipes everything → the job is re-running the whole pipeline
- No warning on an edited artefact → user work silently destroyed

**Edge cases**
- Regenerate personas after the ICP changed → uses the current ICP
- Regenerate with no upstream artefact → clear error
- Rapid double-click → the duplicate-run guard applies

**Success criteria**
- Single-stage regeneration; edits protected; history retained

---

## Test 8 — Error handling: bad URL

**Preconditions** Worker running.

**Steps**
1. Create a project with `https://this-domain-definitely-does-not-exist-99999.com`.
2. Observe the run.
3. Create one with a URL that 404s on a real domain.
4. Create one with `file:///etc/passwd`.
5. Create one with `javascript:alert(1)`.

**Expected**
- Non-existent domain → run fails with *"Could not reach <url>"*, no traceback in the UI
- 404 → similar, naming the status
- `file://` and `javascript:` → **rejected at validation**, project never created (422)
- No crash in any case

**Failure behaviour**
- `file://` accepted → **security defect**; local file read
- Raw traceback shown to the user → error mapping missing

**Edge cases**
- URL with a port → allowed
- `localhost` / `127.0.0.1` / `169.254.169.254` → consider blocking (SSRF); document the decision
- Extremely slow site → times out at 15 s per page

**Success criteria**
- Bad URLs fail cleanly; dangerous schemes rejected

---

## Test 9 — Operating without an API key

**Preconditions** Clear the API key from `/settings/ai`.

**Steps**
1. Restart the dashboard.
2. Observe the startup message.
3. Open `/projects`.
4. Try to create a project.
5. Run `python main.py scrape`.
6. Open `/`.

**Expected**
- Startup logs *"AI features disabled — no API key configured"*
- `/projects` shows a banner explaining AI is disabled
- Creating a project is either blocked with an explanation or creates one without artefacts
- `/projects` disables the URL input and links to `/settings/ai`
- **`python main.py scrape` works normally**
- Legacy dashboard fully functional

**Failure behaviour**
- App refuses to start → AI must be optional
- Scraping broken → the phases are not independent

**Edge cases**
- Invalid key (not empty) → `AuthenticationError` surfaced clearly on first use
- Key added later → works after restart

**Success criteria**
- The product degrades to a working scraper without AI

---

## Test 10 — Legacy dashboard after `base.html` extraction

**Preconditions** Pre-Phase-4 HTML snapshot of `/`.

**Steps**
1. Open `/`; save the source.
2. Diff against the pre-phase snapshot.
3. Verify all three charts render.
4. Exercise every filter, sort, and pagination control.
5. Exercise all six sidebar cards.
6. Export CSV.

**Expected**
- Diff limited to the new "Projects" header link and timestamps
- All charts, filters, and sidebar functions unchanged
- CSV: 13 columns

**Failure behaviour**
- Layout shifted → the extraction changed CSS ordering
- A chart missing → the Chart.js script tag moved out of scope
- Any sidebar card broken → JS block scoping changed

**Edge cases**
- Very narrow viewport → layout still usable
- Zero leads → empty state renders

**Success criteria**
- Visually and functionally identical apart from the new nav link

---

## Test 11 — All 23 BKB sections, and section failure isolation

**Test case** The Business Knowledge Base is complete, and one bad section does not destroy the rest.

**Preconditions** A content-rich site fixture; a `FakeProvider` able to inject a schema-invalid
payload for a single named section.

**Steps**
1. Analyse a real site. On `/projects/<id>`, count the sections rendered across the four bands.
2. `SELECT section_key FROM bkb_sections WHERE bkb_id=?` — confirm 23 distinct keys.
3. Confirm each band contains the sections listed in [06e §2](../06e-business-knowledge-base.md).
4. Re-run with the provider injecting an invalid `content_themes` payload.
5. Inspect `bkb_sections` again.

**Expected**
- 23 sections, each with a `payload_json` and a `confidence`
- After step 4: 22 sections `status='ok'`, `content_themes` `status='incomplete'`, `bkb.status='partial'`
- The UI shows `content_themes` as incomplete with a `Regenerate` action; the other 22 render normally

**Failure behaviour**
- Fewer than 23 keys → the consolidated prompt is dropping sections; check `max_tokens` for truncation
- The whole BKB failing on one bad section → failure isolation is not implemented, and one flaky
  section will cost a full re-analysis every time

**Edge cases**
- A section legitimately empty (no competitors found) → present with an empty payload, **not** absent
- Two sections failing → both marked, remaining 21 intact

**Success criteria**
- 23 sections always present; a single section failure is contained to that section

---

## Test 12 — Entity resolution and competitor aliases

**Test case** Competitor mentions are caught through surface forms no keyword list would contain.

**Preconditions** A BKB whose competitor registry includes `Segment`.

**Steps**
1. On `/projects/<id>`, open the Competitors section and note the generated aliases.
2. Call `EntityRegistry.resolve()` (or the debug endpoint) with, in turn: `"Segment"`,
   `"segment"`, `"segment.io"`, `"segement"`, `"Segment.com"`, and the unrelated `"segmentation"`.
3. Add a hand-written alias via `POST /api/projects/<id>/bkb/entities/<eid>/aliases`; resolve it.

**Expected**
- Tier 1 (exact), tier 2 (normalised), and tier 3 (fuzzy) each resolve their cases to the same
  canonical entity, and the tier used is reported
- `"segmentation"` resolves to **nothing** — a false positive here would inject a spurious
  high-weight signal into every affected lead
- The hand-added alias resolves immediately, `source='confirmed'`

**Failure behaviour**
- `"segement"` missing → fuzzy tier absent or its edit-distance threshold too tight
- `"segmentation"` matching → the threshold is too loose; tighten before shipping, because
  competitor mention is one of the highest-weighted signals in the score

**Edge cases**
- A single-character competitor name → fuzzy matching must be **disabled** below the 5-character
  token floor, or everything matches
- Two competitors with similar names → each resolves to itself, never to the other

**Success criteria**
- All legitimate surface forms resolve; the near-miss does not

---

## Test 13 — The enrichment prefix is bounded and correct

**Test case** Only the matching surface enters the prefix, and the budget is enforced visibly.

**Preconditions** A BKB; `prefix_token_budget` temporarily lowered to force a drop.

**Steps**
1. `GET /api/projects/<id>/bkb/prefix`; record the token count and the sections present.
2. Compare the section list against the matching-surface table in
   [06e §6](../06e-business-knowledge-base.md).
3. Confirm the `▣` / `○` markers on `/projects/<id>` match `bkb_sections.in_prefix`.
4. Lower `prefix_token_budget` to 1,500 and rebuild.
5. Check the logs and `bkb.dropped_sections_json`.

**Expected**
- Token count ≤ budget; no retrieval-only section (products, features, pricing, JTBD, value props,
  outreach angles, content themes, SEO/GEO entities) appears in the rendered prefix
- After step 4: sections dropped in the documented priority order, each **named in the log** and
  recorded in `dropped_sections_json`

**Failure behaviour**
- Prefix over budget → batch attention dilution (R23); the safe batch size silently drops
- A silent truncation with no log line → classification behaviour changes with no visible cause,
  which is the specific failure this test exists to prevent

**Edge cases**
- An operator adding 40 pain phrasings → token count rises visibly on `/projects/<id>`
- Budget large enough for everything → nothing dropped, `dropped_sections_json` is null

**Success criteria**
- Prefix membership matches the specification; drops are always logged, never silent

---

## Test 14 — The semantic layer degrades cleanly

**Test case** A host without `sqlite-vec` still gets a fully working platform.

**Preconditions** A way to make the extension unloadable (rename the binary, or set
`semantic.enabled: false`).

**Steps**
1. With the extension unavailable, run `alembic upgrade head` on an empty database.
2. Start the app; open `/health`.
3. Analyse a website end to end.
4. Confirm `bkb_embeddings` and `bkb_embedding_meta` are absent.
5. Restore the extension, re-run migrations on a fresh DB, and confirm both tables exist.

**Expected**
- Migration **completes**, logging `sqlite-vec unavailable (…); semantic layer disabled`
- `/health` reports `semantic_layer: disabled`
- The BKB builds with all 23 sections, entity resolution tiers 1–3 working; only tier 4 is inactive
- Every other Phase-4 acceptance criterion still passes

**Failure behaviour**
- Migration aborting → the schema is un-installable on that host in exchange for a recall
  improvement, which is never the right trade (R25)
- `/health` silent about it → a degraded system that looks healthy is worse than one that fails

**Edge cases**
- The extension disappearing *after* vectors exist → reads fail soft, tier 4 is skipped, tiers 1–3 continue
- Re-enabling it later → vectors rebuild on the next BKB regeneration, keyed by `model_name`

**Success criteria**
- The platform is fully functional without the extension, and says so

---

## Test 15 — The origin guard: regeneration must not delete learned knowledge

**Test case** Regenerating a section replaces only what regeneration originally wrote.

**Preconditions** A BKB with rows of all three origins in `customer_language` and
`competitor_references`: `website` rows from the original build, a `reddit_learned` row from an
accepted suggestion, and an `operator` row added by hand.

**Steps**
1. Record every row in both sections with its `origin`.
2. Regenerate `customer_language` via the UI. Re-record.
3. Regenerate it a second time. Re-record.
4. Regenerate **every** section in a loop, twice. Re-record all.
5. Call the regenerate handler **directly**, bypassing the UI, and re-record.

**Expected**
- After every step: **zero `reddit_learned` or `operator` rows lost**, in any section
- `website` rows are replaced by the new generation
- Step 5 behaves identically — the guard is in the write path, not the UI

**Failure behaviour**
- A `reddit_learned` row disappearing → months of accumulated knowledge can be destroyed by one
  click, invisibly, because the section still looks populated afterwards. This is R28, the most
  likely real data-loss bug in the plan
- Step 5 diverging from step 2 → the guard lives in the UI layer and a scheduled job will bypass it

**Edge cases**
- A section with **only** `reddit_learned` rows → regeneration adds `website` rows beside them
- A `reddit_learned` row whose text duplicates a new `website` row → both retained, deduped at read
- Regeneration failing mid-way → transactional; no partial deletion

**Success criteria**
- Learned and operator knowledge survives arbitrary regeneration, through every entry point

---

## Test 16 — Evidence typing and the inference ceiling

**Test case** Every claim is attributed, and inference can never promote itself.

**Preconditions** A completed BKB; a `FakeProvider` able to return crafted output.

**Steps**
1. Query `bkb_evidence` grouped by `source_type`; confirm all five types are representable.
2. Confirm every BKB claim has ≥1 evidence row. Inject a claim with none.
3. Confirm `website` quotes are literal substrings of the snapshot; `ai_inference` rows carry **no**
   quote.
4. Regenerate a section three times, each producing the same inferred persona. Check its status.
5. Promote a claim as an operator; inspect the resulting evidence row.

**Expected**
- Step 2: the zero-evidence claim **fails validation** and is not persisted
- Step 3: an `ai_inference` row with a quote is rejected — there is nothing for it to quote
- Step 4: the persona remains inference-backed. **Repetition is not corroboration**; a model
  agreeing with itself three times is one opinion
- Step 5: an `operator` evidence row records who and when

**Failure behaviour**
- Inference silently promoting after N agreements → the observed/inferred distinction collapses and
  the knowledge base fills with confident guesses
- A claim with zero evidence persisting → unattributable knowledge, which is the failure the whole
  evidence model exists to prevent

**Edge cases**
- A thin site producing mostly inference → the BKB builds, and the UI shows how much is inferred
- Reddit-sourced evidence whose lead was deleted → the evidence row survives with a null lead ref
  and is marked as orphaned rather than dropped

**Success criteria**
- All five source types work; no automatic path converts inference to confirmed

---

## Test 17 — Staleness is visible and inert

**Test case** Age is shown to the operator and changes nothing about scoring.

**Preconditions** A project with leads scored; ability to advance the clock or back-date
`last_verified_at`.

**Steps**
1. Record every lead's `confidence_score`.
2. Back-date all sections well past their thresholds.
3. Reload `/projects/<id>`; check badges per group.
4. Re-score the run. Compare every score to step 1.
5. Check Group C sections specifically.

**Expected**
- Step 3: Group A/B/D show `stale` badges with a suggested action; **Group C shows nothing**
- Step 4: **every score identical** — staleness is an operator signal, never a score input
- No section regenerates automatically

**Failure behaviour**
- Any score changing → the score has become clock-dependent, breaking the reproduction guarantee
  ([AD-19](../03-architecture.md)) and every historical explanation with it
- Group C badging → invites the regeneration Test 15 exists to prevent
- Automatic regeneration → an operator's hand-tuned ICP is overwritten while nobody is watching

**Edge cases**
- A section exactly at its threshold → `stale` (boundary inclusive, asserted)
- `staleness_days IS NULL` → never stales, whatever the age

**Success criteria**
- Badges correct per group; scores bit-identical across an arbitrary clock advance

---

## Sign-off

| Test | Result | Notes |
|---|---|---|
| 1 Website analysis | ☐ Pass ☐ Fail | |
| 2 **Verbatim evidence** | ☐ Pass ☐ Fail | **Blocking** |
| 3 Thin content | ☐ Pass ☐ Fail | |
| 4 Cost & caching | ☐ Pass ☐ Fail | |
| 5 Cost cap | ☐ Pass ☐ Fail | |
| 6 Editing | ☐ Pass ☐ Fail | |
| 7 Regenerate | ☐ Pass ☐ Fail | |
| 8 Bad URLs | ☐ Pass ☐ Fail | |
| 9 No API key | ☐ Pass ☐ Fail | |
| 10 Legacy dashboard | ☐ Pass ☐ Fail | |
| 11 **23 sections + failure isolation** | ☐ Pass ☐ Fail | |
| 12 **Entity resolution** | ☐ Pass ☐ Fail | **Blocking** — false positives corrupt scoring |
| 13 **Prefix bounded and correct** | ☐ Pass ☐ Fail | |
| 14 **Semantic layer degrades** | ☐ Pass ☐ Fail | |
| 15 **Origin guard** | ☐ Pass ☐ Fail | **Blocking** — data loss (R28) |
| 16 **Evidence typing** | ☐ Pass ☐ Fail | **Blocking** |
| 17 **Staleness inert** | ☐ Pass ☐ Fail | |

**Phase 4 complete when Part A is fully ticked and all 17 Part B tests pass.**
