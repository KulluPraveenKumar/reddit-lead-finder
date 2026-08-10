# P7 DECISION ANALYSIS — Notification tier

**Written:** 2026-08-10 · Companion to [P7-IMPLEMENTATION-REVIEW.md](P7-IMPLEMENTATION-REVIEW.md)

> Eight decisions. **Six are BLOCKING** — D1, D2, **D2b**, D3, **D7**, D4 — and implementation does not
> begin until they are answered. D2b and D7 were **found by verifying D2 and D3 against the code**
> rather than by reading the documents: one rule fires on every run in the shipped configuration, and
> one of the five kinds had no delivery path at all. Both are recorded rather than quietly patched.
>
> D5 and D6 are constants that must be *chosen*, not defaulted into: P6's **F4** records
> that *"an unspecified constant is a decision, and it belongs in the docstring"*, and that the obvious
> choice there erased a distinction the code was making.
>
> Nothing here is chosen silently. Where a recommendation is made, the reason it beats the
> alternatives is stated, and so is what it costs.

---

## D1 — Which transports ship, and which is the default

### 🔴 BLOCKING

**The conflict.** [34 §P7](34-implementation-plan.md) task 3: *"Transport interface + T1 (`hermes
serve`) / T2 (subprocess) / T3 (**direct Bot API**), selected by config."*
[21 §7.1](21-hermes-architecture.md) makes the *choice between them* a function of measurement M-9 —
and **M-9 was never taken.** [SPRINT-0-MEASUREMENTS](SPRINT-0-MEASUREMENTS.md) F8: *"Track B (Hermes)
is **BLOCKED**"*; §9 defers M-5/M-9/M-10 to Track B; the closing recommendation says *"Track B is not
needed until **P23**."* Meanwhile [34 §P7](34-implementation-plan.md) lists those three measurements
as a dependency. Both cannot hold (review C1).

**Verified this session:** `hermes` is not on PATH and is not in `requirements.txt`. There is no
runtime to measure and none arrives before [P23](34-implementation-plan.md).

### Options

| | Option | Pros | Cons |
|---|---|---|---|
| **A** | **Ship all three behind the interface; default `T3`** | Satisfies task 3 **as written** and [21 §7.1](21-hermes-architecture.md)'s *"one interface, three impls"* verbatim · T3 is *"zero cost **by construction** — no Hermes involvement at all"* and *"removes the M-5 dependency entirely"* · all three are offline-testable (`responses` for T1, patched `subprocess` for T2) · **the decision becomes a config value rather than a rewrite**, which is 21 §7.1's stated purpose · when Track B runs before P23, switching to T1 is one config key | T1 and T2 are never **live**-verified in P7 (A7) · ~120 LOC that no manual test exercises end to end |
| **B** | **Ship T3 only**; add T1/T2 when Track B measures | Least code · nothing unverifiable ships · superficially echoes the U4/DI12 precedent | ⛔ **The U4 analogy is false and must not be used.** U4 was *refuted* — the header provably never arrives, so the branch was unreachable. M-9 is merely **unmeasured**, and T1/T2 are both testable offline · contradicts task 3 · the retrofit is a rewrite of the seam, which is the exact cost 21 §7.1 designed the interface to avoid · P4's `ManagedProxyProvider` is the counter-precedent: shipped, config-only, no vendor bought |
| **C** | **Ship T2 as default** (co-located subprocess) | Closest to [21 §7.2](21-hermes-architecture.md)'s worked diagram | ⛔ **Cannot work.** `hermes` is not installed — the default would fail on every send · 21 §7.1 itself calls T2 *"H1-only. Adequate for the phase, not for production"* · makes the phase's headline criterion unachievable |
| **D** | **Defer P7** until Track B is run | Removes C1 entirely | ⛔ Needs a `DEEPSEEK_API_KEY` and a Telegram token the operator has not supplied, to unblock a phase that **does not need a model at all** · contradicts P0's own *"not needed until P23"* · blocks P18, which depends on P7 · a phase whose whole point is *zero* AI cost would be gated on an AI credential |

### ✅ Recommendation — **Option A**

**Why.** It is the only option that satisfies both frozen texts without reinterpreting either. The
unmeasured dependency is then *irrelevant to correctness* rather than worked around: T3 needs no
Hermes, so a notification cannot cost a token no matter what M-5 would have said.
[34 §P0](34-implementation-plan.md) already carries the branch — *"If M-5 fails, notifications switch
to transport T3"* — and an unmeasured M-5 is strictly weaker evidence than a failed one, so the same
fallback applies with more reason, not less.

**What it costs, stated plainly.** T1 and T2 ship unit-tested and **never live-verified**. That is
recorded as assumption **A7** and must appear in the completion report as a limit, not be quietly
omitted.

**Impact.** `transport.py` ≈ 230 LOC, four implementations (T1, T2, T3, `NullTransport`).
`notify.transport: null` is the shipped default (see D4); `bot_api` is the default *once a token
exists*. Zero new dependencies — `requests` is already present.

**⚠️ The C1 dependency remains formally UNSATISFIED and must be reported as such.** This decision
routes around it; it does not close it. Track B still owes M-5, M-9 and M-10 before P23.

---

## D2 — Which five notification kinds

### 🔴 BLOCKING

**The conflict.** [freeze §7](ARCHITECTURE_FREEZE.md) fixes **5** kinds at first delivery (target 9)
but names none. [22 §4.12](22-hermes-skills.md) lists **6**. [21 §7.1](21-hermes-architecture.md)
lists **7**. [34 §P7](34-implementation-plan.md) task 1 says **5** and cites the table with 6, while
its own task 5 names **`run.failed`**, which is in neither table (review C2).

**The discriminator: can the kind actually fire at revision `0005`?** Verified against the schema and
the code, not recalled:

| Candidate | Data source | Available at `0005`? |
|---|---|---|
| `run.complete` | `runs.state = COMPLETE`, `finalize_run` | ✅ **Yes** |
| `run.failed` | `RunService.fail()` → `RunState.FAILED` (`run_service.py:348`, the only such transition) | ✅ **Yes** |
| `gate.reached` | `AWAITING_*_REVIEW`; [freeze §11.1](ARCHITECTURE_FREEZE.md) 2026-08-07 — a run *"walks both review gates"* | ✅ **Yes** (rich card is P18's — C6) |
| `proxy.pool_degraded` | P4's `policy.peek_notices()` + `ProxySnapshot.degraded/healthy`, already surfaced at `/health` | ✅ **Yes** |
| `discovery.overflow` | P6's `overflow` + `overflowed_subreddits` on `discovery.poll.done` | ✅ **Yes** |
| `lead.high_confidence` | `leads.confidence_score` | ❌ Column is `0006` (P8); populated **P21** |
| `quality.red` | `quality_snapshots` | ❌ Revision `0010` (**P25/P26**) |
| `budget.warning` | An 80%-of-cap signal | ❌ `src/ai/cost.py::check_budget` raises at **100%** only; no 80% signal exists, and **nothing in P1–P7 spends anything** |

**The governing precedent** is P6's own `config.yaml` note on `density_threshold`: *"A key nothing
reads is a documented capability that does not exist, so it is absent rather than ignored."*
Shipping `notify.min_confidence_alert` for a column that does not exist repeats that mistake exactly.

### Options

| | Option | Pros | Cons |
|---|---|---|---|
| **A** | **`run.complete` · `run.failed` · `gate.reached` · `proxy.pool_degraded` · `discovery.overflow`** | Exactly **5** — satisfies [freeze §7](ARCHITECTURE_FREEZE.md) and task 1 · **every one has a live emitter today**, so every policy row is driven by a test rather than merely covered (P6 **F1**: coverage cannot see a branch nothing reaches) · includes `run.failed`, which task 5 requires · `discovery.overflow` serves **R19** (*"overflow is an error, never a silent gap"*) and answers [PHASE-06-HANDOVER §1.1](PHASE-06-HANDOVER.md) directly: *"`overflowed_subreddits` is what an overflow alert should name"* | `discovery.overflow` appears in no frozen kind list — it is an addition, even though freeze §7 fixes only the count |
| **B** | **[22 §4.12](22-hermes-skills.md)'s six, minus `quality.red`** — i.e. `gate.reached`, `run.complete`, `lead.high_confidence`, `budget.warning`, `proxy.pool_degraded` | Closest to the letter of the cited table | ⛔ Two of the five **cannot fire**: no `confidence_score` column, no 80% budget signal · ships `min_confidence_alert` as a key nothing reads (G8's exact lesson) · **omits `run.failed`**, which task 5 names · three of five policy rows would be tested only by synthetic injection |
| **C** | **Four now, fifth when P8 lands** | Nothing unreachable ships | ⛔ Violates [freeze §7](ARCHITECTURE_FREEZE.md)'s *5 at first delivery* · leaves P18 depending on a tier still being assembled |
| **D** | **All nine now** | No later expansion | ⛔ Freeze §7 caps first delivery at 5; expansion *"requires operator request"* · five of nine have no data source |

### ✅ Recommendation — **Option A**

**Why.** It is the only set of five in which **all five are emittable and assertable today**. That
matters more than textual proximity to [22 §4.12](22-hermes-skills.md), because §4.12 ranks below the
freeze (authority row 6 vs row 1), disagrees with [21 §7.1](21-hermes-architecture.md) anyway, and
keys its dedup on a table that has been **withdrawn** (review C4). Freeze §7 constrains the *count*,
and Option A meets it with five live kinds instead of three live ones and two placeholders.

`discovery.overflow` earns its place rather than filling a slot: R19 makes overflow an **error** that
must never be silent, P6 built the per-subreddit detection and named the field an alert should use,
and until P7 the only place that error surfaced was a log line and a run-page row the operator has to
be looking at.

**Impact.** `notify.min_confidence_alert` **is not shipped** — it is a documented deferral, not an
omission. The three dropped kinds go to DEFERRED-IMPROVEMENTS with triggers:

| Deferred kind | Trigger — the evidence that would justify building it |
|---|---|
| `lead.high_confidence` | `leads.confidence_score` exists (`0006`, P8) **and** is populated (P21). Ships with `min_confidence_alert` at that point |
| `quality.red` | `quality_snapshots` exists (`0010`, P25) and P26 computes a red state |
| `budget.warning` | Something spends, **and** an 80%-of-cap signal exists — `check_budget` currently raises only at 100% |

**Recorded as a [freeze §11.1](ARCHITECTURE_FREEZE.md) reconciliation**, not an amendment: no
technology, table or decision changes: three documents disagreed about the identity of a set whose
size the freeze fixes, and the disagreement is settled by which data sources exist.

### ⚠️ D2b — `proxy.pool_degraded`'s trigger must be respecified, or it is a permanent false alarm

**Found by checking whether the rule fires *meaningfully*, not merely whether its data exists.**
Emittability was the right first filter; it is not sufficient.

[22 §4.12](22-hermes-skills.md)'s rule is *"Notify if **healthy < 3**."* Under the **shipped**
configuration that is true on every run, forever:

- `config.yaml` ships `proxy.file: ''` and the `dc` provider with `allow_empty: true`, and its own
  comment states the consequence: *"An absent proxy file is tolerated: the pool comes up empty and
  egress goes direct."*
- Verified in code: with no pool, `routes_health.py:89–103` reports `healthy: 0`, `total: 0`,
  `enabled: False`.
- **This is the intended steady state, not an edge case.** P0's closing recommendation is *"Do **not**
  purchase proxies. Direct outperforms the datacenter pool on every measured dimension."*

So `0 < 3` → notify, every run, about a condition that is the deliberate design. That is precisely the
failure mode T4's rationale names: **an alert annoying enough that the operator switches the tier
off** — and a notification tier switched off is worse than one never built.

| | Option | Verdict |
|---|---|---|
| **A** | Keep `healthy < 3` | ⛔ Fires on every run in the shipped config |
| **B** | `healthy < 3` **and** `pool.enabled` | Better, but still fires continuously for anyone who *does* configure a small pool — and a 2-proxy pool is a choice, not an incident |
| **C** | **Notify when a degradation actually occurred during this run** — `policy.peek_notices()` is non-empty | ✅ **Recommended** |

**✅ Recommendation — C.** P4 already built exactly this signal and for exactly this reason: its
decision (c) was that *"degradation notices are buffered and drained after the scrape"*, and
`/health` already renders them (`routes_health.py:73`). An **event** ("egress degraded from `dc` to
`direct` twice during this run") is actionable; a **level** ("healthy is 0") is a description of the
operator's own configuration.

**Recorded with C2 as part of the same [§11.1](ARCHITECTURE_FREEZE.md) reconciliation.** No table or
decision changes — a threshold specified before the direct-first measurement was taken no longer
describes an incident.

⚠️ **Generalised lesson for the remaining four kinds:** *does the rule fire meaningfully under the
shipped configuration?* is a second filter, and it must be applied to each. `run.complete`,
`run.failed`, `gate.reached` and `discovery.overflow` all pass it — each corresponds to a discrete
event, not to a standing level.

⚠️ **Operator override point.** If you would rather hold the five to
[22 §4.12](22-hermes-skills.md)'s names and accept two rows that cannot fire until P21, say so — it
is a legitimate call about textual fidelity, and it is yours. It would change three policy rows, add
one config key, and weaken the "every row is driven" property.

---

## D3 — Where a notification is dispatched from

### 🔴 BLOCKING

**The conflict.** Trap **T0** — [PHASE-06-HANDOVER §5](PHASE-06-HANDOVER.md): *"the write lock,
again, and **P7 is where it returns**… A notification sent while the session is dirty holds SQLite's
single write lock across a network call to Telegram. **Send outside the transaction, or queue the
send and commit first.** P3 lost a sign-off to this; P4, P5 and P6 each had to prove they had not
re-opened it."*

**Verified mechanically:** `worker.py::_handler_session` commits **after** the handler returns, so an
inline send from a dirty handler holds the lock for the duration of the network call.

### Options

| | Option | Pros | Cons |
|---|---|---|---|
| **A** | **Buffer in the handler; drain after commit in the worker** | Structurally airtight — the drain is provably post-commit · mirrors P4's *"degradation notices are buffered and drained after the scrape"* | ⛔ Requires editing **`worker.py`**, P2's core loop and outside P7's Files row · every handler needs the buffer plumbed · a *notification* concern lands in the generic job loop, so P8…P30 inherit it |
| **B** | **A new `notify` job type** | Send happens in its own job, no other handler is touched · retry comes free from the queue | ⛔ `handlers/__init__.py`: *"`docs/04` §2.4 names **seven** job types and **the freeze closes that list**"* — this would be an eighth · would lean on `discover`'s **unreconciled** eighth type as precedent (review C8), i.e. justify one drift with another · latency: the send waits for the next worker tick, against a **< 10 s** criterion |
| **C** | **Dispatch at handler boundaries: commit bookkeeping → send → record outcome** | ✅ **Exactly what `handlers/__init__.py` prescribes**: *"Such a handler commits its bookkeeping **before** the blocking call"* · **`handle_discover` already ships on this pattern** (G4), so it is a worked precedent, not a new idea · no worker change, no new job type, no `run_service.py` change · entirely inside the Files row: `handlers/*.py ~ (emit points)` · sub-second latency | The discipline is per-call-site, so a future handler could get it wrong — which is why it is a documented precondition **plus** a test **plus** mutation M1 |

### ✅ Recommendation — **Option C**, in the specific shape below

The refinement that makes C strong is to notice that
[34 §P7](34-implementation-plan.md) task 2 (*"Markdown renderers **from SQL**"*) and task 4
(*"Query-based dedup against `run_events`"*) describe **one mechanism, not two**. The notification
tier is therefore a **reader of `run_events`**, not a set of push hooks bolted onto each emitter:

```
handler does its work, emit_event(...)          ← ordinary, unchanged
        │
        ├─ COMMIT                               ← the session is now clean
        │
        └─ NotificationService.dispatch_pending(run_id)
              ├─ SELECT notifiable events for this run     (SQL)
              ├─ LEFT JOIN against notify.sent rows        (dedup, task 4)
              ├─ decide()      — deterministic table, no model, no I/O
              ├─ render()      — Markdown from SQL         (task 2)
              ├─ transport.send()                          ← network, lock NOT held
              └─ emit_event("notify.sent" | "notify.failed") + commit
```

**Why this shape and not merely "option C".** Four properties fall out of it that the alternatives
have to build by hand:

1. **No emitter needs to know notifications exist.** They keep calling `emit_event`. So
   `run_service.py` is **not** touched, and a notification is never sent from inside a Flask request
   (R8).
2. **Dedup is inherent**, not bolted on — a `notify.sent` row per `(run_id, kind)` *is* the dedup key
   AD-29 says `run_events` should carry.
3. **`finalize_run` is the dispatch point**, immediately after its terminal transition commits →
   satisfies **< 10 s** for `run.complete` (AC1), and inherits the terminal-state guard that already
   makes it idempotent (AC4). Because it *drains everything pending for the run*, it also delivers
   `gate.reached` and `discovery.overflow` without either emitter being touched.
4. **No new job type, no worker change, no eighth-type precedent needed.** C8 stays exactly as open
   as P6 left it.

### ⚠️ Two facts verified after this decision was first drafted, which narrow it

**(a) `discover.py` does not need to be modified at all — and must not be.** `handle_discover` already
emits `discovery.overflow` to `run_events` (`discover.py:391`, via `_report_overflow`). Under the
reader design that is *sufficient*: the event is the queue. Critically, the handler has **exactly one
`session.commit()`, at line 107, before the fetch** — there is **no** commit after overflow detection.
Adding a dispatch there would require adding a commit, perturbing the transaction structure P6's G4
and G5 tests assert. **`discover.py` is therefore removed from the files-to-modify list.**

**(b) `gate.reached` and `run.failed` are emitted from web routes, not handlers.**
`RunService.create()` calls `_walk_to_scraping()`, which walks **all seven hops including both gate
states** — and `create()` is called from `routes.py:498` and `routes_runs.py:139`, i.e. inside a Flask
request. `RunService.fail()` is likewise reachable from a route. So **no handler is running** when
those two events are emitted, and dispatching from the route would put a network call inside a web
request — which **R8** (*"web routes write single rows only"*) exists to prevent.

**Consequence, stated rather than glossed:** under D3 alone, `gate.reached` is delivered *when the run
finalises*, and `run.failed` from a route is **not delivered at all** until something sweeps. AC1's
10 s is scoped to *"a completed run"*, so late gate delivery is defensible — but a `run.failed` that
never arrives is not. **That is D7.**

**Impact.** `finalize.py` +45; plus D7's single enqueue in `run_service.py`. `maintenance.py`,
`worker.py` and `run_service.py` **unchanged** — a diff touching any of the three is the signal that
the design drifted back into the trap.

**What is honestly given up.** Dispatch is **at-least-once**, not exactly-once: there is an
irreducible window where the send succeeds and the process dies before the `notify.sent` row is
written. This review **does not claim exactly-once** (assumption A3). AC4 is still satisfied, because
`finalize_run`'s terminal guard fires before dispatch is reached on a replay.

---

## D4 — The live half, and blocker B1

### 🔴 BLOCKING (an operator choice, not a technical one)

**The situation.** [35 §P7](35-testing-strategy.md)'s manual row is *"Complete a run; **receive one
Telegram message**; check `ai_calls` for zero agent rows."* That middle clause needs
`TELEGRAM_BOT_TOKEN`. Verified: `.env` contains **only** `APP_SECRET_KEY`.
[PHASE-06-HANDOVER §8](PHASE-06-HANDOVER.md) already flagged this as **B1** — *"⚠️ **Yes, for the
live half.** P7 is the notification tier and its transport needs this"* — and made it an entry
condition with an explicit escape: *"`TELEGRAM_BOT_TOKEN` present in `.env`, **or the live half of P7
explicitly deferred**."*

### Options

| | Option | Pros | Cons |
|---|---|---|---|
| **A** | **Ship the offline half complete; mark the live test BLOCKING and unsigned** | Uses the escape hatch the handover wrote for exactly this · [lock §4.1](EXECUTION_MODE_LOCK.md): *"finish every other part in full and state precisely what was left and why"* · policy, renderers, dedup, quiet hours, retry, redaction, both fences and **all three transports** are verifiable offline · nothing false is claimed | P7 cannot be tagged as fully signed off until the live test runs |
| **B** | **Operator provides a token now**; run the live half in this phase | Complete sign-off · closes B1 · exercises the real Bot API | Needs the operator to create a bot and a chat id (~10 min) · a real token on the machine, in an untracked `.env` |
| **C** | **Declare the offline half sufficient** and treat the live test as passed | Fastest | ⛔ **Claims a verification that did not happen.** [lock §6.2](EXECUTION_MODE_LOCK.md) forbids exactly this. Not a real option; listed to be ruled out |

### ✅ Recommendation — **Option A, with B available at any time**

**Why.** It is the path the handover pre-authorised, and it keeps the phase honest. Nine of the ten
manual tests are executable today; **Test 11 is marked BLOCKING and left unsigned** until a token
exists. The moment the operator supplies one, Test 11 runs unchanged — the guide is written so that no
other step depends on it.

**Impact.** The completion report must state: *offline half complete and verified; live delivery not
verified (B1)*. Per [lock §6.2](EXECUTION_MODE_LOCK.md), **no tag** while a sign-off table is
unsigned — which is independently already true because of **D1/O3** (P00–P06 unsigned).

---

## D7 — What delivers a notification when no handler is running

### 🔴 BLOCKING — found by verifying D3, not by reading

**The gap.** Three of the five kinds are emitted where `finalize_run` will not reach them:

| Kind | Emitted from | Reached by `finalize_run`'s drain? |
|---|---|---|
| `run.complete` | `handle_finalize_run` itself | ✅ Immediately |
| `discovery.overflow` | `handle_discover` (`discover.py:391`) | ✅ Later, when the run finalises |
| `gate.reached` | `RunService.create()` → `_walk_to_scraping()`, **from a web route** | ⚠️ Later, when the run finalises |
| `proxy.pool_degraded` | P4's buffered notices, drained after a scrape | ⚠️ Later |
| **`run.failed`** | **`RunService.fail()`, reachable from a web route** | ❌ **Never — `finalize_run` does not run on a failed run** |

**And the obvious sweeper does not exist.** [21 §13](21-hermes-architecture.md) says failures are
*"retried by the maintenance job"*, and `handle_maintenance` **is** registered — but **nothing enqueues
it.** Verified: the only `enqueue(` call sites in `src/` are `run_service.py:298` (scrape jobs),
`run_service.py:317` (finalize) and `scrape.py:172`. `main.py schedule` enqueues *runs*, not
maintenance. `handle_maintenance` is a handler with no driver — **the same species of gap as P6's
`repo.due()`**, which *"exists, nothing calls it on a timer yet."*

So the retry requirement in [34 §P7](34-implementation-plan.md) task 6 (*"retry on failure; failures
recorded, never silent"*) currently has nothing to run it.

### Options

| | Option | Pros | Cons |
|---|---|---|---|
| **A** | **The worker enqueues `maintenance` on an interval** (e.g. every 5 min when the queue is idle) | Gives task 6's retry a real driver · fixes `run.failed` · one mechanism covers every late kind · `maintenance` stops being dead code | ⛔ Touches **`worker.py`** — P2's core loop, and the file D3 exists to avoid · arguably P17's scheduling scope |
| **B** | **`RunService.fail()` enqueues a `finalize_run` job** so the existing drain runs on the failure path | No worker change · reuses the shipped handler and its terminal guard · the enqueue is a single row in the caller's transaction, **no network in the request** | Touches `run_service.py` (outside the Files row, permitted by [34 §1.1](34-implementation-plan.md)) · `finalize_run` must learn that an already-`FAILED` run is a drain-only no-op, not an error |
| **C** | **Dispatch synchronously from the web route** | Immediate delivery | ⛔ A network call inside a Flask request. Violates **R8** and re-opens **T0** from the web side, which is *where P3 originally lost its sign-off* |
| **D** | **Accept it: `run.failed` is delivered on the next run's finalise, or not at all** | Zero extra code | ⛔ *"The operator learns what happened"* is the phase's Objective, and a **failure** is the one thing they most need to learn. Fails AC5's spirit |
| **E** | **Ship four kinds; defer `run.failed` to P17's scheduler** | Honest, minimal | ⛔ Breaks [freeze §7](ARCHITECTURE_FREEZE.md)'s five, and drops the kind [34 §P7](34-implementation-plan.md) task 5 explicitly names |

### ✅ Recommendation — **Option B**, with A recorded as the deferred general fix

**Why B.** It solves the actual gap with the smallest, most reversible change, and it does not put I/O
anywhere near a request. `RunService.fail()` already writes the `FAILED` transition and its
`run_events` row in one transaction; adding **one** `enqueue(FINALIZE_JOB, …)` to that same
transaction is atomic, costs a single row, and hands delivery to the worker — where D3's
commit-then-send discipline already lives and is already tested. `finalize_run` is idempotent by
design and already returns `{"skipped": <state>}` for a terminal run; it gains a drain call on that
path, which is a two-line change to a branch that already exists.

**What it costs.** `run_service.py` is touched after all — one enqueue, plus a docstring line saying
why. [34 §1.1](34-implementation-plan.md) permits this (*Files* is *"a guide, not a contract"*), and it
must be **declared** in the completion report rather than slipped in.

**Why not A now**, even though it is the better long-term answer: it edits P2's worker loop for a
notification concern, and a periodic-`maintenance` driver is a *scheduling* capability that
[34 §P17](34-implementation-plan.md) owns. Recorded as **DI18** with the trigger: *the first phase that
needs periodic background work — P17's due-queue scheduler is the natural home, and it needs the same
driver.*

**Accepted latency, stated plainly.** With B, `gate.reached`, `proxy.pool_degraded` and
`discovery.overflow` are delivered **when the run finalises**, not when they occur. `run.complete` and
`run.failed` are immediate. AC1's *"< 10 s"* is scoped to *"a completed run"* and is therefore met.
⚠️ **This must be written into the completion report and the handover as a known characteristic**, not
left for P18 to discover — P18 is the phase that will want an *immediate* gate card, and it will need
either A or its own dispatch.

---

## D5 — The unspecified constants

### 🟡 Not blocking — but each must be chosen and documented

P6's **F4**: *"`default_rate` had no documented value; the obvious choice erased a distinction the
code makes. An unspecified constant is a decision, and it belongs in the docstring."*

| Constant | Specified anywhere? | Options | ✅ Recommendation | Why |
|---|---|---|---|---|
| `quiet_hours_utc` **format** | ❌ Named in [34 §P7](34-implementation-plan.md) Config and [21 §13](21-hermes-architecture.md); never defined | `"22:00-07:00"` string · `[22, 7]` pair · `{start, end}` map · cron | **`"22:00-07:00"`, or `null`/absent for none** | One readable value in a committed file; unambiguous when it **wraps midnight**, which the pair form makes easy to get wrong. Parsed once, validated at load, rejected loudly |
| **Quiet-hours exemptions** | Partly — task 5 exempts `run.failed` and `budget.warning` | Task 5 verbatim · all error-level kinds · none | **`run.failed` + `discovery.overflow`** | Task 5's `budget.warning` is not a shipped kind (D2), so its exemption has nothing to apply to. `discovery.overflow` takes the vacated slot because **R19 makes overflow an error**, and an error suppressed until morning is the silent gap R19 exists to forbid. `gate.reached` is **not** exempt — a gate waits indefinitely by design ([freeze AD-6](ARCHITECTURE_FREEZE.md): gates never time out), so it loses nothing by waiting for daylight |
| **Retry count / backoff** | ❌ Task 6 says only *"retry on failure; failures recorded, never silent"* | 3 attempts exp · 2 retries 1 s/2 s · none | **1 attempt + 2 retries at 1 s and 2 s; 5 s transport timeout; then `notify.failed` and stop** | Worst case ≈ 18 s bounded, then it stops — so a dead transport never becomes a hot loop (R6). ⚠️ There is **no periodic sweeper** to pick it up later (**D7**): a failure past the retry budget is *recorded* and delivered on the next drain for that run, or not at all. Do not describe it as "retried later". ⚠️ **AC1's "< 10 s" is therefore stated for the first-attempt success path** — p95, measured monotonically, on the path that succeeds. A delivery that needed retries is *recorded*, not silently counted as fast |
| `notify.transport` **default** | ❌ | `bot_api` · `null` | **`null` (`NullTransport`)** | With `enabled: false` shipped by default (D6), a transport that tries to reach the network on first upgrade is the wrong failure. `NullTransport` renders and records without sending, so the whole pipeline is exercisable — including by the operator — with no token at all |
| **`chat_id` in `run_events`** | ❌ | Raw · hashed · omitted | **`chat_id_hash` (first 12 hex of sha256)** | `run_events.data_json` is rendered into an HTML page. R15 keeps a chat identifier out of a template, and a hash still answers *"did this go to the right chat?"* |

Every one of these lands in the module docstring or `config.yaml` comment that owns it — per F4, not
in this file alone.

---

## D6 — Default-on or default-off

### 🟡 Not blocking

**Options.** `notify.enabled: true` (the feature works on upgrade) · **`false`** (explicit opt-in).

### ✅ Recommendation — **`false`**

**Why.** Three reasons, and the third is the one that matters:

1. A tier that starts messaging a chat id nobody configured, on upgrade, is a worse failure than one
   that is quiet until asked.
2. It composes with D5's `NullTransport` default: nothing can reach the network until the operator
   sets **two** keys deliberately.
3. **`notify.enabled: false` is the phase's documented rollback**
   ([34 §P7](34-implementation-plan.md)). Shipping it as the *default* means the rollback state is
   exercised by every test run and every fresh install — not only by the rollback drill in Stage 7.
   [lock §4](EXECUTION_MODE_LOCK.md) requires the rollback to be **executed and verified**; making it
   the default means it is verified continuously.

**Impact.** `P07-testing.md` Test 1 enables it explicitly, and Test 9 restores the default — with
full rollback instructions, because `config.yaml` is a **tracked file**.

---

## Summary — what is needed to start

| # | Decision | Status | Recommendation |
|---|---|---|---|
| **D1** | Transport set + default | 🔴 **BLOCKING** | **A** — all three behind the interface, `T3` default. C1's dependency reported **unsatisfied** |
| **D2** | The five kinds | 🔴 **BLOCKING** | **A** — `run.complete`, `run.failed`, `gate.reached`, `proxy.pool_degraded`, `discovery.overflow`. Three deferred with triggers |
| **D2b** | `proxy.pool_degraded`'s trigger | 🔴 **BLOCKING** | **C** — fire on a *recorded degradation this run*, not on `healthy < 3`, which is true on every run in the shipped config |
| **D3** | Dispatch point | 🔴 **BLOCKING** | **C** — commit → send → record, reading `run_events`, dispatched from `finalize_run`. **`discover.py` not modified** |
| **D7** | Delivery when no handler is running | 🔴 **BLOCKING** | **B** — `RunService.fail()` enqueues `finalize_run`. Nothing enqueues `maintenance` today; a periodic driver is deferred as **DI18** |
| **D4** | The live half (B1) | 🔴 **BLOCKING** (operator) | **A** — offline half complete; Test 11 marked BLOCKING and unsigned |
| **D5** | Five unspecified constants | 🟡 Choose + document | As tabled above; each into its own docstring (F4) |
| **D6** | Default-on/off | 🟡 | **`false`** — which makes the rollback the shipped state |

**Also requiring an operator answer, carried from earlier phases and not P7's to decide:**

| # | Item | Blocks P7? |
|---|---|---|
| **O2 / B3** | `mypy` absent → gate check 3 unclaimable for a seventh phase | No — recorded, not claimed |
| **O3 / D1** | P00–P06 manual sign-off tables unsigned | Not technically; **blocks tagging** ([lock §6.2](EXECUTION_MODE_LOCK.md)) |
| **C8** | `discover` is an unreconciled eighth job type | No — D3 adds none. Proposed as **DI15** |
