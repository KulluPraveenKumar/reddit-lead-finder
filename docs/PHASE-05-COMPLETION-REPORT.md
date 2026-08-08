# PHASE-05 COMPLETION REPORT — RSS client & Atom parser

**Phase:** P5 · [34 §P5](34-implementation-plan.md) · **Completed 2026-08-08**
**Companions:** [PHASE-05-HANDOVER.md](PHASE-05-HANDOVER.md) ·
[P5-IMPLEMENTATION-REVIEW.md](P5-IMPLEMENTATION-REVIEW.md) ·
[P5-DECISION-ANALYSIS.md](P5-DECISION-ANALYSIS.md) · [testing/P05-testing.md](testing/P05-testing.md)
**Architecture status:** FROZEN. P5 produced **two amendments and two reconciliations**
([freeze §11](ARCHITECTURE_FREEZE.md)) — all four forced by measurements, none by argument.

---

## 1. Phase summary

Reddit publishes every subreddit, user and search as an **Atom feed**. P5 teaches the project to read
them: one request now returns up to 100 posts across many subreddits, where the HTML path returned 25
from one. `get_feed()` is additive and has no caller — P6 wires it into collection.

The phase delivered everything in its row except the parts a P0 measurement had already deleted, and
one operator-requested addition — a **live parity validator** — turned out to be the most valuable
thing in it. It failed on its first run and proved that a frozen document had been wrong for months.

| | |
|---|---|
| Suite | **803 passed, 2 skipped** (P4 baseline: 695 / 2) — **+108 tests** |
| Under `-W error::DeprecationWarning` | 803 passed, 2 skipped |
| `ruff check` / `format --check` | All checks passed! / 109 files already formatted |
| Coverage | `src/discovery/` **91%** · `src/net/` **91%** (unchanged) |
| Mutations | **11 designed, 11 detected** — 2 only after the gaps they exposed were fixed |
| `alembic heads` | `0004_orchestration (head)` — **no migration** |
| `check_schema.py` | OK — all 25 checks passed |
| Grep fences | 4 of 4 |
| New runtime dependencies | **0** |

---

## 2. Root cause analysis — every defect discovered

Five. Two are in shipped production code and predate P5; three are in P5's own work, caught before
it shipped.

### D1 — The HTML listing page carries no selftext *(pre-existing, product-wide)*

**Symptom.** `scripts/validate_feed_parity.py`, first live run: **25 of 25** shared posts mismatched
on `body` — HTML empty, feed populated.

**Root cause.** Old Reddit renders a listing expando as
`<div class="expando expando-uninitialized"><span class="error">loading...</span></div>` and fetches
the text over AJAX when a reader clicks. `_extract_post` reads `div.expando .md`, which matches
**zero** elements. Every listing-sourced lead has had `body == ""` since before P5.

**Why it survived this long.** Nothing compared the two sources. The shipped fixture
`listing_page1.html` has the same empty expandos, so the HTML tests asserted `body == ""` and passed;
[28 §2.2](28-discovery-redesign.md) asserted the opposite in prose and nothing checked prose.

**Verified three ways** — live `/r/startups/new/` (25 expandos, 0 bodies), the P0 capture (25, 0),
and `search_page1.html` for contrast (22 bodies via `div.search-result-body .md`).

**Fix.** Not a code change — the parsers are both correct. Recorded as a
[freeze §11](ARCHITECTURE_FREEZE.md) amendment; [28 §2.2](28-discovery-redesign.md) corrected;
`body` added as a documented listing-only difference; **P6 task 5 flagged for redesign**.

**Lesson.** *A comparison nobody runs is a claim, not a fact.* Both parsers were individually
tested and individually right. The wrong thing was the sentence between them.

### D2 — `url` means different things on the two endpoints *(pre-existing)*

**Symptom.** Same tool, r/SaaS: 3 of 25 mismatched on `url` — HTML `https://i.redd.it/….png`, feed a
permalink.

**Root cause.** A listing title links to the post's *destination*. `_extract_post` reads that href,
so link and media posts store the shared thing, not the post. Separately,
`_extract_search_post` never normalises its host, so search-sourced leads carry `old.reddit.com` —
the live DB splits **444 / 27** across 471 rows.

**Fix.** **The feed keeps the permalink.** It is the actionable URL for a lead, matches the search
path, and matches 444 of 471 existing rows. Documented as a link/media-only difference and asserted
narrowly — the feed's permalink must carry *this* post's id — so the exception cannot hide a wrong
permalink. Host normalisation on the search path is **DI14**, deferred: it changes shipped behaviour
and raises a data-migration question about the 444 rows.

**Lesson.** *Parity is not the goal; correctness is.* Matching an endpoint that answers a different
question would have been a regression with a green test.

### D3 — The parity fixture was authored from documentation, not from the site *(P5, caught)*

**Symptom.** `tests/test_feed_parity.py` passed while the product was wrong.

**Root cause.** `listing_matched.html` was written with a *populated* expando — how old Reddit's
markup is described, not how it is served. The test therefore compared the feed against markup that
does not exist.

**Fix.** The fixture now carries the real empty expando, with a boxed warning telling the next
engineer not to "fix" it. Body parity moved to a **search** pair, where HTML genuinely renders a body
inline — so the guarantee is still proved against Reddit's own HTML rather than written off.

**Lesson.** **P4's F5, exactly repeated.** A fixture derived from how a thing *should* look tests the
author's belief. Fixtures must descend from captures.

### D4 — The XSS-hardening test passed with hardening disabled *(P5, caught by mutation M9)*

**Symptom.** M9 flipped `resolve_entities=False` → `True`; `test_external_entities_are_not_resolved`
still passed.

**Root cause.** It used `file:///etc/passwd` and asserted the output lacked `root:`. On Windows the
path does not exist, so the entity expanded to nothing and the assertion held **on every machine the
project runs on**.

**Fix.** Rewritten to declare an *internal* entity and assert it is not expanded — deterministic and
platform-independent. Now detects M9.

**Lesson.** **PHASE-04-HANDOVER T2, third occurrence.** *A guard you have not run is not a guard.*
This one was written, reviewed, and useless.

### D5 — Two mutations silently skipped on CRLF *(P5, caught)*

**Symptom.** M5 and M6 reported `SKIP — anchor not found`.

**Root cause.** The mutation anchors ended in `\n`; the working tree is CRLF.

**Why it matters more than it looks.** A skipped mutation prints a line nobody reads and the run
still reports a total. Rewritten without newline anchors; both now detect.

**Lesson.** *A test harness needs the same scepticism as the code.* `8/11` was one unread line away
from being reported as success.

---

## 3. Files created

| File | Purpose |
|---|---|
| `src/discovery/__init__.py` | Package boundary: no AI, no transport |
| `src/discovery/feed_parser.py` | Atom → `_extract_post`'s dict shape; hardened parser |
| `scripts/validate_feed_parity.py` | **Live** HTML-vs-RSS drift detector (operator tool, not in the suite) |
| `tests/fixtures/atom/listing_multireddit.xml` + `.expected.json` | 3 posts, 2 subreddits, every strip-artifact present |
| `tests/fixtures/atom/search.xml` + `.expected.json` | Boolean search feed; one entry with no `<content>` |
| `tests/fixtures/atom/empty.xml` + `.expected.json` | Valid feed, zero entries |
| `tests/fixtures/atom/malformed.xml` | Truncated; expectation is an **exception**, so no `.expected.json` |
| `tests/fixtures/atom/listing_100.xml` | 100 entries — volume only |
| `tests/fixtures/reddit/listing_matched.html` | HTML twin, **real empty expandos** |
| `tests/fixtures/reddit/search_matched.html` | HTML twin **with** bodies — where body parity is proved |
| `tests/test_feed_parser.py` · `test_feed_parity.py` · `test_get_feed.py` · `test_feed_cli.py` · `test_feed_parity_validator.py` | +108 tests |
| `docs/P5-IMPLEMENTATION-REVIEW.md` · `P5-DECISION-ANALYSIS.md` · `P5-IMPLEMENTATION-CHECKLIST.md` · `testing/P05-testing.md` | Pre-implementation review set |

## 4. Files modified

| File | Change |
|---|---|
| `src/reddit_client.py` | **+`get_feed()`, +`_feed_url()`, +`FeedDisabled`** and two module helpers. The six frozen methods are untouched (AD-2) |
| `src/net/http_client.py` | `_retry_after` also reads **`x-ratelimit-reset`**, seconds-remaining, clamped. Generic header only — fence 4 still passes |
| `main.py` | **+`feed` command** with `--file` and `--config`; help text. No existing command changed |
| `config.yaml` | **+`discovery:`** block, fully defaulted |
| `tests/test_boundaries.py` | +3 boundary tests |
| `tests/test_net.py` | +5 rate-limit-header tests |
| `docs/ARCHITECTURE_FREEZE.md` | §11: 2 amendments · §11.1: 2 reconciliations |
| `docs/28-discovery-redesign.md` | §2.2 corrected · §7.2 corrected · §12 file table · D-AC2 voided |
| `docs/34-implementation-plan.md` | P5 row struck/DELIVERED · **P6 task 5 flagged** |
| `docs/35-testing-strategy.md` | P5 row: 304 removed, parity added |
| `docs/07-scraping-pipeline.md` | **New §2a** — the feed surface |
| `docs/04-system-design.md` | **New §5.0** — `get_feed` |
| `docs/00-current-state.md` | §7 — zero new dependencies |
| `docs/DEFERRED-IMPROVEMENTS.md` | +DI12, DI13, DI14 |
| `docs/README.md` · `CHANGELOG.md` | Execution table, changelog |

## 5. Database / schema changes

**None.** No migration, no model change, no write. `alembic heads` is one `0004_orchestration`
before and after; `check_schema.py` passes 25/25.

## 6. API / interface changes

**All additive.** Nothing existing changed signature, return shape or behaviour.

| Interface | Change |
|---|---|
| `RedditClient.get_feed(subreddits, *, sort, limit, query)` | **New.** Returns `list[dict]` in `_extract_post`'s shape |
| `RedditClient` six frozen methods | **Unchanged** — asserted by introspection |
| `src.discovery.parse_feed(xml)` / `FeedParseError` | **New** |
| `RedditClient.FeedDisabled` | **New** — raised when `rss_enabled: false` |
| `ProxiedHTTPClient` | **No signature change.** `_retry_after` reads one more header |
| `python main.py feed` | **New command** |
| `config.yaml discovery.*` | **New, all defaulted** — absence reproduces the defaults |

---

## 7. Validation results

| Check | Result |
|---|---|
| Full suite | **803 passed, 2 skipped** · 190 s |
| `-W error::DeprecationWarning` | **803 passed, 2 skipped** · 284 s |
| `ruff check` / `ruff format --check` | All checks passed! / 109 files already formatted |
| Grep fences 1–4 | 4/4, including fence 4 after the `http_client.py` edit |
| `alembic heads` | one head, `0004` — no migration |
| `check_schema.py` | 25/25 |
| Legacy contract | 459 baseline leads · `GET /` · 13 CSV columns · 17 endpoints |
| Rollback L1 `rss_enabled: false` | **Executed** — refuses, makes no request (guide T8) |
| Rollback L2 absent `discovery:` | **Executed** — defaults apply |
| Rollback L3 additive-only | **Executed** — six frozen methods verified by introspection |

**2 skipped**, unchanged from P4: live-database tests that skip where `data/leads.db` is absent
(blocker **C1**).

## 8. Coverage results

| Package | Coverage | Gate |
|---|---|---|
| `src/discovery/feed_parser.py` | **91%** | ≥70% new modules ✅ |
| `src/discovery/__init__.py` | 100% | ✅ |
| `src/net/` | **91%** | ≥85% ✅ (unchanged from P4) |

The 8 uncovered `feed_parser.py` statements are defensive branches: the per-entry `except`, the
`findtext` fallbacks and the relative-URL path — reachable only from markup Reddit does not send.

## 9. Mutation testing results

**11 designed, 11 detected.** Two were undetected on the first attempt and are D4 and D5 above.

| # | Mutation | Detector |
|---|---|---|
| M1 | body = whole `<content>`, not `div.md` | `test_the_submitted_by_footer_is_not_part_of_the_body` |
| M2 | drop the `/u/` strip | `test_each_shared_listing_field_individually` |
| M3 | `parse_feed` returns `[]` on malformed XML | `test_a_malformed_feed_raises` |
| M4 | `get_feed` ignores `limit` | `test_the_limit_trims_the_returned_posts` |
| M5 | drop `request_class` (RSS would use the proxy ladder) | `test_a_feed_request_uses_the_rss_class` |
| M6 | drop `allow_cache=False` | `test_a_feed_request_bypasses_the_http_cache` |
| M7 | `x-ratelimit-reset` unclamped | `test_an_implausible_reset_value_is_clamped` |
| M8 | `rss_enabled: false` stops refusing | `test_the_off_switch_refuses_and_makes_no_request` |
| M9 | parser resolves entities | `test_declared_entities_are_not_expanded` — **failed first, see D4** |
| M10 | validator tolerates any `url` difference | `test_a_feed_permalink_for_the_WRONG_post_is_not_tolerated` |
| M11 | validator tolerates an empty feed body | `test_a_feed_with_no_body_where_html_has_one_is_drift` |

## 9a. Live parity validation — operator-requested

Run 2026-08-08 against live Reddit, two requests per run.

| | r/startups | r/SaaS |
|---|---|---|
| HTML posts / feed posts | 25 / 100 | 25 / 100 |
| Compared (shared) | 25 | 25 |
| **Hard mismatches** | **0** | **0** |
| Tolerated | 25 `body` | 24 `body`, 3 `url` |
| Feed posts carrying selftext | **100 of 100** | **97 of 100** |
| Exit code | 0 | 0 |

Compared: `id`, `title`, `author`, `body`, `subreddit`, `url`, `created_utc`.
Normalised and **reported, never silently dropped**: `score`, `num_comments`, `body` (listing only),
`url` (link/media only).

**The first run of this tool failed** — 25 of 25 on `body` — which is D1. It has paid for itself.

### Today's measurements, consolidated

| Measurement | Result |
|---|---|
| **Listing HTML has no populated selftext** | 0 bodies from 25 expandos, live and in the P0 capture |
| **RSS contains full selftext** | 97–100% of feed posts; P0 measured a 1,089-char median |
| **HTML search still contains body text** | 22 of 22, `div.search-result-body .md` |
| `x-ratelimit-reset` | **32** — seconds remaining, inside P0's 17–48 band |
| `ETag` / `Last-Modified` on `.rss` | **Neither.** U4 reconfirmed 3 days after P0 |
| `<id>` format | Bare fullname `t3_…` |
| `<published>` present | Yes, alongside `<updated>` |

**Why this affects P6:** [34 §P6](34-implementation-plan.md) task 5 chooses between an HTML *listing*
fetch and a *permalink* fetch by density. The listing branch has no bodies to return at any density.
See [PHASE-05-HANDOVER.md §4](PHASE-05-HANDOVER.md).

## 10. CI results

P4 green on `origin/main` at entry (run 31249734916). P5's run follows this commit.
**Standing limitation, unchanged:** `data/leads.db` is correctly gitignored, so three live-database
tests skip on the runner — "CI is green" does not mean the legacy contract is machine-verified
(blocker **C1**).

## 11. Manual testing guide

[testing/P05-testing.md](testing/P05-testing.md) — 14 tests, PowerShell, written for a
non-developer. **Every command executed as written**; two errors were found and fixed by executing
rather than assuming:

- **T9 Step 3** checked for a `v0.1.0-p4` tag that does not exist (P2–P4 are untagged because their
  sign-off tables are blank).
- **T10**'s `-k` filters matched fewer tests than intended — `-k "discovery"` and
  `-k "fixtures_are_anonymised"` selected 2 and **0**. A `-k` that matches nothing still exits
  successfully, so the step would have passed while proving nothing. The guide now asserts the count.

**No mutation of a tracked file.** T8 writes a small standalone config in a scratch directory.

## 12. Completion report

This document.

## 13. Handover document

[PHASE-05-HANDOVER.md](PHASE-05-HANDOVER.md).

## 14. Progress update

[progress/P05-COMPLETE.md](progress/P05-COMPLETE.md); [README.md](README.md) execution table updated.

## 15. Remaining risks

| # | Risk | Status |
|---|---|---|
| **D1** | P00–P05 manual sign-off tables unsigned | **Open** — the project's own rule ([lock §4](EXECUTION_MODE_LOCK.md)). No tag is created while they are blank |
| **C1** | R20's migration half never verified in CI | **Open**, standing property of the CI design |
| **B3/O2** | `mypy` not installed — [35 §2](35-testing-strategy.md) check 3 | **Open** since P2 |
| **N2** | `pause_run` / `fail_run` indistinguishable at run level | **Open** — P6, with the transport change |
| **New** | **P6 task 5's density heuristic rests on a refuted premise** | **Open by design** — flagged, not fixed. P5 was told not to redesign P6 |
| **New** | The feed is now the only bulk source of selftext | **Accepted.** [28 §11 D3](28-discovery-redesign.md)'s HTML fallback still exists but no longer supplies bodies — P6 must not treat it as a full substitute |
| **New** | `scripts/validate_feed_parity.py` is not in CI | **Accepted, deliberate.** [34 §1.2](34-implementation-plan.md) forbids live calls in `pytest`. Its *logic* is unit-tested; only the fetching is manual |

## 16. Deferred improvements

Three raised: **DI12** conditional GET (trigger: Reddit starts sending the headers) · **DI13**
`num_comments = 0` → `None` on the HTML path (trigger: P11's comment-fetch eligibility) · **DI14**
`_extract_search_post` host normalisation (trigger: P10's dedup keys on `url`).
