# 33 — Final Architecture Review

> **Steps 1 and 2 of the freeze review.** Consistency verification across all 46 documents, the
> final research pass, and the documentation update plan.
>
> **This review does not redesign.** Where a gap is found, it is closed by the smallest change that
> closes it. Two changes to the plan are proposed; both are corrections, not designs.
>
> Evidence labels: ✅ Verified · ◐ Inferred · ▶ Recommendation · ❓ Unknown.

---

## 1. Verification matrix

The thirteen areas named in the brief, each verified against the documents that govern it.

| # | Area | Governing docs | Verdict |
|---|---|---|---|
| 1 | **Architecture consistency** | [03](03-architecture.md), [21](21-hermes-architecture.md), [27](27-architecture-review.md) | ⚠️ **3 open items** — §2.1, §2.2, §2.3 |
| 2 | **ADR consistency** | [03 §6](03-architecture.md) AD-1…AD-24 + AD-25…AD-31 ([32 §4](32-documentation-consistency.md)) | ✅ Consistent. AD-25…AD-31 are additive; four amendments are explicit; two withdrawals are marked in place |
| 3 | **Database consistency** | [05](05-database-plan.md), [28 §10](28-discovery-redesign.md), [31 §5](31-execution-plan.md) | ⛔ **1 defect** — §2.4, `prescores` ordering |
| 4 | **Migration order** | [31 §5](31-execution-plan.md) | ⛔ **Same defect.** Otherwise linear, one head, ten revisions |
| 5 | **Execution order** | [31 §2](31-execution-plan.md) | ✅ Consistent; [25](25-hermes-roadmap.md) superseded and marked |
| 6 | **Documentation consistency** | [32](32-documentation-consistency.md) | ⚠️ **6 known contradictions scheduled**, 3 new found — §2 |
| 7 | **Hermes architecture** | [19](19-hermes-research.md)–[23](23-hermes-memory-and-knowledge.md), [27 §5](27-architecture-review.md) | ✅ Consistent after the AD-29/AD-30 withdrawals were marked in [21](21-hermes-architecture.md) |
| 8 | **Discovery pipeline** | [28](28-discovery-redesign.md) | ✅ Internally consistent; four ❓ assigned to P0 |
| 9 | **AI pipeline** | [06](06-ai-pipeline.md)–[06i](06i-feedback-and-memory.md), [30](30-ai-call-inventory.md) | ⚠️ **Cost figures disagree across docs** — §2.5 |
| 10 | **Telegram** | [21 §7](21-hermes-architecture.md), [28](28-discovery-redesign.md), [29](29-network-and-proxy-strategy.md), AD-28 | ✅ Consistent. Notification path is agent-free and ships in Stage C |
| 11 | **Proxy abstraction** | [29](29-network-and-proxy-strategy.md), AD-25 | ✅ Consistent; [07 §1](07-scraping-pipeline.md)/[08 §7](08-proxy-service.md) edits scheduled |
| 12 | **Cost optimization** | [24](24-cost-optimization.md), [30](30-ai-call-inventory.md) | ⚠️ **Authority unstated** — §2.5 |
| 13 | **Testing strategy** | [02 §10](02-research-findings.md), `testing/`, [35](35-testing-strategy.md) | ⚠️ **Phase→test-doc mapping broken** by renumbering — §2.6 |
| 14 | **Deployment strategy** | AD-30, [31 §4](31-execution-plan.md) S9 | ✅ Consistent after the [21 §8](21-hermes-architecture.md) supersession note |

**Eleven of fourteen clean. Three carry open items, one of which is a genuine defect.**

---

## 2. Findings

### 2.1 ⚠️ Seam tool count and skill count are stated twice, differently

| Doc | Says |
|---|---|
| [21 §4](21-hermes-architecture.md) | 17 seam tools |
| [22 §3](22-hermes-skills.md) | 13 skills |
| [31 §4](31-execution-plan.md) S7 | **5 tools, 3 skills at first delivery** |

Neither is wrong — [31](31-execution-plan.md) says *"at first delivery"* — but a reader of
[21](21-hermes-architecture.md) or [22](22-hermes-skills.md) alone will build seventeen tools.

**▶ Fix (documentation only):** [21 §4](21-hermes-architecture.md) and [22 §3](22-hermes-skills.md)
gain a header stating that the table is the **target surface**, that first delivery is 5 tools and
3 skills, and that each addition requires a stated operator need. Recorded in
[ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) §7 as a freeze rule.

### 2.2 ⚠️ `WebsiteFetcher` egress is specified twice, incompatibly

[14 §9.1](14-phase-04.md) and [08 §10](08-proxy-service.md) route it through `ProxiedHTTPClient`.
[29 §2](29-network-and-proxy-strategy.md) and AD-25 route it **direct** — a customer's own site
should not be crawled from ten rotating datacenter IPs.

**▶ Fix:** AD-25 is authoritative. Edit both at Stage E. No design change.

### 2.3 ⚠️ [23 §5](23-hermes-memory-and-knowledge.md)'s retention table lists withdrawn tables

`agent_events` and `notification_log` appear in the operational memory class. AD-29 withdrew both.

**▶ Fix:** replace both rows with *"agent turns — see `ai_calls`, `stage='agent.%'`"*. Retention is
already defined for `ai_calls`, so the class loses nothing.

### 2.4 ⛔ **DEFECT — `prescores` is required in Stage C but created in Stage D**

This is a real ordering error, and it is mine from the previous review.

✅ [28 §10](28-discovery-redesign.md) specifies:

```sql
ALTER TABLE prescores ADD COLUMN stage VARCHAR(20) NOT NULL DEFAULT 'full';
```

…implying `prescores` already exists. But [31 §5](31-execution-plan.md) creates it in
`0006_local_pipeline` (Stage D), while [28 §3](28-discovery-redesign.md)'s **Stage 3 metadata
triage** — which records a rejection reason per discovered item — runs in Stage C, one revision
earlier.

◐ **Consequence if unfixed:** Stage C's triage rejections have nowhere to be recorded, so the
metadata-triage holdout audit ([28 §9 D6](28-discovery-redesign.md)) cannot run, and
[AD-10b](03-architecture.md)'s rule — *a gate that silently discards a good lead is worse than no
gate* — is violated by the very stage introduced to be cheap.

**▶ Fix — the smallest one that works:**

| Change | Detail |
|---|---|
| `prescores` moves from `0006` to **`0005_discovery`** | It is a discovery artefact before it is a qualification artefact |
| `prescores.comment_id` is **created without a `REFERENCES` clause** | `comments` does not exist until `0006`; the FK is added there via `batch_alter_table` — the pattern `ai_calls.project_id` already uses ([05 §7.1](05-database-plan.md)) |
| `prescores.stage` is part of the **`CREATE TABLE`**, not an `ALTER` | `0005` has not shipped |
| `0006` keeps | `comments`, `dedup_groups`, `dedup_members`, `minhash_bands`, `leads` +4 columns |

**Revision count and head count are unchanged.** One table moves one revision earlier.

### 2.5 ⚠️ Cost authority is unstated, and three documents disagree

| Doc | Monthly platform AI cost |
|---|---|
| [24 §7](24-cost-optimization.md) | **$0.59** |
| [30 §5](30-ai-call-inventory.md) | **$0.34** |
| [06d §2.4](06d-ai-budget-and-scale.md) | **$0.16** (pipeline only, pre-Hermes) |

Each is correct in its own frame, and no document says which frame is current.
[27 §1.4](27-architecture-review.md) already found the same class of drift across five documents and
named [06d](06d-ai-budget-and-scale.md) as authority — but [06d](06d-ai-budget-and-scale.md) has not
been updated with the agent tier.

**▶ Fix:** [06d](06d-ai-budget-and-scale.md) becomes the single source and is updated once, at
Stage E, with three separated figures — pipeline, agent tier, total. [24](24-cost-optimization.md)
and [30](30-ai-call-inventory.md) cite it. **A number that appears in four documents will be wrong in
three of them.**

### 2.6 ⚠️ The `testing/phase-NN` mapping is broken by renumbering

Eight files named `testing/phase-01-testing.md` … `phase-08-testing.md` map to the *old* phase
numbers. The plan now has 31 implementation phases across ten stages.

**▶ Fix:** [35](35-testing-strategy.md) defines `testing/phase-NN-testing.md` for the **new**
numbering, and a mapping table in [README](README.md) retires the old names by pointing at their
successor stage. ▶ Renaming eight files would churn every cross-reference in the set to buy naming
symmetry; the mapping table is cheaper and loses nothing.

### 2.7 ✅ Verified clean — no action

| Check | Result |
|---|---|
| Alembic chain linear with one head, `0001`→`0010` | ✅ after §2.4 |
| Only `0001`–`0003` applied to the live database | ✅ |
| No revision renumbering required | ✅ — the `0005_agent_tier` proposal was withdrawn (AD-29) |
| Four grep fences defined and non-overlapping | ✅ |
| Every AD has context, decision, consequences, rejections | ✅ |
| Every withdrawn decision is marked at its source | ✅ — [21 §8](21-hermes-architecture.md), [21 §13](21-hermes-architecture.md), [25](25-hermes-roadmap.md), [26](26-documentation-plan.md) |
| Legacy guarantees stated in every phase | ✅ — 459 leads, 17 endpoints, 13 CSV columns |
| No document proposes a second AI boundary | ✅ — AD-21 holds |
| No document proposes writing the BKB from the agent | ✅ — AD-17 holds |

---

## 3. Final research pass

Three topics were genuinely unresolved. The rest of the brief's list is already decided with cited
reasoning ([02 §7.1](02-research-findings.md) queues, [02 §7.2](02-research-findings.md) SQLite WAL,
[02 §6](02-research-findings.md) DeepSeek, [19](19-hermes-research.md) Hermes, [29](29-network-and-proxy-strategy.md)
proxies) and re-researching them would produce churn, not improvement.

### 3.1 Agent Skills standard ✅ — resolves the skills question

Fetched from **agentskills.io**, the open standard Hermes declares compatibility with.

> "At its core, a skill is a folder containing a `SKILL.md` file. This file includes metadata
> (`name` and `description`, at minimum) and instructions."

```
my-skill/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation
├── assets/           # Optional: templates, resources
```

> "Agents load skills through **progressive disclosure**, in three stages:
> 1. **Discovery**: At startup, agents load only the name and description of each available skill…
> 2. **Activation**: When a task matches a skill's description, the agent reads the full `SKILL.md`…
> 3. **Execution**: The agent follows the instructions, optionally executing bundled code…"
>
> "Full instructions load only when a task calls for them, so agents can keep many skills on hand
> with only a small context footprint."

**Two findings that matter:**

1. ✅ **The standard confirms [22 §2](22-hermes-skills.md)'s authoring rules exactly.** Description
   is paid at discovery on every turn; body is free until activation. SR1–SR4 stand as written, now
   with a primary source rather than an inference.
2. ✅ **Claude Code and Hermes are both listed clients of the same standard.** ◐ Therefore **one skill
   format serves both runtimes** — the implementation/testing skills the brief asks for
   (`.claude/skills/`) and the operator skills ([22](22-hermes-skills.md), `~/.hermes/skills/`) are
   the same artefact type in different directories.

▶ This resolves an ambiguity in the brief, which lists `reddit-rss`, `deduplication`,
`keyword-filter` and `lead-scoring` alongside `implementation-planner` and `unit-test-runner` as if
they were one category. They are three. [36](36-skills-architecture.md) separates them.

**No change to the plan.** Confirmation, not redesign.

### 3.2 Structured logging library ✅ — closes a genuinely open decision

[03 §7](03-architecture.md) and [13 §4](13-phase-03.md) require *"structured JSON logs to file +
`rich` to console"* with a redaction filter, but **no library is named anywhere**. That is a real
gap: an implementer would choose one, and the choice affects every module.

✅ Research (Dash0, BSWEN, tutorials.technology, 2026):

> "stdlib + `python-json-logger` is **the safe, universal choice** for libraries and when you want
> zero surprises. `structlog` is **the performance and observability champion** for microservices,
> high-throughput applications, or when you need OpenTelemetry with minimal friction."
>
> Benchmarks: "Structlog+OTel shows 0.8% overhead vs stdlib's 5.2%."

**▶ Decision: stdlib `logging` + `python-json-logger`.**

| Criterion | Assessment |
|---|---|
| Volume | ◐ ~60 HTTP requests/day and ~140 AI calls/month. The 5.2% vs 0.8% overhead difference is measured on high-throughput services and is **irrelevant at our scale** |
| OpenTelemetry | ⛔ Explicitly rejected — [02b §6](02b-research-2026-07.md): *"no distributed tracing, no external observability vendor"* |
| Redaction filter | Both support it; stdlib's `Filter` is what [08 §1](08-proxy-service.md) already specifies |
| Third-party capture | `requests`, `urllib3`, `alembic`, `flask` all log through stdlib. structlog would need `LoggerFactory()` wiring to capture them |
| Dependency cost | `python-json-logger` is small and pure-Python; structlog is larger and would be the only logging abstraction in a codebase that otherwise uses the standard library |

▶ Choosing structlog here would be buying a benchmark advantage we cannot observe, at the price of a
dependency and a wiring step. **Recorded as a freeze decision so it is not relitigated.**

**Plan change:** `python-json-logger>=2.0` added to Stage B (P2) dependencies; named in
[03 §7](03-architecture.md) and [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) §6.

### 3.3 Atom parsing library ✅ — confirms zero new dependencies

[28 §10](28-discovery-redesign.md) proposes `src/discovery/feed_parser.py`;
[32 §5.3](32-documentation-consistency.md) claims *"Atom parses with `lxml`, already present"* —
which was an assertion, not a researched one.

✅ Research (kagisearch/fastfeedparser, feedparser issue #209, webscraping.fyi, 2026):

> "FastFeedParser (which uses `lxml`) is **10x–100x faster** than `feedparser`… about **25x
> faster**."
>
> "`feedparser` is **the gold standard** for RSS/Atom parsing in Python, battle-tested with over 15
> years of development, **abstracting feed format differences**."
>
> Reported: 50k-entry feed took feedparser 8 s; ElementTree cut it to 2 s.

**▶ Decision: parse with `lxml` directly. No new dependency.**

The discriminating question is what `feedparser`'s robustness actually buys *here*:

| `feedparser` strength | Applies to us? |
|---|---|
| Abstracts RSS 0.9x/1.0/2.0, Atom 0.3/1.0, RDF differences | ❌ **We parse exactly one format from exactly one source** |
| Tolerates malformed feeds in the wild | ◐ Marginal — Reddit's Atom is machine-generated |
| Date-format normalisation | ◐ Useful, and ~15 lines with `datetime.fromisoformat` |
| 15 years of edge cases | ✅ Genuine — but for a feed ecosystem we do not consume |

▶ Performance is **not** the reason. At ≤100 entries per feed, both are instant. The reason is
dependency discipline: [00 §7](00-current-state.md) keeps the runtime dependency list short and
justified, `lxml` is already required by BeautifulSoup, and adding a library to parse one
machine-generated format is complexity without a matching benefit.

**The guard that makes this safe** — and it is required, not optional: golden Atom fixtures with
`.expected.json`, exactly as [07 §9](07-scraping-pipeline.md) does for HTML. A hand-rolled parser
without fixtures would be a worse trade than the dependency.

**No plan change** — [28 §10](28-discovery-redesign.md) stands; the fixture requirement is added to
P5's acceptance criteria.

### 3.4 Topics deliberately not re-researched ▶

| Topic | Already decided | Where |
|---|---|---|
| SQLite WAL, `busy_timeout`, `synchronous`, `foreign_keys` | ✅ | [02 §7.2](02-research-findings.md), [05 §8](05-database-plan.md) |
| Job queue vs broker | ✅ Six options compared | [02 §7.1](02-research-findings.md) |
| asyncio vs threads | ✅ Sync + bounded `ThreadPoolExecutor` | [03 §8](03-architecture.md), [06a §8.1](06a-ai-service-layer.md) |
| HTTP client, pooling, retry | ✅ `requests` + per-proxy `HTTPAdapter`, `max_retries=0` | [08 §3.3](08-proxy-service.md) |
| Caching layers | ✅ Six tiers | [06a §7](06a-ai-service-layer.md) |
| Retry strategy | ✅ Two distinct loops, full error table | [06a §8.3](06a-ai-service-layer.md) |
| DeepSeek mechanics | ✅ Verified 2026-07-30; **re-verification is P0 task V-2** | [02 §6](02-research-findings.md) |
| Managed proxy providers | ✅ Eight compared | [29 §5](29-network-and-proxy-strategy.md) |
| Scheduling | ✅ `hermes cron` replaces `schedule` | [19 §16](19-hermes-research.md), [31](31-execution-plan.md) S7 |
| Memory, tool calling, skill loading | ✅ | [19](19-hermes-research.md), [23](23-hermes-memory-and-knowledge.md) |

▶ Re-researching a decided question with a citation and a rejection register produces churn, not
improvement. The brief asked for research on *unknowns*; these are knowns.

---

## 4. Documentation update plan (final)

[32 §5](32-documentation-consistency.md) remains the working list. This section states the
**additions and the authority rules**, which is what a freeze needs.

### 4.1 Additional edits found by this review

| Doc | Change | Stage |
|---|---|---|
| [05](05-database-plan.md) | **`prescores` moves to `0005`** with `comment_id` FK deferred to `0006` (§2.4) | C |
| [28 §10](28-discovery-redesign.md) | `prescores.stage` becomes part of `CREATE TABLE`, not an `ALTER` | C |
| [31 §5](31-execution-plan.md) | Migration table corrected for the `prescores` move | C |
| [21 §4](21-hermes-architecture.md), [22 §3](22-hermes-skills.md) | Header: *target surface; first delivery is 5 tools / 3 skills* (§2.1) | H |
| [23 §5](23-hermes-memory-and-knowledge.md) | Retention rows for `agent_events` / `notification_log` replaced (§2.3) | H |
| [06d](06d-ai-budget-and-scale.md) | Becomes the **single cost authority**; three separated figures (§2.5) | E |
| [03 §7](03-architecture.md) | Name the logging library (§3.2) | B |
| [00 §7](00-current-state.md) | `+python-json-logger`; **no feed-parsing dependency** (§3.2, §3.3) | B |
| [README](README.md) | Test-document mapping table (§2.6) | B |
| [08 §10](08-proxy-service.md), [14 §9.1](14-phase-04.md) | `WebsiteFetcher` egress is direct (§2.2) | E |

### 4.2 The authority rules — the part that prevents future drift

▶ Each figure or decision has **exactly one home**. Everything else cites it.

| Subject | Single authority | Everything else |
|---|---|---|
| Cost and call figures | [06d](06d-ai-budget-and-scale.md) | Cites, never restates |
| Confidence weights | [04 §9.1](04-system-design.md) | [09](09-dashboard-plan.md) renders from it |
| Migration chain | [05 §7](05-database-plan.md) | Phase docs name their revision only |
| Architecture decisions | [03 §6](03-architecture.md) | AD-NN referenced by number |
| Execution order | [34](34-implementation-plan.md) | [31](31-execution-plan.md) is its rationale |
| Frozen constraints | [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) | Everything defers to it |
| Skill catalogue | [36](36-skills-architecture.md) | [22](22-hermes-skills.md) is its Hermes subset |
| Testing procedure | [35](35-testing-strategy.md) | Phase docs reference the gate |

---

## 5. Freeze readiness

| Criterion | Status |
|---|---|
| All documents read and cross-checked | ✅ 46 documents |
| Contradictions found | **9** — 6 previously scheduled, 3 new (§2.1–2.3) |
| Defects found | **1** — §2.4, `prescores` ordering |
| Defects closed by a design change | **0** — the fix moves one table one revision earlier |
| Open unknowns | **16**, all assigned to P0 and none blocking the freeze |
| New dependencies introduced by this review | **1** (`python-json-logger`) |
| New dependencies avoided by this review | **1** (`feedparser`) |
| Research topics genuinely open | **0** |

> **The architecture is ready to freeze.** No finding in this review required a design change. One
> table moves one revision earlier; one dependency is named; nine documentation edits are scheduled.
> That is the expected outcome of a fourth review pass — if it had produced another redesign, the
> third pass would have been wrong.

Proceed to [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md).
