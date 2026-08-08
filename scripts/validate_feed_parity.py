"""Compare what Reddit says about a post over HTML against what it says over RSS.

**Purpose: detect parser drift that fixtures cannot detect.**

``tests/test_feed_parity.py`` proves the two parsers agree about the Reddit of
2026-08-08, because that is the day its fixtures were captured. Fixtures are
frozen; Reddit's markup is not. The day old Reddit renames a CSS class or adds
an element to an Atom entry, the fixture pair keeps passing and production
quietly starts collecting two different populations. Only a live run notices.

**This is not part of the test suite, and must not become part of it.**
``docs/34-implementation-plan.md`` §1.2 requires ``pytest`` to make no live
network or API calls, and that rule is worth more than the convenience of
running this automatically. It is an operator tool, like
``scripts/check_schema.py``: run deliberately, and its output pasted into the
phase completion report.

    python scripts/validate_feed_parity.py
    python scripts/validate_feed_parity.py --subreddit SaaS --json out.json

**Two requests, and only two.** One HTML listing page, one feed. P0 measured the
RSS budget at one request per ~60 seconds per IP (U1) and confirmed the HTML and
RSS budgets are independent (U7), so this costs nothing either path will miss.

Compared: ``id``, ``title``, ``author``, ``body``, ``subreddit``, ``url``,
``created_utc``. Everything else is either intentionally different or not a
field. The intentional differences are normalised **and reported**, never
silently dropped -- an exclusion nobody can see is indistinguishable from a
comparison that was never made.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config  # noqa: E402
from src.reddit_client import RedditClient  # noqa: E402

#: The fields that must agree. `score` and `num_comments` are deliberately not
#: here; see INTENTIONAL below.
COMPARED = ("id", "title", "author", "body", "subreddit", "url", "created_utc")

#: Differences that are correct, each with the reason it is correct. Printed on
#: every run, so a reader of the output never has to ask what was excluded.
INTENTIONAL = {
    "score": (
        "a feed does not carry it. RSS reports None (unknown); HTML reports the "
        "vote count. Reporting 0 would be a fabricated fact. SPRINT-0 §2.3"
    ),
    "num_comments": (
        "a feed does not carry it either. RSS reports None. Note the HTML path "
        "reports 0 rather than None here, which is the same class of bug fixed "
        "for `score` and is recorded in DEFERRED-IMPROVEMENTS.md"
    ),
    "url": (
        "LINK AND MEDIA POSTS ONLY. A listing title links to the destination "
        "(v.redd.it, i.redd.it, an external site) and _extract_post reads that "
        "href; the feed's <link href> is always the permalink. The feed keeps "
        "the permalink deliberately: it is the actionable URL for a lead and "
        "what the search path already stores. Self posts agree on both paths"
    ),
    "body": (
        "LISTING PAGES ONLY, and the other way round: the FEED carries the "
        "selftext and the HTML listing does not. Old Reddit renders a listing "
        "expando as <span class='error'>loading...</span> and fetches the body "
        "over AJAX, so div.expando .md matches nothing. Measured 2026-08-08; "
        "ARCHITECTURE_FREEZE.md §11. HTML *search* does carry bodies, which is "
        "where tests/test_feed_parity.py proves the feed parser extracts them "
        "correctly"
    ),
}

#: Same ceiling `_extract_post` applies, so a long body is not reported as a
#: mismatch merely because one path truncated it.
MAX_BODY = 5000


def _tolerances(html: dict, rss: dict) -> dict[str, str]:
    """Differences that are explainable rather than drift.

    Each returns a sentence, or nothing if the field genuinely differs. These
    are *narrow* on purpose: a tolerance wide enough to absorb a real defect is
    worse than no comparison, because it reports success.
    """
    notes: dict[str, str] = {}

    # A link post: the HTML url points off Reddit entirely, the feed url is the
    # permalink. Deliberately narrow -- it applies only when the HTML side is
    # NOT a Reddit permalink and the feed side IS one carrying this post's id.
    # A tolerance that merely said "the urls differ" would hide a feed pointing
    # at the wrong post, which is the failure this whole script exists to find.
    html_url = html.get("url") or ""
    rss_url = rss.get("url") or ""
    html_host = urlsplit(html_url).netloc
    bare_id = str(html.get("id") or "").removeprefix("t3_")
    if (
        html_url != rss_url
        and not html_host.endswith("reddit.com")
        and urlsplit(rss_url).netloc == "www.reddit.com"
        and bare_id
        and f"/comments/{bare_id}/" in rss_url
    ):
        notes["url"] = (
            f"link/media post: the listing title points at {html_host or 'another host'} "
            "while the feed gives the permalink for this same post id"
        )

    html_body = (html.get("body") or "")[:MAX_BODY]
    rss_body = (rss.get("body") or "")[:MAX_BODY]

    if not html_body and rss_body:
        # The measured endpoint difference, not drift. Note the direction: the
        # FEED has more, which is the favourable case and the whole reason RSS
        # became primary discovery. The reverse -- HTML has a body and the feed
        # does not -- falls through below and IS reported as a mismatch.
        notes["body"] = (
            "the HTML listing carries no selftext (lazy expando, measured "
            "2026-08-08); the feed does. Endpoint difference, not drift"
        )
        return notes

    # Both must be non-empty: every string starts with "", so without that
    # guard a total body-extraction failure would be tolerated as truncation.
    both_present = bool(html_body) and bool(rss_body)
    is_prefix = html_body.startswith(rss_body) or rss_body.startswith(html_body)
    if both_present and html_body != rss_body and is_prefix:
        notes["body"] = (
            "one body is a prefix of the other, which is truncation or an "
            "edit between the two fetches, not a parsing difference"
        )
    return notes


def compare(html_posts: list[dict], rss_posts: list[dict]) -> dict:
    """Join on id and compare the intersection field by field.

    **Only the intersection.** The two endpoints return different windows -- one
    HTML page is 25 posts, one feed is up to 100 -- and several seconds pass
    between the two requests. A post in one and not the other is *coverage*, and
    reporting it as a mismatch would bury the real signal under noise on every
    single run.
    """
    html_by_id = {p["id"]: p for p in html_posts}
    rss_by_id = {p["id"]: p for p in rss_posts}
    shared = sorted(set(html_by_id) & set(rss_by_id))

    mismatches: list[dict] = []
    tolerated: list[dict] = []
    for reddit_id in shared:
        html, rss = html_by_id[reddit_id], rss_by_id[reddit_id]
        notes = _tolerances(html, rss)
        for field in COMPARED:
            html_value, rss_value = html.get(field), rss.get(field)
            if field == "body":
                html_value = (html_value or "")[:MAX_BODY]
                rss_value = (rss_value or "")[:MAX_BODY]
            if html_value == rss_value:
                continue
            record = {
                "id": reddit_id,
                "field": field,
                "html": str(html_value),
                "rss": str(rss_value),
            }
            if field in notes:
                tolerated.append({**record, "why": notes[field]})
            else:
                mismatches.append(record)

    engagement = [
        {"id": rid, "html_score": html_by_id[rid]["score"], "rss_score": rss_by_id[rid]["score"]}
        for rid in shared
        if rss_by_id[rid]["score"] is not None
    ]

    # Because the listing tolerance above forgives "HTML empty, RSS full", a
    # feed parser that returned an empty body for EVERY post would otherwise be
    # tolerated on every row and reported as OK. P0 measured selftext on the
    # feed at a median of 1,089 characters (U2), so a feed with no bodies at all
    # is a regression, not a quiet day.
    rss_with_body = sum(1 for post in rss_posts if post.get("body"))
    rss_bodies_missing = bool(rss_posts) and rss_with_body == 0

    return {
        "html_count": len(html_posts),
        "rss_count": len(rss_posts),
        "shared": len(shared),
        "html_only": sorted(set(html_by_id) - set(rss_by_id)),
        "rss_only": sorted(set(rss_by_id) - set(html_by_id)),
        "compared_fields": list(COMPARED),
        "mismatches": mismatches,
        "tolerated": tolerated,
        "rss_reported_a_score": engagement,
        "rss_posts_with_a_body": rss_with_body,
        "rss_bodies_missing": rss_bodies_missing,
        "ok": (not mismatches and not engagement and not rss_bodies_missing and bool(shared)),
    }


def _report(subreddit: str, result: dict) -> None:
    print(f"\nSubreddit          r/{subreddit}")
    print(f"HTML posts         {result['html_count']}")
    print(f"RSS posts          {result['rss_count']}")
    print(f"Compared (shared)  {result['shared']}")
    print(f"Fields compared    {', '.join(result['compared_fields'])}")

    print("\nIntentional differences, normalised before comparing:")
    for field, why in INTENTIONAL.items():
        print(f"  {field:<14} {why}")

    if result["html_only"] or result["rss_only"]:
        print("\nCoverage (different windows and a few seconds between fetches — not drift):")
        print(f"  only in HTML   {len(result['html_only'])}")
        print(f"  only in RSS    {len(result['rss_only'])}")

    if result["tolerated"]:
        print("\nTolerated differences (explained, not ignored):")
        for item in result["tolerated"]:
            print(f"  {item['id']} {item['field']}: {item['why']}")

    print(
        f"\nFeed bodies         {result['rss_posts_with_a_body']} of {result['rss_count']} "
        "posts carry selftext (P0 measured a median of 1,089 characters)"
    )
    if result["rss_bodies_missing"]:
        print("FAILURE — the feed returned no bodies at all. The parser has regressed.")

    if result["rss_reported_a_score"]:
        print("\nFAILURE — RSS reported a score, which a feed cannot carry:")
        for item in result["rss_reported_a_score"]:
            print(f"  {item['id']}: rss={item['rss_score']}")

    if result["mismatches"]:
        print(f"\nFAILURE — {len(result['mismatches'])} field mismatches:")
        for item in result["mismatches"]:
            print(f"  {item['id']} .{item['field']}")
            print(f"    HTML: {item['html'][:160]}")
            print(f"    RSS:  {item['rss'][:160]}")
    elif result["shared"]:
        print(f"\nOK — {result['shared']} posts agree on all {len(COMPARED)} compared fields.")
    else:
        print("\nINCONCLUSIVE — no post appeared in both results, so nothing was compared.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subreddit", help="defaults to the first configured subreddit")
    parser.add_argument("--limit", type=int, default=25, help="HTML posts to fetch (default 25)")
    parser.add_argument("--json", dest="json_path", help="write the full result to this file")
    args = parser.parse_args(argv)

    config = load_config()
    subreddit = args.subreddit or (config.get("subreddits") or ["SaaS"])[0]

    print("LIVE — this makes two real requests to Reddit (one HTML page, one feed).")
    client = RedditClient(config)

    print(f"  1/2  HTML  /r/{subreddit}/new/")
    html_posts = client.get_new_posts(subreddit, limit=args.limit)
    print(f"       {len(html_posts)} posts")

    print(f"  2/2  RSS   /r/{subreddit}/new/.rss")
    rss_posts = client.get_feed([subreddit])
    print(f"       {len(rss_posts)} posts")

    result = compare(html_posts, rss_posts)
    result["subreddit"] = subreddit
    _report(subreddit, result)

    if args.json_path:
        Path(args.json_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_path}")

    if not result["shared"]:
        # Nothing was compared. Neither a pass nor a failure, and saying "OK"
        # here would be the worst outcome available.
        return 2
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
