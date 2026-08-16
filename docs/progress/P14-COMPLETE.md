# P14 — Complete

**Phase:** P14, `analyze_business` · **Date:** 2026-08-16 · **Risk:** High (K5, the largest single call)

> The resume record. If this session is lost, **§6 is where the next one picks up.**

---

## 1. What shipped

**A website becomes 23 individually-validated sections of business knowledge, from one AI call.**

- `src/knowledge/{__init__,sections,bkb}.py` — new package, **inside grep fence 2**
- `src/db/repositories/knowledge.py` — supersede, upsert, soft delete, origin guard's near half
- `src/orchestration/handlers/website.py` — the stage (**not a job type**) and the manual-guide CLI
- `src/ai/schemas.py` ~ — the envelope made lenient; the 17 strict models moved to `src/knowledge/`
- `src/ai/service.py` ~ — `analyze_business_call()`, config-driven output budget, `ai_calls.project_id`
- `src/ai/prompts/business_intelligence.v1.md` ~ — rule 7, *an omitted signal is unobserved*
- `config.yaml` ~ — `ai.max_tokens.business_intelligence: 12000`
- `src/scoring/__init__.py` ~ — one `ABSENT_COMPONENTS` value gains a clause (**D2**); the `P14`
  prefix stays, because that dict names the phase supplying the *data*
- `tests/test_boundaries.py` ~ — fence 2 extended to `src/knowledge/`

**No migration. No new table. No new dependency. No new technology.** Head is still
`0007_projects_and_knowledge_base`; seven revisions of ten.

---

## 2. The two entry conditions, and what happened to them

1. **P13's sign-off table was blank.** Raised before any code. Recorded as signed on the operator's
   explicit instruction, on P12's precedent, with a note in the guide saying it was stamped rather
   than executed in that session.
2. **V-1.** Resolved with both halves stated: the decision was never open
   ([freeze §5](../ARCHITECTURE_FREEZE.md)), and the *offline automated suite* cannot take the
   measurement. A price-table comparison was **declined** as the technology evaluation
   [lock §2](../EXECUTION_MODE_LOCK.md) forbids. **No provider code was written.**
   ⚠️ **Corrected after the operator flagged it:** the live measurement is **not blocked by a
   missing `.env` key** — the application takes the key at **`/settings/ai`**, and running the manual
   guide's **T5–T8** with a real key is what closes B1 and V-1.

---

## 3. Six decisions, recorded in [P14-DECISION-ANALYSIS.md](../P14-DECISION-ANALYSIS.md)

| | |
|---|---|
| **D1** | The golden-set acceptance criterion is **P20's** — no golden set exists, and `golden_*` tables arrive in `0010` with P25 |
| **D2** | **Operator decision.** P14 writes `pain_points.phrases_json`; **P16** wires the component. One rescale, not two. A first attempt re-pointed the `ABSENT_COMPONENTS` label to `P16` and broke P12's assertion — **reverted, because the test was right** |
| **D3** | **DI33 closed** — unobserved markup is omitted and flagged, never sent as four empty lists |
| **D4** | Lenient envelope, strict sections — the only way *"one `ai_calls` row"* and *"one section's failure isolates"* both hold |
| **D5** | Section models live in `src/knowledge/` because **R3 requires it**; fence 2 extended to the package P14 created |
| **D6** | **DI37 opened** — `_record_ai_call` loses its row under an open write transaction. P14 is immune by calling before writing |

---

## 4. What the fences and mutations caught

**Three real defects, none of which review would reliably have found:**

1. **`src/knowledge/sections.py` imported `src.ai.schemas`** — a direct **R3** breach. Caught by
   writing the fence test the package had never had.
2. **A `BKBSettings` dataclass knew what an output budget was** — caught by
   `test_no_wire_format_details_outside_ai`.
3. **Mutation M3 survived** — the isolation test asserted `status` only, and the outer
   belt-and-braces `except` produced the same status as the item loop while losing all the section's
   content. **Fixed by strengthening the test, not by weakening the mutation.**

**Mutation testing: 15 designed · 14 detected · 1 control · 0 survived.**

---

## 4a. Measured validation

| | |
|---|---|
| `pytest` bare | **2,161 passed · 0 failed · 2 skipped** in **466.85 s (7:46)** |
| `pytest --cov` | **2,154 passed · 0 failed · 9 skipped** in **658.43 s (10:58)** |
| New tests | **+115** (50 · 20 · 23 · 19 = 112, plus 3 fence tests) |
| Coverage, whole tree | **90%** (P13: 89.55%) |
| Coverage, `src/{ai,net,scoring,knowledge}` | **90.81%** against a ≥85% floor |
| `src/knowledge/` | 100% · 100% · 99% |
| `ruff check` / `format --check` | Clean · 188 files |
| Boundary / fence suite | **54 passed** (`test_boundaries.py` 44 → 47) |
| `check_schema.py` | **76/76**, re-run after every edit |
| `alembic heads` | one — `0007_projects_and_knowledge_base` |
| Legacy contract | 459 leads · `max 164.28` · `avg 42.29` · 13 CSV · 17 endpoints |
| Doc links | **192 checked in P14's docs, 0 broken** |

**Skips explained:** bare 2 = proxy tests with no pool. Coverage 9 = those 2 plus **7 performance
tests that self-skip under a tracer by design** — and those 7 **ran and passed** in the bare run.
Matches P13's recorded 2-and-9 exactly.

**Not executable, pre-existing:** `mypy` (**B3**/**O2**, deferred by D6 in P8); `pytest tests/unit`
and `tests/integration` (**DI31** — neither exists; bare `pytest` runs everything); the literal
`grep` form of the fences (**DI29** — prose only, zero imports).

**Partially verified:** *"exactly one `ai_calls` row"* and *"cost < $0.05"* are against
`FakeProvider` — the control flow and the accounting, **not** a real response and **not** an invoice.
**T5–T8 with a real key are what close them**, and B1/V-1 with them.

---

## 5. Deferred Improvements

- **Closed:** [DI33](../DEFERRED-IMPROVEMENTS.md) — P14 was its named owner and first consumer
- **Opened:** [DI37](../DEFERRED-IMPROVEMENTS.md) — the `_record_ai_call` transaction stall
- Register now runs **DI1–DI37, no gaps**

---

## 6. ▶ Resume point

**P14 is code-complete, gate-green, documented, committed and pushed. It is NOT signed off.**

### The next action is not P15

1. **The operator runs [`docs/testing/P14-testing.md`](../testing/P14-testing.md)** — 14 steps,
   ~35 minutes with an API key and ~20 without.
   - **T5–T8 need a DeepSeek key, entered on the Settings page** (`/settings/ai` → *Paste your API
     key* → **Validate & save** → **Test connection**). They are the only steps that spend money,
     well under a cent. **The key is not a `.env` variable** — it is validated before storage and
     encrypted at rest (AD-12).
   - If there is no key, tick the *"Did you enter a DeepSeek API key on the Settings page?"* box
     **No** and record that the **live** verification of the one-call and cost criteria did not
     happen. They are covered against `FakeProvider`, which proves the control flow and the
     accounting but **not** that a real response validates first time, and **not** an invoice.
   - **Running T5–T8 with a real key closes SPRINT-0 blocker B1 and V-1.**
   - **R2 is the only destructive step**, it takes a backup first, and it is reversed in the step.
2. **Sign the table.**
3. **Then, and only then, tag:** `git tag -a v0.1.0-p14 -m "P14 complete: analyze_business"` and
   `git push origin v0.1.0-p14`. **Do not tag before the table is signed** — the tag would claim a
   verification that did not happen.
4. **Then P15** — entities, evidence, lifecycle, prefix — after explicit approval.
   Entry conditions are [PHASE-14-HANDOVER §9](../PHASE-14-HANDOVER.md).

### If the manual run finds a defect

Fix it **scoped to that defect**, re-run the gate on a single clean run, update the completion report
and this file, and re-push. That is what P13 did twice, and it is the mechanism working rather than
a setback.

### The three things P15 must read before its first edit

- **[PHASE-14-HANDOVER §3.1](../PHASE-14-HANDOVER.md)** — 🔴 `src/knowledge/` is **inside fence 2**;
  the AI service is a **parameter**, never an import
- **[§4 T1](../PHASE-14-HANDOVER.md)** — 🔴 the lenient envelope is deliberate; reverting it breaks
  two acceptance criteria at once
- **[§4 T2](../PHASE-14-HANDOVER.md)** — 🔴 the outer `except` is a backstop; assert **survivors**,
  not status
