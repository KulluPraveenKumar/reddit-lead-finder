"""P0 Track A — RSS validation.

Settles U1–U6 from ``docs/31-execution-plan.md`` §3.1 and every RSS assumption
in ``docs/28-discovery-redesign.md``, which is currently sourced from
third-party writing rather than from a live probe.

The four that change the arithmetic:

* **U1** per-feed or per-IP rate limit — decides whether multireddit combining
  is optional or mandatory.
* **U2** does ``<content>`` carry full selftext — decides whether RSS replaces
  the listing fetch (−66%) or only augments it (−28%).
* **U3** boolean ``subreddit:a OR subreddit:b`` in search — 12 requests or 120.
* **U4** conditional GET — decides whether an idle poll costs ~0 bytes.

RSS is fetched **through** a transport, never instead of one. This module takes
a ``TransportManager`` and never constructs a session of its own.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import UTC

from lxml import etree  # noqa: E402

from scripts.probe.transport import TransportManager, polite_sleep  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
HOSTS = ["https://www.reddit.com", "https://old.reddit.com"]
SUBS = ["SaaS", "startups", "Entrepreneur", "marketing", "smallbusiness"]


@dataclass
class FeedShape:
    """What a parsed feed actually contained — the answer to U2 and U5."""

    url: str
    status: int | None
    entries: int
    has_title: bool = False
    has_author: bool = False
    has_link: bool = False
    has_updated: bool = False
    has_content: bool = False
    content_max_chars: int = 0
    content_median_chars: int = 0
    looks_like_selftext: bool = False
    subreddits_seen: list[str] = field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None


def parse_feed(body: bytes, url: str, status: int | None, headers: dict | None = None) -> FeedShape:
    shape = FeedShape(url=url, status=status, entries=0)
    if headers:
        shape.etag = headers.get("ETag")
        shape.last_modified = headers.get("Last-Modified")
    if not body:
        return shape
    try:
        root = etree.fromstring(body)
    except Exception as exc:  # noqa: BLE001
        shape.error = f"parse failed: {type(exc).__name__}: {exc}"[:150]
        return shape

    entries = root.findall(f"{ATOM}entry")
    shape.entries = len(entries)
    lengths: list[int] = []
    subs: set[str] = set()
    for e in entries:
        if e.find(f"{ATOM}title") is not None:
            shape.has_title = True
        if e.find(f"{ATOM}author/{ATOM}name") is not None:
            shape.has_author = True
        if e.find(f"{ATOM}link") is not None:
            shape.has_link = True
        if e.find(f"{ATOM}updated") is not None:
            shape.has_updated = True
        c = e.find(f"{ATOM}content")
        if c is not None and c.text:
            shape.has_content = True
            lengths.append(len(c.text))
        link_el = e.find(f"{ATOM}link")
        href = link_el.get("href", "") if link_el is not None else ""
        m = re.search(r"/r/([A-Za-z0-9_]+)/", href)
        if m:
            subs.add(m.group(1).lower())
    if lengths:
        lengths.sort()
        shape.content_max_chars = lengths[-1]
        shape.content_median_chars = lengths[len(lengths) // 2]
        # Reddit wraps every entry's content in a "submitted by" footer. Real
        # selftext pushes the median well past that boilerplate.
        shape.looks_like_selftext = shape.content_median_chars > 600
    shape.subreddits_seen = sorted(subs)
    return shape


def _fetch(mgr: TransportManager, url: str, transport: str, extra_headers: dict | None = None):
    return mgr.get(
        url,
        transport=transport,
        session_key="rss",
        timeout=(10.0, 30.0),
        extra_headers=extra_headers,
    )


def probe_u5_u2(mgr: TransportManager, transport: str) -> dict:
    """U5 (limit honoured) and U2 (selftext present)."""
    url = f"{HOSTS[0]}/r/{SUBS[0]}/new/.rss?limit=100"
    r = _fetch(mgr, url, transport)
    shape = parse_feed(r.body, url, r.status)
    return {
        "url": url,
        "status": r.status,
        "bytes": r.size,
        "entries": shape.entries,
        "limit_100_honoured": shape.entries > 25,
        "fields": {
            "title": shape.has_title,
            "author": shape.has_author,
            "link": shape.has_link,
            "updated": shape.has_updated,
            "content": shape.has_content,
        },
        "content_median_chars": shape.content_median_chars,
        "content_max_chars": shape.content_max_chars,
        "U2_selftext_present": shape.looks_like_selftext,
        "error": shape.error,
    }


def probe_u6_host_parity(mgr: TransportManager, transport: str) -> dict:
    """U6 — does old.reddit serve the same feed as www?"""
    out = {}
    for host in HOSTS:
        url = f"{host}/r/{SUBS[0]}/new/.rss?limit=25"
        r = _fetch(mgr, url, transport)
        s = parse_feed(r.body, url, r.status)
        out[host] = {"status": r.status, "entries": s.entries, "bytes": r.size, "error": s.error}
        polite_sleep(2.0, 4.0)
    a, b = out[HOSTS[0]], out[HOSTS[1]]
    out["parity"] = a["status"] == b["status"] and a["entries"] == b["entries"] and a["entries"] > 0
    return out


def probe_multireddit(mgr: TransportManager, transport: str) -> dict:
    """Can one request cover many subreddits? The whole request-reduction case."""
    combined = "+".join(SUBS)
    url = f"{HOSTS[0]}/r/{combined}/new/.rss?limit=100"
    r = _fetch(mgr, url, transport)
    s = parse_feed(r.body, url, r.status)
    return {
        "url": url,
        "status": r.status,
        "entries": s.entries,
        "bytes": r.size,
        "subreddits_requested": len(SUBS),
        "distinct_subreddits_in_feed": len(s.subreddits_seen),
        "subreddits_seen": s.subreddits_seen,
        "multireddit_works": r.status == 200 and len(s.subreddits_seen) > 1,
        "error": s.error,
    }


def probe_u3_search(mgr: TransportManager, transport: str) -> dict:
    """U3 — restricted search feed, and boolean multi-subreddit search."""
    simple = (
        f"{HOSTS[0]}/r/{SUBS[0]}/search.rss?q=%22looking+for%22&restrict_sr=1&sort=new&limit=25"
    )
    r1 = _fetch(mgr, simple, transport)
    s1 = parse_feed(r1.body, simple, r1.status)
    polite_sleep(3.0, 5.0)

    q = f'(subreddit:{SUBS[0]} OR subreddit:{SUBS[1]}) AND "looking for"'
    boolean = f"{HOSTS[0]}/search.rss?q={requests_quote(q)}&sort=new&limit=50"
    r2 = _fetch(mgr, boolean, transport)
    s2 = parse_feed(r2.body, boolean, r2.status)
    return {
        "restricted_search": {
            "url": simple,
            "status": r1.status,
            "entries": s1.entries,
            "works": r1.status == 200 and s1.entries > 0,
            "error": s1.error,
        },
        "boolean_multi_subreddit": {
            "url": boolean,
            "status": r2.status,
            "entries": s2.entries,
            "distinct_subreddits": len(s2.subreddits_seen),
            "subreddits_seen": s2.subreddits_seen,
            "U3_works": (r2.status == 200 and s2.entries > 0 and len(s2.subreddits_seen) > 1),
            "error": s2.error,
        },
    }


def requests_quote(s: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(s)


def probe_u4_conditional(mgr: TransportManager, transport: str) -> dict:
    """U4 — does Reddit honour If-None-Match / If-Modified-Since?"""
    url = f"{HOSTS[0]}/r/{SUBS[0]}/new/.rss?limit=25"
    provider = mgr.provider(transport)
    # We need response headers, which TransportResult does not carry; use the
    # provider's own session directly for this one probe only.
    sess = getattr(provider, "_session", None)
    if sess is None:
        return {"supported": None, "note": "transport has no single session to inspect"}
    r1 = sess.get(url, timeout=(10, 30))
    etag = r1.headers.get("ETag")
    last_mod = r1.headers.get("Last-Modified")
    cache_control = r1.headers.get("Cache-Control")
    result = {
        "first_status": r1.status_code,
        "first_bytes": len(r1.content),
        "etag_present": bool(etag),
        "last_modified_present": bool(last_mod),
        "cache_control": cache_control,
    }
    polite_sleep(3.0, 5.0)
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_mod:
        headers["If-Modified-Since"] = last_mod
    if not headers:
        result["supported"] = False
        result["note"] = "server sent neither ETag nor Last-Modified"
        return result
    r2 = sess.get(url, timeout=(10, 30), headers=headers)
    result["second_status"] = r2.status_code
    result["second_bytes"] = len(r2.content)
    result["supported"] = r2.status_code == 304
    result["bytes_saved_pct"] = round(100 * (1 - len(r2.content) / max(1, len(r1.content))), 1)
    return result


def probe_u1_rate_limit(mgr: TransportManager, transport: str) -> dict:
    """U1 — is the ~1/min RSS limit per feed or per IP?

    Five *distinct* feeds fetched back to back from one address. All 200 means
    the budget is per feed. First 200 then 429s means it is per IP.
    """
    results = []
    for sub in SUBS:
        url = f"{HOSTS[0]}/r/{sub}/new/.rss?limit=10"
        r = _fetch(mgr, url, transport)
        s = parse_feed(r.body, url, r.status)
        results.append(
            {"subreddit": sub, "status": r.status, "entries": s.entries, "bytes": r.size}
        )
        time.sleep(1.0)  # deliberately fast: this probe is about the limit itself
    statuses = [x["status"] for x in results]
    ok = sum(1 for s in statuses if s == 200)
    limited = sum(1 for s in statuses if s == 429)
    if limited == 0:
        verdict = "per_feed_or_absent"
    elif ok == 1 and limited >= 1:
        verdict = "per_ip"
    else:
        verdict = "mixed"
    return {"sequence": results, "ok": ok, "rate_limited": limited, "U1_verdict": verdict}


def probe_freshness(mgr: TransportManager, transport: str) -> dict:
    """How stale is the newest entry? Bounds the polling interval."""
    from datetime import datetime

    url = f"{HOSTS[0]}/r/{SUBS[0]}/new/.rss?limit=25"
    r = _fetch(mgr, url, transport)
    if not r.ok:
        return {"status": r.status, "error": "fetch failed"}
    root = etree.fromstring(r.body)
    stamps = []
    for e in root.findall(f"{ATOM}entry"):
        u = e.find(f"{ATOM}updated")
        if u is not None and u.text:
            with contextlib.suppress(ValueError):
                stamps.append(datetime.fromisoformat(u.text.replace("Z", "+00:00")))
    if not stamps:
        return {"status": r.status, "error": "no timestamps"}
    now = datetime.now(UTC)
    newest, oldest = max(stamps), min(stamps)
    span_min = (newest - oldest).total_seconds() / 60
    return {
        "status": r.status,
        "entries": len(stamps),
        "newest_age_minutes": round((now - newest).total_seconds() / 60, 1),
        "window_span_minutes": round(span_min, 1),
        "observed_posts_per_hour": round(len(stamps) / max(span_min / 60, 0.01), 1),
    }


def main(transport: str = "direct", proxy_file: str | None = None) -> dict:
    from scripts.probe.transport import build_manager

    mgr = build_manager(proxy_file)
    print(f"RSS probes via transport={transport}")

    out: dict = {}
    steps = [
        ("U5_U2_limit_and_selftext", probe_u5_u2),
        ("multireddit", probe_multireddit),
        ("U3_search", probe_u3_search),
        ("U4_conditional_get", probe_u4_conditional),
        ("U6_host_parity", probe_u6_host_parity),
        ("U1_rate_limit", probe_u1_rate_limit),
        ("freshness", probe_freshness),
    ]
    for name, fn in steps:
        print(f"  -> {name}")
        try:
            out[name] = fn(mgr, transport)
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
            print(f"     FAILED: {exc}")
        polite_sleep(3.0, 6.0)
    return out


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else "direct"
    pf = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(main(t, pf), indent=2))
