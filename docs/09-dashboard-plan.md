# 09 — Dashboard Plan

## 1. Design constraints

1. **The existing dashboard must keep working, unchanged, at `/`.** It is the fallback and the
   backward-compatibility proof for the 459 legacy leads.
2. **No build step.** Server-rendered Jinja, inline CSS/JS, Chart.js from CDN. Adding npm/webpack
   would cost more than it returns for a single-operator tool.
3. **The dark theme with `#ff4500` Reddit-orange accents is preserved** — new pages extract the
   existing styles into `base.html` rather than inventing a second visual language.
4. **The review gates are the product.** They get the most design attention, because a gate that is
   tedious to use will be skipped, and a skipped gate means wasted scraping.

---

## 2. Information architecture

```
/                          Legacy dashboard (unchanged) — all leads, existing filters
/projects                  Project list + "New project" URL input
/projects/<id>             Project overview: the Business Knowledge Base + runs
/projects/<id>/edit        Edit Business Knowledge Base sections
/projects/<id>/patterns    What Reddit is telling us — recurring pains, objections, language
/runs/<id>                 Run progress + live event log
/runs/<id>/subreddits      ◄ GATE 1 — review/edit subreddit recommendations
/runs/<id>/keywords        ◄ GATE 2 — review/edit keywords
/runs/<id>/options         Scraping options + cost estimate + confirm
/runs/<id>/leads           Ranked leads for this run
/leads/<id>                Lead detail (drawer over the table; deep-linkable)
/settings                  Application settings
/settings/ai               ◄ AI provider: API key, Test Connection, status, model, usage
/health                    System health
/health/proxies            Proxy pool table
/health/ai                 AI metrics: cost, tokens, cache-hit ratio, repair rate
/health/quality            Accuracy, calibration, efficiency, drift
```

Navigation is a single top bar: **Projects · Legacy Dashboard · Settings · Health**. Deliberately
flat — there are four things, not twelve.

The two pages added by the final review keep it that way: `/projects/<id>/patterns` is reached from
the project page and `/health/quality` from `/health`. **Neither earns a top-level slot**, because
both are read periodically rather than daily, and a nav bar that grows one entry per feature stops
being navigation.

---

## 2a. `/settings/ai` — the AI provider page

The first page a new operator visits, because nothing AI-powered works until it is filled in.

```
┌────────────────────────────────────────────────────────────────────────┐
│  Settings › AI Provider                                                │
│                                                                        │
│  Provider   [ DeepSeek ▾ ]                                             │
│             DeepSeek V4 Flash · OpenAI-compatible · 1M context         │
│                                                                        │
│  ── API key ───────────────────────────────────────────────────────    │
│  ┌──────────────────────────────────────────────┐                      │
│  │ sk-••••••••••••••••••••••••••••••••••a3f9    │  [Replace key]       │
│  └──────────────────────────────────────────────┘                      │
│  Stored encrypted. Never shown in full, never logged, never exported.   │
│                                                                        │
│                                            [ Test Connection ]         │
│                                                                        │
│  ── Status ────────────────────────────────────────────────────────    │
│   ● Connected                                                          │
│   Model              deepseek-v4-flash                                 │
│   Context window     1,000,000 tokens                                  │
│   Last validated     2026-07-30 14:22 UTC  (412 ms)                    │
│   Pricing            $0.14 in · $0.0028 cached · $0.28 out  per 1M     │
│                      verified 2026-07-30 · no peak surcharge active    │
│                                                                        │
│  ── Usage ─────────────────────────────────────────────────────────    │
│   Today          $0.04      1,284 calls      cache hit 91%             │
│   This month     $1.87     48,210 calls      cache hit 89%             │
│   Caps           $2.00 / run    $5.00 / day        [Edit]              │
│                                                                        │
│  ── Advanced ──────────────────────────────────────────────────────    │
│   Model override   [ deepseek-v4-flash ▾ ]  per-stage overrides ▸      │
│   Concurrency      [ 8 ]  adaptive: floor 1, ceiling 16                │
│   Timeouts         connect [10]s   read [60]s                          │
│                                                    [Save]              │
└────────────────────────────────────────────────────────────────────────┘
```

### Status states — all six are designed, not just the happy one

| State | Indicator | Message | Action offered |
|---|---|---|---|
| Not configured | ○ grey | "No API key configured. AI features are disabled; scraping still works." | Enter key |
| Validating | ◐ spinner | "Testing connection…" | — |
| Connected | ● green | Model, context window, latency, last validated | Test again |
| Invalid key (401) | ● red | "DeepSeek rejected this key. Check it was copied completely." | Replace key |
| **Insufficient balance (402)** | ● amber | **"DeepSeek balance exhausted. Add credit to resume AI features."** | Link to DeepSeek billing · Retest |
| Unreachable | ● amber | "Could not reach api.deepseek.com — network or outage. Scraping is unaffected." | Retest |

The 402 state is deliberately amber, not red: **nothing is broken**, the account simply needs
credit. Colouring it as an error would send the operator debugging the wrong thing.

### Test Connection

Issues a minimal 1-token completion (≈$0.0000005) and persists the outcome to
`ai_provider_state`. Renders inline within ~2 s:

```
✓ Connected in 412 ms · deepseek-v4-flash · validated 2026-07-30 14:22 UTC
```

or, on failure, the specific reason and its remedy — never a raw traceback and never a bare
"Error".

### Key handling in the UI

- The field renders a **masked fingerprint**, never the key. There is no reveal control and no API
  that returns plaintext.
- **Replace key** clears the field for fresh entry; the old key is only overwritten after the new
  one validates (unless the operator ticks "save without validating").
- On paste, whitespace is stripped and an obviously malformed key is rejected client-side before a
  network call.
- The masked value updates only after a successful save, so a failed save leaves the working key
  intact.

### Why not a config file

A key in `config.yaml` gets committed, gets copied into a support ticket, and gets shared when the
file is shared. Runtime entry plus encrypted storage means the repository never contains a
credential and there is no file for anyone to accidentally publish. The honest limitation is stated
in the UI: *"Encrypted at rest. On a self-hosted install the decryption key is on this machine, so
this protects a copied database file, not an attacker with server access."*

---

## 3. Page designs

### 3.1 `/projects` — entry point

```
┌────────────────────────────────────────────────────────────────────────┐
│  Reddit Lead Finder                    Projects · Legacy · Health      │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│   Find leads for your product                                          │
│   ┌──────────────────────────────────────────────┐  ┌──────────────┐   │
│   │ https://yourcompany.com                      │  │   Analyse →  │   │
│   └──────────────────────────────────────────────┘  └──────────────┘   │
│   We read your site, build an ICP, and find where your buyers post.    │
│                                                                        │
│   ── Your projects ─────────────────────────────────────────────────   │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ Acme Analytics            acme.com                           │     │
│   │ ● Awaiting subreddit review     3 runs · 412 leads           │     │
│   │                              [Review subreddits →]           │     │
│   ├──────────────────────────────────────────────────────────────┤     │
│   │ Beta Tools                betatools.io                       │     │
│   │ ✓ Complete                      1 run · 87 leads             │     │
│   │                              [View leads →]                  │     │
│   └──────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────┘
```

The card's call-to-action is derived from `run.state`, so the user always lands on the one thing
that needs them. A project blocked at a gate is visually distinct (amber dot) from one that is
running (spinner) or complete (green check).

### 3.2 `/projects/<id>` — the Business Knowledge Base

The 23 sections of the BKB ([06e §2](06e-business-knowledge-base.md)), grouped by the four bands
that describe how each is *used*, because that grouping is what tells an operator which sections are
worth their editing time:

```
┌────────────────────────────────────────────────────────────────────────┐
│  Acme Analytics · acme.com          BKB v3 · 23/23 sections · 3.4k tok │
│                                                     [New run]  [Edit]  │
│  ┌──────────┬─────────────┬───────────────┬──────────────────────────┐ │
│  │ Identity │ Buyer model │ Competitive & │ Activation & discovery   │ │
│  │  (1–6)   │   (7–11)    │ language (12-18)│        (19–23)         │ │
│  └──────────┴─────────────┴───────────────┴──────────────────────────┘ │
│                                                                        │
│  ▣ = in the enrichment prefix (matching surface)   ○ = retrieval-only  │
│                                                                        │
│  ▣ Pain points (7)                            confidence 0.84   [Edit] │
│    attribution-gap        severity 5 · freq 4                          │
│      how people phrase it: "no idea which channel actually converted", │
│      "our attribution is a mess", "last-click is lying to us"          │
│      ▸ evidence: "stop guessing which channel drove the deal"   acme.com/  │
│    tooling-sprawl         severity 3 · freq 5                          │
│    …                                                                   │
│                                                                        │
│  ▣ Competitors (4)                                              [Edit] │
│    Segment      aliases: segment.io, segment io, segement (misspell)   │
│    Dreamdata    aliases: dream data, dreamdata.io                      │
│                                                                        │
│  ○ Outreach angles (11)      used when rendering a lead, not matching  │
│                                                                        │
│  ⚑ 3 pending knowledge suggestions                            [Review] │
│  ⏱ Personas verified 94 days ago                            [Review ▾] │
│                                            [Regenerate section ▾]      │
└────────────────────────────────────────────────────────────────────────┘
```

Sections carry an age state ([06h §2](06h-knowledge-lifecycle.md)) — `fresh` shows nothing,
`ageing` a subtle marker, `stale` an amber badge with a suggested action. **Group C sections
(competitors, customer language, terminology, objections, signals) never show an age badge at all**,
because they accrete continuously from Reddit and are getting *fresher*, not older. Badging them
would invite exactly the regeneration that would delete what they learned.

Every row also shows its **origin** — `website`, `reddit-learned`, or `operator` — as a small
inline marker. That is what makes the `Regenerate` button honest: it visibly touches only the
`website` rows, so an operator can see in advance what a regeneration will and will not replace.

**Design decisions:**

- **The prefix marker (`▣` / `○`) is shown, not hidden.** A section in the enrichment prefix
  directly affects every lead's classification; a retrieval-only section affects only how a lead is
  *presented*. An operator editing pain phrasings should know they are changing matching behaviour,
  and an operator editing outreach angles should know they are not.
- **The evidence line is not decoration.** Every claim links to the verbatim site phrase and page it
  came from. If the evidence looks wrong, the section is wrong, and that is visible in two seconds
  rather than three stages later.
- **Aliases are shown with the competitor.** They are the highest-yield matching asset in the system
  ([06e §4](06e-business-knowledge-base.md)) and the thing an operator can most usefully add to.
- **Sections regenerate independently.** Regenerating personas must not discard a hand-edited
  competitor registry — they have different lifetimes and different evidence. Edits set
  `bkb_sections.edited_by_user = 1`, and a regenerate warns before overwriting.
- **Pending suggestions are surfaced here, never auto-applied** ([06e §7](06e-business-knowledge-base.md)).
  Each shows the lead and span that produced it. This is the same review-gate philosophy that governs
  subreddits and keywords, applied to the knowledge model itself.
- **The token count is displayed** because it is a real operating constraint: a prefix that grows
  past its budget dilutes batch attention (R23), and an operator adding forty pain phrasings should
  see the number move.

### 3.3 `/runs/<id>/subreddits` — Gate 1

The most important screen in the product.

```
┌────────────────────────────────────────────────────────────────────────┐
│  Review subreddits                              Step 1 of 3 ●○○        │
│                                                                        │
│  We found 23 candidates and validated 18. Pick the ones worth          │
│  scraping — you can add your own.                                      │
│                                                                        │
│  ✓ 12 selected        [Select all] [Select none] [Select top 10]       │
│                                                                        │
│  ☑ r/SaaS                                    182,400 members   ▲ 0.91  │
│    Discussion for SaaS founders and operators                          │
│    found by: AI · search (14 hits) · sidebar          [why? ▾]         │
│  ─────────────────────────────────────────────────────────────────     │
│  ☑ r/marketing                               1,240,000 members ▲ 0.74  │
│    found by: AI · search (6 hits)                     [why? ▾]         │
│  ─────────────────────────────────────────────────────────────────     │
│  ☐ r/PPC                                      98,300 members   ▲ 0.68  │
│    found by: search (9 hits)                          [why? ▾]         │
│  ─────────────────────────────────────────────────────────────────     │
│                                                                        │
│  Rejected (5)  ▾                                                       │
│    r/AttributionOps — not found (AI-proposed, does not exist)          │
│    r/b2bsaasgrowth — only 340 members (below minimum)                  │
│    r/growthhacking_ — private                                          │
│                                                                        │
│  + Add a subreddit:  [r/________________]  [Add]                       │
│                                                                        │
│                            [Regenerate]      [Continue to keywords →]  │
└────────────────────────────────────────────────────────────────────────┘
```

**Design decisions:**
- **The rejected list is shown, collapsed, with reasons.** This is the hallucination-transparency
  feature. Seeing "r/AttributionOps — does not exist" builds more trust than never mentioning it,
  and it is the operator's early warning that the ICP may be off.
- **`found by:` is the multi-channel provenance.** A subreddit found by all three channels is a
  much stronger signal than one the model merely suggested, and the user can see that.
- **`[why? ▾]`** expands the full ranking breakdown (all five components with their values) — the
  explainability requirement.
- **`[Select top 10]`** is the fast path. Most users will use it. The per-row checkboxes exist for
  the ones who care.
- Manually added subreddits are validated on `Add` (live fetch) and show an inline error if they
  don't exist, rather than failing silently during the scrape an hour later.
- **`Continue` is disabled at zero selections**, with an inline explanation.

### 3.4 `/runs/<id>/keywords` — Gate 2

```
┌────────────────────────────────────────────────────────────────────────┐
│  Review keywords                                Step 2 of 3 ●●○        │
│                                                                        │
│  ┌ Applies to all subreddits ────────────────────────── 8 keywords ─┐  │
│  │  HIGH   ☑ "attribution is broken"           ☑ "best alternative  │  │
│  │         ☑ "which attribution tool"             to segment"       │  │
│  │  MED    ☑ "can't track conversions"         ☑ "struggling with   │  │
│  │         ☑ "multi touch attribution"            attribution"      │  │
│  │  + Add: [_____________________] tier [high ▾]  [Add]             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌ r/SaaS ──────────────────────────────────────────── 6 keywords ──┐  │
│  │  HIGH   ☑ "marketing attribution saas"  ☐ "roi tracking tool"    │  │
│  │  …                                                               │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌ Exclude posts containing ────────────────────────── 7 terms ─────┐  │
│  │  ☑ hiring   ☑ [for hire]   ☑ giveaway   ☑ promo code             │  │
│  │  ☑ weekly thread   ☑ AMA   ☑ roast my                            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  32 keywords × 12 subreddits ≈ 384 searches ≈ 28 min                   │
│                                                                        │
│                              [Regenerate]      [Continue to options →] │
└────────────────────────────────────────────────────────────────────────┘
```

**Design decisions:**
- **The negative-term panel is on this page, not buried in settings.** It is the highest-leverage
  precision control and the user will only tune it if they can see it at the moment they are
  thinking about keywords.
- **The live estimate line updates as boxes are ticked.** Showing "≈28 min" before committing is
  what makes an unchecked 384-search run the user's decision rather than a surprise.
- Grouping by subreddit with a shared "applies to all" group avoids the 384-row flat list that
  nobody would read.

### 3.5 `/runs/<id>/options` — the commit point

```
┌────────────────────────────────────────────────────────────────────────┐
│  Scraping options                               Step 3 of 3 ●●●        │
│                                                                        │
│  Time window     ( ) Past week  (•) Past month  ( ) Past year  ( ) All │
│  Sort            (•) Newest     ( ) Most relevant  ( ) Top             │
│  Results/keyword [100 ▾]                                               │
│                                                                        │
│  ☑ Also scrape comments   (much better signal, ~2× slower)             │
│      Max comments per post  [30]                                       │
│      Only posts with ≥ [3] comments, up to [100] posts                 │
│                                                                        │
│  ☑ Analyse with AI                                                     │
│      Model  [deepseek-v4-flash ▾]     Cost cap  [$2.00]                │
│                                                                        │
│  ── AI coverage ───────────────────────────────────────────────────    │
│   ( ) Thorough   296 candidates   ~$0.043   miss rate <2%              │
│   (•) Balanced   214 candidates   ~$0.031   miss rate <5%              │
│   ( ) Frugal     128 candidates   ~$0.019   miss rate <12%             │
│                                                                        │
│   How 214 was decided        knee detection                            │
│     Knee at rank 214 (pre-score 29.4) · floor ≥25 allowed 268          │
│     Clamps [17, 296] not binding                                       │
│     A fixed ≥35 cut would admit 180 — the knee shows the curve is      │
│     still steep below 35, so 34 more are worth analysing.              │
│                                                                        │
│   Rejected items are audited on a 2% sample, so the "miss rate"        │
│   above is measured after the run, not assumed.                        │
│                                                                        │
│  ── Estimate ──────────────────────────────────────────────────────    │
│    Scraping        ~390 requests      ~33 min                          │
│    Collected       ~1,200 items → 329 candidates                       │
│    To analyse      ~217 items         (214 admitted + 3 audit)         │
│    AI calls         ~28               (batches of 8)                   │
│    AI cost          $0.031 – $0.040   (hot – cold cache)   cap $2.00   │
│                                                                        │
│                                        [Back]    [Start scraping →]    │
└────────────────────────────────────────────────────────────────────────┘
```

**The three coverage modes express appetite; the data decides the count.** Each number above is
computed from *this run's* pre-score distribution ([06f](06f-adaptive-budget.md)), not from a stored
percentage — so what the operator sees is what those modes would really do on this data, not an
average over runs that never happened.

**The "how 214 was decided" block is the part that must not be dropped for tidiness.** An automated
decision the operator cannot interrogate is one they will eventually work around — usually by
picking `thorough` every time to be safe, which defeats the whole mechanism. Showing the knee, the
floor, the clamps, and the fixed-cut counterfactual keeps the automation reviewable.

The `miss rate` column is what makes the trade honest: it is **measured** by the holdout audit after
every run ([06c §6](06c-local-first-pipeline.md)), not asserted here.

The estimate shows a **range**, not a point, because DeepSeek's caching is best-effort — a run
quoting $0.03 and billing $0.11 because the cache was cold would destroy trust in every later
estimate.

Every toggle recomputes the estimate live. The user commits with full knowledge of time and cost —
this is the difference between a tool that feels controllable and one that feels like a slot machine.

### 3.6 `/runs/<id>` — progress

```
┌────────────────────────────────────────────────────────────────────────┐
│  Run #14 · Acme Analytics                            ⏸ Pause  ✕ Cancel │
│                                                                        │
│  ████████████████████████░░░░░░░░░░░  62%                              │
│  Scraping r/marketing (8 of 12)                                        │
│                                                                        │
│  Leads found  247      Requests  241/390     AI cost  $0.006           │
│  Elapsed  18m 22s      ETA  ~11m             Proxies  9/10 healthy     │
│                                                                        │
│  ── Funnel ────────────────────────────────────────────────────────    │
│   1,240 collected → 282 passed filters → 179 admitted → 24 AI calls    │
│   rejected: 318 already analysed · 186 negative · 142 near-dup ·       │
│             94 noise · 61 short · 38 bot · 27 window                   │
│                                                                        │
│  ── Activity ──────────────────────────────────────────────── live ──  │
│  18:42:11  r/marketing  page 3 · 25 items · 6 new                      │
│  18:41:58  r/marketing  page 2 · 25 items · 11 new                     │
│  18:41:12  ⚠ proxy 198.105.121.200:6462 blacklisted (403) for 30m      │
│  18:40:55  r/SaaS  done · 187 posts · 23 leads · 3m 34s                │
│  …                                                                     │
└────────────────────────────────────────────────────────────────────────┘
```

Polls `GET /api/runs/<id>/progress` every 3 s. `run_events` is the activity feed. Warnings are
inline and amber — the operator sees proxy trouble as it happens instead of discovering an empty
result set later.

### 3.7 `/runs/<id>/leads` — the payoff

```
┌────────────────────────────────────────────────────────────────────────┐
│  Leads · Acme Analytics · Run #14                    [Export ▾]        │
│                                                                        │
│  [search…] [subreddit ▾] [status ▾] [intent stage ▾] [min conf: 40]    │
│  [pain point ▾] [persona ▾]                        Sort: Confidence ▾  │
│                                                                        │
│  CONF  TITLE                                  r/       INTENT   STATUS │
│  ┌───┐                                                                 │
│  │ 92│ Our attribution is completely broken   SaaS    evaluating  new ▾│
│  │   │ after the iOS update — what are you…                            │
│  │   │ 💬 "we're actively looking to replace Segment this quarter"     │
│  │   │ 🎯 attribution-gap · tool-migration   👤 Growth Lead            │
│  ├───┤                                                                 │
│  │ 78│ Anyone using Dreamdata? Worth it?      B2BSaaS solution_  new ▾ │
│  │   │                                               aware             │
│  ├───┤                                                                 │
│  │ 61│ How do you attribute self-serve signups PPC   problem_   new ▾  │
│  │   │                                               aware             │
│  └───┘                                                                 │
│                                     ‹ 1 2 3 4 5 ›   showing 1-25 of 247│
└────────────────────────────────────────────────────────────────────────┘
```

**Design decisions:**
- **The evidence quote is on the row, not hidden in a detail view.** It is the single fastest way
  for a human to judge a lead, and putting it one click away halves the triage rate.
- Confidence is a colour-graded badge (≥75 green, ≥50 amber, below red), extending the existing
  score-badge pattern rather than replacing it.
- New filters — intent stage, pain point, persona, min confidence — are the ones the AI made
  possible. All existing filters are preserved.
- **NULL confidence sorts last, not first.** An unanalysed lead is not a zero-confidence lead.

### 3.8 `/leads/<id>` — detail drawer

Slides in from the right; deep-linkable so a lead can be shared.

```
│  Our attribution is completely broken after the iOS update      ✕     │
│  r/SaaS · u/growthlead_mk · 2 days ago · ▲ 47 · 💬 23                 │
│  [Open on Reddit ↗]                                                   │
│                                                                       │
│  ── Why this scored 92 ──────────────────────────────────────────     │
│   Intent (evaluating)     0.85 × 0.28 = 23.8                          │
│   Pain match (2 of 3)     0.67 × 0.20 = 13.4                          │
│   Buying signals (2)      0.90 × 0.16 = 14.4                          │
│   Keyword score (38)      0.76 × 0.12 =  9.1                          │
│   Persona (Growth Lead)   1.00 × 0.10 = 10.0                          │
│   Recency (2 days)        0.93 × 0.06 =  5.6                          │
│   Engagement              0.71 × 0.05 =  3.6                          │
│   Subreddit fit           0.91 × 0.03 =  2.7                          │
│                                       ───────────                     │
│                                            82.6 → 92 (signal boost)   │
│                                                                       │
│  ── What matched ────────────────────────────────────────────────     │
│   ICP           mid-market B2B SaaS         partial fit               │
│   Persona       Growth Lead ↗                                         │
│   Pain points   attribution-gap ↗ · tooling-sprawl ↗                  │
│   Features      multi-touch attribution ↗   (local match)             │
│   Language      "which channel actually converted"  (local match)     │
│   Signals       evaluating-alternatives (T1) · stated-timeline (T2)   │
│   Keywords      cluster: attribution-tools                            │
│   Competitor    Segment ↗   matched surface form "Segment"            │
│                                                                       │
│  ── AI analysis ─────────────────────────────────────────────────     │
│  Evidence  "we're actively looking to replace Segment this quarter"   │
│  Why       Evaluating alternatives with a stated timeline and a       │
│            named incumbent; matches the growth-lead persona and       │
│            the attribution-gap pain.                                  │
│  Angle     Lead with the iOS-attribution gap; they have already       │
│            diagnosed the problem and are shopping.                    │
│                                                                       │
│  ── Post ────────────────────────────────────────────────────────     │
│  <full body>                                                          │
│                                                                       │
│  ── Comments (23) ───────────────────────────── 4 flagged as leads    │
│  ▲12  u/dataops_sam                                    conf 71        │
│      "same here, we ripped out Segment in March…"                     │
│  …                                                                    │
│                                                                       │
│  Status [new ▾]   [Re-analyse]   [Delete]                             │
```

**The score breakdown is the trust mechanism.** A user who disagrees with a 92 can see exactly which
component produced it and go change that weight. This is what makes the scoring system tunable
rather than magic.

**The "What matched" panel is the ten explanation fields** from
[06g §2](06g-explainability-and-quality.md), and three properties of it are deliberate:

1. **Every `↗` is a link back into the Business Knowledge Base.** Clicking `attribution-gap` opens
   that pain as the BKB defines it, with the site sentence it was derived from. The operator can
   follow the whole chain — *website sentence → pain definition → Reddit phrasing → score component*
   — which is auditability end to end, and is only possible because these are first-class entities
   rather than strings.
2. **Fields marked "(local match)" cost nothing.** Five of the ten are computed by deterministic
   index lookups, not by the model. Labelling them keeps the distinction visible: an operator
   debugging a bad match needs to know whether to fix a prompt or a phrase list.
3. **The competitor row shows the *surface form* alongside the canonical entity.** When
   `"segement"` resolves to `Segment`, seeing both is what lets an operator confirm the resolution
   was right — and, when it was wrong, confirm it from the alias table rather than by guessing.

#### Researcher view

Because this is an internal platform we can show researchers material a commercial product would
hide, and **all of it is already stored** — the cost is UI, not architecture
([06i §6](06i-feedback-and-memory.md)). Behind a per-user toggle, off by default:

| Revealed | Answers |
|---|---|
| Full evidence chain: Reddit span → pain → BKB section → website span | *Is this match real?* — judged in seconds instead of reading the thread |
| Every score component with its weight and raw value | *Which dial is wrong?* |
| Confidence history for this lead | *Did re-analysis change the verdict, and when?* |
| Pattern history for each matched entity | *"This objection has appeared 14 times since April"* |
| Pinned `bkb_id` / `prompt_version` / `weights_version` / `ruleset_version` | *Why does an old lead look different from a new one?* |
| Analysis tier, cost, cache status | *What did this actually cost?* |

**It is a toggle rather than an expansion of the default view, and that is the point.** The default
answers *"should I act on this?"*; the researcher view answers *"why does the system think so, and
is the system right?"* Those are different questions from different people at different times, and
a panel that tries to answer both at once answers neither. A debug dump would be worse than the
curated view it replaced.

**`Why` is the only free-prose field**, capped at 240 characters and validated to reference nothing
outside the eight matched-entity fields above it. It cannot introduce a claim the panel does not
already support, which is what makes the explanation faithful rather than merely fluent
([AD-15](03-architecture.md)).

**Status changes write `lead_labels`.** Marking a lead `interested` or `not relevant` is not just
housekeeping — it is the ground truth behind precision, ECE calibration, and the yield curve that
tunes the adaptive budget. The label control therefore appears on both the drawer and the list row,
because a metric suite whose input requires extra clicks is a metric suite that starves.

**`not_relevant` asks one follow-up question**, a single-click reason chip:

```
Not relevant — why?   [wrong persona] [wrong pain] [not a buyer]
                      [competitor staff] [too old] [other]
```

Optional, one click, dismissible. The reason is worth more than the label
([06i §2.2](06i-feedback-and-memory.md)): an undifferentiated rejection lowers a number, whereas
`wrong_persona` five times about the same persona is evidence the **persona definition** is wrong —
a knowledge problem routed to the suggestions queue rather than to the scorer. Making it optional
matters: a required field would make labelling slower, and labels the operator does not give are
worth nothing at all.

**Audit-sourced leads carry a visible badge:**

```
r/SaaS · 6d · 12↑ 3💬          🔍 found by filter audit          41
```

These are the 2% of *rejected* candidates the holdout audit enriched anyway
([06c §6.1](06c-local-first-pipeline.md)). They appear in the list, score normally, and are
labellable like any other lead — which is the entire point. Their labels are the only signal the
system ever receives from below the admission cut, and without them the yield curve would learn
nothing but the shape of its own gate. The badge is there so an operator understands why a
lower-scoring lead is in front of them, not to discount it.

---

### 3.8a `/projects/<id>/patterns` — what Reddit is telling us

The read-only face of pattern discovery ([06h §6](06h-knowledge-lifecycle.md)). Pure SQL over
`lead_analysis`; **zero AI cost.**

```
┌───────────────────────────────────────────────────────────────────────┐
│  What Reddit is telling us              Acme Analytics · last 90 days │
│  ┌──────┬────────────┬─────────────┬──────────┬─────────────────────┐ │
│  │ Pains│ Objections │ Competitors │ Language │ Buying triggers     │ │
│  └──────┴────────────┴─────────────┴──────────┴─────────────────────┘ │
│                                                                       │
│  ● known    attribution-gap          41 leads · 28 groups   ▲ rising  │
│  ● known    tooling-sprawl           19 leads · 14 groups   ─ flat    │
│  ○ NEW      "spreadsheet fallback"    7 leads ·  5 groups   ▲   [+]   │
│  ○ NEW      "procurement blocked it"  4 leads ·  3 groups       [+]   │
│  · below threshold  "audit season"    2 leads ·  1 group             │
│                                                                       │
│  ● in the knowledge base   ○ candidate   · not yet enough evidence    │
└───────────────────────────────────────────────────────────────────────┘
```

Three design points, each load-bearing:

- **Groups, not leads, are the count that matters.** The badge shows both, but the threshold tests
  *distinct dedup groups* — one viral thread and its forty reposts contribute 1. Showing only the
  lead count would let the loudest thread look like a trend.
- **Below-threshold rows are visible, greyed, and not actionable.** Hiding them would make the
  system look like it had found nothing; showing them with a `[+]` button would let an operator
  promote a single observation into permanent knowledge, which is what
  [06h §4.2](06h-knowledge-lifecycle.md) forbids.
- **`known` rows are the more useful half.** A pain already in the BKB rising from 19 to 41 mentions
  is a market signal, not a discovery. Splitting the page into "new stuff" and "everything else"
  would bury it.

`[+]` opens the same Knowledge Suggestions review as everywhere else. There is exactly one write
path into the knowledge base from Reddit, and this page uses it rather than adding a second.

---

### 3.9 `/health/quality` — is the system still right?

The four bands of [06g §6](06g-explainability-and-quality.md), on one page:

```
┌───────────────────────────────────────────────────────────────────────┐
│  Quality                                     Acme Analytics ▾   30d ▾ │
│                                                                       │
│  ACCURACY                                             214 labels      │
│   Precision @70   0.81 ▲.03      False positives      0.19            │
│   Gate miss rate  3.1%  ✓        Worst reason  negative_term (7/22)   │
│                                                                       │
│  CALIBRATION                                                          │
│   ECE 0.07 ✓   Brier 0.14        [reliability diagram]                │
│   Band 90–100 observed 0.84 — slightly overconfident                  │
│                                                                       │
│  EFFICIENCY                                                      7d   │
│   Cache hit 68% ✓  Calls/1k 23  Cost/run $0.030  P95 78s             │
│   Month $1.84 / $5.00                                                 │
│                                                                       │
│  DRIFT                                                                │
│   Golden F1 0.87 (v4, unchanged)   PSI 0.08 ✓   Repair 1.2%          │
│   Hallucinated spans 0.4%          Last golden run 2d ago             │
└───────────────────────────────────────────────────────────────────────┘
```

- **Every number links to the query that produced it.** A quality metric an operator cannot drill
  into is a number they will eventually stop believing.
- **Under-powered metrics say `insufficient data`, never a number.** ECE below 100 labels is noise
  with a confident interface, and a metric that lies when under-powered is worse than a missing one.
- **The page states the action, not just the value.** A red ECE shows *"recalibrate"*, not
  *"reweight"* — the two have different consequences for the ranking, and the distinction is easy to
  get wrong under pressure ([06g §7](06g-explainability-and-quality.md)).

---

## 4. API surface

### 4.1 Preserved verbatim

All 17 existing endpoints keep their paths, methods, request shapes, and response shapes.
`routes.py` is not rewritten; new endpoints go in new blueprints. This is a **hard rule** verified
by a contract test that replays recorded requests against the new build.

### 4.2 New endpoints

**Projects**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/projects` | List with run state and lead counts |
| `POST` | `/api/projects` | `{url, name?}` → creates project + run, enqueues `analyze_website` |
| `GET` | `/api/projects/<id>` | Project + BKB summary (version, status, section count) |
| `PUT` | `/api/projects/<id>` | Rename / archive |
| `DELETE` | `/api/projects/<id>` | Cascades; leads get `project_id = NULL` (not deleted) |

**Business Knowledge Base**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/projects/<id>/bkb` | Current BKB: version, status, prefix tokens, all 23 sections |
| `GET` | `/api/projects/<id>/bkb/sections/<key>` | One section + its evidence |
| `PUT` | `/api/projects/<id>/bkb/sections/<key>` | Operator edit; sets `edited_by_user`, bumps section version |
| `POST` | `/api/projects/<id>/bkb/sections/<key>/regenerate` | Single-section job; warns if `edited_by_user` |
| `GET` | `/api/projects/<id>/bkb/entities` | Entities + aliases (filterable by `kind`) |
| `POST` | `/api/projects/<id>/bkb/entities/<eid>/aliases` | Add an alias by hand |
| `GET` | `/api/projects/<id>/bkb/suggestions` | Pending proposals + evidence |
| `POST` | `/api/projects/<id>/bkb/suggestions/<sid>` | `{decision: accept\|reject}` — **the only path by which learned knowledge is applied** |
| `GET` | `/api/projects/<id>/bkb/prefix` | The rendered matching surface + token count (debugging R23) |
| `GET` | `/api/projects/<id>/bkb/freshness` | Per-section `last_verified_at`, threshold, derived state, `origin` mix |
| `GET` | `/api/projects/<id>/patterns` | Recurring pains, objections, competitors, language; filter `in_bkb`, `min_groups` |

**Runs**

| Method | Route | Notes |
|---|---|---|
| `POST` | `/api/projects/<id>/runs` | New run on an existing project |
| `GET` | `/api/runs/<id>` | Full run object |
| `GET` | `/api/runs/<id>/progress` | **Poll target.** `RunProgress`. Must be < 50 ms. |
| `GET` | `/api/runs/<id>/events?after=<id>` | Incremental activity feed |
| `POST` | `/api/runs/<id>/cancel` | |
| `POST` | `/api/runs/<id>/retry` | From `FAILED` |
| `GET` | `/api/runs/<id>/estimate` | Requests, minutes, items, USD — for the options screen |

**Gates**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/runs/<id>/subreddits` | Candidates incl. rejected + reasons |
| `POST` | `/api/runs/<id>/subreddits` | Manually add; **validates live**, 422 if it doesn't exist |
| `PUT` | `/api/runs/<id>/subreddits/<sid>` | Toggle approved/rejected |
| `POST` | `/api/runs/<id>/approve-subreddits` | `{ids[]}` → advances the state machine |
| `GET`/`POST`/`PUT`/`DELETE` | `/api/runs/<id>/keywords[/<kid>]` | Same shape |
| `POST` | `/api/runs/<id>/approve-keywords` | `{ids[]}` |
| `POST` | `/api/runs/<id>/options` | `RunOptions` → starts scraping |

**Leads and analysis**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/leads` (extended) | New query params: `project_id`, `run_id`, `min_confidence`, `intent_stage`, `pain_slug`, `persona_slug`, `sort=confidence` |
| `GET` | `/api/leads/<id>/detail` | Lead + analysis + **all 10 explanation fields with entity refs** + score breakdown + comments |
| `POST` | `/api/leads/<id>/analyze` | Sync re-analysis of one lead |
| `PUT` | `/api/leads/<id>/label` | `{label, reason?, note?}` → `lead_labels`. **Feeds precision, ECE, the yield curve, and knowledge suggestions.** |
| `POST` | `/api/leads/<id>/deepen` | Request Tier 2 analysis for one lead ([06i §3](06i-feedback-and-memory.md)); respects the run's Tier 2 cap |
| `GET` | `/api/leads/export` (extended) | `format=csv\|json\|xlsx`; **default `csv` with the original 13 columns** |

**Budget and quality**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/runs/<id>/budget` | The `ai_budgets` row: admitted, `method`, knee rank, floor, clamps, fixed-cut counterfactual |
| `GET` | `/api/quality?project_id=&window=` | The four bands rendered on `/health/quality`; under-powered metrics return `insufficient_data`, never a number |
| `GET` | `/api/quality/calibration` | Reliability-diagram bins + active `calibration_map` |
| `GET` | `/api/quality/golden` | Golden-run history by prompt version, with pass/fail |
| `POST` | `/api/quality/golden/run` | Trigger a golden-set regression (also runs automatically on prompt/model change) |

**AI provider settings**

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/settings/ai` | Provider, status, masked fingerprint, model info, last validation, caps. **Never the key.** |
| `PUT` | `/api/settings/ai/key` | `{api_key}` — validates, then stores encrypted. 422 with the specific reason on failure. |
| `DELETE` | `/api/settings/ai/key` | Clears the key; AI disabled |
| `POST` | `/api/settings/ai/test` | Test Connection → `{ok, model, context_window, latency_ms, validated_at, error?}` |
| `PUT` | `/api/settings/ai/config` | Model overrides, concurrency, timeouts, caps |
| `GET` | `/api/settings/ai/providers` | Registry descriptors — drives the provider dropdown |
| `GET` | `/api/ai/usage?period=today\|month\|run\|project` | Cost, tokens, calls, cache-hit ratio |

**Health**

| Method | Route |
|---|---|
| `GET` | `/health` |
| `GET` | `/health/proxies` |
| `GET` | `/health/ai` |
| `GET` | `/health/quality` |
| `GET` | `/health/metrics` |

`/health/ai` renders the metrics that predict cost problems before the invoice does:

```
Provider   deepseek · deepseek-v4-flash · ● connected (validated 22 min ago)
Cost       today $0.04 · month $1.87 · caps $2.00/run · $5.00/day · 500 calls/run

 EFFICIENCY
 Calls per 1,000 posts  23    ██████░░░░░░░░░░░░░░░   target ≤ 30
 Gate reduction        82%    ████████████████░░░░░   informational — NOT a target
 Near-dup collapse     14%    ████░░░░░░░░░░░░░░░░░   target > 8%
 Cache hit ratio       91%    ████████████████████░   target > 85%
 Response cache hits   34%    ███████░░░░░░░░░░░░░░

 QUALITY
 Gate miss rate       3.1%    █░░░░░░░░░░░░░░░░░░░░   target < 5%
 Hallucinated spans   0.4%    ░░░░░░░░░░░░░░░░░░░░░   target < 2%
 Batch mismatch rate  0.2%    ░░░░░░░░░░░░░░░░░░░░░   target < 1%
 Repair rate          2.1%    █░░░░░░░░░░░░░░░░░░░░   target < 5%
 Empty-content rate   0.4%    ░░░░░░░░░░░░░░░░░░░░░   target < 2%

 ADAPTIVE BUDGET                                    last 20 runs
 Method    knee 12 · knee+floor 5 · knee+marginal 2 · clamped 1
 Clamps bound on        5%    █░░░░░░░░░░░░░░░░░░░░   target < 10%
 Prefix size          3.4k    of 4.0k budget · 0 sections dropped

 THROUGHPUT
 Mean latency         1.8s    p95 4.2s
 Batch size              8    adaptive 4–12 (measured ceiling)
 Concurrency             8    adaptive · no throttling in last hour
```

The page is split **efficiency / quality / budget / throughput** on purpose. Efficiency metrics
without quality metrics beside them would let an operator tune the gate down until the product
quietly stopped working. **Gate miss rate is the counterweight to gate reduction**, and they are
read together.

**Gate reduction is deliberately labelled "not a target."** Under adaptive budgeting the admitted
count is an *output* of the data, not a dial — a run whose distribution is genuinely strong
*should* show lower reduction, and treating that as a regression would push an operator to
re-introduce exactly the fixed cut [06f](06f-adaptive-budget.md) removed. Optimising a number the
system is supposed to derive is how a good mechanism gets defeated by its own dashboard.

The **Adaptive Budget** band exists so the mechanism stays inspectable in aggregate, not just per
run. The method histogram answers the question that actually matters — *is the knee doing the work,
or are the clamps?* If `clamped` ever dominates, the knee detector or the pre-score needs attention,
and no per-run view would have shown it.

A cache-hit ratio below target is rendered in red with the explanation
*"prompt prefix is not matching — costs may be up to 50× the estimate."* That single line is the
difference between noticing a misconfiguration today and noticing it on a bill.

### 4.3 Conventions

- Errors: `{"error": "message", "code": "machine_readable"}` — extends the existing `{"error": ...}`
  shape additively so existing clients still parse.
- Validation failures: `422` with `{"error", "field", "code"}`.
- State-machine violations: `409` with the current and attempted states.
- All list endpoints paginate (`page`, `per_page`, max 200).

---

## 5. Frontend implementation

### 5.1 Template structure

`base.html` extracts the existing `<head>`, CSS block, and container from `index.html`.
**`index.html` is then rewritten to `{% extends "base.html" %}` with byte-identical rendered
output** — verified by a snapshot test that diffs the rendered HTML before and after.

New CSS is appended, never edited in place:

```css
/* additions only — existing rules untouched */
.conf-badge      { … }
.conf-high       { background:#1a472a; color:#4ade80; }
.conf-med        { background:#4a3728; color:#fbbf24; }
.conf-low        { background:#3b2828; color:#f87171; }
.evidence-quote  { border-left:3px solid #ff4500; padding-left:10px; color:#bbb;
                   font-style:italic; font-size:.85rem; }
.gate-card       { … }
.progress-bar    { … }
.score-breakdown { display:grid; grid-template-columns:1fr auto auto; gap:4px 12px; }
```

### 5.2 JavaScript

Vanilla, in `<script>` blocks, matching the existing style. Three shared helpers:

```javascript
async function api(method, url, body) {
  const r = await fetch(url, {method, headers:{'Content-Type':'application/json'},
                              body: body ? JSON.stringify(body) : undefined});
  if (!r.ok) throw new ApiError(await r.json().catch(() => ({error: r.statusText})), r.status);
  return r.status === 204 ? null : r.json();
}

function poll(url, onUpdate, intervalMs = 3000) { /* setInterval + stop condition + backoff on error */ }

function toast(msg, kind = 'info') { /* replaces the current silent-failure alert()s */ }
```

**Polling discipline:** stop when `state` is terminal; back off to 10 s after three consecutive
errors; stop entirely when `document.hidden` and resume on `visibilitychange`. Without this, a
forgotten browser tab polls a dead run forever.

### 5.3 Accessibility and robustness

- Every interactive control is a real `<button>` or `<input>`, keyboard reachable.
- Colour is never the only signal — the confidence badge shows the number, not just a colour.
- All destructive actions confirm (already the pattern for lead delete).
- Every AJAX failure surfaces a toast. **The current code fails silently on several endpoints**,
  which is a real usability defect worth fixing while we are here.
- Long tables use `content-visibility: auto` rather than virtual scrolling — a one-line CSS fix that
  handles 2,000 rows without a framework.

---

## 6. Export

| Format | Contents |
|---|---|
| **CSV (default)** | **The existing 13 columns, unchanged**, plus 8 appended: `Confidence`, `Intent Stage`, `Pain Points`, `Signals`, `Persona`, `Evidence`, `Suggested Angle`, `Project`. Appending keeps existing importers working. |
| JSON | Full nested objects: lead + analysis + breakdown + comments |
| XLSX | Two sheets — `Leads` (formatted, conditional colour on confidence) and `Summary` (run parameters, counts, cost) |

Export honours every active filter, as it does today. XLSX adds an `openpyxl` dependency — already
a transitive dependency of nothing else, so it is a genuine addition and is justified by the fact
that the operator's downstream consumer is a spreadsheet.

---

## 7. Phasing of UI work

| Phase | UI delivered |
|---|---|
| 1 | **`/settings/ai`** — key entry, Test Connection, all six status states, usage, caps; `/health/ai` |
| 2 | `/health/proxies` (proxy pool table) |
| 3 | `/health`, run list, run progress page with live event feed |
| 4 | `/projects`, `/projects/<id>` with all six intelligence tabs, edit + regenerate |
| 5 | `/runs/<id>/subreddits`, `/runs/<id>/keywords` — both gates |
| 6 | `/runs/<id>/options` with cost estimate, comment display in lead detail |
| 7 | Confidence column, enrichment filters, `/leads/<id>` drawer with the hybrid breakdown |
| 8 | Polish, JSON/XLSX export, calibration report, empty/error states |

The Settings page ships **first** because it is the precondition for every AI feature, and because
it gives Phase 1 a visible, testable deliverable rather than an invisible library.

Each phase ships a usable increment. At no point is there a half-built page in the navigation.
