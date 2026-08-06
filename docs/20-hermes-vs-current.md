# 20 — Current System vs. Hermes: Subsystem Comparison

> A disposition for every subsystem in the platform. Research basis:
> [19 — Hermes Research](19-hermes-research.md). The architecture that follows from this table is
> [21 — Hermes Architecture](21-hermes-architecture.md).
>
> **The headline number: of 31 subsystems, 21 are Keep, 6 are Merge, 3 are Add, 1 is Replace, and 0
> are Delete.** That ratio is the finding. Hermes is a genuinely valuable addition to this platform —
> at its edges. It is not a replacement for its middle.

---

## 1. How to read the dispositions

| Disposition | Meaning |
|---|---|
| **Keep** | Unchanged. Hermes has no equivalent, or ours is better-specified for our constraints |
| **Merge** | Both exist; a defined seam is added between them. Neither is discarded |
| **Replace** | Hermes' version supersedes ours |
| **Add** | New capability that only Hermes makes available |
| **Ignore** | Hermes offers it; we decline it, with a reason |

Effort is stated in **engineer-days for one developer**, assuming the existing codebase and test
suite. "Risk" is the risk of *doing it*, not of leaving it alone.

---

## 2. Phase 1–2 shipped code — the baseline that must survive

Before the table: **Phases 1 and 2 are not plans, they are shipped code** —
`src/ai/` at 87% coverage, `src/net/` with 251 passing tests, migrations `0001`–`0003` applied
against a live 459-lead database, an `OpenRouterProvider` added without touching anything outside
`providers/` ([PHASE-01-STATUS](PHASE-01-STATUS.md), [PHASE-02-STATUS](PHASE-02-STATUS.md)).

Any Hermes design that requires rewriting either package is wrong on its face. The comparison below
holds them fixed and asks what Hermes adds *around* them.

---

## 3. The comparison

### 3.1 AI and model access

| # | Current subsystem | Hermes equivalent | Disposition | Risk | Benefit | Difficulty | Effort |
|---|---|---|---|---|---|---|---|
| 1 | **`AIService`** — 4 domain methods, one `_call()` path, cache/dedup/budget/retry/repair/metrics ([06a](06a-ai-service-layer.md)) | `AIAgent.run_conversation()` — a general tool-calling loop | **Keep** | — | Bounded, reproducible, budgeted, cached. None of which the agent loop offers | — | 0 |
| 2 | **`LLMProvider` ABC + provider registry** (DeepSeek, OpenRouter, OpenAI, Fake) | `runtime_provider.py` — 18+ providers, OAuth, credential pools | **Keep, both** | Low | Two provider layers is *correct*: ours is grep-fenced and vendor-neutral by test (AC8); Hermes' serves the agent tier only | Trivial | 0 |
| 3 | **Frozen prefix / `ContextBuilder`** — sorted JSON, 64-token padding, `prefix_hash` drift detection | Tiered system prompt (stable → context → **volatile incl. timestamp**) | **Keep ours; Ignore Hermes' for volume** | **High if confused** | Our prefix is byte-stable by test; Hermes' cannot be ([19 §26](19-hermes-research.md)) | — | 0 |
| 4 | **Three-branch repair ladder** (empty / invalid JSON / schema) | Undocumented retry semantics; `api_max_retries: 3` | **Keep** | — | 401/402 as distinct product states; concurrency halving on 429/503 | — | 0 |
| 5 | **Six-layer cache hierarchy** (L1 website → L5 in-flight guard) | Anthropic-shaped `prompt_caching.cache_ttl` + gateway LRU | **Keep ours; Add Hermes' for the agent tier** | Low | Layers 1–3b prevent the *call*; Hermes' only makes an unavoidable call cheaper | Trivial | 0 |
| 6 | **`CostTracker` + 4 pre-call ceilings** ($2/run, $5/day, 500 calls/run, 2,000 items/run) | **None.** No spend cap exists in Hermes | **Keep + extend to cover the agent tier** | **High** | Closes [19 §40](19-hermes-research.md)'s most serious production gap | Moderate | **3** |
| 7 | **Prompt files, versioned + hash-locked**, `# JSON Shape` test-enforced | `SKILL.md` + `SOUL.md` + `AGENTS.md` | **Merge** | Low | Ours version *classification* prompts; Hermes' version *agent procedures*. Different jobs, both needed | Low | 1 |

**The decisive row is #3.** Everything else in this section follows from it. Our cost model is built
on a prefix that is byte-identical across thousands of calls, verified by a test that raises
`PrefixDriftError` on change. A Hermes turn appends a timestamp block and a growing message array. If
those two mechanisms are allowed to touch, the 50× (DeepSeek-direct) or 5× (OpenRouter) cached-input
discount evaporates silently — and a silent cache miss is
[R2](10-implementation-roadmap.md), rated **Critical**.

### 3.2 Orchestration

| # | Current subsystem | Hermes equivalent | Disposition | Risk | Benefit | Difficulty | Effort |
|---|---|---|---|---|---|---|---|
| 8 | **`runs` state machine** — 11 states, validated transitions, two indefinite human-gate states | **None.** Sessions and cron jobs only ([19 §20](19-hermes-research.md), L1) | **Keep** | — | The gates are *the product* ([01 §3](01-product-vision.md)). Nothing in Hermes can pause a week and resume | — | 0 |
| 9 | **`jobs` queue** — claim-with-lease, jittered backoff, reclaim, per-type `max_attempts` | Cron `executions.db` with PID-fingerprint recovery | **Keep** | — | Ours is a work queue; Hermes' is a scheduler ledger. Different problems | — | 0 |
| 10 | **`Worker`** — single loop, heartbeat, graceful shutdown, sole bulk writer | Gateway daemon + cron tick | **Keep + Merge** | Low | The worker stays the only DB writer. Hermes reaches the platform over HTTP, never the file | Low | 1 |
| 11 | **`scheduler.py`** (`schedule` lib) — per-project monitoring | **`cronjob` / `hermes cron`** — natural-language + cron expressions, skill attachment, 20+ delivery targets, `.tick.lock`, drift guard | **Replace** | **Medium** | Natural-language scheduling, per-job skill attachment, delivery fan-out, and an execution ledger we would otherwise write ourselves | Moderate | **3** |
| 12 | **`run_events`** — append-only user-facing timeline | Session transcript + `display.tool_progress` | **Keep** | — | `run_events` is queryable, correlated to `run_id`, and renders the live progress page | — | 0 |

**#11 is the one genuine Replace in the whole table**, and it is worth stating why it is safe. The
`schedule` library today does one thing: enqueue a monitoring run at an interval. Hermes' cron does
that *and* attaches skills, delivers to Telegram, records an execution ledger, survives restarts with
PID fingerprinting, and takes "every weekday at 9" as an instruction. The migration is small because
the thing being replaced is small.

**The guard that makes it safe:** a Hermes cron job must never *do* the work. It calls
`POST /api/runs` on the platform and returns. The run then executes in our worker, under our state
machine, with our budget ceilings. Cron becomes a trigger, not an executor.

### 3.3 Knowledge and memory

| # | Current subsystem | Hermes equivalent | Disposition | Risk | Benefit | Difficulty | Effort |
|---|---|---|---|---|---|---|---|
| 13 | **Business Knowledge Base** — 23 typed sections, per-section versioning, evidence spans, `origin` guard, staleness policy | **None.** `MEMORY.md` is 2,200 chars ([19 §8](19-hermes-research.md), L2/L3) | **Keep** | — | The BKB is the platform's core asset ([AD-13](03-architecture.md)). Hermes has nothing of this shape | — | 0 |
| 14 | **`EntityRegistry`** — 4-tier resolution, alias generation, entity lifecycle | **None** | **Keep** | — | Deterministic, zero-cost, and the highest-yield matching asset we have | — | 0 |
| 15 | **`SemanticIndex`** — Model2Vec + `sqlite-vec`, optional, degrading | External memory providers (Honcho, Mem0, Hindsight) offering *"semantic search"* | **Keep ours; Ignore Hermes'** | Low | Ours is local, free, versioned, and already designed to degrade. A hosted memory provider adds a network dependency and a second source of truth | — | 0 |
| 16 | **`bkb_suggestions`** — operator-gated knowledge accretion, ≥3 occurrences across ≥2 dedup groups | *"Self-improving"* memory + skill writes, with optional `write_approval` | **Merge** | **Medium** | Hermes' `write_approval: true` is the *same philosophy* we already apply to the BKB. Adopt it for skills and memory; never let Hermes write the BKB directly | Low | 1 |
| 17 | **Four memory classes, one file** (durable / evidence / operational / disposable) | `MEMORY.md`, `USER.md`, `state.db`, cron output | **Merge** | Low | Hermes gains a **fifth class: agent memory**, with its own retention rule ([23 §4](23-hermes-memory-and-knowledge.md)) | Low | 1 |
| 18 | — | **`session_search`** — FTS5 over all past sessions, ~20 ms, **zero LLM cost** | **Add** | Low | Free operator recall of *"what did we decide about r/SaaS last month?"* | Trivial | 0 |

**#16 deserves a note.** Hermes is marketed as *self-improving* — it writes its own skills and
nudges itself to persist memories. That is precisely the property [AD-17](03-architecture.md) and
[R24](10-implementation-roadmap.md) exist to constrain, for the same reason: automatic
self-modification lets one wrong observation become a permanent fact, and the error compounds
invisibly.

Hermes ships the exact control we need — `skills.write_approval: true` and
`memory.write_approval: true`, with staged writes reviewable at `/skills pending` and
`/memory pending`. **Both are enabled in our profile, unconditionally.** The philosophy we already
apply to subreddits, keywords, and knowledge suggestions extends to the agent's own self-modification
without inventing anything.

### 3.4 Collection and processing

| # | Current subsystem | Hermes equivalent | Disposition | Risk | Benefit | Difficulty | Effort |
|---|---|---|---|---|---|---|---|
| 19 | **`src/net/` proxy pool** — rotation, health, leak detection, circuit breaker, per-proxy sessions | `web_search`/`web_extract`; browser backends (Browserbase, Browser Use, CDP) | **Keep** | — | Ours is old.reddit-tuned, credential-safe, and leak-detecting. Hermes' web tools are general-purpose and unproxied | — | 0 |
| 20 | **`RedditClient`** — frozen public API, corrected pagination, block classification | **None** | **Keep** | — | 251 tests. Nothing to gain | — | 0 |
| 21 | **Scrapers** (subreddit / keyword / comment / user) | **None** | **Keep** | — | — | — | 0 |
| 22 | **`src/rules/`, `src/dedupe/`, `src/scoring/prescore`** — deterministic, grep-fenced from `src.ai` | **None**; the model would do it in-context | **Keep, and extend the fence** | **High if breached** | These are the 95%+ cost argument. A grep test must now also forbid Hermes reaching them via a tool that calls a model | Trivial | 1 |
| 23 | **`PreAIGate`** — 11 counted rejection reasons | **None** | **Keep** | — | — | — | 0 |
| 24 | **`AdaptiveBudget`** — knee + floor + marginal + clamps | **None** | **Keep** | — | — | — | 0 |
| 25 | **`ConfidenceScorer`** — deterministic, 11 components, free re-ranking | Model-emitted judgement | **Keep** | **Critical if replaced** | Reproducibility, calibration, explainability. [AD-11](03-architecture.md) | — | 0 |
| 26 | **Holdout audit** — 2% of rejects, gate miss rate | **None** | **Keep** | — | — | — | 0 |

**Section 3.4 is entirely Keep, and that is the most important structural fact in this document.**
The deterministic core — 22 through 26 — is where the platform's cost argument, quality argument, and
explainability argument all live. Hermes touches none of it. The grep fence
([03 §2](03-architecture.md)) gains one clause and is otherwise unchanged.

### 3.5 Interface and operations

| # | Current subsystem | Hermes equivalent | Disposition | Risk | Benefit | Difficulty | Effort |
|---|---|---|---|---|---|---|---|
| 27 | **Flask dashboard** — 17 legacy endpoints + project/run/gate/lead/health pages | Messaging gateway; API server (OpenAI-compatible); web UI | **Keep** | — | The gates, BKB browser, lead triage, and quality dashboards are dense interactive surfaces. Chat is a poor substitute | — | 0 |
| 28 | — | **Telegram via the messaging gateway** — inline buttons, reactions, streaming, rich messages, voice, files | **Add** | **Medium** — auth surface | Alerts and light approvals where the operator already is. `hermes send` makes notifications free | Moderate | **5** |
| 29 | **`/health`, `/health/ai`, `/health/proxies`, `/health/quality`** | `hermes doctor`, `hermes dump`, usage reports, outbound webhooks | **Merge** | Low | Agent-tier spend lands on `/health/ai` beside pipeline spend, via signed webhooks. One page, not two | Low | **2** |
| 30 | **Structured JSON logs with `run_id`/`job_id`/`project_id` + redaction** | `hermes logs`, `display.tool_progress: log` | **Merge** | Low | Correlation IDs cross the boundary explicitly; Hermes' logs are ingested, not replaced ([19 §36](19-hermes-research.md)) | Low | **2** |
| 31 | **Deployment: one process + SQLite, `python main.py dashboard`** | systemd/launchd gateway; 7 terminal backends; `docker-compose.yml` | **Merge** | **Medium** | Two containers on one VPS: platform + gateway. SQLite retained; single-writer discipline preserved by forbidding Hermes DB access | Moderate | **5** |

### 3.6 What Hermes offers that we decline

| Capability | Disposition | Reason |
|---|---|---|
| **Agent-driven pipeline orchestration** | **Ignore** | [02b §2](02b-research-2026-07.md) rejects model-driven orchestration for pipelines whose steps are known in advance. Our steps are known. That reasoning survives Hermes' arrival unchanged |
| **Terminal / file / browser toolsets in the agent** | **Ignore** | The agent reads Reddit text, which is attacker-controlled. Terminal + prompt injection = RCE ([19 §24](19-hermes-research.md), L8) |
| **Skill auto-creation without approval** | **Ignore** | `skills.write_approval: true`. Same reasoning as [R24](10-implementation-roadmap.md) |
| **Micro-compaction** | **Ignore** | *"invalidates cached prefix tokens every turn"*; off by default and stays off |
| **Cloud terminal backends** (Modal, Daytona, Vercel, Singularity) | **Ignore** | We run one VPS. Each backend is a credential, a bill, and a failure mode for capability we do not use |
| **External memory providers** (Honcho, Mem0, …) | **Ignore** | Second source of truth for knowledge the BKB already owns, with a network dependency attached |
| **Batch runner** (`batch_runner.py`) | **Ignore** | It runs the *agent* across many prompts — full loop per prompt. Our enrichment needs one bounded call per 8 items, not one agent per item. Precisely the wrong shape |
| **Voice, TTS, image generation, wake word, browser automation** | **Ignore** | No use case. Each is Level-0 token tax and attack surface |
| **`x_search`, Home Assistant, ACP/IDE, kanban, projects** | **Ignore** | No use case |
| **Nous Portal subscription** | **Ignore** | We have a DeepSeek/OpenRouter key and a working cost model |

**Ten declines, each with a reason.** That ratio is deliberate. Hermes is a large surface, and most
of it is irrelevant to a Reddit lead-intelligence platform. Adopting a framework means adopting the
parts you need and *saying no in writing* to the rest — otherwise the surface grows by accretion and
nobody can later reconstruct why.

---

## 4. Effort summary

| Workstream | Days |
|---|---|
| Agent-tier cost governor (#6) | 3 |
| Scheduler migration to `hermes cron` (#11) | 3 |
| Worker ↔ Hermes HTTP seam (#10) | 1 |
| Prompt/skill versioning conventions (#7) | 1 |
| Skill + memory write-approval wiring (#16) | 1 |
| Fifth memory class + retention (#17) | 1 |
| Grep-fence extension (#22) | 1 |
| Telegram gateway, pairing, notifications, gate approvals (#28) | 5 |
| Health/observability merge (#29) | 2 |
| Log correlation across the boundary (#30) | 2 |
| Docker + VPS deployment (#31) | 5 |
| Custom plugin: platform tools (`src/hermes_plugin/`) | 4 |
| Skills authoring (13 skills, [22](22-hermes-skills.md)) | 5 |
| `AGENTS.md` / `SOUL.md` / context files | 1 |
| Measurement tasks closing the [19 §41](19-hermes-research.md) gaps | 2 |
| Testing, hardening, documentation | 5 |
| **Total** | **≈ 42 engineer-days** |

Phased in [25 — Roadmap](25-hermes-roadmap.md) as **H1–H4**, landing beside the existing Phases 3–8
rather than replacing them.

---

## 5. Migration risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| HR1 | **Hermes becomes a second path to a model**, bypassing `AIService`'s budget, cache, repair, and `ai_calls` ledger | **High if unguarded** | **Critical** | Hermes' own provider key is a *separate* credential with its own ceiling; a webhook records every Hermes turn into `ai_calls` with `stage='agent'`; the pipeline grep fence gains a Hermes clause |
| HR2 | **Agent-tier spend is unbounded** — no cap exists in Hermes ([19 §40](19-hermes-research.md)) | **High** | High | External governor ([24 §7](24-cost-optimization.md)): a `pre_llm_call` plugin hook that reads today's agent spend and blocks above the cap |
| HR3 | **Prompt injection from Reddit content** reaches an agent with tools | Medium | **Critical** | `agent.disabled_toolsets` removes terminal/file/browser/code; Reddit text reaches the agent only as tool *results*, never as instructions; Hermes' own injection scanner covers context files and memory |
| HR4 | **Hermes writes to `leads.db`** and breaks single-writer discipline | Medium | High | Hermes has no filesystem access to the DB; the platform is reachable only over localhost HTTP. Asserted by a test that the container mount is absent |
| HR5 | **v0.20.0 breaking change** on `hermes update` | Medium | Medium | Pin the version in the image; `hermes update` disabled in the container; upgrades are a deliberate, tested deployment |
| HR6 | **Telegram bot token leaked** → third-party control of an agent | Low | **Critical** | Token in `.env` only, never in config or DB; `TELEGRAM_ALLOWED_USERS` set; DM pairing default-deny; the existing `RedactingFilter` gains the token pattern |
| HR7 | **Cron drift** — a job silently inherits a paid model switch | Low | Medium | `cron.model_drift_guard: true` (Hermes default); jobs pin their model explicitly |
| HR8 | **Skill/Level-0 bloat** — bundled skills tax every turn | **High if unmanaged** | Medium | `--no-skills` profile; ≤15 skills; ≤12-word descriptions; measured in H1 |
| HR9 | **Two sources of truth for operator preferences** — `USER.md` vs `settings` | Medium | Low | `USER.md` holds *conversational* preferences only; anything that changes a score or a filter lives in `settings` and is edited in Flask |
| HR10 | **The gates move to Telegram and get rubber-stamped** — a one-tap "approve all" defeats the quality mechanism | Medium | High | Telegram offers *"approve top N"* and *"open in dashboard"*, never *"approve everything"*. Editing remains a dashboard action |

**HR1 and HR2 are the two that would quietly destroy the cost model**, and both are closed by
mechanism rather than by discipline — a separate credential, a recording webhook, and a blocking
hook. That is the same posture as [AD-10a](03-architecture.md): make the wrong thing structurally
impossible rather than procedurally discouraged.

---

## 6. The one-paragraph verdict

Hermes is a strong fit for the three things this platform genuinely lacks — a conversational operator
surface, a real scheduler, and a messaging gateway — and a poor fit for the thing it does best, which
is turning 1,200 Reddit posts into 24 bounded, cached, budgeted API calls. **Adopt it as the operator
and automation tier; keep the pipeline deterministic; put a hard, mechanical boundary between them.**
The next document specifies that boundary.
