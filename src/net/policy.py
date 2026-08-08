"""``NetworkPolicy`` — egress is chosen per request class, with a degradation ladder.

This is the component P4 is named for, and [AD-25](../../docs/ARCHITECTURE_FREEZE.md)
in one sentence: **egress is a policy, not a mandate.**

Three ideas, and they are deliberately separate:

* **Request class** decides *what kind* of traffic this is. RSS, health checks
  and the customer's own website are always direct -- that is [R18], frozen
  architecture, and it is not a configuration preference.
* **Policy** decides which providers are *eligible*: ``direct_only``,
  ``prefer_proxy``, ``proxy_only``.
* **Ladder** decides the *order* eligible providers are tried in.

Policy and ladder are two axes because the measurement that sets the order is
independent of the rule that sets eligibility. P0 measured direct at 100%
success and the datacenter pool at 71.4% (``docs/SPRINT-0-MEASUREMENTS`` §1.2),
so the shipped ladder is ``[direct, dc]`` -- while ``proxy_only`` remains
available and, with ``on_pool_exhausted: fail_run``, reproduces exactly the
pre-P4 behaviour. Encoding order in the eligibility enum would have made
re-measuring a code change.

**Nothing here holds a database session.** Degradation is recorded as a value
object and drained by the caller after its network work finishes -- see
:meth:`NetworkPolicy.drain_notices`. A network layer that wrote to SQLite would
hold the single write lock across a multi-minute fetch, which is the defect that
blocked P3's sign-off (``docs/PHASE-03-COMPLETION-REPORT`` §5.0).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .providers import (
    DirectProvider,
    Lease,
    NetworkProvider,
    Outcome,
    ProviderUnavailable,
    WebshareDatacenterProvider,
    build_provider,
)
from .retry import ProxyExhaustedError

log = logging.getLogger(__name__)


class RequestClass(StrEnum):
    """What kind of traffic this is. Deliberately target-agnostic names."""

    #: Published feeds. Low volume, and the publisher expects to be polled.
    RSS = "rss"
    #: Canaries and reachability probes. Must reflect the real path.
    HEALTH = "health"
    #: The customer's own website. Crawling it from ten rotating datacenter IPs
    #: looks like an attack; it should come from one stable address.
    WEBSITE = "website"
    #: Bulk listing and search pages -- where IP exposure actually accumulates.
    HTML = "html"
    COMMENTS = "comments"
    #: Bursty lookups. A burst from one address is the most block-prone pattern
    #: in the system.
    VALIDATION = "validation"


#: **Frozen architecture, not configuration** ([R18]). These three classes are
#: direct under every policy value. ``network.direct.classes`` may name more; it
#: cannot take one of these away, and an attempt to is logged and ignored rather
#: than honoured -- an operator cannot switch off a freeze rule by editing a list.
ALWAYS_DIRECT: frozenset[str] = frozenset(
    {RequestClass.RSS.value, RequestClass.HEALTH.value, RequestClass.WEBSITE.value}
)

DEFAULT_REQUEST_CLASS = RequestClass.HTML.value


class Policy(StrEnum):
    DIRECT_ONLY = "direct_only"
    PREFER_PROXY = "prefer_proxy"
    PROXY_ONLY = "proxy_only"


class OnPoolExhausted(StrEnum):
    #: Continue on the direct connection, under the hourly governor, and log a
    #: visible warning. The default: a truncated run is worse than a slower one.
    DEGRADE_TO_DIRECT = "degrade_to_direct"
    #: Fail retryably; the run resumes when the pool recovers. For when IP
    #: exposure matters more than latency.
    PAUSE_RUN = "pause_run"
    #: The pre-P4 ``fail_closed`` behaviour. Kept for compliance situations.
    FAIL_RUN = "fail_run"


class EgressExhausted(ProxyExhaustedError):
    """No eligible provider could serve this request class.

    Subclasses ``ProxyExhaustedError`` so every pre-P4 handler still catches it.
    ``action`` records which ``on_pool_exhausted`` setting produced it, and
    ``retryable`` is what a future job handler will map to ``RetryableError``
    once the transport raises rather than swallowing (``PHASE-03-HANDOVER`` T5).
    """

    def __init__(self, message: str, *, action: str = OnPoolExhausted.FAIL_RUN.value):
        super().__init__(message)
        self.action = action

    @property
    def retryable(self) -> bool:
        return self.action == OnPoolExhausted.PAUSE_RUN.value


@dataclass(frozen=True)
class DegradationNotice:
    """One ladder step, recorded for the operator's timeline.

    A value object on purpose: it crosses from the network layer to the
    orchestration layer as *data*, so nothing in ``src/net/`` needs a database
    session to make degradation visible.
    """

    request_class: str
    from_provider: str
    to_provider: str
    reason: str

    @property
    def key(self) -> tuple[str, str]:
        """Dedup key. One notice per ladder step per run, not one per request."""
        return (self.from_provider, self.to_provider)

    def message(self) -> str:
        return (
            f"Egress degraded: {self.from_provider} → {self.to_provider} "
            f"for {self.request_class} traffic ({self.reason})"
        )

    def as_data(self) -> dict[str, str]:
        return {
            "request_class": self.request_class,
            "from_provider": self.from_provider,
            "to_provider": self.to_provider,
            "reason": self.reason,
        }


class NetworkPolicy:
    """Chooses a provider per request class and degrades along the ladder."""

    def __init__(
        self,
        providers: list[NetworkProvider],
        *,
        policy: str = Policy.PREFER_PROXY.value,
        ladder: list[str] | None = None,
        on_pool_exhausted: str = OnPoolExhausted.DEGRADE_TO_DIRECT.value,
        classes_by_provider: dict[str, set[str]] | None = None,
        direct_classes: set[str] | None = None,
    ):
        self.providers = {provider.name: provider for provider in providers}
        self.policy = Policy(policy)
        self.on_pool_exhausted = OnPoolExhausted(on_pool_exhausted)
        self.ladder = [name for name in (ladder or list(self.providers)) if name in self.providers]
        if not self.ladder:
            self.ladder = list(self.providers)
        self.classes_by_provider = classes_by_provider or {}
        # ALWAYS_DIRECT is unioned in, never intersected: config may widen the
        # direct set, and cannot narrow it below the frozen three.
        self.direct_classes = set(direct_classes or set()) | set(ALWAYS_DIRECT)

        self._lock = threading.RLock()
        self._notices: dict[tuple[str, str], DegradationNotice] = {}

    # ------------------------------------------------------------ selection

    def _serves(self, provider: NetworkProvider, request_class: str) -> bool:
        allowed = self.classes_by_provider.get(provider.name)
        return True if allowed is None else request_class in allowed

    def eligible(self, request_class: str) -> list[NetworkProvider]:
        """Providers that may serve this class, in ladder order.

        The [R18] classes short-circuit the policy entirely: they resolve to the
        direct providers and nothing else, whatever ``policy`` says and whether
        or not ``direct`` appears in the ladder.
        """
        if request_class in self.direct_classes:
            # Searched across **every configured provider**, not just the ladder.
            # The ladder is a degradation order for the classes that consult one;
            # these classes do not. Restricting them to the ladder would let
            # `ladder: [dc]` quietly leave a customer's own website with no
            # eligible provider -- turning a frozen rule into a config option by
            # omission, which is the subtler half of the same mistake as
            # deleting an entry from `direct.classes`.
            ordered = list(self.providers.values())
            return [p for p in ordered if p.exposes_origin_ip and self._serves(p, request_class)]

        ordered = [self.providers[name] for name in self.ladder]

        if self.policy is Policy.DIRECT_ONLY:
            ordered = [p for p in ordered if p.exposes_origin_ip]
        elif self.policy is Policy.PROXY_ONLY:
            ordered = [p for p in ordered if not p.exposes_origin_ip]

        return [p for p in ordered if self._serves(p, request_class)]

    def provider_for(self, request_class: str = DEFAULT_REQUEST_CLASS) -> NetworkProvider:
        """The provider a request of this class would use right now.

        Introspection for the health page and the manual guide. It reports the
        first *healthy* eligible provider, so it answers "what would happen"
        rather than "what is configured".
        """
        candidates = self.eligible(request_class)
        for provider in candidates:
            if provider.health().healthy:
                return provider
        if candidates:
            return candidates[0]
        raise EgressExhausted(
            f"no provider is eligible for {request_class!r} traffic under policy "
            f"{self.policy.value!r}",
            action=self.on_pool_exhausted.value,
        )

    def _direct_fallback(self, tried: set[str]) -> NetworkProvider | None:
        """A configured direct provider that the ladder walk did not reach.

        This is what ``degrade_to_direct`` means when the class's own provider
        list contains only proxies. Under ``proxy_only`` it returns nothing:
        that policy says the operator's address must not be used, and an
        exhaustion setting does not override an eligibility rule.
        """
        if self.policy is Policy.PROXY_ONLY:
            return None
        for provider in self.providers.values():
            if provider.exposes_origin_ip and provider.name not in tried:
                return provider
        return None

    # -------------------------------------------------------------- acquire

    def acquire(
        self,
        request_class: str = DEFAULT_REQUEST_CLASS,
        *,
        session_key: str | None = None,
        exclude: set[str] | None = None,
    ) -> Lease:
        """A lease for one request, walking the ladder until something serves it."""
        candidates = self.eligible(request_class)
        if not candidates:
            raise EgressExhausted(
                f"no provider is eligible for {request_class!r} traffic under policy "
                f"{self.policy.value!r}",
                action=self.on_pool_exhausted.value,
            )

        excluded = set(exclude or set())
        failed_from: str | None = None
        last_reason = "no provider was usable"
        tried_providers: set[str] = set()

        for provider in candidates:
            tried_providers.add(provider.name)
            health = provider.health()
            if not health.healthy:
                last_reason = health.reason or "unhealthy"
                failed_from = failed_from or provider.name
                continue
            try:
                lease = provider.acquire(session_key=session_key, exclude=excluded)
            except ProviderUnavailable as exc:
                last_reason = str(exc)
                failed_from = failed_from or provider.name
                continue

            if failed_from is not None and failed_from != provider.name:
                self._note(request_class, failed_from, provider.name, last_reason)
            return lease

        fallback = self._direct_fallback(tried_providers)
        if self.on_pool_exhausted is OnPoolExhausted.DEGRADE_TO_DIRECT and fallback is not None:
            if fallback.health().healthy:
                try:
                    lease = fallback.acquire(session_key=session_key, exclude=excluded)
                except ProviderUnavailable as exc:
                    last_reason = str(exc)
                else:
                    self._note(
                        request_class, failed_from or "proxy pool", fallback.name, last_reason
                    )
                    return lease
            else:
                last_reason = fallback.health().reason or last_reason

        raise EgressExhausted(
            f"every eligible provider for {request_class!r} traffic is unavailable "
            f"({last_reason}). Policy {self.policy.value!r}, "
            f"on_pool_exhausted {self.on_pool_exhausted.value!r}.",
            action=self.on_pool_exhausted.value,
        )

    def release(
        self,
        lease: Lease,
        *,
        outcome: Outcome,
        status: int | None = None,
        latency_ms: float = 0.0,
        bytes_in: int = 0,
    ) -> None:
        provider = self.providers.get(lease.provider)
        if provider is None:  # pragma: no cover - a lease names a live provider
            return
        provider.release(
            lease, outcome=outcome, status=status, latency_ms=latency_ms, bytes_in=bytes_in
        )

    # ----------------------------------------------------------- degradation

    def _note(self, request_class: str, from_provider: str, to_provider: str, reason: str) -> None:
        notice = DegradationNotice(request_class, from_provider, to_provider, reason)
        with self._lock:
            if notice.key in self._notices:
                # Once per ladder step, not once per request. A run that
                # degrades four hundred times produces one timeline entry; four
                # hundred identical warnings is an unreadable feed.
                return
            self._notices[notice.key] = notice
        # Logged immediately even though the timeline row waits for the caller
        # to drain: an operator watching the log should not have to wait for a
        # subreddit to finish.
        log.warning("%s", notice.message())

    def drain_notices(self) -> list[DegradationNotice]:
        """Return the degradation notices recorded so far, and clear them.

        Called by the job handler **after** its network work returns, so the
        resulting ``run_events`` write happens outside the window where a dirty
        session would hold SQLite's write lock across a fetch.
        """
        with self._lock:
            notices = list(self._notices.values())
            self._notices.clear()
        return notices

    def peek_notices(self) -> list[DegradationNotice]:
        """Read without clearing — for the health surface."""
        with self._lock:
            return list(self._notices.values())

    # -------------------------------------------------------------- reporting

    def describe(self) -> dict[str, Any]:
        """Operator-facing state. Contains no credential, by construction."""
        return {
            "policy": self.policy.value,
            "ladder": list(self.ladder),
            "on_pool_exhausted": self.on_pool_exhausted.value,
            "direct_classes": sorted(self.direct_classes),
            "providers": [self.providers[name].describe() for name in self.ladder],
            "routing": {
                request_class.value: self._routing_name(request_class.value)
                for request_class in RequestClass
            },
        }

    def _routing_name(self, request_class: str) -> str | None:
        try:
            return self.provider_for(request_class).name
        except EgressExhausted:
            return None

    @property
    def direct_provider(self) -> DirectProvider | None:
        for provider in self.providers.values():
            if isinstance(provider, DirectProvider):
                return provider
        return None

    @property
    def pool(self):
        """The first datacenter pool, or ``None``.

        The health page and several tests were written against a single
        ``ProxyManager`` and still ask for one. Exposing it as a view keeps
        those readers working without giving them a second source of truth.
        """
        for provider in self.providers.values():
            if isinstance(provider, WebshareDatacenterProvider):
                return provider.manager
        return None


# ---------------------------------------------------------------- construction


def _classes_of(spec: dict[str, Any]) -> set[str] | None:
    raw = spec.get("classes")
    if raw is None:
        return None
    return {str(item) for item in raw}


def build_policy_from_config(config: dict | None, *, secret_lookup=None) -> NetworkPolicy:
    """Build from ``config.yaml``.

    With no ``network:`` block this falls back to the legacy ``proxy:`` block and
    reproduces the pre-P4 arrangement exactly, so an installation upgrading from
    P3 keeps working without editing a file. That fallback is the second rollback
    level in ``docs/34`` P4.
    """
    config = config or {}
    network = config.get("network") or {}
    if not network:
        return _legacy_policy(config, secret_lookup=secret_lookup)

    specs = list(network.get("providers") or [])
    if not specs:
        return _legacy_policy(config, secret_lookup=secret_lookup)

    direct_config = network.get("direct") or {}
    declared_direct = _classes_of(direct_config) or set()
    missing = ALWAYS_DIRECT - declared_direct
    if declared_direct and missing:
        # R18 is architecture. Report the attempt loudly and keep the rule --
        # silently honouring it would let a config edit disable a freeze rule,
        # and silently ignoring it would leave the operator believing otherwise.
        log.warning(
            "network.direct.classes omits %s; these are always direct (R18) and the "
            "omission is ignored",
            ", ".join(sorted(missing)),
        )

    providers: list[NetworkProvider] = []
    classes_by_provider: dict[str, set[str]] = {}
    for spec in specs:
        provider = build_provider(spec, secret_lookup=secret_lookup)
        providers.append(provider)
        classes = _classes_of(spec)
        if classes is not None:
            classes_by_provider[provider.name] = classes

    return NetworkPolicy(
        providers,
        policy=str(network.get("policy", Policy.PREFER_PROXY.value)),
        ladder=[str(name) for name in (network.get("ladder") or [])] or None,
        on_pool_exhausted=str(
            network.get("on_pool_exhausted", OnPoolExhausted.DEGRADE_TO_DIRECT.value)
        ),
        classes_by_provider=classes_by_provider,
        direct_classes=declared_direct,
    )


def _legacy_policy(config: dict, *, secret_lookup=None) -> NetworkPolicy:
    """The pre-P4 arrangement, expressed as a policy.

    One datacenter pool plus a direct connection, proxy first --  which is what
    ``ProxiedHTTPClient`` did before this phase. ``proxy.fail_closed`` maps onto
    the two-value question it always really was: stop, or continue direct.
    """
    proxy_config = config.get("proxy") or {}
    enabled = bool(proxy_config.get("enabled", True))
    proxy_file = proxy_config.get("file") or None
    if not proxy_file and secret_lookup is not None:
        proxy_file = secret_lookup("PROXY_FILE")

    providers: list[NetworkProvider] = []
    ladder: list[str] = []
    if enabled and proxy_file:
        providers.append(
            build_provider(
                {
                    "name": "dc",
                    "type": "managed_list",
                    "file": proxy_file,
                    "delay_min": proxy_config.get("delay_min", 3.0),
                    "delay_max": proxy_config.get("delay_max", 7.0),
                    "blacklist_threshold": proxy_config.get("blacklist_threshold", 3),
                    "blacklist_cooldown": proxy_config.get("blacklist_cooldown", 900.0),
                },
                secret_lookup=secret_lookup or (lambda _name: None),
            )
        )
        ladder.append("dc")

    providers.append(DirectProvider("direct"))
    ladder.append("direct")

    pool = next((p for p in providers if not p.exposes_origin_ip), None)
    has_pool = pool is not None and pool.capacity().usable_exits > 0
    fail_closed = bool(proxy_config.get("fail_closed", True)) and has_pool

    return NetworkPolicy(
        providers,
        policy=Policy.PROXY_ONLY.value if fail_closed else Policy.PREFER_PROXY.value,
        ladder=ladder,
        on_pool_exhausted=(
            OnPoolExhausted.FAIL_RUN.value
            if fail_closed
            else OnPoolExhausted.DEGRADE_TO_DIRECT.value
        ),
    )


def build_legacy_policy(manager) -> NetworkPolicy:
    """Express an already-built :class:`ProxyManager` as a policy.

    The compatibility path: ``ProxiedHTTPClient(pool)`` still works, and behaves
    as it did before P4. ``fail_closed`` was always the two-value form of one
    question -- *when the pool is empty, stop or continue direct?* -- so it maps
    onto ``policy`` and ``on_pool_exhausted`` without inventing anything:

    ===============================  ==================  =====================
    ``fail_closed`` (with a pool)    ``policy``          ``on_pool_exhausted``
    ===============================  ==================  =====================
    ``True``                         ``proxy_only``      ``fail_run``
    ``False`` / no pool              ``prefer_proxy``    ``degrade_to_direct``
    ===============================  ==================  =====================
    """
    providers: list[NetworkProvider] = []
    ladder: list[str] = []

    if manager is not None and manager.endpoints:
        providers.append(WebshareDatacenterProvider("dc", manager))
        ladder.append("dc")

    providers.append(DirectProvider("direct"))
    ladder.append("direct")

    fail_closed = bool(manager is not None and manager.fail_closed and manager.endpoints)

    return NetworkPolicy(
        providers,
        policy=Policy.PROXY_ONLY.value if fail_closed else Policy.PREFER_PROXY.value,
        ladder=ladder,
        on_pool_exhausted=(
            OnPoolExhausted.FAIL_RUN.value
            if fail_closed
            else OnPoolExhausted.DEGRADE_TO_DIRECT.value
        ),
        # No class restrictions: the pre-P4 client sent everything the same way,
        # and this path exists to reproduce that. ALWAYS_DIRECT still applies --
        # it is architecture, and no caller in P4 uses those classes anyway.
        classes_by_provider=None,
    )


def build_policy_from_settings(settings) -> NetworkPolicy:
    """Build from the settings resolver, for the dashboard's process-wide policy."""
    yaml_config = getattr(settings, "yaml_config", None) or {}
    return build_policy_from_config(yaml_config, secret_lookup=settings.get_secret)
