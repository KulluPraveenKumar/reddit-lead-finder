# 10 — Implementation Roadmap

## 1. Phase overview

DeepSeek is **integrated throughout**, not appended as an AI phase. The AI Service Layer is
foundational infrastructure in Phase 1; every later phase consumes it through domain methods.

| # | Phase | Doc | Testing | Migration | Deliverable | Cumulative |
|---|---|---|---|---|---|---:|
| 1 | **AI Foundation & DeepSeek Integration** | [11](11-phase-01.md) | [P1](testing/phase-01-testing.md) | `0001`–`0002` | AI Service Layer, DeepSeek provider, Settings page, connection test, token/cost tracking, caching, prompt framework | **14%** |
| 2 | Proxy Service & Scraping Transport | [12](12-phase-02.md) | [P2](testing/phase-02-testing.md) | `0003` | Rotating proxies, retries, parser fixes | **24%** |
| 3 | Orchestration: Runs, Jobs, Worker | [13](13-phase-03.md) | [P3](testing/phase-03-testing.md) | `0004` | Persisted state machine + background worker | **34%** |
| 4 | **Business Knowledge Base** — one consolidated call | [14](14-phase-04.md) | [P4](testing/phase-04-testing.md) | `0005` | URL → 23-section BKB + entity registry + semantic index, in a single DeepSeek request | **50%** |
| 5 | Discovery, Keywords & Review Gates | [15](15-phase-05.md) | [P5](testing/phase-05-testing.md) | `0006` | Validation + ranking (**zero AI** — everything read from the BKB), both human gates | **63%** |
| 6 | Scrape Execution, Comments & **Local Pipeline** | [16](16-phase-06.md) | [P6](testing/phase-06-testing.md) | `0007` | Scraping + 3-tier dedup + rule engine + entity resolution + deterministic pre-score | **75%** |
| 7 | **Adaptive, Batched** Enrichment & Explainable Confidence | [17](17-phase-07.md) | [P7](testing/phase-07-testing.md) | `0008` | Adaptive budget → batched enrichment → holdout audit → hybrid scoring → 10 explanation fields | **90%** |
| 8 | Quality, Dashboard, Export & Production Readiness | [18](18-phase-08.md) | [P8](testing/phase-08-testing.md) | `0009` | Golden set, calibration, drift, quality dashboard, exports, monitoring, hardening | **100%** |

### What changed from the pre-DeepSeek plan

| Was | Now | Why |
|---|---|---|
| **AI called on every scraped post** | **Adaptive gate admits ~18%**; the rest resolved locally | AI calls scale with unique high-value candidates, not scraped volume |
| **6 generation calls + 12 keyword calls** | **1 consolidated call** | 19 calls → 1 |
| **1 enrichment call per item** | **Batched, B=8 (measured ceiling)** | 1,000 calls → ~21 |
| No dedup before AI | **Exact hash + MinHash/LSH** grouping | 40 rewordings cost one analysis |
| No measurement of what filtering discards | **Holdout audit → gate miss rate** | Cost optimisation becomes provable, not hopeful |
| P1 proxy, P2 migrations, P4 AI | **P1 AI foundation**, P2 proxy, P3 orchestration | AI is a first-class architectural component, not a mid-project addition |
| AI code scattered across generators | One `AIService` with **4 model-invoking methods** | Business logic must never call a provider |
| Anthropic + Batch API | DeepSeek V4 Flash + bounded concurrency | **DeepSeek has no batch endpoint** |
| `cache_control` breakpoints | Byte-identical frozen prefixes | DeepSeek caching is implicit prefix matching |
| Server-enforced schemas | Client-side Pydantic + 3-branch repair ladder | DeepSeek JSON mode guarantees syntax, not schema |
| API key in `config.yaml` / env | Settings page, Fernet-encrypted in `settings` | Runtime configuration; nothing committed |
| `max_cost_per_run_usd: 5.00` | `2.00`/run, `5.00`/day, **plus a 500-call ceiling** | Two independent dials: cost and call count can diverge |

### 1.1 What the 2026-07-30 research phase invalidated

Five earlier decisions were **wrong, not merely improvable**, and have been corrected at their
source rather than annotated. Full research basis in [02b](02b-research-2026-07.md); this table is
the roadmap consequence of each.

| # | Invalidated assumption | Why it was wrong | Roadmap consequence |
|---|---|---|---|
| 1 | **"Website analysis produces artefacts that downstream stages read."** | The richest artefact in the system was being used once and discarded — the exact weakness identified in both Tydal and RedShip ([02a §3](02a-competitor-analysis.md)). Business understanding is an *asset*, not an intermediate value. | **Phase 4 is rescoped** from "generate artefacts" to "build the Business Knowledge Base." Migration `0005` drops `ai_artifacts` and ships `bkb`, `bkb_sections`, and five entity/link/evidence tables. Phase 5 and Phase 7 both become BKB *consumers* rather than artefact readers. |
| 2 | **"Embeddings require a hosted model or an API, so they are disproportionate"** ([02 §6.10](02-research-findings.md)) | **Factually wrong for static embeddings.** Model2Vec is ~30 MB, CPU-only, 50–100k docs/sec, no API and no per-item cost. The stated objection did not describe the actual technology. The internal-tool framing then removed the remaining objection. | **Phase 4 gains** the semantic index (built from the BKB); **Phase 6 gains** dedup tier 3 and semantic pre-score matching. No new phase — both land inside existing scope. |
| 3 | **"A fixed admission threshold is the cost dial."** | A fixed cut encodes an assumption about the *shape* of the score distribution — and the shape is fully observable before any AI call, so the assumption was never necessary. It discards real leads on steep curves and wastes money on flat ones ([06f §1](06f-adaptive-budget.md)). | **Phase 7's gate is rebuilt** around the adaptive budget: `scoring/budget.py`, `knee.py`, `yield_curve.py`, and the `ai_budgets` table in `0008`. The fixed thresholds survive **only** as the small-`n` fallback. |
| 4 | **"Explainability falls out of storing the score components."** | It nearly does — but "nearly" is not testable. Nothing specified *which* fields exist, where each comes from, or what stops a model inventing a persona. Unspecified explainability is unshippable explainability. | **Phase 7 gains** ten named explanation fields, closed-set slug validation, and verbatim-span checking. **Phase 8 gains** the entity-linked lead detail view. |
| 5 | **"Quality is covered by the holdout audit."** | The audit measures *one* thing — what the gate discarded. It says nothing about calibration, drift, grounding, or whether a prompt change degraded anything. A single metric is not a quality programme. | **Phase 8 is rescoped** from "calibration + monitoring" to a full quality suite: golden set as a *blocking* gate, ECE/Brier, PSI drift, `hallucinated_span_rate`, and `/health/quality`. Five tables added to `0009`. |

**Two of these moved the cost numbers, and both moved them up.** Enrichment now admits ~18% of
collected rather than ~15%, and a 1,000-post run costs ~$0.030 rather than ~$0.026
([06d §2](06d-ai-budget-and-scale.md)). Every figure was **re-derived, not adjusted**.

That direction deserves a sentence, because it looks like a regression against the standing
instruction to minimise calls. It is not. The instruction was *minimise DeepSeek API calls*, and the
binding constraint on it has always been *"cost optimisation must never reduce product quality."*
Adaptive budgeting revealed that the fixed 15% cut was on the wrong side of that constraint on
healthy distributions — it was cheaper because it was discarding leads. **The goal is the fewest
calls that do not lose real leads, not the fewest calls.** The holdout audit is what distinguishes
the two, and it is the only reason we can tell the difference at all.

**No phase was added, and no migration was inserted.** All five corrections land inside the existing
eight phases and the existing nine-revision chain, which remains linear with a single head. That is
a deliberate constraint on this revision: research that forces a ninth phase would be a signal the
original decomposition was wrong, and it was not — the phases were scoped by *capability*, and
capabilities are what deepened.

### 1.2 The final review — one defect, five additions, no new scope

A last architecture pass before implementation ([02c](02c-research-final-review.md)) reviewed eleven
topics and **rejected six of them wholly or in part.** What survived:

| # | Change | Phase | Why |
|---|---|---|---|
| 1 | **Holdout-audited items become real, labellable leads** (`leads.source`) | 6, 7 | **Correctness fix.** The yield curve was fitted only on labels from *admitted* leads, so it would learn the shape of its own gate and narrow every cycle — a degenerate feedback loop that precision could never reveal. The exploration channel already existed; its output was being discarded ([02c §0](02c-research-final-review.md)) |
| 2 | **Version pinning** — `lead_analysis.bkb_id`, `weights_version`, `ruleset_version` | 7 | Makes historical decisions reconstructible, and **makes Phase-8 AC28 satisfiable** — nothing pinned a BKB, so an old lead's links silently resolved to *current* knowledge while still looking correct |
| 3 | **Origin-guarded regeneration** + section staleness | 4 | Regenerating a Group-C section from the website would have deleted months of Reddit-learned knowledge, invisibly. Now structurally impossible ([AD-17](03-architecture.md)) |
| 4 | **Typed evidence + knowledge accretion from Reddit** | 4, 7 | The BKB can learn terminology, competitors, objections and language from aggregate patterns — the mechanism (`bkb_suggestions`) already existed and is widened, not replaced |
| 5 | **Pattern discovery** (`patterns`) and **Tier 2 enrichment** | 8, 7 | Patterns are a `GROUP BY` over data we already label — no clustering, no model. Tier 2 un-batches the top slice, because batching measurably degrades quality and the best leads were getting the weakest analysis |

**No new phase. No new migration.** Every column lands in `0005`, `0007`, `0008`, or `0009` — none
of which has shipped, so the columns go into their `CREATE TABLE` statements rather than arriving as
`ALTER`s. The chain stays linear at nine with one head.

**What was rejected, and stays rejected:** continuous confidence decay, expiring leads, learned
rankers and online training, topic modelling, event sourcing and immutable ledgers, separate
datastores — alongside the earlier rejections of agent frameworks, vector databases, graph
databases, and RAG over raw text. Reasoning for each in [02c](02c-research-final-review.md).

**Most of the plan was re-confirmed rather than revised**, including the local-first funnel, the
adaptive budget mechanism, hybrid confidence, faithful explainability, four-tier entity resolution,
and the calibration approach ([02c §12](02c-research-final-review.md)). This pass was scoped to look
for reasons *not* to add machinery, and mostly found them.

---

## 2. Completion percentage rationale

| After | % | What the operator can actually do |
|---:|---:|---|
| Phase 1 | 14% | Enter a DeepSeek key, test the connection, see live token/cost/cache metrics. The AI platform exists and is observable — but has nothing to analyse yet. |
| Phase 2 | 24% | Run today's scrapers through rotating proxies with correct search pagination. Immediate improvement to the existing product. |
| Phase 3 | 34% | Trigger a run from the UI, watch progress, survive restarts. |
| Phase 4 | 50% | **Paste a URL and get a browsable, versioned Business Knowledge Base** — 23 sections, resolved competitor aliases, evidence spans back to the source page. The first phase that feels like the product, and the phase that produces the asset every later one reads. |
| Phase 5 | 63% | Full targeting with both review gates. The pipeline is complete up to scraping. |
| Phase 6 | 75% | End-to-end: URL → approved targets → posts and comments, deduplicated and pre-scored. |
| Phase 7 | 90% | Adaptively budgeted, AI-enriched, hybrid-scored, **explainable** ranked leads. **The vision is delivered.** |
| Phase 8 | 100% | Production-ready: measured quality, calibration, drift detection, exports, monitoring, documented operations. |

---

## 3. Critical path

```
P1 ──► P2 ──► P3 ──► P4 ──► P5 ──► P6 ──► P7 ──► P8
```

| Edge | Why it cannot be reordered |
|---|---|
| P1 → P2 | Nothing hard — but P1 first makes AI foundational. P2's `proxies` table follows P1's Alembic setup. |
| P2 → P3 | Website crawling (P4) and scraping (P6) both need the proxied client; the worker runs those jobs |
| P3 → P4 | Website intelligence is a multi-minute, multi-stage job needing the worker and state machine |
| P4 → P5 | Discovery consumes the ICP, personas, and vocabulary P4 produces |
| P5 → P6 | Scraping targets are what the gates approve |
| P6 → P7 | Enrichment needs collected posts and comments |
| P7 → P8 | Export and calibration need scores to export and calibrate |

### The one deviation from the literal instruction, stated plainly

The requirement named **Phase 2 = Website Intelligence**. It is Phase 4 here, for two concrete
reasons:

1. Website analysis is a **multi-minute job**: a bounded crawl, local signal extraction, and one
   large AI call with a repair ladder. Running it inside an HTTP request would time out and could
   not be resumed. It needs the worker and run state machine (Phase 3).
2. It **crawls an arbitrary third-party site** that may rate-limit or geo-block. It needs the
   proxied, retrying HTTP client (Phase 2).

Everything else the requirement listed for Phase 1 — AI infrastructure, DeepSeek configuration,
Settings page, provider abstraction, prompt framework, token monitoring, connection testing — is in
Phase 1 exactly as asked.

**What makes that possible:** `create_all()` creates missing tables perfectly well; it only cannot
`ALTER` existing ones. `ai_calls`, `ai_cache`, and `ai_provider_state` are all new, and the API key
lives in the **pre-existing** `settings` table. So the AI layer needs no schema surgery and can land
before the schema work it would otherwise have waited behind.

**Parallelisable within phases:**

| Phase | Track A | Track B |
|---|---|---|
| 1 | Provider + transport + retry ladder | Settings page + credential store |
| 2 | `ProxyManager` + client | HTML fixtures + parser fixes |
| 4 | Website fetcher + extraction | Prompts + schemas |
| 5 | Discovery channels + validator | Gate UI |
| 7 | Enrichment + concurrency pool | `ConfidenceScorer` + lead detail UI |

---

## 4. Recommended implementation order

Strictly 1 → 8. Within a phase: **migration → infrastructure → domain → orchestration wiring → UI →
tests.** Do not start the next phase until the current phase's testing document passes both Part A
and Part B.

Two rules make the ordering non-negotiable:

1. **P1 first** because every subsequent phase's AI work assumes `AIService` exists, and because
   getting the provider boundary right at the start is what prevents DeepSeek specifics leaking into
   later call sites.
2. **Alembic before any `ALTER`.** `create_all()` will not add a column to the live `leads` table.
3. **Local machinery before the gate.** The rule engine, dedup, and pre-score land in Phase 6 —
   *before* `PreAIGate` in Phase 7 — because the gate is meaningless without something deterministic
   to gate on. Building the gate first would force AI-on-everything as an interim state, which is
   the architecture this plan exists to avoid.

### The governing principle

**Never call AI if the task can be completed locally.** Keyword matching, regex, dedup, URL and HTML
parsing, subreddit filtering, age and score arithmetic, author normalisation, sorting, filtering,
ranking, competitor dictionary matching, rule-based scoring, and similarity hashing are all
deterministic — none of them may reach a provider. AI solves only what requires reasoning, and only
after `PreAIGate` admits it. See [06c](06c-local-first-pipeline.md).

---

## 5. High-risk areas

| # | Risk | Likelihood | Impact | Mitigation | Phase |
|---|---|---|---|---|---|
| R1 | **Reddit changes its HTML** — every parser silently returns zero | Medium | Critical | Golden fixtures with field-level assertions; weekly live canary alerting on zero extraction | 2 |
| R2 | **Prompt cache silently stops hitting** → up to **50×** input cost | Medium | **Critical** | `prompt_cache_hit_tokens > 0` asserted from call 2; `prefix_hash` constant per run; loud `run_events` warning; red indicator on `/health/ai`; no volatile data in the prefix (test-enforced) | 1, 7 |
| R3 | **Concurrent result mis-attribution** — enrichment attached to the wrong lead | Low | **Critical** | `futures[fut] → item` mapping, never positional; blocking test with shuffled completion order | 7 |
| R4 | Proxy pool exhausted / ASN blocked | Medium | High | Circuit breaker, per-proxy blacklist, `fail_closed`, visible pool health | 2 |
| R5 | Migration corrupts the live 459-lead database | Low | Critical | Auto timestamped backup via the SQLite backup API; tested `downgrade()`; suite runs on a copy of the real DB | 1 |
| R6 | **DeepSeek JSON mode returns unusable output** (empty / invalid / off-schema) | Medium | High | Three-branch repair ladder; `# JSON Shape` in every prompt; `repair_rate` and `empty_content_rate` metrics with targets | 1, 7 |
| R7 | LLM hallucinates subreddits, slugs, or evidence | High | Medium | Mandatory live subreddit validation; verbatim-substring evidence check; slug allow-list reconciliation; rejected list shown with reasons | 4, 5, 7 |
| R8 | **API key leaked** into a log, an export, or the repo | Low | **Critical** | Fernet at rest; never returned by any API; redaction filter; grep tests over logs, DB, templates, and repo | 1 |
| R9 | **402 insufficient balance mid-run** | Medium | Medium | Own exception and product state; enrichment stops, completed work preserved; amber banner on Settings and `/health` | 1, 7 |
| R10 | SQLite `database is locked` under worker + web | Medium | High | WAL, `busy_timeout=10000`, single-writer discipline, short transactions | 1, 3 |
| R11 | Cost overrun from a runaway loop | Low | Medium | Per-run, per-day **and per-call-count** caps; pre-call budget guard; pre-run estimate with confirmation | 1, 7 |
| R18 | **Batch quality degradation** — attention dilution starves middle items | Medium | High | Batch size is a *measured* ceiling (golden-set sweep at B ∈ {1,4,8,12,16}); id-echo required per element; length mismatch is a batch failure that splits and retries | 7 |
| R19 | **The admission gate silently discards real leads** | Medium | **High** | **Holdout audit**: 2% of rejects enriched anyway, gate miss rate published with `worst_reason`, warning above threshold. The single strongest quality guarantee in the design — and, since the gate became adaptive, the only thing that validates the knee ([06f §5](06f-adaptive-budget.md)) | 7 |
| R20 | Over-aggressive near-dedup merges genuinely different discussions | Low | Medium | Jaccard ≥ 0.85 is conservative; groups are visible in the UI ("similar discussions (3)"); **each lead keeps its own confidence score** | 6, 7 |
| R21 | Consolidated call degrades artefact quality vs. six staged calls | Medium | High | Phase-4 acceptance requires a golden-set comparison against the staged baseline — **consolidation ships only if quality holds** | 4 |
| R22 | **Adaptive budget produces a nonsensical admission count** — Kneedle is unstable on flat or short curves | Medium | High | `n < 200` bypass; min/max clamps at 5%/90% of `n`; `Budget.method` records every binding constraint; acceptance target: clamps bind on **< 10%** of runs. A budget that silently returns 3 of 250 would look like a working cheap run | 7 |
| R23 | **The BKB enrichment prefix grows and dilutes batch attention** | Medium | High | Only the *matching surface* enters the prefix (~3.5k tok); a `prefix_token_budget` is enforced at build time and **drops are logged, never silent**; the golden-set sweep re-runs when the prefix changes. This is the same mechanism as R18 — a bigger prefix lowers the safe batch size | 4, 7 |
| R24 | **Learned BKB suggestions poison the knowledge base** — one mis-scored lead becomes a permanent "fact" | Low | High | Suggestions are **never auto-applied**; every proposal carries its evidence and requires operator acceptance; provenance records `operator-confirmed`. Compounding silent self-modification is the failure mode being designed out | 7, 8 |
| R25 | **`sqlite-vec` unavailable on the host** → migration `0005` fails and the schema is un-installable | Low | Medium | Vector-table creation is wrapped in `try/except`; every consumer degrades to its lexical path; `/health` reports `semantic_layer: disabled` so the degradation is visible rather than silent | 4 |
| R26 | **Calibration "fix" silently re-ranks the lead list** | Low | Medium | Isotonic recalibration is applied at **display time only**; `leads.confidence_score` stays raw; the response to high ECE is explicitly *recalibrate, do not reweight* ([06g §7](06g-explainability-and-quality.md)) | 8 |
| R27 | **Degenerate learning loop** — the yield curve is fitted only on admitted leads, re-confirms its own gate, and recall collapses while precision looks stable | **High if unfixed** | **Critical** | Holdout-audited items become labellable leads (`leads.source`); a test **fails if the fit query filters to admitted leads**; hash sampling asserted uncorrelated with pre-score. Found by research, not by testing — which is why it is here ([02c §0](02c-research-final-review.md)) | 6, 7 |
| R28 | **Regeneration deletes Reddit-learned knowledge** — a Group-C section is rebuilt from the website and months of accretion vanish, invisibly, because the section still looks populated | Medium | **Critical** | `origin` on every content row; regeneration deletes only `origin='website'`; Group-C sections never show a staleness badge; assertion: regenerate everything twice and lose no `reddit_learned` or `operator` row ([AD-17](03-architecture.md)) | 4 |
| R29 | **Knowledge base absorbs noise** — one viral thread's forty reposts manufacture a "pattern" and become permanent business knowledge | Medium | High | Threshold is **distinct dedup groups**, never raw occurrences (≥3 occurrences in ≥2 groups); nothing auto-applies; every proposal shows its contributing leads; below-threshold rows visible but not actionable | 7, 8 |
| R30 | **Explanations drift** — an old lead's entity links resolve to today's knowledge base and confidently cite a definition that did not exist when it was scored | Medium | High | `bkb_id` pinned on every `lead_analysis` row; reproduction guarantee asserted ([AD-19](03-architecture.md)); this is what makes Phase-8 AC28 true rather than aspirational | 7, 8 |
| R31 | **Tier 2 fragments comparability** — deep analysis changes a lead's score, so two leads with identical evidence rank differently depending on which tier ran | Low | High | Tier 2 enriches presentation only and **never touches the confidence score**; capped independently; failure leaves the Tier 1 analysis intact and displayed | 7 |
| R12 | A regression breaks the legacy dashboard | Medium | High | Contract tests replaying all 17 endpoints; rendered-HTML snapshot diff; run after every phase | all |
| R13 | Vendor coupling leaks past the abstraction | Medium | Medium | Grep test: no `deepseek` outside `providers/`; whole AI suite runs on `FakeProvider` | 1+ |
| R14 | Job lease expiry causes duplicate work or double-charging | Medium | Medium | Idempotent handlers; response cache + content-hash dedup mean a retried item is free | 3, 7 |
| R15 | JS-only SPA → thin content → garbage ICP | Medium | Medium | `thin_content` detection, visible warning, reduced confidence, manual editing | 4 |
| R16 | Peak-hour surcharge activates unnoticed, doubling cost | Low | Low | Surcharge-aware estimator shipped disabled; `verified_on` date displayed | 1 |
| R17 | Scope creep into engagement automation | Medium | Medium | Explicit non-goal in [01 §5](01-product-vision.md) — no reply drafting, no posting, no DMs | all |

---

## 6. Technical debt to avoid

| Anti-pattern | Tempting because | Rule |
|---|---|---|
| Calling DeepSeek directly from a handler | "It's one call" | **Everything** goes through `AIService`. Grep-enforced. |
| A model name outside `providers/` | Autocomplete | Model IDs are config, resolved by the provider |
| Putting the API key in `config.yaml` or `.env` | Fastest thing that works | Settings page + encrypted storage, always |
| Returning the key from an API "for the UI" | The form needs a value | Masked fingerprint only. No reveal endpoint. |
| A timestamp or run id in the system prompt | Convenient for debugging | Destroys the 50× cache benefit. Test-enforced. |
| `json.dumps()` without `sort_keys=True` in the prefix | It looks the same | It is not byte-identical, so it does not cache |
| Trusting DeepSeek's JSON | It's called "JSON mode" | Syntax only. Pydantic validates; the ladder repairs. |
| Regexing JSON out of prose | The model wrapped it in fences | Strip fences, parse, validate, repair — in that order |
| Catching bare `Exception` around a provider call | Makes the error go away | Typed classes; 401/402 are product states, not noise |
| Retrying a 402 | It's an HTTP error | Non-retryable. Retrying wastes time and changes nothing. |
| Attributing concurrent results by position | The list is "in order" | `futures[fut]`. Always. |
| Asking the model for the confidence score | One call instead of arithmetic | Forfeits reproducibility, free re-ranking, and calibration |
| **Calling AI for something a regex can do** | It's already in the prompt | Competitor matching, keyword hits, recency, engagement are deterministic. `PreAIGate` and the rule engine exist so this never happens. |
| **Enriching every scraped post** | Simplest control flow | ~85% of collected items are resolved locally. Cost scales with candidates, not volume. |
| **Hardcoding a batch size of 50 or 100** | Round numbers feel efficient | Quality collapses past the measured ceiling. B is a measured value, re-measured on model change. |
| **Accepting a short batch response** | 7 of 8 results looks like partial success | It is silent lead loss. Length mismatch splits and retries. |
| **Reporting a gate saving without a miss rate** | The number looks good | Unmeasured filtering is indistinguishable from quality loss. |
| Rewriting `intent_score` with the new formula | "One score is cleaner" | Frozen. `confidence_score` is a new column. |
| `create_all()` to "add a column" | It appears to work on a fresh DB | Every schema change is an Alembic revision |
| `project_id NOT NULL` with a backfilled legacy project | "Cleaner schema" | Nullable — it is what preserves 459 rows unrewritten |
| Per-row queries in a loop | Easy to write | Batch with `IN`; query counts are asserted |
| Caching a non-200 or block-page response | The cache layer can't tell | Classify before caching |
| Reading `os.environ` outside `settings.py` | One line vs. one import | Single resolution point |
| Skipping golden fixtures because "the parser works" | It does — today | The only defence against R1 |
| Silent AJAX failure | Already the existing pattern | Every failure gets a toast |

---

## 7. Definition of done (every phase)

- [ ] All code implemented and committed
- [ ] `ruff check` and `ruff format --check` pass
- [ ] `pytest` passes; coverage ≥ 70% on new modules (≥ 85% on `src/ai/` and `src/net/`)
- [ ] **No live AI API calls in CI** — the suite runs on `FakeProvider`
- [ ] Alembic upgrade **and** downgrade tested against a copy of the live database
- [ ] **Regression suite passes:** 459 leads present, `GET /` renders, CSV export has 13 columns,
      all 17 legacy endpoints respond identically
- [ ] **Grep tests pass:** no `deepseek` outside `providers/`; no secret in logs, DB, templates, repo
- [ ] `docs/testing/phase-NN-testing.md` Part A fully checked
- [ ] `docs/testing/phase-NN-testing.md` Part B manually executed and recorded
- [ ] New config keys documented in `config.yaml` and `.env.example`
- [ ] `README.md` updated with any new command or setup step

---

## 8. Phase document template

Every `docs/1N-phase-NN.md` uses **these exact headings, in this order**, even when a section is
"None".

```markdown
# Phase NN — <Title>
## 1. Objective
## 2. Scope            (2.1 In scope · 2.2 Out of scope)
## 3. Architecture
## 4. Files affected
## 5. Database changes
## 6. APIs
## 7. UI changes
## 8. AI changes
## 9. Backend changes
## 10. Frontend changes
## 11. Risks
## 12. Dependencies
## 13. Acceptance criteria
## 14. Completion checklist
```

Every `docs/testing/phase-NN-testing.md` uses:

```markdown
## Part A — Claude Verification
(architecture · compilation · lint · imports · typing · edge cases · error handling ·
 security · performance · scalability · logging · retries · regression ·
 existing features · AI: connection · prompts · JSON validation · retry · timeout ·
 cache · duplicate prevention · token usage · cost estimation · fallback)

## Part B — Manual Testing
(per feature: Test Case · Preconditions · Steps · Expected Behaviour ·
 Failure Behaviour · Edge Cases · Success Criteria)
```

---

## 9. Future enhancements

| Idea | Value | Cost | Prerequisite |
|---|---|---|---|
| Second provider (OpenAI / Groq / Together) | Redundancy, price comparison | ~40-line subclass | P1 |
| Provider fallback chain on 402 or outage | Resilience | Policy layer over the registry | P1 |
| Local model (Ollama / vLLM) | Zero marginal cost, full privacy | One provider + hardware | P1 |
| `deepseek-v4-pro` for the top-N leads | Higher-quality deep analysis | Config flag, already designed | P7 |
| Author cross-posting discovery (channel 4) | Finds where a persona really lives | 1 request per author | P5 |
| Headless browser for JS-only sites | Fixes SPA thin content | Playwright + ~300 MB | P4 |
| `a.morecomments` expansion | Deeper comment coverage | 1 request per expansion | P6 |
| Embedding-based subreddit matching | Better semantic discovery | Embeddings API or model hosting | P5 |
| Scheduled monitoring per project | Continuous lead flow | Reuses `schedule` + `runs` | P3 |
| Alerts on high-confidence leads | Closes the loop | Notification service | P7 |
| Multi-user auth + organisations | SaaS-ability | Auth, RBAC, Postgres | P4 |
| Postgres migration | Concurrency, scale | Alembic revisions already portable | P1 |
| Reply drafting | **Explicitly refused** — engagement automation | — | — |

---

## 10. Production readiness checklist

### Functional
- [ ] DeepSeek key entered via Settings; Test Connection passes; status and model shown
- [ ] URL → business profile, industry, competitors, positioning, ICP, personas, pain points,
      buying signals, vocabulary
- [ ] AI subreddit recommendation with 3 discovery channels and live validation
- [ ] Gate 1 with add / remove / edit and rejection reasons visible
- [ ] AI keyword generation with tiers and negative keywords
- [ ] Gate 2 with add / remove / edit
- [ ] Scraping options with live time **and cost** estimate
- [ ] Post scraping via `old.reddit.com` through rotating proxies
- [ ] Comment scraping with score back-fill
- [ ] Per-item enrichment: summary, pain point, category, urgency, buying intent, ICP match,
      persona match, competitor mention, sentiment, opportunity, priority, outreach angle
- [ ] Hybrid confidence score with a visible component breakdown
- [ ] Dashboard with enrichment filters and a lead detail drawer
- [ ] CSV / JSON / XLSX export carrying the AI fields

### AI platform
- [ ] All AI access via `AIService`; grep test confirms no provider name outside `providers/`
- [ ] `FakeProvider` runs the whole suite; **zero live API calls in CI**
- [ ] Prompt cache hit ratio > 85%; alert if it drops
- [ ] Response cache + content-hash dedup: identical content never analysed twice
- [ ] Incremental enrichment: a re-run only analyses new items
- [ ] Repair ladder handles empty / invalid / off-schema; rates within target
- [ ] Per-run and per-day cost caps enforced pre-call
- [ ] Cost estimate shown and confirmed before every run
- [ ] 401 and 402 surfaced as distinct, actionable states
- [ ] Adding a provider requires no change to any business-logic file

### Reliability
- [ ] Proxy rotation, health checks, blacklisting, circuit breaker
- [ ] Exponential backoff with jitter everywhere
- [ ] Adaptive concurrency responds to 429/503 and latency
- [ ] Runs resume after process restart
- [ ] Jobs idempotent under lease expiry
- [ ] Partial failure never loses completed work

### Data
- [ ] All migrations have tested `upgrade` and `downgrade`
- [ ] Automatic backup before every migration
- [ ] 459 legacy leads intact, visible, exportable; `intent_score` unchanged
- [ ] WAL, `busy_timeout`, `foreign_keys=ON` verified on an application connection
- [ ] Retention job for `http_cache`, `jobs`, `run_events`, `metrics`, `ai_calls`

### Security
- [ ] API key encrypted at rest; never in config, logs, exports, templates, or any API response
- [ ] Encryption's threat model stated honestly in the UI
- [ ] `.env`, proxy file, `*.db` gitignored
- [ ] Log redaction filter active and tested
- [ ] No Reddit authentication anywhere
- [ ] Flask `debug=False`; secret key from env with no fallback
- [ ] No `|safe` on any model-generated or user content
- [ ] `pip-audit` clean

### Observability
- [ ] `/health` — worker, queue, proxies, DB, schema version
- [ ] `/health/ai` — cost, tokens, cache-hit ratio, repair rate, latency, concurrency
- [ ] `/health/proxies` — per-proxy stats, credentials redacted
- [ ] Structured logs with `run_id` / `job_id` / `project_id`
- [ ] `run_events` renders as a live activity feed

### Operations
- [ ] `README.md`: install, config, `.env`, proxy file, **DeepSeek key setup**, first run
- [ ] `python main.py migrate` handles fresh and existing databases
- [ ] Graceful shutdown on SIGTERM/SIGINT
- [ ] Documented rollback per phase
- [ ] Weekly HTML-canary check documented

### Quality
- [ ] `ruff` clean
- [ ] Coverage ≥ 70% overall; ≥ 85% on `src/ai/`, `src/net/`, `src/scoring/`, `src/knowledge/`
- [ ] Golden HTML fixtures for every parser path
- [ ] Golden lead set (100 items) wired as a **blocking** gate on prompt and model changes
- [ ] Precision @70, gate miss rate, ECE and Brier published on `/health/quality`
- [ ] Drift monitors live: PSI, category priors, repair rate, `hallucinated_span_rate`
- [ ] Verbatim-span validation enforced; `hallucinated_span_rate` < 2%
- [ ] Adaptive budget: `Budget.method` persisted on 100% of runs; clamps bind on < 10%
- [ ] BKB: every claim carries evidence; suggestions require operator acceptance
- [ ] Boundary greps pass, including `src/knowledge/` and `src/feedback/` not importing `src.ai`
- [ ] **Yield curve fitted on labels from both sides of the admission cut** (R27)
- [ ] **Regenerating every section twice loses no `reddit_learned` or `operator` row** (R28)
- [ ] **`DELETE FROM ai_cache; DELETE FROM http_cache;` changes no lead's score** ([AD-18](03-architecture.md))
- [ ] **Every `lead_analysis` row pins `bkb_id`, `weights_version`, `ruleset_version`** ([AD-19](03-architecture.md))
- [ ] Pattern aggregation and quality rollups make **zero** AI calls
- [ ] All 8 phase testing documents executed and recorded

---

## 11. Why this architecture should remain maintainable for 3–5 years

Not a claim that it will not change — a claim about *how* it will change, and why the changes stay
cheap.

### 11.1 The surface that ages fastest is the smallest

Everything that will certainly change within five years — model, provider, pricing, prompt style,
context limits — is behind **one boundary**: `LLMProvider` and the four domain methods of
`AIService` ([06a](06a-ai-service-layer.md)). A grep test asserts the string `deepseek` appears
nowhere outside `src/ai/providers/`.

DeepSeek V4 Flash will be superseded. When it is, the change is a subclass and a config value, and
the golden set says whether the replacement is better. **Nothing in the rule engine, the knowledge
base, the scorer, or the dashboard knows a vendor exists.** That single boundary is the difference
between a model migration and a rewrite.

### 11.2 The valuable asset is not the code

By month twelve, the code is replaceable and the **Business Knowledge Base is not**: hundreds of
real customer phrasings, a resolved competitor registry with confirmed aliases, calibrated
confidence, and a labelled lead history. All of it in an open, inspectable, plain-SQL schema in one
file.

If the entire application were rewritten, that asset would survive intact, because it is data with
explicit semantics rather than state inside a framework. Systems become unmaintainable when their
value lives in code; this one puts its value in a database whose meaning is documented.

### 11.3 Deterministic core, probabilistic edge

The score is arithmetic. Dedup is hashing. The gate is a curvature calculation. Entity resolution is
three dictionary lookups and an optional vector. **The only probabilistic component is one classifier
call whose output is constrained to closed sets.**

That ratio is what keeps the system debuggable at year three. When a lead looks wrong, the question
*"why?"* has an answer that can be read off stored numbers — not a model interrogation. A codebase
where the non-deterministic surface is small stays reasonable about long after one where it is
everywhere.

### 11.4 Every mechanism has a stated failure response

The dangerous kind of decay is not a bug; it is a system that quietly stops working well while every
dashboard stays green. Three mechanisms exist specifically to make that impossible: the **holdout
audit** (what did the filter discard?), the **golden set** as a blocking release gate (did that
prompt change hurt?), and **calibration** (does 80 still mean 80?). Each has a threshold and a
documented response ([06g §7](06g-explainability-and-quality.md)) decided in advance, not under
pressure.

### 11.5 Complexity was spent deliberately, and refused often

Across three review passes the architecture **rejected**: agent frameworks, vector databases, graph
databases, RAG over raw text, LLM-as-judge, microservices, event sourcing, immutable ledgers,
separate datastores, learned rankers, online training, topic modelling, confidence-decay curves, and
distributed tracing. Each rejection is recorded **with its reasoning**, so the question does not
reopen every time someone reads a blog post.

What remains is one Python process, one SQLite file, one linear migration chain, one AI boundary.
The complexity that was accepted — the knowledge base, the adaptive budget, the quality suite — was
accepted because it is what makes the system get *better* over months, which is the entire point of
an internal research platform.

### 11.6 The honest risks

Maintainability is not guaranteed, and three things would erode it:

| Risk | Early signal | Guard |
|---|---|---|
| **Knowledge-base schema sprawl** — 23 sections becomes 40, each with special handling | Section-specific branches appearing in `PrefixBuilder` or the scorer | Sections are JSON payloads behind one typed interface; only three have special storage, and that is documented ([05 §5.1b](05-database-plan.md)) |
| **Rule-engine accretion** — the negative vocabulary grows to hundreds of hand-tuned terms nobody dares remove | `ruleset_version` incrementing frequently with no measured effect | Every rule's contribution is visible in `prescores`; the holdout audit's `worst_reason` names rules that over-reject |
| **Metric fatigue** — the quality suite becomes wallpaper nobody reads | Red values persisting across weeks | Each metric maps to a stated action, and metrics with no action attached were deliberately excluded ([06g §8](06g-explainability-and-quality.md)) |

The first two are the likeliest. Both are visible in data the system already collects, which is the
best that can be arranged in advance.
