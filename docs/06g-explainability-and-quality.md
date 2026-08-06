# 06g — Explainability & Quality Measurement

> Two halves of one requirement. **Explainability** answers *why is this lead here?* for a single
> lead. **Quality measurement** answers *is the system still right?* across all of them. Neither is
> optional in a platform whose output is a ranked list an operator will act on.

---

## Part I — Explainable Leads

## 1. Faithful by construction

There are two ways to explain a machine judgement, and only one of them is trustworthy.

| Approach | How it works | Problem |
|---|---|---|
| **Post-hoc rationalisation** | Compute a score, then ask the model to explain it | The explanation is generated *from* the score, not from the computation. It can be fluent and wrong. Research on LLM self-explanation consistently finds stated reasoning need not reflect actual reasoning. |
| **Faithful by construction** *(ours)* | The score **is** a weighted sum over named, stored components. The explanation enumerates them. | The explanation cannot diverge from the computation, because it *is* the computation, rendered. |

Our hybrid confidence engine ([04 §9](04-system-design.md)) already computes the score in
deterministic Python from 11 stored components. **The explanation is therefore free** — it is a
rendering of data we must store anyway.

**Rule: no explanation field may be produced by a model call whose output is not also an input to
the score.** If the model writes it and nothing consumes it, it is decoration, and decoration that
looks like reasoning is worse than no reasoning at all.

---

## 2. The ten explanation fields

Every lead carries these. Provenance is stated for each, because *where a field comes from*
determines how much it can be trusted.

| # | Field | Source | Type |
|---|---|---|---|
| 1 | `matched_icp` | Model selects from BKB ICP slugs (closed set) | Entity ref + fit strength |
| 2 | `matched_persona` | Model selects from BKB persona slugs (closed set) | Entity ref + evidence span |
| 3 | `matched_pain_points` | Model selects from BKB pain slugs (closed set) | Entity refs + verbatim spans |
| 4 | `matched_product_features` | **Local** — feature-term index over post text | Entity refs + matched terms |
| 5 | `matched_customer_language` | **Local** — phrase index from BKB §14/15 | Phrase list + offsets |
| 6 | `buying_signals` | Model selects from BKB signal taxonomy (closed set) | Signal refs + tier + spans |
| 7 | `matched_keyword_cluster` | **Local** — which keyword group found this item | Cluster ref |
| 8 | `competitor_mentions` | **Local** — entity registry resolution ([06e §4](06e-business-knowledge-base.md)) | Canonical entity + surface form |
| 9 | `why_relevant` | Model, ≤ 240 chars, **constrained to reference only fields 1–8** | Prose |
| 10 | `confidence_reasoning` | **Deterministic** — rendered from the score components | Structured breakdown |

**Five of ten are computed locally at zero cost.** Four are *selections from closed sets*, not free
generation — the model picks slugs that exist in the BKB, so an invented persona fails validation.
Only field 9 is free prose, capped at 240 characters, and validated to mention nothing absent from
1–8.

### 2.1 Verbatim-span validation

Every quoted span must appear **exactly** in the source text. This is checked with a string search,
not a similarity measure:

```python
def validate_spans(analysis: Analysis, source: str) -> list[SpanError]:
    """Every evidence span must be a literal substring of source.
    Non-matching spans are dropped and counted in `hallucinated_span_rate`."""
```

A dropped span does not fail the lead — it degrades the explanation and **increments a published
metric**. A rising `hallucinated_span_rate` is the earliest available signal that a prompt change
has degraded grounding, and it costs nothing to compute.

### 2.2 Field 10 is not written by a model

`confidence_reasoning` is rendered from the stored components:

```
Confidence 78 / 100
  Pain match          strong        +22.5   (attribution-gap, tooling-sprawl)
  Buying intent       evaluating    +18.0   (tier-2: "comparing options")
  Persona fit         strong        +15.0   (growth-lead)
  ICP fit             partial        +7.5
  Competitor mention  yes            +6.0   (Segment — via alias "segment.io")
  Solution seeking    yes            +4.5
  Post engagement     34 pts, 12 c   +2.4
  Recency             6 days         +3.5
  Negative signals    none           -0.0
  Subreddit fit       0.71           +1.4
  Author signals      neutral        +0.0
```

The numbers add up because they are the arithmetic. An operator who thinks 78 is too high can see
which component to reweight. **This is what neither competitor offers**
([02a §5](02a-competitor-analysis.md)) — and it costs one extra output field, because everything
shown is already stored.

---

## 3. Rendering

**Lead card (list view)** — the three highest-contribution components, always the same three slots:

```
r/SaaS · 6d · 34↑ 12💬                                        78
"anyone else drowning in attribution reports?"
  pain attribution-gap · intent evaluating · persona growth-lead
  mentions Segment
```

**Lead detail** — full breakdown, source spans highlighted in the original text, entity links back
to the BKB section that defined each matched entity, and the `suggested_outreach_angle` pulled from
BKB §19 by `(persona × pain)` — a retrieval, not a generation.

**Why the entity links matter.** Clicking `attribution-gap` shows the pain as the BKB defines it,
including its evidence from the source website. The operator can see the whole chain: *this website
sentence → this pain definition → this Reddit phrasing → this score component*. That is auditability
end to end, and it is only possible because entities are first-class ([06e §3](06e-business-knowledge-base.md)).

---

# Part II — Quality Measurement

## 4. The metric suite

Grouped by what each answers. **Cost column is honest** — some of these require labelled data or
extra calls, and pretending otherwise would be how a metric suite quietly stops being maintained.

### 4.1 Accuracy — "are the leads good?"

| Metric | Definition | Source | Cost |
|---|---|---|---|
| **Precision @ threshold** | Of leads scored ≥ 70, fraction the operator marks `interested` | Operator labels | Free (labels are already collected) |
| **False positive rate** | High-scored leads marked `not relevant` | Operator labels | Free |
| **Rejection-reason mix** | Which `not_relevant` reason dominates | `lead_labels.reason` | Free |
| **False negative estimate** | Real leads the gate rejected | **Holdout audit** | see below |
| **Gate miss rate** | Fraction of audited rejects that would have scored ≥ 70 | Holdout audit | Included above |
| **`worst_reason`** | Which rejection reason produces the most misses | Holdout audit | Free |

**The rejection-reason mix is a diagnosis, not a score.** A `not_relevant` rate of 0.19 says the
system is wrong sometimes; `wrong_persona` appearing in 11 of those 19 says *which thing* is wrong,
and routes to the persona definition rather than to the scorer
([06i §2.2](06i-feedback-and-memory.md)). It costs one nullable column and turns an aggregate
complaint into an actionable one.

**Holdout cost, stated precisely.** The audit samples **2% of rejected candidates** — that is a
*sample rate*, not a spend share, and the two must not be used interchangeably. Because the sample
is batched at B=8 alongside everything else, it is typically **one extra call per run**. On the
canonical 1,000-post run ([06d §3.1](06d-ai-budget-and-scale.md)) it is **1 call of 23 — ≈ 4.3% of
run spend, ~$0.001**. On a large run it is 1 of 88, under 1.2%.

**It is the single most important metric in this document** — the only one that measures what
aggressive filtering *costs*. Precision without recall is the metric of a system that has quietly
stopped finding things, and 4.3% is a very low price for knowing.

### 4.2 Calibration — "does 80 mean 80?"

A score that ranks correctly but is systematically overconfident makes every threshold decision
wrong. Two standard measures:

| Metric | What it detects | Target |
|---|---|---|
| **ECE** (Expected Calibration Error, 10 bins) | Average gap between stated confidence and observed hit rate | **< 0.10** |
| **Brier score** | Mean squared error of the probability estimate — captures calibration *and* discrimination | Lower is better; tracked as a trend |
| **Reliability diagram** | *Where* miscalibration lives (usually the high-confidence tail) | Visual, on the quality page |

ECE requires labelled outcomes; it reports `insufficient_data` below 100 labels rather than
displaying a meaningless number. **A metric that lies when under-powered is worse than a missing
metric.**

When ECE exceeds 0.10, the response is **recalibration, not reweighting**: fit a monotonic mapping
(isotonic regression) from raw score to observed rate. This preserves ranking — the order of leads
is unchanged — while making the numbers mean what they say.

**Re-confirmed unchanged by the 2026-07-30 review** ([02c §10](02c-research-final-review.md)). ECE
with 10 bins, Brier, isotonic correction at display time, and an `insufficient_data` floor is what
the calibration research recommends; nothing about the design needed revision.

**⏸ Deferred: segmented calibration** (per intent category, or per subreddit tier). Justified only
above **~500 total labels and ≥200 within a segment** — below that, segmenting fits noise and
produces per-segment curves that swing on a handful of outcomes. The thresholds are named here so
the decision is checkable rather than perpetual.

One caution for whoever implements it: segmenting **fragments the ECE denominator**. The global ECE
and the per-segment ECEs will not reconcile — they are computed over different populations with
different bin populations — and someone will eventually try to add them up. Display them as separate
figures, never in the same column.

### 4.3 Efficiency

| Metric | Target | Alerts |
|---|---|---|
| Cache hit ratio (`prompt_cache_hit_tokens / total input`) | > 60% steady state | < 30% for 24 h → prefix instability |
| AI calls per 1,000 collected | ~24 | > 2× budget |
| Tokens in / out per call | Stable | Drift signals prompt bloat |
| Cost per run / day / month | Under caps | 80% of cap |
| P50 / P95 enrichment latency | P95 < 90 s per batch | 3× baseline |
| Local pipeline throughput | > 500 items/s | — |

### 4.4 Drift — "has something changed underneath us?"

The hardest category, because nothing announces itself. Drift can come from the provider (a silent
model update), the corpus (Reddit vocabulary shifts), or us (a prompt edit).

| Signal | Method | Why it works |
|---|---|---|
| **Golden-set regression** | 100 hand-labelled items re-run on every prompt or model change | The only *direct* measurement. Everything else is inference. |
| **Score distribution shift** | Population Stability Index on the score histogram vs a 30-day baseline | PSI > 0.2 = significant shift; needs no labels |
| **Category prior shift** | Distribution of `buying_intent` categories over time | Cheap; catches model behaviour change quickly |
| **Refusal / repair rate** | Frequency of the repair ladder firing | Rises sharply on provider-side changes |
| **Hallucinated span rate** | §2.1 | Direct grounding measure |
| **Cache hit collapse** | §4.3 | Often the *first* sign the provider changed something |

**The golden set is the anchor.** 100 items, hand-labelled once, re-run **on every prompt or model
version change and whenever an unlabelled drift signal fires** — *not* on every scrape run. At B=8
that is 13 calls, roughly **$0.014 per execution**, perhaps twice a month. Everything else in this
table is an unlabelled *trigger* for running it.

---

## 5. When these run

| Cadence | What |
|---|---|
| **Per call** | Tokens, cost, cache hit, latency, repair, span validation |
| **Per run** | Funnel counts, gate miss rate, `worst_reason`, score distribution, admission method |
| **On prompt/model change** | Golden-set regression — **blocking**; a prompt version does not ship if F1 drops > 0.02 |
| **Nightly** | PSI, category priors, cache trend, cost rollup |
| **Weekly** | ECE, Brier, reliability diagram, precision from accumulated labels |
| **On demand** | Full audit report |

Nightly and weekly jobs are **pure SQL over `ai_calls`, `leads`, `lead_labels`, and `gate_audits`.
Zero API cost.** The only paid measurements in the entire suite are the 2% holdout and the golden set.

---

## 6. The quality dashboard

One page, `/health/quality`, four bands matching §4:

```
ACCURACY (last 30 days, 214 labels)
  Precision @70   0.81  ▲.03      False positive rate  0.19
  Gate miss rate  3.1%  ✓         Worst reason  negative_term (7 of 22)

CALIBRATION
  ECE  0.07 ✓      Brier  0.14      [reliability diagram]
  High-confidence band 90–100 observed 0.84 — slightly overconfident

EFFICIENCY (last 7 days)
  Cache hit 68% ✓   Calls/1k 23   Cost/run $0.027   P95 78s   Month $1.84 / $5.00

DRIFT
  Golden set F1 0.87 (v4, unchanged)   PSI 0.08 ✓   Repair rate 1.2%
  Hallucinated spans 0.4%              Last golden run 2d ago
```

Every number links to the query that produced it. **A quality metric an operator cannot drill into
is a number they will eventually stop believing.**

---

## 7. What happens when a metric goes red

Stated in advance, because deciding under pressure is how quality regressions get rationalised away.

| Condition | Response |
|---|---|
| Gate miss rate > 10% | Warn prominently; suggest widening; log to run history ([06f §5](06f-adaptive-budget.md)) |
| Precision @70 < 0.60 | Golden-set run; review the top score weights; consider raising the display threshold |
| ECE > 0.10 with ≥ 200 labels | Fit isotonic recalibration; **do not reweight** — that changes ranking, recalibration does not |
| PSI > 0.2 | Trigger golden set; check provider status; diff recent prompt versions |
| Golden F1 drops > 0.02 | **Block the prompt version.** Roll back. Non-negotiable. |
| Cache hit < 30% for 24 h | Audit prefix stability — something upstream is mutating the frozen prefix |
| Hallucinated spans > 2% | Roll back the prompt; grounding has degraded |

---

## 8. Why this is the right amount of measurement

An internal platform can afford instrumentation a $29/mo product cannot, but "measure everything" is
not a design — it is how dashboards become wallpaper.

The suite is bounded by one test: **would a red value change what we do?** Each metric in §7 maps to
a specific action. Metrics considered and rejected for having no such mapping: per-subreddit
precision (too sparse to be significant), inter-annotator agreement (single operator), token-level
attribution (no action attached), embedding-drift monitoring on the BKB (the BKB is versioned; drift
would be an artefact of our own edits, and we already know when we edit).

The economics, derived from [06f §4](06f-adaptive-budget.md) rather than asserted:

| Measurement | Cadence | Cost | Share of AI spend |
|---|---|---|---:|
| Holdout audit | Every run | 1 call, ~$0.001 | **4.3%** of the canonical 1,000-post run |
| Golden-set regression | Per prompt/model change (~2×/month) | 13 calls, ~$0.014 | ~1% amortised |
| Everything else in §4 | Continuous | SQL over existing tables | **0%** |
| | | | **≈ 4–5%** |

Roughly **one twentieth of AI spend goes to measuring whether the other nineteen twentieths are
working.** For a system whose entire cost argument rests on *not* calling the model, that is the
minimum responsible ratio — and it is what separates a cost optimisation from an undetected quality
regression.
