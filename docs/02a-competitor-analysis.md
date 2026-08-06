# 02a — Competitor Analysis: Tydal & RedShip

> Researched 2026-07-30 from primary sources. The purpose is **not** to copy either product. It is
> to locate the architectural assumptions they share, and to decide deliberately where an internal
> intelligence platform should diverge.

---

## 1. Tydal (tydal.co)

### What it is

An **AI Reddit engagement automation** platform. Finds high-intent threads, then posts replies and
DMs on the user's behalf.

| Dimension | Detail |
|---|---|
| Positioning | "Scans Reddit at scale and jumps straight to threads where people already sound like buyers" |
| Discovery | Continuous subreddit monitoring; user supplies keywords or accepts suggested subreddits |
| Scoring | Numerical thread fit score, 0–10 scale, on "buyer intent and product fit" |
| Engagement | **Public replies + private DMs**, AI-drafted to "feel natural" and on-brand |
| Automation modes | **Autopilot** (aged high-karma accounts post for you) · Chrome extension (approve each send) · Manual |
| Differentiator claimed | Account safety — "your personal account stays private" and protected from bans |
| Secondary angle | Long-tail SEO + "GEO & AI visibility" — replies positioned where search engines and AI models cite them |
| Inbox | Unified view of all outreach conversations, synced via the user's Reddit session |
| Pricing | $99/mo Pro; 100 credits; comment/DM generation 0.1 credits, high-karma account post 10 credits |

### Their AI workflow, as far as it is observable

```
keywords / suggested subreddits
        ↓
continuous scan
        ↓
per-thread intent score (0–10)
        ↓
prioritised feed
        ↓
AI-drafted reply or DM
        ↓
post via aged account / extension / manual
```

### Strengths

1. **Closes the loop.** Discovery through to posted reply in one product. Nothing else on our list does that.
2. **Account-risk framing is a genuine insight.** Reddit bans promotional accounts; renting aged karma is a real answer to a real problem.
3. **SEO/GEO angle is strategically sharp.** A Reddit reply that ranks on Google, or gets cited by an LLM, keeps paying out long after the thread dies.
4. **Credit pricing maps to marginal cost** — 0.1 credits for a generated comment vs 10 for a posted one correctly prices the expensive part.

### Weaknesses

1. **A 0–10 score with no stated basis.** No visible explanation of *why* a thread scored 8. Unexplainable scores cannot be tuned, calibrated, or trusted.
2. **Keyword-first, not understanding-first.** The system is told what to look for. It does not appear to build a deep model of the business.
3. **Automated posting is a durable liability.** Reddit's rules and moderator culture are hostile to it; "aged high-karma accounts" is ban evasion by another name, and the account-safety pitch is an admission that the core mechanic is risky.
4. **Per-credit economics discourage depth.** If analysis costs credits, the product is structurally incentivised to analyse *less*.
5. **No visible quality measurement.** No precision, no false-negative estimate, no calibration.

---

## 2. RedShip (redship.io)

### What it is

A **Reddit monitoring and alerting** platform. Explicitly refuses reply automation.

| Dimension | Detail |
|---|---|
| Positioning | "We automate the search, not your voice" |
| Onboarding | **Add website → platform analyses it to identify keywords worth monitoring** |
| Discovery | Keyword + brand matching across posts and comments sitewide |
| Scoring | "AI relevance scoring" — rates threads before inbox delivery |
| Competitor tracking | Watches competitor mentions to catch "warmest leads" seeking alternatives |
| SEO opportunities | Weekly scans for threads already ranking on Google for target keywords |
| GEO tracking | Weekly scans of ChatGPT, Perplexity, Gemini for brand mentions, with sentiment and frequency |
| Engagement | **Manual only** — by design, citing Reddit bot detection |
| Pricing | Founder $29/mo (1 site, 10 keywords, 3 competitors) · Company $49/mo (3 sites, 30 keywords, 10 competitors) |

### Their AI workflow

```
website URL
        ↓
AI extracts keywords
        ↓
continuous keyword + brand + competitor matching
        ↓
AI relevance score
        ↓
filtered inbox
        ↓
human writes the reply
```

### Strengths

1. **The website-as-input insight is correct** — and is the same starting point we chose. A URL is a far better brief than a keyword list.
2. **Refusing reply automation is principled and probably right.** It protects the user's account and their credibility, and it is a defensible long-term position.
3. **Competitor-mention tracking is high-yield.** Someone asking for an alternative to a named competitor is the warmest possible lead.
4. **AI-visibility tracking is genuinely forward-looking.** Measuring whether LLMs mention you is a real 2026 concern.
5. **Honest, legible pricing.**

### Weaknesses

1. **The website analysis appears to terminate in keywords.** The deep business understanding is used once, then discarded — no reusable ICP, personas, or pain-point model is visible.
2. **Hard keyword and competitor caps** (10 / 30 keywords; 3 / 10 competitors) are commercial packaging that directly limits intelligence.
3. **"AI relevance scoring" is a single opaque number**, same critique as Tydal.
4. **Keyword matching is lexical.** A post that describes the problem without using any tracked keyword is invisible.
5. **No lead-quality feedback loop.** Nothing measures what the filter discarded.

---

## 3. What both share — the architectural assumptions we reject

| Shared assumption | Why it constrains them | What we do instead |
|---|---|---|
| **Keywords are the primary index** | A buyer who describes the pain in their own words, using none of your terms, is never seen | Keywords are one of several channels; matching also runs against pain phrasing, personas, and (P5+) semantic similarity |
| **Website analysis is a means to keywords** | The richest artefact in the system is used once and thrown away | The website becomes a persisted, versioned **Business Knowledge Base** reused by every later stage ([06e](06e-business-knowledge-base.md)) |
| **The score is a single opaque number** | Cannot be tuned, calibrated, audited, or trusted | Deterministic weighted score with **every component stored and displayed** ([06g](06g-explainability-and-quality.md)) |
| **Filtering quality is unmeasured** | Nobody knows what the filter threw away | **Holdout audit** publishes a gate miss rate every run |
| **Per-seat / per-keyword limits** | Commercial packaging caps intelligence | Internal tool — no artificial ceilings; the only limits are cost caps we choose |
| **AI runs on everything that matches** | Cost scales with volume, so depth must be rationed | Local-first funnel; AI runs on ~18% of collected — **and how much is decided per run by the data** ([06f](06f-adaptive-budget.md)) — so depth is affordable where it matters |
| **Engagement is the product** | Optimises for reply volume | **Discovery is the product.** Engagement is an explicit non-goal |

---

## 4. Capability comparison

| Capability | Tydal | RedShip | **This platform** |
|---|:---:|:---:|:---:|
| Website → keywords | ⚠️ implied | ✅ | ✅ |
| Website → **reusable knowledge base** | ❌ | ❌ | ✅ **23-section BKB** |
| ICP generation | ❌ | ❌ | ✅ |
| Buyer personas | ❌ | ❌ | ✅ |
| Pain-point model with customer phrasing | ❌ | ❌ | ✅ |
| Buying-intent signal taxonomy | ⚠️ implicit in score | ⚠️ implicit | ✅ explicit, weighted |
| Competitor intelligence | ❌ | ✅ | ✅ + aliases, entity-resolved |
| Subreddit **discovery** (not just monitoring) | ⚠️ suggestions | ❌ | ✅ 3 channels + live validation |
| Human review gates before scraping | ❌ | ❌ | ✅ two gates |
| Comment-level analysis | ❌ | ⚠️ matching only | ✅ |
| **Explainable lead scoring** | ❌ | ❌ | ✅ **faithful by construction** |
| Confidence calibration | ❌ | ❌ | ✅ |
| **Measured filter quality (miss rate)** | ❌ | ❌ | ✅ |
| Semantic (non-lexical) matching | ❌ | ❌ | ✅ **Phase 4** (BKB vectors) · **Phase 6** (dedup, pre-score) |
| Incremental / cached enrichment | ❌ | ❌ | ✅ $0.00 re-runs |
| Cost transparency | ⚠️ credits | ❌ | ✅ per call, run, day |
| SEO opportunity detection (SERP) | ✅ | ✅ | ⛔ Future — needs a SERP source |
| AI-visibility tracking (GEO) | ✅ | ✅ | ⛔ Future — different product |
| Automated replies / DMs | ✅ | ❌ by design | ⛔ **Permanent non-goal** |
| Unified outreach inbox | ✅ | ⚠️ | ⛔ non-goal |

---

## 5. Where we are meaningfully better — and where we are not

### Genuinely better

1. **Understanding-first, not keyword-first.** Both competitors reduce a business to a keyword list. We build a structured knowledge model and keep it. Every downstream decision — subreddit choice, keyword generation, lead scoring, explanation — reads from it.
2. **Explainability that is faithful by construction.** Our score is a weighted sum over stored components, so the breakdown *is* the computation, not a story told about it afterwards ([06g §2](06g-explainability-and-quality.md)). Neither competitor shows any reasoning.
3. **We measure what we discard.** The holdout audit is, as far as this research shows, unique. Both competitors filter aggressively and publish nothing about what filtering costs them.
4. **Cost architecture permits depth.** At ~$0.03 per 1,000 collected posts we can afford comment-level analysis, re-analysis on prompt changes, and a 2% audit. A per-credit model cannot.
5. **No artificial caps.** 10 keywords and 3 competitors is a pricing decision. We can track 400 keyword variants and every competitor alias because nothing bills us per row.

### Where they are ahead, stated honestly

1. **Tydal closes the loop.** They find *and* act. We deliberately stop at discovery — that is a choice, but it is less complete.
2. **Both ship SEO/GEO tracking.** Real capabilities we do not have. See §6.
3. **Both are far simpler to operate.** Ours has a rule engine, a dedup layer, a gate, an audit, and a knowledge base. That complexity is justified only because intelligence is the objective; it would be indefensible in a $29/mo product.
4. **Tydal's account-safety insight is real** — and it is precisely why we refuse automated engagement rather than solving it.

---

## 6. The SEO / GEO decision

Both competitors ship two adjacent capabilities. Deciding rather than deferring:

| Capability | Verdict | Reasoning |
|---|---|---|
| **SEO/GEO *entities* in the knowledge base** | ✅ **Adopt** | Extracted from the site at zero marginal cost, and they measurably improve keyword generation and competitor matching. They are BKB sections 21–22 ([06e](06e-business-knowledge-base.md)). |
| **SERP-based opportunity detection** (Reddit threads ranking on Google) | ⛔ **Future enhancement** | Requires an external SERP data source — a new paid dependency, new rate limits, new failure modes. Genuinely valuable, but it is a *search* product bolted onto a *Reddit intelligence* product. Recorded with the dependency named. |
| **AI-visibility tracking** (mentions in ChatGPT/Perplexity/Gemini) | ⛔ **Future enhancement** | A different product with a different data source and cadence. Tracking whether an LLM mentions your brand has nothing to do with finding Reddit leads. |

Adopting the entities without the integrations captures most of the value at none of the
dependency cost.

---

## 7. What we deliberately do *not* build

| Not building | Why |
|---|---|
| Automated replies or DMs | Violates Reddit norms, risks the operator's accounts and reputation. Tydal's "aged high-karma accounts" pitch is an admission of the risk. |
| Aged / rented Reddit accounts | Ban evasion. |
| Unified outreach inbox | We are a discovery tool. Engagement happens in Reddit. |
| Reply drafting | The lead's `suggested_outreach_angle` is a *hint for a human*, not a draft to send. |
| Per-seat or per-keyword limits | Internal tool. Artificial scarcity would only reduce our own intelligence. |

The line: **we tell you where to go and why. You decide what to say.**

---

## 8. The design question this research answers

> *"If I were building the most intelligent Reddit Lead Intelligence platform for internal use,
> how would I design it?"*

Neither competitor answers this, because both are optimising for a $29–99/mo subscriber who wants
fewer decisions. Freed from that constraint, the answer inverts on four axes:

| They optimise for | We optimise for |
|---|---|
| Time to first lead | **Depth of business understanding** |
| Fewer user decisions | **Two deliberate human review gates** |
| A simple score | **An explainable, calibrated, auditable score** |
| Cost per subscriber | **Cost per unit of intelligence** — which is why we can afford to analyse comments, re-analyse on prompt change, and audit our own filter |

The resulting shape: **a knowledge base with a Reddit crawler attached**, rather than a Reddit
crawler with keywords attached.
