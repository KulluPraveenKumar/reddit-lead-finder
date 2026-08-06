# 31 — Execution Plan

> **Parts 2, 9 and 10.** The optimised implementation sequence, the Validation Sprint, and the
> updated roadmap.
>
> Evidence labels: ✅ Verified · ◐ Inferred · ▶ Recommendation · ❓ Unknown.

---

## 1. The ordering principles

▶ Five principles, applied in priority order when they conflict.

| # | Principle | Consequence |
|---|---|---|
| **P1** | **Validate early, integrate late** | Every existential unknown is settled in Sprint 0 with throwaway code. Hermes is *validated* in week 1 and *integrated* in month 3 |
| **P2** | **Real data as early as possible** | The current plan cannot scrape until Phase 6 — 75% through. Collection moves to Sprint 2 using the subreddit list that already exists in `config.yaml` |
| **P3** | **Zero AI until the deterministic funnel is measured** | The gate's cost argument depends on filter rates nobody has measured ([27 A2](27-architecture-review.md)). Sprints 1–3 make no model calls |
| **P4** | **Every sprint ships behind a flag defaulting to the old behaviour** | Rollback is a config flip, not a revert |
| **P5** | **Migrations follow sprint order and are additive** | One linear chain, one head, every revision tested on a copy of the live 459-lead database |

### 1.1 Why the brief's suggested order is not the recommendation

The brief proposes: *Validation → Foundation → Discovery → Qualification → Outreach → Knowledge →
Production Hardening.*

▶ Two problems, one structural:

| Issue | Detail |
|---|---|
| **Knowledge is placed after Outreach** | The BKB is *upstream* of almost everything. Discovery reads the ICP and vocabulary; qualification matches against pain phrasings; outreach retrieves from `outreach_angles`. Knowledge at Sprint 5 would mean building three consumers before the thing they consume |
| **Outreach is a Sprint** | It is one lazy call and one skill ([30 §3.6](30-ai-call-inventory.md)) — a day's work, and mostly a deterministic template. Sizing it as a sprint overstates it |

**Kept from the brief:** Validation first, Foundation second, Production Hardening last. Those are
right.

---

## 2. The recommended order

```
S0  Reality Check          3d   throwaway code · settles 16 unknowns
     │
S1  Orchestration          8d   runs · jobs · worker · events          [0004]
     │
S2  Collection & Alerts    9d   network policy · RSS · watermarks       [0005]
     │                          · Telegram notifications (no Hermes)
     │                          ◄── REAL DATA FLOWING
S3  Local Qualification    8d   rules · dedup · pre-score · comments    [0006]
     │                          ◄── STILL ZERO AI
S4  Knowledge (BKB)       12d   the first AI call                       [0007]
     │
S5  Targeting & Gates      8d   discovery channels · both gates         [0008]
     │
S6  Enrichment & Scoring  12d   adaptive budget · batch · confidence    [0009]
     │                          ◄── THE PRODUCT VISION IS DELIVERED
S7  Agent Tier             8d   Hermes · seam · 3 skills · cron         [none]
     │
S8  Quality & Measurement 10d   golden set · calibration · drift        [0010]
     │
S9  Production Hardening   6d   systemd · backups · runbook · security
                          ────
                          84d
```

| Sprint | Cumulative | What the operator can do at the end |
|---|---:|---|
| S0 | — | Nothing new. **But sixteen assumptions are now facts** |
| S1 | 9% | Start a run from the UI, watch it progress, kill the process and resume |
| **S2** | **20%** | **Collect leads from the existing subreddits at ~1/14th the request volume, and get a Telegram alert when a run finishes** |
| S3 | 30% | See a full funnel with counts and reasons, deterministically scored. Still $0.00 of AI |
| S4 | 45% | Paste a URL, get a browsable 23-section knowledge base |
| S5 | 55% | Full targeting with both human review gates |
| S6 | 72% | **Ranked, explained, adaptively budgeted leads. The vision is delivered** |
| S7 | 82% | Ask questions and approve gates from Telegram |
| S8 | 93% | Know whether the system is still right |
| S9 | 100% | Run it in production, back it up, and recover it |

### 2.1 The three ordering changes that matter

**1. Collection moves from Phase 6 to Sprint 2.** ▶ The single largest debugging improvement
available. Today the plan builds orchestration, knowledge, and targeting — 34% of the project —
before a single new lead is collected. Every defect in those layers is found against fixtures.
`config.yaml` already contains four subreddits and the database holds 459 real leads; there is no
reason to wait.

**2. Hermes moves from H1 (position 4) to Sprint 7 (position 8), but is *validated* in Sprint 0.**
This is P1. The agent tier is the least essential component, the most uncertain (v0.20.0, pre-1.0),
and its skills need leads, quality metrics and a BKB to be useful — none of which exist before
Sprint 6. Validating it in week 1 means a fundamental problem is discovered when it is free to
respond to.

**3. Notifications decouple from Hermes entirely.** [29](29-network-and-proxy-strategy.md) and
[27 §7](27-architecture-review.md) established that `src/notify/` needs a transport interface anyway,
and that a direct Telegram Bot API call is zero-cost *by construction*. So Sprint 2 ships alerts with
`requests` and no agent runtime. ◐ The highest-value, lowest-risk half of the Telegram story lands
six sprints before the highest-risk half.

---

## 3. Part 9 — Sprint 0: Reality Check

> ✅ **EXECUTED 2026-08-05.** Results: [SPRINT-0-MEASUREMENTS.md](SPRINT-0-MEASUREMENTS.md).
>
> | Track | Status |
> |---|---|
> | **A — Reddit transport (U1–U8)** | ✅ **Complete.** Direct 100% / Webshare 71.4%; RSS per-IP at 1 req/60 s; U2, U3, U5, U6 confirmed; **U4 refuted** |
> | **B — Hermes (M-1…M-12)** | ⛔ **BLOCKED** — no `DEEPSEEK_API_KEY`, no `TELEGRAM_BOT_TOKEN`. Gates P23 only; run immediately before it |
> | **C — Provider & environment (V-2…V-5)** | ✅ **Complete.** Prices unchanged; SQLite extension loading works; live DB untouched. **V-1 deferred with Track B** |
>
> Two amendments recorded in [ARCHITECTURE_FREEZE §11](ARCHITECTURE_FREEZE.md): layer L1 deleted
> (U4), multireddit combining made mandatory (U1).

**Purpose.** Convert sixteen assumptions into measurements before any production code depends on
them. Every deliverable is a script under `scripts/probe/` and a row in a results document. **None of
it ships.**

**Estimated time: 3 days. Risk: none — nothing is modified.**

### 3.1 Track A — Reddit transport reality (1 day)

| # | Question | Method | Decides |
|---|---|---|---|
| **U1** | Is the RSS rate limit **per feed or per IP**? | Fetch 5 distinct feeds within 60 s from one IP. All 200 → per-feed. First 200, rest 429 → per-IP | Whether multireddit combining is optional or mandatory ([28 §2.1](28-discovery-redesign.md)) |
| **U2** | Does Atom `<content>` carry **full selftext**? | Fetch a feed; compare `<content>` length to the HTML permalink's body for 10 self-posts | Whether RSS replaces the listing fetch (−66%) or only augments it (−28%) |
| **U3** | Does search RSS support **`subreddit:a OR subreddit:b`**? | `/search.rss?q=(subreddit:saas OR subreddit:startups) AND "attribution"&sort=new&limit=100`; check results span both | 12 search requests versus 120 |
| **U4** | **Conditional GET** — does Reddit return 304? | Fetch, capture `ETag`/`Last-Modified`, refetch with `If-None-Match`/`If-Modified-Since` | Whether an idle poll costs ~0 bytes |
| **U5** | Does `?limit=100` actually return 100? | Count `<entry>` elements | The core density claim |
| **U6** | Does **`old.reddit.com/.rss`** behave as `www`? | Same probes on both hosts | Which host the client targets |
| **U7** | Do RSS and HTML **share a rate budget** on one IP? | Interleave RSS and HTML from one IP; watch for 429 | Whether the two paths can run concurrently |
| **U8** | **Block rate at the reduced volume** | Replay [28 §7.3](28-discovery-redesign.md)'s daily pattern (~28 requests over 6 h) direct, and via the existing pool. Record `ok/blocked` per path | ✅ **Whether to buy proxies at all** ([29 §5.3](29-network-and-proxy-strategy.md)) |

▶ **U8 is the highest-value probe in the entire sprint.** [PHASE-02-STATUS §4.1](PHASE-02-STATUS.md)
measured a 67% block rate from a 36-request burst. The redesigned pattern is an order of magnitude
less dense. If the block rate collapses, the proxy purchase is unnecessary and `fail_closed` becomes
straightforwardly wrong. If it does not, we buy residential bandwidth with evidence.

### 3.2 Track B — Hermes reality (1 day)

The brief's suggested goals, plus the paths [30 §2](30-ai-call-inventory.md) found unbudgeted.

| # | Measurement | Method | Threshold |
|---|---|---|---|
| **M-1** | Tool-schema token cost | `hermes -z --usage-file`, with and without `disabled_toolsets` | Pruning saves ≥30% of system-prompt tokens |
| **M-2** | Level-0 skill metadata cost | Same, 0 skills vs 3 skills | Sets the [22 §8](22-hermes-skills.md) ceiling |
| **M-3** | Baseline turn cost, no tools called | One trivial prompt | Within ±30% of the 9k-in/700-out estimate |
| **M-4** | Does DeepSeek report `prompt_cache_hit_tokens` through Hermes? | Two identical turns; inspect usage | Confirms or refutes the zero-cache-credit assumption |
| **M-5** | **Does `hermes send` cost tokens?** | 10 sends; inspect usage | **Must be exactly 0** |
| **M-6** | Retry/backoff on 429 | Scripted provider error | Fills the [19 §38](19-hermes-research.md) gap |
| **M-7** | `docker compose` bring-up | Run the repo's compose file | ▶ Informational only — [27 §7](27-architecture-review.md) recommends systemd |
| **M-8** | Enumerate bundled skills | `hermes skills browse --source official` | Confirms `--no-skills` is needed |
| **M-9** | Is `hermes send` reachable over `hermes serve` or the API server? | Start `hermes serve`; check `/v1/capabilities`; attempt a send | Notification transport ([29](29-network-and-proxy-strategy.md) T1 vs T3) |
| **M-10** | Does `hermes send` enter the session transcript? | Send, then `session_search` | What T3 costs |
| **M-11** | **Memory background-review frequency** | 10 turns; count model calls beyond the turns themselves | ▶ **If per-turn, disable.** Potentially 45% of agent spend ([30 §2.4](30-ai-call-inventory.md)) |
| **M-12** | Does `skill_manage` auto-creation fire on our turn shapes? | 10 representative turns; watch for staged writes | Whether auto-creation needs disabling |

**Also in Track B — the brief's checklist, end to end:**

- [ ] Install Hermes; create a profile with `--no-skills`
- [ ] Connect DeepSeek (`base_url: https://api.deepseek.com`, model `deepseek-v4-flash`)
- [ ] Author **one** custom skill and confirm it loads and is invocable
- [ ] Register **one** plugin tool that calls a local HTTP endpoint; confirm the round trip
- [ ] Store one memory; restart; confirm it survives and is in the next session's prompt
- [ ] Read one knowledge file via the tool; confirm the content reaches the model
- [ ] Send one Telegram notification; confirm delivery and **zero** token usage
- [ ] Kill the gateway mid-turn; restart; confirm recovery behaviour ✅ documented as a delivery ledger

### 3.3 Track C — Provider and environment reality (1 day)

| # | Question | Method | Decides |
|---|---|---|---|
| **V-1** | **DeepSeek direct vs OpenRouter** | Same 8-item enrichment on both. Record latency, reported cost, `prompt_cache_hit_tokens` | ▶ [27 §6.1](27-architecture-review.md) recommends direct; this is the evidence |
| **V-2** | Model IDs and prices, re-verified | `deepseek.ai/pricing` + API docs | ✅ The table is 8 days old in a market that retired two aliases in 6 days |
| **V-3** | Does `sqlite-vec` load on the target VPS? | `import sqlite_vec; load()` | Whether the semantic tier exists or degrades ([AD-16](03-architecture.md)) |
| **V-4** | Does Model2Vec run in the VPS's memory budget? | Embed 1,000 strings; measure RSS and throughput | Same |
| **V-5** | Baseline posts/day for the 4 configured subreddits | Poll for 24 h; count | ✅ Replaces assumption A1, on which the whole cost model rests |
| **V-6** | Peak-surcharge status | DeepSeek pricing page | `pricing.peak_surcharge.enabled` |

### 3.4 Acceptance criteria

- [ ] **S0-AC1** — All sixteen questions answered and recorded in `docs/SPRINT-0-MEASUREMENTS.md` with method, date, and raw output
- [ ] **S0-AC2** — Each answer states which downstream decision it settles, and which document must change
- [ ] **S0-AC3** — Every conflicting or surprising result is flagged, not smoothed
- [ ] **S0-AC4** — The provider decision (V-1) is made and recorded
- [ ] **S0-AC5** — No file under `src/` is modified; no migration is applied; the live database is untouched
- [ ] **S0-AC6** — A go/no-go is recorded for each of: RSS discovery, direct-first networking, Hermes adoption

**Rollback strategy.** None needed — nothing is changed. ▶ That is the point of a Sprint 0.

**Testing requirements.** Probe scripts are throwaway and untested; their *output* is the artefact.
The one durable test: `scripts/probe/` is excluded from coverage and from the packaged application.

---

## 4. Sprints 1–9

### Sprint 1 — Orchestration Foundation

| Field | Detail |
|---|---|
| **Purpose** | Replace the fire-and-forget thread with a persisted run state machine and durable job queue. Everything after this is a job, and inherits retry, resume and progress for free |
| **Deliverables** | `runs`/`jobs`/`run_events` + `scrape_runs.run_id`; `RunState`/`JobState` with a validated transition table; `JobQueue` with atomic claim-and-lease; `Worker` with heartbeat and graceful shutdown; `RunService`; `POST /api/scrape` as a shim with an **unchanged response shape**; `/runs` and `/runs/<id>`; `maintenance` job. **Scheduling deferred to Sprint 7** |
| **Dependencies** | None (Phases 1–2 shipped) |
| **Migration** | `0004_orchestration` — additive |
| **Acceptance** | [13 §13](13-phase-03.md) AC1–AC15 unchanged, plus: a notification-worthy transition writes exactly one `run_events` row and is idempotent under lease expiry |
| **Rollback** | `WORKER_INPROCESS=false` + `alembic downgrade 0003`. `POST /api/scrape` keeps its legacy code path behind `orchestration.enabled: false` |
| **Time / Risk** | **8 days · Medium** — SQLite writer contention is the known hazard ([R10](10-implementation-roadmap.md)) |
| **Testing** | Claim-race under two workers; lease expiry without duplicate leads; SIGTERM within 30 s; 10-minute concurrent read/write soak with **zero** `database is locked`; 459 leads intact; 17 legacy endpoints byte-identical |

### Sprint 2 — Collection & Alerts ◄ the pivotal sprint

| Field | Detail |
|---|---|
| **Purpose** | Make collection cheap, reliable and observable — and get real leads flowing into the existing database. Deliver Telegram alerts without an agent runtime |
| **Deliverables** | **(a) Network policy** — `NetworkProvider` ABC, `DirectProvider`, `ManagedProxyProvider`, `NetworkPolicy` with per-class egress, `on_pool_exhausted` ladder, target-acceptance health ([29](29-network-and-proxy-strategy.md)). **(b) RSS discovery** — Atom parser, `discovery_watermarks`, change detection, overflow detection, density-adaptive body fetch, adaptive polling policy ([28](28-discovery-redesign.md)). **(c) Notifications** — `src/notify/` with the three-implementation transport; kinds: `run.started`, `run.complete`, `run.failed`, `proxy.pool_degraded`. **(d)** `BaseScraper` refactor; subreddit and keyword scrapers become watermark-driven |
| **Dependencies** | Sprint 1 (jobs); Sprint 0 U1–U8, M-9, M-10 |
| **Migration** | `0005_discovery` — `discovery_watermarks` only |
| **Acceptance** | [28 §11](28-discovery-redesign.md) D-AC1…D-AC12 and [29 §7](29-network-and-proxy-strategy.md) N-AC1…N-AC11, plus: **steady-state daily requests ≤ 80** for the configured subreddits; a Telegram alert arrives within 10 s of run completion at **zero** token cost |
| **Rollback** | `discovery.rss_enabled: false` → the HTML path, which is retained not deleted. `network.policy: proxy_only` → Sprint-1 behaviour. `notify.enabled: false`. `alembic downgrade 0004` |
| **Time / Risk** | **9 days · Medium** — the risk is RSS behaving differently from Sprint 0's probes at sustained volume |
| **Testing** | All 251 `src/net/` tests pass or their change is justified; Atom fixtures with `.expected.json`; watermark overflow fixture (150 new posts); a 200-with-block-page is never cached; RSS and HTML produce identical `Lead` rows for the same `reddit_id`; credentials absent from every log, response and DB column; `src/net/` contains zero Reddit identifiers |

▶ **This sprint is where the plan's biggest change lands, and it is deliberately the one with the
most retained fallbacks.** RSS, the network policy and notifications each have a flag that restores
prior behaviour. A sprint that rewrites the collection layer without a way back would be the single
riskiest step in the project.

### Sprint 3 — Local Qualification

| Field | Detail |
|---|---|
| **Purpose** | Everything deterministic, measured on real data, before a single token is spent |
| **Deliverables** | `src/rules/` (keywords, negatives, structural, authors, competitors); `src/dedupe/` (exact → MinHash → optional semantic); `scoring/prescore.py` with all components persisted; `CommentScraper` ordered by **pre-score**; funnel counts on the run page; **Stage-3 metadata-triage holdout** ([28 §9 D6](28-discovery-redesign.md)) |
| **Dependencies** | Sprint 2 (collected items); Sprint 0 V-3/V-4 |
| **Migration** | `0006_local_pipeline` — `comments`, `dedup_groups`, `dedup_members`, `minhash_bands`, `prescores` (+`stage`), `leads` +4 columns. ◐ `project_id` is **nullable** on the dedup tables, FK added in `0007` — the deferred-FK pattern `ai_calls` already uses |
| **Acceptance** | [16 §13](16-phase-06.md) AC1–AC23, plus: **A2 measured** (hard-filter rate on real data, against the assumed 73%); **A5 measured** (MinHash over 2,000 items < 2 s); `SELECT COUNT(*) FROM ai_calls WHERE run_id=?` = **0** |
| **Rollback** | `pipeline.local_qualification: false` → items keep `intent_score` only. `alembic downgrade 0005` |
| **Time / Risk** | **8 days · Low** — pure computation, fully testable offline |
| **Testing** | Boundary grep: no `src.ai` import in `rules`/`dedupe`/`scoring`; a full run with `AIService` replaced by a provider that raises; group-of-N yields N distinct pre-scores; alias-only competitor mention contributes its component |

▶ **The end of Sprint 3 is the best debugging position in the whole plan.** The entire funnel runs,
every rejection has a counted reason, nothing is probabilistic, and nothing costs money. Every
assumption the AI cost model rests on ([27 §10](27-architecture-review.md) A1, A2, A5) is now
measured rather than assumed.

### Sprint 4 — Knowledge (the Business Knowledge Base)

| Field | Detail |
|---|---|
| **Purpose** | A website URL becomes a persisted, versioned, entity-resolved knowledge base. **The first AI call.** |
| **Deliverables** | As [14](14-phase-04.md), unchanged: `WebsiteFetcher` (**direct egress**, [29 §2](29-network-and-proxy-strategy.md)), local signal extraction, one consolidated `analyze_business()` producing 23 sections with per-section failure isolation, `EntityRegistry`, evidence typing, the `origin` guard, section lifecycle, `SemanticIndex`, `PrefixBuilder`, `/projects` and `/projects/<id>` |
| **Dependencies** | Sprint 1 (worker), Sprint 2 (HTTP client), Sprint 0 V-1/V-2/V-3 |
| **Migration** | `0007_projects_and_knowledge_base` + the deferred FKs from `0002`, `0006` |
| **Acceptance** | [14 §13](14-phase-04.md) AC1–AC30 unchanged |
| **Rollback** | `alembic downgrade 0006`. The BKB is additive — no existing behaviour depends on it yet |
| **Time / Risk** | **12 days · Medium-High** — the largest single AI call; [R21](10-implementation-roadmap.md) (consolidation quality) and [R28](10-implementation-roadmap.md) (origin guard) both live here |
| **Testing** | Exactly one `ai_calls` row per analysis; total < $0.05; re-analysis of an unchanged fingerprint makes **zero** calls; **regenerate every section twice and lose no `reddit_learned` or `operator` row**; every evidence quote is a literal substring; `sqlite-vec` absent → migration completes and `/health` reports `semantic_layer: disabled` |

### Sprint 5 — Targeting & Gates

| Field | Detail |
|---|---|
| **Purpose** | The ICP becomes validated Reddit targets that a human has approved |
| **Deliverables** | Discovery channels 1–4; live validation with recorded rejection reasons; ranking with all five components persisted; deterministic keyword generation from BKB sections (**zero AI**); both gate UIs; run options with a live estimate; **gate notifications via Sprint 2's notifier** |
| **Dependencies** | Sprint 4 (ICP, personas, vocabulary), Sprint 2 (RSS search) |
| **Migration** | `0008_targeting` |
| **Acceptance** | [15 §13](15-phase-05.md) AC1–AC16, plus: a gate notification is delivered exactly once per gate per run at zero token cost |
| **Rollback** | `alembic downgrade 0007`; runs skip straight to `AWAITING_OPTIONS` with a manual subreddit list — **which is exactly what Sprint 2 already supports** |
| **Time / Risk** | **8 days · Low** — no new AI calls; the highest-risk element (hallucinated subreddits) is fully mitigated by live validation |
| **Testing** | ≥70% of proposed subreddits survive validation; a hallucinated name is rejected and shown; the run sits at the gate indefinitely and survives restart; approving with zero selections returns 422 |

### Sprint 6 — Enrichment & Confidence ◄ the vision is delivered

| Field | Detail |
|---|---|
| **Purpose** | Adaptive budget → batched enrichment → holdout audit → hybrid confidence → ten explanation fields |
| **Deliverables** | As [17](17-phase-07.md), plus [24 §4.1–4.2](24-cost-optimization.md) (label-reason rule proposals, cross-project negative reuse with the `bkb_id IS NULL` rule) and **Tier 2 as lazy, not eager** ([30 §3.5](30-ai-call-inventory.md)) |
| **Dependencies** | Sprints 3 (pre-score) and 4 (BKB prefix) |
| **Migration** | `0009_enrichment` — `lead_analysis` (incl. `reused_cross_project`), `gate_audits`, `ai_budgets` |
| **Acceptance** | [17 §13](17-phase-07.md) AC1–AC34, plus [30 §7](30-ai-call-inventory.md) AI-AC5/AI-AC6 |
| **Rollback** | `ai.enabled: false` → leads keep deterministic scores and `has_ai=false`. This path is required behaviour, not a rollback hack ([04 §9.2](04-system-design.md)) |
| **Time / Risk** | **12 days · High** — [R2](10-implementation-roadmap.md) prefix cache, [R3](10-implementation-roadmap.md) attribution, [R18](10-implementation-roadmap.md) batch quality, [R22](10-implementation-roadmap.md) adaptive budget all land together |
| **Testing** | Shuffled-completion attribution (blocking); the five [06f §4](06f-adaptive-budget.md) distributions replayed as fixtures with documented `method`; batch-size sweep at B ∈ {1,4,8,12,16}; gate miss rate < 5%; rescore of 10,000 leads in < 2 s with **zero** API calls; the rendered breakdown reconciles exactly to the stored score ([27 §1.2](27-architecture-review.md)) |

### Sprint 7 — Agent Tier

| Field | Detail |
|---|---|
| **Purpose** | Conversational operator access and real scheduling — bounded, metered, and unable to reach the pipeline |
| **Deliverables** | Hermes installed with the [30 §2.7](30-ai-call-inventory.md) config; `SOUL.md`/`AGENTS.md`; **5 seam tools** (`platform_status`, `list_runs`, `run_detail`, `approve_gate`, `cost_report`); **3 skills** (`reddit-run-control`, `quality-analyst`, `operator-onboarding`); the `pre_llm_call` governor; agent turns → `ai_calls` with `stage='agent.%'`; **`hermes cron` replaces `schedule`**; Telegram conversation and gate approval |
| **Dependencies** | Sprint 6 (data worth discussing), Sprint 0 Track B |
| **Migration** | **None** ([27 §5](27-architecture-review.md)) |
| **Acceptance** | Approving a gate from Telegram produces an identical `runs` transition and `run_events` row; the governor blocks at the cap with **zero** provider calls while notifications keep flowing; every turn appears in `ai_calls`; **no `hermes` import exists in `src/`**; agent spend ≤ $1.00/month |
| **Rollback** | `systemctl stop hermes-gateway`. **Nothing in the pipeline breaks** — this is the acceptance criterion for the whole boundary ([21 §14](21-hermes-architecture.md)). Notifications continue via the direct transport |
| **Time / Risk** | **8 days · Medium** — pre-1.0 dependency; mitigated by Sprint 0 and by the platform having no dependency on it |
| **Testing** | Governor blocks with zero calls; seam requires its bearer token and is not publicly reachable; an injection fixture in lead text produces a report, not an action; `disabled_toolsets` verified at runtime; `test_platform_no_hermes_import` |

### Sprint 8 — Quality & Measurement

| Field | Detail |
|---|---|
| **Purpose** | Know whether the system is still right |
| **Deliverables** | As [18](18-phase-08.md) minus deployment: `lead_labels` with reason chips, `patterns`, researcher view, retention by memory class (incl. the agent class), **golden set as a blocking gate (100 items)**, ECE/Brier/isotonic at display time, PSI drift, `/health/quality`, CSV/JSON/XLSX export, empty and error states, performance work |
| **Dependencies** | Sprint 6 (scored leads), Sprint 7 (agent metrics) |
| **Migration** | `0010_monitoring_and_quality` |
| **Acceptance** | [18 §13](18-phase-08.md) AC1–AC35 minus AC13 (moves to S9), plus: **the golden set is 100 items and the 40-item Sprint-6 set is documented as its precursor** ([27 §1.3](27-architecture-review.md)) |
| **Rollback** | `alembic downgrade 0009`. Purely additive measurement |
| **Time / Risk** | **10 days · Low** — mostly SQL over existing tables, zero AI cost except the golden replay |
| **Testing** | A degraded prompt version scoring > 0.02 below reference is **refused**; recalibration changes displayed values and leaves sort order identical; nightly rollups make **zero** AI calls; `DELETE FROM ai_cache; DELETE FROM http_cache;` changes no score; deleting agent memory changes no score |

### Sprint 9 — Production Hardening

| Field | Detail |
|---|---|
| **Purpose** | Run it, back it up, recover it, and know what to do at 3am |
| **Deliverables** | **systemd units for platform and gateway under two unix users** ([27 §7](27-architecture-review.md) — no Docker); `chmod 0600` on `leads.db` owned by the platform user; Caddy for TLS + basic auth; nightly backup via the SQLite backup API **plus a restore drill**; secret-rotation procedure for all five secrets; disk-space monitoring on `/health`; `operator_timezone`; the canary scheduled; notification backlog policy; degraded-mode decision tree; `RUNBOOK.md`; security review across both planes; CI (lint → offline tests → **three grep fences** → skill lint → migration up/down on a live-DB copy → deploy → smoke) |
| **Dependencies** | All prior sprints |
| **Migration** | None |
| **Acceptance** | Both services start on boot and restart on failure; **the Hermes user cannot read `leads.db`** (asserted by an actual read attempt as that user); a restored backup opens with 459+ leads and renders `GET /`; stopping the gateway breaks nothing; full security checklist passes; `pip-audit` clean |
| **Rollback** | Previous venv retained and symlink-switched; database backup taken before deploy |
| **Time / Risk** | **6 days · Medium** — first real deployment; mitigated by the systemd choice being simpler than the container one |
| **Testing** | Restore drill executed and timed; boot test; permission test; smoke test after deploy; rollback drill |

---

## 5. Migration chain

| Rev | Title | Sprint | Notes |
|---|---|---|---|
| `0001` | `baseline` | ✅ shipped | Stamped on the live DB |
| `0002` | `ai_infrastructure` | ✅ shipped | |
| `0003` | `net_infrastructure` | ✅ shipped | |
| `0004` | `orchestration` | S1 | |
| `0005` | `discovery` | S2 | `discovery_watermarks` |
| `0006` | `local_pipeline` | S3 | `comments`, dedup tables, `prescores`, `leads` +4. **`project_id` nullable**, FK deferred to `0007` |
| `0007` | `projects_and_knowledge_base` | S4 | + deferred FKs from `0002` and `0006` |
| `0008` | `targeting` | S5 | |
| `0009` | `enrichment` | S6 | + `reused_cross_project` |
| `0010` | `monitoring_and_quality` | S8 | |

**Linear, one head, ten revisions.** ◐ The numbering differs from
[05 §7](05-database-plan.md) because the sprint order differs — but **none of `0004`–`0010` has
shipped**, so these are authored in sprint order rather than renumbered. Only `0001`–`0003` are
applied to the live database and none of them moves.

▶ **Hermes adds no migration** ([27 §5](27-architecture-review.md)), which is why the agent tier can
move from position 4 to position 8 without disturbing anything.

---

## 6. Part 10 — Phase review

| Existing phase | Disposition | Becomes | Why |
|---|---|---|---|
| **1 — AI Foundation** | **Keep** | ✅ shipped | Untouched |
| **2 — Proxy & Transport** | **Keep + Modify** | ✅ shipped; extended in **S2** | Provider abstraction added; `fail_closed` replaced by policy ([29 §2.2](29-network-and-proxy-strategy.md)) |
| **3 — Orchestration** | **Modify** | **S1** | Scheduling deferred to S7; notification hook added |
| **4 — Business Knowledge Base** | **Keep + Move** | **S4** | Content unchanged; moves later than the old H1 slot, earlier than targeting |
| **5 — Discovery, Keywords & Gates** | **Split + Move** | **S5** *(targeting)* + **S2** *(collection mechanics)* | Collection no longer waits for targeting; a manual subreddit list is sufficient to start |
| **6 — Scrape & Local Pipeline** | **Split + Move** | **S2** *(collection)* + **S3** *(local qualification)* | Two unrelated concerns in one phase; splitting moves real data six sprints earlier |
| **7 — Adaptive Enrichment** | **Modify** | **S6** | + lazy Tier 2, cross-project reuse rule, label-reason proposals |
| **8 — Quality, Dashboard, Export, Production** | **Split** | **S8** *(quality)* + **S9** *(hardening)* | Quality must not wait for deployment |
| **H1 — Hermes Foundation** | **Merge + Move** | **S0** *(validation)* + **S7** *(integration)* | P1: validate early, integrate late |
| **H2 — Agent Tier** | **Merge + Reduce** | **S7** | 5 tools not 17; 3 skills not 13 |
| **H3 — Operator Intelligence** | **Move** | **Post-S9 backlog** | Needs S6/S8 data; not on the critical path |
| **H4 — Deployment** | **Modify** | **S9** | Docker removed ([27 §7](27-architecture-review.md)) |
| — | **Add** | **S0** | Sprint 0 did not previously exist |
| — | **Add** | **S2** | Network policy + RSS discovery + notifications |
| — | **Remove** | — | **Nothing removed** |

**Summary: 2 Keep · 3 Modify · 4 Split · 2 Merge · 4 Move · 2 Add · 0 Remove.**

---

## 7. Risk register — the sprint-order risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| X1 | **RSS is deprecated or throttled further mid-build** | Low | High | The HTML path is retained, not deleted; `discovery.rss_enabled: false` restores it; the canary detects it daily |
| X2 | **Sprint 0 invalidates the discovery redesign** (U2 and U3 both unfavourable) | Medium | Medium | The pessimistic branch still delivers −64% in steady state. The design does not depend on the optimistic branch |
| X3 | **Sprint 2 destabilises the shipped `src/net/`** | Medium | High | 251 existing tests are the gate; the provider refactor keeps `ProxiedHTTPClient`'s contract and the `session_for` fake seam |
| X4 | **Collecting before targeting fills the DB with off-ICP leads** | Medium | Low | They carry `project_id IS NULL`, exactly like the 459 legacy rows, and are excluded from project views by the existing filter |
| X5 | **Hermes at Sprint 7 means its cost model is unvalidated for months** | Low | Medium | Sprint 0 Track B measures it in week 1; only *integration* is deferred |
| X6 | **Deferring the scheduler to S7 leaves no automation for six sprints** | Medium | Low | The existing `schedule` library keeps working; it is replaced, not removed, in S7 |
| X7 | **Systemd instead of Docker weakens isolation** | Low | Medium | Unix users + `chmod 0600` are stronger than a mount omission, and are asserted by an actual read attempt as the Hermes user |
| X8 | **Sprint 2 is the largest single change** and touches shipped code | Medium | High | Three independent feature flags; the HTML path retained; a full regression against the live-DB copy before merge |

---

## 8. Continuous testing after every milestone

▶ The brief asks for this explicitly. It is achieved by one rule:

> **Every sprint ends with the same regression suite, and it must pass unchanged.**

```
after every sprint:
  ruff check · ruff format --check
  pytest  (offline: FakeProvider, FakeHermes, fake sessions — no network)
  grep fence 1: no `deepseek` outside providers/
  grep fence 2: no `src.ai` in rules|dedupe|scoring|knowledge|feedback
  grep fence 3: no `hermes` import anywhere in src/
  alembic upgrade head && downgrade one && upgrade head   (on a copy of leads.db)
  REGRESSION: 459 leads present · intent_score fingerprint unchanged
            · GET / byte-identical · CSV export 13 columns
            · all 17 legacy endpoints respond identically
  SMOKE: create a run → it reaches a terminal state → the funnel counts render
```

The last line is what makes this *continuous* rather than merely repeated: **from Sprint 2 onward,
every sprint can run a real end-to-end collection and see leads appear.** Before the reorder, that
was impossible until Phase 6.

| Sprint | What the smoke test proves |
|---|---|
| S1 | A run starts, progresses, and completes |
| S2 | Real posts are collected and a Telegram alert arrives |
| S3 | The funnel produces counted rejections and deterministic scores |
| S4 | A URL becomes a 23-section knowledge base |
| S5 | Targets are proposed, validated, and approved by a human |
| S6 | Leads are ranked with explanations that reconcile to their scores |
| S7 | A gate is approved from Telegram |
| S8 | Quality metrics render, and a bad prompt version is refused |
| S9 | The system boots, backs up, and restores |

---

## 9. Summary

| | Before this review | After |
|---|---|---|
| Sequence | 12 phases by document number | **10 sprints by dependency and risk** |
| First real data | Phase 6 (75%) | **Sprint 2 (20%)** |
| First AI call | Phase 4 | **Sprint 4** — after the funnel is measured |
| Hermes validated | H1 (position 4) | **Sprint 0 (week 1)** |
| Hermes integrated | H1–H3 | **Sprint 7** |
| Migrations | 10, with a renumbering | **10, authored in sprint order, no renumbering** |
| Effort | 89 days | **84 days** |
| Docker | 2 containers, registry, CI images | **systemd, 2 unix users** |
| ◐ Monthly AI cost | $0.59 | **$0.34** ([30 §5](30-ai-call-inventory.md)) |
| ◐ Monthly Reddit requests | 11,700 | **944 – 4,479** ([28 §4.4](28-discovery-redesign.md)) |
| Rollback per sprint | Not specified | **A feature flag defaulting to prior behaviour** |
