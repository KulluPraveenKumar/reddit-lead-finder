# 01 — Product Vision

## 1. One-sentence definition

**Paste a website URL; get a ranked list of Reddit conversations where real people are describing
the problem that website solves, with evidence for why each one is a lead.**

---

## 2. The canonical flow

```
User enters Website URL
        │
        ▼
  AI understands website ─────────────► Business Profile
        │                                    │
        │                                    ├─► ICP
        │                                    ├─► Personas
        │                                    ├─► Pain Points
        │                                    ├─► Buying Intent signals
        │                                    └─► Reddit Vocabulary
        ▼
  Find relevant subreddits
        │
        ▼
 ╔══════════════════════════════╗
 ║  GATE 1 — user reviews/edits ║   ← pipeline PAUSES and persists
 ║  subreddit recommendations   ║
 ╚══════════════════════════════╝
        │
        ▼
  AI generates search keywords
        │
        ▼
 ╔══════════════════════════════╗
 ║  GATE 2 — user reviews/edits ║   ← pipeline PAUSES and persists
 ║  keywords                    ║
 ╚══════════════════════════════╝
        │
        ▼
  User selects scraping options (depth, time window, comments on/off, limits)
        │
        ▼
  System scrapes Reddit  ──  old.reddit.com only  ──  rotating Webshare proxies
        │
        ├─► Extract Posts
        └─► Extract Comments
        │
        ▼
  AI analyses every result
        ├─► Detect pain points
        ├─► Detect buying intent
        └─► Calculate confidence score
        │
        ▼
  Rank opportunities
        │
        ▼
  Display leads in dashboard  ──►  Export results
```

Everything above the first gate is **understanding**. Everything between the gates is
**targeting**. Everything below is **collection and qualification**. The three stages have
different failure modes, different latencies, and different costs, which is why they are separated
by persisted state rather than by function calls.

---

## 3. Why the review gates are the defining architectural constraint

An LLM that reads a website and guesses at subreddits will be right most of the time and
embarrassingly wrong occasionally — proposing `r/marketing` for a dev-tools company, or a dead
subreddit with 400 subscribers. Scraping on a wrong target costs proxy bandwidth, LLM tokens, and
the user's trust.

The gates are therefore not a UI nicety; they are the quality mechanism. Their existence forces
three architectural decisions:

1. **Run state must be persisted, not held in a thread.** A user may approve subreddits an hour
   later, or never. The process may restart in between.
2. **The pipeline is a state machine**, not a function. Each stage has an explicit entry state, an
   exit state, and a failure state.
3. **Every AI output must be editable.** If the user can only accept or reject, the gate is
   worthless. Subreddits and keywords must be add/remove/edit collections in the UI, backed by
   rows the user owns.

---

## 4. Stage-by-stage definition

### 4.1 Website understanding

**Input:** a URL.
**Process:** fetch the landing page plus a small, bounded set of high-signal internal pages
(`/pricing`, `/features`, `/about`, `/product`, `/solutions`, `/customers`, `/use-cases`), strip to
readable text, and send a single consolidated prompt to the LLM.
**Output:** a `BusinessProfile` — what the company sells, category, delivery model, price posture,
target market size, geography, competitors named on-site, and the value propositions in the
company's own words.

**Non-goal:** crawling the whole site. Bounded depth, bounded page count, bounded characters.

### 4.2 ICP

The firmographic and situational description of who buys: company size, industry, stage, team
composition, tooling, budget authority, and the trigger events that create demand. Derived from the
business profile, not from the raw HTML — this keeps the prompt small and the reasoning explicit.

### 4.3 Personas

Three to five named roles, each with a job title, seniority, day-to-day responsibilities, the
metrics they are measured on, what they already use, and — critically — **where on Reddit that
person actually posts.** A persona that cannot be located on Reddit is not useful here.

### 4.4 Pain points

Concrete, observable problems the ICP experiences, expressed the way a person would complain about
them, not the way a marketer would frame them. "Our attribution is broken across paid channels" is
usable; "suboptimal marketing ROI" is not. Each pain point carries a severity and a frequency
estimate so that scoring can weight them.

### 4.5 Buying intent

The observable signals that separate someone who *has* the problem from someone who is *shopping
for a solution*. Explicit request for a recommendation, dissatisfaction with a named incumbent,
evaluating alternatives, budget/timeline mentioned, asking about pricing, describing a failed
in-house attempt. Each signal gets a weight; these weights feed the confidence score.

### 4.6 Reddit vocabulary

The bridge between marketing language and how people actually type. Slang, abbreviations,
competitor names and their misspellings, tool names, phrases people use when frustrated, and
explicit **negative terms** that indicate a false positive (job postings, "hiring", "promo",
"giveaway"). This is what makes the generated keywords land on real posts instead of press releases.

### 4.7 Subreddit discovery

Candidates come from four independent channels so that no single failure mode blinds the search:

1. LLM proposals from the ICP and personas (high precision, limited recall, may hallucinate).
2. Sitewide `old.reddit.com` search on the vocabulary terms, collecting the subreddits that appear
   in results (high recall, empirically grounded).
3. Sidebar "related subreddits" links from already-validated communities (expands the graph).
4. Author cross-posting — where the authors of high-signal posts also post.

Every candidate is then **validated against live old.reddit HTML**: does it exist, is it public, how
many subscribers, is it active. Hallucinated subreddits die here. Survivors are ranked on
subscriber count, topical relevance, and observed hit density from channel 2.

### 4.8 Keyword generation

For each approved subreddit, generate query strings from the vocabulary and pain points, tagged by
intent tier. Keywords must be valid `old.reddit.com` search syntax and must be deduplicated across
subreddits. The user edits this set at Gate 2.

### 4.9 Scraping

Strictly `old.reddit.com` HTML. No Reddit API, no OAuth, no PRAW — a hard product requirement, and
also a business-continuity one: the tool that dominated this category shut down in 2025 after
failing to obtain a Reddit Data API commercial licence. All traffic exits through the rotating
Webshare proxy pool.

Two collection modes, both reusing the existing client:
- **Listing mode** — `/r/<sub>/new/`, cursor-paginated, for freshness.
- **Search mode** — `/r/<sub>/search?q=...&restrict_sr=on`, for targeting.

Then, for posts that pass a cheap pre-filter, **comment extraction** — the highest-value untapped
source, since the buying-intent signal in a comment thread is often stronger than in the post title.

### 4.10 AI analysis

Every candidate post and comment is analysed to produce structured output: is this a lead at all,
which pain points does it match, which intent signals fire, what stage of the buying journey, what
persona is speaking, a one-line evidence quote, and a suggested angle for engagement.

Cheap deterministic pre-filtering runs first so the LLM only sees plausible candidates. Cost
control is a first-class design constraint, not an optimisation.

### 4.11 Confidence score and ranking

A single 0–100 number the user can sort by, composed from weighted, individually visible
components: AI intent, pain-point match, persona match, recency, engagement, subreddit fit, and the
existing keyword score. **Every component is displayed** — an opaque score users cannot interrogate
will not be trusted, and cannot be tuned.

### 4.12 Dashboard and export

Project-scoped views: the profile/ICP the run was based on, the two review gates, live run
progress, the ranked lead table with evidence, a lead detail drawer, and export to CSV / JSON /
XLSX carrying the AI fields.

---

## 5. Explicit non-goals

| Not building | Why |
|---|---|
| Posting, commenting, or DMing on Reddit | Automated engagement violates Reddit's rules and risks the user's accounts. This is a *discovery* tool. |
| Reddit account login / OAuth | Hard product constraint; also the failure mode that killed the category leader. |
| Multi-user accounts, auth, RBAC | Single-operator self-hosted tool. Adding auth now is speculative complexity. |
| Real-time streaming ingest | Batch + scheduled is sufficient and vastly cheaper. |
| Postgres / Redis / Celery | SQLite + a single worker process meets the load. Documented as a future option, not a phase. |
| A JS build pipeline | The current server-rendered Jinja + inline JS approach works and has zero toolchain cost. |
| Full-site crawling | Bounded page fetch only. |

---

## 6. Success criteria for the finished product

| # | Criterion | Measurement |
|---|---|---|
| 1 | URL → approved subreddits in under 3 minutes | Wall clock, Gate 1 reached |
| 2 | ≥ 70% of AI-proposed subreddits survive live validation | validated ÷ proposed |
| 3 | ≥ 60% of top-20 ranked leads judged genuinely relevant by the operator | manual spot-check of 20 |
| 4 | Zero Reddit API / OAuth / PRAW calls | dependency audit + code grep |
| 5 | 100% of Reddit traffic exits via proxy | request log inspection |
| 6 | Proxy failure of any single IP does not fail a run | kill-one-proxy test |
| 7 | A full run is resumable after process restart | kill worker mid-run, restart |
| 8 | The 459 pre-existing leads remain visible and exportable | row count + CSV diff |
| 9 | LLM cost per full run is known and bounded before the run starts | pre-run estimate vs. actuals |
| 10 | Every score is explainable to the user | UI shows all components |

---

## 7. Principles

1. **Extend, don't rewrite.** `RedditClient`, `LeadScorer`, the `Lead` model, and the dashboard
   shell survive intact. Every new capability is additive.
2. **Backward compatibility is a hard gate.** After every phase the existing DB opens and the
   existing dashboard renders.
3. **Persist before you compute.** Every stage writes its output before the next stage reads it, so
   any stage can be retried in isolation without re-running the ones before it.
4. **Deterministic first, LLM second.** Anything a regex, a set membership test, or a SQL query can
   decide must not cost a token.
5. **Validate LLM output against a schema, always.** An unvalidated JSON blob from a model is an
   outage waiting for a Tuesday.
6. **Fail soft on enrichment, hard on collection.** If the AI analyser fails on one post, that post
   keeps its keyword score and is flagged for retry. If the proxy pool is exhausted, the run stops
   loudly.
7. **Cost is a feature.** Show it, cap it, cache it.
