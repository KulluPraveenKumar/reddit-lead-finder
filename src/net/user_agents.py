"""Internally-consistent browser header profiles.

**This module is the fix for a real, measured block.** On 2026-07-31 the
pre-existing header set was getting HTTP 403 from `old.reddit.com` on every
request, from the local IP *and* from all ten proxies. The set was:

    User-Agent:      Chrome/120 on Windows
    Accept-Language: en-US,en;q=0.5      <- Firefox's value; Chrome sends q=0.9
    (no Sec-CH-UA, no Sec-Fetch-*, no Upgrade-Insecure-Requests)

A real Chrome never sends that combination. Swapping in a coherent Chrome
profile returned **200 on the same proxy, seconds later**. The block was a
fingerprint problem, not an IP problem — which is why the fix lives here rather
than in the proxy pool.

Two rules follow:

1. **A profile is atomic.** Mixing a UA from one and an Accept-Language from
   another recreates exactly the bug above. Nothing here exposes a way to take
   one field.
2. **A profile is pinned per proxy** for the life of a session. Ten residential
   IPs presenting one identical header set is a stronger signal than one IP
   would be; ten IPs each *changing* fingerprint mid-session is stronger still.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HeaderProfile:
    name: str
    headers: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, str]:
        return dict(self.headers)


def _chrome(version: int, platform: str, ua_platform: str) -> HeaderProfile:
    # ua_platform arrives quoted because that is the wire format of the
    # sec-ch-ua-platform header ('"Windows"'). Stripped outside the f-string:
    # a backslash escape inside one needs PEP 701, which is Python 3.12+, and
    # the declared floor for this project is 3.11.
    short_platform = ua_platform.strip('"').lower()
    return HeaderProfile(
        name=f"chrome-{version}-{short_platform}",
        headers={
            "User-Agent": (
                f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{version}.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "sec-ch-ua": (
                f'"Google Chrome";v="{version}", "Chromium";v="{version}", "Not_A Brand";v="24"'
            ),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": ua_platform,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Connection": "keep-alive",
        },
    )


def _firefox(version: int, platform: str, tag: str) -> HeaderProfile:
    return HeaderProfile(
        name=f"firefox-{version}-{tag}",
        headers={
            "User-Agent": (
                f"Mozilla/5.0 ({platform}; rv:{version}.0) Gecko/20100101 Firefox/{version}.0"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            # Firefox really does send q=0.5 here. Correct *for Firefox*.
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Connection": "keep-alive",
            # No Sec-CH-UA: Firefox does not implement Client Hints. Adding it
            # would be the same incoherence in the opposite direction.
        },
    )


WIN = "Windows NT 10.0; Win64; x64"
MAC = "Macintosh; Intel Mac OS X 10_15_7"

PROFILES: list[HeaderProfile] = [
    _chrome(131, WIN, '"Windows"'),
    _chrome(130, WIN, '"Windows"'),
    _chrome(131, MAC, '"macOS"'),
    _firefox(133, "Windows NT 10.0; Win64; x64", "windows"),
    _firefox(133, "Macintosh; Intel Mac OS X 10.15", "macos"),
]

#: Used where no rotation is wanted. Chrome-on-Windows is the commonest real
#: client, so it is the least remarkable thing to be.
DEFAULT_PROFILE = PROFILES[0]


def pick_profile(seed: str | None = None) -> HeaderProfile:
    """Deterministic per ``seed`` so a proxy keeps one identity."""
    if seed is None:
        return random.choice(PROFILES)
    return PROFILES[hash(seed) % len(PROFILES)]


def headers_for(seed: str | None = None, *, referer: str | None = None) -> dict[str, str]:
    headers = pick_profile(seed).as_dict()
    if referer:
        headers["Referer"] = referer
        # A browser arriving from another page on the same site reports
        # same-origin, not "none". Leaving "none" beside a Referer is another
        # incoherent pair of exactly the kind that caused the 403.
        headers["Sec-Fetch-Site"] = "same-origin"
    return headers
