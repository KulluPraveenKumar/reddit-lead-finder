# Phase 08 — Quality Measurement, Dashboard, Export & Production Readiness

**Completion after this phase: 100%**

> **Rescoped by the 2026-07-30 research phase** from "calibration + monitoring" to a full quality
> programme. The holdout audit measures exactly one thing — what the gate discarded — and says
> nothing about calibration, drift, or grounding. A single metric is not a quality programme
> ([10 §1.1](10-implementation-roadmap.md), [06g Part II](06g-explainability-and-quality.md)).

## 1. Objective

Close the gap between "the pipeline works" and "an operator can run this reliably, **know it is
still right**, understand it, tune it, and get the data out." The quality suite, exports in three
formats, scheduled monitoring, maintenance automation, complete error and empty states, and
documented operations.

## 2. Scope

### 2.1 In scope

- Revision `0009_monitoring_and_quality` — monitoring columns plus **`lead_labels`, `golden_items`,
  `golden_runs`, `quality_snapshots`, `calibration_maps`**
- **`lead_labels`** capture from the lead list and drawer, **with optional reason chips**
  (`wrong_persona`, `wrong_pain`, `not_a_buyer`, `competitor_staff`, …) — the ground truth behind
  precision, ECE and the yield curve, and the input that routes a *knowledge* problem to the
  knowledge base rather than to the scorer ([06i §2.2](06i-feedback-and-memory.md))
- **`patterns`** — the nightly `GROUP BY` over `lead_analysis`, and `/projects/<id>/patterns`.
  **Zero AI cost**; no clustering, because the data is already labelled
  ([06h §6](06h-knowledge-lifecycle.md))
- **Researcher view** — a per-user toggle exposing evidence chains, component weights, pattern
  history and pinned versions ([06i §6](06i-feedback-and-memory.md))
- **Retention by memory class** — disposable cache purgeable at will, operational purged after
  aggregation, evidence and durable knowledge never auto-purged ([AD-18](03-architecture.md))
- **Golden set (100 items) as a *blocking* gate** — a prompt or model version does not ship if F1
  drops more than 0.02 against the reference
- **Calibration** — ECE (10 bins), Brier, reliability diagram, isotonic `calibration_maps` applied
  **at display time only** so recalibration never re-ranks
- **Drift monitors** — PSI on the score histogram, category priors, repair rate,
  `hallucinated_span_rate`, cache-hit collapse
- **`/health/quality`** — the four bands, every number drillable, under-powered metrics reporting
  `insufficient_data` rather than a misleading value
- **Nightly and weekly rollups into `quality_snapshots`** — pure SQL, **zero API cost**
- **Documented red-metric responses** ([06g §7](06g-explainability-and-quality.md)) — decided in
  advance so they are not rationalised away under pressure
- Entity-linked lead detail: every matched slug links back to its BKB section
- JSON and XLSX export alongside the extended CSV
- Scheduled per-project monitoring runs
- Maintenance job scheduled and verified
- Complete empty, loading, and error states across every page
- `/health` consolidation; metrics dashboard
- Performance work: query profiling, index verification, `content-visibility` for long tables
- Security review: secret handling, log redaction, Flask config
- `README.md` rewrite; operations runbook
- Final full-system regression against the live database

### 2.2 Out of scope

Everything in [10 §9 Future enhancements](10-implementation-roadmap.md) — notably reply drafting,
which is a permanent non-goal.

## 3. Architecture

No new architecture. This phase completes existing components:

```
src/export/
   ├─ csv_export.py     (extracted from routes.py, columns extended)
   ├─ json_export.py    (new)
   └─ xlsx_export.py    (new)

src/analytics/
   └─ calibration.py    (new — score deciles vs. `interested` rate)

src/orchestration/
   ├─ scheduler.py      (per-project monitoring runs)
   └─ handlers/maintenance.py   (retention purges, verified)
```

## 4. Files affected

**New**

| File | Purpose |
|---|---|
| `src/export/__init__.py`, `csv_export.py`, `json_export.py`, `xlsx_export.py` | Three formats |
| `src/analytics/calibration.py` | Calibration report |
| `src/dashboard/routes_analytics.py` | |
| `src/dashboard/templates/calibration.html` | |
| `src/dashboard/templates/health.html` | Consolidated health page |
| `src/dashboard/templates/partials/*.html` | Empty / error / loading states |
| `docs/RUNBOOK.md` | Operations |
| `scripts/canary.py` | Weekly live HTML check |

**Modified**

| File | Change |
|---|---|
| `src/dashboard/routes.py` | Export delegates to `src/export/`; **default CSV output unchanged** |
| `src/orchestration/scheduler.py` | Per-project schedules |
| All templates | Empty / error states |
| `README.md` | Full rewrite |
| `config.yaml` | `monitoring:`, `retention:` sections |
| `requirements.txt` | `+openpyxl` |

## 5. Database changes

Revision `0009_monitoring_and_quality` — additive, and **the last revision in the chain**:

```sql
ALTER TABLE projects ADD COLUMN monitoring_enabled  BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE projects ADD COLUMN monitoring_interval_hours INTEGER NULL;
ALTER TABLE projects ADD COLUMN last_monitored_at   DATETIME NULL;

CREATE TABLE lead_labels       (...);   -- incl. `reason`  — 05 §5.4c
CREATE TABLE golden_items      (...);
CREATE TABLE golden_runs       (...);
CREATE TABLE quality_snapshots (...);
CREATE TABLE calibration_maps  (...);
CREATE TABLE patterns          (...);   -- 05 §5.4d
```

`patterns` is a **rebuildable projection** — dropping and recomputing it from `lead_analysis`
loses nothing, which is why its `downgrade()` is a plain `DROP` with no data-preservation step.

Everything else this phase needs already exists.

## 6. APIs

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/leads/export?format=csv\|json\|xlsx` | **`format` defaults to `csv` with the original 13 columns** |
| `GET` | `/api/projects/<id>/export` | Full project bundle: artefacts + leads + analyses |
| `GET` | `/api/analytics/calibration?project_id=` | Deciles vs. `interested` rate |
| `GET` | `/api/analytics/summary` | Runs, leads, cost, conversion over time |
| `PUT` | `/api/projects/<id>/monitoring` | `{enabled, interval_hours}` |
| `GET` | `/health` | Consolidated |
| `GET` | `/health/metrics` | Recent metrics |
| `POST` | `/api/maintenance/run` | Trigger purges manually |

## 7. UI changes

**Export menu** — CSV / JSON / XLSX, honouring every active filter.

**`/analytics/calibration`:**

```
Score calibration · Acme Analytics · 412 leads · 88 triaged

 DECILE   LEADS  CONTACTED  INTERESTED  RATE
 90-100      31         22          14  63.6%  ████████████
 80-89       44         19           9  47.4%  █████████
 70-79       58         14           5  35.7%  ███████
 …
 0-9        102          2           0   0.0%

 A healthy scorer shows a monotonically decreasing rate down the table.
 Yours does. ✓
```

This is the honest-feedback mechanism. A flat curve means the score carries no information, and the
page says so.

**`/health`** — one page: worker liveness, queue depth, proxy pool, DB, schema version, recent runs,
recent errors, LLM spend today.

**Empty and error states** — every list page gets a designed empty state with a next action rather
than a blank table. Every failure surfaces a toast; **the current silent-failure pattern on several
AJAX endpoints is fixed**.

**Monitoring toggle** on the project page: *"Re-run this project every [24] hours and alert me to
new high-confidence leads."*

## 8. AI changes

No new stages. Two refinements:

1. **Tier 2 deep analysis** ships in Phase 7 ([06i §3](06i-feedback-and-memory.md)); this phase adds
   only its **UI affordance** — a per-lead `Deepen` button and the run-page cap indicator. The
   optional `deepseek-v4-pro` model override for Tier 2 is a config flag here, exercising the
   per-stage override the provider abstraction already supports. Tier 2 **never alters a
   confidence score**, so enabling it cannot re-rank a completed run.
2. **Prompt evaluation script** (`scripts/eval_prompts.py`) runs the golden set against two prompt
   versions and prints precision / recall / F1 / hallucination rate / mean tokens, so a prompt
   change ships on evidence.

## 9. Backend changes

### 9.1 Export

| Format | Contents |
|---|---|
| **CSV** | **The original 13 columns first, unchanged**, then 8 appended: `Confidence`, `Intent Stage`, `Pain Points`, `Signals`, `Persona`, `Evidence`, `Suggested Angle`, `Project`. Appending is what keeps existing importers working. |
| JSON | Nested: lead → analysis → breakdown → comments; plus run and project metadata |
| XLSX | Sheet `Leads` (frozen header, autofilter, conditional colour on confidence) + sheet `Summary` (run parameters, counts, cost, pre-filter stats) |

Streaming generators for all three, so a 10,000-row export does not materialise in memory.

### 9.2 Calibration

```python
def calibrate(session, project_id=None) -> CalibrationReport:
    rows = leads_with_status(session, project_id)
    deciles = defaultdict(lambda: {"n": 0, "contacted": 0, "interested": 0})
    for lead in rows:
        if lead.confidence_score is None:
            continue
        d = min(9, int(lead.confidence_score // 10))
        deciles[d]["n"] += 1
        if lead.status in ("contacted", "interested"): deciles[d]["contacted"] += 1
        if lead.status == "interested":                deciles[d]["interested"] += 1
    return CalibrationReport(deciles, monotonic=_is_monotonic(deciles),
                             sample_sufficient=sum(d["contacted"] for d in deciles.values()) >= 30)
```

`sample_sufficient` matters: reporting a calibration curve from 6 triaged leads would be worse than
reporting nothing, and the page says "not enough data yet" instead of drawing a misleading chart.

### 9.3 Scheduled monitoring

```python
def schedule_monitoring():
    for p in due_projects(session):
        if has_active_run(session, p.id):
            continue                          # never stack runs
        run = RunService().create(p.id, p.default_options)
        RunService().skip_to(run, RunState.SCRAPING)   # reuse approved targets; no gates
        p.last_monitored_at = utcnow()
```

Monitoring runs **skip both gates** and reuse the already-approved subreddits and keywords. Asking a
human to re-approve identical targets every 24 hours would guarantee the feature goes unused.

### 9.4 Performance

- Profile the ten most frequent queries with `EXPLAIN QUERY PLAN`; confirm each uses its intended
  index
- `keyword_breakdown()` gets a `LIMIT` and a project filter (the [05 §9](05-database-plan.md)
  anti-pattern)
- `/api/runs/<id>/progress` asserted < 50 ms under a 5,000-job load
- Lead list asserted < 200 ms at 10,000 rows
- `content-visibility: auto` on table rows — one CSS line instead of a virtual-scroll library

### 9.5 Security review

| Check | Method |
|---|---|
| No secret in the repo | `git grep` for the proxy password, `sk-ant`, and known credential shapes |
| No secret in the DB | Schema review + a query across all TEXT columns |
| No secret in logs | Full-run log capture, grepped |
| Log redaction active | Unit test on `RedactingFilter` |
| Flask `debug=False` | Config assertion at startup |
| Secret key from env | No hardcoded fallback |
| No Reddit auth anywhere | Grep for `oauth`, `praw`, `client_secret` |
| Deps clean | `pip-audit` |
| SQL injection | All queries parameterised (SQLAlchemy); no f-string SQL — grep-verified |
| XSS | Jinja autoescaping on; no `|safe` on user or model content — grep-verified |

The `|safe` check matters more than usual here: LLM output is rendered throughout the UI and is
untrusted input by definition.

## 10. Frontend changes

- Export dropdown
- `calibration.html` with the decile chart
- Consolidated `health.html`
- Empty / loading / error partials used across every page
- Toast on every AJAX failure
- Monitoring toggle
- `content-visibility` on long tables
- Keyboard shortcuts: `/` focus search, `j`/`k` navigate rows, `Esc` close drawer

## 11. Risks

| Risk | Mitigation |
|---|---|
| Extended CSV breaks an existing importer | Original 13 columns first and unchanged; new columns appended; header order snapshot-tested |
| XLSX memory blow-up on large exports | `openpyxl` write-only mode + streaming |
| Monitoring runs accumulate cost | Per-project cost cap; skip when a run is active; cost shown on the project page |
| Calibration misleads on a small sample | `sample_sufficient` gate with an explicit "not enough data" state |
| Maintenance purges something needed | Conservative windows (30/90/14 days); dry-run mode; counts logged |
| Final regression misses something | The full Part B suite for **all eight phases** is re-executed against a copy of the live DB |

## 12. Dependencies

**Upstream:** Phases 1–7, all complete and passing.

**New packages:** `openpyxl>=3.1`, `pip-audit` (dev only).

## 13. Acceptance criteria

- [ ] AC1 — CSV export **default output is byte-identical to Phase 0 for legacy leads**
- [ ] AC2 — CSV with AI columns exports correctly for analysed leads
- [ ] AC3 — JSON export validates against its documented schema
- [ ] AC4 — XLSX opens in Excel and LibreOffice with both sheets intact
- [ ] AC5 — Exports honour every active filter
- [ ] AC6 — Calibration renders with sufficient data and shows the insufficient-data state otherwise
- [ ] **AC20 — Labels are cheap to give.** `PUT /api/leads/<id>/label` is reachable from both the list row and the drawer, and writes `lead_labels`
- [ ] **AC21 — ECE and Brier computed** over ≥ 100 labels; below that, both return `insufficient_data` and the page says so rather than showing a number
- [ ] **AC22 — Recalibration preserves ranking.** Applying a fitted `calibration_map` changes displayed confidences but leaves `leads.confidence_score` untouched and the sort order **identical** (asserted)
- [ ] **AC23 — The golden set blocks.** A deliberately degraded prompt version scoring > 0.02 below the reference F1 is **refused**, with the delta reported; the previous version stays active
- [ ] **AC24 — Drift monitors fire.** A synthetically shifted score distribution raises PSI > 0.2 and triggers a golden-set run
- [ ] **AC25 — `hallucinated_span_rate` is real.** Injecting a non-substring evidence span causes the span to be dropped, the lead to survive, and the metric to increment
- [ ] **AC26 — Measurement is nearly free.** Nightly and weekly rollups make **zero** AI calls (`SELECT COUNT(*) FROM ai_calls` unchanged across a rollup)
- [ ] **AC27 — Every red metric has a documented action** rendered on the page, and the ECE action reads *recalibrate*, never *reweight*
- [ ] **AC29 — Cache is not state.** Snapshot every score, `DELETE FROM ai_cache; DELETE FROM http_cache;`, re-score, confirm **every score is identical**
- [ ] **AC30 — Operational purge is lossless where it matters.** `ai_calls` rows are aggregated into monthly totals *before* deletion; the totals survive
- [ ] **AC31 — Patterns are free and group-counted.** The nightly aggregation makes **zero** AI calls; a 40-repost thread contributes `distinct_groups = 1`
- [ ] **AC32 — Below-threshold patterns are inert.** A pattern under the threshold renders greyed with no promote control
- [ ] **AC33 — Researcher view is off by default**, persists per user, and adds no query to the default lead detail
- [ ] **AC28 — Explanations link back.** Every matched slug on the lead detail resolves to its BKB section, including for a lead whose BKB has since been regenerated (version-pinned, not dangling)
- [ ] AC7 — Monitoring creates a run on schedule, skips the gates, and never stacks runs
- [ ] AC8 — Maintenance purges all four targets and logs counts
- [ ] AC9 — `/health` reports every subsystem accurately
- [ ] AC10 — Every page has a designed empty state
- [ ] AC11 — Every AJAX failure produces a visible toast
- [ ] AC12 — Lead list < 200 ms at 10,000 rows; progress < 50 ms at 5,000 jobs
- [ ] AC13 — Full security checklist passes
- [ ] AC14 — `README.md` takes a new operator from clone to first run
- [ ] AC15 — `docs/RUNBOOK.md` covers backup, restore, rollback, and pool expansion
- [ ] AC16 — **All eight phases' Part B suites re-executed and passing**
- [ ] AC17 — 459 legacy leads intact and exportable
- [ ] AC18 — All 17 legacy endpoints unchanged
- [ ] AC19 — The full production readiness checklist in [10 §10](10-implementation-roadmap.md) is ticked

## 14. Completion checklist

- [ ] Revision `0009_monitoring_and_quality` with downgrade, including the five quality tables
- [ ] `src/quality/golden.py` — 100-item set, replay harness, **blocking** release gate
- [ ] `src/quality/calibration.py` — ECE, Brier, reliability bins, isotonic fit; display-time application only
- [ ] `src/quality/drift.py` — PSI, category priors, repair and span rates
- [ ] `src/quality/report.py` — nightly + weekly rollups into `quality_snapshots`, zero API calls
- [ ] `src/knowledge/patterns.py` — nightly aggregation into `patterns`, joined to `dedup_members`
- [ ] `/projects/<id>/patterns` with known / candidate / below-threshold states
- [ ] Label reason chips on the list row and the drawer; routing to `bkb_suggestions`
- [ ] Researcher view toggle, persisted per user
- [ ] Retention policy per memory class, with the cache-is-not-state assertion
- [ ] `lead_labels` capture from list row and drawer
- [ ] `/health/quality` with four bands, drill-through links, and `insufficient_data` handling
- [ ] Red-metric action text rendered from [06g §7](06g-explainability-and-quality.md)
- [ ] Entity links from lead detail into BKB sections, version-pinned
- [ ] `src/export/` with three formats, all streaming
- [ ] CSV column order snapshot-tested against Phase 0
- [ ] Analytics endpoints and page
- [ ] Scheduled monitoring with gate-skip and no-stacking
- [ ] Maintenance job scheduled, with dry-run mode
- [ ] Consolidated `/health`
- [ ] Empty / loading / error states everywhere
- [ ] Toast on every AJAX failure
- [ ] Query profiling; every hot query uses its index
- [ ] `keyword_breakdown` bounded
- [ ] Performance assertions in tests
- [ ] `content-visibility` on long tables
- [ ] Keyboard shortcuts
- [ ] Security checklist executed and recorded
- [ ] `pip-audit` clean
- [ ] `scripts/canary.py` + weekly schedule documented
- [ ] `scripts/eval_prompts.py`
- [ ] Deep re-analysis flag and button
- [ ] `README.md` rewritten
- [ ] `docs/RUNBOOK.md` written
- [ ] All eight Part B suites re-run against a live-DB copy
- [ ] Production readiness checklist fully ticked
- [ ] `docs/testing/phase-08-testing.md` Part A complete
- [ ] `docs/testing/phase-08-testing.md` Part B executed and recorded
