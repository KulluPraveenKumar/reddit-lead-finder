# P12 — Complete

**Phase:** P12, project & BKB schema · **Date:** 2026-08-15 · **Revision:** `0007_projects_and_knowledge_base`

> The resume record. If this session is lost, this is where the next one picks up.
> Evidence: [PHASE-12-COMPLETION-REPORT.md](../PHASE-12-COMPLETION-REPORT.md).
> Forward-looking: [PHASE-12-HANDOVER.md](../PHASE-12-HANDOVER.md).
> Reasoning: [P12-DECISION-ANALYSIS.md](../P12-DECISION-ANALYSIS.md).

---

## 1. State at the end of P12

| | |
|---|---|
| `alembic heads` | `0007_projects_and_knowledge_base` — **one head**, seven revisions of ten |
| `data/leads.db` | **at `0007`** · 492 leads (459 baseline + 33) · `projects` and `bkb` empty |
| Backup before the upgrade | `data/backups/leads-20260815T101958Z.db` · 14,319,616 bytes |
| Full suite | **1903 passed, 2 skipped** in 388.07 s |
| Coverage | **89.20%** whole tree · **90%** on `src/{ai,net,scoring}` |
| `check_schema.py` | **76/76** on the live database |
| Mutation testing | **18 designed · 17 detected · 1 survived (the control) · 0 not applied** |
| Migration duration | **0.120 s** up · **0.165 s** down |
| Rollback | **Executed** on a copy — 51/51 down, 76/76 back up, fingerprint identical |
| AI calls | **0** |
| Commit · push | `51eecba` on `main`, pushed |
| CI | ✅ **green** — run `31879457795`, `conclusion: success` |
| Sign-off | ❌ **Unsigned** — `docs/testing/P12-testing.md` awaits the operator |
| Tag | ❌ **Not tagged**, and must not be while the sign-off is blank ([lock §6.2](../EXECUTION_MODE_LOCK.md)) |

---

## 2. What shipped

`0007` — twelve tables, six deferred `project_id` foreign keys closed, one `CHECK`, and a
conditional `vec0` pair that **was skipped** because `sqlite-vec` is not installed.

```
projects · website_snapshots · bkb · bkb_sections · personas · pain_points ·
intent_signals · bkb_entities · bkb_entity_aliases · bkb_links · bkb_evidence ·
bkb_suggestions            (+ bkb_embeddings, bkb_embedding_meta — skipped)

FKs closed: ai_calls · runs · leads · comments · dedup_groups · minhash_bands
```

**Every table is empty.** P14 writes the BKB; P16 writes the first project.

---

## 3. The three decisions that changed the revision

Each was **measured before code was written**, and each is a
[freeze §11.1](../ARCHITECTURE_FREEZE.md) reconciliation — **not** a §11 amendment.

1. **`runs.project_id` stays nullable.** [34 §P12](../34-implementation-plan.md) asked for
   `NOT NULL`; **11 of 11 live runs are `NULL`**, the rebuild fails on them, backfilling is the row
   rewrite **M5** forbids, and **AD-5** freezes project scoping as *additive and nullable*.
2. **Six foreign keys close, not four.** Four documents gave four different counts.
   [05 §7.1](../05-database-plan.md)'s table wins; the `leads` rebuild was probed on a copy of the
   live database first (492 rows, fingerprint `9327a13dd9ef4185`, nine indexes, all preserved).
3. **`bkb_sections.payload_json` is nullable with a `CHECK`.** [05 §5.1](../05-database-plan.md)
   says `NOT NULL`, [05 §5.1b](../05-database-plan.md) requires `NULL` for exactly three sections.
   §5.1b wins. **`ideal_customer_profiles` is not exempt.**

---

## 4. What was deliberately not done

* **[DI28](../DEFERRED-IMPROVEMENTS.md) `leads.run_id`** — considered while `0007` was open and
  **declined**, on DI28's own trigger text (*"no failed measurement"*) and [lock §8](../EXECUTION_MODE_LOCK.md).
  Pinned by `test_leads_has_no_run_id`; the entry stays open, now naming **P17**.
* **The three absent pre-score components** — `0007` creates their tables **empty**, so scoring them
  would be [DI24](../DEFERRED-IMPROVEMENTS.md) verbatim. **The labels were corrected** to name P14,
  P15 and P16 — the phases that write the rows.
* **`dedup_groups`/`minhash_bands` `project_id`** — left nullable; the dedup cascade writes `None`
  on every run.
* **`sqlite-vec` as a dependency** — not added. Optional by [freeze §5](../ARCHITECTURE_FREEZE.md).

---

## 5. Open, and whose

| Item | Owner |
|---|---|
| **The `vec0` DDL has never executed** — `sqlite_vec` absent on every host measured | **P15** |
| [DI29](../DEFERRED-IMPROVEMENTS.md) — **new**: the literal grep form of fences 2 and 3 returns 6 and 2 prose matches | Operator, when a reader acts on it |
| [DI28](../DEFERRED-IMPROVEMENTS.md) — `leads.run_id` | **P17** (`0008`) |
| `pain_phrase` · `competitor` · `subreddit_fit` | **P14** · **P15** · **P16** |
| One unreproduced test failure under CPU contention, identity not captured | *A second occurrence* |
| Manual sign-off tables for P00–P07, P09–P12 | Operator |

---

## 6. Resume point

**P12 is implemented, validated and committed. It is _not_ signed off and _not_ tagged.**

The next session does **one** of these, in this order of precedence:

1. **If the operator has signed `docs/testing/P12-testing.md`** — tag the phase:
   ```bash
   git tag -a v0.1.0-p12 -m "P12 complete: projects and BKB schema, revision 0007"
   git push origin v0.1.0-p12
   ```
   Then, and only then, P13 may begin on explicit approval.

2. **If the sign-off is still blank** — do nothing to the code. The gate between phases is the
   quality mechanism, not overhead. Report that P12 awaits sign-off and stop.

3. **P13 — Website fetch & local signals** ([34 §P13](../34-implementation-plan.md)), when approved:
   * Read [PHASE-12-HANDOVER.md](../PHASE-12-HANDOVER.md) in full — **§4 T1, T2 and T3 especially**.
   * `WebsiteFetcher` with **direct egress** (`request_class="website"`, AD-25), `site_signals.py`,
     the L1 fingerprint cache on `website_snapshots.content_hash`.
   * Adds **`trafilatura`** to `requirements.txt` — named in
     [freeze §5](../ARCHITECTURE_FREEZE.md), so no amendment is needed for that one specifically.
   * **Zero AI calls** in P13.

**Before any of it:** `git status` clean · `alembic heads` = one `0007` · full suite green at
**1903 passed, 2 skipped** · `check_schema.py --db data\leads.db` = **76/76** · `config.yaml` checked
for uncommitted local values.
