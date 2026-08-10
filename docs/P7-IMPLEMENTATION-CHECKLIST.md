# P7 IMPLEMENTATION CHECKLIST — Notification tier

**Written:** 2026-08-10 · Companion to [P7-IMPLEMENTATION-REVIEW.md](P7-IMPLEMENTATION-REVIEW.md) ·
[P7-DECISION-ANALYSIS.md](P7-DECISION-ANALYSIS.md)

> **Seven stages, seven commits.** Each stage has an objective, its files, its tests, its mutations, a
> named rollback point and a validation command set. **No giant commits.**
>
> Every stage ends with the suite green. A stage that cannot end green is not committed — it is fixed
> at root cause, never by weakening an assertion ([lock §3](EXECUTION_MODE_LOCK.md) step 6).
>
> ⛔ **Stage 0 is a gate, not a formality.** Nothing under `src/` is edited until the six blocking
> decisions — **D1, D2, D2b, D3, D7, D4** — are answered.

---

## Stage 0 — Pre-flight gate

**Objective.** Confirm the decisions are made and the baseline is still green at the moment work starts.

- [ ] **All six blocking decisions answered by the operator** — **D1** (transports), **D2** (the five
      kinds), **D2b** (`proxy.pool_degraded`'s trigger), **D3** (dispatch point), **D7** (delivery when
      no handler runs), **D4** (the live half) — see [P7-DECISION-ANALYSIS](P7-DECISION-ANALYSIS.md)
- [ ] D5 constants chosen; D6 confirmed
- [ ] `phase-manager` skill loaded — **required before the first edit under `src/`** ([lock §3](EXECUTION_MODE_LOCK.md))
- [ ] `git status --porcelain` → empty
- [ ] `main` == `origin/main`
- [ ] Baseline re-recorded (it may have moved since 2026-08-10)

```powershell
git status --porcelain
git fetch origin; git rev-parse HEAD origin/main
python -m pytest --no-header
python -m ruff check . ; python -m ruff format --check .
python scripts/check_schema.py
python -m alembic heads
gh run list --limit 1 --branch main
```

**Expected:** clean · two identical SHAs · `887 passed, 2 skipped` · `All checks passed!` /
`118 files already formatted` · `OK — all 31 checks passed` · `0005_discovery (head)` · `success`.

**Rollback point:** `99977bd` (or the recorded HEAD). Nothing has changed.

---

## Stage 1 — The fences, before the code they constrain

**Objective.** Grep fence 3 (R4) exists for the first time, and the R17 fence for `src/notify/` is in
place **before** a single line of transport code.

> **Why first.** [PHASE-06-HANDOVER §5](PHASE-06-HANDOVER.md) T1: *"Establish the fence in the first
> commit, as P5 did for `src/discovery/` — retrofitting is far more expensive."* And review **C9**:
> fence 3 has been claimed by [34 §1.2](34-implementation-plan.md) as a universal criterion since P1
> and **has never existed**. This is the third occurrence of P4's fence-4 species.

**Files**

| File | Change |
|---|---|
| `src/notify/__init__.py` | + Package with `Kind` only. Enough for a fence to have a root to walk |
| `tests/test_boundaries.py` | + `test_the_platform_never_imports_hermes` (**fence 3, R4**) |
| | + `test_notify_invokes_no_model` (R17 / AD-28) |
| | + `test_renderers_import_no_http_client` (AC3) |
| | + `test_the_notify_package_exists` |

**Tests**

- [ ] Fence 3 is **AST-based**, over every file under `src/`: rejects `import hermes`,
      `from hermes… import`, `importlib.import_module("hermes")`, `__import__("hermes")`.
      **Not `grep -ri`** — [freeze §11.1](ARCHITECTURE_FREEZE.md) already records that raw-text fences
      *"match docstrings and comments and therefore fail against correct, shipped code"*, and
      `transport.py` must be free to explain in prose why T2 shells out to a binary it does not import.
- [ ] R17 fence: `src/notify/**` imports no `src.ai` and no agent runtime.
- [ ] `renderers.py` imports no HTTP client (`requests`, `httpx`, `urllib.request`, `http.client`).
- [ ] `test_the_notify_package_exists` — the G1 lesson: *"a fence that walks whatever files are there
      passes vacuously if the file it was written for is deleted."*
- [ ] Each fence asserts it **walked a non-zero number of files** (F3: *"a guard that cannot fail is
      documentation"*).

**Mutations**

| # | Mutation | Must fail |
|---|---|---|
| **M8** | Delete `src/notify/` from the R17 fence's roots | `test_notify_invokes_no_model` (its non-zero-files assertion) |
| **M3a** | Add `import hermes` to any module under `src/` | **fence 3** |
| **M3b** | Add `import requests` to `renderers.py` | `test_renderers_import_no_http_client` |
| **M3c** | Delete `src/notify/__init__.py` | `test_the_notify_package_exists` |

> ⚠️ **Prove each fence FAILS before it passes.** Introduce the violation, watch the test go red,
> revert, watch it go green. A fence never observed failing has not been tested — it has been written.

**Validation**

```powershell
python -m pytest tests/test_boundaries.py --no-header
python -m pytest tests/test_boundaries.py --no-header -k "hermes or notify or renderers"
```

**Expected:** all pass; the `-k` run selects **4** tests (quoted — trap **T3**; an unquoted `-k`
selected zero tests and reported success twice in this project's history).

**Rollback point:** `git revert` this commit. `src/notify/` is an empty package nothing imports.

**Commit:** `test(P7): grep fence 3 (R4) and the src/notify boundary fences`

---

## Stage 2 — Kinds, settings and the deterministic policy table

**Objective.** Given an event and a clock, the tier decides notify-or-suppress. Pure: no I/O, no
session, no model.

**Files**

| File | Change |
|---|---|
| `src/notify/__init__.py` | ~ Export `Kind`, `Decision`, `NotifySettings` |
| `src/notify/service.py` | + `Kind` (5 per **D2**), `POLICY`, `NotifySettings`, `quiet_hours`, `decide()` |
| `tests/test_notify_policy.py` | + |

**Tests**

- [ ] Every one of the five kinds has a policy row, and **each row is driven by a test** — not merely
      covered (P6 **F1**: *"coverage counts executed lines; it cannot see a branch nothing reaches"*).
- [ ] `run.complete` notifies on leads > 0 **and** on 0 leads with a failure ([22 §4.12](22-hermes-skills.md)).
- [ ] An unknown kind → **suppress** (§4.12's *"everything else"* row). **No model path exists** (C5).
- [ ] Quiet hours suppress non-exempt kinds; `run.failed` and `discovery.overflow` are **exempt** (D5).
- [ ] A quiet window that **wraps midnight** (`"22:00-07:00"`) is handled — the case the pair form
      gets wrong.
- [ ] Boundary minutes: exactly `22:00` and exactly `07:00`.
- [ ] `quiet_hours_utc: null` / absent → nothing suppressed.
- [ ] A malformed `quiet_hours_utc` is rejected **loudly at load**, never silently ignored.
- [ ] `NotifySettings` from `{}` → `enabled=False`, `transport="null"` (**D6**).
- [ ] Property test: no `(kind, payload, now)` triple raises.

**Mutations**

| # | Mutation | Must fail |
|---|---|---|
| **M4** | Remove the `run.failed` quiet-hours exemption | `test_quiet_hours_never_suppress_a_failure` |
| **M5** | Invert the quiet-hours window comparison | `test_quiet_hours_boundaries` |

**Validation**

```powershell
python -m pytest tests/test_notify_policy.py --no-header
python -m pytest --no-header
```

**Expected:** new file green; full suite still `887 passed, 2 skipped` **plus** the new tests. Record
the exact count.

**Rollback point:** revert. Nothing calls `decide()` yet.

**Commit:** `feat(P7): five notification kinds and the deterministic policy table`

---

## Stage 3 — Renderers, from SQL

**Objective.** Each kind renders to Markdown from database state. No model, no HTTP import.

**Files**

| File | Change |
|---|---|
| `src/notify/renderers.py` | + One renderer per kind + `render(kind, session, run_id)` |
| `tests/test_notify_renderers.py` | + |

**Tests**

- [ ] Five golden Markdown fixtures, asserted **field by field**, not by substring.
- [ ] Every figure comes from a query — no renderer accepts a pre-computed total from its caller.
- [ ] `discovery.overflow` names **every** overflowed subreddit from `overflowed_subreddits` — **G5**:
      overflow is a *per-subreddit* fact, and a renderer printing `subreddits[0]` would undo in the UI
      what P6 built in the data.
- [ ] `gate.reached` renders with P17's fields **absent** — they do not exist yet (**C6**), and the
      renderer must degrade rather than raise. P18 adds counts, rejects, estimate and the deep link.
- [ ] `proxy.pool_degraded` renders healthy/degraded counts from `ProxySnapshot`.
- [ ] A run with **zero** leads renders correctly (no division, no empty-list crash).
- [ ] **No credential and no raw `chat_id`** appears in any rendered body (R15).
- [ ] Rendering issues **no** write — asserted by a statement counter.

**Mutations**

| # | Mutation | Must fail |
|---|---|---|
| **M3b** | `import requests` in `renderers.py` | Stage 1's fence (re-run here) |
| **M11** | Make the overflow renderer print `subreddits[0]` instead of the full list | `test_overflow_names_every_subreddit` |

**Validation**

```powershell
python -m pytest tests/test_notify_renderers.py tests/test_boundaries.py --no-header
python -m pytest --no-header
```

**Rollback point:** revert. Renderers are pure functions nothing calls.

**Commit:** `feat(P7): markdown renderers built from SQL, never from a model`

---

## Stage 4 — The transport interface and all four implementations

**Objective.** `Transport` with `BotApiTransport` (T3), `ServeTransport` (T1),
`SubprocessTransport` (T2) and `NullTransport` — **selected by config** (D1). Fully offline-testable.

**Files**

| File | Change |
|---|---|
| `src/notify/transport.py` | + Protocol + four implementations + `build_transport(settings)` |
| `src/obs/logging.py` | ~ `TELEGRAM_BOT_TOKEN` shape → `_SECRET_PATTERNS` (**task 7**) |
| `tests/test_notify_transport.py` | + |

**Tests**

- [ ] **No live network anywhere** ([34 §1.2](34-implementation-plan.md) U2). T1/T3 via `responses`;
      T2 via a patched `subprocess.run`.
- [ ] T3 posts to `…/bot<token>/sendMessage` and **the captured request is asserted** — trap **T2a**:
      *"a returned flag is not a performed action."* P6 shipped `html_fallback: True` from a branch
      that fetched nothing.
- [ ] T3 with no token **refuses loudly at construction**, never at send time.
- [ ] Telegram `4xx` vs `5xx` are distinguished — one is retryable, the other is not.
- [ ] T2 builds `hermes send -t telegram:<chat> -f <file>` and **imports nothing** (fence 3 covers it).
- [ ] T2's temp file is deleted even when the subprocess fails.
- [ ] `NullTransport` returns an id and performs **no** I/O.
- [ ] `build_transport` constructs all four from config; an unknown name raises naming the value.
- [ ] `TELEGRAM_BOT_TOKEN` is redacted from a log line, an exception message and a traceback.
- [ ] `reset_policy()` in every test reaching the network layer — trap **T5**.

**Mutations**

| # | Mutation | Must fail |
|---|---|---|
| **M7** | Return success without issuing a request | `test_the_transport_actually_posted` |
| **M9** | Remove the `TELEGRAM_BOT_TOKEN` pattern from `RedactingFilter` | `test_bot_token_is_redacted` |
| **M12** | Treat a `5xx` as non-retryable | `test_5xx_is_retryable` |

**Validation**

```powershell
python -m pytest tests/test_notify_transport.py --no-header
python -m pytest --no-header -W error::DeprecationWarning
```

**Rollback point:** revert. No caller.

**Commit:** `feat(P7): transport interface with T1/T2/T3 and bot-token redaction`

---

## Stage 5 — `dispatch_pending`: dedup, retry, outcome recording

**Objective.** Read `run_events` → decide → render → send → record. The reader design from **D3**.

**Files**

| File | Change |
|---|---|
| `src/notify/service.py` | ~ `NotificationService.dispatch_pending()` |
| `src/notify/__init__.py` | ~ Export `NotificationService` |
| `tests/test_notify_dispatch.py` | + |

**Tests**

- [ ] **AC4 — 20 lease-expiry replays send exactly one message.** Assert **one** transport call *and*
      **one** `notify.sent` row. Duplicate rate **0**.
- [ ] Two **different** kinds on one run both send (dedup is on `(run_id, kind)`, not `run_id`).
- [ ] A second **run** is notified independently (dedup is not on `kind` alone).
- [ ] **AC5** — transport raises → `notify.failed` at `level="error"`, run still reaches `COMPLETE`.
- [ ] Retry: 1 attempt + 2 retries at 1 s / 2 s, then stop (**D5**). Assert **3** transport calls, not 4.
- [ ] `enabled: false` → **zero** renders, **zero** transport calls, **zero** `notify.*` rows.
- [ ] Suppressed by quiet hours → no send, and **no** `notify.sent` row (so it is retried later, not
      lost).
- [ ] **AC1 — p95 < 10 s**, measured with `time.monotonic()` around **the dispatch call only**.
      ⚠️ Not wall-clock around a run: `test_parse_speed_stays_inside_the_budget` failed at 105.3 ms
      against a 50 ms budget purely under machine load during this review's baseline run
      ([review §4.3](P7-IMPLEMENTATION-REVIEW.md)). Generous headroom; documented as load-sensitive.
- [ ] **AC2 — zero tokens.** `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` → **0**.

**Mutations**

| # | Mutation | Must fail |
|---|---|---|
| **M2** | Drop the `kind` term from the dedup query | `test_two_different_kinds_both_send` |
| **M3** | Drop the `run_id` term from the dedup query | `test_a_second_run_is_notified_independently` |
| **M6** | `NullTransport.send` returns an id, record nothing | `test_a_send_writes_a_notify_sent_row` |
| **M10** | Swallow the transport exception instead of recording it | `test_transport_failure_is_recorded_not_silent` |

**Validation**

```powershell
python -m pytest tests/test_notify_dispatch.py --no-header
python -m pytest --no-header
```

**Rollback point:** revert. No handler calls `dispatch_pending` yet.

**Commit:** `feat(P7): run_events-backed dispatch with dedup, bounded retry and recorded failure`

---

## Stage 6 — Wire the emit points ⚠️ THE T0 STAGE

**Objective.** `finalize_run`, `maintenance` and `discover` dispatch **after** committing. The write
lock is never held across the send.

> ⚠️ **This is the stage that loses sign-offs.** [PHASE-06-HANDOVER §5](PHASE-06-HANDOVER.md) T0:
> *"P7 adds notification emission to every handler… **Send outside the transaction, or queue the send
> and commit first.** P3 lost a sign-off to this; P4, P5 and P6 each had to prove they had not
> re-opened it."*
>
> The precedent to copy is `handle_discover`, which already commits its start event before fetching
> (**G4**). `handlers/__init__.py` states the rule: *"Such a handler commits its bookkeeping **before**
> the blocking call."*

**Files**

| File | Change |
|---|---|
| `src/orchestration/handlers/finalize.py` | ~ Commit the terminal transition, **then** dispatch. Also drain on the already-terminal branch |
| `src/orchestration/run_service.py` | ~ **`fail()` enqueues `FINALIZE_JOB`** in its own transaction (**D7**). One enqueue, no I/O |
| `tests/test_notify_dispatch.py` | ~ + the lock-discipline tests |

**⛔ Files that must NOT appear in this diff**

| File | Why |
|---|---|
| `src/orchestration/worker.py` | D3 exists so P2's core loop stays untouched. A change here means the design drifted to D3 option A |
| `src/orchestration/handlers/discover.py` | It **already** emits `discovery.overflow` to `run_events` (`discover.py:391`), so the reader design needs nothing. It has **exactly one commit, at line 107, before the fetch** — adding a dispatch would require adding a commit and would perturb the transaction structure P6's **G4/G5** tests assert |
| `src/orchestration/handlers/maintenance.py` | **Nothing enqueues `maintenance`** — verified: the only `enqueue(` sites are `run_service.py:298`, `run_service.py:317`, `scrape.py:172`. A sweeper here would never run. Deferred as **DI18** |

**Tests**

- [ ] **`test_dispatch_never_holds_the_write_lock`** — inspect the session **from inside the
      transport**; assert it is clean (`session.dirty`, `session.new`, `session.deleted` all empty) and
      that the run's terminal state is already committed and visible to a **second** connection. This
      is P6's own technique: it *"asserts it by a test that inspects the session from inside the
      fetch."*
- [ ] A second concurrent writer can write **while** the transport is blocked.
- [ ] `finalize_run` remains idempotent: re-run on a terminal run → `{"skipped": …}`, **no** second
      message.
- [ ] **`run.failed` is delivered** (**D7**): `RunService.fail()` enqueues `finalize_run`; the worker
      drains it; assert the message and that **no network call happened inside the `fail()` call**.
- [ ] `fail()`'s enqueue is in the **same transaction** as the `FAILED` transition — a rollback must not
      leave a job pointing at a run that never failed.
- [ ] `finalize_run` on an already-terminal run **drains but does not re-transition**, and re-running it
      does not re-send.
- [ ] `handle_discover` still commits its start event before fetching, and **still has exactly one
      commit** — **G4 and G5 unbroken**. Assert the commit count, not just that tests pass.
- [ ] Every existing `finalize` / `discover` / `maintenance` test still passes **unmodified**. A test
      that had to be edited to accommodate the change is a signal, not a chore.

**Mutations**

| # | Mutation | Must fail |
|---|---|---|
| **M1** | Move the dispatch **before** the commit (dirty the session, then send) | `test_dispatch_never_holds_the_write_lock` |
| **M13** | Remove `finalize_run`'s terminal-state early return | The 20-replay dedup test |
| **M14** | Remove `fail()`'s `enqueue(FINALIZE_JOB)` | `test_run_failed_is_delivered` |
| **M15** | Add a second `session.commit()` to `handle_discover` | `test_discover_commits_exactly_once` (**G4/G5**) |

**Validation**

```powershell
python -m pytest tests/test_notify_dispatch.py tests/test_finalize.py tests/test_discovery_handler.py --no-header
python -m pytest --no-header
python -m pytest --no-header -W error::DeprecationWarning
```

**Rollback point:** revert. `src/notify/` is complete but nothing calls it — a state the earlier
stages already proved green.

**Commit:** `feat(P7): dispatch from handler boundaries, after the commit and outside the lock`

---

## Stage 7 — Config, documentation, and the executed rollback

**Objective.** The tier is configurable, the phase's **Docs** field has landed, and the rollback has
been **performed**, not described.

**Files**

| File | Change |
|---|---|
| `config.yaml` | + `notify:` block — fully commented, every key defaulted, rollback stated inline |
| `docs/09-dashboard-plan.md` | + **New §8** (review **C7** — §8 does not exist; P7 authors it) |
| `docs/21-hermes-architecture.md` | ~ §7.1: the shipped transport, and C1's unsatisfied dependency |
| `docs/ARCHITECTURE_FREEZE.md` | ~ §11.1 reconciliations for **C2** (kind list) and **C4** (`notification_log`) |
| `docs/DEFERRED-IMPROVEMENTS.md` | ~ DI15 (C8, the `discover` job type), DI16 (the three deferred kinds) |
| `docs/testing/P07-testing.md` | ~ Executed; every number replaced with real output |
| `docs/PHASE-07-COMPLETION-REPORT.md` | + |
| `docs/PHASE-07-HANDOVER.md` | + |
| `docs/progress/P07-COMPLETE.md` | + |
| `docs/README.md` | ~ Execution table |

**Tests**

- [ ] Deleting the whole `notify:` block reproduces the defaults exactly (`enabled: false`,
      `transport: null`) — the same property P6's discovery block has, and the reason its comment says
      so.
- [ ] Every shipped key is **read by code**. ⚠️ **G8's lesson**: *"a key nothing reads is a documented
      capability that does not exist."* `min_confidence_alert` is **not** shipped (**D2**) — it would
      configure a column that arrives in `0006`.
- [ ] A grep asserts `min_confidence_alert` appears **nowhere** in `config.yaml` or `src/`.

**Rollback — executed, per [lock §4](EXECUTION_MODE_LOCK.md)**

- [ ] Set `notify.enabled: false`; run a full run; assert **zero** `notify.*` rows and zero transport
      calls; assert the run still completes.
- [ ] Delete the `notify:` block entirely; repeat; identical result.
- [ ] Restore `config.yaml` with **`git checkout -- config.yaml`** — *not* by re-typing, and **never**
      by a `Get-Content`/`Set-Content` round-trip, which adds a BOM and mojibakes UTF-8.
- [ ] Confirm `git diff --stat config.yaml` is empty afterwards.
- [ ] Record the executed rollback in the completion report.

**Validation — the full gate, one uninterrupted run**

```powershell
python -m pytest --no-header
python -m pytest --no-header -W error::DeprecationWarning
python -m ruff check . ; python -m ruff format --check .
python scripts/check_schema.py
python -m alembic heads
python -m pytest tests/test_boundaries.py --no-header
```

**Expected:** green throughout · `OK — all 31 checks passed` · `0005_discovery (head)` — **one** head,
unchanged, because P7 adds no revision.

⚠️ `mypy` — gate check 3 — **cannot run** (blocker **B3/O2**). Record as unclaimable; do **not** report
the gate as fully passed.

**Commit:** `docs(P7): notify config, dashboard §8, reconciliations and the executed rollback`

---

## Post-implementation — [lock §3](EXECUTION_MODE_LOCK.md) steps 8–16

- [ ] `docs/testing/P07-testing.md` executed; **every expected value replaced with real output**
      (trap **T4**: four of P6's manual counts were wrong until executed)
- [ ] `docs/PHASE-07-COMPLETION-REPORT.md` — including, stated plainly:
  - [ ] C1's M-5/M-9/M-10 dependency **UNSATISFIED**; T1/T2 unit-tested, never live-verified (A7)
  - [ ] Test 11 (live delivery) **BLOCKING on B1**, unsigned (D4)
  - [ ] Three of five kinds are delivered **at finalise, not when they occur** (A9) — P18 will want immediate
  - [ ] `handle_maintenance` has **no driver**; a periodic one is deferred as **DI18**
  - [ ] `mypy` unclaimable (B3/O2)
  - [ ] Dispatch is **at-least-once**, not exactly-once (A3)
  - [ ] Fence 3 built in P7 after six phases of vacuous claims (C9)
- [ ] `docs/PHASE-07-HANDOVER.md` — guarantees, traps for P8, blockers
- [ ] `docs/progress/P07-COMPLETE.md` — ending in a resume point
- [ ] **Repository Hygiene Review** ([lock §5](EXECUTION_MODE_LOCK.md)) on the **staged** diff:

```powershell
git status --short
git diff --cached --stat
git diff --cached | Select-String -Pattern 'sk-|api[_-]?key|password|secret|token|PRIVATE KEY' -CaseSensitive:$false
git diff --cached | Select-String -Pattern 'C:\\Users\\|/home/|/Users/'
git check-ignore -v .env data/leads.db
```

⚠️ H1 will flag the word `token` in `transport.py` and `logging.py`. That is **expected** — the review
is for *values*, not the identifier. Confirm no literal token, then proceed.

- [ ] `git push origin main`; confirm CI green
- [ ] **Do NOT tag** — sign-off tables unsigned (**D1/O3**), and [lock §6.2](EXECUTION_MODE_LOCK.md)
      forbids a tag that claims a verification that did not happen
- [ ] **STOP.** Report, and wait for approval

---

## Stage summary

| # | Stage | Files | New tests | Mutations | Rollback |
|---|---|---|---:|---|---|
| 0 | Pre-flight gate | — | 0 | — | Nothing changed |
| 1 | **The fences** | 2 | ~6 | M8, M3a–c | revert |
| 2 | Kinds + policy | 3 | ~16 | M4, M5 | revert |
| 3 | Renderers | 2 | ~13 | M3b, M11 | revert |
| 4 | Transports | 3 | ~15 | M7, M9, M12 | revert |
| 5 | Dispatch | 3 | ~14 | M2, M3, M6, M10 | revert |
| 6 | **Emit points (T0)** | 4 | ~8 | M1, M13, M14 | revert |
| 7 | Config + docs + rollback | 10 | ~3 | — | `git checkout -- config.yaml` |
| | **Total** | | **≈ 75** | **17** | |

**17 mutations** against the review's 10 — the extra seven are the per-stage ones. Per trap **T2**,
*"a green mutation run proves the mutations you wrote, not the ones you did not"*: a review pass
after Stage 6 hunts for the eighteenth, exactly as P6 found M12–M14 only in review.
