"""``/health`` and ``/health/ai``.

The AI page is split efficiency / quality / throughput on purpose. Efficiency
metrics without quality metrics beside them would let an operator tune the
system down until it quietly stopped working.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template

from ..db.database import get_session
from ..db.migrate import MigrationRunner
from ..db.models import Lead
from ..db.repositories.ai import AICacheRepository, AICallRepository

log = logging.getLogger(__name__)

bp = Blueprint("health", __name__)


def _service():
    from .app import get_ai_service

    return get_ai_service()


def _pool():
    from .app import get_proxy_manager

    return get_proxy_manager()


def _pool_payload() -> dict:
    """Pool state as JSON.

    Every field here comes from :meth:`ProxyManager.snapshot`, which emits
    ``host:port`` labels only. No username or password reaches this payload, the
    template that renders it, or the database behind it.
    """
    from .app import proxy_manager_error

    pool = _pool()
    if pool is None:
        return {
            "enabled": False,
            "error": proxy_manager_error(),
            "total": 0,
            "healthy": 0,
            "degraded": 0,
            "blacklisted": 0,
            "untested": 0,
            "circuit_open": False,
            "fail_closed": None,
            "proxies": [],
        }

    snap = pool.snapshot()
    return {
        "enabled": True,
        "error": None,
        "total": snap.total,
        "healthy": snap.healthy,
        "degraded": snap.degraded,
        "blacklisted": snap.blacklisted,
        "untested": snap.untested,
        # Open means no proxy is currently usable. With fail_closed the next
        # fetch stops rather than falling back to the local IP, so this is the
        # single field that says whether scraping can run at all.
        "circuit_open": snap.circuit_open,
        "fail_closed": pool.fail_closed,
        "proxies": snap.proxies,
    }


@bp.route("/health")
def health_page():
    return render_template("health_ai.html", nav_active="health_ai")


@bp.route("/health/ai")
def health_ai_page():
    return render_template("health_ai.html", nav_active="health_ai")


@bp.route("/health/proxies")
def health_proxies_page():
    return render_template("health_proxies.html", nav_active="health_proxies")


@bp.route("/api/health/proxies", methods=["GET"])
def health_proxies():
    """Pool state plus transport counters. Read-only -- no network calls.

    The live check is a separate POST so that loading this page cannot
    accidentally fire ten outbound requests.
    """
    return jsonify(_pool_payload())


@bp.route("/api/health/proxies/check", methods=["POST"])
def health_proxies_check():
    """Test every proxy against the IP echo service, in parallel.

    POST, not GET: it spends real requests through real proxies and mutates
    recorded state, so it must not be reachable by a link, a prefetch or a
    browser retry.
    """
    pool = _pool()
    if pool is None:
        from .app import proxy_manager_error

        return jsonify({"ok": False, "error": proxy_manager_error() or "proxying disabled"}), 503

    try:
        results = pool.health_check_all()
    except Exception as exc:
        log.warning("proxy health check failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    payload = _pool_payload()
    payload["ok"] = True
    payload["checked"] = results["checked"]
    payload["reachable"] = results["reachable"]
    # If any exit IP equals this machine's address, the proxy is not proxying
    # and the real address is reaching the target. That is the one failure the
    # pool exists to prevent, so it is reported explicitly rather than left to
    # be inferred from a table of IPs.
    payload["leaking"] = results["leaking"]
    # Whether the comparison could be made at all. If the local address could
    # not be determined, `leaking` is empty because nothing was compared -- not
    # because nothing leaked. Reporting "no leak" there would be a false
    # negative on the one check that matters most.
    payload["local_ip_known"] = results["local_ip_known"]
    return jsonify(payload)


@bp.route("/api/health", methods=["GET"])
def health():
    from ..db.database import DB_PATH

    session = get_session()
    try:
        lead_count = session.query(Lead).count()
    except Exception as exc:
        lead_count = -1
        log.warning("health: lead count failed: %s", exc)
    finally:
        session.close()

    try:
        status = MigrationRunner(DB_PATH).status()
        schema = {
            "current": status.current,
            "head": status.head,
            "up_to_date": status.is_current,
        }
    except Exception as exc:
        schema = {"error": str(exc)}

    service = _service()
    key_status = service.credentials.status()

    pool = _pool_payload()

    return jsonify(
        {
            "status": "ok",
            "database": {"leads": lead_count, "path": str(DB_PATH)},
            "schema": schema,
            # Summary only. The full per-proxy table lives at
            # /api/health/proxies; this is what a monitor would alert on.
            "proxies": {
                "enabled": pool["enabled"],
                "healthy": pool["healthy"],
                "total": pool["total"],
                "circuit_open": pool["circuit_open"],
            },
            "ai": {
                "enabled": service.enabled,
                "provider": service.provider_name,
                "status": key_status.status,
                "model": key_status.model_id,
                "last_validated_at": (
                    key_status.last_validated_at.isoformat()
                    if key_status.last_validated_at
                    else None
                ),
            },
        }
    )


@bp.route("/api/health/ai", methods=["GET"])
def health_ai():
    service = _service()
    session = get_session()
    try:
        calls = AICallRepository(session)
        cache = AICacheRepository(session)
        today = calls.usage_today()
        month = calls.usage_month()
        outcomes = calls.outcome_counts()
        distinct_prefixes = calls.distinct_prefixes(days=1)
        cache_stats = cache.stats()
    finally:
        session.close()

    key_status = service.credentials.status()
    health_metrics = service.metrics.health()

    # Persisted history is more honest than in-process counters, which reset on
    # restart and would make a cache regression look like it had healed.
    total_input = today["input_tokens_cached"] + today["input_tokens_uncached"]
    persisted_cache_ratio = (
        today["input_tokens_cached"] / total_input if total_input else None
    )
    if persisted_cache_ratio is not None:
        health_metrics["prefix_cache_ratio"]["value"] = round(persisted_cache_ratio, 4)
        health_metrics["prefix_cache_ratio"]["ok"] = (
            persisted_cache_ratio >= 0.85 or today["calls"] < 2
        )
    health_metrics["prefix_stable"]["value"] = max(distinct_prefixes, 1)
    health_metrics["prefix_stable"]["ok"] = distinct_prefixes <= 1

    return jsonify(
        {
            "provider": {
                "name": service.provider_name,
                "model": key_status.model_id or getattr(service.provider, "model", None),
                "status": key_status.status,
                "enabled": service.enabled,
                "last_validated_at": (
                    key_status.last_validated_at.isoformat()
                    if key_status.last_validated_at
                    else None
                ),
                "last_error": key_status.last_error,
            },
            "cost": {
                "today_usd": today["cost_usd"],
                "month_usd": month["cost_usd"],
                "limits": {
                    "per_run": service.limits.max_cost_per_run_usd,
                    "per_day": service.limits.max_cost_per_day_usd,
                    "calls_per_run": service.limits.max_calls_per_run,
                },
                "prices": service.cost.prices.to_dict(),
            },
            "efficiency": {
                "prefix_cache_ratio": health_metrics["prefix_cache_ratio"],
                "response_cache_entries": cache_stats["entries"],
                "response_cache_hits": cache_stats["hits"],
                "calls_today": today["calls"],
            },
            "quality": {
                "repair_rate": health_metrics["repair_rate"],
                "empty_rate": health_metrics["empty_rate"],
                "prefix_stable": health_metrics["prefix_stable"],
                "outcomes": outcomes,
            },
            "throughput": {
                "mean_latency_ms": today["mean_latency_ms"],
                "p95_latency_ms": service.metrics.p95_latency_ms,
                "concurrency": service.pool.current,
                "concurrency_ceiling": service.pool.ceiling,
            },
            "session_metrics": service.metrics.to_dict(),
            # Per-provider circuit state, latency and failure rate. Surfaced
            # here rather than only in logs, so a degraded provider is visible
            # before it becomes a stalled run.
            "routing": service.router.status(),
        }
    )


@bp.route("/api/health/providers", methods=["GET"])
def health_providers():
    """Per-provider health plus a like-for-like cost comparison.

    The comparison is estimated from published price tables, not measured. Its
    job is to make a provider switch a decision with a number attached; each row
    carries the date its prices were verified so an unconfirmed figure is
    visibly unconfirmed.
    """
    service = _service()
    return jsonify(
        {
            "routing": service.router.status(),
            "comparison": service.provider_comparison(),
        }
    )
