# Phase 09 — Completion Report

**Phase:** P9 — Rule engine · **Revision:** none — P9 adds no migration
**Implemented:** 2026-08-13 → 2026-08-14 · **Days / Risk as planned:** 2 · Low

> Backward-looking: what was built, and the evidence. What the next phase must know lives in
> [PHASE-09-HANDOVER.md](PHASE-09-HANDOVER.md); where a lost session resumes lives in
> [progress/P09-COMPLETE.md](progress/P09-COMPLETE.md).

> ⚠️ **P9 is `src/rules/` and nothing else.** It is **not** [16-phase-06.md](16-phase-06.md), which
> bundles the rule engine with the dedup cascade, entity resolution and the pre-score against
> migration `0007`. That document belongs to the **superseded** eight-phase numbering
> ([lock §2.1](EXECUTION_MODE_LOCK.md)) and maps to **P9, P10, P11 and P15**.

---

## 1. What was built

Six modules under `src/rules/`, **imported by nothing**. P9 built the library; P10 and P11 are its
first callers.

| Module | What it holds |
|---|---|
| `__init__.py` | `RuleResult`, the four-reason vocabulary, `RulesSettings`, `evaluate()` |
| `keywords.py` | `normalise`, tier matching, negative terms |
| `structural.py` | Five noise patterns, the length floor |
| `authors.py` | `[deleted]`, the known-bot set, the `*Bot` suffix, an allowlist |
| `competitors.py` | The `EntityRegistry` protocol, a dictionary fallback — **inert until P15** |
| `__main__.py` | `python -m src.rules` — the only thing in this phase a person can look at |

**No migration, no table, no column, no route, no template, no handler change.** `alembic heads`
stayed at `0006_content_and_dedup` throughout.

---

## 2. The commits, in order

| Stage | Commit | Subject |
|---|---|---|
| plan | `2832d38` | implementation review, decisions, checklist and testing guide |
| — | `f9e1ffc` | **P8's** manual testing sign-off — closed the entry-condition blocker |
| 1 | `dc0f155` | the R3 fence, before the package it constrains |
| — | `4a7b96a` | stabilize the DI18 timing test *(pulled forward from Stage 6)* |
| — | `8707f19` | measure parse cost as a ratio, not in milliseconds |
| 2 | `85cb286` | the four predicates, and the neutral type that keeps R3 intact |
| 3 | `64ad729` | competitor matching, and the registry that does not exist yet |
| 4 | `e30aafb` | the rules config block, and a rollback that runs |
| — | `e24fb90` | **fix:** catastrophic backtracking in the AMA pattern |
| 5 | `6beac44` | property tests, two performance assertions, and the demo's coverage |
| 6 | `8b83235` | the heartbeat flake, measured and registered rather than guessed at |
| 7 | `dbd7dab` | four reconciliations, and the DI20 gap closed |

Twelve commits, 28 files, +4,919 / −48. Every one CI-green before the next began.

---

## 3. Acceptance criteria

[34 §P9](34-implementation-plan.md), as reconciled in Stage 7.

| | Criterion | Evidence |
|---|---|---|
| **A1** | Four rejection predicates, reasons drawn from `RejectionReason`'s spelling; counting is P19's | `tests/test_rules_vocabulary.py` — `REASONS` is exactly the four, and is asserted a **subset** of `RejectionReason.ALL` |
| **A2** | **`grep -rn "import.*src\.ai" src/rules/` returns nothing** *(bold)* | `test_the_rules_package_is_inside_the_ai_fence` + `test_the_rules_package_exists`; mutations M1–M3 |
| **A3** | A post using only a competitor alias matches | `test_an_alias_only_post_resolves_to_the_canonical_name`, six fixtures, each asserting the canonical name is **absent** from the text |
| **A4** | Negative terms case- and punctuation-insensitive | `test_a_negative_term_matches_regardless_of_case_or_punctuation`, plus the **over-match** guard the criterion does not ask for |
| **A5** | Property test: no input crashes | `tests/test_rules_properties.py` — 40 tests, hostile corpus + 300 seeded random inputs. **Read to include "no input hangs"** |
| **A6** | Rule evaluation < 1 ms/item | `test_rule_evaluation_stays_inside_the_budget` — ~0.008 ms/item measured |
| **A7** | 100% branch coverage on rejection reasons | **100% on all six modules** — 183 statements, 60 branches, 0 missed |
| **Rollback** | `pipeline.rules_enabled: false`, **executed** | Run twice — via `--rules-enabled false` and against the real `config.yaml`; sha256 `37e88b3d36c8c890` identical before and after |

### 3.1 Universal criteria — [34 §1.2](34-implementation-plan.md)

| | Result |
|---|---|
| `ruff check` / `format --check` | Clean · 142 files |
| `pytest`, no live network | **1380 passed, 2 skipped** |
| Coverage ≥70% on new modules | **100%** |
| Four grep fences (R2–R5) | Pass — and **fence 2 gained its second real path in eight phases** |
| Migration round-trip | ➖ N/A — no revision. `alembic heads` = one, `0006`, unchanged |
| Legacy contract | 459 leads · fingerprint unchanged · 13 CSV columns · 17 endpoints — `check_schema.py` **51/51** |
| Manual guide | [testing/P09-testing.md](testing/P09-testing.md), Part B executed through Stage 6 |
| Documentation edits | Stage 7 — four reconciliations |

---

## 4. Mutation testing

**31 designed, 31 died, 0 survived** at the end. Re-run in full at Stages 5, 6 and 7.

| Set | Count | Targets |
|---|---:|---|
| Stage 2 | 15 | The fence, five pattern drops, `IGNORECASE`, two hiring widenings, three normaliser mutations, the `min_chars` boundary, the bot suffix, the closed vocabulary |
| Stage 3 | 5 | Canonical-only matching, substring-vs-token-boundary, **one per arm of the inertness guard** |
| Stage 4 | 8 | The off switch, four defaults, two settings pass-throughs, the shipped config |
| Stage 5 | 3 | Reverting the AMA fix, and rules made 3× and 64× slower |

### 4.1 Two survivors, and what they were

**M25 survived its first pass, and it was a real test defect.** Replacing
`skip_bot_authors=cfg.skip_bot_authors` with a hardcoded `True` inside `evaluate()` left the whole
suite green: every test either used the default — `True`, and so indistinguishable — or disabled the
engine entirely. **The settings were plumbed and nothing proved the plumbing carried anything.** Four
tests were added; M28 was added alongside for `min_chars`, which had the identical gap. This is the
masked-assertion class [PHASE-08-HANDOVER §4 T5](PHASE-08-HANDOVER.md) records.

**Three mutations reported *"anchor not found"* rather than a pass** — M4 after `ruff format`
reflowed a tuple, M21 and M16 because the sources are CRLF and the literals assumed LF. Each time the
driver surfaced the distinction instead of counting a non-applied mutation as a success, which is the
only reason any of them was noticed. M4 was then expanded into one variant per pattern.

---

## 5. 🔴 The defect P9 found in its own code

**`evaluate()` burned 67.8 seconds of CPU on a 100,000-space title.** Found by the A5 property test
on its first run, in Stage 5 verification.

The AMA pattern was `^\s*\[?\s*ama\b\s*\]?` — two `\s*` quantifiers separated by an optional, so on a
whitespace-only prefix the engine tries every way of splitting that run between them. `re` has no
timeout, so the failure mode is a **wedged worker, not an exception** — invisible to any test that
only catches exceptions. Post titles are attacker-supplied.

| Payload | hiring | giveaway | megathread | **ama** | promo |
|---|---|---|---|---|---|
| 2,000 spaces | 0.000s | 0.000s | 0.000s | **0.031s** | 0.000s |
| 4,000 spaces | 0.000s | 0.000s | 0.000s | **0.063s** | 0.000s |
| 8,000 spaces | 0.000s | 0.000s | 0.000s | **0.266s** | 0.000s |

Doubling the input quadrupled the time. Fixed to `^\s*(?:\[\s*)?ama\b\s*\]?`, which makes the bracket
and its trailing whitespace one optional group.

**Semantics were verified, not argued: 22,847 generated inputs compared old against new, with zero
behavioural differences.** Committed separately as `e24fb90`, a cross-stage correctness fix.

---

## 6. The performance work

Two absolute timing assertions were confronted in this phase, and they failed in **opposite**
directions. That symmetry is the phase's most transferable finding.

### 6.1 DI18 — a budget too tight to survive

`test_parse_speed_stays_inside_the_budget` failed for the **seventh** time during Stage 2's gate, at
**115.6 ms CPU** against a ~25 ms parser. Three instruments were tried:

1. **Wall clock** (shipped) — measured the machine, not the parser.
2. **CPU time, batched** — better, and still failed 3/6 under heavy load, because a contended process
   burns more of its *own* CPU for identical work. Also quantised: Windows `GetProcessTimes()`
   advertises 1e-07 resolution and ticks at **15.625 ms**, so a single parse produced exactly **two**
   distinct readings across 60 runs.
3. **A calibration ratio** — time raw `lxml` parsing of the same bytes either side of the measurement
   and assert the ratio. Load inflates both and divides out.

**Measured, `min` of 5:** quiet 0.872–1.345 · twelve busy processes 0.862–**0.980** · 2× slower
2.142+ · 3× slower 2.982+. **Load pushes the ratio *down*, so contention cannot cause a false
failure.** Ceiling 1.70 is the geometric midpoint of 1.345 and 2.142.

> **The docstring's claim that *"a regression that doubled the cost would still fail"* was false, and
> was false before this phase touched it.** Against a deliberately 2×-slowed parser on a quiet
> machine the original wall-clock form passed **5/5**. DI18 was not a good test that flaked — it was
> a weak test whose only failures were load artifacts.

### 6.2 A6 — a budget too loose to bite

Rule evaluation costs **~0.0076 ms/item** against a 1 ms budget: **~100× headroom quiet, 13× under
twelve competing processes.** An absolute budget is therefore safe *here* in a way it never was for
the parser — and 100× headroom means the budget alone first fails at roughly a **64×** regression.

So a second, additive assertion was added: a drift ratio catching **3×** reliably. **3× and not 2×**,
because measured separation between the worst normal ratio (0.258) and the cheapest 2× regression
(0.326) is only 1.26× — too narrow to place a threshold with margin on both sides.

**No threshold was weakened and none was removed.** The published 1 ms figure is asserted unchanged.

---

## 7. The flaky-test decision — D6, closed by measurement

| Test | Outcome |
|---|---|
| `test_parse_speed_stays_inside_the_budget` | **Fixed.** Reproduced on demand, cause measured, metric redesigned |
| `test_the_heartbeat_thread_extends_a_lease_while_a_handler_runs` | **Left unchanged, registered as [DI27](DEFERRED-IMPROVEMENTS.md)** |
| `test_does_not_write_to_the_database_it_checks` | **Registered as [DI20](DEFERRED-IMPROVEMENTS.md)**, filling a number reserved since 2026-08-10 |

**The heartbeat test would not reproduce: 56 runs, zero failures** — 12 quiet, 12 under twelve
competing processes, 8 with the claim window cut to **zero**, 24 with the heartbeat margin cut from
+0.40 s to **+0.02 s**. Both root causes derived from code inspection were **falsified**: the claim
lands in microseconds, and the beat's `done.wait(1.0)` and the handler's `sleep()` share a scheduler,
so their margin is proportional rather than absolute.

It was therefore left exactly as it is. [lock §3](EXECUTION_MODE_LOCK.md) step 6 requires a root cause
be *fixed*, not guessed at.

---

## 8. Verification snapshot

| | |
|---|---|
| Full suite | **1380 passed, 2 skipped** (P8: 1148 / 2) |
| New tests | **+232** |
| Branch coverage, `src/rules/` | **100%** — 183 statements, 60 branches, 0 missed |
| `ruff check` / `format --check` | Clean · 142 files |
| `alembic heads` | `0006_content_and_dedup` — one head, **unchanged all phase** |
| `check_schema.py` | **51/51** |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns |
| Mutation testing | **31 designed · 31 detected · 0 survived** |
| Grep fences | Fence 2 now covers **2 of its 6 specified paths**, and says so |
| Rollback | **Executed**, twice, including against the real `config.yaml` |
| Migration | **None.** The frozen chain is untouched |

The 2 skips are the performance tests under the coverage tracer, by design: instrumentation inflates
Python far more than C, so the ratio is not merely noisy under coverage but biased.

---

## 9. Operator decisions this phase was built on

| | Decision |
|---|---|
| **D1** | `src/rules/` owns a neutral `RuleResult`; no import of `src.ai`; the fence lands in Stage 1 |
| **D2** | Four predicates, three production-wired; counting is P19's; A1 rewritten |
| **D3** | `RejectionReason`'s spelling, granularity in `detail`; triage convergence → DI23 |
| **D4** | `src/rules/` reads `pipeline.rules_enabled` itself; demo module for manual verification |
| **D5** | `EntityRegistry` protocol + dictionary fallback + an inertness guard until P15 |
| **D6** | Fix the timing tests, register what cannot be fixed; no weakened assertions |
| — | **Mid-phase:** DI18 pulled forward from Stage 6; the metric redesigned; the AMA fix approved as a cross-stage correctness fix |

---

## 10. What P9 deliberately did **not** do

- **No migration, table or column.** The chain stays at `0006`.
- **No dedup, no pre-score, no `PreAIGate` composition, no adaptive budget** — P10, P11, P19.
- **No edit to `src/ai/gate.py`.** P19's Files row owns it.
- **No `EntityRegistry` implementation.** P15's. P9 ships the interface and a dictionary fallback.
- **No change to `src/discovery/triage.py`** — assumption A-2, and DI23/DI25.
- **No fix to `_triage_config`** — DI24.
- **No NFKC normalisation** — DI26.
- **No fuzzy or embedding resolver tiers** — P15's four-tier resolver.
- **No route, template or funnel rendering** — P11, P16.
