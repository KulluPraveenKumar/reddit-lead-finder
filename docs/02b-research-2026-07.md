# 02b — Deep Research: Intelligence Architecture

> Research conducted 2026-07-30 for the internal-tool architectural review. Twenty topics, each
> ending in a **decision** — adopt, adopt-with-limits, defer, or reject — with the reasoning stated.
> A research note with no decision attached is a note nobody will act on.
>
> Companion documents: [02](02-research-findings.md) (Reddit, proxies, DeepSeek mechanics) and
> [02a](02a-competitor-analysis.md) (Tydal and RedShip).

---

## How to read the verdicts

| Verdict | Meaning |
|---|---|
| ✅ **Adopt** | In the roadmap, with a phase |
| ⚠️ **Adopt with limits** | In, but deliberately scoped down; the limit is stated |
| ⏸ **Defer** | Valuable, dependency named, not scheduled |
| ⛔ **Reject** | Considered and declined, with the reason |

**Seven of the twenty end in "reject" or "defer."** That is the point of a research phase. An
architecture that adopts everything it reads about is not evidence-based; it is fashionable.

---

## Group A — The AI layer

### 1. DeepSeek V4 Flash internals

Covered in depth in [02 §6.2–6.9](02-research-findings.md). The findings that drive architecture:
1M context, 384K max output, MoE 284B/13B activated, OpenAI-compatible wire format, **implicit**
prefix caching in 64-token chunks with a 50× price differential, **no batch endpoint**, and JSON
mode that validates *syntax only* — never schema.

**Two consequences worth restating here**, because they shape everything downstream:

- **The 50× cache differential is the single largest cost lever in the system**, larger than
  batching, larger than model choice. Architecture that keeps a byte-stable prefix is therefore not
  a micro-optimisation; it is the cost model.
- **Because caching is implicit and best-effort with no guaranteed hit rate**, every cost figure must
  be quoted as a hot–cold range. A design that only works with a warm cache is a design that fails
  every Monday morning.

✅ **Adopt** — as already specified in [06b](06b-deepseek-optimization.md).

### 2. AI orchestration patterns

The consistent finding across production write-ups is that **deterministic orchestration outperforms
model-driven orchestration** for pipelines whose steps are known in advance. Agent frameworks earn
their unpredictability when the task decomposition is genuinely unknown; ours is not — the pipeline
is crawl → analyse → discover → gate → enrich → score, every time.

⛔ **Reject agent frameworks.** No LangChain, no LangGraph, no tool-calling loop. The orchestration
is Python control flow in a worker ([04 §3](04-system-design.md)). This costs us nothing we want and
saves an entire dependency surface, a class of nondeterminism, and an unbounded token cost.

✅ **Adopt** the one orchestration pattern that does apply: **bounded adaptive concurrency with
two-level attribution** (`futures[fut] → batch`, then echoed `id` → item). Positional attribution
across a concurrency pool is the classic silent-corruption bug in batched LLM pipelines.

### 3. Enrichment pipeline design

Production enrichment pipelines converge on the same shape: **filter cheap, enrich expensive,
and make the filter's cost measurable.** The failure mode is not enriching too little; it is
filtering aggressively while having no idea what the filter discarded.

✅ **Adopt** the local-first funnel ([06c](06c-local-first-pipeline.md)) *with* the holdout audit.
The audit is not an add-on to the funnel — it is the thing that makes aggressive filtering
defensible rather than merely cheap.

### 4. Hybrid rule + LLM systems

The literature is consistent: **rules for what is deterministic, models for what is ambiguous, and
never let the model do arithmetic.** LLMs are poorly calibrated numeric estimators; asking one for a
"confidence score from 0–100" produces a number with clustering artefacts (heavy mass on 70, 80, 85)
and no stable meaning across prompts.

✅ **Adopt, and it is already the design.** The model emits **categoricals only** (`strong` /
`moderate` / `weak`, `evaluating` / `researching` / `unaware`); deterministic Python maps those to
weights and sums. This is what makes re-ranking free, calibration possible, and the explanation
faithful ([06g §1](06g-explainability-and-quality.md)).

### 5. Prompt lifecycle management

Findings: prompts are code and need versioning, diffing, and rollback; the reliable regression
signal is a **held-out labelled set**, not eyeballing outputs; and prompt changes must be gated,
because a fluent-looking prompt edit can silently degrade grounding.

✅ **Adopt.** Prompts live in versioned files, `prompt_version` is stored on every artefact and
analysis, and **a version cannot ship if golden-set F1 drops more than 0.02**
([06g §5](06g-explainability-and-quality.md)). The blocking gate is the part that matters; versioning
without a gate is just a changelog.

### 6. Production AI systems — what actually breaks

Recurring failure modes in production LLM deployments, and our specific answer to each:

| Failure mode | Our mitigation |
|---|---|
| Schema drift in model output | Pydantic validation + three-branch repair ladder, max 2 attempts per branch |
| Silent provider model updates | Golden-set regression + PSI drift monitoring ([06g §4.4](06g-explainability-and-quality.md)) |
| Cost blowout from a loop or a retry storm | Four independent ceilings, checked **pre-call** ([06d §4](06d-ai-budget-and-scale.md)) |
| Positional misattribution in batches | Echoed `id` per item; length mismatch is a **failure**, never a partial success |
| Cache invalidation from prefix mutation | Byte-stable frozen prefix; a cache-hit collapse alert |
| Quality regression nobody notices | The entire §4.4 drift suite |

⚠️ **Adopt with limits** — no distributed tracing, no external observability vendor. Structured logs
plus the `ai_calls` table cover a single-operator internal tool; OpenTelemetry would be
instrumentation for a scale we do not have.

---

## Group B — Knowledge representation

### 7. Semantic search & 8. Vector search

The relevant finding is not "vector search works" — it is that **static embeddings changed the cost
structure**. Model2Vec distils a sentence transformer into a static model: ~8–30 MB, CPU-only,
50–100k documents/second, no server. Combined with `sqlite-vec`, vectors live in the database that
already exists.

Also material: the **two-stage retrieval cascade** is the standard production shape — a cheap
high-recall first stage, then an expensive high-precision reranker, reported to gain roughly 5–15%
NDCG@10 over single-stage. The generalisable principle is *cheap recall first, expensive precision
second*, which is exactly the shape of our dedup tiers and our pre-score → AI gate.

✅ **Adopt a local semantic layer.** This **reverses** the exclusion in
[02 §6.10](02-research-findings.md); the reversal and its justification are in
[06e §5](06e-business-knowledge-base.md).

⛔ **Reject a vector database.** Pinecone, Weaviate, Qdrant, Chroma — all solve a scale problem
(millions of vectors, distributed queries, ANN index tuning) we do not have. We have ~50 vectors per
project. A dedicated service would be a new process, a new backup story, and a new failure mode in
exchange for nothing.

### 9. Knowledge graphs vs structured knowledge bases

Graph databases earn their overhead on **multi-hop traversal** — paths, neighbourhoods, patterns
across arbitrarily connected data. For document-shaped data with shallow relationships, relational
storage plus vectors is sufficient and simpler.

Our deepest query is **two hops** (`persona → pain → phrasing`; `competitor → alias → mention`).
That is a join.

⛔ **Reject the graph database.** ✅ **Adopt the graph *model***: typed entities, typed links, and
provenance, in SQLite ([05 §5.1a](05-database-plan.md)). We get the semantics — entity identity,
relationship types, evidence — without a second datastore. Recorded explicitly so nobody later
"upgrades" this to Neo4j and inherits an operational dependency for a two-hop join.

### 10. Entity resolution

The production pattern is **canonicalise → block → match**, with cheap deterministic comparisons
first and expensive methods reserved for the residue. Blocking exists to avoid the O(n²) all-pairs
comparison; alias tables are the standard canonicalisation mechanism.

✅ **Adopt** — the four-tier resolver in [06e §4](06e-business-knowledge-base.md): exact alias →
normalised alias → fuzzy alias → embedding neighbour. Tiers 1–3 are dictionary and edit-distance
lookups; only tier 4 is non-deterministic, and it never fires unless the first three miss.

**Why this ranks so high for us specifically:** a competitor mention is the highest-value signal in
the pipeline, and it is *the* signal most likely to be missed by keyword matching. "hubspots pricing
is insane" matches no keyword and resolves cleanly through an alias table.

### 11. RAG over structured business profiles

The finding that matters is negative: **naive RAG over raw documents underperforms structured
retrieval when the structure is knowable in advance.** Chunking discards exactly the organisation
you spent an LLM call creating.

⛔ **Reject RAG over raw website text.** ✅ **Adopt structured retrieval over BKB sections.** The BKB
*is* the retrieval artefact — sections are the chunks, and they are semantically coherent by
construction rather than by a 512-token window. Re-chunking the raw HTML would reintroduce the noise
that structuring removed.

This also settles a practical question: what goes in the enrichment prefix. **Only the matching
surface** (~3,500 tokens); everything else is retrieved on demand
([06e §6](06e-business-knowledge-base.md)). Not for cost — cached input is $0.0028/M — but because
**prefix length dilutes attention in a batched prompt**, which is the same mechanism that caps batch
size ([02 §6.8](02-research-findings.md)). A bigger prefix would make an 8-item batch measurably
worse at its only job.

---

## Group C — Efficiency and adaptivity

### 12. Incremental enrichment

✅ **Adopt** — `(content_hash, prompt_version)` as the reuse key ([06c §5](06c-local-first-pipeline.md)).
The consequence is the strongest single economic property in the design: **an unchanged re-run costs
$0.00**, which is what makes scheduled monitoring viable at all.

### 13. Semantic deduplication

✅ **Adopt** the three-tier cascade (§7–8 above; [02 §6.10](02-research-findings.md) as revised).

The correctness rule is the part most likely to be got wrong: **group for analysis, score
individually.** Two near-identical threads have different authors, subreddits, recency, and
engagement, and therefore different value. One `lead_analysis` row links to N leads, each keeping
its own score components. Collapsing the scores too would emit N identical numbers for N
different-value leads — a silent quality bug that would look like a working feature.

### 14. Adaptive AI budgeting

This was the least-settled topic and required composing findings rather than adopting one.

- **Knee/elbow detection** — Kneedle identifies the point of maximum curvature on a
  monotonic curve. Known weaknesses: instability at small N and on near-uniform curves. Both are
  handled by clamps and a small-`n` bypass.
- **Adaptive stopping** — the standard rule is to stop when marginal gain falls below a fraction of
  the first step's gain. Applied to expected lead yield, fitted from labelled outcomes.
- **Guardrails are not optional.** Every source that recommends automatic thresholding also
  recommends bounding it. An unclamped Kneedle on 250 near-identical scores will confidently return
  rank 3.

✅ **Adopt** the composed mechanism in [06f](06f-adaptive-budget.md): knee × mode bias, bounded below
by a quality floor, above by marginal value, clamped, and **validated after the fact by the holdout
audit**. The pairing is the substance: the knee decides how many, the audit decides whether the knee
was right. Neither is sufficient alone — the knee has no ground truth, the audit has no control input.

⚠️ **Limit:** the marginal-value stage requires ~200 labelled outcomes and simply does not run before
then. Documented rather than faked, because a yield curve fitted on 12 labels is noise with a
confident interface.

---

## Group D — Quality and observability

### 15. AI quality evaluation & 16. AI observability

Findings: LLM-as-judge is convenient but correlates weakly with human judgement on domain-specific
relevance tasks; a small hand-labelled golden set is the reliable signal; and **precision without
recall is the metric of a system that has quietly stopped finding things.**

✅ **Adopt** the 100-item golden set as the blocking gate on prompt and model changes.
⛔ **Reject LLM-as-judge** for scoring quality. We would be using the same model to grade itself on
the same failure modes, and it would cost real money to produce a correlated error.

✅ **Adopt** per-call telemetry into `ai_calls` (tokens, cache hit/miss, latency, repair, cost) —
the substrate every other metric is computed from, at zero marginal cost since the response carries
it.

### 17. Confidence calibration

**ECE** (Expected Calibration Error) with 10 bins and the **Brier score** are the standard measures;
**isotonic regression** is the standard monotonic recalibration, and it preserves ranking while
fixing meaning.

✅ **Adopt** — target ECE < 0.10, reported as `insufficient_data` below 100 labels.
✅ **Adopt** the response rule: when calibration is off, **recalibrate, do not reweight.**
Reweighting changes which leads are at the top; recalibration changes only what the number claims.
Conflating the two is how a calibration fix silently becomes a ranking regression.

### 18. Cost monitoring

✅ **Adopt** four independent ceilings checked pre-call, plus per-run/day/month rollups.

The design point: **cost and call count can diverge**. A prompt-size regression raises cost without
raising calls; a batching regression raises calls without raising cost much. Two independent dials
catch both; one would miss half the failures.

### 19. Reddit & discussion intelligence

Reddit-specific signals that generic text analysis misses, all computed locally: comment-tree
position, score velocity vs subreddit baseline, OP-replied, question vs statement structure,
crosspost origin, account age and karma bands, flair, and **subreddit-relative** engagement (30
points is exceptional in a niche subreddit and unremarkable in a large one).

✅ **Adopt** — all of these feed the pre-score. **None requires AI**, and normalising engagement
against the subreddit's own baseline rather than an absolute threshold is the difference between a
signal and a popularity contest.

### 20. Lead intelligence & information extraction

The consistent finding across information-extraction work: **closed-set selection beats open
generation** for anything that will be stored, joined, or filtered. A model asked to "identify the
persona" invents a new label every third call; a model asked to pick from six slugs picks a slug.

✅ **Adopt** — the model selects from BKB-defined slug enums, and a slug outside the set fails
validation. This is what makes explanations joinable to the knowledge base, and it is the mechanism
behind the entity links in [06g §3](06g-explainability-and-quality.md).

✅ **Adopt** verbatim-span grounding: every quoted span must be a literal substring of the source.
Non-matching spans are dropped and counted, giving `hallucinated_span_rate` — the earliest and
cheapest available signal that a prompt change has degraded grounding.

---

## What this research changed

Five decisions were **reversed or materially altered** by this phase. Each is corrected at its
source rather than annotated, per the instruction not to append notes:

| # | Was | Now | Why it changed |
|---|---|---|---|
| 1 | Embeddings excluded as "new infrastructure and new per-item cost" ([02 §6.10](02-research-findings.md)) | Local static-embedding tier adopted | The cost premise was **factually wrong for static embeddings** (30 MB, CPU, no API), and the internal-tool framing changed the objective |
| 2 | Website analysis → four artefacts, used once | **23-section versioned Business Knowledge Base** ([06e](06e-business-knowledge-base.md)) | The richest artefact in the system was being discarded — the specific weakness identified in both competitors |
| 3 | Fixed admission thresholds, ~15% of collected | **Adaptive budget** from the pre-score distribution ([06f](06f-adaptive-budget.md)) | A fixed cut assumes a distribution shape that is fully observable before any AI call |
| 4 | `ai_artifacts` table in migration `0005` | **Replaced** by `bkb` + `bkb_sections` + entity tables, still in `0005` | Superseded by #2; keeping both would create two sources of truth for the same facts |
| 5 | Explanation implicit in the stored score components | **Ten explicit fields**, five computed locally, four closed-set, one constrained prose ([06g](06g-explainability-and-quality.md)) | Explainability was assumed to fall out of the design; it needed to be specified to be testable |

Reversals 1 and 3 also moved the numbers: enrichment now admits **~18% of collected rather than
~15%**, and a 1,000-post run costs **$0.030 rather than $0.026**. Both figures went **up**, and both
were re-derived rather than adjusted. That direction is deliberate — the goal is the minimum number
of calls that does not discard real leads, not the minimum number of calls. The holdout audit is
what distinguishes the two, and it is why we can tell.
