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


def _policy():
    from .app import get_network_policy

    return get_network_policy()


def _egress_payload() -> dict:
    """The egress policy: which providers exist, in what order, and what happens
    when they run out.

    Additive to the pre-P4 payload -- every key that existed still does, with the
    same meaning -- because this endpoint is read by a page, a test and an
    operator, and removing a field breaks all three for no gain.
    """
    from src.net.egress import policy_error

    try:
        policy = _policy()
    except Exception as exc:  # noqa: BLE001 - /health must not 500
        log.warning("health: egress policy unavailable: %s", exc)
        return {"error": str(exc)}

    described = policy.describe()
    direct = policy.direct_provider
    return {
        "error": policy_error(),
        "policy": described["policy"],
        "ladder": described["ladder"],
        "on_pool_exhausted": described["on_pool_exhausted"],
        "direct_classes": described["direct_classes"],
        "routing": described["routing"],
        "providers": described["providers"],
        "direct_requests_this_hour": direct.requests_this_hour if direct else None,
        "direct_max_requests_per_hour": direct.max_requests_per_hour if direct else None,
        # Degradations recorded but not yet drained by a job handler. Peeked,
        # never drained: this is a read-only view, and consuming them here would
        # steal the timeline entry the run page is waiting for.
        "degradations": [notice.as_data() for notice in policy.peek_notices()],
    }


def _pool_payload() -> dict:
    """Pool state as JSON.

    Every field here comes from :meth:`ProxyManager.snapshot`, which emits
    ``host:port`` labels only. No username or password reaches this payload, the
    template that renders it, or the database behind it. The same holds for the
    provider rows: a provider's ``describe()`` returns names, flags and counts.
    """
    from .app import proxy_manager_error

    egress = _egress_payload()
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
            "fail_closed": _fail_closed(egress),
            "acceptance_rate": None,
            "proxies": [],
            **egress,
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
        # Open means no proxy is currently usable, or the target is refusing the
        # whole pool. Either way the next fetch degrades or stops per the policy,
        # so this is the single field that says whether proxied scraping can run.
        "circuit_open": snap.circuit_open,
        "fail_closed": _fail_closed(egress),
        "acceptance_rate": snap.acceptance_rate,
        "proxies": snap.proxies,
        **egress,
    }


def _fail_closed(egress: dict) -> bool | None:
    """The pre-P4 field, derived from the setting that replaced it.

    ``fail_closed`` was always the two-value form of one question: when the pool
    is empty, stop or continue? ``on_pool_exhausted`` answers it with three
    values. Keeping the boolean as a derivation means nothing that read it
    breaks, and there is still exactly one source of truth.
    """
    action = egress.get("on_pool_exhausted")
    return None if action is None else action == "fail_run"


def _queue_payload() -> dict:
    """Queue depth, plus whether *this* process is executing jobs.

    ``docs/13`` §14 asks ``/health`` for "worker liveness and queue depth". Depth
    is a query. **Liveness is not, and P3 cannot make it one**: proving a worker
    in another process is alive needs a heartbeat row, and P3 owns no migration
    to add the table for it. Reporting a guess would be worse than reporting the
    gap, so this says exactly what it knows — the depth, the age of the oldest
    queued job, and whether this process holds a worker.

    ``oldest_queued_at`` is the field that actually detects a dead worker: a
    queue with jobs whose oldest has been waiting an hour is a stalled queue, no
    matter what any liveness flag claims.
    """
    from .app import get_worker

    session = get_session()
    try:
        from ..db.repositories.runs import JobRepository

        depth = JobRepository(session).queue_depth()
    except Exception as exc:  # noqa: BLE001 - /health must not 500
        log.warning("health: queue depth failed: %s", exc)
        depth = {"error": str(exc)}
    finally:
        session.close()

    oldest = depth.pop("oldest_queued_at", None) if isinstance(depth, dict) else None
    worker = get_worker()
    return {
        **depth,
        "oldest_queued_at": oldest.isoformat() if oldest else None,
        "inprocess_worker": worker is not None and not worker.stopping,
        "worker_id": worker.worker_id if worker is not None else None,
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
            "queue": _queue_payload(),
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
    persisted_cache_ratio = today["input_tokens_cached"] / total_input if total_input else None
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
