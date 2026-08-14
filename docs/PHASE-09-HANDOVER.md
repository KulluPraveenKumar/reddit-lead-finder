# Phase 09 — Handover

**From:** P9, the rule engine (`src/rules/`) · **Written:** 2026-08-14
**To:** **P10**, and for the debts, **P11**, **P15** and **P19**

> Evidence lives in [PHASE-09-COMPLETION-REPORT.md](PHASE-09-COMPLETION-REPORT.md).
> Where the next session resumes lives in [progress/P09-COMPLETE.md](progress/P09-COMPLETE.md).

---

## 1. What now exists

Six modules under `src/rules/` — keywords, structural, authors, competitors, a neutral result type,
and a demo CLI. **Nothing imports them.** P9 built the library; **P10 is its first caller.**

No migration, no table, no column, no route. `alembic heads` is `0006_content_and_dedup`, unchanged.

---

## 2. Guarantees P10 must not break

| | Guarantee | Enforced by |
|---|---|---|
| **G1** | **`src/rules/` imports neither `src.ai` nor `hermes`** | `test_the_rules_package_is_inside_the_ai_fence`, AST-based |
| **G2** | **Deleting the package fails a test rather than silencing the fence** | `test_the_rules_package_exists`, plus `assert scanned > 0` |
| **G3** | **P9's four reasons stay a strict subset of P19's eleven** | `test_every_p9_reason_is_one_of_p19s_eleven` — the one file that may import both sides |
| **G4** | **`reject()` refuses any reason outside `REASONS`** | `ValueError`, and mutation M15 |
| **G5** | **The competitor rule stays inert until P15** | `test_the_competitor_registry_was_not_wired_before_p15`, three arms |
| **G6** | The 459 original leads and the `intent_score` fingerprint | `check_schema.py`, unchanged by P9 |
| **G7** | One head, always — and P9 added no revision | `test_single_head` |

---

## 3. ⚠️ What P10 inherits directly

**P10 is the first phase to consume `src/rules/`, and the first to extend fence 2.**

1. **`RuleResult`, not `GateDecision`.** `src/dedupe/` must return the same neutral type for the same
   reason: `GateDecision` lives in `src/ai/gate.py` and **R3** forbids the import. The adapter is
   P19's. This is the single most likely thing for a reader to "simplify" wrongly.

2. **Extend fence 2 to `src/dedupe/`, with an existence guard beside it.**
   [35 §2.1](35-testing-strategy.md) row 9 now carries a table naming which phase owns which path.
   Copy P9's pairing exactly — a fence that walks whatever is there passes vacuously the moment the
   package is deleted, which is **P5's F3, now recorded four times**.

3. **Your two reasons are `duplicate_exact` and `duplicate_near`**, spelled to match
   `RejectionReason` and **not imported from it**. Extend `REASONS` and the subset test together.

4. **`docs/34 §P10`'s acceptance says "no `src.ai` import"** — that is now a real fence, not a grep
   someone runs once.

---

## 4. Traps waiting in P10 and P11

**T1 — [DI14](DEFERRED-IMPROVEMENTS.md) fires in P10, and it fires on your keying decision.** The
live database splits **444 `old.reddit.com` / 27 `www.reddit.com`** across 471 rows. If the cascade
keys on `url`, the same post appears twice. This was flagged for P10 by P8's handover and is still
open.

**T2 — [DI22](DEFERRED-IMPROVEMENTS.md) is yours.** *"At most one group per run"* is **not expressible
in the schema** — `dedup_members` has no `run_id` and SQLite cannot constrain uniqueness across a
join. P8 deliberately shipped **no test that appears to check it**. It becomes an application-level
guarantee P10 must uphold and test.

**T3 — 🔴 [DI25](DEFERRED-IMPROVEMENTS.md): `triage.py` is discarding real leads right now.** Its
hiring pattern contains a bare `\bhiring\b`, which rejects *"Our hiring process is broken and I need a
tool to fix it"*. Found in P9 Stage 2 while writing a near-miss fixture. **P9's own pattern
deliberately omits it, so the two modules now disagree** — see DI23. The trigger is **P11**, which
owns the 2% holdout that can measure the loss; P10 should not "fix" it in passing.

**T4 — a mutation that reports *"anchor not found"* is not a pass.** Three did in this phase — one
after `ruff format` reflowed a tuple, two because the sources are CRLF and the literals assumed LF.
A driver that counts a non-applied mutation as a success is the exact failure the discipline exists
to prevent. Build anchors from the file's own newline.

**T5 — a survivor can be a *test* defect, not a code defect.** M25 survived because every test used
the default value of the setting it was checking. **The settings were plumbed and nothing proved the
plumbing carried anything.** When a survivor appears, ask what the test failed to distinguish before
asking what the code got wrong.

**T6 — the property tests are where the real defect was found.** Not the unit tests, not review — the
A5 corpus, on its first run, at 67.8 seconds of CPU. **Read "no input crashes" as "no input hangs"**:
`re` has no timeout and a catastrophic backtrack raises nothing. P10's MinHash and shingling take the
same attacker-supplied text.

**T7 — `test_whitespace_scaling_is_not_quadratic` is sized so a *reverted* fix still finishes.** A
first draft used 8,000 against 128,000 and took over fifteen minutes under mutation, producing a
harness timeout rather than a verdict. If you add a scaling guard, size it the same way.

---

## 5. Debts carried forward, by owner

| | Item | Owner |
|---|---|---|
| **DI14** | The 444/27 permalink host split | **P10** |
| **DI22** | The `dedup_members` invariant | **P10** |
| **DI23** | Two rejection vocabularies ship and disagree | **P11** |
| **DI24** | `_triage_config` reads a mapping as a list; P6 has never matched a keyword | **P11** |
| **DI25** | 🔴 `triage.py`'s bare `\bhiring\b` discards real leads | **P11** |
| **DI26** | `normalise` tears decomposed Unicode apart | **P11 or P15** |
| **DI27** | The heartbeat flake — one occurrence, never reproduced | *A second occurrence* |
| **DI20** | The `check_schema` WAL/mtime race | *A fifth occurrence, or one in CI* |
| **DI13** | `num_comments = 0` where the honest value is `None` | **P11** |
| **DI16 / T1 (P8)** | `leads.confidence_score` exists but is not populated | **P21** |
| **DI17** | Nothing enqueues `maintenance` | **P17** |
| **L4 (P7)** | Notification retry — **still nobody's** | Open since P7 |
| **O2** | `mypy`, 193 errors, deferred by D6 in P8. `src/rules/` ships clean under it | Its own scoped task |

**No DI was closed in P9.** None of the recorded triggers has been satisfied.

---

## 6. Things P15 and P19 must delete on purpose

Two tests exist specifically to **fail** when a later phase wires something up. Deleting them is the
act of enabling the feature, and must be deliberate — the discipline
[PHASE-08-HANDOVER §4 T1](PHASE-08-HANDOVER.md) demands for `notify.min_confidence_alert`.

| Phase | Test | Why it is there |
|---|---|---|
| **P15** | `test_the_competitor_registry_was_not_wired_before_p15` | A competitor rule that quietly matches nothing looks exactly like a business with no competitors, and nothing in this system reports the difference |
| **P19** | *(none yet)* | But **`evaluate()` is not `PreAIGate` and must not become it.** It composes only P9's four rules. Nothing enforces that boundary today |

---

## 7. Verification snapshot at handover

| | |
|---|---|
| Full suite | **1380 passed, 2 skipped** (P8: 1148 / 2) |
| New tests | **+232** |
| Branch coverage, `src/rules/` | **100%** — 183 statements, 60 branches |
| `ruff check` / `format --check` | Clean · 142 files |
| `alembic heads` | `0006_content_and_dedup` — one head, unchanged |
| `check_schema.py` | **51/51** |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns |
| Mutation testing | **31 designed · 31 detected · 0 survived** |
| Grep fences | Fence 2 covers **2 of 6** specified paths, and now says so |
| Rollback | **Executed**, twice |

---

## 8. Blockers carried into P10

| ID | Blocker | Blocks P10? |
|---|---|---|
| **D1/O3** | **P00–P07 manual sign-off tables unsigned.** **P8's was signed 2026-08-14** — the first in the project | **No, but no tag.** P9's own guide is unsigned until the operator runs it |
| **O2** | `mypy` not in the gate — 193 errors in 23 files | **No.** Deferred by D6 in P8 |
| **L4 (P7)** | Notification retry undelivered | **No**, still an open P7 obligation |
| **DI25** | 🔴 A live defect discarding leads | **No** — P11's, and it should not be fixed in passing |

---

## 9. Entry conditions for P10

- [ ] `docs/testing/P09-testing.md` sign-off table signed — **T2, T3 and T6 especially**
- [ ] **[§3 read]** — `RuleResult` not `GateDecision`, and fence 2 is yours to extend
- [ ] **[§4 T1/T2 read]** — DI14's permalink split and DI22's inexpressible invariant are both P10's
- [ ] **[§4 T6 read]** — property tests found this phase's only real defect; MinHash takes the same input
- [ ] **[§6 read]** — the competitor guard is P15's to delete, not P10's
- [ ] [34 §P10](34-implementation-plan.md) read — all thirteen fields, including **A5's measured
      2,000-items-under-2-seconds**, which is still unmeasured
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] The full suite recorded green before the first change — **1380 passed, 2 skipped**
- [ ] `git status` clean · `alembic heads` = one `0006` · `check_schema.py` 51/51
- [ ] `gh run list` checked: P9 green on `origin/main`
- [ ] ⚠️ **`config.yaml` checked for uncommitted local values** — it carried a real chat id at the
      start of both P8 and P9, and P9 was the first phase to edit that file since
