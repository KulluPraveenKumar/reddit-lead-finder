# Phase 11 — Handover

**From:** P11, the pre-score, the funnel and comments · **Written:** 2026-08-15
**To:** **P12**, and for the debts, **P15**, **P19** and **P21**

> Evidence lives in [PHASE-11-COMPLETION-REPORT.md](PHASE-11-COMPLETION-REPORT.md).
> Reasoning lives in [P11-DECISION-ANALYSIS.md](P11-DECISION-ANALYSIS.md).
> Where the next session resumes lives in [progress/P11-COMPLETE.md](progress/P11-COMPLETE.md).

---

## 1. What now exists

**The deterministic pipeline runs.** For three phases `src/rules/` and `src/dedupe/` sat with no
caller; P11 is the first caller of both, and the first phase where a collected item is scored,
grouped, counted and rendered end to end.

Seven modules under `src/scoring/`, a comment scraper, a comment repository, a pipeline stage, and a
funnel on the run page. **No migration** — `alembic heads` is `0006_content_and_dedup` for the fourth
phase running.

**The public surface P12 will meet:**

```python
from src.scoring import PrescoreSettings, keyword_tiers_of
from src.scoring.prescore import ScoredItem, prescore

result = prescore(ScoredItem(title=…, body=…, …), PrescoreSettings.from_config(config),
                  keyword_tiers=keyword_tiers_of(config))
# result.total 0-100 · .components (six) · .absent (three) · .decision · .reason
```

The stage runs from `handle_finalize_run`, via
`src/orchestration/handlers/prescore.py::run_prescore_stage`.

---

## 2. Guarantees P12 must not break

| | Guarantee | Enforced by |
|---|---|---|
| **G1** | **`src/scoring/` imports neither `src.ai` nor `hermes`** | `test_the_scoring_package_is_inside_the_ai_fence`, AST-based |
| **G2** | **Deleting the package fails a test rather than silencing the fence** — and the guard asserts the **package** form, because `src/scoring` was a *module* until P11 and a directory walk over the old tree scans nothing | `test_the_scoring_package_exists` |
| **G3** | **`from src.scoring import LeadScorer` keeps working** — four call sites depend on it | `test_the_legacy_lead_scorer_is_still_importable` |
| **G4** | **P9's four + P10's two + P11's two stay a strict subset of P19's eleven** | `test_p9_p10_and_p11_together_reach_eight_of_p19s_eleven` |
| **G5** | **Every item the run collects gets a `prescores` row, admitted or not** | `test_every_collected_item_gets_a_prescores_row_admitted_or_not` |
| **G6** | **Grouping mutates no per-item score** — P10's G6, now upheld across the boundary | `test_a_group_of_n_yields_n_distinct_prescores` |
| **G7** | **`SELECT COUNT(*) FROM ai_calls WHERE run_id=?` = 0** through the whole deterministic pipeline | `test_the_stage_makes_no_ai_call` |
| **G8** | **An unknown `score`/`num_comments` persists as NULL, and a measured zero as 0** | `test_an_unknown_score_persists_as_null`, `test_a_known_zero_persists_as_zero` |
| **G9** | **Re-running the stage or the comment fetch writes nothing twice** | `test_re_running_the_stage_writes_no_second_row`, `test_re_running_comment_extraction_creates_zero_duplicates` |
| **G10** | The 459 original leads and the `intent_score` fingerprint | `check_schema.py` 51/51, unchanged by P11 |
| **G11** | One head, always — and P11 added no revision | `test_single_head` |

---

## 3. ⚠️ What P12 inherits directly

**P12 creates revision `0007`, and three of P11's loose ends are waiting in it.**

1. **The three absent pre-score components are yours to fill — two of them.**
   `src/scoring/ABSENT_COMPONENTS` names `pain_phrase` and `subreddit_fit` as **P12's** and
   `competitor` as **P15's**. `0007` creates `projects`, `pain_points` and `bkb_entities`, which is
   what they need. **Add the weight to `WEIGHTS` and the component to `prescore()`; do not re-tune
   the six that shipped** — the weights are normalised by their own sum at call time precisely so
   that adding a term does not require touching the others. Delete the entry from
   `ABSENT_COMPONENTS` in the same change, or `prescores.components_json` will keep claiming a
   component is absent while it is being scored.

2. **[DI28](DEFERRED-IMPROVEMENTS.md) is yours to consider, and `0007` is the cheap moment.**
   `leads` has no `run_id`, so `_collected_leads` selects `Lead.scraped_at >= run.started_at`. That
   is **exact today** under the one-active-run constraint, so there is **no failed measurement** and
   it is not an amendment — but every quantity the funnel publishes rests on it, and `0007` already
   runs `batch_alter_table` over four deferred FKs. One more column there costs a line; a revision
   of its own costs an amendment.

3. **`test_tier_three_off_is_the_shipped_default` becomes live for you.**
   [PHASE-10-HANDOVER §6](PHASE-10-HANDOVER.md) records it: when `0007` creates the vector tables,
   `src/dedupe/semantic.py`'s in-memory comparison is the thing to revisit, and cross-tier extension
   under complete linkage is rare **by construction**. P11 changed nothing there and the tier is
   still off; the note is unchanged and still P12's.

---

## 4. Traps waiting in P12

**T1 — 🔴 a component that scores 0.0 is indistinguishable from one that does not exist, and P11
built the machinery to tell them apart specifically so you would not have to guess.**
`prescores.components_json` carries `_absent` naming each missing component **and the phase that
supplies it**. When you add `pain_phrase`, rows written before `0007` will carry
`_absent: {"pain_phrase": "P12 …"}` and rows after will carry a value. **Both readings are correct
for their row and neither is correct for the other** — any query that aggregates a component across
runs spanning `0007` must filter on `_absent`, or it will average a real distribution against a
population that had no such component. This is [DI24](DEFERRED-IMPROVEMENTS.md)'s lesson at the
scale of a schema change.

**T2 — 🔴 the weights are cited, not fitted, and adding a component changes every score.**
The six weights come from [04 §9.1](04-system-design.md) by the derivation in
[P11-DECISION-ANALYSIS §D2](P11-DECISION-ANALYSIS.md). They are normalised by their **own sum**, so
adding a seventh with weight `w` **reduces every existing component's share** by `w / (Σ + w)` —
every stored `total` from before your change is on a different scale from every one after. That is
correct and unavoidable, but it means **`prescores.total` is not comparable across a weight
change**, and the admission floor of 35 was chosen against the six-component distribution
(median **41.27**, p25 **35.09** on 492 real leads). **Re-measure the distribution before assuming
35 still cuts where you think it does.** `scripts/`-free: the measurement is 20 lines against a
read-only copy, and the numbers to beat are in [§7](#7-verification-snapshot-at-handover).

**T3 — the pre-score and `intent_score` are different numbers and will be confused.**
`leads.intent_score` is the **legacy** keyword score, pinned by R20 and produced by
`src/scoring/legacy.py`. `prescores.total` is P11's 0–100. They share a package and neither is
derived from the other. A UI that shows "score" without saying which will be misread; P21 owns the
lead detail page and inherits that.

**T4 — the funnel's two stages are counted separately, and summing them is wrong.**
`metadata` (P6's triage, deciding on a **title**) and `full` (P11's, deciding with a **body**) are
facts about different populations. `FunnelReport` keeps them apart deliberately: a combined
"rejected" total would let a triage regression hide inside a full-stage improvement.

**T5 — A2's two numbers are both real and neither is "the" answer.**
**75.4%** across the archive, **20.9%** in-window. The first is dominated by `out_of_window` on a
29-month corpus; the second removes that and is far below the assumed 73%. The gap is structural —
[06c §8](06c-local-first-pipeline.md)'s 73% counts `already_analyzed` (**26%** of its example, and
P19/P20's response cache) and `negative_term` (its largest single filter, and
`discovery.negative_terms` ships **empty**). **Do not tune a filter toward 73%**; the comparable
figure arrives with the cache and an operator vocabulary.

**T6 — the holdout's miss rate is `not measured` more often than you would expect, and that is
correct.** At a 2% rate a run must reject ~50 posts before it samples one. `MissRate.measured` is
false at zero samples and the page renders the words rather than `0.0%` — **a run that sampled
nothing has not demonstrated a miss rate below 5%, it has demonstrated nothing.** Any later
aggregation must sum `sampled` and `would_have_qualified` across runs, never average the rates.

**T7 — `python -m src.scoring "a title"` with no `--body` reports `too_short`, and it is right.**
`rules.min_chars: 80` measures a **body**, and P11 is the first phase to bind it to one. It has its
own step in the manual guide because a tester will otherwise read it as a defect.

**T8 — the comment stage commits before it fetches, and the row can vanish underneath it.**
Never hold SQLite's single write lock across a network call — the defect that returned HTTP 500 when
a run was cancelled mid-scrape in P3, named as trap T0 in three handovers. `_backfill` therefore
tolerates a `Lead` that has been deleted since planning; a crash there would lose every remaining
candidate's comments.

**T9 — `get_post_detail` is an eighth public method on `RedditClient`, and the six frozen ones are
still frozen.** Additive under AD-2, the precedent `get_feed` set in P5.
`test_the_six_frozen_methods_are_untouched` holds the originals. `get_post_comments` was left
**byte-identical** rather than widened, because four callers and a signature test depend on its list
return shape.

**T10 — two mutations survive by design, and both are documented equivalents.**
`_clamp`'s NaN guard is redundant **purely because of its argument order** (`max(0.0, nan)` is
`0.0`; `max(nan, 0.0)` is `nan`), and `length_plausibility`'s floor check is redundant with the
clamp. Both **stay**, and both have a test pinning the property that makes them redundant, so a
"simplification" fails rather than silently making one load-bearing again.

---

## 5. Debts carried forward, by owner

| | Item | Owner |
|---|---|---|
| **DI28** | **New.** `leads` has no `run_id`; the stage scopes by time. Exact today | **P12**, if it wants the column while `0007` is open |
| **DI26** | `keywords.normalise` tears decomposed Unicode apart. **Not built in P11** — no P11 task required it, and NFKC changes matching for every existing term | **P15** |
| **DI14** | `_extract_search_post` does not normalise its host. Does not bite the cascade or the pre-score, both content-keyed | Unchanged |
| **DI15** | An eighth job type shipped unreconciled. **P11 added none** — its stage is a function, not a job type | Unchanged |
| **DI16 / T1 (P8)** | `leads.confidence_score` exists, not populated | **P21** |
| **DI17** | Nothing enqueues `maintenance` | **P17** |
| **DI20 · DI27** | Triggers not satisfied across this phase's runs | *A further occurrence* |
| **L4 (P7)** | Notification retry — **still nobody's** | Open since P7 |
| **O2** | `mypy`, 193 errors, deferred by D6 in P8. P11's new modules ship clean under it | Its own scoped task |

**DI13, DI23, DI24 and DI25 were built and are closed.** Four closed, one opened.

---

## 6. Things a later phase must delete on purpose

| Phase | Test | Why it is there |
|---|---|---|
| **P12** | `test_the_three_absent_components_are_recorded_as_absent_not_as_zero` | It asserts exactly three absences. When `0007` lands and `pain_phrase`/`subreddit_fit` become computable, **this test must be updated in the same change** — if it is not, it will keep passing while asserting a lie, because `ABSENT_COMPONENTS` is a constant nobody is forced to maintain |
| **P15** | `test_the_competitor_registry_was_not_wired_before_p15` | *(P9's)* Unchanged — P11 did not wire it |
| **P19** | *(none yet)* | **`run_prescore_stage()` is not `PreAIGate` and must not become it.** It composes P9's rules, P10's cascade and P11's arithmetic. The budget, the response cache, the adaptive cut and the eleven-reason `GateReport` are yours — and the adapter from `RuleResult` to `GateDecision` still lives on your side of the R3 fence. Nothing enforces that boundary today |
| **P21** | *(none yet)* | `src/scoring/` will hold `ConfidenceScorer`, and **R6 is "categoricals in, arithmetic out"** — the analysis arrives as a stored row, never as a call. Fence 2 covers the path; the temptation is documented at [35 §2.1](35-testing-strategy.md) |

---

## 7. Verification snapshot at handover

| | |
|---|---|
| Full suite | **1871 passed, 2 skipped** in 293.57 s (P10: 1640 / 2) |
| New tests | **+231** |
| Branch coverage, P11's new code | **100%** across all eight new modules |
| Coverage, whole tree | **87%** |
| `ruff check` / `format --check` | Clean · 174 files |
| `alembic heads` | `0006_content_and_dedup` — one head, unchanged |
| `check_schema.py` | **51/51** |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns · `GET /` 200 |
| Mutation testing | **46 designed · 43 detected · 3 survived · 0 hung · 0 not applied.** All three survivors provably equivalent, one the deliberate control |
| Grep fences | Fence 2 covers **4 of 6**, and says so |
| Rejection vocabulary | **8 of 11**; the remaining three are all P19's |
| **A2** | **75.4%** archive · **20.9%** in-window · assumed 73% |
| **Collapse, real data** | **5.69%** (P10 measured 5.74% on 488; 492 now). **Threshold not tuned** |
| **Pre-score distribution**, 492 leads | min **2.07** · p25 **35.09** · median **41.27** · p75 **47.64** · p90 **53.52** · max **70.15** · mean **41.37** |
| At the shipped floor of 35 | **75.6%** of the archive would be admitted |
| AI calls | **0** |
| Rollback | **Executed** three ways — flag, CLI, block deletion |

---

## 8. Blockers carried into P12

| ID | Blocker | Blocks P12? |
|---|---|---|
| **D1/O3** | **P00–P07, P09, P10 manual sign-off tables unsigned.** P8's was signed 2026-08-14 | **No, but no tag.** P11's guide is unsigned until the operator runs it |
| **O2** | `mypy` not in the gate — 193 errors in 23 files | **No.** Deferred by D6 in P8 |
| **L4 (P7)** | Notification retry undelivered | **No**, still an open P7 obligation |
| **DI28** | `leads` has no `run_id` | **No — it is an opportunity while `0007` is open**, not a blocker |
| **A2 gap** | 20.9% in-window against an assumed 73% | **No.** Measured, published and explained; the comparable figure needs P19/P20's cache |

---

## 9. Entry conditions for P12

- [ ] `docs/testing/P11-testing.md` sign-off table signed — **T3, T8 and T10 especially**
- [ ] **[§3 read]** — two absent components are yours, and `ABSENT_COMPONENTS` must be updated in the
      same change that fills them
- [ ] **[§4 T1/T2 read]** — a 0.0 component is not an absent one, and adding a seventh weight
      **rescales every stored total**. Re-measure the distribution before trusting the floor of 35
- [ ] **[§4 T5 read]** — A2 has two numbers and neither is to be tuned toward
- [ ] **[§6 read]** — `test_the_three_absent_components_are_recorded_as_absent_not_as_zero` is
      **yours to update**, and it will pass while lying if you do not
- [ ] [34 §P12](34-implementation-plan.md) read — all thirteen fields, including the **15-step
      creation order**, the **`sqlite-vec` try/except**, and **all four deferred FKs**
- [ ] [DI28](DEFERRED-IMPROVEMENTS.md) read — decide on `leads.run_id` deliberately while `0007` is
      open
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] The full suite recorded green before the first change — **1871 passed, 2 skipped**
- [ ] `git status` clean · `alembic heads` = one `0006` · `check_schema.py` 51/51
- [ ] `gh run list` checked: P11 green on `origin/main`
- [ ] ⚠️ **`config.yaml` checked for uncommitted local values** — it carried a real chat id at the
      start of both P8 and P9. It was clean at the start of P10 and P11; P11 added the `scraping:`
      and `gate:` blocks and two `pipeline.prescore_*` keys to it
- [ ] ⚠️ **`0007` is the largest revision in the chain and the first to touch the live database
      since `0006`.** M7 requires a timestamped backup via the SQLite backup API **before** the
      upgrade, and M9 requires up/down/up against a copy of the live 492-lead database
