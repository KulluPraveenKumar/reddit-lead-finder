"""Error classification and backoff for network calls.

Separate from the AI layer's retry policy on purpose. The two look similar and
are not: the AI policy retries *the same provider* because a 5xx there is
transient, while this one's answer to most failures is **a different proxy**.
Sharing an implementation would force one of them to compromise.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum


class NetErrorClass(StrEnum):
    #: Retry on a different proxy.
    ROTATE = "rotate"
    #: Retry on the same proxy after waiting (the server told us to).
    BACKOFF = "backoff"
    #: The request itself is wrong; another proxy earns the same answer.
    FATAL = "fatal"
    NONE = "none"


class ProxyExhaustedError(RuntimeError):
    """Every proxy has been tried or blacklisted."""


class BlockedError(RuntimeError):
    """The target refused us, hard or soft."""

    def __init__(self, message: str, *, kind: str = "hard", status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


def classify(status_code: int | None, exception: BaseException | None = None) -> NetErrorClass:
    if exception is not None:
        import requests

        if isinstance(exception, requests.exceptions.Timeout):
            return NetErrorClass.ROTATE
        if isinstance(exception, requests.exceptions.ProxyError | requests.exceptions.SSLError):
            return NetErrorClass.ROTATE
        if isinstance(exception, requests.exceptions.ConnectionError | OSError):
            return NetErrorClass.ROTATE
        return NetErrorClass.ROTATE

    if status_code is None:
        return NetErrorClass.ROTATE
    if status_code == 200:
        return NetErrorClass.NONE
    if status_code == 429:
        # Honour Retry-After on the same proxy: rotating immediately would
        # spend a second IP's budget on a limit we were already told about.
        return NetErrorClass.BACKOFF
    if status_code in (403, 401):
        return NetErrorClass.ROTATE
    if status_code == 404:
        return NetErrorClass.FATAL
    if status_code >= 500:
        return NetErrorClass.ROTATE
    if 400 <= status_code < 500:
        return NetErrorClass.FATAL
    return NetErrorClass.ROTATE


@dataclass
class RetryPolicy:
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: float = 0.3

    def should_retry(self, error_class: NetErrorClass, attempt: int) -> bool:
        if error_class in (NetErrorClass.NONE, NetErrorClass.FATAL):
            return False
        return attempt < self.max_attempts

    def delay_for(
        self, error_class: NetErrorClass, attempt: int, retry_after: float | None = None
    ) -> float:
        if error_class is NetErrorClass.BACKOFF and retry_after is not None:
            return min(float(retry_after), self.max_delay)
        if error_class is NetErrorClass.ROTATE:
            # Rotation already changes the exit IP, so a long wait buys little.
            return min(self.base_delay * attempt, 5.0) * self._jitter()
        return min(self.base_delay * (2 ** (attempt - 1)), self.max_delay) * self._jitter()

    def _jitter(self) -> float:
        return 1 + random.uniform(-self.jitter, self.jitter)
