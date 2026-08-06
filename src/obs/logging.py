"""Structured logging with credential redaction.

``RedactingFilter`` is the last line of defence, not the first. Nothing should
be passing a key to a logger in the first place; this exists because "should"
is not a guarantee, and a leaked key in a log file is unrecoverable — you cannot
un-write a log someone has already shipped to a support ticket.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# Patterns that look like credentials regardless of where they came from.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # OpenAI-style / DeepSeek keys: sk- followed by 20+ key characters.
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),
    # Bearer tokens in headers or curl echoes.
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{16,}"),
    # key=..., api_key: "...", "token": "..." in any quoting style.
    re.compile(
        r"(?i)\b(api[_-]?key|apikey|token|secret|password|passwd|pwd)"
        r"(\"?\s*[:=]\s*\"?)([^\s\",;}]{6,})"
    ),
    # Proxy credentials: user:pass@host — the proxy file format.
    re.compile(r"\b([A-Za-z0-9_\-]{4,}):([^\s:@/]{4,})@([\w.\-]+:\d+)"),
]

# ASCII deliberately: this lands in Windows consoles running cp1252, and a
# UnicodeEncodeError inside the logger would be a spectacular own goal.
REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Replace anything credential-shaped. Idempotent and safe on any string."""
    if not text:
        return text
    out = text
    out = _SECRET_PATTERNS[0].sub(REDACTED, out)
    out = _SECRET_PATTERNS[1].sub(r"\1 " + REDACTED, out)
    out = _SECRET_PATTERNS[2].sub(r"\1\2" + REDACTED, out)
    out = _SECRET_PATTERNS[3].sub(r"\1:" + REDACTED + r"@\3", out)
    return out


class RedactingFilter(logging.Filter):
    """Redacts the message, its args, and any string field on the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact(a) if isinstance(a, str) else a for a in record.args
                )

        if record.exc_text:
            record.exc_text = redact(record.exc_text)

        for key, value in list(record.__dict__.items()):
            if key not in _RESERVED and isinstance(value, str):
                record.__dict__[key] = redact(value)

        return True


_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName",
}

# Context keys carried on every line when in scope.
_CONTEXT_KEYS = ("run_id", "job_id", "project_id", "stage", "provider", "lead_id")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        ctx = " ".join(
            f"{k}={getattr(record, k)}" for k in _CONTEXT_KEYS if getattr(record, k, None) is not None
        )
        return f"{base}  [{ctx}]" if ctx else base


def configure_logging(level: str = "INFO", fmt: str = "console", log_file: str | None = None) -> None:
    """Install handlers with the redacting filter attached to every one."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)

    redactor = RedactingFilter()

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    stream.addFilter(redactor)
    root.addHandler(stream)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(redactor)
        root.addHandler(file_handler)

    # These are noisy at INFO and say nothing an operator needs.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
