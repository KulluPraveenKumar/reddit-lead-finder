"""``NetworkProvider`` — one way of getting bytes from the internet.

Reddit-agnostic by construction, like the rest of ``src/net/``: a provider knows
about exits, credentials and bandwidth, and nothing about what is being fetched.

**The capability flags are the point of the abstraction.** ``NetworkPolicy``
decides what to do with a provider by reading ``exposes_origin_ip`` and
``is_metered``, never by branching on ``name`` or ``type``. A policy that says
``if provider.name == "direct"`` has to be edited every time a provider is added;
one that says ``if provider.exposes_origin_ip`` does not. That is what makes
adding a vendor a configuration change (``docs/29`` §5.4).

Four methods, and each answers a different question:

* ``acquire``  — give me an exit to send this request through
* ``release``  — here is what happened; update your state
* ``health``   — can you serve requests at all right now?
* ``capacity`` — how much can you serve before you cannot?

``health`` and ``capacity`` are separate because "working" and "has budget left"
fail independently: a metered gateway with 0 GB remaining is perfectly reachable
and completely unusable, and a policy that only asked one question would route to
it until the vendor started returning errors.

Specification: ``docs/29-network-and-proxy-strategy.md`` §3.1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

import requests

from ..retry import ProxyExhaustedError
from ..user_agents import HeaderProfile


class Outcome(StrEnum):
    """What happened to one request, from the provider's point of view.

    ``BLOCKED`` and ``ERROR`` are deliberately distinct. A block is the target
    refusing *this exit* — the useful response is to stop using it. An error is
    the transport failing — the exit may be fine. Collapsing them would make a
    flaky network look like a burned IP and retire good exits.
    """

    OK = "ok"
    #: The target refused us through this exit: 403, 429 or a soft-block page.
    BLOCKED = "blocked"
    #: The request never completed: timeout, connection reset, TLS failure.
    ERROR = "error"


class Rotation(StrEnum):
    PER_REQUEST = "per_request"
    STICKY_SESSION = "sticky_session"
    NONE = "none"


class ProviderUnavailable(ProxyExhaustedError):
    """This provider cannot serve a request right now.

    Subclasses ``ProxyExhaustedError`` on purpose: ``ProxiedHTTPClient`` and
    ``RedditClient`` already handle that type, and a new sibling exception would
    silently bypass both handlers. The policy catches this to step the ladder;
    anything that does not catch it behaves exactly as it did before P4.
    """


@dataclass(frozen=True)
class Lease:
    """One authorisation to send one request through one exit.

    ``label`` is the only identifier that may be logged, rendered or stored —
    ``host:port`` for a proxy, the provider name for a direct connection. The
    credentialled URL lives in ``proxies`` and never leaves the transport.
    """

    provider: str
    label: str
    session: requests.Session
    proxies: dict[str, str] | None = None
    #: The header profile this lease's session was built with. Carried on the
    #: lease so a caller adding a ``Referer`` extends *that* identity rather than
    #: picking a fresh one -- mixing two profiles in one exchange is the
    #: incoherence that produced a measured 100% block rate twice.
    profile: HeaderProfile | None = None
    session_key: str | None = None
    #: Provider-private handle (a ``ProxyEndpoint``, a gateway identity, ...).
    #: Opaque to the policy and the transport; passed straight back to
    #: ``release`` so the provider can find its own bookkeeping.
    handle: Any = None

    def __repr__(self) -> str:  # pragma: no cover - trivial, but see the note
        # Never the default dataclass repr: it would print ``proxies``, which
        # contains the credentialled URL. This class is passed through exception
        # paths and debug logs, which is exactly where a credential escapes.
        return f"<Lease {self.provider}:{self.label}>"


@dataclass(frozen=True)
class ProviderHealth:
    """Can this provider serve a request right now, and if not, why not."""

    healthy: bool
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Capacity:
    """How much this provider can still serve.

    ``bytes_remaining`` is ``None`` for an unmetered provider — *unknown*, not
    *zero*. A policy that treated ``None`` as exhausted would refuse to use the
    free datacenter pool, which is the opposite of the intent.
    """

    usable_exits: int
    requests_per_minute: float | None = None
    bytes_remaining: float | None = None


class NetworkProvider(ABC):
    """One way of getting bytes from the internet. Knows nothing about Reddit."""

    #: The ``type`` string this provider is selected by in ``config.yaml``.
    type: ClassVar[str] = ""

    #: True only for a direct connection. Every proxy is False. The policy reads
    #: this to know which providers reveal the operator's own address.
    exposes_origin_ip: ClassVar[bool] = False
    #: Billed per GB, so bandwidth is a budgeted resource rather than free.
    is_metered: ClassVar[bool] = False
    #: Can pin a session to one exit for the life of a cursor walk.
    supports_sticky: ClassVar[bool] = False
    supports_geo: ClassVar[bool] = False
    rotation: ClassVar[Rotation] = Rotation.NONE

    def __init__(self, name: str):
        self.name = name

    @classmethod
    @abstractmethod
    def from_config(cls, name: str, spec: dict[str, Any]) -> NetworkProvider:
        """Build from one ``network.providers[]`` block.

        Construction knowledge lives on the class rather than in the registry so
        that adding a provider means adding one file, not editing two. ``spec``
        arrives with ``${VAR}`` references already resolved; keys the provider
        does not recognise (``classes``, which belongs to the policy) are
        ignored.
        """

    @abstractmethod
    def acquire(self, *, session_key: str | None = None, exclude: set[str] | None = None) -> Lease:
        """An exit to send one request through.

        ``exclude`` is the set of labels already tried for this request. It is
        **explicit** rather than emergent (``docs/29`` §4.2): retrying the same
        failing exit is the classic rotating-proxy bug, and it should not depend
        on an ordering side effect.

        Raises :class:`ProviderUnavailable` when nothing is usable.
        """

    @abstractmethod
    def release(
        self,
        lease: Lease,
        *,
        outcome: Outcome,
        status: int | None = None,
        latency_ms: float = 0.0,
        bytes_in: int = 0,
    ) -> None:
        """Record what happened. Always called, including on failure."""

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Whether this provider can serve a request right now."""

    @abstractmethod
    def capacity(self) -> Capacity:
        """What is left: usable exits, request rate, bandwidth."""

    def describe(self) -> dict[str, Any]:
        """Operator-facing summary. **Never contains a credential.**

        Every field here is a name, a flag or a count. The credentialled URL is
        reachable only through a :class:`Lease`, which is not serialised.
        """
        health = self.health()
        capacity = self.capacity()
        return {
            "name": self.name,
            "type": self.type,
            "healthy": health.healthy,
            "reason": health.reason,
            "exposes_origin_ip": self.exposes_origin_ip,
            "metered": self.is_metered,
            "supports_sticky": self.supports_sticky,
            "rotation": str(self.rotation),
            "usable_exits": capacity.usable_exits,
            "bytes_remaining": capacity.bytes_remaining,
        }

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"
