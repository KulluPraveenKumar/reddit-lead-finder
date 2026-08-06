# 06a — AI Service Layer

> The single boundary between this application's business logic and any AI model vendor.
> **Nothing outside `src/ai/providers/` ever knows that DeepSeek exists.**

---

## 1. The contract

Business logic calls **domain methods**. It does not construct prompts, does not choose models, does
not parse JSON, does not retry, and does not know what a token costs.

```python
class AIService:
    # ── Website intelligence — ONE consolidated call per project ──────────
    def analyze_business(self, site: ExtractedSite,
                         signals: LocalSiteSignals) -> BusinessIntelligence: ...
        """Profile + industry + competitors + positioning + ICP + personas +
           pain points + buying signals + vocabulary + subreddits + keywords,
           in a single request. See 06 §3."""

    # ── Targeted regeneration — ONE BKB section, reusing persisted context ──
    def regenerate_section(self, key: SectionKey,
                            ctx: ProjectContext) -> BaseModel: ...

    # ── Enrichment — BATCHED, the only high-volume path ───────────────────
    def enrich_batch(self, items: list[AnalysisInput], ctx: ProjectContext,
                     on_result: Callable[[AnalysisInput, LeadAnalysis | Failure], None]
                     ) -> BatchReport: ...
        """B items per request (default 8, measured ceiling). Every output
           element echoes its input id; a length mismatch splits and retries."""

    # ── Optional, lazy, single-item ───────────────────────────────────────
    def suggest_outreach(self, lead: LeadInput, analysis: LeadAnalysis,
                         ctx: ProjectContext) -> OutreachSuggestion: ...

    # ── Operations — no model call except test_connection ─────────────────
    def test_connection(self) -> ConnectionResult: ...
    def estimate_cost(self, plan: WorkloadPlan) -> CostEstimate: ...
    def usage_summary(self, *, run_id=None, project_id=None) -> UsageSummary: ...
```

**Four model-invoking methods, not twelve.** The earlier draft exposed one method per artefact,
which mapped one prompt to one call and produced six requests where one suffices. The consolidated
surface is the direct expression of the *minimise calls* mandate:

| Was | Now | Effect |
|---|---|---|
| 6 generation methods | `analyze_business()` | 6 calls → **1** |
| 2 targeting methods | folded into `analyze_business()` | 13 calls → **0 extra** |
| 2 per-item enrichment methods | `enrich_batch()` | 1,000 calls → **~21** |
| `summarize_opportunity()` | dropped — the summary is a field of `LeadAnalysis` | 1 call → **0** |
| — | `regenerate_section()` | preserves per-section Regenerate |

`suggest_outreach()` survives as a **lazy, on-demand** call: it is generated only when the operator
opens a lead and asks for it, so it costs nothing for the 95% of leads nobody opens.

**Nothing here is called unless [`PreAIGate`](06c-local-first-pipeline.md) has already admitted the
work.** The service is the last step in the funnel, never the first.

**`confidence_score` is deliberately absent.** The AI never emits the final score — it emits
categorical judgements that a deterministic Python scorer consumes. See
[04 §9](04-system-design.md) and [§10](#10-the-hybrid-confidence-engine) below.

---

## 2. Component architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  BUSINESS LOGIC                                                          │
│  handlers · discovery · scrapers · scoring · dashboard                   │
│  — calls domain methods only —                                           │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │  AIService (the ONLY entry point)
┌────────────────────────────────▼─────────────────────────────────────────┐
│  AI SERVICE LAYER            src/ai/service.py                           │
│                                                                          │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐   │
│  │ PromptManager  │  │ SchemaValidator  │  │ ResponseRepairer        │   │
│  │ versioned .md  │  │ Pydantic models  │  │ empty / invalid / schema│   │
│  │ render + hash  │  │ client-side      │  │ 3-branch ladder         │   │
│  └────────────────┘  └──────────────────┘  └─────────────────────────┘   │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐   │
│  │ ContextBuilder │  │ ResponseCache    │  │ DedupeGuard             │   │
│  │ frozen prefix  │  │ content-hash key │  │ in-flight request keys  │   │
│  │ sorted JSON    │  │ + prompt_version │  │ never ask twice         │   │
│  └────────────────┘  └──────────────────┘  └─────────────────────────┘   │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐   │
│  │ RateLimiter    │  │ CostTracker      │  │ ConcurrencyPool         │   │
│  │ adaptive       │  │ tokens → USD     │  │ bounded, adaptive       │   │
│  │ token bucket   │  │ budget guard     │  │ future → item map       │   │
│  └────────────────┘  └──────────────────┘  └─────────────────────────┘   │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐   │
│  │ RetryPolicy    │  │ AIMetrics        │  │ StructuredLogger        │   │
│  │ classify+backoff│  │ counters/latency │  │ redacting, run-scoped  │   │
│  └────────────────┘  └──────────────────┘  └─────────────────────────┘   │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │  LLMProvider  (abstract)
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
┌────────────────┐    ┌────────────────────┐    ┌────────────────────┐
│ DeepSeekProvider│   │ OpenAICompatible   │    │ (future) Anthropic │
│ ★ PRIMARY       │   │ Provider — base    │    │ Gemini · Ollama    │
│ v4-flash        │   │ class it derives   │    │ vLLM · Bedrock     │
└────────────────┘    └────────────────────┘    └────────────────────┘
```

**Why `DeepSeekProvider` derives from `OpenAICompatibleProvider`:** DeepSeek speaks the OpenAI wire
format. Putting the shared request/response shape in a base class means adding Together, Groq,
DeepInfra, vLLM, or Ollama later is a subclass with a different base URL, model ID, and price
table — perhaps 40 lines. Anthropic and Gemini would be full implementations of the same interface.

---

## 3. The provider interface

Deliberately minimal. Every capability the service needs, and nothing that assumes a vendor.

```python
@dataclass(frozen=True)
class ChatRequest:
    system: str
    user: str
    max_tokens: int
    json_mode: bool = True
    stop: list[str] | None = None
    model_override: str | None = None

@dataclass(frozen=True)
class ChatResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int          # prompt_cache_hit_tokens on DeepSeek
    uncached_input_tokens: int        # prompt_cache_miss_tokens on DeepSeek
    latency_ms: float
    finish_reason: str
    raw: dict                         # provider payload, for diagnostics only

class LLMProvider(ABC):
    name: str                                   # "deepseek"
    default_model: str                          # "deepseek-v4-flash"

    @abstractmethod
    def chat(self, req: ChatRequest, *, timeout: tuple[float, float]) -> ChatResponse: ...

    @abstractmethod
    def validate_credentials(self) -> ConnectionResult: ...

    @abstractmethod
    def price_table(self) -> PriceTable: ...    # $/1M for cached-in, uncached-in, out

    @abstractmethod
    def classify_error(self, exc_or_status) -> AIErrorClass: ...

    @property
    def supports_prefix_caching(self) -> bool: ...      # DeepSeek: True (implicit)
    @property
    def supports_schema_enforcement(self) -> bool: ...  # DeepSeek: False (JSON only)
    @property
    def supports_batch_api(self) -> bool: ...           # DeepSeek: False
    @property
    def cache_chunk_tokens(self) -> int: ...            # DeepSeek: 64
```

The three `supports_*` properties are how the service adapts without branching on vendor names.
`enrich_batch()` reads `supports_batch_api` and picks the concurrency pool; the repairer reads
`supports_schema_enforcement` and enables the client-side ladder; `ContextBuilder` reads
`cache_chunk_tokens` and pads the stable prefix accordingly. **A future provider that does have a
batch API or does enforce schemas gets the better path for free**, with no change to any caller.

---

## 4. Prompt management

### 4.1 Layout

```
src/ai/prompts/
├── _shared/
│   ├── json_contract.md        # "return json / no prose" — included by every prompt
│   ├── grounding_rules.md      # anti-hallucination rules
│   └── batch_contract.md       # id-echo + array-length rules for batched prompts
├── business_intelligence.v1.md # ★ THE consolidated website call
├── enrichment_batch.v1.md      # ★ THE batched Reddit call
├── section_regen.v1.md         # single-section regeneration (parameterised by section_key)
└── outreach_suggestion.v1.md   # lazy, on demand
```

**Four templates, not twelve.** Fewer templates is not a tidiness preference — each template is a
distinct cache namespace, and consolidating them means the two that run at volume accumulate deep,
warm caches instead of twelve shallow cold ones.

### 4.2 Mandatory sections

Every prompt file has **six** sections. Sections 4 and 5 are DeepSeek requirements, not style
preferences — the vendor documents that JSON mode needs the literal word "json" and an example of
the shape.

```markdown
# Role            — who the model is, one paragraph
# Task            — what to produce, imperative
# Rules           — grounding, anti-hallucination, stage-specific constraints
# Rubric          — enum criteria (classification stages only)
# Batch Contract  — ★ REQUIRED for batched prompts: echo every input id; emit
#                   exactly one element per input; never merge or omit
# JSON Shape      — ★ REQUIRED: a literal fenced example of the output object
# Output          — "Return only the json object. No prose, no markdown fences."
```

A test fails any prompt file that lacks a `# JSON Shape` section, lacks a fenced example, or does
not contain the case-insensitive token `json`.

### 4.3 Versioning

`(stage, version)` is recorded on every BKB section, every analysis row, and every `ai_calls` row, and
participates in the response-cache key.

**Editing a prompt without bumping its version is a bug** — the cache would serve results generated
by the old text forever. A test stores a content hash per `(stage, version)` and fails if a file
changes without a version bump.

### 4.4 Rendering and the frozen prefix

```python
class PromptManager:
    def render(self, stage: str, *, context: ProjectContext | None,
               variables: dict) -> RenderedPrompt:
        """Returns (system, user, version, prefix_hash).

        INVARIANT: `system` is byte-identical for every call within a (stage, project,
        prompt_version) triple. All per-item variability lives in `user`.
        """
```

`prefix_hash` is asserted constant across a run. A change mid-run raises `PrefixDriftError` — it
means the cache is silently missing and the input bill is up to 50× higher than estimated.

---

## 5. Context building — the frozen prefix

The single highest-leverage component in the service, because of DeepSeek's 50× cache differential.

```python
class ContextBuilder:
    def build(self, project: Project, stage: str) -> str:
        """Deterministic, frozen, chunk-aligned project context."""
        blob = {
            "business":  {...},                       # one-liner, category, positioning
            "icp":       {...},                       # summary, industries, disqualifiers
            "personas":  [{"slug":..., "title":...}],  # sorted by slug
            "pain_points":    [...],                   # sorted by slug
            "intent_signals": [...],                   # sorted by slug
            "vocabulary": {...},                       # sorted lists
        }
        text = json.dumps(blob, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return self._pad_to_chunk_boundary(text)       # 64-token alignment
```

**Enforced invariants** — each has a test:

| Invariant | Why |
|---|---|
| No timestamp, UUID, run id, lead id, or counter anywhere in the prefix | Any of them invalidates every cache hit |
| `sort_keys=True` on every `json.dumps` | Python dict ordering is insertion-ordered, not stable across regeneration |
| Every list sorted by a stable key (`slug`) | Same reason |
| Fixed separators, `ensure_ascii=False` | Whitespace and escaping changes are byte changes |
| Padded to a 64-token boundary | The tail chunk would otherwise be lost |
| ≥ 512 tokens before caching is counted on in an estimate | Shorter prefixes cache poorly or not at all |
| Model fixed for the duration of a run | A model change is a different cache namespace |

---

## 6. Response handling: the three-branch repair ladder

DeepSeek's JSON mode guarantees syntax, not schema. This ladder is what converts that weaker
guarantee into a typed object or an honest failure.

```
provider.chat(req)
    │
    ├─ HTTP error ──► RetryPolicy.classify()
    │                   ├─ 401 → InvalidAPIKeyError      (non-retryable, marks key invalid)
    │                   ├─ 402 → InsufficientBalanceError (non-retryable, PRODUCT STATE)
    │                   ├─ 400/422 → AIRequestError       (non-retryable, a bug)
    │                   └─ 429/500/503/timeout → retry with backoff + halve concurrency
    │
    └─ HTTP 200
         │
         ├─ content is empty  ──────────► BRANCH 1
         │     Documented DeepSeek behaviour. Retry with a PERTURBED prompt
         │     (append a short restatement of the required shape). Deliberately
         │     sacrifices the cache hit for this one call. Max 2 attempts.
         │
         ├─ json.loads() raises ────────► BRANCH 2
         │     Retry with the parser error appended verbatim. Strip markdown
         │     fences first — models wrap JSON in ```json despite instructions.
         │     Max 2 attempts.
         │
         ├─ parses, Pydantic rejects ───► BRANCH 3
         │     Retry with the SPECIFIC field-level validation error appended
         │     ("personas: list should have at most 5 items"). Max 2 attempts.
         │
         └─ parses and validates ───────► SUCCESS
               ├─ post-validate: verbatim-evidence check, slug allow-list check
               ├─ cache the result
               └─ record ai_calls row
```

After the ladder is exhausted: `SchemaValidationError`, the item is marked `failed`, and the caller
falls back to non-AI scoring. **A failure never discards completed work.**

---

## 7. Caching, dedup, and "never analyse the same content twice"

Four independent layers. Each catches something the others cannot.

| # | Layer | Key | Scope | Prevents |
|---|---|---|---|---|
| **L1** | **Website cache** | `sha256(normalised extracted site text)` | Per project, 7 d | Re-crawling and re-analysing an unchanged website |
| **L2** | **Business-profile cache** | Website fingerprint + `prompt_version` | Per project, permanent | Regenerating intelligence that already exists |
| **L3** | **Post-analysis cache** | `sha256(title + body + top comments)` + `prompt_version` | Per project, permanent | Re-enriching an item whose content has not changed |
| **L3b** | **Near-duplicate group** | MinHash/LSH, Jaccard ≥ 0.85 | Per run | Enriching 40 rewordings of the same question |
| **L4** | **Provider prefix cache** | Implicit, DeepSeek-side, byte-identical prefix | Per request | Paying 50× for the project context on every call |
| **L5** | **In-flight guard** | Same key as L3, in-memory | Per process | Two workers issuing an identical request simultaneously |

L1–L3b are **local and free**: they prevent the call entirely. L4 only makes a call that is
happening anyway cheaper. **The local tiers are worth far more**, and the numbering reflects the
order they are consulted.

Layer 3 is what satisfies **"never analyze identical content twice."** Two different Reddit posts
with byte-identical bodies produce one analysis, linked to both leads:

```python
h = sha256(normalise(item.text))
if (existing := repo.analysis_by_content_hash(project_id, h, prompt_version)):
    repo.link_analysis(item, existing)      # zero API calls, zero cost
    return existing
```

**Incremental enrichment** falls out of the same mechanism: a re-run analyses only items whose
`(content_hash, prompt_version)` pair has never been seen. A second run over a subreddit that
gained 12 new posts costs 12 calls, not 400.

**Cache invalidation is by `prompt_version` only.** Bumping a version produces a new key namespace
and preserves the old results for comparison. There is no TTL — an unchanged prompt asked about
unchanged text has an unchanged answer, and expiring that would only cost money.

---

## 8. Concurrency, rate limiting, and retries

### 8.1 Bounded adaptive concurrency (replaces the batch API)

```python
class ConcurrencyPool:
    def __init__(self, initial=8, floor=1, ceiling=16): ...

    def map(self, items, fn, on_result) -> BatchReport:
        with ThreadPoolExecutor(max_workers=self.current) as ex:
            futures = {ex.submit(fn, it): it for it in items}     # ← attribution
            for fut in as_completed(futures):
                item = futures[fut]                               # ← never by position
                try:
                    on_result(item, fut.result())
                except AIError as e:
                    on_result(item, Failure(e))
```

`futures[fut]` is the correctness mechanism that replaces `custom_id`. **Attribution by position is
the defect class this design must never permit**, and it gets a dedicated blocking test.

**Adaptation:** sustained 429/503 or a p95 latency rise beyond a threshold halves `current` (floor
1); a clean window of N completions steps it back up (ceiling 16). Because DeepSeek slows rather
than refuses, latency is the primary signal and errors are the secondary one.

**Concurrency is account-level on DeepSeek**, shared across every key. The ceiling is therefore a
global setting, not per-run, and a second concurrent run shares the same pool.

### 8.2 Rate limiting

A token-bucket limiter in front of the pool, configured in requests/minute and tokens/minute. It
exists not because DeepSeek publishes hard caps — it does not — but because a runaway loop should
be bounded by our own governor rather than discovered on the invoice.

### 8.3 Retry policy

```python
def backoff(attempt: int, err: AIErrorClass, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, 120.0)
    return min(60.0, 2.0 ** attempt) * random.uniform(0.7, 1.3)    # jittered
```

| Class | Retry | Max attempts | Side effect |
|---|:---:|---:|---|
| `RATE_LIMITED` (429) | ✅ | 5 | Halve concurrency |
| `SERVER_ERROR` (500) | ✅ | 4 | — |
| `OVERLOADED` (503) | ✅ | 5 | Halve concurrency |
| `TIMEOUT` / network | ✅ | 4 | — |
| `EMPTY_CONTENT` | ✅ | 2 | Perturb the prompt |
| `INVALID_JSON` | ✅ | 2 | Append parser error |
| `SCHEMA_VIOLATION` | ✅ | 2 | Append field error |
| `INVALID_KEY` (401) | ❌ | — | Mark key invalid; surface in Settings + `/health` |
| `INSUFFICIENT_BALANCE` (402) | ❌ | — | Stop enrichment; preserve work; surface in UI |
| `BAD_REQUEST` (400/422) | ❌ | — | Fail the job; it is a bug |
| `BUDGET_EXCEEDED` (local) | ❌ | — | Stop enrichment; preserve work |

**Timeouts are always `(connect, read)` tuples** — 10 s connect, 120 s read for generation stages,
60 s for enrichment. A scalar timeout in `requests` applies per socket operation and can hang far
longer than the number implies.

---

## 9. Cost and token tracking

Every call writes an `ai_calls` row. Nothing is estimated after the fact.

```python
def cost_usd(resp: ChatResponse, prices: PriceTable, at: datetime) -> float:
    mult = prices.surcharge_multiplier(at)          # peak-window aware; 1.0 by default
    return mult * (
        resp.uncached_input_tokens / 1e6 * prices.input_uncached +   # $0.14
        resp.cached_input_tokens   / 1e6 * prices.input_cached   +   # $0.0028
        resp.output_tokens         / 1e6 * prices.output             # $0.28
    )
```

Surfaced at four levels: per call (`ai_calls`), per run (`runs.llm_cost_usd`), per project
(aggregate), and per day (`/health`). The budget guard runs **before** each call, never after.

Token-efficiency metrics that matter more than raw spend:

| Metric | Healthy | Meaning if unhealthy |
|---|---|---|
| `cache_hit_ratio` | > 0.85 after warm-up | A prefix invalidator — up to 50× overspend |
| `response_cache_hit_ratio` | > 0.30 on re-runs | Incremental enrichment is not working |
| `repair_rate` | < 0.05 | The prompt's JSON shape section is unclear |
| `empty_content_rate` | < 0.02 | Prompt needs restructuring |
| `avg_output_tokens` | near the schema's natural size | The model is padding; tighten the prompt |

---

## 10. The hybrid confidence engine

The user requirement is to replace keyword-heavy scoring with an AI-assisted engine. The design
already separates *judgement* from *arithmetic*; this section makes the hybrid structure explicit.

```
   RULE-BASED SIGNALS            AI SIGNALS                REDDIT METRICS
   ┌──────────────────┐   ┌──────────────────────┐   ┌──────────────────┐
   │ keyword matches  │   │ intent_stage         │   │ upvotes          │
   │ negative terms   │   │ matched pain slugs   │   │ comment count    │
   │ subreddit fit    │   │ matched signal slugs │   │ author history   │
   │ post structure   │   │ persona match        │   │ subreddit size   │
   │ (LeadScorer)     │   │ urgency · sentiment  │   └────────┬─────────┘
   └────────┬─────────┘   │ competitor mention   │            │
            │             │ ICP match            │            │
            │             └──────────┬───────────┘            │
            │                        │                        │
            │        RECENCY ────────┼──────── ENGAGEMENT ────┤
            │                        │                        │
            └────────────────────────┼────────────────────────┘
                                     ▼
                    ┌────────────────────────────────────┐
                    │  ConfidenceScorer  (pure Python)   │
                    │  weighted, clamped, explainable    │
                    │  every component persisted         │
                    └────────────────┬───────────────────┘
                                     ▼
                          confidence_score  0–100
```

**Why hybrid rather than "ask the model for a score":**

1. **Reproducibility.** The same inputs always produce the same number. An LLM asked for a 0–100
   score will not.
2. **Free re-ranking.** Changing a weight re-ranks 10,000 leads in under two seconds with zero API
   calls. That is impossible if the number came from the model.
3. **Calibration.** The `interested` rate per score decile is measurable and the weights are
   tunable in response. You cannot tune a black box.
4. **Graceful degradation.** With AI disabled, out of balance, or over budget, the rule-based and
   Reddit-metric components still produce a usable ranking.
5. **Explainability.** The UI shows every component's value, weight, and contribution. A user who
   disagrees with a 92 can see exactly which component produced it.

The AI's contribution is the part it is genuinely better at — *reading a post and deciding what kind
of thing it is*. The arithmetic stays in Python where it belongs.

---

## 11. Non-functional requirements — how each is met

| Requirement | Mechanism |
|---|---|
| **Modular** | 12 named collaborators, each independently unit-testable |
| **Provider agnostic** | `LLMProvider` ABC + capability flags; grep test forbids vendor names outside `providers/` |
| **Scalable** | Bounded adaptive concurrency; per-run budgets; incremental enrichment |
| **Maintainable** | Prompts are versioned files; schemas are Pydantic; one call site per capability |
| **Testable** | Provider is injectable; `FakeProvider` replays recorded fixtures; **no live API calls in CI** |
| **Production ready** | Health checks, metrics, structured logs, budget guards, graceful degradation |
| **Cost efficient** | 4 cache layers, dedup, pre-filter, per-run cap, cost shown before commit |
| **Token efficient** | Frozen prefix, compressed context, minimal windows, tight `max_tokens` |
| **Low latency** | Concurrency pool, connection pooling, cache hits return in microseconds |
| **Cache friendly** | Byte-identical prefixes enforced by test; chunk alignment; content-hash dedup |
| **Retry safe** | Every operation idempotent; dedup guard prevents double-charging on retry |
| **Future proof** | Adding a provider is one subclass; capability flags select the better path automatically |

---

## 12. Adding a second provider — the extensibility test

The abstraction is only real if the steps are small and touch no business logic.

**To add OpenAI, Together, Groq, DeepInfra, vLLM, or Ollama** (all OpenAI-compatible):

1. Subclass `OpenAICompatibleProvider`; set `name`, `default_model`, `base_url`, `price_table()`.
2. Override `supports_*` if capabilities differ (e.g. OpenAI supports schema enforcement → the
   repair ladder is bypassed automatically).
3. Register in `PROVIDER_REGISTRY`.
4. Add its credential field to the Settings page (driven by a provider descriptor, so this is data,
   not code).

**To add Anthropic or Gemini** (different wire format): implement `LLMProvider` directly — one file,
roughly 150 lines. Everything above it is unchanged.

**What must never be required:** a change to `AIService`'s public methods, to any handler, to any
scraper, to the scoring engine, or to any prompt file.

A test enforces this: `FakeProvider` implements `LLMProvider` and the **entire** AI test suite runs
against it with zero DeepSeek-specific code paths.

---

## 13. Package layout

```
src/ai/
├── service.py                 # AIService — the only public entry point
├── schemas.py                 # every Pydantic output model
├── context.py                 # ContextBuilder — the frozen prefix
├── prompts.py                 # PromptManager: load, render, version, hash
├── prompts/                   # versioned .md templates
├── repair.py                  # the three-branch ladder
├── cache.py                   # response cache + content-hash dedup + in-flight guard
├── concurrency.py             # bounded adaptive pool
├── cost.py                    # PriceTable, CostTracker, budget guard
├── metrics.py                 # AI-specific counters
├── errors.py                  # the exception hierarchy
├── credentials.py             # encrypted key storage, validation, fingerprints
└── providers/
    ├── base.py                # LLMProvider ABC, ChatRequest/ChatResponse
    ├── openai_compatible.py   # shared wire format
    ├── deepseek.py            # ★ DeepSeekProvider
    ├── fake.py                # test double
    └── registry.py            # PROVIDER_REGISTRY + descriptors for the Settings UI
```

`src/ai/` imports from `src/net/` (HTTP), `src/db/` (repositories), and nothing else.
**Nothing outside `src/ai/providers/` may contain the string `deepseek`.**
