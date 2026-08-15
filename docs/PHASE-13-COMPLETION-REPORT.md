# Phase 13 — Completion Report

**Phase:** P13, website fetch & local signals · **Completed:** 2026-08-15
**Objective ([34 §P13](34-implementation-plan.md)):** *"A URL becomes clean text plus locally
extracted facts, with **zero AI**."*

> Forward-looking notes live in [PHASE-13-HANDOVER.md](PHASE-13-HANDOVER.md).
> The operator's steps live in [testing/P13-testing.md](testing/P13-testing.md).
> Where an interrupted session resumes lives in [progress/P13-COMPLETE.md](progress/P13-COMPLETE.md).

---

## 1. Summary

**A web address now becomes text, and facts, and nothing else.** `WebsiteFetcher` reads a customer's
landing page plus up to six priority internal pages — seven requests total, 40 KB maximum, 15 seconds
each — extracts readable text with `trafilatura` and a BeautifulSoup fallback, fingerprints it, and
stores a `website_snapshots` row. `site_signals` then reads six kinds of fact off the same pages by
regex and dictionary: competitors, pricing posture, tech markers, `schema.org` blocks, social links
and the nav taxonomy.

**No model was called, and that is asserted rather than assumed.** `SELECT COUNT(*) FROM ai_calls` is
`0`, checked directly in `test_the_phase_makes_no_ai_call` — the idiom
[35 §6](35-testing-strategy.md)'s P11 row pins as *"not inferred from the fence"*, because a fence
proves nobody **imported** the AI layer, not that nobody **called** it.

**Three things about this phase are worth stating plainly.**

**The egress guarantee is tested where it can fail.** Every request carries
`request_class="website"`, which `src/net/policy.py` holds in the frozen `ALWAYS_DIRECT` set
([R18](ARCHITECTURE_FREEZE.md), [AD-25](ARCHITECTURE_FREEZE.md)). The obvious test — assert it goes
direct — **passes whatever the code does** under the shipped `prefer_proxy` + `[direct, dc]` ladder,
because direct is first anyway. So the assertion is made under **`policy: proxy_only` with a healthy
pool configured**, the only arrangement in which a bug is visible. That is P5's F3, which this
project has now recorded six times, and it was caught before the test was written rather than after.

**No migration, and no second writer.** `website_snapshots` was created by `0007`; the DB row is
*"writes"*, not *"creates"*. The chain stays at seven revisions of ten and
`test_the_chain_is_still_ten_revisions_or_fewer` remains **P17's**. `projects` still has exactly one
writer — P16's `project add`, which does not exist yet — so this phase's tests create their project
row in a fixture, exactly as [PHASE-12-HANDOVER §3.2](PHASE-12-HANDOVER.md) required. The CLI added
for manual verification writes **nothing at all**, for the same reason.

**The Files row is honoured and nothing sits outside it** — the first phase since P4 for which that
is true. `save_snapshot` lives inside `src/ai/website_fetcher.py` rather than in a new
`src/db/repositories/website.py`, because P14's Files row is where a knowledge repository first
appears.

**Four documentation clarifications were recorded before code was written**, at
[34 §P13](34-implementation-plan.md). **None is a [§11](ARCHITECTURE_FREEZE.md) amendment or a
[§11.1](ARCHITECTURE_FREEZE.md) reconciliation** — a reconciliation needs a *failed measurement*,
which is the standard P12's three met and these do not. **`ARCHITECTURE_FREEZE.md` is therefore
unchanged by this phase**, which is the correct outcome and is stated here rather than left as an
absence a reader has to notice.

---

## 2. Files added

| File | Purpose |
|---|---|
| `src/ai/website_fetcher.py` | `WebsiteFetcher`, `ExtractedSite`, `WebsiteSettings`, URL validation, the L1 cache, `save_snapshot`, and the operator CLI |
| `src/ai/site_signals.py` | The six local signals, `SiteSignals`, `PricingSignal` |
| `tests/test_website_fetcher.py` | 81 tests |
| `tests/test_site_signals.py` | 49 tests |
| `tests/fixtures/sites/landing.html` | A realistic SaaS landing page: nav, footer, priority links, three known script hosts and one unknown, a `@graph` with `Organization`/`Product`/`Offer`/`BreadcrumbList`, four social links, one off-site link, and three competitor phrasings |
| `tests/fixtures/sites/pricing.html` | Three tiers, two currencies, both intervals, `contact sales`, `custom pricing`, `free trial` |
| `tests/fixtures/sites/spa_shell.html` | A JavaScript-only shell — the `thin_content` path |
| `tests/fixtures/sites/not_found.html` | A 404 body |
| `docs/testing/P13-testing.md` | The manual guide |
| `docs/PHASE-13-COMPLETION-REPORT.md` | This file |
| `docs/PHASE-13-HANDOVER.md` | Forward-looking notes for P14 |
| `docs/progress/P13-COMPLETE.md` | Resume point |

**No migration file.** Deliberate — see §1.

---

## 3. Files modified, with the reason for each

| File | Reason |
|---|---|
| `requirements.txt` | `+trafilatura>=2.0`, the first new runtime dependency since P2. Named in [freeze §5](ARCHITECTURE_FREEZE.md) as the text-extraction choice, so **no amendment is needed**. It is **required**, not optional like P10's tier 3: all of P14 reads the text it produces, so a host without it would have a working fetcher and an empty knowledge base |
| `config.yaml` | The five `website.*` keys the Config row names. Placed before `network:` with a comment stating that egress for this fetch is **not** configurable here |
| `docs/34-implementation-plan.md` | The four clarifications and the two deliberate omissions, under the P13 row — the P12 pattern |
| `docs/35-testing-strategy.md` | The P13 row in §6, rewritten to name *where* each assertion has to be made rather than only what it asserts; and a note on gate rows 4 and 5 (see §6) |
| `docs/05-database-plan.md` | `website_snapshots` now has a writer. Records that `url` holds the **normalised** form, that every post-TTL fetch **inserts**, and that no markup is stored |
| `docs/14-phase-04.md` | §9.1 described `WebsiteFetcher` as *"goes through `ProxiedHTTPClient`"* and was silent on the half that matters. It is one of the two documents the phase's **Docs** row names |
| `docs/DEFERRED-IMPROVEMENTS.md` | DI31, DI32, DI33 and DI34 opened; the register range corrected to DI1–DI34 |
| `docs/README.md` | The execution table row for P13 |
| `README.md` | The **Status** section had said *"P0 and P1 complete"* since P1, twelve phases ago |
| `docs/testing/P12-testing.md` | ⚠️ **The P12 sign-off table was stamped** — see §10 |

---

## 4. Validation results

### 4.1 The gate

| Check | Result |
|---|---|
| `ruff check .` | **Clean** |
| `ruff format --check .` | **Clean** · 179 files |
| Full suite | **2035 passed, 2 skipped** in 1205.35 s (P12: 1905 / 2) |
| Full suite **under coverage** | **2028 passed, 9 skipped** in 1600.12 s — the extra 7 are the performance tests, which **self-skip under a tracer** by design (`docs/35` §2.1 checks 4–5); pre-existing behaviour, not a P13 effect |
| New tests | **+130** — 81 fetcher, 49 signals |
| Coverage, whole tree | **89.54%**, against the ≥70% gate (P12: 89.20%) |
| Coverage, `src/{ai,net,scoring}` | **90.29%**, against the ≥85% floor (P12: 90%) |
| Coverage, the two new modules | **97.27%** combined — `website_fetcher.py` **98.20%** · `site_signals.py` **96.13%** |
| `alembic heads` | `0007_projects_and_knowledge_base` — one head, **unchanged**; seven revisions of ten |
| `check_schema.py` | **76/76** on the live database |
| Boundary / fence tests | **81 passed** (AST-based) |
| Grep fences 2 and 3 | Prose matches only — 3 and 1, every one a docstring or comment, **zero import statements**. [DI29](DEFERRED-IMPROVEMENTS.md) unchanged |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns · `GET /` 200 |
| Offline guarantee | Held — the socket-blocking fixture is autouse and the only live fetch in this phase is the CLI, which no test invokes over the network |
| AI calls | **0**, asserted as `COUNT(*) FROM ai_calls` |
| Migration round-trip | Executed — see §4.3 |
| Documentation validation (check 18) | Every doc edit landed. **586 relative links checked across the twelve documents this phase touched; 6 broken, all six pre-existing** — see below |

> ⚠️ **Six broken internal links, none of them P13's.** Gate check 18 requires *"no broken internal
> link"*, and running it found six, every one pointing at `02-research-findings.md`, a file that has
> never existed. They date from the initial commit `87ba926`, appear **nowhere in P13's diff**
> (`git diff d0ef28c..HEAD` matches nothing), and sit in four documents this phase edited for
> unrelated reasons. **They were recorded rather than fixed** — [DI34](DEFERRED-IMPROVEMENTS.md) —
> because the four citations are to different claims and each needs checking against
> [02b](02b-research-2026-07.md) and [02c](02c-research-final-review.md) individually. That is a
> reading task, not a search-and-replace, and it is unrelated cleanup in this phase.

> **On the whole-tree figure, and a correction to an earlier reading in this session.** An
> intermediate coverage run reported **88.89%** and I recorded that P12's **89.20%** was *"not
> reproducible on this tree today."* **That was wrong**, and the final run says so: with the two new
> modules omitted it reports **89.19%** — P12's figure to within a rounding step — and with them
> **89.54%**. So P13 **raises** whole-tree coverage by **+0.35 pp** and the baseline reproduces
> exactly. The intermediate reading came from a run whose numbers I did not reconcile before writing
> them down; the final figures above are from a single uninterrupted run against the shipped code.

### 4.2 Mutation discipline

Every **bold** criterion in [34 §P13](34-implementation-plan.md) plus the surrounding guarantees.
**17 designed · 16 detected · 1 control held · 0 survived.**

| # | Guarantee broken | Verdict |
|---|---|---|
| M1 | `request_class` `website` → `html` — the direct-egress criterion | **DETECTED** |
| M2 | The L1 cache never hits — the zero-fetch criterion | **DETECTED** |
| M3 | The L1 cache ignores the freshness window | **DETECTED** |
| M4 | The page budget excludes the landing page (the off-by-one the clarification exists for) | **DETECTED** |
| M5 | The scheme allowlist becomes a denylist of the two schemes the plan names | **DETECTED** |
| M6 | The thin-content threshold drops to zero | **DETECTED** |
| M7 | The snapshot insert is suppressed when the hash is unchanged | **DETECTED** |
| M8 | Competitor names may end in a sentence period again | **DETECTED** |
| M9 | Competitor phrases become case-sensitive again | **DETECTED** |
| M10 | The sentence-start stopword guard is removed | **DETECTED** |
| M11 | Off-site links are followed | **DETECTED** |
| M12 | A non-200 landing page is accepted | **DETECTED** |
| M13 | An internal page failure aborts the crawl | **DETECTED** |
| M14 | The 40 KB character budget is not enforced | **DETECTED** |
| M15 | An L1 hit is not flagged as markup-free | **DETECTED** |
| M16 | **Control** — a comment changes; nothing should fail | **Control held** |
| M17 | The cache path reports the stored (normalised) URL again — the fourth real defect, below | **DETECTED** |

**M8, M9, M10 and M17 are not hypothetical — they are the four defects this phase actually shipped
and fixed.** The first three were found by the fixture rather than by inspection:

1. The competitor phrase patterns were **case-sensitive**, so every sentence-initial *"Compared to
   Xero"* was missed. `test_the_landing_fixture_yields_the_three_it_names` failed and named `Xero`.
2. The name pattern allowed a **trailing dot**, so *"an alternative to Xero. Plans start at…"*
   extracted the competitor **`Xero. Plans`** — which would have been seeded into P15's entity
   registry and aliased. `test_a_cache_hit_reports_that_it_saw_no_markup` failed and printed it.
3. A capitalised word beginning the next clause could still join a name; the trailing-stopword trim
   closes it.

The fix uses scoped `(?i:…)` groups rather than a whole-pattern flag, because `re.IGNORECASE` would
make `[A-Z]` match anything and **delete the capitalisation requirement every refusal depends on**.

**A fourth real defect was found in review, after the first commit, and fixed in `4a4e05a`.**
`ExtractedSite.url` **changed shape depending on whether the L1 cache hit**: a fresh fetch returned
`validate_url`'s output (`https://ledgerloop.example/` — path and trailing slash kept) while a cache
hit returned `row.url`, which is `normalise_url`'s output (`https://ledgerloop.example` — scheme and
host only). Measured directly: the two compare **unequal**. Nothing asserted `first.url ==
second.url`, so the whole suite passed over it.

`url` is on the surface **P14 consumes**, and a field that changes shape depending on a cache state
is the kind of difference that surfaces as a duplicate row three phases later rather than as an error
where it was introduced. Both paths now build `url` from the validated target; the **stored row stays
keyed on the normalised form**, because that is what makes `https://Example.com/` and `example.com`
one cache entry. Two tests pin both halves, and **M17** confirms the revert is caught.

**One test of my own was found vacuous and removed**: `test_the_known_dictionary_is_passed_through`
contained `assert … or True`, which passes unconditionally. It is exactly the defect
[35 §2.4](35-testing-strategy.md) exists to catch, and it was mine.

### 4.3 Rollback — executed, both paths

**P13 introduces no schema change**, so the Rollback row's `alembic downgrade 0006` is P12's
revision boundary. Both paths were run rather than described.

| Path | Result |
|---|---|
| **R1** — delete the `website:` block from `config.yaml` | `WebsiteSettings` **identical**: `max_pages=7, max_depth=2, max_total_chars=40000, per_page_timeout=15.0, cache_ttl_days=7` both with and without the block. `config.yaml` verified byte-identical afterwards by hash |
| **R2** — `alembic downgrade 0006_content_and_dedup` on a **copy** of the live database, then back up | **51/51** checks at `0006` with `--skip-p12`; **76/76** after `upgrade head`. The `sqlite-vec unavailable` warning appeared on the way back up, as expected |

### 4.4 Live verification

The CLI was run against a real website — the manual guide's expected output is a copy of it, not a
prediction:

```
URL              https://example.com/
Requests made    1
Pages read       1
Characters       285
Thin content     YES — under 500 characters
Content hash     01d96b8d4067ef0fef8a52fb6beff911cea8e1e8ed8758425b51ea30d8f0e862
```

`file:///etc/passwd`, `javascript:alert(1)` and `ftp://example.com` were each refused with a readable
sentence and no traceback; `https://example.com/definitely-not-a-real-page` failed with
*"answered HTTP 404. Check the URL — a project needs a page that loads."*

### 4.5 Budgets

| Budget | Result |
|---|---|
| ≤7 requests per project version | **7**, asserted exactly; the landing page is one of the seven |
| Extraction ≤ 40 KB | **40,000 characters**, truncation asserted |
| L1 hit = 0 requests | **0**, counted |
| Cost | **$0.00** — no provider was contacted |

---

## 5. Documentation updated

`docs/34-implementation-plan.md` · `docs/35-testing-strategy.md` · `docs/05-database-plan.md` ·
`docs/14-phase-04.md` · `docs/DEFERRED-IMPROVEMENTS.md` · `docs/README.md` · `README.md` ·
`docs/testing/P13-testing.md` · `docs/PHASE-13-COMPLETION-REPORT.md` ·
`docs/PHASE-13-HANDOVER.md` · `docs/progress/P13-COMPLETE.md`

**`ARCHITECTURE_FREEZE.md` is unchanged.** No amendment was needed and no reconciliation was forced.

---

## 6. Deferred improvements opened and closed

**Four opened. None closed.** All four are things the phase chose not to build or fix.

| | Entry | Owner |
|---|---|---|
| **DI34** | Six internal links point at `02-research-findings.md`, which has never existed. Found by gate check 18; pre-existing since `87ba926` and absent from P13's diff | Whoever next edits one of the four documents — it needs a person to decide which document each of the four claims lives in |
| **DI31** | `tests/integration/` does not exist while [35 §2.1](35-testing-strategy.md) row 5 runs `pytest tests/integration -q` as a gate check. Measured: exit code **4**, `ERROR: file or directory not found`. **Row 4 has the same defect** — `tests/unit/` holds exactly one file, so `pytest tests/unit -q` runs one file and reports success. What every phase has actually run is bare `pytest`, so **no test goes unrun**; the defect is in what the table claims. Same family as [DI29](DEFERRED-IMPROVEMENTS.md) and P5's F3 | Operator — it is a documentation decision (does row 5 name a directory or a marker?), which is why P13 did not make it unilaterally |
| **DI32** | `website.max_depth` ships, is validated, and is read by nothing | A phase needing a page two hops from the landing page. **None is planned** |
| **DI33** | An L1 cache hit yields no HTML, so four of the six signals cannot be recomputed from it | **P14**, the first consumer |

**No entry reached its trigger.** [DI28](DEFERRED-IMPROVEMENTS.md) stays with **P17** — P13 opened no
revision, so the question of `leads.run_id` did not arise. [DI30](DEFERRED-IMPROVEMENTS.md) is
unchanged and its warning was honoured: the suite was run **locally**, not read off a CI badge.

---

## 7. Commits

| Commit | Message |
|---|---|
| **`a1ea5c2`** | `feat(P13): the website fetcher, six local signals, and zero AI` — 22 files, **+4,140 / −21** |
| **`c9da926`** | `docs(P13): record the commit and the green CI run` |
| **`8c1503e`** | `docs(P13): DI34 — six pre-existing broken doc links, found by gate check 18` |
| **`26ba0a6`** | `fix(P13): ExtractedSite.url changed shape depending on the cache` — the review fix in §4.2, and the coverage correction |

Four commits, `d0ef28c..26ba0a6`, all pushed. `git status -sb` reports `## main...origin/main` with
no ahead count.

**Repository hygiene ([lock §5](EXECUTION_MODE_LOCK.md) H1–H8), against the staged diff:**

- Every one of the 22 files justified in §2 and §3. No `.db`, no `.log`, no scratch file.
- Secret scan: every match of `token` is prose or code **about parsing tokens** — `_NAME` splitting,
  a comment about CSRF tokens. **No credential shape.**
- Absolute-path scan: **one** match, `"file://C:/Users/someone/.env"` — a **synthetic** test input in
  the `file://` rejection parametrisation, deliberately Windows-shaped. It names no real user and
  leaks nothing; it is kept because a Windows file URL is a case worth refusing explicitly.
- `git check-ignore -v` confirms `.gitignore:2` ignores `.env` and `.gitignore:11` ignores
  `data/leads.db`.

---

## 8. CI status

✅ **Green on the final commit** — run
[`31893183382`](https://github.com/KulluPraveenKumar/reddit-lead-finder/actions/runs/31893183382)
(`26ba0a6`), `conclusion: success`. `ruff check` clean; `pytest` **2025 passed, 12 skipped** in
231.10 s. The first commit's run [`31890330477`](https://github.com/KulluPraveenKumar/reddit-lead-finder/actions/runs/31890330477)
was also green (**2023 passed, 12 skipped**).

⚠️ **That is ten fewer passes and ten more skips than the local 2035 / 2**, and the difference is
[DI30](DEFERRED-IMPROVEMENTS.md), not a regression: `data/leads.db` is gitignored, so a fresh checkout
skips the ten live-database tests — **including the migration round-trip
[35 §2.3](35-testing-strategy.md) calls non-negotiable**. P12's run showed the same signature
(1893/12 in CI against 1903/2 locally). **A green CI run is not evidence this phase is sound.** The
local **2035 passed / 2 skipped** in §4.1 is the one that counts, and it is why the manual guide's T9
tells the operator to run the suite themselves.

---

## 9. Manual testing guide

[docs/testing/P13-testing.md](testing/P13-testing.md) — eleven steps including both rollback paths,
about 25 minutes. Every expected output is copied from a real run on 2026-08-15.

**One step is a test rather than a click, and says so.** T7 proves the zero-fetch guarantee by running
the named tests, because the *"paste it again and watch nothing happen"* version needs a saved project
to paste against and **no project can exist yet** — the first is created by P16's `project add`, and
P13 was forbidden from adding a second way to create one. P16's guide is where that becomes a click.

**P13 also ships an operator CLI**, `python -m src.ai.website_fetcher <url>`, because a phase with no
operator-visible surface cannot be manually verified and *"read the source and trust it"* is not a
test step. It lives inside `website_fetcher.py`, so **the Files row stays exact** — same basis as P5's
`feed` CLI, P9's `python -m src.rules` and P10's `python -m src.dedupe`. It writes nothing.

---

## 10. Ready for manual sign-off

**Yes**, with two things stated rather than left implicit.

⚠️ **The P12 sign-off table was blank and has been stamped in this session.** The operator stated
P12 was signed off; `docs/testing/P12-testing.md` still showed `☐ PASS ☐ FAIL` with no date and no
signature on all nine rows. On the operator's explicit instruction the table was filled in
(PASS / 2026-08-15 / Praveen). **This is recorded because a stamped table is a claim about a human
having run those steps**, and the record should say who stamped it and when.

⚠️ **No tag.** [lock §6.2](EXECUTION_MODE_LOCK.md) permits one only when the phase's own sign-off
table is signed. P13's is blank, as it must be until the operator runs it.

**Not started, and will not be until P13 is approved:** Phase 14.
