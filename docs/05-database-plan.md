# 05 — Database Plan

## 1. Governing constraints

1. **A live database exists** — `data/leads.db`, 459 leads, 10 scrape runs, 6 settings.
   It must keep opening and rendering after every migration.
2. **`create_all()` cannot alter tables.** Adding `leads.confidence_score` will not happen by
   itself. Alembic is mandatory.
3. **SQLite ignores foreign keys unless `PRAGMA foreign_keys=ON`.** Every `ON DELETE` clause in this
   plan is inert without it.
4. **Additive only.** No existing column is dropped, renamed, or retyped. No existing row is
   rewritten by a migration.

---

## 2. The single biggest decision: project scoping

**Stated assumption, made explicit rather than decided silently:**

> The product is single-operator and multi-project. One website URL owns one project, and a project
> owns its own profile, ICP, personas, subreddits, keywords, runs, leads, and comments.
> Existing leads predate projects and belong to none.

**Implementation:** `leads.project_id INTEGER NULL REFERENCES projects(id) ON DELETE SET NULL`.

| Alternative | Why rejected |
|---|---|
| `project_id NOT NULL` with a backfilled "Legacy" project | Rewrites 459 existing rows; fabricates a project with no website, no ICP, and no run; breaks the "no migration rewrites data" rule |
| Separate `project_leads` table | Duplicates the entire Lead model, splits the dedup index, doubles every query |
| No scoping (keep global) | Two projects targeting different ICPs would poison each other's lead lists and share a keyword namespace — the product stops working |

**Query consequence.** The legacy dashboard (`GET /`) shows *everything*: `WHERE 1=1`. A project
view filters `WHERE project_id = :pid`. A "legacy leads" view filters `WHERE project_id IS NULL`.
This is applied in exactly one place — `LeadRepository` — never inline in a route.

---

## 3. Existing schema — frozen

| Table | Change |
|---|---|
| `leads` | **+3 nullable columns** (§4.1). Nothing else. |
| `subreddits` | none |
| `dashboard_subreddits` | none |
| `dashboard_keywords` | none |
| `dashboard_search_queries` | none |
| `settings` | none (new keys are new rows) |
| `tracked_users` | none |
| `scrape_runs` | **+1 nullable column** `run_id` (§4.2) |

That is the complete set of changes to existing tables across the entire project.

---

## 4. Changes to existing tables

### 4.1 `leads`

```sql
-- ⚠️ project_id ships BARE. NO `REFERENCES projects(id)` at 0006 — the FK is
--    added in 0007, which creates `projects`. See §7.1: writing the clause here
--    breaks every INSERT into leads, silently. This is the shipped DDL.
ALTER TABLE leads ADD COLUMN project_id       INTEGER NULL;
ALTER TABLE leads ADD COLUMN confidence_score REAL   NULL;
ALTER TABLE leads ADD COLUMN analysis_status  VARCHAR(20) NOT NULL DEFAULT 'not_analyzed';
ALTER TABLE leads ADD COLUMN source           VARCHAR(20) NOT NULL DEFAULT 'scrape';

CREATE INDEX ix_leads_project_id       ON leads (project_id);
CREATE INDEX ix_leads_confidence_score ON leads (confidence_score);
CREATE INDEX ix_leads_analysis_status  ON leads (analysis_status);
CREATE INDEX ix_leads_project_conf     ON leads (project_id, confidence_score DESC);
-- Four columns, four indexes. `source` deliberately has none.
```

- `source` ∈ `scrape | holdout_audit`. **Added 2026-08-11 (P8).** Its DDL previously existed only in
  [16 §115](16-phase-06.md) — a superseded, read-only document — while
  [freeze §4.1](ARCHITECTURE_FREEZE.md) said *"`leads` +4"* and [34 §P8](34-implementation-plan.md)
  asserted `source='scrape'` in its acceptance criteria. The definition is moved here, verbatim, so
  the frozen schema carries the column it has always counted. It is the fix for
  [R27](10-implementation-roadmap.md), the degenerate-learning-loop risk: a holdout-audited item
  must become a real, labellable lead, or the yield curve is fitted only on the gate's own
  admissions and recall collapses invisibly. **No index** — its only consumer, P11's holdout, reads
  by run — and **no `CHECK`** on the domain, because every other enumerated column here
  (`analysis_status`, `gate_decision`, `method`) is a bare `VARCHAR`.
- `project_id` — NULL for the 459 existing rows, forever, **and bare until `0007`**.
- `confidence_score` — **NULL means "never analysed"**, which is semantically different from 0.0
  ("analysed and judged worthless"). Sorting must place NULLs last, not first.
- `analysis_status` ∈ `not_analyzed | pending | analyzed | failed | skipped`. Defaults on existing
  rows to `not_analyzed`, which is exactly correct.
- `intent_score` is **untouched** and keeps its current meaning. This is the guarantee that the 459
  rows stay usable.

Also change `score` to allow NULL going forward (SQLite is dynamically typed; the existing
`INTEGER DEFAULT 0` column already accepts NULL at the storage layer, so this is a model-level
change only — `Column(Integer, nullable=True)` — with no `ALTER`). This implements the
search-score fix from [02 §3](02-research-findings.md).

### 4.2 `scrape_runs`

```sql
ALTER TABLE scrape_runs ADD COLUMN run_id INTEGER NULL REFERENCES runs(id) ON DELETE SET NULL;
```

Existing 10 rows keep `NULL`. New scrapes link to their orchestrated run. The table stays as the
per-scraper audit record it already is; `runs` is the higher-level concept.

---

## 5. New tables

### 5.1 Project and the Business Knowledge Base

```sql
CREATE TABLE projects (
    id                INTEGER PRIMARY KEY,
    name              VARCHAR(200) NOT NULL,
    website_url       TEXT NOT NULL,
    normalized_url    TEXT NOT NULL,                 -- scheme+host, lowercased, no trailing slash
    status            VARCHAR(20) NOT NULL DEFAULT 'active',   -- active | archived
    created_at        DATETIME NOT NULL,
    updated_at        DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_projects_normalized_url ON projects (normalized_url);

-- Website fetch cache + provenance. Separate from projects so a re-analysis can compare.
CREATE TABLE website_snapshots (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    extracted_text TEXT NOT NULL,
    content_hash  VARCHAR(64) NOT NULL,
    fetched_at    DATETIME NOT NULL
);
CREATE INDEX ix_website_snapshots_project ON website_snapshots (project_id);

-- The Business Knowledge Base: one current row per project. Replaces `ai_artifacts`.
CREATE TABLE bkb (
    id              INTEGER PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL DEFAULT 1,
    model           VARCHAR(60) NOT NULL,
    prompt_version  INTEGER NOT NULL,
    prefix_tokens   INTEGER NULL,      -- measured size of the enrichment prefix (06e §6)
    dropped_sections_json TEXT NULL,   -- sections omitted from the prefix by budget, if any
    status          VARCHAR(20) NOT NULL DEFAULT 'complete',  -- complete|partial|failed
    created_at      DATETIME NOT NULL,
    superseded_at   DATETIME NULL
);
CREATE INDEX ix_bkb_current ON bkb (project_id, superseded_at);

-- 23 rows per BKB. Each section versions independently (06e §3.2).
CREATE TABLE bkb_sections (
    id              INTEGER PRIMARY KEY,
    bkb_id          INTEGER NOT NULL REFERENCES bkb(id) ON DELETE CASCADE,
    section_key     VARCHAR(40) NOT NULL,   -- company_overview | pain_points | ... (23 values)
    -- ⚠️ NULLABLE, corrected 2026-08-15 (P12). This said `TEXT NOT NULL`, which
    --    §5.1b below then contradicts by requiring NULL for exactly three keys.
    --    §5.1b wins — it is the later and more specific rule, and it carries its
    --    reasoning. The biconditional ships as ck_bkb_sections_payload_null_rule
    --    rather than as a convention. See freeze §11.1.
    payload_json    TEXT NULL,              -- validated Pydantic model, json.dumps(sort_keys=True)
    confidence      REAL NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    in_prefix       BOOLEAN NOT NULL DEFAULT 0,   -- matching surface vs retrieval-only (06e §6)
    edited_by_user  BOOLEAN NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'ok',  -- ok|incomplete
    created_at      DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_bkb_sections ON bkb_sections (bkb_id, section_key);
```

**Why `bkb_sections` keeps a JSON payload rather than 23 typed tables:** the sections are read
whole, written whole, and never filtered by their internal fields. Typed columns would cost a
migration every time a section's schema gains a field. The Pydantic model *is* the schema;
`prompt_version` records which one applied. What changed from the old `ai_artifacts` design is not
the storage strategy but the *granularity and lifecycle* — 23 independently versioned, independently
regenerable, independently prefix-flagged sections instead of four monolithic artefacts.

**Why `ai_artifacts` is gone rather than kept alongside.** Its four kinds (`business_profile`,
`icp`, `pain_analysis`, `vocabulary`) are wholly subsumed by BKB sections 1–6, 7, 9, and 14–15
respectively. Keeping both would mean two sources of truth for the same facts, and the older one
would rot. `0005` never ships `ai_artifacts`, so there is no data to migrate — the table is removed
from the plan, not deprecated in it.

Personas, pain points, and intent signals **are** promoted to real tables, because they are
referenced by foreign key from analysis rows and are filtered on:

```sql
CREATE TABLE personas (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    slug         VARCHAR(60) NOT NULL,          -- stable id used in LLM output enums
    name         VARCHAR(120) NOT NULL,
    job_title    VARCHAR(160),
    seniority    VARCHAR(60),
    description  TEXT,
    goals_json   TEXT,
    tools_json   TEXT,
    subreddits_json TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at   DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_personas_project_slug ON personas (project_id, slug);

CREATE TABLE pain_points (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    slug         VARCHAR(60) NOT NULL,
    title        VARCHAR(200) NOT NULL,
    description  TEXT,
    severity     INTEGER NOT NULL DEFAULT 3,     -- 1..5
    frequency    INTEGER NOT NULL DEFAULT 3,     -- 1..5
    phrases_json TEXT,                           -- how a person phrases this complaint
    persona_id   INTEGER NULL REFERENCES personas(id) ON DELETE SET NULL,
    created_at   DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_pain_points_project_slug ON pain_points (project_id, slug);

CREATE TABLE intent_signals (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    slug         VARCHAR(60) NOT NULL,
    label        VARCHAR(160) NOT NULL,
    description  TEXT,
    weight       REAL NOT NULL DEFAULT 0.2,      -- feeds ConfidenceScorer
    tier         VARCHAR(20) NOT NULL DEFAULT 'medium',   -- high | medium | low
    created_at   DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_intent_signals_project_slug ON intent_signals (project_id, slug);
```

`slug` is the join key the LLM emits. It is stable, human-readable, and — crucially — lets the
analysis prompt reference `pain-attribution-gap` instead of a database integer the model would have
no reason to get right.

### 5.1a Knowledge-base entities, links, evidence and vectors

These complete the BKB. See [06e §3](06e-business-knowledge-base.md) for the model and
[06e §4](06e-business-knowledge-base.md) for the resolution algorithm.

**Scope rule, to avoid two registries for the same thing.** `personas`, `pain_points`, and
`intent_signals` above already *are* typed entity tables with slugs, and they are joined on by
`lead_analysis`. `bkb_entities` therefore covers **only the entity kinds that have no typed table**:
`competitor`, `product`, `feature`, `tool`, `alternative`. Nothing appears in both.

### 5.1b Where a persona, pain, or signal actually lives

Exactly three of the 23 BKB sections have a typed table behind them:

| Section (06e §2) | Typed table |
|---|---|
| 8 `buyer_personas` | `personas` |
| 9 `pain_points` | `pain_points` |
| 17 `buying_signals` | `intent_signals` |

**`ideal_customer_profiles` is *not* one of them** — there is no `icps` table, so its
`payload_json` is the only copy of an ICP and must be populated like any other section. It is easy
to assume otherwise because ICPs feel structurally similar to personas; they are not, and the
distinction is load-bearing.

Left unstated, an implementer cannot tell whether a pain point's text lives in
`bkb_sections.payload_json` or in `pain_points.description`, and would reasonably write both.

**→ Rule: for an overlapping section, the typed table is authoritative for content; the
`bkb_sections` row carries section-level metadata only.**

| | Authoritative for |
|---|---|
| `bkb_sections` (overlapping keys) | `confidence`, `version`, `in_prefix`, `edited_by_user`, `status`. **`payload_json` is `NULL`.** |
| `personas` · `pain_points` · `intent_signals` | Every field of every row |

The three typed tables therefore **also carry `bkb_id`**, not only `project_id`:

```sql
ALTER TABLE personas       ADD COLUMN bkb_id INTEGER REFERENCES bkb(id) ON DELETE CASCADE;
ALTER TABLE pain_points    ADD COLUMN bkb_id INTEGER REFERENCES bkb(id) ON DELETE CASCADE;
ALTER TABLE intent_signals ADD COLUMN bkb_id INTEGER REFERENCES bkb(id) ON DELETE CASCADE;
-- created inline in 0005; shown as ALTER here only to isolate the change.
```

Three consequences, each of which is the reason for the rule:

1. **One source of truth.** `payload_json IS NULL` on those three keys is asserted by a test, so a
   future contributor cannot quietly start writing a second copy of the personas.
2. **Evidence cascades correctly.** `bkb_evidence.bkb_id` cascades from `bkb`. Without `bkb_id` on
   the typed tables, deleting a superseded BKB version would drop the evidence while leaving the
   pain point behind, **unevidenced but still displayed** — a claim with its provenance silently
   removed, which is worse than either keeping or dropping both.
3. **Independent versioning still holds.** Regenerating `pain_points` supersedes its section row and
   upserts the typed rows by `(bkb_id, slug)`; the competitor registry is untouched.

**Non-overlapping sections keep their payload in `bkb_sections.payload_json` as normal.** The
`NULL`-payload rule applies to exactly `buyer_personas`, `pain_points`, and `buying_signals` — and
nowhere else. A test asserts both directions: those three are `NULL`, and the other twenty are not.

### 5.1c Lifecycle, evidence typing and entity status

Added by the final review ([02c](02c-research-final-review.md)); design in
[06h](06h-knowledge-lifecycle.md). **All of it lands inside `0005` — no new revision.**

```sql
-- bkb_sections: visible age, and who wrote each section (06h §2, §5.2)
ALTER TABLE bkb_sections ADD COLUMN last_verified_at DATETIME;
ALTER TABLE bkb_sections ADD COLUMN staleness_days   INTEGER NULL;  -- NULL = never stales
ALTER TABLE bkb_sections ADD COLUMN origin           VARCHAR(20) NOT NULL DEFAULT 'website';
                                                     -- website | reddit_learned | operator

-- the three typed content tables carry the same origin marker, for the same reason
ALTER TABLE personas       ADD COLUMN origin VARCHAR(20) NOT NULL DEFAULT 'website';
ALTER TABLE pain_points    ADD COLUMN origin VARCHAR(20) NOT NULL DEFAULT 'website';
ALTER TABLE intent_signals ADD COLUMN origin VARCHAR(20) NOT NULL DEFAULT 'website';

-- bkb_evidence: WHERE a claim came from, not just what it quotes (06h §3)
ALTER TABLE bkb_evidence ADD COLUMN source_type  VARCHAR(20) NOT NULL DEFAULT 'website';
                                    -- website | reddit_post | reddit_comment | operator | ai_inference
ALTER TABLE bkb_evidence ADD COLUMN lead_id      INTEGER NULL REFERENCES leads(id) ON DELETE SET NULL;
ALTER TABLE bkb_evidence ADD COLUMN comment_id   INTEGER NULL REFERENCES comments(id) ON DELETE SET NULL;
ALTER TABLE bkb_evidence ADD COLUMN confirmed_by VARCHAR(80) NULL;
ALTER TABLE bkb_evidence ADD COLUMN confirmed_at DATETIME NULL;
CREATE INDEX ix_bkb_evidence_source ON bkb_evidence (source_type);

-- bkb_entities: entities drift; aliases alone don't capture it (06h §7)
ALTER TABLE bkb_entities ADD COLUMN status         VARCHAR(20) NOT NULL DEFAULT 'active';
                                                   -- active | merged_into | retired
ALTER TABLE bkb_entities ADD COLUMN merged_into_id INTEGER NULL REFERENCES bkb_entities(id);

-- bkb_suggestions: aggregate evidence, so the §4.2 threshold is checkable
ALTER TABLE bkb_suggestions ADD COLUMN pattern_kind    VARCHAR(30) NULL;
ALTER TABLE bkb_suggestions ADD COLUMN distinct_groups INTEGER NOT NULL DEFAULT 1;
```

> Shown as `ALTER` for readability only. **`0005` creates these tables with the columns already
> present** — the revision has not shipped, so there is nothing to alter. Writing them as `ALTER`
> in an unshipped revision would be a self-inflicted `batch_alter_table` on SQLite.

**`bkb_evidence.lead_id` / `.comment_id` are what make Reddit-sourced knowledge auditable.** When an
operator accepts a suggestion, the resulting evidence row points at the actual posts that produced
it, so *"why does the BKB think this objection exists?"* resolves to three real threads rather than
to a count.

**Two constraints worth stating**, both enforced in application code rather than as SQL `CHECK`s
because they span rows:

1. A `bkb_evidence` row with `source_type='ai_inference'` has **no** `quote` and no source
   reference — there is nothing to point at, and a quote there would be a fabrication.
2. Every BKB claim has **≥1** evidence row. Zero evidence rows is a validation failure, not a
   quiet default; `ai_inference` is the honest floor.

### 5.1d Freshness defaults

`staleness_days` is seeded per section key at BKB build time from the policy in
[06h §5.1](06h-knowledge-lifecycle.md):

| Group | Sections | `staleness_days` |
|---|---|---:|
| A — Identity | overview, products, features, pricing, industry, target market | 180 |
| B — Buyer model | ICPs, personas, pains, JTBD, value propositions | 90 |
| C — Competitive & linguistic | competitors, alternatives, customer language, Reddit terminology, search intent, buying signals, objections | **NULL** |
| D — Activation | outreach angles, content themes, SEO/GEO entities, negative signals | 180 |

Group C is `NULL` — **never stales** — because it accretes continuously from Reddit and is therefore
getting *fresher*, not older. Showing it an age badge would invite exactly the regeneration the
`origin` guard exists to prevent.

```sql
CREATE TABLE bkb_entities (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind         VARCHAR(30) NOT NULL,   -- competitor|product|feature|tool|alternative
    slug         VARCHAR(80) NOT NULL,
    canonical_name VARCHAR(160) NOT NULL,
    description  TEXT,
    weight       REAL NOT NULL DEFAULT 0.0,   -- contribution to the confidence score
    created_at   DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_bkb_entities ON bkb_entities (project_id, kind, slug);

-- Surface forms. Resolution tiers 1-3 are pure lookups over this table (06e §4).
CREATE TABLE bkb_entity_aliases (
    id           INTEGER PRIMARY KEY,
    entity_id    INTEGER NOT NULL REFERENCES bkb_entities(id) ON DELETE CASCADE,
    alias        VARCHAR(160) NOT NULL,
    alias_norm   VARCHAR(160) NOT NULL,   -- casefolded, punctuation and spacing stripped
    source       VARCHAR(30) NOT NULL,    -- site|casing|misspelling|acronym|domain|confirmed
    created_at   DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_bkb_alias_norm ON bkb_entity_aliases (entity_id, alias_norm);
CREATE INDEX ix_bkb_alias_lookup ON bkb_entity_aliases (alias_norm);

-- Typed edges. Endpoints are (table, row id) pairs so links can span the typed
-- tables and bkb_entities without five nullable FK columns.
CREATE TABLE bkb_links (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    relation     VARCHAR(40) NOT NULL,    -- persona_has_pain|pain_answered_by|competitor_alt_to|...
    src_kind     VARCHAR(30) NOT NULL,    -- persona|pain_point|intent_signal|bkb_entity
    src_id       INTEGER NOT NULL,
    dst_kind     VARCHAR(30) NOT NULL,
    dst_id       INTEGER NOT NULL,
    confidence   REAL NULL,
    created_at   DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_bkb_links ON bkb_links (project_id, relation, src_kind, src_id, dst_kind, dst_id);
CREATE INDEX ix_bkb_links_src ON bkb_links (src_kind, src_id);

-- Provenance for every claim: the verbatim span and the page it came from.
CREATE TABLE bkb_evidence (
    id           INTEGER PRIMARY KEY,
    bkb_id       INTEGER NOT NULL REFERENCES bkb(id) ON DELETE CASCADE,
    subject_kind VARCHAR(30) NOT NULL,   -- bkb_section|persona|pain_point|bkb_entity|...
    subject_id   INTEGER NOT NULL,
    quote        TEXT NOT NULL,          -- must be a literal substring of the snapshot text
    source_url   VARCHAR(500) NULL,
    snapshot_id  INTEGER NULL REFERENCES website_snapshots(id) ON DELETE SET NULL,
    created_at   DATETIME NOT NULL
);
CREATE INDEX ix_bkb_evidence_subject ON bkb_evidence (subject_kind, subject_id);

-- Local static embeddings (Model2Vec) held in sqlite-vec. ~50 rows per project.
-- Created only when the `sqlite-vec` extension loads; see §8.
CREATE VIRTUAL TABLE bkb_embeddings USING vec0(
    rowid          INTEGER PRIMARY KEY,
    embedding      FLOAT[256]
);
CREATE TABLE bkb_embedding_meta (
    rowid        INTEGER PRIMARY KEY,     -- matches bkb_embeddings.rowid
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject_kind VARCHAR(30) NOT NULL,
    subject_id   INTEGER NOT NULL,
    model_name   VARCHAR(80) NOT NULL,    -- invalidation key on model change
    created_at   DATETIME NOT NULL
);
CREATE INDEX ix_bkb_emb_meta ON bkb_embedding_meta (project_id, subject_kind, subject_id);

-- Learned proposals awaiting operator review (06e §7). Never auto-applied.
CREATE TABLE bkb_suggestions (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind         VARCHAR(30) NOT NULL,    -- alias|pain_phrase|entity
    payload_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,          -- lead ids and spans that produced the proposal
    occurrences  INTEGER NOT NULL DEFAULT 1,
    status       VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending|accepted|rejected
    created_at   DATETIME NOT NULL,
    decided_at   DATETIME NULL
);
CREATE INDEX ix_bkb_suggestions_pending ON bkb_suggestions (project_id, status);
```

**`bkb_embeddings` is the only optional object in the schema.** If `sqlite-vec` fails to load, the
migration logs a warning and skips both vector tables; every consumer of the semantic layer degrades
to its lexical path ([06e §5.3](06e-business-knowledge-base.md) — embeddings never *reject* anything,
so their absence costs recall, not correctness). A hard dependency on a loadable extension would
make the whole schema un-migratable on a machine where the extension is unavailable, which is not a
trade worth making for a recall improvement.

### 5.2 Targeting

```sql
CREATE TABLE project_subreddits (
    id               INTEGER PRIMARY KEY,
    project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id           INTEGER NULL REFERENCES runs(id) ON DELETE SET NULL,
    name             VARCHAR(100) NOT NULL,      -- lowercase, no r/
    status           VARCHAR(20) NOT NULL DEFAULT 'proposed',
        -- proposed | approved | rejected | user_added
    source_channels  VARCHAR(80),                -- csv: llm,search,sidebar
    subscribers      INTEGER,
    description      TEXT,
    rank_score       REAL,
    rank_components_json TEXT,                   -- all 5 components, for explainability
    validation_state VARCHAR(30),                -- valid | not_found | too_small | inaccessible
    validation_note  TEXT,
    created_at       DATETIME NOT NULL,
    updated_at       DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_project_subreddits ON project_subreddits (project_id, name);
CREATE INDEX ix_project_subreddits_status ON project_subreddits (project_id, status);

CREATE TABLE project_keywords (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id        INTEGER NULL REFERENCES runs(id) ON DELETE SET NULL,
    subreddit_id  INTEGER NULL REFERENCES project_subreddits(id) ON DELETE CASCADE,
        -- NULL = applies to every approved subreddit
    query         VARCHAR(300) NOT NULL,
    intent_tier   VARCHAR(20) NOT NULL DEFAULT 'medium',   -- high | medium | low | negative
    status        VARCHAR(20) NOT NULL DEFAULT 'proposed', -- proposed|approved|rejected|user_added
    rationale     TEXT,
    est_volume    INTEGER NULL,                  -- results seen on a probe fetch, if any
    created_at    DATETIME NOT NULL,
    updated_at    DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_project_keywords ON project_keywords (project_id, subreddit_id, query);
CREATE INDEX ix_project_keywords_status ON project_keywords (project_id, status);
```

`intent_tier='negative'` rows are exclusion terms — the hiring/promo/giveaway filter from
[02 §9](02-research-findings.md) — stored in the same table so the user can edit them at Gate 2
alongside the positive keywords.

### 5.3 Orchestration

```sql
CREATE TABLE runs (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    state         VARCHAR(40) NOT NULL,
    options_json  TEXT,                     -- RunOptions: limits, time window, comments on/off
    stats_json    TEXT,                     -- rolling counters for the progress endpoint
    llm_cost_usd  REAL NOT NULL DEFAULT 0.0,
    error         TEXT,
    started_at    DATETIME NOT NULL,
    updated_at    DATETIME NOT NULL,
    finished_at   DATETIME NULL
);
CREATE INDEX ix_runs_project_state ON runs (project_id, state);

CREATE TABLE jobs (
    id               INTEGER PRIMARY KEY,
    run_id           INTEGER NULL REFERENCES runs(id) ON DELETE CASCADE,
    job_type         VARCHAR(60) NOT NULL,
    payload_json     TEXT NOT NULL,
    state            VARCHAR(20) NOT NULL DEFAULT 'queued',   -- queued|running|done|failed|cancelled
    priority         INTEGER NOT NULL DEFAULT 100,
    attempts         INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 3,
    available_at     DATETIME NOT NULL,
    worker_id        VARCHAR(80),
    lease_expires_at DATETIME NULL,
    result_json      TEXT,
    error            TEXT,
    created_at       DATETIME NOT NULL,
    started_at       DATETIME NULL,
    finished_at      DATETIME NULL
);
CREATE INDEX ix_jobs_claim  ON jobs (state, available_at, priority, id);
CREATE INDEX ix_jobs_run    ON jobs (run_id, state);
CREATE INDEX ix_jobs_lease  ON jobs (state, lease_expires_at);

CREATE TABLE run_events (
    id         INTEGER PRIMARY KEY,
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    level      VARCHAR(10) NOT NULL DEFAULT 'info',   -- info | warning | error
    event      VARCHAR(80) NOT NULL,
    message    TEXT,
    data_json  TEXT,
    created_at DATETIME NOT NULL
);
CREATE INDEX ix_run_events_run ON run_events (run_id, id);
```

`ix_jobs_claim` is the index the claim query lives or dies on; its column order matches the
`WHERE state=? AND available_at<=? ORDER BY priority, id` shape exactly.

### 5.4 Content

```sql
CREATE TABLE comments (
    id            INTEGER PRIMARY KEY,
    lead_id       INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    project_id    INTEGER NULL,              -- BARE at 0006; FK added in 0007 (§7.1)
    reddit_id     VARCHAR(20) NULL,          -- old.reddit comments expose t1_ ids inconsistently
    author        VARCHAR(100) NOT NULL DEFAULT '[deleted]',
    body          TEXT NOT NULL,
    score         INTEGER NULL,
    depth         INTEGER NOT NULL DEFAULT 0,
    created_utc   DATETIME NULL,
    scraped_at    DATETIME NOT NULL,
    analysis_status VARCHAR(20) NOT NULL DEFAULT 'not_analyzed',
    confidence_score REAL NULL,
    body_hash     VARCHAR(64) NOT NULL       -- sha256(lead_id|author|body) — the real dedup key
);
CREATE UNIQUE INDEX ux_comments_hash ON comments (body_hash);
CREATE INDEX ix_comments_lead    ON comments (lead_id);
CREATE INDEX ix_comments_project ON comments (project_id, confidence_score DESC);
```

**Why `body_hash` and not `reddit_id`:** `_parse_comments` does not currently extract a comment ID,
and old.reddit's comment markup exposes it inconsistently across thread depths. A content hash is
deterministic, requires no parser change, and correctly deduplicates on re-scrape. If a reliable
`t1_` id is later extracted it becomes an additional nullable column, not a replacement key.

### 5.4a AI Service Layer infrastructure

These three tables are **all new**, so `create_all()` handles them and no `ALTER` is required. That
is what allows the AI Service Layer to land in Phase 1 ahead of the schema work.

```sql
-- Every provider call. The source of truth for cost, tokens, cache health, and latency.
CREATE TABLE ai_calls (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NULL REFERENCES runs(id) ON DELETE SET NULL,
    project_id     INTEGER NULL REFERENCES projects(id) ON DELETE SET NULL,
    provider       VARCHAR(40) NOT NULL,          -- "deepseek"
    model          VARCHAR(60) NOT NULL,          -- "deepseek-v4-flash"
    stage          VARCHAR(60) NOT NULL,          -- "post_analysis"
    prompt_version INTEGER NOT NULL,
    prefix_hash    VARCHAR(64),                   -- detects prefix drift within a run
    input_tokens_cached   INTEGER NOT NULL DEFAULT 0,  -- prompt_cache_hit_tokens
    input_tokens_uncached INTEGER NOT NULL DEFAULT 0,  -- prompt_cache_miss_tokens
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd       REAL NOT NULL DEFAULT 0.0,
    surcharge_multiplier REAL NOT NULL DEFAULT 1.0,
    latency_ms     INTEGER,
    attempt        INTEGER NOT NULL DEFAULT 1,
    outcome        VARCHAR(30) NOT NULL,
        -- ok | cached | empty_content | invalid_json | schema_error
        -- | rate_limited | server_error | invalid_key | insufficient_balance
        -- | budget_exceeded | timeout
    error          TEXT,
    created_at     DATETIME NOT NULL
);
CREATE INDEX ix_ai_calls_run     ON ai_calls (run_id, created_at);
CREATE INDEX ix_ai_calls_project ON ai_calls (project_id, created_at);
CREATE INDEX ix_ai_calls_stage   ON ai_calls (stage, outcome);
CREATE INDEX ix_ai_calls_day     ON ai_calls (created_at);   -- daily budget cap

-- Response cache. Permanent: an unchanged prompt about unchanged text has an unchanged answer.
CREATE TABLE ai_cache (
    cache_key      VARCHAR(64) PRIMARY KEY,   -- sha256(provider|model|stage|version|system|user)
    provider       VARCHAR(40) NOT NULL,
    model          VARCHAR(60) NOT NULL,
    stage          VARCHAR(60) NOT NULL,
    prompt_version INTEGER NOT NULL,
    content_hash   VARCHAR(64),               -- sha256(normalised item text) — cross-item dedup
    payload_json   TEXT NOT NULL,
    hits           INTEGER NOT NULL DEFAULT 0,
    created_at     DATETIME NOT NULL,
    last_hit_at    DATETIME NULL
);
CREATE INDEX ix_ai_cache_content ON ai_cache (content_hash, stage, prompt_version);
CREATE INDEX ix_ai_cache_stage   ON ai_cache (stage, prompt_version);

-- Provider health and validation state. NO CREDENTIAL IS STORED HERE.
CREATE TABLE ai_provider_state (
    id                  INTEGER PRIMARY KEY,
    provider            VARCHAR(40) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'unconfigured',
        -- unconfigured | valid | invalid_key | insufficient_balance | unreachable
    key_fingerprint     VARCHAR(20),           -- "sk-…a3f9" — display only
    key_sha256          VARCHAR(64),           -- change detection only, never the key
    model_id            VARCHAR(60),
    last_validated_at   DATETIME NULL,
    last_validation_ms  INTEGER NULL,
    last_error          TEXT,
    updated_at          DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_ai_provider_state ON ai_provider_state (provider);
```

**`ix_ai_cache_content` is the "never analyse identical content twice" index.** Two different Reddit
posts with byte-identical bodies resolve to one cached analysis, linked to both leads, at zero cost.

**The API key is not in any of these tables.** The Fernet ciphertext lives in the pre-existing
`settings` table under the key `ai.provider.deepseek.api_key_enc`, so no schema change is needed to
store it and no migration is needed to add it. `ai_provider_state` holds only the fingerprint,
the SHA-256 digest used for change detection, and health.

### 5.4b Local-first pipeline: dedup, gate, holdout

All deterministic. None of these tables requires an AI call to populate — that is the point.

```sql
-- Near-duplicate grouping. One row per group; representatives get enriched.
CREATE TABLE dedup_groups (
    id             INTEGER PRIMARY KEY,
    -- NULL, not NOT NULL: `projects` does not exist until 0007, so no value
    -- could satisfy it at 0006. FK added in 0007; whether it also becomes
    -- NOT NULL is P12's decision, not P8's (§7.1).
    project_id     INTEGER NULL,
    run_id         INTEGER NULL REFERENCES runs(id) ON DELETE SET NULL,
    representative_lead_id INTEGER NULL REFERENCES leads(id) ON DELETE SET NULL,
    representative_comment_id INTEGER NULL REFERENCES comments(id) ON DELETE SET NULL,
    member_count   INTEGER NOT NULL DEFAULT 1,
    method         VARCHAR(20) NOT NULL,      -- exact | minhash
    similarity     REAL,                      -- Jaccard for minhash groups
    created_at     DATETIME NOT NULL
);
CREATE INDEX ix_dedup_groups_project ON dedup_groups (project_id, run_id);

-- Membership.
-- ⚠️ This previously read "a lead or comment belongs to at most one group per
--    run". The indexes below do NOT enforce that, and cannot: there is no
--    run_id here, the run is reachable only through dedup_groups, and SQLite
--    cannot constrain uniqueness across a join. What they enforce is "at most
--    once WITHIN a group". The per-run invariant is application-level and
--    P10's to uphold and test.
CREATE TABLE dedup_members (
    id          INTEGER PRIMARY KEY,
    group_id    INTEGER NOT NULL REFERENCES dedup_groups(id) ON DELETE CASCADE,
    lead_id     INTEGER NULL REFERENCES leads(id) ON DELETE CASCADE,
    comment_id  INTEGER NULL REFERENCES comments(id) ON DELETE CASCADE,
    is_representative BOOLEAN NOT NULL DEFAULT 0,
    CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))
);
CREATE UNIQUE INDEX ux_dedup_members_lead    ON dedup_members (group_id, lead_id)
    WHERE lead_id IS NOT NULL;
CREATE UNIQUE INDEX ux_dedup_members_comment ON dedup_members (group_id, comment_id)
    WHERE comment_id IS NOT NULL;

-- MinHash signature bands for LSH lookup. Rebuilt per run; purged with the run.
CREATE TABLE minhash_bands (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NULL,               -- see dedup_groups.project_id above (§7.1)
    run_id      INTEGER NULL REFERENCES runs(id) ON DELETE CASCADE,
    band_index  INTEGER NOT NULL,
    band_hash   VARCHAR(32) NOT NULL,
    lead_id     INTEGER NULL REFERENCES leads(id) ON DELETE CASCADE,
    comment_id  INTEGER NULL REFERENCES comments(id) ON DELETE CASCADE
);
CREATE INDEX ix_minhash_lookup ON minhash_bands (project_id, band_index, band_hash);

-- Deterministic pre-score. Written for EVERY collected item, admitted or not.
CREATE TABLE prescores (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    lead_id        INTEGER NULL REFERENCES leads(id) ON DELETE CASCADE,
    comment_id     INTEGER NULL REFERENCES comments(id) ON DELETE CASCADE,
    total          REAL NOT NULL,
    components_json TEXT NOT NULL,
    gate_decision  VARCHAR(20) NOT NULL,      -- admit | reject | cached | grouped
    gate_reason    VARCHAR(30),               -- 11 reasons, see 06c §3.2
    holdout_sampled BOOLEAN NOT NULL DEFAULT 0,
    created_at     DATETIME NOT NULL,
    CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))
);
CREATE INDEX ix_prescores_run    ON prescores (run_id, gate_decision);
CREATE INDEX ix_prescores_reason ON prescores (run_id, gate_reason);
CREATE INDEX ix_prescores_total  ON prescores (run_id, total DESC);

-- Holdout audit results. The evidence that aggressive filtering is not losing leads.
CREATE TABLE gate_audits (
    id                   INTEGER PRIMARY KEY,
    run_id               INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    sampled              INTEGER NOT NULL DEFAULT 0,
    would_have_qualified INTEGER NOT NULL DEFAULT 0,
    gate_miss_rate       REAL,
    worst_reason         VARCHAR(30),
    worst_reason_misses  INTEGER NOT NULL DEFAULT 0,
    created_at           DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_gate_audits_run ON gate_audits (run_id);
```

**`prescores` stores a row for every collected item, including rejected ones.** That is deliberate
and is what makes the funnel auditable: without it, the run page could report *that* 1,021 items
were filtered but never *which*, and the gate would be untunable. `ix_prescores_total` is what the
candidate-selection query orders by.

**`minhash_bands` is run-scoped and purged with the run** — it is a lookup index, not a durable
record. The durable output is `dedup_groups` + `dedup_members`.

### 5.5 Lead enrichment

One row per enriched item per prompt version. Columns map 1:1 onto the `LeadAnalysis` schema in
[06 §4](06-ai-pipeline.md).

```sql
CREATE TABLE lead_analysis (
    id                 INTEGER PRIMARY KEY,
    lead_id            INTEGER NULL REFERENCES leads(id) ON DELETE CASCADE,
    comment_id         INTEGER NULL REFERENCES comments(id) ON DELETE CASCADE,
    project_id         INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id             INTEGER NULL REFERENCES runs(id) ON DELETE SET NULL,

    -- ── core judgement ────────────────────────────────────────────────
    is_lead              BOOLEAN NOT NULL DEFAULT 0,
    summary              TEXT,
    buying_intent        VARCHAR(30),    -- unaware|problem_aware|solution_aware|evaluating|ready_to_buy
    urgency              VARCHAR(20),    -- none|low|medium|high|critical
    icp_match            VARCHAR(20),    -- none|weak|partial|strong
    sentiment            VARCHAR(20),    -- negative|frustrated|neutral|positive
    opportunity_score    INTEGER,        -- 0..10, the model's coarse read — ONE input to the scorer
    recommended_priority VARCHAR(20),    -- low|medium|high|urgent

    -- ── matched entities (slugs, reconciled against the project) ──────
    pain_point_slug      VARCHAR(60),    -- the primary one
    matched_pain_slugs   TEXT,           -- csv
    problem_category     VARCHAR(120),
    matched_signal_slugs TEXT,           -- csv
    persona_slug         VARCHAR(60),
    competitor_mentions  TEXT,           -- csv

    -- ── narrative ─────────────────────────────────────────────────────
    evidence_quote           TEXT,
    evidence_verified        BOOLEAN NOT NULL DEFAULT 0,   -- verbatim substring check passed
    reasoning                TEXT,
    suggested_outreach_angle TEXT,
    disqualifiers            TEXT,

    -- ── provenance ────────────────────────────────────────────────────
    -- These five pin WHAT the system looked like when the decision was made,
    -- so any historical score stays reconstructible (06i §5).
    raw_json           TEXT NOT NULL,
    provider           VARCHAR(40) NOT NULL,
    model              VARCHAR(60) NOT NULL,
    prompt_version     INTEGER NOT NULL,
    bkb_id             INTEGER NULL REFERENCES bkb(id) ON DELETE SET NULL,  -- which knowledge base
    weights_version    INTEGER NOT NULL DEFAULT 1,   -- which confidence weights
    ruleset_version    INTEGER NOT NULL DEFAULT 1,   -- which rules + negative vocabulary
    tier               INTEGER NOT NULL DEFAULT 1,   -- 1 = batched · 2 = deep, un-batched
    content_hash       VARCHAR(64),      -- links identical content to one analysis
    from_cache         BOOLEAN NOT NULL DEFAULT 0,
    repair_attempts    INTEGER NOT NULL DEFAULT 0,
    created_at         DATETIME NOT NULL,

    CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))   -- exactly one target
);
CREATE UNIQUE INDEX ux_lead_analysis_lead    ON lead_analysis (lead_id, prompt_version, tier)
    WHERE lead_id IS NOT NULL;
CREATE UNIQUE INDEX ux_lead_analysis_comment ON lead_analysis (comment_id, prompt_version, tier)
    WHERE comment_id IS NOT NULL;
CREATE INDEX ix_lead_analysis_project ON lead_analysis (project_id, is_lead);
CREATE INDEX ix_lead_analysis_intent  ON lead_analysis (project_id, buying_intent);
CREATE INDEX ix_lead_analysis_content ON lead_analysis (content_hash, prompt_version);
```

Create the partial indexes with Alembic's `sqlite_where` kwarg, not raw SQL:

```python
op.create_index("ux_lead_analysis_lead", "lead_analysis",
                ["lead_id", "prompt_version", "tier"],
                unique=True, sqlite_where=sa.text("lead_id IS NOT NULL"))
```

**`tier` is part of the unique key, and that is deliberate.** Tier 2 writes a **second row**, not an
update ([06i §3](06i-feedback-and-memory.md)). Without `tier` in the key the index would reject it;
with an update instead, a Tier 2 failure would have already destroyed the Tier 1 analysis it was
supposed to leave intact. Two rows means the deep analysis is strictly additive — the lead detail
reads Tier 2 when present and falls back to Tier 1 otherwise, and a Tier 2 rollback is a `DELETE`.

**Idempotency.** Re-running enrichment at the same `prompt_version` **and tier** collides on the
partial unique index and is skipped. Bumping the version produces a new row and **preserves the old judgement for
comparison** — which is what makes prompt iteration measurable rather than destructive.

**`repair_attempts` is a quality metric, not bookkeeping.** A rising average means the prompt's
`# JSON Shape` section is unclear and should be revised; it is reported per prompt version.

**There is no `llm_batches` table.** DeepSeek has no batch endpoint; bulk enrichment is a bounded
concurrency pool inside one job ([04 §6.5](04-system-design.md)). Cost and token accounting live in
`ai_calls` ([§5.4a](#54a-ai-service-layer-infrastructure)).

### 5.6 Infrastructure

```sql
CREATE TABLE proxies (
    id            INTEGER PRIMARY KEY,
    host          VARCHAR(60) NOT NULL,
    port          INTEGER NOT NULL,
    label         VARCHAR(80),                -- "host:port" — the display/log form
    state         VARCHAR(20) NOT NULL DEFAULT 'unknown',  -- healthy|degraded|blacklisted|unknown
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    total_requests   INTEGER NOT NULL DEFAULT 0,
    total_failures   INTEGER NOT NULL DEFAULT 0,
    avg_latency_ms   REAL,
    last_used_at     DATETIME NULL,
    last_ok_at       DATETIME NULL,
    last_error       TEXT,
    blacklisted_until DATETIME NULL,
    created_at    DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_proxies_host_port ON proxies (host, port);
```

**No credentials are stored.** `proxies` holds identity and health only; username/password live in
the file referenced by `PROXY_FILE` and never enter the database, the logs, or the UI.

```sql
CREATE TABLE http_cache (
    cache_key    VARCHAR(64) PRIMARY KEY,     -- sha256(url)
    url          TEXT NOT NULL,
    status_code  INTEGER NOT NULL,
    body         BLOB NOT NULL,
    fetched_at   DATETIME NOT NULL,
    expires_at   DATETIME NOT NULL
);
CREATE INDEX ix_http_cache_expires ON http_cache (expires_at);

CREATE TABLE metrics (
    id         INTEGER PRIMARY KEY,
    name       VARCHAR(80) NOT NULL,
    labels_json TEXT,
    value      REAL NOT NULL,
    recorded_at DATETIME NOT NULL
);
CREATE INDEX ix_metrics_name_time ON metrics (name, recorded_at);
```

---

### 5.4c Adaptive budget and quality measurement

Two small groups that make [06f](06f-adaptive-budget.md) and
[06g Part II](06g-explainability-and-quality.md) implementable. **Neither adds a migration** — the
budget rows land in `0008` beside `gate_audits`, the quality rows in `0009`.

```sql
-- 0008 — one row per run: how the admission count was decided (06f §2.5).
CREATE TABLE ai_budgets (
    id                INTEGER PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    mode              VARCHAR(20) NOT NULL,      -- thorough|balanced|frugal
    strategy          VARCHAR(20) NOT NULL,      -- adaptive|fixed
    collected         INTEGER NOT NULL,
    candidates        INTEGER NOT NULL,          -- n: the base for every fraction
    admitted          INTEGER NOT NULL,
    method            VARCHAR(60) NOT NULL,      -- e.g. "knee+floor+clamped_min"
    knee_rank         INTEGER NULL,              -- NULL when no knee was found
    knee_prescore     REAL NULL,
    floor_allows      INTEGER NULL,
    marginal_allows   INTEGER NULL,
    clamp_lo          INTEGER NOT NULL,
    clamp_hi          INTEGER NOT NULL,
    fixed_would_admit INTEGER NULL,              -- the counterfactual shown in the UI
    created_at        DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_ai_budgets_run ON ai_budgets (run_id);
```

```sql
-- 0009 — operator outcome labels. The input to precision, FP/FN, ECE and the yield curve.
CREATE TABLE lead_labels (
    id           INTEGER PRIMARY KEY,
    lead_id      INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    label        VARCHAR(20) NOT NULL,      -- interested|contacted|converted|not_relevant|duplicate_of
    reason       VARCHAR(30) NULL,          -- when not_relevant: wrong_persona|wrong_pain|wrong_icp|
                                            -- not_a_buyer|competitor_staff|too_old|already_engaged|other
    note         TEXT NULL,
    labelled_at  DATETIME NOT NULL
);
CREATE INDEX ix_lead_labels_reason ON lead_labels (reason) WHERE reason IS NOT NULL;
CREATE UNIQUE INDEX ux_lead_labels_lead ON lead_labels (lead_id);
CREATE INDEX ix_lead_labels_label ON lead_labels (label, labelled_at);

-- 0009 — the 100-item golden set and its per-version results (06g §4.4).
CREATE TABLE golden_items (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER NULL REFERENCES projects(id) ON DELETE SET NULL,
    content_hash  VARCHAR(64) NOT NULL,
    source_text   TEXT NOT NULL,
    expected_json TEXT NOT NULL,           -- hand-labelled ground truth
    created_at    DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_golden_items_hash ON golden_items (content_hash);

CREATE TABLE golden_runs (
    id             INTEGER PRIMARY KEY,
    prompt_version INTEGER NOT NULL,
    model          VARCHAR(60) NOT NULL,
    batch_size     INTEGER NOT NULL,
    f1             REAL NOT NULL,
    precision_     REAL NOT NULL,
    recall         REAL NOT NULL,
    passed         BOOLEAN NOT NULL,        -- F1 within 0.02 of the reference; blocks release
    detail_json    TEXT NOT NULL,
    created_at     DATETIME NOT NULL
);
CREATE INDEX ix_golden_runs_version ON golden_runs (prompt_version, created_at);

-- 0009 — nightly/weekly rollups so the quality page is a lookup, not a scan.
CREATE TABLE quality_snapshots (
    id             INTEGER PRIMARY KEY,
    project_id     INTEGER NULL REFERENCES projects(id) ON DELETE CASCADE,
    window_days    INTEGER NOT NULL,
    label_count    INTEGER NOT NULL,       -- metrics report insufficient_data below thresholds
    precision_at70 REAL NULL,
    fp_rate        REAL NULL,
    gate_miss_rate REAL NULL,
    ece            REAL NULL,
    brier          REAL NULL,
    psi            REAL NULL,
    cache_hit_ratio REAL NULL,
    hallucinated_span_rate REAL NULL,
    computed_at    DATETIME NOT NULL
);
CREATE INDEX ix_quality_snapshots ON quality_snapshots (project_id, computed_at);

-- 0009 — the fitted score -> probability mapping (isotonic), when ECE demands one.
CREATE TABLE calibration_maps (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NULL REFERENCES projects(id) ON DELETE CASCADE,
    knots_json   TEXT NOT NULL,            -- monotonic (raw_score -> observed_rate) pairs
    label_count  INTEGER NOT NULL,
    ece_before   REAL NOT NULL,
    ece_after    REAL NOT NULL,
    active       BOOLEAN NOT NULL DEFAULT 0,
    created_at   DATETIME NOT NULL
);
CREATE INDEX ix_calibration_active ON calibration_maps (project_id, active);
```

### 5.4d Pattern discovery

The nightly aggregation output ([06h §6](06h-knowledge-lifecycle.md)). **Ships in `0009`; no new
revision.**

```sql
CREATE TABLE patterns (
    id              INTEGER PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    pattern_kind    VARCHAR(30) NOT NULL,   -- pain|objection|competitor|language|signal|persona
    pattern_key     VARCHAR(160) NOT NULL,  -- the slug or normalised phrase
    occurrences     INTEGER NOT NULL,       -- raw count
    distinct_groups INTEGER NOT NULL,       -- dedup groups — THIS is what the threshold tests
    avg_confidence  REAL NULL,
    first_seen_at   DATETIME NOT NULL,
    last_seen_at    DATETIME NOT NULL,
    in_bkb          BOOLEAN NOT NULL DEFAULT 0,   -- already known? then it is a trend, not a discovery
    computed_at     DATETIME NOT NULL
);
CREATE UNIQUE INDEX ux_patterns ON patterns (project_id, pattern_kind, pattern_key);
CREATE INDEX ix_patterns_new ON patterns (project_id, in_bkb, distinct_groups);
```

**`distinct_groups`, not `occurrences`, is the threshold column.** It counts dedup groups, so one
viral thread and its forty reposts contribute **1**, not 40. Thresholding on raw occurrences would
let the loudest thread rewrite the knowledge base — the failure mode
[06h §4.2](06h-knowledge-lifecycle.md) exists to prevent.

**`in_bkb` separates discovery from trend.** A pattern already in the knowledge base is useful
history (*"this objection has appeared 14 times since April"*); one that is not is a candidate for
`bkb_suggestions`. The same table serves both, and only the second raises a proposal.

The table is a **rebuildable projection** — dropping and recomputing it from `lead_analysis` loses
nothing. It sits in the operational class ([06i §4](06i-feedback-and-memory.md)) for that reason,
even though it feeds durable knowledge.

---

**`calibration_maps` is applied at display time, never at storage time.** The stored
`leads.confidence_score` stays raw so that recalibrating never rewrites history and the reliability
diagram can always be recomputed from the original numbers. This also keeps the guarantee in
[06g §7](06g-explainability-and-quality.md) — recalibration changes what a number *means*, never the
order of the list.

---

## 6. Full ERD

```
projects ─┬─< website_snapshots
          ├─< dedup_groups ──< dedup_members
          ├─< minhash_bands
          ├─< bkb ─┬─< bkb_sections        (23 per bkb, independently versioned)
          │        └─< bkb_evidence        (verbatim spans, -> website_snapshots)
          ├─< bkb_entities ──< bkb_entity_aliases
          ├─< bkb_links                    (typed edges, polymorphic endpoints)
          ├─< bkb_suggestions              (pending, operator-reviewed)
          ├─< bkb_embedding_meta ─· bkb_embeddings (vec0, conditional)
          ├─< personas ──< pain_points (persona_id)
          ├─< pain_points
          ├─< intent_signals
          ├─< calibration_maps
          ├─< quality_snapshots
          ├─< project_subreddits ──< project_keywords (subreddit_id)
          ├─< project_keywords
          ├─< runs ─┬─< jobs
          │         ├─< prescores        (one per collected item, admitted or not)
          │         ├─< ai_budgets       (one per run — how admission was decided)
          │         ├─< gate_audits      (one per run — the holdout result)
          │         ├─< run_events
          │         ├─< ai_calls (run-scoped)
          │         └─< scrape_runs (run_id, nullable — legacy rows have NULL)
          ├─< leads (project_id NULLABLE — legacy rows have NULL)
          │     ├─< comments
          │     ├─< lead_analysis
          │     └─· lead_labels (0..1 — the operator's outcome judgement)
          ├─< comments
          ├─< lead_analysis
          └─< ai_calls

standalone: settings (holds the encrypted API key) · ai_cache · ai_provider_state ·
            golden_items · golden_runs ·
            subreddits · dashboard_subreddits · dashboard_keywords ·
            dashboard_search_queries · tracked_users · proxies · http_cache · metrics
```

---

## 7. Migration sequence

> ⚠️ **Corrected 2026-08-11 (P8).** This section previously opened *"This table is authoritative"*
> and listed a chain that **[31](31-execution-plan.md)'s reorder had already superseded** — it put
> `projects` at `0005` and `content_and_dedup` at `0007`, when the shipped chain has `discovery` at
> `0005` and `content_and_dedup` at `0006`. The stale claim of authority was the dangerous part: it
> would have had P8 author the wrong revision number and write four `REFERENCES projects(id)`
> clauses at a revision where `projects` does not exist — a defect that breaks **every** `INSERT`
> into `leads` while every gate in the project reports green.
>
> **[ARCHITECTURE_FREEZE §4.1](ARCHITECTURE_FREEZE.md) is the authority for the chain.** This
> section is the design detail behind it and is reconciled to it below. Recorded as a
> [§11.1](ARCHITECTURE_FREEZE.md) reconciliation, 2026-08-11: no technology, table or decision
> changes — a revision-numbering table that predated a reorder was brought into line with it.

Alembic revisions form a single linear chain; no phase may insert a revision out of sequence or
suffix one (`0005a`) — that produces two heads and breaks `upgrade head`.

| Rev | Title | Phase | Contents |
|---|---|---|---|
| `0001` | `baseline` | 1 | The 8 existing tables exactly as `create_all()` produces them. **Stamped, not applied,** on the live DB. |
| `0002` | `ai_infrastructure` | 1 | `ai_calls`, `ai_cache`, `ai_provider_state` |
| `0003` | `net_infrastructure` | 2 | `proxies`, `http_cache`, `metrics` |
| `0004` | `orchestration` | **P1 ✅ shipped 2026-08-05** | `runs`, `jobs`, `run_events`; `scrape_runs.run_id` (+FK); closes the deferred `ai_calls.run_id` FK |
| `0005` | `discovery` | **P6 ✅ shipped 2026-08-08** | `discovery_watermarks`, `prescores` (incl. `stage`; `comment_id` FK **deferred to `0006`**) |
| `0006` | `content_and_dedup` | **P8 ✅ shipped 2026-08-11** | `comments`, `dedup_groups`, `dedup_members`, `minhash_bands`; the **4** `leads` columns (`project_id`, `confidence_score`, `analysis_status`, **`source`**) + 4 indexes; **closes** the `prescores.comment_id` FK |
| `0007` | `projects_and_knowledge_base` | **P12 ✅ shipped 2026-08-15** | `projects`, `website_snapshots`, **`bkb`, `bkb_sections`**, `personas`, `pain_points`, `intent_signals`, **`bkb_entities`, `bkb_entity_aliases`, `bkb_links`, `bkb_evidence`, `bkb_suggestions`, `bkb_embeddings`+`bkb_embedding_meta` (conditional)**; closes **six** deferred `project_id` FKs (§7.1). `runs.project_id` stays **nullable** |
| `0008` | `targeting` | P17 | `project_subreddits`, `project_keywords` |
| `0009` | `enrichment` | P19 | `lead_analysis` (incl. **`bkb_id`, `weights_version`, `ruleset_version`, `tier`**), `gate_audits`, **`ai_budgets`** |
| `0010` | `monitoring_and_quality` | P25 | `projects.monitoring_enabled`, `monitoring_interval_hours`, `last_monitored_at`; **`lead_labels`** (incl. `reason`), **`golden_items`, `golden_runs`, `quality_snapshots`, `calibration_maps`, `patterns`** |

**The 2026-07-30 architecture review did not force a new revision.**
([02c](02c-research-final-review.md)) added lifecycle, evidence-typing, provenance-pinning, feedback
and pattern columns — **every one of them into a revision that already existed**. None of those
revisions had shipped, so the columns are written into their `CREATE TABLE` statements rather than
appended as `ALTER`s. A review that forced an extra migration would have been a signal the original
decomposition was wrong; it was not.

> **Both "No tenth revision" paragraphs are struck, 2026-08-11 (P8).** They were correct for the
> nine-revision chain they were written against. [31](31-execution-plan.md)'s reorder made the chain
> **ten**, and [freeze §4.1](ARCHITECTURE_FREEZE.md) records `0010 monitoring_and_quality` (P25) as
> its last entry: *"Ten revisions. No eleventh without an amendment under §11."* The Business
> Knowledge Base still replaces `ai_artifacts` rather than arriving later — that reasoning survives
> intact — but it now does so inside **`0007`**, not `0005`.

The chain is **linear with a single head**:
`0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 → 0008 → 0009 → 0010`.

Each revision has a working `downgrade()`. **`0006` is the only one that touches `leads`**; its
downgrade drops the **four** added columns and their four indexes, restoring the original table.
Verified on a copy of the live database — see §7.1b.

**Three placement decisions worth stating explicitly**, because a naive reading of §4–§5 would put
them elsewhere:

- **AI infrastructure is `0002`, in Phase 1.** `ai_calls`, `ai_cache`, and `ai_provider_state` are
  all *new* tables, so nothing here requires an `ALTER`, and the API key itself lives in the
  pre-existing `settings` table. This is precisely what allows the AI Service Layer to land first.
- **The four `leads` columns land in `0006` (P8), not earlier.** Nothing writes them until the
  phases that populate them, and touching the live `leads` table once is better than twice.
  *(Corrected 2026-08-11: previously "three columns … `0007` (Phase 6)". The count is four —
  `source` was added by [02c](02c-research-final-review.md) — and the revision is `0006`.)*
- **There is no `llm_batches` revision.** DeepSeek has no batch endpoint; bulk enrichment is a
  bounded concurrency pool with no persisted batch state to track.

### 7.1 Deferred foreign keys

**Eight** columns reference a table that does not yet exist when their own table is created. Because
the AI layer lands first and `projects` does not arrive until `0007` (P12), this is unavoidable.

> ⚠️ **It is not "cheap because SQLite ignores `REFERENCES` unless `PRAGMA foreign_keys` is on."**
> That sentence was here until 2026-08-11 and **it is wrong in the way that matters.** A
> `REFERENCES` clause naming a table that does not exist makes **every `INSERT` into the child table
> fail** — with `no such table: main.projects`, *regardless of the pragma*, and even when the column
> is set to `NULL` — because SQLite resolves the parent table when it **prepares** the statement,
> not when it checks the constraint. Measured on SQLite 3.45.3, twice, in two sessions.
>
> Worse, it is silent: the migration applies, `SELECT` works, `PRAGMA foreign_key_check` returns
> `[]`, the up/down/up round-trip passes and `check_schema.py` reports OK. Deferral is therefore
> **mandatory, not an optimisation**. `tests/test_migrations.py::test_no_revision_leaves_a_dangling_foreign_key`
> now enforces it across every revision.

| Column | Created in | References | FK added in |
|---|---|---|---|
| `ai_calls.run_id` | `0002` | `runs` (`0004`) | `0004` |
| `ai_calls.project_id` | `0002` | `projects` (`0007`) | `0007` |
| `runs.project_id` | `0004` | `projects` (`0007`) | `0007` |
| `prescores.comment_id` | `0005` | `comments` (`0006`) | **`0006` ✅ closed** |
| **`leads.project_id`** | **`0006`** | `projects` (`0007`) | **`0007`** |
| **`comments.project_id`** | **`0006`** | `projects` (`0007`) | **`0007`** |
| **`dedup_groups.project_id`** | **`0006`** | `projects` (`0007`) | **`0007`** |
| **`minhash_bands.project_id`** | **`0006`** | `projects` (`0007`) | **`0007`** |

> **P12 inherits six `batch_alter_table` rebuilds**, one of them over `leads`. Take an M7 backup
> first. A rebuild is a genuine copy-and-move **when it changes constraints**, which is exactly what
> `0007` does — note that `batch_alter_table` does *not* rebuild when its only operation is
> `add_column`; alembic emits a plain `ALTER` there (measured: `rootpage` unchanged).
>
> ✅ **Answered in P12, 2026-08-15 — all six close, and none of the three columns is tightened.**
> This table's count of six is the one that shipped; [34 §P12](34-implementation-plan.md)'s four and
> §7.1a's three are reconciled to it at [freeze §11.1](ARCHITECTURE_FREEZE.md). The `leads` rebuild
> was measured on a copy of the live database **before** the revision was written: 492 rows, the
> `intent_score` fingerprint `9327a13dd9ef4185`, all nine indexes including the `reddit_id` UNIQUE,
> the child FKs on `comments` and `dedup_members`, `foreign_key_check` empty, `integrity_check = ok`.
>
> **The three nullability questions are all answered "leave it", each against a document.**
> `dedup_groups.project_id` and `minhash_bands.project_id` — the choice this note handed to P12 —
> **stay nullable**, because P10's cascade and P11's stage write `None` into both on every run and
> there is no project to attribute a run to until P16; tightening them would satisfy §5.4b by
> breaking shipped code. `runs.project_id` **also stays nullable**, which is the substantive one:
> all 11 live runs have it `NULL`, so the rebuild's `INSERT … SELECT` fails, the backfill that would
> fix it is the row rewrite **M5** forbids, and **AD-5** freezes project scoping as *additive and
> nullable*. Pinned by `tests/test_schema_0007.py`, in both directions.
>
> **The ON DELETE actions are deliberately not uniform.** `ai_calls` → `SET NULL` and `runs` →
> `CASCADE` are given literally in the code block below. `leads` and `comments` → **`SET NULL`**,
> because [freeze §8](ARCHITECTURE_FREEZE.md) makes expiring leads a permanent non-goal — *a lead is
> a historical fact* — so deleting a project must not delete the corpus collected for it.
> `dedup_groups` and `minhash_bands` → **`CASCADE`**, as derived per-run artefacts that are rebuilt
> from scratch and already cascade from `runs`. If they ever become uniform, one of them is wrong.

**Each of these columns is created with a bare type and no `REFERENCES` clause.** The constraint is
added later:

```python
# 0004_orchestration
with op.batch_alter_table("ai_calls") as b:
    b.create_foreign_key("fk_ai_calls_run", "runs", ["run_id"], ["id"], ondelete="SET NULL")

# 0005_projects_and_intelligence
with op.batch_alter_table("ai_calls") as b:
    b.create_foreign_key("fk_ai_calls_project", "projects", ["project_id"], ["id"],
                         ondelete="SET NULL")
with op.batch_alter_table("runs") as b:
    b.create_foreign_key("fk_runs_project", "projects", ["project_id"], ["id"],
                         ondelete="CASCADE")
```

### 7.1a Intra-revision table ordering

Alembic executes `upgrade()` top to bottom, so **table creation order within a single revision is a
real constraint, not a formality.** `0006_content_and_dedup` creates four tables with dependencies
between them; the DDL in §5.4b lists them by topic, **not** by creation order. The required order is:

```
0006_content_and_dedup:
  1. ALTER leads (4 columns + 4 indexes)   ← project_id BARE (§7.1)
  2. CREATE comments                 ← referenced by 3, 4, 5, 6
  3. CREATE dedup_groups             ← references leads, comments
  4. CREATE dedup_members            ← references dedup_groups, leads, comments
  5. CREATE minhash_bands            ← references leads, comments
  6. batch_alter_table('prescores'): close comment_id -> comments
```

`downgrade()` drops them in exactly the reverse order, and **the `prescores` constraint is dropped
first** — it references `comments`, which cannot be dropped while a constraint points at it. Writing
the DDL in the order it appears in §5.4b would fail on `dedup_groups` because `comments` would not
yet exist.

> ⚠️ **Corrected 2026-08-11 (P8), in three ways.** The block was titled `0007` (it is `0006`); said
> *"3 columns"* (it is four — `source`); and its step 6 was **`CREATE prescores`**, which would fail
> with *"table prescores already exists"* because [33 §2.4](33-final-review.md) moved `prescores`
> into `0005`, where `migrations/versions/0005_discovery.py` creates it. Worse, the block **omitted
> the one thing `0006` actually owes `prescores`** — closing the `comment_id` FK that `0005`
> deliberately left bare, which is [34 §P8](34-implementation-plan.md) task 4 and appeared nowhere
> in this document. Step 6 now names it.

### 7.1b The `0006` rollback, executed

Not described — **run**, on a copy of the live database, 2026-08-11. Actual terminal output:

```
P8 ROLLBACK DRILL — executed on a copy of data/leads.db
==============================================================
start      rev=0005_discovery           leads=478  fp=52b2ebb2aeaf9165
upgrade    rev=0006_content_and_dedup   leads=478  fp=52b2ebb2aeaf9165
           check_schema --revision 0006 : exit=0  OK — all 52 checks passed.
DOWNGRADE  rev=0005_discovery           leads=478  fp=52b2ebb2aeaf9165
           check_schema --skip-p8       : exit=0  OK — all 31 checks passed.
           P8 tables remaining          : NONE
           P8 leads columns remaining   : NONE
re-upgrade rev=0006_content_and_dedup   leads=478  fp=52b2ebb2aeaf9165
           check_schema --revision 0006 : exit=0  OK — all 52 checks passed.
==============================================================
baseline fingerprint expected: 52b2ebb2aeaf9165
```

`fp` is the first 16 hex of the `intent_score` fingerprint over the 459 baseline rows — the same
digest `tests/baseline/db_fingerprint.json` pins. **The lead count and the fingerprint are identical
at every stage, and the fingerprint matches the recorded baseline**, so the round-trip neither lost a
row nor altered a score.
`tests/test_migrations.py::test_a1_up_down_up_on_a_copy_of_the_live_database` asserts the same
round-trip on every run, and additionally asserts that the four tables and four columns are **gone**
at `0005` — a downgrade that silently left them behind would otherwise pass a row-count check.

**`0005_projects_and_knowledge_base` now has the same hazard**, and a longer chain — §5.1 and §5.1a
list its tables by topic. The required order is:

> ⚠️ **Corrected 2026-08-15 (P12), in three ways.** The block was titled `0005` (it is **`0007`** —
> [31](31-execution-plan.md)'s reorder, the same staleness §7's opening note corrects); step 3 asked
> to *"tighten `project_id` NOT NULL"*, which is **not buildable** and is reconciled away at
> [freeze §11.1](ARCHITECTURE_FREEZE.md); and steps 2–3 closed **two** foreign keys where §7.1's
> table names **six**, omitting the four `project_id` columns `0006` creates. The shipped order is
> below. Its cross-references were also off by one throughout, because the list had fewer steps than
> the tables it ordered.

```
0007_projects_and_knowledge_base:
  1.  CREATE projects                ← referenced by everything below
  2.  ALTER  ai_calls       ADD FK -> projects  ON DELETE SET NULL   (batch_alter_table)
  3.  ALTER  runs           ADD FK -> projects  ON DELETE CASCADE    — project_id stays NULLABLE
  4.  ALTER  leads          ADD FK -> projects  ON DELETE SET NULL   ← the legacy table; M7 backup
  5.  ALTER  comments       ADD FK -> projects  ON DELETE SET NULL
  6.  ALTER  dedup_groups   ADD FK -> projects  ON DELETE CASCADE    — stays NULLABLE
  7.  ALTER  minhash_bands  ADD FK -> projects  ON DELETE CASCADE    — stays NULLABLE
  8.  CREATE website_snapshots       ← referenced by 17
  9.  CREATE bkb                     ← referenced by 10, 11, 12, 13, 17
  10. CREATE bkb_sections            ← + ck_bkb_sections_payload_null_rule
  11. CREATE personas                ← referenced by 12
  12. CREATE pain_points             ← references personas
  13. CREATE intent_signals
  14. CREATE bkb_entities            ← referenced by 15; self-reference on merged_into_id
  15. CREATE bkb_entity_aliases
  16. CREATE bkb_links               ← polymorphic endpoints; no FK ordering requirement
  17. CREATE bkb_evidence            ← references bkb, website_snapshots, leads, comments
  18. CREATE bkb_suggestions
  19. TRY    CREATE bkb_embeddings (vec0) + bkb_embedding_meta   ← conditional, see below
```

`downgrade()` reverses it exactly, and **the six batch constraints are dropped before `projects`** —
for the reason `0006`'s downgrade drops the `prescores` constraint first: a table cannot be dropped
while a foreign key points at it, and a reference left behind is invisible to `foreign_key_check`
while breaking every `INSERT` into the child. Step 19's pair is dropped **first and conditionally**
(`DROP TABLE IF EXISTS`), because on a host without the extension it was never created and a
downgrade that raised there would make the rollback unavailable exactly where the upgrade had
already degraded.

Step 15 is wrapped:

```python
try:
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    op.execute("CREATE VIRTUAL TABLE bkb_embeddings USING vec0(...)")
    op.create_table("bkb_embedding_meta", ...)
except Exception as exc:                       # extension unavailable on this host
    log.warning("sqlite-vec unavailable (%s); semantic layer disabled", exc)
```

**The migration must not fail when the extension is missing.** A machine without `sqlite-vec` still
gets a fully working platform with the lexical paths only; a migration that aborted there would make
the entire schema un-installable in exchange for a recall improvement. A startup check reports
`semantic_layer: disabled` on `/health` so the degradation is visible rather than silent.

SQLite cannot `ADD CONSTRAINT`; Alembic's `batch_alter_table` performs the
create-copy-drop-rename rebuild. **`runs.project_id` is nullable and stays nullable** — a run created
before a project exists has no project to belong to, which is the reason this paragraph gave for
deferring the constraint and is equally the reason not to tighten the column. *(Corrected
2026-08-15: this sentence previously said "and is tightened to `NOT NULL` in the same rebuild",
contradicting its own first clause and **AD-5**. Measured: 11 of 11 live runs have it `NULL`, so the
rebuild fails; the backfill that would fix it is the row rewrite **M5** forbids.
[freeze §11.1](ARCHITECTURE_FREEZE.md).)*

The alternative — reordering revisions so `projects` precedes everything — would push the AI layer
behind the schema work and defeat the phase ordering. A test asserts that after `alembic upgrade
head`, `PRAGMA foreign_key_list` reports all **six** constraints.

### 7.1 Baseline stamping procedure

```bash
# Existing database — tables already exist, so record it as already at 0001:
python main.py migrate stamp 0001
python main.py migrate upgrade head

# Fresh database — nothing exists:
python main.py migrate upgrade head
```

`main.py migrate` wraps Alembic so the operator never needs to know Alembic exists. It:
1. Detects whether `alembic_version` exists.
2. If not, and `leads` exists → stamp `0001` automatically, then upgrade.
3. If not, and `leads` does not exist → upgrade from empty.
4. **Before any upgrade that would change the schema, copy `data/leads.db` to
   `data/backups/leads-<utc>.db`** and print the path.

Step 4 is the safety net that makes every subsequent migration recoverable with a file copy.

---

## 8. Session and engine configuration

```python
# src/db/database.py
from sqlalchemy import event

def init_db(db_path=None, *, run_migrations: bool = False):
    global ENGINE, SessionFactory
    db_file = Path(db_path) if db_path else DB_PATH
    db_file.parent.mkdir(parents=True, exist_ok=True)

    ENGINE = create_engine(
        f"sqlite:///{db_file}",
        echo=False,
        connect_args={"timeout": 30, "check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(ENGINE, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    if run_migrations:
        run_alembic_upgrade(db_file)
    else:
        Base.metadata.create_all(ENGINE)      # preserved for tests / first-run bootstrap

    SessionFactory = sessionmaker(bind=ENGINE, expire_on_commit=False)
    return ENGINE


@contextmanager
def session_scope():
    s = SessionFactory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
```

`check_same_thread=False` is required because the worker thread and Flask threads share the engine.
`expire_on_commit=False` prevents the lazy-reload-after-commit pattern that would otherwise generate
extra queries in the scrape loops.

**Pragma caveat worth knowing:** `journal_mode=WAL` is persistent (stored in the file header) but
`busy_timeout`, `synchronous`, and `foreign_keys` are **per-connection** and must be set on every
connect — hence the event listener rather than a one-time statement.

---

## 9. Query patterns and index justification

| Query | Index used | Why it matters |
|---|---|---|
| Batched dedup: `reddit_id IN (25 ids)` | `ix_leads_reddit_id` (unique, exists) | Replaces 25 queries with 1 |
| Ranked project leads | `ix_leads_project_conf (project_id, confidence_score DESC)` | The main dashboard query; covering-ish |
| Legacy dashboard, all leads by intent | `ix_leads_intent_score` (exists) | Unchanged path stays fast |
| Pending analysis backlog | `ix_leads_analysis_status` | `WHERE analysis_status='pending'` |
| Job claim | `ix_jobs_claim (state, available_at, priority, id)` | Column order matches the query exactly |
| Lease reclaim | `ix_jobs_lease (state, lease_expires_at)` | Runs every worker tick |
| Run progress counts | `ix_jobs_run (run_id, state)` | `GROUP BY state` for the progress bar |
| Comments for a lead | `ix_comments_lead` | Detail drawer |
| Cost per run | `ix_ai_calls_run` | Budget enforcement, checked before each call |
| Cost today (daily cap) | `ix_ai_calls_day` | Per-day budget guard |
| Identical content already analysed | `ix_ai_cache_content` | "Never analyse the same content twice" |

**Anti-pattern explicitly prohibited:** the current keyword-breakdown chart loads
`Lead.matched_keywords` for **every** row and aggregates in Python (`routes.py:143-154`). At 459
rows this is fine; at 50,000 it is not. It moves into `LeadRepository.keyword_breakdown()` with a
`LIMIT` and, if it ever becomes hot, a materialised counter table.

---

## 10. Data lifecycle and retention

| Table | Growth driver | Retention policy |
|---|---|---|
| `leads` | scrape volume | Never auto-deleted; user deletes explicitly |
| `comments` | leads × comments/post | Purge with the parent lead (`ON DELETE CASCADE`) |
| `lead_analysis` | items × prompt versions | Keep all versions; they are the audit trail |
| `jobs` | runs × stages | **Delete `done` jobs older than 30 days** (a scheduled maintenance job) |
| `run_events` | verbosity | **Delete events for runs finished > 90 days ago** |
| `http_cache` | request volume | **Delete `expires_at < now` every hour**; hard cap 500 MB |
| `ai_cache` | distinct prompts × content | **Keep — it is the cost saving.** Purge only by `prompt_version` when a prompt version is formally retired |
| `minhash_bands` | items × 16 bands per run | **Purge with the run** — it is a lookup index, not a record |
| `prescores` | one row per collected item | **Delete with runs finished > 90 days ago**; the funnel statistics are aggregated into `runs.stats_json` first |
| `dedup_groups` / `dedup_members` | groups per run | Cascade with the run |
| `gate_audits` | one row per run | Keep — it is the quality-evidence trail |
| `ai_calls` | one row per API call | **Delete rows older than 180 days**; aggregate monthly cost into `metrics` first |
| `ai_provider_state` | one row per provider | Never purged |
| `metrics` | 1 flush/min | **Delete rows older than 14 days** |

`ai_cache` deliberately has **no TTL**. An unchanged prompt asked about unchanged text has an
unchanged answer; expiring it would only cost money. Its growth is bounded by distinct
`(content_hash, stage, prompt_version)` triples, not by time.

A `maintenance` job type runs these purges nightly. Without it, `http_cache` alone would grow
without bound and eventually dominate the database file.

> ✅ **Shipped in P2** — `src/orchestration/handlers/maintenance.py`. All four purges plus a
> `VACUUM` guarded by a free-page threshold; `ai_cache` is deliberately untouched, and a test asserts
> that. **Nothing schedules it yet:** scheduling arrives with `hermes cron` in P24, so until then the
> job is enqueued by hand.

---

## 11. Backward-compatibility verification

Run after **every** migration, as an automated test:

```sql
SELECT COUNT(*) FROM leads;                              -- must be >= 459
SELECT COUNT(*) FROM leads WHERE project_id IS NULL;     -- must be >= 459
SELECT COUNT(*) FROM scrape_runs;                        -- must be >= 10
SELECT COUNT(*) FROM settings;                           -- must be >= 6
SELECT MIN(intent_score), MAX(intent_score), AVG(intent_score) FROM leads;
    -- must remain 5.0 / 164.28 / 42.29 (±0.01)
```

Plus a live check: `GET /` returns 200 and renders a lead table with the same total count, and
`GET /api/leads/export` returns exactly 13 header columns.
