from __future__ import annotations

import logging

from flask import Flask

from src.db.database import init_db

log = logging.getLogger(__name__)

_ai_service = None
_proxy_manager = None
# One-element lists so the helpers below can write them without another
# `global` declaration in each.
_proxy_manager_failed = [False]
_proxy_manager_error: list[str | None] = [None]


def get_ai_service():
    """Process-wide ``AIService``.

    Constructed lazily and never at import time: building it touches the
    database and reads settings, and an import-time failure would take down the
    legacy dashboard along with the AI layer it has nothing to do with.
    """
    global _ai_service
    if _ai_service is None:
        from src.ai.service import AIService
        from src.config import load_config
        from src.settings import get_settings

        try:
            yaml_config = load_config()
        except Exception:
            yaml_config = {}
        _ai_service = AIService(get_settings(yaml_config))
    return _ai_service


def reset_ai_service() -> None:
    """Test hook."""
    global _ai_service
    _ai_service = None


def get_proxy_manager():
    """Process-wide :class:`ProxyManager`, or ``None`` when proxying is off.

    Same lazy construction as the AI service, for the same reason: reading the
    proxy file at import time would make a missing or unreadable file break the
    dashboard, when the correct outcome is a health page that says the pool is
    unavailable and why.

    Returning ``None`` -- rather than an empty pool -- keeps "proxying is
    disabled" distinguishable from "proxying is enabled and every proxy is
    down". They need different words on the page and different operator action.
    """
    global _proxy_manager
    if _proxy_manager is None and not _proxy_manager_failed[0]:
        from src.net.proxy_manager import build_from_settings
        from src.settings import get_settings

        try:
            from src.config import load_config

            yaml_config = load_config()
        except Exception:
            yaml_config = {}
        try:
            _proxy_manager = build_from_settings(get_settings(yaml_config))
        except Exception as exc:
            # Cached so a broken proxy file is not re-read on every request.
            _proxy_manager_failed[0] = True
            _proxy_manager_error[0] = str(exc)
            log.warning("proxy pool unavailable: %s", exc)
            return None
    return _proxy_manager


def proxy_manager_error() -> str | None:
    """Why :func:`get_proxy_manager` returned ``None``, if it did."""
    return _proxy_manager_error[0]


def reset_proxy_manager() -> None:
    """Test hook."""
    global _proxy_manager
    _proxy_manager = None
    _proxy_manager_failed[0] = False
    _proxy_manager_error[0] = None


def create_app(*, run_migrations: bool = True):
    app = Flask(__name__)
    init_db(run_migrations=run_migrations)

    from src.settings import get_settings

    settings = get_settings()
    app.secret_key = (
        settings.get_secret("FLASK_SECRET_KEY") or settings.get_secret("APP_SECRET_KEY") or "dev-only"
    )

    from .nav import nav_context

    # One navigation, injected everywhere. A nav built per-template drifts the
    # moment a page is added, and the forgotten page is always the newest one.
    app.context_processor(nav_context)

    from .routes import bp

    app.register_blueprint(bp)

    # New surfaces go in new blueprints; routes.py is not rewritten, which is
    # what keeps all 17 legacy endpoints byte-identical.
    from .routes_health import bp as health_bp
    from .routes_pages import bp as pages_bp
    from .routes_settings import bp as settings_bp

    app.register_blueprint(settings_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(pages_bp)

    return app
