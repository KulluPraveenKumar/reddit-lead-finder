"""Reddit HTML client for old.reddit.com.

**The public API is frozen.** ``get_new_posts``, ``get_hot_posts``,
``search_posts``, ``get_post_comments``, ``get_user_posts`` and
``get_subreddit_info`` keep their signatures and return shapes; the three
scrapers call them unchanged. Only the transport moved, from a bare
``requests.Session`` to ``ProxiedHTTPClient``.

Six bugs fixed here, all confirmed against live HTML on 2026-07-31 rather than
inferred:

1. **Search pagination never worked.** The selector was ``nav-buttons`` — a tag
   name. The class selector is ``.nav-buttons``, and the tag matched nothing, so
   search silently stopped at one page of ~25 results forever.
2. **...and the obvious fix is also wrong.** A search page has **two**
   ``.nav-buttons``: one paginates *subreddit* results (``type=sr``,
   ``after=t5_``), one paginates *posts* (``after=t3_``). Taking the first would
   have paginated the wrong listing and returned zero new posts each time —
   pagination "working" while producing nothing.
3. **Queries were not URL-encoded.** A query containing a space, ``&`` or ``#``
   was silently truncated or corrupted by the target.
4. **Search results claimed ``score = 0``.** Search HTML carries no score at
   all, so 0 was a fabricated fact. Now ``None`` — unknown.
5. **Pagination rebuilt the URL** by appending ``&after=``, accumulating
   parameters across pages. Now the ``next`` href is followed directly, as a
   browser would.
6. **No loop guard.** A repeated or self-referential ``after`` cursor looped
   forever. Now bounded by page count and a seen-cursor set.
"""

from __future__ import annotations

import datetime
import logging
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from rich.console import Console

from .discovery import parse_feed
from .net import BlockedError, BlockSignatures, ProxiedHTTPClient, ProxyExhaustedError, RequestClass
from .net.blocks import GENERIC_BAD_TITLES, GENERIC_SOFT_MARKERS

console = Console()
log = logging.getLogger(__name__)

BASE_URL = "https://old.reddit.com"
DISPLAY_URL = "https://www.reddit.com"

#: What an interstitial from *this* target looks like.
#:
#: These live here rather than in ``src/net/`` because they are knowledge about
#: Reddit, and the transport layer is required to have none (R5, grep fence 4).
#: The generic challenge markers are inherited and extended, not replaced -- a
#: Cloudflare page in front of this target is still a Cloudflare page.
#:
#: Measured on 2026-07-31: ``old.reddit.com`` answered with HTTP 200, 311 KB and
#: the *new* Reddit interstitial containing zero ``div.thing`` elements. Without
#: detection that page is cached as valid, parsed to zero posts, and reported as
#: "no new submissions" -- a silent, plausible, completely wrong answer.
REDDIT_SIGNATURES = BlockSignatures(
    soft_markers=(
        *GENERIC_SOFT_MARKERS,
        ("whoa there, pardner", "Reddit rate-limit interstitial"),
    ),
    bad_titles=(*GENERIC_BAD_TITLES, "welcome to reddit"),
    #: The new-Reddit web app. On an old.reddit URL its presence means we were
    #: bounced off the HTML site we asked for, whatever the status code says.
    app_markers=("shreddit-app", "<faceplate-", "shreddit-async-loader"),
    app_marker_reason="served the new Reddit app instead of old HTML",
)

#: Old Reddit serves 25 items per page. Used only to bound pagination.
PAGE_SIZE = 25
#: Hard ceiling on pages per call, whatever `limit` asks for. A safety net
#: against a cursor that never terminates, not a product limit.
MAX_PAGES = 40

#: Where feeds are fetched from. `old.reddit.com` because 07 §1 permits only
#: that host, and P0's U6 measured it serving RSS identically to `www`.
DEFAULT_RSS_HOST = BASE_URL
#: P0's U5 measured `?limit=100` as honoured, returning 100 entries. It is the
#: real ceiling per request, and asking for more gets 100 anyway.
MAX_FEED_LIMIT = 100
DEFAULT_FEED_LIMIT = MAX_FEED_LIMIT
#: The sorts a feed accepts, mirroring the site's own.
FEED_SORTS = frozenset({"new", "hot", "top", "rising"})


class FeedDisabled(RuntimeError):
    """``discovery.rss_enabled`` is false.

    Raised rather than returning ``[]`` so the operator's rollback switch is
    visible in a log instead of looking like a subreddit with nothing new --
    the same reason a malformed feed raises. See P5's rollback level 1.
    """


class RedditClient:
    def __init__(self, config=None, http_client: ProxiedHTTPClient | None = None):
        self.config = config or {}
        self.http = http_client or _default_client(self.config)

    # ------------------------------------------------------------ transport

    def _get(self, url: str, *, expect_selector: str | None = None) -> str | None:
        """Fetch one page. Returns None on failure, as the old client did.

        The return contract is preserved deliberately: the scrapers already
        handle None by stopping, and changing them to handle exceptions is
        Phase 6 work.
        """
        try:
            result = self.http.get(url, expect_selector=expect_selector)
        except ProxyExhaustedError as exc:
            console.print(f"[red]Proxy pool exhausted: {exc}[/red]")
            return None
        except BlockedError as exc:
            console.print(f"[yellow]Blocked: {exc}[/yellow]")
            return None
        except Exception as exc:  # noqa: BLE001 - one page must not kill a run
            log.warning("request failed for %s: %s", url, exc)
            console.print(f"[red]Request failed: {exc}[/red]")
            return None

        if not result.ok:
            console.print(f"[yellow]{url} -> {result.status_code} {result.verdict.reason}[/yellow]")
            return None
        return result.text

    def _paginate(self, first_url: str, parser, limit: int, *, expect_selector: str):
        """Walk `next` links, following hrefs rather than rebuilding URLs."""
        items: list[dict] = []
        url: str | None = first_url
        seen_urls: set[str] = set()
        pages = 0

        while url and len(items) < limit and pages < MAX_PAGES:
            if url in seen_urls:
                # A next link pointing at a page already fetched. Reddit does
                # this at the end of some listings; without this the loop is
                # infinite.
                log.debug("pagination cursor repeated; stopping at %d items", len(items))
                break
            seen_urls.add(url)

            html = self._get(url, expect_selector=expect_selector)
            if not html:
                break

            page_items, next_url = parser(html, url)
            if not page_items:
                break

            items.extend(page_items)
            pages += 1
            url = next_url

        return items[:limit]

    # --------------------------------------------------------- public API

    def get_new_posts(self, subreddit, limit=100):
        return self._paginate(
            f"{BASE_URL}/r/{subreddit}/new/",
            self._parse_listing,
            limit,
            expect_selector="div.thing.link",
        )

    def get_hot_posts(self, subreddit, limit=50):
        return self._paginate(
            f"{BASE_URL}/r/{subreddit}/hot/",
            self._parse_listing,
            limit,
            expect_selector="div.thing.link",
        )

    def search_posts(self, query, subreddit=None, limit=50, sort="new", time_filter=None):
        """Search posts.

        ``sort`` and ``time_filter`` are new optional parameters; both default
        to the previous behaviour, so existing callers are unaffected.
        """
        return self._paginate(
            self._search_url(query, subreddit=subreddit, sort=sort, time_filter=time_filter),
            self._parse_search_results,
            limit,
            expect_selector="div.search-result-link",
        )

    def _search_url(self, query, *, subreddit=None, sort="new", time_filter=None):
        """Build the search URL.

        Separate from :meth:`search_posts` so the encoding can be tested without
        a network call. ``quote_plus`` matters more than it looks: an unencoded
        ``&`` in the query would terminate the ``q`` parameter and silently
        search for the fragment before it, and an unencoded ``#`` would turn the
        rest of the query into a URL fragment that is never sent to the server.
        Both fail quietly, returning plausible results for the wrong search.
        """
        encoded = quote_plus(str(query))
        if subreddit:
            url = f"{BASE_URL}/r/{subreddit}/search?q={encoded}&restrict_sr=on&sort={sort}"
        else:
            url = f"{BASE_URL}/search?q={encoded}&sort={sort}"
        if time_filter:
            url += f"&t={quote_plus(str(time_filter))}"
        return url

    def get_post_comments(self, post_url, limit=50):
        html = self._get(post_url, expect_selector="div.comment")
        if not html:
            return []
        return self._parse_comments(html)[:limit]

    def get_user_posts(self, username, limit=50):
        return self._paginate(
            f"{BASE_URL}/user/{username}/submitted/new/",
            self._parse_listing,
            limit,
            expect_selector="div.thing.link",
        )

    def get_subreddit_info(self, subreddit_name):
        html = self._get(f"{BASE_URL}/r/{subreddit_name}/")
        if not html:
            return None
        return self._parse_subreddit_about(html, subreddit_name)

    # ---------------------------------------------------------------- feeds

    def get_feed(self, subreddits, *, sort="new", limit=None, query=None):
        """Fetch one Atom feed and return posts in ``_extract_post``'s shape.

        **Additive.** The six methods above keep their signatures and return
        shapes ([AD-2](../docs/ARCHITECTURE_FREEZE.md)); this is a seventh, and
        nothing calls it until P6.

        Why it does not paginate, unlike everything else here: a feed carries up
        to 100 items in one response (U5) and offers no `next` link, and P0
        measured the RSS budget at **one request per ~60 seconds per IP** (U1) --
        so a second request would cost a minute of wall clock to fetch a page
        that does not exist. Many subreddits go in **one** multireddit URL for
        the same reason; combining is mandatory, not an optimisation.

        Egress is `rss`, which is direct under every policy value -- frozen
        architecture (R18), not configuration. The cache is bypassed: a 15-minute
        TTL serving a stale feed to a 15-minute poll means the watermark never
        advances and new posts are silently lost ([28 §11 D5](../docs/28-discovery-redesign.md)).

        Failures are deliberately separated. A **transport** failure returns
        `[]`, matching `_get`'s long-standing contract, because the caller
        already handles "nothing came back". A **parse** failure raises
        `FeedParseError`, because "the feed is broken" and "the subreddit is
        quiet" must never look the same.
        """
        discovery = (self.config or {}).get("discovery", {}) or {}
        if not discovery.get("rss_enabled", True):
            raise FeedDisabled(
                "feed collection is disabled (discovery.rss_enabled: false); "
                "the HTML path is unaffected"
            )

        if limit is None:
            limit = discovery.get("rss_limit", DEFAULT_FEED_LIMIT)
        limit = _clamp_feed_limit(limit)

        url = self._feed_url(
            subreddits,
            sort=sort,
            limit=limit,
            query=query,
            host=discovery.get("rss_host") or DEFAULT_RSS_HOST,
        )

        try:
            result = self.http.get(
                url,
                request_class=RequestClass.RSS.value,
                allow_cache=False,
            )
        except ProxyExhaustedError as exc:
            console.print(f"[red]Proxy pool exhausted: {exc}[/red]")
            return []
        except BlockedError as exc:
            console.print(f"[yellow]Blocked: {exc}[/yellow]")
            return []
        except Exception as exc:  # noqa: BLE001 - one feed must not kill a run
            log.warning("feed request failed for %s: %s", url, exc)
            console.print(f"[red]Feed request failed: {exc}[/red]")
            return []

        if not result.ok:
            console.print(f"[yellow]{url} -> {result.status_code} {result.verdict.reason}[/yellow]")
            return []

        return parse_feed(result.text)[:limit]

    def _feed_url(self, subreddits, *, sort="new", limit=DEFAULT_FEED_LIMIT, query=None, host=None):
        """Build the feed URL.

        Separate from :meth:`get_feed` so every URL shape is testable without a
        network call -- the same reason `_search_url` is separate, and the same
        bug class it exists to prevent: an unencoded `&` or `#` in a query
        silently searches for the fragment before it and returns plausible
        results for the wrong search.

        Two shapes, both measured in P0:

        * **listing** -- ``/r/a+b+c/new/.rss?limit=100``. One request, many
          subreddits (U1 makes combining mandatory).
        * **search** -- ``/search.rss?q=(subreddit:a OR subreddit:b) AND "kw"``.
          U3 confirmed boolean multi-subreddit search works, which is what turns
          120 keyword requests into 12. The boolean form is used even for a
          single subreddit, so there is one search path rather than two.
        """
        names = _feed_subreddits(subreddits)
        if sort not in FEED_SORTS:
            raise ValueError(f"sort must be one of {sorted(FEED_SORTS)}, not {sort!r}")
        limit = _clamp_feed_limit(limit)
        base = (host or DEFAULT_RSS_HOST).rstrip("/")

        if query:
            clause = " OR ".join(f"subreddit:{name}" for name in names)
            expression = f'({clause}) AND "{query}"'
            return f"{base}/search.rss?q={quote_plus(expression)}&sort={sort}&limit={limit}"

        return f"{base}/r/{'+'.join(names)}/{sort}/.rss?limit={limit}"

    # ------------------------------------------------------------ parsing

    def _parse_listing(self, html, base_url: str = BASE_URL):
        soup = BeautifulSoup(html, "lxml")
        posts = []

        for thing in soup.select("div.thing.link"):
            post = self._extract_post(thing)
            if post:
                posts.append(post)

        next_url = None
        next_link = soup.select_one("span.nextprev a[rel~='next']")
        if next_link and next_link.get("href"):
            next_url = urljoin(base_url, next_link["href"])

        return posts, next_url

    def _parse_search_results(self, html, base_url: str = BASE_URL):
        """Parse a search page and find the *posts* next link.

        The `next` link must come from the result group that actually contains
        posts. A search page also renders a subreddit-results group with its own
        `.nav-buttons`, and following that one paginates subreddits — producing
        pages with zero posts, indefinitely.
        """
        soup = BeautifulSoup(html, "lxml")
        posts = []

        for result in soup.select("div.search-result-link"):
            post = self._extract_search_post(result)
            if post:
                posts.append(post)

        next_url = None
        groups = [
            g for g in soup.select("div.search-result-group") if g.select("div.search-result-link")
        ]
        for group in groups:
            link = group.select_one(".nav-buttons a[rel~='next']")
            if link and link.get("href"):
                next_url = urljoin(base_url, link["href"])
                break

        if next_url is None:
            # Fallback for a layout without result groups: accept any next link
            # whose cursor is a POST fullname (t3_), never a subreddit (t5_).
            for link in soup.select("a[rel~='next']"):
                href = link.get("href", "")
                if "after=t3_" in href:
                    next_url = urljoin(base_url, href)
                    break

        return posts, next_url

    def _extract_post(self, thing):
        try:
            post_id = thing.get("data-fullname", "")
            if not post_id:
                return None

            title_el = thing.select_one("a.title, p.title a")
            title = title_el.get_text(strip=True) if title_el else ""
            url = title_el.get("href", "") if title_el else ""

            if url and url.startswith("/"):
                url = f"{DISPLAY_URL}{url}"

            author = thing.get("data-author", "[deleted]")
            subreddit = thing.get("data-subreddit", "")
            score_str = thing.get("data-score", "")
            # Absent attribute means unknown, which is not the same as zero.
            score = int(score_str) if score_str.lstrip("-").isdigit() else None

            created_utc = None
            timestamp = thing.get("data-timestamp", "")
            if timestamp:
                try:
                    # data-timestamp is milliseconds since epoch.
                    created_utc = datetime.datetime.fromtimestamp(
                        int(timestamp) / 1000, tz=datetime.UTC
                    ).replace(tzinfo=None)
                except (ValueError, OSError, OverflowError):
                    pass

            if not created_utc:
                created_utc = _parse_time_element(thing)

            num_comments = 0
            comments_el = thing.select_one("a.comments")
            if comments_el:
                match = re.search(r"(\d+)", comments_el.get_text())
                if match:
                    num_comments = int(match.group(1))

            body = ""
            expando = thing.select_one("div.expando .md")
            if expando:
                body = expando.get_text(strip=True)[:5000]

            return {
                "id": post_id,
                "title": title,
                "url": url,
                "author": author,
                "subreddit": subreddit,
                "score": score,
                "num_comments": num_comments,
                "body": body,
                "created_utc": created_utc,
            }
        except Exception as exc:
            log.debug("could not parse post: %s", exc)
            return None

    def _extract_search_post(self, result):
        try:
            post_id = result.get("data-fullname", "")
            if not post_id:
                return None

            title_el = result.select_one("a.search-title")
            title = title_el.get_text(strip=True) if title_el else ""
            url = title_el.get("href", "") if title_el else ""

            if url and url.startswith("/"):
                url = f"{DISPLAY_URL}{url}"

            author_el = result.select_one("a.author")
            author = author_el.get_text(strip=True) if author_el else "[deleted]"

            sub_el = result.select_one("a.search-subreddit-link")
            subreddit = ""
            if sub_el:
                subreddit = sub_el.get_text(strip=True).replace("r/", "")

            num_comments = 0
            comments_el = result.select_one("a.search-comments")
            if comments_el:
                match = re.search(r"(\d+)", comments_el.get_text())
                if match:
                    num_comments = int(match.group(1))

            body = ""
            body_el = result.select_one("div.search-result-body .md")
            if body_el:
                body = body_el.get_text(strip=True)[:5000]

            # Search HTML carries no score. `data-score` may be present on some
            # layouts; where it is not, the honest value is None. Reporting 0
            # would let a search-sourced lead outrank a real zero-score post
            # for no reason, and nothing downstream could tell the difference.
            score_str = result.get("data-score", "")
            score = int(score_str) if score_str.lstrip("-").isdigit() else None

            return {
                "id": post_id,
                "title": title,
                "url": url,
                "author": author,
                "subreddit": subreddit,
                "score": score,
                "num_comments": num_comments,
                "body": body,
                "created_utc": _parse_time_element(result),
            }
        except Exception as exc:
            log.debug("could not parse search result: %s", exc)
            return None

    def _parse_comments(self, html):
        soup = BeautifulSoup(html, "lxml")
        comments = []

        for comment_el in soup.select("div.comment"):
            try:
                author_el = comment_el.select_one("a.author")
                author = author_el.get_text(strip=True) if author_el else "[deleted]"

                body_el = comment_el.select_one("div.usertext .md")
                body = body_el.get_text(strip=True) if body_el else ""

                score = 0
                score_el = comment_el.select_one("span.score")
                if score_el:
                    match = re.search(r"(-?\d+)", score_el.get_text())
                    if match:
                        score = int(match.group(1))

                if body:
                    comments.append(
                        {
                            "author": author,
                            "body": body,
                            "score": score,
                            "created_utc": _parse_time_element(comment_el),
                        }
                    )
            except Exception:
                continue

        return comments

    def _parse_subreddit_about(self, html, name):
        soup = BeautifulSoup(html, "lxml")
        try:
            desc_el = soup.select_one("div.titlebox .usertext-body .md")
            description = desc_el.get_text(strip=True) if desc_el else ""

            sub_count_el = soup.select_one("span.subscribers .number") or soup.select_one(
                "div.subscribers .number"
            )
            subscribers = 0
            if sub_count_el:
                text = sub_count_el.get_text(strip=True).replace(",", "")
                if text.isdigit():
                    subscribers = int(text)

            return {
                "name": name,
                "description": description[:500],
                "subscribers": subscribers,
            }
        except Exception:
            return {"name": name, "description": "", "subscribers": 0}


def _feed_subreddits(subreddits) -> list[str]:
    """Normalise the caller's list into names a feed URL can carry.

    Accepts a bare string as well as a list, because ``get_feed("SaaS")`` is
    what a caller writes by accident and iterating it would build
    ``/r/S+a+a+S/``. That URL is valid, returns a feed, and is silently wrong --
    the failure mode worth ten lines of normalisation.
    """
    if isinstance(subreddits, str):
        subreddits = [subreddits]
    names = []
    for raw in subreddits or []:
        name = str(raw).strip().strip("/")
        if name.lower().startswith("r/"):
            name = name[2:]
        if name:
            names.append(name)
    if not names:
        raise ValueError("get_feed needs at least one subreddit")
    return names


def _clamp_feed_limit(limit) -> int:
    """1..100. Above 100 Reddit returns 100 anyway (U5); below 1 returns nothing."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_FEED_LIMIT
    return max(1, min(MAX_FEED_LIMIT, value))


def _parse_time_element(element):
    time_el = element.select_one("time")
    if not time_el:
        return None
    raw = time_el.get("datetime", "")
    if not raw:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _default_client(config) -> ProxiedHTTPClient:
    """Build the transport from configuration.

    Egress degrades rather than fails: with no proxy file the policy runs
    direct, which is what keeps `python main.py scrape` working on a machine
    that has never been given one.

    The policy is resolved **process-wide** rather than per client. The hourly
    direct governor and the pool's blacklist are budgets over a machine, not
    over an object: one policy per scrape job would give twelve subreddits
    twelve independent 120-request allowances, and reset the blacklist between
    each. See `src/net/egress.py`.
    """
    from .net import HTTPCache, NetMetrics
    from .net.egress import get_policy

    proxy_config = (config or {}).get("proxy", {}) or {}

    return ProxiedHTTPClient(
        get_policy(config),
        cache=HTTPCache(ttl=int(proxy_config.get("cache_ttl", 900))),
        metrics=NetMetrics(),
        timeout=(
            float(proxy_config.get("connect_timeout", 10.0)),
            float(proxy_config.get("read_timeout", 30.0)),
        ),
        block_signatures=REDDIT_SIGNATURES,
    )
