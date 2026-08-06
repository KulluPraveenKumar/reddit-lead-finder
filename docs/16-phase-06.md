# Phase 06 — Scrape Execution, Comments & the Local Processing Pipeline

**Completion after this phase: 75%**

## 1. Objective

Execute the approved targeting plan: scrape posts from the approved subreddits using the approved
keywords, **wire up the comment parser that has existed and never been called**, back-fill missing
scores, and attach everything to the project.

After this phase the pipeline runs end to end — URL in, project-scoped leads and comments out —
with only AI ranking left to add.

## 2. Scope

### 2.1 In scope

- **`src/rules/`** — keyword tiers, negatives, structural noise, competitor matching **via the
  Phase-4 `EntityRegistry` (alias-resolved, not a flat dictionary)**, author heuristics
- **`src/dedupe/`** — the three-tier cascade: exact content hash → MinHash + LSH → **semantic
  neighbours** (cosine ≥ 0.88, from the Phase-4 index), then representative selection.
  Tier 3 **degrades to a no-op** when the semantic layer is disabled
- **`src/scoring/prescore.py`** — deterministic 0–100 pre-score, all components persisted, including
  **semantic pain-point matching** so a post that describes a pain in untracked words still scores
- **Everything in this phase reads the Business Knowledge Base and calls no model.** The grep
  boundary (`src/rules/`, `src/dedupe/`, `src/scoring/`, `src/knowledge/` may not import `src.ai`)
  is a phase-6 acceptance criterion, not just an architectural aspiration
- Revision `0007_content_and_dedup` — `leads.project_id`, `leads.confidence_score`, `leads.analysis_status`,
  **`leads.source`** (`scrape` | `holdout_audit` — the exploration channel, [06i §2.3](06i-feedback-and-memory.md)),
  `dedup_groups`, `dedup_members`, `minhash_bands`, `prescores`,
  `comments`, plus indexes
- `BaseScraper` refactor; `SubredditScraper` and `KeywordScraper` become project-aware
- `CommentScraper` — new, wrapping the existing `_parse_comments`
- Comment depth extraction and `body_hash` dedup
- Score back-fill for search-sourced leads during comment fetch
- Per-tier keyword thresholds
- Job fan-out: one `scrape_subreddit` per subreddit, then `scrape_comments`, then `finalize_run`
- Run states `SCRAPING` → `ANALYZING` (Phase 7 consumes) → `COMPLETE`
- Lead budget enforcement and truncation reporting
- Deterministic scraper ordering
- Project-scoped lead views

### 2.2 Out of scope

- AI analysis and confidence scoring (Phase 7) — leads are written with
  `analysis_status='pending'` and `confidence_score=NULL`
- `a.morecomments` expansion
- Concurrency beyond the default single in-flight request

## 3. Architecture

```
POST /api/runs/<id>/options
   └─► run.state = AWAITING_OPTIONS → SCRAPING
   └─► for each approved subreddit: enqueue("scrape_subreddit")

Worker: handle_scrape_subreddit          (session_key = f"sub:{name}")
   ├─ SubredditScraper   /r/<sub>/new/         ← if mode in (listing, both)
   ├─ KeywordScraper     /r/<sub>/search?…     ← one walk per approved keyword
   ├─ per page:  filter_new() → score → insert qualifying → COMMIT
   ├─ update `subreddits` metadata row
   ├─ ScrapeRun audit row (run_id set)
   └─ when the LAST scrape job for this run completes:
         if options.fetch_comments: enqueue("scrape_comments")
         else:                      enqueue("finalize_run")

Worker: handle_scrape_comments
   ├─ select candidate leads: qualifying score AND num_comments >= N, capped
   ├─ per lead: GET permalink → _parse_comments(max_depth=4)
   │             ├─ back-fill lead.score from data-score if NULL
   │             ├─ pre-filter each comment
   │             └─ insert Comment (dedup on body_hash)
   └─ enqueue("finalize_run")

Worker: handle_finalize_run
   ├─ aggregate stats into runs.stats_json
   └─ run.state = SCRAPING → ANALYZING  (Phase 7)  |  → COMPLETE (until then)
```

## 4. Files affected

**New**

| File | Purpose |
|---|---|
| `migrations/versions/0007_content_and_dedup.py` | `leads` columns (incl. `source`) + indexes, `comments`, `dedup_groups`, `dedup_members`, `minhash_bands`, `prescores` |
| `src/scrapers/base.py` | `BaseScraper`, `ScrapeContext`, `ScrapeReport` |
| `src/scrapers/comment_scraper.py` | |
| `src/db/repositories/comments.py` | |
| `src/dashboard/routes_leads.py` | Project-scoped lead endpoints |
| `src/dashboard/templates/run_leads.html` | |

**Modified**

| File | Change |
|---|---|
| `src/db/models.py` | `Lead` +4 columns (incl. `source`); +`Comment` |
| `src/scrapers/subreddit_scraper.py` | Extends `BaseScraper`; project-aware; ctx-driven limits |
| `src/scrapers/keyword_scraper.py` | Extends `BaseScraper`; approved keywords from `project_keywords`; per-tier thresholds |
| `src/scrapers/user_scraper.py` | Extends `BaseScraper`; behaviour unchanged |
| `src/scrapers/__init__.py` | `SCRAPER_ORDER` constant |
| `src/reddit_client.py` | `_parse_comments` gains `depth` + `body_hash`; `max_depth` param |
| `src/orchestration/handlers/scrape.py` | Fan-out, comment enqueue, finalize |
| `src/orchestration/run_service.py` | `set_options` starts scraping |
| `main.py` | Uses `SCRAPER_ORDER` |

## 5. Database changes

Revision `0007_content_and_dedup`:

```sql
ALTER TABLE leads ADD COLUMN project_id       INTEGER NULL REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE leads ADD COLUMN confidence_score REAL    NULL;
ALTER TABLE leads ADD COLUMN analysis_status  VARCHAR(20) NOT NULL DEFAULT 'not_analyzed';
ALTER TABLE leads ADD COLUMN source           VARCHAR(20) NOT NULL DEFAULT 'scrape';
                                              -- scrape | holdout_audit  (06i §2.3)

CREATE INDEX ix_leads_project_id       ON leads (project_id);
CREATE INDEX ix_leads_confidence_score ON leads (confidence_score);
CREATE INDEX ix_leads_analysis_status  ON leads (analysis_status);
CREATE INDEX ix_leads_project_conf     ON leads (project_id, confidence_score DESC);

CREATE TABLE comments (...);   -- see 05 §5.4
```

**The 459 existing rows get `project_id = NULL`, `confidence_score = NULL`,
`analysis_status = 'not_analyzed'`, `source = 'scrape'` — all of which are semantically correct.** No row is rewritten;
`ALTER TABLE ADD COLUMN` with a default is a metadata-only operation in SQLite.

`Lead.score` becomes `nullable=True` at the ORM level (no `ALTER` needed — SQLite already accepts
NULL there) so search-sourced leads can store "unknown".

## 6. APIs

**Extended**

| Route | New query params |
|---|---|
| `GET /api/leads` | `project_id`, `run_id`, `has_comments` |
| `GET /` | `project_id` — legacy default (`None`) shows everything, unchanged |
| `GET /api/leads/export` | `project_id`, `run_id` |

**New**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/runs/<id>/leads` | Paginated, project-scoped |
| `GET` | `/api/leads/<id>/comments` | Comments for a lead |
| `GET` | `/api/runs/<id>/stats` | Posts seen, leads created, comments, truncation flags |

## 7. UI changes

- **`/runs/<id>/leads`** — the ranked table (sorted by `intent_score` this phase; confidence
  arrives in Phase 7), with a comment-count column
- **Comments in the lead view** — expandable inline list, indented by `depth`
- **Run progress page** gains live scrape counters: posts seen, leads created, comments fetched,
  current subreddit
- **Truncation banner** when a limit was hit: *"Stopped at 2,000 leads (your limit). Raise
  `max_total_leads` to collect more."*
- The **legacy dashboard is unchanged** — with no `project_id` filter it shows all leads, including
  the new project-scoped ones, exactly as before

## 8. AI changes

**No new AI code.** Leads and comments land with `analysis_status='pending'`; Phase 7 enriches them.

Two decisions here exist to make Phase 7's enrichment cheap, and are worth stating where the data is
produced rather than where it is consumed:

- **`comments.body_hash` doubles as the enrichment dedup key.** The same content hash that prevents
  duplicate comment rows also lets Phase 7 recognise that two items carry identical text and analyse
  them once. Crossposts, reposts, and quoted replies therefore cost nothing to enrich.
- **Comment candidates are selected by descending `intent_score`**, so when the cap bites it drops
  the *least* promising posts. Enrichment quality is bounded by collection quality; spending the
  comment budget on the best posts is what makes the AI spend worthwhile.

`finalize_run` transitions to `ANALYZING` when AI is enabled and configured, and straight to
`COMPLETE` otherwise — so the pipeline is fully usable with no API key.

## 9. Backend changes

### 9.1 `BaseScraper`

```python
class BaseScraper(ABC):
    @abstractmethod
    def collect(self, ctx: ScrapeContext) -> Iterator[tuple[list[dict], dict]]:
        """Yield (page_of_posts, meta) where meta carries query/tier for threshold selection."""

    def run(self, session, ctx) -> ScrapeReport:
        scorer, report = LeadScorer(self.config, session), ScrapeReport(ctx.subreddit)
        for page, meta in self.collect(ctx):
            report.posts_seen += len(page)
            for post in self.repo.filter_new(session, page):
                res = scorer.score_post(post["title"], post["body"] or "",
                                        post["score"], post["num_comments"], post["created_utc"])
                threshold = TIER_MIN_SCORE.get(meta.get("tier"), ctx.min_score)
                if scorer.is_lead(res, min_score=threshold):
                    session.add(self._to_lead(post, res, ctx))
                    report.leads_created += 1
            session.commit()                               # per page: crash-safe
            if self._budget_exhausted(session, ctx, report):
                report.truncated = True; break
        self._record_scrape_run(session, ctx, report)
        return report
```

Per-page commits are finer-grained than today's per-subreddit commit, so a crash loses at most 25
posts of work instead of a whole subreddit.

### 9.2 `CommentScraper`

```python
def _candidates(self, session, ctx) -> list[Lead]:
    return (session.query(Lead)
            .filter(Lead.project_id == ctx.project_id,
                    Lead.subreddit == ctx.subreddit,
                    Lead.num_comments >= ctx.min_post_comments_for_comment_fetch)
            .order_by(desc(Lead.intent_score))
            .limit(ctx.max_comment_posts).all())
```

Ordered by `intent_score` descending so that when the cap bites, it drops the *least* promising
posts. Comment fetching is the most expensive collection step — one request per post with no
pagination reuse — so the cap and the ordering both matter.

```python
def _fetch_one(self, session, lead, ctx):
    html = self.client._get(lead.url, session_key=f"sub:{lead.subreddit}")
    if not html:
        return 0
    self._backfill_score(session, lead, html)
    n = 0
    for c in self.client._parse_comments(html, max_depth=4)[: ctx.max_comments_per_post]:
        if not self._prefilter(c):
            continue
        try:
            with session.begin_nested():
                session.add(Comment(lead_id=lead.id, project_id=ctx.project_id, **c))
            n += 1
        except IntegrityError:
            pass                       # body_hash collision = already have it
    return n
```

`begin_nested()` around each insert means a duplicate comment is skipped without rolling back the
whole batch — the correct handling for a unique-constraint backstop.

### 9.3 Score back-fill

```python
def _backfill_score(self, session, lead, html):
    if lead.score is not None:
        return
    thing = BeautifulSoup(html, "lxml").select_one("div.thing.link[data-fullname]")
    if thing:
        s = thing.get("data-score", "")
        if s.lstrip("-").isdigit():
            lead.score = int(s)
            lead.intent_score = self._rescore(session, lead)
            emit_event(session, lead_run_id, "comments.score_backfilled",
                       lead_id=lead.id, score=lead.score)
```

Free accuracy: a request already being made yields the field that search results omit.

### 9.4 Per-tier thresholds

```python
TIER_MIN_SCORE = {"high": 3.0, "medium": 5.0, "low": 8.0}
```

A `high`-tier keyword is itself evidence of intent, so a post it matched qualifies at a lower total.
This replaces the current flat `min_score=5` for all keyword-sourced leads
([00 §4.3](00-current-state.md)) with something that reflects what the keyword actually meant.

### 9.5 Ordering determinism

`SCRAPER_ORDER = ("subreddit", "keyword", "user")`, imported by both `main.py` and the dashboard
handler. This closes [00 §4.10](00-current-state.md) — the same input now produces the same leads
regardless of entry point.

## 10. Frontend changes

- `run_leads.html`
- Expandable comment list in the lead row, indented by depth
- Live scrape counters on the run progress page
- Truncation banner
- Project filter on the legacy dashboard (opt-in dropdown; default "all" preserves current
  behaviour exactly)

## 11. Risks

| Risk | Mitigation |
|---|---|
| Comment scraping doubles run time | Capped by `max_comment_posts` (default 100) and `min_post_comments`; shown in the estimate; toggleable |
| `comments` table growth | 100 posts × 30 comments = 3,000 rows/run — modest; cascades on lead delete |
| Migration on the live DB adds columns to `leads` | `ADD COLUMN` with a default is metadata-only in SQLite; auto-backup; downgrade tested; row count asserted |
| Legacy dashboard hides new leads or shows them wrong | Default `project_id=None` means no filter — verified by a snapshot test |
| Back-fill rescoring changes existing scores | Only runs where `score IS NULL`, which no legacy lead has |
| Lead budget silently truncates | `truncated` flag + banner + `run_events` entry |
| Per-page commits slow the scrape | Negligible next to a 3–7 s network delay per request |
| Comment dedup misses on edited comments | Accepted — an edited comment is arguably new content; the `body_hash` design makes this explicit |

## 12. Dependencies

**Upstream:** Phases 1–5. Phase 5's approved subreddits and keywords are the direct input.

**New packages:** none.

## 13. Acceptance criteria

- [ ] AC1 — Approving options starts scraping and the run reaches a terminal state
- [ ] AC2 — Leads are created with the correct `project_id`
- [ ] AC3 — One `scrape_subreddit` job per approved subreddit; all complete or fail individually
- [ ] AC4 — Search pagination returns > 25 results per query where available (Phase 1 fix, verified end to end)
- [ ] AC5 — Comments are extracted and stored with `depth` and `body_hash`
- [ ] AC6 — Re-running comment extraction creates zero duplicates
- [ ] AC7 — Search-sourced leads have their `score` back-filled during comment fetch
- [ ] AC8 — `high`-tier keywords qualify at a lower threshold than `low`-tier
- [ ] AC9 — Lead budget truncates cleanly, sets the flag, and shows the banner
- [ ] AC10 — One dedup query per page, not one per post (statement counter)
- [ ] AC11 — Killing the worker mid-scrape and restarting resumes remaining subreddits with no duplicates
- [ ] AC12 — `GET /` with no `project_id` shows all leads, legacy and new, unchanged
- [ ] AC13 — 459 legacy leads have `project_id IS NULL` and render identically
- [ ] AC14 — CSV export still returns the original 13 columns by default
- [ ] AC15 — `main.py scrape` and the dashboard produce identical results for identical input
- [ ] AC16 — All 17 legacy endpoints unchanged
- [ ] **AC17 — Zero AI in this phase.** A full run completes with `AIService` replaced by a provider that raises on any call; `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` = 0
- [ ] **AC18 — Boundary grep passes.** `grep -rn "import.*src\.ai" src/rules/ src/dedupe/ src/scoring/ src/knowledge/` returns nothing
- [ ] **AC19 — Dedup tier 3 adds recall.** On a fixture containing paraphrase pairs that share no character 5-grams, tier 3 groups them and tiers 1–2 do not
- [ ] **AC20 — Tier 3 never rejects.** With the semantic layer disabled, the same run completes and produces the same *lead set* (fewer groups, identical membership count); no lead is lost
- [ ] **AC21 — Group for analysis, score individually.** A group of N members yields N distinct pre-scores; identical scores across a group is a failure
- [ ] **AC22 — Alias-resolved competitor matching.** A post using only a competitor alias contributes the competitor component to the pre-score

## 14. Completion checklist

- [ ] Revision `0007_content_and_dedup` with downgrade
- [ ] `BaseScraper` / `ScrapeContext` / `ScrapeReport`
- [ ] Three existing scrapers refactored onto the base; behaviour preserved
- [ ] `CommentScraper` implemented
- [ ] `_parse_comments` gains `depth`, `body_hash`, `max_depth`
- [ ] Comment pre-filter
- [ ] `body_hash` dedup with `begin_nested()` + `IntegrityError` handling
- [ ] Score back-fill with rescore
- [ ] Per-tier thresholds
- [ ] Job fan-out and completion detection
- [ ] `scrape_comments` and `finalize_run` handlers
- [ ] Lead budget enforcement + truncation reporting
- [ ] `SCRAPER_ORDER` used by both entry points
- [ ] Project-scoped lead endpoints
- [ ] `run_leads.html` with comment expansion
- [ ] Live scrape counters on the progress page
- [ ] Legacy dashboard verified unchanged
- [ ] `docs/testing/phase-06-testing.md` Part A complete
- [ ] `docs/testing/phase-06-testing.md` Part B executed and recorded
