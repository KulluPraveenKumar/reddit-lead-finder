# P00 — COMPLETE

**Phase name:** P0 — Validation Sprint (Stage A — Validation)
**Plan:** [34-implementation-plan.md §P0](../34-implementation-plan.md)
**Completion date:** 2026-08-05
**Recorded:** 2026-08-05, retroactively, during recovery from an unexpected shutdown
([`RECOVERY_REPORT.md`](../../RECOVERY_REPORT.md))

> ⚠️ **P0 of the frozen P0–P30 plan.** Not related to the legacy eight-phase numbering
> (`11-phase-01.md` … `18-phase-08.md`, `PHASE-01-STATUS.md`). See
> [`RECOVERY_REPORT.md` §1.2](../../RECOVERY_REPORT.md).

---

## Objective

> *"Convert 16 assumptions into measurements. **No production code.**"*

**Met.** Sixteen of sixteen measurable assumptions were answered or explicitly marked BLOCKED with
the reason named. One assumption (U4) was **refuted**, which removed a designed layer rather than
adding one.

---

## Git status

**None — the project is not under version control.** No `.git` directory exists. This is carried as
risk **K-R1** in the recovery report and is the highest-value outstanding fix.

---

## Files changed

| Area | Files |
|---|---|
| Probes (throwaway, by design) | `scripts/probe/probe_env.py`, `probe_rss.py`, `probe_rss_limits.py`, `probe_transport.py`, `transport.py` |
| Tests | `tests/unit/test_probe_transport.py` |
| Measurements | `docs/measurements/p0-transport.json` |
| Docs | `docs/SPRINT-0-MEASUREMENTS.md` (new), `ARCHITECTURE_FREEZE.md`, `docs/28-discovery-redesign.md`, `docs/29-network-and-proxy-strategy.md`, `docs/31-execution-plan.md`, `docs/35-testing-strategy.md`, `docs/testing/P00-testing.md` (new) |

**Nothing under `src/` was modified** — P0's defining constraint, and an explicit acceptance
criterion.

---

## Findings recorded

| # | Finding | Consequence |
|---|---|---|
| F1 | Direct: 100 % success, 0 % blocks. Webshare: 71.4 % success, 28.6 % hard blocks | **AD-25 validated** — direct-first is the default; proxies are a fallback |
| F2 | RSS carries full selftext (median 1,089 chars) | U2 confirmed on the favourable branch |
| F3 | RSS rate-limited to ~1 request / 60 s **per IP** | U1 = per-IP; multireddit combining becomes mandatory |
| F4 | No `ETag`, no `Last-Modified` on RSS | **U4 refuted** — doc 28 layer L1 deleted |
| F5 | Boolean multi-subreddit search works | U3 confirmed — 12 search requests, not 120 |
| F6 | Measured volume ~116 posts/day across 4 subreddits, not ~1,000 | Cost model is *more* favourable than assumed |
| F7 | The 100-entry RSS window takes 20.6 h to fill | Polling can be far less frequent than designed |
| F8 | Track B (Hermes) **BLOCKED** — no provider key, no Telegram token | 12 measurements deferred; nothing depends on them |
| F9 | Two grep fences in doc 35 are mis-specified — must be AST-based | Documentation defect; shipped enforcement was already correct |

**No architecture change was required.** One documented layer was deleted.

---

## Tests passed

Suite stood at **265 passed** at the end of P0. Re-verified during recovery at the current head:
**301 passed, 0 failed** (the delta is P1's 35 orchestration tests, plus adjustments).

---

## Manual testing completed

⚠️ **NO.** [`docs/testing/P00-testing.md`](../testing/P00-testing.md) exists and is complete
(T1–T7 plus rollback), but its **sign-off table is blank** — all nine checkboxes ☐, Tester and Date
empty.

`PHASE-01-COMPLETION-REPORT.md` describes P0 as *"signed off"*, citing this guide and
`SPRINT-0-MEASUREMENTS.md`. The measurements report is thorough and verified; **the checkbox table
carries no attestation.** Recorded as defect **D1** in the recovery report and deliberately left
uncorrected — only the operator can say whether the guide was executed and the table simply never
filled in, or never executed at all.

---

## Documentation updated

`SPRINT-0-MEASUREMENTS.md` (new), `docs/testing/P00-testing.md` (new), plus the freeze and the four
plan documents listed above. Doc 28's layer L1 was **removed** on the strength of F4.

---

## Known issues carried forward

| ID | Issue |
|---|---|
| **B1** | `.env` has no `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN` — gates P23 and Hermes Track B |
| **B3** | `mypy` required by doc 35 / FREEZE §5, **not installed** |
| **D1** | P00 sign-off table unsigned (above) |
| **K-R1** | Project not under version control |
| — | Multireddit volume anomaly — scheduled for P6 |

---

## Next phase

**P1 — Run & job schema.** Started and completed 2026-08-05; see
[`P01-COMPLETE.md`](P01-COMPLETE.md).

## Resume point

P0 requires no resumption. If work must restart from here, the entry point is P1, which is itself
already complete.
