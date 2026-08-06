"""AI exception hierarchy.

The distinctions here are product decisions, not taxonomy for its own sake:

* **401 vs 402.** An invalid key and an empty account are both "the request
  failed", but they need opposite responses. 401 means the key is wrong —
  reject it and do not store it. 402 means the key is *correct* and the account
  needs credit — store it, show amber, and never retry.
* **Retryable vs not.** Retrying a 401 burns latency to earn the same 401.
  ``retryable`` is on the exception so the retry policy never has to guess.
"""

from __future__ import annotations


class AIError(Exception):
    """Base for everything this layer raises."""

    retryable: bool = False
    outcome: str = "error"

    def __init__(self, message: str, *, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.message} ({self.detail})" if self.detail else self.message


# --------------------------------------------------------------- configuration


class AIDisabledError(AIError):
    """AI is not usable: no APP_SECRET_KEY, no API key, or an unreadable one.

    Not a failure — a state. Scraping and the legacy dashboard are unaffected,
    and callers are expected to degrade rather than abort.
    """

    outcome = "disabled"


class ProviderNotConfiguredError(AIDisabledError):
    outcome = "unconfigured"


class CredentialDecryptionError(AIDisabledError):
    """Stored ciphertext will not decrypt — almost always a rotated APP_SECRET_KEY.

    Distinct from "no key configured" because the remedy differs: re-enter the
    key, rather than enter one for the first time.
    """

    outcome = "undecryptable"


# ------------------------------------------------------------------- provider


class ProviderError(AIError):
    """A provider call failed. Carries the HTTP status when there was one."""

    def __init__(self, message: str, *, status_code: int | None = None, detail: str | None = None):
        super().__init__(message, detail=detail)
        self.status_code = status_code


class InvalidAPIKeyError(ProviderError):
    """HTTP 401. Never retried. The key is NOT stored."""

    retryable = False
    outcome = "invalid_key"


class InsufficientBalanceError(ProviderError):
    """HTTP 402. Never retried. The key IS stored — it is valid.

    Amber, not red: nothing is broken, the account needs credit. Colouring it
    as an error sends the operator debugging the wrong thing.
    """

    retryable = False
    outcome = "insufficient_balance"


class RateLimitedError(ProviderError):
    """HTTP 429. Retryable, and halves concurrency."""

    retryable = True
    outcome = "rate_limited"

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ProviderServerError(ProviderError):
    """HTTP 5xx. Retryable with backoff."""

    retryable = True
    outcome = "server_error"


class ProviderUnreachableError(ProviderError):
    """Connection error, DNS failure, or timeout. Retryable."""

    retryable = True
    outcome = "unreachable"


class ProviderBadRequestError(ProviderError):
    """HTTP 400/422. Not retryable — the same request earns the same rejection."""

    retryable = False
    outcome = "bad_request"


# -------------------------------------------------------------------- content


class ResponseError(AIError):
    """The call succeeded but the body was unusable."""

    retryable = True

    def __init__(self, message: str, *, raw: str | None = None, attempts: int = 0, **kwargs):
        super().__init__(message, **kwargs)
        self.raw = raw
        self.attempts = attempts


class EmptyContentError(ResponseError):
    outcome = "empty_content"


class InvalidJSONError(ResponseError):
    outcome = "invalid_json"


class SchemaValidationError(ResponseError):
    """Valid JSON, wrong shape. DeepSeek's JSON mode guarantees syntax only."""

    outcome = "schema_error"

    def __init__(self, message: str, *, field_errors: list[str] | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.field_errors = field_errors or []


# --------------------------------------------------------------------- budget


class BudgetExceededError(AIError):
    """A cost or call ceiling would be breached. Raised BEFORE the call.

    Checking after would mean paying for the call that broke the cap, which
    makes the cap an observation rather than a limit.
    """

    retryable = False
    outcome = "budget_exceeded"

    def __init__(
        self, message: str, *, limit_name: str = "", limit: float = 0.0, spent: float = 0.0
    ):
        super().__init__(message)
        self.limit_name = limit_name
        self.limit = limit
        self.spent = spent


class GateRejectedError(AIError):
    """PreAIGate refused the work. Nothing reaches a provider without passing it."""

    outcome = "gate_rejected"

    def __init__(self, message: str, *, reason: str = ""):
        super().__init__(message)
        self.reason = reason


def classify_http_status(status: int, body: str = "") -> type[ProviderError]:
    """Map an HTTP status to its exception class (docs/02 §6.6)."""
    if status == 401:
        return InvalidAPIKeyError
    if status == 402:
        return InsufficientBalanceError
    if status == 429:
        return RateLimitedError
    if status in (400, 422):
        return ProviderBadRequestError
    if status >= 500:
        return ProviderServerError
    return ProviderError
