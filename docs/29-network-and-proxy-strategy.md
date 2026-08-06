# 29 — Network & Proxy Strategy

> **Parts 5 and 6.** When proxies should be used at all, how the networking layer should be
> abstracted, and which managed provider to buy.
>
> **Stated up front, because it governs everything below:** the objective is a *reliable,
> maintainable networking layer that minimises unnecessary requests and handles failure gracefully*.
> It is not to defeat Reddit's protections. Every recommendation here reduces request volume,
> respects published rate-limit headers, and keeps the platform's existing posture — no
> authentication, no account, human-scale cadence, no republication
> ([07 §6.6](07-scraping-pipeline.md)).
>
> Evidence labels: ✅ Verified · ◐ Inferred · ▶ Recommendation · ❓ Unknown.

---

## 1. The evidence that forces a rethink

✅ Three measurements from this repository, never previously read together:

| # | Measurement | Source |
|---|---|---|
| E1 | Unproxied `old.reddit.com` listing and search both returned **HTTP 200**, 192 KB, 25 posts | [00 §3](00-current-state.md), 2026-07-29 |
| E2 | All 10 proxies **and the local IP** got 403 — cause was **header incoherence**, not addressing. A coherent Chrome profile returned 200 *"through the same proxy seconds later"* | [PHASE-02-STATUS §3.1](PHASE-02-STATUS.md) |
| E3 | After the header fix: **`ok=12, failed=24, blocked=24`**, 8 of 10 proxies blacklisted, pagination truncated on 3 of 4 subreddits | [PHASE-02-STATUS §4.1](PHASE-02-STATUS.md) |

◐ **The conclusion:** the block problem was never an IP problem, and the datacenter pool is a
*worse* path than the direct connection for this target. Yet [07 §1](07-scraping-pipeline.md)
mandates that `RedditClient` have **no direct `requests` access**, and
[08 §7](08-proxy-service.md) sets `fail_closed: true` — *"refuse to start if 0 healthy proxies"*.

**The architecture requires the slower, less reliable path and forbids the faster, more reliable
one.** [PHASE-02-STATUS §4.1](PHASE-02-STATUS.md) says as much in its own words: *"Residential
proxies would change the number; nothing in this codebase will."*

---

## 2. Should proxies always be used?

**▶ No.** The mandate conflates a real goal with one implementation of it.

| Goal | Does a rotating proxy serve it? |
|---|---|
| **Not exposing the operator's residential IP to Reddit at volume** | **Yes.** This is the real goal, and it is worth paying for |
| Throughput | **No.** Measured 67% block rate versus a working direct connection |
| Avoiding a licensing dependency | No — that is [D1](02-research-findings.md) (no API/OAuth), independent of egress |
| Surviving a single-IP block | **Partially.** The pool blocked faster than the single IP did |
| Fetching the **customer's own website** (Phase 4) | **No — actively harmful.** ▶ Crawling a customer's site from ten rotating datacenter IPs looks like an attack. It should come from one stable, identifiable address |

▶ The last row is a design error in the current plan that nobody has noticed, because Phase 4 has
not shipped. [08 §10](08-proxy-service.md) lists `WebsiteFetcher` as a proxy-pool consumer and calls
it *"the payoff for building the proxy layer first."* It is the opposite: a bounded, polite,
seven-page crawl of a site whose owner is the operator's own customer is the one fetch in the system
that should be direct and consistent.

### 2.1 The decision table

▶ Egress is chosen by **request class**, not globally.

| Request class | Volume | Default egress | Reasoning |
|---|---|---|---|
| **RSS discovery** | ~25/day | **Direct** | Published feed; low volume; respects `x-ratelimit-*` |
| **Health / canary** | ~2/day | **Direct** | Must reflect the real path |
| **Website fetch** (Phase 4) | ~7 per project version | **Direct** | Customer's own site; rotation is anti-social |
| **HTML listing / search bulk** | 3–120/day | **Proxy preferred**, direct on pool failure | Where IP exposure actually accumulates |
| **Comment permalinks** | ~15/day | **Proxy preferred** | Same |
| **Subreddit validation** (Phase 5) | ~30 per run, bursty | **Proxy preferred** | A burst of 30 lookups from one IP is the most block-prone pattern in the system |

◐ After the [28](28-discovery-redesign.md) redesign, **the proxy-preferred classes total roughly 30–140
requests per day** rather than 390 per run. That is small enough that a paid residential pool costs
under $2/month (§6.5) — which is the finding that makes this whole section actionable rather than
theoretical.

### 2.2 What replaces `fail_closed: true`

The current setting is binary: proxies or refuse to run. ▶ Replace it with a three-value policy:

```yaml
network:
  policy: prefer_proxy        # direct_only | prefer_proxy | proxy_only
  direct:
    enabled: true
    max_requests_per_hour: 120        # a hard governor on the operator's own IP
    classes: [rss, health, website]   # always direct regardless of policy
  on_pool_exhausted: degrade_to_direct  # degrade_to_direct | pause_run | fail_run
```

| `on_pool_exhausted` | Behaviour | ▶ When to choose it |
|---|---|---|
| `degrade_to_direct` | Continue on the direct connection, under `max_requests_per_hour`, and **log a visible warning to `run_events`** | **Default.** A truncated run is worse than a slower one |
| `pause_run` | Job fails as retryable; the run resumes when the pool recovers | When IP exposure genuinely matters more than latency |
| `fail_run` | Today's `fail_closed` behaviour | Kept for compliance situations |

**The honest trade-off**, and the reason [08 §7](08-proxy-service.md) chose `fail_closed` originally:
*"Setting it to `false` means the tool will scrape Reddit from the operator's own IP when the pool
dies — which is exactly the situation proxies exist to prevent."* That reasoning is sound and is
**not** dismissed here. What changes is that degradation is now **bounded and visible** — a
per-hour governor, a class allowlist, and a `run_events` warning — rather than an unbounded silent
fallback. ▶ A capped, logged fallback is a different thing from the uncapped one that decision
rejected.

---

## 3. The provider interface

### 3.1 Design

```python
# src/net/providers/base.py
class NetworkProvider(ABC):
    """One way of getting bytes from the internet. Knows nothing about Reddit."""

    name: str
    # ── capability flags: how the policy layer reasons without branching on name ──
    exposes_origin_ip: bool        # Direct: True. Any proxy: False
    is_metered: bool               # billed per GB → bandwidth is a budgeted resource
    supports_sticky: bool          # can pin a session to one exit
    supports_geo: bool
    rotation: Literal["per_request", "sticky_session", "none"]

    @abstractmethod
    def acquire(self, *, session_key: str | None = None,
                exclude: set[str] | None = None) -> Lease: ...
    @abstractmethod
    def release(self, lease: Lease, *, outcome: Outcome,
                status: int | None, latency_ms: float, bytes_in: int) -> None: ...
    @abstractmethod
    def health(self) -> ProviderHealth: ...
    @abstractmethod
    def capacity(self) -> Capacity: ...      # usable exits, req/min, GB remaining
```

```
                    ┌───────────────────────────────┐
                    │   NetworkPolicy               │
                    │   class → provider selection  │
                    │   degradation ladder          │
                    │   bandwidth budget            │
                    └───────────────┬───────────────┘
                                    │
     ┌────────────────┬─────────────┼──────────────┬─────────────────┐
     ▼                ▼             ▼              ▼                 ▼
 Direct        WebshareDC     WebshareResi   ManagedProxy      Null
 Provider      Provider       Provider       Provider          Provider
 ─────────     ──────────     ───────────    ─────────────     ────────
 origin_ip ✅   metered ❌      metered ✅      metered ✅         tests
 metered  ❌   sticky   ✅      sticky   ✅      per-vendor        offline
 free           per-IP list    gateway URL    gateway URL       fixtures
```

| Implementation | Backed by | Notes |
|---|---|---|
| `DirectProvider` | `requests.Session` with a pinned header profile | **The only provider with `exposes_origin_ip = True`.** Governed by `max_requests_per_hour` |
| `WebshareDatacenterProvider` | The existing 10-IP `ip:port:user:pass` file | Today's `ProxyManager`, refactored behind the interface. **No behaviour change** |
| `WebshareResidentialProvider` | Rotating gateway endpoint | Bandwidth-metered; `capacity()` reports GB remaining |
| `ManagedProxyProvider` | Generic gateway: host, port, credentials, optional session suffix | ▶ Covers Decodo, IPRoyal, NetNut, SOAX, Oxylabs and Bright Data **without a per-vendor class** — they all speak the same `user-session-xxx:pass@gateway:port` shape |
| `NullProvider` | Raises on use | Asserts a code path made no network call |

▶ **`ManagedProxyProvider` is the design's main economy.** [08](08-proxy-service.md) currently
assumes one vendor with a per-IP list. Almost every managed residential vendor instead exposes a
*single gateway* where rotation and geo are encoded in the username. One generic class plus a
per-vendor config block covers the entire market, so **switching vendors is a config change, not a
code change** — which is precisely what Part 6 asks for.

### 3.2 What does not change

`ProxiedHTTPClient`'s public contract is unchanged, so `RedditClient` and `WebsiteFetcher` need no
edits:

```python
client.get(url, session_key=..., timeout=..., use_cache=..., max_attempts=...) -> Response
```

Only the internals change: `manager.acquire()` becomes `policy.acquire(request_class, session_key)`.
◐ This preserves [AD-2](03-architecture.md) (`RedditClient`'s API is frozen) and keeps the 251
existing `src/net/` tests meaningful — the fake-session seam at `session_for` is retained.

---

## 4. Health, rotation, cooldown, failure

### 4.1 Health measurement — the current check has a real gap ▶

[08 §3.4](08-proxy-service.md) health-checks against `api.ipify.org` and verifies the exit IP differs
from the local one. Both are correct and both must stay — the leak check in particular is the one
guarantee the pool exists to provide.

**But a proxy that returns 200 from ipify and a soft-block page from Reddit is reported `healthy`.**
◐ That is exactly the state 8 of 10 proxies were in during the [PHASE-02-STATUS §4.1](PHASE-02-STATUS.md)
run, and the health page would have shown them as fine right up to the moment the retry ladder
blacklisted them.

▶ **Add a second, passive signal: target acceptance rate**, computed from real traffic rather than
from a synthetic probe.

| Signal | Source | Meaning |
|---|---|---|
| **Reachability** | ipify probe | The proxy works at all |
| **Leak** | exit IP ≠ local IP | The proxy is actually proxying |
| **★ Target acceptance** | rolling window of real outcomes: `ok ÷ (ok + blocked)` | The proxy works **for this target** |

`ProxyRuntime` gains `target_ok`, `target_blocked` and a derived `acceptance_rate`. Selection
prefers high acceptance; the health page shows it; a pool-wide acceptance below a floor opens the
circuit breaker *before* every proxy is individually blacklisted.

▶ This is a genuine improvement over the current design and costs **zero extra requests** — it is
derived from traffic that is happening anyway. Synthetic health checks answer *"is it up?"*; only
real outcomes answer *"is it useful?"*

### 4.2 Rotation

| Aspect | Decision |
|---|---|
| Strategy | **Keep LRU with per-proxy pacing** — implemented and tested ([PHASE-02-STATUS §8](PHASE-02-STATUS.md)). The three strategies [08 §3.1](08-proxy-service.md) specified were deliberately not built, correctly |
| Ordering | Prefer higher `acceptance_rate`, then least-recently-used |
| Sticky | Keep per-subreddit pinning (`session_key=f"sub:{sub}"`) — a cursor walk on one IP ([08 §3.2](08-proxy-service.md)) |
| Retry | ▶ **Make `exclude=tried` explicit.** [12 §14](12-phase-02.md) records it as an emergent LRU property, not an enforced one. Retrying the same failing IP is the classic rotating-proxy bug and should not depend on an ordering side effect |
| **Cross-provider** | ▶ **New:** on pool exhaustion, the *policy* degrades to the next provider — the ladder is `WebshareResi → WebshareDC → Direct`, not just proxy-to-proxy |

### 4.3 Cooldown

Keep [08 §2](08-proxy-service.md)'s state machine (`UNKNOWN → HEALTHY → DEGRADED → BLACKLISTED →
COOLDOWN`) with one addition:

▶ **Cooldown duration scales with pool pressure.** With 8 of 10 blacklisted, a fixed 15-minute
cooldown means the run stalls; the honest response is to return proxies to probation *sooner* and
accept a higher failure rate, or to degrade to the next provider. Concretely:

```
effective_cooldown = base_cooldown × (healthy_count / pool_size)
```

At 2/10 healthy a 900 s cooldown becomes 180 s. ◐ The reasoning: a blacklist is a guess about
whether the target will accept this IP again, and when almost nothing is accepted, waiting longer
buys no information.

### 4.4 Failure handling

| Failure | Current | Change |
|---|---|---|
| 403 / 429 / soft block | Blacklist + rotate + backoff | **Unchanged.** Also decrements `acceptance_rate` |
| Pool exhausted | `ProxyExhaustedError`, job fails | **Degrade per `on_pool_exhausted`** (§2.2) |
| Circuit open (pool-wide) | All requests raise | **Unchanged** — plus acceptance-rate as a second trigger |
| **Bandwidth exhausted** (metered) | — | ▶ **New.** `capacity()` reports GB remaining; below a floor the provider reports unhealthy and the policy degrades. A metered provider that silently runs out mid-run looks like a network outage |
| Exit-IP leak | `ProxyLeakError`, fatal | **Unchanged.** ✅ Correct as written |

---

## 5. Part 6 — Managed proxy providers

### 5.1 What the platform actually needs

◐ Derived from [28 §4.4](28-discovery-redesign.md), and the numbers are unusually favourable:

| Requirement | Value |
|---|---|
| Bandwidth/month | **0.10 – 0.55 GB** |
| Requests/month | 944 – 4,479 |
| Concurrency | 1–3 |
| Geo | None — Reddit is global |
| Session persistence | Yes, for cursor walks |
| Residential vs datacenter | **Residential** — datacenter is measurably blocked (E3) |
| Billing shape | ▶ **Non-expiring credits strongly preferred** |

**The billing-shape row is the discriminating requirement, and it is easy to miss.** At 0.1–0.55
GB/month, a plan with a 25 GB monthly minimum wastes 98% of what it bills. ◐ A pay-as-you-go plan
with non-expiring bandwidth turns a $5 purchase into roughly a year of operation.

### 5.2 Comparison ✅ (prices as published, 2026-08; verify before purchase)

| Provider | Residential entry | At volume | Datacenter | Non-expiring? | Tier |
|---|---:|---:|---|---|---|
| **Webshare** | **$3.50/GB** (1 GB) · $2.25/GB (100 GB) | $1.40/GB (3 TB) | **$0.0299/proxy/mo**; free 10 | ❓ | Budget |
| **IPRoyal** | ~$1.75–3.50/GB PAYG | −75% at 10 TB | Yes | ✅ *"bandwidth that never expires"* | Budget |
| **DataImpulse** | ~$1.00/GB; 5 GB for $5 | — | Yes | ❓ | Budget |
| **Decodo** (ex-Smartproxy) | **$5.50/GB** (10 GB) · ~$3.75/GB | ~$2/GB at 1 TB+ | Yes | ✅ non-expiring credits; 14-day refund | Mid |
| **NetNut** | ~$3.53/GB | — | Yes | ❓ | Mid |
| **SOAX** | ~$3.60/GB; plans from $90/mo (25 GB) | — | Yes | ❌ monthly | Mid |
| **Oxylabs** | **$8.00/GB** (10 GB = $80) | — | Free 5 DC IPs; 7-day trial | ❌ | Enterprise |
| **Bright Data** | **$8.40/GB** (10 GB) · ~$4 promo | **$3.30/GB** at 10 TB | Yes | ❌ | Enterprise |

Sources: provider pricing pages and 2026 comparisons (aimultiple, brightdata, dataimpulse,
trustmyip). ▶ Proxy pricing changes frequently and every figure carries the same
`verified_on` caveat the platform already applies to model pricing
([02 §6.2](02-research-findings.md)).

### 5.3 Recommendations ▶

| Stage | Recommendation | Cost at our volume | Reasoning |
|---|---|---:|---|
| **MVP** | **`DirectProvider` + the existing free Webshare datacenter pool as failover** | **$0** | ✅ **CONFIRMED BY MEASUREMENT, P0 2026-08-05.** Direct: **100% success, 0% blocks, 1,342 ms mean**. Webshare: **71.4% success, 28.6% hard blocks, 2,081 ms mean**. Reproduced twice. Direct also won on CPU (2.55×) and posts extracted. **Buy nothing.** See [SPRINT-0-MEASUREMENTS §1](SPRINT-0-MEASUREMENTS.md) |
| **Production** | **Webshare rotating residential, pay-as-you-go** | **~$3.50 once**, covering ~2–6 months | Same vendor, same credential format, same `ManagedProxyProvider` config as the datacenter pool already in use — the lowest-integration-risk upgrade available. Residential is what E3 says is needed |
| **Production alternative** | **IPRoyal** | ~$2–5 once | Choose this over Webshare **if Webshare's residential bandwidth expires monthly** (❓ — confirm before purchase). Non-expiring credit is worth more than per-GB price at our volume |
| **Enterprise** | **Oxylabs**, or Bright Data | $80+/mo | Only when a *compliance* requirement appears — audited sourcing, contractual SLA, geo-targeting. **We have none of these**, and paying enterprise rates for 0.5 GB would be paying for a procurement posture, not a capability |

▶ **The MVP recommendation is deliberately "buy nothing yet."** The block rate measured in
[PHASE-02-STATUS §4.1](PHASE-02-STATUS.md) was produced by a 36-request burst against 4 subreddits.
Under [28](28-discovery-redesign.md) the same coverage costs ~28 requests spread across a day, at a
fraction of the density. ◐ It is entirely possible that the block problem substantially dissolves
once the request pattern stops looking like a scrape — and spending money before measuring that
would be buying a solution to a problem we may have just removed.

### 5.4 Provider swap procedure

The design target is that changing vendor touches no scraper code. Concretely:

```yaml
network:
  policy: prefer_proxy
  providers:
    - name: direct
      type: direct
      classes: [rss, health, website]
      max_requests_per_hour: 120
    - name: resi
      type: managed_gateway            # ← ManagedProxyProvider
      gateway: "p.webshare.io:80"
      username: "${PROXY_USER}"
      password: "${PROXY_PASS}"
      session_param: "-session-{key}"  # vendor-specific sticky syntax
      metered: true
      bandwidth_floor_gb: 0.05
      classes: [html, comments, validation]
    - name: dc
      type: managed_list               # ← the existing file-based pool
      file: "${PROXY_FILE}"
      classes: [html, comments, validation]
  ladder: [resi, dc, direct]           # degradation order
```

Switching to Decodo or IPRoyal changes `gateway`, `username`, `password` and `session_param`. **No
Python changes, no scraper changes, no test changes** — asserted by a test that constructs every
registered provider from config and exercises the same request against a fake session.

---

## 6. Changes to existing documents

| Doc | Change |
|---|---|
| [07 §1](07-scraping-pipeline.md) | *"All traffic via rotating proxy"* → **"All traffic via the network policy; egress is chosen per request class."** The enforcement (no bare `requests.get` in `RedditClient`) is unchanged |
| [08 §7](08-proxy-service.md) | `fail_closed: true` → the three-value `on_pool_exhausted` policy (§2.2), with the original reasoning retained and the bounded-degradation argument added |
| [08 §3.4](08-proxy-service.md) | Add target-acceptance rate as a third health signal (§4.1) |
| [08 §10](08-proxy-service.md) | **`WebsiteFetcher` moves off the proxy pool** — the customer's own site is fetched direct (§2) |
| [08 §3.1](08-proxy-service.md) | Record LRU as the shipped strategy; make `exclude=tried` explicit |
| [12 §14](12-phase-02.md) | Move `exclude=tried` from "deliberately not built" to a Sprint task |
| [03 §8](03-architecture.md) | Technology table gains a **network provider** row |
| **New ADR** | ADR-02 (§ [32](32-documentation-consistency.md)) — *egress is a policy, not a mandate* |

---

## 7. Acceptance criteria

- [ ] **N-AC1** — RSS, health and website-fetch requests go **direct** even when `policy: prefer_proxy`
- [ ] **N-AC2** — Bulk HTML uses a proxy when one is healthy, and degrades per `on_pool_exhausted` when none is
- [ ] **N-AC3** — Degradation to direct emits a **visible `run_events` warning** and respects `max_requests_per_hour`
- [ ] **N-AC4** — `ProxyLeakError` remains fatal; the exit-IP check is unchanged
- [ ] **N-AC5** — A proxy that returns 200 from the health endpoint but soft-blocks on the target is reported **degraded**, not healthy (§4.1)
- [ ] **N-AC6** — Swapping the residential vendor is a config change; a test constructs every provider from config with **no code change**
- [ ] **N-AC7** — A metered provider below its bandwidth floor reports unhealthy and the policy degrades
- [ ] **N-AC8** — Retries use a **different** exit than the failed attempt, enforced rather than emergent
- [ ] **N-AC9** — Credentials appear in no log, no DB column, no API response, and no UI surface — the existing four guarantees ([PHASE-02-STATUS §6](PHASE-02-STATUS.md)) extended to the new providers
- [ ] **N-AC10** — All 251 existing `src/net/` tests pass unchanged, or their change is justified in review
- [ ] **N-AC11** — `src/net/` still contains **zero** Reddit identifiers (grep test)

---

## 8. Summary

| Question | Answer |
|---|---|
| Should proxies always be used? | **No.** Per request class (§2.1) |
| When is direct preferred? | RSS, health checks, and the customer's own website — always. Bulk HTML when the pool is exhausted, under a governor |
| When are proxies preferred? | Bulk HTML, comment permalinks, subreddit validation bursts |
| How is health measured? | Reachability + leak check + **target acceptance rate** (new) |
| How does rotation work? | LRU with per-proxy pacing, ordered by acceptance, sticky per subreddit, enforced exclusion on retry |
| How does cooldown work? | Existing state machine, with duration scaled by pool pressure |
| How are failures handled? | Rotate → backoff → blacklist → **degrade to the next provider** → policy decision |
| How are providers abstracted? | `NetworkProvider` ABC + capability flags + a `NetworkPolicy` that selects by request class |
| Best MVP provider | **Direct + the existing free pool. Buy nothing until Sprint 0 measures the new request pattern** |
| Best production provider | **Webshare rotating residential PAYG** (~$3.50, months of runway), or **IPRoyal** if non-expiring credit is confirmed to matter |
| Best enterprise provider | **Oxylabs** or Bright Data — and only for a compliance requirement we do not currently have |

▶ **The single most useful thing in this section is the sequencing:** reduce request volume first
([28](28-discovery-redesign.md)), measure the block rate at the new volume, and only then buy
bandwidth. The current plan buys the proxy layer first and discovers the volume problem afterwards —
which is how a $0 problem becomes a $7/month problem with a 67% failure rate.
