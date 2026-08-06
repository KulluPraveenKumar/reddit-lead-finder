"""Soft-block detection.

**A 200 is not proof of success.** Measured on 2026-07-31: `old.reddit.com`
answered a request with HTTP 200, 311 KB, and the *new* Reddit interstitial
("Welcome to Reddit", `shreddit`/`faceplate` markers) containing zero
`div.thing` elements. The same URL had returned 25 posts minutes earlier from a
different proxy.

Without detection that page would be cached as a valid response, parsed to zero
posts, and reported as "the subreddit has no new submissions" — a silent,
plausible, completely wrong answer. That is far worse than an error, because
nothing looks broken.

The detector is deliberately conservative. A false positive costs one retry on
another proxy; a false negative poisons the cache and the lead table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class BlockKind(StrEnum):
    NONE = "none"
    #: HTTP 403/429 - unambiguous.
    HARD = "hard"
    #: HTTP 200 carrying a challenge or interstitial instead of content.
    SOFT = "soft"
    #: 200, right shape, but empty. Might be genuine; the caller decides.
    EMPTY = "empty"


@dataclass(frozen=True)
class BlockVerdict:
    kind: BlockKind
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return self.kind in (BlockKind.HARD, BlockKind.SOFT)

    @property
    def cacheable(self) -> bool:
        """Never cache a block. A cached block is a block that outlives its cause."""
        return self.kind is BlockKind.NONE


#: Phrases that only appear on a challenge or interstitial page.
_SOFT_MARKERS: tuple[tuple[str, str], ...] = (
    ("just a moment", "Cloudflare challenge"),
    ("whoa there, pardner", "Reddit rate-limit interstitial"),
    ("checking your browser", "browser check"),
    ("enable javascript and cookies to continue", "JS challenge"),
    ("verifying you are human", "bot check"),
    ("access to this page has been denied", "denial page"),
)

#: The new-Reddit web app. On an old.reddit URL its presence means we were
#: bounced off the HTML site we asked for, whatever the status code says.
_NEW_REDDIT_MARKERS = ("shreddit-app", "<faceplate-", "shreddit-async-loader")

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

#: Titles the old HTML site never serves for a content page.
_BAD_TITLES = ("welcome to reddit", "blocked", "too many requests", "just a moment")


def _title(html: str) -> str:
    match = _TITLE.search(html)
    return match.group(1).strip().lower() if match else ""


def classify(
    status_code: int,
    html: str,
    *,
    expect_selector_hits: int | None = None,
) -> BlockVerdict:
    """Classify a response.

    ``expect_selector_hits`` is how many content elements the caller's parser
    found. Supplying it turns "200 with no content and a suspicious title" from
    a guess into a determination.
    """
    if status_code in (403, 429):
        return BlockVerdict(BlockKind.HARD, f"HTTP {status_code}")
    if status_code >= 500:
        return BlockVerdict(BlockKind.HARD, f"HTTP {status_code} (upstream)")
    if status_code != 200:
        return BlockVerdict(BlockKind.HARD, f"HTTP {status_code}")

    lowered = html[:200_000].lower()

    for marker, reason in _SOFT_MARKERS:
        if marker in lowered:
            return BlockVerdict(BlockKind.SOFT, reason)

    title = _title(html)
    if any(bad in title for bad in _BAD_TITLES):
        return BlockVerdict(BlockKind.SOFT, f"interstitial title: {title[:60]!r}")

    # New-Reddit markers only matter when we expected old-Reddit content and
    # got none. On their own they could be a legitimately embedded widget.
    if expect_selector_hits == 0 and any(m in lowered for m in _NEW_REDDIT_MARKERS):
        return BlockVerdict(BlockKind.SOFT, "served the new Reddit app instead of old HTML")

    if expect_selector_hits == 0:
        # Shape is right, content is absent. A genuinely empty subreddit looks
        # exactly like this, so it is reported rather than judged.
        return BlockVerdict(BlockKind.EMPTY, "200 with no matching content elements")

    return BlockVerdict(BlockKind.NONE)
