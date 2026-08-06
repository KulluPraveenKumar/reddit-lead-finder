# 06e — Business Knowledge Base

> A website stops being an input to one AI call and becomes a **persisted, versioned, queryable
> model of the business** that every later stage reads from. This is the platform's core asset and
> its primary differentiator ([02a §3](02a-competitor-analysis.md)).

---

## 1. What changes and why

**Before.** The site was crawled, one AI call produced eight artefacts, they were stored, and
downstream stages read a few of them.

**After.** The site produces a **Business Knowledge Base (BKB)** — 23 typed sections, entity-resolved,
versioned, embedded, and reused. The distinction is not cosmetic:

| | Artefact store | Knowledge base |
|---|---|---|
| Shape | A JSON blob per artefact kind | Typed sections + resolved entities + typed links |
| Reuse | Read whole by the next stage | Queried by section, by entity, by similarity |
| Lifetime | Superseded on regeneration | Versioned; sections evolve independently |
| Enrichment context | Everything or nothing | A deliberate **matching subset** (§6) |
| Growth | Static after generation | Accumulates evidence from every run (§7) |

The knowledge base is what makes the platform improve over time rather than merely repeat itself.

---

## 2. The 23 sections

Grouped by how they are used, which turns out to matter more than what they contain.

### Group A — Identity (generation input, display, rarely matched)

| # | Section | Contents |
|---|---|---|
| 1 | `company_overview` | What the company is, one paragraph; founding context if stated |
| 2 | `products_services` | Named offerings with one-line descriptions |
| 3 | `features` | Capability list, grouped by product |
| 4 | `pricing_positioning` | Model (free/freemium/tiered/enterprise), posture, published price points if detectable |
| 5 | `industry` | Primary + adjacent, with a taxonomy code where one applies |
| 6 | `target_market` | B2B/B2C, company sizes, stages, geographies |

### Group B — Buyer model (the matching surface)

| # | Section | Contents |
|---|---|---|
| 7 | `ideal_customer_profiles` | 1–3 ICPs, each with firmographics, trigger events, disqualifiers |
| 8 | `buyer_personas` | 1–5 personas: role, seniority, responsibilities, metrics, tools, where they ask for help |
| 9 | `pain_points` | 3–12, each with severity, frequency, **how people phrase it** |
| 10 | `jobs_to_be_done` | Functional / emotional / social jobs, in JTBD form |
| 11 | `value_propositions` | Claims made, mapped to the pain they answer |

### Group C — Competitive and linguistic (matching surface)

| # | Section | Contents |
|---|---|---|
| 12 | `competitor_references` | Named competitors + **aliases, misspellings, abbreviations** (§4) |
| 13 | `alternative_solutions` | Non-product alternatives: spreadsheets, agencies, in-house builds, doing nothing |
| 14 | `customer_language` | Verbatim phrasing customers use, sourced from testimonials, FAQs, and support copy |
| 15 | `reddit_terminology` | Slang, abbreviations, community-specific vocabulary |
| 16 | `search_intent` | Query shapes: informational / comparison / transactional / troubleshooting |
| 17 | `buying_signals` | Weighted, tiered signal taxonomy |
| 18 | `common_objections` | Price, trust, migration cost, incumbent lock-in, "we built it internally" |

### Group D — Activation and discovery (retrieval-only)

| # | Section | Contents |
|---|---|---|
| 19 | `outreach_angles` | Per persona × pain: the framing that would land |
| 20 | `content_themes` | Topic clusters the business can credibly speak to |
| 21 | `seo_entities` | Named entities the business should own in search |
| 22 | `geo_entities` | Entities relevant to LLM/AI answer surfaces |
| 23 | `negative_signals` | What indicates *not* a lead: hiring, promos, students, competitors' own staff |

**Section 23 is deliberately part of the knowledge model, not a filter config.** Knowing what a
business is *not* looking for is business knowledge, it improves with use, and it belongs beside
the positive signals it mirrors.

---

## 3. Storage model — typed sections, resolved entities, explicit links

### 3.1 The knowledge-graph question, decided

Research is clear that graph databases earn their overhead on **multi-hop traversal** — paths,
neighbourhoods, patterns across connected data — and that for document-shaped or shallow-relationship
work, relational plus vector storage is sufficient.

**→ Decision: adopt the knowledge *model*, refuse the graph *database*.**

Our deepest query is two hops (`persona → pain → phrasing`, `competitor → alias → mention`). That is
a join, not a traversal. A typed relational model with explicit link tables in the **existing SQLite
database** gives the semantics — entities, types, relationships, provenance — with no second
datastore, no new process, no new backup story, and no new failure mode.

This is recorded so a future reader does not "upgrade" the design to Neo4j and inherit an
operational dependency for a two-hop join.

### 3.2 Shape

```
bkb (one current row per project, versioned)
   ├── bkb_sections            23 rows: version, confidence, in_prefix, edited_by_user
   │      ├── payload_json     the content — for 20 of the 23 sections
   │      └── payload NULL     for buyer_personas / pain_points / buying_signals,
   │                           whose content lives in the typed tables below (05 §5.1b)
   ├── personas ─┬─ pain_points ─┬─ intent_signals    typed, slug-keyed, bkb_id-scoped
   │             └───────────────┘   joined on by lead_analysis
   ├── bkb_entities            canonical entities WITHOUT a typed table:
   │      │                    competitor, product, feature, tool, alternative
   │      └── bkb_entity_aliases   surface forms, misspellings, abbreviations
   ├── bkb_links               typed edges: persona→pain, pain→value_prop, competitor→alternative
   ├── bkb_evidence            verbatim source spans + provenance URL per claim
   ├── bkb_suggestions         learned proposals, operator-gated (§7)
   └── bkb_embeddings          section- and entity-level vectors (§5, optional)
```

**Sections version independently.** Regenerating personas must not invalidate the competitor
registry — those have different lifetimes and different evidence.

**Every claim carries evidence.** `bkb_evidence` stores the verbatim source span and the page it
came from. This is what makes the BKB auditable rather than a pile of plausible assertions, and it
is what the verbatim-quote validator checks against.

---

## 4. Entity resolution

Competitor and tool mentions are the highest-signal matches in the whole pipeline — someone asking
for "an alternative to X" is the warmest possible lead. Catching them requires resolving surface
forms to canonical entities.

The production pattern is **canonicalise → block → match**, with cheap deterministic matching first
and expensive methods reserved for the residue.

```python
class EntityRegistry:
    def resolve(self, surface: str) -> ResolvedEntity | None:
        """1. exact alias hit          (dict lookup)
           2. normalised alias hit     (casefold, strip punctuation/spacing)
           3. fuzzy alias hit          (Levenshtein ≤ 2 on tokens > 5 chars)
           4. embedding neighbour      (cosine ≥ 0.82, §5) — the only non-deterministic tier
           None if all four miss."""
```

Alias generation at BKB build time, all deterministic:

| Source | Example |
|---|---|
| Site comparison pages | `vs\.?\s+(\w+)`, `alternative to (\w+)` |
| Casing and spacing variants | `HubSpot` → `hubspot`, `hub spot` |
| Common misspellings | keyboard-adjacency + doubled/dropped letters |
| Abbreviations and acronyms | `Google Analytics` → `GA`, `GA4` |
| Domain forms | `hubspot.com`, `@hubspot` |

**Why this matters more than it looks.** A Reddit user writes "hubspots pricing is insane". No
keyword matches. Alias resolution catches it, and it becomes a `competitor_mention` — one of the
highest-weighted signals in the confidence score.

---

## 5. The semantic layer — a reversed decision

### 5.1 The reversal, stated plainly

[02 §6.10](02-research-findings.md) rejected embedding-based semantic matching as "disproportionate:
it requires either a hosted model or an embeddings API — new infrastructure and new per-item cost."

**That judgment was correct under the frame it was made in, and is wrong under this one.** Two things
changed:

1. **The objective changed.** This is an internal platform optimising for *intelligence*, not a
   cost-minimising product optimising for simplicity.
2. **The cost assumption was wrong for static embeddings.** Model2Vec distils a sentence transformer
   into a static model that is **~30 MB on disk, runs on CPU, and embeds 50–100k documents per
   second** — no API, no GPU, no server. Paired with **sqlite-vec**, vectors live in the database we
   already have.

The marginal cost of the semantic layer is a 30 MB file and a SQLite extension. Under the original
frame it was "new infrastructure"; measured, it is neither new infrastructure nor a per-item cost.

**→ Decision: adopt a local semantic layer.**

### 5.2 What it is used for

| Use | Why lexical matching fails | Gain |
|---|---|---|
| **Semantic near-dedup** | MinHash catches rewordings, not paraphrases. "Which CRM should I use?" and "Looking for recommendations on customer management software" share almost no character 5-grams. | Higher collapse rate → fewer AI calls |
| **Subreddit discovery (4th channel)** | LLM proposal + search harvest + sidebar are all lexical or model-recall bound | Finds communities whose *description* matches the ICP without sharing vocabulary |
| **Pain-point matching in the pre-score** | A post can describe a pain using none of the tracked phrases | Higher recall at the gate → lower miss rate |
| **BKB retrieval** | Selecting which sections to load for a given task | Keeps the enrichment prefix small (§6) |
| **Entity resolution tier 4** | Aliases cannot be exhaustively enumerated | Catches unanticipated surface forms |

### 5.3 What it is deliberately *not* used for

- **Not a replacement for MinHash.** Both run. MinHash is precise on rewordings and cheap;
  embeddings are recall-oriented and fuzzier. Exact hash → MinHash → embeddings, in that order,
  each catching what the previous cannot. This is the standard **cheap-recall-then-expensive-precision
  cascade**, and running only the expensive tier would be slower *and* less precise.
- **Not a RAG system over raw site text.** The BKB *is* the retrieval artefact. Chunking and
  re-retrieving raw HTML would reintroduce exactly the noise that structuring the knowledge removed.
- **Not a vector database.** `sqlite-vec` in the existing file. No new server.

### 5.4 Trade-off, stated

Embedding similarity has **lower precision than MinHash** at any given recall. Two posts about
unrelated products can be near neighbours because both are frustrated questions about software
pricing. Mitigations: a higher threshold for grouping (cosine ≥ 0.88) than for candidate
suggestion (≥ 0.75); embeddings never *reject* an item, only group or surface it; and any
embedding-formed group still resolves to **one analysis with N individually-scored leads**, so a
wrong grouping costs a shared analysis, never a wrong score.

---

## 6. What enters the enrichment prefix — and what does not

**The single most important operational decision in this document.** A richer BKB makes the frozen
prefix bigger, and the enrichment prefix is sent with every batch.

The cost impact is negligible — cached input is $0.0028/M — but **prefix size dilutes attention in a
batched prompt**, and attention dilution is exactly the failure mode that caps batch size
([02 §6.8](02-research-findings.md)). A 7,000-token prefix carrying pricing tiers and content
themes would make an 8-item batch measurably worse at the only job it has.

**→ The principle: the prefix carries only what the classifier must match *against*. Everything
else is retrieved on demand.**

| Enters the enrichment prefix (~3,500 tok) | Retrieval-only (queried when needed) |
|---|---|
| ICP summary + disqualifiers (compressed) | Full company overview |
| Persona slugs + titles, one line each | Persona responsibilities, metrics, tools |
| Pain slugs + `how_people_phrase_it` | Pain descriptions, severity rationale |
| Buying-signal slugs + tier + example phrases | Signal descriptions |
| Competitor canonical names + top aliases | Full alias tables, alternative solutions |
| Customer-language phrases (top 20) | Full language corpus |
| Negative signals | Objections, outreach angles, content themes |
| — | Products, features, pricing, JTBD, value props, SEO/GEO entities |

**Retrieval-only sections are used where they belong:** outreach angles at lead-detail render time,
content themes and SEO/GEO entities during keyword generation, features and value propositions when
explaining *why* a lead matches ([06g](06g-explainability-and-quality.md)).

A `prefix_token_budget` (default 4,000) is enforced at build time. If the compressed matching
surface exceeds it, sections are dropped in a fixed priority order and **the drop is logged** —
never silently truncated, because a silently shortened prefix changes classification behaviour with
no visible cause.

---

## 7. The knowledge base learns

A BKB that never changes after generation is just a bigger artefact store. Three feedback paths make
it accumulate:

| Signal | Source | Effect |
|---|---|---|
| **Confirmed competitor mentions** | Enrichment finds a competitor alias not in the registry | Proposed as a new alias, queued for operator confirmation |
| **High-confidence pain phrasing** | Leads scoring >80 contain phrasings absent from `how_people_phrase_it` | Proposed as additional phrasings |
| **Lead outcome labels** *(Phase 8)* | The operator marks a lead `interested` / `rejected` | Feeds confidence calibration ([06g §4](06g-explainability-and-quality.md)) and flags which pains and personas actually convert |

The first two paths are live from Phase 7. **The third activates in Phase 8**, because it depends on
the `lead_labels` table that ships in migration `0009` — the knowledge base starts learning from
matches before it can learn from outcomes.

**All three propose; none auto-apply.** Automatic self-modification would let one mis-scored lead
poison the knowledge base, and the errors would compound silently. A **Knowledge Suggestions** panel
shows pending proposals with their evidence, and the operator accepts or rejects — the same review-gate
philosophy that governs subreddits and keywords, applied to the knowledge model.

---

## 8. Generation

Still **one consolidated call** ([06 §3](06-ai-pipeline.md)). The BKB is richer, not more expensive
in call count.

```
crawl + local extraction  →  ONE analyze_business() call  →  BKB v1
                                                              ├─ 23 sections
                                                              ├─ entity resolution (local)
                                                              ├─ embeddings (local, ~200 ms)
                                                              └─ evidence linkage (local)
```

| | Value |
|---|---|
| Input | ~12,000 tok (site text + local signals) |
| Output | ~7,000 tok (23 sections) |
| `max_tokens` | 12,000 — headroom against truncation |
| Cost | **≈ $0.0037** |
| Calls | **1** |

Up from $0.0025 for the eight-artefact version. **Roughly one-tenth of one cent more for a
substantially richer knowledge model** — which is exactly the trade an internal intelligence
platform should take.

Section-level failure isolation: a repair failure in `content_themes` does not discard
`pain_points`. Sections that fail validation after the repair ladder are marked `incomplete` and
individually regenerable, rather than failing the whole call.

---

## 9. Versioning and lifecycle

| Event | Behaviour |
|---|---|
| Website fingerprint unchanged | **No AI.** BKB reused as-is. |
| Website changed | Diff extracted text; regenerate **only** affected sections where attributable, else full regeneration |
| Prompt version bumped | New BKB version; previous retained for comparison |
| Operator edits a section | Section marked `edited_by_user`; regeneration requires confirmation |
| Suggestion accepted | Section version increments; provenance records "operator-confirmed" |
| Project archived | BKB retained — it is the durable asset |

**The BKB outlives runs.** Runs come and go; the knowledge base is the thing worth keeping, and it
is what makes the second project on the same domain nearly free.

---

## 10. Why this is the platform's core advantage

Neither competitor persists business understanding ([02a §3](02a-competitor-analysis.md)). RedShip
analyses a website and terminates in keywords; Tydal starts from keywords. In both, the richest
artefact the system ever produces is used once and discarded.

Consequences of keeping it:

1. **Every stage reads from one shared, versioned model** instead of re-deriving context — the
   compression that makes the whole cost model work.
2. **Matching is against a buyer model, not a keyword list.** A post that never uses a tracked term
   can still match on pain phrasing, persona language, or a competitor alias.
3. **Explanations become concrete.** "Matched pain `attribution-gap`, persona `growth-lead`,
   competitor `Segment`" is possible only because those are first-class entities
   ([06g](06g-explainability-and-quality.md)).
4. **Knowledge compounds.** Confirmed aliases and phrasings make the next run better.
5. **Re-runs are nearly free** because the expensive artefact already exists.

---

## 11. Schema summary

Full DDL in [05 §5.1 and §5.1a](05-database-plan.md); all of it ships in migration **`0005`**, which
*replaces* the former `ai_artifacts` table rather than adding to it. No new migration is introduced.

| Table | Rows | Purpose |
|---|---|---|
| `bkb` | 1 current per project | Version, prompt version, prefix token count, status |
| `bkb_sections` | 23 per BKB | `section_key`, `payload_json`, `confidence`, `version`, `in_prefix`, `edited_by_user` |
| `personas` · `pain_points` · `intent_signals` | 1–12 each | **Pre-existing typed entity tables**, now BKB-scoped via `bkb_id` and joined on by `lead_analysis`. They back sections **8 `buyer_personas`, 9 `pain_points`, 17 `buying_signals`** — for those three the typed table is authoritative and `payload_json` is `NULL`. **`ideal_customer_profiles` has no typed table** and keeps its payload — see [05 §5.1b](05-database-plan.md) |
| `bkb_entities` | 10–100 per project | Only the kinds *without* a typed table: competitor, product, feature, tool, alternative |
| `bkb_entity_aliases` | 3–10 per entity | Surface forms + generation source; the index behind resolution tiers 1–3 |
| `bkb_links` | 20–200 per project | Typed edges with polymorphic `(kind, id)` endpoints |
| `bkb_evidence` | 1–6 per claim | Verbatim span + source URL + snapshot |
| `bkb_embeddings` + `bkb_embedding_meta` | ~50 per project | `sqlite-vec` vectors — **conditional; skipped if the extension is unavailable** |
| `bkb_suggestions` | variable | Pending proposals with evidence, awaiting operator review |

**One registry per entity kind, never two.** `personas`, `pain_points`, and `intent_signals` are
already typed tables with slugs and are referenced by foreign key from analysis rows, so they are
*not* duplicated into `bkb_entities`, and their content is *not* duplicated into
`bkb_sections.payload_json` either. Splitting by whether a kind needs a typed table avoids the
failure mode where a persona exists in two places and the two disagree; the `NULL`-payload rule in
[05 §5.1b](05-database-plan.md) is what stops that duplication being reintroduced later.
