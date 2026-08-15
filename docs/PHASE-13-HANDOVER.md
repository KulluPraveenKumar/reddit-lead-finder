# Phase 13 — Handover

**From:** P13, website fetch & local signals · **Written:** 2026-08-15
**To:** **P14**, and for the debts, **P15**, **P16** and **P17**

> Evidence lives in [PHASE-13-COMPLETION-REPORT.md](PHASE-13-COMPLETION-REPORT.md).
> Where the next session resumes lives in [progress/P13-COMPLETE.md](progress/P13-COMPLETE.md).

---

## 1. What now exists

**A URL becomes text and facts, and nothing reaches a model.** Two modules, no migration, no route.

```
WebsiteFetcher.fetch(url, session=?, project_id=?)
   │
   ├─ validate_url          http/https ALLOWLIST; anything else raises 422 before any request
   ├─ L1 cache lookup       (project_id, normalised url) + freshness  ──► HIT: 0 requests, done
   ├─ landing page          request_class="website"  ──►  ALWAYS DIRECT (R18)
   │     └─ non-200 or unreachable ──► WebsiteUnreachable, readable
   ├─ ≤6 priority links     scored against PRIORITY_PATHS, same host only; a failure is SKIPPED
   ├─ extract               trafilatura, BeautifulSoup fallback per page
   ├─ join + truncate       40,000 chars
   └─ ExtractedSite         + save_snapshot() when a session was passed

site_signals.extract(site)  ──►  competitors · pricing · tech · schema.org · social · nav
```

**The public surface P14 will meet:**

```python
from src.ai.website_fetcher import (
    PRIORITY_PATHS,          # the 8, in 06 §2.1 order
    THIN_CONTENT_CHARS,      # 500
    ExtractedSite,           # url, pages, text, content_hash, thin
                             #   + from_cache, requests_made, html_pages
    WebsiteFetcher, WebsiteSettings,
    InvalidWebsiteURL,       # status_code = 422
    WebsiteUnreachable,      # status_code = 502
    WebsiteFetchError,       # the base
    save_snapshot, validate_url, normalise_url, content_hash, extract_text,
)
from src.ai.site_signals import SiteSignals, PricingSignal, extract
```

**`website_snapshots` is the only table this phase writes**, and it writes nothing else.

---

## 2. Guarantees P14 must not break

| | Guarantee | Enforced by |
|---|---|---|
| **G1** | **Every website request goes out `request_class="website"`, and therefore direct** — asserted under `proxy_only` **with a healthy pool**, the only configuration where a bug is visible | `test_it_goes_direct_even_under_proxy_only_with_a_healthy_pool`, `test_the_fetcher_end_to_end_never_touches_the_pool`, `test_every_request_carries_the_website_class` |
| **G2** | **An L1 hit makes exactly zero requests**, counted rather than timed | `test_a_second_analysis_inside_the_window_makes_zero_fetches` |
| **G3** | **`SELECT COUNT(*) FROM ai_calls` is 0 for this phase** | `test_the_phase_makes_no_ai_call` |
| **G4** | **The page budget is 7 in total, landing page included** | `test_the_page_budget_includes_the_landing_page`, `test_a_budget_of_one_fetches_only_the_landing_page` |
| **G5** | **The scheme check is an allowlist** — `data:`, `ftp:` and `gopher:` are refused as firmly as `file:` | `test_a_non_http_scheme_is_rejected` (6 schemes) |
| **G6** | **Validation happens before any request** — a `file://` URL never reaches the transport | `test_validation_happens_before_any_request` |
| **G7** | **Off-site links are never followed** | `test_offsite_links_are_never_followed` |
| **G8** | **A failing internal page is skipped; only the landing page is fatal** | `test_a_failing_internal_page_is_skipped_and_the_crawl_continues` |
| **G9** | **Every post-TTL fetch INSERTS**, even when the hash is unchanged | `test_the_expired_refetch_writes_a_second_row_even_when_the_text_is_identical` |
| **G10** | **`content_hash` is over the extracted text, not the markup** | `test_it_is_over_the_extracted_text_not_the_markup` |
| **G11** | **Deleting the `website:` block reproduces the defaults exactly** | `test_deleting_the_block_reproduces_the_defaults`, `test_the_shipped_config_file_matches_the_defaults` |
| **G12** | **The CLI writes nothing** — no `projects` row, no `website_snapshots` row | `test_it_writes_nothing_to_the_database` |
| **G13** | **`SiteSignals.markup_seen` is `False` on a cache hit** | `test_a_cache_hit_reports_that_it_saw_no_markup` (both files) |
| **G14** | One head, still `0007` — P13 added no revision | `test_single_head`, `test_the_head_is_0007_and_there_is_still_one_of_them` |
| **G15** | **`ExtractedSite.url` has the same shape whether or not the cache hit**, while the stored row stays keyed on the normalised form | `test_a_cache_hit_returns_the_same_url_shape_as_a_fresh_fetch`, `test_the_row_is_still_keyed_on_the_normalised_url` |

---

## 3. ⚠️ What P14 inherits directly

1. **`ExtractedSite.text` is the input to `analyze_business`, and it is already ≤ 40 KB.**
   No further truncation is needed and adding one would change `content_hash`'s meaning.

2. **`content_hash` is your L2 cache key**, paired with the prompt version.
   [34 §P14](34-implementation-plan.md)'s *"re-analysis of an unchanged fingerprint makes **zero**
   calls"* is a query against it. The column is populated on every snapshot.

3. **`site_signals.extract(site)` is what you pass to the model as facts, not as questions.**
   [06 §2.2](06-ai-pipeline.md): asking a model to find a `<meta generator>` tag is paying tokens for
   a parser. `competitors(text, known=[...])` takes a per-project dictionary — that is the parameter
   the BKB fills once you have one.

4. **`ExtractedSite.url` and `website_snapshots.url` are deliberately different strings, and you
   will read both.** `ExtractedSite.url` is the **validated target** — it keeps its path and its
   trailing slash, and it is now identical on the fresh and the cached path (**G15**; it was not,
   and the fix is P13's own, found in review). `website_snapshots.url` is the **normalised**
   scheme+host, because that is the L1 cache key and it is what makes `https://Example.com/` and
   `example.com` one entry.

   ⚠️ **A consequence worth knowing before you meet it:** a project entered as
   `https://example.com/en/` caches under `https://example.com`. Within one project that is
   harmless — [05 §5.1](05-database-plan.md) makes `normalized_url` the project identity, so one
   project is one site — but if P16 ever allows two projects to differ only by path, the L1 key
   stops distinguishing them.

5. **`projects` still has no writer, and P16 is still the one.** P13 did not become a second one, and
   its own tests create the row in a fixture. If P14's handler needs a project, it does the same.

6. **`test_p12_wrote_no_row` is still yours to narrow, not to delete** —
   [PHASE-12-HANDOVER §6](PHASE-12-HANDOVER.md), unchanged. P13 wrote no row to any of the twelve
   either; `website_snapshots` is written only by a caller that passes a session, and no shipped
   caller does yet.

---

## 4. Traps waiting in P14

**T1 — 🔴 A cache hit hands you text and no markup, and four of the six signals go quiet.**
`website_snapshots` stores `extracted_text` and nothing else, so `ExtractedSite.html_pages` is empty
on the L1 path and `tech_markers`, `structured_data`, `social_links` and `nav_taxonomy` all come back
`()`. **`SiteSignals.markup_seen` is `False` and that is the flag to read** — four empty tuples with
no explanation read identically to *"this site has none of these"*, and a consumer that cannot tell
those apart records *"this company uses no analytics"* as a fact about the business. **P13 picked
none of the three fixes** (persist the signals — needs a column and therefore an amendment; re-fetch
— defeats G2; accept and mark — what ships) because P13 had no consumer and would have been guessing.
**You are the consumer.** [DI33](DEFERRED-IMPROVEMENTS.md).

**T2 — 🔴 `422` is on the exception, not in a response, and P16 owns the mapping.**
`InvalidWebsiteURL.status_code == 422` and `WebsiteUnreachable.status_code == 502`. If P14's handler
catches these, it must not invent its own status. **P16 is the phase that turns them into HTTP**, and
the attribute exists so that mapping is one line rather than a re-derivation.

**T3 — the competitor regex fails toward silence, deliberately, and it is easy to "improve" wrongly.**
Names must look like product names — capitalised or all-caps — which misses a genuinely lowercase
brand. **That is the intended direction.** A missed competitor costs one row your model may still find
in the prose; a *wrong* one is seeded into P15's entity registry, gains five kinds of alias, and
matches Reddit posts for the life of the project. Three real defects were found here by the fixture
(see [the completion report §4.2](PHASE-13-COMPLETION-REPORT.md)); the loosest of them extracted the
competitor **`Xero. Plans`**. If you widen the patterns, **widen the refusal tests in the same
change**.

**T4 — `re.IGNORECASE` on the whole competitor pattern would silently delete the capitalisation rule.**
The patterns use scoped `(?i:…)` groups so the *phrase* is case-insensitive and the *name* is not. A
flag on the whole expression makes `[A-Z]` match anything, and every refusal in T3 stops working while
every test that asserts a *match* keeps passing. This is the exact failure M9 and M10 pin.

**T5 — the `website:` block is read once, at construction.** `WebsiteFetcher(config=...)` builds
`WebsiteSettings` eagerly. A handler that changes config mid-run gets the old values, which is the
same contract every other settings object here has — but it means a test that monkeypatches config
after constructing the fetcher will silently test nothing.

**T6 — `max_depth` is validated and unused.** [DI32](DEFERRED-IMPROVEMENTS.md). Do not read it and
conclude a depth-2 crawl exists.

**T7 — the CLI makes a real network call and no test invokes it over the wire.** `main()` is the only
thing in this phase that reaches a live website. `render_report` is factored out precisely so it can
be tested without one, and the CLI tests substitute a fetcher over a fake client. **A test that let
`main()` reach the network would breach the offline guarantee** ([35 §2.3](35-testing-strategy.md)
check 6) rather than verify anything.

**T8 — trafilatura's `no_fallback` is deprecated and was removed during this phase.** The call passes
`include_comments=False, include_tables=True` and nothing else. If you re-add a speed flag, note that
`fast=` does not exist before trafilatura 2.1 and `requirements.txt` floors at 2.0.

---

## 5. Debts carried forward, by owner

| | Item | Owner |
|---|---|---|
| **DI34** | **New.** Six internal doc links point at `02-research-findings.md`, which has never existed. Pre-existing since `87ba926`; found by gate check 18 | Whoever next edits [05](05-database-plan.md), [34](34-implementation-plan.md), [35](35-testing-strategy.md) or [README](README.md) near the citation |
| **DI33** | 🔴 **New.** A cache hit yields no markup; four of six signals cannot be recomputed | **P14** — §4 T1 |
| **DI32** | **New.** `website.max_depth` ships unused | A phase needing depth 2. **None planned** |
| **DI31** | **New.** `tests/integration/` does not exist while gate row 5 names it; `tests/unit/` holds one file while row 4 names it. Bare `pytest` is what every phase has run, so nothing goes unrun | Operator — a documentation decision |
| **DI28** | `leads` has no `run_id`. P13 opened no revision, so the question did not arise | **P17**, the next revision (`0008`) |
| **`pain_phrase`** | Absent pre-score component. `pain_points` is still empty | **P14** |
| **`competitor`** | Absent pre-score component. `test_the_competitor_registry_was_not_wired_before_p15` still passes | **P15** |
| **`subreddit_fit`** | Absent pre-score component. `projects` is still empty | **P16** |
| **T3 (P12)** | The `vec0` DDL is still unexecuted — P13 did not touch the semantic layer | **P15** |
| **DI30** | 🔴 CI still cannot run the ten live-database tests. **Honoured, not closed**: this phase's suite was run locally | Operator |
| **DI29** | The literal `grep` form of fences 2 and 3 still returns prose matches — 3 and 1 today, every one a docstring or comment, **zero imports**. The AST-based enforcement passes, 81 tests | Unchanged |
| **DI26** | `keywords.normalise` tears decomposed Unicode apart | **P15** |
| **DI14** | `_extract_search_post` does not normalise its host | Unchanged |
| **DI15** | An eighth job type shipped unreconciled. **P13 added none** | Unchanged |
| **DI16 / T1 (P8)** | `leads.confidence_score` exists, not populated | **P21** |
| **DI17** | Nothing enqueues `maintenance` | **P17** |
| **DI18 · DI20 · DI22 · DI27** | Triggers not satisfied across this phase | *A further occurrence* |
| **L4 (P7)** | Notification retry — **still nobody's** | Open since P7 |
| **O2** | `mypy`, deferred by D6 in P8. P13's new code ships clean under it | Its own scoped task |

**No Deferred Improvement was closed. Four were opened.**

---

## 6. Things a later phase must delete or narrow on purpose

| Phase | Test | Why it is there |
|---|---|---|
| **P14** | `test_the_three_absent_pre_score_components_are_still_absent` | Unchanged from P12 — P13 supplied none of the three. When P14 writes `pain_points.phrases_json`, update it **with** `WEIGHTS` and `prescore()`; a seventh weight **rescales every stored total** ([PHASE-11-HANDOVER §4](PHASE-11-HANDOVER.md) T2) |
| **P14** | `test_p12_wrote_no_row` | Still P12's, still to be **narrowed**, not deleted |
| **P14** | `test_a_cache_hit_reports_that_it_saw_no_markup` | If P14 resolves [DI33](DEFERRED-IMPROVEMENTS.md) by persisting signals, this test's *meaning* changes and it must change with it — do not simply delete it, or nothing will notice signals silently going empty |
| **P15** | `test_the_competitor_registry_was_not_wired_before_p15` | *(P9's)* Unchanged — P13 did not wire it. **`site_signals.competitors(known=…)` is the seam it will use**, and the parameter already exists |
| **P16** | *(new)* | When `POST /api/projects` lands, it maps `InvalidWebsiteURL` → **422** and `WebsiteUnreachable` → **502**. `test_the_rejection_carries_422` pins the attribute; P16 adds the test that pins the *response* |
| **P17** | `test_the_chain_is_still_ten_revisions_or_fewer` | Asserts **seven** revisions and that the last is `0007`. **P13 did not change it.** `0008_targeting` makes it eight |
| **P17** | `test_leads_has_no_run_id` | P12's DI28 decision, pinned. Unchanged by P13 |

---

## 7. Verification snapshot at handover

| | |
|---|---|
| Full suite | **2035 passed, 2 skipped** in 1205.35 s (P12: 1905 / 2) |
| Under coverage | **2028 passed, 9 skipped** — the extra 7 are performance tests that **self-skip under a tracer** by design, not a P13 effect |
| New tests | **+130** |
| Coverage, whole tree | **89.54%** (P12: 89.20%) · without the two new modules the same run reports **89.19%**, so P13 **raised** it by 0.35 pp |
| Coverage, `src/{ai,net,scoring}` | **90.29%**, against the ≥85% floor · new modules **98.20%** and **96.13%** |
| `ruff check` / `format --check` | Clean · 179 files |
| `alembic heads` | `0007_projects_and_knowledge_base` — one head, **unchanged**; seven revisions of ten |
| `check_schema.py` | **76/76** on the live database |
| Boundary / fence tests | **81 passed** (AST-based) |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns · `GET /` 200 |
| Mutation testing | **17 designed · 16 detected · 1 control · 0 survived.** **Four real defects found** — three in P13's own competitor regex, caught by the fixture; the fourth an `ExtractedSite.url` that changed shape on a cache hit, caught in review after the first commit |
| Migration | **None added.** The chain is unchanged |
| AI calls | **0** |
| Rollback | **Executed, both paths** — config-block deletion gives identical settings; `0006` round-trip gives 51/51 down and 76/76 up |
| New dependency | `trafilatura 2.2.0` + 13 transitive packages |
| Live verification | `https://example.com` fetched: 1 request, 285 chars, thin, hash `01d96b8d…` |

---

## 8. Blockers carried into P14

| ID | Blocker | Blocks P14? |
|---|---|---|
| **D1/O3** | **P00–P07, P09–P11 sign-off tables unsigned.** P8's was signed 2026-08-14; **P12's was stamped in P13's session** on the operator's instruction (see [completion report §10](PHASE-13-COMPLETION-REPORT.md)) | **No, but no tag.** P13's own guide is unsigned until the operator runs it |
| **🔴 V-1** | **The provider decision is P14's stated dependency** — [34 §P14](34-implementation-plan.md) reads *"Depends on P13, **P0 (V-1 provider decision)**"*. [31 §3.3](31-execution-plan.md) V-1 is *"DeepSeek direct vs OpenRouter — same 8-item enrichment on both"* | ⚠️ **Check before starting.** This is the one entry condition below that is not about P13 |
| **T3 (P12)** | The `vec0` branch has never executed | **No.** P14 does not touch the semantic layer; **P15** does |
| **DI33** | A cache hit yields no markup | **No, but it is P14's to decide** — §4 T1 |
| **O2** | `mypy` not in the gate | **No.** Deferred by D6 in P8 |
| **L4 (P7)** | Notification retry undelivered | **No**, still an open P7 obligation |

---

## 9. Entry conditions for P14

- [ ] `docs/testing/P13-testing.md` sign-off table signed — **T6, T7 and R2 especially**
- [ ] **[§3 read]** — `content_hash` is your L2 key; `site_signals.extract` is your facts-not-questions input
- [ ] **[§4 T1 read]** — 🔴 a cache hit has **no markup**; `markup_seen` is the flag, and [DI33](DEFERRED-IMPROVEMENTS.md) is **yours to resolve**
- [ ] **[§4 T2 read]** — 422/502 live on the exceptions; **P16** maps them to HTTP
- [ ] **[§4 T3 and T4 read]** — the competitor regex fails toward silence on purpose, and a whole-pattern `re.IGNORECASE` would silently delete every refusal
- [ ] **[§6 read]** — `test_p12_wrote_no_row` is to be **narrowed**; the three absent pre-score components need `WEIGHTS` updated **in the same change**
- [ ] ⚠️ **V-1 answered** — [34 §P14](34-implementation-plan.md) names it as a dependency and it is a **P0** item, not a P13 one. Check [SPRINT-0-MEASUREMENTS.md](SPRINT-0-MEASUREMENTS.md) before writing a provider call
- [ ] [34 §P14](34-implementation-plan.md) read — all thirteen fields, including **exactly one `ai_calls` row**, **< $0.05**, and **per-section failure isolation**
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] `trafilatura` installed — `pip install -r requirements.txt`. **P13 added it and it is required**, not optional
- [ ] The full suite recorded green before the first change — **2035 passed, 2 skipped**. ⚠️ **Run it locally, not from a CI badge** — [DI30](DEFERRED-IMPROVEMENTS.md)
- [ ] `git status` clean · `alembic heads` = one `0007` · `check_schema.py` **76/76**
- [ ] ⚠️ **`config.yaml` checked for uncommitted local values** — it carried a real chat id at the start of both P8 and P9. **P13 added the `website:` block**; nothing else in the file should have moved
- [ ] ⚠️ **P14 opens no revision.** `0008` is **P17's**. P14 writes rows into tables `0007` already created
- [ ] `gh run list` checked: P13 green on `origin/main`
