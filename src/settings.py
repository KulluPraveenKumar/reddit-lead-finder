"""Typed settings resolution: env var -> DB settings row -> config.yaml -> default.

Three similarly-named things coexist in this project. Keeping them straight:

* ``src/config.py``   — loads and validates ``config.yaml``. Unchanged behaviour.
* ``src/settings.py`` — *this* module. The single resolver every consumer uses.
* the ``settings`` table — a key/value store; one of the four sources below,
  and the place the encrypted API key lives.

Nothing outside this module reads ``os.environ`` for configuration.

Precedence is deliberate: an environment variable always wins, so an operator
can override a bad stored value without database surgery.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_MISSING = object()
_dotenv_loaded = False


def load_env() -> None:
    """Load ``.env`` once. Real environment variables always win."""
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        _dotenv_loaded = True


def _env_name(key: str) -> str:
    """``ai.concurrency`` -> ``AI_CONCURRENCY``."""
    return key.replace(".", "_").replace("-", "_").upper()


def _from_yaml(key: str, yaml_config: dict | None) -> Any:
    if not yaml_config:
        return _MISSING
    node: Any = yaml_config
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _coerce(raw: str, default: Any) -> Any:
    """Environment variables are strings; make them match the default's type."""
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(raw)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    if isinstance(default, list | dict):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default
    return raw


class SettingsResolver:
    """Resolves a dotted key across the four sources, in precedence order."""

    def __init__(self, yaml_config: dict | None = None, session_factory=None):
        load_env()
        self.yaml_config = yaml_config or {}
        self._session_factory = session_factory

    # -------------------------------------------------------------- DB access

    def _db_get(self, key: str) -> Any:
        """Read a ``settings`` row. Never raises: config must not break on a
        database that is missing, locked, or not yet migrated."""
        try:
            if self._session_factory is not None:
                session = self._session_factory()
            else:
                from src.db.database import get_session

                session = get_session()
        except Exception:
            return _MISSING

        try:
            from src.db.models import Settings as SettingsRow

            row = session.query(SettingsRow).filter_by(key=key).one_or_none()
            return row.value if row is not None else _MISSING
        except Exception:
            return _MISSING
        finally:
            with contextlib.suppress(Exception):
                session.close()

    def db_set(self, key: str, value: str) -> None:
        from src.db.database import session_scope
        from src.db.models import Settings as SettingsRow

        with session_scope() as session:
            row = session.query(SettingsRow).filter_by(key=key).one_or_none()
            if row is None:
                session.add(SettingsRow(key=key, value=value))
            else:
                row.value = value

    def db_delete(self, key: str) -> None:
        from src.db.database import session_scope
        from src.db.models import Settings as SettingsRow

        with session_scope() as session:
            session.query(SettingsRow).filter_by(key=key).delete()

    # ---------------------------------------------------------------- resolve

    def get(self, key: str, default: Any = None, *, use_db: bool = True) -> Any:
        raw_env = os.environ.get(_env_name(key))
        if raw_env is not None:
            return _coerce(raw_env, default)

        if use_db:
            db_value = self._db_get(key)
            if db_value is not _MISSING:
                return _coerce(db_value, default) if isinstance(db_value, str) else db_value

        yaml_value = _from_yaml(key, self.yaml_config)
        if yaml_value is not _MISSING:
            return yaml_value

        return default

    def get_secret(self, name: str) -> str | None:
        """Process-environment only. Secrets never come from the database or YAML.

        ``APP_SECRET_KEY`` is the key that decrypts stored credentials, so
        reading it from the database it protects would be circular.
        """
        load_env()
        value = os.environ.get(name)
        return value.strip() if value else None

    # ----------------------------------------------------------- convenience

    @property
    def app_secret_key(self) -> str | None:
        return self.get_secret("APP_SECRET_KEY")

    def require_app_secret_key(self) -> str:
        secret = self.app_secret_key
        if not secret:
            from src.ai.errors import AIDisabledError

            raise AIDisabledError(
                "APP_SECRET_KEY is not set. AI features are disabled. "
                "Copy .env.example to .env and generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return secret


_resolver: SettingsResolver | None = None


def get_settings(yaml_config: dict | None = None) -> SettingsResolver:
    """Process-wide resolver. Pass ``yaml_config`` on first call to seed it."""
    global _resolver
    if _resolver is None or yaml_config is not None:
        _resolver = SettingsResolver(yaml_config)
    return _resolver


def reset_settings() -> None:
    """Test hook: drop the cached resolver."""
    global _resolver
    _resolver = None
