# 06c — Local-First Pipeline: Never Call AI If It Isn't Required

> **The governing rule: AI is the last enrichment step, never the first.**
> Anything a regex, a hash, a set-membership test, a SQL query, or arithmetic can decide must not
> cost a token. This document specifies the deterministic machinery that runs before any provider
> call, and the measurement that proves it isn't silently discarding good leads.

---

## 1. The two funnels

### 1.1 Website intelligence

```
Website URL
     │
     ▼  LOCAL
┌──────────────────────────────────────────────────────────┐
│ Crawler          bounded fetch, ≤7 pages, ≤40 KB          │
│ HTML parsing     trafilatura → plain text                 │
│ Local extraction competitor dictionary · tech signals ·   │
│                  pricing regex · social links · schema.org│
│ Fingerprint      sha256(normalised extracted text)        │
└────────────────────────┬─────────────────────────────────┘
                         ▼
             ┌───────────────────────┐
             │  L1 Website cache     │  fingerprint unchanged?
             │  L2 Profile cache     │  profile exists for it?
             └───────────┬───────────┘
                    HIT  │  MISS
              ┌──────────┴──────────┐
              ▼                     ▼
        reuse, $0.00      ╔══════════════════════════╗
                          ║ ONE DeepSeek call        ║
                          ║ BusinessIntelligence     ║
                          ╚═══════════┬══════════════╝
                                      ▼
                              Stored + fingerprinted
```

### 1.2 Reddit enrichment

```
Scraping (old.reddit.com)
     │
     ▼  LOCAL — every stage below is deterministic and free
┌──────────────────────────────────────────────────────────────────┐
│ 1. Parsing            HTML → structured posts/comments           │
│ 2. Exact dedup        reddit_id + content_hash                   │
│ 3. Near-dedup         MinHash+LSH, char 5-grams, Jaccard ≥ 0.85  │
│ 4. Rule engine        keywords · negatives · competitor dict ·   │
│                       structural noise · author heuristics       │
│ 5. Metric scoring     upvotes · comments · recency · sub fit     │
│ 6. Ranking            deterministic pre-score, 0–100             │
│ 7. Filtering          PreAIGate — 11 rejection reasons, counted  │
│ 8. Semantic grouping  cluster representatives chosen             │
│ 9. Candidate select   top-N by pre-score within budget           │
└────────────────────────────────┬─────────────────────────────────┘
                                 ▼
                   ┌─────────────────────────┐
                   │  L3 Post-analysis cache │  content_hash seen
                   │      at this version?   │
                   └────────────┬────────────┘
                           HIT  │  MISS
                    ┌───────────┴───────────┐
                    ▼                       ▼
              reuse, $0.00      ╔═══════════════════════════╗
                                ║ Batched DeepSeek call     ║
                                ║ B=8 items per request     ║
                                ╚════════════┬══════════════╝
                                             ▼
                                    Persist · fan out to
                                    every lead in the group
                                             ▼
                          ┌──────────────────────────────────┐
                          │ Hybrid confidence — per lead,    │
                          │ NOT per group (§4.4)             │
                          └──────────────────────────────────┘
                                             ▼
                          ┌──────────────────────────────────┐
                          │ Holdout audit — 2% of REJECTS    │
                          │ enriched anyway → gate miss rate │
                          └──────────────────────────────────┘
```

---

## 2. What never touches AI

Enumerated so it is auditable, not aspirational. Each has a home in deterministic code.

| Task | Mechanism | Module |
|---|---|---|
| Keyword matching | substring / compiled regex | `rules/keywords.py` |
| Negative-term filtering | set membership | `rules/keywords.py` |
| Structural noise (hiring, giveaway, megathread) | compiled regex | `rules/structural.py` |
| Exact duplicate detection | `sha256` content hash | `dedupe/exact.py` |
| Near-duplicate detection | MinHash + LSH | `dedupe/minhash.py` |
| URL parsing / normalisation | `urllib.parse` | `net/urls.py` |
| Website crawling | `ProxiedHTTPClient` | `ai/website_fetcher.py` |
| HTML parsing | BeautifulSoup + trafilatura | `ai/website_fetcher.py` |
| Subreddit filtering | set membership | `discovery/` — **not** `rules/subreddits.py`; see the note below |
| Age / recency calculation | `datetime` arithmetic | `scoring/features.py` |
| Upvote / comment scoring | arithmetic | `scoring/features.py` |
| Author normalisation, bot detection | regex + allowlist | `rules/authors.py` |
| Sorting, filtering, ranking | SQL + Python | `db/repositories/` |
| **Competitor mention detection** | dictionary from the business profile | `rules/competitors.py` |
| **Tech-stack / pricing signals on a website** | regex + `schema.org` parse | `ai/site_signals.py` |
| Rule-based pre-scoring | weighted arithmetic | `scoring/prescore.py` |
| Similarity hashing | MinHash | `dedupe/minhash.py` |

> **Reconciliation, P9, 2026-08-14 — `rules/subreddits.py` does not exist and is not planned.**
> This table was the only document naming it. [34 §P9](34-implementation-plan.md)'s Files row lists
> five modules and not that one, and [03 §2](03-architecture.md)'s map likewise lists
> *"keywords · negatives · structural · competitors · authors"* while placing subreddit work in
> `src/discovery/` (*"subreddit candidate generation + validation + rank"*), which is
> [34 §P17](34-implementation-plan.md)'s. P9 built the five and deliberately did not create a sixth.
> The row is corrected rather than deleted because the *task* is real; only its address was wrong.

**Competitor detection deserves emphasis.** Once the business profile names competitors, finding
them in a Reddit post is a dictionary lookup with alias and misspelling variants — not a reasoning
task. Asking a model to do it would be paying for `in`.

**Enforced by test:** `src/rules/`, `src/dedupe/`, and `src/scoring/` must contain no import of
`src.ai` and no reference to any provider. Grep-verified in every phase's Part A.

---

## 3. The rule engine and pre-score

### 3.1 Deterministic pre-score (0–100, no AI)

```python
def prescore(item, project) -> PreScore:
    c = {
        "keyword_tier":   TIER_VALUE[item.matched_keyword_tier],      # high/med/low
        "keyword_density": min(1.0, item.keyword_hits / 3),
        "pain_phrase":    phrase_overlap(item.text, project.pain_phrases),
        "question_form":  1.0 if QUESTION_RE.search(item.title) else 0.0,
        "competitor":     1.0 if competitor_mentions(item.text, project) else 0.0,
        "recency":        recency_decay(item.created_utc),
        "engagement":     engagement(item.score, item.num_comments),
        "subreddit_fit":  project.subreddit_fit(item.subreddit),
        "length":         length_plausibility(len(item.text)),
    }
    return PreScore(total=100 * sum(W[k] * v for k, v in c.items()), components=c)
```

Every component is stored. The pre-score is a **recall instrument, not a precision one** — it is
tuned to cast wide and drop only items that are obviously not leads. Precision is the AI's job.

> ⚠️ **Shipped in P11, 2026-08-15: six of these nine components, and `W` is not written down
> anywhere.** Two findings, both recorded at [freeze §11.1](ARCHITECTURE_FREEZE.md).
>
> **Three components have no data source at revision `0006`.** `pain_phrase`, `competitor` and
> `subreddit_fit` all read `project.*`, and `projects`, `pain_points` and `bkb_entities` arrive in
> `0007` with **P12 — which depends on P11**. `src/scoring/prescore.py` therefore ships **six**, and
> declares the other three absent by name in `ABSENT_COMPONENTS`, each with the phase that supplies
> it. They are **not** shipped scoring `0.0`: that is [DI24](DEFERRED-IMPROVEMENTS.md)'s exact
> failure mode — a component nobody noticed was always zero — inside the phase that fixes DI24. The
> absences are persisted alongside the values in `prescores.components_json`, so a P12 reader can
> tell *"did not exist yet"* from *"scored 0.0"* once the components do exist.
>
> **`W` is supplied by no frozen document.** Grepped across `docs/` on 2026-08-15. P11 cites
> [04 §9.1](04-system-design.md)'s four **non-AI** weights rather than inventing six — `keyword 0.10`
> split evenly across the two keyword components, `recency 0.07` and `engagement 0.05` transferred
> directly, and `subreddit 0.03`'s *magnitude* reused for `question_form` and `length`, which 04 has
> no analogue for. The raw cited values are stored and **normalised by their own sum at call time**,
> which is what keeps the total inside 0–100 exactly and lets P12's three components slot in without
> re-tuning the six. Same discipline as P9's `min_chars: 80` and P10's `shingle_k`. **D1, D2.**

### 3.2 `PreAIGate`

```python
class PreAIGate:
    def evaluate(self, item, project, run) -> GateDecision:
        """Returns ADMIT | REJECT(reason) | CACHED(analysis_id) | GROUPED(rep_id)."""
```

| Reason | Rule | Typical share |
|---|---|---:|
| `already_analyzed` | `(content_hash, prompt_version)` seen | 0–60% on re-runs |
| `duplicate_exact` | content hash matches another item this run | 3–8% |
| `duplicate_near` | MinHash Jaccard ≥ 0.85 with a chosen representative | 8–20% |
| `negative_term` | project negative vocabulary | 10–20% |
| `structural_noise` | hiring / giveaway / megathread / AMA regex | 5–12% |
| `too_short` | `len(text) < min_chars` | 4–8% |
| `bot_or_deleted` | `[deleted]`, AutoModerator, `*Bot` | 2–5% |
| `out_of_window` | outside the run's time window | 0–10% |
| `downvoted` | comment score < 0 | 1–3% |
| `below_prescore` | pre-score under the admission threshold | **the tunable dial** |
| `budget_exhausted` | run's AI budget consumed | 0% normally |

Every reason is counted, persisted on the run, and rendered. A gate whose statistics are invisible
is a gate nobody will ever tune.

### 3.3 The admission threshold is adaptive, not fixed

`below_prescore` is where the operator trades money for coverage — but **the cut point is derived
from the pre-score distribution, not configured as a fixed threshold or percentage.** The full
mechanism is [06f — Adaptive AI Budget](06f-adaptive-budget.md); the summary:

> Sort the `n` candidates by pre-score, find the **knee** of the curve, bound it below by a
> mode-derived **quality floor**, bound it above by a **marginal-value** cutoff once labelled
> outcomes exist, then **clamp** to guard against degenerate distributions.

The three presets survive, but as an *appetite bias* applied to that computation rather than as the
rule itself:

| Mode | Knee × | Quality floor | ω | Fixed threshold (fallback only) | Use |
|---|---:|---:|---:|---:|---|
| `thorough` | 1.6 | ≥ 15 | 0.05 | ≥ 20 | Small runs, first run on a new project |
| `balanced` *(default)* | 1.0 | ≥ 25 | 0.15 | ≥ 35 | Normal operation |
| `frugal` | 0.6 | ≥ 40 | 0.30 | ≥ 50 | Large exhaustive scrapes, monitoring |

The `fixed_threshold` column is used only when adaptive budgeting cannot run — fewer than 200
candidates, or a distribution with no detectable knee. Both cases are reported explicitly rather
than silently substituted.

**Why the earlier fixed thresholds were replaced.** A fixed cut assumes a distribution *shape*. On a
run whose curve is still steep below 35 it discards real leads; on a flat curve it admits a large
block the rules already judged mediocre. The shape is fully observable before any AI call, so the
assumption was never necessary — see [06f §1](06f-adaptive-budget.md) and the five worked
distributions in [06f §4](06f-adaptive-budget.md).

The resulting count, the method that produced it, and **what the fixed cut would have admitted** are
all shown on the options screen before the run commits, so the choice stays explicit rather than
becoming an opaque automation.

---

## 4. Deduplication

### 4.1 Tier 1 — exact

`content_hash = sha256(normalise(title + "\n" + body))`, where `normalise` collapses whitespace,
casefolds, and strips markdown emphasis and trailing edit markers. Catches crossposts, reposts, and
quoted duplicates. One indexed lookup.

### 4.2 Tier 2 — near-duplicate via MinHash + LSH

```python
SHINGLE_K   = 5        # character 5-grams
NUM_PERM    = 128      # MinHash permutations
LSH_THRESH  = 0.85     # Jaccard
```

Character n-grams rather than word n-grams because Reddit text is noisy — typos, punctuation, and
casing vary far more than substance. LSH banding avoids the O(n²) comparison.

**Performance is a design target, not a measured claim.** Phase 6 asserts that indexing and querying
2,000 items completes in **< 2 s on CPU**; the surveyed literature covers different techniques at
different scales, so this number is validated in testing rather than assumed here.

> ⚠️ **Measured in P10, 2026-08-14 — and the literal reading of *"128 perms"* fails.** Classic
> MinHash re-hashes every shingle under 128 independent permutations, which cost **6.36 s** for
> 2,000 305-character documents and **11.11 s** for 870-character ones on the reference host. The
> shipped `src/dedupe/minhash.py` uses **One-Permutation Hashing with densification**: the same
> 128-slot signature, the same banding, the same estimator, measured at **0.27 s / 0.55 s** — and
> *more* accurate (0.0279 against 0.0308 mean absolute Jaccard error). This paragraph's caution was
> right: the number needed validating, and validating it changed the implementation.
> [freeze §11.1](ARCHITECTURE_FREEZE.md), 2026-08-14.

> ⚠️ **The paragraph that stood here — *"No embedding model, no vector database, no embeddings API.
> That tier is deliberately excluded"* — was superseded by [AD-16](03-architecture.md) and is
> struck.** [freeze §5](ARCHITECTURE_FREEZE.md) lists *"Vectors — Model2Vec + `sqlite-vec`,
> optional"*, and [34 §P10](34-implementation-plan.md) task 3 specifies the tier explicitly.
>
> Its objection is answered rather than overruled. Model2Vec is a **static distillation** — one
> matrix lookup per token, no GPU, no server, no API call — and `sqlite-vec` is a SQLite extension
> rather than a datastore, so neither is the *"new infrastructure and new per-item cost"* the
> exclusion rejected. §4.2a below is what actually ships.
> [freeze §11.1](ARCHITECTURE_FREEZE.md), 2026-08-14.

### 4.2a Tier 3 — paraphrase via a static embedding

*"Which CRM should I use"* and *"any recommendations for customer relationship software"* are the
same question and share **no** character 5-gram. Tiers 1 and 2 cannot see that; an embedding can.

```python
SEMANTIC_THRESHOLD = 0.88   # cosine; `null` means the tier does not run
```

**Optional, local, and never authoritative** ([AD-16](03-architecture.md)). It ships **off**
(`dedup.semantic_threshold: null`) because P0 measured neither `model2vec` nor `sqlite_vec` as
installed ([SPRINT-0-MEASUREMENTS §3.1](SPRINT-0-MEASUREMENTS.md)) — a tier defaulting to on would be
off in practice on every host, and a default that lies about what runs is worse than one that does
not.

When the library is absent the tier contributes nothing, raises nothing, and **the run produces the
identical lead set**. That is the acceptance criterion, not a hope: tier 3 is additive by
construction — it can only merge items tiers 1 and 2 left ungrouped, it never splits a group, and it
never removes an item.

The vector *store* (`bkb_embeddings`, `sqlite-vec`) arrives in `0007` with **P12**. P10's DB row is
*"None"*, so its tier 3 compares within the run's own items and persists nothing.

### 4.3 Group representative selection

```python
def choose_representative(group: list[Item]) -> Item:
    return max(group, key=lambda i: (i.prescore.total, i.score or 0, i.created_utc))
```

The representative is enriched; **the analysis is linked to every member of the group.**

> ⚠️ **`prescore` does not exist until P11, and P11 depends on P10.** `src/scoring/prescore.py` is
> [34 §P11](34-implementation-plan.md)'s Files row, so the cascade that ships in P10 takes the
> pre-score as an **injected** value (`DedupItem.rank`, default `None`) and falls back to
> `(score, created_utc, row_id)` — the trailing row id being the tie-break that keeps selection
> deterministic when the first three are equal. P11 fills `rank` in without a signature change.
> [34 §P10](34-implementation-plan.md)'s *"a group of N yields N distinct pre-scores"* moves to P11
> with it; what P10 proves is that grouping preserves N distinct members and mutates no per-item
> score. [freeze §11.1](ARCHITECTURE_FREEZE.md), 2026-08-14.

> ✅ **Filled in by P11, 2026-08-15.** `rank` now carries the pre-score at the cascade's only call
> site (`src/orchestration/handlers/prescore.py`), so the ordering this section specifies is what
> runs — **no signature changed**, exactly as P10 designed for.
>
> ⚠️ **And the *"N distinct pre-scores"* criterion is not literally satisfiable.** Measured on the
> live 492 leads: of **23** groups, **two** yield fewer distinct totals than members. Leads 108/109
> are a repost pair created **one minute apart** with identical text, both at 0 upvotes and 0
> comments; every component agrees to four decimals and both total **32.28**. A 60-second age
> difference moves `recency` by ~0.003%, below the second decimal the total is rounded to.
>
> **That is §4.4 working, not failing.** What §4.4 requires is *score individually* — each member
> gets its **own** score from its **own** metadata — and two posts identical in every scored
> dimension scoring identically is the correct answer. Adding decimal places until sub-minute ages
> separate them would game a criterion rather than measure a lead. Selection stays deterministic
> under the tie via the trailing `row_id`. [freeze §11.1](ARCHITECTURE_FREEZE.md), 2026-08-15.

### 4.4 The correctness rule: group for analysis, score individually

This is the subtle part and getting it wrong would be a silent quality regression.

Two near-identical "which CRM should I use" threads may have different authors, subreddits,
recency, and engagement — and therefore genuinely different value as leads.

```
dedup group (3 leads)
   └── ONE lead_analysis row          ← the AI judgement, shared
         ├── lead A → confidence 84   ← own recency + engagement + subreddit fit
         ├── lead B → confidence 71
         └── lead C → confidence 52
```

**One shared `lead_analysis`; three different `confidence_score` values.** Collapsing the scores
too would emit three identical numbers for three different-value leads, and the operator would
correctly stop trusting the ranking.

The UI shows a "similar discussions (3)" affordance on grouped leads so the grouping is visible
rather than hidden.

---

## 5. Incremental enrichment

Nothing is ever analysed twice at the same prompt version.

```python
key = (content_hash, prompt_version)
if existing := repo.analysis_by_key(project_id, key):
    repo.link_analysis(item, existing)     # zero calls, zero cost
```

| Scenario | Items enriched |
|---|---|
| First run | All admitted candidates |
| Re-run, nothing changed | **0** |
| Re-run, 50 new posts arrive | ≤ 50 (fewer after dedup) |
| Post edited (content hash changed) | That post only |
| Prompt version bumped | All admitted candidates, old rows retained |
| Comments added to an analysed post | The comments only; the post is reused |

**Scheduled monitoring is the case this exists for.** A project polled every 24 hours over a month
performs one full enrichment and then thirty cheap deltas.

---

## 6. The holdout audit — proving the gate is honest

A gate that discards a good lead is worse than no gate, because it fails silently. Cost
optimisation that cannot be measured is indistinguishable from quality loss.

```python
HOLDOUT_RATE = 0.02        # 2% of REJECTED candidates

def audit_sample(rejected: list[Item]) -> list[Item]:
    """Deterministic sampling: hash-based, so the audit is reproducible per run."""
    return [i for i in rejected if stable_hash(i.content_hash) % 50 == 0]
```

Sampled rejects are enriched anyway and compared against what the gate assumed:

```
Gate miss rate    3.1%   (4 of 128 sampled rejects would have qualified as leads)
Target            < 5%
Verdict           ✓ gate is not over-filtering
```

| Field | Meaning |
|---|---|
| `sampled` | Rejects re-admitted for audit |
| `would_have_qualified` | Of those, how many the AI marked `is_lead` |
| `gate_miss_rate` | The ratio — the headline number |
| `worst_reason` | Which rejection reason produced the most misses |

Surfaced on the run page and `/health/ai`. Above threshold → an explicit warning:
*"Your filter rejected an estimated 7% of real leads. Consider switching to `thorough` mode."*

**`worst_reason` is the actionable part** — it tells the operator *which* rule is too aggressive,
usually an over-broad negative keyword.

**Cost:** 2% of rejects on a typical run is ~8 extra items, roughly $0.001. A rounding error against
the ~85% the gate saves, in exchange for the only real evidence that quality is intact.

### 6.1 The audit is also the exploration channel

**Audited items are persisted as real, labellable leads**, flagged `leads.source='holdout_audit'`
and badged in the lead list. This is not a convenience — it is what stops the learning loop
degenerating.

The adaptive budget's yield curve is fitted from operator labels. Labels exist only for leads the
operator sees; the operator sees only leads the gate **admitted**. Fitting on admitted leads alone
would teach the curve the shape of the gate's own output, which would then narrow the gate, every
cycle — and precision, also measured only on admitted leads, would never reveal it
([02c §0](02c-research-final-review.md)).

The 2% sample is random exploration of exactly the region no other signal reaches. Storing only the
aggregate counts — as the original design did — produced a **metric with no learning signal**.

Two requirements follow, both asserted in the test suite ([06i §8](06i-feedback-and-memory.md)):

- Audit-sourced leads appear in the lead list and can be labelled like any other.
- `YieldCurve` fitting **must not filter to admitted leads.** A test fails if the query contains
  such a predicate.

The audit keeps its measurement role unchanged and gains a second one it was always structurally
capable of performing.

**Exclusions from sampling:** `already_analyzed`, `duplicate_exact`, `duplicate_near`, and
`budget_exhausted` are never sampled — those rejections are provably correct, and auditing them
would waste calls proving arithmetic works.

> ✅ **Built in P11, 2026-08-15 — the stage-3 half of R11, and it costs nothing.**
> `src/scoring/holdout.py`, sampled in `src/orchestration/handlers/discover.py`.
>
> **No body is fetched, and none needs to be.** [34 §P11](34-implementation-plan.md) task 6 says
> *"2% of metadata-triage rejects get bodies fetched and full-scored"* on the premise that a triage
> reject has no body — but P5 measured that the feed carries the body for ~97% of posts **in the
> request stage 1 already makes** ([freeze §11.1](ARCHITECTURE_FREEZE.md), 2026-08-08), which is why
> stage 4 was reduced to body *accounting*. The bodies are already in hand, so the audit costs **no
> extra request** rather than the ~$0.001 estimated above. The ~3% with no body anywhere are link and
> media posts, scored on their titles.
>
> **No AI is involved, and that is not a compromise.** [34 §P11](34-implementation-plan.md) requires
> `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` to be **0**, so *"would have qualified"* cannot mean
> *"the model marked `is_lead`"* at this stage. It means **the full-stage deterministic gate admits
> what the metadata gate rejected** — which is exactly the disagreement worth measuring at a stage
> whose whole premise is deciding without a body. The AI-judged variant needs `gate_audits`
> (revision `0009`) and is P19/P20's.
>
> **`no_title` joins the exclusion list**, as P11's own addition: a post with no title has nothing
> for the full-stage gate to score, so sampling it enters a guaranteed non-miss into the denominator
> and biases the published rate **downwards** — flattering the gate, the one direction an audit must
> never be wrong in.
>
> **The first thing it caught was [DI25](DEFERRED-IMPROVEMENTS.md).** `triage.py`'s bare
> `\bhiring\b` had been discarding *"Our hiring process is broken and I need a tool to fix it"* live
> since P6. The full-stage gate scores that post **66.88 and admits it**. The audit was built
> **before** the regex was fixed, deliberately — fixing it first would have deleted the evidence that
> justified the fix — and `test_the_audit_catches_di25s_own_example_as_a_miss` reproduces the
> detection against the pre-fix pattern.

---

## 7. Where each stage lives

| Stage | Phase | Module |
|---|---|---|
| Local site signal extraction | 4 | `ai/site_signals.py` |
| Website fingerprint + L1/L2 cache | 4 | `ai/website_fetcher.py`, `ai/cache.py` |
| Exact dedup | 6 | `dedupe/exact.py` |
| MinHash near-dedup | 6 | `dedupe/minhash.py` |
| Rule engine + pre-score | 6 | `rules/`, `scoring/prescore.py` |
| `PreAIGate` | 7 | `ai/gate.py` |
| Group representative selection | 7 | `dedupe/groups.py` |
| Candidate selection + budget | 7 | `ai/gate.py` |
| Batched enrichment | 7 | `ai/service.py` |
| Holdout audit | 7 | `ai/holdout.py` |
| Per-lead confidence fan-out | 7 | `scoring/confidence.py` |

---

## 8. Worked example — 1,200 collected items, `balanced`

```
 1,200  collected
  −312  already analysed at this prompt version (re-run)
  − 58  exact duplicates
  − 95  near-duplicates removed
          142 items formed 47 groups; the 47 representatives are KEPT,
          so 142 − 47 = 95 are resolved by reusing a group's analysis
  −186  negative term
  − 94  structural noise
  − 61  too short
  − 38  bot or deleted
  − 27  out of window
  ──────
   329  candidates passed the hard filters      ( n = 329, 27% of collected )
  −115  below the adaptive admission cut
          knee at rank 214 · floor(≥25) allows 268 · clamp [17, 296]
          method = "knee"   (a fixed ≥35 cut would have admitted only 180)
  ──────
   214  admitted to AI                          (18% of collected)
  +  3  holdout audit sample (2% of 115 rejects)
  ──────
   217  items enriched

   214 ÷ 8 = 27 enrichment calls  +  1 holdout call  =  28 DeepSeek calls
   cost ≈ $0.031

   Against naive one-call-per-post over the same 1,200 items:
     1,200 calls · $0.178 (cache working) or $0.672 (cold cache)

   43× fewer calls · 83% lower cost vs. cache-working naive, 95% vs. cold
   gate miss rate MEASURED at 2.8%
```

Note that adaptive budgeting made this run **more** expensive than the fixed ≥35 cut would have
(214 admitted rather than 180, $0.031 rather than $0.026) — and that is the correct outcome. The
knee shows the pre-score curve is still steep below 35, so those 34 extra candidates are on the
slope, not the tail. **Minimising calls is the goal; minimising them below the point where real
leads start being discarded is not.** The holdout audit is what tells the difference, and at 2.8% it
confirms the wider cut is not leaking.

**Read the near-duplicate line carefully.** Grouping does not discard 142 items — it discards 95 and
keeps 47 representatives, whose single analysis is then reused by every member of their group. All
142 leads still appear in the dashboard, each with its own confidence score
([§4.4](#44-the-correctness-rule-group-for-analysis-score-individually)).
