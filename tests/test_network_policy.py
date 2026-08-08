"""P4: ``NetworkPolicy`` — egress chosen per request class, with a ladder.

Offline. Providers are real classes with unreachable endpoints, or deliberate
failures; nothing dials out.

The two properties these tests exist for:

* **R18** — RSS, health and website are direct under *every* policy. Frozen
  architecture, so the test that matters most is the one that tries hardest to
  route them elsewhere.
* **The ladder degrades, visibly.** A degradation that nobody can see is the
  unbounded silent fallback ``docs/08`` §7 rejected.
"""

from __future__ import annotations

import pytest

from src.net.policy import (
    ALWAYS_DIRECT,
    DegradationNotice,
    EgressExhausted,
    NetworkPolicy,
    OnPoolExhausted,
    Policy,
    RequestClass,
    build_legacy_policy,
    build_policy_from_config,
)
from src.net.providers import (
    DirectProvider,
    NullProvider,
    Outcome,
    ProviderUnavailable,
    WebshareDatacenterProvider,
)
from src.net.proxy_manager import ProxyManager
from src.net.proxy_models import ProxyEndpoint

BULK = [RequestClass.HTML.value, RequestClass.COMMENTS.value, RequestClass.VALIDATION.value]
PROXY_CLASSES = set(BULK)
ALL_CLASSES = [c.value for c in RequestClass]


def _endpoint(host="203.0.113.10") -> ProxyEndpoint:
    return ProxyEndpoint(host, 8080, "user", "pass")


def _pool(*hosts, **kwargs) -> ProxyManager:
    kwargs.setdefault("delay_range", (0.0, 0.0))
    return ProxyManager([_endpoint(h) for h in (hosts or ("203.0.113.10",))], **kwargs)


def _dead_pool() -> ProxyManager:
    """A pool whose every proxy is blacklisted -- the exhaustion case."""
    pool = _pool("203.0.113.10", "203.0.113.11", blacklist_threshold=1)
    for endpoint in pool.endpoints:
        pool.record_failure(endpoint, "blocked", blocked=True)
    return pool


def _policy(*, pool=None, **kwargs) -> NetworkPolicy:
    providers = [DirectProvider("direct"), WebshareDatacenterProvider("dc", pool or _pool())]
    kwargs.setdefault("ladder", ["direct", "dc"])
    kwargs.setdefault("classes_by_provider", {"direct": set(ALL_CLASSES), "dc": set(PROXY_CLASSES)})
    kwargs.setdefault("direct_classes", set(ALWAYS_DIRECT))
    return NetworkPolicy(providers, **kwargs)


# ------------------------------------------------------- R18: always direct


class TestAlwaysDirectClasses:
    """R18. Not a preference — a frozen rule, and these tests try to break it."""

    @pytest.mark.parametrize("request_class", sorted(ALWAYS_DIRECT))
    @pytest.mark.parametrize(
        "policy", [Policy.DIRECT_ONLY.value, Policy.PREFER_PROXY.value, Policy.PROXY_ONLY.value]
    )
    def test_they_are_direct_under_every_policy(self, request_class, policy):
        assert _policy(policy=policy).provider_for(request_class).name == "direct"

    def test_they_are_direct_even_when_direct_is_absent_from_the_ladder(self):
        """The hardest case: the strictest policy, and the ladder does not name
        the direct provider at all. A customer's own website must *still* not be
        crawled from ten rotating datacenter IPs."""
        policy = _policy(policy=Policy.PROXY_ONLY.value, ladder=["dc"])
        for request_class in sorted(ALWAYS_DIRECT):
            assert policy.provider_for(request_class).name == "direct"

    def test_removing_one_from_the_config_list_is_ignored_not_honoured(self, caplog):
        """An operator cannot switch off a freeze rule by editing a list — and
        must be told, rather than left believing they did."""
        import logging

        config = _config(direct_classes=["health", "website"])
        with caplog.at_level(logging.WARNING):
            policy = build_policy_from_config(config, secret_lookup=lambda _n: None)
        assert policy.provider_for(RequestClass.RSS.value).name == "direct"
        assert "rss" in caplog.text and "R18" in caplog.text

    def test_the_frozen_set_is_exactly_the_three_named_in_the_architecture(self):
        assert {"rss", "health", "website"} == ALWAYS_DIRECT


# ------------------------------------------------------------ class routing


class TestRequestClassRouting:
    def test_bulk_classes_follow_the_ladder(self):
        assert _policy(ladder=["direct", "dc"]).provider_for("html").name == "direct"
        assert _policy(ladder=["dc", "direct"]).provider_for("html").name == "dc"

    def test_proxy_only_never_routes_bulk_to_the_direct_provider(self):
        policy = _policy(policy=Policy.PROXY_ONLY.value, ladder=["direct", "dc"])
        for request_class in BULK:
            assert policy.provider_for(request_class).name == "dc"

    def test_direct_only_never_routes_anything_to_a_proxy(self):
        policy = _policy(policy=Policy.DIRECT_ONLY.value, ladder=["dc", "direct"])
        for request_class in ALL_CLASSES:
            assert policy.provider_for(request_class).name == "direct"

    def test_a_provider_only_serves_the_classes_it_declares(self):
        policy = _policy(
            ladder=["dc", "direct"],
            classes_by_provider={"dc": {"html"}, "direct": set(ALL_CLASSES)},
        )
        assert policy.provider_for("html").name == "dc"
        assert policy.provider_for("comments").name == "direct"

    def test_provider_for_reports_what_would_happen_not_what_is_configured(self):
        """It skips unhealthy rungs, because an operator asking "where does this
        go" means "right now", not "in principle"."""
        policy = _policy(pool=_dead_pool(), ladder=["dc", "direct"])
        assert policy.provider_for("html").name == "direct"


# ---------------------------------------------------------------- the ladder


class TestLadderDegradation:
    def test_it_steps_to_the_next_rung_when_the_first_is_exhausted(self):
        policy = _policy(pool=_dead_pool(), ladder=["dc", "direct"])
        assert policy.acquire("html").provider == "direct"

    def test_stepping_records_a_notice_naming_both_ends(self):
        policy = _policy(pool=_dead_pool(), ladder=["dc", "direct"])
        policy.acquire("html")
        notices = policy.drain_notices()
        assert len(notices) == 1
        assert (notices[0].from_provider, notices[0].to_provider) == ("dc", "direct")
        assert "dc" in notices[0].message() and "direct" in notices[0].message()

    def test_a_notice_is_recorded_once_per_ladder_step_not_once_per_request(self):
        """AS-7. Four hundred identical warnings is an unreadable timeline."""
        policy = _policy(pool=_dead_pool(), ladder=["dc", "direct"])
        for _ in range(20):
            policy.acquire("html")
        assert len(policy.drain_notices()) == 1

    def test_draining_clears_so_the_next_job_reports_only_its_own(self):
        policy = _policy(pool=_dead_pool(), ladder=["dc", "direct"])
        policy.acquire("html")
        assert policy.drain_notices()
        assert policy.drain_notices() == []

    def test_peeking_does_not_clear(self):
        """The health page reads; only a job handler consumes. A page that drained
        would steal the run timeline's entry."""
        policy = _policy(pool=_dead_pool(), ladder=["dc", "direct"])
        policy.acquire("html")
        assert policy.peek_notices()
        assert policy.peek_notices()
        assert len(policy.drain_notices()) == 1

    def test_no_notice_when_the_first_rung_serves(self):
        policy = _policy(ladder=["dc", "direct"])
        policy.acquire("html")
        assert policy.drain_notices() == []


# ------------------------------------------------------- on_pool_exhausted


class TestOnPoolExhausted:
    """The three values must behave differently, or the setting is decorative."""

    def _exhausted(self, action: str) -> NetworkPolicy:
        return _policy(
            pool=_dead_pool(),
            policy=Policy.PROXY_ONLY.value,
            ladder=["dc"],
            on_pool_exhausted=action,
        )

    def test_degrade_to_direct_continues_when_direct_is_eligible(self):
        policy = _policy(
            pool=_dead_pool(),
            ladder=["dc"],
            classes_by_provider={"dc": set(PROXY_CLASSES), "direct": set(ALL_CLASSES)},
            on_pool_exhausted=OnPoolExhausted.DEGRADE_TO_DIRECT.value,
        )
        assert policy.acquire("html").provider == "direct"
        assert policy.drain_notices()

    def test_degrade_to_direct_does_not_override_proxy_only(self):
        """``proxy_only`` says the operator's address must not be used. An
        exhaustion setting is not permitted to overrule an eligibility rule."""
        with pytest.raises(EgressExhausted) as excinfo:
            self._exhausted(OnPoolExhausted.DEGRADE_TO_DIRECT.value).acquire("html")
        assert excinfo.value.action == OnPoolExhausted.DEGRADE_TO_DIRECT.value

    def test_pause_run_is_retryable(self):
        with pytest.raises(EgressExhausted) as excinfo:
            self._exhausted(OnPoolExhausted.PAUSE_RUN.value).acquire("html")
        assert excinfo.value.retryable is True

    def test_fail_run_is_not_retryable(self):
        with pytest.raises(EgressExhausted) as excinfo:
            self._exhausted(OnPoolExhausted.FAIL_RUN.value).acquire("html")
        assert excinfo.value.retryable is False

    def test_the_three_are_genuinely_distinguishable(self):
        outcomes = {}
        for action in (a.value for a in OnPoolExhausted):
            try:
                provider = self._exhausted(action).acquire("html").provider
                outcomes[action] = ("served", provider)
            except EgressExhausted as exc:
                outcomes[action] = ("raised", exc.retryable)
        assert outcomes[OnPoolExhausted.PAUSE_RUN.value] != outcomes[OnPoolExhausted.FAIL_RUN.value]

    def test_exhaustion_is_still_a_proxy_exhausted_error(self):
        """Every pre-P4 handler catches that type. A new sibling would silently
        bypass both ``ProxiedHTTPClient`` and ``RedditClient``."""
        from src.net.retry import ProxyExhaustedError

        with pytest.raises(ProxyExhaustedError):
            self._exhausted(OnPoolExhausted.FAIL_RUN.value).acquire("html")

    def test_the_message_names_the_policy_so_it_is_diagnosable(self):
        with pytest.raises(EgressExhausted) as excinfo:
            self._exhausted(OnPoolExhausted.FAIL_RUN.value).acquire("html")
        message = str(excinfo.value)
        assert "proxy_only" in message and "fail_run" in message


# ------------------------------------------------------------------ bandwidth


class TestMeteredProviderDegrades:
    def test_a_provider_under_its_bandwidth_floor_is_skipped(self):
        """N-AC7. It reports unhealthy *before* the vendor starts refusing, so a
        run degrades rather than looking like a network outage."""
        from src.net.providers import ManagedProxyProvider

        gateway = ManagedProxyProvider(
            "resi",
            gateway="gw.example.com:7000",
            username="u",
            password="p",
            bandwidth_budget_gb=0.001,
            bandwidth_floor_gb=0.0005,
        )
        policy = NetworkPolicy(
            [gateway, DirectProvider("direct")],
            ladder=["resi", "direct"],
        )
        assert policy.acquire("html").provider == "resi"

        gateway.release(gateway.acquire(), outcome=Outcome.OK, bytes_in=700_000)

        assert policy.acquire("html").provider == "direct"
        assert policy.drain_notices()[0].to_provider == "direct"


# --------------------------------------------------------------- leak safety


class TestLeakRemainsFatal:
    def test_the_ladder_does_not_swallow_a_leak(self):
        """RK-6. ``ProxyLeakError`` is fatal by design: continuing after learning
        that traffic is not actually proxied would silently violate the one
        guarantee the pool exists to provide. The ladder catches
        ``ProviderUnavailable`` only, so anything else propagates."""

        class LeakingProvider(DirectProvider):
            type = "leaky"
            exposes_origin_ip = False

            def acquire(self, *, session_key=None, exclude=None):
                raise ProxyLeakError("exit IP equals the local address")

        policy = NetworkPolicy(
            [LeakingProvider("leaky"), DirectProvider("direct")],
            ladder=["leaky", "direct"],
        )
        with pytest.raises(ProxyLeakError):
            policy.acquire("html")

    def test_a_provider_unavailable_is_the_only_thing_that_steps_the_ladder(self):
        assert issubclass(ProviderUnavailable, Exception)
        assert not issubclass(ProxyLeakError, ProviderUnavailable)


class ProxyLeakError(RuntimeError):
    """Stand-in for the fatal leak condition, which has no shipped raiser yet.

    ``ProxyManager.local_ip_leaked`` reports leaks and the health endpoint
    surfaces them; nothing raises today. This asserts the *ladder's* contract --
    that it steps on ``ProviderUnavailable`` and on nothing else -- so whenever a
    raiser is added it cannot be silently absorbed.
    """


# ----------------------------------------------------------------- config


def _config(*, policy="prefer_proxy", ladder=None, direct_classes=None, on_exhausted=None):
    return {
        "network": {
            "policy": policy,
            "direct": {
                "enabled": True,
                "max_requests_per_hour": 120,
                "classes": direct_classes if direct_classes is not None else list(ALWAYS_DIRECT),
            },
            "providers": [
                {"name": "direct", "type": "direct", "classes": ALL_CLASSES},
                {
                    "name": "dc",
                    "type": "managed_list",
                    "allow_empty": True,
                    "classes": sorted(PROXY_CLASSES),
                },
            ],
            "ladder": ladder or ["direct", "dc"],
            "on_pool_exhausted": on_exhausted or "degrade_to_direct",
        }
    }


class TestBuildFromConfig:
    def test_the_shipped_config_yaml_builds_and_routes_correctly(self):
        """Not a synthetic block: the file that actually ships."""
        from src.config import load_config

        policy = build_policy_from_config(load_config(), secret_lookup=lambda _n: None)
        assert policy.policy is Policy.PREFER_PROXY
        assert policy.ladder == ["direct", "dc"]
        assert policy.on_pool_exhausted is OnPoolExhausted.DEGRADE_TO_DIRECT
        for request_class in sorted(ALWAYS_DIRECT):
            assert policy.provider_for(request_class).name == "direct"

    def test_ladder_order_is_honoured_independently_of_policy(self):
        """D-A/A1: policy decides eligibility, ladder decides order. If the enum
        decided order, re-measuring would be a code change."""
        forward = build_policy_from_config(
            _config(ladder=["direct", "dc"]), secret_lookup=lambda _n: None
        )
        reverse = build_policy_from_config(
            _config(ladder=["dc", "direct"]), secret_lookup=lambda _n: None
        )
        assert forward.ladder == ["direct", "dc"]
        assert reverse.ladder == ["dc", "direct"]

    def test_an_unknown_ladder_name_is_dropped_rather_than_crashing(self):
        policy = build_policy_from_config(
            _config(ladder=["typo", "direct"]), secret_lookup=lambda _n: None
        )
        assert policy.ladder == ["direct"]

    def test_no_network_block_falls_back_to_the_legacy_proxy_block(self):
        """AS-6. An installation upgrading from P3 keeps working without editing
        a file, which is also the second rollback level."""
        policy = build_policy_from_config(
            {"proxy": {"enabled": True, "fail_closed": True, "file": None}},
            secret_lookup=lambda _n: None,
        )
        assert policy.provider_for("html").name == "direct"

    def test_an_empty_config_yields_a_working_direct_policy(self):
        policy = build_policy_from_config({}, secret_lookup=lambda _n: None)
        assert policy.provider_for("html").name == "direct"


class TestLegacyPolicyReproducesPreP4Behaviour:
    def test_fail_closed_with_a_pool_is_proxy_only_and_fail_run(self):
        policy = build_legacy_policy(_pool(fail_closed=True))
        assert policy.policy is Policy.PROXY_ONLY
        assert policy.on_pool_exhausted is OnPoolExhausted.FAIL_RUN

    def test_fail_open_with_a_pool_degrades_to_direct(self):
        policy = build_legacy_policy(_pool(fail_closed=False))
        assert policy.policy is Policy.PREFER_PROXY
        assert policy.on_pool_exhausted is OnPoolExhausted.DEGRADE_TO_DIRECT

    def test_no_pool_at_all_still_scrapes(self):
        """A machine that was never given a proxy file must keep working —
        `python main.py scrape` depends on it."""
        policy = build_legacy_policy(None)
        assert policy.acquire("html").provider == "direct"

    def test_a_fail_closed_pool_that_is_dead_raises_rather_than_using_our_address(self):
        policy = build_legacy_policy(_dead_pool_with_fail_closed())
        with pytest.raises(EgressExhausted):
            policy.acquire("html")


def _dead_pool_with_fail_closed() -> ProxyManager:
    pool = _pool("203.0.113.10", blacklist_threshold=1, fail_closed=True)
    pool.record_failure(pool.endpoints[0], "blocked", blocked=True)
    return pool


# ------------------------------------------------------------------ release


class TestRelease:
    def test_it_reaches_the_provider_that_issued_the_lease(self):
        pool = _pool()
        policy = _policy(pool=pool, ladder=["dc", "direct"])
        lease = policy.acquire("html")
        policy.release(lease, outcome=Outcome.OK, status=200, latency_ms=10, bytes_in=1234)
        assert pool.stats_for(pool.endpoints[0]).target_ok == 1

    def test_describe_is_credential_free_and_complete(self):
        payload = _policy().describe()
        assert set(payload) == {
            "policy",
            "ladder",
            "on_pool_exhausted",
            "direct_classes",
            "providers",
            "routing",
        }
        assert "pass" not in str(payload).lower().replace("password", "")


class TestNoticeValueObject:
    def test_the_dedup_key_is_the_ladder_step(self):
        first = DegradationNotice("html", "dc", "direct", "exhausted")
        second = DegradationNotice("comments", "dc", "direct", "different reason")
        assert first.key == second.key

    def test_it_carries_no_session_and_no_run_id(self):
        """The reason the network layer can report degradation without touching
        SQLite — see ``PHASE-03-COMPLETION-REPORT`` §5.0."""
        notice = DegradationNotice("html", "dc", "direct", "exhausted")
        assert set(notice.as_data()) == {
            "request_class",
            "from_provider",
            "to_provider",
            "reason",
        }


class TestTheProcessWidePolicy:
    """P-2. The governor and the blacklist are budgets over a *machine*.

    ``handle_scrape_subreddit`` builds a scraper per job. If each built its own
    policy, twelve subreddits would get twelve independent 120-request
    allowances -- the frozen budget enforced at 12x -- and each would start with
    an empty blacklist, re-learning the same dead proxies twelve times.
    """

    def test_every_caller_resolves_the_same_policy(self):
        from src.net.egress import get_policy, reset_policy

        reset_policy()
        try:
            assert get_policy({}) is get_policy({})
        finally:
            reset_policy()

    def test_two_clients_built_the_production_way_share_one_governor(self):
        from src.net.egress import reset_policy
        from src.reddit_client import RedditClient

        reset_policy()
        try:
            first, second = RedditClient({}).http, RedditClient({}).http
            assert first.policy is second.policy

            direct = first.policy.direct_provider
            before = direct.requests_this_hour
            first.policy.acquire(RequestClass.HTML.value)
            assert second.policy.direct_provider.requests_this_hour == before + 1
        finally:
            reset_policy()

    def test_a_scraper_rebuilt_per_job_does_not_reset_the_hourly_budget(self):
        """The failure this exists to prevent, stated as the operator would see
        it: a cap of N enforced N-times-per-run instead of once."""
        from src.net.egress import get_policy, reset_policy
        from src.orchestration.handlers.scrape import build_scraper

        reset_policy()
        try:
            policy = get_policy({})
            policy.direct_provider.max_requests_per_hour = 2

            build_scraper({})
            policy.acquire(RequestClass.HTML.value)
            build_scraper({})
            policy.acquire(RequestClass.HTML.value)

            with pytest.raises(EgressExhausted):
                get_policy().acquire(RequestClass.HTML.value)
        finally:
            reset_policy()

    def test_a_broken_provider_block_degrades_rather_than_stopping_the_tool(self):
        """An operator typo in one provider must not make the app unstartable."""
        from src.net.egress import get_policy, policy_error, reset_policy

        reset_policy()
        try:
            policy = get_policy({"network": {"providers": [{"name": "x", "type": "wormhole"}]}})
            assert policy.provider_for("html").name == "direct"
            assert "wormhole" in (policy_error() or "")
        finally:
            reset_policy()


class TestNullProviderInAPolicy:
    def test_a_class_routed_to_null_cannot_reach_the_network(self):
        policy = NetworkPolicy(
            [NullProvider("none"), DirectProvider("direct")],
            ladder=["none"],
            classes_by_provider={"none": {"html"}, "direct": set()},
            on_pool_exhausted=OnPoolExhausted.FAIL_RUN.value,
        )
        with pytest.raises(EgressExhausted):
            policy.acquire("html")
