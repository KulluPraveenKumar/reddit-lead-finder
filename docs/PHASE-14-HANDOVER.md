# Phase 14 — Handover

**From:** P14, `analyze_business` · **Written:** 2026-08-16
**To:** **P15**, and for the debts, **P16**, **P17** and **P20**

> Evidence lives in [PHASE-14-COMPLETION-REPORT.md](PHASE-14-COMPLETION-REPORT.md).
> Reasoning lives in [P14-DECISION-ANALYSIS.md](P14-DECISION-ANALYSIS.md).
> Where the next session resumes lives in [progress/P14-COMPLETE.md](progress/P14-COMPLETE.md).

---

## 1. What now exists

**A website becomes 23 persisted, individually-validated sections of business knowledge, from one AI
call.** One new package, one new repository, one new stage, no migration, no route.

```
handle_analyze_website(session, project_id, run_id=?, config=?, fetcher=?, service=?)
   │
   ├─ WebsiteFetcher.fetch          P13's — direct egress (R18), L1 cache, ≤7 pages
   ├─ site_signals.extract          P13's — six local signals, zero AI
   ├─ build_local_signals           facts not questions; DI33's flag
   ├─ AIService.analyze_business_call()   ◄── the ONE call (R2, R10)
   │      └─ ai_cache hit on (site fingerprint, stage, prompt v) ──► ZERO calls
   ├─ validate_sections             23 verdicts; CANNOT raise
   ├─ KnowledgeRepository           supersede → 23 sections → 3 typed tables
   └─ emit_event                    only when run_id is not None
```

**The public surface P15 will meet:**

```python
from src.knowledge import (
    SECTION_SPECS,           # dict[str, SectionSpec], the 23 in BKB_SECTION_KEYS order
    STATUS_OK, STATUS_INCOMPLETE,
    SectionSpec, ValidatedSection,
    validate_sections,       # (raw) -> exactly 23 verdicts, never raises
    analyze,                 # (session, project_id, site, signals, service, config) -> BKBResult
    build_local_signals,
    BKBResult,
    COST_BUDGET_USD, MARKUP_ABSENT_KEY, MARKUP_SIGNAL_KEYS,
)
from src.knowledge.sections import (
    PersonaOut, PainPointOut, BuyingSignalOut, CompetitorOut, ICPOut,
    CompanyOverviewOut, ProductServiceOut, FeatureSetOut, PricingPositioningOut,
    IndustryOut, TargetMarketOut, JobToBeDoneOut, ValuePropositionOut,
    AlternativeSolutionOut, SearchIntentOut, ObjectionOut, OutreachAngleOut,
    SLUG_PATTERN,
)
from src.db.repositories.knowledge import (
    KnowledgeRepository, ORIGIN_WEBSITE, BKB_COMPLETE, BKB_PARTIAL, TIER_WEIGHTS,
)
from src.orchestration.handlers.website import (
    BKB_EVENT, handle_analyze_website, build_ai_service, build_website_fetcher,
    render_report, render_stored, main,
)
```

**Five tables are written** — `bkb`, `bkb_sections`, `personas`, `pain_points`, `intent_signals` —
and nothing else.

---

## 2. Guarantees P15 must not break

| | Guarantee | Enforced by |
|---|---|---|
| **G1** | **Exactly one `ai_calls` row with `stage='business_intelligence'` per analysis** | `test_exactly_one_ai_call_row_is_written_per_analysis`, `test_one_call_still_holds_when_a_section_fails_validation` · mutation **M1** |
| **G2** | **`validate_sections` returns exactly 23 verdicts and raises for nothing, ever** | `test_validation_never_raises_even_on_a_hostile_payload`, `test_an_empty_response_yields_twenty_three_incomplete_verdicts_not_a_short_list` |
| **G3** | **Breaking any one of the 23 leaves the other 22 `ok`** — asserted over **all 23**, not an example | `test_any_single_section_can_be_destroyed_without_taking_the_others` (parametrised ×23) · **M3** |
| **G4** | **An unchanged fingerprint makes zero calls *and* burns no BKB version** | `test_a_second_analysis_of_an_unchanged_site_makes_zero_calls`, `test_a_reused_analysis_does_not_burn_a_bkb_version` · **M2** |
| **G5** | **`src/knowledge/` imports `src.ai` not at all** — the service is injected | `test_the_knowledge_package_is_inside_the_ai_fence` + its existence guard · **M7** |
| **G6** | **`SLUG_PATTERN` is identical on both sides of the fence** | `test_the_slug_pattern_agrees_across_the_fence` |
| **G7** | **`payload_json` is NULL for exactly the three typed sections** — satisfied by construction from `ValidatedSection` | `test_the_payload_null_rule_is_satisfied_by_the_database_not_just_by_us` · **M9** |
| **G8** | **Exactly one BKB is ever live per project**, and supersede closes *every* live row | `test_exactly_one_bkb_is_ever_live`, `test_supersede_closes_every_live_row_not_merely_the_newest` · **M10** |
| **G9** | **A row whose `origin` is not `website` is re-pointed and never rewritten** | `test_an_operator_edited_row_survives_a_re_analysis_unchanged` · **M11** |
| **G10** | **Nothing is deleted by any path in `KnowledgeRepository`** | `test_nothing_is_ever_deleted_by_any_path_in_this_repository` |
| **G11** | **`staleness_days` comes from P12's `BKB_STALENESS_DAYS`; Group C is NULL** | `test_staleness_is_seeded_from_p12s_policy_and_group_c_never_stales` · **M12** |
| **G12** | **The model call happens before the first write** — DI37 immunity | `test_the_model_call_happens_before_the_first_write` · **M8** |
| **G13** | **Bounds are a verdict, not a request** — 1–3 ICPs, 1–5 personas, 3–12 pains, 3–12 signals | `test_the_stated_bounds_are_enforced_here_and_not_only_asked_for` · **M4** |
| **G14** | **A duplicate slug never reaches a UNIQUE index; the FIRST occurrence wins** | `test_a_duplicate_slug_is_caught_before_it_reaches_a_unique_index` · **M6** |
| **G15** | **`ai_calls.project_id` is populated** | `test_the_call_is_attributed_to_the_project` · **M13** |
| **G16** | **DI33: unobserved markup is omitted and flagged, never sent empty** — asserted on the **rendered request** | `test_the_flag_reaches_the_prompt_the_model_actually_sees` · **M5** |
| **G17** | One head, still `0007` — **P14 added no revision** | `test_single_head`, `test_the_head_is_0007_and_there_is_still_one_of_them` |
| **G18** | **`WEIGHTS` still has six components; `prescore()` untouched** | `test_the_three_absent_pre_score_components_are_still_absent` |

---

## 3. ⚠️ What P15 inherits directly

1. **`src/knowledge/` is inside grep fence 2 and P14 put it there.** `test_the_scoring_package_is_inside_the_ai_fence`
   said *"`src/knowledge/` is P15's"* — that referred to the package's **bulk**, and P14 created it,
   so P14 extended the fence. **You cannot import `src.ai` from this package.** P14's first draft
   did, and the fence caught it. The service is a **parameter**.

2. **The origin guard's far half is yours, and its near half already exists.**
   [34 §P15](34-implementation-plan.md) task 4 is `regenerate_section` deleting only
   `origin='website'` rows. P14 does **not** delete anything, and it already refuses to *overwrite* a
   non-`website` row (**G9**). Build on that rather than around it — and note that P14's writer takes
   the guard from `row.origin`, not from an argument.

3. **The soft delete has no column and does not need one.** A typed row is *current* iff its
   `bkb_id` is the current BKB's. A vanished slug is simply not re-pointed. `orphaned_slugs()` is
   what makes that observable. **Do not add a `status` or `deleted_at` column** — `0007` is shipped
   and it would be a [freeze §4.1](ARCHITECTURE_FREEZE.md) amendment needing a failed measurement.

4. **`bkb.prefix_tokens` and `bkb.dropped_sections_json` are still NULL, and they are yours.**
   P12 created them; P14 writes neither. [34 §P15](34-implementation-plan.md) task 6's
   `PrefixBuilder` — *"budget enforced, drops logged"* — is what fills them.

5. **`bkb_evidence` is still empty.** The `evidence` array **is** returned by the model and validated
   by `Evidence` in the envelope, but P14 writes no `bkb_evidence` rows — that table is P15's task 3,
   and it requires the `source_type` vocabulary and the literal-substring check P14 does not have.
   ⚠️ **The evidence is therefore in the response and not in the database.** If you need P14's
   evidence, it is reachable only by re-analysing; the L2 cache will serve the same payload.

6. **`TIER_WEIGHTS` maps `high|medium|low` to `0.5|0.3|0.15`.** This is R6 in miniature — the model
   emits the categorical, Python computes the number, and `BuyingSignalOut` has **no weight field**
   for a model to put one in. If P21's calibration wants different numbers, change them here; do not
   ask the model.

7. **`projects` still has exactly one writer, and it is still P16's.** P13 declined to become a
   second one; P14 declines too, and `test_no_project_row_is_created_by_this_stage` pins it. P14's
   tests and its manual guide both create the row explicitly.

---

## 4. Traps waiting in P15

**T1 — 🔴 The lenient envelope will look like a bug, and reverting it breaks two acceptance
criteria at once.** `BusinessKnowledgeOut` types every section as `list[dict]` / `dict` with
everything defaulted. It is *tempting* to restore the strict types now that
`src/knowledge/sections.py` has them. **Do not.** `AIService._record_ai_call` writes **one row per
attempt** and `_execute` retries on any `output_model` failure, so a strict envelope turns one
malformed persona slug into three `ai_calls` rows and 23 lost sections. Mutation **M1** is exactly
this change and it fails. The reasoning is in the envelope's own docstring and in
[P14-DECISION-ANALYSIS §D4](P14-DECISION-ANALYSIS.md).

**T2 — 🔴 `_validate_one`'s outer `except Exception` is a backstop and must never become the working
path.** A section it catches has **lost all its content**, because the item loop never finished — while
a section the item loop handled keeps its valid entries. **Both produce `status='incomplete'`**, and
mutation **M3 survived** an earlier test that asserted only the status. If you add a section shape,
assert the **survivor**, not the status. `test_the_outer_backstop_is_a_backstop_and_not_the_working_path`
is the pattern to copy.

**T3 — the L2 reuse is keyed on `ai_cache`, not on a column, and `bkb` has nowhere to record a
fingerprint.** `analyze` decides to reuse from `result.from_cache` **and** a prompt-version match.
There is no `bkb.source_content_hash` and adding one is a migration. If P15 changes the prompt (it
adds no stage, but `section_regen` is nearby), note that **`prompt_version` is compared** — a bumped
version correctly forces a rebuild, which is `test_a_reuse_is_refused_when_the_prompt_version_moved`.

**T4 — the model call is before the first write, and that ordering is load-bearing.**
[DI37](DEFERRED-IMPROVEMENTS.md): `_record_ai_call` uses its **own** session, so a caller holding a
write transaction stalls it for the whole `busy_timeout` and then **silently loses the row**. Measured
at 21.6 s per affected test. `test_the_model_call_happens_before_the_first_write` fails if you
reorder. If P15's `regenerate_section` needs to write before it calls, **you have met DI37 head-on**
and it becomes yours to solve rather than to avoid.

**T5 — `ideal_customer_profiles` is not a typed section and it is easy to "fix".** An ICP feels
structurally like a persona, so marking it typed looks like tidiness. There is **no `icps` table**;
its `payload_json` is the only copy an ICP has, and marking it typed would store `NULL` and lose the
section. 05 §5.1b flags this exact mistake and
`test_ideal_customer_profiles_is_not_typed` pins it.

**T6 — a section's `error` string is rendered by P16 and is truncated to 2,000 characters.** It is
written for an operator reading *"why is this section flagged?"*, not for a stack trace. If P15 adds
validation, keep that voice.

**T7 — `render_stored` and `render_report` exist for the manual guide, and `main()` is the only thing
in the phase that reaches the network.** No test invokes `main()` over the wire; a test that did
would **breach** the offline guarantee rather than verify anything. P13's trap T7, unchanged.

**T8 — the manual guide is PowerShell and a bash heredoc silently does nothing there.** P14's first
draft of `docs/testing/P14-testing.md` used `python - <<'PY'` in six steps. On Windows PowerShell
that does not run, and the failure is quiet enough to read as a passing step. `--show` was added to
the CLI specifically so the guide needs **one command** instead of a multi-line snippet.

---

## 5. Debts carried forward, by owner

| | Item | Owner |
|---|---|---|
| **DI37** | **New.** `_record_ai_call` loses its row when the caller holds a write transaction | **A phase that must write before it calls.** P14 is immune |
| **DI33** | ✅ **Closed by P14** — omitted and flagged, never sent empty | — |
| **`bkb_evidence`** | Empty. The `evidence` array is returned and validated but not persisted | **P15** — task 3 |
| **`prefix_tokens` / `dropped_sections_json`** | NULL | **P15** — task 6 |
| **`competitor`** | Absent pre-score component. `test_the_competitor_registry_was_not_wired_before_p15` still passes | **P15** |
| **`pain_phrase`** | ⚠️ **P14 wrote `phrases_json`; the component is deliberately unwired** (operator decision D2). Its `ABSENT_COMPONENTS` label still reads **`P14`** — that dict names the phase supplying the *data* — and the value says the component waits for P16 | **P16** — with `subreddit_fit`, in **one** rescale |
| **`subreddit_fit`** | Absent pre-score component | **P16** |
| **T3 (P12)** | The `vec0` DDL is still unexecuted | **P15** — `SemanticIndex` |
| **DI28** | `leads` has no `run_id`. P14 opened no revision | **P17** (`0008`) |
| **DI31** | `tests/integration/` does not exist while gate row 5 names it | Operator — a documentation decision |
| **DI32** | `website.max_depth` ships unused. **P14 does not traverse**, so unchanged | A phase needing depth 2. None planned |
| **DI34** | Six broken links to `02-research-findings.md`. **None in P14's diff** | Whoever edits those four documents near the citation |
| **DI30** | 🔴 CI cannot run the ten live-database tests. **Honoured, not closed** — this phase's suite was run locally | Operator |
| **DI29** | Literal `grep` fences 2 and 3 return prose. **Re-measured: fence 2 now returns 9**, still zero imports | Unchanged |
| **DI26** | `keywords.normalise` tears decomposed Unicode apart | **P15** — alias generators inherit it |
| **DI35** | A flaky notify test, one occurrence | *A second occurrence* |
| **DI15** | An eighth job type shipped unreconciled. **P14 added none** | Unchanged |
| **O2** | `mypy` not in the gate, deferred by D6 in P8 | Its own scoped task |
| **L4 (P7)** | Notification retry — still nobody's | Open since P7 |

**One Deferred Improvement closed (DI33). One opened (DI37).**

---

## 6. Things a later phase must delete or narrow on purpose

| Phase | Test | Why it is there |
|---|---|---|
| **P15** | `test_the_competitor_registry_was_not_wired_before_p15` | *(P9's)* Unchanged — P14 did not wire it. `competitor_references` is now **persisted as a section payload**, which is the data the registry will read |
| **P15** | `test_the_payload_null_rule_is_satisfied_by_the_database_not_just_by_us` | If P15 ever adds a fourth typed table, this and `BKB_TYPED_SECTION_KEYS` and the CHECK must move **together** |
| **P16** | `test_the_three_absent_pre_score_components_are_still_absent` | **Now two of three are P16's.** When you wire `pain_phrase` and `subreddit_fit`, update `WEIGHTS` and `prescore()` in the **same** change — eight weights **rescale every stored total** ([PHASE-11-HANDOVER §4](PHASE-11-HANDOVER.md) T2) |
| **P16** | `test_no_project_row_is_created_by_this_stage` | P14's, and still true. **P16 becomes the writer** — narrow this to "the *website stage* creates none", do not delete it |
| **P16** | *(new)* | `POST /api/projects` maps `InvalidWebsiteURL` → **422** and `WebsiteUnreachable` → **502**. P14 pins that they propagate untranslated; P16 adds the response test |
| **P17** | `test_the_chain_is_still_ten_revisions_or_fewer` | Asserts **seven** revisions, last `0007`. **P14 did not change it.** `0008_targeting` makes it eight |
| **P17** | `test_leads_has_no_run_id` | P12's DI28 decision, pinned. Unchanged by P14 |
| **P20** | *(new)* | The golden-set criterion in [34 §P14](34-implementation-plan.md)'s Acceptance row is **P20's** — `golden_leads.jsonl` is P20's artefact and `golden_*` tables arrive in `0010` with P25. P14 ships the thing that makes it possible: `analyze_business` is a pure function of `(site_text, local_signals, prompt_version)`. See [P14-DECISION-ANALYSIS §D1](P14-DECISION-ANALYSIS.md) |

---

## 7. Verification snapshot at handover

| | |
|---|---|
| Full suite, **bare** | ✅ **2,161 passed · 0 failed · 2 skipped** in **466.85 s (7:46)** — P13's baseline shape (2,046 / 2) |
| Full suite, **under coverage** | ✅ **2,154 passed · 0 failed · 9 skipped** in **658.43 s (10:58)** |
| The skips | **Bare: 2** — both proxy tests with no pool on this machine. **Under coverage: 9** — the same 2 plus **7 performance tests that self-skip under a tracer by design**; those 7 **ran and passed** in the bare run. Matches P13's recorded 2-and-9 exactly; **none introduced by P14** |
| New tests | **+115** — 50 sections · 20 repository · 23 orchestration · 19 handler (**112**), plus **3** fence tests in `test_boundaries.py`. Reconciles exactly: 2,161 − P13's 2,046 = **115** |
| Coverage, whole tree | **90%** (P13: 89.55%) |
| Coverage, `src/{ai,net,scoring,knowledge}` — floor ≥85% | **90.81%** ✅ |
| Coverage, P14's own files | `knowledge/__init__` **100%** · `knowledge/bkb` **100%** · `knowledge/sections` **99%** · `repositories/knowledge` **99%** · `handlers/website` **100%** |
| `ruff check` / `format --check` | ✅ Clean · **188 files** |
| Boundary / fence suite | ✅ **54 passed** — `test_boundaries.py` **44 → 47**, P14 added 3 |
| `alembic heads` | `0007_projects_and_knowledge_base` — one head, **unchanged**; seven revisions of ten |
| `check_schema.py` | ✅ **76/76**, re-run **after** every edit |
| Legacy contract | ✅ 459 original leads · `max 164.28` · `avg 42.29` · 13 CSV columns · 17 endpoints |
| Mutation testing | **15 designed · 14 detected · 1 control · 0 survived.** **M3 survived first time** and exposed a false-passing isolation test |
| Migration | **None added.** The chain is unchanged |
| New dependency | **None** |
| AI calls, live | **0** — the suite runs offline; the live criteria are the manual guide's T5–T8 |
| Rollback | Documented and scripted in the guide (**R1**, **R2**); **executed by the operator during manual testing**, not in this session |

⚠️ **Not executable on this host, and unchanged by P14:** `mypy` (**B3**/**O2**, deferred by D6 in
P8); `pytest tests/unit` and `tests/integration` (**[DI31](DEFERRED-IMPROVEMENTS.md)** — neither
directory exists, and bare `pytest` runs everything); the literal `grep` form of the four fences
(**[DI29](DEFERRED-IMPROVEMENTS.md)**, prose matches only, zero imports).

⚠️ **Partially verified:** *"exactly one `ai_calls` row"* and *"cost < $0.05"* are verified against
`FakeProvider` and the shipped price tables — proving the **control flow and the accounting**, not
that a real response validates first time and **not an invoice**. **T5–T8 with a real key are the
only thing that closes them**, and that also closes B1 and V-1.

---

## 8. Blockers carried into P15

| ID | Blocker | Blocks P15? |
|---|---|---|
| **B1 / V-1** | **No DeepSeek credential configured on this host**, so the *offline suite* cannot take V-1's measurement. ⚠️ **Not blocked by a file** — the key is entered at **`/settings/ai`**, validated before storage and encrypted at rest (AD-12); `credentials.py:147` names the Settings page the intended path and the env var a dev fallback. Running P14's manual **T5–T8** with a real key closes B1 and V-1 | **No.** P15 makes **no new AI call** — `analyze_business` and `section_regen` both exist. P15's manual guide should follow P14's T5 pattern: enter the key in the UI, **Test connection**, then run the live steps |
| **D1/O3** | P00–P07, P09–P11 sign-off tables unsigned. **P12's and P13's are now recorded** | **No, but no tag** until P14's own guide is signed |
| **T3 (P12)** | The `vec0` branch has never executed | **Yes, in part** — `SemanticIndex` is P15 task 7, and it is the phase that must make it run or prove it no-ops |
| **DI37** | `_record_ai_call` loses its row under an open write transaction | **Only if P15 writes before it calls** — see §4 T4 |
| **DI30** | CI cannot run the ten live-database tests | **No**, but the suite must be run locally |
| **O2** | `mypy` not in the gate | **No.** Deferred by D6 in P8 |

---

## 9. Entry conditions for P15

- [ ] `docs/testing/P14-testing.md` sign-off table signed — **T5, T6, T7 and T8 especially**, or the
      *"Did you enter a DeepSeek API key on the Settings page?"* box ticked **No** and the skipped
      criteria recorded. ⚠️ **Those four are the only live verification P14 has**: everything else is
      against `FakeProvider`, which proves the control flow and the accounting but **not** that a
      real response validates first time and **not** a real cost
- [ ] **[§2 read]** — 18 guarantees, and **G1/G3/G4 are the three the phase was measured on**
- [ ] **[§3.1 read]** — 🔴 `src/knowledge/` is **inside fence 2**; the AI service is a **parameter**
- [ ] **[§3.2 read]** — the origin guard's near half already exists; build on it
- [ ] **[§3.3 read]** — the soft delete has no column and must not gain one
- [ ] **[§3.5 read]** — `bkb_evidence` is empty and the evidence is in the response, not the database
- [ ] **[§4 T1 read]** — 🔴 the lenient envelope is **deliberate**; reverting it breaks two criteria
- [ ] **[§4 T2 read]** — 🔴 the outer `except` is a backstop; assert **survivors**, not status
- [ ] **[§4 T4 read]** — [DI37](DEFERRED-IMPROVEMENTS.md): call **before** you write, or own the fix
- [ ] **[§6 read]** — `pain_phrase` moved to **P16**; do not wire it in P15
- [ ] [34 §P15](34-implementation-plan.md) read — all thirteen fields, including the **origin guard**
      and *"regenerate every section twice and lose no `reddit_learned` or `operator` row"*
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] ⚠️ **P15 opens no revision.** `0008` is **P17's**. P15 writes into tables `0007` created
- [ ] The full suite recorded green before the first change. ⚠️ **Run it locally, not from a CI
      badge** — [DI30](DEFERRED-IMPROVEMENTS.md)
- [ ] `git status` clean · `alembic heads` = one `0007` · `check_schema.py` **76/76**
- [ ] ⚠️ **`config.yaml` checked for uncommitted local values.** **P14 added the `ai.max_tokens`
      block**; nothing else in the file should have moved
- [ ] ⚠️ **If a key was entered for P14's T5–T8, it lives encrypted in `settings`, not in a file** —
      confirm P14's T9 was run: zero cleartext keys in the `settings` table, and
      `GET /api/settings/ai` returns a fingerprint rather than the key (R15, AD-12)
- [ ] `gh run list` checked: P14 green on `origin/main`
