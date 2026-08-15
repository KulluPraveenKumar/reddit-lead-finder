# P13 — Complete

**Phase:** P13, website fetch & local signals · **Date:** 2026-08-15 · **Revision:** none added

> The resume record. If this session is lost, this is where the next one picks up.
> Evidence: [PHASE-13-COMPLETION-REPORT.md](../PHASE-13-COMPLETION-REPORT.md).
> Forward-looking: [PHASE-13-HANDOVER.md](../PHASE-13-HANDOVER.md).

---

## 1. State at the end of P13

| | |
|---|---|
| `alembic heads` | `0007_projects_and_knowledge_base` — **one head, unchanged**; seven revisions of ten |
| `data/leads.db` | **at `0007`**, untouched by this phase · 492 leads (459 baseline + 33) · every P12 table still empty |
| Full suite | **2035 passed, 2 skipped** in 1205.35 s (P12: 1905 / 2) · **+130 tests** |
| Under coverage | **2028 passed, 9 skipped** — the extra 7 are performance tests that self-skip under a tracer, by design |
| Coverage | **89.54%** whole tree (P12: 89.20%) · **90.29%** on `src/{ai,net,scoring}` · new modules **98.20%** and **96.13%** |
| `check_schema.py` | **76/76** on the live database |
| Boundary / fence tests | **81 passed** |
| Mutation testing | **17 designed · 16 detected · 1 control held · 0 survived** |
| Rollback | **Executed, both paths** — config-block deletion identical; `0006` round-trip 51/51 down, 76/76 up |
| New dependency | `trafilatura 2.2.0` + 13 transitive packages — **required, not optional** |
| AI calls | **0**, asserted as `COUNT(*) FROM ai_calls` |
| Live verification | `https://example.com` — 1 request, 285 chars, thin, hash `01d96b8d…` |
| Commit · push | `a1ea5c2` on `main`, pushed (`d0ef28c..a1ea5c2`) |
| CI | ✅ **green** — run `31890330477`, `conclusion: success`. **2023 passed, 12 skipped** — ten fewer than local, which is [DI30](../DEFERRED-IMPROVEMENTS.md), not a regression |
| Sign-off | ❌ **Unsigned** — `docs/testing/P13-testing.md` awaits the operator |
| Tag | ❌ **Not tagged**, and must not be while the sign-off is blank ([lock §6.2](../EXECUTION_MODE_LOCK.md)) |

⚠️ **`docs/testing/P12-testing.md` was stamped during this session** (PASS / 2026-08-15 / Praveen) on
the operator's explicit instruction, after they stated P12 was signed off and the table was found
blank. Recorded here because a stamped table is a claim about a human having run those steps.

---

## 2. What was built

Two modules, no migration, no route, no writer of `projects`.

* `src/ai/website_fetcher.py` — bounded crawl (landing + ≤6 priority paths, **7 total**, 40 KB,
  15 s/page), `request_class="website"` → **always direct** (R18/AD-25), `trafilatura` with a
  BeautifulSoup fallback, `content_hash`, the L1 cache on `(project_id, normalised url)` + freshness,
  `save_snapshot`, an http/https **allowlist**, and the operator CLI.
* `src/ai/site_signals.py` — competitors, pricing, tech markers, `schema.org`, social links, nav
  taxonomy.
* Four site fixtures, 130 tests.

**Four clarifications recorded at [34 §P13](../34-implementation-plan.md)**, none of them a freeze
amendment or a §11.1 reconciliation: the `422` is an exception attribute because P13 ships no route;
the L1 key is the URL, not the content fingerprint; `max_pages: 7` is a total; `max_depth` ships
unused. **`ARCHITECTURE_FREEZE.md` is unchanged.**

---

## 3. Deferred improvements

**Four opened — [DI31](../DEFERRED-IMPROVEMENTS.md), [DI32](../DEFERRED-IMPROVEMENTS.md),
[DI33](../DEFERRED-IMPROVEMENTS.md), [DI34](../DEFERRED-IMPROVEMENTS.md). None closed.** DI33 is
**P14's**; DI34 is six pre-existing broken doc links, found by gate check 18 and recorded rather than
fixed because fixing them is unrelated cleanup.

---

## 4. Resume point

**P13 is implemented, validated and committed. It is _not_ signed off and _not_ tagged.**

The next session does **one** of these, in this order of precedence:

1. **If the operator has signed `docs/testing/P13-testing.md`** — tag the phase:
   ```bash
   git tag -a v0.1.0-p13 -m "P13 complete: website fetch and local signals"
   git push origin v0.1.0-p13
   ```
   Then, and only then, P14 may begin **on explicit approval**.

2. **If the sign-off is still blank** — do nothing to the code. The gate between phases is the
   quality mechanism, not overhead. Report that P13 awaits sign-off and stop.

3. **P14 — `analyze_business`** ([34 §P14](../34-implementation-plan.md)), when approved:
   * Read [PHASE-13-HANDOVER.md](../PHASE-13-HANDOVER.md) in full — **§4 T1, T2, T3 and T4
     especially**.
   * ⚠️ **Check V-1 first.** P14's Depends-on row names *"P0 (V-1 provider decision)"* — DeepSeek
     direct vs OpenRouter. That is a **P0** item, not a P13 one, and it gates the first provider call
     this project makes.
   * **Exactly one** `ai_calls` row per analysis · **< $0.05** · 23 sections · per-section failure
     isolation · L2 cache on `content_hash` + prompt version.
   * ⚠️ **P14 opens no revision.** `0008` is **P17's**.
   * **[DI33](../DEFERRED-IMPROVEMENTS.md) is yours to resolve**: a cache hit hands you text and no
     markup, so four of the six local signals come back empty. `SiteSignals.markup_seen` is the flag.

**Before any of it:** `git status` clean · `alembic heads` = one `0007` · full suite green at
**2035 passed, 2 skipped** · `check_schema.py --db data\leads.db` = **76/76** · `trafilatura`
installed · `config.yaml` checked for uncommitted local values.

⚠️ **Run the suite locally. A green CI badge is not a substitute** — CI has no `data/leads.db` and
skips ten tests including the migration round-trip ([DI30](../DEFERRED-IMPROVEMENTS.md)). That is how
P12's regression reached `main` green and was caught by an operator instead.
