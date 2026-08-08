# P05 — COMPLETE

**Phase:** P5 — RSS client & Atom parser · **2026-08-08**
**Full record:** [PHASE-05-COMPLETION-REPORT.md](../PHASE-05-COMPLETION-REPORT.md) ·
[PHASE-05-HANDOVER.md](../PHASE-05-HANDOVER.md)

> This file answers one question: **if this session is lost, where does the next one resume?**

---

## 1. State at the end of P5

| | |
|---|---|
| Branch | `main`, clean, committed |
| Suite | **803 passed, 2 skipped** (P4: 695 / 2) |
| Migration | **none added** — `alembic heads` = one `0004_orchestration` |
| `check_schema.py` | OK — 25/25 |
| Tag | **none.** [Lock §6.2](../EXECUTION_MODE_LOCK.md) forbids tagging a phase whose manual sign-off table is blank; P00–P05 are all blank (blocker **D1**) |
| Rollback point | the P5 commit's parent — P4's `9b5fbe5` |

## 2. What P5 delivered

`RedditClient.get_feed()` reads Reddit's Atom feeds and returns posts in the same dict shape the HTML
extractor produces. One request now yields up to 100 posts across many subreddits.

- `src/discovery/feed_parser.py` — Atom → post dicts, hardened parser, no AI, no transport
- `src/reddit_client.py` — `get_feed()`, `_feed_url()`, `FeedDisabled` (six frozen methods untouched)
- `src/net/http_client.py` — `x-ratelimit-reset`, seconds-remaining, clamped
- `main.py feed` — CLI, with `--file` (offline) and `--config` (scoped)
- `config.yaml discovery:` — `rss_enabled` / `rss_limit` / `rss_host`, all defaulted
- `scripts/validate_feed_parity.py` — **live** HTML-vs-RSS drift detector, outside the suite
- 5 Atom fixtures, 2 HTML twins, +108 tests

**Nothing calls `get_feed()` yet.** P6 wires it into collection.

## 3. The result that matters most

The operator-requested live parity validator **failed on its first run** — 25 of 25 posts — and
proved that **the HTML listing page carries no selftext at all**. Old Reddit lazy-loads the expando,
so `div.expando .md` matches nothing. Confirmed live, in the P0 capture, and against HTML search
(which *does* carry bodies).

This refuted [28 §2.2](../28-discovery-redesign.md) and **invalidated the premise of P6 task 5's
density heuristic**. Two [freeze §11](../ARCHITECTURE_FREEZE.md) amendments and two §11.1
reconciliations were recorded. **P5 did not redesign P6** — that was explicitly out of scope.

## 4. Resume point

**The next action is P6 — Watermarks & incremental discovery, and it does not begin until it is
approved.**

Before writing any P6 code:

1. **Read [PHASE-05-HANDOVER.md §4](../PHASE-05-HANDOVER.md).** P6 task 5 is not implementable as
   written. The listing branch of the density heuristic fetches a page with no bodies in it.
2. Read [34 §P6](../34-implementation-plan.md) in full — thirteen fields, and note the ⚠️ on task 5.
3. Run `python scripts\validate_feed_parity.py` once. Two requests; the only check that notices
   Reddit changing under the project.
4. Record the suite green before the first change: **803 passed, 2 skipped**.
5. Load the `phase-manager` skill before the first edit under `src/`.

P6 adds migration `0005` (`discovery_watermarks`, `prescores`) — the first migration since `0004`,
and the phase where blocker **C1** (R20's migration half is never verified in CI) matters most.

## 5. Open blockers

| ID | Blocker |
|---|---|
| **D1** | P00–P05 manual sign-off tables unsigned — no tags created |
| **C1** | R20's migration half never verified in CI |
| **B3/O2** | `mypy` not installed |
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` — gates P23 |
| **N1** | Keyword and user leads not collected by the button or scheduler — P17 |
| **N2** | `pause_run` / `fail_run` indistinguishable at run level — closes in P6 |
| **NEW** | P6 task 5's premise refuted — redesign required before implementing it |
