"""Structured logging with credential redaction and run/job correlation.

Three things live here, and they are separate on purpose:

1. ``RedactingFilter`` is the last line of defence, not the first. Nothing should
   be passing a key to a logger in the first place; this exists because "should"
   is not a guarantee, and a leaked key in a log file is unrecoverable — you cannot
   un-write a log someone has already shipped to a support ticket.
2. ``ContextFilter`` stamps ``run_id`` / ``job_id`` / ``project_id`` onto every
   record emitted while a :func:`log_context` block is open, including records
   from third-party libraries that know nothing about this project. That is the
   whole reason the context is a ``ContextVar`` and not an argument: the worker
   cannot pass ``run_id`` into ``urllib3``.
3. The JSON formatter comes from ``python-json-logger`` (``docs/33`` §3.2,
   ``ARCHITECTURE_FREEZE`` §5). It replaced a hand-rolled ``json.dumps``
   formatter in P2 — same output shape, one less thing to maintain.

Filter order is load-bearing: ``ContextFilter`` runs **before** ``RedactingFilter``
on every handler, so context values are redacted too. A filter that injected a
credential after the redactor had run would defeat the redactor entirely.
"""

from __future__ import annotations

import contextvars
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from pythonjsonlogger.json import JsonFormatter as _LibraryJsonFormatter

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
    # Telegram bot tokens: `<bot_id>:<35 chars>`, with or without the `bot`
    # prefix the API URL uses. P7 task 7.
    #
    # None of the patterns above catches this, and the gap matters because of
    # *where* the token appears: the Bot API puts it in the PATH, so any log line
    # or traceback quoting the URL quotes the credential. Pattern 3 needs a
    # `token=` keyword and pattern 4 needs `@host`, and the API URL has neither.
    #
    # The numeric bot id is kept: it is public, and it is what tells an operator
    # *which* bot the line is about. Only the secret half is replaced.
    re.compile(r"\b(bot)?(\d{8,12}):[A-Za-z0-9_\-]{35}\b"),
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
    # `\g<1>` rather than `\1`: the group is optional, so on a bare token it
    # substitutes empty — and `\1` followed by a digit would be read as a
    # two-digit group reference.
    out = _SECRET_PATTERNS[4].sub(r"\g<1>\g<2>:" + REDACTED, out)
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
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)

        if record.exc_text:
            record.exc_text = redact(record.exc_text)

        for key, value in list(record.__dict__.items()):
            if key not in _RESERVED and isinstance(value, str):
                record.__dict__[key] = redact(value)

        return True


_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}

# Context keys carried on every line when in scope.
#
# `worker_id` and `provider` are separate keys on purpose: the worker's identity
# and the AI provider's name are different questions, and one key answering both
# makes "which provider was slow?" unanswerable by grep the moment P20 lands.
_CONTEXT_KEYS = ("run_id", "job_id", "project_id", "stage", "worker_id", "provider", "lead_id")

#: The ambient correlation context. A ``ContextVar`` rather than a thread-local
#: because the worker's heartbeat thread and any future executor inherit a
#: *copy* on creation — a thread-local would silently lose the run id at exactly
#: the moment a background thread logged something worth correlating.
_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("log_context")


def current_context() -> dict[str, Any]:
    """The correlation fields currently in scope. Never ``None``."""
    return dict(_CONTEXT.get({}))


@contextmanager
def log_context(**fields: Any) -> Iterator[dict[str, Any]]:
    """Stamp ``fields`` onto every log record emitted inside the block.

    Nests: an inner block adds to the outer one rather than replacing it, so
    ``log_context(run_id=1)`` wrapping ``log_context(job_id=7)`` yields records
    carrying both. Values of ``None`` are dropped rather than logged as null —
    "job_id": null is noise on every line the worker writes while idle.
    """
    merged = current_context()
    merged.update({k: v for k, v in fields.items() if v is not None})
    token = _CONTEXT.set(merged)
    try:
        yield merged
    finally:
        _CONTEXT.reset(token)


class ContextFilter(logging.Filter):
    """Copies the ambient context onto each record, without overwriting.

    An explicit ``log.info("...", extra={"run_id": 9})`` wins over the ambient
    value: the caller who bothered to be specific is more likely to be right.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in _CONTEXT.get({}).items():
            if getattr(record, key, None) is None:
                setattr(record, key, value)
        return True


class JsonFormatter(_LibraryJsonFormatter):
    """One JSON object per line, with this project's field names.

    The format string is empty on purpose: every emitted key is chosen in
    :meth:`add_fields` below, so the output schema is decided in one readable
    place rather than by a ``%(...)s`` string read in two.
    """

    def __init__(self) -> None:
        super().__init__("", json_default=str)

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        ordered: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                ordered[key] = value
        if record.exc_info:
            # Redacted here, not by the filter: a traceback does not exist until
            # a formatter renders it, so the filter has nothing to redact yet.
            # A key in an exception message is the most common way one reaches a
            # log at all.
            ordered["exc"] = redact(self.formatException(record.exc_info))

        # Anything the library added that is not one of ours is dropped: the
        # keys above are what `docs/35` check 17 asserts on, and an unbounded
        # key set makes a log grep a guessing game.
        log_record.clear()
        log_record.update(ordered)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        # Redacted on the way out for the same reason the JSON formatter does it:
        # the traceback is rendered here, after every filter has run.
        base = redact(super().format(record))
        ctx = " ".join(
            f"{k}={getattr(record, k)}"
            for k in _CONTEXT_KEYS
            if getattr(record, k, None) is not None
        )
        return f"{base}  [{ctx}]" if ctx else base


def configure_logging(
    level: str = "INFO", fmt: str = "console", log_file: str | None = None
) -> None:
    """Install handlers with the context and redacting filters on every one."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    _attach_filters(stream)
    root.addHandler(stream)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        _attach_filters(file_handler)
        root.addHandler(file_handler)

    # These are noisy at INFO and say nothing an operator needs.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _attach_filters(handler: logging.Handler) -> None:
    """Context first, then redaction — see the module docstring."""
    handler.addFilter(ContextFilter())
    handler.addFilter(RedactingFilter())
