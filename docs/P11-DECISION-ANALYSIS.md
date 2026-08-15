# P11 — Decision Analysis

**Phase:** P11 ([34 §P11](34-implementation-plan.md)) · **Written:** 2026-08-15

> Four decisions the specification did not settle, each recorded with what was measured, what was
> rejected, and why. The reconciliations they produced are in
> [freeze §11.1](ARCHITECTURE_FREEZE.md); this is the reasoning behind them.
>
> **None is a [freeze §11](ARCHITECTURE_FREEZE.md) amendment.** No technology, table, decision or
> dependency changes, and P11 ships no migration — `alembic heads` is `0006_content_and_dedup` for
> the fourth phase running.

---

## D1 — Six components ship; three are declared absent

**The question.** [06c §3.1](06c-local-first-pipeline.md) specifies a **nine**-component pre-score.
Three of them read `project.*`:

```python
"pain_phrase":   phrase_overlap(item.text, project.pain_phrases),
"competitor":    1.0 if competitor_mentions(item.text, project) else 0.0,
"subreddit_fit": project.subreddit_fit(item.subreddit),
```

`projects`, `pain_points` and `bkb_entities` arrive in revision **`0007`**, which is
[§P12](34-implementation-plan.md)'s — **and P12 depends on P11.** The entity registry behind
competitor matching is **P15**'s, and
`tests/test_boundaries.py::test_the_competitor_registry_was_not_wired_before_p15` fails if it is
wired early. So three of nine cannot be computed at this revision, by construction.

**The options.**

| | Ship all nine, three at `0.0` | **Ship six, declare three absent** ▶ | Stop for a freeze decision |
|---|---|---|---|
| Fidelity to 06c §3.1 | Literal | The six that can be computed | — |
| What a reader sees | `subreddit_fit: 0.0` | `subreddit_fit: "P12 — projects arrives in 0007"` | — |
| Score magnitude | Depressed on **every** item by the three absent weights | Correct against the components that exist | — |
| P12's job | Change three zeroes to values, and re-tune | Add three weights; the normaliser adjusts | — |

**Decision: six ship, three are declared absent, each naming its owning phase.**

**The reason is DI24, and it is not an analogy.**
[DI24](DEFERRED-IMPROVEMENTS.md) is *"P6's keyword matching has never matched a keyword"* — a score
component that was always `0.0`, for months, on live data, and *"nothing downstream noticed"*.
**P11 is the phase that fixes DI24.** Shipping three components that silently contribute zero would
reproduce that exact failure inside the phase whose job is ending it, and the register entry would
have to be re-opened against P11's own code.

The precedents are explicit and recent: P6 shipped **no** `density_threshold` key because *"a key
nothing reads is a documented capability that does not exist"*, and P10 shipped tier 3 **off**
because *"a default that lies about what runs is worse than one that does not."*

**What ships.** `src/scoring/ABSENT_COMPONENTS` names all three with the phase that supplies each,
`python -m src.scoring` prints them, and the absences are persisted into
`prescores.components_json` under `_absent` — so a P12 reader can tell *"did not exist yet"* from
*"scored 0.0"* at a point when the components **do** exist and the distinction is no longer obvious.

---

## D2 — The weights are cited from 04 §9.1, not invented

**The question.** [06c §3.1](06c-local-first-pipeline.md) ends:

```python
return PreScore(total=100 * sum(W[k] * v for k, v in c.items()), components=c)
```

**`W` is never given.** Grepped across every document in `docs/` on 2026-08-15 — no frozen document
supplies the pre-score weights, and the 0–100 bound
[34 §P11](34-implementation-plan.md) asserts depends on them.

**The options.** Equal weights (`1/N` each); weights derived from a frozen document; operator-supplied.

**Decision: derive from [04 §9.1](04-system-design.md)'s non-AI classes.**

This is the discipline P9 and P10 both applied. P9 took `min_chars: 80` from
[06b](06b-deepseek-optimization.md) rather than picking a number, recording that *"the value is
cited rather than invented"*. P10 took `shingle_k`, `num_perm` and `jaccard_threshold` from
06c §4.2's literal constants. Equal weights would have been defensible as a deliberate non-choice,
but 04 §9.1 **does** contain relative weights for three of the six shipped components, and
discarding real information in favour of `1/6` is not neutrality.

**The derivation, in full, so it can be checked rather than trusted.** 04 §9.1's four non-AI weights
are `keyword 0.10`, `recency 0.07`, `engagement 0.05`, `subreddit 0.03`.

| Pre-score component | Weight | Where it comes from |
|---|---:|---|
| `keyword_tier` | 0.05 | 04's `keyword` **0.10**, split evenly across the two keyword components 04 does not distinguish |
| `keyword_density` | 0.05 | as above |
| `recency` | 0.07 | 04's `recency`, transferred directly |
| `engagement` | 0.05 | 04's `engagement`, transferred directly |
| `question_form` | 0.03 | 04's `subreddit` **magnitude** — its "weak but non-zero" value — reused for a component 04 has no analogue for |
| `length` | 0.03 | as above |

04's `subreddit 0.03` does **not** transfer as itself: `subreddit_fit` is one of D1's three absent
components.

**The raw values are stored and normalised by their own sum at call time**, rather than pre-divided
into constants. Three consequences, and the third is the reason:

1. The arithmetic is **exact** — pre-rounded to four places these sum to 1.01, not 1.00.
2. The cited numbers stay legible and traceable to 04 §9.1 in the source.
3. **When P12 and P15 supply the three absent components, their weights slot in and the normaliser
   adjusts — without re-tuning the six that shipped.** A phase that had to re-derive six constants
   to add three would be far more likely to change behaviour it did not intend to.

**Where a different answer would be accepted:** once `lead_labels` exists (revision `0010`, P25) the
weights should be **fitted**, not argued about. These are a starting point with a citation, not a
finding.

---

## D3 — The holdout sample is persisted as `source='holdout_audit'` leads

**The question.** [34 §P11](34-implementation-plan.md)'s first acceptance line is *"every collected
item has a `prescores` row, **admitted or not**"*. But `prescores` carries

```sql
CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))
```

so every row must point at a **stored** `Lead` — and a metadata-triage rejection is by definition a
post that was never stored. **P6 filed this exact wall** and recorded that the two ways out
*"need a schema amendment for capability P11 owns"*. P11's **DB** row is `None`, and
[freeze §4.1](ARCHITECTURE_FREEZE.md) fixes the chain at ten revisions.

**Decision: the 2% holdout sample is stored as real leads with `leads.source='holdout_audit'`, and
that is what makes its `prescores` row possible.**

**This was already required, for an independent reason.**
[06c §6.1](06c-local-first-pipeline.md) is unambiguous:

> *"Audited items are persisted as real, labellable leads … This is not a convenience — it is what
> stops the learning loop degenerating. … Storing only the aggregate counts — as the original design
> did — produced a metric with no learning signal."*

P19's yield curve can only be fitted on leads an operator can see and label. So the storage is not a
workaround for the CHECK; the CHECK and 06c §6.1 want the same thing, and satisfying one satisfies
the other. `leads.source` has existed since `0006` and carries no CHECK constraint on its values.

**What was rejected.** Storing every triage reject (changes what `leads` means to the operator — the
same objection P6 recorded); relaxing the CHECK and adding a `reddit_id` column (a schema amendment
with no failed measurement behind it); counters only (loses 06c §6.1's exploration channel, which is
the half that stops the loop degenerating).

**The line holds in full for stage 4:** every item the run *collected* gets a `prescores` row,
admitted or not. The ~98% of triage rejects that were never collected stay as `run_events` counters,
in the shape P6 shipped.

### D3a — and no body is fetched

Task 6 says *"2% of metadata-triage rejects get **bodies fetched** and full-scored"*. **They are
already in hand.** P5 measured that the feed carries the body for ~97% of posts **in the request
stage 1 already makes** ([freeze §11.1](ARCHITECTURE_FREEZE.md), 2026-08-08) — which is why stage 4
was reduced to body *accounting* in P6. A permalink fetch per sampled reject would spend one request
each to re-collect what the feed already gave us. **The audit costs no extra request.**

### D3b — and no AI, which is not a compromise

*"Would have qualified"* cannot mean *"the model marked `is_lead`"*, because
[34 §P11](34-implementation-plan.md) requires `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` to be
**0**. It means **the full-stage deterministic gate admits what the metadata gate rejected** — which
is precisely the disagreement worth measuring at a stage whose entire premise is deciding *without a
body*. The AI-judged variant needs `gate_audits` (revision `0009`) and is P19/P20's.

**It works.** The first thing the audit caught was [DI25](DEFERRED-IMPROVEMENTS.md).

---

## D4 — "N distinct pre-scores" is met as a property, not as a count

**The measurement.** On a read-only copy of `data/leads.db` (492 leads), 2026-08-15: of **23**
groups the cascade forms, **two** yield fewer distinct totals than they have members.

| Group | Members | Distinct totals | Why |
|---|---:|---:|---|
| leads 108 / 109 | 2 | **1** — both `32.28` | Identical text, both 0 upvotes and 0 comments, created **one minute apart** |
| leads 331 / 403 / 404 | 3 | **2** — 403 and 404 both `47.61` | Identical text and engagement, created **three minutes apart** |

A 60-second age difference moves the `recency` component by roughly **0.003%**, which is below the
second decimal place the total is rounded to.

**Decision: the criterion ships as the property that carries its meaning — *N members, N
independently computed scores, and any difference in a scored input produces a different number*.**

[06c §4.4](06c-local-first-pipeline.md) asks for **"group for analysis, score individually"** — that
each member gets its **own** score from its **own** metadata, so that *"three threads with different
authors, subreddits and recency"* do not collapse to one number. Two posts identical in every scored
dimension producing identical scores is **that rule working**. It is determinism, which is the
property the whole local-first argument rests on.

**What was rejected: increasing the stored precision** until sub-minute age differences separate the
totals. That games a criterion rather than measuring a lead — a pre-score is a ranking instrument,
and two decimals are already finer than the ordering needs.

**The consequence is bounded and handled.** When two members tie, representative selection stays
deterministic through P10's trailing `row_id` tie-break, so two identical runs enrich the same
member. `test_two_members_identical_in_every_scored_dimension_share_a_pre_score` pins both halves.

**This is the same species as P10's collapse-rate reconciliation** — a criterion written before the
data was seen, measured, and read as the thing it was always about.

---

## A2 — measured, and both numbers published

Not a decision, but the phase's headline measurement, and it needs its context stated rather than a
single number quoted.

[27 §10](27-architecture-review.md) assumes **A2: hard filters remove ~73% of collected**, marked
*"❓ Sprint 3, on real data"*. [34 §P11](34-implementation-plan.md) asks for it to be *"measured —
real hard-filter rate **recorded** against the assumed 73%"*.

| Population | Items | Hard-filter rate | Admitted |
|---|---:|---:|---:|
| The whole archive | 492 | **75.4%** | 22.8% |
| In-window only | 153 | **20.9%** | 73.2% |

**Both are published, and neither alone is honest.** The archive spans **29 months** against a
30-day window, so `out_of_window` alone accounts for **68.9 points** of the first number — it is
measuring the calendar. The second removes that, and is much lower than 73%.

**The gap is structural, and it is the same shape as P10's collapse metric.**
[06c §8](06c-local-first-pipeline.md)'s worked example reaches 73% by counting things P11 cannot
produce:

- **`already_analyzed`** — 312 of its 1,200 items, **26%**. Needs the response cache: P19/P20's.
- **`negative_term`** — 186 items, **15.5%**, its single largest hard filter. `discovery.negative_terms`
  ships **empty**, so there is nothing to match. It is operator vocabulary, not a structural rate.
- **`duplicate_exact` / `duplicate_near`** — counted separately by P11 as `grouped`, because
  [06c §8](06c-local-first-pipeline.md) itself insists grouping *"does not discard"* those items.

**The criterion is met** — it asks for the rate to be *measured and recorded*, and it is, against the
assumption, with the reason for the gap stated. **No threshold was tuned toward it**, on P10's
precedent for the collapse metric: tuning a filter to reach an assumed number would replace a
measurement with a target.

The intra-run figure that can be compared to 06c §8 directly arrives with the response cache and an
operator negative vocabulary.

---

## What P11 deliberately did not do

| | Why |
|---|---|
| Add `leads.run_id` | The direct fix for the time-window scoping in `_collected_leads`, and it needs a migration. P11's **DB** row is `None`, freeze §4.1 fixes the chain at ten revisions, and there is **no failed measurement** — the window is exact under the one-active-run constraint. Registered as [DI28](DEFERRED-IMPROVEMENTS.md) for the next phase that opens a revision |
| Fix [DI26](DEFERRED-IMPROVEMENTS.md) | `keywords.normalise` tearing decomposed Unicode apart. Its trigger names *"P11 or P15"*, and the four DIs P11 **did** build were each required transitively by one of its own tasks. This one is not: NFKC changes matching for every existing term and wants its own before/after measurement, which is what its entry says |
| Build the adaptive admission cut | [06f](06f-adaptive-budget.md)'s knee/floor/clamp is **P19's** and needs `ai_budgets` (`0009`). P11 uses 06c §3.3's documented **fallback** and reports the method rather than substituting it silently |
| Converge the two rejection **writers** | DI23 is reconciled for **display**. Converging the writers changes P6's shipped behaviour on a live path, which is what the entry says must not happen in passing |
| Add a timing assertion | [35 §2.2](35-testing-strategy.md) lists P11 under Performance, but its pass condition is *"named budget in the phase's **Metrics row**"* and P11's Metrics row names **no clock** — its performance claim is a request count. Adding one would import P10's T3 for nothing |
| Tune `jaccard_threshold` | [PHASE-10-HANDOVER §4 T1](PHASE-10-HANDOVER.md) measured the collapse rate **flat from 0.85 down to 0.60**. P11 measured **5.69%** on the same archive against P10's 5.74% — the 0.05 difference is the four leads collected since. Loosening finds nothing, and the handover says so explicitly |
