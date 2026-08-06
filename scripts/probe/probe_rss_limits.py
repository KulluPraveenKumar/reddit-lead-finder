"""P0 Track A — RSS rate-limit characterisation.

The first RSS pass established that one request succeeds and everything after it
is refused. That is the single most consequential unknown in
``docs/28-discovery-redesign.md``, because it decides whether steady-state
discovery costs 28 requests a day or is not viable at all.

This probe answers, in order:

* What does the 429 actually say? (``Retry-After``, ``x-ratelimit-*``)
* How long is the recovery window?
* Is the budget **per feed** or **per IP**? (U1)
* Once recovered, do multireddit, restricted search and boolean search work?
  (U3, and the multireddit assumption)
* Does ``old.reddit.com`` behave the same as ``www``? (U6)

It is deliberately slow. Hammering a rate limit to learn its shape would be both
rude and self-defeating — the answer would describe the penalty box rather than
the budget.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from scripts.probe.transport import build_manager  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
INTERESTING = (
    "retry-after",
    "x-ratelimit-used",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "cache-control",
    "expires",
    "etag",
    "last-modified",
    "age",
    "x-served-by",
)


def _entries(body: bytes) -> int:
    try:
        return len(etree.fromstring(body).findall(f"{ATOM}entry"))
    except Exception:  # noqa: BLE001
        return 0


def _subs(body: bytes) -> list[str]:
    import re

    try:
        root = etree.fromstring(body)
    except Exception:  # noqa: BLE001
        return []
    out = set()
    for e in root.findall(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link")
        href = link.get("href", "") if link is not None else ""
        m = re.search(r"/r/([A-Za-z0-9_]+)/", href)
        if m:
            out.add(m.group(1).lower())
    return sorted(out)


def fetch(session, url: str, label: str) -> dict:
    t0 = time.monotonic()
    try:
        r = session.get(url, timeout=(10, 30))
    except Exception as exc:  # noqa: BLE001
        return {"label": label, "url": url, "error": f"{type(exc).__name__}: {exc}"[:120]}
    hdrs = {k: v for k, v in r.headers.items() if k.lower() in INTERESTING}
    rec = {
        "label": label,
        "url": url,
        "status": r.status_code,
        "bytes": len(r.content),
        "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        "entries": _entries(r.content) if r.status_code == 200 else 0,
        "subreddits": _subs(r.content) if r.status_code == 200 else [],
        "headers": hdrs,
    }
    print(
        f"  {label:<28} {rec['status']:>4}  {rec['entries']:>3} entries  "
        f"{rec['bytes']:>7}B  {rec['latency_ms']:>7.0f}ms  {hdrs or ''}"
    )
    return rec


def main() -> dict:
    mgr = build_manager()
    session = mgr.provider("direct")._session  # one address, deliberately
    out: dict = {"steps": []}

    print("Cooling down 75s before first probe...")
    time.sleep(75)

    # 1. Baseline — should succeed after the cooldown.
    a = fetch(session, "https://www.reddit.com/r/SaaS/new/.rss?limit=25", "baseline_SaaS")
    out["steps"].append(a)

    # 2. Immediately fetch a DIFFERENT feed. This is U1.
    b = fetch(
        session, "https://www.reddit.com/r/startups/new/.rss?limit=25", "immediate_different_feed"
    )
    out["steps"].append(b)

    if a.get("status") == 200 and b.get("status") == 200:
        out["U1_verdict"] = "per_feed"
        out["U1_note"] = "Two distinct feeds succeeded back to back from one address."
    elif a.get("status") == 200 and b.get("status") == 429:
        out["U1_verdict"] = "per_ip"
        out["U1_note"] = (
            "A second, different feed was refused immediately after a "
            "successful one from the same address."
        )
    else:
        out["U1_verdict"] = "inconclusive"
        out["U1_note"] = f"baseline={a.get('status')}, second={b.get('status')}"

    # 3. Recovery ladder — how long until the budget returns?
    print("\nRecovery ladder:")
    recovery = []
    for wait in (30, 30, 30, 60):
        print(f"  waiting {wait}s...")
        time.sleep(wait)
        elapsed = sum(x["waited"] for x in recovery) + wait
        r = fetch(
            session, "https://www.reddit.com/r/SaaS/new/.rss?limit=25", f"recovery_after_{elapsed}s"
        )
        recovery.append({"waited": wait, "cumulative_s": elapsed, "status": r.get("status")})
        out["steps"].append(r)
        if r.get("status") == 200:
            out["recovery_seconds"] = elapsed
            break
    out["recovery_ladder"] = recovery
    out.setdefault("recovery_seconds", None)

    # 4. Feature probes, each after a full recovery wait.
    features = [
        ("multireddit", "https://www.reddit.com/r/SaaS+startups+Entrepreneur/new/.rss?limit=100"),
        (
            "restricted_search",
            "https://www.reddit.com/r/SaaS/search.rss?q=%22looking+for%22"
            "&restrict_sr=1&sort=new&limit=25",
        ),
        (
            "boolean_search",
            "https://www.reddit.com/search.rss?q=%28subreddit%3ASaaS+OR+subreddit%3Astartups"
            "%29+AND+%22looking+for%22&sort=new&limit=50",
        ),
        ("old_reddit_host", "https://old.reddit.com/r/SaaS/new/.rss?limit=25"),
    ]
    gap = max(out.get("recovery_seconds") or 90, 90)
    print(f"\nFeature probes, {gap}s apart:")
    for label, url in features:
        time.sleep(gap)
        out["steps"].append(fetch(session, url, label))

    # ---- verdicts -------------------------------------------------------
    by_label = {s["label"]: s for s in out["steps"]}

    def ok(label: str) -> bool:
        s = by_label.get(label, {})
        return s.get("status") == 200 and s.get("entries", 0) > 0

    multi = by_label.get("multireddit", {})
    out["verdicts"] = {
        "multireddit_works": ok("multireddit"),
        "multireddit_distinct_subreddits": len(multi.get("subreddits", [])),
        "restricted_search_works": ok("restricted_search"),
        "U3_boolean_search_works": (
            ok("boolean_search")
            and len(by_label.get("boolean_search", {}).get("subreddits", [])) > 1
        ),
        "U6_old_host_works": ok("old_reddit_host"),
    }
    return out


if __name__ == "__main__":
    result = main()
    print("\n" + json.dumps(result, indent=2))
