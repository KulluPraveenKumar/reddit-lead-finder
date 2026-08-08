# P5 IMPLEMENTATION REVIEW — RSS client & Atom parser

**Written:** 2026-08-08, **before** any production code.
**Governs:** [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) (constraints) ·
[EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md) (process).
**Companions:** [P5-DECISION-ANALYSIS.md](P5-DECISION-ANALYSIS.md) ·
[P5-IMPLEMENTATION-CHECKLIST.md](P5-IMPLEMENTATION-CHECKLIST.md) ·
[testing/P05-testing.md](testing/P05-testing.md).

> These four files are **execution records** of the same kind P4 produced
> ([P4-IMPLEMENTATION-REVIEW.md](P4-IMPLEMENTATION-REVIEW.md) et al.). They are not new
> architecture, roadmap, governance or testing-strategy documents, and therefore are not on
> [lock §2](EXECUTION_MODE_LOCK.md)'s prohibited list.

---

## 1. The authoritative specification for P5

| Rank | Document | What it settles for P5 | Status |
|---|---|---|---|
| **1** | [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) — R1–R20, AD-1…AD-31, **§11 amendment log** | The freeze is the constraint set. **§11 already carries the U4 amendment**, which deletes conditional GET. R5 (network layer is target-agnostic), R18 (RSS is always direct), AD-2 (RedditClient API frozen, `get_feed` explicitly additive) | Authoritative |
| **2** | [SPRINT-0-MEASUREMENTS.md §2](SPRINT-0-MEASUREMENTS.md) | U1–U7, measured 2026-08-05. Feed shape, rate limit, header names and units, `limit=100`, host parity | Authoritative — measurement beats text |
| **3** | [34-implementation-plan.md §P5](34-implementation-plan.md) (lines 241–256) | Objective, Deliverables, Files, Config, Tasks, Acceptance, Metrics, Rollback, Docs | Authoritative **except** where it predates P0 — see §2 |
| **4** | [28-discovery-redesign.md](28-discovery-redesign.md) §2.1, §3 stage 1 & 5, §11 D3/D5, §12 | Feed URL shapes, multireddit mandate, the parity requirement between the Atom parser and `_extract_post`, cache bypass | Authoritative **except** §12's file table and D-AC2 — see §2 |
| **5** | [07-scraping-pipeline.md](07-scraping-pipeline.md) §1, §2, §4.1 | The hard requirements P5 inherits and the post dict shape RSS must reproduce. **P5 owns the new §2a** | Authoritative |
| **6** | [35-testing-strategy.md](35-testing-strategy.md) §2, §5, §6 | The gate, the manual-guide rules, and P5's additional test requirements | Authoritative **except** its "304 handling" cell — see §2 |
| **7** | [PHASE-04-HANDOVER.md](PHASE-04-HANDOVER.md) | G1–G7 (must not break), T0–T6 (traps), entry conditions | Authoritative for entry |

**Nothing else is a P5 specification.** In particular [15-phase-05.md](15-phase-05.md) and
[testing/phase-05-testing.md](testing/phase-05-testing.md) are **not** — see §2.1.

---

## 2. Document conflicts, numbering traps and stale notes

Six were found. One is a numbering trap, four are stale pre-P0 transcriptions of a single deleted
capability, one is an internal inconsistency in doc 28.

### 2.1 The numbering trap — restated because it has cost time twice

⚠️ **`docs/15-phase-05.md` and `docs/testing/phase-05-testing.md` are NOT this phase.**
They belong to the superseded eight-phase scheme completed 2026-07-30/31
([lock §2.1](EXECUTION_MODE_LOCK.md)). Legacy "Phase 05" is **Adaptive Budget / AI cost control**,
which in the frozen plan is **P19**. The two schemes are unrelated. P4 paid half a day to establish
the same fact for "Phase 04" ([handover §preamble](PHASE-04-HANDOVER.md)); this review pays it once
more so P6 does not.

Files that are historical records and must not be read as P5 spec, extended or renumbered:
`11-phase-01.md` … `18-phase-08.md`, `PHASE-01-STATUS.md`, `PHASE-02-STATUS.md`,
`docs/testing/phase-0N-testing.md` (lower case).

### 2.2 Conflict C1 — conditional GET: four documents describe a capability the freeze deleted

**This is the material finding of the review.** It removes three of P5's seven Tasks, one
Deliverable, one Files entry and one Acceptance criterion.

| Where | What it says | Verdict |
|---|---|---|
| [34 §P5](34-implementation-plan.md) Deliverables | "conditional-GET support" | **Stale.** Pre-P0 text |
| [34 §P5](34-implementation-plan.md) Files | `src/net/http_client.py ~ (if_none_match, if_modified_since, 304 handling)` | **Stale** |
| [34 §P5](34-implementation-plan.md) Tasks 4 & 5 | "304 handled as success-with-no-body"; "Capture and persist `ETag`/`Last-Modified`" | **Stale** |
| [34 §P5](34-implementation-plan.md) Acceptance | "a 304 is success and transfers no body" | **Stale** |
| [28 §12](28-discovery-redesign.md) file table | `http_client.py` gains `if_none_match` / `if_modified_since` | **Stale** |
| [28 D-AC2](28-discovery-redesign.md) | "**With U4 supported**, an unchanged feed returns 304" | **Void by its own terms** — U4 was refuted |
| [35 §6](35-testing-strategy.md) P5 row | "304 handling" | **Stale** |

**Against:**

| Where | What it says |
|---|---|
| [ARCHITECTURE_FREEZE §11](ARCHITECTURE_FREEZE.md), 2026-08-05, **amendment** | "Reddit sends neither `ETag` nor `Last-Modified` on `.rss` … **Layer L1 is deleted** … `discovery_watermarks` drops `last_etag` and `last_modified`" |
| [SPRINT-0 §2.1 U4](SPRINT-0-MEASUREMENTS.md) | "**NO** ⛔ Neither `ETag` nor `Last-Modified` sent" — measured on 4 feeds, 2 hosts |
| [28 §5.1 line 298](28-discovery-redesign.md) | "~~L1 Conditional GET~~ — **DELETED — U4 refuted in P0**" |
| [28 §9 line 362](28-discovery-redesign.md) | "Conditional fetching — ⛔ **Rejected — U4 refuted in P0**" |
| [28 §10 line 185](28-discovery-redesign.md) | "`last_etag` / `last_modified` REMOVED" |
| [P4-IMPLEMENTATION-CHECKLIST.md](P4-IMPLEMENTATION-CHECKLIST.md) line 363 | Already flagged: excluded from P4, "P0's U4 measurement refuted conditional GET on `.rss` anyway" |

**Resolution — [freeze §11.1](ARCHITECTURE_FREEZE.md) documentation reconciliation, not a new
amendment.** The amendment path for U4 was consumed on 2026-08-05 by P0. What remains is four
documents transcribing text the amendment already superseded. Filing a second amendment would
misrepresent a settled measurement as an open decision. Full argument, alternatives and the
authority chain: [P5-DECISION-ANALYSIS.md §D1](P5-DECISION-ANALYSIS.md).

**Consequence — stated loudly, because [lock §4.1](EXECUTION_MODE_LOCK.md) forbids silent
narrowing:** P5 ships **no** `if_none_match`, **no** `if_modified_since`, **no** 304 branch and
**no** `ETag`/`Last-Modified` capture. `src/net/http_client.py` is touched **only** for
`x-ratelimit-reset` (Task 6), which is a generic HTTP header and does not offend R5. The capability
goes to [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) with a re-measurement trigger.

### 2.3 Conflict C2 — doc 28 disagrees with itself about the feed and `http_cache`

| Where | What it says |
|---|---|
| [28 §7.2](28-discovery-redesign.md) line 394 | "`http_cache` (15 min, 60 min for search) — Serves the feed; **zero network**" |
| [28 §11 D5](28-discovery-redesign.md) line 534 | "**Discovery requests bypass `http_cache` entirely.** The watermark *is* the cache" |

**Resolution: D5 wins.** It is a risk-register mitigation with a downstream acceptance criterion
behind it — [34 §P6](34-implementation-plan.md) requires "discovery bypasses `http_cache`
(statement counter)". §7.2 is a narrative cost scenario, and its "0 requests" line is the same
class of claim the U4 amendment already corrected elsewhere. Recorded as a reconciliation;
`get_feed` passes `allow_cache=False`. Rationale: [P5-DECISION-ANALYSIS.md §D2](P5-DECISION-ANALYSIS.md).

### 2.4 Conflict C3 — `04 §5`'s `_get` signature does not match the shipped code

[04 §5](04-system-design.md) shows `_get(self, url, *, session_key=None)` raising
`ProxyExhaustedError`. The shipped `src/reddit_client.py:87` is
`_get(self, url, *, expect_selector=None)` and **swallows** `ProxyExhaustedError`, returning `None`.

**Not P5's to resolve.** [PHASE-04-HANDOVER §3 and T1](PHASE-04-HANDOVER.md) assign transport-raising
to **P5 or P6**; this review takes the explicit decision that it is **P6's**, with reasons in
[P5-DECISION-ANALYSIS.md §D5](P5-DECISION-ANALYSIS.md). P5 keeps the `None` contract and is
additive only, per AD-2 and the P5 Files row. Stated here so it is not silent narrowing.

### 2.5 Conflict C4 — the P5 Files row omits `main.py`

[35 §6](35-testing-strategy.md) requires the P5 manual guide to "**Fetch one feed by CLI**". No CLI
surface exists for feeds and the Files row does not list `main.py`. The Files row is documented as
"a guide, not a contract" ([34 §1.1](34-implementation-plan.md)), and the gate document is frozen,
so the gate wins: P5 adds one additive `feed` command. See
[P5-DECISION-ANALYSIS.md §D3](P5-DECISION-ANALYSIS.md).

### 2.6 Outdated implementation note — `04 §5`'s constructor

[04 §5](04-system-design.md) names `build_default_client(config)`; the shipped name is
`_default_client(config)`, and `__init__` takes `http_client=`, not `http=`. Cosmetic, pre-existing,
**not corrected by P5** — editing it would touch a frozen document for no behavioural reason. Noted
so the next reader does not treat the document as the API.

### 2.7 What was checked and found clean

- `docs/05-database-plan.md` contains **no** `last_etag` / `last_modified` columns — the U4 amendment
  already landed there. P6's `discovery_watermarks` inherits a correct table.
- No P5 file collides with a P6/P7 file. `src/discovery/` is new; P6 adds siblings.
- No second `discovery:` block exists in `config.yaml` (top-level keys: `subreddits`, `keywords`,
  `scoring`, `schedule`, `dashboard`, `ai`, `pricing`, `logging`, `worker`, `orchestration`,
  `network`, `proxy`). P5's key is genuinely new.

---

## 3. Dependency verification, P0 → P4

### 3.1 Phase dependencies

[34 §P5](34-implementation-plan.md) **Depends on: P4, P0 (U1–U6).**

| Dependency | Required for P5 | Verified |
|---|---|---|
| **P0 U1** — RSS limit is **per IP**, ~60 s recovery | Pacing is a real constraint; multireddit is mandatory | ✅ [SPRINT-0 §2.1/2.2](SPRINT-0-MEASUREMENTS.md) |
| **P0 U2** — `<content>` carries full selftext (median 1,089 chars) | The parser must extract a body, not just metadata | ✅ |
| **P0 U3** — boolean `subreddit:A OR subreddit:B` works | Decides the search-feed URL shape | ✅ |
| **P0 U4** — **no** conditional GET | Deletes Tasks 4 & 5 — §2.2 | ✅ (refuted) |
| **P0 U5** — `?limit=100` honoured (100 entries) | An acceptance criterion | ✅ |
| **P0 U6** — `old.reddit.com` serves RSS | Fixes `discovery.rss_host`'s default under [07 §1](07-scraping-pipeline.md) | ✅ |
| **P0 rate-limit headers** — `x-ratelimit-reset: 17–48` on success; 429 with zero bytes | Task 6's units. **17–48 is seconds-remaining, not epoch** | ✅ [SPRINT-0 §2.2](SPRINT-0-MEASUREMENTS.md) |
| **P4** — `RequestClass.RSS` routed direct, unconditionally | `get_feed` needs only to pass `request_class="rss"` | ✅ `src/net/policy.py:74` `ALWAYS_DIRECT` |
| **P4** — `ProxiedHTTPClient.get(request_class=, session_key=)` | The transport seam `get_feed` calls | ✅ `src/net/http_client.py:107` |
| **P4** — one policy per process (`src/net/egress.get_policy`) | `get_feed` must reuse `self.http`, never build one | ✅ |
| **P1–P3** — run/job schema, worker, run pages | Not used by P5. `get_feed` is additive and has no handler until P6 | n/a |

### 3.2 Repository health at entry — measured 2026-08-08, this session

| Check | Result |
|---|---|
| `git status --short` | ⚠️ **Was not clean** — see §3.3. Clean after restore |
| Full suite | **695 passed, 2 skipped** in 171.7 s — matches [PHASE-04-HANDOVER §6](PHASE-04-HANDOVER.md) exactly |
| `ruff check .` | All checks passed! |
| `ruff format --check .` | 101 files already formatted |
| `alembic heads` | `0004_orchestration (head)` — one head |
| `python scripts/check_schema.py` | **OK — all 25 checks passed** |
| `gh run list` | P4 green on `origin/main` (run 31249734916) |

### 3.3 ⚠️ Finding at entry — an un-executed P4 rollback

The working tree was **not** clean. `config.yaml` carried `ladder: [dc]` — the mutation
[testing/P04-testing.md](testing/P04-testing.md) T10 Step 397 instructs a tester to apply and line
422 instructs them to reverse. The committed value is `ladder: [direct, dc]`.

This matters for three reasons, not one:

1. [lock §4](EXECUTION_MODE_LOCK.md) requires rollback **executed and verified**, not documented.
   A guide step that says "restore" and was not run is exactly P4's **F1** defect — *a documented
   check that was never executed is worse than an absent one, because it is counted as coverage.*
2. `ladder: [dc]` is the precise configuration that produced P4's **F2** — the R18 hole reachable
   only by omitting `direct` from the ladder. A baseline recorded under it is not the baseline
   [PHASE-04-HANDOVER §8](PHASE-04-HANDOVER.md) means.
3. P5's own guide mutates `config.yaml`. Starting from a dirty tree would make P5's rollback
   unverifiable.

**Action taken:** `git restore config.yaml`, **then** the §3.2 baseline was recorded. The tree is
clean. No P4 conclusion is affected — P4's suite results were recorded from a clean tree and
reproduce exactly (695/2).

---

## 4. Acceptance criteria

### 4.1 P5-specific — [34 §P5](34-implementation-plan.md), as reconciled

| # | Criterion | Bold? | How it is proved |
|---|---|---|---|
| **A1** | RSS and HTML produce **identical post dicts** for the same `reddit_id`, except `score` and `num_comments` | **Yes** | A matched fixture pair (one HTML listing, one Atom feed, same three anonymised posts); `assert rss == {**html, "score": None, "num_comments": None}` |
| **A2** | `limit=100` returns up to 100 entries | No | A 100-entry Atom fixture; `len(...) == 100`; a `limit=10` call over it returns 10 |
| ~~A3~~ | ~~A 304 is success and transfers no body~~ | — | **STRUCK — §2.2.** U4 refuted; there is no 304 |
| **A4** | A malformed feed raises `ParseError`, **never a silent empty list** | **Yes** | `pytest.raises(FeedParseError)` on a truncated-XML fixture; and mutation M3 |
| **A5** | **No new runtime dependency** | **Yes** | `lxml>=5.0.0` is already a direct pin (`requirements.txt:3`); a test asserts `src/discovery/` imports nothing outside the shipped set |
| **A6** | Fixtures assert **field-by-field** | No | Each `*.xml` has a sibling `*.expected.json`; the test compares dicts key by key, not by count |

### 4.2 Metrics — [34 §P5](34-implementation-plan.md)

| Metric | Target | Measurement |
|---|---|---|
| Parse throughput | **100 entries < 50 ms** | `time.perf_counter()` around `parse_feed` on the 100-entry fixture, asserted with headroom |
| Fixtures | **4**, each with `.expected.json` | listing · search · empty · malformed (malformed has no `.expected.json`; it has an expected *exception* — stated, not silently skipped) |
| Dependencies | **`pip list` diff = 0** | Recorded before and after in the manual guide |

### 4.3 Universal — [34 §1.2](34-implementation-plan.md), every phase

`ruff check` + `ruff format --check` · `pytest` green with **no live network** · coverage ≥70% on
new modules · **all four grep fences** · `alembic upgrade head → downgrade -1 → upgrade head` on a
**copy** of the live DB · legacy contract (459 leads, `intent_score` fingerprint, `GET /`, 13 CSV
columns, 17 endpoints) · manual guide generated **and executed** · documentation landed.

---

## 5. Mandatory boundaries

Seven, six inherited from P4 plus one new.

| # | Boundary | Source | How P5 holds it |
|---|---|---|---|
| **B1** | **`src/net/` contains zero Reddit identifiers** (R5, fence 4) | [handover G1](PHASE-04-HANDOVER.md) | Atom parsing lives in `src/discovery/feed_parser.py`; URL construction in `src/reddit_client.py`. The only `http_client.py` edit is `x-ratelimit-reset`, a generic header |
| **B2** | Nothing in `src/net/` holds a DB session | [handover G2](PHASE-04-HANDOVER.md) | P5 adds no session anywhere; `get_feed` returns dicts |
| **B3** | **Never hold the SQLite write lock across I/O** | [handover T0](PHASE-04-HANDOVER.md) — cost P3 a sign-off | P5 adds **no** handler and **no** DB write. Restated because P6 will, and this is where it bites |
| **B4** | One policy per process | [handover G4](PHASE-04-HANDOVER.md) | `get_feed` uses `self.http`. It must not call `get_policy`, `build_policy_from_config` or construct a client |
| **B5** | R18: `rss` is direct in **code**, not configuration | [handover G5](PHASE-04-HANDOVER.md) · `policy.py:74` | `get_feed` passes `request_class=RequestClass.RSS.value`. It does not read `network.direct.classes` |
| **B6** | `build_scraper()` keeps its name and one-argument shape | [handover G7](PHASE-04-HANDOVER.md) | Untouched |
| **B7** | **`RedditClient`'s six public methods are frozen** (AD-2) | [freeze AD-2](ARCHITECTURE_FREEZE.md) | `get_feed` is a **seventh**, additive. `get_new_posts`, `get_hot_posts`, `search_posts`, `get_post_comments`, `get_user_posts`, `get_subreddit_info` keep signature and return shape; [P04-testing T12 Step 6](testing/P04-testing.md) asserts this by introspection and must keep passing |

Plus two P5 adds:

| # | Boundary | Why |
|---|---|---|
| **B8** | **`src/discovery/` imports no `src.ai`** | [34 §P6](34-implementation-plan.md) makes this an acceptance criterion for `discovery/policy.py`. Establishing it in P5, when the package has one file, is free; retrofitting it later is not |
| **B9** | **The XML parser resolves no entities and opens no network** | Untrusted network input into `lxml`, plus a deliberately malformed fixture. `etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)`. Not a new capability — the correct way to call an already-shipped dependency |

---

## 6. Interfaces

### 6.1 New — `RedditClient.get_feed()`

```python
def get_feed(
    self,
    subreddits: list[str],
    *,
    sort: str = "new",
    limit: int = 100,
    query: str | None = None,
) -> list[dict]:
    """Fetch one Atom feed and return posts in `_extract_post`'s shape."""
```

- **One network request**, never paginated. RSS has no `next` link and U1 makes a second request
  cost 60 s of wall clock.
- `request_class="rss"` → always direct (R18). `allow_cache=False` → D5.
- Raises `FeedParseError` on malformed XML (A4). Returns `[]` on an empty-but-valid feed.
- Transport failure keeps the pre-P5 contract: `_get`-style `None` handling → `[]`. **P6 changes
  this** (§2.4).

### 6.2 New — `src/discovery/feed_parser.py`

```python
class FeedParseError(ValueError): ...

def parse_feed(xml: str | bytes) -> list[dict]:
    """Atom 1.0 -> the dict shape `RedditClient._extract_post` returns."""
```

Reddit-aware, transport-unaware: it takes bytes and returns dicts, holds no client, no session and
no config.

### 6.3 Changed — `src/net/http_client.py`

`_retry_after(response)` additionally reads **`x-ratelimit-reset`**, in **seconds remaining**
(P0-measured 17–48), when `Retry-After` is absent. Clamped. Header name only; no target knowledge.

### 6.4 Changed — `main.py`

One additive command:

```
python main.py feed --subreddits a,b,c [--limit N] [--sort new|hot|top|rising]
                    [--query "..."] [--file PATH] [--config PATH]
```

`--file` parses a local Atom file and makes **no** network call — this is what lets the manual guide
be deterministic and offline. `--config` is scoped to this command only.

### 6.5 Configuration — additive, all defaulted

```yaml
discovery:
  rss_enabled: true                        # rollback switch (34 §P5 Rollback)
  rss_limit: 100                           # U5: honoured, 100 entries
  rss_host: "https://old.reddit.com"       # U6: works; 07 §1 requires old.reddit.com
```

Absent `discovery:` reproduces these defaults — the same fallback discipline as P4's `network:`
block ([handover T3](PHASE-04-HANDOVER.md)), and tested.

---

## 7. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **R-1** | **Atom `<content>` is escaped HTML with a "submitted by" footer**; naive text extraction makes bodies differ from the HTML path and A1 fails | **High** | A1 fails late | Parse the unescaped content with `BeautifulSoup(..., "lxml")` and select `div.md` — the *same* selector the HTML path uses on `div.expando .md`. Then `get_text(strip=True)[:5000]`, the same truncation. Proved by the matched fixture pair |
| **R-2** | `<author><name>` carries a **`/u/` prefix**; HTML's `data-author` does not | **High** | A1 fails | Strip the prefix; assert it in `.expected.json` |
| **R-3** | `<link href>` uses the **requested host**; `_extract_post` emits `https://www.reddit.com/...` | **High** | A1 fails | Normalise to `DISPLAY_URL`. Test with an `old.reddit.com` fixture |
| **R-4** | `subreddit` is not a first-class Atom field | Medium | A1 fails on multireddit | `<category term=>` first, link-path regex as fallback — the regex is the form P0's probe validated (`probe_rss.py:96`). Fixture is a **multireddit** feed with mixed subreddits |
| **R-5** | `<published>` may be absent; `<updated>` is an *edit* time, not a creation time | Medium | `created_utc` silently wrong | `published` when present, else `updated`; naive-UTC, `tzinfo` stripped, matching `_extract_post`. **The fixture states which element it carries** rather than the parser assuming |
| **R-6** | `x-ratelimit-reset` misread as epoch → a 55-year sleep | Low | Hang | P0 measured **17–48 = seconds remaining**. Implemented as a delta and **clamped** to a sane ceiling; a test asserts the clamp |
| **R-7** | Adding a `304` branch out of habit, or `if_none_match` "while we're here" | Medium | Freeze §12 violation | §2.2; a boundary test asserts `if_none_match`/`if_modified_since` appear nowhere in `src/` |
| **R-8** | Fixtures derived from live captures leak real usernames / permalinks into a **public** repo | Medium | [lock §5.1 H2](EXECUTION_MODE_LOCK.md) | Fixtures are **authored anonymised**: `example_user_1`, `t3_aaaa01`, `example.invalid` where a host is not load-bearing. A test greps the fixtures for `/u/` names outside the allowed set |
| **R-9** | A test accidentally makes a live request | Low | Gate rule violated | No fixture test constructs a client; the CLI's network path is exercised **only** in the manual guide |
| **R-10** | Leaving the process-wide policy degraded between tests | Low | Unrelated later failure | [handover T4](PHASE-04-HANDOVER.md): `reset_policy()` in any test touching egress |

---

## 8. Assumptions

Stated because each is a place P5 could be wrong, and each is falsifiable by a fixture or a manual
step rather than by argument.

| # | Assumption | Basis | If false |
|---|---|---|---|
| **A-1** | Reddit's Atom `<id>` is the bare fullname `t3_xxxxx`, matching `data-fullname` | `probe_rss.py` parsed entries by `{Atom}` names; the ids feed `_extract_post`'s `id` field | Extract the fullname from the URI. The parser has one place to change and a fixture that says so |
| **A-2** | `x-ratelimit-reset` is **seconds remaining** | [SPRINT-0 §2.2](SPRINT-0-MEASUREMENTS.md): "17–48" — an epoch value would be ~1.8 × 10⁹ | The clamp keeps the sleep sane in either reading |
| **A-3** | Selftext lives in a `div.md` inside `<content>` | `probe_rss.py:103` records the "submitted by" footer wrapping; the HTML path uses the same `.md` class | Body extraction falls back to full-text minus the footer. Detected by A1, not by inspection |
| **A-4** | An empty feed is a **valid** Atom document with zero `<entry>` elements | Atom 1.0 requires no entries | Only the empty-feed fixture changes |
| **A-5** | The operator's machine can reach `old.reddit.com` for the one live manual step | U6 measured 200 | The guide marks that step **optional** and every automated criterion still holds |

**A-1 and A-3 cannot be verified against a fixture this project authors** — that would restate the
assumption, not test it, and `probe_rss.py` checked neither `<published>` nor the `<id>` format. So
[checklist stage 1.1](P5-IMPLEMENTATION-CHECKLIST.md) takes **one live capture** and derives the
fixtures from it; if the capture is not possible, both are recorded in the completion report as
**assumptions carried, not verified**, with their falsification path named. The word "verified" is
not written without the capture — [handover F1](PHASE-04-HANDOVER.md) applied in the direction that
is invisible from inside.

---

## 9. Rollback requirements

| Level | Mechanism | Verified by |
|---|---|---|
| **1 — config** | `discovery.rss_enabled: false` → `get_feed` refuses and the HTML path is untouched | Automated test + manual guide **T8**, including the restore |
| **2 — absent config** | Delete the whole `discovery:` block → defaults apply, nothing raises | Automated test |
| **3 — code** | `get_feed` is **additive**; no caller exists until P6. Deleting `src/discovery/` and the `get_feed` method returns the tree to P4 behaviour exactly | Manual guide **T9** — the six frozen methods asserted present and unchanged |
| **4 — git** | `git revert` the P5 commits, or check out tag `v0.1.0-p4` | Manual guide **T9** |
| **DB** | **None.** P5 has no migration; `alembic heads` stays at one `0004` | `alembic heads` before and after |

[lock §4](EXECUTION_MODE_LOCK.md): rollback is **executed and verified**, never merely documented —
the rule §3.3 above found broken.

---

## 10. Testing requirements

### 10.1 The gate — [35 §2](35-testing-strategy.md)

Full suite · `-W error::DeprecationWarning` · `ruff` ×2 · four grep fences · coverage · legacy
contract · `alembic` up/down/up on a **copy** · `check_schema.py` · CI.
**Known gap, unchanged:** `mypy` (check 3) is not installed — blocker **B3/O2**, carried from P2.

### 10.2 P5 additions — [35 §6](35-testing-strategy.md), reconciled

| Requirement | Form |
|---|---|
| Atom fixtures **field-by-field** | 4 fixtures, `.expected.json` siblings, dict comparison |
| ~~304 handling~~ | **Struck — §2.2** |
| Malformed feed **raises** | `pytest.raises(FeedParseError)` |
| Manual focus: **fetch one feed by CLI**, compare entry count to the site | Guide T7 (live, marked optional) |

### 10.3 Mutation discipline — [lock §4](EXECUTION_MODE_LOCK.md), every **bold** criterion

[Handover T2](PHASE-04-HANDOVER.md): three of P4's seven mutations were undetected on the first
attempt. **Every mutation below is run before its guard is believed.**

| # | Mutation | Must be caught by |
|---|---|---|
| **M1** | Body extraction returns the whole `<content>` text instead of `div.md` | A1 parity test |
| **M2** | Drop the `/u/` strip from author | A1 parity test |
| **M3** | `parse_feed` returns `[]` instead of raising on malformed XML | A4 |
| **M4** | `limit` ignored — return every entry | A2 |
| **M5** | `request_class` dropped from `get_feed`'s transport call | A routing test asserting `rss` reaches `policy.acquire` |
| **M6** | `allow_cache=False` removed from `get_feed` | The cache-bypass test (D5) |
| **M7** | `x-ratelimit-reset` read as epoch instead of a delta | The clamp test |
| **M8** | `rss_enabled: false` no longer refuses | The rollback test |

### 10.4 Boundary and regression

Four fences · B7 introspection (six frozen methods) · B8 (`src/discovery/` imports no `src.ai`) ·
R-7 (`if_none_match` nowhere in `src/`) · R-8 (fixtures anonymised) · 459 leads · `intent_score`
fingerprint · `GET /` · 13 CSV columns · 17 endpoints.

---

## 11. What P5 deliberately does NOT do

| Not done | Owner | Why |
|---|---|---|
| Conditional GET, `ETag`/`Last-Modified`, 304 | **Nobody** — deleted | §2.2. Trigger recorded in [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) |
| `discovery_watermarks`, incremental diff, overflow detection | **P6** | [34 §P6](34-implementation-plan.md) |
| A discovery **handler**, `run_events` emission, any DB write | **P6** | Keeps B3 out of P5 entirely |
| `RedditClient._get` raising instead of returning `None` | **P6** | §2.4, [P5-DECISION-ANALYSIS §D5](P5-DECISION-ANALYSIS.md) |
| Sticky sessions on feeds | — | RSS is one request; `session_key` has no meaning here |
| Adaptive polling / `next_interval()` | **P6** | |
| Score / comment back-fill from HTML | **P11** | RSS carries neither; `None` is the honest value |
| `num_comments = 0` → `None` on the **HTML** path | Deferred | The same class of bug as the `score` fix, but it would perturb the legacy contract and is outside P5's scope. Recorded in [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) |
| Any migration | — | `alembic heads` stays one `0004` |

---

## 12. Entry conditions — [PHASE-04-HANDOVER §8](PHASE-04-HANDOVER.md)

| Condition | State |
|---|---|
| `docs/34` P5 read in full, all thirteen fields | ✅ §1, §4 |
| [07 §2a](07-scraping-pipeline.md) and [28](28-discovery-redesign.md) read | ✅ — §2a does not exist yet; **P5 creates it** |
| [SPRINT-0 §2](SPRINT-0-MEASUREMENTS.md) re-read: U1, U2, U4, U6 | ✅ §3.1 |
| `phase-manager` skill loaded before the first `src/` edit | ⏳ At implementation start |
| Full suite green **before** the first change | ✅ 695 / 2 |
| `gh run list`: P4 green on `origin/main` | ✅ |
| P00–P04 manual sign-off tables signed | ❌ **Blocker D1**, unchanged — the operator has declared P0–P4 signed off; the tables in the repository remain blank |

**Blockers carried:** D1 (unsigned tables) · C1 (R20's migration half unverified in CI) · B3/O2
(`mypy`) · B1 (`.env` keys, gates P23) · N1 (keyword/user leads uncollected) · N2 (`pause_run` vs
`fail_run`, closes in P6). **None blocks P5's implementation.**

---

## 12a. Live measurements taken during P5 — 2026-08-08

Added after implementation, at the operator's request. **Everything below is measured, not
inferred.** Three of these change frozen documents; two are recorded as
[freeze §11](ARCHITECTURE_FREEZE.md) amendments.

### 12a.1 The feed, captured live

`GET https://old.reddit.com/r/SaaS/new/.rss?limit=5` → **200, 7,815 bytes.**

| Property | Observed | Consequence |
|---|---|---|
| `<id>` | a bare fullname of the form `t3_<7 chars>`, not a URI | Matches `data-fullname`; **A-1 verified** |
| `<content type="html">` | `<!-- SC_OFF --><div class="md">…</div><!-- SC_ON -->` + `submitted by … [link] [comments]` | The selftext is the `div.md`; the footer is not body text. **A-3 verified** |
| Entry children | `author, category, content, id, link, updated, published, title` | `<published>` is present; `<updated>` is the fallback |
| `<author><name>` | `/u/…` | The prefix is real; must be stripped |
| `<category>` | `term="SaaS" label="r/SaaS"` | Per-entry subreddit, which is what makes multireddit work |
| `<link href>` | `https://old.reddit.com/r/…` | Host normalisation required |
| Headers | `x-ratelimit-used: 1`, `x-ratelimit-remaining: 0.0`, **`x-ratelimit-reset: 32`**, `Cache-Control: private, max-age=3600`. **No `ETag`. No `Last-Modified`** | **32 is seconds-remaining** — inside P0's 17–48 band, so **A-2 verified**. And **U4 independently reconfirmed three days after P0**: [decision D1](P5-DECISION-ANALYSIS.md) rests on a repeatable measurement, not a one-off |

### 12a.2 Where the body actually lives — the finding that changed the architecture

| Source | Bodies found | Selector |
|---|---|---|
| **HTML listing**, live `/r/startups/new/` | **0 of 25** | `div.expando .md` — 25 expandos, every one `<span class="error">loading...</span>` |
| **HTML listing**, shipped P0 capture `listing_page1.html` | **0 of 25** | same |
| **HTML search**, shipped capture `search_page1.html` | **22 of 22** | `div.search-result-body .md` — rendered inline |
| **Feed**, live r/SaaS | **97 of 100** | `div.md` inside `<content>` |
| **Feed**, live r/startups | **100 of 100** | same |

▶ **The HTML listing page carries no selftext. It never has.** Old Reddit fetches the body over
AJAX when a reader clicks. The feed is the only bulk source of selftext; HTML **search** still
carries bodies inline and is unaffected.

**Why this affects P6.** [34 §P6](34-implementation-plan.md) task 5 specifies a density-adaptive body
fetch — *listing ≥25%, permalink <25%, hysteresis 30/20* — which chooses between two sources when
many posts need bodies. **One of those two sources has no bodies to give.** The listing branch would
spend a request and return nothing at any density. The real choice is *feed body vs permalink fetch*,
and the feed already covers ~97%, so the branch may not need to exist at all. **P6 owns that
redesign; P5 did not attempt it** — see [PHASE-05-HANDOVER.md §4](PHASE-05-HANDOVER.md).

### 12a.3 What `url` means on each endpoint

| Path | `url` is | Measured |
|---|---|---|
| HTML listing, self post | the permalink | agrees with the feed |
| HTML listing, **link/media post** | the **destination** (`v.redd.it`, `i.redd.it`, external) | **3 of 25** on r/SaaS |
| HTML search | the permalink, on `old.reddit.com` — the host is never normalised | 471 live rows split **444 / 27** |
| Feed | the permalink, always | normalised to `www.reddit.com` |

**The feed was not changed to match.** The permalink is the actionable URL for a lead, it is what the
search path already stores, and it is what 444 of 471 existing rows carry. Echoing the listing's
external URL would trade a useful value for a matching one — the failure mode the operator's
instruction 6 names. Recorded as a documented difference, asserted narrowly: the feed's permalink
must carry *this* post's id, so the exception cannot hide a wrong permalink.

### 12a.4 Amendments and reconciliations produced

| Kind | Subject |
|---|---|
| **Amendment** ([freeze §11](ARCHITECTURE_FREEZE.md)) | The HTML listing carries no selftext — refutes [28 §2.2](28-discovery-redesign.md), invalidates P6 task 5's premise |
| **Amendment** ([freeze §11](ARCHITECTURE_FREEZE.md)) | `url` semantics differ per endpoint; the feed keeps the permalink |
| **Reconciliation** ([freeze §11.1](ARCHITECTURE_FREEZE.md)) | Conditional GET struck from four documents |
| **Reconciliation** ([freeze §11.1](ARCHITECTURE_FREEZE.md)) | [28 §7.2](28-discovery-redesign.md) vs D5 — the feed bypasses `http_cache` |

---

## 13. Recommendation

**Proceed**, subject to the four decisions in [P5-DECISION-ANALYSIS.md](P5-DECISION-ANALYSIS.md)
being accepted — D1 in particular, which strikes three Tasks and one acceptance criterion from the
P5 row on the authority of a frozen measurement.

Risk remains **Low**, as [34 §2](34-implementation-plan.md) rates it: no migration, no DB write, no
handler, no new dependency, and every deliverable is additive behind a config switch.
