# 08 — Proxy Service

> A standalone, reusable, Reddit-agnostic HTTP egress layer. `src/net/` knows nothing about
> subreddits, leads, or Reddit markup; it knows about proxies, retries, and HTTP. That separation is
> what lets Phase 4's website fetcher inherit the whole thing for free.

---

## 1. Credential handling — read this first

The supplied file is:

```
%USERPROFILE%\Downloads\Webshare 10 proxies.txt
```

Format, one per line:

```
<ip>:<port>:<username>:<password>
```

**Rules, all enforced by code and by review:**

| Rule | Enforcement |
|---|---|
| The file lives **outside the repository** | Referenced by the `PROXY_FILE` env var; the repo has no copy |
| No credential ever enters the database | `proxies` table stores `host`, `port`, health — nothing else |
| No credential ever enters a log line | `RedactingFilter` on the logging config, plus `ProxyEndpoint.__repr__` returns `host:port` |
| No credential ever renders in the UI | The proxy health page shows `ip:port` only |
| No credential in `config.yaml` | `config.yaml` holds `file: "${PROXY_FILE}"`, interpolated at load |
| `.env`, `*.txt` proxy files gitignored | `.gitignore` entries added in Phase 1 |

```python
@dataclass(frozen=True)
class ProxyEndpoint:
    host: str
    port: int
    username: str = field(repr=False)      # repr=False — never printed
    password: str = field(repr=False)

    @property
    def key(self) -> str:
        return f"{self.host}:{self.port}"          # the ONLY form that leaves this module

    @property
    def url(self) -> str:
        return f"http://{quote(self.username)}:{quote(self.password)}@{self.host}:{self.port}"

    def as_requests_proxies(self) -> dict[str, str]:
        return {"http": self.url, "https": self.url}   # HTTPS tunnels via CONNECT over HTTP proxy

    def __str__(self) -> str:
        return self.key
```

Both `http` and `https` keys point at the **`http://`** proxy URL. Webshare proxies are HTTP
proxies that tunnel HTTPS via `CONNECT`; writing `https://user:pass@…` for the `https` key is the
single most common configuration error with this provider and produces an immediate SSL failure.

### Parser

```python
def load_proxies(path: str | Path) -> list[ProxyEndpoint]:
    out, seen = [], set()
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) != 4:
            log.warning("proxy_parse_skip", line=lineno, reason="expected ip:port:user:pass")
            continue
        host, port, user, pw = parts
        try:
            port_i = int(port)
        except ValueError:
            log.warning("proxy_parse_skip", line=lineno, reason="non-numeric port"); continue
        if not (0 < port_i < 65536):
            log.warning("proxy_parse_skip", line=lineno, reason="port out of range"); continue
        if (host, port_i) in seen:
            log.warning("proxy_parse_skip", line=lineno, reason="duplicate"); continue
        seen.add((host, port_i))
        out.append(ProxyEndpoint(host, port_i, user, pw))
    if not out:
        raise ProxyConfigError(f"no usable proxies in {path}")
    return out
```

Note that the failure log names a **line number**, never the line content — a malformed line still
contains a password.

---

## 2. Proxy states

```
                  health check OK / request OK
        ┌──────────────────────────────────────────┐
        │                                          │
        ▼                                          │
   ┌─────────┐  consecutive_failures >= N    ┌───────────┐
   │ HEALTHY │ ────────────────────────────► │ DEGRADED  │
   └─────────┘                               └───────────┘
        ▲                                          │
        │                          403 / 429 / soft-block, or
        │                          consecutive_failures >= 2N
        │                                          ▼
        │       blacklisted_until < now      ┌─────────────┐
        └────────────────────────────────────│ BLACKLISTED │
                     (→ COOLDOWN)            └─────────────┘

   ┌─────────┐  first successful health check
   │ UNKNOWN │ ──────────────────────────────► HEALTHY
   └─────────┘  (startup state)
```

| State | Selectable? | Meaning |
|---|---|---|
| `UNKNOWN` | ✅ (last resort) | Never health-checked yet |
| `HEALTHY` | ✅ | Normal |
| `DEGRADED` | ✅ (deprioritised) | Failing but not banned — still better than nothing |
| `BLACKLISTED` | ❌ | Temporarily excluded until `blacklisted_until` |
| `COOLDOWN` | ✅ (deprioritised) | Just came off the blacklist; gets one probationary request |

`COOLDOWN` exists so a proxy returning from a 30-minute blacklist does not immediately receive the
full request load and get re-banned within seconds. One success in `COOLDOWN` → `HEALTHY`; one
failure → straight back to `BLACKLISTED` with **doubled** duration.

**Blacklist durations** (doubling on repeat, capped at 2 h):

| Cause | Initial |
|---|---:|
| HTTP 403 | 1800 s |
| HTTP 429 | `Retry-After` value, capped at 600 s |
| Soft block page | 900 s |
| `max_consecutive_failures` reached | 300 s |
| Health check failure | 600 s |

---

## 3. ProxyManager

```python
class ProxyManager:
    def __init__(self, endpoints: list[ProxyEndpoint], *, repo: ProxyRepository,
                 strategy: str = "round_robin", max_consecutive_failures: int = 3,
                 sticky: bool = True): ...

    # selection
    def acquire(self, *, session_key: str | None = None,
                exclude: set[str] | None = None) -> ProxyLease: ...
    def release(self, lease: ProxyLease, *, ok: bool,
                status: int | None = None, latency_ms: float = 0.0,
                outcome: Outcome | None = None) -> None: ...

    # health
    def health_check_all(self, *, timeout: float = 10.0) -> dict[str, bool]: ...
    def start_background_health_checks(self, interval_s: int = 300) -> None: ...

    # admin
    def blacklist(self, key: str, seconds: int, reason: str) -> None: ...
    def reset(self, key: str) -> None: ...
    def stats(self) -> list[ProxyStats]: ...
    def healthy_count(self) -> int: ...
```

### 3.1 Selection strategies

```python
def _selectable(self, exclude) -> list[ProxyRuntime]:
    now = utcnow()
    out = []
    for p in self._pool:
        if p.key in (exclude or ()):                       continue
        if p.state is BLACKLISTED and p.blacklisted_until > now:  continue
        if p.state is BLACKLISTED:                         p.state = COOLDOWN
        out.append(p)
    return out
```

| Strategy | Rule |
|---|---|
| `round_robin` (default) | Index cursor over selectable, ordered by `key` for determinism. Predictable, testable, even distribution. |
| `random` | Uniform over selectable. Less predictable — harder to fingerprint, harder to debug. |
| `least_used` | Minimum `total_requests`; ties broken by oldest `last_used_at`. Best for heterogeneous pools. |

All three sort `HEALTHY` before `COOLDOWN`/`DEGRADED` before `UNKNOWN`, so degraded proxies are used
only when healthy ones are unavailable.

> **What actually shipped.** One strategy exists: **least-recently-used with per-proxy pacing**
> ([12 §14](12-phase-02.md) records the other two as deliberately not built — configuration surface
> with no evidence for choosing between them). P4 orders by **measured target acceptance first, then
> LRU** (§3a), and leaves everything else as built.
>
> **`exclude=tried` is enforced as of P4**, not emergent. [12 §14](12-phase-02.md) previously
> recorded it as a side effect of LRU ordering; `ProxyManager.acquire(exclude=…)` now filters
> explicitly and raises when every usable exit has already been tried for this request. Retrying the
> same failing IP is the classic rotating-proxy bug and must not depend on an ordering accident —
> and the case that proves the difference is a paced pool where the *excluded* exit is the only one
> ready.
>
> **Cooldown scales with pool pressure** (`effective_cooldown = base × healthy/size`), with a
> **floor** that is not a rounding detail: without it, zero healthy proxies yields a zero-second
> cooldown, every blacklisted proxy returns to rotation instantly, `ProxyExhaustedError` becomes
> unreachable, and the entire P4 degradation ladder silently never fires.

### 3.2 Sticky sessions

```python
def acquire(self, *, session_key=None, exclude=None) -> ProxyLease:
    with self._lock:
        if session_key and self.sticky:
            pinned = self._sticky.get(session_key)
            if pinned and self._is_selectable(pinned, exclude):
                return self._lease(pinned, session_key)
            self._sticky.pop(session_key, None)          # pinned proxy went bad → re-pin
        cands = self._selectable(exclude)
        if not cands:
            raise ProxyExhaustedError(
                f"0 of {len(self._pool)} proxies selectable; "
                f"next available in {self._seconds_to_next_available()}s")
        chosen = self._strategy_pick(cands)
        if session_key and self.sticky:
            self._sticky[session_key] = chosen.key
        return self._lease(chosen, session_key)
```

**Why sticky matters here specifically:** a paginated walk through `/r/SaaS/new/` uses a cursor
(`after=t3_…`) that Reddit associates with the requesting session. Rotating IP mid-walk produces
inconsistent pages and looks anomalous. `session_key=f"sub:{subreddit}"` keeps one subreddit's whole
walk on one IP; different subreddits get different IPs, so the pool is still exercised.

Sticky bindings expire after `sticky_ttl_s` (default 1800) so the pool doesn't ossify.

### 3.3 Per-proxy session and header pinning

```python
class ProxyRuntime:
    endpoint: ProxyEndpoint
    session: requests.Session          # own cookie jar, own connection pool
    header_profile: dict               # pinned for this proxy's lifetime
    state: ProxyState
    consecutive_failures: int
    total_requests: int
    total_failures: int
    latency_ms: Deque[float]           # rolling window of 50
    last_used_at: datetime | None
    blacklisted_until: datetime | None
```

Session construction:

```python
s = requests.Session()
s.proxies.update(ep.as_requests_proxies())
s.headers.update(build_headers(profile))
s.mount("https://", HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0))
s.mount("http://",  HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0))
```

`max_retries=0` is deliberate: **all** retry logic lives in `ProxiedHTTPClient` where it can switch
proxies. Urllib3's own retry would re-attempt on the *same* dead proxy, which is exactly wrong.

Connection pooling per proxy is a real win — TLS handshake through a proxy is expensive, and reusing
the connection across a subreddit's pagination walk cuts latency materially.

### 3.4 Health checking

```python
HEALTH_URL = "https://api.ipify.org?format=json"      # NOT Reddit — see below

def _check_one(self, p: ProxyRuntime, timeout: float) -> bool:
    t0 = time.monotonic()
    try:
        r = p.session.get(HEALTH_URL, timeout=(5, timeout))
        ok = r.status_code == 200 and "ip" in r.json()
        exit_ip = r.json().get("ip")
        if ok and exit_ip == self._own_ip:              # proxy silently not applied
            log.error("proxy_leak", proxy=p.key)
            ok = False
        return ok
    except Exception:
        return False
    finally:
        p.latency_ms.append((time.monotonic() - t0) * 1000)
```

**Three deliberate decisions:**

1. **Never health-check against Reddit.** A 10-proxy pool checking every 5 minutes is 120
   extra Reddit requests/hour that produce no data and materially raise the block risk. The one
   thing guaranteed to get a pool banned is health-checking the target.
2. **Verify the exit IP differs from our own.** If a proxy silently fails open, `requests` returns
   a perfectly valid 200 from our real IP. Without this check the tool believes it is proxied when
   it is not — the failure that leaks the operator's home IP to Reddit. This is checked at startup
   and on every background health check, and a leak is a **loud error**, not a warning.
3. Run at startup (blocking, with a summary) and then on a background thread every
   `health_check_interval_s`.

---

## 3a. Target acceptance — the third health signal *(added in P4)*

**Both checks above are necessary and neither is sufficient.** A proxy that returns 200 from
`api.ipify.org` and a soft-block page from the target is reported `healthy` by everything in §3.4 —
and that is exactly the state 8 of 10 proxies were in during the run recorded in
[PHASE-02-STATUS §4.1](PHASE-02-STATUS.md). The health page would have shown them as fine right up
to the moment the retry ladder blacklisted them.

| Signal | Source | Answers |
|---|---|---|
| Reachability | ipify probe | Does the proxy work at all? |
| Leak | exit IP ≠ local IP | Is it actually proxying? |
| **★ Target acceptance** | rolling window of real outcomes: `ok ÷ (ok + blocked)` | Does it work **for this target**? |

`ProxyStats` carries `target_ok`, `target_blocked` and a derived `acceptance_rate`. Three properties
of the implementation are load-bearing:

- **The health probe does not count.** `record_success(..., target=False)` — the probe hits an IP echo
  service, and counting it would report a proxy as accepted on the strength of a request the target
  never saw, which is the blind spot this signal exists to close.
- **Only a refusal counts against it.** A timeout or a reset says the transport failed, not that the
  exit is unwelcome. Collapsing the two would retire good exits on a flaky network.
- **Unknown is not zero.** `acceptance_rate` is `None` before there is evidence, and selection
  ignores it below `ACCEPTANCE_MIN_SAMPLES` (5). At `0.0`-on-no-data, one early success would pin the
  whole pool to a single exit and destroy the spread that LRU selection provides.

Pool-wide acceptance below `POOL_ACCEPTANCE_FLOOR` (0.2, over ≥10 samples) opens the circuit
**before** every proxy has been individually blacklisted — blacklisting needs three consecutive
failures each, so a ten-proxy pool otherwise spends thirty requests learning what this knows after
ten.

**It costs zero extra requests.** It is derived from traffic that is happening anyway. Synthetic
health checks answer *"is it up?"*; only real outcomes answer *"is it useful?"*

Startup output:

```
Proxy pool: 10 loaded · 9 healthy · 1 failed (198.105.121.200:6462 — connect timeout)
Egress verified: 9 distinct exit IPs, none matching local address
```

If **zero** proxies are healthy at startup and `proxy.enabled: true`, the process **refuses to
start** rather than falling back to direct connections. Silent fallback to the operator's own IP is
worse than an outage.

---

## 4. ProxiedHTTPClient

```python
class ProxiedHTTPClient:
    def __init__(self, manager: ProxyManager, cache: HTTPCache | None,
                 policy: RetryPolicy, metrics: Metrics,
                 min_delay_s: float = 3.0, max_delay_s: float = 7.0,
                 connect_timeout: float = 10.0, read_timeout: float = 30.0): ...

    def get(self, url, *, session_key=None, headers=None, timeout=None,
            use_cache=True, max_attempts=None) -> Response:
```

### 4.1 Request algorithm

```
 1. url = normalise(url)
 2. if use_cache and (hit := cache.get(url)) and not hit.expired:
        metrics.inc("http.cache_hit"); return hit.response
 3. tried = set()
 4. for attempt in 1..max_attempts:                        # default 4
 5.     lease = manager.acquire(session_key=session_key, exclude=tried)
 6.     tried.add(lease.key)
 7.     _throttle(lease)                                    # per-proxy random 3–7 s since its last use
 8.     t0 = monotonic()
 9.     try:  resp = lease.session.get(url, timeout=(connect, read), headers=headers)
10.     except Exception as e:  outcome = classify_exception(e); resp = None
11.     else:                   outcome = classify_response(resp)
12.     latency = (monotonic() - t0) * 1000
13.     manager.release(lease, ok=(outcome is OK), status=..., latency_ms=latency, outcome=outcome)
14.     metrics.observe("http.latency_ms", latency, proxy=lease.key, outcome=outcome.name)
15.     if outcome is OK:
16.         if use_cache: cache.put(url, resp, ttl)         # only OK responses are ever cached
17.         return resp
18.     if outcome is NOT_FOUND:                            raise NotFoundError(url)
19.     apply_proxy_penalty(manager, lease, outcome, resp)  # blacklist / failure count
20.     sleep(backoff(attempt, outcome, resp))              # honours Retry-After for 429
21. raise ScraperError(f"{url}: {max_attempts} attempts failed, last={outcome.name}")
```

**Line 7 is the throttle and it is per proxy, not global.** Each `ProxyRuntime` records
`last_used_at`; the client sleeps only the remainder of that proxy's own delay window. Ten proxies
therefore yield ten times the aggregate throughput of one without any proxy exceeding its individual
rate. This is the mechanism that turns "10 proxies" into actual capacity rather than just IP
diversity.

**Line 5's `exclude=tried`** guarantees each retry uses a *different* proxy while any is available.
Retrying the same failing IP four times is the single most common rotating-proxy bug.

**Line 16 never caches a non-OK response**, and `classify_response` treats a soft-block page as
non-OK. See [07 §6.4](07-scraping-pipeline.md) — caching a block page silently zeroes a run.

### 4.2 Backoff

```python
def backoff(attempt: int, outcome: Outcome, resp) -> float:
    if outcome is RATE_LIMITED and resp is not None:
        try:    return min(float(resp.headers.get("Retry-After", 60)), 600)
        except (TypeError, ValueError):  pass
    base = min(60.0, 2.0 ** attempt)          # 2, 4, 8, 16 …
    return base * random.uniform(0.7, 1.3)    # jitter avoids synchronised retry storms
```

### 4.3 Timeouts

`timeout=(connect, read)` is always a **tuple**. A scalar timeout in `requests` applies to each
socket operation independently, so a slow-trickle response can hang far longer than the number
suggests. Defaults: connect 10 s, read 30 s. Health checks use `(5, 10)`.

---

## 5. Circuit breaker

Individual proxy failures are normal. **Pool-wide** failure means something systemic — Reddit
blocking the whole Webshare ASN, the proxy account expiring, or the local network being down — and
hammering it makes it worse.

```python
class PoolCircuitBreaker:
    """Opens when the pool-wide failure rate exceeds a threshold over a rolling window."""
    window_s: int = 120
    min_samples: int = 20
    failure_threshold: float = 0.8
    open_duration_s: int = 300

    def allow(self) -> bool: ...
    def record(self, ok: bool) -> None: ...
```

When **open**: all `get()` calls raise `CircuitOpenError` immediately. Scrape jobs fail as
retryable and back off; the run stays alive and resumes when the circuit half-opens (one probe
request; success closes it, failure reopens for a doubled duration).

This turns "Reddit blocked us" from a 400-failed-request thrash into a clean pause with a
diagnosable message.

---

## 6. Metrics and health surface

Per proxy (`proxies` table + in-memory rolling window):

| Field | Use |
|---|---|
| `state`, `blacklisted_until` | Selection |
| `consecutive_failures` | State transitions |
| `total_requests`, `total_failures` | Lifetime success rate |
| `avg_latency_ms` (p50/p95 from the rolling window) | Ranking, diagnostics |
| `last_used_at`, `last_ok_at`, `last_error` | Debugging |

Pool-level metrics: `healthy_count`, `blacklisted_count`, requests/min, aggregate success rate,
circuit state.

**`GET /health/proxies`** (HTML + JSON) renders:

```
Pool: 10 total · 8 healthy · 1 cooldown · 1 blacklisted (3m 12s remaining)
Circuit: CLOSED       Requests/min: 47       Success: 96.2%

 proxy               state         reqs   fail   p50     p95    last error
 31.59.20.176:6754   healthy       412    3      840ms   2.1s   —
 45.38.107.97:6014   healthy       398    7      910ms   2.4s   read timeout (12m ago)
 198.105.121.200:6462 blacklisted  201    41     1.4s    5.8s   HTTP 403 (3m ago)
 …
```

Credentials appear nowhere. Every row is `ip:port`.

---

## 7. Configuration

```yaml
proxy:
  enabled: true
  file: "${PROXY_FILE}"
  strategy: round_robin              # round_robin | random | least_used
  sticky_sessions: true
  sticky_ttl_s: 1800

  health_check_url: "https://api.ipify.org?format=json"
  health_check_interval_s: 300
  health_check_on_start: true
  verify_egress_differs: true        # fail loudly if a proxy exits from our own IP

  max_consecutive_failures: 3
  blacklist_seconds: 900
  blacklist_max_seconds: 7200

  connect_timeout_s: 10
  read_timeout_s: 30
  max_attempts: 4

  min_delay_s: 3.0
  max_delay_s: 7.0

  circuit_window_s: 120
  circuit_failure_threshold: 0.8
  circuit_open_seconds: 300

  fail_closed: true                  # ⚠️ SUPERSEDED IN P4 — see below
```

> ⚠️ **`fail_closed` was replaced in P4 by `network.on_pool_exhausted`.** The key is still read, and
> a machine with no `network:` block still behaves exactly as described here — but the three-value
> policy below is what ships. **The original reasoning is retained rather than deleted**, because it
> was correct and only half of it changed:
>
> > `fail_closed: true` is the default and should stay that way. Setting it to `false` means the tool
> > will scrape Reddit from the operator's own IP when the pool dies — which is exactly the situation
> > proxies exist to prevent.
>
> That objection is to an **unbounded, silent** fallback, and it stands. What P4 adds is a fallback
> that is neither: a per-hour governor on the operator's own address
> (`network.direct.max_requests_per_hour`, 120), a class allowlist, and a **visible `run_events`
> warning** every time it happens. A capped, logged fallback is a different thing from the uncapped
> one this decision rejected ([29 §2.2](29-network-and-proxy-strategy.md)).

```yaml
network:
  policy: prefer_proxy           # which providers are ELIGIBLE
  ladder: [direct, dc]           # what ORDER they are tried in
  on_pool_exhausted: degrade_to_direct
  direct:
    max_requests_per_hour: 120
    classes: [rss, health, website]     # always direct (R18)
```

| `on_pool_exhausted` | Behaviour | When to choose it |
|---|---|---|
| `degrade_to_direct` | Continue on the direct connection, under the governor, and log a visible `run_events` warning | **Default.** A truncated run is worse than a slower one |
| `pause_run` | Raises with `retryable=True`; the run resumes when the pool recovers | When IP exposure genuinely matters more than latency |
| `fail_run` | This section's original `fail_closed` behaviour | Kept for compliance situations |

**Policy and ladder are two axes, deliberately.** `policy` answers *which providers may be used*;
`ladder` answers *in what order*. P0 measured the direct connection at 100% success against the
datacenter pool's 71.4% ([SPRINT-0 §1.2](SPRINT-0-MEASUREMENTS.md)), so the shipped ladder is
`[direct, dc]`. Encoding order in the eligibility enum would have made re-measuring a code change.

**Rollback:** `policy: proxy_only` + `on_pool_exhausted: fail_run` reproduces this section exactly.

---

## 8. Error hierarchy

```
NetworkError (base)
├── ProxyConfigError        # file missing / unparseable / empty        → fatal at startup
├── ProxyExhaustedError     # no selectable proxy right now             → fatal for the job
├── CircuitOpenError        # pool-wide failure                         → retryable, long backoff
├── ScraperError            # all attempts for one URL failed           → caller returns None
│   ├── RateLimitedError
│   ├── ForbiddenError
│   ├── SoftBlockError
│   └── NotFoundError       # never retried
└── ProxyLeakError          # exit IP == our own IP                     → fatal, loud
```

`ProxyLeakError` is fatal by design. Continuing after detecting that traffic is not actually
proxied would silently violate the project's stated requirement.

---

## 9. Testing

All tests run offline via `responses` / `requests-mock`.

| Test | Asserts |
|---|---|
| `test_parse_valid_file` | 10 endpoints from the real format |
| `test_parse_skips_malformed` | Bad lines skipped; **log message contains no password** |
| `test_parse_rejects_empty` | `ProxyConfigError` |
| `test_url_shape` | `http://` scheme for both `http` and `https` keys; credentials URL-quoted |
| `test_repr_redacts` | `repr(endpoint)` and `str(endpoint)` contain neither username nor password |
| `test_round_robin_even` | 100 acquires over 10 proxies → exactly 10 each |
| `test_excludes_blacklisted` | Blacklisted never selected until expiry |
| `test_cooldown_probation` | Post-blacklist proxy gets one request; failure re-blacklists with doubled duration |
| `test_sticky_pins` | Same `session_key` → same proxy across 20 acquires |
| `test_sticky_repins_on_failure` | Pinned proxy blacklisted → new proxy pinned |
| `test_exhaustion_raises` | All blacklisted → `ProxyExhaustedError` naming seconds-to-next |
| `test_retry_uses_different_proxy` | 3 failures → 3 distinct proxies in `tried` |
| `test_429_honours_retry_after` | `Retry-After: 42` → sleep ≈42 s (clock patched) |
| `test_403_blacklists` | Proxy blacklisted 1800 s |
| `test_soft_block_not_cached` | 200 + "Just a moment" → not cached, proxy blacklisted, retried |
| `test_404_no_retry` | Exactly one request issued |
| `test_backoff_growth` | Delays are monotonically increasing within jitter bounds |
| `test_circuit_opens_and_recovers` | 80% failure over the window opens; probe closes |
| `test_egress_leak_detected` | Health endpoint returns our own IP → `ProxyLeakError` |
| `test_per_proxy_throttle` | 10 requests across 10 proxies complete without 10× the single-proxy delay |
| `test_no_secret_in_any_log` | Full log capture across a whole test run, grepped for the password |

The last test is a standing guard: it runs a representative workload and asserts the captured log
output contains neither the username nor the password from the fixture file.

---

## 10. Reuse beyond Reddit

Because `src/net/` has no Reddit knowledge:

| Consumer | Phase | Egress class | Benefit |
|---|---|---|---|
| `RedditClient` | 1 | `html` / `comments` | Rotation, retry, caching, metrics |
| **`WebsiteFetcher`** | **P13** | **`website` — always DIRECT** | See the correction below |
| Subreddit validator | P17 | `validation` | Live validation without a separate transport |
| Comment scraper | P8–P11 | `comments` | One transport, one policy |
| RSS discovery | P5–P6 | `rss` — always direct | Published feed, low volume |
| Any future source | — | — | Implement a parser; egress is solved |

> ⚠️ **Correction, P4.** This section previously listed `WebsiteFetcher` as a proxy-pool consumer and
> called it *"the payoff for building the proxy layer first."* **It is the opposite.** A bounded,
> polite, seven-page crawl of a site whose owner is the operator's own customer is the one fetch in
> the system that should be **direct and consistent**: arriving from ten rotating datacenter IPs
> looks like an attack, and the customer is the person the operator least wants to alarm.
>
> `website` is therefore in the `ALWAYS_DIRECT` set ([R18](ARCHITECTURE_FREEZE.md)) — enforced in
> `src/net/policy.py`, unaffected by `policy`, by the ladder, or by editing
> `network.direct.classes`. See [29 §2](29-network-and-proxy-strategy.md), where the error was
> identified before P13 could ship it.

The reuse claim itself holds, and P4 strengthened it: `src/net/` now contains **zero** Reddit
identifiers in executable code, enforced by grep fence 4
(`tests/test_boundaries.py::test_the_network_layer_has_no_reddit_knowledge`). Target-specific
soft-block signatures are injected by the caller, so P13 fetches a customer's website without
Reddit's interstitial heuristics being applied to it. Every later network consumer is a parser plus a
schema, not a transport project.
