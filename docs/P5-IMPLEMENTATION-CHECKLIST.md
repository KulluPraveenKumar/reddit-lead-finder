# P5 IMPLEMENTATION CHECKLIST — RSS client & Atom parser

**Companion to:** [P5-IMPLEMENTATION-REVIEW.md](P5-IMPLEMENTATION-REVIEW.md) ·
[P5-DECISION-ANALYSIS.md](P5-DECISION-ANALYSIS.md).
**Order is load-bearing.** Each stage ends with a green suite and, where marked, its own commit.

---

## Stage 0 — Entry (no code)

- [x] Working tree clean — ⚠️ required `git restore config.yaml`; see
      [review §3.3](P5-IMPLEMENTATION-REVIEW.md)
- [x] Baseline recorded: **695 passed, 2 skipped**, 171.7 s
- [x] `ruff check` / `ruff format --check` clean · `alembic heads` = one `0004` · `check_schema.py`
      25/25 · `gh run list` P4 green
- [ ] `phase-manager` skill loaded **before** the first edit under `src/`
- [ ] Decisions **D1–D5** accepted by the operator

---

## Stage 1 — Fixtures and ground truth (no `src/` change) · commit `test(P5)`

The fixtures come **first** so the parser is written against evidence rather than the Atom spec —
[handover F1/T2](PHASE-04-HANDOVER.md).

### 1.0 — Fixture provenance. Read this before authoring anything

> ⚠️ **A fixture that omits an artifact the parser strips silently disables the mutation that guards
> it.** If the Atom fixture's `<content>` has no `SC_OFF` / "submitted by" footer, **M1 passes with
> the parser broken**. If `<author><name>` has no `/u/` prefix, **M2 passes with the parser broken**.
> If `<link href>` already points at `www.reddit.com`, **R-3 is never exercised**.
>
> Equally: authoring the HTML twin *to match* the Atom fixture makes A1 compare two files the same
> author wrote to agree — it passes by construction. This is P4's **F3/F5** shape.

**Therefore the derivation runs in this direction, and only this direction:**

1. [ ] **HTML twin from real captured markup.** Take three `div.thing.link` elements from the
       already-shipped, real `tests/fixtures/reddit/listing_page1.html`. Anonymise `data-author`,
       `data-fullname` and the permalink. **Do not touch the markup structure.**
2. [ ] **Atom fixture authored to Reddit's real Atom structure**, carrying those same three posts and
       **every artifact the parser is supposed to strip**: the `/u/` prefix on `<author><name>`, the
       `<!-- SC_OFF --><div class="md">…</div><!-- SC_ON --> submitted by <a…>` wrapper inside
       `<content>`, an `old.reddit.com` host in `<link href>`, and `<category term=>`.
3. [ ] **Run M1 and M2 first**, before any other mutation. If either is *not* detected, the fixture is
       wrong — fix the fixture, not the test.

### 1.1 — Ground truth: one live capture · ✅ **DONE 2026-08-08**

`GET https://old.reddit.com/r/SaaS/new/.rss?limit=5` → 200, 7,815 bytes. Captured to a scratch
directory, **not** committed. Observed:

| Property | Observed | Settles |
|---|---|---|
| `<id>` | a **bare fullname** of the form `t3_<7 chars>`, not a URI | **A-1 verified**. Matches `data-fullname` |
| `<content type="html">` | `<!-- SC_OFF --><div class="md">…</div><!-- SC_ON -->` + a `submitted by … [link] [comments]` footer | **A-3 verified**. `div.md` is the selftext container, exactly as on the HTML path |
| Entry children | `author, category, content, id, link, updated, published, title` | `<published>` **is** present; `<updated>` is the fallback, not the primary |
| `<author><name>` | `/u/…` | R-2 confirmed — the prefix is real |
| `<category>` | `term="SaaS" label="r/SaaS"` | R-4 confirmed — `term` is the subreddit |
| `<link href>` | `https://old.reddit.com/r/…` | R-3 confirmed — host normalisation is required |
| Response headers | `x-ratelimit-used: 1`, `x-ratelimit-remaining: 0.0`, **`x-ratelimit-reset: 32`**, `Cache-Control: private, max-age=3600`. **No `ETag`. No `Last-Modified`** | **A-2 verified** — 32 is seconds-remaining, inside P0's 17–48 band. And **U4 independently reconfirmed**, three days after P0: [decision D1](P5-DECISION-ANALYSIS.md) rests on a repeatable measurement, not a one-off |

⚠️ The captured bytes contain real usernames and permalinks and are **never** committed
([lock §5.1 H2](EXECUTION_MODE_LOCK.md)). The fixtures are hand-authored to this *structure* with
invented values.

### 1.2 — The files

- [ ] `tests/fixtures/atom/listing_multireddit.xml` — **3 entries, 2 distinct subreddits**, one link
      post with no `div.md`, one entry carrying `<published>`, one carrying only `<updated>`,
      host `old.reddit.com`, all four strip-artifacts present per 1.0
- [ ] `tests/fixtures/atom/listing_multireddit.expected.json`
- [ ] `tests/fixtures/atom/search.xml` + `.expected.json` — boolean sitewide search feed (U3 shape)
- [ ] `tests/fixtures/atom/empty.xml` + `.expected.json` — valid Atom, **zero** `<entry>` → `[]`
- [ ] `tests/fixtures/atom/malformed.xml` — truncated XML. **No `.expected.json`**; its expectation
      is an exception, and the test says so
- [ ] `tests/fixtures/atom/listing_100.xml` — 100 entries, generated, for A2 and the < 50 ms metric
- [ ] `tests/fixtures/reddit/listing_matched.html` — the **HTML twin**, derived per 1.0 step 1 from
      real captured markup. This pair is what A1 is proved against
- [ ] **Anonymisation (lock §5.1 H2):** authors `example_user_1..n`, ids `t3_aaaa01..`, no real
      permalink, no real subreddit member name. `.expected.json` matches the anonymised values

**Gate:** fixtures parse as XML; `git status` shows only intended files.

---

## Stage 2 — `src/discovery/feed_parser.py` · commit `feat(P5)`

- [ ] `src/discovery/__init__.py` — exports `parse_feed`, `FeedParseError`
- [ ] `FeedParseError(ValueError)`
- [ ] `parse_feed(xml) -> list[dict]` returning `_extract_post`'s **exact** key set:
      `id, title, url, author, subreddit, score, num_comments, body, created_utc`
- [ ] **Hardened parser (B9):** `etree.XMLParser(resolve_entities=False, no_network=True,
      huge_tree=False)`
- [ ] Field rules per [decision D4](P5-DECISION-ANALYSIS.md):
  - [ ] `id` — `<id>`, fullname extracted if it arrives as a URI
  - [ ] `title` — `<title>` text
  - [ ] `url` — `<link href>`, host normalised to `https://www.reddit.com`
  - [ ] `author` — `<author><name>`, leading `/u/` stripped; `[deleted]` when absent
  - [ ] `subreddit` — `<category term=>`, link-path regex fallback
  - [ ] `score` = `None`, `num_comments` = `None`
  - [ ] `body` — unescaped `<content>` → `BeautifulSoup(..., "lxml")` → `div.md` →
        `get_text(strip=True)[:5000]`; `""` when absent
  - [ ] `created_utc` — `<published>` else `<updated>`, naive UTC
- [ ] A malformed document **raises**; a valid empty feed returns `[]`
- [ ] **No import of `src.ai`, `src.net` or `src.db`** (B8)

**Tests — `tests/test_feed_parser.py`:**

- [ ] Field-by-field against each `.expected.json` (**A6**)
- [ ] Empty feed → `[]`
- [ ] Malformed → `pytest.raises(FeedParseError)` (**A4**)
- [ ] 100-entry fixture: 100 dicts, parse **< 50 ms** (metric, asserted with headroom)
- [ ] Multireddit fixture yields **2 distinct** subreddits (R-4)
- [ ] Link post → `body == ""` (R-1)
- [ ] The `<updated>`-only entry gets a `created_utc` (R-5)
- [ ] Entity-expansion attempt is not resolved (B9)

**Gate:** suite green; coverage on `src/discovery/` ≥ 70%.

---

## Stage 3 — The parity proof · same commit

- [ ] `tests/test_feed_parity.py`: parse the HTML twin with `RedditClient._parse_listing` and the
      Atom fixture with `parse_feed`; assert for each `reddit_id`

      ```python
      assert rss == {**html, "score": None, "num_comments": None}
      ```

- [ ] The assertion compares **whole dicts**, so a new or missing key fails it (**A1**)

**Gate:** A1 proved. If it fails, fix the parser — never the fixture pair.

---

## Stage 4 — `RedditClient.get_feed()` · commit `feat(P5)`

- [ ] `_feed_url(subreddits, *, sort, limit, query, host)` — a **pure** function, tested without
      network:
  - [ ] No query → `{host}/r/{a+b+c}/{sort}/.rss?limit={limit}` (multireddit mandatory, U1)
  - [ ] Query → `{host}/search.rss?q=(subreddit:a OR subreddit:b) AND "…"&sort=new&limit={limit}`
        (U3 boolean form, [28 §3](28-discovery-redesign.md))
  - [ ] `quote_plus` on the query — the P2 encoding bug, not repeated
  - [ ] `sort` restricted to `new | hot | top | rising`; anything else raises `ValueError`
  - [ ] `limit` clamped to 1…100 (U5)
- [ ] `get_feed(subreddits, *, sort="new", limit=<config>, query=None) -> list[dict]`
  - [ ] `self.http.get(url, request_class=RequestClass.RSS.value, allow_cache=False)` (**B5**, **D2**)
  - [ ] Uses `self.http`; builds **no** client and **no** policy (**B4**)
  - [ ] `discovery.rss_enabled: false` → raises `FeedDisabled`, makes no request
  - [ ] Transport failure → `[]` (**D5**); parse failure → `FeedParseError` propagates (**A4**)
  - [ ] Applies `limit` to the returned list (**A2**)
- [ ] **No pagination.** One request per call, with a comment saying why (U1)
- [ ] The six frozen methods are **untouched** (**B7**)

**Tests — `tests/test_get_feed.py`** (a stub `http` double; no network):

- [ ] URL shapes for listing, multireddit, search, sort and limit clamp
- [ ] `request_class == "rss"` reaches the transport (**M5**)
- [ ] `allow_cache is False` (**M6**)
- [ ] `rss_enabled: false` → raises, zero calls (**M8**)
- [ ] Absent `discovery:` block → defaults apply, nothing raises (rollback level 2)
- [ ] `reset_policy()` in any test touching egress ([handover T4](PHASE-04-HANDOVER.md))

---

## Stage 5 — `x-ratelimit-reset` · commit `feat(P5)`

- [ ] `src/net/http_client.py::_retry_after` reads `Retry-After` first, then **`x-ratelimit-reset`**
      as **seconds remaining** ([SPRINT-0 §2.2](SPRINT-0-MEASUREMENTS.md): 17–48)
- [ ] Clamped to a sane ceiling; a non-numeric or negative value is ignored
- [ ] **Header name only** — no target knowledge; fence 4 still passes (**B1**)
- [ ] Tests: header honoured · `Retry-After` wins when both present · absurd value clamped (**M7**) ·
      garbage ignored

---

## Stage 6 — Configuration · commit `feat(P5)`

- [ ] `config.yaml` gains a `discovery:` block with `rss_enabled`, `rss_limit`, `rss_host` and
      comments citing U5/U6 and the rollback
- [ ] Defaults survive the block's absence
- [ ] `.env.example` unchanged — P5 needs no secret

---

## Stage 7 — CLI · commit `feat(P5)`

- [ ] `cmd_feed(config, args)` in `main.py`; `feed` wired in `main()`; `print_help()` updated
- [ ] `--subreddits a,b,c` · `--limit` · `--sort` · `--query` · `--file PATH` (offline) ·
      `--config PATH` (scoped to this command)
- [ ] **`--config` is re-loaded inside `cmd_feed`**, falling back to the config `main()` already
      passed in. `main()`'s own `load_config()` at line 317 is **not** restructured — doing so would
      change every other command's behaviour and break D3's "no existing command changes" claim
- [ ] **Explicit `sys.exit(1)`** on a disabled feed and on `FeedParseError`. No `cmd_*` exits
      non-zero today, and guide **T5** and **T8 Step 2** both assert `$LASTEXITCODE` ≠ 0
- [ ] **`FeedParseError` is caught and its message printed** — an unhandled raise also exits 1 but
      prints a traceback, which satisfies the exit code while failing T5's actual expectation of a
      clear message
- [ ] Prints a per-entry table and a count
- [ ] No existing command changes behaviour
- [ ] Tests: `--file` path end to end; `--config` honoured; unknown `--sort` reports usefully;
      **exit codes asserted** for the two failure paths

---

## Stage 8 — Boundaries and regression · commit `test(P5)`

- [ ] `tests/test_boundaries.py`:
  - [ ] `src/discovery/` imports no `src.ai` (**B8**)
  - [ ] `if_none_match` / `if_modified_since` appear **nowhere** under `src/` (**R-7**, D1)
  - [ ] Atom fixtures carry no real usernames or permalinks (**R-8**, lock H2)
- [ ] Fence 4 still passes after the `http_client.py` edit
- [ ] `RedditClient`'s six frozen methods asserted by introspection (**B7**)
- [ ] Legacy contract: 459 leads · `intent_score` fingerprint · `GET /` · 13 CSV columns ·
      17 endpoints

---

## Stage 9 — Mutation testing

**Run each mutation, watch the named test fail, revert.** A mutation not run is a guard not held —
[handover T2](PHASE-04-HANDOVER.md), where three of P4's seven were undetected first time.

**Result: 11 designed, 11 detected.** Two were not detected on the first attempt.

| # | Mutation | Detector | Ran | Detected |
|---|---|---|---|---|
| **M1** | Body = whole `<content>` text, not `div.md` | `test_the_submitted_by_footer_is_not_part_of_the_body` | ✅ | ✅ |
| **M2** | Drop the `/u/` strip | `test_each_shared_listing_field_individually` | ✅ | ✅ |
| **M3** | `parse_feed` returns `[]` on malformed XML | `test_a_malformed_feed_raises` | ✅ | ✅ |
| **M4** | Ignore `limit` | `test_the_limit_trims_the_returned_posts` | ✅ | ✅ |
| **M5** | Drop `request_class` from `get_feed` | `test_a_feed_request_uses_the_rss_class` | ✅ | ✅ ⚠️ |
| **M6** | Remove `allow_cache=False` | `test_a_feed_request_bypasses_the_http_cache` | ✅ | ✅ ⚠️ |
| **M7** | Read `x-ratelimit-reset` as epoch | `test_an_implausible_reset_value_is_clamped` | ✅ | ✅ |
| **M8** | `rss_enabled: false` stops refusing | `test_the_off_switch_refuses_and_makes_no_request` | ✅ | ✅ |
| **M9** | Parser resolves declared entities | `test_declared_entities_are_not_expanded` | ✅ | ✅ ⚠️ |
| **M10** | Validator tolerates any `url` difference | `test_a_feed_permalink_for_the_WRONG_post_is_not_tolerated` | ✅ | ✅ |
| **M11** | Validator tolerates an empty feed body | `test_a_feed_with_no_body_where_html_has_one_is_drift` | ✅ | ✅ |

⚠️ **M9 survived its first run.** `test_external_entities_are_not_resolved` used
`file:///etc/passwd` and asserted the output lacked `root:` — on Windows the path does not exist, so
the entity expanded to nothing and the test passed **on every machine this project runs on**, with
`resolve_entities=True`. Rewritten to declare an *internal* entity and assert it is not expanded.
**PHASE-04-HANDOVER T2, third occurrence.**

⚠️ **M5 and M6 silently SKIPPED on the first run** — their anchors ended in `\n` and the working tree
is CRLF. A skipped mutation prints one line and the run still reports a total; `8/11` was one unread
line away from being recorded as a pass. Anchors rewritten without newlines.

---

## Stage 9a — **Live parity validation against Reddit** · commit `feat(P5)`

Operator-requested, 2026-08-08. **Purpose: detect parser drift that fixtures cannot detect.** A
fixture is frozen the day it is written; Reddit's markup is not. A fixture pair proves the two
parsers agree about *2026-08-08 Reddit*. Only a live run proves they still agree about today's.

### Why this is permitted

| Constraint | Why it is not violated |
|---|---|
| [34 §1.2](34-implementation-plan.md) — *"`pytest` passes; **no live network or API calls**"* | This is **not a pytest test**. It is an operator-run script, excluded from the suite and from CI. The automated gate stays hermetic |
| [lock §5.1 H4](EXECUTION_MODE_LOCK.md) — no scratch scripts | It is a **maintained operator tool**, in the same category as the shipped `scripts/check_schema.py` and `scripts/probe/`, not a scratch file |
| [freeze §12](ARCHITECTURE_FREEZE.md) — no new capability | It adds none. It calls `get_new_posts()` and `get_feed()` — both already shipped — and compares dicts |
| R18 | The RSS half is direct automatically; the HTML half follows the ladder. Nothing is bypassed |
| U1 — 1 RSS request/60 s/IP | It makes **one** RSS request and **one** HTML request. U7 measured the two budgets as independent |
| No new dependency | Uses `RedditClient` and the standard library |

### The work

- [ ] `scripts/validate_feed_parity.py`
  - [ ] Fetch **one** subreddit by HTML — `RedditClient.get_new_posts(sub, limit=25)`
  - [ ] Fetch **the same** subreddit by RSS — `RedditClient.get_feed([sub], limit=100)`
  - [ ] Join on `id`; compare **only the intersection** — the two endpoints return different windows,
        and that is not drift
  - [ ] **Normalise the intentional differences**: drop `score` and `num_comments` before comparing,
        and assert separately that RSS reports both as `None`
  - [ ] Compare field by field: **`id`, `title`, `author`, `body`, `subreddit`, `url`, `created_utc`**
  - [ ] Report per field: matched / mismatched, with both values printed on a mismatch
  - [ ] Exit non-zero if any **hard** field mismatches
  - [ ] `--json PATH` to write a machine-readable record for the completion report
  - [ ] Runs against a **live** target and says so on the first line; `--subreddit` defaults to one
        of the configured subreddits
- [ ] **Documented tolerances** — a mismatch that is *not* drift, each stated in the script's output
      rather than silently ignored:
  - [ ] `score`, `num_comments` — **intentional**, RSS carries neither ([SPRINT-0 §2.3](SPRINT-0-MEASUREMENTS.md))
  - [ ] Posts present in only one result set — different windows (25 vs 100) and a few seconds
        between the two fetches. Reported as **coverage**, never as a mismatch
  - [ ] `body` — an edit between the two fetches, and HTML's 5,000-character truncation. Compared
        after the same truncation both sides; a length-only difference is reported distinctly from a
        content difference
  - [ ] `created_utc` — compared to the second; both are naive UTC
- [ ] Unit-tested with **stubbed** clients, so the comparison logic itself is in the hermetic suite
      even though the fetching is not
- [ ] **Run it live once**; paste the output into
      [PHASE-05-COMPLETION-REPORT.md](PHASE-05-COMPLETION-REPORT.md) as its own section, with the
      date, subreddit, counts and every documented difference
- [ ] Added to [testing/P05-testing.md](testing/P05-testing.md) as **T7a**, marked live and optional,
      with the 429 guidance T7 already carries

### ⛔ Stage 9a result — the validator found a real defect on its first run. **STOPPED.**

Run: 2026-08-08, `r/startups`, 25 HTML posts vs 100 feed posts, 25 shared.
**25 of 25 shared posts mismatched on `body`: HTML empty, RSS populated.**

**Root cause — the HTML listing page does not carry selftext at all.** Old Reddit renders the
expando lazily:

```html
<div class="expando expando-uninitialized" style="display: none">
  <span class="error">loading...</span>
</div>
```

`_extract_post` reads `div.expando .md`, which matches **zero** elements. Confirmed three ways, so
this is not a transient or a block:

| Source | `div.expando` | `div.expando .md` |
|---|---|---|
| Live `/r/startups/new/`, 2026-08-08 | 25 | **0** |
| `tests/fixtures/reddit/listing_page1.html` — the real P0/P1 capture | 25 | **0** |
| `tests/fixtures/reddit/search_page1.html` — HTML **search** | 0 | 22 via `div.search-result-body .md` |

So: **HTML search carries bodies. HTML listing never has.** `body` is empty for every
listing-sourced lead in the shipped product, and has been since before P5.

**This contradicts a frozen document and a P5 acceptance criterion:**

| Where | Claim | Measured |
|---|---|---|
| [28 §2.2](28-discovery-redesign.md) | HTML listing: "**Selftext body** ✅" | ⛔ **False** |
| [28 §2.2](28-discovery-redesign.md) | "An HTML listing page carries 25 posts *with body and score*… if full data is needed for more than ~25% of discovered posts, HTML listing is the cheaper source" | ⛔ The premise is false; the listing yields no bodies at any density |
| [34 §P5](34-implementation-plan.md) Acceptance | "identical … except `score`/`num_comments`" | ⛔ On live listing data `body` is a **third** difference |
| [34 §P6](34-implementation-plan.md) Task 5 | "density-adaptive body fetch (listing ≥25%, permalink <25%, hysteresis 30/20)" | ⛔ **Directly affected.** The ≥25% branch would fetch a listing page and get no bodies |

**Why this was invisible until now, and why the fixture pair could not have caught it:**
`tests/fixtures/reddit/listing_matched.html` was authored with a populated expando, because that is
what old Reddit's markup *looks like* in documentation. Live pages ship it empty. The fixture parity
test therefore passes on markup the site does not serve — the exact class of defect
[stage 1.0](#stage-1--fixtures-and-ground-truth-no-src-change--commit-testp5) warns about, caught by
the live validator the operator asked for. **The validator justified itself on its first run.**

⚠️ **`tests/fixtures/reddit/listing_matched.html` is currently unrepresentative and must be
corrected as part of whichever resolution is chosen.** It is the only known unsound artifact in P5.

**Not a P5 code defect.** The RSS parser is correct — its bodies are real selftext, verified against
the live capture. Nothing in P5 needs to change to make P5 correct; what needs deciding is what
"identical" means and what P6 inherits.

**Stopped here** per the operator's instruction and [lock §8](EXECUTION_MODE_LOCK.md): this is an
unexpected design conflict against a frozen document, and its resolution reaches into P6.

---

## Stage 10 — Full gate

- [ ] `pytest` — one clean uninterrupted run; record counts
- [ ] `pytest -W error::DeprecationWarning`
- [ ] `ruff check .` · `ruff format --check .`
- [ ] Coverage: `src/discovery/` ≥ 70%; `src/net/` still ≥ 85%
- [ ] All four grep fences
- [ ] `alembic heads` = one `0004`; up → down → up on a **copy** of the live DB
- [ ] `python scripts/check_schema.py` → 25/25
- [ ] Legacy contract green
- [ ] CI green on the pushed branch (push only on explicit instruction)

---

## Stage 11 — Documentation · commit `docs(P5)`

- [ ] [07-scraping-pipeline.md](07-scraping-pipeline.md) — **new §2a**, the feed surface
- [ ] [04-system-design.md](04-system-design.md) §5 — `get_feed`
- [ ] [00-current-state.md](00-current-state.md) §7
- [ ] [34-implementation-plan.md](34-implementation-plan.md) P5 row — DELIVERED note; struck items
      named with their reason (D1)
- [ ] [28-discovery-redesign.md](28-discovery-redesign.md) — §12 file table, **D-AC2**, §7.2's
      "zero network" row
- [ ] [35-testing-strategy.md](35-testing-strategy.md) §6 — P5 row's "304 handling" removed
- [ ] [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) **§11.1** — two reconciliation rows (D1, D2).
      **No amendment**
- [ ] [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) — conditional GET (re-measurement
      trigger); HTML `num_comments = 0` → `None`
- [ ] [CHANGELOG.md](../CHANGELOG.md)
- [ ] `docs/testing/P05-testing.md` — **every command re-executed** after implementation
- [ ] `docs/PHASE-05-COMPLETION-REPORT.md` · `docs/PHASE-05-HANDOVER.md` ·
      `docs/progress/P05-COMPLETE.md` · `docs/README.md` execution table

---

## Stage 12 — Hygiene and commit — [lock §5](EXECUTION_MODE_LOCK.md)

- [ ] `git status --short` — nothing unexpected, tracked or untracked
- [ ] `git diff --cached --stat` read in full; every file justified
- [ ] Secret / machine-path scans (H1, H3)
- [ ] `git check-ignore -v .env data/leads.db` proves the rules fire (H7)
- [ ] **`config.yaml` is at its committed value** — the §3.3 finding, not repeated
- [ ] Commit; **do not push and do not tag** without explicit instruction
- [ ] **STOP.** Do not begin P6
