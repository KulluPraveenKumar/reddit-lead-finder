# 35 — Testing Strategy

> **The gate every phase must pass.** Automated validation, then a generated manual guide, then
> approval. A phase is not complete until both pass.
>
> Governed by [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md). Phases in
> [34](34-implementation-plan.md).

---

## 1. The testing contract

```
implement  →  AUTOMATED GATE  →  fix  →  re-run  →  MANUAL GUIDE  →  operator runs it  →  approve
                    │                                                                        │
                    └────────────── repeat until every check passes ──────────────────────────┘
```

▶ Two rules make this real rather than aspirational:

1. **Claude runs the automated gate itself and fixes what it finds**, repeating until clean. A phase
   is never handed over with known failures and a note.
2. **The manual guide is written for a non-developer.** If a step cannot be verified without reading
   code, the step is wrong — rewrite it against something observable: a page, a log line, a database
   value, an API response.

### 1.1 Why the pyramid is inverted here

[02 §10](02-research-findings.md) established this and it still holds: **the riskiest code in this
system is the parsers, and they are trivially testable offline.** A Reddit markup change silently
returns zero results with no error anywhere ([K1](ARCHITECTURE_FREEZE.md)). So golden fixtures with
field-by-field assertions sit at the base of the pyramid, not the top.

The Hermes tier inverts it further: an agent's behaviour is not unit-testable, so it is bounded by
configuration and verified by assertion on *config state* and *ledger rows* rather than on outputs.

---

## 2. The automated gate

Every check below runs at the end of every phase. **`make gate` runs all of them.**

### 2.1 Always — all 31 phases

| # | Check | Command | Pass condition |
|---:|---|---|---|
| 1 | Lint | `ruff check .` | Clean |
| 2 | Format | `ruff format --check .` | Clean |
| 3 | Type check | `mypy src/ --ignore-missing-imports` | No new errors vs the baseline |
| 4 | Unit tests | `pytest tests/unit -q` | All pass |
| 5 | Integration tests | `pytest tests/integration -q` | All pass |
| 6 | **Offline guarantee** | Socket-blocking autouse fixture | **Zero network calls** |
| 7 | Coverage | `pytest --cov=src --cov-fail-under=70` | ≥70%; ≥85% on `src/{ai,net,scoring,knowledge}` |
| 8 | **Fence 1** — no vendor coupling outside `src/ai/providers/` | `pytest tests/test_boundaries.py` | Passes |
| 9 | **Fence 2** | `grep -rn "import.*src\.ai" src/rules/ src/dedupe/ src/scoring/ src/knowledge/ src/feedback/ src/discovery/policy.py` | 0 matches |
| 10 | **Fence 3** | `grep -rn "import.*hermes" src/` | 0 matches |
| 11 | **Fence 4** — no Reddit knowledge in `src/net/` | `pytest tests/test_boundaries.py` | Passes |

> ⚠️ **Fences 1 and 4 are AST-based, not `grep`.** An earlier revision of this table specified
> `grep -ri "deepseek" src/` and `grep -ri "reddit" src/net/`. Both **fail against correct, shipped
> code**: 14 files match each, and every match is a **docstring or comment**. `src/net/user_agents.py`
> necessarily explains in its docstring that it exists because of `old.reddit.com` 403s.
>
> The shipped enforcement `tests/test_boundaries.py` parses the AST and says so in its own comment —
> *"Uses `ast` rather than `tokenize`: docstrings are an AST concept."* A literal reading of the old
> text would have forced an engineer to delete the comments that explain why the boundary exists.
> Corrected in P0; see [SPRINT-0-MEASUREMENTS §7](SPRINT-0-MEASUREMENTS.md).
>
> Fences 2 and 3 remain `grep` because they match on `import` statements, which do not appear in prose.
| 12 | **Migration round-trip** | `upgrade head` → `downgrade -1` → `upgrade head` on a **copy** of `leads.db` | Succeeds; `alembic heads` = 1 |
| 13 | **Legacy regression** | 459 leads · `intent_score` SHA-256 unchanged · `GET /` byte-identical · 13 CSV columns · 17 endpoints identical | All |
| 14 | Secret scan | grep logs, DB, templates, repo, API responses for credential shapes | 0 matches |
| 15 | Error-path tests | Every typed exception raised and handled | All covered |
| 16 | Edge cases | Empty, null, max-length, unicode, malformed | All covered |
| 17 | Logging validation | Every log record carries `run_id`/`job_id`/`project_id` when in scope; redaction active | Asserted |
| 18 | Documentation validation | Every doc edit this phase owns has landed; no broken internal link | Asserted |

### 2.2 Conditional — when the phase touches the area

| Check | Applies when | Pass condition |
|---|---|---|
| **API contract** | Any route changes | Recorded request/response replay; only **additive** field changes allowed |
| **Database validation** | Any migration | Table/column/index/FK present; `PRAGMA foreign_key_list` verified; row counts unchanged |
| **Performance** | P3, P10, P11, P21, P22, P26 | Named budget in the phase's Metrics row |
| **Concurrency** | P2, P6, P20 | Race, lease-expiry, shuffled-completion, soak |
| **Retry** | P2, P4, P20 | Backoff growth, max attempts, non-retryable classes |
| **Cost validation** | P14, P19, P20, P24 | `ai_calls` count and USD within the phase's stated bound |
| **Telemetry** | P2, P24, P26 | Metrics written; agent rows excluded from efficiency queries |
| **Memory validation** | P24, P26 | Cache-is-not-state; agent-memory-is-not-state |

### 2.3 The four checks that are non-negotiable

▶ These four have caught real defects in this codebase already, or exist to catch a Critical risk.
**A phase does not merge with any of them failing, regardless of schedule.**

| Check | Guards | Evidence it matters |
|---|---|---|
| **Legacy regression (13)** | 459 real leads and a working dashboard | The whole compatibility contract |
| **Grep fences (8–11)** | The four architectural boundaries | The only mechanical enforcement the architecture has |
| **Migration round-trip (12)** | The live database | ✅ [K14](ARCHITECTURE_FREEZE.md) — Critical |
| **Offline guarantee (6)** | Test-suite honesty | ✅ [PHASE-01-STATUS AC9](PHASE-01-STATUS.md) noted this was *not* machine-enforced; a socket-blocking fixture closes it |

### 2.4 Mutation discipline

✅ [PHASE-02-STATUS §7](PHASE-02-STATUS.md) records that mutation testing caught **two tests that
passed for the wrong reason** — a soft-block fixture that tripped two independent detection paths,
and a cache test that exercised the wrong guard.

**▶ Rule: for every acceptance criterion, deliberately break the guarantee in the source, confirm the
test fails, and restore it.** A test that has never been seen to fail is not evidence.

Required for: every criterion marked **bold** in [34](34-implementation-plan.md), and every check in
§2.3.

---

## 3. Test layout

```
tests/
├── conftest.py               # session fixtures; SOCKET-BLOCKING autouse fixture
├── fake_provider.py          # LLMProvider double — the whole AI suite runs on this
├── fake_hermes.py            # seam double
├── fake_session.py           # requests.Session double at ProxyManager.session_for
├── fixtures/
│   ├── html/                 # golden old.reddit pages + .expected.json
│   ├── atom/                 # golden RSS feeds + .expected.json          ← P5
│   ├── sites/                # website fixtures incl. an SPA shell and a 404
│   ├── llm/                  # recorded provider responses
│   ├── golden_leads.jsonl    # 40 items (P20) → 100 items (P25)
│   └── budgets/              # the five 06f §4 distributions               ← P19
├── unit/
├── integration/
├── migration/                # runs against a COPY of the live leads.db
└── regression/               # the legacy contract — check 13
```

**▶ `conftest.py` gets the socket-blocking fixture in P2**, not later. Adding it once tests exist
means retrofitting; adding it first means the guarantee holds from the beginning.

---

## 4. Phase → test-document mapping

[33 §2.6](33-final-review.md) found the old mapping broken by renumbering. The resolution:

| Old | Covers | New home |
|---|---|---|
| `testing/phase-01-testing.md` | AI foundation | ✅ Shipped — retained as the historical record |
| `testing/phase-02-testing.md` | Proxy & transport | ✅ Superseded by [PHASE-02-STATUS §5](PHASE-02-STATUS.md) |
| `testing/phase-03-testing.md` | Orchestration | → `testing/phase-01-03-testing.md`? **No** — new guides are `testing/P01-testing.md` … `P30-testing.md` |
| `phase-04` … `phase-08` | — | Content redistributed across P12–P27; the old files are retained and marked *superseded, content migrated* |

▶ Renaming the eight existing files would churn every cross-reference in the set. The mapping table
in [README](README.md) is cheaper and loses nothing.

---

## 5. The manual testing guide template

Every phase generates `docs/testing/PNN-testing.md` from this template. The format matches
[MANUAL-TESTING-PHASE-01.md](MANUAL-TESTING-PHASE-01.md), which is the house style and is written so
a non-developer can follow it.

```markdown
# Manual Testing Guide — Phase NN: <Title>

Written so a **non-developer can validate this phase without guessing**.
Every step states what you should see. If what you see differs, that step's
*Possible failure* section tells you what it means.

- **Time:** ~NN minutes for the full suite, ~N minutes for the smoke path (T1–T3).
- **You need:** <terminal / browser / Telegram / API key>
- **Destructive steps:** <none, or named and marked reversible>

Throughout, `>` marks a command to run and `→` marks what you should see.

---

## Before you start

> cd <the folder containing pyproject.toml>
> python -m pip install -r requirements.txt
→ Finishes without errors.

**If the app is already running**, stop it first — a stale process keeps port
5000 and serves you *old code*, which looks exactly like a broken change:

> powershell "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*dashboard*' } | Stop-Process -Force"

**Take a backup before any step marked ⚠️:**
> python scripts/backup.py

---

# T1 — <Objective in one line>

**Purpose:** <what this test proves>
**Preconditions:** <what must already be true>

### Step 1
> <exact command, or "Open http://127.0.0.1:5000/x in a browser">

→ **Expected:** <exactly what appears — quote real output>

**Possible failure**
| You see | Meaning | Troubleshooting |
|---|---|---|
| <symptom> | <cause> | <fix> |

**Screenshot expected:** <what to capture, or "none">

**Logs to verify**
> python -c "..."  or  tail the log
→ Contains: `<exact line or field>`

**Database values to verify**
```sql
SELECT ... FROM ... WHERE ...;
```
→ Returns: `<exact expected value>`

**API response to verify**
> curl -s http://127.0.0.1:5000/api/... | python -m json.tool
→ Contains: `"field": <value>`

**Acceptance:** ✅ <the binary condition for this step>

### Step 2
…

**Expected final result:** <the state of the system after T1>

---

# T2 — …

---

## Rollback verification

**Purpose:** prove this phase can be undone in production.

### Step 1
> <the rollback command from the phase's Rollback Plan>
→ <what returns to the previous behaviour>

### Step 2
Confirm the legacy contract still holds:
> curl -s http://127.0.0.1:5000/api/leads/export | head -1
→ Exactly 13 columns.
```sql
SELECT COUNT(*) FROM leads;
```
→ ≥ 459.

**Acceptance:** ✅ The system behaves as it did before this phase.

---

## Sign-off

| Check | Pass |
|---|---|
| All T-tests passed | ☐ |
| Rollback verified | ☐ |
| No unexpected errors in the log | ☐ |
| 459 leads intact | ☐ |
| Dashboard renders | ☐ |

**Tester:** __________  **Date:** __________
```

### 5.1 Rules for writing a manual step

| Rule | Why |
|---|---|
| **Quote real output**, never paraphrase | *"Shows the run status"* is unverifiable; a quoted line is |
| **One assertion per step** | A failed compound step does not say which half failed |
| **Every step names an observable** | Page, log line, SQL result, or API field — never *"it should work"* |
| **Failures get meanings, not just symptoms** | ✅ [MANUAL-TESTING-PHASE-01 T1](MANUAL-TESTING-PHASE-01.md) does this well: *"`No package.json found` → You ran `pnpm`/`npm`. This is a **Python** project"* |
| **Mark destructive steps ⚠️ and state the reversal** | A non-developer must never be surprised |
| **Include the rollback test** | A rollback plan nobody has run is a hope |

---

## 6. Per-phase testing requirements

Beyond the universal gate. Only the additions are listed.

| Phase | Additional automated | Manual guide focus |
|---|---|---|
| **P0** | None — probes are throwaway | Read the measurements document; confirm 16/16 answered |
| **P1** | Illegal-transition raises; FK present | Migration runs; 459 intact; `alembic heads` = 1 |
| **P2** | **Claim race (2 workers), lease expiry, SIGTERM < 30 s, 10-min soak with 0 lock errors**, full-log secret grep | Start worker; kill it mid-job; restart; job completes once |
| **P3** | Progress < 50 ms at 5,000 jobs; `/api/scrape` contract replay | Click Run Scraper; watch progress; cancel; restart process; run resumes |
| **P4** | All 251 `src/net/` tests; provider construction from config ×5; leak detection | `/health/proxies`: 10 rows, **no credentials**; force pool exhaustion; see the degradation warning |
| **P5** | Atom fixtures field-by-field; 304 handling; malformed feed raises | Fetch one feed by CLI; compare entry count to the site |
| **P6** | **Overflow fixture (150 posts)**; idle poll = 1 request; statement counter for cache bypass | Run a poll twice; second finds nothing and costs one request |
| **P7** | **Token cost = 0**; duplicate = 0 over 20 replays; transport-down path | Complete a run; **receive one Telegram message**; check `ai_calls` for zero agent rows |
| **P8** | Migration ordering; 459 rows get correct defaults | Confirm the four new columns and their values on a legacy lead |
| **P9** | Grep fence 2; 11 reasons counted; property test | Feed a hiring post through; see it rejected with reason `structural_noise` |
| **P10** | **2,000 items < 2 s**; identical lead set with tier 3 off; N distinct pre-scores | Two near-identical posts group; both still appear in the list |
| **P11** | **0 AI calls**; comment requests −5%; triage miss rate < 5% | Read the funnel counts on the run page; they sum correctly |
| **P12** | **Migration completes with `sqlite-vec` absent**; 4 FKs; payload-NULL rule | `/health` shows `semantic_layer` state |
| **P13** | Direct egress asserted; L1 hit = 0 fetches; `file://` → 422 | Paste a URL; see the snapshot; paste it again; **no second fetch** |
| **P14** | **Exactly 1 `ai_calls` row**; < $0.05; section isolation | See 23 sections render; cost chip shows one call |
| **P15** | **Regenerate twice, lose no learned row**; clock advance changes no score | Edit a section; regenerate a different one; the edit survives |
| **P16** | **`GET /` byte-identical snapshot** | Open `/`; it looks exactly as before |
| **P17** | **0 AI calls for discovery/keywords**; ≥70% survival | See the rejected list with reasons |
| **P18** | Gate survives restart 10/10; estimate ±30% | Reach Gate 1; restart the app; the gate is still there |
| **P19** | **5/5 budget fixtures**; fit query has no admitted filter | Options screen shows the method and the counterfactual |
| **P20** | **Shuffled-completion attribution (blocking)**; cache hit > 85%; miss rate < 5% | Run enrichment; check calls-per-1,000 on `/health/ai` |
| **P21** | **Breakdown reconciles exactly**; rescore 10k < 2 s, 0 calls; 459 unchanged | Open a lead; add the components; they equal the score |
| **P22** | < 200 ms at 10k; 0 dangling entity links | Sort, filter, open the drawer, click an entity link |
| **P23** | Toolsets absent at runtime; 0 title-generation calls; no `hermes` import | Stop Hermes; **the pipeline still works** |
| **P24** | **Governor blocks with 0 calls**; agent rows excluded from efficiency | Hit the cap; conversation stops, **notifications keep arriving** |
| **P25** | **Degraded prompt version refused**; patterns 0 AI calls | Label a lead; see it in the quality page |
| **P26** | **Sort order identical after recalibration**; cache deletion changes no score | Read `/health/quality`; every number drills through |
| **P27** | **Byte-identical legacy CSV**; 10k export memory bound | Export CSV, JSON, XLSX; open the XLSX |
| **P28** | **EACCES reading the DB as the Hermes user**; seam unreachable externally | Reboot the VPS; both services come back |
| **P29** | **Restore drill executed and timed** | Restore a backup into a temp path; it opens with 459 leads |
| **P30** | Full security checklist; CI blocks on each gate | Push a deliberate lint error; **CI fails** |

---

## 7. Definition of done

A phase is complete **only if every line is checked**:

- [ ] Code implemented
- [ ] `make gate` passes — all 18 universal checks plus the phase's conditional ones
- [ ] Mutation discipline applied to every bold acceptance criterion
- [ ] Documentation edits owned by this phase have landed
- [ ] Manual testing guide generated at `docs/testing/PNN-testing.md`
- [ ] Manual testing executed and signed off
- [ ] Performance within the phase's stated budget
- [ ] Cost within the phase's stated bound (`ai_calls` count and USD)
- [ ] Logging verified — correlation IDs present, redaction active
- [ ] Error handling verified — every typed exception raised and handled
- [ ] **Rollback executed and verified**, not merely documented
- [ ] Legacy contract intact: 459 leads · `intent_score` unchanged · `GET /` byte-identical · 13 CSV columns · 17 endpoints

▶ **The rollback line is the one most likely to be skipped and the one most worth keeping.** Every
phase in [34](34-implementation-plan.md) names a rollback; a plan that has never been executed is a
guess about behaviour under conditions nobody has tried.
