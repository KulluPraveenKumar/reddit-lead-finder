"""P4: the four egress providers, and the registry that builds them from config.

Offline by construction. No provider here dials anything: the datacenter pool is
given endpoints that are never contacted, the gateway is never connected to, and
``DirectProvider``'s session is inspected rather than used.

The credential strings are distinctive so a substring check is meaningful. They
must not appear in a repr, a describe(), a log line or an API response.
"""

from __future__ import annotations

import logging

import pytest

from src.net.policy import RequestClass
from src.net.providers import (
    DirectProvider,
    ManagedProxyProvider,
    NullProvider,
    Outcome,
    ProviderConfigError,
    ProviderUnavailable,
    WebshareDatacenterProvider,
    build_provider,
    provider_types,
)
from src.net.proxy_manager import ProxyManager
from src.net.proxy_models import ProxyEndpoint
from src.net.user_agents import PROFILES

GATEWAY_USER = "gwuser7x"
GATEWAY_PASS = "GatewayP4ss-zz9"
LIST_USER = "listuser3q"
LIST_PASS = "ListP4ss-kk1"


def _endpoint(host="203.0.113.10", port=8080) -> ProxyEndpoint:
    return ProxyEndpoint(host, port, LIST_USER, LIST_PASS)


def _pool(*hosts, **kwargs) -> ProxyManager:
    endpoints = [_endpoint(h) for h in (hosts or ("203.0.113.10",))]
    kwargs.setdefault("delay_range", (0.0, 0.0))
    return ProxyManager(endpoints, **kwargs)


def _gateway(**overrides) -> ManagedProxyProvider:
    spec = {
        "name": "resi",
        "type": "managed_gateway",
        "gateway": "gw.example.com:7000",
        "username": GATEWAY_USER,
        "password": GATEWAY_PASS,
        "session_param": "-session-{key}",
        "metered": True,
        "bandwidth_budget_gb": 1.0,
        "bandwidth_floor_gb": 0.05,
    }
    spec.update(overrides)
    return ManagedProxyProvider.from_config(spec["name"], spec)


# ------------------------------------------------------------------- the ABC


class TestProviderContract:
    def test_every_registered_type_implements_the_whole_interface(self):
        """A provider missing a method would fail at the worst moment: mid-run,
        on the degradation path, which is the path nobody exercises by hand."""
        for name in provider_types():
            cls = build_provider(_minimal_spec(name)).__class__
            for method in ("acquire", "release", "health", "capacity", "from_config"):
                assert callable(getattr(cls, method)), f"{name} is missing {method}"

    def test_capability_flags_default_to_the_safe_answer(self):
        """``exposes_origin_ip`` defaulting to True would silently mark a proxy as
        revealing the operator's address, and the policy reasons on that flag."""
        for name in provider_types():
            provider = build_provider(_minimal_spec(name))
            if name != "direct":
                assert provider.exposes_origin_ip is False, name

    def test_only_the_direct_provider_exposes_the_origin_ip(self):
        assert DirectProvider("direct").exposes_origin_ip is True
        assert WebshareDatacenterProvider("dc", _pool()).exposes_origin_ip is False
        assert _gateway().exposes_origin_ip is False
        assert NullProvider("none").exposes_origin_ip is False


def _minimal_spec(type_name: str) -> dict:
    base = {"name": f"p-{type_name}", "type": type_name}
    if type_name == "managed_list":
        base["allow_empty"] = True
    if type_name == "managed_gateway":
        base.update({"gateway": "gw.example.com:7000", "username": "u", "password": "p"})
    return base


# ------------------------------------------------------------------- registry


class TestRegistryBuildsFromConfig:
    """N-AC6. Swapping vendor must be a config change, never a code change."""

    def test_all_four_types_construct(self):
        assert provider_types() == [
            "direct",
            "managed_gateway",
            "managed_list",
            "null_provider",
        ]
        for name in provider_types():
            assert build_provider(_minimal_spec(name)).type == name

    def test_five_config_blocks_across_four_classes(self):
        """The Metrics row says "all 5 types"; there are four classes and five
        blocks -- residential is ``managed_gateway`` pointed at a different
        vendor, which is precisely the economy the design claims."""
        blocks = [
            {"name": "direct", "type": "direct"},
            {"name": "dc", "type": "managed_list", "allow_empty": True},
            {
                "name": "resi",
                "type": "managed_gateway",
                "gateway": "p.webshare.io:80",
                "username": "u",
                "password": "p",
            },
            {
                "name": "resi2",
                "type": "managed_gateway",
                "gateway": "gate.decodo.com:7000",
                "username": "u",
                "password": "p",
                "session_param": "-sessid-{key}",
            },
            {"name": "none", "type": "null_provider"},
        ]
        built = [build_provider(b) for b in blocks]
        assert [p.name for p in built] == ["direct", "dc", "resi", "resi2", "none"]
        assert sum(1 for p in built if p.type == "managed_gateway") == 2

    def test_switching_vendor_is_four_lines_of_yaml(self):
        webshare = _gateway(gateway="p.webshare.io:80", session_param="-session-{key}")
        iproyal = _gateway(gateway="geo.iproyal.com:12321", session_param="_session-{key}")
        assert webshare.__class__ is iproyal.__class__
        assert webshare.label_for("s") != iproyal.label_for("s")

    def test_env_references_are_resolved(self):
        provider = build_provider(
            {
                "name": "resi",
                "type": "managed_gateway",
                "gateway": "gw.example.com:7000",
                "username": "${PROXY_USER}",
                "password": "${PROXY_PASS}",
            },
            secret_lookup={"PROXY_USER": GATEWAY_USER, "PROXY_PASS": GATEWAY_PASS}.get,
        )
        assert GATEWAY_PASS not in repr(provider)
        assert provider.acquire().proxies["https"].startswith("http://")

    def test_unknown_type_is_a_readable_error_not_a_keyerror(self):
        with pytest.raises(ProviderConfigError) as excinfo:
            build_provider({"name": "x", "type": "wormhole"})
        message = str(excinfo.value)
        assert "wormhole" in message
        assert "managed_gateway" in message, "the error must list what IS valid"

    def test_bare_yaml_null_is_explained_rather_than_reported_as_missing(self):
        """``type: null`` parses as None. An operator who typed something and is
        told the key is absent will not find the problem."""
        with pytest.raises(ProviderConfigError) as excinfo:
            build_provider({"name": "x", "type": None})
        assert "null_provider" in str(excinfo.value)

    def test_a_gateway_without_credentials_is_rejected(self):
        with pytest.raises(ProviderConfigError) as excinfo:
            build_provider(
                {"name": "resi", "type": "managed_gateway", "gateway": "gw.example.com:7000"}
            )
        assert "config.yaml is committed" in str(excinfo.value)


# --------------------------------------------------------------------- direct


class TestDirectProvider:
    def test_the_governor_permits_n_and_refuses_n_plus_one(self):
        provider = DirectProvider("direct", max_requests_per_hour=3)
        for _ in range(3):
            provider.acquire()
        assert provider.requests_this_hour == 3
        with pytest.raises(ProviderUnavailable) as excinfo:
            provider.acquire()
        assert "3 of 3" in str(excinfo.value)

    def test_reaching_the_cap_reports_unhealthy_so_the_ladder_can_step(self):
        provider = DirectProvider("direct", max_requests_per_hour=1)
        assert provider.health().healthy
        provider.acquire()
        assert not provider.health().healthy
        assert "hourly limit" in provider.health().reason

    def test_the_window_rolls_rather_than_resetting_on_the_clock_hour(self, monkeypatch):
        """A fixed hourly reset lets 2N requests through in two minutes either
        side of the boundary, which is not a cap."""
        clock = {"t": 1000.0}
        monkeypatch.setattr("src.net.providers.direct.time.monotonic", lambda: clock["t"])
        provider = DirectProvider("direct", max_requests_per_hour=2)
        provider.acquire()
        provider.acquire()
        with pytest.raises(ProviderUnavailable):
            provider.acquire()

        clock["t"] += 3601
        assert provider.requests_this_hour == 0
        provider.acquire()

    def test_the_header_profile_is_whole_and_pinned(self):
        """AS-5. A hand-assembled header set produced a measured 100% block rate
        twice, six days apart. Nothing may hand out one field of a profile."""
        provider = DirectProvider("direct")
        lease = provider.acquire()
        assert lease.profile is provider.profile
        assert lease.profile in PROFILES
        sent = dict(lease.session.headers)
        for key, value in provider.profile.as_dict().items():
            assert sent[key] == value, f"{key} was not sent as the profile defines it"

    def test_the_session_is_reused_so_one_identity_is_presented(self):
        provider = DirectProvider("direct")
        assert provider.acquire().session is provider.acquire().session

    def test_a_lease_carries_no_proxy_configuration(self):
        assert DirectProvider("direct").acquire().proxies is None

    def test_excluding_the_only_exit_leaves_nothing_to_retry(self):
        provider = DirectProvider("direct")
        with pytest.raises(ProviderUnavailable):
            provider.acquire(exclude={"direct"})

    def test_the_governor_counts_requests_issued_not_requests_that_worked(self):
        """It bounds *exposure*. A blocked request reached the target from this
        address just as much as a successful one."""
        provider = DirectProvider("direct", max_requests_per_hour=2)
        lease = provider.acquire()
        provider.release(lease, outcome=Outcome.BLOCKED, status=403)
        assert provider.requests_this_hour == 1


# -------------------------------------------------------------- managed_list


class TestWebshareDatacenterProvider:
    def test_it_adapts_the_shipped_pool_rather_than_replacing_it(self):
        pool = _pool()
        provider = WebshareDatacenterProvider("dc", pool)
        assert provider.acquire().label == "203.0.113.10:8080"
        assert pool.stats_for(pool.endpoints[0]).last_used_at > 0

    def test_release_feeds_the_pool_bookkeeping(self):
        pool = _pool(blacklist_threshold=2)
        provider = WebshareDatacenterProvider("dc", pool)
        for _ in range(2):
            provider.release(provider.acquire(), outcome=Outcome.BLOCKED, status=403)
        assert not provider.health().healthy

    def test_a_successful_release_records_target_acceptance(self):
        pool = _pool()
        provider = WebshareDatacenterProvider("dc", pool)
        provider.release(provider.acquire(), outcome=Outcome.OK, status=200, latency_ms=12)
        assert pool.stats_for(pool.endpoints[0]).target_ok == 1

    def test_it_reports_sticky_as_unsupported_rather_than_ignoring_the_request(self):
        """``docs/12`` §14 records sticky sessions as deliberately not built.
        Accepting a session_key and silently rotating anyway would mislead the
        one caller that eventually needs pinning."""
        assert WebshareDatacenterProvider.supports_sticky is False

    def test_an_empty_pool_is_unavailable_not_a_crash(self):
        provider = WebshareDatacenterProvider("dc", ProxyManager([]))
        assert not provider.health().healthy
        with pytest.raises(ProviderUnavailable):
            provider.acquire()

    def test_a_missing_proxy_file_degrades_to_an_empty_pool(self, caplog):
        """A machine that was never given a proxy file must still scrape."""
        with caplog.at_level(logging.WARNING):
            provider = WebshareDatacenterProvider.from_config(
                "dc", {"file": "C:/definitely/not/here.txt"}
            )
        assert provider.capacity().usable_exits == 0
        assert not provider.health().healthy

    def test_describe_carries_no_credential(self):
        provider = WebshareDatacenterProvider("dc", _pool())
        rendered = str(provider.describe())
        assert LIST_USER not in rendered
        assert LIST_PASS not in rendered


# ----------------------------------------------------------- managed_gateway


class TestManagedProxyProvider:
    def test_the_session_suffix_is_rendered_into_the_username(self):
        provider = _gateway()
        assert provider.username_for("sub-saas") == f"{GATEWAY_USER}-session-sub-saas"
        assert provider.username_for(None) == GATEWAY_USER

    def test_the_same_session_key_yields_the_same_identity(self):
        provider = _gateway()
        first, second = provider.acquire(session_key="a"), provider.acquire(session_key="a")
        assert first.label == second.label
        assert first.session is second.session

    def test_different_session_keys_do_not_share_a_cookie_jar(self):
        provider = _gateway()
        assert (
            provider.acquire(session_key="a").session
            is not provider.acquire(session_key="b").session
        )

    def test_the_proxy_url_tunnels_https_over_an_http_proxy(self):
        """An ``https://`` proxy URL means TLS *to the proxy*, which is the single
        most common misconfiguration with these vendors."""
        proxies = _gateway().acquire().proxies
        assert proxies["http"].startswith("http://")
        assert proxies["https"].startswith("http://")

    def test_bandwidth_is_counted_and_the_floor_stops_the_provider(self):
        """N-AC7. A metered provider that silently runs out mid-run looks exactly
        like a network outage."""
        provider = _gateway(bandwidth_budget_gb=0.001, bandwidth_floor_gb=0.0005)
        assert provider.health().healthy
        lease = provider.acquire()
        provider.release(lease, outcome=Outcome.OK, status=200, bytes_in=700_000)
        assert not provider.health().healthy
        assert "bandwidth floor" in provider.health().reason
        with pytest.raises(ProviderUnavailable):
            provider.acquire()

    def test_bytes_are_counted_on_a_blocked_response_too(self):
        """The vendor bills for a block. Counting only successes would let a run
        of blocks exhaust a plan while the counter reported plenty left."""
        provider = _gateway()
        provider.release(provider.acquire(), outcome=Outcome.BLOCKED, status=403, bytes_in=5_000)
        assert provider.bytes_used == 5_000

    def test_an_unmetered_gateway_reports_unknown_rather_than_zero_remaining(self):
        provider = _gateway(metered=False, bandwidth_budget_gb=None)
        assert provider.capacity().bytes_remaining is None
        assert provider.health().healthy

    def test_credentials_appear_in_no_operator_facing_surface(self):
        """RK-7. This is a NEW credential path: gateway secrets come from config
        and environment, not from the proxy file the P2 guarantees were built
        around."""
        provider = _gateway()
        provider.acquire(session_key="s")
        for rendered in (
            repr(provider),
            str(provider.describe()),
            provider.label_for("s"),
            repr(provider.acquire(session_key="s")),
        ):
            assert GATEWAY_USER not in rendered
            assert GATEWAY_PASS not in rendered

    def test_the_credential_does_exist_where_it_must(self):
        """So the assertions above are provably about redaction and not about a
        provider that simply cannot authenticate."""
        assert GATEWAY_PASS in _gateway().acquire().proxies["https"]

    def test_a_lease_repr_never_prints_its_proxy_configuration(self):
        """Leases travel through exception paths and debug logs, which is exactly
        where a credential escapes."""
        rendered = repr(_gateway().acquire())
        assert GATEWAY_PASS not in rendered
        assert "gw.example.com" in rendered


# ----------------------------------------------------------------------- null


class TestNullProvider:
    def test_it_raises_and_says_what_tried(self):
        with pytest.raises(ProviderUnavailable) as excinfo:
            NullProvider("no-network").acquire()
        assert "no-network" in str(excinfo.value)
        assert "must make no network call" in str(excinfo.value)

    def test_it_is_never_healthy(self):
        assert not NullProvider("none").health().healthy
        assert NullProvider("none").capacity().usable_exits == 0

    def test_it_proves_a_code_path_made_no_request(self):
        """Its whole purpose, exercised as a user would use it."""
        from src.net.policy import EgressExhausted, NetworkPolicy

        policy = NetworkPolicy([NullProvider("none")], ladder=["none"])
        with pytest.raises(EgressExhausted):
            policy.acquire(RequestClass.HTML.value)
