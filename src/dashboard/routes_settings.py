"""``/settings/ai`` — provider configuration.

The invariant this module exists to hold: **no route returns the plaintext API
key**, ever, under any parameter. There is no reveal endpoint and no debug flag
that produces one. The UI shows a masked fingerprint, which is enough to confirm
*which* key is stored and useless to anyone who obtains it.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

from ..ai.errors import (
    AIDisabledError,
    InvalidAPIKeyError,
    ProviderUnreachableError,
)
from ..ai.providers import selectable_descriptors
from ..db.database import get_session
from ..db.repositories.ai import AICallRepository

log = logging.getLogger(__name__)

bp = Blueprint("settings", __name__)


def _service():
    from .app import get_ai_service

    return get_ai_service()


@bp.route("/settings")
def settings_index():
    return render_template("settings_ai.html", nav_active="settings_ai")


@bp.route("/settings/ai")
def settings_ai():
    return render_template("settings_ai.html", nav_active="settings_ai")


@bp.route("/api/settings/ai", methods=["GET"])
def get_ai_settings():
    service = _service()
    status = service.credentials.status()
    descriptor = None
    for candidate in selectable_descriptors():
        if candidate.name == service.provider_name:
            descriptor = candidate
            break

    return jsonify(
        {
            "provider": service.provider_name,
            "provider_info": descriptor.to_dict() if descriptor else None,
            "key": status.to_dict(),  # fingerprint only — never the key
            "enabled": service.enabled,
            "limits": {
                "max_cost_per_run_usd": service.limits.max_cost_per_run_usd,
                "max_cost_per_day_usd": service.limits.max_cost_per_day_usd,
                "max_calls_per_run": service.limits.max_calls_per_run,
            },
            "advanced": {
                "model": getattr(service.provider, "model", None),
                "concurrency": service.pool.current,
                "concurrency_floor": service.pool.floor,
                "concurrency_ceiling": service.pool.ceiling,
                "timeout_connect": float(service.settings.get("ai.timeout.connect", 10.0)),
                "timeout_read": float(service.settings.get("ai.timeout.read", 60.0)),
            },
            "prices": service.cost.prices.to_dict(),
        }
    )


@bp.route("/api/settings/ai/providers", methods=["GET"])
def list_providers():
    return jsonify({"providers": [d.to_dict() for d in selectable_descriptors()]})


@bp.route("/api/settings/ai/key", methods=["PUT"])
def set_ai_key():
    """Validate, then store. 422 with the specific reason on failure."""
    payload = request.get_json(silent=True) or {}
    api_key = (payload.get("api_key") or "").strip()
    validate = payload.get("validate", True)

    if not api_key:
        return jsonify({"error": "No API key supplied."}), 422

    service = _service()
    try:
        status = service.credentials.set_key(api_key, validate=bool(validate))
    except InvalidAPIKeyError as exc:
        # NOT stored. The specific reason matters: "rejected" sends the operator
        # to re-copy the key, where a generic failure sends them nowhere.
        return jsonify({"error": exc.message, "status": "invalid_key"}), 422
    except ProviderUnreachableError as exc:
        return jsonify({"error": exc.message, "status": "unreachable"}), 422
    except AIDisabledError as exc:
        return jsonify({"error": exc.message, "status": exc.outcome}), 422
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422

    service.refresh_provider()
    return jsonify({"ok": True, "key": status.to_dict()})


@bp.route("/api/settings/ai/key", methods=["DELETE"])
def clear_ai_key():
    service = _service()
    service.credentials.clear_key()
    service.refresh_provider()
    return jsonify({"ok": True, "key": service.credentials.status().to_dict()})


@bp.route("/api/settings/ai/test", methods=["POST"])
def test_ai_connection():
    service = _service()
    result = service.test_connection()
    return jsonify(result.model_dump())


@bp.route("/api/settings/ai/config", methods=["PUT"])
def update_ai_config():
    payload = request.get_json(silent=True) or {}
    service = _service()

    numeric = {
        "max_cost_per_run_usd": ("ai.limits.max_cost_per_run_usd", float),
        "max_cost_per_day_usd": ("ai.limits.max_cost_per_day_usd", float),
        "max_calls_per_run": ("ai.limits.max_calls_per_run", int),
        "concurrency": ("ai.concurrency", int),
        "timeout_connect": ("ai.timeout.connect", float),
        "timeout_read": ("ai.timeout.read", float),
    }

    updated = {}
    for field, (setting_key, caster) in numeric.items():
        if field in payload:
            try:
                value = caster(payload[field])
            except (TypeError, ValueError):
                return jsonify({"error": f"{field} must be a number"}), 422
            if value <= 0:
                return jsonify({"error": f"{field} must be greater than zero"}), 422
            service.settings.db_set(setting_key, str(value))
            updated[field] = value

    if "model" in payload and payload["model"]:
        service.settings.db_set("ai.model", str(payload["model"]))
        service.refresh_provider()
        updated["model"] = payload["model"]

    # Apply live so a lowered cap takes effect on the next call, not the next
    # restart. A cap that needs a restart is a cap nobody trusts.
    if "max_cost_per_run_usd" in updated:
        service.limits.max_cost_per_run_usd = updated["max_cost_per_run_usd"]
    if "max_cost_per_day_usd" in updated:
        service.limits.max_cost_per_day_usd = updated["max_cost_per_day_usd"]
    if "max_calls_per_run" in updated:
        service.limits.max_calls_per_run = updated["max_calls_per_run"]

    return jsonify({"ok": True, "updated": updated})


@bp.route("/api/ai/usage", methods=["GET"])
def ai_usage():
    period = request.args.get("period", "today")
    session = get_session()
    try:
        repo = AICallRepository(session)
        data = repo.usage_month() if period == "month" else repo.usage_today()
        data["period"] = period
        data["outcomes"] = repo.outcome_counts()
        return jsonify(data)
    finally:
        session.close()
