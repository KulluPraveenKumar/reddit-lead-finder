# P7 IMPLEMENTATION REVIEW — Notification tier

**Written:** 2026-08-10 · **Phase:** P7 (frozen numbering) · **Revision:** none · **Days / Risk:** 2 · Low
**Status:** review only. **No production code has been written.**

> ⚠️ **P7 is the notification tier.** It is **not** `docs/17-phase-07.md` ("Adaptive, Batched
> Enrichment & Explainable Confidence"), which belongs to the **superseded eight-phase numbering**
> ([lock §2.1](EXECUTION_MODE_LOCK.md), [PHASE-06-HANDOVER](PHASE-06-HANDOVER.md) line 10). That
> document maps to **P19–P22** and migration `0009` ([32 §4](32-documentation-consistency.md) row
> `[17] → S6`). `docs/testing/phase-07-testing.md` is its companion and is likewise historical.
> Reading either as P7's specification would build Stage G twelve phases early.

---

## 1. Authority ranking

When two documents disagree, the higher row wins. This ordering is used to resolve every conflict in
§2, and nothing below row 4 is treated as binding.

| # | Authority | Scope | Why it ranks here |
|---|---|---|---|
| **1** | [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) | R4, R8, R9, R15, R17, R20; AD-28, AD-29; §5 technology; §7 scope limits; §11 amendments | Self-declared binding constraint set. Amendable **only** by a failed measurement |
| **2** | [EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md) | Process: §3 workflow, §4 phase discipline, §4.1 partial delivery, §5 hygiene, §7 priorities | Governs *how* the phase is executed; cannot be traded away for scope |
| **3** | [34 §P7](34-implementation-plan.md) + [34 §1.2](34-implementation-plan.md) | Objective, Deliverables, Files, DB, Config, Depends on, 7 Tasks, Acceptance, Metrics, Rollback, Docs | "The definitive execution guide." Its **Files** row is explicitly *"a guide, not a contract"* ([34 §1.1](34-implementation-plan.md)) |
| **4** | [35 §P7](35-testing-strategy.md) | The gate; the manual row: *"Complete a run; receive one Telegram message; check `ai_calls` for zero agent rows"* | The named testing gate |
| **5** | [PHASE-06-HANDOVER.md](PHASE-06-HANDOVER.md) | §2 guarantees G1–G8, §5 traps T0–T6, §8 blockers, §9 entry conditions | Execution record of the immediate predecessor; forward-looking and specific |
| **6** | [21 §7.1](21-hermes-architecture.md) · [22 §4.12](22-hermes-skills.md) · [32 §4](32-documentation-consistency.md) · [09](09-dashboard-plan.md) | Transport table T1/T2/T3; the deterministic policy table; AD-28/AD-29 rationale; UI | Design detail. **Subordinate** — each is internally inconsistent with the freeze on at least one point (§2) |
| **7** | [SPRINT-0-MEASUREMENTS.md](SPRINT-0-MEASUREMENTS.md) | What is measured vs BLOCKED | Facts, not decisions. Constrains what may be *claimed* |
| **⛔** | `17-phase-07.md`, `testing/phase-07-testing.md`, [25](25-hermes-roadmap.md), [26](26-documentation-plan.md) | — | **Superseded / historical. Read-only, never extended** ([lock §2.1](EXECUTION_MODE_LOCK.md)) |

---

## 2. Conflicts, gaps and stale assumptions

Nine were found. **None is worked around silently.** C1, C2 and C3 are **blocking** and are analysed
as decisions in [P7-DECISION-ANALYSIS.md](P7-DECISION-ANALYSIS.md).

### 2.1 ⚠️ C1 (BLOCKING) — P7's stated dependency was never measured

[34 §P7](34-implementation-plan.md) **Depends on:** *"P3, P0 (M-5, M-9, M-10)."*

M-5, M-9 and M-10 **do not exist.** [SPRINT-0-MEASUREMENTS](SPRINT-0-MEASUREMENTS.md) F8 records
*"Track B (Hermes) is **BLOCKED** — no provider key, no Telegram token"*; §5's blocker table names
`TELEGRAM_BOT_TOKEN absent → M-5, M-9, M-10 — the notification-cost measurements`; and §9 defers
`hermes send` cost and reachability (M-5, M-9, M-10) to *"Track B."* P0's own closing recommendation
is blunter still: *"Track B is not needed until **P23**."*

So the plan simultaneously says P7 depends on three measurements and that those measurements are not
needed for sixteen more phases. **Both cannot hold.**

This matters because [21 §7.1](21-hermes-architecture.md) makes the transport choice *a function of*
M-9: T1 if *"M-9 confirms send is exposed over a network interface"*, T3 if *"M-9 unfavourable."*
With M-9 unmeasured, neither branch is entered.

**Verified independently this session:** `hermes` is **not on PATH** and appears **nowhere in
`requirements.txt`**. There is no Hermes runtime on this machine to measure, and [34 §P23](34-implementation-plan.md)
is where one arrives. `.env` contains **exactly one** key, `APP_SECRET_KEY` — no `TELEGRAM_BOT_TOKEN`
(blocker **B1**, still open).

**Resolution path, not a work-around:** T3 (direct Telegram Bot API) is described by
[21 §7.1](21-hermes-architecture.md) as *"a genuinely good fallback rather than a consolation"* that
*"removes the M-5 dependency entirely — a notification cannot cost tokens if no agent runtime is in
the path."* [34 §P0](34-implementation-plan.md)'s go/no-go note already carries the branch: *"If M-5
fails, notifications switch to transport T3."* Shipping all three implementations behind one
interface with **T3 as the default** satisfies task 3 as written and makes the unmeasured dependency
irrelevant to correctness. **See D1.**

⚠️ This is **not** the U4/DI12 situation and must not be argued as if it were. U4 was *refuted by
measurement* — the server provably never sends the headers, so the branch was unreachable and
building it would have shipped untestable dead code. M-9/M-10 are merely **unmeasured**, and both T1
and T2 are offline-testable (`responses` for T1's HTTP POST, a patched `subprocess.run` for T2).
Declining to build them would be a scope decision, not a forced one.

### 2.2 ⚠️ C2 (BLOCKING) — four documents, four different sets of notification kinds

| Source | Count | Kinds |
|---|---:|---|
| [freeze §7](ARCHITECTURE_FREEZE.md) | **5** | Unnamed — the row fixes only the *number* (first delivery 5, target 9) |
| [34 §P7](34-implementation-plan.md) task 1 | **5** | Unnamed; cites [22 §4.12](22-hermes-skills.md) |
| [22 §4.12](22-hermes-skills.md) | **6** | `gate.reached`, `run.complete`, `lead.high_confidence`, `budget.warning`, `quality.red`, `proxy.pool_degraded` |
| [21 §7.1](21-hermes-architecture.md) | **7** | run started/complete, gate reached, high-confidence lead, budget warning, quality red, daily digest, error |
| [34 §P7](34-implementation-plan.md) task 5 | — | Names **`run.failed`**, which appears in *neither* table |

Freeze §7 binds the count at five. The identities are unfixed by any authority above row 6, and rows
6's two tables disagree with each other — so the five must be *chosen*, and the choice must be
recorded.

**The discriminator is emittability at revision `0005`.** Three of [22 §4.12](22-hermes-skills.md)'s
six have no data source at this revision, verified against the schema and the code this session:

| Kind | Source it needs | Exists at `0005`? |
|---|---|---|
| `lead.high_confidence` | `leads.confidence_score` | ❌ **No.** Column arrives in `0006` (P8); populated in P21. `grep` over `src/db/models.py` finds no `confidence_score` |
| `quality.red` | `quality_snapshots` | ❌ **No.** Revision `0010` (P25) |
| `budget.warning` | An 80%-of-cap signal | ❌ **No.** `src/ai/cost.py::check_budget` raises `BudgetExceededError` at **100%** only; there is no 80% warning, and nothing in P1–P7 spends anything |

Shipping `notify.min_confidence_alert` as a configured key that nothing reads would repeat exactly
the mistake P6 refused: *"A key nothing reads is a documented capability that does not exist, so it
is absent rather than ignored"* (`config.yaml`, on `density_threshold`). **See D2.**

### 2.3 ⚠️ C3 (BLOCKING) — where a notification may be sent without re-opening the write lock

This is trap **T0**, which [PHASE-06-HANDOVER §5](PHASE-06-HANDOVER.md) names as *"the write lock,
again, and **P7 is where it returns**… P3 lost a sign-off to this; P4, P5 and P6 each had to prove
they had not re-opened it."*

**Verified mechanically.** `src/orchestration/worker.py::_handler_session` commits **after** the
handler returns:

```python
session = Session(bind=self.queue.engine, expire_on_commit=False)
try:
    yield session
    session.commit()          # ← only here
```

So any send performed inside a handler that has already dirtied its session holds SQLite's single
write lock across a network call to Telegram. `handlers/__init__.py` states the required discipline
in its own docstring: *"Such a handler commits its bookkeeping **before** the blocking call."*

Three candidate designs, and one of them is a trap of its own:

| Option | Verdict |
|---|---|
| Buffer in the handler, drain **after** commit in the worker | Requires editing `worker.py`, which is outside P7's Files row and is P2's core loop |
| A new `notify` **job type** | `handlers/__init__.py`: *"`docs/04` §2.4 names **seven** job types and **the freeze closes that list**."* A `notify` type would be an eighth |
| **Commit bookkeeping → send → record outcome, at handler boundaries** | ✅ Exactly what `handlers/__init__.py` prescribes and what `handle_discover` already does (G4). No worker change, no new job type, inside the Files row |

**See D3**, which develops the third into a design where the notification tier *reads* `run_events`
rather than being pushed to from each emitter — which also makes task 2 ("renderers **from SQL**")
and task 4 ("query-based dedup against `run_events`") the same mechanism instead of two.

### 2.4 C4 — `notification_log` is withdrawn, and two documents still key on it

[22 §4.12](22-hermes-skills.md)'s Caching row says *"`notification_log` dedup key"*, and
[21 §13](21-hermes-architecture.md) (line 898) says *"`hermes send` fails; **`notification_log`
records the error**; retried by the maintenance job."*

That table is **withdrawn and not to be reinstated** ([freeze §3](ARCHITECTURE_FREEZE.md), AD-29).
[34 §P7](34-implementation-plan.md)'s **DB** row is already correct: *"None — dedup rides on
`run_events` + the transition guard (AD-29)."*

**Resolution:** the freeze wins; both sentences are stale. P7 adds **no table and no migration**.
Recorded as a [§11.1 reconciliation](ARCHITECTURE_FREEZE.md), not an amendment — no technology, table
or decision changes; two documents transcribed a pre-withdrawal design. *(21 §13's mention of the
maintenance job retry is independently useful and is adopted — see D3.)*

### 2.5 C5 — the `notify-policy` skill contradicts R17 as written

[22 §4.12](22-hermes-skills.md) specifies a Hermes skill `notify-policy` whose purpose is to *"decide
whether an **ambiguous** event deserves an alert"*, with **AI required? Rarely** — *"~95% of events
are classified by a deterministic table"* — and a cost line of **≈ $0.02/month** in [22 §6](22-hermes-skills.md).

**R17 admits no five per cent:** *"Notifications never invoke a model."* AD-28 is equally absolute:
*"**No model is involved in a notification, ever**"* ([21 §7.1](21-hermes-architecture.md)).
[34 §P7](34-implementation-plan.md)'s acceptance criterion is *"**zero tokens consumed**"*, and
[35 §P7](35-testing-strategy.md)'s manual check is *"check `ai_calls` for **zero** agent rows."*

**Resolution:** R17 wins outright, and no conflict actually reaches P7's code. `notify-policy` is a
**Hermes skill**, and [freeze §7](ARCHITECTURE_FREEZE.md) caps first delivery at **3 skills** — it is
in the backlog, not the delivery. [22 §7](22-hermes-skills.md) already draws the line P7 must hold:
*"`telegram-notifier` — ⛔ **Not a skill**… **A skill would make every notification cost a model
call**; today they cost nothing."* P7's deterministic table therefore covers **100%** of events, and
the residual class [22 §4.12](22-hermes-skills.md) routes to a model is **suppressed by default**
per its own *"everything else → Suppress"* row. No ambiguity path is built.

### 2.6 C6 — `gate.reached`'s emission point belongs to P18, not P7

[34 §P7](34-implementation-plan.md) task 5 lists `gate.reached` in its policy table, but
[34 §P18](34-implementation-plan.md) — *"Depends on P17, **P7**"* — has **Files:** `src/notify/service.py ~`
and **task 5:** *"`gate.reached` notification with counts, rejects, estimate and a deep link"*, with
the acceptance criterion *"a gate card is delivered **exactly once per gate per run at $0.00**."*
P7's Files row contains no `run_service.py` and no review templates.

**Resolution:** P7 ships the **kind, the policy row, the renderer and the dispatch mechanism**;
**P18 wires the rich gate card** (counts, rejects, estimate, deep link) once P17 has produced
candidates to count. The gate states *are* reachable today — [freeze §11.1](ARCHITECTURE_FREEZE.md)
(2026-08-07) established that a run *"walks both review gates"* — so P7's renderer is exercisable
now against a real transition, with the fields P17 has not yet produced simply absent. This is a
**scope boundary, not a conflict**, and getting it wrong expands P7 into P18.

### 2.7 C7 — `09-dashboard-plan.md` has no §8 to modify

[34 §P7](34-implementation-plan.md) **Docs:** *"[21 §7.1] transport; **[09] new §8**."* Confirmed:
`09-dashboard-plan.md` ends at **§7 (Phasing of UI work)**. The word "new" is doing real work — P7
**authors** §8. Not a conflict; recorded so it is not read as an edit to something that exists, and
so the Docs field is not silently skipped.

### 2.8 C8 — an eighth job type already shipped, unreconciled

`handlers/__init__.py` asserts that [04 §2.4](04-system-design.md) *"names seven job types and the
freeze closes that list"*, and the registry then contains **four** entries including
`DISCOVER_JOB = "discover"`. [04 §2.4](04-system-design.md)'s table has `analyze_business`,
`validate_subreddits`, `scrape_subreddit`, `scrape_comments`, `enrich_leads`, `finalize_run`,
`maintenance` — **no `discover`.** No [§11.1](ARCHITECTURE_FREEZE.md) entry records the addition, and
`grep` over P6's completion report and handover finds no discussion of it.

**Not P7's to fix**, and P7 deliberately does **not** rely on it as precedent: D3 adds no job type,
so the question stays exactly as open as P6 left it. Raised here because it is live technical debt
that the next phase to want a job type will trip over, and because it weakens the "closed list"
argument that D3 otherwise leans on. **Recommended for DEFERRED-IMPROVEMENTS as DI15** (**Q6**).

### 2.9 C9 — R20's fourth grep fence (R4) does not exist

[34 §1.2](34-implementation-plan.md) asserts, as a **universal** acceptance criterion for **every
phase without exception**: *"All four grep fences pass ([freeze](ARCHITECTURE_FREEZE.md) R2–R5)."*

**R4** is *"`src/` never imports Hermes. The platform does not depend on the control plane"*,
enforced by *"Grep fence 3."*

**It does not exist.** `grep -i hermes` over the whole of `tests/` returns **no files**. Every phase
from P1 to P6 has claimed a criterion that has never been checked.

This is the **third occurrence of the same species**. P4 found that *"grep fence 4 was specified in
three documents and ticked as delivered in [12 §14](12-phase-02.md), **did not exist**, and failed on
seven identifiers when written."* P6's F3 states the lesson: *"a guard that cannot fail is
documentation."*

**P7 is fence 3's natural owner** — transports T1 and T2 are the first plausible reason for anything
under `src/` to reach for Hermes, and [PHASE-06-HANDOVER §5](PHASE-06-HANDOVER.md) T1 says to
*"establish the fence in the first commit, as P5 did for `src/discovery/` — retrofitting is far more
expensive."* Building it is **in scope, cheap, and reduces risk without expanding product scope.**
See §17 and **Q1** in §20.

---

## 3. P6 handover verification

Every guarantee, trap, deferral and blocker in [PHASE-06-HANDOVER.md](PHASE-06-HANDOVER.md), checked
against the tree at `99977bd` rather than recalled.

### 3.1 The eight guarantees P7 must not break

| # | Guarantee | Still applies? | P7 exposure |
|---|---|---|---|
| **G1** | `src/discovery/` imports no `src.ai` | ✅ Verified — `tests/test_boundaries.py::test_discovery_makes_no_ai_calls` + `test_the_policy_module_exists_and_is_inside_the_ai_fence` | **None.** P7 touches nothing under `src/discovery/`. The *pattern* is what P7 copies for `src/notify/` |
| **G2** | Six frozen `RedditClient` methods still return `None` on failure; do not simplify the `TransportError` catch away | ✅ Applies | **None** — P7 makes no Reddit request |
| **G3** | Malformed feed raises · empty returns `[]` · blocked raises | ✅ Applies | **None** |
| **G4** | **The write lock is never held across I/O** | ✅ **Applies, and is P7's central risk** | **Direct.** See C3 / D3 / R1. `handle_discover` is the worked precedent to copy |
| **G5** | Overflow is an error, detected **per subreddit**; one watermark row per subreddit | ✅ Applies | **Indirect** — if `discovery.overflow` becomes a kind (D2), its renderer reads `overflowed_subreddits`, which G5 guarantees is per-subreddit. A renderer that printed `subreddits[0]` would undo G5 in the UI |
| **G6** | Watermark diffs on the id set, never id comparison | ✅ Applies | **None** |
| **G7** | Two partial unique indexes, not one | ✅ Applies (`check_schema.py` asserts both) | **None** — P7 adds no index |
| **G8** | No `density_threshold` | ✅ Applies; fenced by `test_the_density_heuristic_was_not_reintroduced` | **By analogy only** — the reasoning ("a key nothing reads is a capability that does not exist") is what governs `min_confidence_alert` in C2/D2 |

### 3.2 The six traps

| # | Trap | Verified | Verdict for P7 |
|---|---|---|---|
| **T0** | The write lock, and **P7 is where it returns** | ✅ Confirmed mechanically — `worker.py::_handler_session` commits only after the handler returns (C3) | **LIVE. The phase's defining risk.** D3 exists for it; mutation M1 targets it |
| **T1** | R17 — notifications never invoke a model; establish the fence in the **first** commit | ✅ Confirmed, and worse than stated: fence **3** does not exist at all (C9) | **LIVE.** Stage 1 ships both fences before any transport code |
| **T2** | A mutation you have not run is a test you do not have; three of P6's were only added in review | ✅ Applies | **LIVE.** §10.2 designs 10; every **bold** AC gets one |
| **T2a** | **A returned flag is not a performed action** — P6 shipped `html_fallback: True` from a branch that fetched nothing | ✅ Applies | **LIVE, and acute.** `{"sent": True}` from a transport that posted nothing is the identical bug. Assert the *effect* (the recorded `notify.sent` row, the transport's captured request), never the return flag |
| **T3** | A filter that matches nothing exits successfully; unquoted `-k` selected zero tests **twice** | ✅ Applies | **LIVE** for the manual guide. Every `-k` quoted; every step asserts a **count** |
| **T4** | An expected number written from an estimate is not an expected result — four of P6's manual counts were wrong until executed | ✅ Applies | **LIVE.** Every number in `P07-testing.md` is pasted from an executed run, never predicted |
| **T5** | `reset_policy()` in any test touching egress | ✅ Applies | **LIVE if T3 ships.** A Bot API call goes through the network layer; a test that skips `reset_policy()` leaks policy state into the next test |
| **T6** | The feed is one request per ~60 s per IP | ✅ Applies | **None** — P7 makes no feed request |

### 3.3 What P6 deliberately did not do

| Not done | Owner per P6 | Still true? | P7? |
|---|---|---|---|
| Per-item stage-3 `prescores`; the 2% holdout | **P11** | ✅ | No |
| `score` / `num_comments` back-fill | P11 | ✅ | No |
| Comment expansion | P11 (needs `0006`) | ✅ | No |
| Density-adaptive body fetch | **Nobody** — deleted | ✅ | No |
| Selftext for link/media posts | Nobody | ✅ | No |
| **A scheduler process that *drives* the due-queue** | **"P7/P17 — `repo.due()` exists, nothing calls it on a timer yet"** | ✅ | ⚠️ **See §13.** [34 §P7](34-implementation-plan.md) contains no scheduler in Objective, Deliverables, Files, Tasks, Acceptance or Metrics. **P7 does not build it**; P6's "P7/P17" is a guess recorded before P7's row was re-read. Flagged, not silently absorbed |
| `_extract_search_post` host normalisation (DI14) | Deferred | ✅ | No |

### 3.4 §4 — the one narrowing P11 must pick up

Verified and unchanged: `prescores` carries `CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT
NULL))`, `check_schema.py` reports *"prescores.comment_id has no FK yet — deferred to 0006 (M8)"*,
and `tests/test_discovery_handler.py::test_p6_writes_no_prescore_rows` is the test that should fail
and be replaced when P11 acts. **Nothing in P7 touches it.** Confirmed read, per entry condition.

### 3.5 §8 — blockers carried into P7

| ID | Blocker | P6's verdict | Verified now | Blocks P7? |
|---|---|---|---|---|
| **D1** | P00–P06 manual sign-off tables unsigned | *"By the project's own rule, yes"* ([lock §4](EXECUTION_MODE_LOCK.md)); no tag created | ✅ Still unsigned | ⚠️ **Process blocker, operator's call.** Not a technical one. Raised in §12/A6 |
| **B3/O2** | `mypy` not installed | No | ✅ Still absent | No — gate check 3 remains unclaimable in full |
| **B1** | `.env` has no `TELEGRAM_BOT_TOKEN` | ⚠️ *"**Yes, for the live half.** P7 is the notification tier and its transport needs this"* | ✅ **Confirmed:** `.env` contains only `APP_SECRET_KEY`; `.env.example` has `APP_SECRET_KEY`, `FLASK_SECRET_KEY` | ⚠️ **YES for the live half only.** The entire offline half — policy, renderers, dedup, quiet hours, retry, fences, all three transports against `responses` — is fully testable without it. See D4 and `P07-testing.md` Part B |
| **A4** | Cold-start ≥95% not live-verified | No | ✅ Unchanged | No |
| **N1** | Keyword/user leads not collected by button or scheduler | No — P17's | ✅ Unchanged | No |
| ~~**N2**~~ | `pause_run`/`fail_run` indistinguishable | ✅ Closed in P6 | ✅ `TransportError` carries `retryable` | Closed |
| **C1** | R20's migration half unverified in CI | ✅ Closed | ✅ `0005` exercised up/down/up | Closed |

### 3.6 §9 — entry conditions

| Condition | State |
|---|---|
| P00–P06 sign-off tables signed | ❌ **Outstanding** (D1). Operator's call |
| §4 prescores narrowing read | ✅ §3.4 |
| [34 §P7](34-implementation-plan.md) read — all thirteen fields | ✅ Restated in §2, §4, §5, §6, §9, §10 |
| [freeze R17 and AD-28](ARCHITECTURE_FREEZE.md) read | ✅ §2.5, §17 |
| [freeze §7](ARCHITECTURE_FREEZE.md) read — **five** kinds, not nine | ✅ §2.2 / D2 |
| `TELEGRAM_BOT_TOKEN` present, **or the live half explicitly deferred** | ❌ Absent → **D4 proposes explicit deferral** |
| **T0 re-read** | ✅ §3.2, C3, D3 |
| `phase-manager` skill loaded before the first edit under `src/` | ⏳ Stage 1, at implementation time |
| Full suite recorded green before the first change | ✅ §4.3 |
| `git status` clean · one head `0005` · `check_schema.py` 31/31 | ✅ §4.3 |
| `gh run list` — P6 green on `origin/main` | ✅ §4.3 |

### 3.7 Root-cause analysis — hidden technical debt that could affect P7

Not "what P7 must build", but **what is already wrong or unproven in the tree** and could surface
during this phase. Each was verified against code, not recalled.

| # | Debt | Evidence | Effect on P7 | Action |
|---|---|---|---|---|
| **TD1** | **Transaction scope: the worker commits *after* the handler returns**, so any handler doing I/O with a dirty session holds the single write lock for the duration | `worker.py::_handler_session`; `handlers/__init__.py` docstring documents the required discipline as a *convention* | **Direct and central.** P7 is the first module whose job is network I/O from a handler | **D3** + mutation **M1** + `test_dispatch_never_holds_the_write_lock` |
| **TD2** | **Locking: the discipline is per-call-site, not structurally enforced.** Nothing prevents a future handler from sending before committing | Only `handle_discover` currently needs it, and it complies by convention | A P8+ handler could re-open T0 without any test failing | Documented precondition on `dispatch_pending` + a test that inspects the session **from inside the transport**, so the guard lives with the mechanism rather than with each caller |
| **TD3** | **Grep fence 3 (R4) does not exist**, while six phases have claimed it | `grep -i hermes tests/` → **0 files**; 85 `src/` files scanned, 0 violations | The criterion is vacuous; P7 is the first phase that could plausibly violate it | **Q1** — build it in Stage 1 |
| **TD4** | **An eighth job type shipped unreconciled** (`discover`), against a list two documents call closed | `handlers/__init__.py` vs [04 §2.4](04-system-design.md); no [§11.1](ARCHITECTURE_FREEZE.md) entry | Weakens the "closed list" argument D3 relies on | D3 adds **no** job type, so the debt is neither used nor worsened. → **DI15** / **Q6** |
| **TD5** | **Idempotency depends on `run_events` with no unique index.** AD-29 assigns dedup to `run_events`, which has `ix_run_events_run(run_id, id)` — an ordering index, not a constraint | `check_schema.py`; `models.py` | Two concurrent dispatchers could double-send | Bounded by **R8** (one worker, sole writer). Recorded as **A2**; **not** claimed as exactly-once (**A3**) |
| **TD6** | **Retry behaviour is unspecified** across the whole phase — task 6 says only *"retry on failure; failures recorded, never silent"* | [34 §P7](34-implementation-plan.md) task 6 | An unbounded retry turns one dead transport into a hot loop | **D5** fixes 1+2 attempts, 5 s timeout, then stop; `maintenance` owns anything beyond. **R6** |
| **TD7** | **Test weakness: coverage cannot see an unreachable branch.** P6's **F1** — 87% coverage over a branch nothing reached, found only by a surviving mutation | [PHASE-06-HANDOVER §6](PHASE-06-HANDOVER.md) | A policy row for a kind with no emitter would be "covered" and dead | **D2** admits only emittable kinds; every row is *driven*, not merely covered. **Q2**, **Q3** |
| **TD8** | **Test weakness: a filter matching nothing exits successfully — and prints nothing.** Verified 2026-08-10: `-q --no-header -k <no match>` produces **no output** and exit code **5** | Executed this session | A manual step could be recorded green having run nothing | Every `-k` in `P07-testing.md` is quoted **and** prints `$LASTEXITCODE`, with `exit=5` documented as a **failure** |
| **TD9** | **A wall-clock timing assertion is load-sensitive.** `test_parse_speed_stays_inside_the_budget` failed at 105.3 ms vs a 50 ms budget under concurrent load; passed in isolation | Executed this session (§4.3) | P7 has its own timing criterion (AC1) | **Q8** — monotonic clock around the dispatch call only. **R7** |
| **TD10** | **`mypy` absent for a seventh phase**, so gate check 3 has never run | Blocker **B3/O2** | The gate cannot be claimed in full | Recorded, **not claimed**. Operator decision **O2** |
| **TD11** | **Sign-off debt: P00–P06 manual tables unsigned**, which by the project's own rule blocks progression and tagging | Blocker **D1** / **O3** | Process, not technical | Stated at entry (§3.5); no tag ([lock §6.2](EXECUTION_MODE_LOCK.md)) |
| **TD12** | **`state corruption` risk is low but real: `run_events.data_json` is rendered into HTML**, and a chat id or token there would reach a template | `emit_event` redacts on the way in; R15 | A raw `chat_id` in a payload | `chat_id_hash` only — the value is never passed at all (**D5**) |

**No new migration, table, endpoint or dependency** means the usual heavy debt classes — migration
safety, data rewrite, schema drift, rollback of a data change — are **absent from P7 by
construction**. TD1 and TD3 are the two that genuinely matter.

---

## 4. Dependencies and baseline

### 4.1 Phase dependencies

| Dependency | Required by | State |
|---|---|---|
| **P3** — run service, run states, `run_events`, `RunService.transition` | 34 §P7 | ✅ **Satisfied.** Delivered 2026-08-07 |
| **P2** — `emit_event`, `RedactingFilter`, worker, `maintenance` handler | Implied by tasks 2/4/6/7 | ✅ **Satisfied** |
| **P0 (M-5, M-9, M-10)** | 34 §P7 | ❌ **NOT satisfied — never measured.** See C1 / D1 |
| **P4** — `NetworkPolicy`, `reset_policy()` | Only if T3 ships (it does) | ✅ Satisfied |
| **P6** — `overflowed_subreddits` on `discovery.poll.done` | Only if `discovery.overflow` is a kind (D2) | ✅ Satisfied |

### 4.2 Runtime dependencies

**New packages: none.** `requests` is already a dependency and is the only thing T3 needs; T1 uses the
same client; T2 uses stdlib `subprocess`. `responses` is already the test double for HTTP. This keeps
[freeze §5](ARCHITECTURE_FREEZE.md) untouched, which is a requirement, not a nicety.

### 4.3 Baseline — measured 2026-08-10, this session, on `main` @ `99977bd`

| Check | Result |
|---|---|
| `git status --porcelain` | **clean** |
| `main` vs `origin/main` | **identical** — `99977bdfaf3fb171879d30abbc9c05d4297641fd` |
| `pytest` | ✅ **887 passed, 2 skipped** |
| `pytest -W error::DeprecationWarning` | ✅ **887 passed, 2 skipped** |
| `ruff check .` | ✅ **All checks passed!** |
| `ruff format --check .` | ✅ **118 files already formatted** |
| `scripts/check_schema.py` | ✅ **OK — all 31 checks passed** |
| `alembic heads` | ✅ **`0005_discovery (head)`** — one head |
| CI on `origin/main` | ✅ **success** — run `31274309855`, *"docs(P6): record the final CI run"* |

**Baseline is green. P7 may proceed.**

⚠️ **One flake recorded honestly.** On a run launched *concurrently* with another command,
`tests/test_feed_parser.py::test_parse_speed_stays_inside_the_budget` failed:
`AssertionError: 100 entries took 105.3 ms, budget is 50 ms`. Re-run in isolation it passed
(22 passed), as did two full-suite runs. **It is a wall-clock assertion that is sensitive to machine
load, not a defect in the parser.** It is recorded because it is a live warning for P7: the phase has
its own timing criterion (*delivery p95 < 10 s*), and it must be measured with a **monotonic clock
around the dispatch call** rather than as wall-clock around a whole run under load. See R7.

---

## 5. Acceptance criteria

### 5.1 P7-specific — [34 §P7](34-implementation-plan.md), as reconciled by §2

| # | Criterion | How it is proved | Bold? |
|---|---|---|---|
| **AC1** | A completed run delivers a message **within 10 s** | Monotonic-clock assertion around dispatch from `finalize_run`; fake transport records receipt time | ✅ |
| **AC2** | **Zero tokens consumed** | `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` = **0** after a run that sent a message; plus an AST fence that `src/notify/` imports no `src.ai` | ✅ |
| **AC3** | `src/notify/renderers.py` imports neither `src.ai` **nor an HTTP client** | AST fence over the module's imports; `requests` permitted in `transport.py` **only** | ✅ |
| **AC4** | Re-running `finalize_run` after lease expiry sends **one** message, not two | 20 replays; assert exactly one `notify.sent` row and one transport call | ✅ |
| **AC5** | Transport down → **recorded**, run unaffected | Transport raises; run still reaches `COMPLETE`; a `notify.failed` `run_events` row exists at `level="error"` | |
| **AC6** | Quiet hours suppress **non-critical only** | Inside quiet hours: an exempt kind sends, a non-exempt one does not | ✅ |
| **AC7** | Bot token in **no log** | Full log capture greps clean; `TELEGRAM_BOT_TOKEN` added to `RedactingFilter` patterns and unit-tested | ✅ |
| **M1** | Token cost = **0** | = AC2 | |
| **M2** | Duplicate rate = **0 over 20 lease-expiry replays** | = AC4 | |
| **M3** | Delivery p95 **< 10 s** | = AC1, monotonic | |

### 5.2 Universal — [34 §1.2](34-implementation-plan.md), every phase

| # | Criterion | Note for P7 |
|---|---|---|
| U1 | `ruff check` · `ruff format --check` | — |
| U2 | `pytest` passes; **no live network or API calls** | Every transport test uses `responses` or a patched `subprocess`. **No live Telegram call in the suite** |
| U3 | Coverage ≥70% on new modules | `src/notify/` is not in the ≥85% list ([34 §1.2](34-implementation-plan.md) names `src/ai/`, `src/net/`, `src/scoring/`, `src/knowledge/`). Target ≥85% anyway — see **Q2** |
| U4 | **All four grep fences pass (R2–R5)** | ⚠️ **Fence 3 does not exist** (C9). P7 builds it. This criterion has been vacuous since P1 |
| U5 | `alembic upgrade head → downgrade -1 → upgrade head` on a **copy** | P7 adds no revision. Round-trip re-run unchanged on `0005`, asserting P7 did not perturb the chain |
| U6 | Legacy contract — 459 leads, `intent_score` unchanged, 17 endpoints, 13 CSV columns | Unchanged. P7 adds no endpoint |
| U7 | Manual guide generated **and executed** | `docs/testing/P07-testing.md`; live half gated on B1 (D4) |
| U8 | Documentation edits landed | [21 §7.1](21-hermes-architecture.md) transport note; **[09] new §8** (C7); [freeze §11.1](ARCHITECTURE_FREEZE.md) reconciliations for C2 and C4 |

### 5.3 [35 §P7](35-testing-strategy.md) manual row

> *"Complete a run; **receive one Telegram message**; check `ai_calls` for zero agent rows."*

The middle clause needs `TELEGRAM_BOT_TOKEN` and is the **blocking live test** (D4). The first and
third are executable today.

---

## 6. Files to create

| File | Purpose | Est. LOC |
|---|---|---:|
| `src/notify/__init__.py` | Public surface: `NotificationService`, `Kind`, `dispatch_pending` | 25 |
| `src/notify/service.py` | The deterministic policy table; quiet hours; `run_events` dedup; retry; dispatch | 200 |
| `src/notify/renderers.py` | One Markdown renderer per kind, **from SQL**. No HTTP import, no `src.ai` | 190 |
| `src/notify/transport.py` | `Transport` interface + `BotApiTransport` (T3), `ServeTransport` (T1), `SubprocessTransport` (T2), `NullTransport` | 230 |
| `tests/test_notify_policy.py` | Policy table, quiet hours, exemptions, suppression | 200 |
| `tests/test_notify_renderers.py` | Golden Markdown per kind; SQL-only sourcing; no-model fence | 180 |
| `tests/test_notify_transport.py` | All three transports offline; retry; failure recording; token redaction | 230 |
| `tests/test_notify_dispatch.py` | **T0 lock discipline**, 20-replay dedup, p95, transport-down | 210 |
| **Total new** | | **≈ 1,465** |

**Not created:** no migration, no model, no template, no endpoint, no job type, no new dependency.

## 7. Files to modify

| File | Change | Est. LOC | In [34 §P7](34-implementation-plan.md) Files row? |
|---|---|---:|---|
| `src/orchestration/handlers/finalize.py` | Dispatch after the terminal transition commits — `run.complete` / `run.failed` | +45 | ✅ `handlers/*.py ~ (emit points)` |
| `src/orchestration/run_service.py` | **`fail()` enqueues `finalize_run`**, so the failure path has a drain (**D7**) | +8 | ⚠️ **Not listed.** Required — without it `run.failed` is never delivered. Declared under [34 §1.1](34-implementation-plan.md) |
| `src/obs/logging.py` | `TELEGRAM_BOT_TOKEN` shape added to `_SECRET_PATTERNS` (task 7) | +6 | ⚠️ **Not listed.** Required by task 7; declared under [34 §1.1](34-implementation-plan.md) *"a guide, not a contract"* |
| `tests/test_boundaries.py` | **Fence 3 (R4, Hermes)** + the `src/notify/` R17 fence | +70 | ⚠️ Not listed; C9 / **Q1** |
| `config.yaml` | `notify:` block, fully commented and defaulted | +60 | ✅ |
| `docs/09-dashboard-plan.md` | **New §8** (C7) | +75 | ✅ Docs |
| `docs/21-hermes-architecture.md` | §7.1 note: shipped transport + the C1 dependency state | +12 | ✅ Docs |
| `docs/ARCHITECTURE_FREEZE.md` | §11.1 reconciliations for **C2** and **C4** | +8 | ⚠️ Required by §11.1's own rule |
| `docs/DEFERRED-IMPROVEMENTS.md` | DI15 (C8), DI16 (deferred kinds) | +6 | — |
| **Total modified** | | **≈ 347** |

⚠️ **`src/orchestration/worker.py` and `src/orchestration/handlers/discover.py` are NOT modified.**
That is the point of D3, and a diff touching either is a signal the design drifted back into C3's
trap. `discover.py` in particular already emits `discovery.overflow` to `run_events`
(`discover.py:391`) and has **exactly one commit, before the fetch** — adding a dispatch there would
require adding a commit and would perturb the transaction structure P6's G4/G5 tests assert.

⚠️ **`maintenance.py` is NOT modified either, and the reason is a finding: nothing enqueues
`maintenance`.** The only `enqueue(` call sites in `src/` are `run_service.py:298`,
`run_service.py:317` and `scrape.py:172`; `main.py schedule` enqueues *runs*. `handle_maintenance` is a
registered handler with **no driver** — the same species of gap as P6's `repo.due()`. A periodic
driver is deferred as **DI18**; **D7** solves the delivery gap without one.

## 8. Public interface changes

**No HTTP endpoint is added, changed or removed.** The 17 legacy endpoints and the P3/P6 additions are
untouched, so R20 holds by construction rather than by test luck.

```python
# src/notify/__init__.py — the whole public surface

class Kind(StrEnum):
    """The five notification kinds. Adding a sixth is a freeze §7 decision."""
    RUN_COMPLETE       = "run.complete"
    RUN_FAILED         = "run.failed"
    GATE_REACHED       = "gate.reached"
    PROXY_POOL_DEGRADED = "proxy.pool_degraded"
    DISCOVERY_OVERFLOW = "discovery.overflow"      # ← D2 decides this fifth slot

class NotificationService:
    def __init__(self, session: Session, transport: Transport | None = None,
                 settings: NotifySettings | None = None) -> None: ...

    def decide(self, kind: Kind, payload: Mapping[str, Any]) -> Decision:
        """Deterministic. No model, no I/O, no clock beyond `now`."""

    def dispatch_pending(self, run_id: int, *, now: datetime | None = None) -> list[Sent]:
        """Read run_events → decide → render → send → record. Caller has ALREADY committed."""


class Transport(Protocol):
    def send(self, *, chat_id: str, markdown: str) -> str: ...   # returns a provider message id
    @property
    def name(self) -> str: ...
```

**Contract the caller must honour, and it is load-bearing:** `dispatch_pending` is called with a
**clean session** — the caller has committed. It is documented on the method, asserted by a test that
inspects the session from inside the transport, and targeted by mutation **M1**. This is G4 restated
for a new module.

## 9. Schema changes

**None.** No table, no column, no index, no revision. `alembic heads` stays `0005_discovery`.

[34 §P7](34-implementation-plan.md) **DB:** *"None — dedup rides on `run_events` + the transition
guard (AD-29)."* AD-29 is the reason: *"`ai_calls` already carries provider, model, stage, tokens,
cost, latency and outcome; the state machine's transition guard already provides notification
idempotency."* `notification_log` is withdrawn (C4).

Two **existing** `run_events` rows carry the state, written through the existing `emit_event`:

| `event` | `level` | `data_json` |
|---|---|---|
| `notify.sent` | `info` | `{kind, transport, message_id, chat_id_hash}` |
| `notify.failed` | `error` | `{kind, transport, attempts, error}` |

`chat_id_hash`, not `chat_id`: `run_events.data_json` is rendered into an HTML page, and R15 keeps a
chat identifier out of a template. `emit_event` already redacts on the way in — this narrows further
by never passing the value at all.

## 10. Migration strategy

There is no migration. What still runs, because U5 demands it and because a phase that adds no
revision can still break the chain:

1. Copy the live DB (`data/leads.db` → a temp copy). Never operate on the original.
2. `alembic upgrade head` → `downgrade -1` → `upgrade head` on the copy.
3. `scripts/check_schema.py` — expect **31/31**, unchanged.
4. Assert **459** baseline leads and the `intent_score` fingerprint (`5.0 / 164.28 / 42.29`).
5. `alembic heads` → exactly one, `0005_discovery`.

## 11. Rollback strategy

[34 §P7](34-implementation-plan.md) **Rollback:** `notify.enabled: false`.

| Layer | Mechanism | Verified how |
|---|---|---|
| **1 — the switch** | `notify.enabled: false` → `dispatch_pending` returns `[]` before any render or I/O | Test asserts zero transport calls **and** zero `notify.*` rows |
| **2 — delete the block** | Removing `notify:` from `config.yaml` reproduces the defaults, which are `enabled: false` + `NullTransport` | Test constructs settings from `{}` |
| **3 — no token** | `BotApiTransport` with no `TELEGRAM_BOT_TOKEN` refuses **loudly at construction**, and the run is unaffected | Test asserts the run still completes |
| **4 — revert** | `git revert` the phase. No schema, no data, no endpoint changed, so there is nothing to un-migrate | — |

**Default ships `enabled: false`.** A notification tier that starts messaging a chat id nobody
configured, on upgrade, is a worse failure than one that is off until asked. This is also what makes
rollback layer 1 *the shipped state*, so it is exercised by every test run rather than only by the
rollback drill.

⚠️ [lock §4](EXECUTION_MODE_LOCK.md): rollback must be **executed and verified, not merely
documented.** Stage 7 executes it, and `P07-testing.md` Test 9 is the operator's copy.

## 12. Testing strategy

### 12.1 The gate — [35 §2](35-testing-strategy.md)

Every check, run to completion on **one uninterrupted run**: `ruff check` · `ruff format --check` ·
`mypy` *(⚠️ **not installed** — B3/O2, unclaimable, recorded as such)* · `pytest` ·
`pytest -W error::DeprecationWarning` · coverage · the **four** grep fences (fence 3 for the first
time) · `check_schema.py` · migration round-trip · legacy regression · secret scan · error paths ·
edge cases · logging validation · documentation validation.

### 12.2 Mutation discipline — every **bold** criterion

[lock §4](EXECUTION_MODE_LOCK.md) requires it; T2 says the mutations you did not write prove nothing.
Ten designed, each naming the criterion it defends and the test that must fail:

| # | Mutation | Must be caught by | Defends |
|---|---|---|---|
| **M1** | Move the send **before** the caller's commit (dirty the session, then dispatch) | `test_dispatch_never_holds_the_write_lock` | **T0 / G4 / C3** |
| **M2** | Drop the `kind` term from the dedup query (dedup on `run_id` alone) | `test_two_different_kinds_both_send` | AC4 |
| **M3** | Drop the `run_id` term from the dedup query | `test_a_second_run_is_notified_independently` | AC4 |
| **M4** | Remove the `run.failed` quiet-hours exemption | `test_quiet_hours_never_suppress_a_failure` | AC6 |
| **M5** | Invert the quiet-hours window comparison | `test_quiet_hours_boundaries` | AC6 |
| **M6** | Make `NullTransport.send` return an id without recording anything | `test_a_send_writes_a_notify_sent_row` | **T2a** |
| **M7** | Make the transport return `True` without issuing a request | `test_the_transport_actually_posted` (asserts the captured `responses` call) | **T2a** |
| **M8** | Delete `src/notify/` from the R17 fence's roots | `test_notify_invokes_no_model` fails on its own coverage assertion | AC2 / R17 |
| **M9** | Remove the `TELEGRAM_BOT_TOKEN` pattern from `RedactingFilter` | `test_bot_token_is_redacted` | AC7 |
| **M10** | Swallow the transport exception instead of recording it | `test_transport_failure_is_recorded_not_silent` | AC5 |

⚠️ Per T2, a green mutation run proves only these ten. **Q3** recommends the review pass that looks for
the eleventh.

### 12.3 Boundary and regression

- **Fence 2 (R3)** — unchanged, still green.
- **Fence 3 (R4)** — **new.** AST-based, over all of `src/`: no `import hermes`, no `from hermes …`,
  no `hermes` in an `__import__`/`importlib` call. AST, not `grep -ri`, for the reason
  [freeze §11.1](ARCHITECTURE_FREEZE.md) already records: a raw-text fence *"matches docstrings and
  comments and therefore fails against correct, shipped code."* `transport.py` **must** be free to
  explain in prose why T2 shells out to a binary it does not import.
- **New: the R17 fence** — `src/notify/` imports no `src.ai` and no agent runtime; `renderers.py`
  additionally imports no HTTP client (AC3).
- **Legacy** — 459 leads · `intent_score` fingerprint · 17 endpoints · 13 CSV columns · `GET /`.
- **`reset_policy()`** in every test that reaches the network layer (T5).

### 12.4 Manual testing

`docs/testing/P07-testing.md`, PowerShell only, every number pasted from an executed run (T4), every
`-k` quoted **and its exit code printed** (T3 — verified 2026-08-10: a zero-match filter prints
*nothing* and exits **5**, so blank output is indistinguishable from success unless the code is read).
**Eleven tests: ten executable, one BLOCKING** on B1 (D4).

---

## 13. Out-of-scope work

Named so that none of it is drifted into, and so that omission is visible rather than silent.

| Not in P7 | Owner | Authority |
|---|---|---|
| The **rich gate card** — counts, rejects, estimate, deep link | **P18** | [34 §P18](34-implementation-plan.md) task 5 + Files (C6) |
| Inbound Telegram commands (`/approve`, `/review`) | **P18** conversationally, **P23/P24** for the runtime | [21 §7.2](21-hermes-architecture.md) |
| **A scheduler that drives `repo.due()` on a timer** | **P17** *(P6 guessed "P7/P17"; P7's row has no scheduler)* | §3.3 |
| `lead.high_confidence` + `min_confidence_alert` | **P21** (needs `leads.confidence_score`, `0006`) | C2 |
| `quality.red` | **P26** (needs `quality_snapshots`, `0010`) | C2 |
| `budget.warning` at 80% | **P19/P20** (needs a spender and an 80% signal) | C2 |
| `daily-summary` digest | **P24** (`hermes cron`) | [22 §4.9](22-hermes-skills.md) |
| The `notify-policy` skill / any ambiguity path | **Backlog** — 3 skills at first delivery | C5, [freeze §7](ARCHITECTURE_FREEZE.md) |
| Kinds 6–9 | Operator request | [freeze §7](ARCHITECTURE_FREEZE.md) |
| Measuring M-5 / M-9 / M-10 | **Track B, before P23** | C1 |
| Installing `mypy` (O2), signing P00–P06 (D1), fixing `discover`'s job type (C8) | **Operator** | §3.5 |

---

## 14. Implementation order

Dependency-forced, not preference. Each stage ends green and is independently revertable.

| # | Stage | Why here |
|---|---|---|
| **1** | **Fences first** — fence 3 (R4) + the `src/notify/` R17 fence, against an empty package | T1: *"establish the fence in the first commit… retrofitting is far more expensive."* Written **before** the code they constrain, so they are proved to fail-then-pass rather than to pass vacuously (F3) |
| **2** | `Kind` + policy table + quiet hours + `NotifySettings` | Pure, no I/O, no session. The only part with zero integration risk |
| **3** | Renderers from SQL | Depend on `Kind`; independent of transport |
| **4** | `Transport` interface + all four implementations, offline | Depends on nothing above; `responses` / patched `subprocess` |
| **5** | `dispatch_pending` — dedup, retry, `notify.sent` / `notify.failed` | Needs 2, 3, 4 |
| **6** | Wire the dispatch — `finalize.py` + `run_service.fail()` (**D7**) | **The T0 stage.** Last, so the lock test runs against finished dispatch. `discover.py`, `maintenance.py` and `worker.py` untouched |
| **7** | `config.yaml`, `RedactingFilter`, docs, **executed rollback** | [lock §4](EXECUTION_MODE_LOCK.md) |

## 15. Estimated stages

**Seven**, mapped to seven commits in
[P7-IMPLEMENTATION-CHECKLIST.md](P7-IMPLEMENTATION-CHECKLIST.md) — each with its own objective,
files, tests, mutations, rollback point and validation. **No giant commit.**
[34 §P7](34-implementation-plan.md) budgets **2 engineer-days · Low risk**; the risk rating is
believable *only* because there is no migration and no endpoint — T0 is a real trap, but it has a
worked precedent in `handle_discover`.

## 16. Expected LOC

| | Lines |
|---|---:|
| New production (`src/notify/`) | ≈ 645 |
| New tests | ≈ 820 |
| Modified production | ≈ 116 |
| Modified tests (fences) | ≈ 70 |
| Config | ≈ 60 |
| Documentation | ≈ 101 |
| **Total** | **≈ 1,812** |

Test-to-production ratio ≈ **1.2 : 1**, in line with P6. New tests: **≈ 55–70**, against P6's +84 —
lower because there is no migration, no schema and no endpoint to regress.

## 17. Boundary verification

### 17.1 The four fences, mapped to the tests that enforce them

Stated as a mapping rather than asserted as a claim, because C9 is what happens when nobody checks.

| Fence | Rule | Test | State |
|---|---|---|---|
| **1** | R2 — no vendor coupling outside `src/ai/providers/` | `test_no_vendor_coupling_outside_providers`, `test_no_wire_format_details_outside_ai` | ✅ Exists |
| **2** | R3 — `rules/ dedupe/ scoring/ knowledge/ feedback/ discovery/policy.py` never import `src.ai` | `test_discovery_makes_no_ai_calls`, `test_the_policy_module_exists_and_is_inside_the_ai_fence` | ✅ Exists |
| **3** | **R4 — `src/` never imports Hermes** | **— none —** | ❌ **DOES NOT EXIST. P7 builds it** (C9) |
| **4** | R5 — `src/net/` contains no Reddit identifier | `test_the_network_layer_has_no_reddit_knowledge` | ✅ Exists (written in P4, having been ticked as delivered while absent) |

### 17.2 P7's own boundaries

| Boundary | Rule | Enforcement |
|---|---|---|
| **R17 / AD-28** | `src/notify/` imports neither `src.ai` nor an agent runtime | New AST fence; **plus** the token assertion (`ai_calls` = 0), because an import fence cannot see a subprocess |
| **AC3** | `renderers.py` imports **no HTTP client** | Per-module AST fence. `requests` lives in `transport.py` alone |
| **R4** | Nothing under `src/` imports Hermes — **including T1 and T2** | T1 is an HTTP POST to a URL; T2 is `subprocess.run(["hermes", …])`. Neither imports the package, and fence 3 keeps it that way |
| **R8** | The worker is the sole bulk writer; web routes write single rows | P7 adds no route and dispatches only from handlers |
| **R9** | Idempotent | `run_events` dedup + `finalize_run`'s existing terminal guard |
| **R15** | Secrets never reach a log, response, template or repo | `TELEGRAM_BOT_TOKEN` → `RedactingFilter`; `chat_id_hash` never the raw id |
| **R20** | Legacy contract | No endpoint, no schema, no template change |
| **G4 / T0** | The write lock is never held across I/O | `dispatch_pending` requires a clean session; asserted from inside the transport; **mutation M1** |

### 17.3 Honest limits of the fences

- An AST import fence **cannot** see `subprocess.run(["hermes", ...])`. That is deliberate — R4
  forbids a *code dependency*, and [21 §7.1](21-hermes-architecture.md) specifies T2 as a subprocess
  precisely so no import exists. The fence is therefore backed by the **token assertion**, which is
  the criterion that actually matters: zero `ai_calls` rows.
- Coverage cannot prove a branch nothing reaches (P6 **F1**: 87% coverage over an unreachable
  branch). Every policy row gets a test that **drives** it, and any row without a live emitter at
  `0005` is excluded by D2 rather than shipped unreached.

---

## 18. Assumptions

Stated because [PHASE-06-HANDOVER](PHASE-06-HANDOVER.md) **F5** is *"a specification is a hypothesis
until something executes it"* — and three of P6's specification statements were unimplementable.

| # | Assumption | Basis | If false |
|---|---|---|---|
| **A1** | Committing before the send is sufficient to release SQLite's write lock | `handlers/__init__.py` docstring; `handle_discover` ships on it; G4 asserted by a test that inspects the session mid-fetch | The whole T0 mitigation fails. **Directly tested, not assumed** — mutation M1 |
| **A2** | `run_events` is a sufficient dedup store without a unique index | AD-29 states it; `ix_run_events_run(run_id, id)` exists | Duplicates under concurrency. **Mitigated by design:** one worker, one writer (R8) |
| **A3** | Dispatch is **at-least-once**, not exactly-once | There is an irreducible window: send succeeds, process dies before the `notify.sent` write | Honest by construction. AC4 is still met because `finalize_run`'s terminal guard fires first. **This review does not claim exactly-once** |
| **A4** | A run reaching `COMPLETE` is the trigger for `run.complete` | `finalize_run` owns "the run is over" in one place | — |
| **A5** | `RunService.fail()` is the single choke point for `run.failed` | Verified: `run_service.py:348`, the only `RunState.FAILED` transition in `src/` | A second path would go undelivered. **D7** hangs the drain off this one method precisely because it is single |
| **A9** | **Late delivery is acceptable for three of the five kinds.** `gate.reached`, `proxy.pool_degraded` and `discovery.overflow` are emitted from a web route or mid-handler and are delivered when the run finalises | AC1's *"< 10 s"* is scoped to *"a **completed** run"*; `run.complete` and `run.failed` are immediate | P18 wants an *immediate* gate card and will need its own dispatch or **DI18**. **Recorded in the handover, not left to be discovered** |
| **A6** | The offline half of P7 is fully verifiable without `TELEGRAM_BOT_TOKEN` | All three transports are offline-testable | Only the live half defers. **D4** |
| **A7** | `hermes` will be absent for the whole of P7 | Verified: not on PATH, not in `requirements.txt` | T1/T2 remain unit-tested only, never live-verified. **Stated as a limit, not hidden** |
| **A8** | `notify.enabled: false` by default breaks nothing downstream | Nothing consumes notifications yet; P18 is the first consumer | — |

---

## 19. Risk assessment

| # | Risk | Sev | Mitigation | Owner |
|---|---|---|---|---|
| **R1** | **The write lock returns** — a notification sent inside a dirty transaction blocks every writer for the length of a network call | **Critical** | D3's commit-then-send; `dispatch_pending` documents a clean-session precondition; the test inspects the session **from inside the transport**; **mutation M1**; `worker.py` deliberately untouched | P7 |
| **R2** | **A flag that claims a send that never happened** (T2a, exactly P6's `html_fallback`) | **High** | Assert the effect: the captured `responses` request, the `notify.sent` row. **M6 + M7** | P7 |
| **R3** | **Fence 3 is written to pass vacuously** — the F3 failure, third occurrence | **High** | Write the fence before the module; prove it **fails** against a deliberate `import hermes`, then passes. A fence that has never failed is documentation | P7 |
| **R4** | Duplicate messages on lease expiry | Medium | Query dedup on `(run_id, kind)`; `finalize_run`'s terminal guard; 20 replays; **M2 + M3** | P7 |
| **R5** | **Bot token leaks** into a log, a `run_events` row or a template (R15, K6) | **Critical** | `RedactingFilter` pattern + unit test; `chat_id_hash` not `chat_id`; full-log grep; **M9** | P7 |
| **R6** | A retry storm turns one dead transport into a hot loop | Medium | Bounded attempts (2 retries, 1 s / 2 s), 5 s transport timeout, then `notify.failed` and stop. **No periodic sweeper exists** (D7), so there is no retry loop to run away | P7 |
| **R7** | **The p95 < 10 s assertion flakes under load** — precisely the `test_parse_speed` flake seen in §4.3 | Medium | Monotonic clock around the **dispatch call only**, not wall-clock around a run; fake transport; generous headroom; documented as load-sensitive | P7 |
| **R8** | Scope creeps into P18's gate card | Medium | C6 draws the line; §13 names it; P7 ships the kind and renderer, not the card | P7 |
| **R13** | **A kind fires on every run and the operator switches the tier off.** `proxy.pool_degraded` at *"healthy < 3"* is true on **every** run in the shipped config (`proxy.file: ''`, and P0 said buy no proxies) | **High** | **D2b** respecifies it as *a degradation recorded during this run* (`peek_notices()`), which is the signal P4 already built. Second filter added: *does the rule fire meaningfully under the shipped config?* | P7 |
| **R14** | **`run.failed` is never delivered** — `finalize_run` does not run on a failed run, and no sweeper exists | **High** | **D7 option B** — `fail()` enqueues `finalize_run`; the drain runs in the worker | P7 |
| **R9** | A kind ships whose data source does not exist → a config key nothing reads (G8's lesson) | Medium | D2 selects on emittability at `0005`; deferred kinds go to DEFERRED-IMPROVEMENTS with triggers | P7 |
| **R10** | The unmeasured M-5/M-9/M-10 dependency is quietly reinterpreted as satisfied | Medium | C1 states it plainly; D1 ships T3 by default so correctness does not depend on it; the completion report must record the dependency as **unsatisfied** | P7 |
| **R11** | `mypy` still absent → gate check 3 unclaimable for a seventh phase | Low | Recorded, not claimed. Operator decision **O2** | Operator |
| **R12** | Sign-off debt (D1) makes P7 untaggable | Low | Stated at entry (§3.5); no tag until signed ([lock §6.2](EXECUTION_MODE_LOCK.md)) | Operator |

---

## 20. Recommendations — quality improvements inside P7's scope

Eight. Each **reduces risk or improves verification without expanding product scope**, so each passes
[lock §8](EXECUTION_MODE_LOCK.md)'s four conditions. Q1–Q4 are recommended **for P7**; Q5–Q8 are
recorded rather than built, because building them would be scope creep — exactly what
[DEFERRED-IMPROVEMENTS](DEFERRED-IMPROVEMENTS.md) exists to absorb.

### Q1 — Build grep fence 3 (R4) in P7. **Strongly recommended**

The single highest-value item in this review. [34 §1.2](34-implementation-plan.md) has asserted *"all
four grep fences pass"* as a **universal** criterion since P1, and **fence 3 has never existed** (C9).
Six phases have ticked a line nobody could have checked. P7 is its natural owner — T1/T2 are the first
plausible reason for anything under `src/` to reach for Hermes.

**Risk reduced:** R4 becomes enforced instead of asserted. **Scope added:** none — it closes an
existing acceptance criterion rather than adding one. **Cost:** ≈ 35 LOC.

⚠️ **And prove it fails first.** Introduce `import hermes`, watch it go red, revert, watch it go
green. P6's **F3** — *"a guard that cannot fail is documentation"* — was its **third** occurrence, and
a fence written to pass has no evidence behind it.

### Q2 — Hold `src/notify/` to ≥85% coverage, not the ≥70% it is owed

[34 §1.2](34-implementation-plan.md) reserves ≥85% for `src/ai/`, `src/net/`, `src/scoring/`,
`src/knowledge/`. `src/notify/` is not listed, so ≥70% is the letter of the requirement. It should
still be held to 85%: it is small, has no external dependency in the test path, and every branch is
cheap to reach.

**Risk reduced:** P6's **F1** — 87% coverage over a branch nothing could reach. A high bar on a small
module makes an unreachable branch conspicuous rather than affordable. **Scope added:** none.

### Q3 — A post-Stage-6 mutation review pass

The checklist designs 17 mutations. **T2:** *"a green mutation run proves the mutations you wrote, not
the ones you did not"* — and P6's **M12–M14 were only added in review**, each covering a line no
existing mutation touched.

**Recommendation:** after Stage 6, re-read the diff hunting for the eighteenth mutation, specifically
around the two places most likely to be under-covered: the quiet-hours/exemption interaction, and the
`finalize_run` drain's interaction with an already-`notify.sent` kind on the already-terminal branch.

**Risk reduced:** the class of defect that only a mutation finds. **Scope added:** none — a review
pass, not a feature.

### Q4 — Assert the *effect*, never the returned flag

P6 shipped `html_fallback: True` from a branch that fetched nothing, and its test asserted the flag
(**T2a**). A transport returning `{"sent": True}` having posted nothing is the identical bug in a new
module, and it is the most likely single defect in P7.

**Recommendation, as a reviewable rule rather than a hope:** no test in `tests/test_notify_*.py` may
assert only a return value. Every send-path test asserts at least one of — the captured `responses`
request, the `notify.sent` row, or the recorded transport call. Mutations **M6** and **M7** exist to
enforce it.

**Risk reduced:** R2. **Scope added:** none.

### Q5 — `scripts/check_notify.py`, on the model of `check_schema.py` — **not now**

`check_schema.py` mechanised 31 schema checks and has caught real drift. The analogue would verify the
policy table against [22 §4.12](22-hermes-skills.md), the shipped kinds against
[freeze §7](ARCHITECTURE_FREEZE.md)'s count, and that every config key is read.

**Deferred.** With five kinds and one config block, the tests already cover it and a second verifier
would be a second source of truth. **Trigger:** the kind list reaches [freeze §7](ARCHITECTURE_FREEZE.md)'s
target of **9**, or a kind ships whose config key nothing reads. → **DI17**

### Q6 — Reconcile `discover`, the unreconciled eighth job type — **not P7's**

`handlers/__init__.py` states the list is closed at seven; the registry contains `discover`, which is
in neither [04 §2.4](04-system-design.md) nor any [§11.1](ARCHITECTURE_FREEZE.md) entry (C8).

**Not fixed here**, on the same reasoning P6 gave for not editing another phase's signed-off guide:
D3 adds no job type, so P7 neither needs the precedent nor worsens the debt.
**Trigger:** the next phase that wants a job type — most likely **P8/P11**. → **DI15**

### Q7 — The three deferred notification kinds, each with a trigger

`lead.high_confidence`, `quality.red` and `budget.warning` have no data source at `0005` (C2/D2).
Recording them with triggers is what stops them being silently dropped *or* silently built.
→ **DI16**, triggers tabled in [D2](P7-DECISION-ANALYSIS.md).

### Q8 — Make the timing assertion load-tolerant by construction

The baseline run (§4.3) produced a genuine instance of this failure mode:
`test_parse_speed_stays_inside_the_budget` failed at **105.3 ms against a 50 ms budget** purely
because two commands ran concurrently, and passed in isolation. P7 has its own timing criterion
(**AC1**, p95 < 10 s).

**Recommendation:** measure with `time.monotonic()` around **the dispatch call alone** — not
wall-clock around a run — with a fake transport, generous headroom, and a docstring saying the
assertion is load-sensitive. **Do not** simply raise the budget when it flakes: that is weakening an
assertion, which [lock §3](EXECUTION_MODE_LOCK.md) step 6 forbids.

**Risk reduced:** R7, and a flake that erodes trust in the suite. **Scope added:** none.

---

## 21. Verdict

**Proceed to implementation — after three blocking decisions are taken** (D1 transport set, D2 the
five kinds, D3 the dispatch point) **and one deferral is accepted** (D4, the live half, on B1).

The baseline is green on every measure. The phase adds no migration, no endpoint, no dependency and
no table, which is what makes [34 §P7](34-implementation-plan.md)'s *Low* risk rating credible. The
real work is not the feature — it is holding G4 while adding the first component whose job is to
perform network I/O from inside a job handler, and building the fence that six phases have claimed
and none has had.

**Nothing in P7 requires a [freeze §11](ARCHITECTURE_FREEZE.md) amendment.** Two
[§11.1 reconciliations](ARCHITECTURE_FREEZE.md) are proposed (C2's kind list, C4's withdrawn
`notification_log`), and both are documentation catching up with decisions already taken.

**Awaiting approval. No production code will be written until the decisions in
[P7-DECISION-ANALYSIS.md](P7-DECISION-ANALYSIS.md) are settled.**
