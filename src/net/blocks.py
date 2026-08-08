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


#: Phrases that only appear on a challenge or interstitial page, whoever is
#: serving it. These are **target-agnostic**: a Cloudflare challenge looks the
#: same in front of any site, which is why they can live in the transport.
GENERIC_SOFT_MARKERS: tuple[tuple[str, str], ...] = (
    ("just a moment", "Cloudflare challenge"),
    ("checking your browser", "browser check"),
    ("enable javascript and cookies to continue", "JS challenge"),
    ("verifying you are human", "bot check"),
    ("access to this page has been denied", "denial page"),
)

#: Titles no content page serves, whatever the site.
GENERIC_BAD_TITLES: tuple[str, ...] = ("blocked", "too many requests", "just a moment")

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class BlockSignatures:
    """What an interstitial looks like *for one target*.

    **Target-specific signatures are the caller's knowledge, not this layer's.**
    ``src/net/`` is a reusable egress layer with no knowledge of what is being
    fetched (R5, and the grep fence that enforces it); a detector that hard-coded
    one site's markup would be that knowledge, in the one module most likely to
    need editing when that site changes.

    It also matters for correctness, not only tidiness: the same client fetches a
    customer's own website, and applying one site's "you were bounced to the
    wrong app" heuristic to an unrelated page is a false positive waiting to
    happen. A caller supplies the signatures for the target it is talking to;
    everyone else gets the generic set.

    ``app_markers`` are matched **only** when the caller's own selector found no
    content: on their own they could be a legitimately embedded widget.
    """

    soft_markers: tuple[tuple[str, str], ...] = GENERIC_SOFT_MARKERS
    bad_titles: tuple[str, ...] = GENERIC_BAD_TITLES
    app_markers: tuple[str, ...] = ()
    app_marker_reason: str = "served a different application than the one requested"


#: Used when a caller supplies nothing. Detects challenge pages and nothing
#: target-specific -- correct for any target, complete for none.
DEFAULT_SIGNATURES = BlockSignatures()


def _title(html: str) -> str:
    match = _TITLE.search(html)
    return match.group(1).strip().lower() if match else ""


def classify(
    status_code: int,
    html: str,
    *,
    expect_selector_hits: int | None = None,
    signatures: BlockSignatures | None = None,
) -> BlockVerdict:
    """Classify a response.

    ``expect_selector_hits`` is how many content elements the caller's parser
    found. Supplying it turns "200 with no content and a suspicious title" from
    a guess into a determination.

    ``signatures`` describes what an interstitial looks like for *this* target.
    Omitted, the generic challenge set is used.
    """
    signatures = signatures or DEFAULT_SIGNATURES

    if status_code in (403, 429):
        return BlockVerdict(BlockKind.HARD, f"HTTP {status_code}")
    if status_code >= 500:
        return BlockVerdict(BlockKind.HARD, f"HTTP {status_code} (upstream)")
    if status_code != 200:
        return BlockVerdict(BlockKind.HARD, f"HTTP {status_code}")

    lowered = html[:200_000].lower()

    for marker, reason in signatures.soft_markers:
        if marker in lowered:
            return BlockVerdict(BlockKind.SOFT, reason)

    title = _title(html)
    if any(bad in title for bad in signatures.bad_titles):
        return BlockVerdict(BlockKind.SOFT, f"interstitial title: {title[:60]!r}")

    # App markers only matter when we expected content and got none. On their
    # own they could be a legitimately embedded widget.
    if expect_selector_hits == 0 and any(m in lowered for m in signatures.app_markers):
        return BlockVerdict(BlockKind.SOFT, signatures.app_marker_reason)

    if expect_selector_hits == 0:
        # Shape is right, content is absent. A genuinely empty listing looks
        # exactly like this, so it is reported rather than judged.
        return BlockVerdict(BlockKind.EMPTY, "200 with no matching content elements")

    return BlockVerdict(BlockKind.NONE)
