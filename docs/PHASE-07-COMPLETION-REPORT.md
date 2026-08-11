# PHASE-07 COMPLETION REPORT — Notification tier

**Phase:** P7 ([34 §P7](34-implementation-plan.md)) · **Delivered:** 2026-08-10 · **Revision:** none
**Companion:** [PHASE-07-HANDOVER.md](PHASE-07-HANDOVER.md) · [testing/P07-testing.md](testing/P07-testing.md) ·
[P7-IMPLEMENTATION-REVIEW.md](P7-IMPLEMENTATION-REVIEW.md) ·
[P7-DECISION-ANALYSIS.md](P7-DECISION-ANALYSIS.md) ·
[P7-IMPLEMENTATION-CHECKLIST.md](P7-IMPLEMENTATION-CHECKLIST.md) ·
[P7-STAGE5-FLOW.md](P7-STAGE5-FLOW.md)

> ⚠️ **P7 is the notification tier, not `17-phase-07.md`.** That document ("Adaptive, Batched
> Enrichment & Explainable Confidence") belongs to the **superseded eight-phase numbering** and maps to
> **P19–P22** with migration `0009` ([32 §4](32-documentation-consistency.md)). Reading it as P7's
> specification would have built Stage G twelve phases early and invented an eleventh revision. This
> was the first thing the implementation review established.

---

## 1. What was built

The operator now learns what happened, **at zero token cost**.

```
src/notify/
├── __init__.py      the package's public surface
├── service.py       Kind (5) · POLICY · quiet hours · NotifySettings ·
│                    NotificationService.dispatch_pending
├── renderers.py     one Markdown renderer per kind, built from SQL
└── transport.py     Transport protocol + NullTransport · BotApiTransport (T3) ·
                     ServeTransport (T1) · SubprocessTransport (T2)

src/orchestration/handlers/finalize.py  ~ commit, THEN dispatch
src/orchestration/run_service.py        ~ fail() enqueues the drain (D7)
src/obs/logging.py                      ~ TELEGRAM_BOT_TOKEN redaction
config.yaml                             ~ the notify: block
tests/                                  + 5 files, +250 tests
```

**No migration. No table. No endpoint. No new dependency.** `alembic heads` is still
`0005_discovery`, and that is why [34 §P7](34-implementation-plan.md)'s *Low* risk rating held.

### 1.1 The five kinds, and why these five

[freeze §7](ARCHITECTURE_FREEZE.md) fixes first delivery at five and names none; three other documents
name four different sets. The five were chosen on one criterion — **a live emitter at revision
`0005`** — so every policy row is driven by a test rather than merely covered (P6's **F1**).

| Kind | Evidence it is derived from |
|---|---|
| `run.complete` | `run.transition` → `to_state='complete'` |
| `run.failed` | `run.transition` → `to_state='failed'` |
| `gate.reached` | `run.transition` → an `awaiting_*` state |
| `discovery.overflow` | `discovery.overflow` rows, one per subreddit |
| `proxy.pool_degraded` | `net.degraded` rows |

Three candidates were dropped for having no data source, each with a trigger
([DI16](DEFERRED-IMPROVEMENTS.md)). `notify.min_confidence_alert` is **not shipped**, on P6's
`density_threshold` precedent, and a fence now prevents it being added back.

### 1.2 The architecture, in one line

The tier is a **reader of `run_events`**, not a set of push hooks. Emitters keep calling `emit_event`
and stay unaware notifications exist — so `worker.py` is untouched, no job type was added
([04 §2.4](04-system-design.md)'s list stays closed), and nothing is ever sent from inside a Flask
request (**R8**). Flow and boundaries: [P7-STAGE5-FLOW.md](P7-STAGE5-FLOW.md).

---

## 2. Acceptance criteria — [34 §P7](34-implementation-plan.md)

| # | Criterion | Result |
|---|---|---|
| AC1 | A completed run delivers a message **within 10 s** | ✅ Monotonic-clock assertion, plus a p95 over 20 dispatches. **The test did not exist until Stage 7's final validation found it missing** — see §5 |
| AC2 | **Zero tokens consumed** | ✅ `ai_calls` unchanged at 3 across the whole phase; AST fence proves `src/notify/` imports no `src.ai` |
| AC3 | `renderers.py` imports neither `src.ai` nor an HTTP client | ✅ Per-module fence; `requests` confined to `transport.py` |
| AC4 | Re-running `finalize_run` after lease expiry sends **one** message | ✅ 20 replays → 1 send, 1 `notify.sent` row |
| AC5 | Transport down → **recorded**, run unaffected | ✅ `notify.failed` at `level="error"`; run still `COMPLETE`, `error` still `NULL` |
| AC6 | Quiet hours suppress **non-critical only** | ✅ `run.failed` and `discovery.overflow` exempt; both boundary minutes and the midnight wrap pinned |
| AC7 | Bot token in **no log** | ✅ New `RedactingFilter` pattern; the leak vector was the token **in the API URL path**, which no existing pattern caught |
| **M1** | Token cost = 0 | ✅ |
| **M2** | Duplicate rate 0 over 20 replays | ✅ |
| **M3** | Delivery p95 < 10 s | ✅ (see AC1) |

### 2.1 Universal criteria — [34 §1.2](34-implementation-plan.md)

| | Result |
|---|---|
| `ruff check` · `format --check` | ✅ 127 files |
| `pytest`, no live network | ✅ **1131 passed, 2 skipped**; every transport test uses `responses` or a patched `subprocess` |
| Coverage ≥70% on new modules | ✅ **100%** on `src/notify/` (449 statements) |
| **All four grep fences (R2–R5)** | ⚠️ **Fence 3 did not exist.** P7 built it — see §5 |
| Migration round-trip | ✅ Unchanged; P7 adds no revision, one head |
| Legacy contract | ✅ 459 baseline leads, `intent_score` fingerprint, 17 endpoints, 13 CSV columns |
| Manual guide executed | ✅ Part B recorded; **T11 blocked**, sign-off table left for a human |
| Documentation landed | ✅ §6 |
| `mypy` | ❌ **Not installed** (B3/O2). **The gate is not claimed in full** |

---

## 3. The rollback — executed, not described

[lock §4](EXECUTION_MODE_LOCK.md) requires it performed. Three phases against a real run, a real
handler and the real `config.yaml`:

| Phase | `config.yaml` | Run state | `notify.*` rows | Delivered |
|---|---|---|---|---|
| **A** | shipped default, `enabled: false` | `complete` | **0** | — |
| **B** | `enabled: true` | `complete` | **2** | `run.complete`, `gate.reached` |
| **C** | block **deleted entirely** | `complete` | **0** | — |

**A == C, and B differs.** Phase B was not decoration: a switch that suppresses when off but also does
nothing when on is indistinguishable from a broken feature.

Restore via the documented `git checkout -- config.yaml` → diff empty, block present, no BOM, parses
correctly, tree clean. Full suite re-run after the rollback: **1131 passed, 2 skipped**.

⚠️ **A trap in the procedure, found the hard way.** `git checkout --` restores to **HEAD**. On the
first drill the `notify:` block was not yet committed, so the restore *deleted it*. The block was
committed first and the drill re-run. Safe for an operator following the guide; recorded for anyone
re-running the drill against uncommitted work.

---

## 4. Verification

| | |
|---|---|
| Full suite | **1131 passed, 2 skipped** (887 at entry, **+244**) |
| Under `-W error::DeprecationWarning` | **1131 passed, 2 skipped** |
| Coverage, `src/notify/` | **100%** — 449 statements |
| `ruff check` / `format --check` | All checks passed · 127 files |
| `check_schema.py` | **OK — all 31 checks passed** (unchanged; P7 adds no table) |
| `alembic heads` | **`0005_discovery`** — one head |
| Grep fences | **4 of 4**, fence 3 for the first time |
| **Mutation testing** | **78 designed, 78 detected** — 7 survived a first pass and every one was a real gap or a badly-built mutation, none dismissed as noise |
| CI | green on every stage commit |

### 4.1 Mutations by stage

| Stage | Run | Survived first pass | Outcome |
|---|---:|---:|---|
| 1 — fences | 16 | 0 | — |
| 2 — policy | 13 | 0 | — |
| 3 — renderers | 22 | **3** | M28 a real test gap; M34 exposed dead code, removed; M33 was a badly-built mutation of mine |
| 4 — transports | 12 | 0 | — |
| 5 — dispatch | 21 | **2** | M50 and M54 each **masked by a second guard**; both tests strengthened |
| 6 — boundaries | 6 | **1** | M15b — the fixture had no notifiable evidence, so a stray dispatch found nothing to send |
| | **78** | **6** | all closed |

One mutation, **M34b**, survives and is **undetectable rather than untested**: every field value is
`None` or a non-empty `str`, and `"0"` is truthy, so `if value` and `if value is not None` cannot
differ. Proven by enumerating all 14 field expressions and reported as an equivalent mutant.

---

## 5. What implementation found that reading had not

Seven findings. Five are defects in this project's own documents or tests; two are in code P7 wrote.

**F1 — Grep fence 3 (R4) did not exist.** [34 §1.2](34-implementation-plan.md) lists *"all four grep
fences pass"* as a **universal** criterion for every phase, and `grep -i hermes tests/` matched **no
file**. Six phases ticked a line nobody could have checked. **Third occurrence of the species** — P4
found the same for fence 4, ticked as delivered in [12 §14](12-phase-02.md) while absent. P7 built it,
AST-based so T2's `subprocess` argv stays legal.

**F2 — A kind is not a timeline event name.** [P7-IMPLEMENTATION-REVIEW §8](P7-IMPLEMENTATION-REVIEW.md)
asserted *"a kind and the timeline row that carries it are the same identifier"*. True for **one kind
in five**: `run_service.transition` emits a single event name for every hop. Found by reading the code
before writing the dispatcher; the docstring was corrected rather than the mistake worked around.

**F3 — `session.get` is served from the identity map.** Rendering a gate issued **zero SQL** because
the caller already held the `Run` — which the dispatcher always does. It would have rendered the
caller's in-memory object, including an attribute mutated but not flushed, while claiming to render
from SQL. Caught by the read-only test's `assert sql`.

**F4 — AC1 had no test.** The delivery-timing criterion was claimed with nothing asserting it. Found
during Stage 7's final validation while filling in the manual guide. Same species as F1.

**F5 — `transport: null` in YAML is `None`, not `"null"`.** The tier could not construct from its own
shipped config. **Second time this footgun has bitten `config.yaml`** — the `providers:` block already
warns *"`null_provider` and not a bare `null`, which YAML parses as no value at all"*. Fixed both ways.

**F6 — Two unreachable branches, deleted rather than tested.** `_duration`'s `None` guard (both
timestamp columns are `nullable=False`) and the `""` arm of the field filter. P6's **F1** is exactly
that shape of branch reporting coverage while proving nothing. 100% coverage is honest as a result.

**F7 — `-q` doubles to `-qq` and hides the test count.** `pyproject.toml` already sets it, so 31
guide commands asked a tester to read a number pytest was never going to print. Registered as
[DI19](DEFERRED-IMPROVEMENTS.md) because earlier guides may carry it.

---

## 6. Documentation landed

| Document | Change |
|---|---|
| [09 §8](09-dashboard-plan.md) | **New** — the notification surface, the five kinds, timing limits, where it appears |
| [21 §7.1](21-hermes-architecture.md) | The shipped transport set, and C1's **unsatisfied** M-5/M-9/M-10 dependency |
| [ARCHITECTURE_FREEZE §11.1](ARCHITECTURE_FREEZE.md) | **Two reconciliations** — the four-way kind-list disagreement, and the withdrawn `notification_log` two documents still key on |
| [DEFERRED-IMPROVEMENTS](DEFERRED-IMPROVEMENTS.md) | **DI15–DI19** |
| [testing/P07-testing.md](testing/P07-testing.md) | Part B executed and recorded |
| [README](README.md) | Execution record |

**No [freeze §11](ARCHITECTURE_FREEZE.md) amendment was needed.** Both entries are §11.1
reconciliations — documentation catching up with decisions already taken.

---

## 7. Known limits — stated, not hidden

| # | Limit |
|---|---|
| ~~**L1**~~ | ~~**T11 (real Telegram delivery) is not verified.** Blocker **B1**: `.env` holds only `APP_SECRET_KEY`~~ · ✅ **CLOSED 2026-08-11.** Executed live: a real bot, a real token in `.env`, `transport: bot_api`, and a message delivered to a real chat in **2.3 s**. See [§7a](#7a-live-telegram-verification--2026-08-11) |
| **L2** | **M-5, M-9 and M-10 were never measured.** [34 §P7](34-implementation-plan.md) names them as a dependency; P0 says they are not needed until P23. T3 removes the dependency by construction, and it is reported **unsatisfied** |
| **L3** | **T1 and T2 are unit-tested only.** `hermes` is not installed and does not arrive before P23 |
| **L4** | **Retry is not implemented.** Scoped out by the operator. A failure is *recorded*, not retried — [34 §P7](34-implementation-plan.md) task 6's other half is **not delivered** |
| **L5** | **Three of five kinds are delivered late** — at finalise, not when they occur. AC1 is scoped to *"a completed run"*, so it holds. **P18 will want an immediate gate card** |
| **L6** | **Delivery is at-least-once**, not exactly-once |
| **L7** | **T3 sends plain text.** Bodies carry untrusted text, so honouring `*bold*` risks a `400 can't parse entities` that loses the message. ✅ **Now live-observed and unchanged:** the delivered message showed `*Run 4 needs approval*` with **literal asterisks**. Structure renders; emphasis is deliberately not applied. Still a limit, no longer an unverified one |
| **L8** | **`mypy` is not installed** (B3/O2). The gate is not claimed in full |
| **L9** | **The manual sign-off table is unsigned**, and P00–P06 remain unsigned. **No tag** ([lock §6.2](EXECUTION_MODE_LOCK.md)) |

---

## 7a. Live Telegram verification — 2026-08-11

**Blocker B1 is closed.** P7 shipped with its live half deferred under decision **D4 option A**;
option B — *"operator provides a token now"* — has since been taken, after the fact. This section
records the evidence, so that the deferral is closed by proof rather than by assertion.

### What the operator did

1. Created a real bot through **@BotFather**.
2. Put `TELEGRAM_BOT_TOKEN` in `.env` (git-ignored — proved in T8b).
3. Set `notify.enabled: true`, `notify.transport: bot_api` and a real `notify.telegram_chat_id` in
   `config.yaml`.
4. Verified the token and chat id, started a conversation with the bot, and started a run.
5. **A real message arrived in the Telegram chat.**

### What the database proves

`data/leads.db`, run 4:

```
event:      notify.sent
data_json:  {"kind": "gate.reached", "transport": "bot_api",
             "message_id": "4", "chat_id_hash": "47dd2e1a1a6e"}
created_at: 2026-08-11 05:27:43.197202
runs.finished_at for run 4: 2026-08-11 05:27:40.854250
```

| Claim | Status | How this row proves it |
|---|---|---|
| **AC1** — delivery within 10 s of a completed run | ✅ | `05:27:43.197` − `05:27:40.854` = **2.3 s** |
| **R15** — no chat identifier in the database | ✅ | The payload carries `chat_id_hash`, a hash. There is no `chat_id` key |
| **D1** — transports selected by config, Bot API the intended default | ✅ | `"transport": "bot_api"`, chosen by `config.yaml`, not by code |
| **R17** — zero tokens | ✅ | `ai_calls` did not increase. No model is in the path |
| **D3** — commit, then send, then record | ✅ | The `notify.sent` row is *later* than the terminal `run.transition`, in that order |

### The delivery path, now verified end to end

```
finalize_run  ->  dispatch_pending  ->  BotApiTransport  ->  api.telegram.org  ->  the chat
   (commits)        (reads run_events)     (real token)         (HTTP 200)        (message seen)
```

Previously verified only as far as `NullTransport` and as far as `responses`-mocked HTTP.
**The last two hops are now real.**

### Two observations from the live run, both investigated

| | Observation | Verdict |
|---|---|---|
| **O1** | The message read *"Run 4 needs approval"* then *"This run is no longer at a gate."* | ✅ **Expected behaviour.** The late-drain design cost recorded in advance ([handover §4](PHASE-07-HANDOVER.md), [STAGE5-FLOW](P7-STAGE5-FLOW.md) A9). Wording only — **[DI21](DEFERRED-IMPROVEMENTS.md)**. **No code changed** |
| **O2** | Asterisks appeared literally rather than as bold | ✅ **Expected behaviour.** Limit **L7**, a decision recorded in `transport.py`'s own docstring |

**Neither is a defect. No production code was changed to record this section.**

### What closing B1 found that the offline half could not

**One test was depending on the token's absence, and nobody could have known.**

`tests/test_notify_dispatch.py::test_building_the_transport_is_lazy_so_construction_never_raises`
asserts `pytest.raises(SendError, match="TELEGRAM_BOT_TOKEN")` — true only when **no** token exists.
`src/settings.py::load_env` calls `load_dotenv(PROJECT_ROOT / ".env", override=False)` **once per
process, lazily**, so the moment any earlier test touches settings, the newly-real token enters
`os.environ` and stays there for the session.

| | Before B1 closed | After B1 closed |
|---|---|---|
| Test alone | ✅ passes | ✅ passes (`1 passed in 2.59 s`) |
| Full suite | ✅ passes | ❌ **fails** (`1 failed, 1130 passed, 2 skipped`) |

**This is a test-isolation defect, not a production one.** Lazy construction still works; a token that
*is* present *should* build a transport. **CI was never affected** — GitHub Actions has no `.env`, so
the token is absent there, which is precisely why nine phases of green CI could not have caught it.

**Fixed** with one line, `monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)`, which
**strengthens** the assertion rather than weakening it ([lock §3](EXECUTION_MODE_LOCK.md) step 6): the
test now proves what its name claims on a machine that has done the live test as well as on one that
has not. **No production code was touched.**

**The general lesson, worth carrying into P8:** *a test that asserts on the absence of something in
the environment is only as trustworthy as the environment's accidental emptiness.* Closing a blocker
can turn a passing test red without any code changing — and the failure is a real finding, not noise.

---

## 8. Commits

| Stage | Commit | Subject |
|---|---|---|
| plan | `19a8c8a` | review, decisions, checklist, testing guide |
| 1 | `5218977` | grep fence 3 (R4) and the `src/notify` boundary fences |
| — | `a79a893` | DI15–DI19 |
| 2 | `a81526e` | five kinds and the deterministic policy table |
| 3 | `67b0c48` | markdown renderers built from SQL |
| 4 | `32b0d13` | transport interface with T1/T2/T3 and token redaction |
| 5 | `e6ad44a`, `20621c1` | Stage 5 flow doc; `run_events`-backed dispatch |
| 6 | `2342924` | proof the wiring did not re-open P6's guarantees |
| 7 | `42ab9b6`, *this commit* | notify config and the YAML null; docs, rollback, records |

**Every stage was CI-green before the next began.**
