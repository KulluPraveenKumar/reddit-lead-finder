# 06i — Feedback, Progressive Enrichment, Memory & Provenance

> How operator judgement improves the system without training a model, how enrichment escalates,
> what the database remembers versus discards, and how a decision made today stays reconstructible
> in three years. Decisions and research basis in [02c §0, §4, §8, §9, §11](02c-research-final-review.md).

---

## 1. The correctness fix this document exists for

**As designed, the learning loop would degenerate.** This is the defect the final research pass
found, and it is worth stating precisely before anything else, because everything in §2 is shaped
around it.

The adaptive budget's `YieldCurve` ([06f §2.3](06f-adaptive-budget.md)) is fitted from
`(prescore, is_lead)` pairs drawn from `lead_labels`. Labels exist only for leads the operator sees.
The operator sees only leads that were **admitted** to AI. Therefore:

```
gate admits the top region
        ↓
only the top region gets labelled
        ↓
yield curve is fitted on the top region only
        ↓
curve says the top region is where the leads are
        ↓
gate narrows
        ↓  … and repeats
```

The curve would learn the shape of its own output. Nothing in the design would notice: precision,
measured only on admitted leads, would look stable or improve while recall quietly collapsed.

This is a **degenerate feedback loop** — the failure mode where a model's output determines the data
it next learns from. The literature's named mitigations are exploration, exposure-aware modelling,
and candidate-pool growth ([02c §0](02c-research-final-review.md)).

**We already built the exploration channel and then threw away its output.** The holdout audit
enriches 2% of *rejected* candidates — random exploration of exactly the un-admitted region the
mitigation calls for. But `gate_audits` stores only aggregate counts; the audited items never become
visible leads, so they are never labelled, so they contribute nothing.

The fix is in §2.3. It costs a flag column and a badge.

---

## 2. Human feedback

### 2.1 What feedback is, and what it is not

**Adopted:** operator labels adjust *ranking weights*, *confidence calibration*, and *knowledge
suggestions*.
**Rejected:** a learned ranker, online training, propensity-weighted learning-to-rank.

The rejection is arithmetic, not taste. The yield curve does not activate below 200 labels. An
internal team labelling on the order of tens of leads a week reaches 200 in **months**. A learned
ranking model needs at least an order of magnitude more than that before it beats hand-set weights,
and propensity-weighted LTR additionally assumes repeated queries we do not have.

> We would be fitting a model on a few hundred points to replace eleven interpretable weights —
> trading away the explainability the whole platform is built around, for a near-certain overfit.

This stays true even if usage grows tenfold. Deterministic weights an operator can see and adjust,
plus isotonic calibration, is the correct ceiling for this data volume.

### 2.2 Labels carry reasons

```
label:   interested | contacted | converted | not_relevant | duplicate_of
reason:  (when not_relevant)
         wrong_persona | wrong_pain | wrong_icp | not_a_buyer |
         competitor_staff | too_old | already_engaged | other
```

**Reasons are worth more than the label.** An undifferentiated rejection only lowers a number; a
rejection that says `wrong_persona` five times about the same persona is evidence the **persona
definition** is wrong — a knowledge problem, not a scoring problem, routed to
[06h §4](06h-knowledge-lifecycle.md) rather than to the scorer.

| Reason recurs | Interpretation | Route |
|---|---|---|
| `wrong_persona` | Persona too broad or mis-specified | Flag persona for review |
| `wrong_pain` | Pain phrasing over-matching | Flag phrasing for review |
| `not_a_buyer` | Intent signals too permissive | Signal-weight review |
| `competitor_staff` | Missing negative signal | Propose `negative_signals` addition |
| `too_old` | Recency weight too low | Weight review |

Each is a **proposal to the operator**, never an automatic adjustment. A feedback system that
silently retunes itself is one nobody can debug six months later.

### 2.3 The exploration channel — closing the loop

**Holdout-audited items become real, labellable leads.**

```
leads.source:  scrape | holdout_audit
```

| Requirement | Why |
|---|---|
| Audited items are persisted as leads, flagged `holdout_audit` | Otherwise there is nothing to label |
| They appear in the lead list with a visible badge | The operator should know this one came from the audit |
| Their labels feed the yield curve **on equal footing** | This is the entire point — it is the only signal from below the cut |
| `YieldCurve` fitting must **not** filter to admitted leads | Filtering would restore the degeneracy |
| Sampling stays deterministic (hash-based) and unbiased by score | Random exploration must be *random*; biased sampling is not exploration |

The audit keeps its measurement role — the gate miss rate is unchanged — and gains a learning role
it was always structurally capable of performing.

**One consequence worth naming:** the yield curve will be fitted on a sample that is
*deliberately* not representative — dense above the cut, sparse below it. That is the correct shape
for the question being asked (*"how does yield fall as pre-score falls?"*), but the sparse region
carries wide uncertainty. The curve is therefore fitted with monotonicity enforced, and the
marginal-value cutoff it feeds is bounded by the clamps that already exist
([06f §2.4](06f-adaptive-budget.md)) — so a badly-fitted tail cannot produce an absurd budget.

### 2.4 Where feedback lands

| Signal | Consumer | Effect |
|---|---|---|
| `interested` / `not_relevant` on scored leads | Precision, FP rate | Reported on `/health/quality` |
| Labels across the score range | ECE, Brier, isotonic map | Recalibrates *meaning*, never ranking ([06g §4.2](06g-explainability-and-quality.md)) |
| `(prescore, is_lead)` incl. audit leads | `YieldCurve` | Marginal-value cutoff in the adaptive budget |
| Recurring reasons | Knowledge suggestions | [06h §4](06h-knowledge-lifecycle.md) |
| Nothing | Model weights | **No training. Ever.** |

---

## 3. Progressive enrichment — a second AI tier

### 3.1 The cascade already exists

Hard filters → pre-score → adaptive gate → batched enrichment is a textbook LLM cascade, and the
research confirms the existing architecture rather than changing it: production systems *"try the
cheapest routing method first and escalate only when the cheap method cannot decide confidently,"*
with reported cost reductions up to 90% ([02c §8](02c-research-final-review.md)).

### 3.2 The gap: the best leads get the weakest analysis

After the gate, enrichment is **uniform** — every admitted item gets the same B=8 batched treatment.
But our own research established that **batching measurably degrades per-item quality through
attention dilution** ([02 §6.8](02-research-findings.md)); it is why B is a measured ceiling rather
than a guess.

So the highest-value leads currently receive the *lowest* per-item quality the pipeline offers. That
is backwards, and it is a quality argument, not a cost one.

### 3.3 Two tiers

| | Tier 1 | Tier 2 |
|---|---|---|
| Applies to | All admitted items | Top slice only |
| Batching | B=8 | **Un-batched, one item per call** |
| Context | Frozen matching prefix (~3.5k) | Prefix **+ retrieval-only BKB sections** |
| Output | Classification, slugs, evidence spans | Adds objection analysis, outreach angle, competitive framing |
| Trigger | The adaptive gate | `confidence ≥ 80` **or** operator request |
| Budget | The run budget | **Separate cap**, `max_tier2_items_per_run: 25` |
| Storage | `lead_analysis` row, `tier=1` | **A second row**, `tier=2` — never an update |

Tier 2 is cheap precisely because it is rare. On a typical 1,000-post run the qualifying slice is
tens of items, so un-batched treatment costs **~$0.01** — and those are the leads a human will
actually act on.

```
Estimated tier 2:  18 leads ≥ 80 · un-batched · ~$0.008 · cap 25
```

**Tier 2 writes a second `lead_analysis` row rather than updating the first.** `tier` is therefore
part of the partial unique index ([05 §5.4a](05-database-plan.md)), which is the one place this
feature touches an existing constraint. Updating in place would mean a Tier 2 failure had already
destroyed the Tier 1 analysis it is required to preserve — so the additive guarantee in §3.4 is a
property of the schema, not of careful error handling. The lead detail reads `tier=2` when present
and falls back to `tier=1`; rolling Tier 2 back is a `DELETE`.

### 3.4 Guards

- **Tier 2 never changes the confidence score.** It enriches presentation. If it altered the score,
  the score would depend on which tier ran, and two leads with identical evidence could rank
  differently — destroying comparability.
- **Tier 2 is capped independently**, so a run with an unusually strong distribution cannot escalate
  hundreds of items.
- **Tier 2 failure is soft.** The lead keeps its Tier 1 analysis and shows it; the richer view is an
  addition, never a dependency.
- **Tier 2 output is cached on `(content_hash, prompt_version)`** like everything else, so a re-run
  is free.

---

## 4. Memory architecture

### 4.1 Four classes, one file

**Rejected: separate databases, separate services, event sourcing.** Nothing at our scale justifies
a second datastore, and each one adds a backup story, a consistency problem, and a failure mode.

The valuable part of the idea is not physical separation but **stated lifetimes**, which prevent the
slow drift where an operational table quietly becomes load-bearing for scoring.

| Class | Tables | Lifetime | If lost |
|---|---|---|---|
| **Durable knowledge** | `bkb*`, `personas`, `pain_points`, `intent_signals`, `calibration_maps` | Never auto-purged; backed up | Catastrophic — this is the asset |
| **Evidence** | `leads`, `comments`, `lead_analysis`, `bkb_evidence`, `lead_labels`, `prescores` | Never auto-purged | Severe — calibration and patterns lose their substrate |
| **Operational** | `runs`, `jobs`, `run_events`, `ai_calls`, `ai_budgets`, `gate_audits`, `metrics`, `patterns` | Retention schedule, **after** aggregation | Tolerable — history of *how*, not *what* |
| **Disposable cache** | `ai_cache`, `http_cache` | Deletable at any moment | **Nothing.** Costs money to rebuild, changes no result |

**`patterns` is operational, not durable, despite feeding durable knowledge.** It is a *rebuildable
projection* — dropping it and recomputing from `lead_analysis` loses nothing. Classifying it as
durable would be classifying by importance rather than by lifetime, and the classes here are about
lifetime. What it produces — an accepted suggestion written into the BKB — *is* durable.

### 4.2 The rule that makes it enforceable

> **Deleting every row in the disposable class must not change any lead's score.**

One acceptance criterion, asserted in the test suite: snapshot all scores, `DELETE FROM ai_cache`,
`DELETE FROM http_cache`, re-score, compare. This prevents cache from ever becoming state — which is
exactly how caches turn into undocumented databases nobody dares clear.

A parallel rule for the operational class: **purge only after aggregation.** `ai_calls` rows are
rolled into monthly cost totals before deletion, so purging loses granularity, never a number
anyone is looking at.

### 4.3 Why one SQLite file remains right

| Property | Consequence |
|---|---|
| Backup is a file copy | The whole system state, atomically, in one operation |
| No cross-store consistency problem | A lead and its analysis cannot disagree about which run produced them |
| No second process | Nothing to deploy, monitor, or fail independently |
| Migrations are one linear chain | One head, one `alembic upgrade` |

The classes are enforced by naming, documentation, and retention policy — not by physical
separation. **Separation of concerns does not require separation of storage**, and conflating the two
is how single-operator tools acquire distributed-systems problems.

---

## 5. Decision provenance

### 5.1 What is rejected

**Event sourcing, immutable ledgers, cryptographic sealing.** These exist to satisfy auditors of
decisions with legal consequences about people. We rank Reddit threads for an internal marketing
team. The architectural cost is large and permanent; the benefit here is zero. Recorded explicitly
so it is not re-proposed later as a "best practice."

### 5.2 What is adopted — version pinning

`lead_analysis` already records `provider`, `model`, `prompt_version`, `raw_json`, `content_hash`,
and `repair_attempts`. What is missing is what the **rest of the system** looked like at the moment
of the decision:

| Column | Pins |
|---|---|
| `bkb_id` | Which knowledge-base version produced the matched slugs |
| `weights_version` | Which confidence weights were in force |
| `ruleset_version` | Which rule engine and negative vocabulary applied |

Three columns. With them, every historical decision is reconstructible:

> *"Lead 4,182 scored 78 on 12 March. Under BKB v3 it matched `attribution-gap`; weights v2 gave
> that component 22.5 points; ruleset v4's negative list did not contain 'freelance' yet."*

### 5.3 This fixes an unsatisfiable acceptance criterion

Phase-8 **AC28** asserts that a lead's entity links *"resolve to the pinned version, not a dangling
ref."* Nothing in `lead_analysis` pins a BKB today, so after one regeneration those links resolve to
*current* knowledge — silently, and while still looking correct.

That is worse than a broken link: the explanation would confidently cite a pain-point definition
that did not exist when the lead was scored. `bkb_id` makes AC28 true rather than aspirational.

### 5.4 The reproduction guarantee

> **Given the same lead, the same pinned versions, and the same cached analysis, re-running the
> scorer must produce a byte-identical breakdown.**

This holds because the score is deterministic Python over stored components
([AD-11](03-architecture.md)) and nothing in it reads the wall clock — recency is computed from
`created_utc` against the *run's* timestamp, not against `now()`. It is also why **staleness must
never alter a score** ([06h §2.2](06h-knowledge-lifecycle.md)): a clock-dependent score would break
this guarantee, and with it every historical explanation.

---

## 6. The internal-tool advantage: what to expose

Because this is an internal platform, we can show researchers material a commercial product would
hide. All of it is **already stored**, so the cost is UI, not architecture.

| Exposed | Value to a researcher |
|---|---|
| Evidence chain (Reddit → pain → BKB section → website span) | Judge a match in seconds instead of reading the thread |
| Matched ICP / persona / pain / objection / competitor / terminology | See *what* matched, not just that something did |
| Score breakdown with weights | Disagree precisely, and adjust the right dial |
| Confidence history for a lead | See whether re-analysis changed the verdict, and when |
| Pattern history for a pain or competitor | *"This objection has appeared 14 times since April"* |
| Prompt / BKB / weights versions | Explain why an old lead looks different from a new one |
| Cost and cache status per analysis | Understand what a run actually spent |

### 6.1 Curation, not a debug dump

**A panel that shows everything is worse than a curated view.** The default lead detail stays the
ten explanation fields and the score breakdown ([06g §3](06g-explainability-and-quality.md)); the
rest sits behind a **Researcher view** toggle, persisted per user.

The distinction matters because these two audiences want different things from the same row: the
default view answers *"should I act on this?"*, the researcher view answers *"why does the system
think so, and is the system right?"* Merging them produces a screen that answers neither.

---

## 7. Schema additions

**No new migration.** Everything lands in revisions already in the plan
([05 §7](05-database-plan.md)); the chain stays linear at nine with one head.

| Revision | Addition |
|---|---|
| `0007` | `leads.source` (`scrape` \| `holdout_audit`) |
| `0008` | `lead_analysis.bkb_id`, `.weights_version`, `.ruleset_version`, `.tier` |
| `0009` | `lead_labels.reason`; `patterns` ([06h §6](06h-knowledge-lifecycle.md)) |

`prompt_version` already exists on `lead_analysis` and is **not** duplicated.

Full DDL in [05 §5.4c and §5.4d](05-database-plan.md).

---

## 8. Acceptance criteria

- **Holdout-audited items appear as labellable leads** with `source='holdout_audit'` and a visible badge
- **`YieldCurve` fitting includes audit-sourced labels** — asserted by a test that fails if the fit query filters to admitted leads
- Deterministic hash sampling is uncorrelated with pre-score (asserted over a synthetic distribution)
- Label reasons are recorded and routed; recurring reasons raise knowledge proposals, never automatic adjustments
- No code path modifies score weights without an operator action
- Tier 2 runs only above threshold or on request, respects its own cap, and **never alters the confidence score**
- Tier 2 failure leaves the Tier 1 analysis intact and displayed
- **`DELETE FROM ai_cache; DELETE FROM http_cache;` changes no lead's score** (snapshot / delete / re-score / compare)
- `ai_calls` purge runs only after monthly aggregation
- Every `lead_analysis` row pins `bkb_id`, `weights_version`, `ruleset_version`
- **Phase-8 AC28 passes**: after a BKB regeneration, an old lead's entity links resolve to its pinned version
- Re-scoring a lead from stored components reproduces its breakdown byte-identically
- Researcher view is off by default and persists per user
