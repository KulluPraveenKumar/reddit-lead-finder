# P06 — COMPLETE

**Date:** 2026-08-08 · **Phase:** P6 — Watermarks & incremental discovery
**Report:** [PHASE-06-COMPLETION-REPORT.md](../PHASE-06-COMPLETION-REPORT.md) ·
**Handover:** [PHASE-06-HANDOVER.md](../PHASE-06-HANDOVER.md)

---

## What shipped

`0005_discovery` (`discovery_watermarks`, `prescores`) · `src/discovery/{watermarks,policy,triage}.py`
· `src/db/repositories/discovery.py` · `src/orchestration/handlers/discover.py` ·
`TransportError` in `src/reddit_client.py` (**N2 closed**).

An idle poll costs **one request and writes nothing**. Overflow is an **error** with an HTML
fallback and a halved interval. The polling interval is deterministic and makes **zero AI calls**.

## The decision this phase turned on

**P6 task 5's density-adaptive body fetch was deleted, not replaced.** P5 measured that an HTML
listing page carries no selftext; re-confirmed live in P6 (0 of 25 listing, 100 of 100 feed). Its
inputs do not exist — the feed supplies ~97% of bodies for free, the remaining ~3% are link/media
posts with no selftext anywhere, and score/comments are P11's. Stage 4 is now body *accounting*.

## Two further specification conflicts, both resolved

1. `28 §10`'s `ALTER TABLE prescores` → a `CREATE`; the table existed in no earlier migration.
2. **Task 4's "provisional prescore" is unwritable** — the CHECK requires every row to name a stored
   `Lead`, and a triage rejection is never stored. **Found by mutation testing** (two survivors).
   P6 counts rejection reasons on `run_events`; per-item auditing is **P11's**. Operator-approved.

## Verification

`883 passed, 2 skipped` · deprecation gate clean · ruff ×2 clean · `check_schema.py` **31/31** ·
`alembic heads` = one `0005` · **13/13 mutations detected** · coverage 96% / 98% / 87% ·
459 baseline leads intact · live parity exit 0.

**Not verified:** A4 (cold start ≥95%) — needs a paired live capture; recorded as such rather than
claimed.

## State at the end of this phase

- Working tree clean, committed and pushed to `origin/main`.
- Live database upgraded to `0005` after a backup; 459 baseline leads intact.
- **Untagged** — the manual sign-off table is blank (blocker D1, open since P0).

---

## Resume point

**The next action is P7 — Notification tier**, and it does not begin until it is approved.

Before the first edit under `src/`:

1. Read [PHASE-06-HANDOVER.md](../PHASE-06-HANDOVER.md) **§4 and §5** — the prescores narrowing P11
   inherits, and **T0**, which returns in P7 because notifications are emitted from every handler.
2. Read [34 §P7](../34-implementation-plan.md), all thirteen fields, plus
   [freeze R17 / AD-28](../ARCHITECTURE_FREEZE.md) — **notifications never invoke a model** — and
   [freeze §7](../ARCHITECTURE_FREEZE.md): **five** notification kinds, not nine.
3. Confirm `TELEGRAM_BOT_TOKEN` is in `.env`, or agree to defer P7's live half (**blocker B1**).
4. Load the `phase-manager` skill.
5. Record the baseline green **before** the first change: `883 passed, 2 skipped`.
