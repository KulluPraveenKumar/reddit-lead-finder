# 06f — Adaptive AI Budget

> Replaces the fixed-percentage gate. How many candidates get AI enrichment is **derived from the
> data**, not configured — because the right number depends on the shape of the score distribution,
> and that shape differs by run.

---

## 1. Why the fixed threshold was wrong

[06c §3.3](06c-local-first-pipeline.md) specified three presets, each a **fixed pre-score cut**
(`thorough` ≥ 20, `balanced` ≥ 35, `frugal` top-150), yielding roughly 60% / 30% / 12% of
*candidates*. That is simple, predictable, and wrong in both directions:

| Run shape | A fixed cut does | Should do |
|---|---|---|
| Strong distribution: the curve is still steep well below 35 | Stops at 35 — **discards real leads sitting on a steep slope** | Follow the curve down to where it flattens |
| Weak distribution: everything clusters at 30–40 | Admits a large block the rules already judged mediocre | Admit only the genuine top |
| Small run: 31 candidates | Admits a fraction of an already-tiny set | Admit nearly all — the sample is the cost floor anyway |

A fixed cut encodes an assumption about the *shape of the quality distribution* that is only correct
by coincidence. **The distribution is fully observable before any AI call is made**, so the
assumption is unnecessary.

### 1.1 The base, defined once

Throughout this document, **`n` = the number of candidates surviving the hard filters** — the items
that actually have a pre-score. Every fraction, clamp, and percentage is against `n`, never against
the raw collected count. (Collected counts are shown in the examples for context only.)

This is stated first because using two bases is exactly how the earlier funnel arithmetic went
wrong.

**→ Decision: derive the admission count from the pre-score distribution, bounded by explicit
policy limits, validated after the fact by the holdout audit.**

---

## 2. The mechanism

Three signals, combined, then clamped.

```
       pre-score distribution over the n candidates (already computed, free)
                    │
     ┌──────────────┼──────────────┬─────────────────┐
     ▼              ▼              ▼                 ▼
  KNEE          QUALITY        MARGINAL          POLICY
 detection      FLOOR          VALUE             CAPS
 (Kneedle)   (absolute min)  (diminishing     (cost, calls,
                              returns)         items, mode)
     └──────────────┴──────────────┴─────────────────┘
                    │
                    ▼
              admission count N
                    │
                    ▼
       validated after the run by the HOLDOUT AUDIT
```

### 2.1 Knee detection

Sort pre-scores descending and find the knee — the point of maximum curvature, where the curve
turns from steep decline to flat tail. Below the knee, each additional item is materially weaker
than the one before; the value of enrichment falls off there.

The **Kneedle** algorithm is the standard method for identifying the point of maximum curvature on
such a curve.

```python
def knee_index(sorted_scores: list[float]) -> int | None:
    """Kneedle on the descending pre-score curve. Returns None when the
    curve has no meaningful knee (uniform or near-uniform distribution)."""
```

**Failure mode this must survive:** knee detection is unstable at small N and on flat
distributions. Both are handled in §2.4.

### 2.2 Quality floor

The knee is *relative* — it finds where the curve bends, even if everything on the curve is weak.
An absolute floor prevents a run of uniformly poor candidates from admitting its own least-bad
items.

The floor is **mode-derived**, and it is deliberately *below* the mode's fixed threshold — that gap
is what lets adaptive budgeting admit more than a fixed cut would on a genuinely strong run:

| Mode | Fixed threshold (fallback) | Adaptive quality floor |
|---|---:|---:|
| `thorough` | ≥ 20 | **≥ 15** |
| `balanced` | ≥ 35 | **≥ 25** |
| `frugal` | ≥ 50 | **≥ 40** |

Admission requires **both** `rank ≤ knee` and `prescore ≥ floor(mode)`.

### 2.3 Marginal-value check

The adaptive-stopping literature detects diminishing returns by stopping at the first step where
marginal gain falls below a fraction of the first step's gain. Applied to expected lead yield:

```python
def expected_yield(prescore: float, calibration: YieldCurve) -> float:
    """P(is_lead) at this pre-score, learned from prior runs' actual outcomes."""

# stop admitting when the next item's expected yield falls below
# omega x the top item's expected yield
OMEGA = 0.15
```

`YieldCurve` is fitted from historical `(prescore, is_lead)` pairs the platform has already
collected. **On a first run it does not exist**, so the marginal check is skipped and knee + floor
govern alone. It engages once ~200 labelled outcomes accumulate — the system gets better at
budgeting as it runs, which is the behaviour an internal platform should have.

> ### ⚠ The fitting set must include holdout-audit leads
>
> Labels exist only for leads the operator sees, and the operator sees only leads this gate
> **admitted**. Fitting the curve on admitted leads alone would learn the shape of the gate's own
> output and re-confirm it, narrowing every cycle — a **degenerate feedback loop**, invisible to
> precision because precision is also measured only on admitted leads.
>
> The holdout audit is the exploration channel that prevents this: it enriches 2% of *rejected*
> candidates, and those items are persisted as **real, labellable leads**
> ([06i §2.3](06i-feedback-and-memory.md)). `YieldCurve` fitting **must not filter to admitted
> leads** — a test asserts the fit query has no such predicate.
>
> The resulting sample is deliberately unrepresentative: dense above the cut, sparse below it. That
> is the correct shape for the question *"how does yield fall as pre-score falls?"*, but the sparse
> tail carries wide uncertainty — so the fit enforces monotonicity, and the cutoff it produces is
> bounded by the clamps in §2.4. A badly-fitted tail cannot produce an absurd budget.

### 2.4 Policy clamps — the guardrails

Knee detection on a noisy or tiny distribution can produce absurd answers. Every one is clamped:

| Clamp | Value | Prevents |
|---|---|---|
| `min_admission_fraction` | 5% of **n** | A degenerate knee admitting almost nothing |
| `max_admission_fraction` | 90% of **n** | A flat distribution admitting effectively everything |
| `min_candidates` | **n** ≥ 200 | **Below this, skip knee detection entirely** — use the fixed threshold; the curve is too short to be stable |
| `max_items_per_run` | 2,000 | Hard ceiling |
| `max_cost_per_run_usd` | $2.00 | Cost ceiling, checked pre-call |
| `max_ai_calls_per_run` | 500 | Independent call ceiling |

**Why `max_admission_fraction` is 90%, not 70%.** The clamp exists to catch a *degenerate* knee, not
to be a second budget. At 70% of `n` the ceiling would sit close to — and on some distributions
*below* — what the fixed `balanced` cut already admits, which would make adaptive budgeting
systematically stingier than the thing it replaces. The clamp must be loose enough that it only ever
fires on nonsense.

**The `min_candidates` floor matters most.** Kneedle on 40 points produces a number, but not a
meaningful one. Below 200 candidates the adaptive path is skipped and the run uses the mode's
fixed threshold — stated in the estimate as *"too few candidates for adaptive budgeting; using
balanced threshold"*, so the operator knows which path ran.

### 2.5 The combined rule

```python
def admission_count(scores: list[float], mode: Mode, history: YieldCurve | None,
                    policy: Policy) -> Budget:
    """scores = pre-scores of the n candidates that survived the hard filters."""
    n = len(scores)
    s = sorted(scores, reverse=True)

    # --- small-n escape: the curve is too short for a stable knee -------------
    if n < policy.min_candidates:
        return Budget(count=count_above(s, mode.fixed_threshold),
                      n=n, method="fixed_threshold_small_n")

    # --- 1. knee, biased by mode appetite ------------------------------------
    raw_knee = knee_index(s)
    if raw_knee is None:
        k = count_above(s, mode.fixed_threshold)          # flat curve → fall back
        method = "fixed_threshold_no_knee"
    else:
        k = round(raw_knee * mode.knee_multiplier)        # 1.6 / 1.0 / 0.6
        method = "knee"

    # --- 2. quality floor (mode-derived) -------------------------------------
    floor_allows = count_above(s, mode.prescore_floor)    # 15 / 25 / 40
    if floor_allows < k:
        k, method = floor_allows, method + "+floor"

    # --- 3. marginal value (only once a yield curve exists) -------------------
    if history:
        marg_allows = marginal_value_cutoff(s, history, mode.omega)
        if marg_allows < k:
            k, method = marg_allows, method + "+marginal"

    # --- 4. clamps and ceilings ----------------------------------------------
    lo, hi = ceil(policy.min_frac * n), floor(policy.max_frac * n)
    ceiling = min(hi, policy.max_items, cost_ceiling(policy), call_ceiling(policy))
    if k > ceiling:  k, method = ceiling, method + "+clamped_max"
    if k < lo:       k, method = lo,      method + "+clamped_min"

    return Budget(count=k, n=n, method=method, knee_at=raw_knee,
                  floor_allows=floor_allows, clamp=(lo, hi))
```

**`Budget.method` is persisted and displayed.** Which rule actually decided the number is as
important as the number, because "70 admitted" means something different when it came from a knee
than when it came from a clamp. The method string accumulates every binding constraint in the order
it applied, so `knee+floor+clamped_min` tells the whole story in one token.

---

## 3. Modes become a bias, not a rule

The three modes survive, but as a *shift applied to the adaptive result* rather than a fixed
percentage:

| Mode | `knee_multiplier` | `prescore_floor` | `omega` | `fixed_threshold` | Use |
|---|---:|---:|---:|---:|---|
| `thorough` | 1.6 | 15 | 0.05 | ≥ 20 | New project; first run; deliberately wide |
| `balanced` *(default)* | 1.0 | 25 | 0.15 | ≥ 35 | Normal operation |
| `frugal` | 0.6 | 40 | 0.30 | ≥ 50 | Large exhaustive scrapes; scheduled monitoring |

They express *appetite*, and the data decides the number. That is the correct division: the operator
knows how much they care about this run; the distribution knows how many candidates are worth it.

**`thorough` is expected to hit `max_admission_fraction` on a healthy distribution, by design.**
A 1.6× multiplier on a knee near 65% of `n` lands above the 90% ceiling, so `thorough` runs will
routinely report `+clamped_max`. That is the mode doing what it was asked to do — "analyse
practically everything that survived the filters" — not a malfunction. The
**< 10% clamp-binding acceptance target ([06d §5](06d-ai-budget-and-scale.md), target 13) therefore
applies to `balanced` runs only**; a clamp binding in `thorough` carries no diagnostic signal.

---

## 4. Worked examples

All five are `balanced` mode. **Call counts include the holdout audit** (2% of rejects, minimum 1
item, batched at B=8), and cost uses the measured ~$0.0011 per enrichment call from
[06d §2](06d-ai-budget-and-scale.md). Every figure below was computed, not estimated.

**A — strong distribution. The case a fixed cut handles worst.**

```
1,200 collected → n = 329 candidates
  knee at rank 214 (pre-score 29.4) — the curve is still steep below 35
  floor (≥25)      allows 268      not binding
  marginal (ω=.15) allows 254      not binding
  clamp [17, 296]                  not binding
  → 214 admitted     method = "knee"
  27 enrichment + 1 holdout (3 of 115 rejects) = 28 calls · ~$0.031
```

**The fixed `balanced` cut (≥35) would have admitted 180.** Adaptive admits **34 more** — a 19%
coverage gain — because the knee shows the curve has not flattened at 35. This is the failure mode a
fixed threshold cannot see, and the reason the floor sits at 25 rather than at 35.

**B — weak distribution. The quality floor earns its place.**

```
1,100 collected → n = 402 candidates
  knee at rank 310 — the curve is nearly flat, so the "knee" is meaningless
  floor (≥25)      allows only 47   ← BINDS
  marginal (ω=.15) allows 88        not binding
  clamp [21, 361]                   not binding
  → 47 admitted      method = "knee+floor"
  6 enrichment + 1 holdout (8 of 355 rejects) = 7 calls · ~$0.008
```

Knee detection alone would have admitted **310** items on a flat curve — the floor prevented 263
analyses of candidates the rules had already judged weak. The run page reports *"quality floor
limited admission — the pre-score distribution is flat; consider revising keywords."* Note it still
admits 47 where the fixed ≥35 cut would admit 29: adaptive is not simply stingier, it is
*shape-aware*.

**C — small run. Adaptive correctly declines to run.**

```
84 collected → n = 31 candidates
  n < 200 → knee detection skipped entirely
  balanced fixed threshold (≥35) → 22 admitted
  method = "fixed_threshold_small_n"
  3 enrichment + 1 holdout = 4 calls · ~$0.004
```

**D — large, strong run. Marginal value trims the tail.**

```
2,400 collected → n = 900 candidates
  knee at rank 690      ·  floor allows 812  ·  marginal (ω=.15) allows 705
  clamp [45, 810] · max_items 2,000 · cost ceiling ~1,800 — none binding
  → 690 admitted     method = "knee"
  87 enrichment + 1 holdout (5 of 210 rejects) = 88 calls · ~$0.097
```

Fixed ≥35 would admit 720. Adaptive trims 30 from a tail the yield curve says is not worth
enriching — a small saving, and the right one. **On a well-shaped large run, adaptive and fixed
converge.** That is the expected result, not a disappointment: adaptive budgeting earns its value on
the *abnormal* runs (A, B, E), and costs nothing on the normal ones.

**E — degenerate distribution. The minimum clamp catches it.**

```
600 collected → n = 250 candidates (single-keyword monitoring run; scores near-identical)
  knee at rank 3 — a spurious spike on an almost-uniform curve
  clamp [13, 225]  → min clamp BINDS
  → 13 admitted      method = "knee+clamped_min"
  2 enrichment + 1 holdout (5 of 237 rejects) = 3 calls · ~$0.003
```

Unclamped, Kneedle would have admitted **3 items out of 250**. The clamp turns a nonsensical answer
into a defensible one and **says so in the method string**, so the operator can see that the
distribution — not the data quality — is what limited the run.

---

## 5. The audit closes the loop

Knee detection operates on the **pre-score**, which is a *proxy* for value, not value itself. The
knee can be in the wrong place if the pre-score is miscalibrated — and nothing in §2 would notice.

**The holdout audit is what validates the budget.** It samples rejected candidates, enriches them
anyway, and reports how many would have qualified.

| Gate miss rate | Interpretation | Automatic response |
|---|---|---|
| < 2% | Budget may be too generous | Suggest `frugal`; note potential saving |
| 2–5% | **Healthy** | None |
| 5–10% | Slightly tight | Warn; show `worst_reason` |
| > 10% | **Too aggressive** | Warn prominently; suggest `thorough`; **auto-widen next run** by one mode step if `auto_widen` is enabled |

**Auto-widening is opt-in and one step at a time**, because a runaway feedback loop between the
audit and the budget would be worse than a slightly tight gate. The audit *proposes*; the operator's
configured policy decides.

This pairing is the substance of the adaptive design: **the knee decides how many, and the audit
decides whether the knee was right.** Neither alone is sufficient — the knee has no ground truth,
and the audit has no control input.

---

## 6. What is shown to the operator

At the options step, before committing:

```
1,200 collected → 329 candidates passed the hard filters

  Adaptive budget          214 candidates          (65% of candidates)
  Decided by               knee detection
  Knee at                  rank 214 (pre-score 29.4)
  Quality floor (≥25)      allowed 268 — not binding
  Marginal value           allowed 254 — not binding
  Clamps [17, 296]         not binding
  Fixed ≥35 would admit    180  (adaptive is 34 wider)
  Estimated                28 AI calls · $0.031 – $0.040 · ~50 s

  [ thorough  296 · $0.043 ]  [ balanced  214 · $0.031 ]  [ frugal  128 · $0.019 ]
```

And after the run:

```
  Admitted           214        Gate miss rate   2.8%  ✓ healthy
  Method             knee                    Worst reason  negative_term (2 of 4 misses)
```

Every number is explained by the rule that produced it. An operator who disagrees with 214 can see
whether the knee, the floor, the marginal check, or a clamp decided it — and knows which dial to
turn. Showing what the fixed cut *would* have done keeps the mechanism honest and reviewable rather
than merely automatic.

---

## 7. Configuration

```yaml
ai:
  budget:
    strategy: adaptive              # adaptive | fixed
    mode: balanced                  # thorough | balanced | frugal

    adaptive:
      min_candidates_for_knee: 200      # n, post-hard-filter
      min_admission_fraction: 0.05      # of n
      max_admission_fraction: 0.90      # of n — a nonsense guard, not a budget
      yield_curve_min_labels: 200
      auto_widen_on_high_miss_rate: false

    # every per-mode dial lives here; nothing is hardcoded in the gate
    modes:
      thorough: { knee_multiplier: 1.6, prescore_floor: 15, omega: 0.05, fixed_threshold: 20 }
      balanced: { knee_multiplier: 1.0, prescore_floor: 25, omega: 0.15, fixed_threshold: 35 }
      frugal:   { knee_multiplier: 0.6, prescore_floor: 40, omega: 0.30, fixed_threshold: 50 }

    ceilings:
      max_items_per_run: 2000
      max_cost_per_run_usd: 2.00
      max_cost_per_day_usd: 5.00
      max_ai_calls_per_run: 500
```

`strategy: fixed` is retained as an escape hatch. If adaptive budgeting ever misbehaves, an operator
must be able to pin the behaviour without editing code.

---

## 8. Why this is better than a fixed cut

| | Fixed threshold | Adaptive budget |
|---|---|---|
| Strong run (§4A) | Stops at 35 — discards 34 real candidates on a steep slope | Follows the curve to 214 |
| Weak run (§4B) | Admits 29 on an uninformative flat curve | Floor binds at 47 and **says the curve is flat** |
| Small run (§4C) | Applies anyway | Detects `n < 200` and falls back, explicitly |
| Normal large run (§4D) | 720 | 690 — converges, as it should |
| Degenerate input (§4E) | 150 arbitrary items | Clamped to 13, clamp reported |
| Explains itself | "≥ 35" | Knee rank, floor, marginal cutoff, binding clamp, and the fixed-cut counterfactual |
| Improves over time | Never | Yield curve learns from labelled outcomes |
| Validated | Never | Holdout audit every run |

The cost of the mechanism is a sort and a curvature calculation over numbers already computed —
microseconds, zero API calls.
