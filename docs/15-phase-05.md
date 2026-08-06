# Phase 05 — Subreddit Discovery, Keyword Generation & Review Gates

**Completion after this phase: 63%**

## 1. Objective

Turn the ICP into **validated Reddit targets** the user has personally approved: discover subreddit
candidates through three independent channels, validate every one against live `old.reddit.com`,
rank them explainably, generate per-subreddit search keywords, and put both behind editable human
review gates.

This phase completes the pipeline up to the point of scraping. After it, the system knows exactly
where to look and what to look for — and a human has signed off on both.

## 2. Scope

### 2.1 In scope

- Revision `0006` — `project_subreddits`, `project_keywords`
- Discovery channels 1 (BKB-proposed), 2 (sitewide search harvest), 3 (sidebar graph), and
  **channel 4 — semantic match** of subreddit descriptions against the ICP and persona vectors built
  in Phase 4. Channel 4 finds communities whose *description* fits the ICP without sharing its
  vocabulary, which is exactly what the first three channels structurally cannot do
- Live validation of every candidate, with recorded rejection reasons
- Ranking with all five components persisted
- **Keyword generation reads the BKB** — customer language, Reddit terminology, search intent,
  content themes, and SEO/GEO entities (sections 14–16, 20–22) are all inputs, so keywords derive
  from a buyer model rather than from a summary of the homepage
- **Zero AI calls in this phase.** Every input already exists in the Business Knowledge Base;
  keyword expansion is deterministic composition over BKB sections plus live validation
- Run states `DISCOVERING`, `AWAITING_SUBREDDIT_REVIEW`, `GENERATING_KEYWORDS`,
  `AWAITING_KEYWORD_REVIEW`, `AWAITING_OPTIONS` fully wired
- Gate 1 UI (`/runs/<id>/subreddits`) and Gate 2 UI (`/runs/<id>/keywords`)
- Manual add with live validation; regenerate; approve
- Run-time and cost estimation for the options screen

### 2.2 Out of scope

- Author cross-posting as a discovery channel — deferred to future enhancements
- Actual scraping (Phase 6)
- Embedding-based semantic discovery

## 3. Architecture

```
run.state = PROFILING → DISCOVERING
   └─► enqueue("discover_subreddits")

Worker: handle_discover_subreddits
   ├─ ch1  ai.recommend_subreddits(ctx)          → 5–30 names + relevance + reasons
   ├─ ch2  for term in vocabulary.core_terms[:12]:
   │           reddit.search_posts(term, subreddit=None, limit=50, sort="relevance")
   │           Counter(post["subreddit"])        → empirical hit density
   ├─ ch3  for each validated sub: parse sidebar a[href^='/r/']   (one hop)
   ├─ union, record source_channels per candidate
   ├─ Validator: reddit.get_subreddit_info(name)  ← LIVE, uncached
   │      not found / private / banned / < MIN_SUBS  → rejected + reason
   ├─ Ranker: 5-component weighted score, all components persisted
   ├─ persist project_subreddits (status='proposed')
   └─ run.state = AWAITING_SUBREDDIT_REVIEW      ◄ worker idles here

  ── human ──►  edit / add / remove  ──►  POST approve-subreddits
                                              │
run.state = GENERATING_KEYWORDS ◄─────────────┘
   └─► enqueue("generate_keywords")

Worker: handle_generate_keywords
   ├─ global set:    ai.generate_keywords(ctx, subreddit=None)
   ├─ per subreddit: ai.generate_keywords(ctx, subreddit=info)
   ├─ negative terms from vocabulary → intent_tier='negative'
   ├─ dedupe across subreddits
   └─ run.state = AWAITING_KEYWORD_REVIEW        ◄ worker idles here

  ── human ──►  edit  ──►  POST approve-keywords  ──►  AWAITING_OPTIONS
```

**Both gates are worker-idle states.** No job is running, no lease is held, no timeout applies. The
run can sit there for a week.

## 4. Files affected

**New**

| File | Purpose |
|---|---|
| `migrations/versions/0006_targeting.py` | `project_subreddits`, `project_keywords` |
| `src/discovery/__init__.py` | |
| `src/discovery/candidates.py` | The three channels |
| `src/discovery/validator.py` | Live existence/health check |
| `src/discovery/ranker.py` | The weighted formula |
| `src/discovery/service.py` | `DiscoveryService` orchestration |
| `src/ai/keyword_generator.py` | |
| `src/orchestration/handlers/discovery.py` | `discover_subreddits` |
| `src/orchestration/handlers/keywords.py` | `generate_keywords` |
| `src/db/repositories/targeting.py` | |
| `src/dashboard/routes_review.py` | Gate endpoints |
| `src/dashboard/templates/review_subreddits.html` | Gate 1 |
| `src/dashboard/templates/review_keywords.html` | Gate 2 |
| `src/dashboard/templates/run_options.html` | Options + estimate |

**Modified**

| File | Change |
|---|---|
| `src/db/models.py` | +`ProjectSubreddit`, `ProjectKeyword` |
| `src/reddit_client.py` | `get_related_subreddits(html)` sidebar parser (new method, additive) |
| `src/orchestration/run_service.py` | `approve_subreddits`, `approve_keywords`, `set_options`, `estimate` |
| `src/orchestration/handlers/website.py` | On success, transitions to `DISCOVERING` and enqueues discovery |
| `src/dashboard/app.py` | Registers `routes_review` |

## 5. Database changes

Revision `0006_targeting` — DDL in [05 §5.2](05-database-plan.md).

`project_subreddits` notably stores `rank_components_json` (all five components) and
`validation_state` + `validation_note`, because both are rendered to the user. A ranking the user
cannot interrogate is a ranking they will not trust.

`project_keywords.subreddit_id` is nullable: `NULL` means "applies to every approved subreddit",
which is how the shared keyword group in the UI is represented.

## 6. APIs

**Gate 1**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/runs/<id>/subreddits` | Approved, proposed, and **rejected with reasons** |
| `POST` | `/api/runs/<id>/subreddits` | `{name}` — **validates live**; 422 with the reason if invalid |
| `PUT` | `/api/runs/<id>/subreddits/<sid>` | `{status}` |
| `DELETE` | `/api/runs/<id>/subreddits/<sid>` | User-added only |
| `POST` | `/api/runs/<id>/approve-subreddits` | `{ids[]}`; 422 if empty; transitions the run |
| `POST` | `/api/runs/<id>/rediscover` | Back to `DISCOVERING`, preserving user-added rows |

**Gate 2**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/runs/<id>/keywords` | Grouped: global, per subreddit, negatives |
| `POST` | `/api/runs/<id>/keywords` | `{query, intent_tier, subreddit_id?}` |
| `PUT` / `DELETE` | `/api/runs/<id>/keywords/<kid>` | |
| `POST` | `/api/runs/<id>/approve-keywords` | `{ids[]}` |
| `POST` | `/api/runs/<id>/regenerate-keywords` | |

**Options**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/runs/<id>/estimate?<options>` | `{requests, minutes, items, cost_usd}` — recomputed live as the user toggles |
| `POST` | `/api/runs/<id>/options` | `RunOptions` → `AWAITING_OPTIONS` → (Phase 6) `SCRAPING` |

## 7. UI changes

Three new pages, designed in [09 §3.3–3.5](09-dashboard-plan.md).

**Gate 1 highlights:**
- `found by: AI · search (14 hits) · sidebar` — multi-channel provenance is the strongest quality
  signal available and it is on every row
- Collapsed **rejected list with reasons** — the hallucination-transparency feature
- `[why? ▾]` expands all five ranking components with their values
- `[Select top 10]` fast path
- Manual add validates live and errors inline

**Gate 2 highlights:**
- Grouped by subreddit with a shared "applies to all" group
- **Negative-term panel on the same page** — the highest-leverage precision control, placed where
  the user is already thinking about matching
- Live estimate line: `32 keywords × 12 subreddits ≈ 384 searches ≈ 28 min`

**Options highlights:**
- Every toggle recomputes requests, minutes, items, and USD
- The user commits knowing the cost — this is what separates a controllable tool from a slot machine

## 8. AI changes

Two `AIService` methods move from Phase-1 stub to implemented. Both run on `deepseek-v4-flash`:

### `recommend_subreddits`

Input: ICP summary, personas (title + where they ask for help), vocabulary core terms.
Output: `SubredditProposals` (5–30, each with `relevance` and `persona_slugs`).

Prompt bias, stated explicitly in the file: *"Only name subreddits you are confident exist. A wrong
name costs a wasted request; an omitted one costs nothing, because we discover more by search."*
Precision over recall, because channel 2 supplies recall.

### `generate_keywords`

Input: vocabulary, pain points with `how_people_phrase_it`, one subreddit's name + description.
Output: `KeywordSet` (3–25, each tiered with a rationale).

Prompt rules:
- Queries must be valid old.reddit search syntax — no boolean operators old.reddit does not support
- Prefer phrases people actually type over marketing terms
- `high` = explicit request or dissatisfaction; `medium` = problem description; `low` = topical
- Never produce a query that is a single common word

**Cost:** ~$0.0008 for the recommendation + ~$0.0006 per subreddit for keywords. Twelve subreddits
**≈ $0.008** — under one cent ([06b §5.1](06b-deepseek-optimization.md)).

Both stages inherit the Phase-1 repair ladder, response cache, and cost guard unchanged. Neither
benefits much from prefix caching (each has its own stable prefix and runs a handful of times);
caching pays off in Phase 7, where the same prefix is sent thousands of times.

## 9. Backend changes

### 9.1 Channel 2 — the empirical backbone

```python
def _from_search(self, project) -> dict[str, int]:
    counts = Counter()
    for term in project.vocabulary.core_terms[:12]:
        posts = self.reddit.search_posts(term, subreddit=None, limit=50, sort="relevance")
        for p in posts:
            if p["subreddit"]:
                counts[p["subreddit"].lower()] += 1
    return counts
```

Twelve sitewide searches — ~24 requests with pagination — produce a frequency-ranked map of where
the vocabulary actually appears. This is the channel that catches subreddits the model has never
heard of, and it uses the `search_posts(subreddit=None)` branch that has existed and been unused
since day one.

### 9.2 Validation — the hallucination filter

```python
def validate(self, c: Candidate) -> bool:
    info = self.reddit.get_subreddit_info(c.name)      # use_cache=False — must be live
    if info is None:
        return c.reject("not_found", "Subreddit does not exist or is unreachable")
    if info["subscribers"] < self.min_subs:
        return c.reject("too_small", f"Only {info['subscribers']:,} members")
    if self._is_private(info) or self._is_banned(info):
        return c.reject("inaccessible", "Private, banned, or quarantined")
    c.subscribers, c.description = info["subscribers"], info["description"]
    return True
```

Every rejection is persisted with its reason and shown. This converts "the model might be wrong"
from a hidden product risk into a visible statistic — and the hallucination rate becomes a metric
the operator can watch.

### 9.3 Ranking

```python
def score(self, c: Candidate, project) -> tuple[float, dict]:
    comp = {
        "hit_density":       c.search_hits / max(1, total_hits),
        "llm_relevance":     c.llm_relevance or 0.0,
        "size":              min(1.0, math.log10(max(c.subscribers, 10)) / 7),
        "activity":          self._recency_of_newest_post(c),
        "channel_agreement": len(c.channels) / 3,
    }
    total = (0.30*comp["hit_density"] + 0.25*comp["llm_relevance"] + 0.20*comp["size"]
             + 0.15*comp["activity"] + 0.10*comp["channel_agreement"])
    return round(total, 4), comp
```

`size` is **log-scaled and capped**: a 12M-member default subreddit is usually a worse target than
a 40K-member niche one, and a linear subscriber weight would invert the correct ordering.

`activity` costs one extra request per candidate (first page of `/new/`) and is worth it — a
subreddit whose newest post is four months old is dead regardless of its subscriber count.

### 9.4 Estimation

```python
def estimate(run, options) -> Estimate:
    subs = count_approved_subreddits(run)
    kws  = count_approved_keywords(run)
    pages_per_query = ceil(options.limit_per_query / 25)
    requests = subs * (4 + kws * pages_per_query + 1)        # listing + searches + metadata
    if options.fetch_comments:
        requests += min(options.max_comment_posts, subs * 20)
    minutes  = requests * mean_request_seconds() / 60        # from observed metrics, not a constant
    items    = requests * 20 * 0.35                          # empirical new-item rate
    cost     = items * COST_PER_ITEM[options.analysis_model]
    return Estimate(requests, minutes, items, cost)
```

`mean_request_seconds()` reads the actual observed latency from the metrics table rather than
assuming, so the ETA improves as the system learns its own throughput.

## 10. Frontend changes

- Three new templates
- Checkbox-grid component with select-all / none / top-N
- Expandable `[why?]` rows rendering the component breakdown
- Collapsed rejected-list section
- Chip editor for keywords with tier badges
- Live estimate: debounced `GET /api/runs/<id>/estimate` on every toggle
- Stepper header (`Step 1 of 3 ●○○`) shared across the three gate pages

## 11. Risks

| Risk | Mitigation |
|---|---|
| LLM proposes non-existent subreddits | Mandatory live validation; rejections shown with reasons; prompt biased to precision |
| Channel 2 returns mostly noise for a niche vocabulary | Hit-density normalisation; channel agreement rewards multi-channel candidates; the user still approves |
| Validation costs too many requests | ~30 candidates × 2 requests = 60, proxied and rate-limited; ~5 minutes, shown as progress |
| Keyword explosion (25 × 15 subs = 375 searches) | `limits.max_keywords_per_subreddit`; live estimate before commit; user prunes at Gate 2 |
| User approves zero subreddits | `Continue` disabled with an inline explanation; API returns 422 |
| Gate state lost on restart | State is a DB column; the worker is idle at the gate with no lease held |
| Regenerate wipes user-added rows | `status='user_added'` rows are preserved across regeneration |
| Sidebar parsing breaks on unusual layouts | Best-effort channel; failure logs and continues; channels 1 and 2 still deliver |
| Estimate is wildly wrong | Uses observed latency; explicitly labelled an estimate; run page shows real ETA once running |

## 12. Dependencies

**Upstream:** Phase 1 (`AIService`, prompts, cost, cache), Phase 2 (`RedditClient` + sitewide
`search_posts`), Phase 3 (state machine, gates), Phase 4 (ICP, personas, vocabulary).

**New packages:** none.

## 13. Acceptance criteria

- [ ] AC1 — Discovery produces ≥ 10 validated candidates for a typical B2B SaaS ICP
- [ ] AC2 — Every candidate has `source_channels` recorded
- [ ] AC3 — A hallucinated subreddit is rejected as `not_found` and shown in the rejected list
- [ ] AC4 — ≥ 70% of AI-proposed subreddits survive validation
- [ ] AC5 — Ranking components are persisted and rendered by `[why?]`
- [ ] AC6 — Run enters `AWAITING_SUBREDDIT_REVIEW` and stays there indefinitely
- [ ] AC7 — Restarting the process leaves the run at the gate, unchanged
- [ ] AC8 — Manually adding a non-existent subreddit returns 422 with a readable reason
- [ ] AC9 — Approving with zero selections returns 422
- [ ] AC10 — Approving transitions to `GENERATING_KEYWORDS` and enqueues the job
- [ ] AC11 — Keywords generated per approved subreddit plus a global set
- [ ] AC12 — Negative terms appear as `intent_tier='negative'` and render distinctly
- [ ] AC13 — The estimate updates live and is within ±30% of the observed Phase 6 run
- [ ] AC14 — Regenerating preserves `user_added` rows
- [ ] AC15 — Total AI cost for discovery + keywords **< $0.05** for 12 subreddits
- [ ] AC16 — 459 leads intact; all 17 legacy endpoints unchanged

## 14. Completion checklist

- [ ] Revision `0006_targeting` with downgrade
- [ ] Channel 1 — `ai.recommend_subreddits()` with the precision-biased prompt
- [ ] Channel 2 — sitewide search harvest with hit-density counting
- [ ] Channel 3 — sidebar graph, one hop
- [ ] Candidate union with `source_channels` tracking
- [ ] Live validator with all four rejection reasons
- [ ] Ranker with 5 components, log-scaled size, persisted breakdown
- [ ] `discover_subreddits` handler → `AWAITING_SUBREDDIT_REVIEW`
- [ ] `ai.generate_keywords()` implemented against the Phase-1 prompt
- [ ] Negative terms materialised as keyword rows
- [ ] Cross-subreddit keyword dedup
- [ ] `generate_keywords` handler → `AWAITING_KEYWORD_REVIEW`
- [ ] `approve_subreddits` / `approve_keywords` / `set_options` in `RunService`
- [ ] Estimation using observed latency
- [ ] All gate API endpoints incl. live-validating manual add
- [ ] Gate 1 UI with provenance, `[why?]`, rejected list, select-top-N
- [ ] Gate 2 UI with grouping, tiers, negative panel, live estimate
- [ ] Options UI with live estimate
- [ ] Stepper component
- [ ] `docs/testing/phase-05-testing.md` Part A complete
- [ ] `docs/testing/phase-05-testing.md` Part B executed and recorded
