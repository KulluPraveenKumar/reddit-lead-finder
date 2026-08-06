# Phase 04 — The Business Knowledge Base (One Consolidated Call)

**Completion after this phase: 50%**

## 1. Objective

Turn a website URL into a **persisted, versioned, entity-resolved Business Knowledge Base** — 23
typed sections spanning company identity, the buyer model, competitive and linguistic knowledge, and
activation entities ([06e §2](06e-business-knowledge-base.md)) — produced by **one** call to the AI
Service Layer, then enriched locally with entity resolution, evidence linkage, and vectors.

This is the first phase where the operator sees the product they were promised, the first real
exercise of the AI platform built in Phase 1, and — because every later phase reads from the BKB
rather than re-deriving context — **the phase that produces the platform's core asset**.

> **Rescoped by the 2026-07-30 research phase.** This phase previously produced four `ai_artifacts`
> blobs that downstream stages read once. That design discarded the richest artefact in the system —
> the specific weakness identified in both competitors ([02a §3](02a-competitor-analysis.md)).
> See [10 §1.1](10-implementation-roadmap.md) for the full record of what changed and why.

## 2. Scope

### 2.1 In scope

- `WebsiteFetcher` — bounded crawl + readability extraction, **via `ProxiedHTTPClient`**
- Revision `0005_projects_and_knowledge_base` — `projects`, `website_snapshots`, **`bkb`,
  `bkb_sections`**, `personas`, `pain_points`, `intent_signals`, **`bkb_entities`,
  `bkb_entity_aliases`, `bkb_links`, `bkb_evidence`, `bkb_suggestions`**, and the **conditional**
  `bkb_embeddings` + `bkb_embedding_meta`; plus the deferred FKs on `ai_calls` and `runs`
- **Local signal extraction before any AI** — competitor dictionary, pricing regex, tech markers, schema.org
- **L1 website cache** (fingerprint, 7 d) and **L2 BKB cache** (permanent) — a hit means zero AI
- **ONE consolidated `analyze_business()` call** producing all 23 sections, with **per-section
  failure isolation** — a repair failure in `content_themes` must not discard `pain_points`
- **`EntityRegistry`** — canonicalisation, deterministic alias generation (casing, spacing,
  misspelling, acronym, domain forms), and the four-tier resolver ([06e §4](06e-business-knowledge-base.md))
- **`bkb_evidence`** — verbatim span capture with substring validation, and **typed sources**
  (`website` | `reddit_post` | `reddit_comment` | `operator` | `ai_inference`).
  `ai_inference` is visibly marked and **can never be auto-promoted** ([06h §3](06h-knowledge-lifecycle.md))
- **Section lifecycle** — `last_verified_at`, per-type `staleness_days`, derived fresh/ageing/stale
  state. **Staleness never alters a score**
- **The `origin` guard** — every content row is `website` | `reddit_learned` | `operator`, and
  **regeneration deletes only `origin='website'` rows** ([AD-17](03-architecture.md)). This is the
  write-path property that makes knowledge accretion safe
- **Entity lifecycle** — `status` (`active` | `merged_into` | `retired`) so a renamed competitor
  keeps resolving and historical leads stay explainable
- **`SemanticIndex`** — Model2Vec + `sqlite-vec` over sections and entities; **degrades to disabled**
  if the extension will not load
- **`PrefixBuilder`** — renders the ~3,500-token matching surface, enforces `prefix_token_budget`,
  and **logs any dropped section** ([06e §6](06e-business-knowledge-base.md))
- Per-section versioning, supersede semantics, and `edited_by_user` protection
- `analyze_website` and `regenerate_section` job handlers
- `/projects` and `/projects/<id>` — the four BKB bands, prefix markers, evidence, aliases, inline
  editing, per-section regenerate
- Per-project cost visibility and cache-hit reporting
- `thin_content` detection and warning

### 2.2 Out of scope

- Subreddit recommendation and keyword generation (Phase 5) — the prompts exist from Phase 1;
  Phase 5 wires the discovery channels and gates around them
- **Knowledge suggestions being *generated*** — the `bkb_suggestions` table and its review UI ship
  here, but nothing writes proposals until enrichment exists in Phase 7
- Semantic dedup and semantic pre-score matching (Phase 6) — this phase builds the index; Phase 6
  is the first consumer
- Per-item enrichment (Phase 7)
- Headless-browser rendering for JS-only sites

## 3. Architecture

```
POST /api/projects {url}
   └─► ProjectService.create()  →  projects row
   └─► RunService.create()      →  runs row (PENDING)
   └─► enqueue("analyze_website")

Worker: handle_analyze_website
   │
   ├─ WebsiteFetcher.fetch(url)                  [ProxiedHTTPClient + trafilatura]
   │     ├─ landing page + ≤6 priority internal pages, ≤40 KB
   │     └─ website_snapshots row (text + content_hash)
   │         └─ hash matches a snapshot < 7 days old?  →  reuse, ZERO fetches
   │
   ├─ SiteSignals.extract(site)                  [LOCAL: competitors, pricing,
   │                                               tech markers, schema.org]
   │
   ├─ ai.analyze_business(site, signals)  → BKB, 23 sections   ← the ONLY stage that
   │     └─ per-section validation; a failure marks that            sees raw site text
   │        section `incomplete` and leaves the other 22 intact
   │
   ├─ persist bkb + bkb_sections ×23 (supersede), personas/pains/signals (upsert on slug)
   ├─ resolve entities + generate aliases (LOCAL)  ├─ link evidence spans (LOCAL)
   ├─ build semantic index (LOCAL, optional)     └─ render + measure the prefix (LOCAL)
   ├─ ai_calls rows; runs.llm_cost_usd updated
   └─ run.state = PROFILING → DISCOVERING     (Phase 5 picks it up)
```

**Two design decisions define this phase.**

**1. Local extraction before the model sees anything.** Competitors, pricing posture, tech markers,
`schema.org` metadata, and product taxonomy are extracted by regex and dictionary, then passed to
the model **as facts rather than questions**. Asking a model to find a `<meta generator>` tag is
paying tokens for a parser.

**2. One call, not six — and now it returns far more.** The original design made six generation
calls plus twelve per-subreddit keyword calls: 19 requests. All of it is one `analyze_business()`
request returning **23 BKB sections**. Keywords are produced once as a pool and specialised per
subreddit **deterministically**, by intersecting the pool with each subreddit's description
vocabulary. See [06 §3](06-ai-pipeline.md).

**19 calls → 1**, and the single call costs **$0.0037** rather than $0.0025 because it produces the
full knowledge base ([06e §8](06e-business-knowledge-base.md)). An eighth of a cent for a
substantially richer, reusable model of the business — and it is paid once per website version, not
once per run.

**3. Everything after the call is local.** Entity resolution, alias generation, evidence linkage,
embedding, and prefix rendering are deterministic Python. The model produces knowledge; the local
pipeline makes it *queryable*. None of this may reach a provider — enforced by the `src/knowledge/`
boundary grep ([03 §2](03-architecture.md)).

## 4. Files affected

**New**

| File | Purpose |
|---|---|
| `migrations/versions/0005_projects_and_knowledge_base.py` | 12 tables (+2 conditional) in the §7.1a order; deferred FKs on `ai_calls` and `runs` |
| `src/ai/website_fetcher.py` | `WebsiteFetcher`, `ExtractedSite` |
| `src/orchestration/handlers/website.py` | `analyze_website`, `regenerate_section` |
| `src/knowledge/bkb.py`, `sections.py`, `entities.py`, `links.py`, `evidence.py`, `prefix.py`, `semantic_index.py`, `suggestions.py` | The Knowledge tier ([03 §3](03-architecture.md)) |
| `src/db/repositories/knowledge.py` | Section supersede + entity/slug upsert |
| `src/db/repositories/projects.py` | Project CRUD |
| `src/dashboard/routes_projects.py` | Project endpoints |
| `src/dashboard/templates/base.html` | Extracted shell |
| `src/dashboard/templates/projects.html` | |
| `src/dashboard/templates/project_detail.html` | The four BKB bands, prefix markers, evidence, aliases |
| `tests/fixtures/sites/*.html` | Landing pages incl. an SPA shell and a 404 |

**Modified**

| File | Change |
|---|---|
| `src/db/models.py` | +`Project`, `WebsiteSnapshot`, `BKB`, `BKBSection`, `BKBEntity`, `BKBAlias`, `BKBLink`, `BKBEvidence`, `BKBSuggestion`, `Persona`, `PainPoint`, `IntentSignal` |
| `src/ai/service.py` | `analyze_business()` and `regenerate_section()` move from stub to implemented |
| `src/ai/schemas.py` | Finalised against real output |
| `src/ai/prompts/*.v1.md` | Refined against real sites; version bumped if changed |
| `src/dashboard/templates/index.html` | `{% extends "base.html" %}`, rendered output identical |
| `src/dashboard/app.py` | Registers `routes_projects` |
| `main.py` | `project add <url>` CLI |
| `requirements.txt` | `+trafilatura`, `+model2vec`, `+sqlite-vec` (both optional — import failure disables the semantic layer, never the app) |

**No AI infrastructure is written here.** `AIService`, the provider, the repair ladder, caching,
cost tracking, and the prompt framework all exist from Phase 1. This phase writes *domain* code.

## 5. Database changes

**`0005_projects_and_knowledge_base`** — `projects`, `website_snapshots`, `bkb`, `bkb_sections`, `personas`,
`pain_points`, `intent_signals` ([05 §5.1](05-database-plan.md)).

It also closes the **two** forward references left open by earlier revisions — see
[05 §7.1](05-database-plan.md):

```python
# ai_calls.project_id  (column created in 0002)
with op.batch_alter_table("ai_calls") as b:
    b.create_foreign_key("fk_ai_calls_project", "projects", ["project_id"], ["id"],
                         ondelete="SET NULL")

# runs.project_id  (column created in 0004, nullable)
with op.batch_alter_table("runs") as b:
    b.alter_column("project_id", nullable=False)
    b.create_foreign_key("fk_runs_project", "projects", ["project_id"], ["id"],
                         ondelete="CASCADE")
```

SQLite cannot `ADD CONSTRAINT`; `batch_alter_table` performs the create-copy-drop-rename rebuild.
**The `NOT NULL` tightening on `runs.project_id` is safe** because no run can exist before Phase 4
— there is no way to create one without a project.

## 6. APIs

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/projects` | List with run state and counts |
| `POST` | `/api/projects` | `{url, name?}`; validates scheme; 409 on duplicate `normalized_url` |
| `GET` | `/api/projects/<id>` | Project + BKB summary |
| `PUT` | `/api/projects/<id>` | Rename / archive |
| `DELETE` | `/api/projects/<id>` | Cascades the BKB; leads keep `project_id` (nullified in P6) |
| `GET` | `/api/projects/<id>/bkb` · `/bkb/sections/<key>` · `/bkb/entities` · `/bkb/suggestions` · `/bkb/prefix` | Full set in [09 §4.2](09-dashboard-plan.md) |
| `PUT` | `/api/projects/<id>/bkb/sections/<key>` | Operator edit; sets `edited_by_user=1`, bumps that section's version |
| `POST` | `/api/projects/<id>/bkb/sections/<key>/regenerate` | Single-section job; 409 if edited unless `?force=true` |
| `GET` | `/api/projects/<id>/cost` | Total USD, per-stage breakdown, cache-hit ratio |

## 7. UI changes

**`/projects`** — URL input + project cards ([09 §3.1](09-dashboard-plan.md)). If no API key is
configured, the input is disabled with a link to `/settings/ai`.

**`/projects/<id>`** — the four BKB bands ([09 §3.2](09-dashboard-plan.md)):

| Tab | Content |
|---|---|
| **Profile** | One-liner, industry, product category, positioning, delivery model, pricing posture, target audience, competitors, **verbatim evidence quotes**, confidence |
| **ICP** | Summary, industries, sizes, stages, budget authority, trigger events, disqualifiers |
| **Personas** | Card per persona: title, seniority, responsibilities, metrics, tools, likely subreddits, where they ask for help |
| **Pain Points** | Title, problem category, severity/frequency bars, **"how people phrase it"** |
| **Buying Intent** | Signal, tier, weight slider, example phrases |
| **Vocabulary** | Chip lists per category; **negative terms visually distinct in red** |

Every section is click-to-edit and independently regenerable. The header shows a cost chip
(`$0.004 · 1 call · 91% cached`) and the **prefix size** (`3.4k / 4.0k tokens`), because an operator
adding pain phrasings is changing matching behaviour and should see the number move.

Prefix membership is marked per section (`▣` in the enrichment prefix, `○` retrieval-only), so it is
clear which edits affect classification and which affect only presentation.

A `thin_content` project shows a persistent amber banner: *"We only found 180 characters of text on
this site. The knowledge base below may be inaccurate — consider editing it manually."*

## 8. AI changes

**One method moves from Phase-1 stub to implementation.** All AI mechanics — provider, repair
ladder, caching, retry, cost — are inherited unchanged from Phase 1.

| Stage | `AIService` method | Input | Output |
|---|---|---|---|
| 1 | `analyze_business` | Site text (≤40 KB) + locally extracted signals | **The full BKB — all 23 sections** |
| — | `regenerate_section` | Section key + persisted BKB context (no raw site text) | One section |

**Per-section failure isolation** is the structural requirement that makes a single 23-section call
safe. Each section is validated independently; a section that fails after the repair ladder is
persisted as `status='incomplete'` and is individually regenerable. Without this, one flaky section
would cost a full re-analysis every time — which is the strongest argument *against* consolidation,
and the reason it must be answered rather than ignored.

**Everything after the call is deterministic:** entity resolution and alias generation, evidence
linkage and substring validation, embedding, and prefix rendering. Zero additional AI calls.

**Anti-hallucination measures exercised for the first time here:**

- **Verbatim evidence check** — every `evidence` string must be a substring of the extracted site
  text after whitespace normalisation. Failures blank the field and flag `hallucinated_quote`.
- **`unknown` over invention** — the prompt requires the enum value or an empty list where the text
  is silent, rather than inference from general knowledge about similar companies.
- **`confidence` means textual support**, not domain familiarity — stated in the prompt and shown
  in the UI.
- **Slug pattern validation** on personas, pains, and signals; duplicates within one response are
  rejected and repaired.

**Expected cost: ≈ $0.0037 for the single call** ([06e §8](06e-business-knowledge-base.md)). A
re-run of an unchanged site is **$0.00** — snapshot reuse plus response-cache hits.

## 9. Backend changes

### 9.1 `WebsiteFetcher`

```python
@dataclass
class ExtractedSite:
    url: str
    pages: list[tuple[str, str]]     # (path, text)
    text: str                        # concatenated, ≤40 KB
    content_hash: str
    thin: bool                       # len(text) < 500
```

Goes through `ProxiedHTTPClient`, so a target site that rate-limits or geo-blocks is handled by
machinery that already exists — the payoff for AD-1 in [03](03-architecture.md). `trafilatura`
extracts; BeautifulSoup with `script/style/nav/footer/header` stripped is the fallback.

### 9.2 Artefact persistence

```python
def save_artifact(session, project_id, kind, obj, provider, model, stage, version, edited=False):
    session.query(AIArtifact).filter_by(project_id=project_id, kind=kind, superseded_at=None) \
           .update({"superseded_at": utcnow()})
    session.add(AIArtifact(project_id=project_id, kind=kind,
                           payload_json=obj.model_dump_json(),
                           provider=provider, model=model,
                           prompt_stage=stage, prompt_version=version,
                           edited_by_user=edited, created_at=utcnow()))
```

History is retained, so a regenerate that produces worse output is comparable rather than
irrecoverable.

Personas, pain points, and signals are **upserted on `(project_id, slug)`** so a regenerate updates
existing rows instead of orphaning the `lead_analysis` rows that will reference them from Phase 7.
A slug that disappears is soft-deleted, never hard-deleted.

### 9.3 Regenerate semantics

Re-runs **only** the named section, reusing the persisted snapshot and sibling sections. A section with
`edited_by_user=1` returns `409` unless `?force=true`, and the UI confirms first. Cost increases by
one stage only.

## 10. Frontend changes

- `base.html` extracted; `index.html` converted to extend it with **byte-identical rendered output**
  (snapshot test)
- `projects.html`, `project_detail.html`
- Inline-edit component: click → input → blur/Enter → `PUT` → toast
- Cost chip with cache-hit percentage
- `thin_content` amber banner
- Regenerate with confirm-on-edited

## 11. Risks

| Risk | Mitigation |
|---|---|
| JS-only SPA yields no text | `thin_content` detection, visible warning, reduced confidence, manual editing; headless browser documented as future work |
| Hallucinated profile from thin content | Verbatim evidence displayed — a wrong profile is *visibly* wrong in two seconds |
| Cost overrun on a large site | 40 KB extraction cap; per-call budget guard; context compression means only stage 1 is large |
| DeepSeek returns off-schema output for a complex site | Repair ladder from Phase 1; `repair_rate` tracked per stage; a persistently high rate signals a prompt revision |
| Slug collisions across regenerations | Upsert on `(project_id, slug)`; disappeared slugs soft-deleted |
| `base.html` extraction changes legacy rendering | Rendered-HTML snapshot diff before and after |
| Prefix cache not hitting on generation stages | Expected and acceptable — six calls with six different stable prefixes. Caching pays off in Phase 7, not here. |
| SSRF via a malicious project URL | Scheme allowlist (`http`/`https` only); private-IP posture documented and tested |

## 12. Dependencies

**Upstream:** Phase 1 (`AIService`, provider, prompts, cost, cache), Phase 2 (`ProxiedHTTPClient`),
Phase 3 (worker, run state machine).

**New packages:** `trafilatura`.

**External:** A validated DeepSeek key configured in Settings.

## 13. Acceptance criteria

- [ ] AC1 — `POST /api/projects {url}` creates a project and completes the BKB in < 3 min
- [ ] AC2 — **All 23 sections** persist and render on `/projects/<id>`, grouped into the four bands
- [ ] AC3 — Identity sections include industry, product category, target market, pricing positioning
- [ ] AC4 — 1–5 personas, each with a valid slug and likely subreddits
- [ ] AC5 — 3–12 pain points with `how_people_phrase_it`; 3–12 intent signals with tiers
- [ ] AC6 — Customer-language and Reddit-terminology sections have ≥5 terms; `negative_signals` has ≥3
- [ ] AC7 — Every `bkb_evidence.quote` is a **literal substring** of the snapshot text; non-matching spans are dropped and counted
- [ ] AC8 — **Exactly one** DeepSeek call for a full analysis (`SELECT COUNT(*) FROM ai_calls WHERE project_id=? AND stage='business_intelligence'` = 1)
- [ ] AC8b — Total cost for one project is **< $0.05** and is displayed
- [ ] AC8c — A re-analysis with an unchanged website fingerprint makes **zero** calls (L1/L2 hit)
- [ ] AC8d — Golden-set comparison: 23-section output quality is not worse than the four-artefact baseline
- [ ] AC9 — Re-running the same URL within 7 days costs **$0.00** (snapshot + response cache)
- [ ] AC10 — A site with < 500 chars sets `thin` and shows the banner; the run still completes
- [ ] AC11 — A 404 URL fails the run with a readable, non-technical message
- [ ] AC12 — `file://` and `javascript:` URLs are rejected at validation (422)
- [ ] AC13 — Editing a section persists, sets `edited_by_user`, and bumps that section's version only
- [ ] AC14 — Regenerating one section does not alter the others; edited ones require confirmation
- [ ] AC15 — With no API key, `/projects` explains why and links to Settings; `python main.py scrape` still works
- [ ] AC16 — `GET /` renders byte-identically after the `base.html` extraction
- [ ] AC17 — 459 leads intact; all 17 legacy endpoints unchanged
- [ ] **AC18 — Section failure isolation.** A forced schema failure in one section leaves the other 22 persisted and marks only the failed one `incomplete`
- [ ] **AC19 — Entity resolution.** `EntityRegistry.resolve()` returns the canonical competitor for exact, casing-variant, spacing-variant, and single-character-misspelling surface forms
- [ ] **AC20 — No duplicate registry.** No persona, pain point, or intent signal appears in `bkb_entities` (`SELECT COUNT(*) … WHERE kind IN ('persona','pain','signal')` = 0), **and** `bkb_sections.payload_json IS NULL` for exactly `buyer_personas`, `pain_points`, `buying_signals` — and **NOT NULL for the other twenty, including `ideal_customer_profiles`**, which has no typed table ([05 §5.1b](05-database-plan.md))
- [ ] **AC21 — Prefix budget.** `PrefixBuilder` output is ≤ `prefix_token_budget`; any dropped section is logged with its name and is visible via `GET /api/projects/<id>/bkb/prefix`
- [ ] **AC22 — Prefix membership is correct.** Every section flagged `in_prefix` is in the matching-surface list of [06e §6](06e-business-knowledge-base.md); no retrieval-only section appears in the rendered prefix
- [ ] **AC23 — Semantic layer degrades.** With `sqlite-vec` unavailable, migration `0005` completes, the app starts, `/health` reports `semantic_layer: disabled`, and every AC above still passes
- [ ] **AC25 — Origin guard.** Regenerate every section twice; **no `reddit_learned` or `operator` row is lost.** Seed rows of each origin first, or the test proves nothing
- [ ] **AC26 — Evidence is typed and complete.** Every BKB claim has ≥1 `bkb_evidence` row; zero rows fails validation; an `ai_inference` row carries no quote; `website` quotes are literal substrings
- [ ] **AC27 — Inference cannot self-promote.** No automatic path converts an `ai_inference`-only claim to confirmed, including repetition across regenerations
- [ ] **AC28a — Staleness is inert.** Advance the clock past every threshold, re-score a run, and confirm **every score is unchanged**; only the UI state differs
- [ ] **AC29 — Group C never stales.** Competitive and linguistic sections have `staleness_days IS NULL` and render no age badge
- [ ] **AC30 — Entity merge.** A `merged_into` entity resolves to its survivor; a lead scored against the old entity still renders its explanation
- [ ] **AC24 — Migration ordering.** `alembic upgrade head` succeeds on both an empty DB and a copy of the live DB; `alembic downgrade` to `0004` and back up again succeeds; the chain reports **one head**

## 14. Completion checklist

- [ ] Revision `0005_projects_and_knowledge_base` with downgrade; **tables created in the §7.1a order**; deferred FKs added via `batch_alter_table`; `runs.project_id` tightened to `NOT NULL`
- [ ] `sqlite-vec` load wrapped in `try/except`; failure logs a warning and skips both vector tables
- [ ] `WebsiteFetcher` with page/char budgets, timeouts, trafilatura + fallback
- [ ] `thin_content` detection
- [ ] Snapshot reuse on content hash within 7 days
- [ ] `analyze_business()` producing all 23 sections, with per-section failure isolation
- [ ] Context compression verified: only the BKB build receives raw site text
- [ ] Verbatim-evidence validation + `hallucinated_span_rate` counter
- [ ] Slug pattern + duplicate validation
- [ ] `EntityRegistry`: canonicalisation, five alias generators, four-tier `resolve()`
- [ ] `bkb_links` typed edges with polymorphic endpoints
- [ ] `SemanticIndex` over sections and entities; no-ops cleanly when disabled
- [ ] `PrefixBuilder` with enforced budget and logged drops
- [ ] `knowledge/lifecycle.py`: staleness state, per-type `staleness_days` seeding, origin-guarded regeneration
- [ ] `bkb_evidence.source_type` with per-type validation rules
- [ ] Section supersede + independent versioning; entity upsert on slug; soft-delete of vanished slugs
- [ ] `analyze_website` + `regenerate_section` handlers
- [ ] BKB API endpoints (§4.2 of [09](09-dashboard-plan.md)); URL scheme allowlist
- [ ] `base.html` extracted; `index.html` snapshot-identical
- [ ] `/projects` and `/projects/<id>` with the four BKB bands, prefix markers, evidence, aliases
- [ ] `bkb_suggestions` table + review UI present (empty until Phase 7 writes to it)
- [ ] Inline editing with toasts
- [ ] Cost chip with cache-hit percentage
- [ ] `main.py project add <url>`
- [ ] Site fixtures incl. SPA shell and 404; **no live AI calls in CI**
- [ ] `docs/testing/phase-04-testing.md` Part A complete
- [ ] `docs/testing/phase-04-testing.md` Part B executed and recorded
