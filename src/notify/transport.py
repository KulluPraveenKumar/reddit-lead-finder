"""How a rendered body leaves the machine. One interface, four implementations.

``docs/21`` §7.1 asks for exactly this shape -- *"``src/notify/transport.py`` is
written against an interface with all three implementations behind it, so the
decision is a config value rather than a rewrite"* -- and the reason it is a
decision at all is that the transport question was never settled by measurement:

* **T1** ``ServeTransport`` -- ``POST`` to a running ``hermes serve``. Preferred by
  ``docs/21`` §7.1 *if* M-9 confirms send is exposed over a network interface.
* **T2** ``SubprocessTransport`` -- the ``hermes send`` CLI. Co-located only; §7.1
  calls it *"H1-only. Adequate for the phase, not for production"*.
* **T3** ``BotApiTransport`` -- the Telegram Bot API directly. *"Zero cost **by
  construction** -- no Hermes involvement at all."*
* ``NullTransport`` -- renders and records, sends nothing. The shipped default.

**M-5, M-9 and M-10 were never measured.** ``SPRINT-0-MEASUREMENTS`` F8 records
Track B as BLOCKED for want of a Telegram token, and P0's own recommendation says
it *"is not needed until P23"* -- while ``docs/34`` §P7 lists those three
measurements as a dependency. Both cannot hold. T3 is the branch ``docs/34`` §P0
already carries (*"If M-5 fails, notifications switch to transport T3"*) and it
removes the dependency by construction: **a notification cannot cost tokens if no
agent runtime is in the path.** So all three ship behind the interface and the
default is T3 once a token exists (D1). The dependency remains formally
unsatisfied and is reported as such, not reinterpreted as met.

**R4 holds in all four.** Nothing here imports Hermes: T1 posts to a URL, T2
executes a binary through ``subprocess``. Grep fence 3 -- built in Stage 1, after
six phases of claiming it -- enforces that, and it is import-based precisely so
that T2's ``"hermes"`` argv string stays legal while ``import hermes`` does not.

**R17 holds by construction.** No model is reachable from this module.

Specification: ``docs/21-hermes-architecture.md`` §7.1 ·
``docs/34-implementation-plan.md`` §P7 tasks 3 and 7 ·
``docs/P7-DECISION-ANALYSIS.md`` D1, D4, D5.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

import requests

from src.notify.service import NotifySettings

log = logging.getLogger(__name__)

#: Where the bot token lives. **Never** ``config.yaml``, which is committed.
TOKEN_ENV = "TELEGRAM_BOT_TOKEN"

#: Where T1's ``hermes serve`` endpoint lives -- the environment, not ``config.yaml``.
#:
#: ``docs/34`` §P7's Config row names five ``notify.*`` keys and no endpoint for
#: T1, while its task 3 requires T1 to exist and be *"selected by config"*. T1
#: cannot work without one, so the address has to come from somewhere.
#:
#: The environment is where this repository already puts machine-specific
#: locations, and for a stated reason: ``config.yaml`` says of ``proxy.file``
#: that *"this file is committed, and a path here names a location on one
#: person's machine -- so the proxy file is configured per machine via the
#: PROXY_FILE environment variable"*. A localhost port for a sidecar process is
#: the same species of value, and §P7's Config row already reaches for the
#: environment once, for ``TELEGRAM_BOT_TOKEN``. Adding an env var rather than a
#: sixth ``notify.*`` key therefore introduces no capability the frozen Config
#: row does not already imply, and no committed file names anyone's machine.
SERVE_URL_ENV = "HERMES_SERVE_URL"

#: Telegram's API root. A constant so a test can assert the URL shape without
#: matching on a literal spread through the module.
BOT_API_ROOT = "https://api.telegram.org"

#: Seconds. Short on purpose: a notification that has not left in five seconds
#: has already missed the *"delivered within 10 s"* criterion, and the caller has
#: a retry budget of its own. Waiting longer only holds the worker.
DEFAULT_TIMEOUT = 5.0


class SendError(RuntimeError):
    """A send failed, and this says whether trying again could help.

    The shape is deliberately the one P6 gave ``RedditClient.TransportError`` when
    it closed N2: before that, every transport failure was ``None``, so a caller
    could not tell "try again in a moment" from "this will never work" -- two
    outcomes with one representation. The same distinction matters here for the
    same reason, and Stage 5's retry budget is the consumer.

    ``retryable`` is **classified, never inferred by the caller**: a ``5xx`` is
    the server having a bad minute, a ``4xx`` is a wrong chat id or a revoked
    token, and retrying the latter burns the budget to arrive at the same answer.
    """

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@runtime_checkable
class Transport(Protocol):
    """Send one rendered body. Returns a provider message id for the record.

    An **id rather than a bool** because of trap T2a: P6 shipped
    ``html_fallback: True`` from a branch that fetched nothing, and its test
    asserted the flag. A returned identifier is evidence a send happened; a
    boolean is a claim that one did.
    """

    @property
    def name(self) -> str: ...

    def send(self, *, chat_id: str, markdown: str) -> str: ...


class NullTransport:
    """Sends nothing, and says so honestly.

    The **shipped default** (D4/D6). It exists for three jobs: the rollback state
    (``notify.enabled: false`` plus this) is the state every test run and fresh
    install already exercises; the whole pipeline is drivable with no token at
    all; and a machine with no credentials still records what it *would* have
    sent, which is what makes the offline half of P7 verifiable while blocker B1
    is open.

    The returned id is prefixed so a ``notify.sent`` row can never be mistaken
    for evidence of real delivery.
    """

    name = "null"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, *, chat_id: str, markdown: str) -> str:
        self.sent.append((chat_id, markdown))
        log.info("notification not sent: transport is 'null'", extra={"stage": "notify"})
        return f"null:{len(self.sent)}"


class BotApiTransport:
    """T3 -- the Telegram Bot API, directly, with ``requests``.

    Zero cost by construction: no agent runtime is in the path, so R17's *"zero
    tokens"* is a property of the wiring rather than a thing to measure.

    **Plain text, no ``parse_mode``.** The renderers emit ``*bold*``, and honouring
    it means choosing a parse mode -- at which point every reserved character in
    the body must be escaped for that mode. The bodies contain **untrusted text**:
    ``runs.error`` is an arbitrary exception message and subreddit names come from
    Reddit. A single unbalanced ``*`` or unescaped ``.`` in MarkdownV2 returns
    ``400 can't parse entities``, which loses the notification entirely -- and
    with no token on this machine (B1) that failure cannot be live-verified before
    shipping. Trading bold text for a message that cannot fail on its own content
    is the right side of that trade. The asterisks therefore appear literally;
    see the completion report, which records it as a decision rather than an
    oversight.
    """

    name = "bot_api"

    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        api_root: str = BOT_API_ROOT,
    ) -> None:
        resolved = (token if token is not None else os.environ.get(TOKEN_ENV, "")).strip()
        if not resolved:
            # Loudly, at construction -- not at send time. A transport that
            # accepted an empty token and failed on the first real notification
            # would turn a misconfiguration into a lost message, discovered by
            # its absence. Blocker B1: this machine has no token.
            raise SendError(
                f"{TOKEN_ENV} is not set, so the Telegram Bot API transport cannot be built. "
                "Add it to .env (which is gitignored), or set notify.transport: null.",
                retryable=False,
            )
        self._token = resolved
        self.timeout = timeout
        self.api_root = api_root.rstrip("/")

    def _url(self) -> str:
        return f"{self.api_root}/bot{self._token}/sendMessage"

    def send(self, *, chat_id: str, markdown: str) -> str:
        try:
            response = requests.post(
                self._url(),
                json={"chat_id": chat_id, "text": markdown},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            # Retryable: a refused connection or a timeout is a bad moment, not a
            # bad request. `str(exc)` can contain the URL and therefore the token,
            # so the message is built from the exception *type* only.
            raise SendError(
                f"could not reach the Telegram API ({type(exc).__name__})", retryable=True
            ) from None

        if response.status_code >= 500:
            raise SendError(
                f"Telegram returned {response.status_code}",
                retryable=True,
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            # Not retryable. A 400 is a malformed body, a 401 a revoked token, a
            # 403 a bot blocked by the chat -- none of which a second attempt
            # fixes, and all of which the operator must see rather than have
            # buried under a retry budget.
            raise SendError(
                f"Telegram rejected the message with {response.status_code}",
                retryable=False,
                status_code=response.status_code,
            )

        return _message_id(response, fallback=f"bot_api:{response.status_code}")


class ServeTransport:
    """T1 -- ``POST`` to a running ``hermes serve``.

    Preferred by ``docs/21`` §7.1 *"if M-9 confirms send is exposed over a network
    interface"*, because it survives the container split and keeps delivery inside
    Hermes' own durable ledger. **M-9 was never measured** and no Hermes runtime
    exists on this machine, so this ships unit-tested and is not live-verified --
    stated as assumption A7 rather than left to be discovered.

    It reaches Hermes over **HTTP**, importing nothing, which is what keeps R4
    intact while still making T1 available as a config value.
    """

    name = "serve"

    def __init__(self, base_url: str | None = None, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        resolved = (base_url if base_url is not None else os.environ.get(SERVE_URL_ENV, "")).strip()
        if not resolved:
            raise SendError(
                f"{SERVE_URL_ENV} is not set, so the 'serve' transport cannot be built. "
                f"Set it to a running `hermes serve` address, or use notify.transport: null.",
                retryable=False,
            )
        self.base_url = resolved.rstrip("/")
        self.timeout = timeout

    def send(self, *, chat_id: str, markdown: str) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/send",
                json={"target": f"telegram:{chat_id}", "body": markdown},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SendError(
                f"could not reach hermes serve ({type(exc).__name__})", retryable=True
            ) from None

        if response.status_code >= 500:
            raise SendError(
                f"hermes serve returned {response.status_code}",
                retryable=True,
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise SendError(
                f"hermes serve rejected the send with {response.status_code}",
                retryable=False,
                status_code=response.status_code,
            )
        return _message_id(response, fallback=f"serve:{response.status_code}")


class SubprocessTransport:
    """T2 -- ``hermes send -t telegram:<chat_id> -f <file>``.

    ``docs/21`` §7.1's own verdict: *"Only while co-located… H1-only. Adequate for
    the phase, not for production."* It stops working the moment the platform and
    Hermes are separate containers, because the ``hermes`` binary is not in the
    platform image -- and mounting the Docker socket so the platform could
    ``docker exec`` is *"rejected outright"* there for handing the data plane
    host-level control.

    **It imports nothing.** The body goes through a temporary file rather than
    argv, because a command line is visible in ``ps`` to every user on the box and
    a notification body can name a lead. The file is removed in a ``finally``, so
    a failing subprocess does not leave a trail of run summaries in the temp
    directory.

    ``hermes`` is not installed on this machine, so this is unit-tested against a
    patched ``subprocess.run`` and never live-verified (A7).
    """

    name = "subprocess"

    def __init__(self, *, binary: str = "hermes", timeout: float = 30.0) -> None:
        self.binary = binary
        self.timeout = timeout

    def send(self, *, chat_id: str, markdown: str) -> str:
        handle, path = tempfile.mkstemp(prefix="notify-", suffix=".md", text=True)
        os.close(handle)
        body = Path(path)
        try:
            body.write_text(markdown, encoding="utf-8")
            try:
                completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    [self.binary, "send", "-t", f"telegram:{chat_id}", "-f", str(body)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except FileNotFoundError:
                raise SendError(
                    f"{self.binary!r} is not on PATH; the subprocess transport needs it "
                    "co-located with the platform",
                    retryable=False,
                ) from None
            except subprocess.TimeoutExpired:
                raise SendError(
                    f"{self.binary!r} did not finish within {self.timeout:.0f}s", retryable=True
                ) from None

            if completed.returncode != 0:
                # Retryable: a co-located CLI that exits non-zero is usually a
                # transient gateway problem, and the caller's budget is bounded.
                raise SendError(
                    f"{self.binary!r} exited {completed.returncode}: "
                    f"{(completed.stderr or '').strip()[:200]}",
                    retryable=True,
                )
            return f"subprocess:{(completed.stdout or '').strip()[:80] or 'ok'}"
        finally:
            # Always, including on every raise above. A body left behind is a run
            # summary sitting in a world-readable directory.
            body.unlink(missing_ok=True)


def _message_id(response: requests.Response, *, fallback: str) -> str:
    """The provider's own id for the message, or a stand-in.

    Best effort by design: the id is written to ``run_events`` as evidence a send
    happened, and a provider that answered ``200`` with a body this cannot parse
    still sent the message. Failing here would discard a delivery that succeeded.
    """
    try:
        payload = response.json()
    except ValueError:
        return fallback
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict) and result.get("message_id") is not None:
            return str(result["message_id"])
        if payload.get("message_id") is not None:
            return str(payload["message_id"])
    return fallback


#: Config value -> constructor. The whole point of D1: choosing a transport is a
#: config change rather than a rewrite (``docs/21`` §7.1).
TRANSPORTS = ("null", "bot_api", "serve", "subprocess")


def build_transport(settings: NotifySettings, *, token: str | None = None) -> Transport:
    """The transport ``notify.transport`` names.

    An unknown name **raises and lists the valid ones**, rather than falling back
    to ``null``. A silent fallback would leave an operator who mistyped
    ``bot-api`` with a tier that looks configured, reports success, and delivers
    nothing -- the failure mode this project keeps finding and naming (T2a).
    """
    choice = (settings.transport or "null").strip().lower()
    if choice == "null":
        return NullTransport()
    if choice == "bot_api":
        return BotApiTransport(token)
    if choice == "serve":
        return ServeTransport()
    if choice == "subprocess":
        return SubprocessTransport()
    raise SendError(
        f"unknown notify.transport {settings.transport!r}; valid: {', '.join(TRANSPORTS)}",
        retryable=False,
    )


__all__ = [
    "BOT_API_ROOT",
    "TOKEN_ENV",
    "TRANSPORTS",
    "BotApiTransport",
    "NullTransport",
    "SendError",
    "ServeTransport",
    "SubprocessTransport",
    "Transport",
    "build_transport",
]
