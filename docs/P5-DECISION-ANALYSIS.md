# P5 DECISION ANALYSIS

**Written:** 2026-08-08, before implementation.
**Companion to:** [P5-IMPLEMENTATION-REVIEW.md](P5-IMPLEMENTATION-REVIEW.md).

Five decisions must be taken before the first line of P5 is written. Each one is a place where the
frozen documents either disagree with each other or disagree with a P0 measurement. The house rule
applies throughout ([freeze §11](ARCHITECTURE_FREEZE.md)): **a measurement overrides text; an
argument does not.**

---

## D1 — Conditional GET: build it, or record that the freeze already deleted it?

### The question

[34 §P5](34-implementation-plan.md) lists conditional-GET support as a Deliverable, names
`if_none_match` / `if_modified_since` / 304 handling in its Files row, makes it Tasks 4 and 5, and
makes "a 304 is success and transfers no body" an Acceptance criterion. **P0 measured that Reddit
sends neither header on `.rss`.**

### The evidence

| For building it | For not building it |
|---|---|
| [34 §P5](34-implementation-plan.md) Deliverables / Files / Tasks 4–5 / Acceptance | [ARCHITECTURE_FREEZE §11](ARCHITECTURE_FREEZE.md) **amendment**, 2026-08-05: "Reddit sends neither `ETag` nor `Last-Modified` on `.rss` … **Layer L1 is deleted**" |
| [28 §12](28-discovery-redesign.md) file table | [SPRINT-0 §2.1](SPRINT-0-MEASUREMENTS.md) U4: **NO** ⛔, measured on **4 feeds, 2 hosts** |
| [28 D-AC2](28-discovery-redesign.md) | [28 §5.1](28-discovery-redesign.md): "~~L1 Conditional GET~~ — **DELETED**" |
| [35 §6](35-testing-strategy.md) P5 row: "304 handling" | [28 §9](28-discovery-redesign.md): "Conditional fetching — ⛔ **Rejected**" |
| | [28 §10](28-discovery-redesign.md): `last_etag` / `last_modified` **REMOVED** |
| | [P4-IMPLEMENTATION-CHECKLIST.md](P4-IMPLEMENTATION-CHECKLIST.md) line 363 already flagged it |
| | [PHASE-04-HANDOVER T5](PHASE-04-HANDOVER.md): "**do not build conditional GET**" |

D-AC2's own wording settles it: *"**With U4 supported**, an unchanged feed returns 304."* U4 was not
supported. The criterion is void by its own precondition, not overruled.

### Options considered

| | Option | Verdict |
|---|---|---|
| **1** | **Build it anyway** — the plan says so | ❌ Ships dead code that can never take its branch. [Freeze §12](ARCHITECTURE_FREEZE.md) forbids a capability the freeze does not name, and §11 *un-named* this one. It would also make A3 permanently unprovable: no fixture can produce a 304 the server never sends, so the "test" would assert a mock against itself |
| **2** | **File a second §11 amendment** | ❌ An amendment requires a *failed measurement*. There is no new one — the 2026-08-05 measurement is the reason. Filing again would reopen a settled question and imply the first amendment was insufficient |
| **3** | **Skip it silently** and not mention the struck criteria | ❌ Exactly the silent narrowing [lock §4.1](EXECUTION_MODE_LOCK.md) exists to prevent, and P4's **F1** in its other direction |
| **4** ✅ | **Record a [freeze §11.1](ARCHITECTURE_FREEZE.md) documentation reconciliation**, strike the criteria explicitly, correct the four stale documents, defer the capability with a re-measurement trigger | ✅ |

### Decision

**Option 4.** The conflict is between frozen documents where **no technology, table or decision
changes** — precisely §11.1's definition, and the same shape as the 2026-08-07 entry reconciling
[13 §2.2](13-phase-03.md) with [04 §1.2](04-system-design.md).

**What changes, concretely:**

- Struck from P5: Deliverable "conditional-GET support"; Files entry
  `http_client.py (if_none_match, if_modified_since, 304 handling)`; Task 4; Task 5; Acceptance
  criterion **A3**.
- Corrected documents: [34 §P5](34-implementation-plan.md) row · [28 §12](28-discovery-redesign.md)
  file table and **D-AC2** · [35 §6](35-testing-strategy.md) P5 row.
- Freeze §11.1 gains one row. **No amendment. No new ADR.**
- [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) gains the capability with the trigger stated
  as a re-measurement: *"`scripts/probe/probe_rss.py::probe_u4_conditional` reports
  `etag_present: true` or `last_modified_present: true` on a live run."*
- A boundary test asserts `if_none_match` and `if_modified_since` appear **nowhere** in `src/`, so a
  future phase cannot reintroduce it by habit.

**What `http_client.py` still gets:** `x-ratelimit-reset` (Task 6). It is a real, measured header, it
is generic HTTP, and it does not offend R5.

---

## D2 — Does `get_feed` go through `http_cache`?

### The question

Doc 28 contradicts itself. [§7.2](28-discovery-redesign.md) line 394: *"`http_cache` … serves the
feed; **zero network**."* [§11 D5](28-discovery-redesign.md) line 534: *"**Discovery requests bypass
`http_cache` entirely.** The watermark *is* the cache."*

`get_feed` is the discovery request. It must pick one, and whichever it picks is what P6 inherits.

### Options considered

| | Option | Verdict |
|---|---|---|
| **1** | Cache the feed (§7.2) | ❌ D5 names the exact failure: a 15-minute TTL serving a stale feed to a 15-minute poll means the watermark **never advances** and new posts are silently lost. §7.2 is a cost narrative for an operator re-running a job by hand; D5 is a risk mitigation with a downstream acceptance criterion |
| **2** | Leave it to P6 | ❌ P5 must pass *something*. Defaulting to cached and letting P6 flip it means P5 ships the behaviour D5 forbids, and the flip would land with no test that noticed — P4's **F4** |
| **3** ✅ | **Bypass** — `allow_cache=False`, decided in P5, asserted in P6 | ✅ |

### Decision

**Option 3.** `get_feed` passes `allow_cache=False`.

- [34 §P6](34-implementation-plan.md) already makes "discovery bypasses `http_cache` (statement
  counter)" an acceptance criterion. P5 makes it true; P6 proves it at the statement level.
- Recorded as a **§11.1 reconciliation**: 28 §7.2's "zero network" row is corrected to
  **one request**, consistent with what the U4 amendment already did to §4.3's "0 bytes" claim.
- Mutation **M6** guards it.

---

## D3 — Is there a CLI, when the Files row does not name `main.py`?

### The question

[35 §6](35-testing-strategy.md) requires P5's manual guide to *"Fetch one feed by CLI; compare entry
count to the site."* No CLI surface for feeds exists, and [34 §P5](34-implementation-plan.md)'s
Files row does not list `main.py`.

### Options considered

| | Option | Verdict |
|---|---|---|
| **1** | No CLI; the guide uses an inline `python -c` | ❌ Fails [35 §5](35-testing-strategy.md)'s manual-guide rules — a non-developer cannot be handed a multi-line Python expression, and quoting it safely in PowerShell is exactly the trap [testing/P04-testing.md](testing/P04-testing.md) T12 was rewritten to remove |
| **2** | A throwaway script under `scripts/` | ❌ A scratch script that ships is [lock §5.1 H4](EXECUTION_MODE_LOCK.md)'s finding, and it would not be the CLI 35 asks for |
| **3** ✅ | **One additive `feed` command in `main.py`** | ✅ |

### Decision

**Option 3.** The Files row is documented as *"Expected to change — a guide, not a contract"*
([34 §1.1](34-implementation-plan.md)); [35](35-testing-strategy.md) is the frozen gate. The gate wins.

```
python main.py feed --subreddits a,b,c [--limit N] [--sort new|hot|top|rising]
                    [--query "..."] [--file PATH] [--config PATH]
```

Two properties earn their place:

- **`--file PATH`** parses a local Atom file and makes **no** network call. Every deterministic step
  of the manual guide runs through it: same code path, no rate limit, no flakiness, no live
  dependency. Only the one step 35 explicitly asks for is live, and it is marked optional.
- **`--config PATH`** is scoped to this command. It is what lets the guide test the
  `rss_enabled: false` rollback against a **temporary file in a scratch directory** instead of
  editing tracked `config.yaml` — the requirement the task statement makes and the one P4's T12
  workflow had to be corrected for.

The command is additive: no existing command's behaviour, arguments or output changes.

---

## D4 — Which field does `created_utc` come from, and how is the body extracted?

### The question

A1 — *"RSS and HTML produce identical post dicts"* — is P5's hardest criterion, and it fails on
details, not on design. Two are genuinely undetermined by the documents.

### The evidence

`scripts/probe/probe_rss.py` is P0's live-validated reader. It finds `{Atom}title`,
`{Atom}author/{Atom}name`, `{Atom}link`, `{Atom}updated`, `{Atom}content` — and **never checks for
`{Atom}published`**. Its line 103 comment records the decisive fact: *"Reddit wraps every entry's
content in a 'submitted by' footer. Real selftext pushes the median well past that boilerplate."*
Line 96 derives the subreddit from the link path by regex.

Against that, `_extract_post` (`src/reddit_client.py:267`) uses `data-timestamp`, which is
**creation** time in milliseconds, and reads the body from `div.expando .md` — a `.md` container,
`get_text(strip=True)`, truncated at 5,000 characters.

### Decision

| Field | Rule | Why |
|---|---|---|
| `created_utc` | `<published>` when present, else `<updated>`; naive UTC, `tzinfo` stripped | `<updated>` is an *edit* time. Falling back to it is honest; treating it as creation without saying so is not. The fixture states which element it carries, so the fallback is exercised rather than assumed |
| `body` | Unescape `<content>`, parse with `BeautifulSoup(..., "lxml")`, select **`div.md`**, `get_text(strip=True)[:5000]` | The *same* container class and the *same* truncation as the HTML path. This is what strips the "submitted by" footer, and it makes a link post (no `div.md`) produce `""` on both paths |
| `author` | `<author><name>` with a leading `/u/` stripped | HTML's `data-author` is a bare name |
| `url` | `<link href>` with the host normalised to `https://www.reddit.com` | `_extract_post` emits `DISPLAY_URL`; the feed returns whichever host was requested |
| `subreddit` | `<category term=>` first, link-path regex as fallback | The regex is P0-validated; `term` is more direct. A **multireddit** fixture with mixed subreddits proves both |
| `id` | `<id>`, expected to be the bare fullname `t3_…`; if it arrives as a URI, the fullname is extracted | Matches `data-fullname`. Verified against the fixture in stage 1 before the parser is written |
| `score`, `num_comments` | **`None`** | RSS carries neither ([SPRINT-0 §2.3](SPRINT-0-MEASUREMENTS.md)). `0` would be a fabricated fact — the bug already fixed for search `score` ([07 §4.1](07-scraping-pipeline.md)) |

**Method note — the fixtures must carry what the parser strips.** Every rule above is guarded by a
mutation, and every one of those mutations is disabled by a "clean" fixture: with no `/u/` prefix M2
passes with the parser broken; with no `SC_OFF` / "submitted by" wrapper M1 passes with the parser
broken; with a `www.reddit.com` link the host normalisation is never exercised. The Atom fixture
therefore carries **all four artifacts**, and the HTML twin is derived from the **real** captured
markup already in `tests/fixtures/reddit/listing_page1.html` — not authored to match the Atom, which
would make A1 pass by construction ([handover F3/F5](PHASE-04-HANDOVER.md)). Rule and order in
[checklist stage 1.0](P5-IMPLEMENTATION-CHECKLIST.md): M1 and M2 run **first**, and a miss means the
fixture is wrong, not the test.

**On D3's test affordances.** `--file` and `--config` are test affordances shipping in production
code. They earn their place — `--file` is what gives manual tests T2/T4/T5/T6 a real observable
instead of a pytest `PASSED` line, and `--config` is what keeps T8's rollback test off tracked
files — and the completion report says so explicitly, because unexplained CLI surface reads as scope
creep to the next reader.

---

## D5 — Does the transport start raising in P5, or in P6?

### The question

[PHASE-04-HANDOVER §3 and T1](PHASE-04-HANDOVER.md) assign *"`RedditClient._get` raising instead of
returning `None`"* to **"P5/P6"**. It has a real cost today: `on_pool_exhausted: pause_run` and
`fail_run` are indistinguishable from the run page, because neither can reach the handler as an
exception (blocker **N2**).

### Options considered

| | Option | Verdict |
|---|---|---|
| **1** | Change `_get` in P5 | ❌ `_get` is called by all six frozen methods and by `_paginate`. Making it raise changes the behaviour of shipped, tested code — the opposite of the P5 Files row's "**additive only**" — and the caller that would map the exception to a run outcome is `handlers/scrape.py`, which P5 does not touch and P6 does |
| **2** ✅ | **Keep `None`; P6 changes it** | ✅ |

### Decision

**Option 2**, taken explicitly rather than by omission.

- `_get` keeps its `None` contract. `get_feed` does **not** route through `_get` for parsing
  concerns: a transport failure yields `[]`, and a **parse** failure raises `FeedParseError` — the
  distinction A4 demands. The two failure modes stay separable, which is what P6 needs.
- The mapping from `EgressExhausted.action` / `.retryable` to a run outcome is P6's, alongside the
  discovery handler that will be the first caller with a run to fail.
- Recorded in the handover so N2 is not lost.

---

## Summary

| # | Decision | Authority |
|---|---|---|
| **D1** | **No conditional GET.** §11.1 reconciliation; three Tasks and one acceptance criterion struck; capability deferred with a re-measurement trigger | [freeze §11](ARCHITECTURE_FREEZE.md) U4 amendment |
| **D2** | **`get_feed` bypasses `http_cache`** (`allow_cache=False`) | [28 D5](28-discovery-redesign.md) over [28 §7.2](28-discovery-redesign.md); [34 §P6](34-implementation-plan.md) acceptance |
| **D3** | **One additive `main.py feed` command**, with `--file` and `--config` so the guide is offline and mutation-free | [35 §6](35-testing-strategy.md) over [34 §P5](34-implementation-plan.md)'s Files row |
| **D4** | `published`→`updated` fallback; body from `div.md`; `/u/` stripped; host normalised; `score`/`num_comments` = `None` | `_extract_post` + [SPRINT-0 §2](SPRINT-0-MEASUREMENTS.md) + `probe_rss.py` |
| **D5** | **Transport keeps returning `None`; P6 makes it raise** | [AD-2](ARCHITECTURE_FREEZE.md) + [handover §3](PHASE-04-HANDOVER.md) |
