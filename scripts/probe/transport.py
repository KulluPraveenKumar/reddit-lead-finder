"""Transport abstraction for the P0 Validation Sprint.

**What a transport is.** A transport is an *egress path* — how bytes leave this
machine. It knows nothing about Reddit, about RSS, or about why a URL is being
fetched. Callers ask for a URL and get bytes back; which address the request
exited from is the transport's business alone.

**What a transport is not.** RSS is not a transport. RSS is a *format served at
a URL*, and it is fetched **through** a transport exactly like HTML is. Making
``RSSProvider`` a sibling of ``DirectConnectionProvider`` would put a content
format and an egress path on the same axis, and the first time you wanted "RSS
through a proxy" the abstraction would have nowhere to put it. RSS therefore
lives one layer up, in ``probe_rss.py``, and composes with any transport here.

**Scope.** This is probe code for P0. It exists to *compare* transports, not to
serve production traffic. The production implementation is
``docs/29-network-and-proxy-strategy.md`` §3 and lands in P4; this module is
deliberately the smallest thing that can produce an honest measurement.
Nothing here is optimised, pooled beyond one session per exit, or adaptive.

Credential rule, inherited from ``docs/08-proxy-service.md`` §1 and enforced
here: **a proxy is identified by ``host:port`` everywhere it is logged,
printed, or reported.** Username and password exist only inside the requests
session's proxy URL.
"""

from __future__ import annotations

import itertools
import random

# The shipped, measured header profiles. Reusing them rather than hand-rolling
# a header set is deliberate: on 2026-07-31 an incoherent set produced HTTP 403
# from every address including the local one (docs/PHASE-02-STATUS.md §3.1), and
# a probe that reproduced that bug would measure the bug rather than the
# transport.
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.net.user_agents import pick_profile  # noqa: E402


@dataclass
class TransportResult:
    """One request's outcome, from the transport's point of view."""

    transport: str
    exit_label: str  # "local" or "host:port" — NEVER credentials
    url: str
    ok: bool
    status: int | None
    body: bytes
    latency_ms: float
    error: str | None = None
    from_cache: bool = False

    @property
    def size(self) -> int:
        return len(self.body)


class TransportProvider(Protocol):
    """One way of getting bytes from the internet."""

    name: str
    exposes_origin_ip: bool

    def get(
        self,
        url: str,
        *,
        session_key: str | None,
        timeout: tuple[float, float],
        extra_headers: dict[str, str] | None,
    ) -> TransportResult: ...

    def exits(self) -> list[str]: ...


def _session_with_profile() -> tuple[requests.Session, str]:
    """A session with one atomic header profile pinned for its lifetime."""
    s = requests.Session()
    profile = pick_profile()
    s.headers.update(profile.as_dict())
    return s, profile.name


class DirectConnectionProvider:
    """Egress from this machine's own address.

    The only provider that exposes the operator's IP, which is why
    ``exposes_origin_ip`` is a first-class flag rather than a comment.
    """

    name = "direct"
    exposes_origin_ip = True

    def __init__(self) -> None:
        self._session, self._profile = _session_with_profile()

    def get(self, url, *, session_key=None, timeout=(10.0, 30.0), extra_headers=None):
        headers = dict(extra_headers or {})
        t0 = time.monotonic()
        try:
            r = self._session.get(url, timeout=timeout, headers=headers, allow_redirects=True)
            return TransportResult(
                transport=self.name,
                exit_label="local",
                url=url,
                ok=r.status_code == 200,
                status=r.status_code,
                body=r.content,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as exc:  # noqa: BLE001 - probe reports every failure class
            return TransportResult(
                transport=self.name,
                exit_label="local",
                url=url,
                ok=False,
                status=None,
                body=b"",
                latency_ms=(time.monotonic() - t0) * 1000,
                error=f"{type(exc).__name__}: {exc}"[:200],
            )

    def exits(self) -> list[str]:
        return ["local"]


@dataclass
class _Endpoint:
    host: str
    port: int
    username: str = field(repr=False)
    password: str = field(repr=False)

    @property
    def label(self) -> str:
        """The only form that ever leaves this class."""
        return f"{self.host}:{self.port}"

    @property
    def url(self) -> str:
        return f"http://{self.username}:{self.password}@{self.host}:{self.port}"

    def __repr__(self) -> str:  # credentials must not reach a traceback
        return f"_Endpoint({self.label})"

    __str__ = __repr__


def parse_proxy_file(path: str | Path) -> list[_Endpoint]:
    """Parse ``ip:port:user:pass`` lines.

    A malformed line is skipped and reported **by line number only** — a bad
    line is usually a good line with a typo, and it still contains a password.
    """
    out: list[_Endpoint] = []
    seen: set[tuple[str, int]] = set()
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) != 4:
            print(f"  proxy file line {lineno}: skipped (expected ip:port:user:pass)")
            continue
        host, port, user, pw = parts
        try:
            port_i = int(port)
        except ValueError:
            print(f"  proxy file line {lineno}: skipped (non-numeric port)")
            continue
        if (host, port_i) in seen:
            print(f"  proxy file line {lineno}: skipped (duplicate)")
            continue
        seen.add((host, port_i))
        out.append(_Endpoint(host, port_i, user, pw))
    return out


class WebshareProvider:
    """Egress through a pool of per-IP Webshare endpoints.

    Rotation is least-recently-used with a session pinned per exit, matching the
    shipped behaviour in ``src/net/proxy_manager.py``. Each exit gets its own
    session, and therefore its own cookie jar and its own header profile — ten
    addresses presenting one identical fingerprint is a stronger signal than one
    address would be.
    """

    name = "webshare"
    exposes_origin_ip = False

    def __init__(self, proxy_file: str | Path) -> None:
        self._endpoints = parse_proxy_file(proxy_file)
        if not self._endpoints:
            raise ValueError(f"no usable proxies in {proxy_file}")
        self._sessions: dict[str, requests.Session] = {}
        self._profiles: dict[str, str] = {}
        for ep in self._endpoints:
            s, prof = _session_with_profile()
            s.proxies.update({"http": ep.url, "https": ep.url})
            # Retry lives in the caller, which can switch exits. urllib3's own
            # retry would re-attempt on the same dead address.
            self._sessions[ep.label] = s
            self._profiles[ep.label] = prof
        self._cycle = itertools.cycle(self._endpoints)
        self._sticky: dict[str, _Endpoint] = {}

    def _pick(self, session_key: str | None) -> _Endpoint:
        if session_key and session_key in self._sticky:
            return self._sticky[session_key]
        ep = next(self._cycle)
        if session_key:
            self._sticky[session_key] = ep
        return ep

    def get(self, url, *, session_key=None, timeout=(10.0, 30.0), extra_headers=None):
        ep = self._pick(session_key)
        headers = dict(extra_headers or {})
        t0 = time.monotonic()
        try:
            r = self._sessions[ep.label].get(
                url, timeout=timeout, headers=headers, allow_redirects=True
            )
            return TransportResult(
                transport=self.name,
                exit_label=ep.label,
                url=url,
                ok=r.status_code == 200,
                status=r.status_code,
                body=r.content,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as exc:  # noqa: BLE001
            return TransportResult(
                transport=self.name,
                exit_label=ep.label,
                url=url,
                ok=False,
                status=None,
                body=b"",
                latency_ms=(time.monotonic() - t0) * 1000,
                error=f"{type(exc).__name__}: {exc}"[:200],
            )

    def exits(self) -> list[str]:
        return [ep.label for ep in self._endpoints]


class DisabledProvider:
    """Raises on any use.

    Exists so a test can assert that a code path made **no** network call. A
    provider that returns a canned response cannot prove that; one that raises
    can.
    """

    name = "disabled"
    exposes_origin_ip = False

    def get(self, url, *, session_key=None, timeout=None, extra_headers=None):
        raise RuntimeError(f"DisabledProvider: refused outbound request to {url}")

    def exits(self) -> list[str]:
        return []


class FutureManagedProvider:
    """A single-gateway managed provider (Decodo, IPRoyal, NetNut, SOAX, …).

    Not exercised in P0 — no such account exists. It is here because almost
    every managed residential vendor speaks the same shape
    (``user-session-x:pass@gateway:port``), so one class covers the market and
    a vendor change is configuration rather than code. Constructing it is part
    of the P0 acceptance criteria; calling it is not.
    """

    name = "future_managed"
    exposes_origin_ip = False

    def __init__(
        self, gateway: str, username: str, password: str, session_param: str = "-session-{key}"
    ) -> None:
        self._gateway = gateway
        self._username = username
        self._password = password
        self._session_param = session_param

    def get(self, url, *, session_key=None, timeout=(10.0, 30.0), extra_headers=None):
        raise NotImplementedError(
            "FutureManagedProvider is a shape, not an integration. "
            "Configure a real gateway before use."
        )

    def exits(self) -> list[str]:
        return [self._gateway]


class TransportManager:
    """Selects a transport. Callers never name one.

    The whole point of this class is that ``probe_rss`` and ``probe_transport``
    ask for a URL and do not know, and cannot discover, which address it left
    from. That is the property the production ``NetworkPolicy`` must preserve.
    """

    def __init__(self, providers: dict[str, TransportProvider], default: str) -> None:
        if default not in providers:
            raise ValueError(f"default transport {default!r} not in {sorted(providers)}")
        self._providers = providers
        self._default = default

    @property
    def available(self) -> list[str]:
        return sorted(self._providers)

    def provider(self, name: str | None = None) -> TransportProvider:
        return self._providers[name or self._default]

    def get(
        self,
        url: str,
        *,
        transport: str | None = None,
        session_key: str | None = None,
        timeout: tuple[float, float] = (10.0, 30.0),
        extra_headers: dict[str, str] | None = None,
    ) -> TransportResult:
        return self.provider(transport).get(
            url, session_key=session_key, timeout=timeout, extra_headers=extra_headers
        )


def build_manager(
    proxy_file: str | Path | None = None, default: str = "direct"
) -> TransportManager:
    """Assemble every transport that can be constructed on this machine."""
    providers: dict[str, TransportProvider] = {
        "direct": DirectConnectionProvider(),
        "disabled": DisabledProvider(),
    }
    if proxy_file and Path(proxy_file).exists():
        try:
            providers["webshare"] = WebshareProvider(proxy_file)
        except Exception as exc:  # noqa: BLE001
            print(f"  webshare provider unavailable: {exc}")
    return TransportManager(providers, default=default)


def polite_sleep(lo: float = 3.0, hi: float = 7.0) -> None:
    """The cadence from docs/02 §2.1 — randomised, never a fixed interval.

    A fixed sleep is itself a fingerprint, and this probe is measuring how a
    target responds to us; pacing it like the production client is part of
    measuring the right thing.
    """
    time.sleep(random.uniform(lo, hi))
