# Privacy Review — Public Repository Test Fixtures

**Date:** 2026-08-06 · **Scope:** whether verbatim Reddit content may remain in the fixtures of a
**public** repository. **No architecture changed. No P2 work.**

Resolves open decision **O1** in [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md), raised because
[PRE-P2 §5.3](PRE-P2-VERIFICATION-REPORT.md) justified retaining post titles with *"acceptable for a
**private** repository"* — a premise that no longer holds.

---

## 1. Research summary

Five questions, answered from sources rather than assumption.

### 1.1 Are Reddit usernames and posts "personal data"?

**Yes, pseudonymous personal data.** GDPR and CCPA apply to data that identifies or can identify a
natural person; a stable pseudonymous handle with a post history qualifies. The consistent guidance
for scraped social data is to **anonymise or aggregate before storing**, and not to build profiles of
individuals without a lawful basis ([thunderbit](https://thunderbit.com/blog/reddit-scraper-github-guide)).

### 1.2 Does anonymising the *author* protect the author?

**No — not while the text is verbatim.** This is the finding that decides the review:

> *"Anonymisation of verbatim quotes is not possible, as search engines and accruing data from
> multiple sources may lead to re-identification of the original source."*
> — [BPS ethics guidelines for internet-mediated research](https://explore.bps.org.uk/content/report-guideline/bpsrep.2021.rep155/chapter/bpsrep.2021.rep155.5)

Platform search functionality means the content of a post identifies its poster, so best practice
where consent cannot be obtained is to **avoid verbatim quoting entirely**
([ETH Zurich](https://ethz.ch/en/research/ethics/ethics-commission/guidelines/social-media.html)).
Replacing a real handle with `redditor_0003` while leaving the exact title beside it is
therefore **not anonymisation** — it is a redirection that one search query undoes.

### 1.3 What is the accepted mitigation?

**Paraphrase or synthesise.** Roughly a third of reviewed studies paraphrase posts and strip
identifiers specifically to defeat search-engine re-identification
([scoping review, PMC11143395](https://pmc.ncbi.nlm.nih.gov/articles/PMC11143395/)); the recommended
practice is ethically defensible paraphrasing and modification of non-essential detail **without
distorting analytical meaning**. For a *test fixture* nothing analytical depends on the text at all,
so the strongest form — full synthesis — costs nothing.

### 1.4 Legal considerations beyond privacy

Reddit's User Agreement, Data API Terms, Public Content Policy and `robots.txt` all push against
redistributing bulk scraped content, and Reddit has litigated over unauthorised use rather than
merely blocking it (Reddit v. Anthropic, 2025; Reddit v. SerpApi, 2025). Publishing a corpus of real
Reddit posts in a public repository is a redistribution. **Synthetic fixtures are not.**

The repository is MIT-licensed. [README §Licence](../README.md) already states that the tooling is
MIT but the collected data is not ours to relicense — which is an argument *for* not shipping the
data at all.

### 1.5 Does anything technical depend on the real text?

**No. Measured, not assumed.** Every consumer of every fixture was traced:

| Fixture | Read by a test? | What the test asserts |
|---|---|---|
| `tests/baseline/export_baseline.csv` | **No** | — reference artefact only |
| `tests/baseline/index_baseline.html` | **No** | — reference artefact only |
| `tests/baseline/index_pre_ux.html` | **No** | referenced in a docstring as "kept for reference" |
| `tests/baseline/db_fingerprint.json` | Yes | table list, 459 leads, `intent_score` SHA-256 — **no text** |
| `tests/baseline/api_contract.json` | Yes | response keys and the 13-column CSV header — **no text** |
| `tests/fixtures/reddit/listing_page1.html` | Yes | `len(posts) > 0`, some score is not `None` |
| `tests/fixtures/reddit/search_page1.html` | Yes | posts parse, scores are `None`, next link is `after=t3_` |
| `tests/fixtures/reddit/soft_block_interstitial.html` | Yes | classified `SOFT`, yields zero posts |

**Not one assertion names a title, a username or a post id.** The byte-identical `GET /` guard was
itself superseded during Phase 1 by an API-contract check
(`tests/test_boundaries.py::test_legacy_api_contract_is_frozen`), which compares response *shape*,
not rendered content.

---

## 2. Recommendation

> **Synthesise. Retaining verbatim titles in a public repository is not defensible, and removing them
> costs nothing that is measurable.**

| Criterion | Finding |
|---|---|
| Privacy implication | Verbatim titles + subreddit re-identify the 413 authors the earlier pass anonymised. The anonymisation was ineffective as shipped |
| Re-identification risk | **High and trivial** — one search query per title |
| Searchability | Titles are indexed by Reddit, Google and Bing; a repository copy is indexed too |
| Legal | Redistribution of scraped content the project does not own, against a platform that litigates |
| Testing impact | **Zero.** No assertion reads title, author or id text |
| Value of retention | A human eyeballing a diff of a page that no longer has a byte-identical guarantee |
| Value of synthesis | The repository stops republishing other people's content, and the claim "fixtures are anonymised" becomes true rather than partial |

The measurable value is therefore **entirely on the synthesis side**. This is not a close call.

---

## 3. Implementation

A single deterministic transformation, applied once, verified before and after.

### 3.1 What was replaced

| Element | Before | After |
|---|---|---|
| Post titles | 445 distinct real titles (CSV) + 48 (golden fixtures) | Deterministic synthetic titles from a fixed fragment pool, length-matched to the original band |
| Usernames | 25 in `listing_page1`, 19 in `search_page1` | `redditor_0001…` |
| Reddit account ids | 25 `t2_…` opaque ids | Synthetic ids, **same length, same alphabet** |
| Post ids | 25 + 23 base-36 ids | Synthetic ids, same length and alphabet |
| URL slugs | Title-derived — `/comments/<real id>/<the real title, lower-cased and underscored>/` | Re-slugged from the **synthetic** title of the same post, so each row stays internally consistent |

### 3.2 What was deliberately **not** replaced

| Kept | Why |
|---|---|
| Subreddit names (`r/SaaS`, `r/entrepreneur`, …) | A community is not a natural person, and the parsers key on them |
| `AutoModerator` | A site-wide **bot**, not a natural person. GDPR protects identified natural persons; retaining it keeps the fixture's realism, since a bot post in a listing is a real case the parser must handle |
| Every number — scores, comment counts, intent scores, timestamps, row ids | They are the fixture's actual reference value, and the fingerprint depends on them |
| DOM structure, class names, `data-*` attribute names, nav-button groups | The golden fixtures exist to pin the parsers (risk **K1**). Changing text changes nothing they pin |

### 3.3 Invariants asserted after the transformation

Machine-checked, all passing:

| # | Invariant | Result |
|---|---|---|
| 1 | CSV header identical — 13 columns, same order | ✅ |
| 2 | 459 data rows | ✅ |
| 3 | Columns ID, Reddit ID, Subreddit, Author, URL, Score, Comments, **Intent Score**, Keywords, Status, Created UTC, Scraped At **byte-identical** | ✅ |
| 4 | Every Title replaced | ✅ 459/459 |
| 5 | Fingerprint `max 164.28 / avg 42.29` intact | ✅ |
| 6 | CRLF line endings preserved | ✅ |
| 7 | 0 of 60 sampled real titles remain anywhere in the tree | ✅ |
| 8 | 0 of 44 real usernames remain (`AutoModerator` excepted by §3.2) | ✅ |
| 9 | 0 of 25 real post ids remain | ✅ |
| 10 | Golden fixtures: `div.thing`, title anchors, `data-author`, `data-permalink`, `nav-buttons`, `search-result-link`, `after=t3_`, `after=t5_` and score-element counts **all unchanged** | ✅ 19/19 counts |

### 3.4 Mutation discipline — the fixtures still fail when they should

An anonymised fixture that can no longer detect a regression is worse than none.

| Mutation | Expected | Observed |
|---|---|---|
| `_parse_search_results` takes the first `.search-result-group` (the Phase-2 headline bug) | `test_search_next_link_paginates_posts_not_subreddits` fails | ✅ **failed** on `after=t5_2vubg` — the anonymised fixture still catches the exact bug it exists for |
| Listing title selector `a.title` → `a.titlex` | Should fail | ❌ **passed** — see §3.5 |

### 3.5 A gap the mutation testing found, and closed

Breaking the listing title selector left every parsed post with an empty title and
`test_listing_page_parses_posts_with_real_scores` **still passed**. That is a pre-existing coverage
gap, not one this pass introduced — but it is exactly the "quiet subreddit that is really a broken
parser" failure the fixture exists to prevent.

One assertion added: `assert all(p["title"] for p in posts)`. Re-mutated: breaks → **fails**,
restored → **passes**.

---

## 4. Impact analysis

| Area | Impact |
|---|---|
| Automated tests | **None.** 308 passed, 2 skipped — identical to before the change |
| Legacy contract | **Intact.** 459 leads · `intent_score` fingerprint unchanged · 13 CSV columns · 17 endpoints |
| Golden fixtures / K1 | **Preserved.** Structure counts identical; the parser-bug mutation is still detected |
| Manual testing guides | No step reads fixture text; no guide changed for this reason |
| Determinism | The transformation is index-based with no randomness. Re-running it on the same input gives the same output |
| Repository size | −4 KB net |
| Reversibility | The originals were **not** committed after this change and exist only outside the repository. This is intentional: a reversible anonymisation in public history is not an anonymisation |

### 4.1 The sweep caught this document

The first draft of this review quoted a real username and a real post id as illustrations, and the
verification sweep in §3.3 failed on its own report. Both were replaced with placeholders.

Worth recording, because it is the whole argument in miniature: **the leak is rarely in the file you
set out to clean.** The sweep runs over the entire tracked tree, not over the fixtures, which is why
it caught prose written minutes earlier.

### 4.2 What this does not claim

- **Git history still contains the original fixtures** in commits `87ba926` and `d5089ee`. Rewriting
  published history would break every existing clone and the tag, for content that was already public
  for the life of those commits. **Recorded, not hidden.** If the operator wants history rewritten,
  that is a deliberate decision with a known cost — it is not something to do silently.
- The subreddit names, timestamps and score distributions are real. They identify communities and
  moments, not people.

---

## 5. Verdict

**Implemented.** The repository no longer republishes any natural person's Reddit content. Open
decision **O1** is closed; the register entry records it.
