"""Local signal extraction — facts read off a website with **no model involved**.

[06c §2](../../docs/06c-local-first-pipeline.md) lists *"tech-stack / pricing
signals on a website"* against this module and against *"regex + `schema.org`
parse"*, and [06 §2.2](../../docs/06-ai-pipeline.md) is titled *"local signal
extraction — before any model sees the text"*. The argument for doing it here
rather than in the prompt is one sentence long: **asking a model to find a
`<meta generator>` tag is paying tokens for a parser.**

The six signals are [06 §2.2](../../docs/06-ai-pipeline.md)'s table, in its
order. What P14 does with them is also fixed there — they are passed to the model
**as facts rather than as questions**, which is what stops it inventing a
competitor it half-remembers from its training data.

**Everything here is deliberately conservative, and the asymmetry is the reason.**
A missed competitor costs one row P14's model may still find in the prose. A
*wrong* one is seeded into the entity registry in P15, gains aliases, and then
matches Reddit posts for the rest of the project's life — [06e](../../docs/06e-business-knowledge-base.md)
makes the BKB the platform's core asset ([AD-13]), and a false fact in an asset
is worse than a missing one. So the regexes below refuse more than they could,
and the tests pin the refusals as tightly as the matches.

**On the two signal groups that need markup.** Competitors and pricing are read
off the extracted *text*; tech markers, structured data, social links and the nav
taxonomy need the *HTML*. ``website_snapshots`` stores only text, so an
``ExtractedSite`` reused from the L1 cache carries no markup and those four come
back empty. :func:`extract` reports that as ``markup_seen``, rather than
returning four empty tuples that read identically to *"this site has none of
these"*. A caller that needs them re-fetches; P14 is the first caller and its
handover records it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


# ------------------------------------------------------------- competitors

#: Comparison-page phrasings, [06 §2.2](../../docs/06-ai-pipeline.md)'s two,
#: tightened.
#:
#: The plan writes them as ``vs\.?\s+\w+`` and ``alternative to \w+``. Shipped
#: literally, the first matches *"speed vs accuracy"* and the second matches
#: *"an alternative to spreadsheets"* — both of which would enter the entity
#: registry as competitors. The names are therefore required to look like
#: product names: capitalised, or all-caps, optionally dotted or hyphenated.
#: That misses a genuinely lowercase brand, which is the direction this module
#: is supposed to fail in.
#: One product name: a capitalised or all-caps token, optionally two of them.
#:
#: A dot is allowed only **inside** a token (``Next.js``, ``Node.js``), never
#: trailing. Allowing a trailing one lets a sentence-ending period join the name
#: to the first word of the next sentence — *"an alternative to Xero. Plans start
#: at…"* reads as the competitor ``Xero. Plans``, which is then seeded into the
#: entity registry and aliased. Measured against the fixture, not imagined.
_NAME = r"[A-Z][\w&-]*(?:\.[\w&-]+)*(?:\s+[A-Z][\w&-]*(?:\.[\w&-]+)*)?"

#: The **phrase** halves are case-insensitive and the **name** half is not, which
#: is why each pattern uses a scoped ``(?i:…)`` group rather than a flag on the
#: whole expression. A flag would make ``[A-Z]`` match anything and delete the
#: capitalisation requirement the refusals above depend on; leaving it off
#: entirely — the first version of this — misses every sentence-initial
#: *"Compared to Xero"*, which is where a comparison usually appears.
_COMPETITOR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"\b(?i:vs\.?)\s+({_NAME})"),
    re.compile(rf"\b(?i:alternatives?\s+to)\s+({_NAME})"),
    re.compile(rf"\b(?i:compared?\s+(?:to|with))\s+({_NAME})"),
    re.compile(rf"\b(?i:switch(?:ing|ed)?\s+from)\s+({_NAME})"),
)

#: Sentence-initial capitals and headings make every first word look like a
#: brand. These are the words that turn up there and are never a competitor.
_NOT_A_COMPETITOR: frozenset[str] = frozenset(
    {
        "a",
        "all",
        "an",
        "and",
        "any",
        "as",
        "but",
        "each",
        "every",
        "for",
        "how",
        "if",
        "in",
        "it",
        "its",
        "many",
        "more",
        "most",
        "no",
        "not",
        "of",
        "one",
        "or",
        "other",
        "others",
        "our",
        "some",
        "that",
        "the",
        "their",
        "them",
        "these",
        "they",
        "this",
        "those",
        "to",
        "us",
        "we",
        "what",
        "when",
        "which",
        "who",
        "why",
        "you",
        "your",
    }
)


def competitors(text: str, *, known: Iterable[str] = ()) -> tuple[str, ...]:
    """Product names the site compares itself to, best-effort and deduplicated.

    ``known`` is the dictionary half of [06 §2.2](../../docs/06-ai-pipeline.md)'s
    *"dictionary + alias table"*. It is a parameter and not a module constant
    because the dictionary is **per project** and is built from the BKB — which
    does not exist until P14. Passing nothing is the P13 case and gives the
    regex-seeded half on its own.

    Matching for ``known`` is case-insensitive and word-bounded: a substring
    search would find *"Slack"* inside *"slackness"*.
    """
    found: dict[str, None] = {}

    for name in known:
        cleaned = (name or "").strip()
        if cleaned and re.search(rf"\b{re.escape(cleaned)}\b", text, re.IGNORECASE):
            found.setdefault(cleaned, None)

    for pattern in _COMPETITOR_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(1).strip(" .,;:-&")
            if not candidate:
                continue
            tokens = candidate.split()
            # A capitalised second word may be the start of the next clause
            # rather than half the name -- "compared to Xero We do less". Drop it
            # rather than lose the match, which would cost the whole competitor.
            while len(tokens) > 1 and tokens[-1].lower() in _NOT_A_COMPETITOR:
                tokens.pop()
            candidate = " ".join(tokens)
            if tokens[0].lower() in _NOT_A_COMPETITOR:
                continue
            # A single letter is an initial or a list marker, never a product.
            if len(candidate) < 2:
                continue
            found.setdefault(candidate, None)

    return tuple(found)


# ----------------------------------------------------------------- pricing

_CURRENCY_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR"}

_PRICE = re.compile(
    r"(?P<symbol>[$£€₹])\s?(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)"
    r"|(?P<code>USD|GBP|EUR|INR)\s?(?P<amount2>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

_INTERVAL = re.compile(
    r"\b(?:per|/|a)\s*(month|mo|year|yr|annually|monthly|seat|user|agent)\b", re.IGNORECASE
)

_INTERVAL_CANONICAL = {
    "mo": "month",
    "month": "month",
    "monthly": "month",
    "yr": "year",
    "year": "year",
    "annually": "year",
    "seat": "seat",
    "user": "user",
    "agent": "agent",
}

#: Phrases that are a pricing *posture* rather than a number. A site with a
#: "Contact sales" tier and no figures still tells you it sells to enterprises.
_POSTURE_PHRASES: tuple[tuple[str, str], ...] = (
    ("contact sales", "contact_sales"),
    ("contact us for pricing", "contact_sales"),
    ("talk to sales", "contact_sales"),
    ("request a quote", "contact_sales"),
    ("custom pricing", "custom"),
    ("free trial", "free_trial"),
    ("free forever", "free_tier"),
    ("free plan", "free_tier"),
    ("open source", "open_source"),
)


@dataclass(frozen=True)
class PricingSignal:
    """What the site says about what it costs.

    Amounts are strings, not floats, and the currency is kept beside them. R6 is
    *"categoricals in, arithmetic out"* and this is the input side of it: turning
    ``$49`` into ``49.0`` before anything has decided what the number means is
    how a per-seat monthly price ends up compared against a one-off licence fee.
    """

    currencies: tuple[str, ...] = ()
    amounts: tuple[str, ...] = ()
    intervals: tuple[str, ...] = ()
    posture: tuple[str, ...] = ()

    @property
    def has_pricing(self) -> bool:
        return bool(self.amounts or self.posture)


#: A pricing page can list a hundred add-ons. The first handful establishes the
#: posture, which is what P14 asks for; the rest is noise in a 40 KB budget.
_MAX_PRICE_SAMPLES = 12


def pricing(text: str) -> PricingSignal:
    """Currency, amount, interval and posture, per [06 §2.2](../../docs/06-ai-pipeline.md).

    Read over the whole extracted text rather than only over ``/pricing``. The
    plan says *"over `/pricing`"*, and a great many sites price on the landing
    page and have no such path at all — restricting the scan to a page that may
    not have been fetched would report "no pricing" for them.
    """
    currencies: dict[str, None] = {}
    amounts: dict[str, None] = {}

    for match in _PRICE.finditer(text):
        symbol = match.group("symbol")
        if symbol:
            currencies.setdefault(_CURRENCY_SYMBOLS[symbol], None)
            amounts.setdefault(f"{symbol}{match.group('amount')}", None)
        else:
            code = (match.group("code") or "").upper()
            currencies.setdefault(code, None)
            amounts.setdefault(f"{code} {match.group('amount2')}", None)
        if len(amounts) >= _MAX_PRICE_SAMPLES:
            break

    intervals: dict[str, None] = {}
    for match in _INTERVAL.finditer(text):
        intervals.setdefault(_INTERVAL_CANONICAL[match.group(1).lower()], None)

    lowered = text.lower()
    posture: dict[str, None] = {}
    for phrase, label in _POSTURE_PHRASES:
        if phrase in lowered:
            posture.setdefault(label, None)

    return PricingSignal(
        currencies=tuple(currencies),
        amounts=tuple(amounts),
        intervals=tuple(intervals),
        posture=tuple(posture),
    )


# ------------------------------------------------------------ tech markers

#: Hostname fragment -> the tool it identifies. Well-known analytics, CRM,
#: support and commerce vendors, per [06 §2.2](../../docs/06-ai-pipeline.md).
#:
#: A dictionary and not a heuristic: "this script host is Segment" is a fact
#: somebody wrote down once, and guessing at it would produce a tech stack that
#: is confidently wrong. Unknown hosts are simply not reported.
_TECH_HOSTS: tuple[tuple[str, str], ...] = (
    ("google-analytics.com", "Google Analytics"),
    ("googletagmanager.com", "Google Tag Manager"),
    ("segment.com", "Segment"),
    ("segment.io", "Segment"),
    ("mixpanel.com", "Mixpanel"),
    ("amplitude.com", "Amplitude"),
    ("hotjar.com", "Hotjar"),
    ("posthog.com", "PostHog"),
    ("plausible.io", "Plausible"),
    ("hubspot.com", "HubSpot"),
    ("hs-scripts.com", "HubSpot"),
    ("salesforce.com", "Salesforce"),
    ("pardot.com", "Pardot"),
    ("marketo.net", "Marketo"),
    ("intercom.io", "Intercom"),
    ("intercomcdn.com", "Intercom"),
    ("zendesk.com", "Zendesk"),
    ("drift.com", "Drift"),
    ("crisp.chat", "Crisp"),
    ("stripe.com", "Stripe"),
    ("paddle.com", "Paddle"),
    ("chargebee.com", "Chargebee"),
    ("shopify.com", "Shopify"),
    ("typeform.com", "Typeform"),
    ("calendly.com", "Calendly"),
    ("sentry.io", "Sentry"),
    ("cloudflareinsights.com", "Cloudflare Analytics"),
    ("vercel.com", "Vercel"),
    ("netlify.app", "Netlify"),
)


def tech_markers(html: str) -> tuple[str, ...]:
    """Tools identifiable from `<script src>` hosts and `<meta generator>`."""
    if not html:
        return ()

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    found: dict[str, None] = {}

    for script in soup.find_all("script", src=True):
        host = urlsplit(script["src"]).netloc.lower()
        if not host:
            continue
        for fragment, tool in _TECH_HOSTS:
            if host == fragment or host.endswith("." + fragment):
                found.setdefault(tool, None)

    generator = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
    if generator and generator.get("content"):
        found.setdefault(generator["content"].strip(), None)

    return tuple(found)


# ---------------------------------------------------------- structured data

#: The three `schema.org` types [06 §2.2](../../docs/06-ai-pipeline.md) names.
#: Others are parsed and discarded rather than kept: a `BreadcrumbList` is real
#: structured data and tells P14 nothing about the business.
SCHEMA_TYPES: frozenset[str] = frozenset({"Organization", "Product", "Offer"})


def structured_data(html: str) -> tuple[dict, ...]:
    """`schema.org` JSON-LD blocks of the three types that describe a business.

    Malformed JSON is skipped, not raised. A broken `ld+json` block is common,
    entirely the site's business, and not a reason to fail an analysis.

    ``@graph`` and top-level arrays are both walked, because both are legal and
    a reader handling only the bare-object form finds nothing on a great many
    real sites.
    """
    if not html:
        return ()

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    collected: list[dict] = []

    for block in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = block.string or block.get_text() or ""
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            log.debug("skipping a malformed ld+json block")
            continue
        collected.extend(_matching_nodes(parsed))

    return tuple(collected)


def _matching_nodes(node) -> list[dict]:
    """Every dict in ``node`` whose ``@type`` is one of :data:`SCHEMA_TYPES`."""
    if isinstance(node, list):
        return [found for item in node for found in _matching_nodes(item)]
    if not isinstance(node, Mapping):
        return []

    matches: list[dict] = []
    raw_type = node.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    if any(isinstance(t, str) and t in SCHEMA_TYPES for t in types):
        matches.append(dict(node))

    for key in ("@graph", "hasOfferCatalog", "offers", "itemListElement"):
        if key in node:
            matches.extend(_matching_nodes(node[key]))

    return matches


# ------------------------------------------------------------ social links

_SOCIAL_HOSTS: tuple[tuple[str, str], ...] = (
    ("github.com", "github"),
    ("twitter.com", "twitter"),
    ("x.com", "twitter"),
    ("linkedin.com", "linkedin"),
    ("youtube.com", "youtube"),
    ("reddit.com", "reddit"),
    ("discord.gg", "discord"),
    ("discord.com", "discord"),
    ("slack.com", "slack"),
    ("facebook.com", "facebook"),
    ("instagram.com", "instagram"),
    ("news.ycombinator.com", "hackernews"),
    ("producthunt.com", "producthunt"),
    ("mastodon.social", "mastodon"),
)


def social_links(html: str) -> tuple[tuple[str, str], ...]:
    """``(platform, url)`` for every community the site links to.

    Ordered by platform then URL so the result is deterministic: an unordered
    set here would make ``content_hash``-adjacent assertions flap between runs
    for no reason a reader could see.
    """
    if not html:
        return ()

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    found: dict[tuple[str, str], None] = {}

    for anchor in soup.find_all("a", href=True):
        host = urlsplit(anchor["href"].strip()).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        for fragment, platform in _SOCIAL_HOSTS:
            if host == fragment or host.endswith("." + fragment):
                found.setdefault((platform, anchor["href"].strip()), None)
                break

    return tuple(sorted(found))


# ----------------------------------------------------------- nav taxonomy

#: Navigation words that describe the *site*, not the *product*. Keeping them
#: would give every business the same taxonomy.
_NAV_STOPWORDS: frozenset[str] = frozenset(
    {
        "about",
        "blog",
        "careers",
        "contact",
        "cookie policy",
        "docs",
        "documentation",
        "faq",
        "help",
        "home",
        "jobs",
        "legal",
        "log in",
        "login",
        "news",
        "press",
        "privacy",
        "privacy policy",
        "resources",
        "security",
        "sign in",
        "sign up",
        "signup",
        "status",
        "support",
        "terms",
        "terms of service",
    }
)

#: Longer than this is a sentence that happens to be a link, not a nav label.
_MAX_NAV_LABEL_CHARS = 40


def nav_taxonomy(html: str) -> tuple[str, ...]:
    """Product vocabulary from nav and footer link text.

    [06 §2.2](../../docs/06-ai-pipeline.md)'s *"product taxonomy — nav and footer
    link text"*. This is the cheapest description of what a company thinks it
    sells that exists: somebody chose those twelve words deliberately.
    """
    if not html:
        return ()

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    labels: dict[str, None] = {}

    for container in soup.find_all(["nav", "footer"]):
        for anchor in container.find_all("a"):
            label = " ".join(anchor.get_text(separator=" ", strip=True).split())
            if not label or len(label) > _MAX_NAV_LABEL_CHARS:
                continue
            if label.lower() in _NAV_STOPWORDS:
                continue
            labels.setdefault(label, None)

    return tuple(labels)


# ------------------------------------------------------------------ result


@dataclass(frozen=True)
class SiteSignals:
    """Everything read off a site without a model. [06 §2.2](../../docs/06-ai-pipeline.md)'s six.

    ``markup_seen`` is ``False`` when the signals were computed from text alone —
    an L1 cache hit, where ``website_snapshots`` stored no HTML. The four
    markup-derived tuples are then empty *because nothing was parsed*, not
    because the site has none of them, and a consumer that cannot tell those
    apart will record "this company uses no analytics" as a fact.
    """

    competitors: tuple[str, ...] = ()
    pricing: PricingSignal = PricingSignal()
    tech_markers: tuple[str, ...] = ()
    structured_data: tuple[dict, ...] = ()
    social_links: tuple[tuple[str, str], ...] = ()
    nav_taxonomy: tuple[str, ...] = ()
    markup_seen: bool = True

    @property
    def is_empty(self) -> bool:
        """Nothing at all was found — a legitimate outcome for a thin site."""
        return not (
            self.competitors
            or self.pricing.has_pricing
            or self.tech_markers
            or self.structured_data
            or self.social_links
            or self.nav_taxonomy
        )


def extract(site, *, known_competitors: Iterable[str] = ()) -> SiteSignals:
    """Every local signal for one :class:`~src.ai.website_fetcher.ExtractedSite`.

    Takes the site object rather than loose strings so a caller cannot pass one
    page's HTML with another page's text and get a plausible, wrong answer.

    Markup signals are read from **every** page fetched, not only the landing
    page: a `schema.org` `Product` block usually sits on `/product`, and the
    pricing page is where the Stripe script is.
    """
    text = getattr(site, "text", "") or ""
    html_pages = tuple(getattr(site, "html_pages", ()) or ())

    if not html_pages:
        return SiteSignals(
            competitors=competitors(text, known=known_competitors),
            pricing=pricing(text),
            markup_seen=False,
        )

    tech: dict[str, None] = {}
    schema: list[dict] = []
    social: dict[tuple[str, str], None] = {}
    nav: dict[str, None] = {}

    for _, html in html_pages:
        for marker in tech_markers(html):
            tech.setdefault(marker, None)
        schema.extend(structured_data(html))
        for link in social_links(html):
            social.setdefault(link, None)
        for label in nav_taxonomy(html):
            nav.setdefault(label, None)

    return SiteSignals(
        competitors=competitors(text, known=known_competitors),
        pricing=pricing(text),
        tech_markers=tuple(tech),
        structured_data=tuple(schema),
        social_links=tuple(sorted(social)),
        nav_taxonomy=tuple(nav),
        markup_seen=True,
    )


__all__ = [
    "SCHEMA_TYPES",
    "PricingSignal",
    "SiteSignals",
    "competitors",
    "extract",
    "nav_taxonomy",
    "pricing",
    "social_links",
    "structured_data",
    "tech_markers",
]
