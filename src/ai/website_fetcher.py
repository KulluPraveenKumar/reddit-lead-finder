"""``WebsiteFetcher`` — a URL becomes clean text, with **zero AI calls**.

This is [34 §P13](../../docs/34-implementation-plan.md)'s whole objective, and
the phase is deliberately the least clever in the plan: it fetches a bounded set
of pages, strips them to readable text, hashes the result, and stores it. Nothing
here reaches a model. ``test_the_phase_makes_no_ai_call`` asserts that against
``ai_calls`` directly rather than inferring it from the import fence, which is
the idiom P11 established — a fence proves nobody *imported* the AI layer, not
that nobody *called* it.

**Three properties are load-bearing, and each one has a reason that is not
tidiness.**

**1. Egress is direct, and this module does not get a vote.** Every request goes
out with ``request_class="website"``, which ``src/net/policy.py`` holds in the
frozen ``ALWAYS_DIRECT`` set ([R18], [AD-25]). A bounded, polite, seven-page
crawl of a site whose owner is the operator's own *customer* is the one fetch in
this system that must arrive from one stable, identifiable address: ten rotating
datacenter IPs reading a company's pricing page looks like an attack, and the
customer is the person the operator least wants to alarm. [08 §10](../../docs/08-proxy-service.md)
records that this section previously said the opposite and was corrected in P4,
*"where the error was identified before P13 could ship it."* Editing
``network.direct.classes`` cannot undo it.

**2. The budget is a total, not a remainder.** ``max_pages`` is **7 including the
landing page** — [06 §2.1](../../docs/06-ai-pipeline.md)'s ``MAX_PAGES = 7``, and
[34 §P13](../../docs/34-implementation-plan.md)'s Metrics row reads *"≤7 requests
per project version"*. Task 1's *"landing + ≤6 priority paths"* is the same
number said the other way round; reading it as *seven beyond the landing page*
fetches eight and fails the metric it was supposed to satisfy.

**3. The L1 cache is keyed on the URL, not on the content.** [06 §2.3](../../docs/06-ai-pipeline.md)
words the hit condition as *"fingerprint matches a snapshot < 7 days old"*, which
cannot be evaluated as written — a content fingerprint is not knowable before
fetching the content, so a cache that needed one would make zero requests only
after making seven. [35 §6](../../docs/35-testing-strategy.md)'s manual step for
this phase settles the intent: *"Paste a URL; see the snapshot; paste it again;
**no second fetch**."* So the key is ``(project_id, normalised URL)`` plus the
freshness window, and ``content_hash`` is what makes the *reuse* meaningful to
P14 — its L2 profile cache is keyed on fingerprint plus prompt version. This is a
clarification of ambiguous prose, not a [§11.1](../../docs/ARCHITECTURE_FREEZE.md)
reconciliation: no measurement failed, and nothing about the shipped behaviour
differs from what either document wanted.

**A cache hit does not suppress the next miss's row.** Once the window has
passed, a fetch writes a new ``website_snapshots`` row even when the text is
byte-identical to the last one. The table exists *"so a re-analysis can compare
against the text the previous one saw"* (``src/db/models.py``); collapsing
identical rows would save a few kilobytes and delete the only reason the table is
separate from ``projects``.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from src.net import blocks
from src.net.policy import RequestClass

log = logging.getLogger(__name__)


#: Internal paths worth a request, in the order they are worth it.
#:
#: [06 §2.1](../../docs/06-ai-pipeline.md), copied literally rather than
#: reworded. The order is the priority: with a budget of six internal pages and
#: eight candidates, the last two are the ones dropped.
PRIORITY_PATHS: tuple[str, ...] = (
    "/pricing",
    "/product",
    "/features",
    "/solutions",
    "/use-cases",
    "/about",
    "/customers",
    "/how-it-works",
)

#: Below this many characters the site is `thin` and the knowledge built from it
#: is flagged rather than trusted ([06 §2.3](../../docs/06-ai-pipeline.md)). A
#: JavaScript-only shell lands here, which is the intended outcome: this project
#: ships no headless browser ([14 §2.2](../../docs/14-phase-04.md) out of scope).
THIN_CONTENT_CHARS = 500

#: The only two schemes a customer's website can have. `file://` reads the
#: operator's disk and `javascript:` is not a fetch at all; both are rejected
#: before anything touches the network ([14 §7](../../docs/14-phase-04.md): SSRF
#: via a malicious project URL).
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


# ------------------------------------------------------------------ errors


class WebsiteFetchError(Exception):
    """Base for everything this module raises.

    ``status_code`` is carried on the exception rather than decided by whoever
    catches it, matching ``ProviderError`` in ``src/ai/errors.py``. **P13 ships
    no HTTP route** — ``POST /api/projects`` is P16's
    ([14 §9.1](../../docs/14-phase-04.md)) — so [34 §P13](../../docs/34-implementation-plan.md)'s
    *"`file://`/`javascript:` → 422"* cannot be a response code in this phase.
    Attaching the number here is what lets P16 map it in one line instead of
    re-deriving which failures are the caller's fault.
    """

    status_code = 502


class InvalidWebsiteURL(WebsiteFetchError):
    """The URL is not fetchable and no amount of retrying changes that.

    422, because the operator gave us something wrong — not 400, which
    ``src/ai/errors.py`` already pairs with 422 as *"the same request earns the
    same rejection"*.
    """

    status_code = 422


class WebsiteUnreachable(WebsiteFetchError):
    """The landing page could not be read, after the transport gave up.

    An *internal* page failing is not this: it is skipped and logged, and the
    fetch continues ([06 §2.3](../../docs/06-ai-pipeline.md)). Only the landing
    page is fatal, because a site whose front door does not open has nothing
    behind it worth guessing at.
    """

    status_code = 502


# ---------------------------------------------------------------- settings


@dataclass(frozen=True)
class WebsiteSettings:
    """The ``website:`` block, validated.

    Modelled on ``DedupSettings.from_config``, **including the property that
    deleting the whole block reproduces these defaults exactly** — so a rollback
    by deletion behaves identically to a rollback by editing. The ``rules:``,
    ``dedup:``, ``notify:`` and ``discovery:`` blocks all carry it; this is the
    fifth.

    Every default is [06 §2.1](../../docs/06-ai-pipeline.md)'s literal constant,
    cited rather than invented::

        MAX_PAGES, MAX_DEPTH, MAX_TOTAL_CHARS, PER_PAGE_TIMEOUT = 7, 2, 40_000, 15

    ``max_depth`` is stored and **not used**. [34 §P13](../../docs/34-implementation-plan.md)'s
    Config row names it, so it ships; the specified crawl is the landing page
    plus priority-scored links found on it, which is depth 1. Building recursive
    traversal because a config key hints at it would be scope creep, and a key
    that silently did nothing would be worse — so it says so here.
    """

    max_pages: int = 7
    max_depth: int = 2
    max_total_chars: int = 40_000
    per_page_timeout: float = 15.0
    cache_ttl_days: int = 7

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> WebsiteSettings:
        """Build from the parsed config. ``None``, ``{}`` or an absent block -> defaults.

        Unknown keys are ignored rather than rejected, matching every other
        settings object here: a config that refused to load because of a stray
        key would turn a typo into an outage.
        """
        block = (config or {}).get("website") or {}
        return cls(
            max_pages=int(block.get("max_pages", 7)),
            max_depth=int(block.get("max_depth", 2)),
            max_total_chars=int(block.get("max_total_chars", 40_000)),
            per_page_timeout=float(block.get("per_page_timeout", 15)),
            cache_ttl_days=int(block.get("cache_ttl_days", 7)),
        )

    def __post_init__(self) -> None:
        if self.max_pages < 1:
            raise ValueError(
                f"website.max_pages counts the landing page, so it must be >= 1, "
                f"got {self.max_pages}"
            )
        if self.max_depth < 1:
            raise ValueError(f"website.max_depth must be >= 1, got {self.max_depth}")
        if self.max_total_chars < 1:
            raise ValueError(f"website.max_total_chars must be >= 1, got {self.max_total_chars}")
        if self.per_page_timeout <= 0:
            raise ValueError(
                f"website.per_page_timeout is in seconds and must be > 0, "
                f"got {self.per_page_timeout}"
            )
        if self.cache_ttl_days < 0:
            raise ValueError(
                f"website.cache_ttl_days must be >= 0 (0 disables the L1 cache), "
                f"got {self.cache_ttl_days}"
            )


# ------------------------------------------------------------------ result


@dataclass(frozen=True)
class ExtractedSite:
    """What one fetch of a project's site actually read.

    The first five fields are [14 §9.1](../../docs/14-phase-04.md)'s shape,
    unchanged. The three after them are additive and exist because the phase has
    to be able to *prove* things about itself: ``requests_made`` is what the
    zero-fetch acceptance criterion is asserted against, and ``html_pages`` is
    what ``site_signals.extract`` reads.

    ⚠️ **``html_pages`` is empty on a cache hit, and that is not a bug.**
    ``website_snapshots`` stores ``extracted_text`` and no markup, so a reuse has
    no HTML to hand back. Four of the six local signals need markup; the
    extractor degrades to the two that do not rather than pretending. See
    ``site_signals`` and the P13 handover.
    """

    url: str
    pages: tuple[tuple[str, str], ...]
    text: str
    content_hash: str
    thin: bool
    from_cache: bool = False
    requests_made: int = 0
    html_pages: tuple[tuple[str, str], ...] = field(default=())

    @property
    def pages_fetched(self) -> int:
        """What goes in the ``website_snapshots`` column of the same name."""
        return len(self.pages)


# --------------------------------------------------------------------- URLs


def validate_url(raw: str) -> str:
    """Reject anything that is not an ``http(s)`` URL with a host.

    Raises :class:`InvalidWebsiteURL`, which carries ``status_code = 422``.

    The scheme check is an **allowlist**, not a denylist of ``file`` and
    ``javascript``. A denylist of the two named in the plan would pass ``data:``,
    ``ftp:`` and ``gopher:``, and the point of the requirement is that the
    operator's disk and process are not reachable from a text box.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidWebsiteURL("a project needs a website URL; this one is empty")

    candidate = raw.strip()
    parts = urlsplit(candidate)

    # `urlsplit("example.com/pricing")` yields scheme='' and path='example.com/
    # pricing' -- a bare host is the commonest thing an operator types, and
    # rejecting it would be pedantry. It is assumed https and re-split, because
    # `netloc` must come from the parser rather than from string surgery.
    if not parts.scheme:
        parts = urlsplit(f"https://{candidate}")

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise InvalidWebsiteURL(
            f"{parts.scheme}: URLs are not fetchable; a website URL must be "
            f"http or https (got {candidate!r})"
        )
    if not parts.hostname:
        raise InvalidWebsiteURL(f"{candidate!r} has no host")

    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


def normalise_url(raw: str) -> str:
    """Scheme + host, lowercased, no trailing slash — the project identity.

    The same rule ``projects.normalized_url`` is defined by in
    [05 §5.1](../../docs/05-database-plan.md), reproduced rather than imported
    because P16 owns that column and this phase must not become its writer
    ([PHASE-12-HANDOVER §3.2](../../docs/PHASE-12-HANDOVER.md)). It is what makes
    ``https://Example.com/`` and ``example.com`` one L1 cache key rather than two.
    """
    parts = urlsplit(validate_url(raw))
    return f"{parts.scheme}://{parts.netloc}"


def _priority_rank(path: str) -> int | None:
    """Where ``path`` sits in :data:`PRIORITY_PATHS`, or ``None`` if it is not one.

    Prefix matching, so ``/pricing/enterprise`` and ``/about-us`` both count.
    Matching exactly would miss most real sites; matching by substring would
    make ``/blog/how-we-priced-it`` a pricing page.
    """
    lowered = path.rstrip("/").lower() or "/"
    for rank, candidate in enumerate(PRIORITY_PATHS):
        if lowered == candidate or lowered.startswith(candidate + "/"):
            return rank
        if lowered.startswith(candidate + "-"):
            return rank
    return None


def priority_links(html: str, base_url: str, limit: int) -> list[str]:
    """The internal links worth spending the remaining budget on, best first.

    Same host only. Off-site links are the majority of the anchors on a landing
    page — social, docs, status, a parent company — and following one would turn
    a bounded crawl of the customer's site into an unbounded crawl of the web.
    """
    if limit <= 0:
        return []

    from bs4 import BeautifulSoup

    base_host = urlsplit(base_url).netloc.lower()
    ranked: dict[str, int] = {}

    for anchor in BeautifulSoup(html, "lxml").find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        resolved = urljoin(base_url, href)
        parts = urlsplit(resolved)
        if parts.scheme.lower() not in ALLOWED_SCHEMES or parts.netloc.lower() != base_host:
            continue
        rank = _priority_rank(parts.path)
        if rank is None:
            continue
        # Rebuilt without the fragment or query so `/pricing`, `/pricing#plans`
        # and `/pricing?ref=nav` cost one request rather than three.
        clean = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))
        if clean.rstrip("/") == base_url.rstrip("/"):
            continue
        ranked.setdefault(clean, rank)

    ordered = sorted(ranked.items(), key=lambda item: (item[1], item[0]))
    return [url for url, _ in ordered[:limit]]


# --------------------------------------------------------------- extraction


def extract_text(html: str, url: str = "") -> str:
    """Readable text from one page: ``trafilatura``, then BeautifulSoup.

    [ARCHITECTURE_FREEZE §5](../../docs/ARCHITECTURE_FREEZE.md) fixes
    ``trafilatura`` as the text extractor and names readability-lxml and
    newspaper3k as the choices it is not. The fallback is not a second extractor
    in that sense — it is what runs when trafilatura returns nothing usable for a
    *particular page*, which happens on pages that are mostly navigation. Losing
    a nav-heavy page entirely would silently shrink the text the whole knowledge
    base is built from.

    ``script``/``style``/``nav``/``footer``/``header`` are stripped in the
    fallback per [14 §9.1](../../docs/14-phase-04.md); the whole point is to stop
    the same menu appearing seven times in a 40 KB budget.
    """
    if not html or not html.strip():
        return ""

    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            url=url or None,
            include_comments=False,
            include_tables=True,
        )
    except Exception as exc:  # noqa: BLE001 - one page's extractor is not the run
        # A parser that raises on one malformed page must not lose the other
        # six. The fallback below reads the same markup with a more forgiving
        # parser, which is exactly what it is for.
        log.info("trafilatura could not read %s (%s); falling back to BeautifulSoup", url, exc)
        extracted = None

    if extracted and extracted.strip():
        return extracted.strip()

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def content_hash(text: str) -> str:
    """The site fingerprint: ``sha256`` of the extracted text.

    Over the *extracted* text and not the raw HTML, deliberately. A build id, a
    CSRF token or a rotating asset hash in the markup changes on every response,
    which would make a site that had not changed at all look new on every fetch
    and defeat P14's L2 profile cache.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ fetcher


def _utcnow() -> datetime.datetime:
    """Naive UTC, matching every ``DateTime`` column in ``src/db/models.py``.

    Reproduced rather than imported for the reason that module gives: the schema
    stores naive UTC throughout, and one aware value in a comparison against a
    stored one raises ``TypeError`` at the point of comparison rather than where
    it was created.
    """
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class WebsiteFetcher:
    """Reads a customer's website into text, within a hard budget.

    The transport is ``ProxiedHTTPClient``, unchanged and un-subclassed —
    ``src/net/http_client.py``'s own docstring calls P13 reusing it *"the test of
    whether the abstraction is real."* It is: this class supplies a request
    class, a timeout and a signature set, and gets rotation, retry, block
    detection and metrics without adding a line to ``src/net/``.
    """

    def __init__(
        self,
        client=None,
        *,
        settings: WebsiteSettings | None = None,
        config: Mapping[str, Any] | None = None,
    ):
        self.settings = settings or WebsiteSettings.from_config(config)
        self.client = client if client is not None else self._default_client()

    def _default_client(self):
        """A client whose only cache is L1 and whose signatures are generic.

        **``block_signatures`` is passed explicitly, not left to default.**
        ``ProxiedHTTPClient`` defaults to ``blocks.DEFAULT_SIGNATURES``, which is
        generic today — but [08 §10](../../docs/08-proxy-service.md) makes it a
        requirement that a customer's website is fetched *"without Reddit's
        interstitial heuristics being applied to it"*, and a requirement that
        holds only because of another module's default is not held at all. If
        that default ever gains a target-specific marker, a customer's page
        starts being classified as a soft block and every fixture test here keeps
        passing.

        ``cache=None`` for a different reason: the transport's ``http_cache`` and
        the L1 snapshot cache would both answer the same question, and a
        zero-fetch assertion that could be satisfied by either proves neither.
        """
        from src.net.egress import get_policy
        from src.net.http_client import ProxiedHTTPClient

        return ProxiedHTTPClient(
            get_policy(),
            cache=None,
            timeout=(10.0, float(self.settings.per_page_timeout)),
            block_signatures=blocks.BlockSignatures(),
        )

    # -------------------------------------------------------------- fetching

    def fetch(self, url: str, *, session=None, project_id: int | None = None) -> ExtractedSite:
        """Landing page plus priority internal pages, or a cached snapshot.

        ``session`` and ``project_id`` are both optional and are needed together:
        without them there is no L1 cache and no snapshot row, which is the shape
        a unit test and a future CLI probe both want. With them, a project
        analysed inside ``cache_ttl_days`` makes **zero** requests.

        Raises :class:`InvalidWebsiteURL` before any network call, and
        :class:`WebsiteUnreachable` if the landing page cannot be read.
        """
        target = validate_url(url)
        key = normalise_url(target)

        if session is not None and project_id is not None:
            cached = self._cache_hit(session, project_id, key, target)
            if cached is not None:
                log.info("website L1 hit for project %s (%s); 0 requests made", project_id, key)
                return cached

        pages, html_pages, requests_made = self._crawl(target)

        text = self._join(page_text for _, page_text in pages)
        site = ExtractedSite(
            url=target,
            pages=tuple(pages),
            text=text,
            content_hash=content_hash(text),
            thin=len(text) < THIN_CONTENT_CHARS,
            from_cache=False,
            requests_made=requests_made,
            html_pages=tuple(html_pages),
        )

        if site.thin:
            log.warning(
                "website %s yielded %d characters (< %d): thin content, "
                "the knowledge built from it will be flagged",
                target,
                len(text),
                THIN_CONTENT_CHARS,
            )

        if session is not None and project_id is not None:
            save_snapshot(session, project_id, key, site)

        return site

    def _crawl(self, target: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]], int]:
        """The whole request budget, spent landing page first."""
        requests_made = 0

        landing = self._get(target)
        requests_made += 1
        if landing is None:
            raise WebsiteUnreachable(
                f"could not read the landing page at {target}. The site may be down, "
                f"or the URL may be wrong."
            )
        landing_status, landing_html = landing
        if landing_status != 200:
            raise WebsiteUnreachable(
                f"{target} answered HTTP {landing_status}. "
                f"Check the URL — a project needs a page that loads."
            )

        pages = [("/", extract_text(landing_html, target))]
        html_pages = [("/", landing_html)]

        # -1 because the landing page is already spent. docs/06 §2.1's MAX_PAGES
        # is the total, not the remainder -- see this module's docstring.
        remaining = max(0, self.settings.max_pages - 1)
        for link in priority_links(landing_html, target, remaining):
            result = self._get(link)
            requests_made += 1
            if result is None or result[0] != 200:
                # An internal page failing is not fatal: docs/06 §2.3, "skipped,
                # logged, run continues". Six good pages beat one exception.
                log.info("skipping %s (%s)", link, "unreachable" if result is None else result[0])
                continue
            path = urlsplit(link).path or "/"
            pages.append((path, extract_text(result[1], link)))
            html_pages.append((path, result[1]))

        return pages, html_pages, requests_made

    def _get(self, url: str) -> tuple[int, str] | None:
        """One request, direct, returning ``(status, html)`` or ``None``.

        ``None`` means the transport gave up — it raises ``BlockedError`` after
        exhausting the ladder. A 404 does *not* come back that way: it classifies
        as ``FATAL``, so ``ProxiedHTTPClient`` **returns** a ``FetchResult``
        carrying the status rather than raising. Both shapes have to be handled,
        and conflating them is how "a 404 fails with a readable message" turns
        into an unhandled exception with a proxy label in it.
        """
        try:
            result = self.client.get(
                url,
                request_class=RequestClass.WEBSITE.value,
                allow_cache=False,
            )
        except Exception as exc:  # noqa: BLE001 - the transport's failure is data here
            log.info("website fetch failed for %s: %s", url, exc)
            return None
        return result.status_code, result.text

    def _join(self, texts) -> str:
        """Concatenate and truncate to ``max_total_chars``.

        Truncation is at the end and is not clever. A budget spent on the first
        pages is the right outcome: they are the priority-ordered ones, and a
        smarter mid-document trim would make the text non-deterministic, which
        would change ``content_hash`` and defeat both cache layers.
        """
        joined = "\n\n".join(text for text in texts if text)
        return joined[: self.settings.max_total_chars]

    # ----------------------------------------------------------- L1 cache

    def _cache_hit(self, session, project_id: int, key: str, target: str) -> ExtractedSite | None:
        """The newest snapshot for this project and URL, if it is still fresh.

        ``cache_ttl_days: 0`` disables the cache rather than expiring everything
        instantly, which is the reading an operator turning it off expects.

        ``key`` and ``target`` are both needed and are **not** the same string.
        ``key`` is the normalised scheme+host that the row is stored under;
        ``target`` is the validated URL as the caller gave it, which keeps its
        path and its trailing slash. :attr:`ExtractedSite.url` is built from
        ``target`` on **both** paths, because a field that changed shape
        depending on whether the cache hit would be a trap for every consumer:
        P14 reads this attribute, and `https://x.example/` comparing unequal to
        `https://x.example` is the kind of difference that surfaces as a
        duplicate row three phases later rather than as an error here.
        """
        if self.settings.cache_ttl_days <= 0:
            return None

        from src.db.models import WebsiteSnapshot

        cutoff = _utcnow() - datetime.timedelta(days=self.settings.cache_ttl_days)
        row = (
            session.query(WebsiteSnapshot)
            .filter(
                WebsiteSnapshot.project_id == project_id,
                WebsiteSnapshot.url == key,
                WebsiteSnapshot.fetched_at >= cutoff,
            )
            .order_by(WebsiteSnapshot.fetched_at.desc(), WebsiteSnapshot.id.desc())
            .first()
        )
        if row is None:
            return None

        text = row.extracted_text or ""
        return ExtractedSite(
            url=target,
            # The per-page split is not stored -- only the concatenation is --
            # so a reuse reports one page's worth of text under the landing
            # path. `pages_fetched` comes off the row instead, below.
            pages=(("/", text),),
            text=text,
            content_hash=row.content_hash,
            thin=len(text) < THIN_CONTENT_CHARS,
            from_cache=True,
            requests_made=0,
            html_pages=(),
        )


def save_snapshot(session, project_id: int, url: str, site: ExtractedSite):
    """Write one ``website_snapshots`` row and return it.

    Lives here rather than in ``src/db/repositories/`` because
    [34 §P13](../../docs/34-implementation-plan.md)'s **Files** row names two
    modules and no repository — P14's row is where one first appears, and
    [lock §3](../../docs/EXECUTION_MODE_LOCK.md) step 4 is *"every file in the
    phase's Files row, and nothing outside it"*. It takes a session rather than
    opening one, so nothing in this module holds the SQLite write lock across a
    multi-page fetch (the defect that blocked P3's sign-off).

    **It always inserts.** See the module docstring: the table's purpose is
    comparison across re-analyses, and suppressing an insert whose text happened
    to be unchanged would delete the evidence it exists to keep.
    """
    from src.db.models import WebsiteSnapshot

    row = WebsiteSnapshot(
        project_id=project_id,
        url=url,
        pages_fetched=site.pages_fetched,
        extracted_text=site.text,
        content_hash=site.content_hash,
        fetched_at=_utcnow(),
    )
    session.add(row)
    session.flush()
    return row


# --------------------------------------------------------------------- CLI


def render_report(site: ExtractedSite, signals=None) -> str:
    """The operator's view of one fetch, as plain text.

    Separate from :func:`main` so it can be tested without a network call —
    ``main`` is the only thing in this phase that reaches a real website, and a
    test that exercised it would breach the offline guarantee (``docs/35`` §2.3
    check 6) rather than verify anything.
    """
    lines = [
        f"URL              {site.url}",
        f"Requests made    {site.requests_made}",
        f"Pages read       {site.pages_fetched}",
        f"Characters       {len(site.text)}",
        f"Thin content     {'YES — under 500 characters' if site.thin else 'no'}",
        f"Content hash     {site.content_hash}",
        f"From cache       {'yes' if site.from_cache else 'no'}",
        "",
        "Pages:",
    ]
    lines += [f"  {path:<20} {len(text):>7} chars" for path, text in site.pages]

    if signals is not None:
        lines += [
            "",
            "Local signals (no AI call was made):",
            f"  Competitors      {', '.join(signals.competitors) or '(none found)'}",
            f"  Pricing          {', '.join(signals.pricing.amounts) or '(no amounts)'}"
            f"  {'/'.join(signals.pricing.intervals)}",
            f"  Posture          {', '.join(signals.pricing.posture) or '(none)'}",
            f"  Tech markers     {', '.join(signals.tech_markers) or '(none found)'}",
            f"  Structured data  {len(signals.structured_data)} schema.org block(s)",
            f"  Social links     {', '.join(p for p, _ in signals.social_links) or '(none)'}",
            f"  Nav taxonomy     {', '.join(signals.nav_taxonomy) or '(none found)'}",
        ]

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """``python -m src.ai.website_fetcher <url>`` — the operator's view of P13.

    **It writes nothing.** No ``projects`` row, no ``website_snapshots`` row, no
    database connection at all: [PHASE-12-HANDOVER §3.2](../../docs/PHASE-12-HANDOVER.md)
    reserves the first ``projects`` row for **P16**'s ``project add``, and a CLI
    that created one to demonstrate a cache would be exactly the second writer
    that handover forbids. The L1 cache is therefore verified by its tests rather
    than from here, and the manual guide says so rather than leaving the gap.

    It exists for the same reason P5's ``feed`` CLI, P9's ``python -m src.rules``
    and P10's ``python -m src.dedupe`` do: a phase with no operator-visible
    surface cannot be manually verified, and *"read the source and trust it"* is
    not a test step.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.ai.website_fetcher",
        description="Fetch a website into clean text and local signals. Makes NO AI call "
        "and writes NOTHING to the database.",
    )
    parser.add_argument("url", help="the website to read, e.g. https://example.com")
    parser.add_argument(
        "--max-pages", type=int, default=None, help="override the page budget (default 7, total)"
    )
    parser.add_argument("--text", action="store_true", help="also print the extracted text")
    args = parser.parse_args(argv)

    from src.config import load_config

    settings = WebsiteSettings.from_config(load_config())
    if args.max_pages is not None:
        settings = WebsiteSettings(
            max_pages=args.max_pages,
            max_depth=settings.max_depth,
            max_total_chars=settings.max_total_chars,
            per_page_timeout=settings.per_page_timeout,
            cache_ttl_days=settings.cache_ttl_days,
        )

    try:
        site = WebsiteFetcher(settings=settings).fetch(args.url)
    except WebsiteFetchError as exc:
        # The readable message is the product here, so it is printed as itself
        # rather than as a traceback.
        print(f"FAILED: {exc}")
        return 1

    from src.ai.site_signals import extract

    print(render_report(site, extract(site)))
    if args.text:
        print("\n--- extracted text ---\n")
        print(site.text)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())


__all__ = [
    "ALLOWED_SCHEMES",
    "PRIORITY_PATHS",
    "THIN_CONTENT_CHARS",
    "ExtractedSite",
    "InvalidWebsiteURL",
    "WebsiteFetchError",
    "WebsiteFetcher",
    "WebsiteSettings",
    "WebsiteUnreachable",
    "content_hash",
    "extract_text",
    "main",
    "normalise_url",
    "priority_links",
    "render_report",
    "save_snapshot",
    "validate_url",
]
