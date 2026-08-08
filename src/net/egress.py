"""The process-wide :class:`NetworkPolicy`.

**One policy per process, not one per caller — and this is a correctness
requirement, not a tidiness one.**

The two things the policy holds are budgets over *this machine*:

* the direct connection's hourly governor (120/hour, a frozen budget), which
  bounds how much traffic reaches a target from the operator's own address;
* the pool's blacklist and target-acceptance window, which are what the ladder
  degrades on.

``handle_scrape_subreddit`` builds a scraper **per job**. If each of those built
its own policy, twelve subreddits would get twelve independent 120-request
allowances — the cap would be enforced at 12× — and each would start with an
empty blacklist, re-learning the same dead proxies twelve times.

It also closes a gap that predates P4: ``/health/proxies`` has always shown a
pool built by ``src/dashboard/app.py``, while the scraper used one it built
itself. The page was reporting a pool that never served a request. Both now
resolve the same policy, so the numbers on that page are the scraper's.
"""

from __future__ import annotations

import threading

from .policy import NetworkPolicy, build_policy_from_config

_lock = threading.RLock()
_policy: NetworkPolicy | None = None
_error: str | None = None


def get_policy(config: dict | None = None) -> NetworkPolicy:
    """The process-wide policy, built on first use.

    ``config`` seeds it on the first call; later calls ignore it, exactly as
    ``get_settings`` does. A caller that needs a *different* policy constructs
    one directly — this is the shared default, not a mandate.
    """
    global _policy, _error
    with _lock:
        if _policy is None:
            try:
                _policy = build_policy_from_config(config)
                _error = None
            except Exception as exc:  # noqa: BLE001 - a bad block must not stop a scrape
                # Degrade to a bare direct policy rather than refusing to run.
                # A misconfigured provider block is an operator error worth
                # reporting loudly; it is not a reason for the tool to stop
                # working, and R18 keeps the direct classes correct regardless.
                from .providers import DirectProvider

                _error = str(exc)
                _policy = NetworkPolicy([DirectProvider("direct")])
        return _policy


def policy_error() -> str | None:
    """Why the configured policy could not be built, if it could not."""
    return _error


def reset_policy() -> None:
    """Test and settings-change hook: drop the cached policy."""
    global _policy, _error
    with _lock:
        _policy = None
        _error = None
