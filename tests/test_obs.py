"""Structured logging, correlation context, redaction, and ``emit_event``.

The redaction tests are the ones that matter. ``docs/35`` check 14 and R15 say a
credential never reaches a log, and P0 already measured that a naive ``repr()``
leaks proxy credentials — so this file asserts against the shapes that actually
leaked, not against a synthetic "secret123".
"""

from __future__ import annotations

import json
import logging

import pytest

from src.db.models import RunEvent
from src.obs.events import emit_event
from src.obs.logging import (
    REDACTED,
    ConsoleFormatter,
    ContextFilter,
    JsonFormatter,
    RedactingFilter,
    configure_logging,
    current_context,
    log_context,
    redact,
)

#: Credential shapes that have actually appeared in this project's logs or were
#: measured as leaking during P0.
LEAKY = [
    "sk-abcdef0123456789abcdef0123456789",
    "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
    'api_key="dsk-9f8e7d6c5b4a3210"',
    "DEEPSEEK_API_KEY=sk-0123456789abcdefghij",
    "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "http://user1234:hunter2secret@198.51.100.7:8080",
    "password = correcthorsebattery",
]


@pytest.fixture
def logs():
    """Capture formatted JSON log lines, restoring the root logger afterwards."""
    records: list[str] = []

    class Sink(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = Sink()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    previous_handlers, previous_level = root.handlers[:], root.level
    root.handlers = [handler]
    root.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        root.handlers = previous_handlers
        root.setLevel(previous_level)


# -- redaction -------------------------------------------------------------


@pytest.mark.parametrize("sample", LEAKY)
def test_every_known_credential_shape_is_redacted(sample):
    assert REDACTED in redact(sample), f"not redacted: {sample}"


@pytest.mark.parametrize("sample", LEAKY)
def test_no_credential_survives_a_log_line(sample, logs):
    logging.getLogger("t").info("connecting with %s", sample)

    line = logs[-1]
    assert REDACTED in line
    for fragment in _secret_fragments(sample):
        assert fragment not in line, f"{fragment!r} leaked into {line}"


def test_redaction_covers_extra_fields_not_just_the_message(logs):
    logging.getLogger("t").info("ok", extra={"provider": "sk-abcdef0123456789abcdef"})

    assert "sk-abcdef0123456789" not in logs[-1]


def test_redaction_covers_a_traceback(logs):
    try:
        raise ValueError("key sk-abcdef0123456789abcdef0123 rejected")
    except ValueError:
        logging.getLogger("t").exception("call failed")

    assert "sk-abcdef0123456789" not in logs[-1]


def test_redaction_is_idempotent():
    assert redact(redact(LEAKY[0])) == redact(LEAKY[0])


def test_ordinary_text_passes_through_untouched():
    clean = "scraped r/SaaS: 42 posts, 7 leads, 1.8 s"
    assert redact(clean) == clean


def test_ten_megabytes_of_log_contains_no_credential(tmp_path):
    """The phase's metric: 0 secret tokens in 10 MB of captured log."""
    target = 10 * 1024 * 1024
    log_file = tmp_path / "worker.log"
    configure_logging(level="INFO", fmt="json", log_file=str(log_file))
    root = logging.getLogger()
    # Keep only the file handler: 10 MB echoed to stderr makes a failure in any
    # other test in this file unreadable.
    root.handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    log = logging.getLogger("soak")
    try:
        line_no = 0
        while log_file.stat().st_size < target:
            sample = LEAKY[line_no % len(LEAKY)]
            log.info("attempt %d via %s and padding %s", line_no, sample, "x" * 400)
            line_no += 1
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = []

    # Size in bytes, read with newlines untranslated: on Windows the handler
    # writes CRLF, so `read_text` would return ~19k fewer characters than the
    # file actually holds and the "10 MB" claim would quietly be 9.98 MB.
    assert log_file.stat().st_size >= target
    with log_file.open(encoding="utf-8", newline="") as handle:
        body = handle.read()
    for sample in LEAKY:
        for fragment in _secret_fragments(sample):
            assert fragment not in body, f"{fragment!r} survived into the log file"


def _secret_fragments(sample: str) -> list[str]:
    """The parts of a sample that must never appear — not the label around them."""
    return {
        LEAKY[0]: ["sk-abcdef0123456789"],
        LEAKY[1]: ["abcdefghijklmnopqrstuvwxyz012345"],
        LEAKY[2]: ["dsk-9f8e7d6c5b4a3210"],
        LEAKY[3]: ["sk-0123456789abcdefghij"],
        LEAKY[4]: ["ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"],
        LEAKY[5]: ["hunter2secret"],
        LEAKY[6]: ["correcthorsebattery"],
    }[sample]


# -- correlation context ---------------------------------------------------


def test_a_record_inside_log_context_carries_the_run_id(logs):
    with log_context(run_id=12, job_id=34):
        logging.getLogger("t").info("working")

    payload = json.loads(logs[-1])
    assert payload["run_id"] == 12
    assert payload["job_id"] == 34


def test_context_nests_rather_than_replaces(logs):
    with log_context(run_id=1), log_context(job_id=2):
        logging.getLogger("t").info("both")

    payload = json.loads(logs[-1])
    assert (payload["run_id"], payload["job_id"]) == (1, 2)


def test_context_is_gone_after_the_block(logs):
    with log_context(run_id=1):
        pass
    logging.getLogger("t").info("outside")

    assert "run_id" not in json.loads(logs[-1])
    assert current_context() == {}


def test_an_explicit_extra_beats_the_ambient_context(logs):
    with log_context(run_id=1):
        logging.getLogger("t").info("specific", extra={"run_id": 99})

    assert json.loads(logs[-1])["run_id"] == 99


def test_worker_id_and_provider_are_separate_keys(logs):
    """One key answering two questions makes both unanswerable by grep.

    ``worker_id`` is the worker's identity; ``provider`` is the AI provider P20
    will name. They must not share a slot.
    """
    with log_context(worker_id="host-123-abc", provider="deepseek"):
        logging.getLogger("t").info("claimed")

    payload = json.loads(logs[-1])
    assert payload["worker_id"] == "host-123-abc"
    assert payload["provider"] == "deepseek"


def test_none_values_are_not_logged_as_null(logs):
    with log_context(run_id=5, project_id=None):
        logging.getLogger("t").info("no project yet")

    assert "project_id" not in json.loads(logs[-1])


def test_third_party_loggers_inherit_the_context(logs):
    """The whole reason this is a ContextVar: the worker cannot patch urllib3."""
    with log_context(run_id=7):
        logging.getLogger("urllib3.connectionpool").warning("retrying")

    assert json.loads(logs[-1])["run_id"] == 7


def test_json_output_is_one_object_per_line_with_the_expected_keys(logs):
    logging.getLogger("t").warning("hello")

    payload = json.loads(logs[-1])
    assert set(payload) == {"ts", "level", "logger", "msg"}
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "t"


def test_console_format_appends_the_context_in_brackets():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hi", None, None)
    record.run_id = 3
    assert "[run_id=3]" in ConsoleFormatter().format(record)


def test_configure_logging_puts_both_filters_on_every_handler(tmp_path):
    configure_logging(level="DEBUG", fmt="json", log_file=str(tmp_path / "a.log"))
    try:
        handlers = logging.getLogger().handlers
        assert len(handlers) == 2
        for handler in handlers:
            kinds = {type(f) for f in handler.filters}
            assert kinds == {ContextFilter, RedactingFilter}
            # Context first, or a value it injects would never be redacted.
            assert isinstance(handler.filters[0], ContextFilter)
    finally:
        for handler in logging.getLogger().handlers:
            handler.close()
        logging.getLogger().handlers = []


# -- emit_event ------------------------------------------------------------


@pytest.fixture
def run_id(temp_db):
    from sqlalchemy.orm import Session

    from src.db import database
    from src.db.models import Run

    with Session(bind=database.ENGINE) as session:
        run = Run(state="pending")
        session.add(run)
        session.commit()
        return run.id


def _session():
    from sqlalchemy.orm import Session

    from src.db import database

    return Session(bind=database.ENGINE, expire_on_commit=False)


def test_emit_event_appends_a_row_and_logs_the_same_fact(run_id, logs):
    with _session() as session:
        emit_event(session, run_id, "scrape.start", message="Scraping r/SaaS", subreddit="SaaS")
        session.commit()

    with _session() as session:
        row = session.query(RunEvent).one()
    assert row.event == "scrape.start"
    assert row.level == "info"
    assert json.loads(row.data_json)["subreddit"] == "SaaS"
    assert json.loads(logs[-1])["run_id"] == run_id


def test_emit_event_is_not_committed_by_itself(run_id):
    """The caller's transaction owns the row — that is what makes it atomic."""
    session = _session()
    try:
        emit_event(session, run_id, "scrape.start")
        session.rollback()
    finally:
        session.close()

    with _session() as session:
        assert session.query(RunEvent).count() == 0


def test_emit_event_redacts_its_message_and_data(run_id):
    with _session() as session:
        emit_event(
            session,
            run_id,
            "proxy.configured",
            message="via http://user1234:hunter2secret@198.51.100.7:8080",
            url="http://user1234:hunter2secret@198.51.100.7:8080",
        )
        session.commit()

    with _session() as session:
        row = session.query(RunEvent).one()
    assert "hunter2secret" not in row.message
    assert "hunter2secret" not in row.data_json


def test_emit_event_rejects_an_unknown_level(run_id):
    with _session() as session, pytest.raises(ValueError, match="unknown run_event level"):
        emit_event(session, run_id, "x", level="critical")


@pytest.mark.parametrize("level", ["info", "warning", "error"])
def test_every_documented_level_is_accepted(run_id, level):
    with _session() as session:
        emit_event(session, run_id, "x", level=level)
        session.commit()

    with _session() as session:
        assert session.query(RunEvent).one().level == level
