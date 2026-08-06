"""P0 Track C — environment and provider readiness.

Answers V-3 (does ``sqlite-vec`` load?), V-4 (does Model2Vec fit?), V-5
(baseline post volume) and reports which credentials exist, so that anything
blocked is blocked *visibly* rather than silently faked.

Nothing here installs a package or writes to the live database.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]
ATOM = "{http://www.w3.org/2005/Atom}"


def check_optional_packages() -> dict:
    """V-3 / V-4 — are the optional semantic-layer packages present?

    They are *not* installed here. AD-16 requires the whole tier to degrade
    cleanly when they are absent, so 'absent' is a valid, supported state and
    installing them to make a probe green would hide the case that matters.
    """
    out = {}
    for mod, purpose in (
        ("sqlite_vec", "vector storage (AD-16)"),
        ("model2vec", "static embeddings (AD-16)"),
        ("trafilatura", "text extraction (P13)"),
        ("openpyxl", "XLSX export (P27)"),
        ("pythonjsonlogger", "structured logging (P2)"),
    ):
        spec = importlib.util.find_spec(mod)
        out[mod] = {"installed": spec is not None, "purpose": purpose}
    return out


def check_sqlite() -> dict:
    """Can this SQLite build load an extension at all?

    If ``enable_load_extension`` is missing from the Python build, the semantic
    tier can never work here regardless of whether the package installs — which
    is a different failure from 'package not installed' and needs a different
    answer.
    """
    con = sqlite3.connect(":memory:")
    has_api = hasattr(con, "enable_load_extension")
    enabled = False
    err = None
    if has_api:
        try:
            con.enable_load_extension(True)
            enabled = True
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"[:120]
    ver = con.execute("select sqlite_version()").fetchone()[0]
    wal_ok = False
    try:
        con.execute("PRAGMA journal_mode=WAL")
        wal_ok = True
    except Exception:  # noqa: BLE001
        pass
    con.close()
    return {
        "sqlite_version": ver,
        "enable_load_extension_available": has_api,
        "enable_load_extension_works": enabled,
        "wal_supported": wal_ok,
        "error": err,
    }


def check_credentials() -> dict:
    """Which credentials exist? Names and presence only — never values."""
    env_file = ROOT / ".env"
    present: dict[str, bool] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            present[k.strip()] = bool(v.strip())
    needed = {
        "APP_SECRET_KEY": "AI credential encryption (shipped P1)",
        "DEEPSEEK_API_KEY": "V-1 provider comparison, Hermes (Track B)",
        "OPENROUTER_API_KEY": "V-1 provider comparison",
        "TELEGRAM_BOT_TOKEN": "Track B Telegram validation",
        "PROXY_FILE": "transport comparison (supplied by argument instead)",
    }
    return {
        "present_in_env": sorted(k for k, v in present.items() if v),
        "empty_in_env": sorted(k for k, v in present.items() if not v),
        "required_but_missing": sorted(k for k in needed if k not in present or not present.get(k)),
        "purpose": needed,
    }


def check_live_db() -> dict:
    """Read-only sanity on the legacy database. P0 must not modify it."""
    db = ROOT / "data" / "leads.db"
    if not db.exists():
        return {"exists": False}
    before = db.stat().st_mtime
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        leads = con.execute("select count(*) from leads").fetchone()[0]
        runs = con.execute("select count(*) from scrape_runs").fetchone()[0]
        stats = con.execute(
            "select min(intent_score), max(intent_score), avg(intent_score) from leads"
        ).fetchone()
        ver = con.execute("select version_num from alembic_version").fetchone()
        tables = [
            r[0]
            for r in con.execute("select name from sqlite_master where type='table' order by name")
        ]
    finally:
        con.close()
    return {
        "exists": True,
        "leads": leads,
        "scrape_runs": runs,
        "intent_score_min": stats[0],
        "intent_score_max": stats[1],
        "intent_score_avg": round(stats[2], 2) if stats[2] else None,
        "alembic_version": ver[0] if ver else None,
        "table_count": len(tables),
        "mtime_unchanged": db.stat().st_mtime == before,
    }


def measure_post_volume() -> dict:
    """V-5 — how many posts do the configured subreddits actually produce?

    One multireddit RSS request. The rate limit is 1/minute per address
    (measured), so this is deliberately a single call.
    """
    from lxml import etree

    from scripts.probe.transport import build_manager

    subs = ["SaaS", "startups", "Entrepreneur", "marketing"]
    url = f"https://www.reddit.com/r/{'+'.join(subs)}/new/.rss?limit=100"
    mgr = build_manager()
    r = mgr.get(url, transport="direct", session_key="volume")
    if not r.ok:
        return {"status": r.status, "error": "rate limited or blocked; retry after 60s"}

    root = etree.fromstring(r.body)
    stamps = []
    per_sub: dict[str, int] = {}
    import re

    for e in root.findall(f"{ATOM}entry"):
        u = e.find(f"{ATOM}updated")
        if u is not None and u.text:
            with contextlib.suppress(ValueError):
                stamps.append(datetime.fromisoformat(u.text.replace("Z", "+00:00")))
        link = e.find(f"{ATOM}link")
        href = link.get("href", "") if link is not None else ""
        m = re.search(r"/r/([A-Za-z0-9_]+)/", href)
        if m:
            s = m.group(1)
            per_sub[s] = per_sub.get(s, 0) + 1
    if not stamps:
        return {"status": r.status, "error": "no timestamps"}
    span_h = max((max(stamps) - min(stamps)).total_seconds() / 3600, 0.01)
    rate = len(stamps) / span_h
    return {
        "status": r.status,
        "subreddits": subs,
        "entries": len(stamps),
        "window_hours": round(span_h, 2),
        "posts_per_hour": round(rate, 1),
        "projected_posts_per_day": round(rate * 24),
        "per_subreddit_in_window": dict(sorted(per_sub.items(), key=lambda kv: -kv[1])),
        "newest_age_minutes": round((datetime.now(UTC) - max(stamps)).total_seconds() / 60, 1),
        "hours_to_fill_100_slot_window": round(100 / rate, 2),
    }


def main() -> dict:
    return {
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "optional_packages": check_optional_packages(),
        "sqlite": check_sqlite(),
        "credentials": check_credentials(),
        "live_database": check_live_db(),
        "post_volume": measure_post_volume(),
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
