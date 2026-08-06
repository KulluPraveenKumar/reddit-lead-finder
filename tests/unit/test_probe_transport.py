"""Tests for the P0 transport abstraction.

The probe scripts themselves are throwaway — their *output* is the artefact
(``docs/35-testing-strategy.md`` §3). These tests exist anyway, for one reason:
``transport.py`` handles proxy credentials, and credential redaction is a
security guarantee (``ARCHITECTURE_FREEZE.md`` R15), not probe scaffolding. A
guarantee nobody has seen fail is not a guarantee.

Everything here is offline. No test in this file may touch the network.
"""

from __future__ import annotations

import pytest

from scripts.probe.transport import (
    DisabledProvider,
    FutureManagedProvider,
    TransportManager,
    parse_proxy_file,
)

SAMPLE = """\
1.2.3.4:8000:alice:hunter2
5.6.7.8:8001:alice:hunter2
# a comment
9.9.9.9:notaport:alice:hunter2
1.2.3.4:8000:alice:hunter2
malformed-line
"""


@pytest.fixture
def proxy_file(tmp_path):
    p = tmp_path / "proxies.txt"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def test_parses_valid_lines_only(proxy_file):
    eps = parse_proxy_file(proxy_file)
    # two valid, one duplicate, one bad port, one malformed, one comment
    assert [e.label for e in eps] == ["1.2.3.4:8000", "5.6.7.8:8001"]


def test_repr_never_contains_credentials(proxy_file):
    """R15. An endpoint interpolated into a log line must not leak."""
    ep = parse_proxy_file(proxy_file)[0]
    for rendered in (repr(ep), str(ep), f"{ep}", "{}".format(ep)):  # noqa: UP032
        assert "hunter2" not in rendered
        assert "alice" not in rendered
        assert ep.label in rendered


def test_url_does_contain_credentials(proxy_file):
    """The one method that must expose them, pinned deliberately.

    Without this test a suite asserting 'no credentials anywhere' would pass
    just as happily against a pool that could not authenticate.
    """
    ep = parse_proxy_file(proxy_file)[0]
    assert ep.url == "http://alice:hunter2@1.2.3.4:8000"


def test_empty_file_raises(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("# nothing here\n", encoding="utf-8")
    with pytest.raises(ValueError):
        from scripts.probe.transport import WebshareProvider

        WebshareProvider(p)


def test_disabled_provider_refuses_every_call():
    """Proves a code path made no network call. A canned response could not."""
    with pytest.raises(RuntimeError, match="refused outbound request"):
        DisabledProvider().get("https://example.com")


def test_disabled_provider_has_no_exits():
    assert DisabledProvider().exits() == []


def test_future_managed_constructs_but_refuses():
    """It is a shape, not an integration — constructing it must not imply use."""
    p = FutureManagedProvider("gw.example.com:7000", "user", "pass")
    assert p.exits() == ["gw.example.com:7000"]
    assert p.exposes_origin_ip is False
    with pytest.raises(NotImplementedError):
        p.get("https://example.com")


def test_manager_rejects_unknown_default():
    with pytest.raises(ValueError, match="default transport"):
        TransportManager({"disabled": DisabledProvider()}, default="nope")


def test_manager_routes_to_named_transport():
    mgr = TransportManager({"disabled": DisabledProvider()}, default="disabled")
    assert mgr.available == ["disabled"]
    with pytest.raises(RuntimeError):
        mgr.get("https://example.com")


def test_only_direct_exposes_origin_ip():
    """The flag the network policy reasons over, rather than a provider name."""
    from scripts.probe.transport import DirectConnectionProvider

    assert DirectConnectionProvider.exposes_origin_ip is True
    assert DisabledProvider.exposes_origin_ip is False
    assert FutureManagedProvider.exposes_origin_ip is False
