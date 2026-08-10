"""P7 Stage 4 -- the transport interface and its four implementations.

**No test here touches the network.** T1 and T3 go through ``responses``, T2
through a patched ``subprocess.run``. The suite's ``block_network`` fixture would
raise on a real socket anyway, so a test that reached Telegram would fail rather
than quietly succeed on a developer's machine.

Two things every send-path test asserts, and neither is the return value alone:
the **captured request** and the **effect**. Trap T2a is why -- P6 shipped
``html_fallback: True`` from a branch that fetched nothing, and its test asserted
the flag.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

import pytest
import requests
import responses

from src.notify import NotifySettings
from src.notify.transport import (
    BOT_API_ROOT,
    SERVE_URL_ENV,
    TOKEN_ENV,
    TRANSPORTS,
    BotApiTransport,
    NullTransport,
    SendError,
    ServeTransport,
    SubprocessTransport,
    Transport,
    build_transport,
)
from src.obs.logging import RedactingFilter, redact

TOKEN = "123456789:AAHfake_TOKEN_material_35_chars_xyz"
SECRET_HALF = TOKEN.split(":", 1)[1]
SEND_URL = f"{BOT_API_ROOT}/bot{TOKEN}/sendMessage"
BODY = "*Run 1 complete*\n\n- Leads: 12"


@pytest.fixture(autouse=True)
def no_ambient_credentials(monkeypatch):
    """Neither variable may leak in from the developer's environment.

    Without this, a machine that *does* have a token would silently test a
    different code path than CI, which has none -- and the "refuses without a
    token" tests would pass for the wrong reason.
    """
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(SERVE_URL_ENV, raising=False)


# --------------------------------------------------------------- the interface


@pytest.mark.parametrize(
    "transport",
    [
        NullTransport(),
        BotApiTransport(TOKEN),
        ServeTransport("http://127.0.0.1:8765"),
        SubprocessTransport(),
    ],
)
def test_every_implementation_satisfies_the_protocol(transport):
    assert isinstance(transport, Transport)
    assert isinstance(transport.name, str) and transport.name


def test_the_four_names_are_the_documented_set():
    assert set(TRANSPORTS) == {"null", "bot_api", "serve", "subprocess"}


def test_send_error_classifies_rather_than_leaving_the_caller_to_guess():
    """The shape P6 gave ``TransportError`` when it closed N2."""
    assert SendError("x", retryable=True).retryable is True
    assert SendError("x").retryable is False
    assert SendError("x", status_code=503).status_code == 503


# ------------------------------------------------------------- NullTransport


def test_null_transport_records_what_it_would_have_sent_and_performs_no_io():
    t = NullTransport()
    ident = t.send(chat_id="42", markdown=BODY)
    assert t.sent == [("42", BODY)]
    assert ident.startswith("null:"), "the id must be unmistakably not a real delivery"


def test_null_transport_ids_are_distinct_per_send():
    t = NullTransport()
    assert t.send(chat_id="1", markdown="a") != t.send(chat_id="1", markdown="b")


# ------------------------------------------- BotApiTransport (T3) construction


def test_bot_api_refuses_loudly_at_construction_without_a_token():
    """Not at send time. Blocker B1: this machine has no token.

    A transport that accepted an empty token and failed on the first real
    notification would turn a misconfiguration into a lost message, discovered by
    its absence rather than by an error.
    """
    with pytest.raises(SendError, match=TOKEN_ENV):
        BotApiTransport()
    for blank in ("", "   ", None):
        with pytest.raises(SendError, match=TOKEN_ENV):
            BotApiTransport(blank)


def test_bot_api_reads_the_token_from_the_environment(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    assert BotApiTransport().name == "bot_api"


def test_the_token_is_never_stored_where_a_repr_would_print_it():
    """R15: a credential must not reach a log, and a ``repr`` reaches logs."""
    t = BotApiTransport(TOKEN)
    assert SECRET_HALF not in repr(t)
    assert SECRET_HALF not in str(t.__dict__.get("api_root", ""))


# ------------------------------------------------------ BotApiTransport (T3)


@responses.activate
def test_bot_api_actually_posts_and_the_request_is_asserted():
    """T2a: assert the effect, not the returned value.

    A transport that returned an id without issuing a request would satisfy a
    weaker test forever. This inspects the captured call.
    """
    responses.add(responses.POST, SEND_URL, json={"ok": True, "result": {"message_id": 77}})

    ident = BotApiTransport(TOKEN).send(chat_id="42", markdown=BODY)

    assert len(responses.calls) == 1, "exactly one request, and it happened"
    request = responses.calls[0].request
    assert request.url == SEND_URL
    assert request.method == "POST"
    import json as _json

    payload = _json.loads(request.body)
    assert payload == {"chat_id": "42", "text": BODY}
    assert ident == "77", "the provider's own id is the record of delivery"


@responses.activate
def test_the_body_is_sent_as_plain_text_with_no_parse_mode():
    """Deliberate, and the reasoning is in the module docstring.

    Bodies contain untrusted text -- ``runs.error`` is an arbitrary exception
    message, subreddit names come from Reddit -- so a single unbalanced ``*`` or
    unescaped ``.`` under MarkdownV2 returns ``400 can't parse entities`` and the
    notification is lost. With no token on this machine (B1) that failure cannot
    be live-verified before shipping, so the transport sends what cannot fail.
    """
    responses.add(responses.POST, SEND_URL, json={"ok": True, "result": {"message_id": 1}})
    BotApiTransport(TOKEN).send(chat_id="42", markdown="*bold* a.b (c) -d_e!")
    import json as _json

    payload = _json.loads(responses.calls[0].request.body)
    assert "parse_mode" not in payload
    assert payload["text"] == "*bold* a.b (c) -d_e!", "the body is sent verbatim, unescaped"


@responses.activate
@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_5xx_is_retryable(status):
    responses.add(responses.POST, SEND_URL, status=status, json={})
    with pytest.raises(SendError) as exc:
        BotApiTransport(TOKEN).send(chat_id="42", markdown=BODY)
    assert exc.value.retryable is True
    assert exc.value.status_code == status


@responses.activate
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
def test_a_4xx_is_not_retryable(status):
    """A wrong chat id or a revoked token is not fixed by trying again.

    Retrying would burn the budget to arrive at the same answer and bury the one
    thing the operator needs to see.
    """
    responses.add(responses.POST, SEND_URL, status=status, json={})
    with pytest.raises(SendError) as exc:
        BotApiTransport(TOKEN).send(chat_id="42", markdown=BODY)
    assert exc.value.retryable is False
    assert exc.value.status_code == status


@responses.activate
def test_a_connection_failure_is_retryable_and_names_no_url():
    """``str(exc)`` from requests can contain the URL, and the URL is the token."""
    responses.add(responses.POST, SEND_URL, body=requests.ConnectionError("refused"))
    with pytest.raises(SendError) as exc:
        BotApiTransport(TOKEN).send(chat_id="42", markdown=BODY)
    assert exc.value.retryable is True
    assert SECRET_HALF not in str(exc.value)
    assert "api.telegram.org" not in str(exc.value)


@responses.activate
def test_a_timeout_is_retryable():
    responses.add(responses.POST, SEND_URL, body=requests.Timeout("too slow"))
    with pytest.raises(SendError) as exc:
        BotApiTransport(TOKEN).send(chat_id="42", markdown=BODY)
    assert exc.value.retryable is True


@responses.activate
def test_a_200_whose_body_cannot_be_parsed_is_still_a_delivery():
    """Failing here would discard a message that was actually sent."""
    responses.add(responses.POST, SEND_URL, body="not json", status=200)
    assert BotApiTransport(TOKEN).send(chat_id="42", markdown=BODY) == "bot_api:200"


@responses.activate
def test_a_send_honours_its_timeout():
    responses.add(responses.POST, SEND_URL, json={"ok": True, "result": {"message_id": 3}})
    BotApiTransport(TOKEN, timeout=2.5).send(chat_id="42", markdown=BODY)
    assert responses.calls[0].request.req_kwargs["timeout"] == 2.5


# ------------------------------------------------------- ServeTransport (T1)


def test_serve_refuses_loudly_without_an_endpoint():
    with pytest.raises(SendError, match=SERVE_URL_ENV):
        ServeTransport()


def test_serve_reads_its_endpoint_from_the_environment(monkeypatch):
    monkeypatch.setenv(SERVE_URL_ENV, "http://127.0.0.1:8765/")
    assert ServeTransport().base_url == "http://127.0.0.1:8765", "a trailing slash is trimmed"


@responses.activate
def test_serve_posts_the_target_and_body_and_imports_no_hermes():
    """R4: T1 reaches Hermes over HTTP, so nothing under ``src/`` imports it."""
    responses.add(responses.POST, "http://127.0.0.1:8765/send", json={"result": {"message_id": 9}})
    ident = ServeTransport("http://127.0.0.1:8765").send(chat_id="42", markdown=BODY)

    assert len(responses.calls) == 1
    import json as _json

    payload = _json.loads(responses.calls[0].request.body)
    assert payload == {"target": "telegram:42", "body": BODY}
    assert ident == "9"


@responses.activate
def test_serve_accepts_a_flat_message_id():
    """T1's response shape is **unmeasured**, so the parser tolerates both forms.

    M-9 and M-10 were never taken (Track B is blocked for want of a token), so
    nobody knows whether ``hermes serve`` nests its id under ``result`` the way
    Telegram does. Accepting either is not speculative generality -- it is the
    honest response to an unmeasured contract, and the alternative is discarding
    the id of a message that was delivered.
    """
    responses.add(responses.POST, "http://h/send", json={"message_id": "abc-123"})
    assert ServeTransport("http://h").send(chat_id="1", markdown=BODY) == "abc-123"


@responses.activate
def test_a_200_with_no_recognisable_id_still_counts_as_delivered():
    responses.add(responses.POST, "http://h/send", json={"ok": True})
    assert ServeTransport("http://h").send(chat_id="1", markdown=BODY) == "serve:200"


@responses.activate
def test_a_200_whose_json_is_a_list_still_counts_as_delivered():
    """A payload that is valid JSON but not an object must not raise."""
    responses.add(responses.POST, "http://h/send", json=[1, 2, 3])
    assert ServeTransport("http://h").send(chat_id="1", markdown=BODY) == "serve:200"


@responses.activate
def test_serve_classifies_failures_the_same_way():
    responses.add(responses.POST, "http://h/send", status=503, json={})
    with pytest.raises(SendError) as exc:
        ServeTransport("http://h").send(chat_id="1", markdown=BODY)
    assert exc.value.retryable is True

    responses.reset()
    responses.add(responses.POST, "http://h/send", status=400, json={})
    with pytest.raises(SendError) as exc:
        ServeTransport("http://h").send(chat_id="1", markdown=BODY)
    assert exc.value.retryable is False


@responses.activate
def test_serve_unreachable_is_retryable():
    responses.add(responses.POST, "http://h/send", body=requests.ConnectionError("no"))
    with pytest.raises(SendError) as exc:
        ServeTransport("http://h").send(chat_id="1", markdown=BODY)
    assert exc.value.retryable is True


# -------------------------------------------------- SubprocessTransport (T2)


class FakeRun:
    """Records the argv and the file the transport wrote, then answers."""

    def __init__(self, returncode=0, stdout="sent-1", stderr="", raises=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raises = raises
        self.argv: list[str] | None = None
        self.file_contents: str | None = None
        self.file_path: Path | None = None

    def __call__(self, argv, **kwargs):
        self.argv = list(argv)
        self.file_path = Path(argv[-1])
        self.file_contents = self.file_path.read_text(encoding="utf-8")
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def test_subprocess_builds_the_documented_command(monkeypatch):
    """``hermes send -t telegram:<chat> -f <file>`` -- ``docs/21`` §7.1."""
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)

    ident = SubprocessTransport().send(chat_id="42", markdown=BODY)

    assert fake.argv is not None
    assert fake.argv[:5] == ["hermes", "send", "-t", "telegram:42", "-f"]
    assert fake.argv[5].endswith(".md")
    assert ident == "subprocess:sent-1"


def test_the_body_goes_through_a_file_not_argv(monkeypatch):
    """A command line is visible in ``ps`` to every user on the box.

    A notification body can name a lead, so it must not become an argument.
    """
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    SubprocessTransport().send(chat_id="42", markdown=BODY)

    assert fake.file_contents == BODY
    assert BODY not in " ".join(fake.argv or [])


def test_the_temp_file_is_removed_on_success(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    SubprocessTransport().send(chat_id="42", markdown=BODY)
    assert fake.file_path is not None
    assert not fake.file_path.exists()


def test_the_temp_file_is_removed_when_the_subprocess_fails(monkeypatch):
    """A failing send must not leave run summaries in the temp directory."""
    fake = FakeRun(returncode=1, stderr="gateway down")
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(SendError):
        SubprocessTransport().send(chat_id="42", markdown=BODY)
    assert fake.file_path is not None and not fake.file_path.exists()


def test_the_temp_file_is_removed_when_the_binary_is_missing(monkeypatch):
    fake = FakeRun(raises=FileNotFoundError("hermes"))
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(SendError, match="not on PATH"):
        SubprocessTransport().send(chat_id="42", markdown=BODY)
    assert fake.file_path is not None and not fake.file_path.exists()


def test_no_temp_files_are_left_behind_across_many_sends(monkeypatch):
    """The `finally` is asserted by counting the directory, not by reading it."""
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    before = len(list(Path(tempfile.gettempdir()).glob("notify-*.md")))
    for _ in range(5):
        SubprocessTransport().send(chat_id="42", markdown=BODY)
    assert len(list(Path(tempfile.gettempdir()).glob("notify-*.md"))) == before


def test_a_missing_binary_is_not_retryable(monkeypatch):
    """``hermes`` is not installed on this machine, and will not be by a retry."""
    monkeypatch.setattr(subprocess, "run", FakeRun(raises=FileNotFoundError("hermes")))
    with pytest.raises(SendError) as exc:
        SubprocessTransport().send(chat_id="42", markdown=BODY)
    assert exc.value.retryable is False


def test_a_nonzero_exit_is_retryable_and_quotes_stderr(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRun(returncode=3, stderr="gateway down"))
    with pytest.raises(SendError) as exc:
        SubprocessTransport().send(chat_id="42", markdown=BODY)
    assert exc.value.retryable is True
    assert "gateway down" in str(exc.value)


def test_a_subprocess_timeout_is_retryable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRun(raises=subprocess.TimeoutExpired("hermes", 30)))
    with pytest.raises(SendError) as exc:
        SubprocessTransport().send(chat_id="42", markdown=BODY)
    assert exc.value.retryable is True


def test_the_subprocess_never_uses_a_shell(monkeypatch):
    """A body reaching a shell would be an injection surface."""
    seen = {}

    def capture(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", capture)
    SubprocessTransport().send(chat_id="42", markdown=BODY)
    assert seen.get("shell") in (None, False)


# ------------------------------------------------------------ build_transport


def test_build_transport_constructs_each_of_the_four(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv(SERVE_URL_ENV, "http://127.0.0.1:8765")
    for name in TRANSPORTS:
        built = build_transport(NotifySettings(enabled=True, transport=name))
        assert built.name == name


def test_the_default_settings_build_the_null_transport():
    """D4/D6: off, and reaching nothing, until the operator says otherwise."""
    assert build_transport(NotifySettings.from_config({})).name == "null"
    assert build_transport(NotifySettings.from_config(None)).name == "null"


def test_an_unknown_transport_raises_and_names_the_valid_ones():
    """Never a silent fallback to ``null``.

    A fallback would leave an operator who mistyped ``bot-api`` with a tier that
    looks configured, reports success and delivers nothing -- the failure mode
    this project keeps finding.
    """
    with pytest.raises(SendError) as exc:
        build_transport(NotifySettings(enabled=True, transport="bot-api"))
    assert "bot-api" in str(exc.value)
    for name in TRANSPORTS:
        assert name in str(exc.value)


def test_transport_names_are_matched_case_insensitively_and_trimmed(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    assert build_transport(NotifySettings(enabled=True, transport="  BOT_API ")).name == "bot_api"


def test_building_bot_api_without_a_token_surfaces_the_reason():
    with pytest.raises(SendError, match=TOKEN_ENV):
        build_transport(NotifySettings(enabled=True, transport="bot_api"))


# ------------------------------------------------------------------ redaction


def test_the_bot_token_is_redacted_from_a_plain_string():
    assert SECRET_HALF not in redact(TOKEN)
    assert "123456789" in redact(TOKEN), "the public bot id identifies which bot, and is kept"


def test_the_bot_token_is_redacted_inside_the_api_url():
    """The leak vector that no earlier pattern covered.

    The Bot API puts the credential in the **path**, so every log line or
    traceback quoting the URL quotes the token. The keyword pattern needs
    ``token=`` and the proxy pattern needs ``@host``; the API URL has neither.
    """
    assert SECRET_HALF not in redact(f"POST {SEND_URL} -> 200")
    assert SECRET_HALF not in redact(f"could not reach {SEND_URL}: timeout")


def test_the_bot_token_is_redacted_from_a_log_record(caplog):
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger("test.notify.redaction")
    logger.addHandler(handler)
    logger.propagate = True
    try:
        with caplog.at_level(logging.INFO, logger="test.notify.redaction"):
            RedactingFilter().filter(
                logging.LogRecord(
                    "test.notify.redaction",
                    logging.INFO,
                    __file__,
                    1,
                    "posting to %s",
                    (SEND_URL,),
                    None,
                )
            )
        record = logging.LogRecord(
            "x", logging.INFO, __file__, 1, f"posting to {SEND_URL}", None, None
        )
        RedactingFilter().filter(record)
        assert SECRET_HALF not in record.getMessage()
    finally:
        logger.removeHandler(handler)


def test_the_bot_token_is_redacted_from_an_extra_field():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "sent", None, None)
    record.url = SEND_URL  # type: ignore[attr-defined]
    RedactingFilter().filter(record)
    assert SECRET_HALF not in record.url  # type: ignore[attr-defined]


def test_redaction_does_not_fire_on_ordinary_numbers():
    """A false positive that mangled a run id would be its own defect."""
    for benign in ("run 12345678 finished in 42s", "ratio 1234567890:12", "1234:5678"):
        assert redact(benign) == benign


def test_every_shipped_secret_pattern_still_holds():
    """The four that existed before P7 must be unaffected by the fifth."""
    assert "sk-" not in redact("key sk-abcdefghijklmnopqrstuvwx")
    assert "abcdefghijklmnop" not in redact("Authorization: Bearer abcdefghijklmnopqrst")
    assert "hunter2hunter2" not in redact('{"password": "hunter2hunter2"}')
    assert "s3cretpass" not in redact("http://user1:s3cretpass@proxy.example.com:8080")


# ------------------------------------------------------------------ boundaries


def test_transport_imports_no_model_and_no_hermes():
    """R17 and R4, re-asserted at the point of use.

    ``requests`` **is** expected here -- ``transport.py`` is the one module in the
    package allowed an HTTP client, and Stage 1's fence allowlists it by name.
    ``subprocess`` is expected too: T2 executes the ``hermes`` binary without
    importing it, which is exactly how R4 survives T2 existing at all.
    """
    from src.notify import transport as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    imports = [
        line.strip()
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "import" in line
    ]
    joined = " ".join(imports)
    assert "src.ai" not in joined
    assert "import hermes" not in joined
    assert "from hermes" not in joined
    assert "requests" in joined, "T3 needs it, and the fence allows it here only"


def test_a_send_without_a_mock_is_blocked_rather_than_reaching_telegram():
    """The suite is offline, and this proves the transport would really dial out.

    Caught as ``RuntimeError`` rather than by importing ``NetworkCallBlocked``:
    pytest loads ``tests/conftest.py`` as the module ``conftest``, so
    ``tests.conftest.NetworkCallBlocked`` is a *different class object* and
    ``pytest.raises`` would not match it. Both it and :class:`SendError` derive
    from ``RuntimeError``, so the base class is the identity-independent way to
    say "this did not silently succeed".
    """
    with pytest.raises((RuntimeError, requests.RequestException)) as exc:
        BotApiTransport(TOKEN, timeout=0.01).send(chat_id="42", markdown=BODY)

    assert type(exc.value).__name__ in {
        "NetworkCallBlocked",
        "SendError",
        "ConnectionError",
        "ConnectTimeout",
    }, f"unexpected escape: {type(exc.value).__name__}"
