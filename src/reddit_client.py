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

from .net import BlockedError, ProxiedHTTPClient, ProxyExhaustedError

console = Console()
log = logging.getLogger(__name__)

BASE_URL = "https://old.reddit.com"
DISPLAY_URL = "https://www.reddit.com"

#: Old Reddit serves 25 items per page. Used only to bound pagination.
PAGE_SIZE = 25
#: Hard ceiling on pages per call, whatever `limit` asks for. A safety net
#: against a cursor that never terminates, not a product limit.
MAX_PAGES = 40


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

    Proxying degrades rather than fails: with no proxy file the client runs
    direct, which is what keeps `python main.py scrape` working on a machine
    that has never been given one.
    """
    from .net import HTTPCache, NetMetrics, ProxyManager
    from .net.proxy_models import parse_proxy_file

    proxy_config = (config or {}).get("proxy", {}) or {}
    endpoints = []
    proxy_file = proxy_config.get("file")
    if proxy_file:
        try:
            endpoints = parse_proxy_file(proxy_file)
        except Exception as exc:
            log.warning("proxy file unusable (%s); continuing without proxies", exc)

    manager = ProxyManager(
        endpoints,
        delay_range=(
            float(proxy_config.get("delay_min", 3.0)),
            float(proxy_config.get("delay_max", 7.0)),
        ),
        blacklist_threshold=int(proxy_config.get("blacklist_threshold", 3)),
        blacklist_cooldown=float(proxy_config.get("blacklist_cooldown", 900.0)),
        # Only fail closed when proxies were actually configured; otherwise a
        # machine with no proxy file could not scrape at all.
        fail_closed=bool(proxy_config.get("fail_closed", True)) and bool(endpoints),
        enabled=bool(proxy_config.get("enabled", True)),
    )

    return ProxiedHTTPClient(
        manager,
        cache=HTTPCache(ttl=int(proxy_config.get("cache_ttl", 900))),
        metrics=NetMetrics(),
        timeout=(
            float(proxy_config.get("connect_timeout", 10.0)),
            float(proxy_config.get("read_timeout", 30.0)),
        ),
    )
