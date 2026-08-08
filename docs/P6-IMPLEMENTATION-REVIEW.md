# P6 IMPLEMENTATION REVIEW — Watermarks & incremental discovery

**Written:** 2026-08-08, **before** any production code.
**Governs:** [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) (constraints) ·
[EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md) (process).
**Companions:** [P6-DECISION-ANALYSIS.md](P6-DECISION-ANALYSIS.md) ·
[P6-IMPLEMENTATION-CHECKLIST.md](P6-IMPLEMENTATION-CHECKLIST.md) ·
[testing/P06-testing.md](testing/P06-testing.md).

> These are **execution records** of the kind P4 and P5 produced. They are not new architecture,
> roadmap, governance or testing-strategy documents, and are therefore not on
> [lock §2](EXECUTION_MODE_LOCK.md)'s prohibited list.

> ⚠️ **§2.3 is the material section of this review.** P6 Task 5 is specified on a premise P5
> measured to be false. This document redesigns it, and the redesign **removes** a component rather
> than replacing it. Read §2.3 before reading the task list.

---

## 1. The authoritative specification for P6

| Rank | Document | What it settles for P6 | Status |
|---|---|---|---|
| **1** | [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) — R1–R20, AD-1…AD-31, **§4.1 chain**, **§11 amendments** | R3 (`discovery/policy.py` never imports `src.ai`), R8 (worker is sole bulk writer), R9 (handlers idempotent), R11 (every discarding gate is audited), R18 (RSS direct), R19 (**watermark overflow is an error, never a silent gap**), R20 (legacy contract). §4.1 fixes `0005`'s contents. **§11 carries the amendment that refutes Task 5's premise** | Authoritative |
| **2** | [SPRINT-0-MEASUREMENTS.md §2](SPRINT-0-MEASUREMENTS.md) | U1 (rate limit is **per IP**, ~60 s), U3 (boolean search), U5 (`limit=100`) | Authoritative — measurement beats text |
| **3** | [34-implementation-plan.md §P6](34-implementation-plan.md) (lines 274–289) | Objective, Deliverables, Files, DB, Config, Tasks 1–8, Acceptance, Metrics, Rollback, Docs | Authoritative **except** Task 5 — see §2.3 |
| **4** | [28-discovery-redesign.md](28-discovery-redesign.md) §3 (stages), §3.1 (`discovery_watermarks`), §8.1 (`next_interval`), §9 (D1–D7), §10, §11 (D-AC1…D-AC12) | Stage semantics, the watermark table, the polling algorithm, the failure register | Authoritative **except** §3 stage 4, §9 D7, §9 D3 and §10's `ALTER` — see §2 |
| **5** | [05-database-plan.md §5.4](05-database-plan.md) | `prescores` column list | Authoritative **except** its `comment_id` FK — see §2.4 |
| **6** | [35-testing-strategy.md](35-testing-strategy.md) §2, §5, §6 | The gate, manual-guide rules, P6's additional test requirements | Authoritative |
| **7** | [PHASE-05-HANDOVER.md](PHASE-05-HANDOVER.md) | G1–G7 (must not break), T0–T7 (traps), entry conditions, **§4** | Authoritative for entry |

**Nothing else is a P6 specification.** In particular [16-phase-06.md](16-phase-06.md) and
`docs/testing/phase-06-testing.md` are **not** — see §2.1.

---

## 2. Document conflicts, stale assumptions and numbering traps

Six found. One numbering trap, one refuted premise (§2.3, the material one), two schema
disagreements, two scope-ownership conflicts.

### 2.1 The numbering trap — restated once more

⚠️ **`docs/16-phase-06.md` and `docs/testing/phase-06-testing.md` are NOT this phase.** They belong
to the superseded eight-phase scheme completed 2026-07-30/31 ([lock §2.1](EXECUTION_MODE_LOCK.md)).
P4 and P5 each paid to establish this for their own number; P6 pays it once and moves on.

### 2.2 What is NOT re-litigated

Conditional GET is gone. The U4 amendment (2026-08-05) deleted layer L1; P5 reconciled the four
stale documents and shipped
`tests/test_boundaries.py::test_conditional_get_has_not_been_reintroduced`. **P6 Task 2's
"~~conditional GET~~ ⛔ struck" is already correct and needs no further action.** `get_feed` was
re-measured live on 2026-08-08 during this review's entry checks: `Cache-Control: private,
max-age=3600`, no `ETag`, no `Last-Modified`.

### 2.3 ⚠️ Conflict C1 — Task 5's density heuristic rests on a refuted premise

**This is the material finding.** [34 §P6](34-implementation-plan.md) Task 5 specifies:

> ~~Stage 4 density-adaptive body fetch (listing ≥25%, permalink <25%, hysteresis 30/20)~~

The premise is [28 §2.2](28-discovery-redesign.md)'s *"an HTML listing page carries 25 posts with
body and score."* P5 measured that **it carries no body at all**, and the measurement is already a
[freeze §11](ARCHITECTURE_FREEZE.md) amendment dated 2026-08-08.

**Re-confirmed during this review**, live, `scripts/validate_feed_parity.py --subreddit startups`:

| Source | Bodies | Measured |
|---|---|---|
| HTML listing, live `/r/startups/new/` | **0 of 25** | 2026-08-08, this session |
| Feed, live | **100 of 100** | 2026-08-08, this session |

Exit code 0; 25 posts agreed on all seven compared fields, with `body` the sole tolerated difference
on all 25.

#### 2.3.1 The redesign — enumerate what stage 4 must source

The handover framed the open question as *"feed body vs permalink fetch, and the branch may not need
to exist."* That framing is incomplete: stage 4 in [28 §3](28-discovery-redesign.md) delivers three
data classes, not one — *"Score and comment-count arrive here, not before."* Enumerating them makes
the decision mechanical rather than a judgement call:

| Datum stage 4 was to source | Where it actually exists | Cost in P6 | Owner |
|---|---|---|---|
| **Selftext, self posts (~97%)** | The **feed**, in the request stage 1 already makes | **0 requests** | P6 — already delivered by P5's `get_feed` |
| **Selftext, link/media posts (~3%)** | **Nowhere.** A link post has no selftext on any endpoint | — | **Nobody.** There is nothing to fetch |
| **`score`, `num_comments`** | HTML listing (25/req) or permalink (1/req) | — | **P11**, Task 4 — see §2.5 |
| **Comments** | Permalink, one per post | — | **P11**, Task 3 (`CommentScraper`) — see §2.5 |

▶ **Every row is either free, non-existent, or owned by a later phase. Nothing is left for a density
decision to choose between.**

#### 2.3.2 The decision: the heuristic is deleted, not re-targeted

**`density_threshold`, the 25% crossover, and D7's 30/20 hysteresis are not implemented in P6.**

Three independent reasons, any one of which is sufficient:

1. **Its inputs do not exist.** The choice was *listing vs permalink for bodies*. The listing branch
   returns zero bodies at any density, so the "heuristic" reduces to a constant — and a branch with
   one reachable arm is not a branch.
2. **The remaining candidate consumer is a later phase's.** Score back-fill (§2.5) is P11's, and
   P11 performs it *during a permalink comment fetch it is making anyway* ([34 §P11](34-implementation-plan.md)
   Task 4: *"Score back-fill for search-sourced leads during comment fetch"*). A request already
   being made for another reason has no density decision to make.
3. **[lock §8](EXECUTION_MODE_LOCK.md) and the "no speculative implementation" standard.** Building
   a configurable threshold whose only caller arrives five phases later, against data whose shape
   P11 will measure for itself, is speculative by definition.

**What P6 ships in stage 4's place** is not nothing — it is the honest accounting the deleted branch
was hiding:

- `body_source` is recorded per post (`feed` | `absent`), so the ~3% is *counted*, not assumed.
- A test asserts that a link/media post yields `body_source='absent'` and an empty body — **not** a
  silent `""` indistinguishable from a self post with no text.
- The `discovery.density_threshold` config key from [34 §P6](34-implementation-plan.md)'s Config row
  is **not added**. Adding a key nothing reads is a documented capability that does not exist —
  P5's F3 in a new costume.

#### 2.3.3 This is a reconciliation, not a new amendment

The amendment already exists ([freeze §11](ARCHITECTURE_FREEZE.md), 2026-08-08) and already states
that Task 5 *"must be redesigned in P6."* Filing a second amendment for a settled measurement is
what [P5-DECISION-ANALYSIS §D1](P5-DECISION-ANALYSIS.md) argued against.

**P6's obligation is [handover F7](PHASE-05-HANDOVER.md) — *an amendment must be applied, not
merely recorded*.** P6 lands the corrected text as [§11.1](ARCHITECTURE_FREEZE.md) reconciliations
in the three places that still describe the deleted branch:

| Document | Stale text | Correction |
|---|---|---|
| [28 §3](28-discovery-redesign.md) stage 4 box | *"survivors ÷ discovered ≥ 25% → HTML LISTING walk (25/req, full data)"* | The listing carries no body; the feed supplies it; score/comments are P11's |
| [28 §9](28-discovery-redesign.md) **D7** | *"Density heuristic thrashes at the 25% boundary → hysteresis 30/20"* | Void — there is no heuristic to thrash |
| [28 §9](28-discovery-redesign.md) **D3** | *"fall back to HTML listing automatically"* | Restores **discovery**, not bodies — see §2.3.4 |

#### 2.3.4 The consequence for D3 and overflow, stated rather than left implicit

[28 §9 D3](28-discovery-redesign.md) and [28 §9 D1](28-discovery-redesign.md) both fall back to an
HTML **listing** walk. That fallback still works **for its actual job — recovering post ids** — and
P6 keeps it there. It is not re-targeted to HTML search, which cannot enumerate a subreddit's recent
window reliably.

But it must be said plainly: **overflow-recovered and RSS-outage posts arrive with no body.** They
have aged out of the feed, and per-post permalink is the only remaining source. Overflow is rare by
construction (`window_target` 60 against a 100-item ceiling), so this is acceptable — but it is a
documented degradation, not a silent one. `body_source='absent'` records it.

### 2.4 Conflict C2 — three documents disagree about `prescores`

| Where | What it says | Verdict |
|---|---|---|
| [freeze §4.1](ARCHITECTURE_FREEZE.md) | `0005` **creates** `prescores` incl. `stage`; `comment_id` FK **deferred** to `0006` | **Wins** — rank 1, and [33 §2.4](33-final-review.md) moved the table here |
| [28 §10](28-discovery-redesign.md) | `ALTER TABLE prescores ADD COLUMN stage` | **Stale.** Pre-dates the move; there is no table to alter |
| [05 §5.4](05-database-plan.md) | `CREATE TABLE prescores` **without** `stage`, `comment_id INTEGER NULL REFERENCES comments(id)` | **Partly stale.** Column list is authoritative; the inline FK violates **M8** |

**Verified, not assumed:** `prescores` appears in **no** migration (`0001`–`0004`), in **no** module
under `src/`, and in **none** of the live database's 18 tables. The `ALTER` could not execute.

**Resolution:** `0005` creates `prescores` with [05 §5.4](05-database-plan.md)'s columns, **plus**
`stage VARCHAR(20) NOT NULL DEFAULT 'full'` inline, and `comment_id INTEGER NULL` as a **bare column
with no `REFERENCES` clause** (M8) — the FK is added by `0006`'s `batch_alter_table` when `comments`
exists. Recorded as a [§11.1](ARCHITECTURE_FREEZE.md) reconciliation.

### 2.5 Conflict C3 — who owns score back-fill, comments, and the stage-3 holdout?

[28 §3](28-discovery-redesign.md)'s stage diagram puts all three inside the discovery pipeline,
which reads as P6 work. [34](34-implementation-plan.md)'s phase rows put all three in **P11**:

| Capability | [28 §3](28-discovery-redesign.md) | [34 §P11](34-implementation-plan.md) | Owner |
|---|---|---|---|
| `score` / `num_comments` back-fill | Stage 4 — *"arrive here, not before"* | Task 4 — *"Score back-fill for search-sourced leads during comment fetch"* | **P11** |
| Comment expansion | Stage 6 | Task 3 — `CommentScraper`, Deliverables | **P11** |
| Stage-3 holdout audit (D-AC8, R11) | §9 D6 — *"extend the holdout audit to Stage 3"* | Task 6 + Deliverables + `gate.metadata_holdout_rate` | **P11** |

**[34](34-implementation-plan.md) wins on all three**, and the evidence is not merely that it is a
phase plan: **P6's own Tasks field stops at 8 and lists none of them**, while P11's Deliverables
name all three explicitly. The tables they need confirm it — `comments` arrives in `0006` (P8) and
`gate_audits` in `0009` (P19), neither of which exists when P6 runs.

**The R11 obligation is real and P6 must not discharge it by ignoring it.** Stage 3 is a new gate
that discards items, so AD-10b applies. P6's honest position:

- P6 **persists a `prescores` row for every triaged item, admitted or rejected**, with
  `stage='metadata'` and `gate_reason` set. This is what makes the audit *possible*.
- P6 does **not** implement the 2% sampling, the body re-fetch or the miss-rate publication. Those
  need `gate_audits` (`0009`) and full scoring (P11).
- `holdout_sampled` ships as a column in `0005` (it is in [05 §5.4](05-database-plan.md)) and
  P6 writes `0` to it. **No eleventh table is invented** ([freeze §4.1](ARCHITECTURE_FREEZE.md):
  *"Ten revisions. No eleventh without an amendment"*).

Stated loudly per [lock §4.1](EXECUTION_MODE_LOCK.md), because leaving it implicit is exactly the
silent narrowing that rule forbids.

### 2.6 Conflict C4 — `discovery/policy.py` location

[28 §8.1](28-discovery-redesign.md)'s code block is headed `scoring/discovery_policy.py`.
[34 §P6](34-implementation-plan.md)'s Files row and [freeze R3](ARCHITECTURE_FREEZE.md) both say
`src/discovery/policy.py`. **R3 and the Files row win** — R3 names `discovery/policy.py` by path in
a frozen rule. Cosmetic; noted so the next reader does not create a second file.

---

## 3. Dependency verification and baseline

### 3.1 Phase dependencies — [34 §P6](34-implementation-plan.md): **Depends on P5**

| Dependency | Required for P6 | Verified |
|---|---|---|
| **P5** `get_feed()` — one request, multireddit, `limit` clamp | Stage 1's only transport | ✅ `src/reddit_client.py`, [handover §1.1](PHASE-05-HANDOVER.md) |
| **P5** `parse_feed` raises on malformed, `[]` on empty | G3 — the distinction stage 2 depends on | ✅ `src/discovery/feed_parser.py` |
| **P5** `score`/`num_comments` are `None`, never `0` | G7 — reaches the DB in P6 | ✅ |
| **P5** `allow_cache=False` (D5) | D-AC10, asserted by statement counter | ✅ |
| **P5** `request_class="rss"` → direct (R18) | Egress policy | ✅ |
| **P0 U1** — rate limit per IP, ~60 s | Multireddit is mandatory; the poller must space requests (T5) | ✅ |
| **P0 U3** — boolean `subreddit:A OR subreddit:B` | Stage 5's search-feed shape (Task 6) | ✅ |
| **P0 U5** — `limit=100` honoured | The 100-item ceiling `window_target` is sized against | ✅ |
| **P1–P3** — `runs`, `jobs`, `run_events`, worker, `RunService.transition()` | The handler's host; `run_id` FK on `prescores` | ✅ `0004_orchestration` |
| **P4** — one policy per process | G4 — the handler must not build its own | ✅ |

### 3.2 Repository health at entry — measured 2026-08-08, this session

| Check | Result |
|---|---|
| `git status --short` | **Clean** — no output |
| Full suite | **803 passed, 2 skipped** in 140.7 s — matches [handover §7](PHASE-05-HANDOVER.md) exactly |
| `pytest -W error::DeprecationWarning` | **803 passed, 2 skipped** in 140.2 s |
| `ruff check .` | All checks passed! |
| `ruff format --check .` | 109 files already formatted |
| `python scripts/check_schema.py` | **OK — all 25 checks passed** |
| `alembic heads` | `0004_orchestration (head)` — **one head** |
| `scripts/validate_feed_parity.py` (T7) | **exit 0** — 25 posts agree on all 7 fields; `body` the sole tolerated difference ×25; feed 100/100 bodies |
| Live DB | 18 tables · 471 leads (459 baseline intact) · `prescores` **absent**, confirming §2.4 |

**No finding at entry.** Unlike P5 (which found an un-executed P4 rollback), the tree was clean on
first inspection and the baseline was recorded from it.

---

## 4. Acceptance criteria

### 4.1 P6-specific — [34 §P6](34-implementation-plan.md), as reconciled

| # | Criterion | Bold? | How it is proved |
|---|---|---|---|
| **A1** | A poll with nothing new issues **exactly one** request and creates **zero** rows | **Yes** | A `responses`-mocked feed replayed twice; request counter == 1 on the second; row counts before == after. Mutation M1 |
| **A2** | Overflow is **logged as an error** and triggers HTML fallback | **Yes** | Fixture: 150 new posts between polls (feed's oldest is newer than `last_seen_utc`); assert `ERROR` level, `run_events` row, fallback invoked, interval shortened. Mutation M2 |
| **A3** | **Steady-state daily requests ≤ 80** | **Yes** | A deterministic simulation over the 10-subreddit / 12-keyword scenario driving `next_interval()` for 24 h; assert the total. No network |
| **A4** | Cold start collects **≥95%** of what the HTML design collects | No | Fixture-based: the same subreddit rendered as both a 100-entry feed and HTML listing pages; compare id sets. **See §8 A-4** — the live half is *not* claimed without a capture |
| **A5** | `discovery/policy.py` makes **zero** AI calls and imports no `src.ai` | **Yes** | `tests/test_boundaries.py` (AST-based, extends P5's `test_discovery_makes_no_ai_calls`) + an `ai_calls` count assertion. Mutation M3 |
| **A6** | Discovery bypasses `http_cache` | **Yes** | Statement counter around a poll asserting zero `http_cache` SELECTs (D-AC10) |
| **A7** | With `rss_enabled: false` the HTML path passes every test | **Yes** | The whole P6 suite parametrised over both flag states. Mutation M4 |
| **A8** | `policy.next_interval()` computes in **< 1 ms** | No | `perf_counter` over 1,000 calls, asserted with headroom |

### 4.2 Universal — [34 §1.2](34-implementation-plan.md), every phase

`ruff check` + `ruff format --check` · `pytest` green with **no live network** · coverage ≥70% on
new modules · **all four grep fences** · `alembic upgrade head → downgrade -1 → upgrade head` on a
**copy** of the live DB (**this is P6's first migration since `0004`, so C1 finally bites — see
§7 R-8**) · legacy contract (459 leads, `intent_score` fingerprint, `GET /`, 13 CSV columns, 17
endpoints) · `check_schema.py` extended for `0005` · manual guide generated **and executed**.

---

## 5. Mandatory boundaries

| # | Boundary | Source | How P6 holds it |
|---|---|---|---|
| **B1** | **Never hold the SQLite write lock across I/O** | [handover T0](PHASE-05-HANDOVER.md) — cost P3 a sign-off | **The highest-risk boundary in this phase.** P6 adds the first discovery handler and the first discovery write. The handler fetches *outside* the session, then opens a short write transaction. Event emission happens **after** the fetch returns, never before |
| **B2** | `src/discovery/` imports no `src.ai` | [handover G1](PHASE-05-HANDOVER.md), R3, A5 | Extends P5's AST boundary test to the new modules |
| **B3** | `src/net/` contains zero Reddit identifiers | R5, fence 4 | P6 does not touch `src/net/` |
| **B4** | One policy per process | [handover G4](PHASE-05-HANDOVER.md) | The handler receives a client; it never calls `get_policy` or `build_policy_from_config` |
| **B5** | **The six frozen `RedditClient` methods are unchanged** | AD-2, [handover G6](PHASE-05-HANDOVER.md) | Introspection test from P5 must keep passing. P6 adds no seventh method |
| **B6** | **A malformed feed raises; an empty feed returns `[]`** | [handover G3](PHASE-05-HANDOVER.md) | P6 must not collapse them. A damaged response read as `[]` advances nothing and reports silence — the exact shape of D2 watermark poisoning |
| **B7** | The worker is the **sole bulk writer** (R8) | Freeze | The discovery handler runs in the worker. No web route writes watermarks |
| **B8** | Every job handler is **idempotent** (R9) | Freeze | Re-running a discovery job over the same feed creates no duplicate `prescores` and does not double-advance the watermark. Lease-expiry re-run test |
| **B9** | **Overflow is an error, never a silent gap** (R19) | Freeze | A2 + mutation M2 |
| **B10** | Additive migration only (M5); one head (M1); tested `downgrade()` (M6) | Freeze §4 | `0005` creates two tables and alters none |

---

## 6. Interfaces

### 6.1 New — `src/discovery/watermarks.py`

```python
@dataclass(frozen=True)
class DiffResult:
    new_posts: list[dict]      # posts not already seen
    overflow: bool             # the window advanced past us — see below
    seen: int

def diff(posts: list[dict], watermark: Watermark | None) -> DiffResult: ...
def advance(watermark: Watermark, posts: list[dict]) -> Watermark: ...
```

Pure functions over dicts and a row. **No session, no client, no config** — which is what lets the
overflow fixture be a list literal rather than a database.

**The overflow guard is written out in full, because two of its three false cases are reachable and
neither is an error:**

```python
overflow = (
    watermark is not None                      # cold start is NOT overflow
    and watermark.last_seen_utc is not None    # a never-advanced watermark is NOT overflow
    and bool(posts)                            # an empty feed is NOT overflow
    and oldest(posts).created_utc > watermark.last_seen_utc
)
```

A cold start legitimately sees a full feed of unseen posts, and an empty feed legitimately sees
none. Collapsing either into overflow would make R19's error fire on the two most ordinary paths in
the system, and an error that fires constantly is an error nobody reads.

⚠️ **Mutation M2 as originally designed (`overflow` returns `False` always) cannot catch an inverted
null-guard**, because the guard's failure direction is *over*-reporting. A2's fixture set therefore
carries **four** cases, not one: 150-new-posts (overflow), cold start (not), empty feed (not), and
normal incremental (not). See §10.2 M2/M2a.

**Diffing is on the id set, never on id comparison** (A-2): `t3_` fullnames are base-36 but not
reliably ordered across shards, so `last_seen_utc` is used *only* for the overflow test and never to
decide which posts are new.

### 6.2 New — `src/discovery/policy.py`

```python
def next_interval(w: Watermark, cfg: PolicyConfig, *, yield_ratio: float = 0.0) -> timedelta: ...
```

[28 §8.1](28-discovery-redesign.md) exactly: EWMA rate → `window_target / rate` → empty backoff →
yield boost → clamp. **Deterministic, zero AI, no `src.ai` import** (R3, A5). `subreddit_yield` is
passed in as a number rather than queried, so the module holds no session.

### 6.3 New — `src/db/repositories/discovery.py`

Watermark read/upsert, the due-queue query (`next_poll_at <= now`), and the `prescores` bulk insert.
Follows the shape of the existing `runs.py` / `leads.py` repositories.

### 6.4 New — `src/orchestration/handlers/discover.py`

One job handler, registered alongside `scrape`, `finalize`, `maintenance`. **Fetch outside the
session; write inside a short transaction; emit events after the fetch** (B1).

### 6.5 Changed — `src/scrapers/base.py`

Stage 4's body accounting (§2.3.2) — `body_source` recording. **Not** a density decision.

### 6.6 Changed — `src/reddit_client.py` — the N2/T1 closure

[handover T1](PHASE-05-HANDOVER.md) assigns to P6: `_get` currently swallows every transport failure
and returns `None`, making `pause_run` and `fail_run` indistinguishable at run level (**N2**). P6
makes the transport raise and `handlers/` map the exception to a run outcome.

⚠️ **This touches shipped, tested code on a `["ALL"]` lint-exempt module and is the second-highest
risk in the phase** (§7 R-2). It is in scope because the handover assigns it here and A2's error
path depends on it — an overflow that cannot be distinguished from a transport failure is not an
error, it is a `None`.

**The caller policy, settled here rather than discovered at step 5.** `_get` has callers beyond
discovery: all six frozen `RedditClient` methods (AD-2, B5) and `src/scrapers/*`. Two designs were
available:

| Design | Effect on shipped callers | Verdict |
|---|---|---|
| **`_get` raises; each frozen method catches and returns `None`** | **None.** The six keep their documented return shape; only the new discovery path sees the exception | ✅ **Chosen** |
| `_get` raises and the exception propagates through the frozen methods | A behaviour change to six shipped methods | ❌ Violates AD-2's return shape and risks R20; **the handover did not authorise it** |

So the change is **additive in effect**: the exception becomes *available* to a caller that wants
it, and every existing caller is insulated by a catch that preserves today's `None`. The 803-test
baseline is the detector, and the six-frozen-methods introspection test must keep passing.

> **Handling note:** `src/reddit_client.py` is edited with `Edit` only. Never round-trip it through
> `Get-Content`/`Set-Content` — that adds a BOM and mojibakes the UTF-8, and this file is
> lint-exempt so the formatter will not catch it.

### 6.7 Configuration — additive, all defaulted

```yaml
discovery:
  rss_enabled: true          # P5, unchanged — rollback level 1
  rss_limit: 100             # P5, unchanged
  rss_host: "https://old.reddit.com"   # P5, unchanged
  min_interval: 15m          # 28 §8.1 defaults
  max_interval: 24h
  window_target: 60
  empty_backoff: 0.5
  empty_cap: 6
  yield_boost: 1.0
  # density_threshold: DELIBERATELY ABSENT — see §2.3.2
```

Absent keys reproduce these defaults, and that is tested — P4's `network:` discipline.

---

## 7. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **R-1** | **Write lock held across I/O** in the new handler → HTTP 500 under worker+web | **High** | Repeats P3's lost sign-off | B1. Fetch outside the session; a concurrency test asserts the web tier stays responsive during a discovery job |
| **R-2** | **Making `_get` raise breaks a shipped caller** that relies on `None` | **High** | Regression in the legacy scrape path | Enumerate every `_get` caller before changing it; the 803-test baseline is the detector; legacy contract re-asserted |
| **R-3** | **Overflow check inverted** — compares the wrong end of the feed and never fires | Medium | R19 violated silently | Mutation M2; the fixture is 150 posts, well past the 100 ceiling |
| **R-4** | `next_interval` divides by a zero or negative rate | Medium | Crash or absurd interval | [28 §8.1](28-discovery-redesign.md)'s `rate <= 0 → max_interval` guard; property test over the clamp |
| **R-5** | **Idempotency violated** — a re-run duplicates `prescores` | Medium | R9 violated | B8; lease-expiry re-run test |
| **R-6** | A test makes a **live request** | Medium | Gate rule violated | Every P6 test uses `responses` or fixtures. Live checks live only in the manual guide and `validate_feed_parity.py` |
| **R-7** | `reset_policy()` omitted in an egress-touching test | Low | Unrelated later failure | [handover T4](PHASE-05-HANDOVER.md) |
| **R-8** | **`0005` corrupts the live database** (K14) | Low | Critical | M7 backup; up/down/up on a **copy**; `check_schema.py` extended. **C1 — R20's migration half was never verified in CI — matters most here, and P6 closes it** |
| **R-9** | A mutation is designed but **not run**, or silently **skips** | Medium | A guard that cannot fail | [handover T2](PHASE-05-HANDOVER.md) — two of P5's eleven. Every mutation is executed and its *detection* recorded, and skip counts are read, not just totals |
| **R-10** | A fixture is authored from documentation rather than a capture | Medium | Tests our beliefs | [handover T3](PHASE-05-HANDOVER.md) — F2/F5. Feed fixtures descend from P5's captures |

---

## 8. Assumptions

| # | Assumption | Basis | If false |
|---|---|---|---|
| **A-1** | The feed's entries are **newest-first**, so "oldest entry" is the last one | P0/P5 captures; `sort=new` | The overflow check compares the wrong end (R-3). Asserted in the fixture, not assumed in the code |
| **A-2** | `t3_` fullnames are **not** monotonically ordered, so the watermark must diff on **id set + timestamp**, never on id comparison | Reddit ids are base-36 but not a reliable ordering across shards | An id-comparison watermark would be subtly wrong. P6 diffs on the id set and uses `last_seen_utc` only for overflow |
| **A-3** | ~3% of posts are link/media with no selftext | P5 measured 97/100 and 100/100 on two subreddits | Only the `body_source='absent'` count changes; no logic depends on the ratio |
| **A-4** | A fixture-based cold-start comparison (A4) is a fair proxy for the live ≥95% claim | The two sources are the same subreddit's same window | ⚠️ **The word "verified" is not written without a live capture.** If live is blocked, A4 is recorded as *measured against fixtures, live half not captured*, following P5's own precedent |
| **A-5** | The operator's machine can reach `old.reddit.com` for the live manual steps | U6; re-confirmed this session (parity script, exit 0) | Those guide steps are marked **optional** and every automated criterion still holds |

---

## 9. Rollback

| Level | Mechanism | Verified by |
|---|---|---|
| **1 — config** | `discovery.rss_enabled: false` → HTML listing walk, exactly as before (T6) | A7 + manual guide, **including the restore** |
| **2 — absent config** | Delete the new `discovery:` keys → defaults apply | Automated test |
| **3 — DB** | `alembic downgrade 0004` → `0005`'s two tables dropped, no data loss (nothing else references them yet) | **Executed**, up/down/up on a copy (M6, M9) |
| **4 — git** | `git revert` the P6 commits | Manual guide |

[lock §4](EXECUTION_MODE_LOCK.md): rollback is **executed and verified**, never merely documented.

---

## 10. Testing strategy

### 10.1 The gate — [35 §2](35-testing-strategy.md)

Full suite · `-W error::DeprecationWarning` · `ruff` ×2 · four grep fences · coverage ≥70% on new
modules · legacy contract · **`alembic` up/down/up on a copy** · `check_schema.py` extended for
`0005` · CI. **Known gap, unchanged:** `mypy` not installed (blocker B3/O2).

### 10.2 Mutation discipline — every **bold** criterion

| # | Mutation | Must be caught by |
|---|---|---|
| **M1** | The idle poll creates a row anyway | A1 |
| **M2** | Overflow check returns `False` always | A2 (150-post fixture) |
| **M2a** | The overflow **null-guard is dropped** (`watermark`/`last_seen_utc`/empty-feed checks removed) | A2's cold-start and empty-feed fixtures — **M2 alone cannot catch this**, §6.1 |
| **M3** | `policy.py` gains an `src.ai` import | A5 boundary test |
| **M4** | `rss_enabled: false` no longer routes to HTML | A7 |
| **M5** | `allow_cache=True` on the discovery path | A6 statement counter |
| **M6** | Watermark advances even when the diff is empty | A1 + idempotency |
| **M7** | `next_interval` skips the clamp | Property test |
| **M8** | `prescores` written only for admitted items | R11/§2.5 — the audit becomes impossible |
| **M9** | `_get` swallows the exception again | The N2 mapping test |
| **M10** | Handler emits its `run_events` row **before** the fetch | B1 concurrency test |

Every mutation is **run**, and its detection recorded, before its guard is believed (R-9).

### 10.3 Boundary and regression

Four fences · B2 (discovery imports no `src.ai`) · B5 (six frozen methods) · B6 (raise vs `[]`) ·
B8 (idempotent re-run) · 459 leads · `intent_score` fingerprint · `GET /` · 13 CSV columns · 17
endpoints.

### 10.4 Manual testing strategy

`docs/testing/P06-testing.md`, non-developer executable, **every command PowerShell** (memory:
bash escaping silently no-ops, so a broken command reads as a passing test). Following P5's **F5** —
*a `-k` filter that matches nothing exits successfully* — **every filtered test step asserts the
collected count**, not the colour. Live steps marked optional; offline steps use `--file`.

---

## 11. Implementation order

Small commits, each independently green.

| # | Step | Commit |
|---|---|---|
| 1 | `0005_discovery` — `discovery_watermarks` + `prescores` (§2.4); up/down/up on a copy; `check_schema.py` extended | `feat(P6): 0005 discovery migration` |
| 2 | `watermarks.py` — diff + advance + **overflow** (pure, no DB) | `feat(P6): watermark diff and overflow detection` |
| 3 | `policy.py` — `next_interval` (pure, zero AI) | `feat(P6): deterministic polling policy` |
| 4 | `repositories/discovery.py` — watermark + due-queue + prescores | `feat(P6): discovery repository` |
| 5 | `_get` raises; handlers map (N2/T1) — **the risky one, isolated** | `fix(P6): transport raises instead of returning None` |
| 6 | `handlers/discover.py` — stages 1–3, B1 discipline | `feat(P6): discovery handler` |
| 7 | Stage 5 keyword search via RSS (Task 6) | `feat(P6): keyword search channel` |
| 8 | Stage 4 body accounting + `rss_enabled: false` fallback (§2.3.2) | `feat(P6): body source accounting` |
| 9 | Documentation — the three §2.3.3 reconciliations, §2.4, §2.5 | `docs(P6): apply the P5 amendment to doc 28` |

---

## 12. What P6 deliberately does NOT do

| Not done | Owner | Why |
|---|---|---|
| **The density-adaptive body fetch heuristic** | **Nobody — deleted** | §2.3. Its inputs do not exist |
| `discovery.density_threshold` config key | **Nobody** | §2.3.2 — a key nothing reads is a fiction |
| D7's 30/20 hysteresis | **Nobody** | Void with the heuristic |
| `score` / `num_comments` back-fill | **P11** | §2.5 |
| Comment expansion (stage 6) | **P11** | §2.5 — needs `comments` (`0006`) |
| The 2% stage-3 holdout **audit** | **P11 / P19** | §2.5 — needs `gate_audits` (`0009`). P6 persists the rows that make it possible |
| Selftext for link/media posts | **Nobody** | It does not exist on any endpoint |
| Conditional GET | **Nobody** | Deleted 2026-08-05 |
| `_extract_search_post` host normalisation (DI14) | Deferred | Shipped-behaviour change |
| An eleventh migration | — | [freeze §4.1](ARCHITECTURE_FREEZE.md) |

---

## 13. Entry conditions — [PHASE-05-HANDOVER §9](PHASE-05-HANDOVER.md)

| Condition | State |
|---|---|
| **§4 of the P5 handover read in full** | ✅ §2.3 — and redesigned |
| [34 §P6](34-implementation-plan.md) read, all thirteen fields | ✅ §1, §4 |
| [28 §3](28-discovery-redesign.md), §8, §10 read | ✅ §1, §2 |
| [SPRINT-0 §2](SPRINT-0-MEASUREMENTS.md) re-read — U1, U3, U5 | ✅ §3.1 |
| `scripts/validate_feed_parity.py` run once | ✅ **exit 0**, §3.2 |
| Full suite green before the first change | ✅ **803 / 2** |
| `git status` clean · `alembic heads` = one `0004` · `check_schema.py` 25/25 | ✅ §3.2 |
| `gh run list`: P5 green on `origin/main` | ✅ operator-confirmed |
| `phase-manager` skill loaded before the first `src/` edit | ⏳ At implementation start |
| P00–P05 manual sign-off tables signed | ❌ **Blocker D1**, unchanged |

**Blockers carried:** D1 (unsigned tables) · C1 (R20's migration half unverified in CI — **P6
closes it**) · B3/O2 (`mypy`) · B1 (`.env` keys, gates P23) · N1 (P17's scope) · N2 (**closes
here**, §6.6).

---

## 13a. What implementation changed about this review — added 2026-08-08

Three of this review's statements did not survive contact with the code. Recorded here rather than
edited away, because the *pattern* is the phase's most useful result: **a specification is a
hypothesis until something executes it.**

| # | What this review assumed | What implementation found |
|---|---|---|
| **§2.5** | P6 would persist a `prescores` row per triaged item, admitted or rejected, and P11 would audit them | **It cannot.** The CHECK requires every prescore to name a stored `Lead`; a triage rejection is never stored. **Found by mutation testing** — M1 and M8 survived because the branch was unreachable, while coverage still reported 87% on the file. P6 counts rejection reasons on `run_events` instead; operator-approved. [freeze §11.1](ARCHITECTURE_FREEZE.md) |
| **§2.4 / §6.1** | `ux_watermarks (subreddit, channel, query)` as [28 §3.1](28-discovery-redesign.md) specifies | **That index constrains nothing for listing rows** — SQLite treats NULLs as distinct, and `query` is NULL for every one. Shipped as two **partial** unique indexes. Demonstrated, not reasoned about |
| **§6.2** | `default_rate` was a detail | **It erased a distinction the code makes.** 1.0 clamps an unmeasured channel to `max_interval`, where a measured-dead one lives. Set to 60.0, with the reasoning in the docstring |

**And one defect in this review's own testing plan.** The first cold-start test compared a synthetic
id set with itself and asserted 100% coverage — a test that could not fail, which is P5's **F3** for
the third time in this project. Deleted rather than adjusted; **A4 is now recorded as not verified**
(§4.1, and the completion report §10).

### Mutation results — 16 designed, 16 detected

M1, M2, **M2a**, M3, M4, M5, M6, M7, M8, **M8a**, M9, M10, M11. M2a and M8a were added during
implementation: M2 alone cannot catch a dropped null-guard, because that guard's failure direction is
*over*-reporting. The harness asserts each mutation actually changed the file and that pytest
actually collected tests — P5's **F4**.

---

## 14. Recommendation

**Proceed**, subject to the §2.3 redesign being accepted.

That decision is the one thing in this review that a reader could reasonably disagree with, so it is
stated as plainly as possible: **P6 deletes a specified component rather than building it**, on the
authority of a measurement that is already a frozen amendment and that this review re-confirmed
live. The alternative — building a threshold whose only branch is unreachable and whose only
possible future consumer is P11 — would ship a documented capability that does nothing, which is the
failure mode [handover F1 and F3](PHASE-05-HANDOVER.md) both name.

Risk remains **High**, as [34 §P6](34-implementation-plan.md) rates it: the first migration since
`0004`, the first discovery handler, the first discovery write, and a change to shipped transport
behaviour (§6.6). The implementation order in §11 isolates each.
