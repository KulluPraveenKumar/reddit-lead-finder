"""Shared wire format for OpenAI-compatible `/chat/completions` endpoints.

Deliberately raw ``requests`` rather than a vendor SDK. An SDK would bring its
own retry policy, its own error taxonomy, and its own opinions about timeouts —
all of which this layer already implements and needs to control. It would also
put a vendor package name in the dependency list of a project whose whole point
is that the vendor is swappable.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from ..errors import (
    ProviderError,
    ProviderUnreachableError,
    classify_http_status,
)
from .base import ChatRequest, ChatResponse, LLMProvider, ValidationResult

log = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Any provider exposing OpenAI's chat-completions shape."""

    base_url: str = ""
    chat_path: str = "/chat/completions"

    def __init__(self, api_key: str | None = None, *, model: str | None = None, **options):
        super().__init__(api_key, model=model, **options)
        self._session = requests.Session()

    # ------------------------------------------------------------------ wire

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: ChatRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.stop:
            payload["stop"] = request.stop
        return payload

    def _parse_usage(self, usage: dict[str, Any]) -> tuple[int, int, int]:
        """Return ``(cached_in, uncached_in, out)``.

        Providers disagree on the field names for the cached/uncached split.
        Subclasses override; the base falls back to "all input uncached", which
        is pessimistic and therefore safe — it can overstate cost but never
        understate it.
        """
        total_in = int(usage.get("prompt_tokens", 0) or 0)
        out = int(usage.get("completion_tokens", 0) or 0)
        return 0, total_in, out

    def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.api_key:
            from ..errors import ProviderNotConfiguredError

            raise ProviderNotConfiguredError(f"No API key configured for {self.name}")

        url = f"{self.base_url.rstrip('/')}{self.chat_path}"
        payload = self._build_payload(request)
        started = time.perf_counter()

        try:
            response = self._session.post(
                url, json=payload, headers=self._headers(), timeout=request.timeout
            )
        except requests.exceptions.Timeout as exc:
            raise ProviderUnreachableError(
                f"{self.display_name} timed out", detail=str(exc)
            ) from exc
        except (requests.exceptions.RequestException, OSError) as exc:
            # OSError is included deliberately. `requests` normally wraps socket
            # failures, but not always — an adapter, a proxy layer, or a mocking
            # library can surface a bare ConnectionError. Unclassified, it would
            # escape as a generic exception and the retry policy would decline to
            # retry a transient network blip.
            raise ProviderUnreachableError(
                f"Could not reach {self.display_name}", detail=str(exc)
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code != 200:
            body = response.text[:500]
            error_cls = classify_http_status(response.status_code, body)
            raise error_cls(
                self._error_message(response.status_code),
                status_code=response.status_code,
                detail=body,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"{self.display_name} returned a non-JSON body",
                status_code=200,
                detail=response.text[:500],
            ) from exc

        choices = data.get("choices") or []
        # An empty choices array is not an exception here: the repair ladder
        # handles empty content, and raising would skip it.
        content = ""
        finish_reason = None
        if choices:
            content = (choices[0].get("message") or {}).get("content") or ""
            finish_reason = choices[0].get("finish_reason")

        usage = data.get("usage") or {}
        cached_in, uncached_in, out = self._parse_usage(usage)

        return ChatResponse(
            content=content,
            model=data.get("model", request.model or self.model),
            input_tokens_cached=cached_in,
            input_tokens_uncached=uncached_in,
            output_tokens=out,
            reasoning_tokens=int(
                (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
            ),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            reported_cost_usd=self._reported_cost(usage),
            raw=data,
        )

    def _reported_cost(self, usage: dict[str, Any]) -> float | None:
        """Provider-reported cost, if any. Overridden where the field differs."""
        return None

    def _error_message(self, status: int) -> str:
        """Operator-facing text. Never a raw traceback, never a bare 'Error'."""
        return {
            401: f"{self.display_name} rejected this key. Check it was copied completely.",
            402: f"{self.display_name} balance exhausted. Add credit to resume AI features.",
            429: f"{self.display_name} is rate limiting requests.",
            400: f"{self.display_name} rejected the request as malformed.",
            422: f"{self.display_name} could not process the request.",
        }.get(status, f"{self.display_name} returned HTTP {status}.")

    # ------------------------------------------------------------- validation

    def validate_credentials(self) -> ValidationResult:
        """One-token completion: the cheapest proof the key works end to end.

        A models-list call would be cheaper still, but would not prove the key
        can actually complete — some keys list models and cannot infer.
        """
        from ..errors import InsufficientBalanceError, InvalidAPIKeyError
        from ..errors import ProviderError as _ProviderError

        if not self.api_key:
            return ValidationResult(ok=False, error="No API key provided", status="unconfigured")

        request = ChatRequest(
            messages=[ChatMessageFactory.user("ping")],
            model=self.model,
            max_tokens=1,
            json_mode=False,
            timeout=(10.0, 20.0),
        )
        started = time.perf_counter()
        try:
            response = self.chat(request)
            return ValidationResult(
                ok=True,
                model=response.model,
                context_window=self.context_window(),
                latency_ms=response.latency_ms,
                status="valid",
            )
        except InvalidAPIKeyError as exc:
            return ValidationResult(
                ok=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=exc.message,
                status="invalid_key",
            )
        except InsufficientBalanceError as exc:
            # The key is CORRECT. Reporting this as a validation failure would
            # force the operator to re-enter a working key after topping up.
            return ValidationResult(
                ok=False,
                model=self.model,
                context_window=self.context_window(),
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=exc.message,
                status="insufficient_balance",
            )
        except _ProviderError as exc:
            return ValidationResult(
                ok=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=exc.message,
                status="unreachable",
            )

    def price_per_million(self) -> dict[str, float]:
        raise NotImplementedError


class ChatMessageFactory:
    """Tiny helper so callers do not import ``ChatMessage`` just to build one."""

    @staticmethod
    def system(content: str):
        from .base import ChatMessage

        return ChatMessage(role="system", content=content)

    @staticmethod
    def user(content: str):
        from .base import ChatMessage

        return ChatMessage(role="user", content=content)
