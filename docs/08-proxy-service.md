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

  fail_closed: true                  # refuse to start if 0 healthy proxies
```

`fail_closed: true` is the default and should stay that way. Setting it to `false` means the tool
will scrape Reddit from the operator's own IP when the pool dies — which is exactly the situation
proxies exist to prevent.

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

| Consumer | Phase | Benefit |
|---|---|---|
| `RedditClient` | 1 | Rotation, retry, caching, metrics |
| `WebsiteFetcher` | 4 | Target sites that rate-limit or geo-block are handled identically |
| Subreddit validator | 5 | Live validation without a separate transport |
| Comment scraper | 6 | Sticky sessions per subreddit |
| Any future source | — | Implement a parser; egress is solved |

This is the payoff for building the proxy layer first: every later network consumer is a parser plus
a schema, not a transport project.
