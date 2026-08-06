# 06 — AI Pipeline

> The end-to-end flow from website URL to ranked lead. **AI is the last enrichment step, never the
> first.** The deterministic machinery that runs before it is in
> [06c](06c-local-first-pipeline.md); provider mechanics in [06a](06a-ai-service-layer.md) and
> [06b](06b-deepseek-optimization.md); call and cost budgets in [06d](06d-ai-budget-and-scale.md).

---

## 1. Pipeline map

```
Website URL
     │
     ▼  ════════════ LOCAL, FREE ════════════
┌──────────────────────────────────────────────────────────┐
│ Crawler → HTML parse → clean text                        │
│ Local signal extraction:                                 │
│   competitor dictionary · pricing regex · tech markers ·  │
│   schema.org · social links · nav taxonomy                │
│ Fingerprint = sha256(normalised text)                    │
└────────────────────────┬─────────────────────────────────┘
                         ▼
          ┌──────────────────────────────┐
          │ L1 website cache (7 d)       │  unchanged? ─► reuse, $0.00
          │ L2 profile cache (permanent) │  exists?    ─► reuse, $0.00
          └──────────────┬───────────────┘
                    MISS │
                         ▼
    ╔════════════════════════════════════════════════════════╗
    ║  ONE DeepSeek call — analyze_business()                 ║
    ║  ────────────────────────────────────────────────────   ║
    ║  Business summary · industry · product category ·       ║
    ║  target audience · competitors · positioning ·          ║
    ║  value proposition · ICP · buyer personas ·             ║
    ║  pain points · buying signals · search intent ·         ║
    ║  Reddit vocabulary · negative keywords ·                ║
    ║  recommended subreddits · recommended keywords          ║
    ╚═══════════════════════┬════════════════════════════════╝
                            ▼
                 Stored + fingerprinted
                            │
              ╔═════════════╧═════════════╗
              ║ GATE 1 subreddits (human) ║
              ║ GATE 2 keywords   (human) ║
              ╚═════════════╤═════════════╝
                            ▼
                     Scraping (old.reddit.com, proxied)
                            │
     ▼  ════════════ LOCAL, FREE ════════════
┌──────────────────────────────────────────────────────────────────┐
│ Parse → exact dedup → MinHash near-dedup → rule engine →         │
│ metric scoring → deterministic pre-score → PreAIGate →           │
│ semantic grouping → candidate selection within budget            │
└────────────────────────────────┬─────────────────────────────────┘
                                 ▼
                  ┌──────────────────────────┐
                  │ L3 post-analysis cache   │  seen at this version?
                  │ L3b duplicate group      │  ─► reuse, $0.00
                  └────────────┬─────────────┘
                          MISS │
                               ▼
      ╔═══════════════════════════════════════════════════════╗
      ║  BATCHED DeepSeek call — enrich_batch(), B=8           ║
      ║  summary · pain point · problem category · urgency ·   ║
      ║  buying intent · ICP match · persona match ·           ║
      ║  competitor mention · sentiment · opportunity ·        ║
      ║  priority · evidence · outreach angle                  ║
      ╚═══════════════════════┬═══════════════════════════════╝
                              ▼
              Fan out to every lead in each duplicate group
                              ▼
      ┌───────────────────────────────────────────────────────┐
      │ HYBRID CONFIDENCE — per lead, not per group           │
      │ rules + AI + Reddit metrics + recency + engagement    │
      └───────────────────────┬───────────────────────────────┘
                              ▼
      ┌───────────────────────────────────────────────────────┐
      │ HOLDOUT AUDIT — 2% of rejects enriched anyway         │
      │ → gate miss rate, published                           │
      └───────────────────────┬───────────────────────────────┘
                              ▼
                          Dashboard
```

**Two model-invoking stages for an entire project.** One consolidated call for business
intelligence, and one batched call per eight admitted items. Everything else is deterministic.

---

## 2. Stage A — crawl and local extraction (no AI)

### 2.1 Fetch policy

```python
PRIORITY_PATHS = ["/pricing", "/product", "/features", "/solutions",
                  "/use-cases", "/about", "/customers", "/how-it-works"]
MAX_PAGES, MAX_DEPTH, MAX_TOTAL_CHARS, PER_PAGE_TIMEOUT = 7, 2, 40_000, 15
```

Normalise the URL, fetch through `ProxiedHTTPClient`, score internal links against
`PRIORITY_PATHS`, extract with `trafilatura` (BeautifulSoup fallback), concatenate, truncate,
persist to `website_snapshots` with a `content_hash`.

### 2.2 Local signal extraction — before any model sees the text

| Signal | Mechanism |
|---|---|
| Named competitors | Dictionary + alias table, seeded from a comparison-page regex (`vs\.?\s+\w+`, `alternative to \w+`) |
| Pricing posture | Currency + interval regex over `/pricing` |
| Tech markers | `<script src>` hostnames, `<meta generator>`, well-known analytics/CRM domains |
| Structured metadata | `schema.org` JSON-LD: `Organization`, `Product`, `Offer` |
| Social / community links | `href` host matching |
| Product taxonomy | Nav and footer link text |

These are **passed to the model as facts**, not questions. Asking a model to find a `<meta
generator>` tag is paying tokens for a parser.

### 2.3 Failure handling

| Condition | Behaviour |
|---|---|
| Landing page fails after retries | Run `FAILED`, message names the status |
| An internal page fails | Skipped, logged, run continues |
| Extracted text < 500 chars | `thin_content` flag; UI warns; confidence reduced |
| JS-only SPA | Same `thin_content` path — no headless browser |
| **Fingerprint matches a snapshot < 7 days old** | **L1 hit — zero fetches, zero AI** |
| **Fingerprint has an existing profile at this prompt version** | **L2 hit — zero AI** |

---

## 3. Stage B — one consolidated intelligence call

### 3.1 Why one call

| | Calls | Input tok | Output tok | Cost |
|---|---:|---:|---:|---:|
| Six staged calls | 6 | 21,200 | 7,700 | $0.0051 |
| **One consolidated call (23-section BKB)** | **1** | **12,000** | **7,000** | **$0.0037** |

The dollar saving is a quarter of a cent and is not the argument. What matters: **six round trips
become one**, and the `BusinessProfile` is no longer re-sent as uncached input to five downstream
stages.

### 3.2 What it returns

```python
class BusinessIntelligence(BaseModel):
    profile:        BusinessProfile        # summary, industry, category, positioning,
                                           # target audience, competitors, value props
    icp:            ICP
    personas:       list[Persona]          = Field(min_length=1, max_length=5)
    pain_points:    list[PainPoint]        = Field(min_length=3, max_length=12)
    intent_signals: list[IntentSignal]     = Field(min_length=3, max_length=12)
    vocabulary:     RedditVocabulary       # incl. search-intent phrases + negative keywords
    subreddits:     list[SubredditProposal] = Field(min_length=5, max_length=30)
    keywords:       list[GeneratedKeyword]  = Field(min_length=8, max_length=40)
```

`max_tokens = 8000`, giving ~2× headroom over the expected 4,000 so a rich site cannot truncate the
JSON mid-string.

### 3.3 Keywords are generated once, not per subreddit

The earlier design generated keywords **per approved subreddit** — 12 extra calls. They are now
produced once as a single pool with `applies_to` hints, and specialised per subreddit
**deterministically** by intersecting the pool with that subreddit's description vocabulary.

**12 calls → 0.** The per-subreddit tailoring that justified them is a set intersection.

### 3.4 The regeneration escape hatch

One mega-call has real costs: without isolation a schema violation would lose all 23 sections, and per-section
regeneration becomes impossible. The dashboard already promises per-tab **Regenerate**, so:

- **Primary flow:** one consolidated call.
- **Regeneration:** one targeted `regenerate_section(key, ctx)` call reusing persisted upstream
  context.

The brief's requirement is satisfied for the path that runs on every project, without dropping a
capability the UI exposes.

### 3.5 Risk and mitigation

| Risk | Mitigation |
|---|---|
| One schema violation discards everything | Repair ladder is **field-scoped**: the error names the failing path (`personas[3].slug`) and only that constraint is restated on retry |
| 4,000-token output truncates | `max_tokens=8000`; `finish_reason == "length"` triggers a retry at 1.5× |
| Model does eight jobs at once, quality dips | Golden-set comparison against the six-call baseline is a Phase-4 acceptance criterion — **consolidation ships only if quality holds** |
| Harder to attribute a bad section | Every section carries its own `confidence` and `status`; failure is isolated to that section; the evidence panel is per-claim |

---

## 4. Stage C — local processing before enrichment

Fully specified in [06c](06c-local-first-pipeline.md). Summary of what happens with **zero** API
calls:

| # | Stage | Removes / does |
|---|---|---|
| 1 | Parse | HTML → structured items |
| 2 | Exact dedup | `content_hash` — crossposts, reposts |
| 3 | Near dedup | MinHash + LSH, Jaccard ≥ 0.85 → groups |
| 4 | Rule engine | keywords, negatives, structural noise, competitor dictionary |
| 5 | Metric scoring | upvotes, comments, recency, subreddit fit |
| 6 | Pre-score | deterministic 0–100, all components stored |
| 7 | `PreAIGate` | 11 rejection reasons, each counted |
| 8 | Grouping | one representative per duplicate group |
| 9 | Candidate selection | top-N by pre-score within the run's budget |

Typical effect: **1,200 collected → 179 admitted (~15%)**.

---

## 5. Stage D — batched enrichment

### 5.1 The contract

```python
report = ai.enrich_batch(items=admitted, ctx=project_context, on_result=persist)
```

| Property | Value |
|---|---|
| Batch size | **8** default, adaptive 4–12 — a *measured* ceiling ([06b](06b-deepseek-optimization.md)) |
| Prefix | Frozen project context, byte-identical, chunk-aligned |
| Per item in the user turn | `id`, subreddit, type, title, body (truncated), top comment digest |
| Output | JSON array, **one element per input, each echoing its `id`** |
| Length mismatch | **Batch-level failure** → split in half, retry both |
| Concurrency | Bounded adaptive pool, default 8 batches in flight |
| Attribution | `futures[fut] → batch`, then `id` → item. Never positional. |

### 5.2 Two-level attribution

Batching adds a second attribution layer, and both must be explicit:

```
future  ──►  batch          (futures[fut] map — never array position)
  id    ──►  item           (echoed id — never array position)
```

A batch whose response array length differs from its input, or which contains an unknown or
duplicated `id`, is rejected wholesale and split. **Silently accepting 7 results for 8 inputs is
the failure mode that quietly loses leads**, and it is the reason both the id-echo requirement and
the length check exist.

### 5.3 Fan-out to duplicate groups

One `lead_analysis` row per enriched representative, linked to every member of its group. **Each
lead still computes its own `confidence_score`** from its own recency, engagement, and subreddit
fit — see [06c §4.4](06c-local-first-pipeline.md).

---

## 6. Output schemas

Pydantic v2 in `src/ai/schemas.py`. DeepSeek's JSON mode guarantees **syntax, not schema**, so every
constraint is enforced client-side by the repair ladder.

```python
class LeadAnalysis(BaseModel):
    """Per-item enrichment. Categoricals only — no final score."""
    id: str                                          # ★ MUST echo the input id
    is_lead: bool
    summary: str = Field(max_length=300)
    pain_point_slug: str | None = None
    matched_pain_slugs: list[str] = Field(max_length=5)
    problem_category: str | None = None
    urgency: Literal["none","low","medium","high","critical"]
    buying_intent: Literal["unaware","problem_aware","solution_aware",
                           "evaluating","ready_to_buy"]
    matched_signal_slugs: list[str] = Field(max_length=5)
    icp_match: Literal["none","weak","partial","strong"]
    persona_slug: str | None = None
    competitor_mentions: list[str] = Field(max_length=5)
    sentiment: Literal["negative","frustrated","neutral","positive"]
    opportunity_score: int = Field(ge=0, le=10)      # ONE input to the scorer, not the score
    recommended_priority: Literal["low","medium","high","urgent"]
    evidence_quote: str = Field(max_length=400)      # VERBATIM
    reasoning: str = Field(max_length=400)
    suggested_outreach_angle: str = Field(max_length=300)
    disqualifiers: list[str] = Field(max_length=4)

class EnrichmentBatch(BaseModel):
    results: list[LeadAnalysis] = Field(min_length=1, max_length=16)
```

**`id` is the first field for a reason** — it is the attribution key, and putting it first makes a
truncated or malformed element detectable at the point of parse.

`reasoning` and `suggested_outreach_angle` are capped tighter than in the unbatched design (400/300
vs 600/400). Output is the 100× token class, and eight items multiply every saved token by eight.

### 6.1 Verbatim evidence check

```python
def validate_evidence(quote: str, source: str) -> bool:
    return not quote or _norm(quote) in _norm(source)
```

In a batch this runs **per element against its own source item**, matched by `id`. A quote that
validates against the wrong item is exactly the cross-contamination batching risks, so this check
doubles as a batch-integrity test.

---

## 7. Prompt design

Six mandatory sections plus a **Batch Contract** for batched prompts.

```markdown
# Role / # Task / # Rules / # Rubric

# Batch Contract
You will receive N items in a json array, each with an "id".
Return exactly N result objects, one per input item, in the same order.
Every result MUST include the "id" of the item it describes, copied exactly.
Never merge two items. Never omit an item. Never invent an id.
If an item is unanalysable, still return an object for it with is_lead=false.

# JSON Shape
```json
{"results": [
  {"id": "lead-8891", "is_lead": true, "summary": "...", "urgency": "high",
   "buying_intent": "evaluating", "icp_match": "strong", "sentiment": "frustrated",
   "opportunity_score": 8, "recommended_priority": "high",
   "evidence_quote": "...", "reasoning": "...", "suggested_outreach_angle": "..."}
]}
```

# Output
Return only the json object. No prose, no markdown fences.
```

The "still return an object for it with `is_lead=false`" instruction matters: without it, a model
that judges an item irrelevant tends to drop it, producing a length mismatch and a spurious batch
failure.

---

## 8. Failure taxonomy

| Failure | Detection | Response | User-visible |
|---|---|---|---|
| Website unreachable | HTTP after retries | Run `FAILED` | "Could not reach <url>" |
| Thin content | `len(text) < 500` | Continue, flag | Amber banner |
| **Batch length mismatch** | `len(results) != len(batch)` | **Split in half, retry both** | Nothing unless exhausted |
| **Unknown / duplicate `id`** | Set comparison | Batch failure, split | Nothing |
| Empty AI content | `content == ""` | Perturbed retry ×2 | Nothing |
| Invalid JSON | parse error | Strip fences, retry ×2 | Nothing |
| Schema violation | Pydantic | Field-scoped retry ×2, then fail the batch | "Analysis failed" + retry |
| Truncated output | `finish_reason == "length"` | Retry at `max_tokens × 1.5`, or split | Nothing |
| Evidence matches the wrong item | Cross-check by `id` | Blank + flag; log as contamination | "not verifiable" |
| Unknown slug | Set membership | Drop the slug, keep the rest | Nothing |
| 401 invalid key | HTTP | Stop AI, mark key invalid | Settings red |
| **402 balance** | HTTP | Stop, preserve work | "Balance exhausted" |
| 429 / 503 | HTTP | Backoff + halve concurrency | "Rate limited" |
| Budget / call-ceiling exceeded | Pre-call guard | Stop, preserve, `partial_analysis` | "Cap reached. Raise it?" |
| **Cache not hitting** | `prompt_cache_hit_tokens == 0` after batch 2 | Loud warning | "Cache inactive — costs may be far above estimate" |
| **Gate miss rate above threshold** | Holdout audit | Warning + `worst_reason` | "Filter rejected ~7% of real leads" |
| Everything `is_lead=false` | Distribution check | Warning | "Review your ICP" |

The last two rows are the quality guardrails. A pipeline that runs flawlessly and produces nothing
looks identical to a broken one unless something checks.

---

## 9. Evaluation and calibration

**Golden set** — 40 hand-labelled items in `tests/fixtures/golden_leads.jsonl`.

**Two evaluations, both required before shipping a change:**

1. **Batch-size sweep** — run the golden set at B ∈ {1, 4, 8, 12, 16}; publish precision, recall,
   F1, and mean output tokens per B. Ship the largest B whose F1 is within 0.02 of B=1.
2. **Consolidation check** — run the golden site set through the one-call `analyze_business()` and
   the staged baseline; section quality must not regress.

**Prompt versions** are pinned in settings, so a new file on disk never silently changes behaviour.

**Live calibration** bins leads by confidence decile and reports the `interested` rate per bin; a
flat curve means the score carries no information.

**Gate calibration** is the holdout audit ([06c §6](06c-local-first-pipeline.md)) — the only
evidence that aggressive filtering is not costing leads.

---

## 10. Cost summary

Full model in [06d](06d-ai-budget-and-scale.md).

| | Calls | Cost |
|---|---:|---:|
| Business Knowledge Base (once per website version) | **1** | $0.0037 |
| Enrichment, 1,000 collected posts (`balanced`) | **~21** | $0.023 |
| Enrichment, 10,000 collected posts | **~209** | $0.236 |
| Unchanged re-run | **0** | **$0.00** |
| Naive one-call-per-post, 1,000 posts | 1,000 | $0.148 |
| Default caps | 500 calls / run | $2.00 run · $5.00 day |
