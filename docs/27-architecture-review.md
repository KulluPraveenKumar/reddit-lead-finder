# 27 — Final Architecture Review

> **Part 1 of the pre-implementation review.** Every major decision challenged, including the ones
> made in [19–26](19-hermes-research.md). Nothing here assumes the current plan is correct.
>
> **Evidence labels used throughout this document set:**
>
> | Label | Meaning |
> |---|---|
> | ✅ **Verified** | Stated in a primary source (official docs, or this repository's own recorded measurements) |
> | ◐ **Inferred** | Follows from two or more verified facts; the inference is shown |
> | ▶ **Recommendation** | Engineering judgement. Not documented anywhere. Stated as opinion, with the reasoning |
> | ❓ **Unknown** | Not established. Assigned to a measurement task rather than guessed |

---

## 0. Summary of findings

| # | Finding | Class | Severity |
|---|---|---|---|
| F1 | **Six documented contradictions** between existing documents, one of which contradicts a core architectural principle | ✅ | **High** |
| F2 | **The proxy layer is a net liability as configured** — our own Phase 2 measurements show 2/3 of requests blocked and the local IP performing *better* than the pool | ✅ | **High** |
| F3 | **Reddit RSS collapses the discovery request budget by ~10–25×** and is not mentioned anywhere in the plan | ✅ | **High** |
| F4 | **Hermes makes hidden auxiliary model calls** (title generation, compression) that no budget accounts for | ✅ | **Medium** |
| F5 | **Migration `0005_agent_tier` (proposed in [21 §13](21-hermes-architecture.md)) is unnecessary** — both tables collapse into existing ones | ◐ | **Medium** |
| F6 | **DeepSeek direct vs OpenRouter is still undecided**, and the entire cost model is written against a provider we are not using | ✅ | **Medium** |
| F7 | **Docker/Compose is more machinery than this deployment needs** | ▶ | Medium |
| F8 | **Three scores, three caches, three dedup layers** — each justified individually, never justified together | ▶ | Low |
| F9 | **Eight production concerns are absent** from every document | ▶ | Medium |
| F10 | **The model ID and price table are eight days stale**, in a system whose own research notes that DeepSeek retired two model aliases six days before that research was written | ✅ | **Medium** |

Five of the ten are fixed by decisions in this review; five become Sprint 0 measurements
([31](31-execution-plan.md)).

---

## 1. Documented contradictions — F1

These are not ambiguities. They are places where two documents state incompatible things, and an
implementer following either one would be correct and would produce different software.

### 1.1 The confidence-score weights differ between two documents ✅

[04 §9.1](04-system-design.md) specifies **eleven** components:

```
intent 0.22 · pain_match 0.14 · signals 0.12 · icp_match 0.10 · persona 0.07
urgency 0.05 · ai_opinion 0.05 · keyword 0.10 · subreddit 0.03
engagement 0.05 · recency 0.07                                    = 1.00
```

[09 §3.8](09-dashboard-plan.md)'s worked lead-detail example shows **eight**, with different weights:

```
Intent 0.28 · Pain 0.20 · Signals 0.16 · Keyword 0.12 · Persona 0.10
Recency 0.06 · Engagement 0.05 · Subreddit 0.03                    = 1.00
```

**→ Fix:** [04 §9.1](04-system-design.md) is authoritative — it is the specification;
[09 §3.8](09-dashboard-plan.md) is an illustration. Regenerate the illustration from the real weights.
A worked example that does not reconcile to the spec is worse than no example, because it will be
copied.

### 1.2 [09 §3.8](09-dashboard-plan.md) contradicts AD-11 and AD-15 ✅ — **the serious one**

The same worked example ends:

```
                                       ───────────
                                            82.6 → 92 (signal boost)
```

There is no "signal boost" in [04 §9](04-system-design.md). The score is
`100 × Σ(weight × component)`, then multiplied by a penalty factor. Nothing adds 9.4 points.

This matters more than a wrong number. [AD-15](03-architecture.md) states that explanations are
*"renderings of the computation, never generated about it"*, and
[06g §1](06g-explainability-and-quality.md) says the breakdown *"cannot diverge from the computation,
because it **is** the computation, rendered."* A displayed breakdown whose components do not sum to
the displayed score is precisely the failure those decisions exist to prevent — and it is currently
sitting in the design document as the reference rendering.

**→ Fix:** remove the boost line; the example must sum exactly. Add an acceptance criterion to
Phase 7: *the rendered breakdown reconciles to `leads.confidence_score` within rounding, asserted on
every lead in a fixture set.* (Phase 7 AC4 says "within rounding" but does not test the renderer's
own arithmetic against the stored total.)

### 1.3 The golden set is 40 items in one phase and 100 in another ✅

| Source | Size |
|---|---|
| [06 §9](06-ai-pipeline.md) | *"40 hand-labelled items in `tests/fixtures/golden_leads.jsonl`"* |
| [17 §4](17-phase-07.md) | *"40 hand-labelled items"*; AC17 measures precision/recall on it |
| [06g §4.4](06g-explainability-and-quality.md) | *"100 items, hand-labelled once"* |
| [18](18-phase-08.md), [10 §10](10-implementation-roadmap.md) | *"Golden set (100 items)"* |

◐ The likely intent is 40 in Phase 7 for the batch-size sweep, expanded to 100 in Phase 8 as the
blocking release gate. **That is never stated**, so an implementer reading Phase 7 builds a 40-item
set and Phase 8's blocking gate silently runs on an under-powered sample.

**→ Fix:** state the expansion explicitly in both places, and note that the B-sweep and the release
gate are different instruments with different power requirements.

### 1.4 Cost figures drift between documents ✅

| Claim | Source |
|---|---|
| 1,000 collected → **~21 calls, $0.023** | [06 §10](06-ai-pipeline.md) |
| 1,000 collected → **~24 calls, $0.030** | [06d §2.1](06d-ai-budget-and-scale.md), [README](README.md) |
| *"~1 call per 42 collected posts"* | [README](README.md) |
| *"~1 call per 45 posts"* | [06d §2](06d-ai-budget-and-scale.md) |
| *"~1 call per 48 collected posts"* | [03 AD-10a](03-architecture.md) |

The [06d](06d-ai-budget-and-scale.md) figures are the re-derived ones (post-adaptive-budget); the
others are pre-reversal residue.

**→ Fix:** [06d](06d-ai-budget-and-scale.md) is the single source for every cost and call figure.
Every other document cites it rather than restating it. ▶ **Recommendation:** in a document set this
size, a number repeated in five places is a number that will be wrong in four of them.

### 1.5 `ai_artifacts` survives in Phase 4's code sample ✅

[14 §9.2](14-phase-04.md) shows `save_artifact()` writing to `AIArtifact`. But
[05 §5.1](05-database-plan.md) states plainly: *"`0005` never ships `ai_artifacts`, so there is no
data to migrate — the table is removed from the plan, not deprecated in it."*

**→ Fix:** replace the [14 §9.2](14-phase-04.md) sample with the `bkb` / `bkb_sections` supersede
logic it was meant to become.

### 1.6 Phase 2's testing document does not exist ✅

[README](README.md) links `testing/phase-02-testing.md` and counts 18 manual tests from it.
[12 §14](12-phase-02.md) states it was *"superseded by `docs/PHASE-02-STATUS.md` §5"*. The file
exists on disk but is not the executed artefact.

**→ Fix:** cosmetic, but the README's "129 manual tests" total is now unverifiable. Either restore
the count or state which suites were superseded.

---

## 2. F2 — The proxy layer is currently a net liability

This is the most consequential challenge in this review, and the evidence is our own.

### 2.1 What Phase 2 actually measured ✅

From [PHASE-02-STATUS §3.1](PHASE-02-STATUS.md):

> "Every one of the 10 proxies got HTTP 403 from `old.reddit.com` — **and so did the local IP**. That
> ruled out the proxies immediately… The cause was header incoherence."

From [PHASE-02-STATUS §4.1](PHASE-02-STATUS.md), after the header fix:

```
requests=36  ok=12  failed=24  blocked=24  cache_hits=0  p95=3182ms
pool: healthy=2  degraded=0  blacklisted=8  untested=0 / 10
```

> "**Two thirds of requests were blocked, and 8 of 10 proxies ended blacklisted.** … `old.reddit.com`
> blocks these datacenter proxies aggressively. Residential proxies would change the number; nothing
> in this codebase will."

And from [00 §3](00-current-state.md), the original unproxied probe:

> `GET old.reddit.com/r/SaaS/new/` → **200**, 192,655 bytes, 25 posts.

### 2.2 The conclusion the documents do not draw ◐

Three facts sit together and are never combined:

1. The **local IP works** with coherent headers — verified twice, in [00 §3](00-current-state.md) and
   implicitly in [PHASE-02-STATUS §3.1](PHASE-02-STATUS.md).
2. The **Webshare datacenter pool is blocked ~67% of the time**, and 80% of it ends blacklisted after
   36 requests.
3. [08 §7](08-proxy-service.md) sets `fail_closed: true` — *"refuse to start if 0 healthy proxies"* —
   and [07 §1](07-scraping-pipeline.md) requires *"All traffic via rotating proxy"* with
   `RedditClient` having **no direct `requests` access**.

**◐ Therefore: the current architecture mandates the slower, less reliable path and forbids the
faster, more reliable one.** A run that would succeed direct fails or truncates behind the pool —
[PHASE-02-STATUS §4.1](PHASE-02-STATUS.md) records that *"pagination stopped early on 3 of the 4
subreddits."*

### 2.3 What the proxy layer is actually for

The requirement in [07 §1](07-scraping-pipeline.md) conflates two different goals:

| Goal | Served by proxies? |
|---|---|
| **Not exposing the operator's residential IP to Reddit at volume** | Yes — this is the real goal |
| **Achieving throughput** | **No.** Datacenter proxies reduce throughput here |
| **Avoiding a licensing dependency** | No — that is D1 (no API/OAuth), independent of proxies |
| **Surviving a single-IP block** | Partially — but the pool blocks faster than the single IP did |

▶ **Recommendation:** keep the *goal*, replace the *mandate*. The network layer becomes a
**policy** with pluggable providers rather than a hard requirement that one specific provider always
be used. Full design in [29](29-network-and-proxy-strategy.md).

▶ The blunt version: **10 free-tier datacenter proxies are worse than no proxies for
`old.reddit.com`, and our own test run proves it.** The honest choices are (a) direct with strict
rate limiting, (b) residential proxies at ~$1.75–3.50/GB, or (c) RSS-first collection that reduces
request volume so far that a single IP is comfortably within limits. [28](28-discovery-redesign.md)
argues for (c), with (b) available when volume grows.

---

## 3. F3 — Reddit RSS is missing from the plan entirely

✅ **Verified from third-party sources** (not yet from a live probe — that is a Sprint 0 task):

| Fact | Source |
|---|---|
| `.rss` appended to any subreddit, user, search or multireddit URL returns an **Atom 1.0** feed | wprssaggregator, Miessler |
| `?limit=` is honoured, **default 25, maximum 100** | wprssaggregator |
| **Multireddit syntax works**: `/r/a+b+c/.rss` returns a merged feed | wprssaggregator |
| **Search RSS works**: `/r/{sub}/search.rss?q=...&restrict_sr=1&sort=new` | wprssaggregator |
| Public `.rss` endpoints **survived the 2023 API changes** | Miessler |
| Since **2025-06-11**, RSS is rate-limited from ~100 req/10 min to **~1 req/min**, returning 429 with `x-ratelimit-used/remaining/reset` | lapcatsoftware, LavX |
| The known workaround uses `user=` and `feed=` parameters from a **logged-in account's** RSS preferences | lapcatsoftware |

❓ **Unknown and material:** whether the 1/min limit is **per feed** or **per IP**. LavX states *"per
feed"*; lapcatsoftware's own observation — *"only the first request in each batch works, then the
others fail"* — reads as **per IP**. The sources conflict. [28 §3](28-discovery-redesign.md) designs
for the pessimistic (per-IP) case, which also works if the optimistic case is true.

❓ Also unknown: whether `old.reddit.com/.rss` behaves identically to `www.reddit.com/.rss`, and
whether RSS and HTML share a rate-limit budget on the same IP.

**The `user=`/`feed=` workaround is rejected outright.** It requires a Reddit account, and D1
([02 §1.1](02-research-findings.md)) forbids any Reddit authentication — the constraint that exists
because a licensing decision terminated the category leader. A workaround that reintroduces an
account dependency trades the platform's single strategic advantage for a rate limit.

### 3.1 Why this changes the architecture

| | HTML listing | RSS |
|---|---|---|
| Items per request | **25** | **100** |
| Subreddits per request | 1 | **Unlimited** (`r/a+b+c+…`) |
| Bytes per request | ~190 KB | ~20–40 KB ◐ |
| Contains score / comment count / body | ✅ | ❌ title + snippet + link only |
| Parse fragility | High — CSS classes ([R1](10-implementation-roadmap.md)) | **Low — Atom is a stable schema** |
| ToS posture | Scraping a rendered page | **Consuming a published feed** |

◐ **12 subreddits, newest 100 posts each: 48 HTML requests versus 1–12 RSS requests.** And because
RSS carries no score or body, it is *metadata-only discovery* — exactly the layer
[28 §4](28-discovery-redesign.md) needs before deciding which posts are worth an HTML fetch.

**The parse-fragility row deserves separate emphasis.** [R1](10-implementation-roadmap.md) —
*"Reddit changes its HTML, every parser silently returns zero"* — is rated **Critical** and is
mitigated only by golden fixtures and a weekly canary. Atom is a versioned, machine-readable format
with a stable schema. Moving discovery onto RSS does not eliminate R1 (enrichment still parses HTML)
but it removes the *highest-frequency* path from it.

---

## 4. F4 — Hermes makes AI calls nothing has budgeted

✅ **Verified** from the Hermes configuration reference ([19 §"Auxiliary Models"](19-hermes-research.md)):

```yaml
auxiliary:
  title_generation:
    enabled: true          # ← DEFAULT ON
  compression:
    provider: "auto"
  vision:  { ... }
  web_extract: { ... }
approvals:
  mode: smart              # ← "an auxiliary LLM assesses risk"
```

Four hidden call paths, none of which appears in [21 §6.5](21-hermes-architecture.md) or
[24 §5](24-cost-optimization.md):

| Path | When it fires | ◐ Impact |
|---|---|---|
| **`title_generation`** | Once per session | With per-chat sessions and a 24 h idle reset, this is ~1 extra call per conversation *and per cron job*. On ~50 sessions/month that is a 15–20% uplift on agent-tier calls |
| **`compression`** | At 50% of the context limit | Rare given our short turns, but it is a *large* call — it summarises the whole history |
| **`approvals: smart`** | Before a risky terminal command | Moot once `terminal` is disabled (AD-23), but the config default would still route through an auxiliary model if the toolset were ever re-enabled |
| **`web_extract` / `vision`** | Only if those toolsets are enabled | Disabled by AD-23 |

**→ Fix, all configuration:**

```yaml
auxiliary:
  title_generation:
    enabled: false          # sessions are identified by run/chat id, not a generated title
compression:
  enabled: true
  threshold: 0.50           # rarely reached; keep as a safety valve
approvals:
  mode: off                 # no terminal, no file writes, nothing to approve (AD-23)
```

▶ **Recommendation:** the general lesson is that adopting a framework means adopting its *defaults*,
and a framework designed for open-ended assistant work has defaults tuned for pleasantness rather
than for a metered budget. Sprint 0 must diff the effective config against the documented defaults
and account for every model-invoking path found.

---

## 5. F5 — Migration `0005_agent_tier` is unnecessary

Last turn I specified `agent_events` and `notification_log` as a new migration, then had to renumber
`0005`–`0009` to make the ordering legal ([21 §13.1](21-hermes-architecture.md)). Reviewing that
decision rather than defending it:

### 5.1 `agent_events` duplicates `ai_calls`

[05 §5.4a](05-database-plan.md)'s `ai_calls` already has every column an agent turn needs:

| `agent_events` column | `ai_calls` equivalent |
|---|---|
| `event_type`, `skill` | `stage` — e.g. `agent.chat`, `agent.report`, `agent.outreach` |
| `run_id`, `project_id` | Present |
| `input_tokens`, `output_tokens` | `input_tokens_uncached`, `output_tokens` |
| `cost_usd`, `latency_ms`, `outcome` | Present |
| `session_id` | ◐ `error` is free text; add nothing — session id goes in a `stage` suffix or is dropped |

**→ Decision: agent turns are written to `ai_calls` with a `stage` prefix of `agent.`.** Benefits
beyond removing a table:

- `/health/ai` shows **one** spend figure, which was [21 §10](21-hermes-architecture.md)'s stated
  goal, without a union query.
- Retention, monthly aggregation, and the purge-after-aggregation rule
  ([06i §4.2](06i-feedback-and-memory.md)) apply unchanged.
- The daily-cap seeding logic that Phase 1 already fixed
  ([PHASE-01-STATUS bug 2](PHASE-01-STATUS.md)) works for the agent tier for free.

**One required change, and it is a real one:** every existing query that computes *calls per 1,000
collected posts* or *pipeline cost* must add `WHERE stage NOT LIKE 'agent.%'`. That is a
one-line filter in `AICallRepository` plus a test asserting an agent row does not move the
efficiency metric. Without it, the platform's headline efficiency number silently degrades as
conversation increases — an error that would look like a scraping regression.

### 5.2 `notification_log` is not needed in H1

Its only load-bearing job is idempotency ([21 §13](21-hermes-architecture.md)'s
`ux_notification_dedup`). But ◐ **the state machine already provides it for the events that matter**:
`gate.reached` fires on the transition into `AWAITING_SUBREDDIT_REVIEW`, and
[04 §1.2](04-system-design.md)'s `assert_transition` makes that transition occur exactly once. A
re-run of a job cannot re-enter a state it has left.

The events that *are not* transition-guarded are `lead.high_confidence` (per-lead) and
`budget.warning` (per-threshold-crossing). Both can dedup against `run_events` with a query, since
there is exactly one worker and the emission happens inside the transition's transaction.

**→ Decision: H1 uses `run_events` with query-based dedup. A `notifications` table, if it is ever
needed, ships inside Phase 8's revision.**

### 5.3 The consequence

> **Hermes adds zero migrations.** The `0005`–`0009` renumbering proposed in
> [21 §13.1](21-hermes-architecture.md) is withdrawn. The chain is untouched by the agent tier.

▶ That is a strictly better outcome and it was available last turn. The lesson worth recording: a
new tier's instinct is to bring its own tables, and the review question that catches it is *"which
existing table already has these columns?"* — asked before the DDL is written, not after.

---

## 6. F6 and F10 — two open decisions blocking the cost model

### 6.1 DeepSeek direct vs OpenRouter ✅ still undecided

[PHASE-01-STATUS](PHASE-01-STATUS.md) recorded three findings and a recommendation that has not been
actioned:

| | DeepSeek direct | OpenRouter (what is running) |
|---|---|---|
| Cached input | $0.0028/M — **50×** differential | $0.028/M — **5×** differential |
| Cache telemetry | `prompt_cache_hit_tokens` reported | **Not populated** — shows 0% |
| Measured latency | Unmeasured | **12.8 s** mean per enrichment call |

Consequences that are live today:

- **[06d](06d-ai-budget-and-scale.md) is written against DeepSeek direct.** Every figure in it, and
  therefore in [24 §7](24-cost-optimization.md), assumes the 50× differential.
- **[06b §1](06b-deepseek-optimization.md)'s central claim** — *"a cache miss on the shared prefix
  costs 50× a hit. Prefix stability is not an optimisation; it is the cost model"* — is 10× weaker on
  the gateway. Prefix engineering is still worth doing; it is no longer the dominant lever.
- **[06b §6](06b-deepseek-optimization.md)'s throughput target** (1,000 collected in under 2 min) is
  unreachable at 12.8 s/call without far more concurrency.
- **`/health/ai` will show a red cache-hit ratio that is not a fault** — the exact
  false-alarm-versus-emergency confusion [22 §4.6](22-hermes-skills.md) warns about.

▶ **Recommendation: decide in Sprint 0, and decide for DeepSeek direct**, on three grounds — the 10×
cheaper cached input on the platform's highest-volume path, working cache telemetry (without which
[R2](10-implementation-roadmap.md), a Critical risk, is unmonitorable), and probable lower latency.
Keep `OpenRouterProvider` registered as the failover, which is what the provider abstraction was
built for.

### 6.2 The price table and model ID are stale ✅

[02 §6.2](02-research-findings.md) verified pricing on **2026-07-30** and notes, in the same section,
that *"the legacy `deepseek-chat` and `deepseek-reasoner` aliases were retired on 2026-07-24, six
days before this document was written — a reminder that vendor identifiers move."*

That was eight days ago. The document's own argument applies to itself.

Separately, ✅ the DeepSeek Hermes integration guide recommends **`deepseek-v4-pro`**, while
[D30](02-research-findings.md) standardises the platform on **`deepseek-v4-flash`**.
[24 §5.2](24-cost-optimization.md) resolves this in favour of flash — correctly — but the divergence
should be recorded as a deliberate deviation from vendor guidance rather than left implicit.

**→ Sprint 0 task:** re-verify model IDs, context window, max output, and all three token prices
against `deepseek.ai/pricing` and the API docs; update `pricing.verified_on`; confirm the
peak-surcharge status.

---

## 7. F7 — Docker and Compose are more machinery than this needs

[21 §8](21-hermes-architecture.md) specifies two containers, a Compose file, an image registry, and a
CI deploy pipeline. Reviewing that against what it buys:

| Property claimed | Delivered by Docker? | ▶ Simpler alternative |
|---|---|---|
| Hermes cannot open `leads.db` ([HR4](20-hermes-vs-current.md)) | Yes, by omitting a mount | **Unix file permissions.** Run the two processes as different users; `chmod 0600 data/leads.db` owned by the platform user. Stronger, because it also survives a misconfigured mount |
| Reproducible Hermes version ([HR5](20-hermes-vs-current.md)) | Yes, by image pinning | `pip install hermes-agent==0.20.0` in a dedicated venv, plus disabling `hermes update` |
| Process supervision | Via `restart: unless-stopped` | **systemd** — which Hermes already generates for its gateway (`hermes gateway install --system`) ✅ |
| Dependency isolation | Yes | Two venvs |
| Portability | Yes | Not a requirement — one operator, one VPS |

▶ **Recommendation: drop Docker from the critical path.** Deploy both processes as systemd units
under two unix users on one VPS. This removes an image build, a registry, image pinning, a Compose
file, and a container-networking hop between the planes — and it uses the deployment mechanism
Hermes itself documents.

**What is given up, honestly:** a clean rollback story (a container image tag is easier to revert
than a venv), and reproducible dependency resolution. Both are addressable — `pip freeze` into a
lockfile and a timestamped venv directory — but they are genuinely simpler in Docker.

**The trigger to revisit:** a second host, or a second operator, or any need to run the platform
somewhere other than this VPS. Recorded so this is a decision rather than an omission.

---

## 8. F8 — Complexity that is individually justified and collectively unexamined

### 8.1 Three scores

| Score | Written by | Meaning | Why it exists |
|---|---|---|---|
| `leads.intent_score` | `LeadScorer` (legacy) | Keyword-weighted relevance | Frozen to keep the 459 legacy leads valid ([AD-4](03-architecture.md)) |
| `prescores.total` | `scoring/prescore.py` | Deterministic 0–100 recall instrument | The admission gate's input ([06c §3.1](06c-local-first-pipeline.md)) |
| `leads.confidence_score` | `ConfidenceScorer` | The 0–100 output | The product |

▶ Each is defensible. But **nowhere does a single document explain all three together**, and an
implementer will reasonably ask why a lead has three numbers and which one to sort by. Worse,
`prescore` and `intent_score` overlap substantially — both weight keyword hits, recency, and
engagement.

▶ **Recommendation:** add a short section to [04](04-system-design.md) — *"the three scores and why
each exists"* — and state the sort order rule in one place: the dashboard sorts by
`confidence_score` with NULLs last; the gate ranks by `prescore`; `intent_score` is displayed for
legacy leads only. This costs a page and prevents a class of confusion that would otherwise be
rediscovered in code review.

### 8.2 Three caches, two dedup layers

| Layer | Key | Scope |
|---|---|---|
| `http_cache` | `sha256(url)`, 15 min TTL | Transport |
| `ai_cache` | prompt + content hash + version | Model responses |
| L0 `already_analyzed` | `(content_hash, prompt_version)` | Gate |

| Dedup | Key | Where |
|---|---|---|
| `filter_new` | `leads.reddit_id` | Ingest — *has this post been collected?* |
| `dedupe/exact` | `sha256(title+body)` | Enrichment — *has this content been analysed?* |

▶ Both sets are correct and none is redundant. But [28 §5](28-discovery-redesign.md) adds a fourth
cache layer (RSS watermarks), and at that point the interactions need stating explicitly — in
particular, **the `http_cache` 15-minute TTL and the RSS polling interval must be reconciled**, or a
poll will be served a stale feed and the watermark will not advance.

---

## 9. F9 — Missing production considerations

Eight things absent from all 26 documents. ▶ All are recommendations.

| # | Gap | Why it matters | Fix |
|---|---|---|---|
| P1 | **No restore drill.** [05 §7.1](05-database-plan.md) backs up before migrations; nothing ever restores | An untested backup is a hope | Quarterly restore drill in `RUNBOOK.md`; one CI job that restores a backup and asserts 459 leads |
| P2 | **No secret-rotation procedure.** [PHASE-01-STATUS §9](PHASE-01-STATUS.md) says *"Rotate the OpenRouter key. It was pasted into a chat transcript"* — with no documented procedure | `APP_SECRET_KEY` rotation makes the stored API key undecryptable ([11 §11](11-phase-01.md) knows this and handles it as a state, but there is no runbook) | Document rotation for all five secrets: `APP_SECRET_KEY`, pipeline key, agent key, Telegram token, proxy credentials |
| P3 | **No disk-space monitoring.** `http_cache` is capped at 500 MB, `ai_cache` has *no* TTL by design, Hermes `state.db` grows with every session, `cron/output/` accumulates | SQLite on a $5 VPS with a 40 GB disk. Silent fill → `database is locked` → run failures that look like proxy problems | `/health` reports free disk and DB size; maintenance job alerts below a threshold |
| P4 | **Timezone is unspecified.** Runs use UTC; the operator is Asia/Kolkata; quiet hours and digest times are local | A digest at "08:00" is ambiguous, and a UTC quiet-hours window is wrong by 5.5 h | One setting `operator_timezone`; all display and scheduling converted at the boundary, storage stays UTC ([03 §7](03-architecture.md)'s existing rule) |
| P5 | **The canary is designed but never scheduled.** [18 §4](18-phase-08.md) creates `scripts/canary.py`; nothing runs it | R1 is rated Critical and its only early-warning system is unscheduled | A cron job, and — ◐ better — RSS makes a cheaper canary: an Atom feed that parses is a strong signal that Reddit is reachable |
| P6 | **No notification backlog policy.** If the operator is away two weeks, `lead.high_confidence` alerts accumulate | Alert fatigue is how alerting dies | Per-run alert quota (already in [22 §4.12](22-hermes-skills.md)) plus a daily cap and a digest-instead-of-stream fallback |
| P7 | **No degraded-mode definition.** Individual failures are handled; there is no statement of what the platform does when *several* are degraded at once | An operator seeing a red proxy pool, a red cache ratio, and a stalled run needs a priority order | A one-page decision tree in `RUNBOOK.md` |
| P8 | **No data-volume projection.** 459 leads today; [09 §5.3](09-dashboard-plan.md) plans for 2,000-row tables; [18 §9.4](18-phase-08.md) asserts < 200 ms at 10,000 rows | Steady-state monitoring at ~120 new leads/day reaches 10,000 in ~11 weeks and 50,000 in a year | State the projection; the `keyword_breakdown` anti-pattern ([05 §9](05-database-plan.md)) becomes real at ~20k rows |

---

## 10. Weak assumptions inventory

Every load-bearing number that has never been measured.

| # | Assumption | Source | Class | Resolved by |
|---|---|---|---|---|
| A1 | ~1,000 posts/day collected, ~120 genuinely new after dedup | [06d §2.4](06d-ai-budget-and-scale.md) | ❓ | Sprint 0 — measure against the live subreddits |
| A2 | Hard filters remove ~73% of collected | [06c §8](06c-local-first-pipeline.md) | ❓ | Sprint 3, on real data |
| A3 | B=8 holds quality within 0.02 F1 | [02 §6.8](02-research-findings.md) | ◐ from literature | Phase 7 sweep — already planned |
| A4 | Prefix cache hit ratio > 85% | [06b §10](06b-deepseek-optimization.md) | ❓ | Blocked on F6 (OpenRouter does not report it) |
| A5 | MinHash indexes 2,000 items in < 2 s CPU | [06c §4.2](06c-local-first-pipeline.md) | ❓ — the doc says so honestly | Sprint 3 |
| A6 | `sqlite-vec` and Model2Vec load on the VPS | [AD-16](03-architecture.md) | ❓ | Sprint 0 — cheap to check, and the whole tier degrades if not |
| A7 | ~390 requests ≈ 33 min per run | [07 §5](07-scraping-pipeline.md) | ◐ arithmetic on a 5 s delay | Superseded by [28](28-discovery-redesign.md) |
| A8 | Agent turn ≈ 9k in / 700 out | [21 §6.5](21-hermes-architecture.md) | ▶ estimate | Sprint 0 M-1…M-3 |
| A9 | `hermes send` costs zero tokens | ✅ documented, ❓ unmeasured | Sprint 0 M-5 |
| A10 | RSS rate limit is per-feed or per-IP | Sources conflict | ❓ | Sprint 0 — **the highest-value single measurement in this review** |
| A11 | Reddit supports conditional GET (ETag / If-Modified-Since) on HTML or RSS | Nothing found | ❓ | Sprint 0 — a 304 costs ~0 bytes and would be a large win |
| A12 | 459-lead DB is representative for regression | [02 §10](02-research-findings.md) | ✅ reasonable | — |

---

## 11. Duplicated responsibilities

| Duplication | Verdict |
|---|---|
| `scrape_runs` (legacy audit) vs `runs` (orchestration) | **Keep both.** Documented in [05 §4.2](05-database-plan.md); the legacy table stays for the 10 existing rows |
| `agent_events` vs `ai_calls` | **Collapsed** — §5.1 |
| `notification_log` vs `run_events` | **Collapsed** — §5.2 |
| `dashboard_subreddits` + `config.yaml subreddits` vs `project_subreddits` | ▶ **Three sources for one concept.** The union-merge in `subreddit_loader.py` is legacy behaviour that must be preserved, but `project_subreddits` is the future. State the precedence rule once and add a deprecation note rather than leaving three lists |
| `PromptManager` versioning vs Hermes skill versioning | **Keep both** — different artefacts ([20 §3.1](20-hermes-vs-current.md)) |
| `RetryPolicy` in `src/net/` vs `src/ai/` | **Keep both** — one retries HTTP with proxy rotation, one retries a model call with repair. Same name, different contracts ▶ rename the AI one `AIRetryPolicy` to stop them being confused in review |

---

## 12. Decisions this review changes

| # | Was | Now | Reason |
|---|---|---|---|
| **R1** | All Reddit traffic must exit via proxy; `fail_closed: true` | **Network policy with pluggable providers**; direct is a first-class provider | §2 — our own measurements |
| **R2** | Discovery is HTML listing + search pagination | **RSS-first discovery**, HTML for enrichment of survivors only | §3 |
| **R3** | Hermes adds `agent_events` + `notification_log`, and `0005`–`0009` renumber | **Hermes adds no tables and no migrations** | §5 |
| **R4** | Two Docker containers + Compose + registry + CI deploy | **Two systemd units, two unix users, one VPS** | §7 |
| **R5** | Hermes auxiliary models unaddressed | `title_generation: false`, `approvals: off`, compression as a safety valve only | §4 |
| **R6** | Provider undecided; cost model written against DeepSeek direct | **Decide DeepSeek direct in Sprint 0**; OpenRouter becomes failover | §6.1 |
| **R7** | Execution order follows document numbering | **Reordered for earliest end-to-end data flow** | [31 §2](31-execution-plan.md) |
| **R8** | 17 seam tools, 13 skills at H2/H3 | **5 tools, 3 skills at first delivery**; the rest earn their way in | ▶ MVP discipline |

---

## 13. What survives the review unchanged

Stated explicitly, because a review that only lists problems misrepresents the state of the plan.

| Decision | Status |
|---|---|
| `old.reddit.com` HTML only; no API, OAuth, or PRAW ([D1](02-research-findings.md)) | **Confirmed** — and RSS *strengthens* it, being a published feed rather than a scraped page |
| Local-first funnel; AI as the last enrichment step ([AD-10a](03-architecture.md)) | **Confirmed** |
| The AI never produces the final score ([AD-11](03-architecture.md)) | **Confirmed** |
| Adaptive budget: knee + floor + marginal + clamps | **Confirmed** |
| Explanations are renderings, never generated ([AD-15](03-architecture.md)) | **Confirmed** — and §1.2 is a defect *against* it, not evidence against it |
| Knowledge accretes; regeneration replaces only what it wrote ([AD-17](03-architecture.md)) | **Confirmed** |
| Four memory classes, one SQLite file ([AD-18](03-architecture.md)) | **Confirmed** |
| Version pinning on every analysis ([AD-19](03-architecture.md)) | **Confirmed** |
| Two human review gates as the quality mechanism | **Confirmed** |
| Holdout audit as the only evidence that filtering is honest | **Confirmed** |
| Hermes as operator tier, never pipeline ([AD-20](21-hermes-architecture.md), [AD-21](21-hermes-architecture.md)) | **Confirmed** |
| Agent-tier budget ceiling ([AD-22](21-hermes-architecture.md)) | **Confirmed**, mechanism simplified ([31](31-execution-plan.md)) |
| No terminal toolset; untrusted-content envelope ([AD-23](21-hermes-architecture.md), [AD-24](21-hermes-architecture.md)) | **Confirmed** |
| Rejection of Redis, Postgres, Celery, vector DBs, graph DBs, learned rankers | **Confirmed** |

**Twelve of fourteen core decisions survive untouched.** The two that change — the proxy mandate and
the discovery mechanism — are both in the *collection* layer, which is the layer that has had the
least empirical attention and the only one where our own measurements contradict the plan.
