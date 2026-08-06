"""P0 Track A — transport comparison: Direct vs Webshare.

Answers U8 ("what is the block rate at the reduced request volume?") and
produces the recommendation the P0 brief asks for.

**What makes this measurement honest.**

1. It uses the *shipped* header profiles and the *shipped* block classifier.
   A probe that hand-rolled either would measure the probe, not the transport.
2. It paces requests like the production client (randomised 3–7 s per exit).
   Firing a burst measures how a target responds to a burst, which is not the
   question.
3. It classifies a 200 that contains no posts as a **soft block**, not a
   success. ``docs/PHASE-02-STATUS.md`` §3.3 records a real 311 KB, HTTP 200,
   zero-post interstitial; counting that as success would invert the result.
4. It reports failures per *class*, not as one number. "33% failed" is not
   actionable; "33% were soft blocks and 0% were timeouts" is.
"""

from __future__ import annotations

import contextlib
import json
import statistics
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.probe.transport import TransportManager, TransportResult, polite_sleep  # noqa: E402
from src.net.blocks import BlockKind  # noqa: E402
from src.net.blocks import classify as classify_block

# A deliberately small, representative workload. It mirrors the steady-state
# pattern in docs/28 §7.3 rather than a scrape burst: a few listing pages, one
# short pagination walk, one search, one subreddit metadata page.
SUBREDDITS = ["SaaS", "startups", "Entrepreneur", "marketing"]


@dataclass
class Attempt:
    transport: str
    exit_label: str
    url: str
    status: int | None
    outcome: str  # ok | hard_block | soft_block | empty | rate_limited | not_found | server_error | timeout | network
    latency_ms: float
    size: int
    posts_found: int
    error: str | None = None


@dataclass
class TransportReport:
    transport: str
    attempts: list[Attempt] = field(default_factory=list)
    cpu_seconds: float = 0.0
    peak_memory_kb: float = 0.0

    # ---- derived ---------------------------------------------------------
    @property
    def total(self) -> int:
        return len(self.attempts)

    @property
    def ok(self) -> list[Attempt]:
        return [a for a in self.attempts if a.outcome == "ok"]

    @property
    def failures(self) -> list[Attempt]:
        return [a for a in self.attempts if a.outcome != "ok"]

    @property
    def success_rate(self) -> float:
        return len(self.ok) / self.total if self.total else 0.0

    @property
    def block_rate(self) -> float:
        blocked = [a for a in self.attempts if a.outcome in ("hard_block", "soft_block")]
        return len(blocked) / self.total if self.total else 0.0

    def outcome_mix(self) -> dict[str, int]:
        mix: dict[str, int] = {}
        for a in self.attempts:
            mix[a.outcome] = mix.get(a.outcome, 0) + 1
        return dict(sorted(mix.items(), key=lambda kv: -kv[1]))

    def _lat(self, subset: list[Attempt]) -> dict[str, float]:
        if not subset:
            return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
        xs = sorted(a.latency_ms for a in subset)
        return {
            "mean": round(statistics.fmean(xs), 1),
            "p50": round(xs[len(xs) // 2], 1),
            "p95": round(xs[min(len(xs) - 1, int(len(xs) * 0.95))], 1),
        }

    def summary(self) -> dict:
        exits_used = {a.exit_label for a in self.attempts}
        exits_ok = {a.exit_label for a in self.ok}
        return {
            "transport": self.transport,
            "requests": self.total,
            "success_rate": round(self.success_rate, 3),
            "block_rate": round(self.block_rate, 3),
            "outcome_mix": self.outcome_mix(),
            "latency_ok_ms": self._lat(self.ok),
            "latency_fail_ms": self._lat(self.failures),
            "total_posts_found": sum(a.posts_found for a in self.ok),
            "exits_used": len(exits_used),
            "exits_that_ever_succeeded": len(exits_ok),
            "cpu_seconds": round(self.cpu_seconds, 3),
            "peak_memory_kb": round(self.peak_memory_kb, 1),
        }


def _count_posts(body: bytes) -> int:
    """Cheap, parser-free signal for 'did this page actually contain posts?'."""
    text = body.decode("utf-8", errors="ignore")
    return text.count('data-fullname="t3_') or text.count("<entry")


def _classify(res: TransportResult) -> tuple[str, int]:
    """Map a transport result onto an outcome class using the shipped classifier."""
    if res.error:
        low = res.error.lower()
        if "timeout" in low:
            return "timeout", 0
        return "network", 0
    if res.status == 429:
        return "rate_limited", 0
    if res.status == 404:
        return "not_found", 0
    if res.status and res.status >= 500:
        return "server_error", 0
    if res.status == 403:
        return "hard_block", 0
    if res.status != 200:
        return "network", 0

    posts = _count_posts(res.body)
    text = res.body.decode("utf-8", errors="ignore")
    verdict = classify_block(res.status, text, expect_selector_hits=posts)
    if verdict.kind is BlockKind.HARD:
        return "hard_block", posts
    if verdict.kind is BlockKind.SOFT:
        return "soft_block", posts
    if verdict.kind is BlockKind.EMPTY:
        return "empty", posts
    return ("ok" if posts > 0 else "empty"), posts


def _workload() -> list[tuple[str, str]]:
    """(session_key, url) pairs — the steady-state shape, not a burst."""
    jobs: list[tuple[str, str]] = []
    for sub in SUBREDDITS:
        jobs.append((f"sub:{sub}", f"https://old.reddit.com/r/{sub}/new/"))
    # one short pagination walk on the first subreddit, to test cursor stability
    jobs.append((f"sub:{SUBREDDITS[0]}", f"https://old.reddit.com/r/{SUBREDDITS[0]}/new/?count=25"))
    # one restricted search
    jobs.append(
        (
            f"sub:{SUBREDDITS[0]}",
            f"https://old.reddit.com/r/{SUBREDDITS[0]}/search?q=%22looking+for%22"
            "&restrict_sr=on&sort=new",
        )
    )
    # one metadata page
    jobs.append((f"sub:{SUBREDDITS[1]}", f"https://old.reddit.com/r/{SUBREDDITS[1]}/"))
    return jobs


def run(manager: TransportManager, transport: str, *, pace: bool = True) -> TransportReport:
    report = TransportReport(transport=transport)
    tracemalloc.start()
    cpu0 = time.process_time()
    for i, (session_key, url) in enumerate(_workload()):
        res = manager.get(url, transport=transport, session_key=session_key, timeout=(10.0, 30.0))
        outcome, posts = _classify(res)
        report.attempts.append(
            Attempt(
                transport=transport,
                exit_label=res.exit_label,
                url=url,
                status=res.status,
                outcome=outcome,
                latency_ms=round(res.latency_ms, 1),
                size=res.size,
                posts_found=posts,
                error=res.error,
            )
        )
        print(
            f"  [{transport:8}] {outcome:12} {str(res.status or '-'):>4} "
            f"{res.latency_ms:7.0f}ms {res.size:>7}B posts={posts:<3} {res.exit_label}"
        )
        if pace and i < len(_workload()) - 1:
            polite_sleep()
    report.cpu_seconds = time.process_time() - cpu0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report.peak_memory_kb = peak / 1024
    return report


def verify_egress(manager: TransportManager, transport: str) -> dict:
    """Leak check: does traffic actually leave from a different address?

    ``docs/08 §3.4`` calls this the single failure the pool exists to prevent.
    A probe that skipped it could recommend a proxy that was never proxying.
    """
    out: dict = {"transport": transport, "local_ip": None, "exit_ips": [], "leaking": []}
    local = manager.get("https://api.ipify.org?format=json", transport="direct")
    if local.ok:
        with contextlib.suppress(Exception):
            out["local_ip"] = json.loads(local.body)["ip"]
    if transport == "direct":
        out["exit_ips"] = [out["local_ip"]] if out["local_ip"] else []
        return out
    provider = manager.provider(transport)
    for exit_label in provider.exits():
        r = manager.get(
            "https://api.ipify.org?format=json",
            transport=transport,
            session_key=f"leakcheck:{exit_label}",
        )
        ip = None
        if r.ok:
            with contextlib.suppress(Exception):
                ip = json.loads(r.body)["ip"]
        out["exit_ips"].append({"exit": r.exit_label, "ip": ip, "status": r.status})
        if ip and ip == out["local_ip"]:
            out["leaking"].append(r.exit_label)
        time.sleep(0.4)
    return out


def recommend(direct: TransportReport, proxy: TransportReport | None) -> dict:
    """The recommendation the brief asks for, derived from the measurements."""
    if proxy is None or proxy.total == 0:
        return {
            "recommendation": "direct",
            "reason": "No proxy transport could be constructed or exercised.",
        }
    d, p = direct.success_rate, proxy.success_rate
    margin = 0.10  # 10 percentage points — below this the transports are 'similar'
    if d > p + margin:
        rec, why = (
            "direct",
            (f"Direct succeeded on {d:.0%} of requests versus {p:.0%} through Webshare."),
        )
    elif p > d + margin:
        rec, why = "webshare", (f"Webshare succeeded on {p:.0%} of requests versus {d:.0%} direct.")
    else:
        rec, why = (
            "direct_with_webshare_fallback",
            (
                f"Success rates are within {margin:.0%} ({d:.0%} direct vs {p:.0%} Webshare); "
                "direct is preferred as the default because it exposes no third-party "
                "dependency and no bandwidth cost, with Webshare retained as the "
                "degradation step."
            ),
        )
    return {
        "recommendation": rec,
        "reason": why,
        "direct_success_rate": round(d, 3),
        "webshare_success_rate": round(p, 3),
        "direct_block_rate": round(direct.block_rate, 3),
        "webshare_block_rate": round(proxy.block_rate, 3),
        "direct_mean_ok_latency_ms": direct.summary()["latency_ok_ms"]["mean"],
        "webshare_mean_ok_latency_ms": proxy.summary()["latency_ok_ms"]["mean"],
    }


def main(proxy_file: str | None = None) -> dict:
    from scripts.probe.transport import build_manager

    manager = build_manager(proxy_file)
    print(f"transports available: {manager.available}")

    print("\n-- direct --")
    direct = run(manager, "direct")

    proxy: TransportReport | None = None
    if "webshare" in manager.available:
        print("\n-- webshare --")
        proxy = run(manager, "webshare")

    print("\n-- egress verification --")
    egress = {"direct": verify_egress(manager, "direct")}
    if proxy is not None:
        egress["webshare"] = verify_egress(manager, "webshare")

    result = {
        "direct": direct.summary(),
        "webshare": proxy.summary() if proxy else None,
        "egress": egress,
        "recommendation": recommend(direct, proxy),
        "attempts": [asdict(a) for a in direct.attempts]
        + ([asdict(a) for a in proxy.attempts] if proxy else []),
    }
    return result


if __name__ == "__main__":
    pf = sys.argv[1] if len(sys.argv) > 1 else None
    out = main(pf)
    print("\n" + json.dumps({k: v for k, v in out.items() if k != "attempts"}, indent=2))
