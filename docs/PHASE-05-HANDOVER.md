# PHASE-05 HANDOVER — RSS client & Atom parser → P6

**From:** P5 — RSS client & Atom parser (complete 2026-08-08)
**To:** P6 — Watermarks & incremental discovery
**Companion:** [PHASE-05-COMPLETION-REPORT.md](PHASE-05-COMPLETION-REPORT.md) ·
[testing/P05-testing.md](testing/P05-testing.md)
**Architecture status:** FROZEN. P5 produced **two amendments and two reconciliations**
([freeze §11](ARCHITECTURE_FREEZE.md)).

> ⚠️ **Not to be confused with the legacy "Phase 05."** [`15-phase-05.md`](15-phase-05.md) and
> [`testing/phase-05-testing.md`](testing/phase-05-testing.md) belong to the **old eight-phase
> numbering**, where "Phase 05" was the Adaptive Budget — which maps to **P19** here. The two schemes
> are unrelated.

**Read §4 before anything else.** One of P6's nine tasks is built on a premise P5 measured to be
false.

---

## 1. What now exists

```
src/discovery/
├── __init__.py         exports parse_feed, FeedParseError. No AI, no transport — enforced
└── feed_parser.py      Atom 1.0 -> _extract_post's dict shape; hardened XMLParser

src/reddit_client.py  ~ + get_feed(), _feed_url(), FeedDisabled   (six frozen methods untouched)
src/net/http_client.py ~ _retry_after also reads x-ratelimit-reset, clamped
main.py               ~ + `feed` command (--file offline, --config scoped)
config.yaml           ~ + discovery: {rss_enabled, rss_limit, rss_host}
scripts/validate_feed_parity.py +   LIVE drift detector — deliberately outside pytest
```

### 1.1 The interfaces P6 will use

```python
from src.discovery import parse_feed, FeedParseError

client.get_feed(["SaaS", "startups"])                    # one multireddit request, <=100 posts
client.get_feed(subs, query="looking for")               # boolean search feed (U3)
client.get_feed(subs, sort="new", limit=100)             # sort in {new, hot, top, rising}
```

Already handled for you, and **do not re-do them**: `request_class="rss"` (direct, R18),
`allow_cache=False` (D5), the multireddit join, the `limit` clamp, and the `x-ratelimit-reset` wait.

---

## 2. Seven guarantees P6 must not break

**G1 — `src/discovery/` imports no `src.ai`.** Enforced from P5 by
`tests/test_boundaries.py::test_discovery_makes_no_ai_calls`. P6 makes it an acceptance criterion for
`policy.py`; it already holds for the package.

**G2 — `src/net/` still contains zero Reddit identifiers.** P5 touched `http_client.py` for
`x-ratelimit-reset` — a generic header. Fence 4 passes. **Atom parsing stays in `src/discovery/`.**

**G3 — a malformed feed raises; an empty feed returns `[]`.** These must never converge. A damaged
response read as `[]` is indistinguishable from a quiet subreddit, so every poll reports silence and
every poll is believed. `parse_feed` also raises on a **well-formed non-feed** — the shape a
deprecation notice takes ([28 D3](28-discovery-redesign.md)).

**G4 — one policy per process.** `get_feed` uses `self.http`. A handler that builds its own policy
re-grants the hourly governor N times per run.

**G5 — `get_feed` makes exactly one request.** No pagination: a feed has no `next` link and U1 puts
the budget at one request per ~60 s **per IP**. If P6 needs more posts, it needs a *different* feed,
spaced.

**G6 — the six frozen `RedditClient` methods are unchanged** (AD-2), asserted by introspection in
`tests/test_get_feed.py::test_the_six_frozen_methods_are_untouched`.

**G7 — `score` and `num_comments` are `None` on the feed path, never `0`.** `None` is "unknown"; `0`
is a claim. P6 stores whatever `get_feed` returns, so this reaches the database.

---

## 3. What P5 deliberately did NOT do

| Not done | Owner |
|---|---|
| **Conditional GET / `ETag` / `Last-Modified` / 304** — the freeze deleted the layer | **Nobody.** DI12, trigger recorded |
| `discovery_watermarks`, the diff, overflow detection, `next_interval()` | **P6** |
| A discovery **handler**, `run_events` emission, any DB write | **P6** |
| `RedditClient._get` raising instead of returning `None` (blocker N2) | **P6** |
| **P6 task 5's density redesign** — see §4 | **P6** |
| `_extract_search_post` host normalisation (DI14) | Deferred |
| HTML `num_comments = 0` → `None` (DI13) | Deferred |
| Any migration — `alembic heads` is still one `0004` | — |

---

## 4. ⚠️ P6 TASK 5 RESTS ON A PREMISE P5 MEASURED TO BE FALSE

**Read this before designing stage 4.**

[34 §P6](34-implementation-plan.md) task 5 says:

> *Stage 4 density-adaptive body fetch (listing ≥25%, permalink <25%, hysteresis 30/20)*

It chooses between two ways of getting post bodies in bulk: fetch the **HTML listing page** when many
posts need one, or fetch each **permalink** when few do. It comes from
[28 §2.2](28-discovery-redesign.md), which stated that *"an HTML listing page carries 25 posts with
body and score"*.

### It does not. It never has.

Old Reddit renders a listing expando as:

```html
<div class="expando expando-uninitialized" style="display: none">
  <span class="error">loading...</span>
</div>
```

and fetches the text over AJAX when a reader clicks. `_extract_post` reads `div.expando .md`, which
matches **zero** elements on a real page.

| Source | Bodies |
|---|---|
| Live `/r/startups/new/`, 2026-08-08 | **0 of 25** |
| `tests/fixtures/reddit/listing_page1.html` (the P0 capture) | **0 of 25** |
| `tests/fixtures/reddit/search_page1.html` (**search**, for contrast) | **22 of 22** |
| Feed, live | **97–100 of 100** |

**So the listing branch of the heuristic would spend a request and return no bodies, at any
density.** Recorded as a [freeze §11](ARCHITECTURE_FREEZE.md) amendment.

### What P6 should consider — and P5 deliberately did not decide

The real choice is no longer *listing vs permalink*. It is:

1. **The feed already supplies the body** for ~97% of posts, in the request stage 1 makes anyway.
   The remaining ~3% are link and media posts, which have no selftext to fetch on any path.
2. So the branch may not need to exist. If it does, it is *feed body vs permalink fetch*, and the
   permalink is only needed for **comments** — which is stage 4's other half and unaffected.
3. **HTML search still carries bodies inline** (`div.search-result-body .md`), so the HTML fallback
   in [28 D3](28-discovery-redesign.md) is not body-less everywhere — but the **listing** fallback
   is, and D3 should say which one it means.

⚠️ **[28 §11 D3](28-discovery-redesign.md)'s "fall back to HTML listing automatically" no longer
restores full data.** It restores discovery, not bodies. P6 must decide whether that is acceptable
or whether the fallback should target search.

**P5 was explicitly instructed not to redesign P6.** Nothing above is implemented; it is the
evidence P6 needs to make the decision with.

---

## 5. Traps waiting in P6

**T0 — never hold the SQLite write lock across I/O.** Still the most expensive trap here. P3 lost a
sign-off to it; P4 had to prove it did not reopen it. **P6 adds the first discovery handler and the
first discovery write, so this is where it bites.** `handle_scrape_subreddit` drains degradation
notices *after* `scraper.run()` returns; a discovery handler emitting an event before its fetch
reproduces the HTTP 500 exactly.

**T1 — the transport still swallows every failure and returns `None`.** `on_pool_exhausted:
pause_run` and `fail_run` remain indistinguishable at run level (**N2**). `get_feed` keeps the same
contract deliberately: transport failure → `[]`, parse failure → raise. **P6 is where the transport
starts raising and `handlers/` gains the mapping.**

**T2 — a mutation you have not run is a test you do not have.** Two of P5's eleven were undetected
first time: one hardening test that passed on every machine because it depended on a Unix path, and
two mutations that silently *skipped* on CRLF anchors and would have been read as a pass.

**T3 — a fixture written from documentation tests your beliefs.** P5's parity fixture was authored
with a populated expando because that is how the markup is described. It passed against markup Reddit
does not send. **Derive fixtures from captures**, and keep every artifact the parser strips.

**T4 — `reset_policy()` in any test touching egress.** Unchanged from P4.

**T5 — the feed is one request per ~60 s per IP.** P6's poller must space requests. A burst of
twelve subreddit polls is twelve minutes of wall clock, which is why multireddit combining is
mandatory rather than an optimisation.

**T6 — `discovery.rss_enabled: false` must keep working.** It is rollback level 1 and P6 inherits it:
`get_feed` raises `FeedDisabled`, and [34 §P6](34-implementation-plan.md) requires the HTML path to
pass every test with the flag off.

**T7 — run `scripts/validate_feed_parity.py` at the start of P6.** It costs two requests and it is
the only check that notices Reddit changing. It found D1 on its first run.

---

## 6. Findings from P5 worth carrying forward

| # | Finding | Lesson |
|---|---|---|
| **F1** | A frozen document asserted for months that the HTML listing carried bodies. Both parsers were individually correct; the sentence between them was wrong | **A comparison nobody runs is a claim, not a fact** |
| **F2** | The parity fixture was authored from how markup is *documented* | **P4's F5 repeated.** Fixtures descend from captures, never from prose |
| **F3** | The entity-hardening test passed with hardening disabled, on every machine | **P4's T2, third occurrence.** A guard that cannot fail is documentation |
| **F4** | Two mutations *skipped* on CRLF and the run still printed a total | Read the skips. A harness needs the same scepticism as the code |
| **F5** | Two manual-guide `-k` filters selected 2 and 0 tests; both "passed" | **A filter that matches nothing exits successfully.** Assert the count, not the colour |
| **F6** | `url` means different things on three code paths, and the live DB is split 444/27 | Check what the database actually holds before deciding what "correct" is |
| **F7** | The stale conditional-GET text survived in four documents after the amendment | An amendment must be *applied*, not merely recorded |

---

## 7. Verification snapshot at handover

| | |
|---|---|
| Full suite | **803 passed, 2 skipped** · 190 s (P4 baseline: 695 / 2) |
| Under `-W error::DeprecationWarning` | **803 passed, 2 skipped** |
| New P5 tests | **+108** |
| `ruff check` / `format --check` | All checks passed! / 109 files already formatted |
| Coverage | `src/discovery/` **91%** · `src/net/` **91%** |
| `alembic heads` | `0004_orchestration (head)` — one head, **no migration** |
| `check_schema.py` | OK — all 25 checks passed |
| Legacy contract | 459 baseline leads · `GET /` · 13 CSV columns · 17 endpoints |
| Mutation testing | **11 designed, 11 detected** (2 after the gaps they exposed were fixed) |
| Grep fences | 4 of 4 |
| Live parity | r/startups **0 mismatches** · r/SaaS **0 mismatches** |

---

## 8. Blockers carried into P6

| ID | Blocker | Blocks P6? |
|---|---|---|
| **D1** | P00–P05 manual sign-off tables unsigned | **By the project's own rule, yes** ([lock §4](EXECUTION_MODE_LOCK.md)). No tag was created, per [lock §6.2](EXECUTION_MODE_LOCK.md) |
| **C1** | R20's migration half never verified in CI | **No**, but P6 adds `0005` — it is the phase where this matters most |
| **B3/O2** | `mypy` not installed | **No** — the gate cannot be claimed in full |
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` | **No** — gates P23 |
| **N1** | Keyword and user leads not collected by the button or scheduler | **No** — P17's scope |
| **N2** | `pause_run` and `fail_run` indistinguishable | **No** — it is T1, and P6 is where it closes |
| **NEW** | **P6 task 5's premise is refuted** — §4 | **Yes, for that task.** Redesign before implementing it |

---

## 9. Entry conditions for P6

- [ ] `docs/testing/P05-testing.md` sign-off table signed (and P00–P04, still outstanding)
- [ ] **[§4 of this document read in full]** — task 5 is not implementable as written
- [ ] `docs/34-implementation-plan.md` P6 read — all thirteen fields
- [ ] [28 §3](28-discovery-redesign.md) stages 1–6, [28 §8](28-discovery-redesign.md) polling policy,
      [28 §10](28-discovery-redesign.md) `discovery_watermarks` **without** `last_etag`/`last_modified`
- [ ] [07 §2a](07-scraping-pipeline.md) read — the feed surface P5 built and what it does not carry
- [ ] **[SPRINT-0 §2](SPRINT-0-MEASUREMENTS.md) re-read**: U1 (per-IP, ~60 s), U3 (boolean search),
      U5 (`limit=100`)
- [ ] `scripts/validate_feed_parity.py` run once — two requests, and it is the only drift check
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] **The full suite recorded green before the first change** — 803 passed, 2 skipped
- [ ] `git status` clean · `alembic heads` = one `0004` · `check_schema.py` 25/25
- [ ] `gh run list` checked: P5 green on `origin/main`
