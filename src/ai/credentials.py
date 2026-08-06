"""API key storage: encrypted at rest, validated before storing, never returned.

The threat model, stated honestly because the UI states it too: on a
single-tenant self-hosted install the data key is derived from ``APP_SECRET_KEY``
in ``.env``, which lives on the same machine as the database. **This protects a
copied database file or a backup, not an attacker with server access.** Claiming
more would be dishonest, and the point of encrypting it is that database files
get copied, emailed, and dropped into cloud storage far more often than servers
get breached.

Why not a config file at all: a key in ``config.yaml`` gets committed, pasted
into a support ticket, and shared whenever the file is shared. Runtime entry
means the repository never contains a credential.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..db.models import AIStatus
from .errors import (
    AIDisabledError,
    CredentialDecryptionError,
    ProviderNotConfiguredError,
)

log = logging.getLogger(__name__)

#: Settings-table key holding the ciphertext. Never the plaintext.
KEY_SETTING = "ai.provider.{provider}.api_key_enc"

_HKDF_SALT = b"reddit-lead-finder/ai-key/v1"


@dataclass(frozen=True)
class KeyStatus:
    """What the UI is allowed to know about the stored key. Never the key."""

    configured: bool
    status: str
    fingerprint: str | None = None
    model_id: str | None = None
    context_window: int | None = None
    last_validated_at: datetime | None = None
    last_validation_ms: int | None = None
    last_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "configured": self.configured,
            "status": self.status,
            "fingerprint": self.fingerprint,
            "model_id": self.model_id,
            "context_window": self.context_window,
            "last_validated_at": (
                self.last_validated_at.isoformat() if self.last_validated_at else None
            ),
            "last_validation_ms": self.last_validation_ms,
            "last_error": self.last_error,
        }


def fingerprint(api_key: str) -> str:
    """Display-only identifier: ``sk-...a3f9``.

    Enough for an operator to confirm *which* key is stored; useless to anyone
    who obtains it.
    """
    if not api_key:
        return ""
    prefix = api_key[:3] if api_key.startswith("sk-") else api_key[:2]
    return f"{prefix}...{api_key[-4:]}" if len(api_key) > 8 else "..." + api_key[-2:]


def key_digest(api_key: str) -> str:
    """SHA-256 of the key, for change detection only. Not reversible."""
    return hashlib.sha256(api_key.encode()).hexdigest()


class CredentialStore:
    def __init__(self, settings, provider: str | None = None):
        from .providers.registry import DEFAULT_PROVIDER

        self.settings = settings
        # The default comes from the registry, never a literal here: a vendor
        # name in this module would be exactly the coupling the boundary exists
        # to prevent.
        self.provider = provider or DEFAULT_PROVIDER

    # -------------------------------------------------------------- crypto

    def _data_key(self) -> bytes:
        secret = self.settings.app_secret_key
        if not secret:
            raise AIDisabledError(
                "APP_SECRET_KEY is not set. AI features are disabled. "
                "Copy .env.example to .env and generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_HKDF_SALT,
            info=self.provider.encode(),
        ).derive(secret.encode())
        return base64.urlsafe_b64encode(derived)

    def _setting_key(self) -> str:
        return KEY_SETTING.format(provider=self.provider)

    def encrypt(self, api_key: str) -> str:
        return Fernet(self._data_key()).encrypt(api_key.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return Fernet(self._data_key()).decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            # Almost always a rotated APP_SECRET_KEY. Distinct from "no key" so
            # the UI can say "re-enter your key" rather than "enter a key".
            raise CredentialDecryptionError(
                "The stored API key could not be decrypted. This usually means "
                "APP_SECRET_KEY changed. Re-enter your API key on the Settings page."
            ) from exc

    # ---------------------------------------------------------------- access

    def get_key(self, *, allow_env_fallback: bool = True) -> str | None:
        """Return the plaintext key, or None.

        Only ``AIService`` and the validation path call this. It is never
        exposed through an API, a template, or a log line.
        """
        ciphertext = self.settings.get(self._setting_key(), None)
        if ciphertext:
            return self.decrypt(ciphertext)

        if allow_env_fallback:
            # Local-development convenience, documented in .env.example. The
            # Settings page remains the intended path.
            env_key = self.settings.get_secret(f"{self.provider.upper()}_API_KEY")
            if env_key:
                return env_key

        return None

    def has_key(self) -> bool:
        try:
            return self.get_key() is not None
        except AIDisabledError:
            return False

    def require_key(self) -> str:
        key = self.get_key()
        if not key:
            raise ProviderNotConfiguredError(
                f"No {self.provider} API key configured. "
                "Add one on the Settings page to enable AI features."
            )
        return key

    # ----------------------------------------------------------------- write

    def set_key(self, api_key: str, *, validate: bool = True, provider_obj=None) -> KeyStatus:
        """Validate, then store. The order matters.

        Storing first and validating afterwards would leave a broken key in
        place on failure, and the operator would have to remember to remove it.

        A **402 stores the key**: the credential is correct and the account
        merely needs credit. Forcing re-entry after a top-up would be wrong.
        """
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("API key is empty")

        # Cheap client-side sanity check. Catches a truncated paste before
        # spending a network round trip on it.
        if len(api_key) < 16:
            raise ValueError("That does not look like a complete API key.")

        status = AIStatus.VALID
        model_id: str | None = None
        context_window: int | None = None
        latency_ms: int | None = None
        error: str | None = None

        if validate:
            if provider_obj is None:
                from .providers import build_provider

                provider_obj = build_provider(self.provider, api_key)
            else:
                provider_obj.api_key = api_key

            result = provider_obj.validate_credentials()
            status = result.status
            model_id = result.model
            context_window = result.context_window
            latency_ms = result.latency_ms
            error = result.error

            if status == AIStatus.INVALID_KEY:
                # Do NOT store. Record the failure so the UI can explain it.
                self._write_state(
                    status=status,
                    fingerprint=None,
                    digest=None,
                    model_id=None,
                    context_window=None,
                    latency_ms=latency_ms,
                    error=error,
                )
                raise self._invalid_key_error(error)

            if status == AIStatus.UNREACHABLE:
                self._write_state(
                    status=status,
                    fingerprint=None,
                    digest=None,
                    model_id=None,
                    context_window=None,
                    latency_ms=latency_ms,
                    error=error,
                )
                raise self._unreachable_error(error)

        self.settings.db_set(self._setting_key(), self.encrypt(api_key))
        self._write_state(
            status=status,
            fingerprint=fingerprint(api_key),
            digest=key_digest(api_key),
            model_id=model_id,
            context_window=context_window,
            latency_ms=latency_ms,
            error=error,
            validated=validate and status in (AIStatus.VALID, AIStatus.INSUFFICIENT_BALANCE),
        )
        log.info("api key stored for provider=%s status=%s", self.provider, status)
        return self.status()

    def clear_key(self) -> None:
        self.settings.db_delete(self._setting_key())
        self._write_state(
            status=AIStatus.UNCONFIGURED,
            fingerprint=None,
            digest=None,
            model_id=None,
            context_window=None,
            latency_ms=None,
            error=None,
        )
        log.info("api key cleared for provider=%s", self.provider)

    def mark_invalid(self, error: str | None = None) -> None:
        """Called when a 401 arrives mid-run: the key worked and now does not."""
        self._write_state(
            status=AIStatus.INVALID_KEY,
            fingerprint=None,
            digest=None,
            model_id=None,
            context_window=None,
            latency_ms=None,
            error=error or "The provider rejected this key.",
            preserve_identity=True,
        )

    def mark_insufficient_balance(self, error: str | None = None) -> None:
        self._write_state(
            status=AIStatus.INSUFFICIENT_BALANCE,
            fingerprint=None,
            digest=None,
            model_id=None,
            context_window=None,
            latency_ms=None,
            error=error or "Provider balance exhausted.",
            preserve_identity=True,
        )

    # ----------------------------------------------------------------- state

    def _write_state(
        self,
        *,
        status: str,
        fingerprint: str | None,
        digest: str | None,
        model_id: str | None,
        context_window: int | None,
        latency_ms: int | None,
        error: str | None,
        validated: bool = False,
        preserve_identity: bool = False,
    ) -> None:
        from ..db.database import session_scope
        from ..db.models import AIProviderState

        now = datetime.now(UTC).replace(tzinfo=None)
        with session_scope() as session:
            row = session.query(AIProviderState).filter_by(provider=self.provider).one_or_none()
            if row is None:
                row = AIProviderState(provider=self.provider)
                session.add(row)

            row.status = status
            row.last_error = error
            row.updated_at = now

            if not preserve_identity:
                row.key_fingerprint = fingerprint
                row.key_sha256 = digest
                if model_id is not None:
                    row.model_id = model_id
                if context_window is not None:
                    row.context_window = context_window

            if latency_ms is not None:
                row.last_validation_ms = latency_ms
            if validated:
                row.last_validated_at = now

    def status(self) -> KeyStatus:
        from ..db.database import session_scope
        from ..db.models import AIProviderState

        # A missing APP_SECRET_KEY is a distinct state from a missing key: the
        # remedy is a .env edit, not a Settings-page paste.
        if not self.settings.app_secret_key:
            return KeyStatus(
                configured=False,
                status=AIStatus.UNCONFIGURED,
                last_error=(
                    "APP_SECRET_KEY is not set, so the API key cannot be stored securely. "
                    "AI features are disabled; scraping is unaffected."
                ),
            )

        with session_scope() as session:
            row = session.query(AIProviderState).filter_by(provider=self.provider).one_or_none()
            if row is None:
                return KeyStatus(configured=False, status=AIStatus.UNCONFIGURED)

            configured = bool(self.settings.get(self._setting_key(), None))
            status = row.status

            if configured:
                # Ciphertext present but unreadable -> UNDECRYPTABLE, which
                # tells the operator to re-enter rather than to enter.
                try:
                    self.get_key(allow_env_fallback=False)
                except CredentialDecryptionError as exc:
                    return KeyStatus(
                        configured=True,
                        status=AIStatus.UNDECRYPTABLE,
                        fingerprint=row.key_fingerprint,
                        last_error=exc.message,
                    )
            elif status == AIStatus.VALID:
                # State says valid but no ciphertext exists — stale row.
                status = AIStatus.UNCONFIGURED

            return KeyStatus(
                configured=configured,
                status=status,
                fingerprint=row.key_fingerprint,
                model_id=row.model_id,
                context_window=row.context_window,
                last_validated_at=row.last_validated_at,
                last_validation_ms=row.last_validation_ms,
                last_error=row.last_error,
            )

    # ---------------------------------------------------------------- errors

    def _invalid_key_error(self, detail: str | None):
        from .errors import InvalidAPIKeyError

        return InvalidAPIKeyError(
            detail or "The provider rejected this key. Check it was copied completely.",
            status_code=401,
        )

    def _unreachable_error(self, detail: str | None):
        from .errors import ProviderUnreachableError

        return ProviderUnreachableError(
            detail or "Could not reach the provider. Check your network connection.",
        )
