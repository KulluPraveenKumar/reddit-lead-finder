# Phase 14 — Completion Report

**Phase:** P14, `analyze_business` · **Completed:** 2026-08-16
**Objective:** *"**One** AI call produces 23 validated BKB sections, with per-section failure
isolation"* ([34 §P14](34-implementation-plan.md))

> Backward-looking: what was built, and the evidence. Forward-looking lives in
> [PHASE-14-HANDOVER.md](PHASE-14-HANDOVER.md); the reasoning lives in
> [P14-DECISION-ANALYSIS.md](P14-DECISION-ANALYSIS.md).

---

## 1. The entry condition that was not met, and how it was resolved

**[PHASE-13-HANDOVER §9](PHASE-13-HANDOVER.md)'s first entry condition — *"`docs/testing/P13-testing.md`
sign-off table signed"* — was not met when this phase began.** The operator stated that P13 was
manually tested and signed off; the table in the file was **blank**: no PASS marks, no name, no date.

Raised before any code was written. On the operator's explicit instruction the table was recorded as
signed (Praveen, 2026-08-16), on the precedent by which **P12's table was stamped during P13's
session**. A note in `docs/testing/P13-testing.md` records that it was stamped rather than executed
in that session, because *"a generated table is not a signed one"* is that guide's own rule and the
distinction between **executed** and **attested** is the whole value of a sign-off.

**Second entry condition, resolved: V-1.** See §3.

---

## 2. What was built

```
POST-P13 world                         P14 adds
──────────────                         ────────
ExtractedSite + SiteSignals    ──►     build_local_signals()      facts, not questions (+DI33)
                                        │
                                        ▼
                               AIService.analyze_business_call()  ONE call  (R2, R10)
                                        │  └─ ai_cache hit on (fingerprint, prompt v) → ZERO calls
                                        ▼
                               validate_sections()                23 independent verdicts
                                        │                          none can raise
                                        ▼
                               KnowledgeRepository                supersede → 23 sections
                                                                   → 3 typed tables
```

### Files added — 5 production, 4 test (**112 new tests**; 3 more were added to `test_boundaries.py`)

| File | What it is |
|---|---|
| `src/knowledge/__init__.py` | The package. **Inside grep fence 2** — imports `src.ai` not at all |
| `src/knowledge/sections.py` | The 23-section registry, the 17 strict models, and per-section validation that **never raises** |
| `src/knowledge/bkb.py` | One call in, 23 persisted sections out; the L2 reuse; DI33's answer |
| `src/db/repositories/knowledge.py` | Supersede, upsert on `(project_id, slug)`, the soft delete, the origin guard's near half |
| `src/orchestration/handlers/website.py` | The stage — **not a job type** — plus the manual-guide CLI (`--dry-run`, `--show`) |
| `tests/test_knowledge_sections.py` | **50 tests** — isolation over **every one of the 23**, bounds, slugs, strictness |
| `tests/test_knowledge_repository.py` | **20 tests** — supersede, upsert, soft delete, origin guard, staleness |
| `tests/test_knowledge_bkb.py` | **23 tests** — the one-call, cost, zero-call and DI33 criteria |
| `tests/test_website_handler.py` | **19 tests** — the stage, the timeline, the CLI renderer |

### Files modified — 6, each with its reason

| File | Change | Why |
|---|---|---|
| `src/ai/schemas.py` | The envelope's four typed lists became `list[dict]`; the 17 strict models **moved out** | **D4** — a strict envelope makes *"exactly one `ai_calls` row"* and *"one section's failure isolates"* jointly unsatisfiable. **D5** — R3 forbids `src/knowledge/` importing them back |
| `src/ai/service.py` | `analyze_business_call()` added; `max_tokens` from config; `project_id` threaded onto `ai_calls` | The phase's Config row; and P14 is the first stage with a project to attribute a call to |
| `src/ai/prompts/business_intelligence.v1.md` | New rule 7 — *an omitted signal is UNOBSERVED, never ABSENT* | **D3** — DI33's answer is worthless if the model is not told what the flag means |
| `config.yaml` | `ai.max_tokens.business_intelligence: 12000` | The phase's **Config** row, verbatim |
| `src/scoring/__init__.py` | One `ABSENT_COMPONENTS` value gains a clause; **the `P14` prefix stays** | **D2**, operator decision. **No weight changed; `prescore()` untouched.** A first attempt re-pointed the prefix to `P16` and broke P12's assertion — reverted, §4.6 |
| `tests/test_boundaries.py` | Fence 2 extended to `src/knowledge/`, with its existence guard and a cross-fence pattern test | P14 **creates** the package, so P14 owns bringing it under the fence |
| `tests/conftest.py` | `bkb_payload` fixture | The counterpart to `enrichment_payload` |

**No migration. No new table. No new dependency. No new technology.** The chain stays at `0007` —
seven revisions of ten — and `test_the_chain_is_still_ten_revisions_or_fewer` remains **P17's**.

---

## 3. V-1 — resolved, with both halves stated

[34 §P14](34-implementation-plan.md)'s second dependency is *"P0 (V-1 provider decision)"*.

**As a decision it was never open.** [Freeze §5](ARCHITECTURE_FREEZE.md) fixes *"DeepSeek V4 Flash
(direct), OpenRouter failover"*, and [31 §172](31-execution-plan.md) says V-1's role explicitly:
*"27 §6.1 recommends direct; **this is the evidence**."*

**As a measurement it could not be taken *by the automated suite*.** No DeepSeek credential is
configured on this host by either route, and the suite runs offline by design (`block_network`,
[35 §2.3](35-testing-strategy.md) check 6).

⚠️ **A correction, made after the operator flagged it.** An earlier draft of this report and of the
manual guide said the live verification was blocked by the absence of a `DEEPSEEK_API_KEY` in
`.env`. **That was wrong.** The application takes the key **through the Settings page**
(`/settings/ai`), where it is validated against the provider before storage and encrypted at rest
(AD-12); `src/ai/credentials.py:147` calls the environment variable *"local-development
convenience"* and states that **"the Settings page remains the intended path."** So the live
measurement is **available to the operator through the UI** and is not blocked by any file.
[`testing/P14-testing.md`](testing/P14-testing.md) T5 was rewritten against the real UI — enter the
key, **Validate & save**, **Test connection** to confirm the answer came from the real provider,
then T5–T8. Running those steps is what closes **B1** and **V-1**.

⚠️ Separately: **[SPRINT-0 B1](SPRINT-0-MEASUREMENTS.md) itself says *"Add both to `.env`"***, which
is out of step with the shipped product for the DeepSeek key. B1 is a P0 document; correcting it is
not P14's to do, and the discrepancy is recorded in
[P14-DECISION-ANALYSIS §V-1](P14-DECISION-ANALYSIS.md) so it is not repeated.

A cost/latency/maintenance comparison was **declined rather than written**: [lock
§2](EXECUTION_MODE_LOCK.md) prohibits a technology evaluation outright, and substituting arithmetic
over published price tables for the live 8-item run V-1 specifies would put a measurement-shaped
document with no measurement in it into a repository whose amendment path turns on that distinction.

**P14 wrote no provider code and changed no default** — `deepseek.py`, `openrouter.py`, `registry.py`
and `router.py` have all shipped since P4. Full reasoning: [P14-DECISION-ANALYSIS §V-1](P14-DECISION-ANALYSIS.md).

---

## 4. Evidence

### 4.1 Gate results

**The gate is not uniformly "green", and this section does not claim it is.** Three checks are not
executable on this host for reasons that predate P14 and are recorded decisions; two criteria are
only partially verified. Each is named below with its documented reason.

#### Executed and passed

| # | Check | Result |
|---|---|---|
| 1 | `ruff check .` | ✅ **All checks passed** · 188 files |
| 2 | `ruff format --check .` | ✅ **188 files already formatted** |
| — | `pytest` (bare) | ✅ **2,161 passed · 0 failed · 2 skipped · 466.85 s (7:46)** |
| — | `pytest --cov` | ✅ **2,154 passed · 0 failed · 9 skipped · 658.43 s (10:58)** |
| 6 | Offline guarantee | ✅ `block_network` active; **no test opens a socket**. The CLI is the only live path and no test invokes it (P13's trap T7) |
| 7 | Coverage | ✅ **90% whole tree**; floor packages **90.81%** — §4.2 |
| 8 | Fence 1 — vendor coupling | ✅ AST `test_no_vendor_coupling_outside_providers` |
| 9 | Fence 2 — R3 | ✅ **Now 5 of 6 paths.** `test_the_knowledge_package_is_inside_the_ai_fence` is new |
| 10 | Fence 3 — no `hermes` in `src/` | ✅ AST-based |
| 11 | Fence 4 — no Reddit in `src/net/` | ✅ AST-based |
| — | Boundary / fence suite | ✅ **54 passed** across the two boundary files — `test_boundaries.py` **44 → 47** (P14 added 3) |
| 12 | Migration / heads | ✅ `alembic heads` = **one**, `0007_projects_and_knowledge_base`. **P14 adds no revision** |
| — | `check_schema.py` | ✅ **76/76** on the live database, re-run **after** every edit |
| 13 | Legacy contract | ✅ **5 legacy tests passed** · 459 original leads present · `max 164.28` · `avg 42.29` · 13 CSV columns · 17 endpoints |
| 14 | Secret scan | ✅ 0 matches across the phase's source and `config.yaml`; `git check-ignore` proves `.env` and `data/leads.db` are ignored |
| 15 | Error paths | ✅ `InvalidWebsiteURL` (422) and `WebsiteUnreachable` (502) propagate untranslated; unknown project raises; over-budget logs and does not raise |
| 16 | Edge cases | ✅ Empty response, `None` sections, wrong container type, non-strings in a string list, duplicate slugs, bounds at and beyond the limit |
| 17 | Logging | ✅ Reuse, over-budget and non-`website`-origin rows each log; redaction filter unchanged |
| 18 | Documentation | ✅ Docs landed (§5); **110 relative links checked in the files P14 wrote, 0 broken** |

**9 skips, all accounted for and none introduced by P14:** 7 are performance tests that self-skip
under a tracer **by design** (4 in `test_dedupe_performance.py`, 2 in `test_rules_performance.py`, 1
in `test_feed_parser.py` — their budgets are asserted on the uninstrumented run, and padding them to
survive coverage would stop them meaning what [34 §P10](34-implementation-plan.md) says); 2 are
proxy tests with no pool configured on this machine. This matches P13's recorded coverage-run
baseline of 9 exactly.

#### Not executable — pre-existing, documented, untouched by P14

| # | Check | Why, and whose decision |
|---|---|---|
| 3 | `mypy src/ --ignore-missing-imports` | **Not installed.** Blocker **B3** / open decision **O2**, deferred by operator decision **D6 in P8**. P14 neither added nor removed this gap |
| 4 | `pytest tests/unit` | **Directory does not exist** — [DI31](DEFERRED-IMPROVEMENTS.md). It *errors* (exit 4) rather than passing vacuously |
| 5 | `pytest tests/integration` | **Directory does not exist** — [DI31](DEFERRED-IMPROVEMENTS.md). Every integration-shaped test lives flat in `tests/`, which is the shipped convention; **bare `pytest` runs all of them** |
| 8–11 | The **literal `grep` form** of the four fences | [DI29](DEFERRED-IMPROVEMENTS.md) and [freeze §11.1](ARCHITECTURE_FREEZE.md): they match docstrings that name the boundary they forbid. Re-measured — fence 2 now returns **9** (was 6), the three new ones being sentences in `src/knowledge/` stating the package does *not* import the AI layer. **Zero actual imports.** The AST tests above are the shipped enforcement |
| — | Live-database round-trip in CI | [DI30](DEFERRED-IMPROVEMENTS.md) — `data/leads.db` is correctly gitignored, so those ten tests skip on a fresh checkout. **They ran locally here**, which is why this run was done on this machine and not read off a CI badge |

#### Partially verified — live provider not exercised

| Criterion | What was verified | What was **not** |
|---|---|---|
| **Exactly one `ai_calls` row per analysis** | Against `FakeProvider`: the lenient envelope validates in one attempt, the repair ladder is not entered, exactly one row is written and it carries `project_id` | **That a real DeepSeek response validates on the first attempt.** Requires a key |
| **Total cost < $0.05, displayed** | The accounting arithmetic and the display path, using `src/ai/cost.py`'s shipped price tables and `FakeProvider`'s token counts | **A real invoice.** The token counts are fictional. Requires a key |

Both are closed by the manual guide's **T5–T8**, which walk the operator through entering a key at
**`/settings/ai`**, confirming with **Test connection** that the answer came from the real provider,
and re-checking both criteria against it. The sign-off carries an explicit *"Did you enter a DeepSeek
API key on the Settings page?"* box, so a skip is **recorded rather than silent**. Running those
steps also closes **SPRINT-0 B1** and **V-1** — see §3.

### 4.2 Coverage

Measured on the final run, not estimated.

| Scope | Statements | Missed | Coverage |
|---|---|---|---|
| **Whole tree** | 9,884 | 992 | **90%** (P13: 89.55%) |
| **Floor packages** `src/{ai,net,scoring,knowledge}` — **≥85% required** | 4,558 | 419 | **90.81%** ✅ |
| `src/ai` | 2,480 | 291 | 88.27% |
| `src/net` | 1,367 | 118 | 91.37% |
| `src/scoring` | 419 | 7 | 98.33% |
| **`src/knowledge`** | 292 | 3 | **98.97%** |

P14's own files:

| File | Coverage |
|---|---|
| `src/knowledge/__init__.py` | **100%** |
| `src/knowledge/bkb.py` | **100%** |
| `src/knowledge/sections.py` | **99%** |
| `src/db/repositories/knowledge.py` | **99%** |
| `src/orchestration/handlers/website.py` | **100%** — was 71% until §4.5 F2; `main()` is `pragma: no cover` as the only live-network path |

### 4.3 Mutation testing — 15 designed · 14 detected · 1 control · **0 survived**

Every **bold** acceptance criterion, plus the fences.

| # | What was broken | Verdict |
|---|---|---|
| M1 | Envelope made strict again → the repair ladder returns | **DETECTED** |
| M2 | L2 reuse removed | **DETECTED** |
| M3 | A section failure allowed to escape | **DETECTED** *(see below)* |
| M4 | Bounds check dropped | **DETECTED** |
| M5 | Empty markup lists emitted instead of the flag | **DETECTED** |
| M6 | Duplicate-slug detection dropped | **DETECTED** |
| M7 | `src/knowledge/` imports `src.ai` | **DETECTED** |
| M8 | A write hoisted above the model call | **DETECTED** |
| M9 | A payload written for a typed section | **DETECTED** |
| M10 | Supersede skipped | **DETECTED** |
| M11 | An operator-edited row overwritten | **DETECTED** |
| M12 | Staleness policy skipped | **DETECTED** |
| M13 | `ai_calls.project_id` dropped | **DETECTED** |
| M14 | `phrases_json` left unwritten | **DETECTED** |
| M15 | **Control** — a comment change | **CONTROL-OK** (nothing failed) |

**M3 survived on the first run, and that is this phase's one real false-passing test.**
`_validate_one` wraps the item loop in a belt-and-braces `except Exception`, so re-raising inside
`_validate_items` still produced `status='incomplete'` — an identical **status** with entirely
different **content**: the backstop loses the whole section, the item loop keeps the valid entries.
The isolation test asserted only the status, so it could not tell the two apart.

**Fixed by strengthening the test, not by weakening the mutation:** the payload now carries two
personas, the assertion names the survivor, and a second test —
`test_the_outer_backstop_is_a_backstop_and_not_the_working_path` — pins the distinction directly. M3
then **DETECTED**. This is the fifth false-passing test the mutation discipline has caught in this
repository.

### 4.4 The one design defect the fences caught before review did

`src/knowledge/bkb.py` was first written with a `BKBSettings` dataclass reading the phase's config
key. `test_no_wire_format_details_outside_ai` rejected it: **business logic must not know what the
provider's wire knobs are.** It was right. The key is now read by `AIService.analyze_business_call`
and the knowledge layer passes no budget at all. The Config row is still honoured — the key ships,
is read, and its default is asserted where it is read.

Separately, the first draft of `src/knowledge/sections.py` **imported its models from
`src/ai/schemas.py`, which is a direct R3 violation.** Caught by writing the fence test the package
had never had. See [P14-DECISION-ANALYSIS §D5](P14-DECISION-ANALYSIS.md).

### 4.5 Two fixes made during validation

The first full run under coverage returned **1 failed, 2149 passed, 9 skipped in 1037.97 s**. Both
issues below were fixed and the suite re-run from a clean state.

**F1 — `test_the_three_absent_pre_score_components_are_still_absent` failed, and the phase's edit was
the defect.** It asserts `ABSENT_COMPONENTS["pain_phrase"].startswith("P14")`. P14's first
implementation of decision **D2** re-pointed that label to `"P16"`.

**The test was right.** The dict's own docstring, shipped by P12, fixes the convention: *"Each entry
now names the phase that supplies the **data**, not the phase that supplies the column"* — and under
it `pain_phrase` **is** P14's, because `analyze_business` writes `phrases_json`. Re-pointing the
prefix silently changed a shipped convention in order to record a fact the value text could carry on
its own. **The prefix was restored and a clause added instead; P12's assertion is untouched and no
test was weakened.** This is the outcome [lock §3](EXECUTION_MODE_LOCK.md) step 6 requires — fix the
root cause, never the assertion — with the root cause being P14's edit.

**F2 — `src/orchestration/handlers/website.py` was at 71%, and `render_stored` was entirely
untested.** That function is what the manual guide's **T6 and T8 read**, and untested rendering
behind a manual step is [P13's trap T9](PHASE-13-HANDOVER.md) in a new place: a guide that tells an
operator to compare against output nobody has checked teaches them to accept whatever appears. Four
tests were added — the full report, the incomplete-section path, the no-BKB-yet path, and the two
injection seams whose default construction every other test replaces. **71% → 100%.**

Neither fix touched production behaviour beyond the one `ABSENT_COMPONENTS` string.

### 4.6 Verification snapshot

| | |
|---|---|
| Full suite, **bare** | **2,161 passed · 0 failed · 2 skipped** in **466.85 s (7:46)** |
| Full suite, **under coverage** | **2,154 passed · 0 failed · 9 skipped** in **658.43 s (10:58)** |
| New tests | **+115** (50 · 20 · 23 · 19 = 112, plus 3 fence tests) |
| Coverage, whole tree | **90%** (P13: 89.55%) |
| Coverage, floor packages | **90.81%** against a **≥85%** floor |
| `ruff check` / `format --check` | Clean · 188 files |
| Boundary / fence suite | **54 passed**; `test_boundaries.py` 44 → 47 |
| `check_schema.py` | **76/76** |
| `alembic heads` | one — `0007_projects_and_knowledge_base` |
| Legacy contract | 459 leads · `max 164.28` · `avg 42.29` · 13 CSV columns · 17 endpoints |
| Mutation testing | 15 · 14 detected · 1 control · **0 survived** |
| New dependency | **None** |
| Migration | **None** |

> ℹ️ **On the boundary count.** [PHASE-13-HANDOVER §7](PHASE-13-HANDOVER.md) records *"81 passed"*
> for this metric. I could not reproduce 81 under any definition I tried, and **report what I
> measured** rather than restate it: **54** across the two boundary files
> (`test_boundaries.py` + `test_notify_boundaries_p6.py`), with `test_boundaries.py` going 44 → 47.
> The discrepancy is in the *counting*, not in the enforcement — all four fences pass.

---

## 5. Documentation

| Document | Change |
|---|---|
| [P14-DECISION-ANALYSIS.md](P14-DECISION-ANALYSIS.md) | **New.** V-1 and six decisions |
| [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) | **DI33 closed** and moved to §3; **DI37 opened**; DI29's counts re-measured; register now runs DI1–DI37 |
| [testing/P14-testing.md](testing/P14-testing.md) | **New.** 14 steps, an API-key-optional split, and a rollback that is executed |
| [testing/P13-testing.md](testing/P13-testing.md) | Sign-off table recorded — §1 |
| [PHASE-14-HANDOVER.md](PHASE-14-HANDOVER.md) | **New** |
| [progress/P14-COMPLETE.md](progress/P14-COMPLETE.md) | **New** |
| [README.md](README.md) | Execution table updated |

**[34 §P14](34-implementation-plan.md)'s Docs row** names [06 §3](06-ai-pipeline.md) and makes
[06d](06d-ai-budget-and-scale.md) the cost authority. Both are **unchanged**, deliberately: nothing
P14 measured contradicts either, and editing a frozen document without a contradiction to record is
what [lock §2](EXECUTION_MODE_LOCK.md) prohibits.

---

## 6. Deferred Improvements

| | |
|---|---|
| **Closed** | **[DI33](DEFERRED-IMPROVEMENTS.md)** — a cache hit yields no markup. P14 was its named owner and its first consumer; the answer is that the markup signals are **omitted with a flag**, never sent empty |
| **Opened** | **[DI37](DEFERRED-IMPROVEMENTS.md)** — `_record_ai_call` writes through its own session, so a caller holding a write transaction loses the row after a full `busy_timeout` stall. Found by accident, measured at 21.6 s per affected test. **P14 is immune by construction** and pins the ordering |
| **Considered, not acted on** | DI31 (test-layout decision is the operator's), DI32 (`max_depth` still unused — P14 does not traverse), DI34 (six broken links, none in P14's diff), DI29 (re-measured, not fixed — [35](35-testing-strategy.md) is frozen) |

---

## 7. Phase discipline — [lock §4](EXECUTION_MODE_LOCK.md), line by line

| | Line | State |
|---|---|---|
| ✅ | Implementation complete — every deliverable in the phase's row | Done |
| ✅ | Automated tests passing — one clean run | **2,161 / 0 / 2** bare and **2,154 / 0 / 9** under coverage, after two fixes (§4.5) |
| ✅ | Mutation discipline on every **bold** criterion | 15 · 14 detected · 1 control · **0 survived** |
| ✅ | Manual testing guide written | [testing/P14-testing.md](testing/P14-testing.md) — 14 steps |
| ⬜ | **Manual testing completed and signed off by a human** | **NOT DONE.** This is the gate between P14 and P15 |
| ✅ | Documentation updated — the phase's **Docs** field | §5 |
| ✅ | Progress updated | [progress/P14-COMPLETE.md](progress/P14-COMPLETE.md) |
| ⬜ | **Rollback executed and verified** | **Scripted, not executed.** R1 and R2 are the operator's during manual testing — R2 deletes a project and needs one to exist, which only a live T5 creates |
| ✅ | Repository hygiene reviewed — [lock §5](EXECUTION_MODE_LOCK.md) H1–H8 | 22 intended paths; `.env` and `data/leads.db` ignore rules **printed, not assumed**; zero `.db` files tracked |
| ✅ | Committed · pushed | See the phase commit |
| ⬜ | Tagged | **Deliberately not.** [lock §6.2](EXECUTION_MODE_LOCK.md): tagging an unsigned phase would claim a verification that did not happen |
| ✅ | Legacy contract intact | 459 leads · `intent_score` unchanged · 13 CSV columns · 17 endpoints |
| ✅ | No unresolved blockers **for P15** | §6; B1/V-1 is closable by the operator through the UI |

**Three lines are open, and all three are the operator's:** the manual run, the rollback it
contains, and the tag that follows a signed table. **P14 is complete as an implementation and is not
signed off.**

*(Snapshot table: [PHASE-14-HANDOVER §7](PHASE-14-HANDOVER.md).)*
