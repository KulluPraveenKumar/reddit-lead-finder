"""Atom 1.0 -> the same post dict the HTML extractor produces.

**This module's whole purpose is to be indistinguishable from
``RedditClient._extract_post``.** Two collection paths that disagree about what
a post is would give the scorer two populations to reconcile, and nothing
downstream could tell which one it was looking at. So the contract is not "parse
Atom well"; it is "produce byte-identical dicts, except for the two fields a
feed genuinely does not carry" -- and ``tests/test_feed_parity.py`` asserts
exactly that against a matched fixture pair.

Reddit-aware, transport-unaware. It takes bytes and returns dicts: no client, no
session, no config. That is what keeps ``src/net/`` free of Reddit knowledge
(R5, grep fence 4) while this file is free to know everything about it.

Four things the feed does that the HTML page does not, each of which would
silently corrupt a field if left alone. All four were confirmed against a live
capture on 2026-08-08, not inferred from the Atom specification:

1. ``<content>`` is **escaped HTML**, wrapped as
   ``<!-- SC_OFF --><div class="md">…</div><!-- SC_ON --> submitted by …
   [link] [comments]``. Taking its text gives the body *plus a footer naming the
   author and the permalink* -- plausible, wrong, and invisible without a
   comparison. The selftext is the ``div.md``, which is the same container class
   the HTML path reads out of ``div.expando``.
2. ``<author><name>`` is ``/u/someone``; ``data-author`` is ``someone``.
3. ``<link href>`` carries whichever host was requested -- ``old.reddit.com`` for
   this project. ``_extract_post`` emits ``www.reddit.com``.
4. ``<updated>`` is an **edit** time. ``<published>`` is the creation time and is
   what ``data-timestamp`` means, so it is preferred; ``<updated>`` is the
   fallback for the entries that omit it.

``score`` and ``num_comments`` are ``None``, never ``0``. A feed carries neither
([SPRINT-0 §2.3](../../docs/SPRINT-0-MEASUREMENTS.md)), and ``0`` would be a
fabricated fact -- the bug already fixed once for search-sourced ``score``
([07 §4.1](../../docs/07-scraping-pipeline.md)).
"""

from __future__ import annotations

import datetime
import logging
import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup
from lxml import etree

log = logging.getLogger(__name__)

#: Atom 1.0. Reddit has served this namespace unchanged since the feeds existed;
#: it is the "stable schema" half of why RSS beats CSS-class scraping.
ATOM = "{http://www.w3.org/2005/Atom}"

#: Where a permalink is *displayed*. Fetching happens against ``old.reddit.com``
#: (07 §1), but every stored URL points at the canonical host, because that is
#: what ``_extract_post`` has always written and what the 459 existing leads
#: carry.
DISPLAY_HOST = "www.reddit.com"

#: Same ceiling the HTML path applies to ``div.expando .md``.
MAX_BODY_CHARS = 5000

#: A post fullname. Reddit's ``<id>`` is the bare fullname today; this also
#: recovers one from a URI, so a change of shape degrades to a parse rather than
#: to a wrong id.
_FULLNAME = re.compile(r"t3_[a-z0-9]+", re.IGNORECASE)

#: ``/r/<name>/`` inside a permalink. The fallback for ``<category term=>``,
#: and the form P0's probe validated against live multireddit feeds.
_SUBREDDIT_IN_PATH = re.compile(r"/r/([A-Za-z0-9_]+)/")


class FeedParseError(ValueError):
    """The feed could not be understood.

    Raised rather than returning ``[]``, and the distinction is the point. An
    empty list means "this subreddit has nothing new", which a poller is
    supposed to believe and act on. A damaged or non-Atom response means "we do
    not know what is happening", which it must not. Returning ``[]`` for both
    produces a collector that reports silence forever and never fails a run.
    """


def _parser() -> etree.XMLParser:
    """A parser that will not fetch, expand or explode.

    This reads bytes that arrived over the network from a third party, so the
    XML-specific attacks are in scope even though the source is a feed we chose:
    ``resolve_entities=False`` stops billion-laughs expansion and local-file
    disclosure through a DTD, and ``no_network=True`` stops an external DTD
    reference turning a parse into an outbound request from inside the parser --
    which would also route around the network policy entirely.

    Not a new capability: it is how the already-shipped dependency should be
    called.
    """
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        recover=False,
    )


def parse_feed(xml: str | bytes) -> list[dict]:
    """Parse an Atom feed into post dicts.

    Returns ``[]`` for a valid feed with no entries. Raises
    :class:`FeedParseError` for anything that is not a readable Atom feed.
    """
    if isinstance(xml, str):
        # An XML declaration names an encoding, and lxml refuses to reconcile
        # that with a str it has already decoded. Encoding first keeps the
        # declaration authoritative.
        xml = xml.encode("utf-8")

    try:
        root = etree.fromstring(xml, parser=_parser())
    except etree.XMLSyntaxError as exc:
        raise FeedParseError(f"feed is not well-formed XML: {exc}") from exc

    if root is None or root.tag != f"{ATOM}feed":
        # A well-formed document that is not a feed. This is the shape a
        # deprecation notice, an error page or an interstitial takes, and it is
        # exactly [28 §11 D3]'s failure mode: treating it as an empty feed would
        # report "no new posts" for as long as it lasted.
        actual = root.tag if root is not None else "(empty document)"
        raise FeedParseError(f"expected an Atom <feed> root element, found {actual}")

    posts: list[dict] = []
    for entry in root.findall(f"{ATOM}entry"):
        post = _extract_entry(entry)
        if post is not None:
            posts.append(post)
    return posts


def _extract_entry(entry) -> dict | None:
    """One ``<entry>`` -> one post dict, or ``None`` if it has no usable id.

    Mirrors ``_extract_post``'s tolerance deliberately: a single unreadable
    entry drops out, it does not fail the feed. The difference between "one
    malformed row" and "a malformed document" is the difference between a
    missing post and a wrong conclusion about the whole subreddit.
    """
    try:
        post_id = _fullname(entry.findtext(f"{ATOM}id"))
        if not post_id:
            return None

        link = entry.find(f"{ATOM}link")
        href = link.get("href", "") if link is not None else ""

        return {
            "id": post_id,
            "title": (entry.findtext(f"{ATOM}title") or "").strip(),
            "url": _display_url(href),
            "author": _author(entry),
            "subreddit": _subreddit(entry, href),
            # A feed carries neither. None is "unknown"; 0 would be a claim.
            "score": None,
            "num_comments": None,
            "body": _body(entry),
            "created_utc": _created_utc(entry),
        }
    except Exception as exc:  # noqa: BLE001 - one entry must not kill a feed
        log.debug("could not parse feed entry: %s", exc)
        return None


def _fullname(raw: str | None) -> str:
    if not raw:
        return ""
    match = _FULLNAME.search(raw)
    return match.group(0) if match else ""


def _author(entry) -> str:
    """``/u/someone`` -> ``someone``.

    ``[deleted]`` when absent, which is the literal string ``data-author``
    carries for a removed account, so the two paths agree on deletions too.
    """
    name = (entry.findtext(f"{ATOM}author/{ATOM}name") or "").strip()
    if not name:
        return "[deleted]"
    return name[3:] if name.startswith("/u/") else name.removeprefix("u/")


def _subreddit(entry, href: str) -> str:
    """``<category term=>`` first, permalink second.

    Both are needed. ``term`` is the direct statement and is present on every
    entry a live capture showed; the permalink fallback is what P0's probe used
    to prove multireddit feeds carry mixed subreddits, and it keeps a feed
    readable if ``category`` is ever dropped.
    """
    category = entry.find(f"{ATOM}category")
    if category is not None:
        term = (category.get("term") or "").strip()
        if term:
            return term
    match = _SUBREDDIT_IN_PATH.search(href or "")
    return match.group(1) if match else ""


def _display_url(href: str) -> str:
    """Point the permalink at the canonical host, whatever host served us."""
    if not href:
        return ""
    parts = urlsplit(href)
    if not parts.netloc:
        return href
    return urlunsplit(("https", DISPLAY_HOST, parts.path, parts.query, parts.fragment))


def _body(entry) -> str:
    """The selftext, and nothing else.

    ``<content>`` is escaped HTML holding the rendered post *and* a footer that
    names the author and links the permalink. The footer is not body text; a
    keyword rule counting "submitted by" as content would match every single
    post. The selftext is the ``div.md``, read with the same ``get_text`` and the
    same 5,000-character ceiling the HTML path uses, so the two produce the same
    string rather than merely similar ones.

    A link post has no ``div.md`` and no ``<content>`` at all in search feeds.
    Both are ``""``, which is what ``_extract_post`` produces for a post with no
    expando.
    """
    content = entry.find(f"{ATOM}content")
    if content is None or not content.text:
        return ""

    soup = BeautifulSoup(content.text, "lxml")
    md = soup.select_one("div.md")
    if md is None:
        return ""
    return md.get_text(strip=True)[:MAX_BODY_CHARS]


def _created_utc(entry) -> datetime.datetime | None:
    """When the post was **created**, as naive UTC.

    ``<published>`` is preferred and ``<updated>`` is the fallback, because they
    are different facts: a post edited an hour after it appeared has an
    ``<updated>`` an hour late, and ordering a watermark by an edit time would
    re-collect edited posts forever while missing new ones.

    Naive, and stripped rather than merely dropped: the schema stores naive UTC
    (``tests/test_boundaries.py``), and an aware value serialises with a
    ``+00:00`` suffix that silently breaks SQLite string comparisons.
    """
    raw = entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")
    if not raw:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.UTC).replace(tzinfo=None)
    return parsed
