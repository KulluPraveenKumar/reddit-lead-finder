# Phase 11 — Completion Report · Pre-score, funnel & comments

**Phase:** P11 (frozen numbering, [34 §P11](34-implementation-plan.md)) · **Date:** 2026-08-15
**Revision:** none — P11 adds no migration. `alembic heads` remains `0006_content_and_dedup`, for
the fourth phase running.

> Decisions and their measurements: [P11-DECISION-ANALYSIS.md](P11-DECISION-ANALYSIS.md).
> What the next phase inherits: [PHASE-11-HANDOVER.md](PHASE-11-HANDOVER.md).
> Where a lost session resumes: [progress/P11-COMPLETE.md](progress/P11-COMPLETE.md).

---

## 1. What was built

**P11 is the phase where the deterministic pipeline starts running.** P9 built the rules, P10 built
the dedup cascade, and **neither had a caller**. P11 is the first caller of both, and the first
phase in which a collected item is scored, grouped, counted and rendered end to end.

| File | What it is |
|---|---|
| `src/scoring/__init__.py` | The package. P11's two reason constants, `PrescoreSettings`, the cited weights, the three declared absences, and the `LeadScorer` re-export |
| `src/scoring/features.py` | The arithmetic — recency decay, engagement, length plausibility, question form, tier value. Every function returns 0.0–1.0, and that bound is what makes the score 0–100 |
| `src/scoring/prescore.py` | The score and the admission decision |
| `src/scoring/holdout.py` | The 2% sampler, the miss rate, and the exclusions |
| `src/scoring/funnel.py` | The counters, and DI23's two-vocabulary reconciliation |
| `src/scoring/legacy.py` | `LeadScorer`, moved **byte-for-byte** under `git mv` |
| `src/scoring/__main__.py` | `python -m src.scoring` — what the manual guide hands a non-developer |
| `src/db/repositories/comments.py` | `body_hash` and the savepoint writer |
| `src/scrapers/comment_scraper.py` | Candidates ordered by pre-score, the budget, the counterfactual, the back-fill |
| `src/orchestration/handlers/prescore.py` | **The stage** — score, group, count, fetch |

### The correctness rule this phase had to keep

[06c §4.4](06c-local-first-pipeline.md) — **group for analysis, score individually.** P10 protected
it inside the cascade; P11 could have broken it from outside by scoring *after* grouping, or by
scoring the representative and fanning the number out. It scores **first**, so every member has its
own number before any group exists, and `test_a_group_of_n_yields_n_distinct_prescores` holds it.

---

## 2. The Files row, and the files outside it

[34 §P11](34-implementation-plan.md)'s **Files** row names four modules and a template. **Every
acceptance criterion in this phase requires a live call site** — *"every collected item has a
`prescores` row"*, *"A2 measured"*, *"comment requests −5%"*, *"miss rate published"*,
*"`COUNT(*) FROM ai_calls` = 0"* — and the row names **no handler**. Wiring is therefore the phase.

Enumerated in full, under [34 §1.1](34-implementation-plan.md)'s *"a guide, not a contract"* and the
precedent P5's `feed` CLI, P6's `triage.py`, P9's `python -m src.rules` and P10's `__main__.py` each
set. **Nothing here is silent.**

### In the Files row

| File | |
|---|---|
| `src/scoring/prescore.py` | + |
| `src/scoring/features.py` | + |
| `src/scrapers/comment_scraper.py` | + |
| `src/db/repositories/comments.py` | + |
| `src/dashboard/templates/run_progress.html` | ~ (the row says `templates/`; the tree has always had `src/dashboard/templates/`) |

### Outside it, and why

| File | | Why |
|---|---|---|
| `src/scoring/__init__.py` | + | **Forced.** The Files row names a *directory*; a module cannot contain a module |
| `src/scoring/legacy.py` | + | `git mv` of `src/scoring.py`, byte-for-byte. R20's `intent_score` must not move a digit |
| `src/scoring/holdout.py` | + | Task 6's sampler. Pure, so it is testable from literals |
| `src/scoring/funnel.py` | + | Task 2's counters, and DI23's mapping |
| `src/scoring/__main__.py` | + | [35 §1](35-testing-strategy.md) needs a guide a non-developer can execute |
| `src/orchestration/handlers/prescore.py` | + | **The call site.** Not a job type — [DI15](DEFERRED-IMPROVEMENTS.md) records that an eighth already shipped unreconciled against [04 §2.4](04-system-design.md)'s closed list of seven |
| `src/orchestration/handlers/finalize.py` | ~ | Calls the stage. Run-level, and non-fatal per AD-9 |
| `src/orchestration/handlers/discover.py` | ~ | DI24's fix and the stage-3 holdout, which is where triage rejections happen |
| `src/discovery/triage.py` | ~ | 🔴 DI25's fix |
| `src/reddit_client.py` | ~ | DI13 at the parser, and `get_post_detail` — an **eighth** method, additive under AD-2, the precedent P5's `get_feed` set. The six frozen signatures are untouched |
| `src/db/models.py` | ~ | DI13 at the model. **Python-side defaults only; no migration, no schema change** |
| `src/orchestration/run_service.py` | ~ | `RunProgress.funnel`, additive |
| `src/dashboard/templates/index.html` | ~ | A NULL score must not render as the string `None` |
| `pyproject.toml` | ~ | Two ruff excludes narrowed — see §7 |
| `config.yaml` | ~ | The `scraping:` and `gate:` blocks, and `pipeline.prescore_*` |

**`src/scrapers/subreddit_scraper.py` was deliberately not edited.** It is the `intent_score`
producer; the stage runs in the finaliser *after* it returns, so the legacy contract is untouched by
construction rather than by care.

---

## 3. Acceptance criteria

| [34 §P11](34-implementation-plan.md) | Evidence |
|---|---|
| Every collected item has a `prescores` row, admitted or not | `test_every_collected_item_gets_a_prescores_row_admitted_or_not`. The `CHECK` wall P6 filed is discharged by **D3** without a schema change |
| **A2 measured** — against the assumed 73% *(bold)* | **Measured: 75.4% archive · 20.9% in-window.** Both published; the gap is structural and explained at [P11-DECISION-ANALYSIS §A2](P11-DECISION-ANALYSIS.md). Mutations **M1, M28** |
| Comment candidates ordered by pre-score; collected comments fall ≥5% with **no** reduction in admitted items | `test_candidates_are_requested_in_descending_prescore_order`, `test_the_saving_beats_the_five_percent_target_on_a_realistic_run`. A **within-run counterfactual** — nothing called `get_post_comments` before this phase, so there is no live baseline. Admitted items are unaffected: ordering changes *which* posts get a request, never whether an item is admitted. Mutations **M40, M43** |
| Re-running comment extraction creates **zero** duplicates | `test_re_running_comment_extraction_creates_zero_duplicates`, against the real `ux_comments_hash` index. Mutations **M37, M38, M39** |
| Search-sourced `score` back-filled | `test_a_search_sourced_score_is_back_filled_during_the_comment_fetch`. Required DI13 first — see §5. Mutation **M42** |
| **Metadata-triage miss rate published and < 5%** *(bold)* | `test_the_miss_rate_is_published_on_the_timeline`, rendered on the run page. **Zero samples renders "not measured", never 0.0%.** Mutations **M8–M14** |
| **`SELECT COUNT(*) FROM ai_calls WHERE run_id=?` = 0** *(bold)* | `test_the_stage_makes_no_ai_call` — counted in the database on a real run, not inferred from the fence. Mutation **M15** |
| **A group of N yields N distinct pre-scores** *(bold, transferred from P10)* | Met as a **property** — see **D4**. `test_a_group_of_n_yields_n_distinct_prescores` and `test_two_members_identical_in_every_scored_dimension_share_a_pre_score`. Mutation **M29** |
| Intra-run collapse rate measured *(transferred from P10)* | **5.69%** on the live archive against P10's 5.74% — the 0.05 is the four leads collected since. **No threshold tuned.** Mutation **M3** |
| Fence 2 extended to `src/scoring/` with an existence guard | `test_the_scoring_package_is_inside_the_ai_fence` + `test_the_scoring_package_exists` + `test_the_legacy_lead_scorer_is_still_importable`. **4 of 6** |
| Vocabulary six → eight | `test_p9_p10_and_p11_together_reach_eight_of_p19s_eleven` |

### Metrics

| Target | Measured |
|---|---|
| Filter rate measured | ✅ **75.4% / 20.9%** against an assumed 73% |
| Comment requests −5% or better | ✅ measured per run and rendered; ≥5% asserted on a realistic corpus |
| Triage miss rate < 5% | ✅ published; **not measured** rendered honestly when nothing was sampled |
| **0 AI calls** | ✅ **0**, counted in `ai_calls` |

---

## 4. Verification

| Check | Result |
|---|---|
| Full suite | **1871 passed, 2 skipped** in 293.57 s — one clean uninterrupted run (P10: 1640 / 2) |
| New tests | **+231** |
| `ruff check .` / `ruff format --check .` | Clean · 174 files |
| **Branch coverage, P11's new code** | **100%** — `src/scoring/{__init__,features,prescore,holdout,funnel,__main__}.py`, `src/db/repositories/comments.py`, `src/scrapers/comment_scraper.py` |
| Coverage, whole tree | **87%** (gate floor: 70%) |
| `alembic heads` | `0006_content_and_dedup` — one head, unchanged |
| `check_schema.py` | **51/51** |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns · `GET /` 200 |
| Grep fences | Fence 2 covers **4 of 6**, and says so |
| Offline guarantee | Held — the comment path is exercised through a fake client; no test opens a socket |
| Rollback | **Executed** three ways — by flag, by CLI, and by deleting the config block |

---

## 5. 🔴 Four Deferred Improvements built, and the order mattered

All four named **P11** as their trigger, and each was required **transitively** by one of P11's own
tasks rather than fixed in passing.

**[DI25](DEFERRED-IMPROVEMENTS.md) — and the holdout was built first, deliberately.** `triage.py`'s
bare `\bhiring\b` had been discarding *"Our hiring process is broken and I need a tool to fix it"*
— a textbook lead — live, since P6. The register named P11 as the owner *"which owns the 2%
metadata-triage holdout — the first mechanism capable of **measuring** the false-positive rate
rather than arguing about it"*. **Fixing the regex first would have deleted the evidence that
justifies the fix**, so the audit was built first, and the measurement is direct: the full-stage
gate scores that post **66.88 and admits it**, and the audit reports it as a miss with
`worst_reason: hiring`. `test_the_audit_catches_di25s_own_example_as_a_miss` reproduces the detection
against the pre-fix pattern, so the evidence survives the fix permanently.

**[DI24](DEFERRED-IMPROVEMENTS.md) — P6 had never matched a keyword.** One line. Iterating the
`keywords:` mapping yielded its *keys*, so triage matched a title only if it literally contained the
string `high_intent`. P11 is the first consumer of that score.

**[DI23](DEFERRED-IMPROVEMENTS.md) — two vocabularies on one page.** Reconciled for **display
only**; neither writer changes. One genuine divergence closed as a side effect of DI25: the two
`hiring` patterns are now byte-identical.

**[DI13](DEFERRED-IMPROVEMENTS.md) — and it went one layer deeper than the register described.** The
entry is about `_extract_post` reporting `0` for an absent comment count. Fixing that exposed the
larger half: **`models.py` carried a Python-side `default=0` on `leads.score` and
`leads.num_comments`**, which SQLAlchemy applies whenever the value is `None` at INSERT.

> **Measured 2026-08-15 on the live database: 0 of 492 rows carry NULL in either column** — on a
> corpus containing search-sourced leads that *cannot* know a score, while the schema has said
> `nullable=True` with no server default since `0001_baseline`, and `legacy.py` has claimed since
> before Phase 1 that *"the Lead row still stores NULL, because 'unknown' and 'zero upvotes' are
> different facts and conflating them would make the number a quiet lie."*
>
> The intent was documented, tested nowhere, and had never held. **Task 4's back-fill is
> unachievable while the default has already answered the question wrongly.**

Both defaults removed. **No migration** — they are Python-side only, the column definitions are
untouched, and the 459 original rows keep their values. Rendering was fixed at the two read sites: a
NULL exports as an **empty CSV cell** (`csv.writer` renders `None` as empty, pinned by a test) and
displays as an **em dash**, never the string `None`.

---

## 6. Mutation testing

Applied to every **bold** acceptance criterion, to the two transferred from P10, and to all four DIs.

**46 designed · 43 detected · 3 survived · 0 hung · 0 not applied.**

| Group | Count | What they attack |
|---|---:|---|
| `funnel.py` | 7 | A2 folding in the tunable dial, a rate over nothing, collapse counting groups not members, the sums check, DI23's mapping and its granularity |
| `holdout.py` | 7 | reproducibility, the exclusion list, `no_title`, zero-samples-is-not-a-pass, the off switch, `worst_reason`'s tie-break |
| `prescore.py` / `features.py` / `__init__.py` | 11 | the floor boundary, ordering of the window check, components on a rejection, the rollback, `min_chars` binding, unknown age, unknown engagement, tier summing, the normaliser |
| `handlers/prescore.py` | 6 | idempotence, rejections-as-admissions, `rank` not supplied, grouped-vs-admitted, the A2 denominator, the rollback |
| `handlers/discover.py` / `triage.py` | 4 | DI24 and DI25 reintroduced, the audit population, audited-vs-collected |
| `comments.py` / `comment_scraper.py` / `models.py` / `reddit_client.py` | 10 | the hash scope and its encoding, the savepoint, ordering, DI13 ×3, the back-fill, the floor |
| fence | 1 | R3 breached from the new package |

### ⚠️ The first run reported 9 survivors, and 8 were test defects

**The control survived in both runs, which is the only reason either is trustworthy**
([PHASE-10-HANDOVER §4 T4a](PHASE-10-HANDOVER.md): *"a run in which everything is detected is a
broken run, not a triumph"*). Every survivor was probed rather than accepted, and each produced a
**stronger test**:

| | Why it survived | Fix |
|---|---|---|
| **M3** | The fixture had one group of **two**, so `grouped` and `groups` were both 1 and a rate from the wrong one was indistinguishable | A group of **three** — `grouped` 2, `groups` 1 |
| **M4** | Undercounting is caught by `==` and `>=` alike | A **double-counting** case, which is what a broken idempotence guard produces |
| **M14** | `by_reason` insertion order happened to put the max first | The fixture now puts a one-miss reason **ahead** of the two-miss one |
| **M22** | The selector always supplied a score, so the mutated branch was never entered with `None` | Re-pointed at `test_both_unknown_is_zero` |
| **M23** | `high + medium` = 1.5, which the clamp returns to 1.0 — identical to the max | Two **lower** tiers: 0.5 + 0.25 = 0.75 against a max of 0.5 |
| **M29** | The highest-upvoted member was also the highest-scoring, so P10's fallback picked the same representative | The upvoted member is given a **stale timestamp**, so the two orderings disagree |
| **M34** | **NOT-APPLIED** — the anchor spanned two lines and held a typographic apostrophe | Re-cut. P10's T4: *"NOT-APPLIED is not a pass"* |

**The corrected tests were verified green on clean code before the second run** — P10's T4a, applied.

### The three survivors are all provably equivalent

| | Why it cannot be detected |
|---|---|
| **M46** | **The deliberate control.** `self.admitted += n if True else 0` is semantically identical |
| **M24** | Below the floor, `(length - min_chars)` is negative and `_clamp` returns 0.0 regardless. The early return is an optimisation and a statement of intent. It **stays** — `rules.min_chars` is a rejection threshold elsewhere and a reader should see the two agree — and `test_the_floor_check_is_redundant_with_the_clamp_and_stays_anyway` records that the equivalence was measured |
| **M25** | `max(0.0, nan)` returns **0.0**, because `max` keeps its first argument unless a later one compares greater and every NaN comparison is False. So the clamp is already NaN-safe — **purely by the order its arguments are written in**. `max(nan, 0.0)` returns `nan`. The guard **stays** as defence in depth, and the load-bearing thing is attacked separately: `test_the_clamps_nan_safety_rests_on_argument_order_and_that_is_pinned` fails if anyone reorders it |

---

## 7. Things found by testing, not by review

**1. `body_hash`'s separator claim was false, and the failure mode was a silently dropped comment.**
The first version joined the fields with `\x00` on the stated grounds that the character *"cannot
occur in any of the three fields"*. It can — a Python `str` holds `\x00` perfectly well — and
`body_hash(1, "a\x00b", "c")` and `body_hash(1, "a", "b\x00c")` both encoded to `1\x00a\x00b\x00c`
and **collided**. A collision looks exactly like the duplicate the unique index exists to refuse, so
the comment would have been dropped with no error. The author is length-prefixed now.

**2. `leads.score` was never NULL, on 492 rows.** §5 above. Found by a test failing for the *right*
reason: the back-fill fixture set `score=None` and read back `0`.

**3. The A2 denominator was about to be inflated by the audit's own leads.** The holdout stores its
2% sample as leads with `scraped_at` inside the run window, so the finaliser's stage would have
re-scored them — a population **selected for having been rejected**, entering the hard-filter
denominator and biasing A2 **upwards** by an amount growing with the holdout rate. `_collected_leads`
filters `source = 'scrape'`. Mutation **M31**.

**4. A stale ruff exclude would have silently unlinted the legacy scorer.** `pyproject.toml`
exempted `src/scoring.py` from lint **and** format, to protect the R20 `intent_score` fingerprint
([DI4](DEFERRED-IMPROVEMENTS.md)). The moment the module became a package that path literal matched
**nothing**, and `LeadScorer` would have started being formatted — exactly what DI4 says not to do.
The mirror image was true of `src/scrapers/*`, whose **directory** glob would have swallowed P11's
new `comment_scraper.py` under a rule written about pre-Phase-1 code. Both narrowed to named files.

**5. The mutation driver's root-finder walked out of the repository — P10's T4, exactly.** The
driver lives in the scratchpad, which is *outside* the tree, so walking up from `__file__` never
finds `src/`. P10's version spun at the drive root; this one **raised**, because the guard was
copied. The root is now taken from the working directory and **verified**.

**6. A title with no body scores `too_short`, and a tester would reasonably read that as broken.**
`rules.min_chars: 80` measures a **body**, and P11 is the first phase to bind it to one. Given its
own test and its own step in the manual guide rather than a footnote.

---

## 8. Documentation landed

| Document | Change |
|---|---|
| [ARCHITECTURE_FREEZE §11.1](ARCHITECTURE_FREEZE.md) | **Three reconciliations** — the missing weights and three absent components, the `prescores` CHECK wall, and the N-distinct criterion. **No §11 amendment**: no technology, table, decision or dependency changes |
| [34 §P11](34-implementation-plan.md) | A three-part reconciliation note, the A2 measurement with both figures, and the record of which files sit outside the Files row |
| [06c §3.1](06c-local-first-pipeline.md) | The six-of-nine split and the weight derivation |
| [06c §4.3](06c-local-first-pipeline.md) | `rank` filled in; the N-distinct measurement |
| [06c §6](06c-local-first-pipeline.md) | The stage-3 holdout as built — no body fetch, no AI, `no_title` excluded, and DI25 as its first catch |
| [35 §2.1](35-testing-strategy.md) | Fence 2 → **4 of 6**; the R6 temptation `src/scoring/` carries for P21; the module-to-package blind spot |
| [35 §6](35-testing-strategy.md) | P11's row — the counterfactual reading of −5%, and the struck N-distinct criterion |
| [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) | **DI13, DI23, DI24, DI25 built and moved to §3**; **DI28 opened** |
| [docs/README.md](README.md) | P11 execution row |
| `config.yaml` | The `scraping:` and `gate:` blocks and `pipeline.prescore_*`, each with its rollback documented inline |

---

## 9. Deferred Improvements

**Four closed, one opened.**

| | |
|---|---|
| **DI13 · DI23 · DI24 · DI25** | **Built.** §5. Each named P11 and each was required transitively by a P11 task |
| **DI28** | **Opened.** `leads` has no `run_id`, so "this run's leads" is a time window. Exact today under the one-active-run constraint; registered for the next phase that opens a revision — `0007`, P12, which already runs `batch_alter_table` |
| **DI26** | **Untouched, and its trigger named P11 *or* P15.** Not required by any P11 task, and NFKC changes matching for every existing term. It wants its own before/after measurement, which is what its entry says |
| **DI14** | Does not bite P11 — the cascade is content-keyed, and P11 changed nothing about that |
| **DI20 · DI27** | Triggers not satisfied across this phase's runs |

---

## 10. What P11 deliberately did not do

See [P11-DECISION-ANALYSIS §"What P11 deliberately did not do"](P11-DECISION-ANALYSIS.md) — adding
`leads.run_id`, fixing DI26, building the adaptive cut, converging the two rejection writers, adding
a timing assertion, and tuning `jaccard_threshold`.
